"""Shared validation for controller configs (web API and config flow).

The persisted JSON shape intentionally matches the pre-0.4.0 options-flow
schema: sensors / conditions / outputs lists with ``cond_<hex>`` ids and
``ssc_<hex>`` output ids. Only new additive fields (controller-level
``name``/``enabled``, sensor ``alias``) were introduced with 0.4.0.
"""

from __future__ import annotations

import math
import re
import uuid

import voluptuous as vol
from homeassistant.helpers import config_validation as cv

from .const import (
    COND_AND,
    COND_NUMERIC_STATE,
    COND_OR,
    COND_STATE,
    COND_SUN,
    COND_TEMPLATE,
    COND_TIME,
    DEFAULT_SCAN_INTERVAL,
    OUTPUT_BINARY_SENSOR,
    OUTPUT_SWITCH,
    SCAN_INTERVAL_MAX,
    SCAN_INTERVAL_MIN,
    SUN_OFFSET_LIMIT,
)

_COND_ID_RE = re.compile(r"^cond_[0-9a-f]{32}$")
_OUT_ID_RE = re.compile(r"^ssc_[0-9a-f]{32}$")
CTRL_ID_RE = re.compile(r"^ctrl_[0-9a-f]{8}$")
_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d(?::[0-5]\d)?$")
_MAX_LABEL_LEN = 100
_MAX_TEMPLATE_LEN = 2000

LEAF_TYPES = (
    COND_NUMERIC_STATE,
    COND_STATE,
    COND_TIME,
    COND_SUN,
    COND_TEMPLATE,
)
GROUP_TYPES = (COND_AND, COND_OR)
OUTPUT_TYPES = (OUTPUT_SWITCH, OUTPUT_BINARY_SENSOR)


class ControllerValidationError(ValueError):
    """A controller config failed validation; message is user-facing."""


def _fail(msg: str) -> None:
    raise ControllerValidationError(msg)


def _to_bool(value, field: str) -> bool:
    """Strict boolean: only real booleans pass (no "false" → True traps)."""
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    _fail(f"{field} 必须是布尔值")


def _optional_str(value, field: str, max_len: int = _MAX_LABEL_LEN) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        _fail(f"{field} 必须是字符串")
    value = value.strip()
    if len(value) > max_len:
        _fail(f"{field} 长度不能超过 {max_len}")
    return value


def _validate_entity_id(value, field: str) -> str:
    if not isinstance(value, str):
        _fail(f"{field} 必须是实体 ID 字符串")
    value = value.strip()
    try:
        return cv.entity_id(value)
    except vol.Invalid as err:
        _fail(f"{field} 不是合法实体 ID：{value!r}（{err}）")


def _validate_for(value, field: str) -> dict | None:
    """Normalize a FOR duration into {"hours","minutes","seconds"} or None."""
    if value in (None, False):
        return None
    if isinstance(value, bool):
        _fail(f"{field} 的持续时长格式不合法")
    if isinstance(value, (int, float)):
        try:
            seconds = int(value)
        except (OverflowError, ValueError):
            _fail(f"{field} 的持续时长格式不合法")
        if seconds <= 0:
            return None
        return {"hours": 0, "minutes": 0, "seconds": seconds}
    if not isinstance(value, dict):
        _fail(f"{field} 的持续时长格式不合法")
    try:
        hours = int(value.get("hours") or 0)
        minutes = int(value.get("minutes") or 0)
        seconds = int(value.get("seconds") or 0)
    except (OverflowError, TypeError, ValueError):
        _fail(f"{field} 的持续时长格式不合法")
    if hours < 0 or minutes < 0 or seconds < 0:
        _fail(f"{field} 的持续时长不能为负数")
    if hours > 24 or minutes > 59 or seconds > 59:
        _fail(f"{field} 的持续时长超出范围（时 0-24、分/秒 0-59）")
    if hours == 0 and minutes == 0 and seconds == 0:
        return None
    return {"hours": hours, "minutes": minutes, "seconds": seconds}


def _validate_condition(cond) -> dict:
    if not isinstance(cond, dict):
        _fail("条件必须是对象")
    ctype = cond.get("type")
    if ctype not in LEAF_TYPES + GROUP_TYPES:
        _fail(f"未知条件类型：{ctype!r}")

    cid = cond.get("id")
    if cid is None:
        cid = f"cond_{uuid.uuid4().hex}"
    elif not isinstance(cid, str) or not _COND_ID_RE.match(cid):
        _fail(f"条件 id 非法：{cid!r}（应为 cond_<32位hex>）")

    label = _optional_str(cond.get("label"), "条件标签")

    result: dict = {"id": cid, "type": ctype, "label": label}

    if ctype == COND_NUMERIC_STATE:
        result["entity_id"] = _validate_entity_id(cond.get("entity_id"), "条件实体")
        above = cond.get("above")
        below = cond.get("below")
        try:
            above_f = float(above) if above is not None else None
            below_f = float(below) if below is not None else None
        except (OverflowError, TypeError, ValueError):
            _fail("数值条件的 above/below 必须是数字")
        for fname, fval in (("above", above_f), ("below", below_f)):
            if fval is not None and not math.isfinite(fval):
                _fail(f"数值条件的 {fname} 必须是有限数字")
        if above_f is None and below_f is None:
            _fail("数值条件必须提供 above 或 below")
        if above_f is not None:
            result["above"] = above_f
        if below_f is not None:
            result["below"] = below_f
        for_cfg = _validate_for(cond.get("for"), "数值条件")
        if for_cfg:
            result["for"] = for_cfg

    elif ctype == COND_STATE:
        result["entity_id"] = _validate_entity_id(cond.get("entity_id"), "条件实体")
        state = cond.get("state")
        if state is None:
            _fail("状态条件必须提供 state")
        if isinstance(state, str):
            states = [s.strip() for s in state.split(",") if s.strip()]
        elif isinstance(state, list) and all(isinstance(s, str) for s in state):
            states = [s.strip() for s in state if s.strip()]
        else:
            _fail("状态条件的 state 必须是字符串或字符串列表")
        if not states:
            _fail("状态条件的 state 不能为空")
        result["state"] = states[0] if len(states) == 1 else states
        for_cfg = _validate_for(cond.get("for"), "状态条件")
        if for_cfg:
            result["for"] = for_cfg

    elif ctype == COND_TIME:
        for key in ("after", "before"):
            value = cond.get(key)
            if value in (None, ""):
                continue
            if not isinstance(value, str) or not _TIME_RE.match(value.strip()):
                _fail(f"时间条件的 {key} 必须是 HH:MM 或 HH:MM:SS")
            result[key] = value.strip()
        if "after" not in result and "before" not in result:
            _fail("时间条件必须提供 after 或 before")

    elif ctype == COND_SUN:
        for key in ("after", "before"):
            value = cond.get(key)
            if value in (None, "", "none"):
                continue
            if value not in ("sunrise", "sunset"):
                _fail(f"日出日落条件的 {key} 只能是 sunrise/sunset")
            result[key] = value
        if "after" not in result and "before" not in result:
            _fail("日出日落条件必须提供 after 或 before")
        for key in ("after_offset", "before_offset"):
            value = cond.get(key)
            if value in (None, 0, ""):
                continue
            try:
                offset = int(value)
            except (OverflowError, TypeError, ValueError):
                _fail(f"日出日落条件的 {key} 必须是秒数整数")
            if abs(offset) > SUN_OFFSET_LIMIT:
                _fail(f"日出日落条件的 {key} 偏移量不能超过 ±{SUN_OFFSET_LIMIT} 秒")
            if offset:
                result[key] = offset

    elif ctype == COND_TEMPLATE:
        template = cond.get("value_template")
        if not isinstance(template, str) or not template.strip():
            _fail("模板条件必须提供 value_template")
        if len(template) > _MAX_TEMPLATE_LEN:
            _fail(f"模板表达式长度不能超过 {_MAX_TEMPLATE_LEN}")
        result["value_template"] = template

    else:  # and / or
        members = cond.get("conditions")
        if not isinstance(members, list) or not members:
            _fail(f"{ctype} 组条件必须至少引用一个成员条件")
        if not all(isinstance(m, str) for m in members):
            _fail("组条件的成员必须是条件 id 字符串")
        if len(set(members)) != len(members):
            _fail("组条件的成员不能重复")
        result["conditions"] = list(members)

    return result


def _validate_output(out) -> dict:
    if not isinstance(out, dict):
        _fail("输出必须是对象")
    otype = out.get("type", OUTPUT_SWITCH)
    if otype not in OUTPUT_TYPES:
        _fail(f"未知输出类型：{otype!r}")
    name = _optional_str(out.get("name"), "输出名称")
    if not name:
        _fail("输出名称不能为空")
    out_id = out.get("entity_id")
    if out_id is None:
        out_id = f"ssc_{uuid.uuid4().hex}"
    elif not isinstance(out_id, str) or not _OUT_ID_RE.match(out_id):
        _fail(f"输出 id 非法：{out_id!r}（应为 ssc_<32位hex>）")
    result: dict = {
        "name": name,
        "type": otype,
        "entity_id": out_id,
        "manual_override": _to_bool(out.get("manual_override", False), "输出的 manual_override"),
    }
    for key in ("on_conditions", "off_conditions"):
        members = out.get(key) or []
        if not isinstance(members, list) or not all(isinstance(m, str) for m in members):
            _fail(f"输出的 {key} 必须是条件 id 字符串列表")
        result[key] = list(dict.fromkeys(members))
    return result


def _check_graph(conditions: list[dict], outputs: list[dict]) -> None:
    """Cross checks: unique ids, group refs, cycles, output refs."""
    by_id: dict[str, dict] = {}
    for cond in conditions:
        if cond["id"] in by_id:
            _fail(f"条件 id 重复：{cond['id']}")
        by_id[cond["id"]] = cond

    for cond in conditions:
        if cond["type"] in GROUP_TYPES:
            for member in cond["conditions"]:
                if member not in by_id:
                    _fail(f"组条件引用了不存在的成员：{member}")

    # Cycle detection over group references (iterative DFS with colors).
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {cid: WHITE for cid in by_id}
    for root, root_cond in by_id.items():
        if color[root] != WHITE:
            continue
        stack = [(root, iter(root_cond.get("conditions", []) or []))]
        color[root] = GRAY
        while stack:
            node, members = stack[-1]
            advanced = False
            for member in members:
                if member not in by_id:
                    continue
                state = color[member]
                if state == GRAY:
                    _fail("组条件存在循环引用")
                if state == WHITE:
                    color[member] = GRAY
                    stack.append(
                        (member, iter(by_id[member].get("conditions", []) or []))
                    )
                    advanced = True
                    break
            if not advanced:
                color[node] = BLACK
                stack.pop()

    seen_out: set[str] = set()
    for out in outputs:
        if out["entity_id"] in seen_out:
            _fail(f"输出 id 重复：{out['entity_id']}")
        seen_out.add(out["entity_id"])
        for key in ("on_conditions", "off_conditions"):
            for member in out[key]:
                if member not in by_id:
                    _fail(f"输出的 {key} 引用了不存在的条件：{member}")


def validate_controller(data) -> dict:
    """Validate and normalize one controller dict; raises on bad input."""
    if not isinstance(data, dict):
        _fail("控制器配置必须是对象")

    name = _optional_str(data.get("name"), "控制器名称")
    if not name:
        _fail("控制器名称不能为空")

    scan_interval = data.get("scan_interval", DEFAULT_SCAN_INTERVAL)
    try:
        scan_interval = int(scan_interval)
    except (OverflowError, TypeError, ValueError):
        _fail("扫描间隔必须是秒数整数")
    if not SCAN_INTERVAL_MIN <= scan_interval <= SCAN_INTERVAL_MAX:
        _fail(f"扫描间隔必须在 {SCAN_INTERVAL_MIN}-{SCAN_INTERVAL_MAX} 秒之间")

    sensors: list[dict] = []
    seen_sensors: set[str] = set()
    raw_sensors = data.get("sensors") or []
    if not isinstance(raw_sensors, list):
        _fail("传感器池必须是列表")
    for raw in raw_sensors:
        if not isinstance(raw, dict):
            _fail("传感器池条目必须是对象")
        entity_id = _validate_entity_id(raw.get("entity_id"), "传感器池实体")
        if entity_id in seen_sensors:
            continue
        seen_sensors.add(entity_id)
        sensors.append(
            {"entity_id": entity_id, "alias": _optional_str(raw.get("alias"), "传感器别名")}
        )

    raw_conditions = data.get("conditions") or []
    if not isinstance(raw_conditions, list):
        _fail("条件列表必须是列表")
    conditions = [_validate_condition(cond) for cond in raw_conditions]

    raw_outputs = data.get("outputs") or []
    if not isinstance(raw_outputs, list):
        _fail("输出列表必须是列表")
    outputs = [_validate_output(out) for out in raw_outputs]

    _check_graph(conditions, outputs)

    return {
        "name": name,
        "enabled": _to_bool(data.get("enabled", True), "控制器 enabled"),
        "scan_interval": scan_interval,
        "logging_enabled": _to_bool(data.get("logging_enabled", False), "控制器 logging_enabled"),
        "sensors": sensors,
        "conditions": conditions,
        "outputs": outputs,
    }

