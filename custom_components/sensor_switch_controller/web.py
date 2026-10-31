"""Web layer: REST API views, static assets and the sidebar panel.

The panel is a custom element (``sensor-switch-controller-panel``) loaded
from this integration's static directory — same architecture HACS uses, no
iframe, no CDN. The element receives the frontend ``hass`` object and calls
the REST views below with ``hass.fetchWithAuth``.
"""

from __future__ import annotations

import logging
from pathlib import Path

from aiohttp import web
from homeassistant.components import frontend
from homeassistant.components.http import (
    HomeAssistantView,
    StaticPathConfig,
    require_admin,
)
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.event import async_call_later
from homeassistant.loader import async_get_loaded_integration

from .const import (
    API_BASE,
    DOMAIN,
    HUB_BUS_EVENT_PAGE_CHANGED,
    HUB_PAGE_ID,
    HUB_PAGE_ORDER,
    HUB_REGISTRY_KEY,
    PANEL_ELEMENT,
    PANEL_SIDEBAR_ICON,
    PANEL_SIDEBAR_TITLE,
    PANEL_URL_PATH,
    URL_BASE,
)
from .decision_log import read_day_records
from .hub import ScannerHub
from .schema import ControllerValidationError, validate_controller

_LOGGER = logging.getLogger(__name__)

WEB_DATA_KEY = f"{DOMAIN}_web_registered"


def get_hub(hass: HomeAssistant) -> ScannerHub | None:
    """Return the hub, or None while the domain is not set up."""
    return hass.data.get(DOMAIN)


async def _parse_json(request: web.Request) -> dict:
    try:
        body = await request.json()
    except (ValueError, TypeError):
        raise _WebError(400, "请求体不是合法 JSON")
    if not isinstance(body, dict):
        raise _WebError(400, "请求体必须是 JSON 对象")
    return body


class _WebError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def _error_response(view: HomeAssistantView, err: _WebError) -> web.Response:
    return view.json({"ok": False, "error": err.message}, status_code=err.status)


class ConfigView(HomeAssistantView):
    """GET /api/sensor_switch_controller/config — full config + runtime."""

    url = API_BASE + "/config"
    name = "api:sensor_switch_controller:config"
    requires_auth = True

    @require_admin
    async def get(self, request: web.Request) -> web.Response:
        hass = request.app["hass"]
        hub = get_hub(hass)
        if hub is None:
            return self.json({"ok": False, "error": "集成未加载"}, status_code=503)
        return self.json({"ok": True, **hub.snapshot()})


class ControllersView(HomeAssistantView):
    """POST /api/sensor_switch_controller/controllers — create one."""

    url = API_BASE + "/controllers"
    name = "api:sensor_switch_controller:controllers"
    requires_auth = True

    @require_admin
    async def post(self, request: web.Request) -> web.Response:
        hass = request.app["hass"]
        hub = get_hub(hass)
        if hub is None:
            return self.json({"ok": False, "error": "集成未加载"}, status_code=503)
        try:
            body = await _parse_json(request)
            config = validate_controller(body)
        except ControllerValidationError as err:
            return self.json({"ok": False, "error": str(err)}, status_code=400)
        except _WebError as err:
            return _error_response(self, err)

        # The lock spans snapshot → mutate → save (+ rollback) so the
        # whole-table store write can never capture another request's
        # half-committed mutation (审查 R6-2).
        async with hub.crud_lock:
            # A fresh id is guaranteed absent from both dicts (hub._fresh_id),
            # so the key snapshot is the empty state.
            cid = hub.create_controller(config)
            await _save_or_rollback(hass, hub, cid, (False, None, None))
        _schedule_reload(hass, hub)
        _LOGGER.info("Created controller %s (%s) via web", cid, config["name"])
        return self.json({"ok": True, "id": cid})


class ControllerDetailView(HomeAssistantView):
    """PUT/DELETE /api/sensor_switch_controller/controllers/{id}."""

    url = API_BASE + "/controllers/{controller_id}"
    name = "api:sensor_switch_controller:controller_detail"
    requires_auth = True

    @require_admin
    async def put(self, request: web.Request, controller_id: str) -> web.Response:
        """Update one controller (aiohttp passes the URL var as kwarg)."""
        hass = request.app["hass"]
        hub = get_hub(hass)
        if hub is None:
            return self.json({"ok": False, "error": "集成未加载"}, status_code=503)
        cid = controller_id
        repairing = cid in hub.invalid
        if cid not in hub.controllers and not repairing:
            return self.json({"ok": False, "error": "控制器不存在"}, status_code=404)
        try:
            body = await _parse_json(request)
            config = validate_controller(body)
        except ControllerValidationError as err:
            return self.json({"ok": False, "error": str(err)}, status_code=400)
        except _WebError as err:
            return _error_response(self, err)

        # The lock spans snapshot → mutate → save (+ rollback) so the
        # whole-table store write can never capture another request's
        # half-committed mutation (审查 R6-2).
        async with hub.crud_lock:
            # Re-derive the repairing verdict under the lock (审查 R7-4):
            # the pre-lock check raced concurrent DELETEs across the JSON
            # parse await — repairing a controller that was just deleted
            # would resurrect it. repair_controller raises KeyError like
            # update_controller, so both branches answer the same 404.
            repairing = cid in hub.invalid
            before_key = _key_snapshot(hub, cid)
            try:
                if repairing:
                    hub.repair_controller(cid, config)
                else:
                    # Honor the id the client saved under (URL wins over body).
                    hub.update_controller(cid, config)
            except KeyError:
                # check-then-act raced a concurrent DELETE across the await above
                return self.json({"ok": False, "error": "控制器不存在"}, status_code=404)
            await _save_or_rollback(hass, hub, cid, before_key)
        # Save won — sweep registry entries orphaned by the update (F-332):
        # dropped outputs or a switch↔binary_sensor type switch would
        # otherwise linger as ghost "no longer provided" rows (the DELETE
        # path sweeps, the PUT path historically only replaced the config).
        # Best-effort, same as the DELETE sweep: a cleanup failure must not
        # fake a failed update nor skip the reload.
        try:
            hub.sweep_registry_diff(cid, config["outputs"])
        except Exception:
            _LOGGER.exception(
                "Registry diff sweep failed for %s; the update stays, ghost "
                "entries clear on the next entry reload", cid,
            )
        _schedule_reload(hass, hub)
        _LOGGER.info("Updated controller %s (%s) via web", cid, config["name"])
        return self.json({"ok": True, "id": cid})

    @require_admin
    async def delete(self, request: web.Request, controller_id: str) -> web.Response:
        """Delete one controller — two-phase (审查 R5-8): detach memory and
        write the main store FIRST; only once the deletion is durable do the
        irreversible registry/device cleanups and the flag-state drop run.
        A failed main save rolls back to a fully intact controller."""
        hass = request.app["hass"]
        hub = get_hub(hass)
        if hub is None:
            return self.json({"ok": False, "error": "集成未加载"}, status_code=503)
        cid = controller_id
        if cid not in hub.controllers and cid not in hub.invalid:
            return self.json({"ok": False, "error": "控制器不存在"}, status_code=404)
        # The lock spans snapshot → mutate → save (+ rollback) so the
        # whole-table store write can never capture another request's
        # half-committed mutation (审查 R6-2).
        async with hub.crud_lock:
            before_key = _key_snapshot(hub, cid)
            entity_ids = hub.remove_controller(cid)
            await _save_or_rollback(hass, hub, cid, before_key)
        # Save won — the deletion is durable now. Each post-save step is
        # guarded on its own (审查 R6-4): a registry/flag failure must not
        # fake a failed DELETE (the main store already committed) nor skip
        # the remaining cleanup or the reload — every failure is logged,
        # the next step still runs.
        try:
            hub.sweep_registry(cid, entity_ids)
        except Exception:
            _LOGGER.exception(
                "Registry sweep failed for %s; deletion stays, ghost "
                "entries clear on the next entry reload", cid,
            )
        try:
            await hub.async_drop_flag_states(cid)
        except Exception:
            _LOGGER.exception(
                "Failed dropping flag states for %s; deletion stays, the "
                "orphaned entry clears on the next flag save", cid,
            )
        _schedule_reload(hass, hub)
        _LOGGER.info("Deleted controller %s via web", cid)
        return self.json({"ok": True})


class EvaluateView(HomeAssistantView):
    """POST /api/sensor_switch_controller/controllers/{id}/evaluate."""

    url = API_BASE + "/controllers/{controller_id}/evaluate"
    name = "api:sensor_switch_controller:evaluate"
    requires_auth = True

    @require_admin
    async def post(self, request: web.Request, controller_id: str) -> web.Response:
        """Evaluate one controller now, with per-condition detail."""
        hass = request.app["hass"]
        hub = get_hub(hass)
        if hub is None:
            return self.json({"ok": False, "error": "集成未加载"}, status_code=503)
        cid = controller_id
        manager = hub.managers.get(cid)
        if manager is None:
            if cid in hub.controllers:
                return self.json(
                    {"ok": False, "error": "控制器已停用"}, status_code=409
                )
            return self.json({"ok": False, "error": "控制器不存在"}, status_code=404)
        try:
            result = await manager.async_evaluate_with_details()
        except Exception:
            _LOGGER.exception("Trial evaluation failed for %s", cid)
            return self.json({"ok": False, "error": "试运行失败，详见日志"}, status_code=500)
        return self.json({"ok": True, **result})


class ObserveView(HomeAssistantView):
    """GET /api/sensor_switch_controller/controllers/{id}/observe.

    Read-only evaluation for the editor's live condition status: shares the
    evaluation lock (timer ledgers stay consistent) but applies nothing.
    """

    url = API_BASE + "/controllers/{controller_id}/observe"
    name = "api:sensor_switch_controller:observe"
    requires_auth = True

    @require_admin
    async def get(self, request: web.Request, controller_id: str) -> web.Response:
        hass = request.app["hass"]
        hub = get_hub(hass)
        if hub is None:
            return self.json({"ok": False, "error": "集成未加载"}, status_code=503)
        cid = controller_id
        manager = hub.managers.get(cid)
        if manager is None:
            if cid in hub.controllers:
                return self.json(
                    {"ok": False, "error": "控制器已停用"}, status_code=409
                )
            return self.json({"ok": False, "error": "控制器不存在"}, status_code=404)
        try:
            result = await manager.async_observe_conditions()
        except Exception:
            _LOGGER.exception("Observe failed for %s", cid)
            return self.json(
                {"ok": False, "error": "观察失败，详见日志"}, status_code=500
            )
        return self.json({"ok": True, **result})


class LogsView(HomeAssistantView):
    """GET /api/sensor_switch_controller/logs?controller_id=&date=&decision=&limit="""

    url = API_BASE + "/logs"
    name = "api:sensor_switch_controller:logs"
    requires_auth = True

    @require_admin
    async def get(self, request: web.Request) -> web.Response:
        hass = request.app["hass"]
        hub = get_hub(hass)
        if hub is None:
            return self.json({"ok": False, "error": "集成未加载"}, status_code=503)
        cid = request.query.get("controller_id", "")
        if cid not in hub.controllers:
            return self.json({"ok": False, "error": "控制器不存在"}, status_code=404)
        date_str = request.query.get("date") or ""
        if not _valid_date(date_str):
            return self.json(
                {"ok": False, "error": "日期格式应为 YYYY-MM-DD"}, status_code=400
            )
        decision = request.query.get("decision") or None
        if decision is not None and decision not in ("on", "off", "hold"):
            return self.json({"ok": False, "error": "decision 参数非法"}, status_code=400)
        try:
            limit = int(request.query.get("limit", "500"))
        except ValueError:
            return self.json({"ok": False, "error": "limit 必须是整数"}, status_code=400)

        records, truncated = await read_day_records(
            hass, cid, date_str, limit=limit, decision=decision
        )
        return self.json(
            {"ok": True, "date": date_str, "records": records, "truncated": truncated}
        )


def _valid_date(value: str) -> bool:
    if len(value) != 10 or value[4] != "-" or value[7] != "-":
        return False
    year, month, day = value[:4], value[5:7], value[8:10]
    return year.isdigit() and month.isdigit() and day.isdigit()


def _key_snapshot(hub: ScannerHub, cid: str) -> tuple[bool, dict | None, dict | None]:
    """Pre-mutation state of ONE controller key (审查 R6-2): the rollback
    undo is key-granular, so a failed save never clobbers what a concurrent
    request committed under its own lock window."""
    return (
        cid in hub.controllers,
        hub.controllers.get(cid),
        hub.invalid.get(cid),
    )


def _restore_key(hub: ScannerHub, cid: str, snap: tuple) -> None:
    """Undo one request's single-key mutation (the exact inverse of
    create/update/repair/remove) onto the current in-memory dicts."""
    was_controller, config, invalid_item = snap
    if was_controller:
        hub.controllers[cid] = config
    else:
        hub.controllers.pop(cid, None)
    if invalid_item is not None:
        hub.invalid[cid] = invalid_item
    else:
        hub.invalid.pop(cid, None)


async def _save_or_rollback(
    hass: HomeAssistant,
    hub: ScannerHub,
    cid: str,
    before_key: tuple,
) -> None:
    """Persist the store; on failure undo THIS request's key only and
    converge memory with the durable state (审查 R6-2).

    The store write is whole-table, but every CRUD mutation is single-key
    and serialized by ``hub.crud_lock``: the rollback re-reads the store
    (dropping whatever the failed write left behind) and then re-applies
    the inverse of this request's key — concurrent requests' committed
    changes survive and memory never stays split from disk. The first
    in-memory restore runs before the re-read so readers never observe
    the mutation. The detached manager is NOT resurrected; the scheduled
    reload rebuilds it (a sub-second window with no runtime, accepted by
    the R5 review). Re-raises so the HTTP layer still answers 500.
    """
    try:
        await hub.async_save()
    except Exception:
        _LOGGER.exception(
            "Controller store save failed; rolling back controller %s", cid
        )
        _restore_key(hub, cid, before_key)
        try:
            await hub.async_load()
        except Exception:
            _LOGGER.warning(
                "Store re-read after the failed save failed too; %s is "
                "rolled back in memory only",
                cid,
                exc_info=True,
            )
        else:
            _restore_key(hub, cid, before_key)
        _schedule_reload(hass, hub)
        raise


@callback
def _schedule_reload(hass: HomeAssistant, hub: ScannerHub) -> None:
    """Reload the config entry after a store mutation (coalesced).

    ``async_schedule_reload`` is a @callback that schedules the reload task
    itself — it must be called directly, never wrapped in a task. Burst
    CRUD within the 1s window shares one reload: every reload tears down
    and rebuilds all managers, zeroing FOR/duration timers and flapping
    outputs (体检 P3-9).
    """
    if not hub.entry_id:
        return
    if hass.config_entries.async_get_entry(hub.entry_id) is None:
        # Entry was removed; keep the store write but nothing to reload.
        return
    pending_key = WEB_DATA_KEY + "_reload_pending"
    if hass.data.get(pending_key):
        return  # a reload is already queued inside the coalescing window
    hass.data[pending_key] = True

    @callback
    def _go(_now) -> None:
        hass.data[pending_key] = None
        if hub.entry_id and hass.config_entries.async_get_entry(hub.entry_id):
            hass.config_entries.async_schedule_reload(hub.entry_id)

    async_call_later(hass, 1.0, _go)


def _manifest_version(hass: HomeAssistant) -> str:
    try:
        return async_get_loaded_integration(hass, DOMAIN).version or "dev"
    except Exception:  # noqa: BLE001 — version is only a cache buster
        _LOGGER.debug("Could not resolve integration version for panel URL")
        return "dev"


def _descriptor(version: str) -> dict:
    """Hub-shell page descriptor (fumiha_hub registry contract)."""
    return {
        "id": HUB_PAGE_ID,
        "title": PANEL_SIDEBAR_TITLE,
        "icon": PANEL_SIDEBAR_ICON,
        "order": HUB_PAGE_ORDER,
        "version": version,
        "module_url": f"{URL_BASE}/panel.js?ver={version}",
        "element": PANEL_ELEMENT,
    }


def _registration_present(hass: HomeAssistant, mode: str) -> bool:
    """True when the registration a previous _register_page made is intact.

    The mode name alone is not enough: deleting and re-adding the shell
    entry destroys and recreates the registry dict (hub side), so flags may
    say "hub" while the descriptor is gone — early-returning on the mode
    name alone would then skip re-registration forever (SR-F-083).
    """
    if mode == "hub":
        return HUB_PAGE_ID in (hass.data.get(HUB_REGISTRY_KEY) or {})
    return PANEL_URL_PATH in (hass.data.get(frontend.DATA_PANELS) or {})


def _register_page(hass: HomeAssistant, flags: dict) -> None:
    """(Re-)register the panel in whichever mode fits right now.

    Probe = ``HUB_REGISTRY_KEY`` key existence, kept truthful by the hub
    (created in its setup, removed with the entry) — we never create the
    dict ourselves, or the probe would stay true without a shell and the
    page would be unreachable. A mode flip (shell installed/removed while
    the entry lives) tears the old registration down first, symmetrically;
    an equal mode with vanished registration facts (shell entry deleted and
    re-added mid-run) falls through and re-registers.
    """
    mode = "hub" if HUB_REGISTRY_KEY in hass.data else "standalone"
    current = flags.get("page_registered")
    if current == mode and _registration_present(hass, mode):
        return
    if current is not None:
        _teardown_page(hass, flags)

    if mode == "hub":
        registry = hass.data[HUB_REGISTRY_KEY]
        if HUB_PAGE_ID not in registry:
            registry[HUB_PAGE_ID] = _descriptor(_manifest_version(hass))
            hass.bus.async_fire(
                HUB_BUS_EVENT_PAGE_CHANGED, {"id": HUB_PAGE_ID, "action": "register"}
            )
            _LOGGER.info("全屋状态扫描面板已注册到文羽面板壳（%s）", HUB_PAGE_ID)
        flags["page_registered"] = "hub"
        return

    panels = hass.data.get(frontend.DATA_PANELS) or {}
    if PANEL_URL_PATH not in panels:
        frontend.async_register_built_in_panel(
            hass,
            component_name="custom",
            frontend_url_path=PANEL_URL_PATH,
            sidebar_title=PANEL_SIDEBAR_TITLE,
            sidebar_icon=PANEL_SIDEBAR_ICON,
            config={
                "_panel_custom": {
                    "name": PANEL_ELEMENT,
                    "embed_iframe": False,
                    "trust_external": False,
                    "module_url": f"{URL_BASE}/panel.js?ver={_manifest_version(hass)}",
                }
            },
            require_admin=True,
        )
        _LOGGER.info("未检测到文羽面板壳，全屋状态扫描面板注册为独立侧边栏面板")
    flags["page_registered"] = "standalone"


def _teardown_page(hass: HomeAssistant, flags: dict) -> None:
    """Undo _register_page in the recorded mode (hub descriptor vs sidebar)."""
    mode = flags.pop("page_registered", None)
    if mode == "hub":
        registry = hass.data.get(HUB_REGISTRY_KEY)
        if registry is not None and registry.pop(HUB_PAGE_ID, None) is not None:
            hass.bus.async_fire(
                HUB_BUS_EVENT_PAGE_CHANGED,
                {"id": HUB_PAGE_ID, "action": "unregister"},
            )
    elif mode == "standalone":
        frontend.async_remove_panel(hass, PANEL_URL_PATH, warn_if_unknown=False)


async def async_setup_web(hass: HomeAssistant) -> None:
    """Register static assets, panel and API views (once per HA run)."""
    flags: dict = hass.data.setdefault(WEB_DATA_KEY, {})

    if not flags.get("views"):
        hass.http.register_view(ConfigView())
        hass.http.register_view(ControllersView())
        hass.http.register_view(ControllerDetailView())
        hass.http.register_view(EvaluateView())
        hass.http.register_view(ObserveView())
        hass.http.register_view(LogsView())
        flags["views"] = True

    if not flags.get("static"):
        static_dir = Path(__file__).parent / "static"
        await hass.http.async_register_static_paths(
            [StaticPathConfig(URL_BASE, str(static_dir), cache_headers=False)]
        )
        flags["static"] = True

    _register_page(hass, flags)

    if not flags.get("started_recheck"):
        # The hub entry may load after ours during HA boot; at "started" the
        # whole boot set is in, so re-judge the mode once (lux_balance move).
        # Registering for an already-fired event is safe: the listener simply
        # never fires and is popped on the next unload. On-box precedent:
        # FumihaLighting v1.0.1 runs this identical pattern on HA 2026.1.3
        # and reloads cleanly (options saves trigger entry reloads).
        flags["started_recheck"] = hass.bus.async_listen_once(
            EVENT_HOMEASSISTANT_STARTED, _make_started_recheck(hass, flags)
        )


def _make_started_recheck(hass: HomeAssistant, flags: dict):
    @callback
    def _recheck(event: Event) -> None:
        _LOGGER.debug("HA started: re-checking panel registration mode")
        _register_page(hass, flags)

    return _recheck


@callback
def async_unload_web(hass: HomeAssistant) -> None:
    """Tear down the panel on entry unload (static paths/views survive
    entry reloads — the hub object outlives the entry so the API keeps
    answering)."""
    flags: dict = hass.data.get(WEB_DATA_KEY) or {}
    if not flags:
        return
    if flags.get("page_registered"):
        _teardown_page(hass, flags)
    if not flags.get("page_registered") and flags.get("started_recheck"):
        unsub = flags.pop("started_recheck")
        unsub()
