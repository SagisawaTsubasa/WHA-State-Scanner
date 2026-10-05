"""Domain-level hub: owns the controller store and all controller managers.

Stored at ``hass.data[DOMAIN]`` and kept across config-entry reloads so the
web API keeps answering (with torn-down runtime) while the entry reloads.
"""

from __future__ import annotations

import logging
import uuid

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.storage import Store

from .const import (
    CONF_CONTROLLERS,
    CONF_ENABLED,
    CTRL_ID_PREFIX,
    STORE_KEY,
    STORE_VERSION,
)
from .controller import ControllerManager
from .schema import CTRL_ID_RE, ControllerValidationError, validate_controller

_LOGGER = logging.getLogger(__name__)


class ScannerHub:
    """Manages the stored controller configs and their runtime managers."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize."""
        self.hass = hass
        self.store = Store(hass, STORE_VERSION, STORE_KEY)
        self.controllers: dict[str, dict] = {}
        self.managers: dict[str, ControllerManager] = {}
        self.entry_id: str | None = None

    # ------------------------------------------------------------------
    # Storage
    # ------------------------------------------------------------------

    async def async_load(self) -> None:
        """Load controllers from storage, dropping malformed entries."""
        data = await self.store.async_load()
        raw = (data or {}).get(CONF_CONTROLLERS) or {}
        controllers: dict[str, dict] = {}
        for cid, cfg in raw.items():
            if not isinstance(cid, str) or not CTRL_ID_RE.match(cid):
                _LOGGER.warning("Ignoring malformed controller id %r", cid)
                continue
            try:
                controllers[cid] = validate_controller(cfg)
            except ControllerValidationError as err:
                _LOGGER.warning(
                    "Ignoring invalid stored config for %s: %s", cid, err
                )
        self.controllers = controllers
        _LOGGER.debug("Loaded %d controllers from storage", len(controllers))

    async def async_save(self) -> None:
        """Persist controllers to storage."""
        await self.store.async_save({CONF_CONTROLLERS: self.controllers})

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
            self.hass.async_create_task(manager.async_setup())

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
        return {"controllers": controllers}
