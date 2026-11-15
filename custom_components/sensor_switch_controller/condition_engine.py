"""Modular condition evaluation engine.

Since 0.5.0 conditions may reference the *evaluating output* (cooldown)
via the ``out_id`` context, consult the owning manager's flip history,
and query calendar entities. Since 0.6.0 two more timed gates exist:
``duration`` (TON: true once ``start`` held for N seconds, reset when
``start`` drops or ``abort`` turns true) and ``debounce`` (true once the
entity has been quiet for N seconds — stateless, reads last_changed).
Timers still run per condition id and expose their earliest expiry so the
controller can wake up exactly when a gate flips (trigger-driven
evaluation has no polling fallback); ``next_wakeup`` reports both the
instant and the outputs that instant can reach (directed wakeups).
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timedelta
from typing import Any

from homeassistant.const import (
    CONF_ENTITY_ID,
    CONF_STATE,
    CONF_VALUE_TEMPLATE,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.template import Template
from homeassistant.util import dt as dt_util

from .const import (
    CONF_ABORT,
    CONF_CAPTURE,
    CONF_CLEAR,
    CONF_DAY,
    CONF_HOURS,
    CONF_INITIAL,
    CONF_INPUT_A,
    CONF_INPUT_B,
    CONF_OP,
    CONF_RESET_CONDITIONS,
    CONF_SECONDS,
    CONF_SET_CONDITIONS,
    CONF_START,
    CONF_VALUE,
    CONF_VALUE_TYPE,
    CONF_WEEKDAYS,
    COMPARE_OPS,
    COND_COMPARE,
    COND_COUNTDOWN,
    COND_FLAG,
    COND_LITERAL,
    COND_QUOTA,
    COND_SNAPSHOT,
    COND_TRIP_DAY,
    COND_TRIP_DURATION,
    COND_TRIP_ON,
    STATEFUL_GATE_KEYS,
    STATEFUL_TYPES,
    TRIP_ATTR_DAY_N,
    TRIP_ATTR_SINCE,
    TRIP_TYPES,
)

_LOGGER = logging.getLogger(__name__)

GROUP_TYPES = ("and", "or", "not")

# Cap for the per-date sun event cache.
_SUN_CACHE_MAX = 16

# Heartbeat margin for calendar gates (F-320): a calendar verdict flips at
# event boundaries (start - hours, event.end) that raise no HA event. After
# each evaluation the earliest future boundary is cached and offered by
# next_wakeup; this heartbeat covers the never-evaluated gaps (fresh
# restart with an empty cache, far-future events beyond the query window).
_CALENDAR_WAKE_MARGIN = timedelta(minutes=15)

# Rate limit for per-condition evaluation-failure warnings (F-323): template
# render errors and calendar entity/query failures silently degrade the
# condition to False on a hot path — warn once per key per interval.
_EVAL_FAILURE_WARN_INTERVAL = timedelta(minutes=10)

_WEEKDAY_KEYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")

# Sentinel for a capture that must not land (source entity unreadable) —
# distinct from any legal snapshot value (float | str).
_CAPTURE_FAILED = object()


def _parse_finite_float(raw: Any) -> float | None:
    """float(raw) when it parses to a finite number, else None (NaN/inf
    excluded — same gate as the literal validation, schema). Oversized
    ints raise OverflowError from float() and count as non-numeric (R5-4)."""
    try:
        value = float(raw)
    except (TypeError, ValueError, OverflowError):
        return None
    return value if math.isfinite(value) else None


class ConditionEngine:
    """Evaluates a library of conditions with FOR-timer support.

    Design notes:
    - Group conditions (and/or/not) reference their members by condition id;
      ids are resolved back to the condition dicts before evaluation.
    - A ``visited`` set guards against circular group references.
    - OR groups are *not* short-circuited: every leaf is evaluated on every
      cycle so that FOR timers keep a fresh, correct start time.
    - FOR timers are keyed by condition id and cleared whenever a condition
      stops being satisfied; rebuilding the engine (options reload) resets
      all timers.
    - Conditions flagged ``enabled: false`` are skipped and treated as
      satisfied (they never influence AND/OR results).
    - ``cooldown`` conditions consult the owning manager's flip history for
      the output currently being evaluated (``out_id`` context).
    """

    def __init__(
        self,
        hass: HomeAssistant,
        conditions: list[dict] | None,
        manager: Any = None,
        flag_states: dict[str, bool] | None = None,
        snapshot_values: dict[str, Any] | None = None,
        snapshot_gates: dict[str, bool] | None = None,
        stateful_values: dict[str, dict] | None = None,
    ) -> None:
        """Initialize."""
        self.hass = hass
        # Weak coupling: the cooldown leaf reads the manager's flip history.
        # Duck-typed to avoid an import cycle (manager ↔ engine).
        self._manager = manager
        # Latched flag verdicts, seeded from the hub's persisted states so a
        # latch survives entry reloads and HA restarts (0.9.0).
        self._flag_states: dict[str, bool] = dict(flag_states or {})
        # Latched snapshot values (0.13.0), same persistence story: seeded
        # from the hub store, written back on capture/clear. Value type IS
        # the snapshot kind — float = numeric snapshot, str = state snapshot
        # (auto-typed at capture time, see _capture_value).
        self._snapshot_values: dict[str, Any] = dict(snapshot_values or {})
        # Previous-cycle capture-gate verdicts (edge detection), seeded from
        # the persisted gate table (R1-3): without the seed every rebuild
        # (each panel save reloads the entry) would see an empty prev table,
        # treat a still-high gate as a fresh rising edge and OVERWRITE the
        # latched value with the current reading. A missing gate table (old
        # / hand-edited payload) keeps the legacy degrade: first true cycle
        # captures once — idempotent while the source value is unchanged.
        self._snapshot_prev: dict[str, bool] = dict(snapshot_gates or {})
        # Stateful step-node values (0.14.0), same persistence story: seeded
        # from the hub's fifth runtime table, written back on change. The
        # per-node value dict carries the node's verdict plus its kind state
        # (countdown deadline datetime | quota remaining | tally count) and
        # the previous-cycle gate verdicts (edge detection, same seed story
        # as _snapshot_prev). Nodes that never moved keep NO entry — the
        # step applies virtual defaults (quota full / tally zero / countdown
        # idle) so a fresh node writes nothing until its first action.
        self._stateful_values: dict[str, dict] = dict(stateful_values or {})
        self._conditions: dict[str, dict] = {}
        for cond in conditions or []:
            if not isinstance(cond, dict):
                _LOGGER.warning("Ignoring malformed condition entry: %r", cond)
                continue
            cid = cond.get("id")
            if not cid:
                _LOGGER.warning("Condition without 'id' is skipped: %r", cond)
                continue
            if cid in self._conditions:
                _LOGGER.warning("Duplicate condition id '%s'; the last one wins", cid)
            self._conditions[cid] = cond

        self._for_timers: dict[str, datetime] = {}
        self._duration_timers: dict[str, datetime] = {}
        # groups referenced by trigger signal coverage (0.7.3 trigger-logic
        # mode): they evaluate as pass-through instead of their members
        self.signal_group_ids: set[str] = set()
        # (flag id, side, group id) pairs already warned about (审查 R7-3):
        # an empty non-signal group wired into a flag branch evaluates
        # False every cycle — visible once instead of a debug line per tick
        self._empty_branch_warned: set[tuple[str, str, str]] = set()
        self._template_cache: dict[str, Template] = {}
        self._sun_cache: dict[tuple[str, str], Any] = {}
        # Earliest future calendar boundary per condition id, cached by the
        # (async) calendar leaf evaluation and offered by the (sync)
        # next_wakeup (F-320: calendar gates raise no HA event at their
        # edges, so without the cache they would never wake on their own).
        self._calendar_next: dict[str, datetime] = {}
        # (condition key, failure kind) → last warning time (F-323).
        self._eval_failure_warned: dict[tuple[str, str], datetime] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def evaluate_any(self, cond_ids: list[str], out_id: str | None = None) -> bool:
        """OR across condition ids, evaluating all of them (no short-circuit)."""
        if not cond_ids:
            return False
        met = False
        for cid in cond_ids:
            try:
                if await self._evaluate_id(cid, set(), out_id=out_id):
                    met = True
            except Exception:
                _LOGGER.exception("Unexpected error evaluating condition '%s'", cid)
        return met

    async def evaluate_detailed(
        self, cond_ids: list[str], out_id: str | None = None
    ) -> tuple[bool, dict[str, bool]]:
        """Evaluate like evaluate_any but record per-id results for the UI.

        Shares the same code path (and therefore FOR-timer semantics) as the
        regular evaluation cycle, so a trial run behaves exactly like a tick.
        """
        results: dict[str, bool] = {}
        met = False
        for cid in cond_ids or []:
            try:
                if await self._evaluate_id(cid, set(), trace=results, out_id=out_id):
                    met = True
            except Exception:
                _LOGGER.exception("Unexpected error evaluating condition '%s'", cid)
                results[cid] = False
        return met, results

    def flag_states(self) -> dict[str, bool]:
        """Current latched flag verdicts (for hub persistence)."""
        return dict(self._flag_states)

    async def step_flags(self) -> list[str]:
        """Advance every flag's set/reset gate once; returns flipped ids.

        Called once at the start of each evaluation cycle, BEFORE outputs
        are evaluated, so every output in the cycle sees the same flag
        snapshot. Within one cycle reset wins over set (safe side, mirrors
        the off-first output verdict); otherwise set turns it on; otherwise
        the latch holds. Disabled flags are skipped (state frozen).
        """
        flipped: list[str] = []
        for cid, cond in self._conditions.items():
            if not isinstance(cond, dict) or cond.get("type") != COND_FLAG:
                continue
            if cond.get("enabled") is False:
                continue
            # Empty-group branches (审查 R7-3, widened by R9-2/R9-3): the
            # schema keeps empty groups saveable as canvas wiring anchors,
            # but a non-signal-anchor empty group evaluates False every
            # cycle (_evaluate_cond). Walk each side's evaluation edges
            # statically (group membership + duration start/abort, mirroring
            # _evaluate_id/_evaluate_cond — disabled reads True, a signal
            # anchor reads True, live inputs read unknown) and warn once per
            # flag/side/group: branch-level when the whole side is provably
            # dead, member-level when the empty group is merely useless.
            for side, key in (
                ("set", CONF_SET_CONDITIONS),
                ("reset", CONF_RESET_CONDITIONS),
            ):
                members = cond.get(key) or []
                if not members:
                    continue
                dead_groups: list[str] = []
                verdicts = [
                    self._static_verdict(m, set(), dead_groups)
                    for m in members
                ]
                side_dead = not any(v is True or v is None for v in verdicts)
                for group in dead_groups:
                    if (cid, side, group) in self._empty_branch_warned:
                        continue
                    self._empty_branch_warned.add((cid, side, group))
                    if side_dead:
                        _LOGGER.warning(
                            "Flag '%s' %s branch references empty group "
                            "'%s': it is not a signal anchor, so it always "
                            "evaluates False and this branch can never "
                            "fire (add members to the group or unwire it)",
                            cond.get("label") or cid,
                            side,
                            group,
                        )
                    else:
                        _LOGGER.warning(
                            "Flag '%s' %s branch references empty group "
                            "'%s': it is not a signal anchor, so it always "
                            "evaluates False and cannot contribute to this "
                            "gate (add members to the group or unwire it)",
                            cond.get("label") or cid,
                            side,
                            group,
                        )
            initial = bool(cond.get(CONF_INITIAL, False))
            old = self._flag_states.get(cid, initial)
            # No short-circuit: every member is evaluated every cycle so its
            # FOR/duration timers stay fresh (same rule as OR groups above).
            reset_met = False
            for member in cond.get(CONF_RESET_CONDITIONS) or []:
                if await self._evaluate_id(member, set()):
                    reset_met = True
            set_met = False
            for member in cond.get(CONF_SET_CONDITIONS) or []:
                if await self._evaluate_id(member, set()):
                    set_met = True
            if reset_met:
                new = False
            else:
                new = True if set_met else old
            self._flag_states[cid] = new
            if new != old:
                flipped.append(cid)
        return flipped

    def snapshots(self) -> dict[str, Any]:
        """Current latched snapshot values (for hub persistence)."""
        return dict(self._snapshot_values)

    def snapshot_gates(self) -> dict[str, bool]:
        """Previous-cycle capture-gate verdicts (edge-detection state, for
        hub persistence — R1-3: seeding these on rebuild keeps the rising
        -edge semantics exact across reloads/restarts)."""
        return dict(self._snapshot_prev)

    async def step_snapshots(self) -> dict[str, dict]:
        """Advance every snapshot's capture/clear gate once; returns events.

        Stepping order mirrors step_flags (the flag step runs FIRST, then
        this one, once per evaluation cycle; the controller re-steps the
        flags once more when this returns events, so flag gates reading a
        snapshot converge in the same cycle — R1-2): clear is
        level-triggered and wins over capture (safe side, same reset-wins
        rule as flags); capture fires on the capture gate's RISING edge
        only (previous cycle False ∧ now True) — the source entity's later
        changes never refresh the snapshot until the gate drops and rises
        again. The previous-gate verdicts persist with the snapshot table
        (R1-3): seeded on rebuild, the edge semantics stay exact across
        reloads/restarts; a missing gate table (legacy payload) degrades
        to one idempotent re-capture on the first true cycle.

        shortcut: a snapshot's capture/clear referencing ANOTHER snapshot
        reads that node's verdict in CONFIG order within this single loop
        (earlier-listed nodes step first); referencing a flag is always
        safe (flags stepped before snapshots). Schema-level cascade check
        deferred — register in the ledger, revisit when a real config hits
        it.

        Returns {snapshot_id: {"event": "capture"|"clear", ...value}} for
        the nodes whose memory changed this cycle (drives target widening,
        persistence and the decision-log event lines).
        """
        events: dict[str, dict] = {}
        for cid, cond in self._conditions.items():
            if not isinstance(cond, dict) or cond.get("type") != COND_SNAPSHOT:
                continue
            if cond.get("enabled") is False:
                continue  # frozen: no capture, no clear (mirrors flags)
            gate_now = False
            for member in cond.get(CONF_CAPTURE) or []:
                if await self._evaluate_id(member, set()):
                    gate_now = True
            edge = gate_now and not self._snapshot_prev.get(cid, False)
            clear_met = False
            for member in cond.get(CONF_CLEAR) or []:
                if await self._evaluate_id(member, set()):
                    clear_met = True
            had = cid in self._snapshot_values
            if clear_met:
                self._snapshot_values.pop(cid, None)
                self._snapshot_prev[cid] = gate_now
                if had:
                    events[cid] = {"event": "clear"}
            elif edge:
                value = self._capture_value(cond, cid)
                if value is not _CAPTURE_FAILED:
                    self._snapshot_values[cid] = value
                    # a SUCCESSFUL capture consumes the edge; a failed one
                    # (source unreadable) keeps prev at False so the gate
                    # retries every cycle until the source reads again —
                    # R2-2: a transient unavailable at the edge must not
                    # pin the snapshot empty for the whole uptime
                    self._snapshot_prev[cid] = gate_now
                    events[cid] = {"event": "capture", "value": value}
            else:
                # no edge, no clear: the gate verdict still advances
                self._snapshot_prev[cid] = gate_now
        return events

    def stateful_values(self) -> dict[str, dict]:
        """Current stateful node values (for hub persistence). The entries
        are the engine's own dicts — the caller must copy before handing
        them across an await (the controller's payload helper does)."""
        return self._stateful_values

    async def step_stateful(self) -> dict[str, dict]:
        """Advance every stateful node's gate pair once; returns changed ids.

        Stepping order mirrors the flag/snapshot family (flags → snapshots →
        this one, once per evaluation cycle, before outputs are evaluated)
        so every output in the cycle sees the same stateful snapshot. BOTH
        gates are RISING-EDGE triggered (通用口径: a level held high acts
        once — 防连环扣/连环加); within one cycle reset wins over the primary
        gate (safe side, mirrors the flag reset-wins rule) and the swallowed
        gate edge is consumed. Disabled nodes are skipped (state frozen).
        The previous-cycle gate verdicts ride the persisted value dicts, so
        the edge semantics stay exact across reloads/restarts (the
        snapshot_gates lesson, R1-3/F-434): a stale prev would re-fire a
        still-high gate after a rebuild.

        One mechanism, three parameterizations (per STATEFUL_GATE_KEYS):
        - countdown: start rise → (re)start, deadline = now + seconds
          (回满重走), verdict False; reset rise → stop, deadline None; when
          a running deadline passes → verdict True and LATCHES (归零锁存;
          the latch survives via the persisted deadline, which self-heals a
          lost verdict after a restart by re-crossing zero).
        - quota: consume rise → remaining > 0 ? (remaining - 1, verdict
          True) : verdict False (拦截); reset rise → remaining = times. The
          verdict is the LAST consume attempt's result — a consume that took
          the last unit reports True (the attempt was allowed), the next
          attempt at zero reports False.
        - tally: verdict passes the count gate's LEVEL through (透传); a
          rising edge adds +1 (副作用); reset rise → count = 0. No threshold,
          no latch — the count is observability state.

        Returns {node_id: {"flipped": bool}} for the nodes whose ACTION
        state changed this cycle (verdict / deadline / remaining / count —
        it drives the immediate persistence and target widening; ``flipped``
        marks a verdict change, the only change that can alter an output's
        verdict this cycle). Prev-gate-only movements write through to the
        value table but emit NO event — the controller syncs them via the
        if-changed compare (debounced, the same split the snapshot family
        uses between capture/clear events and the gate table, F-434).

        shortcut: a gate referencing ANOTHER stateful node reads that
        node's verdict in CONFIG order within this single loop (earlier-
        listed nodes step first) — the same documented shortcut as the
        snapshot step; referencing a flag/snapshot is always fresh (they
        stepped before this pass).
        """
        now = dt_util.utcnow()

        async def gate_any(members: list | None) -> bool:
            # no short-circuit: every member evaluates every cycle so its
            # FOR/duration timers stay fresh (same rule as the flag step)
            met = False
            for member in members or []:
                if await self._evaluate_id(member, set()):
                    met = True
            return met

        events: dict[str, dict] = {}
        for cid, cond in self._conditions.items():
            if not isinstance(cond, dict):
                continue
            kind = cond.get("type")
            gate_key = STATEFUL_GATE_KEYS.get(kind)
            if gate_key is None:
                continue
            if cond.get("enabled") is False:
                continue  # frozen: no gate move, no action (mirrors flags)
            entry = self._stateful_values.get(cid)
            gate_now = await gate_any(cond.get(gate_key))
            reset_now = await gate_any(cond.get(CONF_RESET_CONDITIONS))
            gate_rise = gate_now and not (
                entry.get("prev_gate", False) if entry else False
            )
            reset_rise = reset_now and not (
                entry.get("prev_reset", False) if entry else False
            )
            # copy-on-write: the new dict differs from the entry only when
            # something actually changed, which IS the change detection
            new_entry = dict(entry) if entry else {}
            new_entry["prev_gate"] = gate_now
            new_entry["prev_reset"] = reset_now

            if kind == COND_COUNTDOWN:
                seconds = float(cond.get(CONF_SECONDS, 0) or 0)
                if reset_rise:
                    # 停止并回满（未启动态）: an already-idle reset is a no-op
                    # (fields unchanged → no event)
                    new_entry["verdict"] = False
                    new_entry["deadline"] = None
                elif gate_rise:
                    # 启动/重启动（回满重走）; 再次 start 瞬间翻 false
                    new_entry["verdict"] = False
                    new_entry["deadline"] = now + timedelta(seconds=seconds)
            elif kind == COND_QUOTA:
                times = int(cond.get("times", 1))
                # 调参夹取 (R2#5): a persisted remaining above a LOWERED
                # times must not keep spending the old budget — clamp every
                # read and write the clamped value through when it moved so
                # the store never carries an over-budget number.
                remaining = min(
                    int(entry.get("remaining", times)) if entry else times,
                    times,
                )
                if entry is not None and entry.get("remaining") != remaining:
                    new_entry["remaining"] = remaining
                if reset_rise:
                    new_entry["remaining"] = times  # 恢复满 X (verdict holds)
                elif gate_rise:
                    if remaining > 0:
                        new_entry["remaining"] = remaining - 1
                        new_entry["verdict"] = True
                    else:
                        new_entry["verdict"] = False  # 剩余=0 → 拦截
            else:  # COND_TALLY
                count = entry.get("count", 0) if entry else 0
                # 透传：出口随门电平 — the verdict key is written only on a
                # CHANGE (a missing key reads as False, the seed default) so
                # a never-acted tally stays entry-free and the first-movement
                # guard below keeps its meaning (R2#2); the count/reset
                # actions are unchanged.
                if gate_now != (bool(entry.get("verdict")) if entry else False):
                    new_entry["verdict"] = gate_now
                if reset_rise:
                    new_entry["count"] = 0  # 归零（同拍优先于计数）
                elif gate_rise:
                    new_entry["count"] = count + 1

            if kind == COND_COUNTDOWN:
                # 归零即锁存 true — checked for every countdown every cycle
                # (a running deadline crossing zero needs no gate edge; the
                # directed wakeup at the deadline guarantees this step runs).
                # as_utc is the LAST line of defense only (R2#1, 教训 R7):
                # the manager's load ladder normalizes naive deadlines at
                # its single tz gate — an aware/naive mix here would
                # TypeError the whole evaluation cycle.
                deadline = new_entry.get("deadline")
                if (
                    deadline is not None
                    and not new_entry.get("verdict")
                    and now >= dt_util.as_utc(deadline)
                ):
                    new_entry["verdict"] = True

            if entry is None:
                # first movement: keep the node entry-free until an ACTION
                # happened (a bare prev table for a never-acted node is churn)
                if set(new_entry) == {"prev_gate", "prev_reset"}:
                    continue
            elif new_entry == entry:
                continue  # nothing moved at all (e.g. a reset while idle)
            self._stateful_values[cid] = new_entry
            action_changed = entry is None or any(
                key not in ("prev_gate", "prev_reset")
                and new_entry[key] != entry.get(key)
                for key in new_entry
            )
            if action_changed:
                old_verdict = bool(entry.get("verdict")) if entry else False
                new_verdict = bool(new_entry.get("verdict"))
                events[cid] = {"flipped": new_verdict != old_verdict}
        return events

    def _capture_value(self, cond: dict, cid: str) -> Any:
        """Snapshot the source entity's current reading, auto-typed
        (attribute hint FIRST, R1-7).

        A source advertising ``unit_of_measurement`` or
        ``state_class == "measurement"`` declares itself numeric: its
        reading is parsed as float, and a hinted reading that fails to
        parse (or is non-finite) WARNs — the sensor is lying about its own
        typing — and degrades to a state snapshot instead of a fabricated
        number. An unhinted source gets the ``float()`` parse fallback
        (digit-shaped state strings still become numeric snapshots, per
        the 0.13.0 spec), where unparseable simply means text. NaN/inf
        never land as numeric values (same isfinite gate as the literal
        validation, schema). An unreadable source (missing entity,
        unknown/unavailable) captures NOTHING — a snapshot that exists but
        carries "unavailable" would make the node's verdict (snapshot
        exists) lie.
        """
        state = self.hass.states.get(cond.get(CONF_ENTITY_ID))
        raw = getattr(state, "state", None)
        if raw is None or raw in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            self._warn_eval_failure(
                cid, "snapshot capture (source unreadable)",
                cond.get(CONF_ENTITY_ID),
            )
            return _CAPTURE_FAILED
        attrs = getattr(state, "attributes", None) or {}
        hinted = (
            isinstance(attrs.get("unit_of_measurement"), str)
            or attrs.get("state_class") == "measurement"
        )
        value = _parse_finite_float(raw)
        if hinted:
            if value is None:
                self._warn_eval_failure(
                    cid,
                    "snapshot capture (numeric sensor with non-numeric "
                    "reading)",
                    raw,
                )
                return raw
            return value
        return raw if value is None else value

    def _static_verdict(
        self,
        cid: str | None,
        visited: set[str],
        dead_groups: list[str],
        *,
        inverted: bool = False,
        in_abort: bool = False,
    ) -> bool | None:
        """Abstract verdict of one condition id, mirroring _evaluate_id's
        decision points without touching live state: unknown id → False,
        circular reference → False, disabled → True, groups merged
        Kleene-style (审查 R9-3: a constant member dominates through NOT
        too — NOT(empty) is constant True — so verdicts must propagate,
        not be judged member-by-member), everything that reads live state
        or timers (leaves, flags, duration timers, debounce) → None.

        Reachable non-signal-anchor empty groups are collected into
        ``dead_groups`` for the step_flags warning — unless a NOT on the
        path inverts their constant False into a constant True (they make
        the branch MORE likely to fire) or they sit in a duration's abort
        slot (an empty abort never fires — harmless); neither deadens
        anything, so neither is collected.
        """
        cond = self._conditions.get(cid)
        if cond is None:
            return False
        if cid in visited:
            return False  # the engine resolves a circular reference False
        if cond.get("enabled") is False:
            return True
        visited.add(cid)
        try:
            return self._static_cond(
                cond, visited, dead_groups,
                inverted=inverted, in_abort=in_abort,
            )
        finally:
            visited.discard(cid)

    def _static_cond(
        self,
        cond: Any,
        visited: set[str],
        dead_groups: list[str],
        *,
        inverted: bool,
        in_abort: bool,
    ) -> bool | None:
        """Abstract verdict of one condition dict (mirror of _evaluate_cond)."""
        if not isinstance(cond, dict):
            return False
        ctype = cond.get("type")
        if ctype is None:
            if "conditions" in cond:
                ctype = "and"  # legacy group without explicit type
            else:
                return False
        if ctype in GROUP_TYPES:
            cond_id = cond.get("id")
            if cond_id and cond_id in self.signal_group_ids:
                return True  # pass-through anchor: members never evaluated
            members = cond.get("conditions") or []
            if not members:
                # Non-signal-anchor empty group: the engine evaluates it
                # False every cycle (_evaluate_cond).
                if cond_id and not inverted and not in_abort:
                    dead_groups.append(cond_id)
                return False
            verdicts: list[bool | None] = []
            # NOT flips polarity (WHA-F-316): an empty group under a NOT is
            # constant TRUE (the Kleene merge below already reflects it in
            # the verdict), so it deadens nothing and must not be collected
            # as a dead branch — pass the flipped flag down so the empty-
            # group collector can tell the two cases apart, matching the
            # _static_verdict docstring.
            member_inverted = not inverted if ctype == "not" else inverted
            for member in members:
                if isinstance(member, str):
                    verdicts.append(
                        self._static_verdict(
                            member, visited, dead_groups,
                            inverted=member_inverted, in_abort=in_abort,
                        )
                    )
                else:
                    verdicts.append(
                        self._static_cond(
                            member, visited, dead_groups,
                            inverted=member_inverted, in_abort=in_abort,
                        )
                    )
            if ctype == "and":
                return (
                    False if any(v is False for v in verdicts)
                    else None if any(v is None for v in verdicts) else True
                )
            if ctype == "or":
                return (
                    True if any(v is True for v in verdicts)
                    else None if any(v is None for v in verdicts) else False
                )
            # not: passes only when NO member is true (engine :532)
            return (
                False if any(v is True for v in verdicts)
                else None if any(v is None for v in verdicts) else True
            )
        if ctype == COND_FLAG:
            return None  # latched read — not statically decidable
        if ctype in STATEFUL_TYPES:
            return None  # latched read (step_stateful) — not statically decidable
        if ctype == COND_LITERAL:
            # constant node — but a `for` makes the first N seconds False
            # (the generic _apply_for path), so it is only PROVABLY true
            # without one (R5-2, mirrors the schema judge)
            return None if cond.get("for") else True
        if ctype == "duration":
            start_v = self._static_verdict(
                cond.get(CONF_START), visited, dead_groups,
                inverted=inverted, in_abort=False,
            )
            abort_v = (
                self._static_verdict(
                    cond.get(CONF_ABORT), visited, dead_groups,
                    inverted=inverted, in_abort=True,
                )
                if cond.get(CONF_ABORT) else False
            )
            # Mirror _evaluate_duration: a provably-dead start or a
            # provably-satisfied abort keeps the gate False; anything else
            # depends on timers/live state.
            return False if start_v is False or abort_v is True else None
        if ctype == "cooldown":
            return False  # no output context during the flag step
        return None  # state/time/sun/template/calendar/debounce: live inputs

    def next_wakeup(
        self, reverse: dict[str, set[str]]
    ) -> tuple[datetime, set[str]] | None:
        """Earliest instant (UTC) at which some output's verdict may flip on
        its own, plus the outputs that instant can reach.

        Sources: running FOR/duration timers, debounce quiet periods,
        active cooldowns, time-range entry/exit points, sun event moments.
        ``reverse`` maps condition id → the set of output ids whose chains
        contain it (the controller's precomputed routing index). Returns
        ``(expiry_utc, out_ids)`` or None when nothing is pending; the
        controller schedules a directed point-in-time wakeup here.
        """
        now_utc = dt_util.utcnow()
        now_local = dt_util.now()
        best: tuple[datetime, set[str]] | None = None

        def offer(expiry: Any, outs: set[str] | None) -> None:
            nonlocal best
            if expiry is None or not outs:
                return
            try:
                expiry = dt_util.as_utc(expiry)
            except (TypeError, ValueError, AttributeError):
                return
            if expiry <= now_utc:
                return
            if best is None or expiry < best[0]:
                best = (expiry, set(outs))
            elif expiry == best[0]:
                # Same-instant wakeups must union their reachable outputs,
                # else the loser's outputs are silently dropped and stay
                # stale until an unrelated trigger fires (WHA-F-022).
                best[1].update(outs)

        # Running FOR timers (leaf `for` fields) and duration gates.
        for timers, seconds_of in (
            (self._for_timers, lambda c: self._parse_for(c.get("for"))),
            (
                self._duration_timers,
                lambda c: timedelta(
                    seconds=float(c.get(CONF_SECONDS, 0) or 0)
                ),
            ),
        ):
            for cid, start in timers.items():
                cond = self._conditions.get(cid)
                if not cond or cond.get("enabled") is False:
                    continue
                duration = seconds_of(cond)
                if not duration or duration.total_seconds() <= 0:
                    continue
                offer(start + duration, reverse.get(cid))

        for cond in self._conditions.values():
            if not isinstance(cond, dict) or cond.get("enabled") is False:
                continue
            ctype = cond.get("type")
            cid = cond.get("id")
            outs = reverse.get(cid) if cid else None
            if ctype == "cooldown":
                seconds = float(cond.get(CONF_SECONDS, 0))
                for oid in outs or ():
                    last = self._manager.last_flip_at(oid) if self._manager else None
                    if last is None:
                        continue
                    offer(last + timedelta(seconds=seconds), {oid})
            elif ctype == "debounce":
                state = self.hass.states.get(cond.get(CONF_ENTITY_ID))
                last_changed = getattr(state, "last_changed", None) if state else None
                if last_changed is None:
                    continue
                seconds = float(cond.get(CONF_SECONDS, 0) or 0)
                offer(dt_util.as_utc(last_changed) + timedelta(seconds=seconds), outs)
            elif ctype == "time":
                self._offer_range_edges(cond, now_local, offer, outs)
            elif ctype == "sun":
                self._offer_sun_edges(cond, now_local, offer, outs)
            elif ctype == COND_COUNTDOWN:
                # 0.14.0: a running countdown flips at its deadline with no
                # HA event — offer the persisted wall-clock deadline (the
                # duration-timer offer, same offer() source). Idle (no
                # deadline) and already-latched nodes offer nothing.
                entry = self._stateful_values.get(cid)
                deadline = entry.get("deadline") if entry else None
                if deadline is not None and not entry.get("verdict"):
                    offer(deadline, outs)
            elif ctype in TRIP_TYPES:
                # 0.16.0 wall-clock edges of the trip leaves (their verdicts
                # flip without HA events): trip_duration crosses at
                # since+hours; trip_day flips when day_n rolls — per the
                # current trip_count semantics that is local midnight.
                # shortcut: a trip_count crossover time other than midnight
                # (v0.3.0 跨点判定 configurable) makes this anchor fire
                # early — a state trigger listening to the trip entity (its
                # attribute change IS a state event) covers the real flip;
                # upgrade when trip_count exposes the crossover moment.
                if not outs:
                    continue
                state = self.hass.states.get(cond.get(CONF_ENTITY_ID))
                if not state or state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
                    continue
                attrs = getattr(state, "attributes", None) or {}
                if ctype == COND_TRIP_DURATION:
                    since_raw = attrs.get(TRIP_ATTR_SINCE)
                    start = None
                    if isinstance(since_raw, str):
                        try:
                            start = dt_util.parse_datetime(since_raw)
                        except (TypeError, ValueError):
                            start = None
                    if start is not None:
                        hours = float(cond.get(CONF_HOURS, 0) or 0)
                        offer(
                            dt_util.as_utc(start)
                            + timedelta(hours=hours),
                            outs,
                        )
                else:  # trip_on: no clock edge; trip_day: the day seam
                    if ctype == COND_TRIP_DAY:
                        next_day = dt_util.start_of_local_day(
                            now_local + timedelta(days=1)
                        )
                        offer(next_day, outs)
            elif ctype == "calendar":
                # F-320: calendar verdicts flip at event boundaries
                # (start - hours / event.end) that raise no HA event. Two
                # tiers: the cached boundary from the last evaluation, plus
                # a periodic heartbeat covering a fresh restart (cache
                # empty) and events beyond the last query window.
                cached = self._calendar_next.get(cid)
                if cached is not None:
                    offer(cached, outs)
                if outs:
                    offer(now_utc + _CALENDAR_WAKE_MARGIN, outs)
        return best

    def _time_window_verdict(self, cond: dict, now_local) -> bool:
        """Time-range verdict at ``now_local`` — the single source shared by
        evaluation and wakeup-edge discovery so the two never drift."""
        weekdays = cond.get(CONF_WEEKDAYS)
        if weekdays and _WEEKDAY_KEYS[now_local.weekday()] not in weekdays:
            return False
        after = dt_util.parse_time(cond["after"]) if cond.get("after") else None
        before = dt_util.parse_time(cond["before"]) if cond.get("before") else None
        if after is not None and before is not None and after > before:
            # Cross-midnight window (e.g. after 22:00, before 06:00).
            return now_local.time() >= after or now_local.time() <= before
        if after is not None and now_local.time() < after:
            return False
        return before is None or now_local.time() <= before

    def _offer_range_edges(self, cond: dict, now_local, offer, outs) -> None:
        """Offer the next entry/exit moments of a time-range condition.

        Two edge kinds: (a) the configured `after`/`before` wall-clock
        moments (up to 8 days out — with a weekday filter the next edge can
        be 6 days away, WHA-F-013); (b) midnight membership boundaries —
        with a weekday filter the verdict flips at day seams, not only at
        the configured moments. For (b) we probe the next 8 local midnights
        with the evaluator's own verdict and offer the first seam where it
        changes; that one rule covers cross-midnight exits/entries
        (WHA-F-023/F-028) and single-sided windows (after-only exit,
        before-only entry, WHA-F-030) without duplicating the semantics.
        """
        if not outs:
            return
        weekdays = cond.get(CONF_WEEKDAYS)
        for key in ("after", "before"):
            text = cond.get(key)
            if not text:
                continue
            parts = str(text).split(":")
            try:
                hh, mm = int(parts[0]), int(parts[1])
                ss = int(parts[2]) if len(parts) > 2 else 0
            except (IndexError, ValueError):
                continue
            for add_days in range(8):
                day = now_local + timedelta(days=add_days)
                if weekdays and _WEEKDAY_KEYS[day.weekday()] not in weekdays:
                    continue
                target = dt_util.start_of_local_day(day) + timedelta(
                    hours=hh, minutes=mm, seconds=ss
                )
                if target > now_local:
                    offer(target, outs)
                    break
        self._offer_midnight_seams(
            lambda now: self._time_window_verdict(cond, now), now_local, offer, outs
        )

    def _offer_midnight_seams(self, verdict, now_local, offer, outs) -> None:
        """Offer the next local midnight whose verdict differs from the
        instant right before it — day-boundary flips (weekday filters,
        per-date sun events) happen at the seam, not at any configured
        moment (WHA-F-023/F-028/F-030/F-034). Eight midnights cover any
        weekday pattern and beyond."""
        for add_days in range(1, 9):
            day = now_local + timedelta(days=add_days)
            midnight = dt_util.start_of_local_day(day)
            if verdict(midnight - timedelta(seconds=1)) != verdict(midnight):
                offer(midnight, outs)
                break

    def _offer_sun_edges(self, cond: dict, now_local, offer, outs) -> None:
        """Offer the next sun event moments (+offset) of a sun condition,
        plus local-midnight seams: single-sided sun verdicts flip at the
        per-date boundary, not at a sun event (WHA-F-034)."""
        if not outs:
            return
        for key in ("after", "before"):
            event = cond.get(key)
            if event not in ("sunrise", "sunset"):
                continue
            offset = self._parse_offset(cond.get(f"{key}_offset", 0))
            for add_days in range(2):
                day = (now_local + timedelta(days=add_days)).date()
                ev = self._sun_event(event, day)
                if ev is None:
                    continue
                target = ev + offset
                if target > now_local:
                    offer(target, outs)
                    break
        self._offer_midnight_seams(
            lambda now: self._sun_verdict(cond, now), now_local, offer, outs
        )

    def _sun_event_moment(self, event, offset_raw, today):
        """Today's moment for a sun edge (event + offset), or None."""
        if event not in ("sunrise", "sunset"):
            return None
        ev = self._sun_event(event, today)
        if ev is None:
            return None
        return ev + self._parse_offset(offset_raw)

    def _sun_verdict(self, cond: dict, now) -> bool:
        """Sun-condition verdict at ``now`` — single source shared by
        evaluation and wakeup-edge discovery (mirrors _time_window_verdict).

        When both edges resolve and `after` lands after `before` on the same
        day, the window spans midnight (e.g. sunset→sunrise night): true
        from today's `after` through tomorrow's `before` — HA sun semantics
        (WHA-F-037). Otherwise edges are plain bounds; single-sided forms
        flip at the per-date boundary (`after` alone true from its event
        until local midnight, `before` alone from midnight until its event).
        """
        today = now.date()
        a_ev = self._sun_event_moment(
            cond.get("after"), cond.get("after_offset", 0), today
        )
        b_ev = self._sun_event_moment(
            cond.get("before"), cond.get("before_offset", 0), today
        )
        if a_ev is not None and b_ev is not None and a_ev > b_ev:
            return now >= a_ev or now <= b_ev
        ok = True
        if a_ev is not None and now < a_ev:
            ok = False
        if b_ev is not None and now > b_ev:
            ok = False
        return ok

    # ------------------------------------------------------------------
    # Resolution / recursion
    # ------------------------------------------------------------------

    async def _evaluate_id(
        self,
        cid: str,
        visited: set[str],
        trace: dict[str, bool] | None = None,
        out_id: str | None = None,
    ) -> bool:
        """Evaluate by condition id with cycle protection."""
        cond = self._conditions.get(cid)
        if cond is None:
            _LOGGER.debug("Unknown condition id '%s'; evaluating as False", cid)
            return False
        if cid in visited:
            _LOGGER.warning(
                "Circular condition reference detected at '%s'; evaluating as False",
                cid,
            )
            return False
        if cond.get("enabled") is False:
            # Disabled conditions are skipped and treated as satisfied so they
            # never influence AND/OR results (mirrors HA semantics).
            if trace is not None:
                trace[cid] = True
            return True
        visited.add(cid)
        try:
            result = await self._evaluate_cond(
                cond, f"id:{cid}", visited, trace, out_id
            )
            if trace is not None:
                trace[cid] = result
            return result
        finally:
            visited.discard(cid)

    async def _evaluate_cond(
        self,
        cond: Any,
        path: str,
        visited: set[str],
        trace: dict[str, bool] | None = None,
        out_id: str | None = None,
    ) -> bool:
        """Recursive evaluation."""
        if isinstance(cond, str):
            return await self._evaluate_id(cond, visited, trace, out_id)
        if not isinstance(cond, dict):
            _LOGGER.warning("Malformed condition at %s: %r", path, cond)
            return False

        ctype = cond.get("type")
        if ctype is None:
            if "conditions" in cond:
                ctype = "and"  # legacy group without explicit type
            else:
                _LOGGER.debug(
                    "Leaf condition at %s has no 'type'; evaluating as False", path
                )
                return False

        if ctype in GROUP_TYPES:
            members = cond.get("conditions") or []
            cond_id = cond.get("id")
            if cond_id and cond_id in self.signal_group_ids:
                # trigger-logic mode (0.7.3): pass-through — the group's job
                # is to merge trigger signals, not to gate the verdict
                if trace is not None:
                    trace[cond_id] = True
                return True
            if not members:
                # Deliberately stricter than HA (empty and/not → True there):
                # empty groups are legal when referenced (signal coverage,
                # another group's membership, an output chain or duration
                # input), but a signal-anchored group is PASS-THROUGH (handled
                # above); reaching here with no members means a NON-signal-
                # anchored empty group (any non-signal reference or no
                # reference) — verdict False.
                _LOGGER.debug("Empty '%s' group at %s evaluates to False", ctype, path)
                return False
            results: list[bool] = []
            for i, member in enumerate(members):
                try:
                    if isinstance(member, str):
                        results.append(
                            await self._evaluate_id(
                                member, visited, trace, out_id
                            )
                        )
                    else:
                        results.append(
                            await self._evaluate_cond(
                                member, f"{path}.{i}", visited, trace, out_id
                            )
                        )
                except Exception:
                    _LOGGER.exception(
                        "Unexpected error evaluating member %d of %s", i, path
                    )
                    results.append(False)
            if ctype == "and":
                return all(results)
            if ctype == "or":
                return any(results)
            # not (HA semantics): passes only when NO member is true.
            return not any(results)  # not

        if ctype == COND_FLAG:
            # latched verdict from the per-cycle step (step_flags); no live
            # evaluation — the flag's set/reset members are NOT re-evaluated
            # here (that happens once per cycle, before outputs)
            return self._flag_states.get(
                cond.get("id"), bool(cond.get(CONF_INITIAL, False))
            )
        if ctype in STATEFUL_TYPES:
            # latched verdict from the per-cycle step (step_stateful, 0.14.0);
            # same shape as the flag read — the gates are NOT re-evaluated
            # here (stepped once per cycle, after flags/snapshots)
            entry = self._stateful_values.get(cond.get("id"))
            return bool(entry.get("verdict")) if entry else False
        if ctype == "duration":
            return await self._evaluate_duration(cond, path, visited, trace, out_id)
        if ctype == "debounce":
            return await self._evaluate_debounce(cond, path)

        raw = await self._evaluate_leaf(cond, ctype, path, out_id)
        return self._apply_for(cond, path, raw)

    async def _evaluate_duration(
        self,
        cond: dict,
        path: str,
        visited: set[str],
        trace: dict[str, bool] | None = None,
        out_id: str | None = None,
    ) -> bool:
        """TON gate: start must hold for `seconds`; abort or a dropped
        start resets the ledger. Timers are keyed by node id."""
        key = cond.get("id") or path
        start_met = await self._evaluate_id(
            cond.get(CONF_START), visited, trace, out_id
        )
        abort_met = False
        if cond.get(CONF_ABORT):
            abort_met = await self._evaluate_id(
                cond[CONF_ABORT], visited, trace, out_id
            )
        if not start_met or abort_met:
            self._duration_timers.pop(key, None)
            return False
        seconds = float(cond.get(CONF_SECONDS, 0) or 0)
        now = dt_util.utcnow()
        started = self._duration_timers.get(key)
        if started is None:
            self._duration_timers[key] = now
            return False
        return (now - started).total_seconds() >= seconds

    async def _evaluate_debounce(self, cond: dict, path: str) -> bool:
        """Stateless: true once the entity has been quiet (no state change
        at all) for `seconds`. Reads last_changed only."""
        eid = cond.get(CONF_ENTITY_ID)
        state = self.hass.states.get(eid)
        if not state:
            return False
        last_changed = getattr(state, "last_changed", None)
        if last_changed is None:
            return False
        seconds = float(cond.get(CONF_SECONDS, 0) or 0)
        elapsed = (dt_util.utcnow() - dt_util.as_utc(last_changed)).total_seconds()
        return elapsed >= seconds

    # ------------------------------------------------------------------
    # Leaf conditions
    # ------------------------------------------------------------------

    def _warn_eval_failure(self, key: str, kind: str, err: Any) -> None:
        """Warn once per (key, kind) per interval about an evaluation
        failure that silently degrades the condition to False (F-323):
        template render errors and calendar entity/query failures are user
        or backend faults — at the default log level the old debug-only
        lines left the condition looking permanently False with no trace.
        Rate-limited because evaluation is a hot path; the engine is
        rebuilt on every entry reload, which naturally resets the window."""
        now = dt_util.utcnow()
        k = (key, kind)
        last = self._eval_failure_warned.get(k)
        if last is not None and (now - last) < _EVAL_FAILURE_WARN_INTERVAL:
            return
        self._eval_failure_warned[k] = now
        _LOGGER.warning(
            "Condition '%s' %s failed and evaluates as False for now: %s",
            key,
            kind,
            err,
        )

    def _evaluate_compare(self, cond: dict, path: str) -> bool:
        """Two-input verdict: both ends numeric → numeric comparison, both
        ends state strings → string equality; anything else (mixed kinds,
        or an above/below-family op on non-numeric ends) evaluates False
        with a rate-limited WARN — never a silent string-coercion fallback
        (broken config semantics must stay visible)."""
        cid = cond.get("id") or path
        op = cond.get(CONF_OP)
        if op not in COMPARE_OPS:
            self._warn_eval_failure(cid, "compare op", op)
            return False
        side_a = self._compare_input(cond.get(CONF_INPUT_A), cid, "a")
        side_b = self._compare_input(cond.get(CONF_INPUT_B), cid, "b")
        if side_a is None or side_b is None:
            return False  # input end unreadable (warned per cause)
        (a_val, a_num), (b_val, b_num) = side_a, side_b
        if a_num and b_num:
            if op == "equal":
                return a_val == b_val
            if op == "not_equal":
                return a_val != b_val
            if op == "above":
                return a_val > b_val
            if op == "below":
                return a_val < b_val
            if op == "above_equal":
                return a_val >= b_val
            return a_val <= b_val  # below_equal (whitelist closed above)
        if op not in ("equal", "not_equal") or a_num != b_num:
            # above-family on string ends, or one numeric end against one
            # state end — semantics broken, visible False beats a guess
            self._warn_eval_failure(
                cid, "compare type mismatch", f"{op}: {a_val!r} vs {b_val!r}"
            )
            return False
        return (a_val == b_val) if op == "equal" else (a_val != b_val)

    def _compare_input(
        self, side: Any, cid: str, which: str
    ) -> tuple[Any, bool] | None:
        """Resolve one compare input end to ``(value, is_numeric)``.

        Returns None — after a rate-limited WARN naming the cause — when
        the end cannot be read: unavailable/missing entity, missing
        attribute, absent snapshot, missing/malformed literal. An entity
        end (state or attribute) is numeric exactly when the raw reading
        parses as a number; a snapshot end is numeric exactly when the
        captured value is a float (auto-typed at capture time)."""
        if not isinstance(side, dict):
            self._warn_eval_failure(cid, f"compare input {which}", side)
            return None
        kind = side.get("kind")
        if kind == "entity":
            state = self.hass.states.get(side.get(CONF_ENTITY_ID))
            if not state or state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
                self._warn_eval_failure(
                    cid,
                    f"compare input {which} (entity unreadable)",
                    side.get(CONF_ENTITY_ID),
                )
                return None
            if side.get("attribute"):
                raw = (state.attributes or {}).get(side["attribute"])
                if raw is None:
                    self._warn_eval_failure(
                        cid,
                        f"compare input {which} (attribute missing)",
                        side["attribute"],
                    )
                    return None
            else:
                raw = state.state
        elif kind == COND_SNAPSHOT:
            raw = self._snapshot_values.get(side.get("cond"))
            if raw is None:
                self._warn_eval_failure(
                    cid,
                    f"compare input {which} (snapshot absent)",
                    side.get("cond"),
                )
                return None
        elif kind == COND_LITERAL:
            lcond = self._conditions.get(side.get("cond"))
            value = lcond.get(CONF_VALUE) if isinstance(lcond, dict) else None
            if (
                not isinstance(lcond, dict)
                or lcond.get("type") != COND_LITERAL
                or (
                    lcond.get(CONF_VALUE_TYPE) == "number"
                    and (
                        isinstance(value, bool)
                        or not isinstance(value, (int, float))
                    )
                )
            ):
                self._warn_eval_failure(
                    cid,
                    f"compare input {which} (literal unreadable)",
                    side.get("cond"),
                )
                return None
            if lcond[CONF_VALUE_TYPE] == "number":
                return float(value), True
            return value, False
        else:
            self._warn_eval_failure(cid, f"compare input {which} (kind)", kind)
            return None
        # entity/snapshot end: numeric exactly when the reading parses as
        # a FINITE number (NaN/inf count as STRING ends, the same
        # isfinite gate the capture path and the literal validation apply
        # — R3-3). Unsupported attribute TYPES (bool/list/dict…) are
        # neither numbers nor strings — a visible False with a WARN beats
        # the silent always-false equality they used to produce (R4-4).
        if not isinstance(raw, (str, int, float)) or isinstance(raw, bool):
            self._warn_eval_failure(
                cid,
                f"compare input {which} (unsupported attribute type)",
                type(raw).__name__,
            )
            return None
        value = _parse_finite_float(raw)
        if value is not None:
            return value, True
        return raw, False

    def _evaluate_trip(self, cond: dict, ctype: str, path: str) -> bool:
        """Trip leaves (0.16.0): read the trip_count trip binary sensor.

        trip_on: the sensor's state == "on" (a trip segment is open).
        trip_day: on AND the ``day_n`` attribute == the configured day (the
        Nth day of the trip — trip_count owns the 跨点 semantics behind
        day_n; WHA only mirrors the value).
        trip_duration: on AND (now − ``since``) >= the configured hours.

        An unreadable source (missing entity, unknown/unavailable state) or
        a missing/unparseable attribute degrades LOUDLY: rate-limited WARN
        (the F-323 face) + False — 决策 5 显式不可用，禁静默回落. A trip in
        progress with day_n/since absent is the same loud face (a lying or
        foreign source must stay visible, not silently read False)."""
        cid = cond.get("id") or path
        eid = cond.get(CONF_ENTITY_ID)
        state = self.hass.states.get(eid)
        if not state or state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            self._warn_eval_failure(cid, "trip source unreadable", eid)
            return False
        if ctype == COND_TRIP_ON:
            return state.state == "on"
        attrs = getattr(state, "attributes", None) or {}
        if ctype == COND_TRIP_DAY:
            day_n = attrs.get(TRIP_ATTR_DAY_N)
            if isinstance(day_n, bool) or not isinstance(day_n, int):
                self._warn_eval_failure(
                    cid, "trip day_n missing", f"{eid} day_n={day_n!r}"
                )
                return False
            return day_n == int(cond.get(CONF_DAY, 1))
        # COND_TRIP_DURATION
        since_raw = attrs.get(TRIP_ATTR_SINCE)
        start = None
        if isinstance(since_raw, str):
            try:
                start = dt_util.parse_datetime(since_raw)
            except (TypeError, ValueError):
                start = None
        if start is None:
            self._warn_eval_failure(
                cid, "trip since missing", f"{eid} since={since_raw!r}"
            )
            return False
        if start.tzinfo is None:
            # R2#1 shape: an offset-less ISO is salvageable data — normalize
            # to UTC instead of TypeError-ing on the subtraction below.
            start = dt_util.as_utc(start)
        hours = float(cond.get(CONF_HOURS, 0) or 0)
        elapsed = (dt_util.utcnow() - dt_util.as_utc(start)).total_seconds()
        return elapsed >= hours * 3600

    async def _evaluate_leaf(
        self, cond: dict, ctype: str, path: str, out_id: str | None = None
    ) -> bool:
        """Evaluate a leaf condition without FOR handling."""
        if ctype in TRIP_TYPES:
            return self._evaluate_trip(cond, ctype, path)

        if ctype == COND_SNAPSHOT:
            # Verdict = the snapshot EXISTS (no snapshot → always False).
            # The value itself is read by compare inputs, never here; the
            # source entity is only read at capture time (step_snapshots).
            return cond.get("id") in self._snapshot_values

        if ctype == COND_LITERAL:
            # Constant node: the value is always there, so the node is
            # always satisfied — no special case needed anywhere (groups
            # and output chains treat it like any true leaf).
            return True

        if ctype == COND_COMPARE:
            return self._evaluate_compare(cond, path)

        if ctype == "numeric_state":
            eid = cond.get(CONF_ENTITY_ID)
            state = self.hass.states.get(eid)
            if not state or state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
                return False
            try:
                val = float(state.state)
            except (ValueError, TypeError):
                return False
            try:
                above = cond.get("above")
                below = cond.get("below")
                above_f = float(above) if above is not None else None
                below_f = float(below) if below is not None else None
            except (TypeError, ValueError):
                _LOGGER.debug("Invalid above/below in numeric_state at %s", path)
                return False
            if above_f is not None and val <= above_f:
                return False
            return below_f is None or val < below_f

        if ctype == "state":
            eid = cond.get(CONF_ENTITY_ID)
            state = self.hass.states.get(eid)
            if not state:
                return False
            expected = cond.get(CONF_STATE)
            if expected is None:
                return True
            if isinstance(expected, list):
                return state.state in expected
            return state.state == expected

        if ctype == "template":
            tpl_str = cond.get(CONF_VALUE_TEMPLATE)
            if not tpl_str:
                return False
            template = self._template_cache.get(tpl_str)
            if template is None:
                template = Template(tpl_str, self.hass)
                self._template_cache[tpl_str] = template
            try:
                return bool(template.async_render())
            except Exception as err:  # noqa: BLE001 — 模板渲染可抛任意异常，失败即条件不成立
                _LOGGER.debug(
                    "Template condition at %s failed to render (%s): %s",
                    path,
                    tpl_str,
                    err,
                )
                self._warn_eval_failure(cond.get("id") or path, "template", err)
                return False

        if ctype == "time":
            return self._time_window_verdict(cond, dt_util.now())

        if ctype == "sun":
            return self._sun_verdict(cond, dt_util.now())

        if ctype == "cooldown":
            seconds = float(cond.get(CONF_SECONDS, 0))
            if self._manager is None or not out_id:
                _LOGGER.debug(
                    "Cooldown condition at %s has no output context; False", path
                )
                return False
            last = self._manager.last_flip_at(out_id)
            if last is None:
                return True  # never flipped: no cooldown in effect
            elapsed = (dt_util.utcnow() - last).total_seconds()
            return elapsed >= seconds

        if ctype == "calendar":
            eid = cond.get(CONF_ENTITY_ID)
            hours = float(cond.get(CONF_HOURS, 24))
            component = self.hass.data.get("entity_components", {}).get("calendar")
            entity = component.get_entity(eid) if component else None
            if entity is None:
                _LOGGER.debug("Calendar entity %s not found; False", eid)
                self._warn_eval_failure(
                    cond.get("id") or eid or path, "calendar entity missing", eid
                )
                return False
            start = dt_util.now()
            end = start + timedelta(hours=hours)
            try:
                # One query with a one-window look-ahead: the verdict counts
                # only events intersecting [now, now+hours] (unchanged
                # semantics), while the boundary cache below also sees events
                # that ENTER the window later — their `start - hours` edge is
                # still future, and without the look-ahead a verdict-False
                # evaluation would cache nothing and fall back to the
                # heartbeat (F-320).
                events = await entity.async_get_events(
                    self.hass, start, end + timedelta(hours=hours)
                )
            except Exception as err:  # noqa: BLE001 — calendar backends may raise anything
                _LOGGER.debug("Calendar query for %s failed: %s", eid, err)
                self._warn_eval_failure(
                    cond.get("id") or eid or path, "calendar query", err
                )
                return False
            # F-320: cache the earliest future flip instant — events enter
            # the verdict window at `start - hours` and leave at `end`.
            # CalendarEvent.start_datetime_local/end_datetime_local normalize
            # both plain and all-day events (date objects) to aware local
            # datetimes (2026.1.3 wheel), so edges compare directly against
            # utcnow().
            now_utc = dt_util.utcnow()
            in_window = False
            boundaries: list[datetime] = []
            for ev in events or ():
                ev_start = getattr(ev, "start_datetime_local", None)
                ev_end = getattr(ev, "end_datetime_local", None)
                if ev_start is None or ev_end is None:
                    # exotic backend payload: cannot judge the window — skip
                    continue
                if ev_start < end and ev_end > start:
                    in_window = True
                boundaries.append(ev_start - timedelta(hours=hours))
                boundaries.append(ev_end)
            future = [b for b in boundaries if b > now_utc]
            if future:
                self._calendar_next[cond.get("id") or path] = min(future)
            else:
                self._calendar_next.pop(cond.get("id") or path, None)
            return in_window

        _LOGGER.debug("Unknown condition type '%s' at %s", ctype, path)
        return False

    def _sun_event(self, event: str, day) -> Any:
        """Return the sun event datetime for a date, cached per (event, date).

        ``homeassistant.helpers.sun.get_astral_event_date`` is a ``@callback``
        (plain sync, pure CPU) — safe to call in the event loop and must NOT
        be awaited. There is no ``async_get_astral_event_date``.
        """
        key = (event, day.isoformat())
        if key in self._sun_cache:
            return self._sun_cache[key]
        from homeassistant.helpers import sun as sun_helper

        ev = sun_helper.get_astral_event_date(self.hass, event, day)
        if len(self._sun_cache) >= _SUN_CACHE_MAX:
            self._sun_cache.clear()
        self._sun_cache[key] = ev
        return ev

    # ------------------------------------------------------------------
    # FOR handling
    # ------------------------------------------------------------------

    def _apply_for(self, cond: dict, path: str, satisfied: bool) -> bool:
        """Apply FOR duration; timers are keyed by condition id when present."""
        key = cond.get("id") or path
        if not satisfied:
            self._for_timers.pop(key, None)
            return False
        for_cfg = cond.get("for")
        if not for_cfg:
            return True
        duration = self._parse_for(for_cfg)
        if not duration or duration.total_seconds() <= 0:
            return True
        now = dt_util.utcnow()
        start = self._for_timers.get(key)
        if start is None:
            self._for_timers[key] = now
            return False
        return now - start >= duration

    # ------------------------------------------------------------------
    # Parsing helpers
    # ------------------------------------------------------------------

    def _parse_for(self, cfg: Any) -> timedelta | None:
        """Parse a FOR duration: seconds, 'HH:MM[:SS]' string, or h/m/s dict."""
        if isinstance(cfg, bool):
            return None
        if isinstance(cfg, (int, float)):
            return timedelta(seconds=float(cfg))
        if isinstance(cfg, str):
            text = cfg.strip()
            if not text:
                return None
            try:
                return timedelta(seconds=float(text))
            except ValueError:
                pass
            parts = text.split(":")
            if len(parts) in (2, 3):
                try:
                    hours = float(parts[0])
                    minutes = float(parts[1])
                    seconds = float(parts[2]) if len(parts) == 3 else 0.0
                except ValueError:
                    return None
                return timedelta(hours=hours, minutes=minutes, seconds=seconds)
            return None
        if isinstance(cfg, dict):
            try:
                return timedelta(
                    hours=float(cfg.get("hours", 0) or 0),
                    minutes=float(cfg.get("minutes", 0) or 0),
                    seconds=float(cfg.get("seconds", 0) or 0),
                )
            except (TypeError, ValueError):
                return None
        return None

    def _parse_offset(self, offset: Any) -> timedelta:
        """Parse a sun offset in seconds (fractional seconds preserved)."""
        if offset is None or isinstance(offset, bool):
            return timedelta(0)
        if isinstance(offset, (int, float)):
            try:
                return timedelta(seconds=float(offset))
            except (TypeError, ValueError, OverflowError):
                return timedelta(0)
        if isinstance(offset, str):
            text = offset.strip()
            neg = text.startswith("-")
            if text.startswith(("+", "-")):
                text = text[1:]
            if not text:
                return timedelta(0)
            try:
                seconds = float(text)
                return timedelta(seconds=-seconds if neg else seconds)
            except ValueError:
                pass
            parts = text.split(":")
            if len(parts) in (2, 3):
                try:
                    hours = float(parts[0])
                    minutes = float(parts[1])
                    seconds = float(parts[2]) if len(parts) == 3 else 0.0
                except ValueError:
                    return timedelta(0)
                td = timedelta(hours=hours, minutes=minutes, seconds=seconds)
                return -td if neg else td
        return timedelta(0)
