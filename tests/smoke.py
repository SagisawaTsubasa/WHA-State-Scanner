# -*- coding: utf-8 -*-
"""Import-chain + 0.7.3 directed-semantics smoke test (no HA required).

Catches the failure classes that ruff/py_compile/node cannot see:
  1. ImportError across the whole integration module graph (missing names,
     stale imports) — run by importing every module with a stubbed HA tree.
  2. Runtime AttributeError inside the evaluation path — driven end-to-end
     against stub HA.
  3. 0.7.3 semantics: v2/v3/v4/v5→v6 store migration (condition coverage),
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
from datetime import datetime, timedelta
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
# 2) v2/v3→v6 store migration chain (pure functions).
# ---------------------------------------------------------------------------

from custom_components.sensor_switch_controller.hub import (  # noqa: E402
    _flatten_group_coverage,
    _migrate_controller_v2,
    _migrate_controller_v4,
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
    "triggers": [{"id": TID1, "type": "state"}],
}
import copy as _copy
_cfg_v2_snapshot = _copy.deepcopy(cfg)  # pre-migration snapshot for dispatch net
_migrate_controller_v2(cfg)
_migrate_controller_v4(cfg)
_strip_duration_coverage(cfg)
_flatten_group_coverage(cfg)  # the full hub chain, v2→6

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
print("[PASS] migration v2/v3→v6: for→duration split, at→after, condition coverage")

# ---------------------------------------------------------------------------
# 3) Schema rules: trigger id preserved, routes validated, time.at rejected.
# ---------------------------------------------------------------------------

from custom_components.sensor_switch_controller.schema import (  # noqa: E402
    ControllerValidationError,
    _validate_condition,
    validate_controller,
    validate_trigger,
)

trg = {"id": TID1, "type": "state", "routes": {"conditions": []}}
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
        {"id": TID1, "type": "state", "routes": {"conditions": [g_id]}}
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
        {"id": TID1, "type": "state", "routes": {"conditions": [g_dur]}}
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
        {"id": TID1, "type": "state",
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
        {"id": TID1, "type": "state", "routes": {"conditions": [empty_anchor]}}
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
        {"id": TID1, "type": "state",
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
fresh = validate_trigger({"type": "state"})
assert fresh["id"].startswith("trg_") and len(fresh["id"]) == 36, fresh["id"]

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
        {"id": TID1, "type": "state", "routes": {"conditions": ["cond_" + "f" * 32]}}
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
        return SimpleNamespace(state=v, attributes={}, last_changed=lc)


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
                "routes": {"conditions": [cond_b]},
            },
            {
                "id": trg_a_only,
                "type": "state",
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
        "sensors": [],
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
        "sensors": [],
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
    assert obs["readings"]["switch.c"] == "on"
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
        "sensors": [{"entity_id": "switch.c"}],
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
        "sensors": [{"entity_id": "switch.c"}],
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
        "sensors": [{"entity_id": "switch.c"}, {"entity_id": "switch.d"}],
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
                      "routes": {"conditions": [x2_id]}}],
        "sensors": [{"entity_id": "switch.c"}],
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
                      "routes": {"conditions": [u_cond]}}],
        "sensors": [{"entity_id": "switch.c"}],
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
        "triggers": [], "sensors": [],
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
    tm_ep.async_setup([])  # empty sensor pool → no targets
    assert tm_ep.register_errors == 1, "empty-pool state trigger must be an error"
    print("[PASS] empty-pool state trigger counts as registration error (R5-9)")

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
        "triggers": [], "sensors": [], "conditions": [],
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

asyncio.run(main())
print("SMOKE OK")
