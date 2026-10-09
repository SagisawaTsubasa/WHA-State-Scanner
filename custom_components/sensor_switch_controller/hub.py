"""Domain-level hub: owns the controller store and all controller managers.

Stored at ``hass.data[DOMAIN]`` and kept across config-entry reloads so the
web API keeps answering (with torn-down runtime) while the entry reloads.
"""

from __future__ import annotations

import copy
import logging
import uuid

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.storage import Store

from .const import (
    COND_DURATION,
    CONF_AT,
    CONF_CONTROLLERS,
    CONF_ENABLED,
    CONF_ROUTES,
    CONF_TRIGGERS,
    CTRL_ID_PREFIX,
    STORE_KEY,
    STORE_VERSION,
)
from .controller import ControllerManager
from .schema import CTRL_ID_RE, ControllerValidationError, validate_controller

_LOGGER = logging.getLogger(__name__)


def _for_seconds(for_cfg) -> int:
    """0.5.x FOR dict {"hours","minutes","seconds"} → total seconds."""
    if not isinstance(for_cfg, dict):
        return 0
    try:
        return (
            int(for_cfg.get("hours") or 0) * 3600
            + int(for_cfg.get("minutes") or 0) * 60
            + int(for_cfg.get("seconds") or 0)
        )
    except (TypeError, ValueError):
        return 0


def _covered_condition_ids(conditions: list, outputs: list, out_ids: list[str]) -> set[str]:
    """All condition ids reachable from the given outputs' chains: on/off
    members, group members (recursive) and duration start/abort inputs.
    ``conditions`` builds the id table, ``outputs`` provides the seeds."""
    by_id = {
        c.get("id"): c
        for c in conditions
        if isinstance(c, dict) and isinstance(c.get("id"), str)
    }
    stack: list[str] = []
    for o in outputs:
        if not isinstance(o, dict) or o.get("entity_id") not in out_ids:
            continue
        stack.extend(o.get("on_conditions") or [])
        stack.extend(o.get("off_conditions") or [])
    seen: set[str] = set()
    while stack:
        cid = stack.pop()
        if cid in seen:
            continue
        seen.add(cid)
        cond = by_id.get(cid)
        if not cond:
            continue
        stack.extend(cond.get("conditions") or [])
        if isinstance(cond.get("start"), str):
            stack.append(cond["start"])
        if isinstance(cond.get("abort"), str):
            stack.append(cond["abort"])
    return seen


def _migrate_controller_v4(cfg: dict) -> dict:
    """v3→v4: triggers stop wiring outputs directly.

    Each trigger's signal coverage becomes the union of the condition
    chains of its previously wired outputs, materialized into
    routes.conditions — legacy configs evaluate exactly as before, and
    from now on evaluation scope flows through the condition graph only.
    """
    triggers = cfg.get(CONF_TRIGGERS)
    conditions = cfg.get("conditions") or []
    if not isinstance(triggers, list):
        return cfg
    for trg in triggers:
        if not isinstance(trg, dict):
            continue
        routes = trg.get(CONF_ROUTES)
        if not isinstance(routes, dict):
            continue
        old_outs = [x for x in (routes.get("outputs") or []) if isinstance(x, str)]
        covered = (
            _covered_condition_ids(conditions, cfg.get("outputs") or [], old_outs)
            if old_outs
            else set()
        )
        merged = {c for c in (routes.get("conditions") or []) if isinstance(c, str)}
        merged |= covered
        trg[CONF_ROUTES] = {"conditions": sorted(merged)}
    return cfg


def _migrate_controller_v2(cfg: dict) -> dict:
    """Migrate one controller config from v2 (0.5.x) to v3, in place.

    ① state/numeric_state conditions with a ``for`` field split into a
       standalone ``duration`` node (start = the original condition); every
       group/output reference to the original is rewired to the duration so
       the timed semantics survive verbatim.
    ② ``time`` conditions with ``at`` degrade to range conditions
       (at → after); time-of-day semantics live in triggers from now on.
    ③ every trigger gets ``routes`` materialized to ALL outputs — the v2
       behaviour (any trigger evaluates everything) preserved exactly;
       users narrow the wiring on the canvas afterwards.
    """
    conditions = cfg.get("conditions")
    if not isinstance(conditions, list):
        conditions = []
        cfg["conditions"] = conditions
    outputs = cfg.get("outputs")
    if not isinstance(outputs, list):
        outputs = []

    rewires: dict[str, str] = {}
    new_nodes: list[dict] = []
    for cond in conditions:
        if not isinstance(cond, dict):
            continue
        if cond.get("type") not in ("numeric_state", "state"):
            continue
        seconds = _for_seconds(cond.get("for"))
        cid = cond.get("id")
        if seconds <= 0 or not isinstance(cid, str):
            cond.pop("for", None)
            continue
        dur_id = f"cond_{uuid.uuid4().hex}"
        label = cond.get("label")
        new_nodes.append(
            {
                "id": dur_id,
                "type": COND_DURATION,
                "label": (f"{label} 持续" if label else ""),
                "enabled": cond.get("enabled", True),
                "seconds": seconds,
                "start": cid,
                "abort": None,
            }
        )
        rewires[cid] = dur_id
        cond.pop("for", None)
    if rewires:
        conditions.extend(new_nodes)
        for cond in conditions:
            if isinstance(cond, dict) and isinstance(cond.get("conditions"), list):
                cond["conditions"] = [rewires.get(m, m) for m in cond["conditions"]]
        for out in outputs:
            if not isinstance(out, dict):
                continue
            for key in ("on_conditions", "off_conditions"):
                members = out.get(key)
                if isinstance(members, list):
                    out[key] = [rewires.get(m, m) for m in members]

    for cond in conditions:
        if isinstance(cond, dict) and cond.get("type") == "time" and cond.get(CONF_AT):
            cond["after"] = cond.pop(CONF_AT)

    triggers = cfg.get(CONF_TRIGGERS)
    if isinstance(triggers, list):
        out_ids = []
        for o in outputs:
            if not isinstance(o, dict):
                continue
            oid = o.get("entity_id")
            if not isinstance(oid, str) or not oid:
                # Validate (later) would mint a fresh id for this output;
                # pre-assign it here so route materialization can reach it
                # instead of stranding the output unwired forever (WHA-F-021).
                oid = f"ssc_{uuid.uuid4().hex}"
                o["entity_id"] = oid
            out_ids.append(oid)
        for trg in triggers:
            if isinstance(trg, dict):
                # v2 materializes full coverage; the conditions list is what
                # v4 keeps (the outputs key is dropped when the v4 step runs).
                trg.setdefault(CONF_ROUTES, {"outputs": list(out_ids), "conditions": [
                    c.get("id")
                    for c in cfg.get("conditions") or []
                    if isinstance(c, dict) and isinstance(c.get("id"), str)
                ]})
    return cfg


class _MigratingStore(Store):
    """Store with the v2→v4 / v3→v4 migrations wired in.

    ``Store`` has no ``migrate_func=`` constructor argument; a subclass
    overrides ``_async_migrate_func(old_major_version, old_data)`` and
    returns the migrated payload (HA saves it back automatically).
    """

    async def _async_migrate_func(self, old_major_version, old_data):
        if old_major_version >= STORE_VERSION:
            return old_data
        raw = (old_data or {}).get(CONF_CONTROLLERS)
        if isinstance(raw, dict):
            steps = {
                2: (_migrate_controller_v2, _migrate_controller_v4),
                3: (_migrate_controller_v4,),
            }
            chain = steps.get(old_major_version, ())
            for cid, cfg in raw.items():
                if not isinstance(cfg, dict):
                    continue
                try:
                    migrated = copy.deepcopy(cfg)
                    for step in chain:
                        migrated = step(migrated)
                    raw[cid] = migrated
                except Exception:
                    # keep the ORIGINAL untouched object, as advertised
                    _LOGGER.exception(
                        "Failed migrating controller %s; kept as-is", cid
                    )
        return old_data


class ScannerHub:
    """Manages the stored controller configs and their runtime managers."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize."""
        self.hass = hass
        self.store = _MigratingStore(hass, STORE_VERSION, STORE_KEY)
        self.controllers: dict[str, dict] = {}
        self.invalid: dict[str, dict] = {}
        self.managers: dict[str, ControllerManager] = {}
        self.entry_id: str | None = None

    # ------------------------------------------------------------------
    # Storage
    # ------------------------------------------------------------------

    async def async_load(self) -> None:
        """Load controllers from storage, dropping malformed entries."""
        data = await self.store.async_load()
        raw = (data or {}).get(CONF_CONTROLLERS) or {}
        if not isinstance(raw, dict):
            # Hand-edited / corrupt store: same guard as the migration path —
            # a non-object payload must not abort the whole integration.
            _LOGGER.warning(
                "Stored %s payload is not an object (%r); ignored",
                CONF_CONTROLLERS, type(raw).__name__,
            )
            raw = {}
        controllers: dict[str, dict] = {}
        self.invalid: dict[str, dict] = {}
        for cid, cfg in raw.items():
            if not isinstance(cid, str) or not CTRL_ID_RE.match(cid):
                _LOGGER.warning("Ignoring malformed controller id %r", cid)
                continue
            try:
                controllers[cid] = validate_controller(cfg)
            except ControllerValidationError as err:
                # Keep the raw config so the next save round-trips it instead
                # of silently deleting user data; surface it in the panel.
                self.invalid[cid] = {"config": cfg, "error": str(err)}
                _LOGGER.warning(
                    "Stored config for %s is invalid (kept as-is): %s", cid, err
                )
        self.controllers = controllers
        _LOGGER.debug(
            "Loaded %d controllers (+%d invalid) from storage",
            len(controllers), len(self.invalid),
        )

    async def async_save(self) -> None:
        """Persist controllers to storage (invalid configs round-trip as-is)."""
        payload = dict(self.controllers)
        for cid, item in self.invalid.items():
            payload[cid] = item["config"]
        await self.store.async_save({CONF_CONTROLLERS: payload})

    # ------------------------------------------------------------------
    # Controllers CRUD (web API; caller schedules the entry reload)
    # ------------------------------------------------------------------

    def create_controller(self, config: dict) -> str:
        """Insert a validated controller under a fresh id."""
        cid = self._fresh_id()
        self.controllers[cid] = config
        return cid

    def update_controller(self, cid: str, config: dict) -> None:
        """Replace an existing controller's config."""
        if cid not in self.controllers:
            raise KeyError(cid)
        self.controllers[cid] = config

    def repair_controller(self, cid: str, config: dict) -> None:
        """Replace a previously invalid stored config with a valid one."""
        self.invalid.pop(cid, None)
        self.controllers[cid] = config

    def remove_controller(self, cid: str) -> None:
        """Delete a controller and its entity-registry entries."""
        manager = self.managers.pop(cid, None)
        if manager:
            registry = er.async_get(self.hass)
            # registry.async_remove() runs the entity removal chain inline
            # (eager task), which pops from manager.entities — snapshot first.
            for entity in list(manager.entities.values()):
                entity_id = getattr(entity, "entity_id", None)
                if entity_id:
                    registry.async_remove(entity_id)
            manager.async_unload()
        self.controllers.pop(cid, None)
        self.invalid.pop(cid, None)

    def _fresh_id(self) -> str:
        while True:
            cid = f"{CTRL_ID_PREFIX}{uuid.uuid4().hex[:8]}"
            if cid not in self.controllers:
                return cid

    # ------------------------------------------------------------------
    # Runtime managers
    # ------------------------------------------------------------------

    def set_entry(self, entry_id: str) -> None:
        """Remember the owning config entry id (single-entry domain)."""
        self.entry_id = entry_id

    def build_managers(self) -> None:
        """(Re)create runtime managers for every enabled controller."""
        self.teardown_managers()
        for cid, config in self.controllers.items():
            if not config.get(CONF_ENABLED, True):
                continue
            manager = ControllerManager(self.hass, cid, config)
            self.managers[cid] = manager
            self.hass.async_create_background_task(
                manager.async_setup(), f"{cid}-setup"
            )

    def teardown_managers(self) -> None:
        """Stop all polling and drop entity references."""
        for manager in self.managers.values():
            manager.async_unload()
        self.managers.clear()

    # ------------------------------------------------------------------
    # Lookups / views for the web layer
    # ------------------------------------------------------------------

    def manager_for_entity(self, entity_id: str) -> ControllerManager | None:
        """Find the manager owning an output entity_id (service API)."""
        for manager in self.managers.values():
            for entity in manager.entities.values():
                if getattr(entity, "entity_id", None) == entity_id:
                    return manager
        return None

    def output_id_for_entity(
        self, manager: ControllerManager, entity_id: str
    ) -> str | None:
        """Reverse lookup: output internal id for an entity_id."""
        for out_id, entity in manager.entities.items():
            if getattr(entity, "entity_id", None) == entity_id:
                return out_id
        return None

    def snapshot(self) -> dict:
        """Full view: config + runtime for every controller."""
        controllers = {}
        for cid, config in self.controllers.items():
            manager = self.managers.get(cid)
            controllers[cid] = {
                **config,
                "active": manager is not None,
                "runtime": manager.runtime_snapshot() if manager else {},
            }
        for cid, item in self.invalid.items():
            controllers[cid] = {
                "_invalid": True,
                "invalid_error": item["error"],
                "name": cid,
                "enabled": False,
                "triggers": [],
                "sensors": [],
                "conditions": [],
                "outputs": [],
                "active": False,
                "runtime": {},
            }
        return {"controllers": controllers}
