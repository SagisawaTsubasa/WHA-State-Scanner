# -*- coding: utf-8 -*-
"""Legacy-config GET→PUT byte round-trip (WHA-SNAPSHOT-121 step 2).

The 0.13.0 data-node types (snapshot/literal/compare) must be a PURE
addition: validating an already-validated stored config must not touch a
byte — the PUT path (web) normalizes through validate_controller, so
idempotence there is exactly the GET→PUT round-trip guarantee (存量配置
字节等价, new-type validation has zero effect on legacy shapes).

The sample below is the v0.12.0-era kitchen sink: every legacy condition
type, a flag, a duration gate, directed trigger routes and both output
kinds — the shapes the live 8-controller store carries.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # noqa: E402

from tests.conftest import _INSTALL_STUBS  # noqa: E402,F401 — installs HA stubs

from custom_components.sensor_switch_controller.schema import (  # noqa: E402
    validate_controller,
)


def _legacy_kitchen_sink() -> dict:
    leaf_a = "cond_" + "a1" * 16  # state leaf (group member + chain)
    leaf_b = "cond_" + "b1" * 16  # numeric leaf
    leaf_c = "cond_" + "c1" * 16  # template leaf (on chain)
    leaf_d = "cond_" + "d1" * 16  # time leaf
    leaf_e = "cond_" + "e1" * 16  # sun leaf
    leaf_f = "cond_" + "f1" * 16  # calendar leaf
    leaf_g = "cond_" + "11" * 16  # debounce leaf
    leaf_h = "cond_" + "22" * 16  # state leaf (duration start)
    dur = "cond_" + "33" * 16  # duration gate
    flag = "cond_" + "44" * 16  # flag
    grp = "cond_" + "55" * 16  # member-carrying group
    cool = "cond_" + "66" * 16  # cooldown (on chain only)
    out1 = "ssc_" + "7" * 32
    out2 = "ssc_" + "8" * 32
    trg1 = "trg_" + "9" * 32
    trg2 = "trg_" + "a" * 32
    return {
        "name": "存量样例",
        "enabled": True,
        "logging_enabled": False,
        "triggers": [
            {
                "id": trg1,
                "type": "state",
                "label": "状态触发",
                "enabled": True,
                "entity_id": ["switch.c", "sensor.a"],
                "routes": {"conditions": [leaf_a, leaf_b, leaf_h]},
            },
            {
                "id": trg2,
                "type": "time",
                "label": "",
                "enabled": False,
                "every_seconds": 600,
                "routes": {"conditions": [leaf_d]},
            },
        ],
        "conditions": [
            {"id": leaf_a, "type": "state", "label": "c 开", "enabled": True,
             "entity_id": "switch.c", "state": "on"},
            {"id": leaf_b, "type": "numeric_state", "label": "", "enabled": True,
             "entity_id": "sensor.a", "above": 5.0},
            {"id": leaf_c, "type": "template", "label": "", "enabled": True,
             "value_template": "{{ true }}"},
            {"id": leaf_d, "type": "time", "label": "", "enabled": True,
             "after": "22:00", "before": "06:00", "weekdays": ["mon", "tue"]},
            {"id": leaf_e, "type": "sun", "label": "", "enabled": True,
             "after": "sunrise", "after_offset": 300},
            {"id": leaf_f, "type": "calendar", "label": "", "enabled": True,
             "entity_id": "calendar.x", "hours": 12.0},
            {"id": leaf_g, "type": "debounce", "label": "", "enabled": True,
             "entity_id": "switch.d", "seconds": 120},
            {"id": leaf_h, "type": "state", "label": "", "enabled": True,
             "entity_id": "switch.d", "state": "on"},
            {"id": dur, "type": "duration", "label": "", "enabled": True,
             "seconds": 5, "start": leaf_h, "abort": None},
            {"id": flag, "type": "flag", "label": "", "enabled": True,
             "set_conditions": [leaf_a], "reset_conditions": [leaf_b],
             "initial": False},
            {"id": grp, "type": "or", "label": "", "enabled": True,
             "conditions": [leaf_c, leaf_e]},
            {"id": cool, "type": "cooldown", "label": "", "enabled": True,
             "seconds": 60},
        ],
        "outputs": [
            {"name": "o1", "type": "switch", "entity_id": out1,
             "manual_override": True,
             "on_conditions": [grp, flag], "off_conditions": [cool]},
            {"name": "o2", "type": "binary_sensor", "entity_id": out2,
             "on_conditions": [dur, leaf_f, leaf_g], "off_conditions": []},
        ],
    }


def _dumps(cfg: dict) -> str:
    return json.dumps(cfg, sort_keys=True, ensure_ascii=False)


def test_legacy_config_put_roundtrip_is_byte_identical() -> None:
    """validate_controller is idempotent on the stored (already validated)
    legacy shape — the GET→PUT round-trip changes zero bytes."""
    stored = validate_controller(_legacy_kitchen_sink())
    again = validate_controller(json.loads(_dumps(stored)))
    assert _dumps(again) == _dumps(stored), "round-trip mutated the stored form"


def test_legacy_config_accepts_new_types_without_drift() -> None:
    """A legacy config validates byte-identically whether or not the 0.13.0
    types exist in the codebase — the pure-addition guarantee (the same
    stored form, re-PUT, must not suddenly include or drop keys)."""
    stored = validate_controller(_legacy_kitchen_sink())
    # every legacy condition type survives with its own keys intact
    types = {c["type"] for c in stored["conditions"]}
    assert types == {
        "state", "numeric_state", "template", "time", "sun", "calendar",
        "debounce", "duration", "flag", "or", "cooldown",
    }, types
    # no data-node keys leaked into legacy nodes
    for c in stored["conditions"]:
        assert "capture" not in c and "value_type" not in c and "op" not in c, c


def _stateful_kitchen_sink() -> dict:
    """The 0.14.0 stateful-node shapes: all three kinds with both gates
    wired, driven by a shared leaf, chained into an output."""
    leaf = "cond_" + "a1" * 16
    reset = "cond_" + "b1" * 16
    cd = "cond_" + "c1" * 16
    qt = "cond_" + "d1" * 16
    tl = "cond_" + "e1" * 16
    out1 = "ssc_" + "7" * 32
    trg1 = "trg_" + "9" * 32
    return {
        "name": "状态节点样例",
        "enabled": True,
        "logging_enabled": False,
        "triggers": [
            {"id": trg1, "type": "state", "label": "状态触发", "enabled": True,
             "entity_id": ["switch.c"], "routes": {"conditions": [leaf]}},
        ],
        "conditions": [
            {"id": leaf, "type": "state", "label": "c 开", "enabled": True,
             "entity_id": "switch.c", "state": "on"},
            {"id": reset, "type": "time", "label": "", "enabled": True,
             "after": "22:00", "before": "06:00"},
            {"id": cd, "type": "countdown", "label": "cd", "enabled": True,
             "seconds": 90, "start_conditions": [leaf], "reset_conditions": [reset]},
            {"id": qt, "type": "quota", "label": "qt", "enabled": True,
             "times": 3, "consume_conditions": [leaf], "reset_conditions": [reset]},
            {"id": tl, "type": "tally", "label": "tl", "enabled": True,
             "count_conditions": [leaf], "reset_conditions": []},
        ],
        "outputs": [
            {"name": "o1", "type": "switch", "entity_id": out1,
             "on_conditions": [cd, qt, tl], "off_conditions": []},
        ],
    }


def test_stateful_config_put_roundtrip_is_byte_identical() -> None:
    """The 0.14.0 stateful shapes are idempotent under validate_controller —
    the GET→PUT round-trip changes zero bytes (same guarantee as the legacy
    sink, extended to the new node kinds)."""
    stored = validate_controller(_stateful_kitchen_sink())
    again = validate_controller(json.loads(_dumps(stored)))
    assert _dumps(again) == _dumps(stored), "round-trip mutated the stored form"
    types = {c["type"] for c in stored["conditions"]}
    assert {"countdown", "quota", "tally"} <= types, types
