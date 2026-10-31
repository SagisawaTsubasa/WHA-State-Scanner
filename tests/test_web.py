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
    DOMAIN,
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


def test_unload_unsubs_pending_recheck():
    """F-334 对照面：监听尚未触发（HA 未 started）时，unload 照常 unsub
    ——此时监听仍在 bus 上，正常移除。"""
    hass = make_hass()
    _setup(hass)
    flags = hass.data[web_mod.WEB_DATA_KEY]
    calls: list = []
    flags["started_recheck"] = lambda: calls.append(1)
    web_mod.async_unload_web(hass)
    assert calls == [1], "a pending listen_once must be unsubbed on unload"
    assert flags.get("started_recheck") is None


def test_unload_skips_unsub_after_recheck_fired():
    """F-334 主钉：recheck 已触发后 unload 不得再 unsub——真实 HA 在触发
    时已自行移除监听（_OneTimeListener.__call__ 先 self.remove()，
    2026.1.3 core.py），再 unsub 会在 EventBus._async_remove_listener 里
    ValueError 并把 "Unable to remove unknown job listener" 写进
    error_log（try/except 治不了：异常在 core 内部被吞并记日志）。"""
    hass = make_hass()
    _setup(hass)
    flags = hass.data[web_mod.WEB_DATA_KEY]
    calls: list = []
    flags["started_recheck"] = lambda: calls.append(1)
    _event_type, recheck = hass.bus.listen_once[0]
    recheck(None)  # fired → the callback clears the key itself
    assert flags.get("started_recheck") is None
    web_mod.async_unload_web(hass)
    assert calls == [], (
        "unload must NOT unsub an already-fired listen_once (F-334)"
    )


# ----------------------------------------------------------------------
# _save_or_rollback (体检 P2-3 / 审查 R5-10, key-granular per 审查 R6-2):
# single-key rollback + store re-read + reload + re-raise
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


def test_save_rollback_restores_key_and_schedules_reload():
    """Store.async_save 抛 OSError（审查 R6-2）：只回滚本次请求的键、对端
    已落盘改动经重读保留、排 reload、异常上抛（HTTP 层据此答 500）。
    整表快照回滚会把对端键一并抹掉——那正是本钉要抓的回归。"""
    hass = _hass_with_config_entries()
    hub = _make_hub(hass)
    hub.controllers["ctrl_aaaaaaaa"] = {"name": "a"}
    hub.controllers["ctrl_bbbbbbbb"] = {"name": "peer"}
    snap = web_mod._key_snapshot(hub, "ctrl_aaaaaaaa")
    # the mutation under test — a failed save must undo exactly this key
    hub.controllers["ctrl_aaaaaaaa"] = {"name": "a2"}
    # a peer change another request committed meanwhile (via its own save)
    hub.controllers["ctrl_bbbbbbbb"] = {"name": "peer2"}

    async def _boom(data):
        raise OSError("disk full")

    hub.store.async_save = _boom
    # the durable store holds the peer's committed state (not our failed one)
    hub.store.load_result = {
        "controllers": {"ctrl_aaaaaaaa": {"name": "a"}, "ctrl_bbbbbbbb": {"name": "peer2"}}
    }
    with pytest.raises(OSError):
        asyncio.run(web_mod._save_or_rollback(hass, hub, "ctrl_aaaaaaaa", snap))
    # the re-read normalizes configs through validate_controller — compare
    # identities: our key rolled back, the peer's committed change survived
    assert {cid: c["name"] for cid, c in hub.controllers.items()} == {
        "ctrl_aaaaaaaa": "a",
        "ctrl_bbbbbbbb": "peer2",
    }, hub.controllers
    # a reload is queued so runtime matches the rolled-back store
    assert hass.data.get(web_mod.WEB_DATA_KEY + "_reload_pending")


def test_save_rollback_without_reread_restores_key_in_memory():
    """重读也失败（存储仍坏）时按键回滚内存快照兜底，并排 reload。"""
    hass = _hass_with_config_entries()
    hub = _make_hub(hass)
    hub.controllers["ctrl_aaaaaaaa"] = {"name": "a"}
    snap = web_mod._key_snapshot(hub, "ctrl_aaaaaaaa")
    hub.controllers["ctrl_aaaaaaaa"] = {"name": "a2"}
    hub.controllers["ctrl_cccccccc"] = {"name": "n"}

    async def _boom(data):
        raise OSError("disk full")

    async def _load_broken():
        raise OSError("still broken")

    hub.store.async_save = _boom
    hub.store.async_load = _load_broken
    with pytest.raises(OSError):
        asyncio.run(web_mod._save_or_rollback(hass, hub, "ctrl_aaaaaaaa", snap))
    assert hub.controllers == {"ctrl_aaaaaaaa": {"name": "a"}, "ctrl_cccccccc": {"name": "n"}}, (
        hub.controllers
    )
    assert hass.data.get(web_mod.WEB_DATA_KEY + "_reload_pending")


def test_save_success_persists_without_rollback():
    """保存成功：store 落盘、内存原样、无回滚、不排 reload。"""
    hass = _hass_with_config_entries()
    hub = _make_hub(hass)
    hub.controllers["ctrl_aaaaaaaa"] = {"name": "a"}
    snap = web_mod._key_snapshot(hub, "ctrl_aaaaaaaa")
    asyncio.run(web_mod._save_or_rollback(hass, hub, "ctrl_aaaaaaaa", snap))
    assert hub.controllers == {"ctrl_aaaaaaaa": {"name": "a"}}
    assert hub.store.saved[-1] == {"controllers": {"ctrl_aaaaaaaa": {"name": "a"}}}
    assert not hass.data.get(web_mod.WEB_DATA_KEY + "_reload_pending")


# ----------------------------------------------------------------------
# DELETE view ordering (审查 R6-6 / R6-4): sweep_registry only after the
# durable save; a failed save skips the irreversible phases entirely.
# ----------------------------------------------------------------------


class _FakeManager:
    """Duck-typed ControllerManager: records unload, holds one entity."""

    def __init__(self):
        self.entities = {
            "ssc_x": types.SimpleNamespace(entity_id="binary_sensor.x")
        }
        self.unloaded = False

    def async_unload(self):
        self.unloaded = True


def _make_crud_hub(hass):
    """A hub PUBLISHED in hass.data — the views read it via get_hub()."""
    hub = _make_hub(hass)
    hass.data[DOMAIN] = hub
    return hub


def _make_request(hass):
    return types.SimpleNamespace(app={"hass": hass})


async def _async_noop(*args, **kwargs):
    return None


def _noop_task(coro, name=None):
    """build_managers hands managers to the background scheduler; the
    reload re-read tests only pin the store, so close the coroutine
    (no runtime, no never-awaited warning)."""
    coro.close()
    return None


def test_delete_view_sweeps_only_after_durable_save():
    """DELETE 视图顺序 = 内存摘除（含活实体分支）→ 主存储落盘 → registry
    清扫 → flag 丢弃 → reload；活实体的 manager 必须被卸载。"""
    hass = _hass_with_config_entries()
    hub = _make_crud_hub(hass)
    hub.controllers["ctrl_ab12cd34"] = {"name": "doomed"}
    mgr = _FakeManager()
    hub.managers["ctrl_ab12cd34"] = mgr
    calls: list[str] = []
    hub.sweep_registry = lambda cid, eids: calls.append("sweep")

    real_save = hub.store.async_save

    async def _save(data):
        calls.append("save")
        await real_save(data)

    hub.store.async_save = _save
    resp = asyncio.run(
        web_mod.ControllerDetailView().delete(
            _make_request(hass), "ctrl_ab12cd34"
        )
    )
    assert resp.status == 200
    assert calls == ["save", "sweep"], calls
    assert mgr.unloaded is True, "the live-entity branch must unload the manager"
    assert "ctrl_ab12cd34" not in hub.controllers
    assert hass.data.get(web_mod.WEB_DATA_KEY + "_reload_pending")


def test_delete_view_failed_save_keeps_controller_and_skips_sweep():
    """save 抛错：不可逆的 registry 清扫不得运行，控制器按键回滚，
    排 reload，异常上抛（HTTP 层据此答 500）。"""
    hass = _hass_with_config_entries()
    hub = _make_crud_hub(hass)
    doomed = {"name": "doomed"}
    hub.controllers["ctrl_ab12cd34"] = doomed
    calls: list[str] = []
    hub.sweep_registry = lambda cid, eids: calls.append("sweep")

    async def _boom(data):
        raise OSError("disk full")

    hub.store.async_save = _boom
    with pytest.raises(OSError):
        asyncio.run(
            web_mod.ControllerDetailView().delete(
                _make_request(hass), "ctrl_ab12cd34"
            )
        )
    assert "sweep" not in calls, (
        "the irreversible sweep must not run before the save wins"
    )
    assert hub.controllers.get("ctrl_ab12cd34") == doomed, (
        "the key rollback must restore the controller"
    )
    assert hass.data.get(web_mod.WEB_DATA_KEY + "_reload_pending")


# ----------------------------------------------------------------------
# Entry reload with a surviving hub (审查 R6-2): the reload MUST re-read
# the store, or a rolled-back memory would permanently diverge from disk
# and the next save would overwrite the peer's committed changes.
# ----------------------------------------------------------------------


def test_setup_entry_reload_rereads_store():
    """hub 存活条目重载：async_setup_entry 重读存储（持 crud_lock），
    内存收敛到落盘状态；重读失败降级 warning 并保留原内存。"""
    from custom_components.sensor_switch_controller import (
        async_setup_entry as _setup_entry,
    )

    hass = make_hass()
    hass.config_entries = types.SimpleNamespace(
        async_get_entry=lambda eid: object(),
        async_schedule_reload=lambda eid: None,
        async_forward_entry_setups=_async_noop,
    )
    hass.async_create_background_task = _noop_task
    hass.config = types.SimpleNamespace(config_dir="/tmp")
    hass.services = types.SimpleNamespace(
        has_service=lambda domain, name: True  # skip service registration
    )
    hub = _make_crud_hub(hass)
    hub.store.load_result = {"controllers": {"ctrl_bbbbbbbb": {"name": "peer"}}}
    entry = types.SimpleNamespace(
        entry_id="entry1",
        async_on_unload=lambda fn: None,
        add_update_listener=lambda fn: None,
    )
    assert asyncio.run(_setup_entry(hass, entry)) is True
    assert "ctrl_bbbbbbbb" in hub.controllers, (
        "the reload must re-read the store into the surviving hub (R6-2)"
    )


def test_setup_entry_reload_keeps_memory_when_reread_fails():
    """重读失败（存储坏）不炸条目 setup：warning + 保留 last-known-good。"""
    from custom_components.sensor_switch_controller import (
        async_setup_entry as _setup_entry,
    )

    hass = make_hass()
    hass.config_entries = types.SimpleNamespace(
        async_get_entry=lambda eid: object(),
        async_schedule_reload=lambda eid: None,
        async_forward_entry_setups=_async_noop,
    )
    hass.async_create_background_task = _noop_task
    hass.config = types.SimpleNamespace(config_dir="/tmp")
    hass.services = types.SimpleNamespace(has_service=lambda domain, name: True)
    hub = _make_crud_hub(hass)
    hub.controllers["ctrl_aaaaaaaa"] = {"name": "keep-me"}

    async def _load_broken():
        raise OSError("still broken")

    hub.store.async_load = _load_broken
    entry = types.SimpleNamespace(
        entry_id="entry1",
        async_on_unload=lambda fn: None,
        add_update_listener=lambda fn: None,
    )
    assert asyncio.run(_setup_entry(hass, entry)) is True
    assert hub.controllers.get("ctrl_aaaaaaaa") == {"name": "keep-me"}, (
        "a failed re-read must keep the last-known-good memory"
    )


# ----------------------------------------------------------------------
# Discriminating pins for the R6 protections themselves (审查 R7-5): the
# per-phase isolation on DELETE (F-293) and the crud_lock serialization
# (F-291) must turn red when the guard itself is deleted, not only when
# the happy path changes shape.
# ----------------------------------------------------------------------


def test_delete_view_sweep_failure_still_drops_flags_and_reloads():
    """sweep_registry 抛错（审查 R7-5/F-293 判别钉）：不假 500、不跳过
    flag 丢弃与 reload——DELETE 后段各阶段独立收口，删除任一 try/except
    本用例即红。"""
    hass = _hass_with_config_entries()
    hub = _make_crud_hub(hass)
    hub.controllers["ctrl_ab12cd34"] = {"name": "doomed"}

    def _boom(cid, eids):
        raise RuntimeError("registry gone")

    hub.sweep_registry = _boom
    dropped: list[str] = []
    real_drop = hub.async_drop_flag_states

    async def _drop(cid):
        dropped.append(cid)
        await real_drop(cid)

    hub.async_drop_flag_states = _drop
    resp = asyncio.run(
        web_mod.ControllerDetailView().delete(
            _make_request(hass), "ctrl_ab12cd34"
        )
    )
    assert resp.status == 200
    assert dropped == ["ctrl_ab12cd34"], (
        "the flag drop must still run after a failed sweep"
    )
    assert hass.data.get(web_mod.WEB_DATA_KEY + "_reload_pending"), (
        "the reload must still be scheduled after a failed sweep"
    )


def test_delete_view_flag_drop_failure_still_reloads():
    """async_drop_flag_states 抛错（审查 R7-5/F-293 判别钉）：sweep 已
    完成、reload 仍排队——删掉第二个 try/except 本用例即红。"""
    hass = _hass_with_config_entries()
    hub = _make_crud_hub(hass)
    hub.controllers["ctrl_ab12cd34"] = {"name": "doomed"}
    swept: list[str] = []
    hub.sweep_registry = lambda cid, eids: swept.append(cid)

    async def _boom(cid):
        raise RuntimeError("flag store locked")

    hub.async_drop_flag_states = _boom
    resp = asyncio.run(
        web_mod.ControllerDetailView().delete(
            _make_request(hass), "ctrl_ab12cd34"
        )
    )
    assert resp.status == 200
    assert swept == ["ctrl_ab12cd34"], (
        "the sweep must still have run before the flag drop failed"
    )
    assert hass.data.get(web_mod.WEB_DATA_KEY + "_reload_pending"), (
        "the reload must still be scheduled after a failed flag drop"
    )


def test_crud_lock_serializes_delete_requests():
    """crud_lock 判别钉（审查 R7-5/F-291）：第二个请求的键快照必须等第
    一个请求的 save 释放锁之后发生——把三视图的 ``async with
    hub.crud_lock`` 删掉本用例即红（快照会在对方 save 挂起时插入）。"""
    hass = _hass_with_config_entries()
    hub = _make_crud_hub(hass)
    hub.controllers["ctrl_aaaaaaaa"] = {"name": "a"}
    hub.controllers["ctrl_bbbbbbbb"] = {"name": "b"}
    events: list[str] = []
    real_snapshot = web_mod._key_snapshot

    def _snapshot(h, cid):
        events.append(f"snapshot:{cid}")
        return real_snapshot(h, cid)

    web_mod._key_snapshot = _snapshot

    async def _driver():
        release = asyncio.Event()
        real_save = hub.store.async_save
        state = {"n": 0}

        async def _gated_save(data):
            state["n"] += 1
            if state["n"] == 1:
                events.append("save:enter:a")
                await release.wait()
                events.append("save:exit:a")
            else:
                events.append("save:fast")
                await real_save(data)

        hub.store.async_save = _gated_save
        view = web_mod.ControllerDetailView()
        t1 = asyncio.create_task(
            view.delete(_make_request(hass), "ctrl_aaaaaaaa")
        )
        for _ in range(20):  # let task 1 reach its gated save
            await asyncio.sleep(0)
        assert "save:enter:a" in events, events
        t2 = asyncio.create_task(
            view.delete(_make_request(hass), "ctrl_bbbbbbbb")
        )
        for _ in range(20):  # the lock must keep task 2 waiting
            await asyncio.sleep(0)
        assert "snapshot:ctrl_bbbbbbbb" not in events, (
            "the second request must block on crud_lock while the first "
            f"save is in flight; events={events}"
        )
        release.set()
        await asyncio.gather(t1, t2)

    try:
        asyncio.run(_driver())
    finally:
        web_mod._key_snapshot = real_snapshot
    assert events.index("save:exit:a") < events.index(
        "snapshot:ctrl_bbbbbbbb"
    ), events
    assert events.count("save:fast") == 1, events


# ----------------------------------------------------------------------
# PUT repair race (审查 R7-4/F-300): the repairing verdict is re-derived
# under the lock and repair_controller raises KeyError on a vanished key
# like update_controller — a concurrent DELETE is never resurrected.
# ----------------------------------------------------------------------


def test_repair_controller_raises_on_vanished_key():
    """repair_controller 对已消失的键抛 KeyError（与 update 同判据）。"""
    hass = _hass_with_config_entries()
    hub = _make_crud_hub(hass)
    with pytest.raises(KeyError):
        hub.repair_controller("ctrl_ab12cd34", {"name": "x"})


def test_put_repair_racing_delete_answers_404():
    """repairing 判据在锁内重判：pre-lock 看见 invalid、拿锁时键已被并发
    DELETE 清掉 → 404，绝不复活已删控制器。"""
    hass = _hass_with_config_entries()
    hub = _make_crud_hub(hass)
    seen = {"first": True}

    class _FlippyInvalid(dict):
        """pre-lock 检查答 True，锁内重判答 False（模拟并发 DELETE 清键）。"""

        def __contains__(self, key):
            if key == "ctrl_ab12cd34" and seen["first"]:
                seen["first"] = False
                return True
            return super().__contains__(key)

    hub.invalid = _FlippyInvalid()
    real_validate = web_mod.validate_controller
    web_mod.validate_controller = lambda body: dict(body)
    req = _make_request(hass)

    async def _json():
        return {"name": "raced"}

    req.json = _json
    try:
        resp = asyncio.run(
            web_mod.ControllerDetailView().put(req, "ctrl_ab12cd34")
        )
    finally:
        web_mod.validate_controller = real_validate
    assert resp.status == 404, resp
    assert "ctrl_ab12cd34" not in hub.controllers, (
        "a controller deleted concurrently must not be resurrected"
    )


# ----------------------------------------------------------------------
# F-332: the PUT path sweeps registry entries orphaned by the update
# (dropped outputs / switch↔binary_sensor type switches) — after the
# durable save only, best-effort, scoped to the controller's unique_id
# prefix and the validated output set.
# ----------------------------------------------------------------------


def _put_request(hass, body):
    req = _make_request(hass)

    async def _json():
        return body

    req.json = _json
    return req


def test_put_view_sweeps_orphaned_registry_entries():
    """PUT 保存成功后 diff 清扫：被删输出与类型切换的 registry 条目移除，
    保留输出与其它控制器的条目不动（DELETE 有 sweep，PUT 自 0.11.0 起同款）。"""
    hass = _hass_with_config_entries()
    hub = _make_crud_hub(hass)
    from homeassistant.helpers import entity_registry as _er

    fake = _er._fake
    fake.entries.clear()
    fake.removed.clear()
    o1 = "ssc_" + "1" * 32
    o3 = "ssc_" + "3" * 32
    fake.add(f"ctrl_ab12cd34_{o1}", "switch.o1", "switch")  # kept
    fake.add("ctrl_ab12cd34_ssc_dead", "switch.o2", "switch")  # dropped
    fake.add(f"ctrl_ab12cd34_{o3}", "switch.o3", "switch")  # type-switched
    fake.add("ctrl_99999999_ssc_9", "switch.other", "switch")  # other cid
    hub.controllers["ctrl_ab12cd34"] = {"name": "x"}
    body = {
        "name": "x",
        "outputs": [
            {"name": "o1", "type": "switch", "entity_id": o1},
            {"name": "o3", "type": "binary_sensor", "entity_id": o3},
        ],
    }
    real_validate = web_mod.validate_controller
    web_mod.validate_controller = lambda b: dict(b)
    try:
        resp = asyncio.run(
            web_mod.ControllerDetailView().put(_put_request(hass, body), "ctrl_ab12cd34")
        )
    finally:
        web_mod.validate_controller = real_validate
    assert resp.status == 200, resp
    assert hub.store.saved, "the update must be durable before the sweep"
    assert sorted(fake.removed) == [
        "switch.o2",
        "switch.o3",
    ], fake.removed
    # reload still scheduled after the sweep
    assert hass.data.get(web_mod.WEB_DATA_KEY + "_reload_pending")


def test_put_view_skips_sweep_when_save_fails():
    """保存失败（rollback 上抛 500）：不可逆的 registry 清扫不得执行。"""
    hass = _hass_with_config_entries()
    hub = _make_crud_hub(hass)
    from homeassistant.helpers import entity_registry as _er

    _er._fake.entries.clear()
    _er._fake.removed.clear()
    hub.controllers["ctrl_ab12cd34"] = {"name": "x"}
    calls: list = []

    def _sweep(cid, outs):
        calls.append(cid)

    hub.sweep_registry_diff = _sweep
    real_save = hub.store.async_save

    async def _fail(data):
        raise OSError("disk full")

    hub.store.async_save = _fail
    body = {"name": "x", "outputs": []}
    real_validate = web_mod.validate_controller
    web_mod.validate_controller = lambda b: dict(b)
    try:
        with pytest.raises(OSError):
            asyncio.run(
                web_mod.ControllerDetailView().put(
                    _put_request(hass, body), "ctrl_ab12cd34"
                )
            )
    finally:
        web_mod.validate_controller = real_validate
        hub.store.async_save = real_save
    assert calls == [], "the sweep must not run before the save wins"
