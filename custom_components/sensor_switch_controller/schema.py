"""Shared validation for controller configs (web API and config flow).

The persisted JSON shape intentionally matches the pre-0.4.0 options-flow
schema: sensors / conditions / outputs lists with ``cond_<hex>`` ids and
``ssc_<hex>`` output ids. Since 0.5.0 evaluation is trigger-driven:
``triggers`` replaces the global ``scan_interval`` (old configs map their
interval to a time trigger on load). Since 0.6.0 triggers carry optional
``routes`` (directed evaluation: absent → legacy evaluate-everything,
present → the outputs reachable from the covered conditions) and two new
leaf conditions exist: ``duration`` (TON gate with start/abort inputs)
and ``debounce`` (true once the entity has been quiet for N seconds).
Since 0.7.0 routes carry conditions only — triggers never wire outputs
directly (an ``outputs`` key in routes is rejected). Since 0.7.1 the
conditions named by routes must be plain leaves: and/or/not groups and
duration gates are not signal origins (rejected at graph level).
"""

from __future__ import annotations

import math
import re
import uuid

import voluptuous as vol
from homeassistant.helpers import config_validation as cv

from .const import (
    CALENDAR_HOURS_MAX,
    COND_AND,
    COND_CALENDAR,
    COND_COOLDOWN,
    COND_DEBOUNCE,
    COND_DURATION,
    COND_NOT,
    COND_NUMERIC_STATE,
    COND_OR,
    COND_STATE,
    COND_SUN,
    COND_TEMPLATE,
    COND_TIME,
    CONF_ABORT,
    CONF_AT,
    CONF_EVERY_SECONDS,
    CONF_HOURS,
    CONF_OFFSET,
    CONF_ROUTES,
    CONF_SCAN_INTERVAL,
    CONF_SECONDS,
    CONF_START,
    CONF_TRIGGERS,
    CONF_WEEKDAYS,
    COOLDOWN_MAX,
    DEBOUNCE_MAX,
    DEFAULT_SCAN_INTERVAL,
    DURATION_MAX,
    OUTPUT_BINARY_SENSOR,
    OUTPUT_SWITCH,
    SUN_OFFSET_LIMIT,
    TRG_HOMEASSISTANT,
    TRG_ID_PREFIX,
    TRG_STATE,
    TRG_SUN,
    TRG_TIME,
    WEEKDAYS,
)

_COND_ID_RE = re.compile(r"^cond_[0-9a-f]{32}$")
_OUT_ID_RE = re.compile(r"^ssc_[0-9a-f]{32}$")
_TRG_ID_RE = re.compile(r"^trg_[0-9a-f]{32}$")
CTRL_ID_RE = re.compile(r"^ctrl_[0-9a-f]{8}$")
_TIME_RE = re.compile(r"^([01]?\d|2[0-3]):[0-5]\d(:[0-5]\d)?$")
_MAX_LABEL_LEN = 100
_MAX_TEMPLATE_LEN = 2000

LEAF_TYPES = (
    COND_NUMERIC_STATE,
    COND_STATE,
    COND_TIME,
    COND_SUN,
    COND_TEMPLATE,
    COND_COOLDOWN,
    COND_CALENDAR,
    COND_DURATION,
    COND_DEBOUNCE,
)
GROUP_TYPES = (COND_AND, COND_OR, COND_NOT)
OUTPUT_TYPES = (OUTPUT_SWITCH, OUTPUT_BINARY_SENSOR)
TRIGGER_TYPES = (TRG_STATE, TRG_TIME, TRG_SUN, TRG_HOMEASSISTANT)
EVERY_SECONDS_MIN, EVERY_SECONDS_MAX = 10, 86400


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


def _validate_weekdays(value) -> list[str] | None:
    """Validate a weekday list (mon..sun); None when absent/empty."""
    if value in (None, "", []):
        return None
    if not isinstance(value, list) or not all(isinstance(d, str) for d in value):
        _fail("星期几必须是 mon/tue/wed/thu/fri/sat/sun 列表")
    days = [d.strip().lower() for d in value]
    bad = [d for d in days if d not in WEEKDAYS]
    if bad:
        _fail(f"非法星期值：{bad}（允许 {list(WEEKDAYS)}）")
    deduped = list(dict.fromkeys(days))
    return deduped or None


def _normalize_time(value: str) -> str:
    """Zero-pad a validated HH:MM[:SS] so the stored form is canonical.

    ``dt_util.parse_time`` may reject unpadded hours like "7:30"; storing
    "07:30" keeps evaluation and wakeup discovery reading the same value.
    """
    parts = value.split(":")
    return ":".join(f"{int(p):02d}" for p in parts)


# ------------------------------------------------------------------
# Triggers
# ------------------------------------------------------------------


def _validate_state_filter(value, field: str) -> str | list[str] | None:
    if value in (None, ""):
        return None
    if isinstance(value, str):
        states = [s.strip() for s in value.split(",") if s.strip()]
    elif isinstance(value, list) and all(isinstance(s, str) for s in value):
        states = [s.strip() for s in value if s.strip()]
    else:
        _fail(f"{field} 必须是字符串或字符串列表")
    return states[0] if len(states) == 1 else (states or None)


def validate_trigger(trg) -> dict:
    """Validate and normalize one trigger; raises on bad input.

    A well-formed caller-supplied ``id`` is preserved so canvas wires
    (trigger routes) survive save/reload round-trips; only a missing or
    malformed id gets a fresh one. ``routes`` is optional: present means
    directed routing (evaluate the outputs reachable from the covered
    conditions — routes carry conditions only), absent means legacy
    behaviour (evaluate everything).
    """
    if not isinstance(trg, dict):
        _fail("触发器必须是对象")
    ttype = trg.get("type")
    if ttype not in TRIGGER_TYPES:
        _fail(f"未知触发器类型：{ttype!r}")

    tid = trg.get("id")
    if isinstance(tid, str) and _TRG_ID_RE.match(tid):
        result_id = tid
    else:
        result_id = f"{TRG_ID_PREFIX}{uuid.uuid4().hex}"

    result: dict = {
        "id": result_id,
        "type": ttype,
        "label": _optional_str(trg.get("label"), "触发器标签"),
        "enabled": _to_bool(trg.get("enabled", True), "触发器 enabled"),
    }

    routes = trg.get(CONF_ROUTES)
    if routes is not None:
        if not isinstance(routes, dict):
            _fail("触发器的 routes 必须是对象")
        if "outputs" in routes:
            _fail(
                "触发器不再直连输出：信号线请连到条件，"
                "输出只由条件链决定"
            )
        result[CONF_ROUTES] = _validate_routes(routes)

    if ttype == TRG_STATE:
        entity_id = trg.get("entity_id")
        if entity_id in (None, ""):
            # empty = whole sensor pool
            result["entity_id"] = None
        else:
            result["entity_id"] = _validate_entity_id(entity_id, "触发实体")
        attribute = _optional_str(trg.get("attribute"), "触发 attribute")
        if attribute:
            result["attribute"] = attribute
        for key in ("from", "to"):
            mapped = _validate_state_filter(trg.get(key), f"触发器 {key}")
            if mapped is not None:
                result[key] = mapped

    elif ttype == TRG_TIME:
        at = trg.get(CONF_AT)
        every = trg.get(CONF_EVERY_SECONDS)
        if at and every:
            _fail("时间触发器的 at 与 every_seconds 只能二选一")
        if at:
            if not isinstance(at, str) or not _TIME_RE.match(at.strip()):
                _fail("时间触发的 at 必须是 HH:MM 或 HH:MM:SS")
            result[CONF_AT] = at.strip()
        elif every is not None:
            try:
                every = int(every)
            except (OverflowError, TypeError, ValueError):
                _fail("时间触发的 every_seconds 必须是秒数整数")
            if not EVERY_SECONDS_MIN <= every <= EVERY_SECONDS_MAX:
                _fail(
                    f"时间触发的 every_seconds 必须在 "
                    f"{EVERY_SECONDS_MIN}-{EVERY_SECONDS_MAX} 秒之间"
                )
            result[CONF_EVERY_SECONDS] = every
        else:
            _fail("时间触发器必须提供 at 或 every_seconds")

    elif ttype == TRG_SUN:
        event = trg.get("event")
        if event not in ("sunrise", "sunset"):
            _fail("太阳触发的 event 必须是 sunrise 或 sunset")
        result["event"] = event
        offset = trg.get(CONF_OFFSET)
        if offset not in (None, 0):
            try:
                offset = int(offset)
            except (OverflowError, TypeError, ValueError):
                _fail("太阳触发的 offset 必须是秒数整数")
            if abs(offset) > SUN_OFFSET_LIMIT:
                _fail(f"太阳触发 offset 不能超过 ±{SUN_OFFSET_LIMIT} 秒")
            if offset:
                result[CONF_OFFSET] = offset

    else:  # homeassistant
        result["event"] = "start"

    return result


def _validate_routes(routes: dict) -> dict:
    """Normalize trigger routes: {conditions: [cond_id]} (0.7.0: triggers
    start evaluation, they no longer wire straight to outputs)."""
    validated: dict[str, list[str]] = {}
    for key, pattern, name in (
        ("conditions", _COND_ID_RE, "条件"),
    ):
        members = routes.get(key) or []
        if not isinstance(members, list) or not all(
            isinstance(m, str) for m in members
        ):
            _fail(f"触发器路由的 {key} 必须是 {name} id 字符串列表")
        for member in members:
            if not pattern.match(member):
                _fail(f"触发器路由的 {key} 含非法 id：{member!r}")
        validated[key] = list(dict.fromkeys(members))
    return validated


def _map_legacy_scan_interval(data: dict) -> list[dict]:
    """Old configs carried a global scan_interval; keep its cadence as a
    time trigger so upgrades never silently stop evaluating."""
    interval = data.get(CONF_SCAN_INTERVAL)
    try:
        interval = int(interval)
    except (TypeError, ValueError):
        interval = DEFAULT_SCAN_INTERVAL
    interval = max(EVERY_SECONDS_MIN, min(interval, EVERY_SECONDS_MAX))
    return [
        {
            "id": f"{TRG_ID_PREFIX}{uuid.uuid4().hex}",
            "type": TRG_TIME,
            "label": "（原扫描间隔）",
            "enabled": True,
            CONF_EVERY_SECONDS: interval,
        }
    ]


def validate_triggers(data: dict) -> list[dict]:
    """Validate the trigger list, mapping legacy scan_interval when absent."""
    raw = data.get(CONF_TRIGGERS)
    if raw is None:
        # pre-0.5.0 config: preserve polling cadence as an explicit trigger
        if data.get(CONF_SCAN_INTERVAL) is not None:
            return _map_legacy_scan_interval(data)
        return []
    if not isinstance(raw, list):
        _fail("触发器必须是列表")
    return [validate_trigger(trg) for trg in raw]


# ------------------------------------------------------------------
# Conditions
# ------------------------------------------------------------------


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
    enabled = _to_bool(cond.get("enabled", True), "条件 enabled")

    result: dict = {"id": cid, "type": ctype, "label": label, "enabled": enabled}

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

    elif ctype == COND_TIME:
        if cond.get(CONF_AT) not in (None, ""):
            _fail(
                "时间条件已不支持 at：每日时刻请改用「每日时刻」触发器，"
                "持续等待请改用「持续」条件"
            )
        for key in ("after", "before"):
            value = cond.get(key)
            if value in (None, ""):
                continue
            if not isinstance(value, str) or not _TIME_RE.match(value.strip()):
                _fail(f"时间条件的 {key} 必须是 HH:MM 或 HH:MM:SS")
            result[key] = _normalize_time(value.strip())
        if "after" not in result and "before" not in result:
            _fail("时间条件必须提供 after 或 before")
        weekdays = _validate_weekdays(cond.get(CONF_WEEKDAYS))
        if weekdays:
            result[CONF_WEEKDAYS] = weekdays

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

    elif ctype == COND_COOLDOWN:
        seconds = cond.get(CONF_SECONDS)
        if isinstance(seconds, float) and not seconds.is_integer():
            _fail("冷却条件的 seconds 必须是整数秒")
        try:
            seconds = int(seconds)
        except (OverflowError, TypeError, ValueError):
            _fail("冷却条件的 seconds 必须是秒数整数")
        if not 1 <= seconds <= COOLDOWN_MAX:
            _fail(f"冷却条件的 seconds 必须在 1-{COOLDOWN_MAX} 秒之间")
        result[CONF_SECONDS] = seconds

    elif ctype == COND_CALENDAR:
        result["entity_id"] = _validate_entity_id(cond.get("entity_id"), "日历实体")
        if not result["entity_id"].startswith("calendar."):
            _fail("日历条件的实体必须是 calendar.* 域")
        hours = cond.get(CONF_HOURS, 24)
        try:
            hours = float(hours)
        except (OverflowError, TypeError, ValueError):
            _fail("日历条件的 hours 必须是数字")
        if not math.isfinite(hours) or not 0 < hours <= CALENDAR_HOURS_MAX:
            _fail(f"日历条件的 hours 必须在 0-{CALENDAR_HOURS_MAX} 之间")
        result[CONF_HOURS] = hours

    elif ctype == COND_DURATION:
        # TON gate: true once `start` has held for `seconds`, reset when
        # `start` drops or `abort` turns true. Reference validity is
        # checked against the whole graph in _check_graph.
        seconds = cond.get(CONF_SECONDS)
        if isinstance(seconds, float) and not seconds.is_integer():
            _fail("持续条件的 seconds 必须是整数秒")
        try:
            seconds = int(seconds)
        except (OverflowError, TypeError, ValueError):
            _fail("持续条件的 seconds 必须是秒数整数")
        if not 1 <= seconds <= DURATION_MAX:
            _fail(f"持续条件的 seconds 必须在 1-{DURATION_MAX} 秒之间")
        result[CONF_SECONDS] = seconds
        start = cond.get(CONF_START)
        if not isinstance(start, str) or not _COND_ID_RE.match(start):
            _fail("持续条件必须提供 start（开始条件的 id）")
        if start == cid:
            _fail("持续条件不能以自身作为开始条件")
        result[CONF_START] = start
        abort = cond.get(CONF_ABORT)
        if abort in (None, ""):
            result[CONF_ABORT] = None
        else:
            if not isinstance(abort, str) or not _COND_ID_RE.match(abort):
                _fail("持续条件的 abort 必须是条件 id 或留空")
            if abort == cid:
                _fail("持续条件不能以自身作为中止条件")
            result[CONF_ABORT] = abort

    elif ctype == COND_DEBOUNCE:
        # True once the entity has been quiet (no state change) for
        # `seconds` — the "reset on retrigger" delay, stateless by design.
        seconds = cond.get(CONF_SECONDS)
        if isinstance(seconds, float) and not seconds.is_integer():
            _fail("防抖条件的 seconds 必须是整数秒")
        try:
            seconds = int(seconds)
        except (OverflowError, TypeError, ValueError):
            _fail("防抖条件的 seconds 必须是秒数整数")
        if not 1 <= seconds <= DEBOUNCE_MAX:
            _fail(f"防抖条件的 seconds 必须在 1-{DEBOUNCE_MAX} 秒之间")
        result[CONF_SECONDS] = seconds
        result["entity_id"] = _validate_entity_id(cond.get("entity_id"), "防抖实体")

    else:  # and / or / not
        members = cond.get("conditions")
        if not isinstance(members, list) or not members:
            _fail(f"{ctype} 组条件必须至少引用一个成员条件")
        if not all(isinstance(m, str) for m in members):
            _fail("组条件的成员必须是条件 id 字符串")
        if len(set(members)) != len(members):
            _fail("组条件的成员不能重复")
        result["conditions"] = list(members)

    if ctype in LEAF_TYPES and ctype not in (COND_DURATION, COND_DEBOUNCE):
        # `for` (hold-before-true) is valid on every ordinary leaf; the
        # engine applies it generically. duration/debounce are timing gates
        # themselves and must not nest one.
        for_cfg = _validate_for(cond.get("for"), "条件")
        if for_cfg:
            result["for"] = for_cfg

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


def _condition_neighbors(cond: dict) -> list[str]:
    """Referenced condition ids of one condition (group members, duration
    start/abort) — the edge set for graph checks."""
    edges = list(cond.get("conditions") or [])
    for key in (CONF_START, CONF_ABORT):
        ref = cond.get(key)
        if isinstance(ref, str):
            edges.append(ref)
    return edges


def _check_graph(
    conditions: list[dict], outputs: list[dict], triggers: list[dict] | None = None
) -> None:
    """Cross checks: unique ids, group/duration refs, cycles, output and
    trigger-route refs."""
    by_id: dict[str, dict] = {}
    for cond in conditions:
        if cond["id"] in by_id:
            _fail(f"条件 id 重复：{cond['id']}")
        by_id[cond["id"]] = cond

    for cond in conditions:
        for member in _condition_neighbors(cond):
            if member not in by_id:
                label = cond.get("label") or cond["id"]
                _fail(f"条件「{label}」引用了不存在的成员：{member}")

    # Cycle detection over group references and duration start/abort edges
    # (iterative DFS with colors).
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {cid: WHITE for cid in by_id}
    for root, root_cond in by_id.items():
        if color[root] != WHITE:
            continue
        stack = [(root, iter(_condition_neighbors(root_cond)))]
        color[root] = GRAY
        while stack:
            node, members = stack[-1]
            advanced = False
            for member in members:
                if member not in by_id:
                    continue
                state = color[member]
                if state == GRAY:
                    _fail("条件存在循环引用（组成员或持续的开始/中止链）")
                if state == WHITE:
                    color[member] = GRAY
                    stack.append((member, iter(_condition_neighbors(by_id[member]))))
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

    signal_leaves = set(LEAF_TYPES) - {COND_DURATION}
    for trg in triggers or []:
        tid = trg.get("id")
        if tid and any(
            other is not trg and other.get("id") == tid for other in (triggers or [])
        ):
            _fail(f"触发器 id 重复：{tid}")
        routes = trg.get(CONF_ROUTES)
        if not routes:
            continue
        label = trg.get("label") or trg.get("id") or "?"
        for member in routes.get("conditions", []):
            if member not in by_id:
                _fail(f"触发器「{label}」的路由引用了不存在的条件：{member}")
            ctype = by_id[member]["type"]
            if ctype not in signal_leaves:
                _fail(
                    f"触发器「{label}」的信号线连到了「{by_id[member].get('label') or member}」"
                    f"（{ctype}）：AND/OR/NOT 组与持续门不能被信号直达，"
                    "请连到具体条件的信号口"
                )


def validate_controller(data) -> dict:
    """Validate and normalize one controller dict; raises on bad input."""
    if not isinstance(data, dict):
        _fail("控制器配置必须是对象")

    name = _optional_str(data.get("name"), "控制器名称")
    if not name:
        _fail("控制器名称不能为空")

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

    triggers = validate_triggers(data)
    _check_graph(conditions, outputs, triggers)

    return {
        "name": name,
        "enabled": _to_bool(data.get("enabled", True), "控制器 enabled"),
        "logging_enabled": _to_bool(data.get("logging_enabled", False), "控制器 logging_enabled"),
        "triggers": triggers,
        "sensors": sensors,
        "conditions": conditions,
        "outputs": outputs,
    }
