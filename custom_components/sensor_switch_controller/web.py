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
from homeassistant.core import HomeAssistant, callback
from homeassistant.loader import async_get_loaded_integration

from .const import (
    API_BASE,
    DOMAIN,
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

        cid = hub.create_controller(config)
        await hub.async_save()
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
        if cid not in hub.controllers:
            return self.json({"ok": False, "error": "控制器不存在"}, status_code=404)
        try:
            body = await _parse_json(request)
            config = validate_controller(body)
        except ControllerValidationError as err:
            return self.json({"ok": False, "error": str(err)}, status_code=400)
        except _WebError as err:
            return _error_response(self, err)

        # Honor the id the client saved under (URL wins over body).
        hub.update_controller(cid, config)
        await hub.async_save()
        _schedule_reload(hass, hub)
        _LOGGER.info("Updated controller %s (%s) via web", cid, config["name"])
        return self.json({"ok": True, "id": cid})

    @require_admin
    async def delete(self, request: web.Request, controller_id: str) -> web.Response:
        """Delete one controller."""
        hass = request.app["hass"]
        hub = get_hub(hass)
        if hub is None:
            return self.json({"ok": False, "error": "集成未加载"}, status_code=503)
        cid = controller_id
        if cid not in hub.controllers:
            return self.json({"ok": False, "error": "控制器不存在"}, status_code=404)
        hub.remove_controller(cid)
        await hub.async_save()
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


class LogsView(HomeAssistantView):
    """GET /api/sensor_switch_controller/logs?controller_id=&date=&decision=&limit="""

    url = API_BASE + "/logs"
    name = "api:sensor_switch_controller:logs"
    requires_auth = True

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


@callback
def _schedule_reload(hass: HomeAssistant, hub: ScannerHub) -> None:
    """Reload the config entry after a store mutation.

    ``async_schedule_reload`` is a @callback that schedules the reload task
    itself — it must be called directly, never wrapped in a task.
    """
    if not hub.entry_id:
        return
    if hass.config_entries.async_get_entry(hub.entry_id) is None:
        # Entry was removed; keep the store write but nothing to reload.
        return
    hass.config_entries.async_schedule_reload(hub.entry_id)


async def async_setup_web(hass: HomeAssistant) -> None:
    """Register static assets, panel and API views (once per HA run)."""
    flags: dict = hass.data.setdefault(WEB_DATA_KEY, {})

    if not flags.get("views"):
        hass.http.register_view(ConfigView())
        hass.http.register_view(ControllersView())
        hass.http.register_view(ControllerDetailView())
        hass.http.register_view(EvaluateView())
        hass.http.register_view(LogsView())
        flags["views"] = True

    if not flags.get("static"):
        static_dir = Path(__file__).parent / "static"
        await hass.http.async_register_static_paths(
            [StaticPathConfig(URL_BASE, str(static_dir), cache_headers=False)]
        )
        flags["static"] = True

    panels = hass.data.get(frontend.DATA_PANELS) or {}
    if PANEL_URL_PATH not in panels:
        version = "dev"
        try:
            version = async_get_loaded_integration(hass, DOMAIN).version or version
        except Exception:  # noqa: BLE001 — version is only a cache buster
            _LOGGER.debug("Could not resolve integration version for panel URL")
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
                    "module_url": f"{URL_BASE}/panel.js?ver={version}",
                }
            },
            require_admin=True,
        )


@callback
def async_unload_web(hass: HomeAssistant) -> None:
    """Remove the sidebar panel (static paths/views survive entry reloads)."""
    frontend.async_remove_panel(hass, PANEL_URL_PATH, warn_if_unknown=False)
