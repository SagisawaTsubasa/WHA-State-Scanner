"""Home Assistant stubs so the WHA web-layer tests run without a HA install.

The stub tree mirrors the long-standing tests/smoke.py one (proven against
this integration's full import chain) with two upgrades: the frontend stub
is observable (mutates ``hass.data["frontend_panels"]`` so dual-path
registration tests can pin both directions) and voluptuous stays real when
installed. If the real ``homeassistant`` package is already imported, stubs
are skipped so the tests exercise the real helpers (the CI import-check job
covers that path).
"""

from __future__ import annotations

import sys
import types
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

# Make ``custom_components.sensor_switch_controller`` importable from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# homeassistant 尚未导入时才打桩（判据是 sys.modules 的加载状态，不是"是
# 否安装"——CI 的 pytest job 即使装了 HA 也是干净进程，因此仍打桩；桩遮蔽
# 真实依赖的问题由独立的真机 import-check job 兜底）
_INSTALL_STUBS = "homeassistant" not in sys.modules


def _module(name: str, **attrs: Any) -> types.ModuleType:
    mod = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(mod, key, value)
    sys.modules[name] = mod
    return mod


def _identity(func):
    return func


def _callback_decorator(func):
    """Mirror the real @callback marker so tests can assert it."""
    func._hass_callback = True
    return func


class _Store:
    """Minimal stand-in for homeassistant.helpers.storage.Store."""

    def __init__(self, hass: Any, version: int, key: str, **kwargs: Any) -> None:
        self.hass = hass
        self.version = version
        self.key = key
        self.kwargs = kwargs
        self.saved: list[Any] = []
        self.load_result: Any = {"controllers": {}}

    async def async_save(self, data: Any) -> None:
        self.saved.append(data)

    async def async_load(self) -> Any:
        return self.load_result


if _INSTALL_STUBS:
    ha = _module("homeassistant")
    ha.__path__ = []  # mark as package
    ha.core = _module(
        "homeassistant.core",
        HomeAssistant=MagicMock,
        ServiceCall=MagicMock,
        Event=type("Event", (), {}),
        callback=_callback_decorator,
        CALLBACK_TYPE=object,
    )
    ha.core.__getattr__ = lambda name: MagicMock()
    ha.config_entries = _module(
        "homeassistant.config_entries",
        ConfigEntry=MagicMock,
        ConfigFlow=type(
            "ConfigFlow",
            (),
            {"__init_subclass__": classmethod(lambda cls, **kwargs: None)},
        ),
        ConfigFlowResult=type("ConfigFlowResult", (), {}),
    )
    # 常量钉值照 smoke.py（其语义断言依赖这些值；真实 HA 的值即字面量，
    # __getattr__ 返回名字只适合"值无关"的常量——WHA-F-256）
    ha_const = _module(
        "homeassistant.const",
        EVENT_HOMEASSISTANT_STARTED="homeassistant_started",
        CONF_ENTITY_ID="entity_id",
        CONF_STATE="state",
        CONF_VALUE_TEMPLATE="value_template",
        STATE_UNAVAILABLE="unavailable",
        STATE_UNKNOWN="unknown",
    )
    # any missing CONF_* resolves to its own key (same as real HA constants)
    ha_const.__getattr__ = lambda name: name
    ha.exceptions = _module(
        "homeassistant.exceptions",
        HomeAssistantError=type("HomeAssistantError", (Exception,), {}),
    )

    ha.helpers = _module("homeassistant.helpers")
    ha.helpers.__path__ = []  # namespace package: allow helpers.X submodule imports

    class _Evt:
        """Stub event helper module (smoke.py 同款：记录监听、手动触发)."""

        LISTENERS = []

        @staticmethod
        def async_track_state_change_event(hass, entities, action):
            _Evt.LISTENERS.append(("state", list(entities), action))
            return lambda: None

        @staticmethod
        def async_track_time_interval(hass, action, interval):
            _Evt.LISTENERS.append(("interval", action, interval))
            return lambda: None

        @staticmethod
        def async_track_point_in_time(hass, action, point):
            _Evt.LISTENERS.append(("pit", action, point))
            return lambda: None

        @staticmethod
        def async_track_sunrise(hass, action, offset=None):
            _Evt.LISTENERS.append(("sunrise", action, offset))
            return lambda: None

        @staticmethod
        def async_track_sunset(hass, action, offset=None):
            _Evt.LISTENERS.append(("sunset", action, offset))
            return lambda: None

        @staticmethod
        def async_call_later(hass, delay, action):
            _Evt.LISTENERS.append(("later", action, delay))
            return lambda: None

    sys.modules["homeassistant.helpers.event"] = _Evt
    ha.helpers.event = _Evt

    ha.helpers.template = _module("homeassistant.helpers.template")

    class _Template:
        def __init__(self, s, hass=None):
            self.s = s

        def async_render(self):
            return True

    ha.helpers.template.Template = _Template

    ha.util = _module("homeassistant.util")
    ha.util.dt = _module(
        "homeassistant.util.dt",
        now=lambda: datetime(2026, 10, 6, 10, 0, 0),
        utcnow=lambda: datetime(2026, 10, 6, 2, 0, 0),
        start_of_local_day=lambda now=None: (
            now or datetime(2026, 10, 6, 10, 0, 0)
        ).replace(hour=0, minute=0, second=0, microsecond=0),
        as_utc=lambda v: v.replace(tzinfo=None) if v and v.tzinfo is None else v,
        parse_time=lambda s: (
            datetime.strptime(s, "%H:%M:%S").time()
            if len(s.split(":")) == 3
            else datetime.strptime(s, "%H:%M").time()
        ),
    )

    ha.helpers.sun = _module("homeassistant.helpers.sun")
    ha.helpers.sun.get_astral_event_date = lambda hass, event, day: (
        None
        if day is None
        else datetime(
            day.year, day.month, day.day, 6 if event == "sunrise" else 18, 0, 0
        )
    )
    ha.helpers.storage = _module("homeassistant.helpers.storage", Store=_Store)
    ha.helpers.config_validation = _module(
        "homeassistant.helpers.config_validation",
        entity_id=lambda v: v,
        config_entry_only_config_schema=lambda domain: lambda config: config,
    )
    ha.helpers.entity = _module("homeassistant.helpers.entity", DeviceInfo=MagicMock)
    ha.helpers.start = _module(
        "homeassistant.helpers.start", async_at_started=lambda hass, cb: lambda: None
    )
    ha.helpers.entity_registry = _module(
        "homeassistant.helpers.entity_registry",
        async_get=lambda hass: types.SimpleNamespace(
            async_remove=lambda entity_id: None
        ),
    )
    ha.loader = _module(
        "homeassistant.loader",
        async_get_loaded_integration=lambda hass, domain: types.SimpleNamespace(
            version="0"
        ),
    )

    ha.components = _module("homeassistant.components")
    ha.components.__path__ = []

    class _HomeAssistantView:
        url = ""
        name = ""
        requires_auth = True

        def json(self, data, status_code=200):
            import json as _json

            return types.SimpleNamespace(
                status=status_code, text=_json.dumps(data, ensure_ascii=False)
            )

    # frontend（面板/注册表双路径）：可观察桩——真实读写 hass.data["frontend_panels"]
    ha.frontend = _module(
        "homeassistant.components.frontend",
        DATA_PANELS="frontend_panels",
        async_register_built_in_panel=lambda hass, **kwargs: hass.data.setdefault(
            "frontend_panels", {}
        ).__setitem__(kwargs["frontend_url_path"], kwargs),
        async_remove_panel=lambda hass, path, warn_if_unknown=True: hass.data.get(
            "frontend_panels", {}
        ).pop(path, None),
    )
    ha.http = _module(
        "homeassistant.components.http",
        HomeAssistantView=_HomeAssistantView,
        StaticPathConfig=MagicMock,
        require_admin=_identity,
    )
    _module(
        "homeassistant.components.switch", SwitchEntity=type("SwitchEntity", (), {})
    )
    _module(
        "homeassistant.components.binary_sensor",
        BinarySensorEntity=type("BinarySensorEntity", (), {}),
    )
    _module(
        "homeassistant.components.calendar",
        async_get_events=lambda *a, **k: [],
    )

    # aiohttp：环境里没装时打桩（web.py 只在注解与 json_response 用到）
    try:
        import aiohttp  # noqa: F401
    except ImportError:
        _aio = _module("aiohttp", web=None)
        _aio_web = _module("aiohttp.web")
        _aio_web.Request = type("Request", (), {})
        _aio_web.Response = type("Response", (), {})
        _aio_web.json_response = lambda *a, **k: types.SimpleNamespace(status=200)
        _aio.web = _aio_web

    # 子模块挂到父模块属性上，供 from homeassistant.components import X 使用
    for name in [m for m in list(sys.modules) if m.startswith("homeassistant.")]:
        parent_name, _, child = name.rpartition(".")
        parent = sys.modules.get(parent_name)
        if parent is not None and not hasattr(parent, child):
            setattr(parent, child, sys.modules[name])
