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
    CONF_HOURS,
    CONF_SECONDS,
    CONF_START,
    CONF_WEEKDAYS,
)

_LOGGER = logging.getLogger(__name__)

GROUP_TYPES = ("and", "or", "not")

# Cap for the per-date sun event cache.
_SUN_CACHE_MAX = 16

_WEEKDAY_KEYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


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
    ) -> None:
        """Initialize."""
        self.hass = hass
        # Weak coupling: the cooldown leaf reads the manager's flip history.
        # Duck-typed to avoid an import cycle (manager ↔ engine).
        self._manager = manager
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
        self._template_cache: dict[str, Template] = {}
        self._sun_cache: dict[tuple[str, str], Any] = {}

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
            if not members:
                # Deliberately stricter than HA (empty and/not → True there):
                # the schema rejects empty groups anyway, so this branch only
                # guards hand-edited stores against forcing outputs on.
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

    async def _evaluate_leaf(
        self, cond: dict, ctype: str, path: str, out_id: str | None = None
    ) -> bool:
        """Evaluate a leaf condition without FOR handling."""
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
                return False
            start = dt_util.now()
            end = start + timedelta(hours=hours)
            try:
                events = await entity.async_get_events(self.hass, start, end)
            except Exception as err:  # noqa: BLE001 — calendar backends may raise anything
                _LOGGER.debug("Calendar query for %s failed: %s", eid, err)
                return False
            return bool(events)

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
