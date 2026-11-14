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
directly (an ``outputs`` key in routes is rejected). Since 0.7.3 the
logic groups are dual-mode: wiring their signal port makes them trigger
mergers (pass-through, members may be empty while signal-covered), wiring
their members port makes them plain and/or/not gates — the two modes are
mutually exclusive on the canvas. Since 0.9.0 there is a ``flag`` node: a
latched virtual boolean with set/reset condition references; its verdict
is stepped once per evaluation cycle (reset wins over set), it carries no
``for``, and it may be referenced by outputs and groups but not by
triggers' routes nor by another flag's set/reset. Since 0.10.0 legacy
full-sweep triggers are gone: ``routes`` is REQUIRED (absent → rejected;
upgraded stores get it materialized by the v6→v7 store migration, and
pre-0.5 configs without a trigger list get it materialized when their
scan interval maps to a time trigger — same signal-leaf set,
WHA-F-310), and state triggers must declare their trigger entities
explicitly — ``entity_id`` as one id or a list of ids (the old "listen
to the whole sensor pool" default is rejected for ENABLED triggers;
pool-empty migrated stores land invalid with a visible error instead of
a never-firing trigger, while a DISABLED pool listener stays legal and
inert — it never registers, WHA-F-309).
"""

from __future__ import annotations

import hashlib
import logging
import math
import re
import uuid

import voluptuous as vol
from homeassistant.helpers import config_validation as cv

from .const import (
    CALENDAR_HOURS_MAX,
    COMPARE_OPS,
    COND_AND,
    COND_CALENDAR,
    COND_COOLDOWN,
    COND_COMPARE,
    COND_COUNTDOWN,
    COND_DEBOUNCE,
    COND_DURATION,
    COND_FLAG,
    COND_LITERAL,
    COND_NOT,
    COND_NUMERIC_STATE,
    COND_OR,
    COND_QUOTA,
    COND_SNAPSHOT,
    COND_STATE,
    COND_SUN,
    COND_TALLY,
    COND_TEMPLATE,
    COND_TIME,
    CONF_ABORT,
    CONF_AT,
    CONF_CAPTURE,
    CONF_CLEAR,
    CONF_EVERY_SECONDS,
    CONF_HOURS,
    CONF_INITIAL,
    CONF_INPUT_A,
    CONF_INPUT_B,
    CONF_OP,
    CONF_OFFSET,
    CONF_RESET_CONDITIONS,
    CONF_ROUTES,
    CONF_SCAN_INTERVAL,
    CONF_SECONDS,
    CONF_SET_CONDITIONS,
    CONF_START,
    CONF_TRIGGERS,
    CONF_VALUE,
    CONF_VALUE_TYPE,
    CONF_WEEKDAYS,
    COOLDOWN_MAX,
    DEBOUNCE_MAX,
    DEFAULT_SCAN_INTERVAL,
    DURATION_MAX,
    OUTPUT_BINARY_SENSOR,
    OUTPUT_SWITCH,
    QUOTA_MAX,
    SUN_OFFSET_LIMIT,
    STATEFUL_GATE_KEYS,
    STATEFUL_TYPES,
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

_LOGGER = logging.getLogger(__name__)

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
    COND_SNAPSHOT,
    COND_LITERAL,
    COND_COMPARE,
)
GROUP_TYPES = (COND_AND, COND_OR, COND_NOT)
# NOT signal origins (R2-7): timing gates latch/hold internal state and
# the 0.13.0 data nodes carry no signal port on the canvas — a trigger
# route naming one is hand-written, can never fire meaningfully and would
# be silently dropped by the next canvas save (_exportGraph rebuilds
# routes from drawable wires). Shared by the _check_graph route rejection
# and the _signal_leaf_ids materialization filter so the two cannot drift.
NON_SIGNAL_TYPES = (
    COND_DURATION,
    COND_FLAG,
    COND_SNAPSHOT,
    COND_LITERAL,
    COND_COMPARE,
    # stateful step nodes (0.14.0): latched verdicts, no signal port —
    # same rejection face as the 0.13.0 data nodes
    *STATEFUL_TYPES,
)
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
    malformed id gets a fresh one. ``routes`` is REQUIRED since 0.10.0
    (legacy full-sweep evaluation is deprecated): present means directed
    routing — evaluate the outputs reachable from the covered conditions
    (routes carry conditions only). The v6→v7 store migration materializes
    routes for upgraded configs, and the pre-0.5 scan-interval mapping
    materializes them for trigger-less configs, before validation runs.
    """
    if not isinstance(trg, dict):
        _fail("触发器必须是对象")
    ttype = trg.get("type")
    if ttype not in TRIGGER_TYPES:
        _fail(f"未知触发器类型：{ttype!r}")

    routes = trg.get(CONF_ROUTES)
    if routes is None:
        # 0.10.0: legacy full-sweep (routes absent) is deprecated — every
        # trigger must declare its signal coverage explicitly so the canvas
        # and the decision log can always answer "what fired what".
        _fail(
            "触发器缺少 routes（0.10.0 起废弃遗留全量评估）："
            "请在画布把信号线连到条件；存量配置升级后由 v7 迁移自动物化"
        )

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
        if entity_id in (None, "", []):
            if result["enabled"] is False:
                # 0.10.0 carve-out (WHA-F-309): a DISABLED state trigger
                # never registers (TriggerManager.async_setup skips
                # enabled=False before registration), so the v6-legal
                # "disabled pool listener" shape — including the empty-pool
                # migration result — stays valid and inert, normalized to
                # an empty list. Enabling it re-runs validation, which
                # then requires explicit entities.
                result["entity_id"] = []
            else:
                # 0.10.0: "empty = whole sensor pool" is deprecated — the
                # trigger entities must be declared explicitly. Pool-empty
                # migrated ENABLED triggers land invalid here (a
                # never-firing trigger was already a registration error).
                _fail(
                    "state 触发器必须声明触发实体（0.10.0 起废弃留空="
                    "监听整个传感器池）：请填写实体，多个实体用列表"
                )
        elif isinstance(entity_id, str):
            result["entity_id"] = _validate_entity_id(entity_id, "触发实体")
        elif isinstance(entity_id, list):
            if not all(isinstance(e, str) for e in entity_id):
                _fail("触发实体列表必须全是实体 ID 字符串")
            result["entity_id"] = list(
                dict.fromkeys(
                    _validate_entity_id(e, "触发实体") for e in entity_id
                )
            )
        else:
            _fail(f"触发实体必须是字符串或非空字符串列表：{entity_id!r}")
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


def _covered_condition_ids(conditions: list, outputs: list, out_ids: list[str]) -> set[str]:
    """All condition ids reachable from the given outputs' chains: on/off
    members, group members (recursive), duration start/abort inputs and
    flag set/reset inputs. ``conditions`` builds the id table, ``outputs``
    provides the seeds. Shared by the two 0.10.0 materializations (the
    v6→v7 store migration in hub.py and the pre-0.5 scan-interval mapping
    below) plus the older v4 chain, so their coverage sets can never
    drift apart.

    Flag edges matter for both 0.10.0 materializations: without them a
    flag-driven output's set/reset leaves drop out of the materialized
    coverage and the output is never woken again (migration equivalence
    break; the controller's own reachability index walks these edges).
    The v4 chain predates flag nodes entirely (no v≤5 store can carry
    one), so walking set/reset there is a no-op.
    """
    by_id = {
        c.get("id"): c
        for c in conditions
        if isinstance(c, dict) and isinstance(c.get("id"), str)
    }
    stack: list[str] = []
    for o in outputs:
        if not isinstance(o, dict) or o.get("entity_id") not in out_ids:
            continue
        stack.extend(o.get("on_conditions") or [])
        stack.extend(o.get("off_conditions") or [])
    seen: set[str] = set()
    while stack:
        cid = stack.pop()
        if cid in seen:
            continue
        seen.add(cid)
        cond = by_id.get(cid)
        if not cond:
            continue
        stack.extend(cond.get("conditions") or [])
        if isinstance(cond.get("start"), str):
            stack.append(cond["start"])
        if isinstance(cond.get("abort"), str):
            stack.append(cond["abort"])
        for key in (
            CONF_SET_CONDITIONS,
            CONF_RESET_CONDITIONS,
            # snapshot capture/clear edges (0.13.0): same story as the flag
            # edges — without them a snapshot-driven chain's capture/clear
            # leaves drop out of the materialized coverage
            CONF_CAPTURE,
            CONF_CLEAR,
            # stateful gate edges (0.14.0): same story — without them a
            # stateful-driven chain's gate leaves drop out of the
            # materialized coverage
            *STATEFUL_GATE_KEYS.values(),
        ):
            stack.extend(m for m in cond.get(key) or [] if isinstance(m, str))
        # compare a/b cond references (0.13.0): the referenced snapshot/
        # literal nodes belong to the chain the same way group members do
        for key in (CONF_INPUT_A, CONF_INPUT_B):
            side = cond.get(key)
            if isinstance(side, dict) and isinstance(side.get("cond"), str):
                stack.append(side["cond"])
    return seen


def _signal_leaf_ids(conditions: list, outputs: list) -> list[str]:
    """Sorted signal-origin leaf ids reachable from ALL output chains —
    the exact materialization set of the v6→v7 routes migration: groups,
    timing gates (duration/flag) and the 0.13.0 data nodes are not signal
    origins (schema rejects them as route targets via NON_SIGNAL_TYPES; an
    empty group would flip into a pass-through anchor and invert its
    verdict), yet every driving leaf stays reachable via group-member,
    duration start/abort, flag set/reset, snapshot capture/clear and
    compare a/b edges (_covered_condition_ids). Outputs without a usable
    ``entity_id`` contribute no coverage — the same face the v7 migration
    shows.
    """
    by_id = {
        c.get("id"): c
        for c in conditions
        if isinstance(c, dict) and isinstance(c.get("id"), str)
    }
    out_ids = [
        o.get("entity_id")
        for o in outputs
        if isinstance(o, dict) and isinstance(o.get("entity_id"), str)
    ]
    return sorted(
        cid
        for cid in _covered_condition_ids(conditions, outputs, out_ids)
        if cid in by_id
        and by_id[cid].get("type")
        not in NON_SIGNAL_TYPES + GROUP_TYPES
    )


def _map_legacy_scan_interval(data: dict) -> list[dict]:
    """Old configs carried a global scan_interval; keep its cadence as a
    time trigger so upgrades never silently stop evaluating.

    0.10.0 (WHA-F-310): the synthetic trigger is born DIRECTED — its
    routes materialize the same signal-leaf set the v6→v7 migration uses
    (_signal_leaf_ids). An unrouted trigger would fail validate_trigger on
    the next whole-table save and land the controller invalid on an
    unrelated CRUD. The id is derived from the config (name + raw
    interval) instead of a fresh uuid4 so repeated loads of a
    never-re-saved store keep the same trigger id (panel/log
    correlation); the first whole-table save persists the trigger list
    verbatim anyway. The result is closed through validate_trigger so the
    mapped shape is guaranteed valid.
    """
    interval = data.get(CONF_SCAN_INTERVAL)
    try:
        interval = int(interval)
    except (TypeError, ValueError):
        interval = DEFAULT_SCAN_INTERVAL
    interval = max(EVERY_SECONDS_MIN, min(interval, EVERY_SECONDS_MAX))
    seed = f"scan_interval:{data.get('name')}:{data.get(CONF_SCAN_INTERVAL)}"
    return [
        validate_trigger(
            {
                "id": f"{TRG_ID_PREFIX}"
                f"{hashlib.sha256(seed.encode()).hexdigest()[:32]}",
                "type": TRG_TIME,
                "label": "（原扫描间隔）",
                "enabled": True,
                CONF_EVERY_SECONDS: interval,
                CONF_ROUTES: {
                    "conditions": _signal_leaf_ids(
                        data.get("conditions") or [],
                        data.get("outputs") or [],
                    )
                },
            }
        )
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
    if ctype not in LEAF_TYPES + GROUP_TYPES + (COND_FLAG,) + STATEFUL_TYPES:
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

    elif ctype == COND_FLAG:
        # Latched virtual boolean: `set_conditions` (any → on) and
        # `reset_conditions` (any → off, reset wins) reference plain
        # condition ids; the verdict is stepped once per evaluation cycle
        # and persists across restarts. No `for` (timing gates below).
        if cond.get("for"):
            _fail("旗标条件不支持 for：旗标本身是锁存，不需要持续前置")
        for key in (CONF_SET_CONDITIONS, CONF_RESET_CONDITIONS):
            members = cond.get(key) or []
            if not isinstance(members, list) or not all(
                isinstance(m, str) for m in members
            ):
                _fail(f"旗标条件的 {key} 必须是条件 id 字符串列表")
            if len(set(members)) != len(members):
                _fail(f"旗标条件的 {key} 成员不能重复")
            if cid in members:
                # R2-4: a DIRECT self reference made the latch's verdict
                # depend on how many times the step ran per cycle (one
                # pass = one-tick pulse, the R1-2 re-step = instant
                # self-clear). The supported self-reset shape goes through
                # a duration gate (R6-1) and stays legal.
                _fail(
                    "旗标条件不能直接以自身作为置位/复位条件：单次步进是一拍脉冲、"
                    "二次步进会立即自清，语义不确定；自复位请经持续门实现"
                )
            result[key] = list(dict.fromkeys(members))
        if not result[CONF_SET_CONDITIONS] and not result[CONF_RESET_CONDITIONS]:
            _fail("旗标条件必须提供 set_conditions 或 reset_conditions")
        initial = cond.get(CONF_INITIAL, False)
        if not isinstance(initial, bool):
            _fail("旗标条件的 initial 必须是布尔值")
        result[CONF_INITIAL] = initial

    elif ctype == COND_SNAPSHOT:
        # Memory node (0.13.0): capture = rising-edge of the capture gate
        # (snapshot the source entity's reading once), clear = level (reset
        # wins); the verdict is "a snapshot exists". Pure read of the source
        # entity — the node never writes it.
        result["entity_id"] = _validate_entity_id(cond.get("entity_id"), "快照源实体")
        for key in (CONF_CAPTURE, CONF_CLEAR):
            members = cond.get(key) or []
            if not isinstance(members, list) or not all(
                isinstance(m, str) for m in members
            ):
                _fail(f"快照条件的 {key} 必须是条件 id 字符串列表")
            if len(set(members)) != len(members):
                _fail(f"快照条件的 {key} 成员不能重复")
            if cid in members:
                # R5-3, same shape as the flag self-reference rule (R2-4):
                # capture=[self] reads "a snapshot exists" — permanently
                # False while empty, so it never fires; clear=[self]
                # clears one cycle after capturing and stays empty while
                # the gate holds. Both are dead configs.
                _fail(
                    "快照条件不能直接以自身作为拍下/清空条件：自拍的门=快照存在"
                    "（无快照恒假、永不拍下），自清会在拍下一拍后清空且门保持期间"
                    "不再拍摄；请经其他条件驱动"
                )
            result[key] = list(dict.fromkeys(members))
        if not result[CONF_CAPTURE] and not result[CONF_CLEAR]:
            _fail("快照条件必须提供 capture 或 clear")

    elif ctype == COND_LITERAL:
        # Constant node (0.13.0): value_type types the value (number | state)
        # and the two must match — the engine trusts the typing verbatim.
        vt = cond.get(CONF_VALUE_TYPE)
        if vt not in ("number", "state"):
            _fail("常量条件的 value_type 必须是 number 或 state")
        value = cond.get(CONF_VALUE)
        if vt == "number":
            # oversized ints raise OverflowError from isfinite (R5-4) —
            # the 400 face must catch them, not the web 500 handler
            try:
                finite = math.isfinite(value)
            except (OverflowError, TypeError):
                finite = False
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not finite
            ):
                _fail("常量条件的 value 必须是有限数字")
            result[CONF_VALUE] = float(value)
        else:
            if not isinstance(value, str) or not value.strip():
                _fail("常量条件的 value 必须是非空字符串")
            result[CONF_VALUE] = value.strip()
        result[CONF_VALUE_TYPE] = vt

    elif ctype == COND_COMPARE:
        # Two-input verdict node (0.13.0): each end is an entity reading
        # (state or attribute), a snapshot node's latched value or a literal
        # node's constant. Cross-node reference targets are checked against
        # the whole graph in _check_graph.
        for key in (CONF_INPUT_A, CONF_INPUT_B):
            result[key] = _validate_compare_input(cond.get(key), key)
        op = cond.get(CONF_OP)
        if op not in COMPARE_OPS:
            _fail(f"求值条件的 op 必须是 {'/'.join(COMPARE_OPS)}")
        result[CONF_OP] = op

    elif ctype in STATEFUL_TYPES:
        # Stateful step nodes (0.14.0): one mechanism, three parameterizations
        # — countdown (start/reset), quota (consume/reset), tally
        # (count/reset). Both gates are condition-id lists stepped once per
        # evaluation cycle; ALL gates are rising-edge (通用口径: a level held
        # high acts once) and same-cycle reset wins. No `for` (the verdict
        # is stepped/latched like a flag — hold-before-true composes via a
        # duration node); the per-kind parameter is range-checked below.
        if cond.get("for"):
            _fail("状态节点不支持 for：出口由步进/锁存决定，持续前置请用持续条件组合")
        if ctype == COND_COUNTDOWN:
            seconds = cond.get(CONF_SECONDS)
            if isinstance(seconds, float) and not seconds.is_integer():
                _fail("倒计时条件的 seconds 必须是整数秒")
            try:
                seconds = int(seconds)
            except (OverflowError, TypeError, ValueError):
                _fail("倒计时条件的 seconds 必须是秒数整数")
            if not 1 <= seconds <= DURATION_MAX:
                _fail(f"倒计时条件的 seconds 必须在 1-{DURATION_MAX} 秒之间")
            result[CONF_SECONDS] = seconds
        elif ctype == COND_QUOTA:
            times = cond.get("times")
            if isinstance(times, float) and not times.is_integer():
                _fail("次数余量条件的 times 必须是整数")
            try:
                times = int(times)
            except (OverflowError, TypeError, ValueError):
                _fail("次数余量条件的 times 必须是次数整数")
            if not 1 <= times <= QUOTA_MAX:
                _fail(f"次数余量条件的 times 必须在 1-{QUOTA_MAX} 次之间")
            result["times"] = times
        gate_key = STATEFUL_GATE_KEYS[ctype]
        gate_label = {
            COND_COUNTDOWN: "开始",
            COND_QUOTA: "消耗",
            COND_TALLY: "计数",
        }[ctype]
        for key in (gate_key, CONF_RESET_CONDITIONS):
            members = cond.get(key) or []
            if not isinstance(members, list) or not all(
                isinstance(m, str) for m in members
            ):
                _fail(f"状态节点条件的 {key} 必须是条件 id 字符串列表")
            if len(set(members)) != len(members):
                _fail(f"状态节点条件的 {key} 成员不能重复")
            if cid in members:
                # F-451 同型拒存：门引用自身读到本节点的出口判定——开始/消耗/
                # 计数门读到的恒是上一拍旧值且边沿永不上升，复位门会拍后自清；
                # 间接引用由 _check_graph 的闭包走查拒绝
                _fail(
                    f"状态节点条件不能直接以自身作为{gate_label}/复位条件："
                    "门读到本节点自己的出口判定，语义不确定；请经其他条件驱动"
                )
            result[key] = list(dict.fromkeys(members))
        if not result[gate_key] and not result[CONF_RESET_CONDITIONS]:
            _fail(f"状态节点条件必须提供 {gate_key} 或 {CONF_RESET_CONDITIONS}")

    else:  # and / or / not
        members = cond.get("conditions") or []
        # an EMPTY group is provisionally allowed here: trigger-logic mode
        # (0.7.3) uses member-less groups as signal anchors. The final
        # verdict lives in _check_graph, which knows the trigger coverage.
        if not isinstance(members, list):
            _fail(f"{ctype} 组条件的成员必须是列表")
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


def _validate_compare_input(side, which: str) -> dict:
    """Validate and normalize one compare input end (a/b, 0.13.0).

    Three shapes: ``{kind: entity, entity_id, attribute?}`` (the entity's
    current state or attribute value), ``{kind: snapshot, cond}`` and
    ``{kind: literal, cond}`` (a node reference — that the target node IS
    of the referenced type is a whole-graph fact, checked in _check_graph)."""
    if not isinstance(side, dict):
        _fail(f"求值条件的 {which} 必须是对象")
    kind = side.get("kind")
    if kind == "entity":
        eid = _validate_entity_id(side.get("entity_id"), f"求值条件 {which} 的实体")
        out: dict = {"kind": "entity", "entity_id": eid}
        attr = _optional_str(side.get("attribute"), f"求值条件 {which} 的 attribute")
        if attr:
            out["attribute"] = attr
        return out
    if kind in (COND_SNAPSHOT, COND_LITERAL):
        ref = side.get("cond")
        if not isinstance(ref, str) or not _COND_ID_RE.match(ref):
            _fail(f"求值条件的 {which} 必须提供 cond（条件 id）")
        return {"kind": kind, "cond": ref}
    _fail(f"求值条件的 {which} kind 必须是 entity/snapshot/literal")


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
    }
    if otype == OUTPUT_SWITCH:
        result["manual_override"] = _to_bool(
            out.get("manual_override", False), "输出的 manual_override"
        )
    # else (F-329): binary_sensor has no control surface to lock — the flag
    # was accepted and persisted with no effect (and resurrected itself on a
    # switch→binary→switch round-trip), so it is dropped for non-switch
    # outputs instead of being stored dead.
    for key in ("on_conditions", "off_conditions"):
        members = out.get(key) or []
        if not isinstance(members, list) or not all(isinstance(m, str) for m in members):
            _fail(f"输出的 {key} 必须是条件 id 字符串列表")
        result[key] = list(dict.fromkeys(members))
    return result


def _condition_neighbors(cond: dict, include_flag_edges: bool = True) -> list[str]:
    """Referenced condition ids of one condition (group members, duration
    start/abort, flag set/reset, compare a/b cond refs, snapshot
    capture/clear) — the edge set for graph checks.

    Group members, duration start/abort and compare a/b cond references
    are EVALUATION-path edges (the engine recurses into members/start/
    abort; a compare reads its a/b node values during evaluation, so a
    chain through them is a live dependency — the routing index walks the
    same edges). Flag set/reset and snapshot capture/clear are STEP edges
    (stepped once per cycle in their own pass, reading latched verdicts —
    the engine never re-evaluates them inside a leaf): cycle detection and
    the flag closure pass ``include_flag_edges=False`` so a step edge can
    neither close an evaluation cycle nor cascade (审查 R6-1). The
    existence check keeps the default: a dangling set/reset/capture/clear
    reference must still fail.
    """
    edges = list(cond.get("conditions") or [])
    for key in (CONF_START, CONF_ABORT):
        ref = cond.get(key)
        if isinstance(ref, str):
            edges.append(ref)
    for key in (CONF_INPUT_A, CONF_INPUT_B):
        side = cond.get(key)
        if isinstance(side, dict) and isinstance(side.get("cond"), str):
            edges.append(side["cond"])
    if include_flag_edges:
        for key in (
            CONF_SET_CONDITIONS,
            CONF_RESET_CONDITIONS,
            CONF_CAPTURE,
            CONF_CLEAR,
            # stateful gate edges (0.14.0) — step edges, same treatment
            *STATEFUL_GATE_KEYS.values(),
        ):
            val = cond.get(key)
            if isinstance(val, list):
                edges.extend(m for m in val if isinstance(m, str))
    return edges


def _flag_branch_verdict(
    cond: dict,
    by_id: dict[str, dict],
    memo: dict[str, bool | None],
) -> bool | None:
    """Abstract verdict of one branch as the flag step evaluates it
    (审查 R6-1/R6-3): False = provably dead in flag context (a cooldown
    has no output context there, an AND with a dead member stays dead, a
    NOT with a satisfied member stays false, a duration whose start is
    dead never completes and whose abort is provably satisfied aborts
    every tick — condition_engine._evaluate_duration); True = provably
    satisfied (a disabled node — the engine returns satisfied WITHOUT
    evaluating its members, condition_engine._evaluate_id); None =
    depends on live state.

    Groups merge under three-valued (Kleene) logic with constant
    dominance (审查 R7-2): one provably False member keeps an AND dead
    and one provably True member kills a NOT, even when another member
    is still unknown — the old "any unknown → unknown" short-circuit
    let exactly those permanently-dead branches save silently.

    Flags read as None: a self reference reads the previous latch
    (deterministic, so a self-resetting latch is legal — R6-1), any
    other reachable flag was already rejected by the reachability walk.
    Empty groups read as None too: they are wiring anchors whose members
    may come later (the member_referenced check accepts flag wiring,
    R6-3). Cycle-safe via a None placeholder before recursing.
    """
    cid = cond.get("id")
    if cid in memo:
        return memo[cid]
    memo[cid] = None  # a reference loop is never provably constant
    if cond.get("enabled") is False:
        verdict: bool | None = True
    else:
        ctype = cond["type"]
        if ctype == COND_COOLDOWN:
            verdict = False  # no output context during the flag step
        elif ctype == COND_FLAG:
            verdict = None  # latched read; non-self callers already failed
        elif ctype in STATEFUL_TYPES:
            verdict = None  # latched read (step_stateful); same clemency
        elif ctype == COND_LITERAL:
            # constant node — but a `for` makes the first N seconds False
            # (the generic _apply_for path), so it is only PROVABLY true
            # without one (R5-2: NOT(literal+for) must stay saveable)
            verdict = None if cond.get("for") else True
        elif ctype in GROUP_TYPES:
            members = cond.get("conditions") or []
            if not members:
                verdict = None
            else:
                verdicts = [
                    _flag_branch_verdict(by_id[member], by_id, memo)
                    for member in members
                ]
                # Kleene merge with constant dominance (审查 R7-2): the
                # engine evaluates every member every cycle, so a single
                # provably-constant member dominates the group verdict —
                # AND(False, x) is dead whatever x is, NOT(True, x) can
                # never pass.
                if ctype == COND_AND:
                    verdict = (
                        False
                        if any(v is False for v in verdicts)
                        else None if any(v is None for v in verdicts) else True
                    )
                elif ctype == COND_OR:
                    verdict = (
                        True
                        if any(v is True for v in verdicts)
                        else None if any(v is None for v in verdicts) else False
                    )
                else:  # not: passes only when NO member is true (engine :500)
                    verdict = (
                        False
                        if any(v is True for v in verdicts)
                        else None if any(v is None for v in verdicts) else True
                    )
        elif ctype == COND_DURATION:
            start = by_id.get(cond.get(CONF_START))
            abort = by_id.get(cond.get(CONF_ABORT))
            start_v = (
                _flag_branch_verdict(start, by_id, memo)
                if start is not None
                else None
            )
            abort_v = (
                _flag_branch_verdict(abort, by_id, memo)
                if abort is not None
                else None
            )
            # The gate drops the timer and returns False the moment the
            # abort is satisfied, and never completes while the start
            # never holds (condition_engine._evaluate_duration) — so a
            # provably-dead start or a provably-satisfied abort keeps the
            # gate provably False (审查 R7-2); anything else is time/live-
            # state dependent.
            verdict = False if start_v is False or abort_v is True else None
        else:  # state/time/sun/template/calendar/debounce: live inputs
            verdict = None
    memo[cid] = verdict
    return verdict


def _reachable_from_chains(
    conditions: list[dict],
    outputs: list[dict],
    out_ids: list[str],
    chain_keys: tuple[str, ...],
    include_flag_edges: bool,
    respect_enabled: bool = False,
) -> dict[str, set[str]]:
    """Per-output reachable condition ids from the named output chains.

    ``include_flag_edges=False`` walks the EVALUATION edges only (group
    members, duration start/abort): a flag's verdict is a latched read, so
    its set/reset inputs never influence an output's own verdict and a
    cooldown hiding in them belongs to the flag-step hazards (already
    covered by the (b) check above), not to the output-side ones.
    ``True`` mirrors the runtime routing index —
    controller._build_route_index walks the same edge set — for the
    trigger-target reachability warning, so the two can never drift.

    ``respect_enabled=True`` prunes every DISABLED condition's outgoing
    edges (the node itself stays reachable — the engine short-circuits it
    to True, a constant rather than a gate): step_flags skips disabled
    flags and disabled conditions short-circuit in _evaluate_id, so a
    disabled flag's set/reset chain, a disabled group's members and a
    disabled gate's start/abort chain are never evaluated — dead branches
    wake nothing. The wakeup/dependency and chain faces need this live
    view (R2#1/R3#2); only the pure topological faces keep the full edge
    set.
    """
    by_id = {
        c.get("id"): c
        for c in conditions
        if isinstance(c, dict) and isinstance(c.get("id"), str)
    }
    reach: dict[str, set[str]] = {}
    for out in outputs:
        if not isinstance(out, dict) or out.get("entity_id") not in out_ids:
            continue
        out_id = out["entity_id"]
        stack: list[str] = []
        for key in chain_keys:
            stack.extend(m for m in out.get(key) or [] if isinstance(m, str))
        seen: set[str] = set()
        while stack:
            cid = stack.pop()
            if cid in seen:
                continue
            seen.add(cid)
            cond = by_id.get(cid)
            if not cond:
                continue
            reach.setdefault(out_id, set()).add(cid)
            if respect_enabled and cond.get("enabled") is False:
                continue
            stack.extend(
                m for m in cond.get("conditions") or [] if isinstance(m, str)
            )
            for ref_key in (CONF_START, CONF_ABORT):
                ref = cond.get(ref_key)
                if isinstance(ref, str):
                    stack.append(ref)
            # compare a/b cond references walk with the evaluation edges
            # (0.13.0) — the routing index (_build_route_index) walks the
            # same set, so the two cannot drift
            for ref_key in (CONF_INPUT_A, CONF_INPUT_B):
                side = cond.get(ref_key)
                if isinstance(side, dict) and isinstance(side.get("cond"), str):
                    stack.append(side["cond"])
            if include_flag_edges:
                for flag_key in (
                    CONF_SET_CONDITIONS,
                    CONF_RESET_CONDITIONS,
                    CONF_CAPTURE,
                    CONF_CLEAR,
                    *STATEFUL_GATE_KEYS.values(),
                ):
                    stack.extend(
                        m
                        for m in cond.get(flag_key) or []
                        if isinstance(m, str)
                    )
    return reach


def _warn_static_hazards(
    conditions: list[dict],
    outputs: list[dict],
    triggers: list[dict] | None,
    by_id: dict[str, dict],
) -> None:
    """Save-time static hazard warnings — NEVER rejecting (the upgrade
    compatibility rule is warn-only, same as the flag dead-branch history):
    existing legal configs must keep saving after an upgrade. Five faces,
    each judged on the graph its claim needs (they are NOT one shared
    graph, R2#1): face ④ the live evaluation-edge set, face ① its OFF-chain
    subset (both R3#2 — disabled subtrees pruned, direct chains still
    warn), face ③ the topological routing set, face ② both — the
    topological set for the signal-coverage arm (wiring is topology) and,
    in the wakeup arm, wall-clock gates from the topological set
    (pure clock/state computations, R3#1) versus evaluation-born timers
    from the live set (dead branches start nothing). Details at each face:

    ① cooldown on an off-chain — the off-side polarity trap (the defect this
    batch was filed for): with no flip history the cooldown reads True, and
    while the output is already off an off verdict applies nothing and so
    never records a flip — the constant True then out-ranks the on-chain
    forever (off wins first). ② an output whose only gate is a calendar
    (F-320): calendar boundaries raise no HA event, wakeups are best-effort.
    ③ a trigger route wired to a condition no output can reach (F-326) —
    silently evaluates nothing while the panel still shows it wired. ④ an
    empty non-signal-anchor group reachable from an output chain (F-327) —
    constant False (constant True under NOT), only the flag branch warned.
    ⑤ an output whose live chain has enabled nodes but no wakeup source at
    all (R5-6): no wall-clock gate, no live duration/`for` timer, no
    enabled trigger's signal coverage, no entity-end join — snapshot
    capture/clear gates do NOT count (next_wakeup never schedules a
    snapshot wakeup and step_snapshots runs only inside an existing cycle,
    R6-fix#2), so the output evaluates once at startup and then only on
    manual evaluate.
    """
    signal_covered = {
        member
        for trg in triggers or []
        for member in (trg.get(CONF_ROUTES) or {}).get("conditions") or []
    }
    # wakeup_covered (R2#2) filters to ENABLED triggers only:
    # TriggerManager.async_setup skips disabled triggers — they never
    # register a listener, so their lines cannot wake anything and must
    # not count as a wakeup source. Face ④ below still uses the raw
    # signal_covered: an anchor's coverage is a wiring fact (a disabled
    # trigger's line must still empty-group-exempt its target, else a
    # disable→save would falsely warn an empty anchor group).
    wakeup_covered = {
        member
        for trg in triggers or []
        if trg.get("enabled", True) is not False
        for member in (trg.get(CONF_ROUTES) or {}).get("conditions") or []
    }
    out_ids = [
        out["entity_id"]
        for out in outputs
        if isinstance(out, dict) and out.get("entity_id")
    ]
    eval_chains = ("on_conditions", "off_conditions")
    # off_reach/chain_reach judge the LIVE view too (R3#2): a member behind
    # a DISABLED group is never evaluated (the group short-circuits to
    # True), so warning about it judges a dead branch. respect_enabled
    # keeps the disabled node itself reachable and prunes only its outgoing
    # edges — a cooldown or empty group chained DIRECTLY to an output is
    # still reached and still warns exactly as before (faces ①/④), while
    # members buried in a disabled subtree stop being judged.
    off_reach = _reachable_from_chains(
        conditions, outputs, out_ids, ("off_conditions",), False,
        respect_enabled=True,
    )
    chain_reach = _reachable_from_chains(
        conditions, outputs, out_ids, eval_chains, False,
        respect_enabled=True,
    )
    route_reach = _reachable_from_chains(
        conditions, outputs, out_ids, eval_chains, True
    )
    # live_reach (R2#1, refined R3#1): the routing edge set with disabled
    # subtrees pruned — the EVALUATION view. It is the right graph for
    # evaluation-born wakeups ONLY: a duration/`for` timer exists because
    # its gate was actually evaluated (_apply_for / _duration_timers), so
    # a gate inside a disabled subtree starts nothing. Wall-clock gates
    # (time/sun/debounce/cooldown) are the exception — next_wakeup walks
    # the flat condition table and computes their edges from pure
    # clock/state timestamps (condition_engine :442-459), so a wall-clock
    # gate inside a disabled group still wakes the chain and the wakeup
    # arm below must accept it from route_reach, not live_ids.
    # The signal arm keeps route_reach — triggering is topological
    # (the routing index ignores enabled; every fire re-evaluates the
    # chain), which is exactly what ④c pinned.
    live_reach = _reachable_from_chains(
        conditions, outputs, out_ids, eval_chains, True, respect_enabled=True
    )
    # wall-clock wakeup types (R3#1): computed by next_wakeup from pure
    # clock/state timestamps, no evaluation-time timer involved. COND_DURATION
    # and `for` gates are deliberately absent — they are evaluation-born
    # (see the wakeup arm below and live_reach above).
    wall_clock_types = {COND_TIME, COND_SUN, COND_DEBOUNCE, COND_COOLDOWN}
    # R4-1 entity-coverage join: compare nodes whose entity end an ENABLED
    # state trigger listens to — the runtime routing index pulls their
    # outputs into that trigger's dispatch targets (controller
    # ._build_route_index) and does NOT filter the compare's own enabled:
    # the join is a dispatch fact (a disabled compare still re-evaluates
    # its outputs when the listened entity changes), so the static hazard
    # faces must credit the same wakeup source without an extra filter,
    # else save-time warnings contradict the runtime and the canvas badge
    # (panel._triggerCoverage walks the same unfiltered set, R6-fix#3).
    listened_entities = {
        eid
        for trg in triggers or []
        if trg.get("type") == TRG_STATE and trg.get("enabled", True) is not False
        for eid in (
            [trg.get("entity_id")]
            if isinstance(trg.get("entity_id"), str)
            else trg.get("entity_id") or []
        )
        if isinstance(eid, str)
    }
    entity_end_covered = {
        cid
        for cid, cond in by_id.items()
        if cond.get("type") == COND_COMPARE
        and any(
            isinstance(cond.get(k), dict)
            and cond[k].get("kind") == "entity"
            and cond[k].get("entity_id") in listened_entities
            for k in (CONF_INPUT_A, CONF_INPUT_B)
        )
    }

    for out in outputs:
        if not isinstance(out, dict) or not out.get("entity_id"):
            continue
        out_label = out.get("name") or out["entity_id"]
        off_ids = chain_reach.get(out["entity_id"], set())
        # naming trap: off_ids (face ④, whole-chain reach) vs off_reach
        # (face ①, OFF-chain-only reach) — one word apart, keep them straight.
        # ① off-chain cooldown (warn-only trap defense)
        for cid in off_reach.get(out["entity_id"], set()):
            cond = by_id.get(cid)
            if not cond or cond["type"] != COND_COOLDOWN:
                continue
            _LOGGER.warning(
                "输出「%s」的 off 条件链包含冷却条件「%s」：冷却在无翻转史时恒为 "
                "True（冷启动/重启/长待机后必现），而输出已处于 off 时 off 判定不"
                "产生新翻转记录，冷却将持续恒 True 并以 off 优先永久压制 on 链——"
                "请勿把冷却挂到 off 链（防频翻请挂 on 链或改用持续条件）",
                out_label,
                cond.get("label") or cid,
            )
        # ② calendar as the only gate of an output (F-320). The wakeup arm
        # splits by wakeup kind (R3#1 — the R2#1 live-graph split is only
        # valid for evaluation-born wakeups). Timer wakeups (duration,
        # `for`) judge the LIVE edge set (live_reach — routing edges with
        # disabled subtrees pruned), because such a timer exists only if
        # its gate was actually evaluated (_apply_for /
        # _duration_timers): a disabled flag's set/reset chain, a
        # disabled group's members and a disabled gate's start chain are
        # never evaluated (step_flags skips disabled flags; disabled
        # conditions short-circuit to True) and a timer reachable only
        # through them is dead wiring (R2#1 — both faces: the false alarm
        # [flag(disabled, set=[calendar])] and the missed alarm
        # [calendar, flag(disabled, set=[duration])]). Wall-clock gates
        # (time/sun/debounce/cooldown) are the exception: next_wakeup
        # offers their edges from pure clock/state computations
        # (condition_engine :442-459) and walks the FLAT condition table —
        # a wall-clock gate inside a disabled group still wakes the chain
        # — so they are accepted from the topological set (wakeup_ids).
        # The signal arm keeps the topological set:
        # the routing index ignores enabled, so every trigger fire wakes
        # the chain (R1#1 ④c) — but only ENABLED triggers ever register a
        # listener, hence wakeup_covered (R2#2). Within the wakeup arm
        # enabled still filters: a DISABLED calendar is not a gate (no
        # warning) and a disabled timer gate never self-wakes
        # (next_wakeup skips it) (F-346, mirrors the F-336 disabled-group
        # fix on face ④; face ④ keeps the live evaluation-edge set
        # (R3#2) because a flag's verdict is a latched read — its own
        # members never influence the output's own verdict, see
        # _reachable_from_chains).
        # A non-zero `for` counts beside the timing gates (R2#4):
        # next_wakeup offers _for_timers right beside _duration_timers,
        # and validation normalizes `for` to a non-zero
        # {hours,minutes,seconds} dict or drops the key entirely
        # (_validate_for), so a truthy value is exactly "a live FOR timer
        # can exist here".
        wakeup_ids = route_reach.get(out["entity_id"], set())
        live_ids = live_reach.get(out["entity_id"], set())
        cal_ids = [
            cid
            for cid in live_ids
            if by_id.get(cid, {}).get("type") == COND_CALENDAR
            and by_id.get(cid, {}).get("enabled") is not False
        ]
        if cal_ids:
            # two-tier wakeup acceptance (R3#1): wall-clock gates qualify
            # from the topological set alone (their edges are pure
            # clock/state math — no evaluation needed, so a disabled
            # subtree containing one still wakes); duration/`for` gates
            # qualify only from the live set (a timer exists only if its
            # gate was evaluated). Enabled still filters both tiers.
            # R4-1 third tier: the entity-coverage join — a compare whose
            # entity end an ENABLED state trigger listens to is woken by
            # that trigger (the runtime routing index does the same join,
            # controller._build_route_index); the heartbeat-only warning
            # must not fire for a chain the join already covers.
            has_other_wakeup = any(
                by_id.get(cid, {}).get("enabled") is not False
                and (by_id.get(cid, {}).get("type") in wall_clock_types
                     or (cid in live_ids
                         and (by_id.get(cid, {}).get("type") == COND_DURATION
                              or by_id.get(cid, {}).get("for"))))
                or cid in wakeup_covered
                or cid in entity_end_covered
                for cid in wakeup_ids
                if by_id.get(cid, {}).get("type") != COND_CALENDAR
            )
            if not has_other_wakeup:
                _LOGGER.warning(
                    "输出「%s」的条件链依赖日历条件「%s」且链上没有其他可唤醒的门："
                    "日历事件边界不产生 HA 事件，评估只能靠周期心跳兜底（重启后或"
                    "远期事件的翻转延迟可达心跳间隔）——建议把触发器信号线接到链上"
                    "的状态类条件",
                    out_label,
                    "、".join(
                        by_id[cid].get("label") or cid for cid in cal_ids
                    ),
                )
        # ④ empty non-signal groups reachable from the chains (F-327)
        for cid in off_ids:
            cond = by_id.get(cid)
            if (
                not cond
                or cond["type"] not in GROUP_TYPES
                or cond.get("conditions")
                # a disabled group short-circuits to True in the engine
                # (condition_engine) — it is NOT constant False, so it must
                # not warn (F-336, same false-positive face as flag-side
                # F-305); enabled defaults to on (None/missing ≠ disabled)
                or cond.get("enabled") is False
                or cid in signal_covered
            ):
                continue
            _LOGGER.warning(
                "输出「%s」的条件链引用了空逻辑组「%s」：非信号锚点的空组恒为 False"
                "（NOT 组下反而恒为 True），不会贡献判定——请补成员或取消引用"
                "（作为触发器信号锚点的空组不受影响）",
                out_label,
                cond.get("label") or cid,
            )
        # ⑤ no-wakeup-source face (R5-6, closes the data-node hazard
        # ledger item): the output's chain carries nothing that can ever
        # flip on its own or be woken — no wall-clock gate, no live
        # duration/`for` timer, no enabled trigger's signal coverage, no
        # entity-end join. The output evaluates once at startup and then
        # only on manual evaluate. Same two-tier set discipline as face ②
        # (R3#1): wall-clock/calendar gates qualify from the TOPOLOGICAL
        # set (a disabled subtree still wakes the chain), duration/`for`
        # timers only from the live set. Calendars count as a (heartbeat-
        # backed) source here — their dedicated face ② already warns about
        # the heartbeat lag. Only outputs whose LIVE chain has at least one
        # ENABLED node warn — a chain wholly behind a disabled group is
        # dead wiring (R3#2's face), not a frozen output. Warn-only.
        # Snapshot capture/clear gates are NOT sources (R6-fix#2): the
        # engine's next_wakeup never schedules a snapshot wakeup (its
        # sources are timers/debounce/cooldown/time/sun/calendar only) and
        # step_snapshots runs only INSIDE an existing cycle (trigger /
        # wakeup / manual), so a snapshot-only chain freezes exactly like
        # a flag-only chain — same treatment as flag flip, which this face
        # has never counted. The gate CONDITIONS stay in wakeup_ids (the
        # routing walk includes the step edges), so a capture/clear gate
        # wired to a wall-clock or timer leaf still silences this face
        # through those branches.
        live_active = {
            cid for cid in live_ids
            if by_id.get(cid, {}).get("enabled") is not False
        }
        if live_active:
            has_wake = any(
                (by_id.get(cid, {}).get("enabled") is not False
                 and (by_id.get(cid, {}).get("type") in wall_clock_types
                      or by_id.get(cid, {}).get("type") == COND_CALENDAR))
                or (cid in live_ids
                    and by_id.get(cid, {}).get("enabled") is not False
                    and (by_id.get(cid, {}).get("type") == COND_DURATION
                         or by_id.get(cid, {}).get("for")))
                or cid in wakeup_covered
                or cid in entity_end_covered
                for cid in wakeup_ids
            )
            if not has_wake:
                _LOGGER.warning(
                    "输出「%s」的条件链上没有任何可唤醒源（壁钟门/计时门/触发器"
                    "信号覆盖/求值实体监听）：该输出只会在初始评估或手动"
                    "「立即评估」时更新——请把触发器信号线连到链上条件，或让 state "
                    "触发器监听求值读取的实体",
                    out_label,
                )

    # ③ trigger routes wired to unreachable conditions (F-326)
    for trg in triggers or []:
        routes = trg.get(CONF_ROUTES)
        if not isinstance(routes, dict):
            continue
        trg_label = trg.get("label") or trg.get("id") or "?"
        for member in routes.get("conditions") or []:
            if any(member in ids for ids in route_reach.values()):
                continue
            member_label = by_id[member].get("label") or member
            _LOGGER.warning(
                "触发器「%s」的信号线连到了「%s」，但该条件沿条件图到不了任何"
                "输出：触发器将不会唤醒任何输出（空转）——请把信号线改连到输出"
                "链可达的条件",
                trg_label,
                member_label,
            )


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

    # Compare a/b node references (0.13.0): a snapshot end must point at a
    # snapshot node and a literal end at a literal node — the engine reads
    # the target by its own kind (a snapshot end reads the snapshot latch,
    # a literal end reads the constant), so a mismatched target would be
    # permanently unreadable (compare False + WARN every cycle).
    for cond in conditions:
        if cond["type"] != COND_COMPARE:
            continue
        label = cond.get("label") or cond["id"]
        for key in (CONF_INPUT_A, CONF_INPUT_B):
            side = cond[key]
            if side["kind"] not in (COND_SNAPSHOT, COND_LITERAL):
                continue
            target = by_id[side["cond"]]
            if target["type"] != side["kind"]:
                _fail(
                    f"求值条件「{label}」的 {key} 引用了 "
                    f"{target['type']} 型节点：{side['kind']} 端只能引用"
                    f"{side['kind']} 节点"
                )

    for cond in conditions:
        if cond["type"] != COND_FLAG:
            continue
        if cond.get("enabled") is False:
            # R2-3: disabled flags are inert (step_flags skips them) —
            # keep them saveable as canvas anchors, same clemency as
            # F-336/F-346 give every other disabled node
            continue
        label = cond.get("label") or cond["id"]
        # (a) Order-dependence hunt (审查 R5-4, narrowed by R6-1/R6-3): any
        # reachable NON-self flag makes the verdict depend on flag stepping
        # order. The flag itself is only ever READ during the step (latched
        # value), so a self reference — directly or through a duration
        # chain (self-resetting latch) — is legal. Disabled nodes are
        # skipped: the engine returns satisfied for them without evaluating
        # their members (condition_engine._evaluate_id).
        for key in (CONF_SET_CONDITIONS, CONF_RESET_CONDITIONS):
            seen: set[str] = set()
            stack = list(cond[key])
            while stack:
                member = stack.pop()
                if member in seen:
                    continue
                seen.add(member)
                mcond = by_id[member]
                if mcond.get("enabled") is False:
                    continue
                if mcond["type"] == COND_FLAG:
                    if member != cond["id"]:
                        _fail(
                            f"旗标「{label}」的 {key}（直接或经组/持续门间接）引用了"
                            "另一个旗标：旗标不能级联"
                        )
                    continue  # self: reads the previous latch — safe (R6-1)
                stack.extend(
                    _condition_neighbors(mcond, include_flag_edges=False)
                )
        # (b) Dead-branch verdicts (审查 R5-4, narrowed by R6-3): a cooldown
        # hidden behind a group/duration is still permanently False in the
        # flag step (no output context), but only a branch with NO usable
        # alternative is rejected — a mixed OR group keeps working via its
        # other members, so rejecting the whole controller for it broke
        # previously valid stores on upgrade.
        for key in (CONF_SET_CONDITIONS, CONF_RESET_CONDITIONS):
            memo: dict[str, bool | None] = {}
            for member in cond[key]:
                if _flag_branch_verdict(by_id[member], by_id, memo) is False:
                    _fail(
                        f"旗标「{label}」的 {key}（直接或经组/持续门间接）恒不成立："
                        "冷却条件在旗标步进时没有输出上下文（恒 False），"
                        "AND 组混入冷却、NOT 组含恒真成员、持续门起点恒假"
                        "或中止恒真同理；请修正该分支"
                    )

    # Snapshot capture/clear dead gates (R1-4): the snapshot step evaluates
    # its gates with NO output context either (same judge as the flag (b)
    # face above — step edges only, never the evaluation-edge hazard faces).
    # A cooldown hidden behind a group/duration is permanently False there,
    # so a gate whose member is provably dead would silently never
    # capture/clear — the node reads "no snapshot" forever with only an
    # invisible debug line. An empty non-signal group stays None (wiring
    # anchor, same clemency as the flag face — R6-3), and a mixed OR GROUP
    # keeps working via its other members (the verdict judges the group as
    # a whole).
    for cond in conditions:
        if cond["type"] != COND_SNAPSHOT:
            continue
        if cond.get("enabled") is False:
            # R2-3: disabled snapshots are frozen (step_snapshots skips
            # them) — saveable as canvas anchors
            continue
        label = cond.get("label") or cond["id"]
        for key in (CONF_CAPTURE, CONF_CLEAR):
            if not cond[key]:
                continue
            memo: dict[str, bool | None] = {}
            for member in cond[key]:
                if _flag_branch_verdict(by_id[member], by_id, memo) is False:
                    _fail(
                        f"快照条件「{label}」的 {key}（直接或经组/持续门间接）恒不"
                        "成立：冷却条件在快照步进时没有输出上下文（恒 False），"
                        "AND 组混入冷却、NOT 组含恒真成员、持续门起点恒假"
                        "或中止恒真同理；请修正该门"
                    )
            # R6-fix#1 (extends R5-3 from the DIRECT self reference to the
            # whole evaluation closure): the gate's dependency closure —
            # group member expansion, duration start edges and compare a/b
            # cond edges, the edges the engine recurses through when it
            # evaluates this gate in step_snapshots (_evaluate_id) —
            # reaching this snapshot reads its own "a snapshot exists"
            # verdict, permanently False while the store is empty: a
            # capture gate can never rise from the self path (the node
            # never captures, only invisible debug lines) and a clear gate
            # self-reads True right after a capture (instant self-clear).
            # Step edges (flag set/reset, snapshot capture/clear) stay
            # excluded like in the flag cascade walk above — they read
            # latched memories, so a gate referencing ANOTHER snapshot/
            # flag is a legal memory read, not a live self-dependency.
            # The duration ABORT edge splits by direction (R8#1/F-459):
            # the CLEAR gate's walk INCLUDES it (clear=[
            # duration(start=X, abort=self)] reads the snapshot's own
            # "a snapshot exists" verdict through the abort input — clear
            # is level-triggered and wins over capture, so the gate holds
            # the snapshot empty forever), while the CAPTURE walk keeps
            # excluding it (a one-shot self-reset via abort is legal — the
            # abort fires only AFTER the capture landed, by design).
            seen: set[str] = set()
            stack: list[tuple[str, tuple[str, ...]]] = [
                (m, (m,)) for m in cond[key]
            ]
            while stack:
                node, path = stack.pop()
                if node == cond["id"]:
                    shown = "→".join(
                        (by_id[n].get("label") or n)
                        + ("（本快照）" if n == cond["id"] else "")
                        for n in path
                    )
                    if key == CONF_CAPTURE:
                        why = (
                            "拍下门读到本快照的「快照存在」判定——无快照时恒假，"
                            "该门永远无法上升，节点永不拍下"
                        )
                    else:
                        why = (
                            "清空门读到本快照的「快照存在」判定——拍下后门即为真，"
                            "下一拍自清且门保持期间不再拍摄"
                        )
                    _fail(
                        f"快照条件「{label}」的 {key}（经 {shown} 间接）引用了"
                        f"自身：{why}；请把该门改为不依赖本快照的条件"
                    )
                if node in seen:
                    continue
                seen.add(node)
                ncond = by_id[node]
                if ncond.get("enabled") is False:
                    continue  # disabled nodes short-circuit: never read
                nxt_edges = list(ncond.get("conditions") or [])
                if isinstance(ncond.get(CONF_START), str):
                    nxt_edges.append(ncond[CONF_START])
                # R8#1/F-459: the duration ABORT edge joins the CLEAR-gate
                # walk only (see the comment above the walk for the split)
                if key == CONF_CLEAR and isinstance(ncond.get(CONF_ABORT), str):
                    nxt_edges.append(ncond[CONF_ABORT])
                for side_key in (CONF_INPUT_A, CONF_INPUT_B):
                    side = ncond.get(side_key)
                    if isinstance(side, dict) and isinstance(
                        side.get("cond"), str
                    ):
                        nxt_edges.append(side["cond"])
                for nxt in nxt_edges:
                    if nxt not in seen:
                        stack.append((nxt, path + (nxt,)))

    # Stateful gate checks (0.14.0): the same two faces as the flag/snapshot
    # step-gate faces. (a) A provably-dead gate member (a cooldown has no
    # output context in ANY step pass) would make the node's gate silently
    # never fire; an empty non-signal group stays None (wiring anchor
    # clemency, R6-3) and a mixed OR group keeps working via its other
    # members. (b) The self-reference closure: the gate's evaluation-edge
    # dependency closure reaching the node itself reads the node's OWN
    # verdict — dead config, rejected (F-451 同型). The walk includes the
    # duration ABORT edge for the RESET gate only (the R8#1/F-459 split:
    # reset=[duration(start=X, abort=self)] self-reads through the abort
    # input; the primary gate keeps the one-shot self-reset via abort legal).
    for cond in conditions:
        if cond["type"] not in STATEFUL_TYPES:
            continue
        if cond.get("enabled") is False:
            # disabled stateful nodes are frozen (step_stateful skips them)
            # — saveable as canvas anchors, same clemency as disabled flags
            continue
        label = cond.get("label") or cond["id"]
        gate_key = STATEFUL_GATE_KEYS[cond["type"]]
        for key in (gate_key, CONF_RESET_CONDITIONS):
            if not cond[key]:
                continue
            memo: dict[str, bool | None] = {}
            for member in cond[key]:
                if _flag_branch_verdict(by_id[member], by_id, memo) is False:
                    _fail(
                        f"状态节点「{label}」的 {key}（直接或经组/持续门间接）恒不"
                        "成立：冷却条件在状态节点步进时没有输出上下文（恒 False），"
                        "AND 组混入冷却、NOT 组含恒真成员、持续门起点恒假"
                        "或中止恒真同理；请修正该门"
                    )
            seen: set[str] = set()
            stack: list[tuple[str, tuple[str, ...]]] = [
                (m, (m,)) for m in cond[key]
            ]
            while stack:
                node, path = stack.pop()
                if node == cond["id"]:
                    shown = "→".join(
                        (by_id[n].get("label") or n)
                        + ("（本节点）" if n == cond["id"] else "")
                        for n in path
                    )
                    if key == gate_key:
                        why = (
                            "门读到本节点的出口判定——未动作时恒为假，该门永远无法"
                            "上升，节点永不动作"
                        )
                    else:
                        why = (
                            "复位门读到本节点的出口判定——动作后门即为真，下一拍"
                            "自复位且门保持期间重复触发"
                        )
                    _fail(
                        f"状态节点「{label}」的 {key}（经 {shown} 间接）引用了"
                        f"自身：{why}；请把该门改为不依赖本节点的条件"
                    )
                if node in seen:
                    continue
                seen.add(node)
                ncond = by_id[node]
                if ncond.get("enabled") is False:
                    continue  # disabled nodes short-circuit: never read
                nxt_edges = list(ncond.get("conditions") or [])
                if isinstance(ncond.get(CONF_START), str):
                    nxt_edges.append(ncond[CONF_START])
                # the ABORT edge joins the RESET-gate walk only (the
                # R8#1/F-459 split — see the snapshot block above)
                if (
                    key == CONF_RESET_CONDITIONS
                    and isinstance(ncond.get(CONF_ABORT), str)
                ):
                    nxt_edges.append(ncond[CONF_ABORT])
                for side_key in (CONF_INPUT_A, CONF_INPUT_B):
                    side = ncond.get(side_key)
                    if isinstance(side, dict) and isinstance(
                        side.get("cond"), str
                    ):
                        nxt_edges.append(side["cond"])
                for nxt in nxt_edges:
                    if nxt not in seen:
                        stack.append((nxt, path + (nxt,)))

    # Cycle detection over group references and duration start/abort edges
    # (iterative DFS with colors).
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {cid: WHITE for cid in by_id}
    for root, root_cond in by_id.items():
        if color[root] != WHITE:
            continue
        # flag set/reset edges are excluded (R6-1): the flag step only
        # reads latched values, so flag references can never close an
        # evaluation cycle — flag→duration→flag must stay saveable
        stack = [
            (root, iter(_condition_neighbors(root_cond, include_flag_edges=False)))
        ]
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
                    stack.append(
                        (
                            member,
                            iter(
                                _condition_neighbors(
                                    by_id[member], include_flag_edges=False
                                )
                            ),
                        )
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

    # Trigger-logic groups (0.7.3): a group with NO members is legal when a
    # trigger's signal coverage names it — it is a trigger-merge anchor
    # (pass-through). An unreferenced empty group stays rejected.
    # Coverage is TOPOLOGICAL — it does not depend on trigger.enabled
    # (0.7.3 F-151 resolution, superseding the F-120 filter): a disabled
    # trigger never fires, so its coverage keeps the anchor valid without
    # ever acting; filtering by enabled made "disable → save" a dead end.
    signal_covered = {
        member
        for trg in triggers or []
        for member in (trg.get(CONF_ROUTES) or {}).get("conditions") or []
    }
    # topological references (WHA-F-167/F-170): membership in another
    # group, an output chain, a duration start/abort, or a flag's
    # set/reset input (审查 R6-3 — same graph, same judgement) — all keep
    # an empty group alive on the canvas. Snapshot capture/clear inputs are
    # the same kind of wire (0.13.0): an empty group wired into a capture
    # gate stays a legal wiring anchor.
    member_referenced = {
        m
        for cond in conditions
        if isinstance(cond, dict)
        for m in (
            (cond.get("conditions") or [])
            + ([cond.get("start")] if cond.get("start") else [])
            + ([cond.get("abort")] if cond.get("abort") else [])
            + list(cond.get(CONF_SET_CONDITIONS) or [])
            + list(cond.get(CONF_RESET_CONDITIONS) or [])
            + list(cond.get(CONF_CAPTURE) or [])
            + list(cond.get(CONF_CLEAR) or [])
            + [
                m
                for key in STATEFUL_GATE_KEYS.values()
                for m in cond.get(key) or []
            ]
        )
        if isinstance(m, str)
    }
    member_referenced |= {
        m
        for out in outputs
        if isinstance(out, dict)
        for m in (out.get("on_conditions") or []) + (out.get("off_conditions") or [])
    }
    for cond in conditions:
        if cond["type"] not in GROUP_TYPES:
            continue
        has_members = bool(cond["conditions"])
        # two distinct notions (WHA-F-168): referenced = kept alive by any
        # wire (trigger coverage OR membership in another group); signal-
        # covered = a trigger wires it directly. Only the latter conflicts
        # with having members (the pass-through engine would ignore them).
        referenced = cond["id"] in signal_covered or cond["id"] in member_referenced
        label = cond.get("label") or cond["id"]
        if not has_members and not referenced:
            _fail(
                f"逻辑组「{label}」没有任何成员：把条件连到它的成员口，"
                "或让触发器信号直达它（触发逻辑模式）"
            )
        if has_members and cond["id"] in signal_covered:
            # canvas exclusivity backstop: a group is EITHER a condition
            # gate (members) OR a trigger-merger anchor (signal-covered),
            # never both — members of a signal-covered group would be
            # silently ignored by the pass-through engine (WHA-F-115)
            _fail(
                f"逻辑组「{label}」同时有成员和触发器信号覆盖（二选一）："
                "删除信号覆盖或清空成员"
            )

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
            if by_id[member]["type"] in NON_SIGNAL_TYPES:
                # R2-7: widened from duration/flag to every portless/
                # latching node — snapshot/compare/literal have no signal
                # port on the canvas, so a hand-written route naming one
                # cannot be drawn and the next canvas save would silently
                # drop it
                _fail(
                    f"触发器「{label}」的信号线连到了持续门、旗标、数据节点"
                    "或状态节点（快照/常量/求值/倒计时/次数余量/累计计数）："
                    "它们都不是信号起点，请连到具体条件或逻辑组"
                )

    # Save-time static hazard warnings (never rejecting): the off-chain
    # cooldown trap, calendar-only outputs, routes to unreachable
    # conditions, empty output-chain groups, and outputs with no wakeup
    # source at all. Warnings only — existing legal configs must keep
    # saving after an upgrade.
    _warn_static_hazards(conditions, outputs, triggers, by_id)


def validate_controller(data) -> dict:
    """Validate and normalize one controller dict; raises on bad input."""
    if not isinstance(data, dict):
        _fail("控制器配置必须是对象")

    name = _optional_str(data.get("name"), "控制器名称")
    if not name:
        _fail("控制器名称不能为空")

    if "sensors" in data:
        # 0.12.0: the sensor-pool field is retired (stored configs had the
        # key stripped by the v8 migration, so this only fires on external
        # payloads — e.g. replaying a pre-0.12.0 config export). Accept and
        # drop loudly instead of 400-ing the whole replay.
        _LOGGER.warning(
            "控制器配置携带已退役的 sensors 字段（传感器池机制已于 0.12.0 下"
            "线）：接受并丢弃该字段；存量决策日志中的 readings 快照保留只读"
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
        "conditions": conditions,
        "outputs": outputs,
    }
