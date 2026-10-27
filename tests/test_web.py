"""Web layer tests: view wiring metadata + dual-path panel registration.

The dual-path suite pins the FumihaHub shell contract (probe → descriptor +
bus event) and the standalone fallback, including symmetric teardown and the
started-recheck mode re-judgement — modeled on the FumihaLighting /
Stockroom reference implementations.
"""

from __future__ import annotations

import asyncio
import types

import pytest

from custom_components.sensor_switch_controller import web as web_mod
from custom_components.sensor_switch_controller.const import (
    API_BASE,
    HUB_BUS_EVENT_PAGE_CHANGED,
    HUB_PAGE_ID,
    HUB_REGISTRY_KEY,
    PANEL_URL_PATH,
    URL_BASE,
)


class FakeBus:
    def __init__(self):
        self.fired: list[tuple] = []
        self.listen_once: list[tuple] = []

    def async_fire(self, event_type, data=None):
        self.fired.append((event_type, data))

    def async_listen_once(self, event_type, cb):
        self.listen_once.append((event_type, cb))
        return lambda: None


class FakeHttp:
    def __init__(self):
        self.views = []
        self.static = []

    def register_view(self, view):
        self.views.append(view)

    async def async_register_static_paths(self, configs):
        self.static.extend(configs)


def make_hass():
    hass = types.SimpleNamespace()
    hass.data = {}
    hass.bus = FakeBus()
    hass.http = FakeHttp()
    return hass


def _setup(hass):
    return asyncio.run(web_mod.async_setup_web(hass))


# ----------------------------------------------------------------------
# View registration metadata
# ----------------------------------------------------------------------


def test_view_urls_and_auth():
    for view, path in (
        (web_mod.ConfigView, "/config"),
        (web_mod.ControllersView, "/controllers"),
        (web_mod.ControllerDetailView, "/controllers/{controller_id}"),
        (web_mod.EvaluateView, "/controllers/{controller_id}/evaluate"),
        (web_mod.ObserveView, "/controllers/{controller_id}/observe"),
        (web_mod.LogsView, "/logs"),
    ):
        instance = view()
        assert instance.url == API_BASE + path
        assert instance.name.startswith("api:sensor_switch_controller:")
        assert instance.requires_auth is True


def test_constants_shape():
    assert URL_BASE == "/sensor_switch_controller"
    assert PANEL_URL_PATH == "wha-scanner"
    assert HUB_PAGE_ID == "sensorswitch.main"


# ----------------------------------------------------------------------
# Dual-path registration (FumihaHub shell probe / standalone fallback)
# ----------------------------------------------------------------------


def test_hub_mode_registers_descriptor():
    hass = make_hass()
    hass.data[HUB_REGISTRY_KEY] = {}
    _setup(hass)
    desc = hass.data[HUB_REGISTRY_KEY][HUB_PAGE_ID]
    assert desc["id"] == "sensorswitch.main"
    assert desc["title"] == "全屋状态扫描"
    assert desc["icon"] == "mdi:state-machine"
    assert desc["order"] == 40
    assert desc["element"] == "sensor-switch-controller-panel"
    assert desc["module_url"].startswith("/sensor_switch_controller/panel.js?ver=")
    assert isinstance(desc["version"], str) and desc["version"]
    # hub 模式不落独立面板；bus 事件恰好一次 register
    assert PANEL_URL_PATH not in hass.data.get("frontend_panels", {})
    assert hass.bus.fired == [
        (HUB_BUS_EVENT_PAGE_CHANGED, {"id": HUB_PAGE_ID, "action": "register"})
    ]
    assert hass.data[web_mod.WEB_DATA_KEY]["page_registered"] == "hub"


def test_standalone_mode_registers_sidebar_panel():
    hass = make_hass()
    _setup(hass)
    panels = hass.data.get("frontend_panels", {})
    assert PANEL_URL_PATH in panels
    panel = panels[PANEL_URL_PATH]
    assert panel["sidebar_title"] == "全屋状态扫描"
    assert panel["sidebar_icon"] == "mdi:state-machine"
    assert panel["config"]["_panel_custom"]["name"] == "sensor-switch-controller-panel"
    assert panel["config"]["_panel_custom"]["module_url"].startswith(
        "/sensor_switch_controller/panel.js?ver="
    )
    # 壳缺席：绝不创建 registry dict（探针必须保持真实），bus 静默
    assert HUB_REGISTRY_KEY not in hass.data
    assert hass.bus.fired == []
    assert hass.data[web_mod.WEB_DATA_KEY]["page_registered"] == "standalone"


def test_repeated_setup_is_idempotent():
    hass = make_hass()
    hass.data[HUB_REGISTRY_KEY] = {}
    _setup(hass)
    _setup(hass)
    assert len(hass.data[HUB_REGISTRY_KEY]) == 1
    assert len(hass.bus.fired) == 1
    assert len(hass.http.views) == 6


def test_hub_unload_pops_descriptor_and_fires_unregister():
    hass = make_hass()
    hass.data[HUB_REGISTRY_KEY] = {}
    _setup(hass)
    web_mod.async_unload_web(hass)
    assert HUB_PAGE_ID not in hass.data[HUB_REGISTRY_KEY]
    assert hass.bus.fired == [
        (HUB_BUS_EVENT_PAGE_CHANGED, {"id": HUB_PAGE_ID, "action": "register"}),
        (HUB_BUS_EVENT_PAGE_CHANGED, {"id": HUB_PAGE_ID, "action": "unregister"}),
    ]
    flags = hass.data[web_mod.WEB_DATA_KEY]
    assert flags.get("page_registered") is None
    assert flags.get("started_recheck") is None


def test_standalone_unload_removes_sidebar_panel():
    hass = make_hass()
    _setup(hass)
    assert PANEL_URL_PATH in hass.data["frontend_panels"]
    web_mod.async_unload_web(hass)
    assert PANEL_URL_PATH not in hass.data.get("frontend_panels", {})
    flags = hass.data[web_mod.WEB_DATA_KEY]
    assert flags.get("page_registered") is None


def test_unload_web_is_noop_without_registration():
    """flags 不存在（从未 setup_web）时卸载是无害 no-op，不碰任何面板。"""
    hass = types.SimpleNamespace(data={})
    calls: list = []
    original = web_mod.frontend.async_remove_panel
    web_mod.frontend.async_remove_panel = lambda *args, **kwargs: calls.append(args)
    try:
        web_mod.async_unload_web(hass)
    finally:
        web_mod.frontend.async_remove_panel = original
    assert calls == []


def test_mode_flip_to_hub_when_shell_arrives():
    """独立面板在先、壳条目后到：再次注册改走 hub 模式并对称拆除旧面板。"""
    hass = make_hass()
    _setup(hass)
    assert hass.data[web_mod.WEB_DATA_KEY]["page_registered"] == "standalone"
    hass.data[HUB_REGISTRY_KEY] = {}
    _setup(hass)
    assert HUB_PAGE_ID in hass.data[HUB_REGISTRY_KEY]
    assert PANEL_URL_PATH not in hass.data.get("frontend_panels", {})
    assert hass.data[web_mod.WEB_DATA_KEY]["page_registered"] == "hub"


def test_hub_reregistration_after_dict_recreated():
    """SR-F-083 回归钉：壳条目删除→重装会换新空 dict——flags 记 hub 而
    描述符已随旧 dict 消失时，条目重载必须补写（模式名早退会永久跳过）。"""
    hass = make_hass()
    hass.data[HUB_REGISTRY_KEY] = {}
    _setup(hass)
    assert HUB_PAGE_ID in hass.data[HUB_REGISTRY_KEY]
    hass.data[HUB_REGISTRY_KEY] = {}  # 壳删除→重装：dict 销毁重建
    _setup(hass)  # 条目重载
    assert HUB_PAGE_ID in hass.data[HUB_REGISTRY_KEY], (
        "描述符必须被补写，不得因模式名相等而早退"
    )
    actions = [d["action"] for _, d in hass.bus.fired]
    assert actions == ["register", "register"]
    assert PANEL_URL_PATH not in hass.data.get("frontend_panels", {})


def test_standalone_reregistration_after_external_removal():
    """SR-F-083 同判据的 standalone 侧：面板被外力移除后重载须重注册。"""
    hass = make_hass()
    _setup(hass)
    assert PANEL_URL_PATH in hass.data["frontend_panels"]
    del hass.data["frontend_panels"][PANEL_URL_PATH]
    _setup(hass)
    assert PANEL_URL_PATH in hass.data["frontend_panels"]


def test_started_recheck_rejudges_mode():
    """壳条目在 HA 启动中晚于本集成加载：started 事件重判一次模式。"""
    hass = make_hass()
    _setup(hass)
    flags = hass.data[web_mod.WEB_DATA_KEY]
    assert flags.get("started_recheck") is not None
    event_type, recheck = hass.bus.listen_once[0]
    assert event_type == "homeassistant_started"
    # 壳仍缺席：重判是 no-op，不误拆独立面板
    recheck(None)
    assert hass.data[web_mod.WEB_DATA_KEY]["page_registered"] == "standalone"
    assert PANEL_URL_PATH in hass.data["frontend_panels"]
    # 壳在启动完成时已就位：翻到 hub 模式
    hass.data[HUB_REGISTRY_KEY] = {}
    recheck(None)
    assert HUB_PAGE_ID in hass.data[HUB_REGISTRY_KEY]
    assert PANEL_URL_PATH not in hass.data.get("frontend_panels", {})


# ----------------------------------------------------------------------
# _save_or_rollback (体检 P2-3 / 审查 R5-10): rollback + reload + re-raise
# ----------------------------------------------------------------------


def _make_hub(hass):
    from custom_components.sensor_switch_controller.hub import ScannerHub

    hub = ScannerHub(hass)
    hub.set_entry("entry1")
    return hub


def _hass_with_config_entries():
    hass = make_hass()
    hass.config_entries = types.SimpleNamespace(
        async_get_entry=lambda eid: object(),
        async_schedule_reload=lambda eid: None,
    )
    return hass


def test_save_rollback_restores_and_schedules_reload():
    """Store.async_save 抛 OSError：内存回滚到快照、排 reload、异常上抛
    （HTTP 层据此答 500）。"""
    hass = _hass_with_config_entries()
    hub = _make_hub(hass)
    hub.controllers["ctrl_a"] = {"name": "a"}
    hub.invalid["ctrl_b"] = {"config": {"name": "b"}, "error": "x"}
    before = (dict(hub.controllers), dict(hub.invalid))
    # the mutation under test — a failed save must undo exactly this
    hub.controllers["ctrl_a"] = {"name": "a2"}
    hub.controllers["ctrl_c"] = {"name": "c"}
    hub.invalid.pop("ctrl_b")

    async def _boom(data):
        raise OSError("disk full")

    hub.store.async_save = _boom
    with pytest.raises(OSError):
        asyncio.run(web_mod._save_or_rollback(hass, hub, before))
    assert hub.controllers == {"ctrl_a": {"name": "a"}}
    assert hub.invalid == {"ctrl_b": {"config": {"name": "b"}, "error": "x"}}
    # a reload is queued so runtime matches the rolled-back store
    assert hass.data.get(web_mod.WEB_DATA_KEY + "_reload_pending")


def test_save_success_persists_without_rollback():
    """保存成功：store 落盘、内存原样、无回滚、不排 reload。"""
    hass = _hass_with_config_entries()
    hub = _make_hub(hass)
    hub.controllers["ctrl_a"] = {"name": "a"}
    asyncio.run(web_mod._save_or_rollback(hass, hub, (dict(hub.controllers), {})))
    assert hub.controllers == {"ctrl_a": {"name": "a"}}
    assert hub.store.saved[-1] == {"controllers": {"ctrl_a": {"name": "a"}}}
    assert not hass.data.get(web_mod.WEB_DATA_KEY + "_reload_pending")
