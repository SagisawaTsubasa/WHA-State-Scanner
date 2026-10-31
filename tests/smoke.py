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
        "sensors": [{"entity_id": "switch.c"}],
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
        "triggers": [], "sensors": [{"entity_id": "switch.c"}],
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
                      "entity_id": "switch.c",
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
                      "entity_id": "switch.c",
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
        "sensors": [{"entity_id": "sensor.a"}, {"entity_id": "switch.c"}],
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
        no-op, but this pin must observe the persisted payloads."""

        def __init__(self):
            self.saved = []

        async def async_save(self, data):
            self.saved.append(data)

        async def async_load(self):
            return None

    hub_f._flag_store = _RecordingFlagStore()
    flip_out = "ssc_" + "1" * 32
    flip_at = _clock["utc"]
    await hub_f.async_save_last_flip("ctrl_ab12cd34", flip_out, flip_at)
    assert hub_f.last_flips["ctrl_ab12cd34"][flip_out] == flip_at.isoformat()
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
        "sensors": [{"entity_id": "switch.c"}],
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
            "name": "hazards", "sensors": [{"entity_id": "switch.c"}],
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

asyncio.run(main())
print("SMOKE OK")
