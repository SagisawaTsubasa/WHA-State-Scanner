# -*- coding: utf-8 -*-
"""Import-chain + 0.7.3 directed-semantics smoke test (no HA required).

Catches the failure classes that ruff/py_compile/node cannot see:
  1. ImportError across the whole integration module graph (missing names,
     stale imports) — run by importing every module with a stubbed HA tree.
  2. Runtime AttributeError inside the evaluation path — driven end-to-end
     against stub HA.
  3. 0.7.3 semantics: v2/v3/v4/v5/v6→v7 store migration (condition coverage),
     trigger routes (directed evaluation, wired-to-nothing wakes nothing),
     duration TON gate,
     debounce quiet gate, directed timed wakeups, schema rules (time.at
     rejected, trigger id preserved).

Usage: python tests/smoke.py
Exit code 0 = pass; anything else prints the failure.
"""

from __future__ import annotations

import asyncio
import importlib
import json
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parent.parent
PKG = "custom_components.sensor_switch_controller"
sys.path.insert(0, str(ROOT))

# ---------------------------------------------------------------------------
# Minimal stub of the homeassistant module tree (only what we import).
# ---------------------------------------------------------------------------

def _mod(name: str) -> types.ModuleType:
    m = types.ModuleType(name)
    sys.modules[name] = m
    return m

ha = _mod("homeassistant")
ha.__path__ = []  # mark as package
ha_const = _mod("homeassistant.const")
for k, v in {
    "CONF_ENTITY_ID": "entity_id",
    "CONF_STATE": "state",
    "CONF_VALUE_TEMPLATE": "value_template",
    "STATE_UNAVAILABLE": "unavailable",
    "STATE_UNKNOWN": "unknown",
    "STATE_ON": "on",
    "STATE_OFF": "off",
}.items():
    setattr(ha_const, k, v)
# any missing CONF_* resolves to its own key (same as real HA constants)
ha_const.__getattr__ = lambda name: name
ha.core = _mod("homeassistant.core")
ha.core.HomeAssistant = MagicMock
ha.core.ServiceCall = MagicMock
ha.core.callback = lambda f: f
ha.core.HassKey = str
ha.core.CALLBACK_TYPE = object
ha.core.__getattr__ = lambda name: MagicMock()
ha.config_entries = _mod("homeassistant.config_entries")
ha.config_entries.ConfigEntry = MagicMock


# Mutable clock: duration/debounce evaluation advances this between checks.
_clock = {
    "local": datetime(2026, 10, 6, 10, 0, 0),
    "utc": datetime(2026, 10, 6, 2, 0, 0),
}


def _advance_utc(seconds: float) -> None:
    _clock["utc"] = _clock["utc"] + timedelta(seconds=seconds)


class _Evt:
    """Stub event helper module: record listeners, manual firing."""

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


ha.helpers = _mod("homeassistant.helpers")
ha.helpers.__path__ = []  # namespace package: allow helpers.X submodule imports
sys.modules["homeassistant.helpers.event"] = _Evt
ha.helpers.event = _Evt
ha.helpers.template = _mod("homeassistant.helpers.template")


class _Template:
    def __init__(self, s, hass=None):
        self.s = s

    def async_render(self):
        return True


ha.helpers.template.Template = _Template
ha.util = _mod("homeassistant.util")
ha.util.dt = _mod("homeassistant.util.dt")
ha.util.dt.now = lambda: _clock["local"]
ha.util.dt.utcnow = lambda: _clock["utc"]
ha.util.dt.start_of_local_day = lambda now=None: (_clock["local"] if now is None else now).replace(
    hour=0, minute=0, second=0, microsecond=0
)
ha.util.dt.as_utc = lambda v: v.replace(tzinfo=None) if v and v.tzinfo is None else v
ha.util.dt.parse_time = lambda s: datetime.strptime(s, "%H:%M:%S").time() if len(s.split(":")) == 3 else datetime.strptime(s, "%H:%M").time()
# F-322: the persisted flip history is stored as ISO strings and parsed back
# on manager construction — the stub clock is naive, so plain fromisoformat
# matches the (naive) round-trip of the real path.
ha.util.dt.parse_datetime = lambda s: (
    datetime.fromisoformat(s) if isinstance(s, str) else None
)

ha.helpers.sun = _mod("homeassistant.helpers.sun")
ha.helpers.sun.get_astral_event_date = lambda hass, event, day: (
    None if day is None else datetime(day.year, day.month, day.day,
    6 if event == "sunrise" else 18, 0, 0)
)
ha.helpers.storage = _mod("homeassistant.helpers.storage")


class _Store:
    def __init__(self, hass, version, key):
        pass

    async def async_load(self):
        return {"controllers": {}}

    async def async_save(self, data):
        pass

    def async_delay_save(self, data_func, delay=0):
        # F-339: the hub's debounced flip-history write lands here; the
        # no-op stub discards it (same shape as async_save). Pins that must
        # observe the payload swap in a _RecordingFlagStore.
        pass


ha.helpers.storage.Store = _Store
ha.helpers.config_validation = _mod("homeassistant.helpers.config_validation")
ha.helpers.config_validation.entity_id = lambda v: v
ha.helpers.entity = _mod("homeassistant.helpers.entity")
ha.helpers.entity.DeviceInfo = MagicMock


class _RestoreEntity:
    """Stub mixin: async_get_last_state yields the instance-configured
    previous state (or None) so the RestoreEntity restore path is testable
    (审查 R5-10)."""

    _restored_state: str | None = None

    async def async_added_to_hass(self):
        return None

    async def async_get_last_state(self):
        if self._restored_state is None:
            return None
        return types.SimpleNamespace(state=self._restored_state)


ha.helpers.restore_state = _mod("homeassistant.helpers.restore_state")
ha.helpers.restore_state.RestoreEntity = _RestoreEntity
ha.helpers.start = _mod("homeassistant.helpers.start")
ha.helpers.start.async_at_started = lambda hass, cb: (lambda: None)
ha.helpers.entity_component = _mod("homeassistant.helpers.entity_component")
ha.helpers.entity_component.DATA_INSTANCES = "entity_components"


class _FakeRegistry:
    """Injectable entity-registry stub: records removals, holds entries."""

    def __init__(self):
        self.removed: list[str] = []
        self.entries: list[types.SimpleNamespace] = []

    def add(self, entity_id, unique_id):
        self.entries.append(
            types.SimpleNamespace(entity_id=entity_id, unique_id=unique_id)
        )

    def async_remove(self, entity_id):
        self.removed.append(entity_id)

    def entries_for(self, config_entry_id):
        return list(self.entries)


_FAKE_REGISTRY = _FakeRegistry()
ha.helpers.entity_registry = _mod("homeassistant.helpers.entity_registry")
ha.helpers.entity_registry.async_get = lambda hass: _FAKE_REGISTRY


def _entries_for_config_entry(registry, config_entry_id):
    return registry.entries_for(config_entry_id)


ha.helpers.entity_registry.async_entries_for_config_entry = (
    _entries_for_config_entry
)


class _FakeDeviceRegistry:
    """Injectable device-registry stub: records removals, holds devices
    (审查 R5-7)."""

    def __init__(self):
        self.removed: list[str] = []
        self.devices: dict[str, types.SimpleNamespace] = {}

    def add(self, device_id, identifiers):
        self.devices[device_id] = types.SimpleNamespace(
            id=device_id, identifiers=identifiers
        )

    def async_get_device(self, identifiers=None, connections=None):
        for device in self.devices.values():
            if device.identifiers == identifiers:
                return device
        return None

    def async_remove_device(self, device_id):
        self.removed.append(device_id)
        self.devices.pop(device_id, None)


_FAKE_DEVICE_REGISTRY = _FakeDeviceRegistry()
ha.helpers.device_registry = _mod("homeassistant.helpers.device_registry")
ha.helpers.device_registry.async_get = lambda hass: _FAKE_DEVICE_REGISTRY

ha.loader = _mod("homeassistant.loader")
ha.loader.async_get_loaded_integration = lambda hass, domain: types.SimpleNamespace(
    version="test"
)
ha.components = _mod("homeassistant.components")
ha.components.__path__ = []
ha.config_entries.ConfigFlow = type("ConfigFlow", (), {"__init_subclass__": classmethod(lambda cls, **kw: None)})
ha.http = _mod("homeassistant.components.http")
ha.http.HomeAssistantView = type("HomeAssistantView", (), {"json": None})

ha.comp_switch = _mod("homeassistant.components.switch")
ha.comp_switch.SwitchEntity = type("SwitchEntity", (), {})
ha.comp_binary = _mod("homeassistant.components.binary_sensor")
ha.comp_binary.BinarySensorEntity = type("BinarySensorEntity", (), {})
ha.comp_calendar = _mod("homeassistant.components.calendar")
ha.comp_calendar.async_get_events = lambda *a, **k: []
ha.http.StaticPathConfig = MagicMock
ha.http.require_admin = lambda f: f
ha.frontend = _mod("homeassistant.components.frontend")
ha.frontend.DATA_PANELS = "frontend_panels"
ha.frontend.async_register_built_in_panel = lambda *a, **k: None
ha.frontend.async_remove_panel = lambda *a, **k: None
# Deliberate trade-off: voluptuous stubbed wholesale, so schema validation is
# partially off (cv.entity_id is identity); the semantic asserts below still
# exercise the pure-Python validation paths.
sys.modules["voluptuous"] = MagicMock()

try:
    import aiohttp  # noqa: F401
except ModuleNotFoundError:
    aiohttp = _mod("aiohttp")
    aiohttp.web = _mod("aiohttp.web")
    aiohttp.web.Request = MagicMock
    aiohttp.web.Response = MagicMock
    aiohttp.web.json_response = MagicMock()
    sys.modules["aiohttp.web"] = aiohttp.web
    sys.modules["aiohttp"] = aiohttp

# ---------------------------------------------------------------------------
# 1) Import every module of the integration (ImportError/NameError class).
# ---------------------------------------------------------------------------

failures = []
for name in [
    "const",
    "schema",
    "condition_engine",
    "decision_log",
    "triggers",
    "controller",
    "hub",
    "web",
    "config_flow",
    "switch",
    "binary_sensor",
    "__init__",
]:
    full = f"{PKG}.{name}"
    try:
        importlib.import_module(full)
    except Exception as err:  # noqa: BLE001 — report and continue
        failures.append(f"IMPORT {full}: {type(err).__name__}: {err}")

if failures:
    print("\n".join(failures))
    sys.exit(1)
print("[PASS] import chain: 12 modules import cleanly")

# ---------------------------------------------------------------------------
# 2) v2/v3→v7 store migration chain (pure functions).
# ---------------------------------------------------------------------------

from custom_components.sensor_switch_controller.hub import (  # noqa: E402
    _flatten_group_coverage,
    _migrate_controller_v2,
    _migrate_controller_v4,
    _migrate_controller_v7,
    _migrate_controller_v8,
    _strip_duration_coverage,
)
from custom_components.sensor_switch_controller.const import COND_DURATION  # noqa: E402

CID1 = "cond_" + "1" * 32
CID2 = "cond_" + "2" * 32
OID1 = "ssc_" + "3" * 32
TID1 = "trg_" + "4" * 32

cfg = {
    "name": "legacy",
    "conditions": [
        {
            "id": CID1,
            "type": "state",
            "entity_id": "sensor.a",
            "state": "on",
            "for": {"hours": 0, "minutes": 1, "seconds": 5},
        },
        {"id": CID2, "type": "time", "at": "07:30"},
    ],
    "outputs": [
        {
            "name": "out",
            "type": "switch",
            "entity_id": OID1,
            "on_conditions": [CID1],
            "off_conditions": [],
        }
    ],
    "sensors": [{"entity_id": "sensor.a"}],
    "triggers": [{"id": TID1, "type": "state"}],
}
import copy as _copy
_cfg_v2_snapshot = _copy.deepcopy(cfg)  # pre-migration snapshot for dispatch net
_migrate_controller_v2(cfg)
_migrate_controller_v4(cfg)
_strip_duration_coverage(cfg)
_flatten_group_coverage(cfg)
_migrate_controller_v7(cfg)  # the full hub chain, v2→7

durs = [c for c in cfg["conditions"] if c.get("type") == COND_DURATION]
assert len(durs) == 1, f"migration must split one duration node: {cfg['conditions']}"
dur = durs[0]
assert dur["start"] == CID1 and dur["seconds"] == 65, dur
assert "for" not in next(c for c in cfg["conditions"] if c["id"] == CID1)
assert dur["id"] in cfg["outputs"][0]["on_conditions"], cfg["outputs"]
assert CID1 not in cfg["outputs"][0]["on_conditions"]
time_cond = next(c for c in cfg["conditions"] if c["type"] == "time")
assert time_cond.get("after") == "07:30" and "at" not in time_cond, time_cond
# v4+strip+flatten: the wired output's chain collapses into the trigger's
# condition coverage; duration ids are stripped, the leaf (state-on) remains
cov = set(cfg["triggers"][0]["routes"]["conditions"])
assert CID1 in cov and dur["id"] not in cov, cfg["triggers"][0]["routes"]
assert "outputs" not in cfg["triggers"][0]["routes"]

# an output missing entity_id gets one pre-assigned so routes reach it (WHA-F-021)
cfg_bare = {
    "conditions": [],
    "outputs": [{"name": "bare", "type": "switch", "on_conditions": [], "off_conditions": []}],
    "triggers": [{"id": "trg_" + "9" * 32, "type": "state"}],
}
_migrate_controller_v2(cfg_bare)
_migrate_controller_v4(cfg_bare)
bare_id = cfg_bare["outputs"][0]["entity_id"]
assert isinstance(bare_id, str) and bare_id.startswith("ssc_") and len(bare_id) == 36, bare_id
assert cfg_bare["triggers"][0]["routes"] == {"conditions": []}, cfg_bare["triggers"]

# v3→v4 on its own: the ONLY source of new coverage is the wired outputs'
# chains — routes.conditions starts empty, exactly like real 0.6.x stores
grp_leaf = "cond_" + "e" * 32
dur_leaf = "cond_" + "f" * 32
grp = "cond_" + "a7" * 16
dur_id3 = "cond_" + "b7" * 16
cfg_v3 = {
    "conditions": [
        {"id": grp_leaf, "type": "state", "entity_id": "switch.c", "state": "on"},
        {"id": dur_leaf, "type": "state", "entity_id": "switch.d", "state": "on"},
        {"id": grp, "type": "or", "conditions": [grp_leaf, dur_id3]},
        {"id": dur_id3, "type": "duration", "seconds": 5, "start": dur_leaf, "abort": None},
    ],
    "outputs": [
        {"name": "o", "type": "switch", "entity_id": OID1,
         "on_conditions": [grp], "off_conditions": []},
    ],
    "triggers": [{"id": TID1, "type": "state",
                  "routes": {"outputs": [OID1], "conditions": []}}],
}
_migrate_controller_v4(cfg_v3)
got = set(cfg_v3["triggers"][0]["routes"]["conditions"])
assert got == {grp_leaf, dur_leaf, grp, dur_id3}, (
    f"v4 coverage must include the recursive chain: {got}"
)
assert "outputs" not in cfg_v3["triggers"][0]["routes"]



# migration dispatch smoke: the three-parameter signature must be callable
# the same way HA's Store baseline path does it (WHA-F-128: three params
# remove all dispatch doubt)
from custom_components.sensor_switch_controller.hub import _MigratingStore  # noqa: E402

store = _MigratingStore(MagicMock(), 3, "smoke")
migrated = asyncio.run(
    store._async_migrate_func(2, 1, {"controllers": {"ctrl_x": _cfg_v2_snapshot}})
)

got_cov = set(migrated["controllers"]["ctrl_x"]["triggers"][0]["routes"]["conditions"])
# deep-copied migration (F-063); duration ids drop out of the condition-id
# coverage (_strip_duration_coverage), filtered below by type.
# Each dispatch run mints fresh uuids — never compare ids across instances
# (WHA-F-205).
gate_types = {"and", "or", "not", COND_DURATION}
leaf_ids = {
    c["id"]
    for c in migrated["controllers"]["ctrl_x"]["conditions"]
    if c["type"] not in gate_types
}
assert got_cov == leaf_ids, got_cov
print("[PASS] migration v2/v3→v7: for→duration split, at→after, condition coverage")

# ---------------------------------------------------------------------------
# 3) Schema rules: trigger id preserved, routes validated, time.at rejected.
# ---------------------------------------------------------------------------

from custom_components.sensor_switch_controller.schema import (  # noqa: E402
    ControllerValidationError,
    _validate_condition,
    validate_controller,
    validate_trigger,
)

trg = {"id": TID1, "type": "state", "entity_id": "sensor.a", "routes": {"conditions": []}}
# migrated output must pass validate_controller as-is (WHA-F-119): the
# group-coverage flattener guarantees schema exclusivity
validate_controller(cfg)

# 0.7.2→0.7.3 store round-trip: a members+signal group (0.7.2 legal) must
# flatten to its leaf and pass validation (WHA-F-119/F-125/F-126)
g_id = "cond_" + "9" * 32
v5cfg = {
    "name": "072store",
    "conditions": [
        {"id": g_id, "type": "or", "conditions": [CID1]},
        {"id": CID1, "type": "state", "entity_id": "sensor.a", "state": "on"},
    ],
    "outputs": [
        {"name": "out", "type": "switch", "entity_id": OID1,
         "on_conditions": [g_id], "off_conditions": []},
    ],
    "triggers": [
        {"id": TID1, "type": "state", "entity_id": "sensor.a",
         "routes": {"conditions": [g_id]}}
    ],
}
_v5cfg_snapshot = _copy.deepcopy(v5cfg)  # pre-migration (WHA-F-169)
_strip_duration_coverage(v5cfg)
_flatten_group_coverage(v5cfg)
validated = validate_controller(v5cfg)
assert validated["triggers"][0]["routes"]["conditions"] == [CID1], (
    validated["triggers"][0]["routes"]
)

# the v5 chain must be reachable through the same dispatch (WHA-F-125's
# steps[5] regression net): a members+signal group flattens to its leaf
migrated5 = asyncio.run(
    store._async_migrate_func(5, 1, {"controllers": {"ctrl_x": _v5cfg_snapshot}})
)
v5cov = migrated5["controllers"]["ctrl_x"]["triggers"][0]["routes"]["conditions"]
assert v5cov == [CID1], v5cov
validate_controller(migrated5["controllers"]["ctrl_x"])
# 0.7.3: a group whose members are ALL duration gates flattens to EMPTY
# coverage (wired-to-nothing) — the only state passing the exclusivity
# backstop; must NOT re-embed the member-carrying group id (WHA-F-133)
g_dur = "cond_" + "bb" * 16
d_mem = "cond_" + "bc" * 16
cfg_durg = {
    "name": "durg",
    "conditions": [
        {"id": g_dur, "type": "or", "conditions": [d_mem]},
        {"id": d_mem, "type": "duration", "seconds": 5, "start": CID1, "abort": None},
        {"id": CID1, "type": "state", "entity_id": "sensor.a", "state": "on"},
    ],
    "outputs": [
        {"name": "out", "type": "switch", "entity_id": OID1,
         "on_conditions": [g_dur], "off_conditions": []},
    ],
    "triggers": [
        {"id": TID1, "type": "state", "entity_id": "sensor.a",
         "routes": {"conditions": [g_dur]}}
    ],
}
_strip_duration_coverage(cfg_durg)
_flatten_group_coverage(cfg_durg)
assert cfg_durg["triggers"][0]["routes"]["conditions"] == [], (
    cfg_durg["triggers"][0]["routes"]
)
validate_controller(cfg_durg)  # must pass, not invalid

# review R5-6: a 0.5.x `for` beyond the v6 duration cap (24:00:01+, legal
# back then — premise verified against the V0.5.0 schema) must be clamped
# by the v2 migration, not migrated into an invalid controller.
long_cfg = {
    "name": "long-for",
    "conditions": [
        {"id": "cond_" + "c" * 32, "type": "state", "entity_id": "sensor.a",
         "state": "on", "for": {"hours": 24, "minutes": 30, "seconds": 0}},
    ],
    "outputs": [],
    "triggers": [],
}
_migrate_controller_v2(long_cfg)
dur_long = next(c for c in long_cfg["conditions"] if c.get("type") == COND_DURATION)
assert dur_long["seconds"] == 86400, dur_long  # clamped to DURATION_MAX
validate_controller(long_cfg)  # must pass, not land invalid
cap_cfg = {
    "name": "cap-for",
    "conditions": [
        {"id": "cond_" + "d" * 32, "type": "state", "entity_id": "sensor.a",
         "state": "on", "for": {"hours": 24}},
    ],
    "outputs": [],
    "triggers": [],
}
_migrate_controller_v2(cap_cfg)
dur_cap = next(c for c in cap_cfg["conditions"] if c.get("type") == COND_DURATION)
assert dur_cap["seconds"] == 86400, dur_cap  # exactly at the cap stays
validate_controller(cap_cfg)
print("[PASS] migration clamps over-cap v2 for (review R5-6)")

kept = validate_trigger(trg)
assert kept["id"] == TID1, f"trigger id must be preserved: {kept['id']}"
# a duration id in the coverage is rejected (duration is not a signal origin)
dur_id2 = "cond_" + "cc" * 16
bad_dur = {
    "name": "bad-dur-route",
    "triggers": [
        {"id": TID1, "type": "state", "entity_id": "sensor.a",
         "routes": {"conditions": [dur_id2]}}
    ],
    "conditions": [
        {"id": dur_id2, "type": "duration", "seconds": 5,
         "start": "cond_" + "cd" * 16},
        {"id": "cond_" + "cd" * 16, "type": "state",
         "entity_id": "sensor.a", "state": "on"},
    ],
    "outputs": [
        {"name": "o", "type": "switch", "entity_id": OID1,
         "on_conditions": [], "off_conditions": [dur_id2]},
    ],
}
try:
    validate_controller(bad_dur)
    raise AssertionError("duration id in routes.conditions must be rejected")
except ControllerValidationError:
    pass

# 0.7.3 dual mode: an EMPTY group named by trigger coverage is a legal
# trigger-logic anchor (pass-through); an unreferenced empty group is not
empty_anchor = "cond_" + "ce" * 16
dual_cfg = {
    "name": "dual-mode",
    "triggers": [
        {"id": TID1, "type": "state", "entity_id": "sensor.a",
         "routes": {"conditions": [empty_anchor]}}
    ],
    "conditions": [
        {"id": empty_anchor, "type": "or", "conditions": []},
    ],
    "outputs": [
        {"name": "o", "type": "switch", "entity_id": OID1,
         "on_conditions": [empty_anchor], "off_conditions": []},
    ],
}
validated = validate_controller(dual_cfg)
assert validated["conditions"][0]["conditions"] == []

# 0.7.3 F-168: nested groups (a member-carrying group referenced by
# another group, no signal coverage) must PASS — the F-167/F-170 widening
# exists precisely to keep them legal
nested_cfg = {
    "name": "nested-groups",
    "triggers": [],
    "conditions": [
        {"id": "cond_" + "d1" * 16, "type": "state", "entity_id": "sensor.a", "state": "on"},
        {"id": "cond_" + "d2" * 16, "type": "or", "conditions": ["cond_" + "d1" * 16]},
        {"id": "cond_" + "d3" * 16, "type": "and", "conditions": ["cond_" + "d2" * 16]},
    ],
    "outputs": [
        {"name": "o", "type": "switch", "entity_id": OID1,
         "on_conditions": ["cond_" + "d3" * 16], "off_conditions": []},
    ],
}
validated = validate_controller(nested_cfg)
assert validated["conditions"][2]["conditions"] == ["cond_" + "d2" * 16]

# 0.7.3: a gate id in the coverage is legal ONLY for an empty group —
# members + signal coverage are mutually exclusive (WHA-F-115)
ok_gate = {
    "name": "gate-route",
    "triggers": [
        {"id": TID1, "type": "state", "entity_id": "sensor.a",
         "routes": {"conditions": ["cond_" + "d0" * 16]}}
    ],
    "conditions": [
        {"id": "cond_" + "d0" * 16, "type": "or", "conditions": []},
        {"id": CID1, "type": "state", "entity_id": "sensor.a", "state": "on"},
    ],
    "outputs": [
        {"name": "o", "type": "switch", "entity_id": OID1,
         "on_conditions": ["cond_" + "d0" * 16], "off_conditions": []},
    ],
}
assert validate_controller(ok_gate)["triggers"][0]["routes"]["conditions"] == [
    "cond_" + "d0" * 16
]
# members + signal coverage together is rejected (canvas exclusivity backstop)
bad_both = dict(ok_gate)
bad_both["conditions"] = [
    {"id": "cond_" + "d0" * 16, "type": "or", "conditions": [CID1]},
    {"id": CID1, "type": "state", "entity_id": "sensor.a", "state": "on"},
]
try:
    validate_controller(bad_both)
    raise AssertionError("members+signal group must be rejected")
except ControllerValidationError:
    pass
# an UNREFERENCED empty group stays rejected at graph level (0.7.3: a
# signal-covered empty group is the legal trigger-logic anchor)
bad_empty = {
    "name": "bad-empty-group",
    "triggers": [],
    "conditions": [
        {"id": "cond_" + "e0" * 16, "type": "and", "conditions": []},
    ],
    "outputs": [],
}
try:
    validate_controller(bad_empty)
    raise AssertionError("unreferenced empty group must stay rejected")
except ControllerValidationError:
    pass
for bad_routes in (
    {"outputs": [OID1], "conditions": []},
    {"outputs": [], "conditions": []},  # key presence is what's rejected
):
    try:
        validate_trigger({"type": "state", "routes": bad_routes})
        raise AssertionError(f"routes.outputs must be rejected: {bad_routes}")
    except ControllerValidationError:
        pass
fresh = validate_trigger(
    {"type": "state", "entity_id": "sensor.a", "routes": {"conditions": []}}
)
assert fresh["id"].startswith("trg_") and len(fresh["id"]) == 36, fresh["id"]

# 0.10.0: legacy full-sweep (routes absent) is rejected — every trigger must
# declare its signal coverage explicitly
try:
    validate_trigger({"type": "state", "entity_id": "sensor.a"})
    raise AssertionError("routes-absent (legacy full-sweep) trigger must be rejected")
except ControllerValidationError:
    pass
# pool listening is gone: entity_id is required (None / "" / [] all fail)
for bad_ent in (None, "", []):
    try:
        validate_trigger(
            {"type": "state", "routes": {"conditions": []}, "entity_id": bad_ent}
        )
        raise AssertionError(f"pool-listening trigger must be rejected: {bad_ent!r}")
    except ControllerValidationError:
        pass
# multi-entity: str | list[str] both accepted; list entries validated+deduped
multi = validate_trigger({
    "type": "state",
    "routes": {"conditions": []},
    "entity_id": ["switch.a", "sensor.b", "switch.a"],
})
assert multi["entity_id"] == ["switch.a", "sensor.b"], multi["entity_id"]
single = validate_trigger({
    "type": "state", "routes": {"conditions": []}, "entity_id": " switch.a ",
})
assert single["entity_id"] == "switch.a", single["entity_id"]
try:
    validate_trigger({"type": "state", "routes": {"conditions": []}, "entity_id": [42]})
    raise AssertionError("non-string entity list must be rejected")
except ControllerValidationError:
    pass

try:
    _validate_condition({"id": CID2, "type": "time", "at": "07:30"})
    raise AssertionError("time.at must be rejected")
except ControllerValidationError:
    pass

dur_cond = _validate_condition(
    {"id": "cond_" + "a" * 32, "type": "duration", "seconds": 60, "start": CID1}
)
assert dur_cond["start"] == CID1 and dur_cond["abort"] is None, dur_cond
try:
    _validate_condition({"id": "cond_" + "b" * 32, "type": "duration", "seconds": 60})
    raise AssertionError("duration without start must be rejected")
except ControllerValidationError:
    pass
deb_cond = _validate_condition(
    {"id": "cond_" + "c" * 32, "type": "debounce", "seconds": 30, "entity_id": "sensor.a"}
)
assert deb_cond["entity_id"] == "sensor.a"

# `for` is valid on every ordinary leaf — time conditions keep it now too
# (WHA-F-031); unpadded times normalize to canonical HH:MM (parse_time safety)
tm_cond = _validate_condition(
    {
        "id": CID2, "type": "time", "after": "7:30",
        "for": {"hours": 0, "minutes": 2, "seconds": 0},
    }
)
assert tm_cond["after"] == "07:30", tm_cond
assert tm_cond["for"] == {"hours": 0, "minutes": 2, "seconds": 0}, tm_cond

# routes referencing a missing condition must fail graph validation
bad = {
    "name": "bad-routes",
    "triggers": [
        {"id": TID1, "type": "state", "entity_id": "sensor.a",
         "routes": {"conditions": ["cond_" + "f" * 32]}}
    ],
    "conditions": [],
    "outputs": [
        {
            "name": "out",
            "type": "switch",
            "entity_id": OID1,
            "on_conditions": [],
            "off_conditions": [],
        }
    ],
}
try:
    validate_controller(bad)
    raise AssertionError("routes referencing unknown condition must be rejected")
except ControllerValidationError:
    pass
print("[PASS] schema: id preserved, routes checked, time.at rejected")

# ---------------------------------------------------------------------------
# 4) Directed evaluation end-to-end against stub HA.
# ---------------------------------------------------------------------------

from custom_components.sensor_switch_controller.controller import ControllerManager  # noqa: E402


class _Hass:
    def __init__(self):
        self.states = _States()
        self.data = {}
        from types import SimpleNamespace

        self.config = SimpleNamespace(config_dir="/tmp")

    def async_add_executor_job(self, fn, *a):
        fut = asyncio.get_event_loop().create_future()
        fn(*a)
        fut.set_result(None)
        return fut

    def async_create_task(self, coro):
        return asyncio.get_event_loop().create_task(coro)

    def async_create_background_task(self, coro, name=None):
        return asyncio.get_event_loop().create_task(coro)

    def async_call_later(self, hass_delay, delay, action):
        return lambda: None


class _States:
    def __init__(self):
        self._d = {
            "sensor.a": "16.7",
            "sensor.b": "已关机",
            "switch.c": "on",
            "switch.d": "off",
        }
        # per-entity attribute overrides (R1-7: capture typing reads
        # unit_of_measurement / state_class from the state attributes)
        self._attrs: dict = {}
        # entities "existed" since fixture construction: fixed last_changed
        # (a live clock here would make debounce never pass)
        self._born = _clock["utc"]
        self.last_changed = {}

    def get(self, eid):
        from types import SimpleNamespace

        v = self._d.get(eid)
        if v is None:
            return None
        lc = self.last_changed.get(eid, self._born)
        return SimpleNamespace(
            state=v, attributes=self._attrs.get(eid, {}), last_changed=lc
        )


class _Entity:
    def __init__(self, eid):
        self.entity_id = eid
        self._on = False

    @property
    def is_on(self):
        return self._on

    async def async_controller_turn_on(self):
        self._on = True
        return True

    async def async_controller_turn_off(self):
        self._on = False
        return True


def _log_cycles(controller_id="ctrl_smoke01"):
    import glob as _glob

    files = _glob.glob(f"/tmp/sensor_switch_controller_logs/{controller_id}/log_*.jsonl")
    recs = []
    for f in files:
        for line in open(f, encoding="utf-8").read().strip().splitlines():
            recs.append(json.loads(line))
    return recs


def _log_tail(recs, controller_id="ctrl_smoke01"):
    return _log_cycles(controller_id)[len(recs):]


# ---------------------------------------------------------------------------
# 2b) v6→v7 migration (0.10.0 causal explicitness): the materialized coverage
# equals the legacy full-sweep evaluation face; the materialized entity_id
# equals the original pool listening face.
# ---------------------------------------------------------------------------

v7_leaf_a = "cond_" + "a1" * 16   # state switch.c on (reached via the group)
v7_leaf_b = "cond_" + "b1" * 16   # numeric sensor.a above 5 (direct chain)
v7_dur_leaf = "cond_" + "c1" * 16
v7_dur = "cond_" + "d1" * 16      # duration gate driven via its start leaf
v7_set_leaf = "cond_" + "e1" * 16
v7_flag = "cond_" + "f1" * 16     # flag driven via its set leaf
v7_empty_g = "cond_" + "01" * 16  # empty-group chain (dead anchor)
v7_grp = "cond_" + "11" * 16      # member-carrying group (never signal-covered)
v7_o1 = "ssc_" + "2" * 32
v7_o2 = "ssc_" + "3" * 32
v7_o3 = "ssc_" + "4" * 32
v7_o4 = "ssc_" + "5" * 32
v7_trg = "trg_" + "6" * 32
v7_cfg = {
    "name": "v6-legacy",
    "conditions": [
        {"id": v7_leaf_a, "type": "state", "entity_id": "switch.c", "state": "on"},
        {"id": v7_leaf_b, "type": "numeric_state", "entity_id": "sensor.a", "above": 5},
        {"id": v7_dur_leaf, "type": "state", "entity_id": "switch.d", "state": "on"},
        {"id": v7_dur, "type": "duration", "seconds": 5, "start": v7_dur_leaf, "abort": None},
        {"id": v7_set_leaf, "type": "state", "entity_id": "switch.e", "state": "on"},
        {"id": v7_flag, "type": "flag", "set_conditions": [v7_set_leaf], "reset_conditions": []},
        {"id": v7_empty_g, "type": "or", "conditions": []},
        {"id": v7_grp, "type": "or", "conditions": [v7_leaf_a]},
    ],
    "outputs": [
        {"name": "o1", "type": "switch", "entity_id": v7_o1,
         "on_conditions": [v7_grp], "off_conditions": [v7_leaf_b]},
        {"name": "o2", "type": "switch", "entity_id": v7_o2,
         "on_conditions": [v7_dur], "off_conditions": []},
        {"name": "o3", "type": "binary_sensor", "entity_id": v7_o3,
         "on_conditions": [v7_flag], "off_conditions": []},
        {"name": "o4", "type": "switch", "entity_id": v7_o4,
         "on_conditions": [v7_empty_g], "off_conditions": []},
    ],
    "sensors": [{"entity_id": "switch.c"}, {"entity_id": "switch.d"},
                {"entity_id": "switch.e"}, {"entity_id": "sensor.a"}],
    # born legacy (no routes) + pool listener (no entity_id) — exactly the
    # two deprecated shapes the v7 migration exists to materialize
    "triggers": [{"id": v7_trg, "type": "state", "enabled": True}],
}
v7_snapshot = _copy.deepcopy(v7_cfg)
_migrate_controller_v7(v7_cfg)
# coverage: leaves only — group/duration/flag ids are excluded (schema rejects
# them as signal origins; an empty group would flip into a pass-through
# anchor and invert its verdict), yet every driving leaf stays reachable via
# group members, the duration start edge and the flag set edge
v7_cov = set(v7_cfg["triggers"][0]["routes"]["conditions"])
assert v7_cov == {v7_leaf_a, v7_leaf_b, v7_dur_leaf, v7_set_leaf}, v7_cov
# listening face: the whole pool, verbatim (pool order preserved)
assert v7_cfg["triggers"][0]["entity_id"] == [
    "switch.c", "switch.d", "switch.e", "sensor.a"
], v7_cfg["triggers"][0]["entity_id"]
validate_controller(v7_cfg)
# evaluation face = the legacy full sweep: every output whose chain can flip
# is woken by the single migrated trigger — o1 (group/state chains), o2
# (duration via its start leaf), o3 (flag via its set leaf); o4 (empty-group
# chain) is the documented hold-frozen exception (README 0.7.0 note ②). No
# group may flip into a signal anchor: verdicts must stay byte-identical.
mgr_v7 = ControllerManager(_Hass(), "ctrl_smoke12", v7_cfg)
assert mgr_v7.engine.signal_group_ids == set(), mgr_v7.engine.signal_group_ids
assert mgr_v7._trg_targets[v7_trg] == {v7_o1, v7_o2, v7_o3}, mgr_v7._trg_targets
# dispatch form: the Store chain v6→7 runs the same migration
migrated7 = asyncio.run(
    store._async_migrate_func(6, 1, {"controllers": {"ctrl_x": v7_snapshot}})
)
m7 = migrated7["controllers"]["ctrl_x"]
assert set(m7["triggers"][0]["routes"]["conditions"]) == v7_cov
assert m7["triggers"][0]["entity_id"] == [
    "switch.c", "switch.d", "switch.e", "sensor.a"
]
validate_controller(m7)
# R1#2: the (6,…) chain is 6→7→8 — the retirement strip must ride the REAL
# upgrade path too, not only the direct-call pin below; deleting
# _migrate_controller_v8 from this chain stays all-green otherwise
# (validate_controller itself accepts-and-drops the key).
assert "sensors" not in m7, m7
# pool-empty store: materializes to an empty list and lands invalid (visible
# fix-up) — the trigger was a never-firing registration error in v6 anyway
v7_empty_pool = {
    "name": "empty-pool",
    "conditions": [
        {"id": v7_leaf_a, "type": "state", "entity_id": "switch.c", "state": "on"}
    ],
    "outputs": [],
    "sensors": [],
    "triggers": [{"id": v7_trg, "type": "state", "enabled": True}],
}
_migrate_controller_v7(v7_empty_pool)
assert v7_empty_pool["triggers"][0]["entity_id"] == []
try:
    validate_controller(v7_empty_pool)
    raise AssertionError("pool-empty migrated store must land invalid")
except ControllerValidationError:
    pass
print("[PASS] v6→v7 migration: coverage=leaf set, entity_id=pool, faces preserved")

# WHA-F-309: a DISABLED pool listener on an empty pool is a legal v6 shape —
# the migration materializes entity_id=[] and the schema keeps the controller
# valid and the trigger inert (it never registers); ENABLED triggers still
# require entities.
v7_disabled_pool = {
    "name": "disabled-empty-pool",
    "conditions": [
        {"id": v7_leaf_a, "type": "state", "entity_id": "switch.c", "state": "on"}
    ],
    "outputs": [
        {"name": "o1", "type": "switch", "entity_id": v7_o1,
         "on_conditions": [v7_leaf_a], "off_conditions": []},
    ],
    "sensors": [],
    "triggers": [
        {"id": v7_trg, "type": "state", "enabled": False},
        {"id": "trg_" + "7" * 32, "type": "time", "every_seconds": 60,
         "routes": {"conditions": [v7_leaf_a]}},
    ],
}
_migrate_controller_v7(v7_disabled_pool)
assert v7_disabled_pool["triggers"][0]["entity_id"] == [], (
    v7_disabled_pool["triggers"][0]
)
v7_validated = validate_controller(v7_disabled_pool)
assert v7_validated["triggers"][0]["entity_id"] == [], v7_validated["triggers"][0]
assert v7_validated["triggers"][0]["routes"]["conditions"] == [v7_leaf_a], (
    v7_validated["triggers"][0]
)
try:
    validate_controller({
        **v7_disabled_pool,
        # F-318: the ENABLED half of the pin must carry routes — a routes-less
        # trigger fails on the (earlier) missing-routes check, which would
        # make this pin pass for the wrong reason
        "triggers": [{"id": v7_trg, "type": "state", "enabled": True,
                      "routes": {"conditions": [v7_leaf_a]}}],
    })
    raise AssertionError("ENABLED pool-empty trigger must stay rejected")
except ControllerValidationError:
    pass
print("[PASS] WHA-F-309: disabled pool listener on empty pool stays valid+inert")

# v7→v8 (0.12.0): the sensor pool is retired — the migration strips the
# stored "sensors" key (logged, not silent) while the v7-materialized
# trigger surfaces stay untouched.
v8_after_v7 = _copy.deepcopy(v7_disabled_pool)  # still carries "sensors": []
assert "sensors" in v8_after_v7
_migrate_controller_v8(v8_after_v7)
assert "sensors" not in v8_after_v7
assert v8_after_v7["triggers"][0]["entity_id"] == [], (
    v8_after_v7["triggers"][0]
)
_v8_validated = validate_controller(v8_after_v7)
assert "sensors" not in _v8_validated
# a payload still carrying the legacy key validates clean too (accept-drop)
assert "sensors" not in validate_controller(v7_disabled_pool)
# R1#2: dispatch the (7,…) chain too — the real 0.11.0 upgrade path. Its only
# regression net must not be the direct-call pin above; same shape as the
# steps[5] net (WHA-F-125).
migrated8 = asyncio.run(
    store._async_migrate_func(
        7, 1, {"controllers": {"ctrl_x": _copy.deepcopy(v7_disabled_pool)}}
    )
)
assert "sensors" not in migrated8["controllers"]["ctrl_x"], migrated8[
    "controllers"
]["ctrl_x"]
print("[PASS] v7→v8 migration: retired sensors key stripped, v7 surface kept")

# 0.12.0: external payloads carrying the retired "sensors" key are accepted
# and dropped with a warning (legacy export replay must not 400) — while a
# clean payload stays warning-free.
import logging as _put_logging

_put_records = []


class _PutCap(_put_logging.Handler):
    def emit(self, record):
        _put_records.append(record.getMessage())


_put_logger = _put_logging.getLogger(
    "custom_components.sensor_switch_controller.schema"
)
_put_handler = _PutCap(level=_put_logging.WARNING)
_put_logger.addHandler(_put_handler)
try:
    _replayed = validate_controller(v7_disabled_pool)  # carries "sensors": []
    assert "sensors" not in _replayed
    assert any("sensors" in m for m in _put_records), _put_records
    _put_records.clear()
    _clean = {
        "name": "put-clean",
        "triggers": [
            {"id": v7_trg, "type": "state", "enabled": False,
             "entity_id": ["switch.c"], "routes": {"conditions": [v7_leaf_a]}}
        ],
        "conditions": [
            {"id": v7_leaf_a, "type": "state", "entity_id": "switch.c",
             "state": "on"}
        ],
        "outputs": [],
    }
    validate_controller(_clean)
    # pin is sensors-specific: other static-hazard warnings may fire on this
    # shape, but the retired-key warning must not
    assert not any("sensors" in m for m in _put_records), _put_records
finally:
    _put_logger.removeHandler(_put_handler)
print(
    "[PASS] retired sensors key on external payloads: accepted, dropped, "
    "warned once per payload"
)

# WHA-F-310: pre-0.5 stores (no triggers key) — the mapped scan-interval
# trigger is born DIRECTED: routes materialize the same signal-leaf set the
# v7 migration uses, the shape passes validate_trigger, the id is derived
# deterministically from the config (stable across loads of a never-re-saved
# store), and the validated config round-trips (the PUT / whole-table-save /
# reload sequence that used to 400 and land the controller invalid).
pre05 = {
    "name": "pre05-legacy",
    "scan_interval": 30,
    "conditions": [
        {"id": v7_leaf_a, "type": "state", "entity_id": "switch.c", "state": "on"},
        {"id": v7_leaf_b, "type": "numeric_state", "entity_id": "sensor.a", "above": 5},
    ],
    "outputs": [
        {"name": "o1", "type": "switch", "entity_id": v7_o1,
         "on_conditions": [v7_leaf_a], "off_conditions": [v7_leaf_b]},
    ],
    "sensors": [{"entity_id": "switch.c"}, {"entity_id": "sensor.a"}],
    # no triggers key — the pre-0.5 shape
}
pre05_mapped = validate_controller(_copy.deepcopy(pre05))
pre05_trg = pre05_mapped["triggers"][0]
assert pre05_trg["type"] == "time" and pre05_trg["every_seconds"] == 30, pre05_trg
assert pre05_trg["routes"] == {"conditions": sorted([v7_leaf_a, v7_leaf_b])}, (
    pre05_trg["routes"]
)
pre05_id = pre05_trg["id"]
assert pre05_id.startswith("trg_") and len(pre05_id) == 36, pre05_id
assert validate_controller(_copy.deepcopy(pre05))["triggers"][0]["id"] == pre05_id, (
    "the mapped trigger id must be deterministic across loads"
)
pre05_rt = validate_controller(_copy.deepcopy(pre05_mapped))
assert pre05_rt["triggers"][0] == pre05_trg, pre05_rt["triggers"][0]
print("[PASS] WHA-F-310: pre-0.5 scan-interval mapping is born directed + stable")


async def main():
    cond_a = "cond_" + "a" * 32  # numeric_state above 20 (False for 16.7)
    cond_b = "cond_" + "b" * 32  # switch.c on (True)
    out_a = "ssc_" + "7" * 32
    out_b = "ssc_" + "8" * 32
    trg_wired = "trg_" + "1" * 32  # covers cond_b (feeds both outputs' on)
    trg_a_only = "trg_" + "4" * 32  # covers cond_a (out_a's off chain only)
    trg_empty = "trg_" + "2" * 32  # covers nothing

    config = {
        "name": "smoke",
        "enabled": True,
        "logging_enabled": True,
        "triggers": [
            {
                "id": trg_wired,
                "type": "state",
                "entity_id": "switch.c",
                "routes": {"conditions": [cond_b]},
            },
            {
                "id": trg_a_only,
                "type": "state",
                "entity_id": "switch.c",
                "routes": {"conditions": [cond_a]},
            },
            {"id": trg_empty, "type": "time", "every_seconds": 300, "routes": {"conditions": []}},
        ],
        "sensors": [
            {"entity_id": "sensor.a", "alias": ""},
            {"entity_id": "switch.c", "alias": ""},
        ],
        "conditions": [
            {"id": cond_a, "type": "numeric_state", "entity_id": "sensor.a", "above": 20},
            {"id": cond_b, "type": "state", "entity_id": "switch.c", "state": "on"},
        ],
        "outputs": [
            {
                "name": "out_a",
                "type": "switch",
                "entity_id": out_a,
                "on_conditions": [cond_b],
                "off_conditions": [cond_a],
                "manual_override": False,
            },
            {
                "name": "out_b",
                "type": "switch",
                "entity_id": out_b,
                "on_conditions": [cond_b],
                "off_conditions": [],
                "manual_override": False,
            },
        ],
    }

    mgr = ControllerManager(_Hass(), "ctrl_smoke01", config)
    await mgr.async_setup()
    ent_a = _Entity("switch.out_a")
    ent_b = _Entity("switch.out_b")
    mgr.register_entity(out_a, ent_a)
    mgr.register_entity(out_b, ent_b)
    mgr.async_entity_added(out_a)
    mgr.async_entity_added(out_b)
    while not mgr.last_cycle:  # init evaluation (targets=None → full sweep)
        await asyncio.sleep(0.01)

    # init runs a full sweep (targets=None via async_entity_added) —
    # both outputs are evaluated regardless of routes
    recs = _log_cycles()
    assert recs and recs[-1]["output"] == "out_b", recs[-3:]
    assert {r["output"] for r in recs[-2:]} == {"out_a", "out_b"}
    assert recs[-2]["decision"] == "on" and recs[-2]["applied"] is True
    assert recs[-1]["decision"] == "on" and recs[-1]["applied"] is True

    # a trigger covering cond_b wakes both outputs (both on-chains reach it)
    _Evt.LISTENERS.clear()
    mgr._on_trigger_fire(trg_wired, "wired")
    mgr._async_debounced_evaluate(None)
    await asyncio.sleep(0.05)
    recs_after = _log_cycles()
    new_recs = recs_after[len(recs):]
    assert len(new_recs) == 2, new_recs
    recs = recs_after

    # a trigger covering only cond_a (out_a's off chain) wakes out_a alone
    mgr._on_trigger_fire(trg_a_only, "a_only")
    mgr._async_debounced_evaluate(None)
    await asyncio.sleep(0.05)
    new_recs = _log_tail(recs)
    assert len(new_recs) == 1 and new_recs[0]["output"] == "out_a", new_recs
    recs = _log_cycles()

    # trigger wired to nothing fires → wakes nothing (no log records at all)
    mgr._on_trigger_fire(trg_empty, "empty")
    mgr._async_debounced_evaluate(None)
    await asyncio.sleep(0.05)
    assert len(_log_cycles()) == len(recs), "empty-routes trigger must wake nothing"

    # unknown trigger id → legacy full sweep (both outputs again)
    mgr._on_trigger_fire(None, "unknown")
    mgr._async_debounced_evaluate(None)
    await asyncio.sleep(0.05)
    tail = _log_cycles()[len(recs):]
    assert len(tail) == 2, f"legacy trigger must sweep everything: {tail}"
    recs = _log_cycles()

    # engine evaluation path still clean (cooldown False within cooldown of flip)
    met, det = await mgr.engine.evaluate_detailed([cond_a, cond_b], out_a)
    assert det[cond_a] is False and det[cond_b] is True, det

    # rerun must keep the swallowed run's directed scope (WHA-F-012): fire a
    # second wired trigger while an evaluation is in flight — the drain pass
    # must evaluate exactly out_b, never widen to a full sweep.
    recs = _log_cycles("ctrl_smoke01b")
    trg_wired_b = "trg_" + "3" * 32
    config["triggers"].append(
        {"id": trg_wired_b, "type": "time", "every_seconds": 600,
         "routes": {"conditions": []}}
    )
    mgr2x = ControllerManager(_Hass(), "ctrl_smoke01b", config)
    mgr2x.triggers = config["triggers"]
    mgr2x._build_route_index()
    for oid, ent in ((out_a, ent_a), (out_b, ent_b)):
        mgr2x.register_entity(oid, ent)
    # mid-run swallow, exercised deterministically through the backlog API:
    mgr2x._evaluating = True  # pretend a run owns the drain loop
    mgr2x._rerun_sources.add("wired_b")
    mgr2x._stack_targets({out_b})
    mgr2x._rerun_pending = True
    await mgr2x._async_drain()
    await asyncio.sleep(0.05)
    new_recs = _log_tail(recs, "ctrl_smoke01b")
    assert len(new_recs) == 1 and new_recs[0]["output"] == "out_b", new_recs
    # an empty directed backlog must evaluate NOTHING, not widen
    recs = _log_cycles("ctrl_smoke01b")
    mgr2x._evaluating = True
    mgr2x._stack_targets(set())
    mgr2x._rerun_pending = True
    await mgr2x._async_drain()
    await asyncio.sleep(0.05)
    assert _log_tail(recs, "ctrl_smoke01b") == [], "empty directed backlog must stay silent"
    # full-sweep backlog still widens (legacy semantics preserved)
    mgr2x._evaluating = True
    mgr2x._stack_targets(None)
    mgr2x._rerun_pending = True
    await mgr2x._async_drain()
    await asyncio.sleep(0.05)
    assert len(_log_tail(recs, "ctrl_smoke01b")) == 2, "full backlog must sweep both"
    mgr2x.async_unload()

    mgr.async_unload()
    print("[PASS] directed evaluation: routed / wired-to-nothing / legacy sweep")

    # recursive reachability in the ROUTER (not just the migration): a
    # trigger covering an OR group wakes the outputs reached via its
    # members' chains — group → member → output off-chain (WHA-F-082)
    ga = "cond_" + "b0" * 16
    gb = "cond_" + "c0" * 16
    grp2 = "cond_" + "d0" * 16
    out_c = "ssc_" + "9" * 32
    cfg3 = {
        "name": "recursive-routing",
        "enabled": True,
        "logging_enabled": True,
        "triggers": [
            # covers a group MEMBER: only add_chain's recursion (member →
            # group → output chain) can map ga to out_c
            {"id": "trg_" + "5" * 32, "type": "time", "every_seconds": 3600,
             "routes": {"conditions": [ga]}},
        ],
        "conditions": [
            {"id": ga, "type": "state", "entity_id": "switch.c", "state": "on"},
            {"id": gb, "type": "state", "entity_id": "switch.d", "state": "on"},
            {"id": grp2, "type": "or", "conditions": [ga, gb]},
        ],
        "outputs": [
            {"name": "out_c", "type": "switch", "entity_id": out_c,
             "on_conditions": [], "off_conditions": [grp2], "manual_override": False},
        ],
    }
    mgr3 = ControllerManager(_Hass(), "ctrl_smoke03", cfg3)
    await mgr3.async_setup()
    ent_c = _Entity("switch.out_c")
    mgr3.register_entity(out_c, ent_c)
    # the router must recurse member ga → group grp2 → out_c's off-chain
    assert mgr3._trg_targets["trg_" + "5" * 32] == {out_c}, mgr3._trg_targets
    assert mgr3._cond_to_outs[ga] == {out_c}, mgr3._cond_to_outs
    recs3 = _log_cycles("ctrl_smoke03")
    mgr3._on_trigger_fire("trg_" + "5" * 32, "grp")
    mgr3._async_debounced_evaluate(None)
    await asyncio.sleep(0.05)
    fired = _log_tail(recs3, "ctrl_smoke03")
    assert len(fired) == 1 and fired[0]["output"] == "out_c", fired
    mgr3.async_unload()
    print("[PASS] recursive routing: group coverage reaches chained outputs")

    # ------------------------------------------------------------------
    # 5) duration TON gate + debounce quiet gate.
    # ------------------------------------------------------------------
    cond_d = "cond_" + "d" * 32  # duration(start=switch.c on, 60s, abort=switch.d on)
    cond_ab = "cond_" + "e" * 32  # abort leaf: switch.d on
    cond_db = "cond_" + "f" * 32  # debounce: switch.c quiet ≥ 30s
    eng_cfg = {
        "name": "timers",
        "enabled": True,
        "logging_enabled": False,
        "triggers": [],
        "conditions": [
            {"id": cond_b, "type": "state", "entity_id": "switch.c", "state": "on"},
            {"id": cond_ab, "type": "state", "entity_id": "switch.d", "state": "on"},
            {
                "id": cond_d,
                "type": "duration",
                "seconds": 60,
                "start": cond_b,
                "abort": cond_ab,
            },
            {"id": cond_db, "type": "debounce", "seconds": 30, "entity_id": "switch.c"},
        ],
        "outputs": [],
    }
    mgr2 = ControllerManager(_Hass(), "ctrl_smoke02", eng_cfg)
    await mgr2.async_setup()
    eng = mgr2.engine

    # t0: start holds → ledger opens, gate still False
    assert await eng.evaluate_any([cond_d]) is False
    # abort is off → advancing 30s is not enough yet
    _advance_utc(30)
    assert await eng.evaluate_any([cond_d]) is False
    # 60s since the ledger opened → True
    _advance_utc(31)
    assert await eng.evaluate_any([cond_d]) is True
    # abort turns true → gate resets to False
    mgr2.hass.states._d["switch.d"] = "on"
    assert await eng.evaluate_any([cond_d]) is False
    # start still on, abort released again → ledger reopens from scratch
    mgr2.hass.states._d["switch.d"] = "off"
    assert await eng.evaluate_any([cond_d]) is False
    _advance_utc(10)
    assert await eng.evaluate_any([cond_d]) is False
    _advance_utc(51)
    assert await eng.evaluate_any([cond_d]) is True

    # debounce: pretend switch.c just changed, then goes quiet
    mgr2.hass.states.last_changed["switch.c"] = _clock["utc"]
    assert await eng.evaluate_any([cond_db]) is False, "just-changed entity must not pass"
    _advance_utc(31)
    assert await eng.evaluate_any([cond_db]) is True, "quiet ≥30s must pass"

    # directed wakeups: put the debounce quiet-point in the future
    # (last_changed = now-10s, gate 30s → expiry in ~20s, reachable out_a)
    mgr2.hass.states.last_changed["switch.c"] = _clock["utc"] - timedelta(seconds=10)
    reverse = {cond_d: {out_a}, cond_db: {out_a}, cond_b: {out_a}}
    pending = eng.next_wakeup(reverse)
    assert pending is not None, "pending timers must produce a wakeup"
    expiry, outs = pending
    assert outs == {out_a}, outs
    assert abs((expiry - _clock["utc"]).total_seconds() - 20) <= 1, expiry

    # same-instant wakeups must union their reachable outputs (WHA-F-022):
    # two identical debounce gates, routed to different outputs
    cond_db2 = "cond_" + "7" * 32
    eng._conditions[cond_db2] = {
        "id": cond_db2, "type": "debounce", "seconds": 30, "entity_id": "switch.c",
    }
    pending = eng.next_wakeup({cond_db: {out_a}, cond_db2: {out_b}})
    assert pending is not None
    expiry, outs = pending
    assert outs == {out_a, out_b}, f"same-instant wakeup must merge: {outs}"

    # cross-midnight window with a weekday filter: the verdict flips at the
    # membership boundary (next midnight of an active day), which doubles as
    # the entry point when today is idle (WHA-F-023 / WHA-F-028). Fixture
    # now = Tue 2026-10-06 10:00; mon-only 22:00–06:00 enters Mon 00:00.
    cond_xm = "cond_" + "8" * 32
    eng._conditions[cond_xm] = {
        "id": cond_xm, "type": "time",
        "after": "22:00", "before": "06:00", "weekdays": ["mon"],
    }
    pending = eng.next_wakeup({cond_xm: {out_a}})
    assert pending is not None
    expiry, outs = pending
    assert outs == {out_a} and expiry == datetime(2026, 10, 12, 0, 0, 0), (
        f"entry boundary must wake at Mon 00:00: {expiry}"
    )
    # second-level precision matches the evaluator's cross-midnight test
    # (WHA-F-029): 22:00:30 > 22:00:00 is a cross-midnight window
    eng._conditions[cond_xm] = {
        "id": cond_xm, "type": "time",
        "after": "22:00:30", "before": "22:00:00", "weekdays": ["mon"],
    }
    pending = eng.next_wakeup({cond_xm: {out_a}})
    assert pending is not None, "second-level cross-midnight must wake at midnight"

    # single-sided window with a weekday filter: after-only exits at the
    # day seam of the last active day (WHA-F-030). Jump to Mon 23:00.
    _clock["local"] = datetime(2026, 10, 12, 23, 0, 0)
    _clock["utc"] = datetime(2026, 10, 12, 15, 0, 0)
    eng._conditions[cond_xm] = {
        "id": cond_xm, "type": "time", "after": "22:00", "weekdays": ["mon"],
    }
    pending = eng.next_wakeup({cond_xm: {out_a}})
    assert pending is not None
    expiry, outs = pending
    assert expiry == datetime(2026, 10, 13, 0, 0, 0), (
        f"after-only window must wake at the day seam: {expiry}"
    )
    _clock["local"] = datetime(2026, 10, 6, 10, 0, 0)
    _clock["utc"] = datetime(2026, 10, 6, 2, 0, 0)

    # single-sided sun verdicts flip at local midnight, not at a sun event
    # (WHA-F-034): before=sunrise is false at 23:59 (past today's 06:00) and
    # true at 00:00 (before tomorrow's) — the seam must be offered.
    eng._conditions[cond_xm] = {
        "id": cond_xm, "type": "sun", "before": "sunrise",
    }
    pending = eng.next_wakeup({cond_xm: {out_a}})
    assert pending is not None
    expiry, outs = pending
    assert outs == {out_a} and expiry == datetime(2026, 10, 7, 0, 0, 0), (
        f"sun before-sunrise must wake at the midnight seam: {expiry}"
    )

    # double-sided cross-midnight sun window (sunset→sunrise night) must be
    # TRUE at night and FALSE at noon — HA sun semantics (WHA-F-037)
    eng._conditions[cond_xm] = {
        "id": cond_xm, "type": "sun", "after": "sunset", "before": "sunrise",
    }
    assert await eng.evaluate_any([cond_xm]) is False, "noon must be outside night"
    _clock["local"] = datetime(2026, 10, 6, 23, 0, 0)
    _clock["utc"] = datetime(2026, 10, 6, 15, 0, 0)
    assert await eng.evaluate_any([cond_xm]) is True, "23:00 is inside the night window"
    pending = eng.next_wakeup({cond_xm: {out_a}})
    assert pending is not None
    expiry, outs = pending
    assert outs == {out_a}, outs
    _clock["local"] = datetime(2026, 10, 6, 10, 0, 0)
    _clock["utc"] = datetime(2026, 10, 6, 2, 0, 0)

    # nothing pending when the reverse index maps nowhere
    assert eng.next_wakeup({}) is None

    mgr2.async_unload()
    print("[PASS] duration TON + debounce + directed wakeup")

    # 0.7.3 observe (WHA-F-201): read-only — verdicts computed, nothing
    # applied, no log written, no flip recorded
    mgr_obs = ControllerManager(_Hass(), "ctrl_smoke04", config)
    await mgr_obs.async_setup()
    ent_o = _Entity("switch.obs1")
    mgr_obs.register_entity(out_a, ent_o)
    import glob as _g

    def _obs_lines():
        files = _g.glob("/tmp/sensor_switch_controller_logs/ctrl_smoke04/log_*.jsonl")
        return sum(sum(1 for _ in open(f, encoding="utf-8")) for f in files)

    before = _obs_lines()
    obs = await mgr_obs.async_observe_conditions()
    # eng_cfg's condition ids: cond_b/CID_B-style ids reused from section 4
    assert set(obs["conditions"]) >= {cond_a, cond_b}, obs["conditions"]
    # 0.12.0: the sensor pool is retired — neither the observe response nor
    # new decision records carry the readings snapshot anymore.
    assert "readings" not in obs, obs.keys()
    rec, _det = await mgr_obs._async_evaluate_output(
        {"name": "obs-out", "type": "switch", "entity_id": out_a,
         "on_conditions": [], "off_conditions": []}
    )
    assert rec and "readings" not in rec, rec.keys()
    assert _obs_lines() == before, "observe must not write decision logs"
    assert ent_o.is_on is False, "observe must not apply actions"
    assert mgr_obs.last_flip_at(out_a) is None
    mgr_obs.async_unload()
    print("[PASS] observe: read-only, no flips, no log, no rearm")

    # ------------------------------------------------------------------
    # 0.9.0 flag (latch): schema rules, per-cycle stepping, reset-wins,
    # initial hold, disabled freeze, evaluate returns the latched verdict
    # ------------------------------------------------------------------
    from custom_components.sensor_switch_controller.schema import (
        ControllerValidationError as _CVE,
        validate_controller as _vc,
    )

    set_leaf = {"id": "cond_" + "1" * 32, "type": "state",
                "entity_id": "switch.c", "state": "on"}
    rst_leaf = {"id": "cond_" + "2" * 32, "type": "state",
                "entity_id": "switch.c", "state": "off"}
    dis_leaf = {"id": "cond_" + "3" * 32, "type": "state",
                "entity_id": "switch.c", "state": "on", "enabled": False}
    flag_a = "cond_" + "a" * 32   # set only
    flag_b = "cond_" + "b" * 32   # set + disabled(reset→always true): reset wins
    flag_c = "cond_" + "c" * 32   # initial=True, reset only (never met): holds
    flag_d = "cond_" + "d" * 32   # disabled flag: frozen
    flag_cfg = {
        "name": "flag-smoke", "enabled": True, "logging_enabled": False,
        "triggers": [],
        "conditions": [
            set_leaf, rst_leaf, dis_leaf,
            {"id": flag_a, "type": "flag",
             "set_conditions": [set_leaf["id"]],
             "reset_conditions": [rst_leaf["id"]]},
            {"id": flag_b, "type": "flag",
             "set_conditions": [set_leaf["id"]],
             "reset_conditions": [dis_leaf["id"]]},
            {"id": flag_c, "type": "flag", "initial": True,
             "set_conditions": [],
             "reset_conditions": [rst_leaf["id"]]},
            {"id": flag_d, "type": "flag",
             "set_conditions": [set_leaf["id"]],
             "reset_conditions": [], "enabled": False},
        ],
        "outputs": [
            {"name": "out-a", "type": "binary_sensor", "entity_id": "ssc_" + "1" * 32,
             "on_conditions": [flag_a], "off_conditions": []},
            {"name": "out-b", "type": "binary_sensor", "entity_id": "ssc_" + "2" * 32,
             "on_conditions": [flag_b], "off_conditions": []},
        ],
    }
    _vc(json.loads(json.dumps(flag_cfg)))  # valid flag config passes

    bad = json.loads(json.dumps(flag_cfg))
    bad["conditions"][3]["reset_conditions"] = [flag_b]  # flag→flag cascade
    try:
        _vc(bad)
        raise AssertionError("flag cascade must be rejected")
    except _CVE:
        pass
    empty = json.loads(json.dumps(flag_cfg))
    empty["conditions"][3]["set_conditions"] = []
    empty["conditions"][3]["reset_conditions"] = []
    try:
        _vc(empty)
        raise AssertionError("flag with no set AND no reset must be rejected")
    except _CVE:
        pass
    routes_bad = json.loads(json.dumps(flag_cfg))
    routes_bad["triggers"] = [{
        "id": "trg_" + "9" * 32, "type": "homeassistant", "enabled": True,
        "routes": {"conditions": [flag_a]},
    }]
    try:
        _vc(routes_bad)
        raise AssertionError("trigger route to a flag must be rejected")
    except _CVE:
        pass

    # review R5-4: cooldown / flag hidden behind a GROUP is the same dead
    # branch as a direct one — the graph check must walk the closure.
    grp_cd = "cond_" + "e" * 32
    bad_cd = json.loads(json.dumps(flag_cfg))
    bad_cd["conditions"].append(
        {"id": "cond_" + "f" * 32, "type": "cooldown", "seconds": 60}
    )
    bad_cd["conditions"].append(
        {"id": grp_cd, "type": "or", "conditions": ["cond_" + "f" * 32]}
    )
    bad_cd["conditions"][3]["set_conditions"] = [grp_cd]
    try:
        _vc(bad_cd)
        raise AssertionError("indirect cooldown via group must be rejected")
    except _CVE:
        pass
    grp_fl = "cond_" + "0" * 32
    bad_fl = json.loads(json.dumps(flag_cfg))
    bad_fl["conditions"].append(
        {"id": grp_fl, "type": "or", "conditions": [flag_b]}
    )
    bad_fl["conditions"][3]["set_conditions"] = [grp_fl]
    try:
        _vc(bad_fl)
        raise AssertionError("flag cascade via group must be rejected")
    except _CVE:
        pass

    # review R6-3: the closure narrows — a cooldown MIXED with usable
    # members keeps the group usable (a dead branch inside a live group is
    # not a dead controller), a disabled intermediate node is never
    # evaluated (engine returns satisfied without reaching members), and an
    # empty group wired into a flag input stays a legal anchor
    # (member_referenced now collects flag set/reset edges).
    mix_grp = "cond_" + "7" * 32
    mix_cfg = json.loads(json.dumps(flag_cfg))
    mix_cfg["conditions"].append(
        {"id": "cond_" + "f" * 32, "type": "cooldown", "seconds": 60}
    )
    mix_cfg["conditions"].append(
        {
            "id": mix_grp,
            "type": "or",
            "conditions": [set_leaf["id"], "cond_" + "f" * 32],
        }
    )
    mix_cfg["conditions"][3]["set_conditions"] = [mix_grp]
    _vc(mix_cfg)  # usable via the state member — must NOT be rejected

    dis_grp = "cond_" + "9" * 32
    dis_cfg = json.loads(json.dumps(flag_cfg))
    dis_cfg["conditions"].append(
        {"id": "cond_" + "f" * 32, "type": "cooldown", "seconds": 60}
    )
    dis_cfg["conditions"].append(
        {
            "id": dis_grp,
            "type": "or",
            "conditions": ["cond_" + "f" * 32],
            "enabled": False,
        }
    )
    dis_cfg["conditions"][3]["set_conditions"] = [dis_grp]
    _vc(dis_cfg)  # disabled group never evaluates its members

    anchor_grp = "cond_" + "8" * 32
    anchor_cfg = json.loads(json.dumps(flag_cfg))
    anchor_cfg["conditions"].append(
        {"id": anchor_grp, "type": "or", "conditions": []}
    )
    anchor_cfg["conditions"][3]["set_conditions"] = [anchor_grp]
    _vc(anchor_cfg)  # empty group referenced by a flag stays alive (R6-3)

    # review R7-2: constant dominance — the old "any unknown → unknown"
    # short-circuit let provably dead groups save silently (the flag then
    # never latched). Kleene merge rejects them again.
    and_grp = "cond_" + "6" * 32
    bad_and = json.loads(json.dumps(flag_cfg))
    bad_and["conditions"].append(
        {"id": "cond_" + "f" * 32, "type": "cooldown", "seconds": 60}
    )
    bad_and["conditions"].append(
        {
            "id": and_grp,
            "type": "and",
            "conditions": ["cond_" + "f" * 32, set_leaf["id"]],
        }
    )
    bad_and["conditions"][3]["set_conditions"] = [and_grp]
    try:
        _vc(bad_and)
        raise AssertionError("AND mixing a cooldown must be rejected (R7-2)")
    except _CVE:
        pass

    not_grp = "cond_" + "7" * 32
    bad_not = json.loads(json.dumps(flag_cfg))
    bad_not["conditions"].append(
        {
            "id": not_grp,
            "type": "not",
            "conditions": [dis_leaf["id"], set_leaf["id"]],
        }
    )
    bad_not["conditions"][3]["set_conditions"] = [not_grp]
    try:
        _vc(bad_not)
        raise AssertionError(
            "NOT with a provably-true member must be rejected (R7-2)"
        )
    except _CVE:
        pass

    # review R9-4 (WHA-F-307): the OR True-dominance arm needs its own pin —
    # set=[NOT(OR(disabled_leaf, live_leaf))]: OR reads True from the
    # disabled member → NOT reads False → rejected. If OR loses its
    # dominance (falls back to any-unknown), the verdict degrades to
    # None → NOT reads None → allowed — yet at runtime NOT(any([True, ...]))
    # is constant False: a silent dead branch would return.
    or_inner_grp = "cond_" + "5" * 32
    or_not_grp = "cond_" + "6" * 32
    bad_or_not = json.loads(json.dumps(flag_cfg))
    bad_or_not["conditions"].append(
        {
            "id": or_inner_grp,
            "type": "or",
            "conditions": [dis_leaf["id"], set_leaf["id"]],
        }
    )
    bad_or_not["conditions"].append(
        {"id": or_not_grp, "type": "not", "conditions": [or_inner_grp]}
    )
    bad_or_not["conditions"][3]["set_conditions"] = [or_not_grp]
    try:
        _vc(bad_or_not)
        raise AssertionError(
            "OR with a provably-true member must be rejected (R9-4)"
        )
    except _CVE:
        pass

    bad_dur_abort = json.loads(json.dumps(flag_cfg))
    bad_dur_abort["conditions"].append(
        {
            "id": "cond_" + "e" * 32,
            "type": "duration",
            "seconds": 5,
            "start": set_leaf["id"],
            "abort": dis_leaf["id"],
        }
    )
    bad_dur_abort["conditions"][3]["set_conditions"] = ["cond_" + "e" * 32]
    try:
        _vc(bad_dur_abort)
        raise AssertionError(
            "duration with a provably-satisfied abort must be rejected (R7-2)"
        )
    except _CVE:
        pass

    # review R6-1: a SELF-resetting latch (flag A → duration D → A's reset)
    # is legal — the flag step only READS the latched value (no cascade,
    # R5-4's blanket flag rejection was wrong here) and the flag edge is
    # not an evaluation edge (no cycle). Before the fix this config saved
    # fine on 0.8.x but the R5-4 closure and the cycle DFS rejected it,
    # landing upgraded stores in `invalid`. Also asserted end-to-end
    # through hub.async_load further below.
    latch_set = "cond_" + "4" * 32
    latch_flag = "cond_" + "5" * 32
    latch_dur = "cond_" + "6" * 32
    latch_cfg = {
        "name": "self-latch", "enabled": True, "logging_enabled": False,
        "triggers": [],
        "conditions": [
            {"id": latch_set, "type": "state",
             "entity_id": "switch.c", "state": "on"},
            {"id": latch_flag, "type": "flag",
             "set_conditions": [latch_set], "reset_conditions": [latch_dur]},
            {"id": latch_dur, "type": "duration",
             "seconds": 5, "start": latch_flag, "abort": None},
        ],
        "outputs": [
            {"name": "out-l", "type": "binary_sensor",
             "entity_id": "ssc_" + "3" * 32,
             "on_conditions": [latch_flag], "off_conditions": []},
        ],
    }
    _vc(json.loads(json.dumps(latch_cfg)))  # R6-1: must be saveable

    mgr_f = ControllerManager(_Hass(), "ctrl_smoke05", _vc(json.loads(json.dumps(flag_cfg))))
    await mgr_f.async_setup()
    ent_fa = _Entity("binary_sensor.fa")
    ent_fb = _Entity("binary_sensor.fb")
    mgr_f.register_entity("ssc_" + "1" * 32, ent_fa)
    mgr_f.register_entity("ssc_" + "2" * 32, ent_fb)
    eng_f = mgr_f.engine
    assert eng_f.flag_states() == {}, "flags start unstepped"

    flipped = await eng_f.step_flags()
    assert flipped == [flag_a], flipped  # flag_b: reset wins over set → stays off, no flip
    assert await eng_f.evaluate_any([flag_a]) is True, "set met → latch on"
    assert await eng_f.evaluate_any([flag_b]) is False, "reset (disabled member=always true) wins over set"
    assert await eng_f.evaluate_any([flag_c]) is True, "initial holds while reset unmet"
    assert await eng_f.step_flags() == [], "steady state → no flips"
    assert eng_f.flag_states() == {flag_a: True, flag_b: False, flag_c: True}, eng_f.flag_states()
    # flag_d (disabled) stays absent: frozen, never stepped
    assert flag_d not in eng_f.flag_states()

    # end-to-end: one evaluation cycle steps flags then applies outputs
    await mgr_f.async_evaluate_with_details()
    assert ent_fa.is_on is True, "output driven by latched flag_a"
    assert ent_fb.is_on is False, "output driven by latched flag_b"
    mgr_f.async_unload()
    print("[PASS] flag latch: stepping, reset-wins, initial, disabled freeze, cascade rules")

    # review R7-3: an empty NON-signal group wired into a flag branch is
    # saveable (canvas anchor) but evaluates False every cycle — the dead
    # branch must be visible once via warning, not a silent debug line.
    anchor_rt_grp = "cond_" + "8" * 32
    from custom_components.sensor_switch_controller.condition_engine import (
        ConditionEngine,
    )

    anchor_rt_cfg = json.loads(json.dumps(flag_cfg))
    anchor_rt_cfg["conditions"].append(
        {"id": anchor_rt_grp, "type": "or", "conditions": []}
    )
    anchor_rt_cfg["conditions"][3]["set_conditions"] = [anchor_rt_grp]
    eng_rt = ConditionEngine(
        _Hass(), _vc(json.loads(json.dumps(anchor_rt_cfg)))["conditions"]
    )
    import logging as _logging

    class _Cap(_logging.Handler):
        def __init__(self):
            super().__init__()
            self.records: list = []

        def emit(self, record):
            self.records.append(record)

    _cap = _Cap()
    _lg = _logging.getLogger(
        "custom_components.sensor_switch_controller.condition_engine"
    )
    _lg.addHandler(_cap)
    try:
        await eng_rt.step_flags()
        await eng_rt.step_flags()  # steady state: no second warning
    finally:
        _lg.removeHandler(_cap)
    warns = [r for r in _cap.records if "empty group" in r.getMessage()]
    assert len(warns) == 1, (
        "empty-group flag branch warns once: "
        + str([r.getMessage() for r in _cap.records])
    )
    assert anchor_rt_grp in warns[0].getMessage(), warns[0].getMessage()
    # once-only bookkeeping is per (flag, side, group)
    assert eng_rt._empty_branch_warned == {(flag_a, "set", anchor_rt_grp)}
    print("[PASS] empty-group flag branch warns once (R7-3)")

    # ------------------------------------------------------------------
    # review R9-2/R9-3 (WHA-F-305/F-306): the empty-branch warning must
    # follow the engine's abstract semantics — disabled groups read True,
    # NOT flips a constant False into a constant True, duration aborts are
    # harmless — and the wording must be member-level unless the whole
    # side is provably dead.
    # ------------------------------------------------------------------

    async def _capture_steps(eng, steps=2):
        """Run step_flags with the capture handler attached; return the
        'empty group' warning records."""
        _cap.records.clear()
        _lg.addHandler(_cap)
        try:
            for _ in range(steps):
                await eng.step_flags()
        finally:
            _lg.removeHandler(_cap)
        return [r for r in _cap.records if "empty group" in r.getMessage()]

    # R9-2 (1/2): a DISABLED empty group evaluates True every cycle — it
    # latches the flag on and must NOT be called a dead branch.
    dis_empty_grp = "cond_" + "9" * 32
    de_flag = "cond_" + "e" * 32
    dis_empty_cfg = {
        "name": "flag-dis-empty", "enabled": True, "logging_enabled": False,
        "triggers": [],
        "conditions": [
            {"id": dis_empty_grp, "type": "or", "conditions": [],
             "enabled": False},
            {"id": de_flag, "type": "flag",
             "set_conditions": [dis_empty_grp], "reset_conditions": []},
        ],
        "outputs": [
            {"name": "out-de", "type": "binary_sensor",
             "entity_id": "ssc_" + "9" * 32,
             "on_conditions": [de_flag], "off_conditions": []},
        ],
    }
    eng_de = ConditionEngine(
        _Hass(), _vc(json.loads(json.dumps(dis_empty_cfg)))["conditions"]
    )
    warns = await _capture_steps(eng_de)
    assert warns == [], [r.getMessage() for r in _cap.records]
    assert eng_de.flag_states().get(de_flag) is True, eng_de.flag_states()
    print("[PASS] disabled empty group latches on, no dead warning (R9-2)")

    # R9-2 (2/2): an empty group beside a live member is real but useless —
    # member-level wording, never "this branch can never fire".
    mix_empty_grp = "cond_" + "9" * 32
    mix_empty_cfg = json.loads(json.dumps(flag_cfg))
    mix_empty_cfg["conditions"].append(
        {"id": mix_empty_grp, "type": "or", "conditions": []}
    )
    mix_empty_cfg["conditions"][3]["set_conditions"] = [
        mix_empty_grp, set_leaf["id"],
    ]
    eng_me = ConditionEngine(
        _Hass(), _vc(json.loads(json.dumps(mix_empty_cfg)))["conditions"]
    )
    warns = await _capture_steps(eng_me)
    assert len(warns) == 1, [r.getMessage() for r in _cap.records]
    msg = warns[0].getMessage()
    assert mix_empty_grp in msg and "cannot contribute" in msg, msg
    assert "can never fire" not in msg, (
        "a side with a live member must not be called dead: " + msg
    )
    print(
        "[PASS] empty group beside a live member warns member-level (R9-2)"
    )

    # R9-3 (1/2): the walk follows evaluation edges — a group whose member
    # is an empty group is itself provably False → branch-level warning
    # naming the inner empty group.
    nest_outer = "cond_" + "9" * 32
    nest_inner = "cond_" + "0" * 32
    nest_cfg = json.loads(json.dumps(flag_cfg))
    nest_cfg["conditions"].append(
        {"id": nest_inner, "type": "or", "conditions": []}
    )
    nest_cfg["conditions"].append(
        {"id": nest_outer, "type": "or", "conditions": [nest_inner]}
    )
    nest_cfg["conditions"][3]["set_conditions"] = [nest_outer]
    eng_n = ConditionEngine(
        _Hass(), _vc(json.loads(json.dumps(nest_cfg)))["conditions"]
    )
    warns = await _capture_steps(eng_n)
    assert len(warns) == 1, [r.getMessage() for r in _cap.records]
    msg = warns[0].getMessage()
    assert nest_inner in msg and "can never fire" in msg, msg
    assert eng_n._empty_branch_warned == {(flag_a, "set", nest_inner)}, (
        eng_n._empty_branch_warned
    )
    assert eng_n.flag_states().get(flag_a) is False, eng_n.flag_states()
    print("[PASS] nested empty group dead branch warns once (R9-3)")

    # R9-3 (2/2): a duration whose start is an empty group is provably
    # False (start never holds) → branch-level warning through the
    # duration's start edge.
    dur_gate = "cond_" + "9" * 32
    dur_empty = "cond_" + "0" * 32
    dur_cfg = json.loads(json.dumps(flag_cfg))
    dur_cfg["conditions"].append(
        {"id": dur_empty, "type": "or", "conditions": []}
    )
    dur_cfg["conditions"].append(
        {"id": dur_gate, "type": "duration", "seconds": 5,
         "start": dur_empty, "abort": None}
    )
    dur_cfg["conditions"][3]["set_conditions"] = [dur_gate]
    eng_du = ConditionEngine(
        _Hass(), _vc(json.loads(json.dumps(dur_cfg)))["conditions"]
    )
    warns = await _capture_steps(eng_du)
    assert len(warns) == 1, [r.getMessage() for r in _cap.records]
    msg = warns[0].getMessage()
    assert dur_empty in msg and "can never fire" in msg, msg
    assert eng_du._empty_branch_warned == {(flag_a, "set", dur_empty)}, (
        eng_du._empty_branch_warned
    )
    assert eng_du.flag_states().get(flag_a) is False, eng_du.flag_states()
    print("[PASS] duration-start empty group dead branch warns once (R9-3)")

    # ------------------------------------------------------------------
    # 0.9.0 review R1-2: a directed evaluation must widen its targets with
    # the outputs reachable from flipped flags, or those outputs sit stale.
    # ------------------------------------------------------------------
    x_id = "cond_" + "e" * 32
    dir_flag = "cond_" + "f" * 32
    dir_cfg = {
        "name": "flag-directed", "enabled": True, "logging_enabled": False,
        "triggers": [{
            "id": "trg_" + "1" * 32, "type": "homeassistant", "enabled": True,
            "routes": {"conditions": [x_id]},
        }],
        "conditions": [
            {"id": x_id, "type": "state", "entity_id": "switch.c", "state": "on"},
            {"id": dir_flag, "type": "flag",
             "set_conditions": [x_id], "reset_conditions": []},
        ],
        "outputs": [
            {"name": "out-x", "type": "binary_sensor", "entity_id": "ssc_" + "a" * 32,
             "on_conditions": [x_id], "off_conditions": []},
            {"name": "out-flag", "type": "binary_sensor", "entity_id": "ssc_" + "b" * 32,
             "on_conditions": [dir_flag], "off_conditions": []},
        ],
    }
    mgr_d = ControllerManager(_Hass(), "ctrl_smoke06", _vc(json.loads(json.dumps(dir_cfg))))
    await mgr_d.async_setup()
    ent_x = _Entity("binary_sensor.dx")
    ent_g = _Entity("binary_sensor.dg")
    mgr_d.register_entity("ssc_" + "a" * 32, ent_x)
    mgr_d.register_entity("ssc_" + "b" * 32, ent_g)
    # Directed scope covers only out-x; the flag flips during this cycle and
    # must drag out-flag into the same evaluation (switch.c is "on" in the
    # stub states, so the set member fires and the flag latches on).
    await mgr_d._async_evaluate(None, ["directed"], {"ssc_" + "a" * 32})
    assert ent_x.is_on is True, "directed target evaluated"
    assert ent_g.is_on is True, (
        "flag flip widened the directed scope to its downstream output"
    )
    mgr_d.async_unload()
    print("[PASS] flag flip widens directed targets (review R1-2)")

    # ------------------------------------------------------------------
    # WHA-SNAPSHOT-121 (0.13.0) data nodes: snapshot capture / clear wins /
    # edge-no-refresh / disabled freeze / persistence + restart idempotence,
    # literal constant, compare six ops / string equality / snapshot ends on
    # both sides / type-mismatch + unavailable + missing-attribute WARNs,
    # schema guards, coverage expansion, no-self-wakeup pin, observe walk.
    # ------------------------------------------------------------------
    sn_gate = "cond_" + "ab" * 16   # capture gate: switch.c on
    sn_clr = "cond_" + "cd" * 16    # clear gate: switch.d on
    sn_num = "cond_" + "ef" * 16    # numeric snapshot of sensor.a
    sn_bad = "cond_" + "9a" * 16    # snapshot of an unreadable source
    sn_off = "cond_" + "bb" * 16    # disabled snapshot: frozen
    lit_25 = "cond_" + "1b" * 16    # literal number 25
    lit_on = "cond_" + "2c" * 16    # literal state "on"
    cmp_snap = "cond_" + "5f" * 16  # entity vs snapshot (b side)
    cmp_sa = "cond_" + "dd" * 16    # snapshot on the A side vs literal
    cmp_bad = "cond_" + "6a" * 16   # above on string ends (type mismatch)
    cmp_gone = "cond_" + "7c" * 16  # unavailable entity end
    cmp_attr = "cond_" + "cc" * 16  # missing attribute end
    dn_cfg = {
        "name": "data-nodes", "enabled": True, "logging_enabled": True,
        "triggers": [{"id": "trg_" + "e" * 32, "type": "state",
                      "entity_id": "switch.c",
                      "routes": {"conditions": [sn_gate]}}],
        "conditions": [
            {"id": sn_gate, "type": "state", "entity_id": "switch.c", "state": "on"},
            {"id": sn_clr, "type": "state", "entity_id": "switch.d", "state": "on"},
            {"id": sn_num, "type": "snapshot", "entity_id": "sensor.a",
             "capture": [sn_gate], "clear": [sn_clr]},
            {"id": sn_bad, "type": "snapshot", "entity_id": "sensor.nope",
             "capture": [sn_gate], "clear": []},
            {"id": sn_off, "type": "snapshot", "entity_id": "sensor.a",
             "capture": [sn_gate], "clear": [], "enabled": False},
            {"id": lit_25, "type": "literal", "value_type": "number", "value": 25},
            {"id": lit_on, "type": "literal", "value_type": "state", "value": "on"},
            {"id": cmp_snap, "type": "compare", "op": "above_equal",
             "a": {"kind": "entity", "entity_id": "sensor.a"},
             "b": {"kind": "snapshot", "cond": sn_num}},
            {"id": cmp_sa, "type": "compare", "op": "not_equal",
             "a": {"kind": "snapshot", "cond": sn_num},
             "b": {"kind": "literal", "cond": lit_25}},
            {"id": cmp_bad, "type": "compare", "op": "above",
             "a": {"kind": "entity", "entity_id": "switch.c"},
             "b": {"kind": "literal", "cond": lit_on}},
            {"id": cmp_gone, "type": "compare", "op": "equal",
             "a": {"kind": "entity", "entity_id": "sensor.gone"},
             "b": {"kind": "literal", "cond": lit_25}},
            {"id": cmp_attr, "type": "compare", "op": "equal",
             "a": {"kind": "entity", "entity_id": "sensor.a", "attribute": "unit"},
             "b": {"kind": "literal", "cond": lit_on}},
        ],
        "outputs": [
            {"name": "dn-out", "type": "switch", "entity_id": "ssc_" + "f" * 32,
             "on_conditions": [cmp_snap], "off_conditions": []},
        ],
    }
    dn_valid = _vc(json.loads(json.dumps(dn_cfg)))
    assert _vc(json.loads(json.dumps(dn_valid))) == dn_valid, (
        "data-node config round-trips byte-identically through validate"
    )
    # schema guards: each mutation must be REJECTED
    from custom_components.sensor_switch_controller.schema import (
        ControllerValidationError as _CVE,
    )
    for bad in (
        {**dn_cfg["conditions"][7], "op": "greater"},                     # op whitelist
        {**dn_cfg["conditions"][7], "b": {"kind": "literal", "cond": sn_gate}},  # literal end pointing at a state node
        {**dn_cfg["conditions"][2], "capture": ["cond_" + "0" * 32]},    # dangling capture ref
        {**dn_cfg["conditions"][2], "capture": [], "clear": []},         # no gate at all
        {"id": "cond_" + "8b" * 16, "type": "literal", "value_type": "number", "value": "x"},  # value/type mismatch
        {"id": "cond_" + "9b" * 16, "type": "literal", "value_type": "state", "value": 5},
        {"id": "cond_" + "bc" * 16, "type": "compare", "op": "equal",
         "a": {"kind": "flag", "cond": sn_gate}, "b": dn_cfg["conditions"][7]["b"]},  # kind whitelist
    ):
        cfg_bad = json.loads(json.dumps(dn_cfg))
        cfg_bad["conditions"] = [
            c for c in cfg_bad["conditions"] if c["id"] != bad["id"]
        ] + [bad]
        try:
            _vc(cfg_bad)
        except _CVE:
            pass
        else:
            raise AssertionError(f"schema accepted a bad data-node config: {bad}")
    print("[PASS] data-node schema: guards reject bad op/kind/refs/value typing")

    # R1-4: dead capture/clear gates are REJECTED — a cooldown inside the
    # snapshot step has no output context (permanently False); a mixed OR
    # GROUP keeps the gate alive via its live member and stays saveable
    cool_dn = "cond_" + "ac" * 16
    grp_dn = "cond_" + "ad" * 16
    dn_dead = json.loads(json.dumps(dn_cfg))
    dn_dead["conditions"].append({"id": cool_dn, "type": "cooldown", "seconds": 60})
    dn_dead["conditions"] = [
        c if c["id"] != sn_num else {**c, "capture": [cool_dn]}
        for c in dn_dead["conditions"]
    ]
    try:
        _vc(dn_dead)
    except _CVE:
        pass
    else:
        raise AssertionError("schema accepted a dead capture gate (cooldown)")
    dn_mixed = json.loads(json.dumps(dn_cfg))
    dn_mixed["conditions"].append({"id": cool_dn, "type": "cooldown", "seconds": 60})
    dn_mixed["conditions"].append(
        {"id": grp_dn, "type": "or", "conditions": [cool_dn, sn_gate]}
    )
    dn_mixed["conditions"] = [
        c if c["id"] != sn_num else {**c, "capture": [grp_dn]}
        for c in dn_mixed["conditions"]
    ]
    _vc(dn_mixed)  # mixed OR group: must NOT raise
    print("[PASS] data-node schema: dead capture gate rejected, mixed OR group saveable (R1-4)")

    # R2-3: disabled snapshots/flags are inert (their gates never step) —
    # dead gates on DISABLED nodes stay saveable as canvas anchors, the
    # F-336/F-346 clemency extended to the new faces
    dn_dis = json.loads(json.dumps(dn_dead))
    dn_dis["conditions"] = [
        c if c["id"] != sn_num else {**c, "enabled": False}
        for c in dn_dis["conditions"]
    ]
    _vc(dn_dis)  # disabled snapshot with a cooldown capture gate: NOT raised
    f_leaf = "cond_" + "bd" * 16
    f_cool = "cond_" + "be" * 16
    f_flag = "cond_" + "bf" * 16
    flag_dis = {
        "name": "flag-disabled", "enabled": True, "logging_enabled": False,
        "triggers": [{"id": "trg_" + "e" * 31 + "f", "type": "state",
                      "entity_id": "switch.c",
                      "routes": {"conditions": [f_leaf]}}],
        "conditions": [
            {"id": f_leaf, "type": "state", "entity_id": "switch.c",
             "state": "on"},
            {"id": f_cool, "type": "cooldown", "seconds": 60},
            {"id": f_flag, "type": "flag", "set_conditions": [f_cool],
             "reset_conditions": [], "initial": False, "enabled": False},
        ],
        "outputs": [],
    }
    _vc(flag_dis)  # disabled flag with a dead set branch: NOT raised
    # R2-4: DIRECT flag self-reference rejected (one step = one-tick
    # pulse, the R1-2 re-step = instant self-clear — semantics depend on
    # unrelated snapshot activity); the duration-based self-reset
    # (latch_cfg, R6-1) stays legal — it was validated above
    self_flag_cfg = json.loads(json.dumps(flag_dis))
    self_flag_cfg["conditions"] = [
        {"id": f_leaf, "type": "state", "entity_id": "switch.c", "state": "on"},
        {"id": f_flag, "type": "flag", "set_conditions": [f_leaf],
         "reset_conditions": [f_flag], "initial": False},
    ]
    try:
        _vc(self_flag_cfg)
    except _CVE:
        pass
    else:
        raise AssertionError("schema accepted a DIRECT flag self-reference (R2-4)")
    # R2-7: hand-written routes onto data nodes (snapshot/literal/compare)
    # are rejected — none carries a signal port, the next canvas save
    # would silently drop the wire
    for bad_target in (sn_num, lit_25, cmp_snap):
        dn_r = json.loads(json.dumps(dn_cfg))
        dn_r["triggers"][0]["routes"]["conditions"] = [bad_target]
        try:
            _vc(dn_r)
        except _CVE:
            pass
        else:
            raise AssertionError(
                f"schema accepted a route onto a data node (R2-7): {bad_target}"
            )
    print("[PASS] data-node schema: disabled-node clemency, self-ref & data-node routes rejected (R2-3/4/7)")

    # R5-3: DIRECT snapshot self-reference rejected (capture=[self] never
    # fires — the gate reads "a snapshot exists", permanently False while
    # empty; clear=[self] empties one cycle after capturing)
    for bad_key in ("capture", "clear"):
        dn_self_snap = json.loads(json.dumps(dn_cfg))
        dn_self_snap["conditions"] = [
            c if c["id"] != sn_num else {**c, bad_key: [sn_num]}
            for c in dn_self_snap["conditions"]
        ]
        try:
            _vc(dn_self_snap)
        except _CVE:
            pass
        else:
            raise AssertionError(
                f"schema accepted a snapshot self-reference ({bad_key}=[self], R5-3)"
            )
    # R5-4: an oversized int literal is rejected at the schema (the 400
    # face) — math.isfinite raises OverflowError on it, the plain check
    # would have surfaced as a web 500
    dn_huge = json.loads(json.dumps(dn_cfg))
    dn_huge["conditions"] = [
        c if c["id"] != lit_25 else {**c, "value": 10 ** 400}
        for c in dn_huge["conditions"]
    ]
    try:
        _vc(dn_huge)
    except _CVE:
        pass
    else:
        raise AssertionError("schema accepted an oversized int literal (R5-4)")
    # R5-2: literal+for is only PROVABLY true WITHOUT the for — a NOT over
    # a held literal stays saveable (the old True verdict rejected it) and
    # latches the flag on the FIRST cycle (literal False → NOT True)
    lf_leaf = "cond_" + "34" * 16   # literal number 5, for 60s
    lf_seed = "cond_" + "37" * 16   # plain state leaf (routes target —
                                    # data nodes are not route targets, R2-7)
    lf_not = "cond_" + "35" * 16    # NOT over it
    lf_flag = "cond_" + "36" * 16
    lf_cfg = {
        "name": "lit-for", "enabled": True, "logging_enabled": False,
        "triggers": [{"id": "trg_" + "3" * 31 + "1", "type": "state",
                      "entity_id": "switch.c",
                      "routes": {"conditions": [lf_seed]}}],
        "conditions": [
            {"id": lf_leaf, "type": "literal", "value_type": "number",
             "value": 5, "for": {"hours": 0, "minutes": 1, "seconds": 0}},
            {"id": lf_seed, "type": "state", "entity_id": "switch.c",
             "state": "on"},
            {"id": lf_not, "type": "not", "conditions": [lf_leaf]},
            {"id": lf_flag, "type": "flag", "set_conditions": [lf_not],
             "reset_conditions": [], "initial": False},
        ],
        "outputs": [],
    }
    lf_valid = _vc(json.loads(json.dumps(lf_cfg)))  # must NOT raise
    eng_lf = ConditionEngine(_Hass(), json.loads(json.dumps(lf_valid["conditions"])))
    assert await eng_lf.step_flags() == [lf_flag], (
        "NOT(literal+for) must latch the flag on the first cycle (R5-2)"
    )
    print("[PASS] data-node schema: self-snap rejected, oversized int 400-face, literal+for verdict (R5-2/3/4)")

    # R6-fix#1: INDIRECT snapshot self-reference rejected — the capture/
    # clear gate reaching the snapshot through the EVALUATION closure
    # (group members / duration start / compare a/b cond edges) reads its
    # own "a snapshot exists" verdict, permanently False while the store
    # is empty, so the node would never capture; the error must name the
    # indirect path. A group NOT reaching the snapshot stays saveable
    # (reachability is the criterion, not "any group")
    r6_grp = "cond_" + "41" * 16
    r6_dur = "cond_" + "42" * 16
    r6_cmp = "cond_" + "43" * 16
    r6_okg = "cond_" + "44" * 16
    for r6_arm, r6_gate in (
        ("group", {"id": r6_grp, "type": "and", "label": "自引组",
                   "conditions": [sn_num]}),
        ("duration", {"id": r6_dur, "type": "duration", "label": "自引持续",
                      "seconds": 30, "start": sn_num}),
        ("compare", {"id": r6_cmp, "type": "compare", "label": "自引求值",
                     "op": "above",
                     "a": {"kind": "snapshot", "cond": sn_num},
                     "b": {"kind": "literal", "cond": lit_25}}),
    ):
        r6_ind = json.loads(json.dumps(dn_cfg))
        r6_ind["conditions"].append(r6_gate)
        r6_ind["conditions"] = [
            c if c["id"] != sn_num
            else {**c, "capture": [r6_gate["id"]], "clear": []}
            for c in r6_ind["conditions"]
        ]
        try:
            _vc(r6_ind)
        except _CVE as r6_err:
            assert (
                r6_gate["label"] in str(r6_err) and "（本快照）" in str(r6_err)
            ), f"indirect self-ref message must name the path ({r6_arm}): {r6_err}"
        else:
            raise AssertionError(
                "schema accepted an indirect snapshot self-reference via "
                f"{r6_arm} (R6-fix#1)"
            )
    r6_ok = json.loads(json.dumps(dn_cfg))
    r6_ok["conditions"].append(
        {"id": r6_okg, "type": "and", "conditions": [sn_gate]}
    )
    r6_ok["conditions"] = [
        c if c["id"] != sn_num else {**c, "capture": [r6_okg], "clear": []}
        for c in r6_ok["conditions"]
    ]
    _vc(r6_ok)  # capture gate through a non-reaching group: must NOT raise
    print("[PASS] data-node schema: indirect snapshot self-ref rejected via group/duration/compare, non-reaching group saveable (R6-fix#1)")

    # engine faces via the manager (hub-seeded persistence path included)
    from custom_components.sensor_switch_controller.hub import ScannerHub as _SH
    hass_dn = _Hass()
    hass_dn.data["sensor_switch_controller"] = _SH(hass_dn)
    mgr_dn = ControllerManager(hass_dn, "ctrl_dnsmk1", json.loads(json.dumps(dn_valid)))
    await mgr_dn.async_setup()
    ent_dn = _Entity("switch.dnout")
    mgr_dn.register_entity("ssc_" + "f" * 32, ent_dn)
    eng_dn = mgr_dn.engine
    # no snapshot yet → False; the literal node is always satisfied
    assert await eng_dn.evaluate_any([sn_num]) is False
    assert await eng_dn.evaluate_any([lit_25]) is True
    assert await eng_dn.evaluate_any([cmp_sa]) is False  # snapshot absent → False
    # cycle 1: gate rises (memory prev is empty → counts as False→True) →
    # capture sensor.a = 16.7 as a FLOAT; the unreadable-source snapshot
    # captures nothing; the disabled snapshot is frozen
    ev1 = await eng_dn.step_snapshots()
    assert ev1 == {sn_num: {"event": "capture", "value": 16.7}}, ev1
    assert sn_bad not in ev1 and sn_off not in ev1
    assert await eng_dn.evaluate_any([sn_num]) is True
    assert await eng_dn.evaluate_any([sn_off]) is True  # disabled → satisfied
    assert await eng_dn.evaluate_any([cmp_sa]) is True  # 16.7 != 25
    # edge does NOT refresh: gate stays on, source moves → no recapture
    hass_dn.states._d["sensor.a"] = "99"
    assert await eng_dn.step_snapshots() == {}
    assert eng_dn.snapshots()[sn_num] == 16.7
    # clear wins over capture in the same cycle
    hass_dn.states._d["switch.d"] = "on"
    ev3 = await eng_dn.step_snapshots()
    assert ev3 == {sn_num: {"event": "clear"}}, ev3
    assert await eng_dn.evaluate_any([sn_num]) is False
    # gate must DROP before it can rise again (edge semantics)
    hass_dn.states._d["switch.d"] = "off"
    hass_dn.states._d["switch.c"] = "off"
    await eng_dn.step_snapshots()
    hass_dn.states._d["switch.c"] = "on"
    ev4 = await eng_dn.step_snapshots()
    assert ev4 == {sn_num: {"event": "capture", "value": 99.0}}, ev4
    assert await eng_dn.evaluate_any([cmp_snap]) is True  # 99 above_equal 99
    # WARN faces: type mismatch / unavailable entity / missing attribute —
    # visible once per key per window (F-323 reuse), never silent
    _capdn = _Cap()
    _lgdn = _logging.getLogger(
        "custom_components.sensor_switch_controller.condition_engine"
    )
    _lgdn.addHandler(_capdn)
    try:
        assert await eng_dn.evaluate_any([cmp_bad]) is False
        assert await eng_dn.evaluate_any([cmp_gone]) is False
        assert await eng_dn.evaluate_any([cmp_attr]) is False
        _msgs = [r.getMessage() for r in _capdn.records]
        assert any("compare type mismatch" in m for m in _msgs), _msgs
        assert any("compare input a (entity unreadable)" in m for m in _msgs), _msgs
        assert any("compare input a (attribute missing)" in m for m in _msgs), _msgs
        await eng_dn.evaluate_any([cmp_bad])  # rate limit: no second warn
        assert sum("compare type mismatch" in r.getMessage() for r in _capdn.records) == 1
    finally:
        _lgdn.removeHandler(_capdn)
    print("[PASS] data-node engine: edge capture, no-refresh, clear-wins, freeze, WARN faces")

    # R1-7: capture typing — attribute hint FIRST, float() fallback second,
    # non-finite numbers never land (isfinite gate, literal parity). A
    # hinted sensor with an unparseable reading WARNs (the sensor lies
    # about its own typing); an unhinted digit-shaped string still parses
    # (fallback), and NaN degrades to the state string.
    hass_t7 = _Hass()
    hass_t7.states._d["sensor.hint"] = "05"
    hass_t7.states._attrs["sensor.hint"] = {"unit_of_measurement": "°C"}
    hass_t7.states._d["sensor.txt"] = "05"
    hass_t7.states._d["sensor.lie"] = "on"
    hass_t7.states._attrs["sensor.lie"] = {"state_class": "measurement"}
    hass_t7.states._d["sensor.nan"] = "nan"
    t7_gate = "cond_" + "ae" * 16
    t7_ids = {
        "hint": "cond_" + "af" * 16,
        "txt": "cond_" + "ba" * 16,
        "lie": "cond_" + "bb" * 16,
        "nan": "cond_" + "bc" * 16,
    }
    t7_conds = [
        {"id": t7_gate, "type": "state", "entity_id": "switch.c", "state": "on"},
    ] + [
        {"id": t7_ids[k], "type": "snapshot", "entity_id": f"sensor.{k}",
         "capture": [t7_gate], "clear": []}
        for k in t7_ids
    ]
    eng_t7 = ConditionEngine(hass_t7, t7_conds)
    _cap7 = _Cap()
    _lgdn.addHandler(_cap7)
    try:
        ev_t7 = await eng_t7.step_snapshots()
    finally:
        _lgdn.removeHandler(_cap7)
    assert ev_t7[t7_ids["hint"]] == {"event": "capture", "value": 5.0}, ev_t7
    assert ev_t7[t7_ids["txt"]] == {"event": "capture", "value": 5.0}, ev_t7
    assert ev_t7[t7_ids["lie"]] == {"event": "capture", "value": "on"}, ev_t7
    assert ev_t7[t7_ids["nan"]] == {"event": "capture", "value": "nan"}, ev_t7
    assert sum(
        "numeric sensor with non-numeric reading" in r.getMessage()
        for r in _cap7.records
    ) == 1, [r.getMessage() for r in _cap7.records]
    print("[PASS] data-node typing: hint-first, parse fallback, NaN gate, lying-sensor WARN (R1-7)")

    # R2-2: a failed capture does NOT consume the edge — a transient
    # unavailable source at the rising moment retries every cycle while
    # the gate stays high, instead of pinning the snapshot empty for the
    # whole uptime
    hass_r2 = _Hass()
    hass_r2.states._d["sensor.a"] = "unavailable"
    eng_r2 = ConditionEngine(
        hass_r2,
        [
            {"id": t7_gate, "type": "state", "entity_id": "switch.c",
             "state": "on"},
            {"id": sn_num, "type": "snapshot", "entity_id": "sensor.a",
             "capture": [t7_gate], "clear": []},
        ],
    )
    ev_r2a = await eng_r2.step_snapshots()  # edge fires, source unreadable
    assert sn_num not in ev_r2a and sn_num not in eng_r2.snapshots()
    assert not eng_r2.snapshot_gates().get(sn_num), (
        "the failed capture must not consume the edge (R2-2)"
    )
    hass_r2.states._d["sensor.a"] = "16.7"  # source recovers, gate still high
    ev_r2b = await eng_r2.step_snapshots()
    assert ev_r2b == {sn_num: {"event": "capture", "value": 16.7}}, ev_r2b
    print("[PASS] data-node retry: failed capture keeps the edge alive (R2-2)")

    # R3-3: non-finite readings on the compare read path are STRING ends —
    # NaN no longer makes not_equal/equal comparisons lie and inf no longer
    # makes above-family always fire (the same isfinite gate capture and
    # the literal validation apply). Old behavior marked red: float("nan")
    # was a numeric end (mixed-kind False here), float("inf") above 25 was
    # True.
    r3f_snap = "cond_" + "fa" * 16
    r3f_lit = "cond_" + "fb" * 16   # literal state "nan"
    r3f_litn = "cond_" + "fc" * 16  # literal number 25
    r3f_eq = "cond_" + "fd" * 16    # snapshot "nan" equal literal "nan"
    r3f_ab = "cond_" + "fe" * 16    # entity "inf" above 25
    hass_r3f = _Hass()
    hass_r3f.states._d["sensor.inf"] = "inf"
    eng_r3f = ConditionEngine(
        hass_r3f,
        [
            {"id": r3f_snap, "type": "snapshot", "entity_id": "sensor.nan",
             "capture": [t7_gate], "clear": []},
            {"id": r3f_lit, "type": "literal", "value_type": "state",
             "value": "nan"},
            {"id": r3f_litn, "type": "literal", "value_type": "number",
             "value": 25},
            {"id": r3f_eq, "type": "compare", "op": "equal",
             "a": {"kind": "snapshot", "cond": r3f_snap},
             "b": {"kind": "literal", "cond": r3f_lit}},
            {"id": r3f_ab, "type": "compare", "op": "above",
             "a": {"kind": "entity", "entity_id": "sensor.inf"},
             "b": {"kind": "literal", "cond": r3f_litn}},
        ],
    )
    # captured as a state string (the R1-7 NaN gate keeps it out of float)
    eng_r3f._snapshot_values[r3f_snap] = "nan"
    assert await eng_r3f.evaluate_any([r3f_eq]) is True, (
        'string "nan" vs string "nan" must compare equal (R3-3)'
    )
    assert await eng_r3f.evaluate_any([r3f_ab]) is False, (
        'the "inf" reading is a string end — above against a number must '
        "be mixed-kind False, not always-true (R3-3)"
    )
    print("[PASS] data-node compare: NaN/inf readings are string ends (R3-3)")

    # R4-4: unsupported attribute TYPES (bool/list/…) are neither numbers
    # nor strings — visible False with one rate-limited WARN beats the
    # silent always-false equality they used to produce
    hass_r4 = _Hass()
    hass_r4.states._attrs["sensor.a"] = {"battery_charging": True}
    r4_eq = "cond_" + "ff" * 16
    eng_r4 = ConditionEngine(
        hass_r4,
        [
            {"id": lit_on, "type": "literal", "value_type": "state",
             "value": "on"},
            {"id": r4_eq, "type": "compare", "op": "equal",
             "a": {"kind": "entity", "entity_id": "sensor.a",
                   "attribute": "battery_charging"},
             "b": {"kind": "literal", "cond": lit_on}},
        ],
    )
    _cap4 = _Cap()
    _lgdn.addHandler(_cap4)
    try:
        assert await eng_r4.evaluate_any([r4_eq]) is False
        assert await eng_r4.evaluate_any([r4_eq]) is False  # rate limit: once
    finally:
        _lgdn.removeHandler(_cap4)
    assert sum(
        "compare input a (unsupported attribute type)" in r.getMessage()
        for r in _cap4.records
    ) == 1, [r.getMessage() for r in _cap4.records]
    print("[PASS] data-node compare: bool attribute end is visible False + WARN (R4-4)")

    # R5-4 engine face: an oversized int attribute parses to None (the
    # OverflowError from float() is caught) and reads as a STRING end —
    # no per-cycle exception logging, no fake numeric comparison
    hass_r5 = _Hass()
    hass_r5.states._attrs["sensor.a"] = {"gauge": 10 ** 400}
    r5_eq = "cond_" + "fe" * 16 + "0"
    eng_r5 = ConditionEngine(
        hass_r5,
        [
            {"id": lit_on, "type": "literal", "value_type": "state",
             "value": "on"},
            {"id": r5_eq, "type": "compare", "op": "not_equal",
             "a": {"kind": "entity", "entity_id": "sensor.a",
                   "attribute": "gauge"},
             "b": {"kind": "literal", "cond": lit_on}},
        ],
    )
    assert await eng_r5.evaluate_any([r5_eq]) is True, (
        "an oversized-int attribute is a string end: not_equal against a "
        "state literal compares the raw value (R5-4)"
    )
    print("[PASS] data-node compare: oversized-int attribute is a string end (R5-4)")

    # six numeric operators against one shared literal (reuse pin)
    six_ids = [f"cond_{i:032x}" for i in range(6)]
    six_ops = ("equal", "not_equal", "above", "below", "above_equal", "below_equal")
    lit25_cond = next(c for c in dn_valid["conditions"] if c["id"] == lit_25)
    liton_cond = next(c for c in dn_valid["conditions"] if c["id"] == lit_on)
    eng6 = ConditionEngine(
        _Hass(),
        [lit25_cond]
        + [
            {"id": six_ids[i], "type": "compare", "op": op,
             "a": {"kind": "entity", "entity_id": "sensor.a"},
             "b": {"kind": "literal", "cond": lit_25}}
            for i, op in enumerate(six_ops)
        ],
    )
    # 16.7 vs 25
    assert [await eng6.evaluate_any([cid]) for cid in six_ids] == [
        False, True, False, True, False, True]
    # 25.0 vs 25 (equal boundary through both >= variants)
    eng6.hass.states._d["sensor.a"] = "25.0"
    assert [await eng6.evaluate_any([cid]) for cid in six_ids] == [
        True, False, False, False, True, True]
    # string equality: state end vs state literal
    eng6s = ConditionEngine(
        _Hass(),
        [liton_cond, {"id": six_ids[0], "type": "compare", "op": "not_equal",
                      "a": {"kind": "entity", "entity_id": "switch.c"},
                      "b": {"kind": "literal", "cond": lit_on}}],
    )
    assert await eng6s.evaluate_any([six_ids[0]]) is False  # "on" == "on"
    print("[PASS] data-node compare: six numeric ops, shared literal, string equality")

    # manager cycle: capture event persists to the hub store AND lands in
    # the decision log; compare verdicts join conditions detail. R1-6: the
    # event record is purely structural (decision/value) — no hardcoded
    # copy in triggered_by (the panel localizes from decision)
    hass_dn.states._d["switch.c"] = "off"
    await eng_dn.step_snapshots()  # drop the gate outside the logged cycle
    recs_dn_before = _log_cycles("ctrl_dnsmk1")
    hass_dn.states._d["switch.c"] = "on"
    det_dn = await mgr_dn.async_evaluate_with_details()
    hub_dn = hass_dn.data["sensor_switch_controller"]
    assert hub_dn.snapshot_states.get("ctrl_dnsmk1", {}).get(sn_num) == {
        "entity_id": "sensor.a", "value": 99.0,
    }, (
        hub_dn.snapshot_states
    )
    # R1-3: the gate table persists with the latches (still-high gate)
    assert hub_dn.snapshot_gates.get("ctrl_dnsmk1", {}).get(sn_num) is True, (
        hub_dn.snapshot_gates
    )
    dn_recs = _log_tail(recs_dn_before, "ctrl_dnsmk1")
    assert any(
        r.get("decision") == "capture" and r.get("output") and r.get("value") == 99.0
        for r in dn_recs
    ), dn_recs
    assert all("triggered_by" not in r for r in dn_recs if r.get("decision") == "capture")
    assert det_dn["conditions"].get(cmp_snap) is True
    # observe walk: a/b and capture/clear references join the live view
    obs_dn = await mgr_dn.async_observe_conditions()
    assert {sn_gate, sn_num, cmp_snap} <= set(obs_dn["conditions"]), obs_dn
    mgr_dn.async_unload()
    print("[PASS] data-node manager: persistence, decision-log event, observe walk")

    # R1-2 + R1-8①: directed-cycle convergence and widening — a capture
    # event must (a) pull out-of-target downstream chains into THIS cycle
    # (R1-8①, mirrors the flag-widening pin) and (b) re-step the flags so
    # a flag whose set gate reads the FRESH snapshot latches within the
    # SAME cycle (R1-2 — without the re-step the flag would wait forever
    # for a second trigger that never comes; without the widening the
    # direct-snapshot output would sit stale).
    rt_gate = "cond_" + "cb" * 16   # capture gate leaf (switch.c on)
    rt_snap = "cond_" + "db" * 16   # snapshot of sensor.a
    rt_flag = "cond_" + "eb" * 16   # flag: set = [snapshot]
    rt_oA = "ssc_" + "1" * 32       # in-target output (chain = gate leaf)
    rt_oB = "ssc_" + "2" * 32       # downstream: on = [snapshot] (direct)
    rt_oC = "ssc_" + "3" * 32       # downstream: on = [flag] (needs re-step)
    rt_cfg = {
        "name": "rt-data", "enabled": True, "logging_enabled": False,
        "triggers": [{"id": "trg_" + "f" * 32, "type": "state",
                      "entity_id": "switch.c",
                      "routes": {"conditions": [rt_gate]}}],
        "conditions": [
            {"id": rt_gate, "type": "state", "entity_id": "switch.c", "state": "on"},
            {"id": rt_snap, "type": "snapshot", "entity_id": "sensor.a",
             "capture": [rt_gate], "clear": []},
            {"id": rt_flag, "type": "flag",
             "set_conditions": [rt_snap], "reset_conditions": [],
             "initial": False},
        ],
        "outputs": [
            {"name": "rtA", "type": "switch", "entity_id": rt_oA,
             "on_conditions": [rt_gate], "off_conditions": []},
            {"name": "rtB", "type": "switch", "entity_id": rt_oB,
             "on_conditions": [rt_snap], "off_conditions": []},
            {"name": "rtC", "type": "switch", "entity_id": rt_oC,
             "on_conditions": [rt_flag], "off_conditions": []},
        ],
    }
    hass_rt = _Hass()
    hass_rt.data["sensor_switch_controller"] = _SH(hass_rt)
    mgr_rt = ControllerManager(hass_rt, "ctrl_rtdn01", _vc(json.loads(json.dumps(rt_cfg))))
    await mgr_rt.async_setup()
    ent_rtA = _Entity("switch.rta")
    ent_rtB = _Entity("switch.rtb")
    ent_rtC = _Entity("switch.rtc")
    mgr_rt.register_entity(rt_oA, ent_rtA)
    mgr_rt.register_entity(rt_oB, ent_rtB)
    mgr_rt.register_entity(rt_oC, ent_rtC)
    await mgr_rt._async_evaluate(None, ["directed"], {rt_oA})
    assert ent_rtA.is_on is True, "in-target output evaluated"
    assert ent_rtB.is_on is True, (
        "capture event must widen the directed scope to the "
        "direct-snapshot output within the same cycle (R1-8)"
    )
    assert ent_rtC.is_on is True, (
        "capture event must re-step the flags so a flag reading the fresh "
        "snapshot latches in the SAME cycle (R1-2)"
    )
    assert (
        hass_rt.data["sensor_switch_controller"].flag_states.get(
            "ctrl_rtdn01", {}
        ).get(rt_flag)
        is True
    ), "the re-stepped flag verdict must persist"
    mgr_rt.async_unload()
    print("[PASS] data-node directed cycle: same-cycle widening + flag re-step (R1-2/R1-8)")

    # R3-1: a pure compare(entity) chain carries no legal signal wire (no
    # signal port, no route target) — its wakeup rides the entity coverage
    # join: a trigger LISTENING to the entity a compare reads pulls that
    # compare's outputs into the dispatch targets. Without the join this
    # exact shape (the UI default) froze the output after startup.
    r3_lit = "cond_" + "da" * 16   # literal number 5
    r3_cmp = "cond_" + "ea" * 16   # compare: sensor.a above 5 (on chain)
    r3_cmp2 = "cond_" + "eb" * 16  # compare: sensor.a below 5 (off chain —
                                   # an unmet on chain only HOLDS, turning
                                   # the output off needs the off chain)
    r3_cmp3 = "cond_" + "ec" * 16  # compare: sensor.b above 5 (out2 chain —
                                   # the JOIN-KEY discriminant: nobody
                                   # listens to sensor.b, so out2 must stay
                                   # out of the a-trigger's targets)
    r3_trg = "trg_" + "1" * 31 + "2"
    r3_trg2 = "trg_" + "1" * 31 + "3"  # DISABLED, listens to sensor.b —
                                       # enabled semantics must survive the
                                       # join (R4-5)
    r3_out = "ssc_" + "9" * 31 + "8"
    r3_out2 = "ssc_" + "9" * 31 + "7"
    r3_cfg = {
        "name": "r3-join", "enabled": True, "logging_enabled": False,
        "triggers": [
            {"id": r3_trg, "type": "state", "entity_id": "sensor.a",
             "routes": {"conditions": []}},
            {"id": r3_trg2, "type": "state", "entity_id": "sensor.b",
             "enabled": False, "routes": {"conditions": []}},
        ],
        "conditions": [
            {"id": r3_lit, "type": "literal", "value_type": "number",
             "value": 5},
            {"id": r3_cmp, "type": "compare", "op": "above",
             "a": {"kind": "entity", "entity_id": "sensor.a"},
             "b": {"kind": "literal", "cond": r3_lit}},
            {"id": r3_cmp2, "type": "compare", "op": "below",
             "a": {"kind": "entity", "entity_id": "sensor.a"},
             "b": {"kind": "literal", "cond": r3_lit}},
            {"id": r3_cmp3, "type": "compare", "op": "above",
             "a": {"kind": "entity", "entity_id": "sensor.b"},
             "b": {"kind": "literal", "cond": r3_lit}},
        ],
        "outputs": [
            {"name": "r3", "type": "switch", "entity_id": r3_out,
             "on_conditions": [r3_cmp], "off_conditions": [r3_cmp2]},
            {"name": "r3b", "type": "switch", "entity_id": r3_out2,
             "on_conditions": [r3_cmp3], "off_conditions": []},
        ],
    }
    hass_r3 = _Hass()
    mgr_r3 = ControllerManager(
        hass_r3, "ctrl_r3join1", _vc(json.loads(json.dumps(r3_cfg)))
    )
    await mgr_r3.async_setup()
    # build face: the empty-coverage trigger's targets grew via the join —
    # and ONLY via the listened entity: out2 (compare on sensor.b, nobody
    # listening) must stay out (a wrong join key unioning every compare
    # entity end yields {r3_out, r3_out2} here — red)
    assert mgr_r3._trg_targets[r3_trg] == {r3_out}, mgr_r3._trg_targets
    # the DISABLED trigger listening to sensor.b gets no join credit
    # (it never registers a listener — enabled semantics survive R4-5)
    assert mgr_r3._trg_targets[r3_trg2] == set(), mgr_r3._trg_targets
    ent_r3 = _Entity("switch.r3out")
    mgr_r3.register_entity(r3_out, ent_r3)
    # startup evaluation: 16.7 above 5 → on
    await mgr_r3._async_evaluate(None, ["init"], None)
    assert ent_r3.is_on is True
    # the entity drops below the threshold and the trigger fires: the
    # output must re-evaluate OFF in the same dispatch (frozen = red)
    hass_r3.states._d["sensor.a"] = "3"
    mgr_r3._on_trigger_fire(r3_trg, "sensor.a")
    mgr_r3._async_debounced_evaluate(None)
    await asyncio.sleep(0.05)
    assert ent_r3.is_on is False, (
        "compare entity ends must wake via the listening trigger (R3-1)"
    )
    mgr_r3.async_unload()
    print("[PASS] data-node wakeup: compare entity ends covered by the entity join (R3-1)")

    # R4-1 schema face: the calendar heartbeat arm credits the entity join
    # — "calendar + compare(entity end an enabled state trigger listens
    # to)" must NOT warn heartbeat-only; without a listener it still does
    r4c_cal = "cond_" + "31" * 16
    r4c_cmp = "cond_" + "32" * 16
    r4c_lit = "cond_" + "33" * 16
    r4c_out = "ssc_" + "9" * 31 + "6"

    def _cal_cfg(listen):
        return {
            "name": "r4-cal", "enabled": True, "logging_enabled": False,
            "triggers": [{
                "id": "trg_" + "2" * 31 + ("1" if listen else "0"),
                "type": "state",
                "entity_id": "sensor.a" if listen else "sensor.z",
                "routes": {"conditions": [r4c_cal]},
            }],
            "conditions": [
                {"id": r4c_cal, "type": "calendar",
                 "entity_id": "calendar.x", "hours": 24.0},
                {"id": r4c_lit, "type": "literal", "value_type": "number",
                 "value": 5},
                {"id": r4c_cmp, "type": "compare", "op": "above",
                 "a": {"kind": "entity", "entity_id": "sensor.a"},
                 "b": {"kind": "literal", "cond": r4c_lit}},
            ],
            "outputs": [
                {"name": "r4c", "type": "switch", "entity_id": r4c_out,
                 "on_conditions": [r4c_cal, r4c_cmp], "off_conditions": []},
            ],
        }

    _scap4 = _Cap()
    _slg4 = _logging.getLogger(
        "custom_components.sensor_switch_controller.schema"
    )
    _slg4.addHandler(_scap4)
    try:
        _vc(_cal_cfg(True))  # listened: no heartbeat-only warning
        assert not any(
            "依赖日历条件" in r.getMessage() for r in _scap4.records
        ), [r.getMessage() for r in _scap4.records]
        _scap4.records.clear()
        _vc(_cal_cfg(False))  # nobody listens: the warning stays
        assert any(
            "依赖日历条件" in r.getMessage() for r in _scap4.records
        ), [r.getMessage() for r in _scap4.records]
    finally:
        _slg4.removeHandler(_scap4)
    print("[PASS] data-node hazards: calendar arm credits the entity join (R4-1)")

    # R5-6 (closes the data-node hazard ledger item): an output whose live
    # chain has NO wakeup source at all warns once — the pure
    # compare(entity, nobody listening) shape froze silently before
    def _frozen_cfg(listen):
        return {
            "name": "r5-frozen", "enabled": True, "logging_enabled": False,
            "triggers": [{
                "id": "trg_" + "4" * 31 + ("1" if listen else "0"),
                "type": "state",
                "entity_id": "sensor.a" if listen else "sensor.z",
                # empty coverage on purpose — a pure compare chain has no
                # legal route target (R2-7); the ONLY wakeup is the join
                "routes": {"conditions": []},
            }],
            "conditions": [
                {"id": r4c_lit, "type": "literal", "value_type": "number",
                 "value": 5},
                {"id": r4c_cmp, "type": "compare", "op": "above",
                 "a": {"kind": "entity", "entity_id": "sensor.a"},
                 "b": {"kind": "literal", "cond": r4c_lit}},
            ],
            "outputs": [
                {"name": "r5f", "type": "switch", "entity_id": r4c_out,
                 "on_conditions": [r4c_cmp], "off_conditions": []},
            ],
        }

    _scap5 = _Cap()
    _slg5 = _logging.getLogger(
        "custom_components.sensor_switch_controller.schema"
    )
    _slg5.addHandler(_scap5)
    try:
        _vc(_frozen_cfg(True))  # listened: join covers it → no warning
        assert not any(
            "没有任何可唤醒源" in r.getMessage() for r in _scap5.records
        ), [r.getMessage() for r in _scap5.records]
        _scap5.records.clear()
        _vc(_frozen_cfg(False))  # nobody listens → the freeze warns
        assert any(
            "没有任何可唤醒源" in r.getMessage() for r in _scap5.records
        ), [r.getMessage() for r in _scap5.records]
    finally:
        _slg5.removeHandler(_scap5)
    print("[PASS] data-node hazards: no-wakeup-source freeze warns, join silences it (R5-6)")

    # R6-fix#2: snapshot capture/clear gates are NOT wakeup sources —
    # next_wakeup never schedules a snapshot wakeup and step_snapshots
    # runs only INSIDE an existing cycle, so a snapshot-only chain with
    # no trigger freezes exactly like a flag-only chain: face ⑤ must warn
    # (R5-6's snapshot branch swallowed it), and an enabled trigger whose
    # signal covers the capture gate's leaf silences it again
    r6_sn = "cond_" + "45" * 16
    r6_drv = "cond_" + "46" * 16
    r6_snout = "ssc_" + "a" * 31 + "1"

    def _snap_only_cfg(listen):
        return {
            "name": "r6-snap-only", "enabled": True,
            "logging_enabled": False,
            "triggers": (
                [{"id": "trg_" + "5" * 31 + "1", "type": "state",
                  "entity_id": "sensor.b",
                  "routes": {"conditions": [r6_drv]}}]
                if listen
                else []
            ),
            "conditions": [
                {"id": r6_drv, "type": "state", "entity_id": "sensor.b",
                 "state": "on"},
                {"id": r6_sn, "type": "snapshot", "entity_id": "sensor.a",
                 "capture": [r6_drv], "clear": []},
            ],
            "outputs": [
                {"name": "r6sn", "type": "switch", "entity_id": r6_snout,
                 "on_conditions": [r6_sn], "off_conditions": []},
            ],
        }

    _scap6 = _Cap()
    _slg6 = _logging.getLogger(
        "custom_components.sensor_switch_controller.schema"
    )
    _slg6.addHandler(_scap6)
    try:
        _vc(_snap_only_cfg(False))  # snapshot-only, zero triggers → warns
        assert any(
            "没有任何可唤醒源" in r.getMessage() for r in _scap6.records
        ), [r.getMessage() for r in _scap6.records]
        _scap6.records.clear()
        _vc(_snap_only_cfg(True))  # live trigger covers the capture leaf
        assert not any(
            "没有任何可唤醒源" in r.getMessage() for r in _scap6.records
        ), [r.getMessage() for r in _scap6.records]
    finally:
        _slg6.removeHandler(_scap6)
    print("[PASS] data-node hazards: snapshot-only chain warns without a trigger, capture-leaf coverage silences it (R6-fix#2)")

    # R6-fix#3: the entity join does NOT filter disabled compares — the
    # runtime routing index (controller._build_route_index) lends targets
    # for every compare with a matching entity end, enabled or not, so a
    # disabled compare behind a listening trigger must NOT raise the
    # no-wakeup-source (face ⑤) or calendar heartbeat-only (face ②)
    # warnings; with the listener gone both faces fire again
    r6_dcal = "cond_" + "47" * 16
    r6_dlit = "cond_" + "48" * 16
    r6_dcmp = "cond_" + "49" * 16
    r6_dout = "ssc_" + "b" * 31 + "2"

    def _dis_cmp_cfg(listen, with_cal):
        chain = [
            {"id": r6_dlit, "type": "literal",
             "value_type": "number", "value": 5},
            {"id": r6_dcmp, "type": "compare", "op": "above",
             "a": {"kind": "entity", "entity_id": "sensor.a"},
             "b": {"kind": "literal", "cond": r6_dlit},
             "enabled": False},
        ]
        # the ENABLED literal sits DIRECTLY on the output chain: a disabled
        # compare prunes its own edges from the live set (respect_enabled),
        # so face ⑤ would see an empty live chain and skip entirely
        on_chain = [r6_dcmp, r6_dlit]
        if with_cal:
            chain.insert(0, {"id": r6_dcal, "type": "calendar",
                             "entity_id": "calendar.x", "hours": 24.0})
            on_chain = [r6_dcal] + on_chain
        return {
            "name": "r6-dis-cmp", "enabled": True,
            "logging_enabled": False,
            "triggers": [{
                "id": "trg_" + "6" * 31 + "1",
                "type": "state",
                "entity_id": "sensor.a",
                "enabled": listen,
                "routes": {"conditions": []},
            }],
            "conditions": chain,
            "outputs": [
                {"name": "r6d", "type": "switch", "entity_id": r6_dout,
                 "on_conditions": on_chain, "off_conditions": []},
            ],
        }

    _scap7 = _Cap()
    _slg7 = _logging.getLogger(
        "custom_components.sensor_switch_controller.schema"
    )
    _slg7.addHandler(_scap7)
    try:
        # face ⑤ arm: chain = disabled compare + literal
        _vc(_dis_cmp_cfg(True, False))  # join credits the DISABLED compare
        assert not any(
            "没有任何可唤醒源" in r.getMessage() for r in _scap7.records
        ), [r.getMessage() for r in _scap7.records]
        _scap7.records.clear()
        _vc(_dis_cmp_cfg(False, False))  # nobody listens → freeze warns
        assert any(
            "没有任何可唤醒源" in r.getMessage() for r in _scap7.records
        ), [r.getMessage() for r in _scap7.records]
        _scap7.records.clear()
        # face ② arm: same chain + a calendar gate
        _vc(_dis_cmp_cfg(True, True))  # join silences heartbeat-only
        assert not any(
            "依赖日历条件" in r.getMessage() for r in _scap7.records
        ), [r.getMessage() for r in _scap7.records]
        _scap7.records.clear()
        _vc(_dis_cmp_cfg(False, True))  # nobody listens → heartbeat warns
        assert any(
            "依赖日历条件" in r.getMessage() for r in _scap7.records
        ), [r.getMessage() for r in _scap7.records]
    finally:
        _slg7.removeHandler(_scap7)
    print("[PASS] data-node hazards: disabled compare credited by the entity join, faces ②/⑤ align with runtime (R6-fix#3)")

    # hub store: three tables in one payload; pre-0.13 payloads (no
    # snapshots key) load silently; bool-poisoned values drop loudly
    class _SnapStore:
        """Recording flag-store stand-in with an injectable load_result
        (the module-level _Store stub is a no-op; this pin observes the
        payloads and the reload faces)."""

        def __init__(self):
            self.saved = []
            self.load_result = {"controllers": {}}

        async def async_load(self):
            return self.load_result

        async def async_save(self, data):
            self.saved.append(data)

        def async_delay_save(self, data_func, delay=0):
            self.saved.append(data_func())

    hub_p13 = _SH(_Hass())
    hub_p13._flag_store = _SnapStore()
    await hub_p13.async_load_flag_states()
    await hub_p13.async_save_snapshots(
        "ctrl_ab12cd34", {sn_num: 16.7, "k": "on"}, {sn_num: True}
    )
    payload13 = hub_p13._flag_store.saved[-1]
    # 0.14.0: the fifth runtime table (stateful) rides every save
    assert set(payload13) == {
        "flags", "last_flip", "snapshots", "snapshot_gates", "stateful",
    }, payload13
    assert payload13["snapshot_gates"] == {"ctrl_ab12cd34": {sn_num: True}}
    hub_p13._flag_store.load_result = payload13
    await hub_p13.async_load_flag_states()
    assert hub_p13.snapshot_states == {"ctrl_ab12cd34": {sn_num: 16.7, "k": "on"}}
    assert hub_p13.snapshot_gates == {"ctrl_ab12cd34": {sn_num: True}}
    hub_old13 = _SH(_Hass())
    hub_old13._flag_store = _SnapStore()
    hub_old13._flag_store.load_result = {
        "flags": {"ctrl_ab12cd34": {sn_num: True}}, "last_flip": {}}
    await hub_old13.async_load_flag_states()
    assert hub_old13.snapshot_states == {}, hub_old13.snapshot_states
    assert hub_old13.snapshot_gates == {}, hub_old13.snapshot_gates
    hub_bad13 = _SH(_Hass())
    hub_bad13._flag_store = _SnapStore()
    hub_bad13._flag_store.load_result = {
        "flags": {}, "last_flip": {},
        "snapshots": {"ctrl_ab12cd34": {"cond_x": True, "cond_y": 5}}}
    await hub_bad13.async_load_flag_states()
    assert hub_bad13.snapshot_states == {"ctrl_ab12cd34": {"cond_y": 5}}
    # R1-5: an explicit null is PRESENT-but-unusable — it must warn, not
    # silently wipe the latches (capture the hub logger for the check)
    import logging as _hub_lg

    class _HubCap(_hub_lg.Handler):
        def __init__(self):
            super().__init__()
            self.records: list = []

        def emit(self, record):
            self.records.append(record.getMessage())

    _hub_cap = _HubCap()
    _hub_logger = _hub_lg.getLogger(
        "custom_components.sensor_switch_controller.hub"
    )
    _hub_logger.addHandler(_hub_cap)
    try:
        hub_null13 = _SH(_Hass())
        hub_null13._flag_store = _SnapStore()
        hub_null13._flag_store.load_result = {
            "flags": {}, "last_flip": {}, "snapshots": None, "snapshot_gates": None}
        await hub_null13.async_load_flag_states()
        assert hub_null13.snapshot_states == {}
        assert sum("'snapshots' payload is not an object" in m for m in _hub_cap.records) == 1, (
            _hub_cap.records
        )
        assert sum("'snapshot_gates' payload is not an object" in m for m in _hub_cap.records) == 1
        _hub_cap.records.clear()
        hub_nullf = _SH(_Hass())
        hub_nullf._flag_store = _SnapStore()
        hub_nullf._flag_store.load_result = {
            "flags": {}, "last_flip": None}
        await hub_nullf.async_load_flag_states()
        assert sum("'last_flip' payload is not an object" in m for m in _hub_cap.records) == 1, (
            "explicit last_flip null must warn too (R1-5 family)",
            _hub_cap.records,
        )
    finally:
        _hub_logger.removeHandler(_hub_cap)
    # R2-6 shaped-value round-trip: the {entity_id, value} form persists
    # and reloads verbatim (a bare legacy scalar also survives)
    await hub_p13.async_save_snapshots(
        "ctrl_cc56aa78",
        {sn_num: {"entity_id": "sensor.a", "value": 3.5}, "k": "on"},
        {},
    )
    payload_typed = hub_p13._flag_store.saved[-1]
    hub_p13._flag_store.load_result = payload_typed
    await hub_p13.async_load_flag_states()
    assert hub_p13.snapshot_states["ctrl_cc56aa78"] == {
        sn_num: {"entity_id": "sensor.a", "value": 3.5}, "k": "on",
    }, hub_p13.snapshot_states
    # R1-3 + R1-8② + R2-6: a manager rebuilt on a SEEDED hub reads the
    # latched values AND gate verdicts — a still-high gate with a changed
    # source must NOT overwrite the latch; a latch whose recorded ORIGIN
    # no longer matches the config is dropped loudly instead
    def _seeded_hub(states, gates):
        h = _Hass()
        hub = _SH(h)
        h.data["sensor_switch_controller"] = hub
        hub.snapshot_states["ctrl_dnsmk2"] = states
        hub.snapshot_gates["ctrl_dnsmk2"] = gates
        return h

    _hub_cap.records.clear()
    _ctrl_logger = _hub_lg.getLogger(
        "custom_components.sensor_switch_controller.controller"
    )
    _ctrl_logger.addHandler(_hub_cap)
    try:
        # origin mismatch (R2-6): captured from sensor.OLD, config reads sensor.a
        hass_stale = _seeded_hub(
            {sn_num: {"entity_id": "sensor.old", "value": 9.9}}, {sn_num: True}
        )
        mgr_stale = ControllerManager(
            hass_stale, "ctrl_dnsmk2", json.loads(json.dumps(dn_valid))
        )
        assert sn_num not in mgr_stale.engine.snapshots(), (
            "a stale-origin latch must be dropped on rebuild (R2-6)"
        )
        assert any("captured from 'sensor.old'" in m for m in _hub_cap.records), (
            _hub_cap.records
        )
        # R5-1: the stale latch's gate seed re-arms (forced False) and the
        # hub tables drop the stale entry — the next true cycle captures
        # the NEW source even while the gate stays high (the old behavior
        # kept prev=True and never re-captured)
        assert mgr_stale.engine.snapshot_gates().get(sn_num) is False, (
            "a dropped latch must re-arm its edge detector (R5-1)"
        )
        hub_stale = hass_stale.data["sensor_switch_controller"]
        assert sn_num not in hub_stale.snapshot_states.get("ctrl_dnsmk2", {}), (
            "the hub table must drop the stale latch entry (R5-1)"
        )
        assert hub_stale.snapshot_gates["ctrl_dnsmk2"][sn_num] is False
        ev_stale = await mgr_stale.engine.step_snapshots()
        # switch.c is on (gate high) AND prev was forced False → capture
        assert ev_stale == {sn_num: {"event": "capture", "value": 16.7}}, (
            ev_stale
        )
        mgr_stale.async_unload()
        _hub_cap.records.clear()
    finally:
        _ctrl_logger.removeHandler(_hub_cap)
    # origin match: the latch seeds the engine and a still-high gate does
    # not re-capture even though the source has MOVED
    hass_seed = _seeded_hub(
        {sn_num: {"entity_id": "sensor.a", "value": 9.9}}, {sn_num: True}
    )
    hass_seed.states._d["sensor.a"] = "42"  # source has MOVED since capture
    mgr_seed = ControllerManager(
        hass_seed, "ctrl_dnsmk2", json.loads(json.dumps(dn_valid))
    )
    assert mgr_seed.engine.snapshots()[sn_num] == 9.9, (
        "hub latches must seed the rebuilt engine (R1-8)"
    )
    ev_seed = await mgr_seed.engine.step_snapshots()
    # gate is high (switch.c on) AND seeded prev=True → no rising edge →
    # the latched 9.9 survives the reload; a fresh (unseeded) engine would
    # have overwritten it with 42.0
    assert ev_seed == {}, ev_seed
    assert mgr_seed.engine.snapshots()[sn_num] == 9.9
    mgr_seed.async_unload()
    # R2-1: a STALE gate seed (stored True, the gate has since dropped)
    # must not swallow the next rising edge — the eventless drop persists
    # through the manager cycle and the following rise captures
    hass_drop = _seeded_hub(
        {sn_num: {"entity_id": "sensor.a", "value": 9.9}}, {sn_num: True}
    )
    hass_drop.states._d["switch.c"] = "off"  # gate is LOW right now
    mgr_drop = ControllerManager(
        hass_drop, "ctrl_dnsmk2", json.loads(json.dumps(dn_valid))
    )
    await mgr_drop._async_evaluate(None, ["drop"], None)
    # no capture/clear fired (values untouched), but the gate table moved
    # True→False and must reach the hub (memory IS the rebuild seed)
    assert mgr_drop.engine.snapshot_gates()[sn_num] is False
    hub_drop = hass_drop.data["sensor_switch_controller"]
    assert hub_drop.snapshot_gates["ctrl_dnsmk2"][sn_num] is False, (
        "eventless gate drop must sync to the hub (R2-1)"
    )
    hass_drop.states._d["sensor.a"] = "42"
    hass_drop.states._d["switch.c"] = "on"  # gate rises again
    recs_drop_before = _log_cycles("ctrl_dnsmk2")
    await mgr_drop._async_evaluate(None, ["rise"], None)
    assert hub_drop.snapshot_states["ctrl_dnsmk2"][sn_num]["value"] == 42.0, (
        "the rising edge after the stale-True window must capture (R2-1)"
    )
    dn_drop_recs = _log_tail(recs_drop_before, "ctrl_dnsmk2")
    assert any(r.get("decision") == "capture" for r in dn_drop_recs), dn_drop_recs
    mgr_drop.async_unload()
    # legacy degrade (no gate table): first true cycle captures once —
    # idempotent while the source is unchanged, the documented fallback
    eng_rs = ConditionEngine(
        _Hass(),
        json.loads(json.dumps(dn_valid["conditions"])),
        snapshot_values={sn_num: 16.7},
    )
    ev_rs = await eng_rs.step_snapshots()  # no gate seed → edge → recapture
    assert ev_rs == {sn_num: {"event": "capture", "value": 16.7}}, ev_rs
    print("[PASS] data-node hub: 4-table payload, legacy/null tolerance, gate-seed rebuild, R2-1/R2-6 pins")

    # coverage expansion: the compare b-side snapshot node and its capture
    # chain join the materialized coverage set (schema face)
    from custom_components.sensor_switch_controller.schema import (
        _covered_condition_ids as _cov,
    )
    cov_dn = _cov(
        dn_valid["conditions"], dn_valid["outputs"], ["ssc_" + "f" * 32]
    )
    assert {sn_gate, sn_num, cmp_snap} <= cov_dn, cov_dn
    # no self-wakeup: pure data nodes carry no timed edge — dependency
    # entities must be declared on triggers explicitly (0.12.0 semantics)
    eng_wake = ConditionEngine(_Hass(), json.loads(json.dumps(dn_valid["conditions"])))
    assert eng_wake.next_wakeup({cmp_snap: {"ssc_" + "f" * 32}}) is None
    print("[PASS] data-node wiring: coverage expansion, no self-wakeup edge")

    # ------------------------------------------------------------------
    # review R6-1 runtime: the self-resetting latch (flag → duration →
    # own reset) must actually cycle at runtime — set fires, the duration
    # gate completes after its seconds, and the next step auto-clears.
    # ------------------------------------------------------------------
    mgr_s = ControllerManager(
        _Hass(), "ctrl_smoke11", _vc(json.loads(json.dumps(latch_cfg)))
    )
    await mgr_s.async_setup()
    ent_sl = _Entity("binary_sensor.sl")
    mgr_s.register_entity("ssc_" + "3" * 32, ent_sl)
    eng_s = mgr_s.engine
    # stub default: switch.c is "on" → the first step latches on
    assert await eng_s.step_flags() == [latch_flag], "set fires → latch on"
    assert await eng_s.evaluate_any([latch_flag]) is True
    assert await eng_s.step_flags() == [], (
        "duration not yet elapsed → reset unmet, latch holds"
    )
    _advance_utc(6)
    assert await eng_s.step_flags() == [latch_flag], (
        "reset via own duration must auto-clear the latch"
    )
    assert await eng_s.evaluate_any([latch_flag]) is False
    mgr_s.async_unload()
    print("[PASS] self-resetting latch saves and cycles (review R6-1)")

    # ------------------------------------------------------------------
    # review R5-3: a reset window must not preserve the set member's FOR
    # ledger — set members are evaluated unconditionally (no short-circuit
    # on reset), so a stale ledger start cannot latch the flag early.
    # ------------------------------------------------------------------
    s_leaf_id = "cond_" + "1" * 32   # set member: switch.c on, for 60s
    r_leaf_id = "cond_" + "2" * 32   # reset member: switch.d on
    w_flag = "cond_" + "3" * 32
    for_flag_cfg = {
        "name": "flag-for-reset", "enabled": True, "logging_enabled": False,
        "triggers": [],
        "conditions": [
            {"id": s_leaf_id, "type": "state", "entity_id": "switch.c",
             "state": "on", "for": {"hours": 0, "minutes": 1, "seconds": 0}},
            {"id": r_leaf_id, "type": "state", "entity_id": "switch.d", "state": "on"},
            {"id": w_flag, "type": "flag",
             "set_conditions": [s_leaf_id], "reset_conditions": [r_leaf_id]},
        ],
        "outputs": [],
    }
    mgr_w = ControllerManager(
        _Hass(), "ctrl_smoke07", _vc(json.loads(json.dumps(for_flag_cfg)))
    )
    await mgr_w.async_setup()
    eng_w = mgr_w.engine
    # t0: set member holds → ledger opens, gate still False
    assert await eng_w.step_flags() == []
    _advance_utc(60)
    # 60s elapsed → set satisfied → flag latches on
    assert await eng_w.step_flags() == [w_flag]
    # reset window: reset member on AND set member drops off — the set
    # ledger must be popped (it is evaluated even though reset wins)
    mgr_w.hass.states._d["switch.d"] = "on"
    mgr_w.hass.states._d["switch.c"] = "off"
    assert await eng_w.step_flags() == [w_flag]  # reset wins → off
    # set member returns, then the reset releases 5s later: the FOR ledger
    # restarted inside the window, so 5s < 60s must NOT latch the flag (the
    # old short-circuit kept the stale pre-window ledger and latched at once)
    mgr_w.hass.states._d["switch.c"] = "on"
    _advance_utc(5)
    mgr_w.hass.states._d["switch.d"] = "off"
    assert await eng_w.step_flags() == [], (
        "reset window must have cleared the set member's FOR ledger"
    )
    # 60 more seconds of continuous set → now it latches
    _advance_utc(60)
    assert await eng_w.step_flags() == [w_flag]
    mgr_w.async_unload()
    print("[PASS] flag reset window clears FOR ledgers (review R5-3)")

    # ------------------------------------------------------------------
    # review R5-2: a directed tick during platform load must not retire the
    # first-eval gate — late-registering outputs still get their sweep.
    # ------------------------------------------------------------------
    x2_id = "cond_" + "5" * 32
    y2_id = "cond_" + "6" * 32
    late_cfg = {
        "name": "late-batch", "enabled": True, "logging_enabled": True,
        "triggers": [{"id": "trg_" + "1" * 32, "type": "state",
                      "entity_id": "switch.c",
                      "routes": {"conditions": [x2_id]}}],
        "conditions": [
            {"id": x2_id, "type": "state", "entity_id": "switch.c", "state": "on"},
            {"id": y2_id, "type": "state", "entity_id": "switch.d", "state": "on"},
        ],
        "outputs": [
            {"name": "out-x", "type": "switch", "entity_id": "ssc_" + "c" * 32,
             "on_conditions": [x2_id], "off_conditions": []},
            {"name": "out-y", "type": "switch", "entity_id": "ssc_" + "d" * 32,
             "on_conditions": [y2_id], "off_conditions": []},
        ],
    }
    mgr_l = ControllerManager(
        _Hass(), "ctrl_smoke08", _vc(json.loads(json.dumps(late_cfg)))
    )
    await mgr_l.async_setup()
    # batch 1: only out-x registers
    ent_lx = _Entity("switch.lx")
    mgr_l.register_entity("ssc_" + "c" * 32, ent_lx)
    mgr_l.async_entity_added("ssc_" + "c" * 32)
    # directed tick between batches (covers out-x's chain only)
    mgr_l._on_trigger_fire("trg_" + "1" * 32, "early")
    mgr_l._async_debounced_evaluate(None)
    await asyncio.sleep(0.05)
    recs_before = _log_cycles("ctrl_smoke08")
    mgr_l._on_trigger_fire("trg_" + "1" * 32, "early")
    mgr_l._async_debounced_evaluate(None)
    await asyncio.sleep(0.05)
    tail_l = _log_tail(recs_before, "ctrl_smoke08")
    assert [r["output"] for r in tail_l] == ["out-x"], tail_l
    assert mgr_l._first_eval_pending is True, (
        "directed tick must not retire the first-eval gate"
    )
    # batch 2: out-y registers → the deferred full first sweep must cover it
    ent_ly = _Entity("switch.ly")
    mgr_l.register_entity("ssc_" + "d" * 32, ent_ly)
    mgr_l.async_entity_added("ssc_" + "d" * 32)
    await asyncio.sleep(0.05)
    tail_l = _log_tail(recs_before, "ctrl_smoke08")
    assert [r["output"] for r in tail_l] == ["out-x", "out-x", "out-y"], tail_l
    mgr_l.async_unload()
    print("[PASS] first-eval gate survives directed ticks (review R5-2)")

    # ------------------------------------------------------------------
    # review R5-5: unload must win over an in-flight drain — no re-arm, no
    # backlog evaluation, no flag write-back from the dead manager.
    # ------------------------------------------------------------------
    from custom_components.sensor_switch_controller.const import DOMAIN as _DOM
    from custom_components.sensor_switch_controller.hub import ScannerHub

    _hass_g = _Hass()
    hub_g = ScannerHub(_hass_g)
    _hass_g.data[_DOM] = hub_g
    u_cond = "cond_" + "d" * 32   # set member: switch.c on, for 60s
    u_flag = "cond_" + "e" * 32
    u_cfg = {
        "name": "unload-guard", "enabled": True, "logging_enabled": True,
        "triggers": [{"id": "trg_" + "7" * 32, "type": "state",
                      "entity_id": "switch.c",
                      "routes": {"conditions": [u_cond]}}],
        "conditions": [
            {"id": u_cond, "type": "state", "entity_id": "switch.c",
             "state": "on", "for": {"hours": 0, "minutes": 1, "seconds": 0}},
            {"id": u_flag, "type": "flag",
             "set_conditions": [u_cond], "reset_conditions": []},
        ],
        "outputs": [
            {"name": "out-u", "type": "switch", "entity_id": "ssc_" + "e" * 32,
             "on_conditions": [u_flag], "off_conditions": []},
        ],
    }
    mgr_g = ControllerManager(
        _hass_g, "ctrl_smoke09", _vc(json.loads(json.dumps(u_cfg)))
    )
    await mgr_g.async_setup()
    ent_gu = _Entity("switch.gu")
    mgr_g.register_entity("ssc_" + "e" * 32, ent_gu)
    mgr_g.async_entity_added("ssc_" + "e" * 32)
    await asyncio.sleep(0.05)  # init sweep: for-ledger opens, rearm arms

    def _pit_count():
        return len([e for e in _Evt.LISTENERS if e[0] == "pit"])

    recs_g = _log_cycles("ctrl_smoke09")
    assert recs_g, "init sweep must have run"
    pit_before = _pit_count()
    assert pit_before >= 1, "the FOR ledger must have armed a wakeup"
    # capture the wakeup callback the rearm registered, then unload: the
    # captured callback firing afterwards is the R5-5 resurrection scenario
    woken = [e for e in _Evt.LISTENERS if e[0] == "pit"][-1][1]
    mgr_g.async_unload()
    # 1) the captured wakeup fires after unload → no evaluation, no re-arm
    woken(None)
    await asyncio.sleep(0.05)
    assert _log_cycles("ctrl_smoke09") == recs_g, "wakeup after unload must not evaluate"
    assert _pit_count() == pit_before, "wakeup after unload must not re-arm"
    # 2) rearm itself is a no-op after unload
    mgr_g._rearm_for_wakeup()
    assert _pit_count() == pit_before, "unload must stop wakeup re-arming"
    # 3) an in-flight drain's backlog dies with the manager; the flag flip
    #    it would produce is NOT written back into the hub store (the
    #    deleted-controller resurrection path, R5-5 + R1-11)
    eng_g = mgr_g.engine
    eng_g._flag_states[u_flag] = False
    eng_g._for_timers[u_cond] = _clock["utc"] - timedelta(seconds=120)
    mgr_g._evaluating = True  # pretend a run owns the drain loop
    mgr_g._stack_targets(None)
    mgr_g._rerun_pending = True
    await mgr_g._async_drain()
    await asyncio.sleep(0.05)
    assert _log_cycles("ctrl_smoke09") == recs_g, "backlog must die with the unloaded manager"
    assert eng_g._flag_states.get(u_flag) is False, (
        "post-unload drain must not step flags (zombie pass)"
    )
    assert "ctrl_smoke09" not in hub_g.flag_states, (
        "unloaded manager must not write flag states back"
    )
    assert _pit_count() == pit_before, "drain must not re-arm after unload"
    print("[PASS] unload stops rearm/evaluation/flag write-back (review R5-5)")

    # ------------------------------------------------------------------
    # review R5-10: RestoreEntity path — the output restores its stored
    # pre-restart state on (re)add; no stored state keeps the default.
    # ------------------------------------------------------------------
    from custom_components.sensor_switch_controller.switch import SensorSwitch

    rst_cfg = {
        "name": "restore", "enabled": True, "logging_enabled": False,
        "triggers": [],
        "conditions": [
            {"id": "cond_" + "b" * 32, "type": "state",
             "entity_id": "switch.c", "state": "on"},
        ],
        "outputs": [
            {"name": "r-on", "type": "switch", "entity_id": "ssc_" + "f" * 32,
             "on_conditions": ["cond_" + "b" * 32], "off_conditions": []},
            {"name": "r-none", "type": "switch", "entity_id": "ssc_" + "0" * 32,
             "on_conditions": [], "off_conditions": []},
        ],
    }
    mgr_r = ControllerManager(
        _Hass(), "ctrl_smoke10", _vc(json.loads(json.dumps(rst_cfg)))
    )
    await mgr_r.async_setup()
    sw_on = SensorSwitch(_Hass(), mgr_r, "ctrl_smoke10", rst_cfg["outputs"][0])
    sw_on._restored_state = "on"
    await sw_on.async_added_to_hass()
    assert sw_on._attr_is_on is True, "restored state must survive the re-add"
    sw_none = SensorSwitch(_Hass(), mgr_r, "ctrl_smoke10", rst_cfg["outputs"][1])
    await sw_none.async_added_to_hass()
    assert sw_none._attr_is_on is False, "no stored state must leave the default"
    assert "ssc_" + "f" * 32 in mgr_r._added_out_ids
    await asyncio.sleep(0.05)  # let the init eval (both now added) settle
    mgr_r.async_unload()
    print("[PASS] RestoreEntity: last state restored on re-add (review R5-10)")

    # ------------------------------------------------------------------
    # review R5-10: R1-12 regression pin — a daily-at callback that raises
    # must still re-arm (try/finally), or the trigger dies forever.
    # ------------------------------------------------------------------
    from custom_components.sensor_switch_controller.triggers import TriggerManager

    tm = TriggerManager(_Hass(), [], lambda tid, desc: None)

    def _boom(_now):
        raise RuntimeError("daily-callback-boom")

    cancel = tm._schedule_daily_at("23:59", _boom)
    armed = _pit_count()
    assert armed >= 1, "daily-at must arm a point-in-time listener"
    action = [e for e in _Evt.LISTENERS if e[0] == "pit"][-1][1]
    try:
        action(None)  # the fire raises inside the callback…
    except RuntimeError:
        pass
    assert _pit_count() == armed + 1, (
        "a callback exception must not stop the daily re-arm (R1-12)"
    )
    cancel()
    print("[PASS] daily-at re-arms through callback exceptions (R1-12 pin)")

    # review R5-9: an empty-pool state trigger counts as a registration
    # failure (panel badge), not a silent skip
    tm_ep = TriggerManager(
        _Hass(), [{"id": "trg_" + "8" * 32, "type": "state", "enabled": True}],
        lambda tid, desc: None,
    )
    tm_ep.async_setup()  # 0.10.0: no declared entities → no targets
    assert tm_ep.register_errors == 1, "entity-less state trigger must be an error"
    print("[PASS] entity-less state trigger counts as registration error (R5-9)")

    # WHA-F-312: the other defensive skip paths count too — same口径 as R5-9
    # (a trigger that can never register must surface on the panel badge)
    tm_t0 = TriggerManager(
        _Hass(),
        [{"id": "trg_" + "b" * 32, "type": "time", "every_seconds": 0}],
        lambda tid, desc: None,
    )
    tm_t0.async_setup()
    assert tm_t0.register_errors == 1, "unregistrable time trigger must be an error"
    tm_uk = TriggerManager(
        _Hass(), [{"id": "trg_" + "c" * 32, "type": "poltergeist"}],
        lambda tid, desc: None,
    )
    tm_uk.async_setup()
    assert tm_uk.register_errors == 1, "unknown trigger type must be an error"
    print("[PASS] defensive skip paths count as registration errors (WHA-F-312)")

    # WHA-F-309 runtime face: the migrated disabled-pool-empty controller is
    # valid; the disabled trigger registers NOTHING (no listener, no error)
    # while the other trigger and the output keep working.
    f309_leaf = "cond_" + "c" * 32  # switch.c on → True (stub state)
    f309_out = "ssc_" + "9" * 32
    f309_cfg = {
        "name": "f309", "enabled": True, "logging_enabled": True,
        "triggers": [
            {"id": "trg_" + "9" * 32, "type": "state", "enabled": False},
            {"id": "trg_" + "a" * 32, "type": "time", "every_seconds": 300,
             "routes": {"conditions": [f309_leaf]}},
        ],
        "sensors": [],
        "conditions": [
            {"id": f309_leaf, "type": "state", "entity_id": "switch.c", "state": "on"},
        ],
        "outputs": [{
            "name": "out_f309", "type": "switch", "entity_id": f309_out,
            "on_conditions": [f309_leaf], "off_conditions": [],
        }],
    }
    _migrate_controller_v7(f309_cfg)
    f309_valid = _vc(f309_cfg)
    assert f309_valid["triggers"][0]["entity_id"] == [], f309_valid["triggers"][0]
    state_before = len([e for e in _Evt.LISTENERS if e[0] == "state"])
    interval_before = len([e for e in _Evt.LISTENERS if e[0] == "interval"])
    mgr_f309 = ControllerManager(_Hass(), "ctrl_smoke14", f309_valid)
    await mgr_f309.async_setup()
    ent_f309 = _Entity("switch.f309")
    mgr_f309.register_entity(f309_out, ent_f309)
    assert len([e for e in _Evt.LISTENERS if e[0] == "state"]) == state_before, (
        "the disabled pool listener must not register any listener"
    )
    assert mgr_f309.trigger_manager.register_errors == 0, (
        "a disabled trigger must not count as a registration error"
    )
    interval_ls = [e for e in _Evt.LISTENERS if e[0] == "interval"]
    assert len(interval_ls) == interval_before + 1, (
        "the time trigger must still register"
    )
    recs_f309 = _log_cycles("ctrl_smoke14")
    interval_ls[-1][1](None)
    mgr_f309._async_debounced_evaluate(None)
    await asyncio.sleep(0.05)
    tail_f309 = _log_tail(recs_f309, "ctrl_smoke14")
    assert len(tail_f309) == 1 and tail_f309[0]["output"] == "out_f309", tail_f309
    assert tail_f309[0]["decision"] == "on" and tail_f309[0]["applied"] is True, (
        tail_f309[0]
    )
    mgr_f309.async_unload()
    print("[PASS] WHA-F-309 runtime: disabled pool listener inert, rest works")

    # ------------------------------------------------------------------
    # 0.10.0 causal explicitness: a multi-entity state trigger registers ONE
    # listener for the whole list (native list form, HA 2026.1.3 verified),
    # the firing entity + its change land in the decision log's
    # triggered_by, and every record carries the per-condition verdicts.
    # ------------------------------------------------------------------
    ce_a = "cond_" + "a" * 32  # numeric sensor.a above 20 (False: 16.7)
    ce_b = "cond_" + "b" * 32  # switch.c on (True)
    ce_out = "ssc_" + "7" * 32
    ce_trg = "trg_" + "e" * 32
    ce_cfg = {
        "name": "causal", "enabled": True, "logging_enabled": True,
        "triggers": [{
            "id": ce_trg, "type": "state", "enabled": True,
            "entity_id": ["switch.c", "switch.d"],
            "routes": {"conditions": [ce_b]},
        }],
        "conditions": [
            {"id": ce_a, "type": "numeric_state", "entity_id": "sensor.a", "above": 20},
            {"id": ce_b, "type": "state", "entity_id": "switch.c", "state": "on"},
        ],
        "outputs": [{
            "name": "out_ce", "type": "switch", "entity_id": ce_out,
            "on_conditions": [ce_a, ce_b], "off_conditions": [],
            "manual_override": False,
        }],
    }
    mgr_ce = ControllerManager(
        _Hass(), "ctrl_smoke13", _vc(json.loads(json.dumps(ce_cfg)))
    )
    await mgr_ce.async_setup()
    ent_ce = _Entity("switch.ce")
    mgr_ce.register_entity(ce_out, ent_ce)
    state_ls = [e for e in _Evt.LISTENERS if e[0] == "state"]
    assert state_ls and state_ls[-1][1] == ["switch.c", "switch.d"], (
        "the whole entity list must reach async_track_state_change_event"
    )
    from types import SimpleNamespace as _NS

    def _state_event(eid, old, new):
        return _NS(data={
            "entity_id": eid,
            "old_state": _NS(state=old, attributes={}) if old else None,
            "new_state": _NS(state=new, attributes={}) if new else None,
        })

    action = state_ls[-1][2]
    recs_ce = _log_cycles("ctrl_smoke13")
    action(_state_event("switch.c", "off", "on"))
    mgr_ce._async_debounced_evaluate(None)
    await asyncio.sleep(0.05)
    tail_ce = _log_tail(recs_ce, "ctrl_smoke13")
    assert len(tail_ce) == 1, tail_ce
    assert "switch.c: off→on" in tail_ce[0]["triggered_by"], tail_ce[0]
    # per-condition verdicts of the evaluated chain are in the record
    assert tail_ce[0]["conditions"] == {ce_a: False, ce_b: True}, tail_ce[0]
    # a change on the SECOND list entity fires too (per-event matching —
    # from/to semantics unchanged for lists)
    recs_ce = _log_cycles("ctrl_smoke13")
    action(_state_event("switch.d", "on", "off"))
    mgr_ce._async_debounced_evaluate(None)
    await asyncio.sleep(0.05)
    tail_ce = _log_tail(recs_ce, "ctrl_smoke13")
    assert len(tail_ce) == 1, tail_ce
    assert "switch.d: on→off" in tail_ce[0]["triggered_by"], tail_ce[0]
    mgr_ce.async_unload()
    print(
        "[PASS] causal log: multi-entity listener, entity+change in "
        "triggered_by, conditions detail"
    )

    # ------------------------------------------------------------------
    # 0.9.0 review R1-7 + R5-7/R5-8: remove_controller detaches memory and
    # returns its entity ids; sweep_registry (post-save phase) removes the
    # entity-registry entries by unique_id prefix AND the controller's
    # device entry; flag states are erased by async_drop_flag_states only.
    # ------------------------------------------------------------------
    hub_t = ScannerHub(_Hass())
    hub_t.set_entry("test_entry_id")
    rid = "ctrl_ab12cd34"
    hub_t.controllers[rid] = _vc({
        "name": "sweep-me", "enabled": False, "logging_enabled": False,
        "triggers": [], "conditions": [],
        "outputs": [],
    })
    # the R1-11 pin must be non-vacuous: seed flag states first (R5-10)
    hub_t.flag_states[rid] = {"cond_" + "a" * 32: True}
    _FAKE_REGISTRY.add("binary_sensor.mine", "ctrl_ab12cd34_ssc_1")
    _FAKE_REGISTRY.add("binary_sensor.mine_no_hass", "ctrl_ab12cd34_ssc_2")
    _FAKE_REGISTRY.add("binary_sensor.other", "ctrl_99999999_ssc_1")
    _FAKE_DEVICE_REGISTRY.add("dev_mine", {("sensor_switch_controller", rid)})
    _FAKE_DEVICE_REGISTRY.add(
        "dev_other", {("sensor_switch_controller", "ctrl_99999999")}
    )
    entity_ids = hub_t.remove_controller(rid)
    # phase 1 detaches memory only — nothing irreversible happened yet (R5-8)
    assert entity_ids == [] and rid not in hub_t.controllers
    assert hub_t.flag_states[rid] == {"cond_" + "a" * 32: True}, (
        "phase 1 must not touch flag states"
    )
    assert _FAKE_REGISTRY.removed == [] and _FAKE_DEVICE_REGISTRY.removed == []
    # phase 2 (the web handler runs it only after the store save won)
    hub_t.sweep_registry(rid, entity_ids)
    assert sorted(_FAKE_REGISTRY.removed) == [
        "binary_sensor.mine",
        "binary_sensor.mine_no_hass",
    ], _FAKE_REGISTRY.removed
    assert "binary_sensor.other" not in _FAKE_REGISTRY.removed
    assert _FAKE_DEVICE_REGISTRY.removed == ["dev_mine"], _FAKE_DEVICE_REGISTRY.removed
    assert "dev_other" not in _FAKE_DEVICE_REGISTRY.removed
    # flag drop (phase 2, persisted — R1-11 made observable by R5-10)
    await hub_t.async_drop_flag_states(rid)
    assert rid not in hub_t.flag_states
    print("[PASS] remove_controller two-phase sweep incl. devices (R1-7/R5-7/R5-8)")

    # ------------------------------------------------------------------
    # review R6-5/R6-6: the store/flag load guards need regression pins —
    # a non-object payload (top level or the controllers value) degrades
    # loudly to empty instead of killing setup (F-280), and a non-object
    # per-controller flag value is dropped with a warning (R6-5). Also
    # proves a VALID store — including the R6-1 self-resetting latch —
    # loads back into controllers, not invalid.
    # ------------------------------------------------------------------
    hub_p = ScannerHub(_Hass())

    async def _load_not_object():
        return ["x"]

    hub_p.store.async_load = _load_not_object
    await hub_p.async_load()
    assert hub_p.controllers == {} and hub_p.invalid == {}, (
        "non-object store payload must degrade to empty (F-280)"
    )

    async def _load_controllers_list():
        return {"controllers": ["x"]}

    hub_p.store.async_load = _load_controllers_list
    await hub_p.async_load()
    assert hub_p.controllers == {} and hub_p.invalid == {}, (
        "non-object controllers payload must degrade to empty (F-280)"
    )

    async def _load_valid():
        return {
            "controllers": {
                "ctrl_ab12cd34": json.loads(json.dumps(latch_cfg)),
            }
        }

    hub_p.store.async_load = _load_valid
    await hub_p.async_load()
    assert set(hub_p.controllers) == {"ctrl_ab12cd34"} and hub_p.invalid == {}, (
        "a valid store (incl. the R6-1 self latch) must load, not land invalid"
    )

    # review R9-1 (WHA-F-304): load one valid + one broken controller so
    # BOTH halves of the (controllers or invalid) memory condition are
    # populated before the shape-guard pins below
    async def _load_mixed():
        return {
            "controllers": {
                "ctrl_ab12cd34": json.loads(json.dumps(latch_cfg)),
                "ctrl_beef0000": {},
            }
        }

    hub_p.store.async_load = _load_mixed
    await hub_p.async_load()
    assert set(hub_p.controllers) == {"ctrl_ab12cd34"}, (
        "the valid half of a mixed store must load"
    )
    assert set(hub_p.invalid) == {"ctrl_beef0000"}, (
        "the broken half of a mixed store must land invalid, kept as-is"
    )

    # review R7-1: a None payload (missing / corrupt file) on the re-read
    # path (rollback re-read or entry reload) must keep the populated
    # memory — a wipe would be persisted by the very next save
    async def _load_none():
        return None

    hub_p.store.async_load = _load_none
    await hub_p.async_load()
    assert (
        set(hub_p.controllers) == {"ctrl_ab12cd34"}
        and set(hub_p.invalid) == {"ctrl_beef0000"}
    ), "a None payload must keep the last-known-good memory (R7-1)"

    # review R9-1 (WHA-F-304): a payload that parses but carries no usable
    # controllers object — a non-object controllers value or an empty store
    # object — must keep the populated memory too (the guard returns before
    # the table rebuild, so the invalid half survives as well). The same
    # shapes degraded to empty further above with EMPTY memory: the memory
    # condition is what separates keep from degrade.
    hub_p.store.async_load = _load_controllers_list
    await hub_p.async_load()
    assert (
        set(hub_p.controllers) == {"ctrl_ab12cd34"}
        and set(hub_p.invalid) == {"ctrl_beef0000"}
    ), (
        "a non-object controllers payload must keep the last-known-good "
        "memory (R9-1)"
    )

    async def _load_empty_object():
        return {}

    hub_p.store.async_load = _load_empty_object
    await hub_p.async_load()
    assert (
        set(hub_p.controllers) == {"ctrl_ab12cd34"}
        and set(hub_p.invalid) == {"ctrl_beef0000"}
    ), "an empty store object must keep the last-known-good memory (R9-1)"

    async def _load_flags():
        return {
            "flags": {
                "ctrl_good": {"cond_" + "1" * 32: True},
                "ctrl_bad_str": "oops",
                "ctrl_bad_num": 5,
                42: {"cond_" + "1" * 32: True},
                # review R7-6: non-boolean latch values inside the dict
                "ctrl_bad_val": {
                    "cond_" + "1" * 32: "on",
                    "cond_" + "2" * 32: True,
                },
                "ctrl_all_bad": {"cond_" + "1" * 32: 1},
            }
        }

    hub_p._flag_store.async_load = _load_flags
    await hub_p.async_load_flag_states()
    assert hub_p.flag_states == {
        "ctrl_good": {"cond_" + "1" * 32: True},
        "ctrl_bad_val": {"cond_" + "2" * 32: True},
        "ctrl_all_bad": {},
    }, "store/flag load guards hold on corrupt payloads: " + repr(
        hub_p.flag_states
    )
    print(
        "[PASS] store/flag load guards hold on corrupt payloads"
        " (F-280/R6-5/R7-1/R7-6/R9-1)"
    )

    # ------------------------------------------------------------------
    # WHA-F-319: the missing-file / first-install None payload is the
    # documented empty-store result — pin the SILENCE (no warning) on an
    # EMPTY memory so a future guard cannot start log-spamming fresh
    # installs (the populated-memory keep-warning above is the other face).
    # ------------------------------------------------------------------
    import logging as _logging

    hub_q = ScannerHub(_Hass())
    none_records = []

    class _NoneCap(_logging.Handler):
        def emit(self, record):
            none_records.append(record.getMessage())

    hub_logger = _logging.getLogger(
        "custom_components.sensor_switch_controller.hub"
    )
    _none_handler = _NoneCap(level=_logging.WARNING)
    hub_logger.addHandler(_none_handler)
    try:
        await hub_q.async_load()
    finally:
        hub_logger.removeHandler(_none_handler)
    assert hub_q.controllers == {} and hub_q.invalid == {}, (
        "an empty-memory None payload degrades to the empty state"
    )
    assert not none_records, (
        f"first-install None payload must stay silent (F-311/F-319): "
        f"{none_records}"
    )
    print("[PASS] WHA-F-319: first-install None payload stays silent")

    # ------------------------------------------------------------------
    # WHA-F-320: calendar gates get a directed wakeup — the (async) leaf
    # caches the earliest future boundary (event.start - hours / event.end)
    # and the (sync) next_wakeup offers it; a heartbeat margin covers the
    # never-evaluated gaps. Query is one window of look-ahead so a
    # verdict-False evaluation still caches the entry edge.
    # ------------------------------------------------------------------
    _hass_c = _Hass()
    cal_cid = "cond_" + "9" * 32

    class _CalEvt:
        def __init__(self, start, end):
            self._start = start
            self._end = end

        @property
        def start_datetime_local(self):
            return self._start

        @property
        def end_datetime_local(self):
            return self._end

    class _CalEntity:
        def __init__(self, events):
            self._events = events

        async def async_get_events(self, hass, start, end):
            return [
                e
                for e in self._events
                if e.start_datetime_local < end and e.end_datetime_local > start
            ]

    cal_entity = _CalEntity(
        # calendar edges live in the LOCAL clock domain (the leaf queries
        # with dt_util.now()); the stub clocks run local=10:00 / utc=02:00
        [_CalEvt(_clock["local"] + timedelta(hours=3), _clock["local"] + timedelta(hours=4))]
    )
    _hass_c.data["entity_components"] = {
        "calendar": types.SimpleNamespace(
            get_entity=lambda eid: cal_entity if eid == "calendar.x" else None
        )
    }
    cal_cond = {
        "id": cal_cid, "type": "calendar", "entity_id": "calendar.x", "hours": 2,
    }
    cal_eng = ConditionEngine(_hass_c, [cal_cond])
    # t0 (local 10:00): the event starts at 13:00 — outside the verdict
    # window [10:00, 12:00] → False, but the look-ahead (query reaches
    # 14:00) caches its entry edge 11:00
    verdict = await cal_eng._evaluate_id(cal_cid, set())
    assert verdict is False, verdict
    assert cal_eng._calendar_next.get(cal_cid) == _clock["local"] + timedelta(hours=1), (
        "a verdict-False evaluation must still cache the entry edge "
        "(start - hours = 11:00)"
    )
    # NOTE on the stub: the local/utc stub clocks differ by 8h and both
    # offers are compared naive — under real HA both are aware UTC and the
    # min() is a true "wake at whichever comes first". Pin the cache value
    # directly (above) and the offer outcome as its stub-reality min.
    from homeassistant.util import dt as _dt

    pending = cal_eng.next_wakeup({cal_cid: {"ssc_out"}})
    assert pending is not None, "calendar gate must produce a directed wakeup"
    expiry, outs = pending
    assert outs == {"ssc_out"}, outs
    assert expiry == min(
        _clock["local"] + timedelta(hours=1), _dt.utcnow() + timedelta(minutes=15)
    ), f"the wakeup must be min(cached edge, heartbeat), got {expiry}"
    # heartbeat tier: nothing cached (fresh engine) → next_wakeup offers the
    # heartbeat margin so a fresh restart still wakes within the margin
    fresh_eng = ConditionEngine(_Hass(), [cal_cond])
    pending = fresh_eng.next_wakeup({cal_cid: {"ssc_out"}})
    assert pending is not None, "heartbeat tier must keep calendar gates waking"
    expiry, outs = pending
    assert outs == {"ssc_out"}, outs
    assert abs(
        (expiry - _dt.utcnow() - timedelta(minutes=15)).total_seconds()
    ) < 1, f"the heartbeat offer is now+15min, got {expiry}"
    # verdict True once the event is inside the window; the exit edge (event
    # end) becomes the cached boundary
    cal_entity._events = [
        _CalEvt(_clock["local"] + timedelta(hours=1), _clock["local"] + timedelta(hours=4))
    ]
    verdict = await cal_eng._evaluate_id(cal_cid, set())
    assert verdict is True, verdict
    # boundaries: entry edge (start-2h = 09:00, still naive-future vs the
    # 02:0x utc stub clock) and the event end (14:00) — the cache takes the
    # min of the future ones (stub-reality; under real HA the past edge is
    # already behind utcnow and the end wins)
    assert cal_eng._calendar_next.get(cal_cid) == min(
        b
        for b in (
            _clock["local"] - timedelta(hours=1),
            _clock["local"] + timedelta(hours=4),
        )
        if b > _dt.utcnow()
    ), "after entering the window the cache must hold the earliest future edge"
    pending = cal_eng.next_wakeup({cal_cid: {"ssc_out"}})
    expiry, _outs = pending
    assert expiry == min(
        _clock["local"] + timedelta(hours=4), _dt.utcnow() + timedelta(minutes=15)
    ), f"the wakeup must be min(event end, heartbeat), got {expiry}"
    print("[PASS] WHA-F-320: calendar boundary wakeup + heartbeat tier")

    # ------------------------------------------------------------------
    # WHA-F-322 (+F-325): the cooldown flip history persists across manager
    # rebuilds (seeded from the hub store, saved on applied flips) and the
    # flag-store payload is snapshotted per controller — mutating the live
    # tables after a save must not retroactively change the saved payload.
    # ------------------------------------------------------------------
    _hass_f = _Hass()
    hub_f = ScannerHub(_hass_f)
    _hass_f.data[_DOM] = hub_f

    class _RecordingFlagStore:
        """Local recording stand-in: the module-level _Store stub is a
        no-op, but this pin must observe the persisted payloads AND the
        call shape (F-343: a regression back to synchronous per-write
        async_save must fail the pin, not just land the same payload)."""

        def __init__(self):
            self.saved = []
            self.calls = []  # ("delay", delay) | ("save", None)
            self.pending = None  # data_func of the last delayed write

        async def async_save(self, data):
            self.calls.append(("save", None))
            self.saved.append(data)

        def async_delay_save(self, data_func, delay=0):
            # F-339 stand-in: record the deferral and hold data_func — the
            # payload is only observed after flush(), like the real Store
            # merging the burst and calling data_func at write time.
            self.calls.append(("delay", delay))
            self.pending = data_func

        def flush(self):
            if self.pending is not None:
                self.saved.append(self.pending())
                self.pending = None

        async def async_load(self):
            return None

    hub_f._flag_store = _RecordingFlagStore()
    flip_out = "ssc_" + "1" * 32
    flip_at = _clock["utc"]
    await hub_f.async_save_last_flip("ctrl_ab12cd34", flip_out, flip_at)
    assert hub_f.last_flips["ctrl_ab12cd34"][flip_out] == flip_at.isoformat()
    # F-343 discriminating pin: the flip-history write must have gone
    # through the debounced path ONLY — a regression back to the old
    # per-write async_save would append ("save", None) here instead.
    assert hub_f._flag_store.calls == [("delay", 1)], (
        hub_f._flag_store.calls
    )
    hub_f._flag_store.flush()
    saved_payload = hub_f._flag_store.saved[-1]
    assert saved_payload["last_flip"] == {"ctrl_ab12cd34": {flip_out: flip_at.isoformat()}}
    # F-325: mutate the live tables — the saved payload must not move
    await hub_f.async_save_flag_states("ctrl_ab12cd34", {"cond_" + "1" * 32: True})
    saved_payload = hub_f._flag_store.saved[-1]
    hub_f.flag_states["ctrl_ab12cd34"]["cond_" + "1" * 32] = False
    hub_f.flag_states["ctrl_99999999"] = {"x": True}
    hub_f.last_flips["ctrl_99999999"] = {"y": "z"}
    assert saved_payload["flags"] == {"ctrl_ab12cd34": {"cond_" + "1" * 32: True}}, (
        "the saved payload must be a per-controller snapshot (F-325)"
    )
    assert "ctrl_99999999" not in saved_payload["flags"]
    assert saved_payload["last_flip"] == {
        "ctrl_ab12cd34": {flip_out: flip_at.isoformat()}
    }
    # a rebuilt manager seeds its cooldown history from the hub store
    seed_cfg = _vc(json.loads(json.dumps({
        "name": "flip-seed", "enabled": True, "logging_enabled": False,
        "triggers": [{"id": "trg_" + "8" * 32, "type": "state",
                      "entity_id": "switch.c",
                      "routes": {"conditions": ["cond_" + "a" * 32]}}],
        "conditions": [
            {"id": "cond_" + "a" * 32, "type": "state",
             "entity_id": "switch.c", "state": "on"},
        ],
        "outputs": [
            {"name": "out-f", "type": "switch", "entity_id": flip_out,
             "on_conditions": ["cond_" + "a" * 32], "off_conditions": []},
        ],
    })))
    mgr_f = ControllerManager(_hass_f, "ctrl_ab12cd34", seed_cfg)
    seeded = mgr_f.last_flip_at(flip_out)
    assert seeded is not None and seeded == flip_at, (
        f"a rebuilt manager must seed its flip history from the hub store, "
        f"got {seeded}"
    )
    # drop clears both tables and persists the erasure (the F-325 noise
    # controller above must survive — the drop is per-controller)
    await hub_f.async_drop_flag_states("ctrl_ab12cd34")
    assert "ctrl_ab12cd34" not in hub_f.last_flips
    assert hub_f._flag_store.saved[-1]["last_flip"] == {
        "ctrl_99999999": {"y": "z"}
    }, hub_f._flag_store.saved[-1]["last_flip"]
    print("[PASS] WHA-F-322/F-325: flip history persists+seeds, payload snapshot")

    # ------------------------------------------------------------------
    # WHA-F-316: an empty group under a NOT is constant True — it must NOT
    # be collected as a dead flag branch (no misleading "cannot contribute"
    # warning); an empty group in a plain branch still warns once.
    # ------------------------------------------------------------------
    not_g = "cond_" + "b" * 32
    empty_g = "cond_" + "c" * 32
    f16_flag = "cond_" + "d" * 32
    f16_flag2 = "cond_" + "e" * 32
    f16_eng = ConditionEngine(_Hass(), [
        {"id": empty_g, "type": "and", "conditions": []},
        {"id": not_g, "type": "not", "conditions": [empty_g]},
        {"id": f16_flag, "type": "flag",
         "set_conditions": [not_g], "reset_conditions": []},
        {"id": f16_flag2, "type": "flag",
         "set_conditions": [empty_g], "reset_conditions": []},
    ])
    eng_records = []

    class _EngCap(_logging.Handler):
        def emit(self, record):
            eng_records.append(record.getMessage())

    eng_logger = _logging.getLogger(
        "custom_components.sensor_switch_controller.condition_engine"
    )
    _eng_handler = _EngCap(level=_logging.WARNING)
    eng_logger.addHandler(_eng_handler)
    try:
        await f16_eng.step_flags()
    finally:
        eng_logger.removeHandler(_eng_handler)
    # exactly ONE warning: the plain-branch reference (the control), not the
    # NOT-wrapped one — the NOT inverts the empty group to constant True
    assert len(eng_records) == 1 and "empty group" in eng_records[0], (
        f"an empty group under NOT is constant True — only the plain-branch "
        f"reference may warn (F-316): {eng_records}"
    )
    print("[PASS] WHA-F-316: empty group under NOT is not a dead branch")

    # ------------------------------------------------------------------
    # Schema save-time static hazard warnings (never rejecting):
    # ① off-chain cooldown warns, on-chain cooldown does not; ② routes wired
    # to an unreachable condition warn; ③ an empty non-signal group in an
    # output chain warns; ④ the calendar-only-output warning.
    # ------------------------------------------------------------------
    sch_records = []

    class _SchCap(_logging.Handler):
        def emit(self, record):
            sch_records.append(record.getMessage())

    sch_logger = _logging.getLogger(
        "custom_components.sensor_switch_controller.schema"
    )
    _sch_handler = _SchCap(level=_logging.WARNING)
    sch_logger.addHandler(_sch_handler)
    try:
        hz_c1 = "cond_" + "a" * 32
        hz_c2 = "cond_" + "b" * 32
        hz_o1 = "ssc_" + "1" * 32
        hz_base = {
            "name": "hazards",
            "conditions": [
                {"id": hz_c1, "type": "state", "entity_id": "switch.c",
                 "state": "on"},
                {"id": hz_c2, "type": "cooldown", "seconds": 30},
            ],
            "triggers": [{"id": "trg_" + "1" * 32, "type": "state",
                          "entity_id": "switch.c",
                          "routes": {"conditions": [hz_c1]}}],
        }
        # ① off-chain cooldown → one warning; the same cooldown on the on
        # chain (legit anti-short-cycle) → none
        _vc({**json.loads(json.dumps(hz_base)), "outputs": [
            {"name": "o", "type": "switch", "entity_id": hz_o1,
             "on_conditions": [hz_c1], "off_conditions": [hz_c2]},
        ]})
        assert sum("off 条件链" in r for r in sch_records) == 1, sch_records
        n_off = len(sch_records)
        _vc({**json.loads(json.dumps(hz_base)), "outputs": [
            {"name": "o", "type": "switch", "entity_id": hz_o1,
             "on_conditions": [hz_c2], "off_conditions": [hz_c1]},
        ]})
        assert len(sch_records) == n_off, (
            f"an on-chain cooldown is legitimate — no warning: {sch_records}"
        )
        # ①k (0.15.0 face ① narrowing): a cooldown that reaches the off
        # chain ONLY through a duration's start edge (on=and[leaf, cooldown]
        # arming the duration whose gate hangs on the off chain) must NOT
        # warn — the cooldown never gates the off verdict itself there, so
        # the off-side polarity trap cannot exist. Group-member expansion
        # onto an off chain keeps warning (the trap is real there).
        n_start_edge = len(sch_records)
        hz_c3 = "cond_" + "c" * 32
        hz_c4 = "cond_" + "d" * 32
        _vc({**json.loads(json.dumps(hz_base)), "conditions": [
            {"id": hz_c1, "type": "state", "entity_id": "switch.c",
             "state": "on"},
            {"id": hz_c2, "type": "cooldown", "seconds": 30},
            {"id": hz_c3, "type": "and", "conditions": [hz_c1, hz_c2]},
            {"id": hz_c4, "type": "duration", "seconds": 60,
             "start": hz_c3, "abort": None},
        ], "outputs": [
            {"name": "o", "type": "switch", "entity_id": hz_o1,
             "on_conditions": [hz_c3], "off_conditions": [hz_c4]},
        ]})
        assert len(sch_records) == n_start_edge, (
            "a cooldown arming a duration.start lives on the on side — the "
            "off-chain drag-in must not warn (0.15.0 face ① narrowing): "
            f"{sch_records[n_start_edge:]}"
        )
        hz_c5 = "cond_" + "f" * 32
        _vc({**json.loads(json.dumps(hz_base)), "conditions": [
            {"id": hz_c1, "type": "state", "entity_id": "switch.c",
             "state": "on"},
            {"id": hz_c2, "type": "cooldown", "seconds": 30},
            {"id": hz_c5, "type": "and", "conditions": [hz_c2]},
        ], "outputs": [
            {"name": "o", "type": "switch", "entity_id": hz_o1,
             "on_conditions": [hz_c1], "off_conditions": [hz_c5]},
        ]})
        assert sum("off 条件链" in r
                   for r in sch_records[n_start_edge:]) == 1, (
            "a cooldown expanded through group members onto an off chain "
            "still warns (face ① keeps the real trap covered): "
            f"{sch_records[n_start_edge:]}"
        )
        # ①n (R1#3): the narrow residual face the 0.15.0 narrowing left —
        # a duration ON the off chain whose start subtree is dominated by
        # cooldowns (direct, or via a group whose own polarity lets a
        # cooldown dominate: AND=all-composed, OR=one member suffices,
        # F-556) still traps with a delay: cold start the cooldown reads
        # True, the duration arms itself N seconds in while the output is
        # already off, no flip is ever recorded and the off chain
        # out-ranks on forever. Mixing a live signal into an AND start
        # group stays the legitimate arming shape — no warning.
        n_1n = len(sch_records)
        hz_c6 = "cond_" + "6" * 32
        _vc({**json.loads(json.dumps(hz_base)), "conditions": [
            {"id": hz_c1, "type": "state", "entity_id": "switch.c",
             "state": "on"},
            {"id": hz_c2, "type": "cooldown", "seconds": 30},
            {"id": hz_c6, "type": "duration", "seconds": 60,
             "start": hz_c2, "abort": None},
        ], "outputs": [
            {"name": "o", "type": "switch", "entity_id": hz_o1,
             "on_conditions": [hz_c1], "off_conditions": [hz_c6]},
        ]})
        assert sum("start 恒真化" in r for r in sch_records[n_1n:]) == 1, (
            "a duration on the off chain armed solely by a cooldown keeps "
            "the delayed off-polarity trap — must warn (R1#3): "
            f"{sch_records[n_1n:]}"
        )
        n_1ng = len(sch_records)
        hz_c8 = "cond_" + "8" * 32
        _vc({**json.loads(json.dumps(hz_base)), "conditions": [
            {"id": hz_c1, "type": "state", "entity_id": "switch.c",
             "state": "on"},
            {"id": hz_c2, "type": "cooldown", "seconds": 30},
            {"id": hz_c8, "type": "and", "conditions": [hz_c2]},
            {"id": hz_c6, "type": "duration", "seconds": 60,
             "start": hz_c8, "abort": None},
        ], "outputs": [
            {"name": "o", "type": "switch", "entity_id": hz_o1,
             "on_conditions": [hz_c1], "off_conditions": [hz_c6]},
        ]})
        assert sum("start 恒真化" in r for r in sch_records[n_1ng:]) == 1, (
            "a pure-cooldown GROUP arming the start is the same delayed "
            f"trap shape as the direct one — must warn (R1#3): "
            f"{sch_records[n_1ng:]}"
        )
        n_1nm = len(sch_records)
        _vc({**json.loads(json.dumps(hz_base)), "conditions": [
            {"id": hz_c1, "type": "state", "entity_id": "switch.c",
             "state": "on"},
            {"id": hz_c2, "type": "cooldown", "seconds": 30},
            {"id": hz_c8, "type": "and", "conditions": [hz_c1, hz_c2]},
            {"id": hz_c6, "type": "duration", "seconds": 60,
             "start": hz_c8, "abort": None},
        ], "outputs": [
            {"name": "o", "type": "switch", "entity_id": hz_o1,
             "on_conditions": [hz_c1], "off_conditions": [hz_c6]},
        ]})
        assert len(sch_records) == n_1nm, (
            "mixing a live signal into the start group is the legitimate "
            "arming shape — the cooldown never gates the off verdict alone "
            f"there, no warning (R1#3 boundary): {sch_records[n_1nm:]}"
        )
        # ② route to an unreachable condition → warning (a legal leaf no
        # output chain reaches — wired on the canvas, wakes nothing)
        orphan_c = "cond_" + "e" * 32
        _vc({**json.loads(json.dumps(hz_base)), "conditions": [
            {"id": hz_c1, "type": "state", "entity_id": "switch.c",
             "state": "on"},
            {"id": orphan_c, "type": "state", "entity_id": "switch.d",
             "state": "on"},
        ], "outputs": [
            {"name": "o", "type": "switch", "entity_id": hz_o1,
             "on_conditions": [hz_c1], "off_conditions": []},
        ], "triggers": [{"id": "trg_" + "1" * 32, "type": "state",
                         "entity_id": "switch.c",
                         "routes": {"conditions": [hz_c1, orphan_c]}}]})
        assert sum("到不了任何输出" in r for r in sch_records) == 1, sch_records
        # ③ empty group referenced by an output chain → warning
        empty_g2 = "cond_" + "0" * 32
        n_r = len(sch_records)
        _vc({**json.loads(json.dumps(hz_base)), "conditions": [
            {"id": hz_c1, "type": "state", "entity_id": "switch.c",
             "state": "on"},
            {"id": empty_g2, "type": "or", "conditions": []},
        ], "outputs": [
            {"name": "o", "type": "switch", "entity_id": hz_o1,
             "on_conditions": [hz_c1, empty_g2], "off_conditions": []},
        ]})
        assert sum("空逻辑组" in r for r in sch_records) == 1, sch_records
        assert len(sch_records) == n_r + 1, (
            f"the unreachable-route warning must NOT repeat for an output-"
            f"chained empty group: {sch_records[n_r:]}"
        )
        # ③b a DISABLED empty group must NOT warn (F-336): the engine
        # short-circuits disabled conditions to True, so it is not
        # constant-False — same false-positive face the flag-side warning
        # already excludes (F-305)
        disabled_g = "cond_" + "9" * 32
        n_r2 = len(sch_records)
        _vc({**json.loads(json.dumps(hz_base)), "conditions": [
            {"id": hz_c1, "type": "state", "entity_id": "switch.c",
             "state": "on"},
            {"id": disabled_g, "type": "or", "conditions": [],
             "enabled": False},
        ], "outputs": [
            {"name": "o", "type": "switch", "entity_id": hz_o1,
             "on_conditions": [hz_c1, disabled_g], "off_conditions": []},
        ]})
        assert len(sch_records) == n_r2, (
            "a disabled empty group short-circuits to True in the engine — "
            f"it must not warn (F-336): {sch_records[n_r2:]}"
        )
        # ④ calendar as the only gate of an output → warning (the trigger is
        # re-anchored on the calendar condition itself: no other wakeup face)
        cal_id = "cond_" + "f" * 32
        _vc({**json.loads(json.dumps(hz_base)), "conditions": [
            {"id": cal_id, "type": "calendar",
             "entity_id": "calendar.x", "hours": 2},
        ], "outputs": [
            {"name": "o", "type": "switch", "entity_id": hz_o1,
             "on_conditions": [cal_id], "off_conditions": []},
        ], "triggers": [{"id": "trg_" + "1" * 32, "type": "state",
                         "entity_id": "switch.c",
                         "routes": {"conditions": [cal_id]}}]})
        assert sum("日历条件" in r for r in sch_records) == 1, sch_records
        # ④b F-346 discriminating pins: a DISABLED calendar is not a gate
        # (the engine treats it as constant True that never self-wakes) →
        # no warning; an ENABLED calendar whose only companion gate is
        # disabled still warns (that gate cannot wake the chain either).
        n_cal = len(sch_records)
        _vc({**json.loads(json.dumps(hz_base)), "conditions": [
            {"id": cal_id, "type": "calendar",
             "entity_id": "calendar.x", "hours": 2, "enabled": False},
        ], "outputs": [
            {"name": "o", "type": "switch", "entity_id": hz_o1,
             "on_conditions": [cal_id], "off_conditions": []},
        ], "triggers": [{"id": "trg_" + "1" * 32, "type": "state",
                         "entity_id": "switch.c",
                         "routes": {"conditions": [cal_id]}}]})
        assert len(sch_records) == n_cal, (
            "a disabled calendar is constant True in the engine — it must "
            f"not warn (F-346): {sch_records[n_cal:]}"
        )
        _vc({**json.loads(json.dumps(hz_base)), "conditions": [
            {"id": cal_id, "type": "calendar",
             "entity_id": "calendar.x", "hours": 2},
            {"id": "cond_" + "d" * 32, "type": "time", "after": "08:00",
             "enabled": False},
        ], "outputs": [
            {"name": "o", "type": "switch", "entity_id": hz_o1,
             "on_conditions": [cal_id, "cond_" + "d" * 32],
             "off_conditions": []},
        ], "triggers": [{"id": "trg_" + "1" * 32, "type": "state",
                         "entity_id": "switch.c",
                         "routes": {"conditions": [cal_id]}}]})
        assert len(sch_records) == n_cal + 1, (
            "an enabled calendar whose only companion gate is disabled must "
            f"still warn (F-346): {sch_records[n_cal:]}"
        )
        # ④c R1#1 third face: coverage is TOPOLOGICAL — a DISABLED condition
        # the signal line still covers wakes the chain on every trigger fire
        # (the routing index ignores enabled), so the enabled calendar beside
        # it must NOT warn. Red before the R1#1 arm split, green after.
        n_cov = len(sch_records)
        _vc({**json.loads(json.dumps(hz_base)), "conditions": [
            {"id": cal_id, "type": "calendar",
             "entity_id": "calendar.x", "hours": 2},
            {"id": "cond_" + "5" * 32, "type": "state", "entity_id": "switch.c",
             "state": "on", "enabled": False},
        ], "outputs": [
            {"name": "o", "type": "switch", "entity_id": hz_o1,
             "on_conditions": [cal_id, "cond_" + "5" * 32],
             "off_conditions": []},
        ], "triggers": [{"id": "trg_" + "1" * 32, "type": "state",
                         "entity_id": "switch.c",
                         "routes": {"conditions": ["cond_" + "5" * 32]}}]})
        assert len(sch_records) == n_cov, (
            "a disabled signal-covered condition still wakes the chain — "
            f"must not warn (R1#1): {sch_records[n_cov:]}"
        )
        # ④d R1#1 flag-edge face: the routing index walks the flag set/reset
        # edges and next_wakeup aims a directed wakeup at a flag's timer
        # members — [flag(set=duration), calendar] HAS a wakeup source and
        # must NOT warn. Red before the R1#1 route_reach switch, green after.
        _vc({**json.loads(json.dumps(hz_base)), "conditions": [
            {"id": cal_id, "type": "calendar",
             "entity_id": "calendar.x", "hours": 2},
            {"id": "cond_" + "6" * 32, "type": "state", "entity_id": "switch.d",
             "state": "on"},
            {"id": "cond_" + "7" * 32, "type": "duration", "seconds": 5,
             "start": "cond_" + "6" * 32, "abort": None},
            {"id": "cond_" + "8" * 32, "type": "flag",
             "set_conditions": ["cond_" + "7" * 32], "reset_conditions": []},
        ], "outputs": [
            {"name": "o", "type": "switch", "entity_id": hz_o1,
             "on_conditions": ["cond_" + "8" * 32, cal_id],
             "off_conditions": []},
        ], "triggers": [{"id": "trg_" + "1" * 32, "type": "state",
                         "entity_id": "switch.c",
                         "routes": {"conditions": ["cond_" + "6" * 32]}}]})
        assert len(sch_records) == n_cov, (
            "a flag's duration member is a wakeup source via the routing "
            f"index — must not warn (R1#1): {sch_records[n_cov:]}"
        )
        # ④e R2#1 live-graph pins (both directions of the adjacency
        # regression): the wakeup face must judge the LIVE edge set
        # (disabled subtrees pruned), not the raw routing set.
        # ④e-A false alarm: a disabled flag's set=[calendar] chain is dead
        # wiring — step_flags skips disabled flags, so the calendar is
        # never evaluated and must NOT warn. Red before the R2#1
        # live_reach split (route_reach walked the set edge), green after.
        n_live = len(sch_records)
        _vc({**json.loads(json.dumps(hz_base)), "conditions": [
            {"id": "cond_" + "1" * 32, "type": "calendar",
             "entity_id": "calendar.x", "hours": 2},
            {"id": "cond_" + "c" * 32, "type": "flag",
             "set_conditions": ["cond_" + "1" * 32],
             "reset_conditions": [], "enabled": False},
        ], "outputs": [
            {"name": "o", "type": "switch", "entity_id": hz_o1,
             "on_conditions": ["cond_" + "c" * 32], "off_conditions": []},
        ], "triggers": []})
        assert len(sch_records) == n_live, (
            "a calendar behind a disabled flag's set edge is dead wiring — "
            f"must not warn (R2#1): {sch_records[n_live:]}"
        )
        # ④e-B missed alarm (the dangerous half): [calendar,
        # flag(disabled, set=[duration])] — the routing set reaches the
        # duration through the flag edge and would silence the warning,
        # but the disabled flag never steps, the duration never starts,
        # and the chain's only real gate is the calendar. MUST warn. Red
        # before the R2#1 split (wakeup_types saw the dead duration),
        # green after.
        _vc({**json.loads(json.dumps(hz_base)), "conditions": [
            {"id": "cond_" + "1" * 32, "type": "calendar",
             "entity_id": "calendar.x", "hours": 2},
            {"id": "cond_" + "2" * 32, "type": "state", "entity_id": "switch.d",
             "state": "on"},
            {"id": "cond_" + "3" * 32, "type": "duration", "seconds": 5,
             "start": "cond_" + "2" * 32, "abort": None},
            {"id": "cond_" + "c" * 32, "type": "flag",
             "set_conditions": ["cond_" + "3" * 32],
             "reset_conditions": [], "enabled": False},
        ], "outputs": [
            {"name": "o", "type": "switch", "entity_id": hz_o1,
             "on_conditions": ["cond_" + "1" * 32, "cond_" + "c" * 32],
             "off_conditions": []},
        ], "triggers": []})
        assert len(sch_records) == n_live + 1, (
            "a duration behind a disabled flag never starts — the calendar "
            f"is the only gate and must warn (R2#1): {sch_records[n_live:]}"
        )
        # ④f R2#2 pin: signal coverage by a DISABLED trigger wakes
        # nothing (TriggerManager.async_setup skips disabled triggers — no
        # listener ever fires), so the wakeup face must count ENABLED
        # triggers only. Red before the wakeup_covered split (the raw
        # signal_covered set counted the dead line), green after.
        n_cov2 = len(sch_records)
        _vc({**json.loads(json.dumps(hz_base)), "conditions": [
            {"id": "cond_" + "1" * 32, "type": "calendar",
             "entity_id": "calendar.x", "hours": 2},
            {"id": "cond_" + "2" * 32, "type": "state", "entity_id": "switch.c",
             "state": "on", "enabled": False},
        ], "outputs": [
            {"name": "o", "type": "switch", "entity_id": hz_o1,
             "on_conditions": ["cond_" + "1" * 32, "cond_" + "2" * 32],
             "off_conditions": []},
        ], "triggers": [{"id": "trg_" + "2" * 32, "type": "state",
                         "entity_id": "switch.c",
                         "routes": {"conditions": ["cond_" + "2" * 32]},
                         "enabled": False}]})
        assert len(sch_records) == n_cov2 + 1, (
            "a state covered only by a disabled trigger never wakes the "
            f"chain — must warn (R2#2): {sch_records[n_cov2:]}"
        )
        # ④g R2#4 pin: a leaf's non-zero `for` is an independent wakeup
        # source — next_wakeup offers _for_timers beside _duration_timers,
        # and validation normalizes `for` to a non-zero
        # {hours,minutes,seconds} dict or drops the key — so
        # [state(for=…), calendar] with no signal coverage must NOT warn.
        # Red before the wakeup arm extension, green after.
        n_for = len(sch_records)
        _vc({**json.loads(json.dumps(hz_base)), "conditions": [
            {"id": "cond_" + "1" * 32, "type": "calendar",
             "entity_id": "calendar.x", "hours": 2},
            {"id": "cond_" + "2" * 32, "type": "state", "entity_id": "switch.d",
             "state": "on",
             "for": {"hours": 0, "minutes": 5, "seconds": 0}},
        ], "outputs": [
            {"name": "o", "type": "switch", "entity_id": hz_o1,
             "on_conditions": ["cond_" + "1" * 32, "cond_" + "2" * 32],
             "off_conditions": []},
        ], "triggers": []})
        assert len(sch_records) == n_for, (
            "a state with a non-zero `for` self-wakes via _for_timers — "
            f"must not warn (R2#4): {sch_records[n_for:]}"
        )
        # ④h R3#1 pin: a wall-clock gate (time) inside a DISABLED group
        # still wakes the chain — next_wakeup walks the flat condition
        # table and computes time edges from pure clock math, so the
        # wakeup arm must accept it from the topological set, not the
        # live set. Red before the R3#1 wall-clock split (live_ids pruned
        # the disabled group's members → false alarm), green after.
        n_wall = len(sch_records)
        _vc({**json.loads(json.dumps(hz_base)), "conditions": [
            {"id": "cond_" + "1" * 32, "type": "calendar",
             "entity_id": "calendar.x", "hours": 2},
            {"id": "cond_" + "2" * 32, "type": "time", "after": "08:00"},
            {"id": "cond_" + "a" * 32, "type": "and",
             "conditions": ["cond_" + "2" * 32], "enabled": False},
        ], "outputs": [
            {"name": "o", "type": "switch", "entity_id": hz_o1,
             "on_conditions": ["cond_" + "1" * 32, "cond_" + "a" * 32],
             "off_conditions": []},
        ], "triggers": []})
        assert len(sch_records) == n_wall, (
            "a time gate inside a disabled group still wakes via "
            "next_wakeup's flat-table wall-clock edges — must not warn "
            f"(R3#1): {sch_records[n_wall:]}"
        )
        # ④i R3#2 pin: a cooldown buried in a DISABLED group's members is
        # never evaluated (the group short-circuits to True) — the
        # off-chain polarity trap cannot exist there, so face ① must NOT
        # warn. respect_enabled keeps the disabled node reachable and
        # prunes only its outgoing edges. Red before (chain_reach walked
        # the dead members), green after.
        n_dead_cool = len(sch_records)
        _vc({**json.loads(json.dumps(hz_base)), "conditions": [
            {"id": "cond_" + "b" * 32, "type": "cooldown", "seconds": 60},
            {"id": "cond_" + "a" * 32, "type": "and",
             "conditions": ["cond_" + "b" * 32], "enabled": False},
        ], "outputs": [
            {"name": "o", "type": "switch", "entity_id": hz_o1,
             "on_conditions": [],
             "off_conditions": ["cond_" + "a" * 32]},
        ], "triggers": []})
        assert len(sch_records) == n_dead_cool, (
            "a cooldown behind a disabled group is never evaluated — its "
            "off-chain trap cannot exist, must not warn "
            f"(R3#2): {sch_records[n_dead_cool:]}"
        )
        # ④j R3#2 pin: an empty group behind a DISABLED group is likewise
        # dead — face ④ must NOT warn about the inner one (the outer group
        # itself has members and is exempt from the empty check). Red
        # before (the dead member was judged), green after.
        n_dead_empty = len(sch_records)
        _vc({**json.loads(json.dumps(hz_base)), "conditions": [
            {"id": "cond_" + "e" * 32, "type": "and", "conditions": []},
            {"id": "cond_" + "a" * 32, "type": "and",
             "conditions": ["cond_" + "e" * 32], "enabled": False},
        ], "outputs": [
            {"name": "o", "type": "switch", "entity_id": hz_o1,
             "on_conditions": ["cond_" + "a" * 32],
             "off_conditions": []},
        ], "triggers": []})
        assert len(sch_records) == n_dead_empty, (
            "an empty group behind a disabled group is never evaluated — "
            f"must not warn (R3#2): {sch_records[n_dead_empty:]}"
        )
        # R2#4: a countdown is an armable timer — face ⑤ must NOT fire for
        # a countdown-only chain (a running countdown self-wakes at its
        # deadline), while the same chain on tally (never self-wakes)
        # still warns; face ② keeps the calendar warning for calendar+
        # tally but not for calendar+countdown
        cd_w = "cond_" + "c" * 32
        cd_g = "cond_" + "d" * 32
        tl_w = "cond_" + "e" * 32
        n_r2w = len(sch_records)
        _vc({"name": "hazards",
             "conditions": [
                 {"id": cd_g, "type": "state", "entity_id": "switch.d",
                  "state": "on"},
                 {"id": cd_w, "type": "countdown", "seconds": 60,
                  "start_conditions": [cd_g], "reset_conditions": []},
             ],
             "triggers": [{"id": "trg_" + "2" * 32, "type": "state",
                           "entity_id": "switch.c",
                           "routes": {"conditions": []}}],
             "outputs": [{"name": "o", "type": "switch", "entity_id": hz_o1,
                          "on_conditions": [cd_w], "off_conditions": []}]})
        assert len(sch_records) == n_r2w, (
            f"a countdown-only chain self-wakes at its deadline — no "
            f"no-wakeup-source warning (R2#4): {sch_records[n_r2w:]}"
        )
        _vc({"name": "hazards",
             "conditions": [
                 {"id": cd_g, "type": "state", "entity_id": "switch.d",
                  "state": "on"},
                 {"id": tl_w, "type": "tally",
                  "count_conditions": [cd_g], "reset_conditions": []},
             ],
             "triggers": [{"id": "trg_" + "2" * 32, "type": "state",
                           "entity_id": "switch.c",
                           "routes": {"conditions": []}}],
             "outputs": [{"name": "o", "type": "switch", "entity_id": hz_o1,
                          "on_conditions": [tl_w], "off_conditions": []}]})
        assert sum("没有任何可唤醒源" in r for r in sch_records[n_r2w:]) == 1, (
            f"a tally never self-wakes — face ⑤ must still warn: "
            f"{sch_records[n_r2w:]}"
        )
        # face ② pair: calendar as the countdown's start gate — the
        # countdown counts as another wakeup, so no calendar-only warning;
        # with a tally in its place the warning fires
        n_r2c = len(sch_records)
        _vc({"name": "hazards",
             "conditions": [
                 {"id": cd_g, "type": "calendar", "entity_id": "calendar.x",
                  "hours": 2},
                 {"id": cd_w, "type": "countdown", "seconds": 60,
                  "start_conditions": [cd_g], "reset_conditions": []},
             ],
             "triggers": [{"id": "trg_" + "2" * 32, "type": "state",
                           "entity_id": "switch.c",
                           "routes": {"conditions": []}}],
             "outputs": [{"name": "o", "type": "switch", "entity_id": hz_o1,
                          "on_conditions": [cd_w], "off_conditions": []}]})
        assert len(sch_records) == n_r2c, (
            f"a calendar+countdown chain has another wakeup — no calendar "
            f"warning (R2#4): {sch_records[n_r2c:]}"
        )
        _vc({"name": "hazards",
             "conditions": [
                 {"id": cd_g, "type": "calendar", "entity_id": "calendar.x",
                  "hours": 2},
                 {"id": tl_w, "type": "tally",
                  "count_conditions": [cd_g], "reset_conditions": []},
             ],
             "triggers": [{"id": "trg_" + "2" * 32, "type": "state",
                           "entity_id": "switch.c",
                           "routes": {"conditions": []}}],
             "outputs": [{"name": "o", "type": "switch", "entity_id": hz_o1,
                          "on_conditions": [tl_w], "off_conditions": []}]})
        assert sum("日历条件" in r for r in sch_records[n_r2c:]) == 1, (
            f"a calendar+tally chain has no other wakeup — the calendar "
            f"warning must fire: {sch_records[n_r2c:]}"
        )
    finally:
        sch_logger.removeHandler(_sch_handler)
    print(
        "[PASS] schema static hazard warnings: off-chain cooldown, dead "
        "route, empty group, calendar-only output"
    )

    # ------------------------------------------------------------------
    # WHA-F-321: the editor preview button is the READ-ONLY observe path;
    # actuation only via the explicit "evaluate now" button behind the
    # overview's action confirm (panel.js is DOM-free in CI — pin the source
    # text so the wiring cannot silently regress).
    # ------------------------------------------------------------------
    panel_src = (
        ROOT / "custom_components" / "sensor_switch_controller" / "static" / "panel.js"
    ).read_text(encoding="utf-8")
    i_tr = panel_src.index("async _trialRun")
    i_en = panel_src.index("_evaluateNow() {")
    i_cl = panel_src.index("_clearTrialArtifacts(ed)", i_en)
    i_rt = panel_src.index("async _runTrial")
    assert i_tr < i_en < i_cl < i_rt, (
        "panel method layout changed — re-check the F-321 pin anchors"
    )
    trial_seg = panel_src[i_tr:i_en]
    assert "/observe" in trial_seg, "the preview button must call observe"
    assert "/evaluate" not in trial_seg, (
        "the preview button must NOT actuate (F-321 regression)"
    )
    evaluate_seg = panel_src[i_en:i_cl]
    assert "evaluateConfirmBody" in evaluate_seg, (
        "the evaluate-now button must sit behind the action confirm"
    )
    print("[PASS] WHA-F-321: editor preview is read-only, evaluate is confirmed")

    # ------------------------------------------------------------------
    # WHA-F-323 (discriminating pin): a template evaluation failure warns
    # once, stays silent inside the rate-limit window, and re-arms after it
    # — driven through the real evaluate path, not the helper directly.
    # ------------------------------------------------------------------
    import logging as _logging
    import custom_components.sensor_switch_controller.condition_engine as condition_engine_mod  # noqa: E402
    from custom_components.sensor_switch_controller.condition_engine import (  # noqa: E402
        _EVAL_FAILURE_WARN_INTERVAL,
        ConditionEngine,
    )

    f323_records = []

    class _F323Cap(_logging.Handler):
        def emit(self, record):
            f323_records.append(record.getMessage())

    f323_logger = _logging.getLogger(
        "custom_components.sensor_switch_controller.condition_engine"
    )
    _f323_handler = _F323Cap(level=_logging.WARNING)
    f323_logger.addHandler(_f323_handler)
    f323_tpl = "cond_" + "t" * 32

    class _BoomTemplate:
        def __init__(self, s, hass=None):
            self.s = s

        def async_render(self):
            raise RuntimeError("boom")

    orig_tpl = condition_engine_mod.Template
    condition_engine_mod.Template = _BoomTemplate
    try:
        f323_eng = ConditionEngine(
            _Hass(), [{"id": f323_tpl, "type": "template",
                       "value_template": "{{ boom }}"}]
        )
        met, _det = await f323_eng.evaluate_detailed([f323_tpl], None)
        assert met is False and _det[f323_tpl] is False, (met, _det)
        assert len(f323_records) == 1 and "failed" in f323_records[0], (
            f"the first failure must warn once (F-323): {f323_records}"
        )
        await f323_eng.evaluate_detailed([f323_tpl], None)
        assert len(f323_records) == 1, (
            f"a repeat inside the window must stay silent (F-323): {f323_records}"
        )
        _advance_utc(_EVAL_FAILURE_WARN_INTERVAL.total_seconds() + 1)
        await f323_eng.evaluate_detailed([f323_tpl], None)
        assert len(f323_records) == 2, (
            f"the window elapsing must re-arm the warning (F-323): {f323_records}"
        )
    finally:
        condition_engine_mod.Template = orig_tpl
        f323_logger.removeHandler(_f323_handler)
    print(
        "[PASS] WHA-F-323: eval-failure warning fires once, rate-limited, "
        "re-arms after the window"
    )

    # ------------------------------------------------------------------
    # WHA-F-324 (discriminating pin): a corrupt non-dict top-level store
    # payload passes through the migration untouched (warning, no
    # AttributeError) so async_load's own guard can degrade it loudly.
    # ------------------------------------------------------------------
    f324_records = []

    class _F324Cap(_logging.Handler):
        def emit(self, record):
            f324_records.append(record.getMessage())

    f324_logger = _logging.getLogger(
        "custom_components.sensor_switch_controller.hub"
    )
    _f324_handler = _F324Cap(level=_logging.WARNING)
    f324_logger.addHandler(_f324_handler)
    _hass_m = _Hass()
    hub_m = ScannerHub(_hass_m)
    corrupt = ["not", "a", "dict"]
    try:
        migrated = await hub_m.store._async_migrate_func(1, 0, corrupt)
        assert migrated is corrupt, (
            "a non-dict top-level payload must pass through untouched "
            f"(F-324), got {migrated!r}"
        )
        assert any("not an object" in m for m in f324_records), (
            f"the corrupt payload must warn (F-324): {f324_records}"
        )
    finally:
        f324_logger.removeHandler(_f324_handler)
    print(
        "[PASS] WHA-F-324: non-dict top-level store payload passes through "
        "with a warning, no crash"
    )

    # ------------------------------------------------------------------
    # Stateful step nodes (0.14.0, WHA-STATEFUL-123): one mechanism, three
    # parameterizations. Pins are discriminating (F-343 教训): every face
    # asserts the value AND a wrong-polarity/wrong-count counterexample.
    # ------------------------------------------------------------------
    from custom_components.sensor_switch_controller.schema import (
        ControllerValidationError,
    )
    from custom_components.sensor_switch_controller.const import STORE_VERSION

    st_cd = "cond_" + "c" * 32  # countdown (start=switch.c, reset=switch.d)
    st_qt = "cond_" + "d" * 32  # quota ×2 (consume=switch.c, reset=switch.d)
    st_tl = "cond_" + "e" * 32  # tally (count=switch.c, reset=switch.d)
    st_snap = "cond_" + "f" * 32  # snapshot (capture=[countdown])
    st_out = "ssc_" + "9" * 32
    st_trg = "trg_" + "8" * 32

    def _st_cfg(with_snap: bool) -> dict:
        conds = [
            {"id": st_cd, "type": "countdown", "label": "cd", "enabled": True,
             "seconds": 60, "start_conditions": ["cond_" + "a" * 32],
             "reset_conditions": ["cond_" + "b" * 32]},
            {"id": st_qt, "type": "quota", "label": "qt", "enabled": True,
             "times": 2, "consume_conditions": ["cond_" + "a" * 32],
             "reset_conditions": ["cond_" + "b" * 32]},
            {"id": st_tl, "type": "tally", "label": "tl", "enabled": True,
             "count_conditions": ["cond_" + "a" * 32],
             "reset_conditions": ["cond_" + "b" * 32]},
            {"id": "cond_" + "a" * 32, "type": "state", "label": "", "enabled": True,
             "entity_id": "switch.c", "state": "on"},
            {"id": "cond_" + "b" * 32, "type": "state", "label": "", "enabled": True,
             "entity_id": "switch.d", "state": "on"},
        ]
        chains = [st_cd, st_qt, st_tl]
        if with_snap:
            conds.append(
                {"id": st_snap, "type": "snapshot", "label": "snap", "enabled": True,
                 "entity_id": "sensor.a", "capture": [st_cd], "clear": []}
            )
            chains = [st_snap]
        return {
            "name": "stful",
            "enabled": True,
            "logging_enabled": False,
            "triggers": [{"id": st_trg, "type": "state", "entity_id": "switch.c",
                          "enabled": True, "routes": {"conditions": ["cond_" + "a" * 32]}}],
            "conditions": conds,
            "outputs": [{"name": "o", "type": "switch", "entity_id": st_out,
                         "on_conditions": chains, "off_conditions": []}],
        }

    # engine level: edge vs level (防连环扣/连环加), same-cycle reset wins,
    # quota zero polarity, latch flip-back, wakeup offers
    eng_st = ConditionEngine(
        _Hass(), json.loads(json.dumps(_st_cfg(with_snap=True)["conditions"]))
    )
    vals = eng_st.stateful_values()
    ev = await eng_st.step_stateful()
    # all gates high (switch.c on, switch.d off): reset absent, edges fire
    assert vals[st_cd]["deadline"] == _clock["utc"] + timedelta(seconds=60), vals[st_cd]
    assert vals[st_qt]["remaining"] == 1 and vals[st_qt]["verdict"] is True, vals[st_qt]
    assert vals[st_tl]["count"] == 1 and vals[st_tl]["verdict"] is True, vals[st_tl]
    # 边沿 vs 电平: the gates STAY high → nothing moves again
    ev = await eng_st.step_stateful()
    assert ev == {}, f"a level-held gate must act once only: {ev}"
    assert vals[st_qt]["remaining"] == 1 and vals[st_tl]["count"] == 1
    # running countdown offers its deadline to the reverse index; quota and
    # tally never self-wake (无自唤醒)
    rev = {st_cd: {st_out}, st_qt: {st_out}, st_tl: {st_out}, st_snap: {st_out}}
    pending = eng_st.next_wakeup(rev)
    assert pending is not None and pending[0] == _clock["utc"] + timedelta(seconds=60), pending
    assert pending[1] == {st_out}, pending
    # advance past the deadline → the NEXT step latches (归零锁存 true)
    _advance_utc(120)
    ev = await eng_st.step_stateful()
    assert ev[st_cd]["flipped"] is True, ev
    assert eng_st.stateful_values()[st_cd]["verdict"] is True
    # latched countdown offers nothing, and so do quota/tally ever
    assert eng_st.next_wakeup(rev) is None
    # 锁存翻回 #1: start rise → 瞬间翻 false + 回满重走
    _hass_st = eng_st.hass
    _hass_st.states._d["switch.c"] = "off"
    await eng_st.step_stateful()  # gate drops, prev advances
    _hass_st.states._d["switch.c"] = "on"
    ev = await eng_st.step_stateful()  # fresh rising edge → restart
    assert ev[st_cd]["flipped"] is True, ev
    assert eng_st.stateful_values()[st_cd]["verdict"] is False
    assert eng_st.stateful_values()[st_cd]["deadline"] == _clock["utc"] + timedelta(seconds=60)
    # 余量 0 拦截极性: the consume that TAKES the last unit reports True,
    # the NEXT attempt (gate drop → rise at 0) reports False — a pinned-True
    # at zero would be the cooldown off-side polarity trap
    assert eng_st.stateful_values()[st_qt]["remaining"] == 0
    assert eng_st.stateful_values()[st_qt]["verdict"] is True  # last unit allowed
    _hass_st.states._d["switch.c"] = "off"
    await eng_st.step_stateful()
    _hass_st.states._d["switch.c"] = "on"
    ev = await eng_st.step_stateful()
    assert eng_st.stateful_values()[st_qt]["verdict"] is False, (
        f"consume at remaining=0 must report False (拦截): {ev}"
    )
    assert ev[st_qt]["flipped"] is True
    # 同拍 reset 优先: reset rises while the gates are high → the reset wins
    # and the gate edge is consumed (quota stays FULL, countdown stays idle)
    _hass_st.states._d["switch.d"] = "on"
    ev = await eng_st.step_stateful()
    assert eng_st.stateful_values()[st_qt]["remaining"] == 2, (
        f"same-cycle reset must win over consume: {ev}"
    )
    assert eng_st.stateful_values()[st_cd]["deadline"] is None
    assert eng_st.stateful_values()[st_tl]["count"] == 0
    assert eng_st.stateful_values()[st_cd]["verdict"] is False  # reset 翻 false
    # 锁存翻回 #2: reset while latched → verdict False (engine-fresh check)
    eng_rst = ConditionEngine(_Hass(), json.loads(json.dumps(_st_cfg(True)["conditions"][:1] + _st_cfg(True)["conditions"][3:])))
    eng_rst._stateful_values[st_cd] = {"verdict": True, "deadline": _clock["utc"], "prev_gate": False, "prev_reset": False}
    _hass_r = eng_rst.hass
    _hass_r.states._d["switch.c"] = "off"
    _hass_r.states._d["switch.d"] = "on"
    ev = await eng_rst.step_stateful()
    assert eng_rst.stateful_values()[st_cd]["verdict"] is False, ev
    assert eng_rst.stateful_values()[st_cd]["deadline"] is None
    # tally 透传: gate low → verdict False while the count persists
    _hass_st.states._d["switch.c"] = "off"
    _hass_st.states._d["switch.d"] = "off"
    ev = await eng_st.step_stateful()
    assert ev[st_tl]["flipped"] is True, ev
    assert eng_st.stateful_values()[st_tl]["verdict"] is False
    assert eng_st.stateful_values()[st_tl]["count"] == 0  # reset already fired
    print("[PASS] stateful engine: edge/level, reset-wins, zero polarity, latch flip-back, no self-wakeup")

    # R2#2: a never-acted tally stays ENTRY-FREE — the verdict key is only
    # written on a change, so the first-movement guard keeps its meaning
    # (pre-fix every tally dropped a {verdict:False} entry on first sight)
    eng_tl = ConditionEngine(
        _Hass(), json.loads(json.dumps(_st_cfg(with_snap=False)["conditions"]))
    )
    eng_tl.hass.states._d["switch.c"] = "off"  # count/consume gates low
    await eng_tl.step_stateful()
    assert not any(
        nid in eng_tl.stateful_values() for nid in (st_cd, st_qt, st_tl)
    ), (
        f"no-action stateful nodes must not create fifth-table entries: "
        f"{eng_tl.stateful_values()}"
    )
    # counterface: a rising count gate DOES land the entry (verdict + count)
    eng_tl.hass.states._d["switch.c"] = "on"
    await eng_tl.step_stateful()
    assert eng_tl.stateful_values()[st_tl] == {
        "count": 1, "verdict": True, "prev_gate": True, "prev_reset": False,
    }, eng_tl.stateful_values()[st_tl]
    print("[PASS] stateful R2#2: no-action tally stays entry-free, acting tally lands")

    # R2#5: quota parameter tuning — a persisted remaining above a LOWERED
    # times clamps down on the next step and writes through
    # (X=5 用 1 → 改 X=2 → seed remaining=4 → 2)
    eng_cl = ConditionEngine(
        _Hass(), json.loads(json.dumps(_st_cfg(with_snap=False)["conditions"]))
    )
    eng_cl.hass.states._d["switch.c"] = "off"  # no consume edge this step
    eng_cl._stateful_values[st_qt] = {
        "remaining": 4, "verdict": True,
        "prev_gate": False, "prev_reset": False,
    }
    ev_cl = await eng_cl.step_stateful()
    assert eng_cl.stateful_values()[st_qt]["remaining"] == 2, (
        f"remaining must clamp to the lowered times: "
        f"{eng_cl.stateful_values()[st_qt]}"
    )
    assert ev_cl.get(st_qt, {}).get("flipped") is False, ev_cl
    print("[PASS] stateful R2#5: lowered times clamps the persisted remaining")

    # controller level: the deadline flip drives the output in ONE cycle and
    # the snapshot capture gate reading the countdown converges same-cycle
    # (the F-427 mirror — without the re-step the capture would wait for a
    # second cycle that never comes)
    st_valid = validate_controller(json.loads(json.dumps(_st_cfg(with_snap=True))))
    hass_stc = _Hass()
    hub_stc = ScannerHub(hass_stc)
    hass_stc.data["sensor_switch_controller"] = hub_stc
    mgr_stc = ControllerManager(hass_stc, "ctrl_stful01", json.loads(json.dumps(st_valid)))
    ent_st = _Entity("switch.out_st")
    mgr_stc.register_entity(st_out, ent_st)
    await mgr_stc._async_evaluate(None, ["init"], None)
    assert ent_st.is_on is False, "a running countdown must not fire its output"
    _advance_utc(120)
    await mgr_stc._async_evaluate(None, ["zero"], None)
    assert ent_st.is_on is True, "the zero-cross cycle must latch AND flip the output"
    assert mgr_stc.engine.snapshots().get(st_snap) == 16.7, (
        "the snapshot capture gate reading the countdown must converge in "
        "the SAME cycle (F-427 mirror)"
    )
    assert hub_stc.stateful_states["ctrl_stful01"][st_cd]["verdict"] is True
    # R2#9 + F-461 read faces: runtime_snapshot mirrors the fifth table
    # (deadline ISO) and the snapshot latch values
    rt = mgr_stc.runtime_snapshot()
    assert rt["stateful"][st_cd]["verdict"] is True, rt["stateful"]
    assert isinstance(rt["stateful"][st_cd]["deadline"], str), rt["stateful"]
    assert rt["snapshots"].get(st_snap) == 16.7, rt["snapshots"]
    mgr_stc.async_unload()
    print("[PASS] stateful controller: zero-cross latch drives output + snapshot gate converges same-cycle")

    # R2#3: a convergence re-step capture reaches the decision log — the
    # countdown zero-cross flips the verdict inside the stateful pass, the
    # snapshot capture fires in the RE-step, and the cycle's log must carry
    # the decision=capture row (pre-fix only first-pass snap events logged)
    cfg_log = json.loads(json.dumps(st_valid))
    cfg_log["logging_enabled"] = True
    hass_lg = _Hass()
    hub_lg = ScannerHub(hass_lg)
    hass_lg.data["sensor_switch_controller"] = hub_lg
    mgr_lg = ControllerManager(hass_lg, "ctrl_stful06", cfg_log)
    mgr_lg.register_entity(st_out, _Entity("switch.out_lg"))
    recs_lg = _log_cycles("ctrl_stful06")
    await mgr_lg._async_evaluate(None, ["init"], None)  # starts the countdown
    assert not [
        r for r in _log_tail(recs_lg, "ctrl_stful06")
        if r.get("decision") == "capture"
    ], "a running countdown must not capture yet"
    _advance_utc(120)
    await mgr_lg._async_evaluate(None, ["zero"], None)
    caps_lg = [
        r for r in _log_tail(recs_lg, "ctrl_stful06")
        if r.get("decision") == "capture"
    ]
    assert len(caps_lg) == 1, (
        f"the convergence re-step capture must land a decision=capture row: "
        f"{caps_lg}"
    )
    mgr_lg.async_unload()
    print("[PASS] stateful R2#3: convergence re-step capture reaches the decision log")

    # R2#8: the two non-trigger entrances step the stateful table too
    # (three entrances unified — deleting either _step_stateful_and_persist
    # call would leave the fifth table empty and these pins red)
    hass_d1 = _Hass()
    hub_d1 = ScannerHub(hass_d1)
    hass_d1.data["sensor_switch_controller"] = hub_d1
    mgr_d1 = ControllerManager(
        hass_d1, "ctrl_stful07", json.loads(json.dumps(st_valid))
    )
    mgr_d1.register_entity(st_out, _Entity("switch.out_d1"))
    await mgr_d1.async_evaluate_with_details()
    assert hub_d1.stateful_states["ctrl_stful07"][st_qt]["remaining"] == 1, (
        "the details entrance must consume the quota (stateful stepped)"
    )
    assert hub_d1.stateful_states["ctrl_stful07"][st_cd]["deadline"], (
        "the details entrance must start the countdown"
    )
    mgr_d1.async_unload()
    hass_d2 = _Hass()
    hub_d2 = ScannerHub(hass_d2)
    hass_d2.data["sensor_switch_controller"] = hub_d2
    mgr_d2 = ControllerManager(
        hass_d2, "ctrl_stful08", json.loads(json.dumps(st_valid))
    )
    mgr_d2.register_entity(st_out, _Entity("switch.out_d2"))
    await mgr_d2.async_evaluate_output(st_out)
    assert hub_d2.stateful_states["ctrl_stful08"][st_qt]["remaining"] == 1, (
        "the service entrance must consume the quota (stateful stepped)"
    )
    mgr_d2.async_unload()
    print("[PASS] stateful R2#8: details/service entrances step the fifth table")

    # persistence / restart wall-clock 续走: the stored deadline is an
    # absolute instant — a rebuilt manager continues to zero by wall-clock
    # difference (downtime counts), quota/tally restore verbatim
    hass_wl = _Hass()
    hub_wl = ScannerHub(hass_wl)
    hass_wl.data["sensor_switch_controller"] = hub_wl
    mgr_wl = ControllerManager(hass_wl, "ctrl_stful02", json.loads(json.dumps(st_valid)))
    mgr_wl.register_entity(st_out, _Entity("switch.out_wl"))
    await mgr_wl._async_evaluate(None, ["init"], None)  # starts countdown, consumes 1
    stored_dl = hub_wl.stateful_states["ctrl_stful02"][st_cd]["deadline"]
    assert isinstance(stored_dl, str), stored_dl
    stored_rem = hub_wl.stateful_states["ctrl_stful02"][st_qt]["remaining"]
    assert stored_rem == 1 and hub_wl.stateful_states["ctrl_stful02"][st_tl]["count"] == 1
    mgr_wl.async_unload()
    _advance_utc(45)  # restart 45s later — 15s of the budget must remain
    mgr_wl2 = ControllerManager(hass_wl, "ctrl_stful02", json.loads(json.dumps(st_valid)))
    ent_wl2 = _Entity("switch.out_wl2")
    mgr_wl2.register_entity(st_out, ent_wl2)
    seeded = mgr_wl2.engine.stateful_values()
    assert seeded[st_qt]["remaining"] == 1 and seeded[st_tl]["count"] == 1, (
        f"quota/tally must restore verbatim (原值恢复): {seeded}"
    )
    _advance_utc(16)  # the remaining 15s elapse
    await mgr_wl2._async_evaluate(None, ["wakeup"], None)
    assert mgr_wl2.engine.stateful_values()[st_cd]["verdict"] is True, (
        "the countdown must continue to zero by wall-clock difference "
        "(壁钟续走到零锁存)"
    )
    assert ent_wl2.is_on is True
    # discriminate: the deadline did NOT restart at the rebuild — the stored
    # instant is preserved verbatim through the reload
    assert hub_wl.stateful_states["ctrl_stful02"][st_cd]["deadline"] == stored_dl
    mgr_wl2.async_unload()
    # a latched countdown re-latches after an even LONGER outage (到零即锁存,
    # self-healing the verdict from the deadline alone)
    hass_wl3 = _Hass()
    hub_wl3 = ScannerHub(hass_wl3)
    hass_wl3.data["sensor_switch_controller"] = hub_wl3
    hub_wl3.stateful_states["ctrl_stful03"] = {
        st_cd: {"verdict": False, "deadline": stored_dl, "prev_gate": True,
                "prev_reset": False},
    }
    mgr_wl3 = ControllerManager(hass_wl3, "ctrl_stful03", json.loads(json.dumps(st_valid)))
    assert mgr_wl3.engine.stateful_values()[st_cd]["verdict"] is False
    _advance_utc(86400)
    await mgr_wl3._async_evaluate(None, ["init"], None)
    assert mgr_wl3.engine.stateful_values()[st_cd]["verdict"] is True, (
        "a deadline long past must re-latch on the first cycle"
    )
    mgr_wl3.async_unload()
    print("[PASS] stateful persistence: wall-clock 续走, 原值恢复, deadline self-heal")

    # hub fifth-table ladder: a 0.13.0 four-table payload (no stateful key)
    # loads silently; wrong-typed fields drop loudly and the good ones stay
    class _StStore:
        """Injectable-load recording store (the module-level _Store stub is
        a no-op; this pin must observe the load face)."""

        def __init__(self):
            self.saved = []
            self.load_result = None

        async def async_load(self):
            return self.load_result

        async def async_save(self, data):
            self.saved.append(data)

        def async_delay_save(self, data_func, delay=0):
            self.saved.append(data_func())

    hub_l = ScannerHub(_Hass())
    hub_l._flag_store = _StStore()
    await hub_l.async_load_flag_states()  # missing file (None) → silent
    assert hub_l.stateful_states == {}
    hub_l._flag_store.load_result = {
        "flags": {}, "last_flip": {}, "snapshots": {}, "snapshot_gates": {},
    }
    await hub_l.async_load_flag_states()
    assert hub_l.stateful_states == {}, "the 0.13.0 four-table shape must stay silent"
    hub_l._flag_store.load_result = {
        "flags": {}, "last_flip": {},
        "stateful": {"ctrl_stful04": {
            st_cd: {"verdict": "yes", "deadline": 5, "prev_gate": True},
            st_qt: {"remaining": True, "verdict": False},
            "cond_nodict": 7,
        }},
    }
    await hub_l.async_load_flag_states()
    tbl = hub_l.stateful_states["ctrl_stful04"]
    assert tbl[st_cd] == {"prev_gate": True}, tbl[st_cd]
    assert tbl[st_qt] == {"verdict": False}, tbl[st_qt]  # bool verdict kept
    assert "cond_nodict" not in tbl
    # drop 成对清理 (F-449 先例): deleting a controller erases the fifth table
    await hub_l.async_save_stateful("ctrl_stful05", {st_cd: {"verdict": True}})
    assert "ctrl_stful05" in hub_l.stateful_states
    await hub_l.async_drop_flag_states("ctrl_stful05")
    assert "ctrl_stful05" not in hub_l.stateful_states
    print("[PASS] stateful hub: 0.13.0 payload silent, bad values self-heal, drop pairs")

    # R2#1 (P2): naive ISO deadline — a hand-edited offset-less store value
    # must load (normalized to UTC at the manager's single tz gate), seed
    # the engine AWARE, and the evaluation cycle must run instead of
    # TypeError-ing on the aware/naive compare. The stub clock is naive by
    # default — this pin explicitly aware-ifies clock + as_utc for the run.
    _dtmod = sys.modules["homeassistant.util.dt"]
    _saved_as_utc = _dtmod.as_utc
    _saved_utc = _clock["utc"]
    _dtmod.as_utc = lambda v: (
        v.replace(tzinfo=timezone.utc)
        if v is not None and getattr(v, "tzinfo", None) is None
        else v
    )
    _clock["utc"] = _saved_utc.replace(tzinfo=timezone.utc)
    try:
        hub_nz = ScannerHub(_Hass())
        hub_nz._flag_store = _StStore()
        hub_nz._flag_store.load_result = {
            "flags": {}, "last_flip": {}, "snapshots": {}, "snapshot_gates": {},
            "stateful": {"ctrl_stful10": {
                st_cd: {"verdict": False, "deadline": "2026-10-06T02:00:00",
                        "prev_gate": True, "prev_reset": False},
            }},
        }
        await hub_nz.async_load_flag_states()
        hass_nz = _Hass()
        hass_nz.data["sensor_switch_controller"] = hub_nz
        mgr_nz = ControllerManager(
            hass_nz, "ctrl_stful10", json.loads(json.dumps(st_valid))
        )
        seeded_dl = mgr_nz.engine.stateful_values()[st_cd]["deadline"]
        assert seeded_dl is not None and seeded_dl.tzinfo is not None, (
            f"the load ladder must normalize a naive deadline at its single "
            f"tz gate: {seeded_dl!r}"
        )
        mgr_nz.register_entity(st_out, _Entity("switch.out_nz"))
        await mgr_nz._async_evaluate(None, ["init"], None)  # must not TypeError
        assert mgr_nz.engine.stateful_values()[st_cd]["verdict"] is True, (
            "a naive past deadline must latch on the first cycle"
        )
        mgr_nz.async_unload()
    finally:
        _dtmod.as_utc = _saved_as_utc
        _clock["utc"] = _saved_utc
    print("[PASS] stateful R2#1: naive deadline seeds aware, cycle runs, latch fires")

    # ------------------------------------------------------------------
    # R1#5 (P3): naive ISO last_flip — the cooldown sibling of the R2#1
    # deadline fix. A hand-edited offset-less flip timestamp must seed
    # AWARE (as_utc at the manager's seeding exit) and the cooldown
    # comparison must evaluate instead of TypeError-ing every cycle
    # (aware utcnow − naive flip → the per-cid except fail-closes the
    # gate to False forever and the stale value is never overwritten).
    # Also pins the hub-side parseability gate: an unparseable flip
    # string is dropped loudly at the store exit. The stub clock is naive
    # by default — same aware-ify swap as the R2#1 pin above.
    # ------------------------------------------------------------------
    _saved_as_utc5 = _dtmod.as_utc
    _saved_utc5 = _clock["utc"]
    _dtmod.as_utc = lambda v: (
        v.replace(tzinfo=timezone.utc)
        if v is not None and getattr(v, "tzinfo", None) is None
        else v
    )
    _clock["utc"] = _saved_utc5.replace(tzinfo=timezone.utc)

    class _R15Cap(_logging.Handler):
        def __init__(self):
            super().__init__()
            self.records: list = []

        def emit(self, record):
            self.records.append(record.getMessage())

    _r15_logger = _logging.getLogger(
        "custom_components.sensor_switch_controller.hub"
    )
    _r15_handler = _R15Cap()
    _r15_logger.addHandler(_r15_handler)
    try:
        hub_mf = ScannerHub(_Hass())
        hub_mf._flag_store = _StStore()
        mf_out = "ssc_" + "7" * 32
        hub_mf._flag_store.load_result = {
            "flags": {},
            "last_flip": {
                "ctrl_mflip": {
                    mf_out: "2026-10-06T01:00:00",  # naive ISO (R1#5 shape)
                    "ssc_bad": "not-a-date",  # unparseable → dropped loudly
                },
            },
            "snapshots": {}, "snapshot_gates": {}, "stateful": {},
        }
        await hub_mf.async_load_flag_states()
        assert set(hub_mf.last_flips.get("ctrl_mflip") or {}) == {mf_out}, (
            f"the store exit must drop only the unparseable flip entry "
            f"and keep the parseable naive ISO: {hub_mf.last_flips}"
        )
        assert any(
            "Dropping 1 malformed last-flip" in m for m in _r15_handler.records
        ), _r15_handler.records
        mf_cfg = _vc(json.loads(json.dumps({
            "name": "flip-naive", "enabled": True, "logging_enabled": False,
            "triggers": [{"id": "trg_" + "7" * 32, "type": "state",
                          "entity_id": "switch.c",
                          "routes": {"conditions": ["cond_" + "5" * 32]}}],
            "conditions": [
                {"id": "cond_" + "5" * 32, "type": "cooldown", "seconds": 60},
            ],
            "outputs": [
                {"name": "out-mf", "type": "switch", "entity_id": mf_out,
                 "on_conditions": ["cond_" + "5" * 32], "off_conditions": []},
            ],
        })))
        hass_mf = _Hass()
        hass_mf.data[_DOM] = hub_mf
        mgr_mf = ControllerManager(hass_mf, "ctrl_mflip", mf_cfg)
        seeded_mf = mgr_mf.last_flip_at(mf_out)
        assert seeded_mf is not None and seeded_mf.tzinfo is not None, (
            "the seeding exit must normalize a naive flip to aware "
            f"(R1#5, R2#1 shape): {seeded_mf!r}"
        )
        met_mf, det_mf = await mgr_mf.engine.evaluate_detailed(
            ["cond_" + "5" * 32], mf_out
        )
        assert met_mf is True, (
            "the cooldown must evaluate (1h since flip > 60s) — a "
            f"TypeError regression would fail-close it to False: {det_mf}"
        )
        mgr_mf.async_unload()
    finally:
        _dtmod.as_utc = _saved_as_utc5
        _clock["utc"] = _saved_utc5
        _r15_logger.removeHandler(_r15_handler)
    print("[PASS] R1#5: naive last_flip seeds aware + cooldown evaluates; "
          "unparseable dropped at load")

    # store version epoch: v9 with an empty v8→v9 controller chain — a real
    # 0.13.0-shaped payload migrates and still validates (教训 R2: 迁移产物
    # →validate 全链冒烟)
    assert STORE_VERSION == 9, STORE_VERSION
    v13_cfg = {
        "name": "v13",
        "conditions": [
            {"id": CID1, "type": "state", "label": "", "enabled": True,
             "entity_id": "sensor.a", "state": "on"},
            {"id": CID2, "type": "flag", "label": "", "enabled": True,
             "set_conditions": [CID1], "reset_conditions": [], "initial": False},
        ],
        "outputs": [{"name": "o", "type": "switch", "entity_id": OID1,
                     "on_conditions": [CID2], "off_conditions": []}],
        "triggers": [{"id": TID1, "type": "state", "entity_id": "sensor.a",
                      "enabled": True, "routes": {"conditions": [CID1]}}],
    }
    hub_mig = ScannerHub(_Hass())
    migrated9 = await hub_mig.store._async_migrate_func(
        8, 1, {"controllers": {"ctrl_v13x1": v13_cfg}}
    )
    validate_controller(migrated9["controllers"]["ctrl_v13x1"])
    # every historical chain still lands valid (v2..v8 dispatch unchanged)
    for old_v in (2, 5, 8):
        migrated = await hub_mig.store._async_migrate_func(
            old_v, 1, {"controllers": {"ctrl_v13x1": json.loads(json.dumps(v13_cfg))}}
        )
        validate_controller(migrated["controllers"]["ctrl_v13x1"])
    print("[PASS] store v9: v8→v9 epoch chain + historical chains all validate")

    # schema faces: self-reference (direct + closure), dead gate, route
    # target, parameter ranges — each rejected with a visible message
    def _st_fail(cfg, frag):
        try:
            validate_controller(cfg)
        except ControllerValidationError as err:
            assert frag in str(err), (frag, str(err))
            return
        raise AssertionError(f"expected failure containing {frag!r}")

    _cfg_self = json.loads(json.dumps(st_valid))
    _cfg_self["conditions"][0]["start_conditions"] = [st_cd]
    _st_fail(_cfg_self, "不能直接以自身作为")
    _cfg_closure = json.loads(json.dumps(st_valid))
    _grp_id = "cond_" + "77" * 16
    _cfg_closure["conditions"].append(
        {"id": _grp_id, "type": "or", "label": "", "enabled": True,
         "conditions": ["cond_" + "a" * 32, st_cd]}
    )
    _cfg_closure["conditions"][0]["start_conditions"] = [_grp_id]
    _st_fail(_cfg_closure, "引用了自身")
    _cfg_dead = json.loads(json.dumps(st_valid))
    _cool_id = "cond_" + "88" * 16
    _cfg_dead["conditions"].append(
        {"id": _cool_id, "type": "cooldown", "label": "", "enabled": True, "seconds": 60}
    )
    _cfg_dead["conditions"][2]["count_conditions"] = [_cool_id]
    _st_fail(_cfg_dead, "恒不成立")
    _cfg_route = json.loads(json.dumps(st_valid))
    _cfg_route["triggers"][0]["routes"] = {"conditions": [st_qt]}
    _st_fail(_cfg_route, "都不是信号起点")
    _cfg_range = json.loads(json.dumps(st_valid))
    _cfg_range["conditions"][0]["seconds"] = 86401
    _st_fail(_cfg_range, "seconds 必须在 1-")
    _cfg_range["conditions"][0]["seconds"] = 60
    _cfg_range["conditions"][1]["times"] = 0
    _st_fail(_cfg_range, "times 必须在 1-")
    # F-459 discriminating pair (snapshot clear vs capture through abort)
    _dur_id = "cond_" + "99" * 16
    _cfg_clear = json.loads(json.dumps(st_valid))
    _cfg_clear["conditions"].append(
        {"id": _dur_id, "type": "duration", "label": "", "enabled": True,
         "seconds": 5, "start": "cond_" + "a" * 32, "abort": st_snap}
    )
    _cfg_clear["conditions"][5]["clear"] = [_dur_id]
    _st_fail(_cfg_clear, "引用了自身")
    _cfg_cap = json.loads(json.dumps(st_valid))
    _cfg_cap["conditions"].append(
        {"id": _dur_id, "type": "duration", "label": "", "enabled": True,
         "seconds": 5, "start": "cond_" + "a" * 32, "abort": st_snap}
    )
    _cfg_cap["conditions"][5]["capture"] = [_dur_id]
    validate_controller(_cfg_cap)  # one-shot self-reset via abort stays legal
    # R2#8: the same abort split for a stateful reset gate — the RESET gate
    # self-reads through the duration abort input (rejected); the PRIMARY
    # gate keeps the one-shot self-reset legal
    _cfg_cdr = json.loads(json.dumps(st_valid))
    _cfg_cdr["conditions"].append(
        {"id": _dur_id, "type": "duration", "label": "", "enabled": True,
         "seconds": 5, "start": "cond_" + "a" * 32, "abort": st_cd}
    )
    _cfg_cdr["conditions"][0]["reset_conditions"] = [_dur_id]
    _st_fail(_cfg_cdr, "引用了自身")
    _cfg_cds = json.loads(json.dumps(st_valid))
    _cfg_cds["conditions"].append(
        {"id": _dur_id, "type": "duration", "label": "", "enabled": True,
         "seconds": 5, "start": "cond_" + "a" * 32, "abort": st_cd}
    )
    _cfg_cds["conditions"][0]["start_conditions"] = [_dur_id]
    validate_controller(_cfg_cds)  # primary-gate one-shot self-reset legal
    print("[PASS] stateful schema: self-ref/dead-gate/route/params rejected, F-459+R2#8 abort pairs split")

    # ------------------------------------------------------------------
    # 0.16.0 trip leaves: schema face — ordinary leaves (`for` applies,
    # routes naming them are LEGAL signal origins), parameter ranges,
    # entity validation.
    # ------------------------------------------------------------------
    trp_leaf = "cond_" + "e" * 32
    trp_trg = "trg_" + "e" * 32
    trp_out = "ssc_" + "e" * 32

    def _trip_base(conds):
        return {
            "name": "trip",
            "enabled": True,
            "logging_enabled": False,
            "triggers": [{"id": trp_trg, "type": "state",
                          "entity_id": "binary_sensor.trip",
                          "enabled": True,
                          "routes": {"conditions": [trp_leaf]}}],
            "conditions": conds,
            "outputs": [{"name": "o", "type": "switch", "entity_id": trp_out,
                         "on_conditions": [trp_leaf], "off_conditions": []}],
        }

    trip_valid = validate_controller(json.loads(json.dumps(_trip_base([
        {"id": trp_leaf, "type": "trip_on", "label": "", "enabled": True,
         "entity_id": "binary_sensor.trip"},
    ]))))
    assert trip_valid["conditions"][0]["type"] == "trip_on"
    # `for` applies (ordinary leaf — NOT a timing gate)
    trip_for = validate_controller(json.loads(json.dumps(_trip_base([
        {"id": trp_leaf, "type": "trip_day", "label": "", "enabled": True,
         "entity_id": "binary_sensor.trip", "day": 2,
         "for": {"hours": 0, "minutes": 1, "seconds": 0}},
    ]))))
    assert trip_for["conditions"][0]["for"]["minutes"] == 1, trip_for["conditions"][0]
    # routes naming a trip leaf are legal above — the trigger survived with
    # its coverage intact (signal origin; NON_SIGNAL_TYPES excludes the
    # trip family)
    assert trip_valid["triggers"][0]["routes"]["conditions"] == [trp_leaf]

    def _trip_fail(ctype, frag, **extra):
        cond = {"id": trp_leaf, "type": ctype, "label": "", "enabled": True,
                "entity_id": "binary_sensor.trip"}
        cond.update(extra)
        try:
            validate_controller(json.loads(json.dumps(_trip_base([cond]))))
        except ControllerValidationError as err:
            assert frag in str(err), (frag, str(err))
            return
        raise AssertionError(f"expected failure containing {frag!r}")

    _trip_fail("trip_day", "必须是天数整数", day="two")
    _trip_fail("trip_day", "必须是天数整数", day=2.5)  # R1#6: no silent truncation
    _trip_fail("trip_day", "必须是天数整数", day=True)  # R1#6: bool is not a day
    _trip_fail("trip_day", "必须在 1-365 天之间", day=0)
    _trip_fail("trip_day", "必须在 1-365 天之间", day=366)
    _trip_fail("trip_duration", "必须是小时数", hours="x")
    _trip_fail("trip_duration", "必须在 0-8760 之间", hours=0)
    _trip_fail("trip_duration", "必须在 0-8760 之间", hours=-1)
    _trip_fail("trip_duration", "必须在 0-8760 之间", hours=float("inf"))
    _trip_fail("trip_duration", "必须在 0-8760 之间", hours=8761)
    _trip_fail("trip_day", "必须是实体 ID 字符串", entity_id=None, day=2)
    print("[PASS] trip schema: ordinary leaf semantics (for + signal origin), param ranges rejected")

    # ------------------------------------------------------------------
    # 0.16.0 trip leaves: engine face — state/day_n/since reads, the loud
    # unavailable degrade (rate-limited WARN + False), and the wall-clock
    # wakeup edges (since+hours for trip_duration, next local midnight for
    # trip_day, none for trip_on / unreadable sources).
    # ------------------------------------------------------------------
    from custom_components.sensor_switch_controller.condition_engine import (  # noqa: E402
        ConditionEngine,
    )

    trp_on = "cond_" + "1a" * 16
    trp_day = "cond_" + "2b" * 16
    trp_dur = "cond_" + "3c" * 16
    eng_h = _Hass()
    eng_h.states._d["binary_sensor.trip"] = "on"
    # since = 40h before the stub utc clock (10-06 02:00) — the 20h
    # threshold is crossed, 50h is not
    eng_h.states._attrs["binary_sensor.trip"] = {
        "day_n": 2, "since": "2026-10-04T10:00:00",
    }
    eng_trp = ConditionEngine(eng_h, [
        {"id": trp_on, "type": "trip_on", "entity_id": "binary_sensor.trip"},
        {"id": trp_day, "type": "trip_day", "entity_id": "binary_sensor.trip",
         "day": 2},
        {"id": trp_dur, "type": "trip_duration",
         "entity_id": "binary_sensor.trip", "hours": 20},
    ])
    assert await eng_trp._evaluate_id(trp_on, set()) is True
    assert await eng_trp._evaluate_id(trp_day, set()) is True
    assert await eng_trp._evaluate_id(trp_dur, set()) is True
    eng_h.states._attrs["binary_sensor.trip"]["day_n"] = 3
    assert await eng_trp._evaluate_id(trp_day, set()) is False
    # loud degrade: source unavailable → False + rate-limited WARN
    class _WarnCap(_put_logging.Handler):
        def __init__(self):
            super().__init__()
            self.records: list = []

        def emit(self, record):
            self.records.append(record.getMessage())

    _eng_logger = _put_logging.getLogger(
        "custom_components.sensor_switch_controller.condition_engine"
    )
    _warn_cap = _WarnCap()
    _eng_logger.addHandler(_warn_cap)
    try:
        eng_h.states._d["binary_sensor.trip"] = "unavailable"
        assert await eng_trp._evaluate_id(trp_on, set()) is False
        assert any(
            "trip source unreadable" in m for m in _warn_cap.records
        ), _warn_cap.records
        # missing attribute → same loud face
        eng_h.states._d["binary_sensor.trip"] = "on"
        eng_h.states._attrs["binary_sensor.trip"] = {"since": None}
        assert await eng_trp._evaluate_id(trp_day, set()) is False
        assert any(
            "trip day_n missing" in m for m in _warn_cap.records
        ), _warn_cap.records
        assert await eng_trp._evaluate_id(trp_dur, set()) is False
        assert any(
            "trip since missing" in m for m in _warn_cap.records
        ), _warn_cap.records
        # R1#1: a NOT-on state is the normal verdict — False with NO WARN
        # in both attribute shapes (trip_count keeps the day_n/since keys
        # with None values while off, cross-repo verified). The pre-fix
        # code fired the missing-attribute WARN on every ordinary off
        # evaluation.
        n_off_warns = len(_warn_cap.records)
        eng_h.states._d["binary_sensor.trip"] = "off"
        eng_h.states._attrs["binary_sensor.trip"] = {
            "day_n": 2, "since": "2026-10-04T10:00:00",
        }
        assert await eng_trp._evaluate_id(trp_day, set()) is False
        assert await eng_trp._evaluate_id(trp_dur, set()) is False
        eng_h.states._attrs["binary_sensor.trip"] = {"day_n": None, "since": None}
        assert await eng_trp._evaluate_id(trp_day, set()) is False
        assert await eng_trp._evaluate_id(trp_dur, set()) is False
        assert len(_warn_cap.records) == n_off_warns, (
            f"an off trip must stay silent (normal state, not unavailable): "
            f"{_warn_cap.records[n_off_warns:]}"
        )
        # wakeup edges: duration offers since+hours (future), day offers the
        # next local midnight, trip_on offers nothing. Expectations derive
        # from the LIVE stub clock — earlier segments advance it (the 续走
        # pin jumps a full day), so a hard-coded instant would land in the
        # past and be dropped by offer(). local is re-synced to the stub's
        # implied +8h relationship for the same reason.
        base_utc = _clock["utc"]
        if base_utc.tzinfo is not None:
            base_utc = base_utc.replace(tzinfo=None)
        _saved_local = _clock["local"]
        _clock["local"] = base_utc + timedelta(hours=8)
        try:
            eng_h.states._attrs["binary_sensor.trip"] = {
                "day_n": 2,
                "since": (base_utc - timedelta(hours=1)).isoformat(),
            }
            pend_d = eng_trp.next_wakeup({trp_dur: {"o1"}})
            assert pend_d is not None and pend_d[0] == base_utc + timedelta(
                hours=19
            ) and pend_d[1] == {"o1"}, pend_d
            pend_n = eng_trp.next_wakeup({trp_day: {"o2"}})
            assert pend_n is not None and pend_n[0] == (
                _clock["local"] + timedelta(days=1)
            ).replace(hour=0, minute=0, second=0, microsecond=0), pend_n
            assert eng_trp.next_wakeup({trp_on: {"o3"}}) is None
            # an unreadable source offers nothing either
            eng_h.states._d["binary_sensor.trip"] = "unknown"
            assert eng_trp.next_wakeup({trp_dur: {"o1"}}) is None
        finally:
            _clock["local"] = _saved_local
    finally:
        _eng_logger.removeHandler(_warn_cap)
    print("[PASS] trip engine: state/day_n/since reads, loud unavailable WARN, wall-clock wakeup edges")

    # ------------------------------------------------------------------
    # 0.16.0 hazard face wiring: the trip leaves join the wall-clock tier —
    # a chain whose only waker is a trip leaf must NOT trip faces ②/⑤.
    # ------------------------------------------------------------------
    trp_out2 = "ssc_" + "e5" * 16
    haz_cfg = json.loads(json.dumps({
        "name": "trip-haz",
        "enabled": True,
        "logging_enabled": False,
        "triggers": [{"id": trp_trg, "type": "state",
                      "entity_id": "binary_sensor.trip",
                      "enabled": True,
                      "routes": {"conditions": []}}],
        "conditions": [{"id": trp_leaf, "type": "trip_day", "label": "",
                        "enabled": True, "entity_id": "binary_sensor.trip",
                        "day": 1}],
        "outputs": [{"name": "o", "type": "switch", "entity_id": trp_out2,
                     "on_conditions": [trp_leaf], "off_conditions": []}],
    }))
    _haz_logger = _put_logging.getLogger(
        "custom_components.sensor_switch_controller.schema"
    )
    _haz_cap = _WarnCap()
    _haz_logger.addHandler(_haz_cap)
    try:
        validate_controller(haz_cfg)
        assert not any(
            "没有任何可唤醒源" in m or "依赖日历条件" in m
            for m in _haz_cap.records
        ), _haz_cap.records
    finally:
        _haz_logger.removeHandler(_haz_cap)
    print("[PASS] trip hazard faces: trip leaves join the wall-clock wakeup tier")

    # ------------------------------------------------------------------
    # 0.16.0 文羽服务 output: schema face — closed built-in domain list,
    # service required, manual_override dropped, chains validated.
    # ------------------------------------------------------------------
    svc_out = "ssc_" + "f" * 32
    svc_cfg = {
        "name": "svc",
        "enabled": True,
        "logging_enabled": False,
        "triggers": [{"id": trp_trg, "type": "state",
                      "entity_id": "binary_sensor.trip",
                      "enabled": True,
                      "routes": {"conditions": [trp_leaf]}}],
        "conditions": [{"id": trp_leaf, "type": "trip_on", "label": "",
                        "enabled": True, "entity_id": "binary_sensor.trip"}],
        "outputs": [{"name": "call-out", "type": "fumiha_service",
                     "entity_id": svc_out, "domain": "trip_count",
                     "service": "depart", "manual_override": False,
                     "on_conditions": [trp_leaf], "off_conditions": []}],
    }
    svc_valid = validate_controller(json.loads(json.dumps(svc_cfg)))
    assert svc_valid["outputs"][0]["domain"] == "trip_count"
    assert svc_valid["outputs"][0]["service"] == "depart"
    assert "manual_override" not in svc_valid["outputs"][0]

    def _svc_fail(mut, frag):
        cfg = json.loads(json.dumps(svc_cfg))
        mut(cfg["outputs"][0])
        try:
            validate_controller(cfg)
        except ControllerValidationError as err:
            assert frag in str(err), (frag, str(err))
            return
        raise AssertionError(f"expected failure containing {frag!r}")

    _svc_fail(lambda o: o.update(domain="not_a_fumiha"), "必须是内置文羽域之一")
    _svc_fail(lambda o: o.update(domain=""), "必须是内置文羽域之一")
    _svc_fail(lambda o: o.update(service="  "), "service 必须是非空服务名")
    _svc_fail(lambda o: o.update(service=None), "service 必须是非空服务名")
    print("[PASS] service output schema: built-in domain list closed, service required, override dropped")

    # ------------------------------------------------------------------
    # 0.16.0 文羽服务 output: engine face — rising-edge call, held gate
    # acts once, off wins / re-arms, loud UNAVAILABLE (missing service →
    # ERROR + retry next cycle), decision-log call row, and the first-eval
    # gate does not wait for the entity-less output.
    # ------------------------------------------------------------------
    svc_h = _Hass()
    svc_h.states._d["switch.c"] = "on"
    svc_calls: list[tuple[str, str]] = []
    svc_missing = [False]

    async def _svc_call(domain, service, blocking=False):
        svc_calls.append((domain, service))

    svc_h.services = types.SimpleNamespace(
        has_service=lambda d, s: not svc_missing[0],
        async_call=_svc_call,
    )
    svc_leaf = "cond_" + "4d" * 16
    svc_mgr_cfg = {
        "name": "svc-run",
        "enabled": True,
        "logging_enabled": True,  # R2#4: the call decision-log face is real
        "triggers": [{"id": "trg_" + "d" * 32, "type": "state",
                      "entity_id": "switch.c", "enabled": True,
                      "routes": {"conditions": [svc_leaf]}}],
        "conditions": [{"id": svc_leaf, "type": "state", "label": "",
                        "enabled": True, "entity_id": "switch.c",
                        "state": "on"}],
        "outputs": [{"name": "call-out", "type": "fumiha_service",
                     "entity_id": svc_out, "domain": "trip_count",
                     "service": "depart",
                     "on_conditions": [svc_leaf], "off_conditions": []}],
    }
    mgr_svc = ControllerManager(svc_h, "ctrl_svc01", svc_mgr_cfg)
    # first-eval gate: the entity-less output must not block the cycle (it
    # used to wait for the 30s fallback with _expected_out_ids non-empty)
    assert mgr_svc._expected_out_ids == set(), mgr_svc._expected_out_ids
    recs_svc = _log_cycles("ctrl_svc01")
    await mgr_svc._async_evaluate(None, ["init"], None)
    assert svc_calls == [("trip_count", "depart")], svc_calls
    assert mgr_svc.last_results[svc_out]["decision"] == "call"
    assert mgr_svc.last_results[svc_out]["applied"] is True
    # R2#4: the call row lands in the decision log (the segment head has
    # claimed this face since 0.16.0 — it was pinned only here, R2-fix)
    svc_log_rows = _log_tail(recs_svc, "ctrl_svc01")
    assert any(
        r.get("decision") == "call" and r.get("output") == "call-out"
        for r in svc_log_rows
    ), svc_log_rows
    # held gate: the next cycle must NOT re-fire (rising edge)…
    await mgr_svc._async_evaluate(None, ["again"], None)
    assert svc_calls == [("trip_count", "depart")], svc_calls
    # …and NEITHER must the one after it (R2#1: the old
    # `bool(gate and applied)` zeroed the ledger the cycle after a success —
    # a level-held gate re-fired every SECOND cycle; this pin is red on the
    # pre-fix code)
    await mgr_svc._async_evaluate(None, ["again-2"], None)
    assert svc_calls == [("trip_count", "depart")], svc_calls
    # gate drops and rises → fires again
    svc_h.states._d["switch.c"] = "off"
    await mgr_svc._async_evaluate(None, ["drop"], None)
    svc_h.states._d["switch.c"] = "on"
    await mgr_svc._async_evaluate(None, ["rise"], None)
    assert svc_calls == [
        ("trip_count", "depart"), ("trip_count", "depart"),
    ], svc_calls
    # off chain wins: off met suppresses the call (edge consumed → no call)
    mgr_svc.outputs[0]["off_conditions"] = [svc_leaf]
    await mgr_svc._async_evaluate(None, ["offwin"], None)
    assert len(svc_calls) == 2, svc_calls
    mgr_svc.outputs[0]["off_conditions"] = []
    # UNAVAILABLE face: service missing → ERROR log, no call, edge stays
    # alive (retry next cycle), record applied=False
    class _ErrCap(_put_logging.Handler):
        def __init__(self):
            super().__init__()
            self.records: list = []

        def emit(self, record):
            self.records.append(
                f"{record.levelname}: {record.getMessage()}"
            )

    _ctl_logger = _put_logging.getLogger(
        "custom_components.sensor_switch_controller.controller"
    )
    _err_cap = _ErrCap()
    _ctl_logger.addHandler(_err_cap)
    try:
        svc_h.states._d["switch.c"] = "off"
        await mgr_svc._async_evaluate(None, ["rearm"], None)
        svc_h.states._d["switch.c"] = "on"
        svc_missing[0] = True
        await mgr_svc._async_evaluate(None, ["missing"], None)
        assert svc_calls == [
            ("trip_count", "depart"), ("trip_count", "depart"),
        ], svc_calls
        assert mgr_svc.last_results[svc_out]["applied"] is False
        assert any("未注册" in m and "ERROR" in m for m in _err_cap.records), (
            _err_cap.records
        )
        # edge alive: the retry next cycle attempts again
        await mgr_svc._async_evaluate(None, ["retry"], None)
        assert svc_calls == [
            ("trip_count", "depart"), ("trip_count", "depart"),
        ], svc_calls
        assert any("未注册" in m and "ERROR" in m for m in _err_cap.records)
        # a THROWING service keeps the edge alive too (failed call retries)
        svc_missing[0] = False

        async def _boom(domain, service, blocking=False):
            raise RuntimeError("boom")

        svc_h.services.async_call = _boom
        await mgr_svc._async_evaluate(None, ["boom"], None)
        assert any("调用" in m and "失败" in m for m in _err_cap.records), (
            _err_cap.records
        )
        assert mgr_svc.last_results[svc_out]["applied"] is False
    finally:
        _ctl_logger.removeHandler(_err_cap)
    mgr_svc.async_unload()
    print("[PASS] service output engine: rising edge, off-wins, loud UNAVAILABLE + retry, no first-eval block")

    # ------------------------------------------------------------------
    # F-556 判别钉: the ①n predicate follows the group's OWN polarity —
    # OR(any-member-cooldown) warns, AND(all-composed) stays the narrow
    # face, pure-live OR stays silent. The old all() let
    # "OR[cooldown, live leaf]" save silently (the constant-True cooldown
    # dominates the OR verdict at cold start = the delayed off trap).
    # ------------------------------------------------------------------
    f556_c = "cond_" + "5a" * 16
    f556_b = "cond_" + "5b" * 16
    f556_dur = "cond_" + "5d" * 16
    f556_or = "cond_" + "5e" * 16
    f556_and = "cond_" + "5f" * 16
    f556_out = "ssc_" + "5a" * 16
    _f556_logger = _put_logging.getLogger(
        "custom_components.sensor_switch_controller.schema"
    )
    _f556_cap = _WarnCap()
    _f556_logger.addHandler(_f556_cap)
    try:
        def _f556_cfg(groups):
            conds = [
                {"id": f556_b, "type": "state", "label": "", "enabled": True,
                 "entity_id": "switch.c", "state": "on"},
                {"id": f556_c, "type": "cooldown", "label": "", "enabled": True,
                 "seconds": 30},
            ]
            conds += groups
            return {
                "name": "f556",
                "enabled": True,
                "logging_enabled": False,
                "triggers": [{"id": trp_trg, "type": "state",
                              "entity_id": "switch.c", "enabled": True,
                              "routes": {"conditions": [f556_b]}}],
                "conditions": conds,
                "outputs": [{"name": "o", "type": "switch",
                             "entity_id": f556_out,
                             "on_conditions": [f556_b],
                             "off_conditions": [f556_dur]}],
            }

        def _f556_n_warn():
            return sum("start 恒真化" in r for r in _f556_cap.records)

        # RED: OR[cooldown, live leaf] arming the off-chain duration —
        # one cooldown member dominates the OR verdict at cold start
        n0 = _f556_n_warn()
        validate_controller(_f556_cfg(
            [{"id": f556_or, "type": "or", "label": "", "enabled": True,
              "conditions": [f556_c, f556_b]},
             {"id": f556_dur, "type": "duration", "label": "", "enabled": True,
              "seconds": 60, "start": f556_or, "abort": None}]
        ))
        assert _f556_n_warn() == n0 + 1, _f556_cap.records[n0:]
        # GREEN: the same live leaf mixed into an AND group — the cooldown
        # no longer gates the off verdict alone (legitimate arming shape)
        n1 = _f556_n_warn()
        validate_controller(_f556_cfg(
            [{"id": f556_and, "type": "and", "label": "", "enabled": True,
              "conditions": [f556_c, f556_b]},
             {"id": f556_dur, "type": "duration", "label": "", "enabled": True,
              "seconds": 60, "start": f556_and, "abort": None}]
        ))
        assert _f556_n_warn() == n1, _f556_cap.records[n1:]
        # GREEN: pure-live OR (no cooldown at all) — no flip-history trap
        n2 = _f556_n_warn()
        validate_controller(_f556_cfg(
            [{"id": f556_or, "type": "or", "label": "", "enabled": True,
              "conditions": [f556_b]},
             {"id": f556_dur, "type": "duration", "label": "", "enabled": True,
              "seconds": 60, "start": f556_or, "abort": None}]
        ))
        assert _f556_n_warn() == n2, _f556_cap.records[n2:]
        # RED: all-cooldown OR — any() keeps it covered
        n3 = _f556_n_warn()
        validate_controller(_f556_cfg(
            [{"id": f556_or, "type": "or", "label": "", "enabled": True,
              "conditions": [f556_c]},
             {"id": f556_dur, "type": "duration", "label": "", "enabled": True,
              "seconds": 60, "start": f556_or, "abort": None}]
        ))
        assert _f556_n_warn() == n3 + 1, _f556_cap.records[n3:]
    finally:
        _f556_logger.removeHandler(_f556_cap)
    print("[PASS] F-556: ①n OR arm = any(cooldown members), AND arm = all, pure-live OR silent")

    # ------------------------------------------------------------------
    # F-471 判别钉: the countdown wakeup credit requires a startable gate —
    # an EMPTY start gate (legal reset-only countdown) or a gate whose
    # members are provably dead in the flag-step judge no longer mutes
    # faces ②/⑤ for chains whose only "waker" can never wake anything.
    # ------------------------------------------------------------------
    f471_cd = "cond_" + "6a" * 16
    f471_x = "cond_" + "6b" * 16
    f471_cool = "cond_" + "6c" * 16
    f471_out = "ssc_" + "6a" * 16

    def _f471_cfg(gate_members, extra_conds=()):
        conds = [
            {"id": f471_cd, "type": "countdown", "label": "", "enabled": True,
             "seconds": 60, "start_conditions": list(gate_members),
             "reset_conditions": [f471_x]},
            {"id": f471_x, "type": "state", "label": "", "enabled": True,
             "entity_id": "switch.c", "state": "on"},
            *extra_conds,
        ]
        return {
            "name": "f471",
            "enabled": True,
            "logging_enabled": False,
            "triggers": [{"id": trp_trg, "type": "state",
                          "entity_id": "switch.c", "enabled": True,
                          "routes": {"conditions": []}}],
            "conditions": conds,
            "outputs": [{"name": "o", "type": "switch",
                         "entity_id": f471_out,
                         "on_conditions": [f471_cd], "off_conditions": []}],
        }

    _f471_logger = _put_logging.getLogger(
        "custom_components.sensor_switch_controller.schema"
    )
    _f471_cap = _WarnCap()
    _f471_logger.addHandler(_f471_cap)
    try:
        def _f471_freeze_warns():
            return sum("没有任何可唤醒源" in r for r in _f471_cap.records)
        # RED: empty start gate (reset-only countdown) — the timer can
        # never start, so crediting it muted the freeze warning forever
        n0 = _f471_freeze_warns()
        validate_controller(_f471_cfg([]))
        assert _f471_freeze_warns() == n0 + 1, _f471_cap.records[n0:]
        # GREEN: a live start gate member credits the countdown
        n1 = _f471_freeze_warns()
        validate_controller(_f471_cfg([f471_x]))
        assert _f471_freeze_warns() == n1, _f471_cap.records[n1:]
        # a gate whose members are ALL provably dead (AND[cooldown]) is
        # already REJECTED by the stateful dead-gate face — the only
        # saveable non-credit shape is the empty gate, covered above
        # GREEN: mixed OR gate keeps a viable member (cooldown + live leaf)
        f471_or = "cond_" + "6e" * 16
        n3 = _f471_freeze_warns()
        validate_controller(_f471_cfg(
            [f471_or],
            extra_conds=[
                {"id": f471_cool, "type": "cooldown", "label": "",
                 "enabled": True, "seconds": 30},
                {"id": f471_or, "type": "or", "label": "", "enabled": True,
                 "conditions": [f471_cool, f471_x]},
            ],
        ))
        assert _f471_freeze_warns() == n3, _f471_cap.records[n3:]
    finally:
        _f471_logger.removeHandler(_f471_cap)
    print("[PASS] F-471: countdown wakeup credit follows the start gate's viability (empty gate warns, live/mixed-OR credits)")

    # ------------------------------------------------------------------
    # F-472 判别钉: a same-cycle capture(main pass)+clear(convergence
    # re-step) on the SAME snapshot id must land BOTH decision-log rows —
    # the old {**a, **b} dict merge kept only the re-step's clear.
    # ------------------------------------------------------------------
    f472_w = "cond_" + "7a" * 16
    f472_x = "cond_" + "7b" * 16
    f472_s = "cond_" + "7c" * 16
    f472_f = "cond_" + "7d" * 16
    f472_c = "cond_" + "7e" * 16
    f472_out = "ssc_" + "7a" * 16
    f472_cfg = {
        "name": "f472",
        "enabled": True,
        "logging_enabled": True,
        "triggers": [{"id": trp_trg, "type": "state",
                      "entity_id": "switch.c", "enabled": True,
                      "routes": {"conditions": [f472_x]}}],
        "conditions": [
            {"id": f472_w, "type": "state", "label": "", "enabled": True,
             "entity_id": "switch.d", "state": "off"},
            {"id": f472_x, "type": "state", "label": "", "enabled": True,
             "entity_id": "switch.c", "state": "on"},
            {"id": f472_s, "type": "snapshot", "label": "", "enabled": True,
             "entity_id": "sensor.a", "capture": [f472_x], "clear": [f472_f]},
            {"id": f472_f, "type": "flag", "label": "", "enabled": True,
             "set_conditions": [f472_c], "reset_conditions": [],
             "initial": False},
            {"id": f472_c, "type": "countdown", "label": "", "enabled": True,
             "seconds": 60, "start_conditions": [f472_w],
             "reset_conditions": []},
        ],
        "outputs": [{"name": "o", "type": "switch", "entity_id": f472_out,
                     "on_conditions": [f472_s], "off_conditions": []}],
    }
    validate_controller(json.loads(json.dumps(f472_cfg)))
    f472_h = _Hass()
    f472_h.states._d["switch.c"] = "off"  # capture gate low at cycle 1
    mgr_472 = ControllerManager(f472_h, "ctrl_f47201", json.loads(json.dumps(f472_cfg)))
    recs_472 = _log_cycles("ctrl_f47201")
    await mgr_472._async_evaluate(None, ["init"], None)  # countdown starts
    f472_h.states._d["switch.c"] = "on"
    _advance_utc(120)  # the deadline passes while the capture gate rises
    await mgr_472._async_evaluate(None, ["zero"], None)
    dec_472 = [r.get("decision") for r in _log_tail(recs_472, "ctrl_f47201")]
    assert "capture" in dec_472 and "clear" in dec_472, dec_472
    # order: the main-pass capture precedes the re-step clear
    assert dec_472.index("capture") < dec_472.index("clear"), dec_472
    mgr_472.async_unload()
    print("[PASS] F-472: same-cycle capture+clear both reach the decision log in pass order")

    # ------------------------------------------------------------------
    # F-473 判别钉: an unparseable deadline is nulled AT the seeding exit
    # AND the cleaned entry self-heals back into the hub table (in-memory
    # immediately + debounced disk write) — no repeat warning next restart.
    # ------------------------------------------------------------------
    class _HealStore:
        def __init__(self):
            self.saved = []
            self.delayed = []
            self.load_result = {"controllers": {}}

        async def async_load(self):
            return self.load_result

        async def async_save(self, data):
            self.saved.append(data)

        def async_delay_save(self, data_func, delay=0):
            self.delayed.append(data_func)

    f473_nid = "cond_" + "8a" * 16
    f473_cfg = {
        "name": "f473",
        "enabled": True,
        "logging_enabled": False,
        "triggers": [{"id": trp_trg, "type": "state",
                      "entity_id": "switch.c", "enabled": True,
                      "routes": {"conditions": []}}],
        "conditions": [
            {"id": f473_nid, "type": "countdown", "label": "",
             "enabled": True, "seconds": 60,
             "start_conditions": [], "reset_conditions": []},
        ],
        "outputs": [{"name": "o", "type": "switch", "entity_id": f472_out,
                     "on_conditions": [f473_nid], "off_conditions": []}],
    }
    hub_473 = ScannerHub(_Hass())
    hub_473._flag_store = _HealStore()
    hub_473.stateful_states["ctrl_f47301"] = {
        f473_nid: {"deadline": "not-a-date", "verdict": True, "count": 2},
    }
    hub_473.hass.data[_DOM] = hub_473  # the manager's seeding exit reads hass.data
    mgr_473 = ControllerManager(hub_473.hass, "ctrl_f47301", f473_cfg)
    healed = (hub_473.stateful_states.get("ctrl_f47301") or {}).get(f473_nid) or {}
    assert healed.get("deadline") is None, healed
    assert healed.get("verdict") is True and healed.get("count") == 2, healed
    assert len(hub_473._flag_store.delayed) == 1, hub_473._flag_store.delayed
    payload = hub_473._flag_store.delayed[0]()
    assert payload["stateful"]["ctrl_f47301"][f473_nid]["deadline"] is None, payload
    assert payload["stateful"]["ctrl_f47301"][f473_nid]["verdict"] is True, payload
    # the engine seed carries the cleaned value too (a rebuild reads None,
    # not the bad string — the warning fires exactly once per bad value)
    assert mgr_473.engine.stateful_values()[f473_nid]["deadline"] is None
    mgr_473.async_unload()
    print("[PASS] F-473: bad deadline self-heals into the hub table + debounced disk write")

    # ------------------------------------------------------------------
    # R1#3 判别钉: trip_on is a state-shaped leaf, NOT a wall-clock gate —
    # a chain whose only "waker" is a trip_on leaf must still warn (face ⑤;
    # next_wakeup offers nothing for trip_on, same face as COND_STATE).
    # ------------------------------------------------------------------
    r1x_on = "cond_" + "9a" * 16
    r1x_out = "ssc_" + "9a" * 16
    _r1x_logger = _put_logging.getLogger(
        "custom_components.sensor_switch_controller.schema"
    )
    _r1x_cap = _WarnCap()
    _r1x_logger.addHandler(_r1x_cap)
    try:
        validate_controller({
            "name": "trip-on-freeze",
            "enabled": True,
            "logging_enabled": False,
            "triggers": [{"id": trp_trg, "type": "state",
                          "entity_id": "binary_sensor.trip", "enabled": True,
                          "routes": {"conditions": []}}],
            "conditions": [{"id": r1x_on, "type": "trip_on", "label": "",
                            "enabled": True,
                            "entity_id": "binary_sensor.trip"}],
            "outputs": [{"name": "o", "type": "switch", "entity_id": r1x_out,
                         "on_conditions": [r1x_on], "off_conditions": []}],
        })
        assert any("没有任何可唤醒源" in m for m in _r1x_cap.records), (
            f"a trip_on-only chain must still warn (no clock edge, no signal "
            f"coverage): {_r1x_cap.records}"
        )
    finally:
        _r1x_logger.removeHandler(_r1x_cap)
    print("[PASS] R1#3: trip_on-only chain warns (not a wall-clock gate)")

    # ------------------------------------------------------------------
    # R1#4 判别钉: F-471 credit narrowed — an EMPTY non-signal-anchor group
    # as the countdown's start gate is NOT viable (the engine judges it
    # constant False), so the chain must warn instead of the credit muting
    # faces ②/⑤. The shape is saveable (member_referenced covers stateful
    # gate members).
    # ------------------------------------------------------------------
    r1y_cd = "cond_" + "9b" * 16
    r1y_grp = "cond_" + "9c" * 16
    r1y_x = "cond_" + "9d" * 16
    r1y_out = "ssc_" + "9b" * 16
    _r1y_logger = _put_logging.getLogger(
        "custom_components.sensor_switch_controller.schema"
    )
    _r1y_cap = _WarnCap()
    _r1y_logger.addHandler(_r1y_cap)
    try:
        validate_controller({
            "name": "f471-empty-group",
            "enabled": True,
            "logging_enabled": False,
            "triggers": [{"id": trp_trg, "type": "state",
                          "entity_id": "switch.c", "enabled": True,
                          "routes": {"conditions": []}}],
            "conditions": [
                {"id": r1y_cd, "type": "countdown", "label": "",
                 "enabled": True, "seconds": 60,
                 "start_conditions": [r1y_grp], "reset_conditions": [r1y_x]},
                {"id": r1y_grp, "type": "and", "label": "", "enabled": True,
                 "conditions": []},
                {"id": r1y_x, "type": "state", "label": "", "enabled": True,
                 "entity_id": "switch.c", "state": "on"},
            ],
            "outputs": [{"name": "o", "type": "switch", "entity_id": r1y_out,
                         "on_conditions": [r1y_cd], "off_conditions": []}],
        })
        assert any("没有任何可唤醒源" in m for m in _r1y_cap.records), (
            f"an empty-group start gate must not credit the countdown "
            f"(engine judges it False): {_r1y_cap.records}"
        )
        # R2#3 (F-631): the narrowing resolves through the WHOLE closure —
        # a NESTED empty group (directly, or mixed with a live leaf in an
        # AND) is constant False in the engine too, so both shapes must
        # warn instead of silently freezing the faces.
        r1y_grp2 = "cond_" + "8b" * 16
        n_1y = sum("没有任何可唤醒源" in m for m in _r1y_cap.records)
        validate_controller({
            "name": "f471-nested-empty",
            "enabled": True,
            "logging_enabled": False,
            "triggers": [{"id": trp_trg, "type": "state",
                          "entity_id": "switch.c", "enabled": True,
                          "routes": {"conditions": []}}],
            "conditions": [
                {"id": r1y_cd, "type": "countdown", "label": "",
                 "enabled": True, "seconds": 60,
                 "start_conditions": [r1y_grp2], "reset_conditions": [r1y_x]},
                {"id": r1y_grp2, "type": "and", "label": "", "enabled": True,
                 "conditions": [r1y_grp]},
                {"id": r1y_grp, "type": "and", "label": "", "enabled": True,
                 "conditions": []},
                {"id": r1y_x, "type": "state", "label": "", "enabled": True,
                 "entity_id": "switch.c", "state": "on"},
            ],
            "outputs": [{"name": "o", "type": "switch", "entity_id": r1y_out,
                         "on_conditions": [r1y_cd], "off_conditions": []}],
        })
        assert sum(
            "没有任何可唤醒源" in m for m in _r1y_cap.records
        ) == n_1y + 1, _r1y_cap.records
        # nested empty group mixed with a live leaf in an AND — the AND
        # merge is constant False, same freeze shape
        r1y_grp3 = "cond_" + "8c" * 16
        n_1y2 = sum("没有任何可唤醒源" in m for m in _r1y_cap.records)
        validate_controller({
            "name": "f471-nested-empty-mixed",
            "enabled": True,
            "logging_enabled": False,
            "triggers": [{"id": trp_trg, "type": "state",
                          "entity_id": "switch.c", "enabled": True,
                          "routes": {"conditions": []}}],
            "conditions": [
                {"id": r1y_cd, "type": "countdown", "label": "",
                 "enabled": True, "seconds": 60,
                 "start_conditions": [r1y_grp3], "reset_conditions": [r1y_x]},
                {"id": r1y_grp3, "type": "and", "label": "", "enabled": True,
                 "conditions": [r1y_grp, r1y_x]},
                {"id": r1y_grp, "type": "and", "label": "", "enabled": True,
                 "conditions": []},
                {"id": r1y_x, "type": "state", "label": "", "enabled": True,
                 "entity_id": "switch.c", "state": "on"},
            ],
            "outputs": [{"name": "o", "type": "switch", "entity_id": r1y_out,
                         "on_conditions": [r1y_cd], "off_conditions": []}],
        })
        assert sum(
            "没有任何可唤醒源" in m for m in _r1y_cap.records
        ) == n_1y2 + 1, _r1y_cap.records
        # RED-green discriminator: the SAME shape with the empty group
        # signal-covered (a trigger anchors it pass-through=True) IS viable
        # — the empty-group face must NOT fire for the anchor (F-327/F-151)
        r1y_cap_n = len(_r1y_cap.records)
        validate_controller({
            "name": "f471-empty-group-anchored",
            "enabled": True,
            "logging_enabled": False,
            "triggers": [{"id": trp_trg, "type": "state",
                          "entity_id": "switch.c", "enabled": True,
                          "routes": {"conditions": [r1y_grp]}}],
            "conditions": [
                {"id": r1y_cd, "type": "countdown", "label": "",
                 "enabled": True, "seconds": 60,
                 "start_conditions": [r1y_grp], "reset_conditions": [r1y_x]},
                {"id": r1y_grp, "type": "and", "label": "", "enabled": True,
                 "conditions": []},
                {"id": r1y_x, "type": "state", "label": "", "enabled": True,
                 "entity_id": "switch.c", "state": "on"},
            ],
            "outputs": [{"name": "o", "type": "switch", "entity_id": r1y_out,
                         "on_conditions": [r1y_cd], "off_conditions": []}],
        })
        assert not any(
            "没有任何可唤醒源" in m for m in _r1y_cap.records[r1y_cap_n:]
        ), _r1y_cap.records[r1y_cap_n:]
    finally:
        _r1y_logger.removeHandler(_r1y_cap)
    print("[PASS] R1#4: empty-group start gate loses the credit unless signal-anchored")

    # ------------------------------------------------------------------
    # R1#5 判别钉: the ①n predicate treats DISABLED members as True
    # contributors (engine short-circuit) — an all-disabled group is a
    # CONSTANT-TRUE start (the delayed off-polarity trap without any
    # cooldown), and the old skip-then-empty→False shape exempted it from
    # every warning face.
    # ------------------------------------------------------------------
    r1z_d1 = "cond_" + "9e" * 16
    r1z_d2 = "cond_" + "9f" * 16
    r1z_live = "cond_" + "9a" * 16
    r1z_grp = "cond_" + "9b" * 16
    r1z_dur = "cond_" + "9c" * 16
    r1z_out = "ssc_" + "9c" * 16
    _r1z_logger = _put_logging.getLogger(
        "custom_components.sensor_switch_controller.schema"
    )
    _r1z_cap = _WarnCap()
    _r1z_logger.addHandler(_r1z_cap)
    try:
        def _r1z_cfg(start_ref):
            return {
                "name": "r1#5",
                "enabled": True,
                "logging_enabled": False,
                "triggers": [{"id": trp_trg, "type": "state",
                              "entity_id": "switch.c", "enabled": True,
                              "routes": {"conditions": [r1z_live]}}],
                "conditions": [
                    {"id": r1z_d1, "type": "state", "label": "",
                     "enabled": False, "entity_id": "switch.c",
                     "state": "on"},
                    {"id": r1z_d2, "type": "state", "label": "",
                     "enabled": False, "entity_id": "switch.d",
                     "state": "on"},
                    {"id": r1z_live, "type": "state", "label": "",
                     "enabled": True, "entity_id": "switch.c",
                     "state": "on"},
                    {"id": r1z_grp, "type": "and", "label": "",
                     "enabled": True,
                     "conditions": [r1z_d1, r1z_d2]},
                    {"id": r1z_dur, "type": "duration", "label": "",
                     "enabled": True, "seconds": 60,
                     "start": start_ref, "abort": None},
                ],
                "outputs": [{"name": "o", "type": "switch",
                             "entity_id": r1z_out,
                             "on_conditions": [r1z_live],
                             "off_conditions": [r1z_dur]}],
            }

        def _r1z_n_warn():
            return sum("start 恒真化" in r for r in _r1z_cap.records)
        # RED: AND[all disabled] start = constant True (delayed off trap)
        n0 = _r1z_n_warn()
        validate_controller(_r1z_cfg(r1z_grp))
        assert _r1z_n_warn() == n0 + 1, _r1z_cap.records[n0:]
        # RED: the same via OR (any True member dominates)
        r1z_grp_or = "cond_" + ("9d" * 16)
        n1 = _r1z_n_warn()
        cfg = _r1z_cfg(r1z_grp_or)
        for c in cfg["conditions"]:
            if c["id"] == r1z_grp:
                c["id"] = r1z_grp_or
                c["type"] = "or"
        validate_controller(cfg)
        assert _r1z_n_warn() == n1 + 1, _r1z_cap.records[n1:]
        # GREEN boundary: mixed AND[live, disabled] keeps the live verdict
        # in the chain (engine AND(live, True) = live) — no warning
        r1z_grp_mix = "cond_" + ("1e" * 16)
        n2 = _r1z_n_warn()
        cfg2 = _r1z_cfg(r1z_grp_mix)
        for c in cfg2["conditions"]:
            if c["id"] == r1z_grp:
                c["id"] = r1z_grp_mix
                c["conditions"] = [r1z_live, r1z_d1]
        validate_controller(cfg2)
        assert _r1z_n_warn() == n2, _r1z_cap.records[n2:]
    finally:
        _r1z_logger.removeHandler(_r1z_cap)
    print("[PASS] R1#5: all-disabled group start warns (constant-True trap), mixed AND stays silent")

asyncio.run(main())
print("SMOKE OK")
