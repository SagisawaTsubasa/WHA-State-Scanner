"""Modular condition evaluation engine.

Since 0.5.0 conditions may reference the *evaluating output* (cooldown)
via the ``out_id`` context, consult the owning manager's flip history,
and query calendar entities. FOR timers still run per condition id and
expose their earliest expiry so the controller can wake up exactly when
a duration elapses (trigger-driven evaluation has no polling fallback).
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
    CONF_AT,
    CONF_HOURS,
    CONF_SECONDS,
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

    def next_for_expiry(self) -> datetime | None:
        """Earliest future expiry among running FOR timers (UTC), or None.

        The controller schedules a point-in-time wakeup at this instant so
        duration-based conditions still flip in a trigger-driven (non
        polling) setup.
        """
        now = dt_util.utcnow()
        earliest: datetime | None = None
        for cid, start in self._for_timers.items():
            cond = self._conditions.get(cid)
            if not cond:
                continue
            duration = self._parse_for(cond.get("for"))
            if not duration:
                continue
            expiry = start + duration
            if expiry > now and (earliest is None or expiry < earliest):
                earliest = expiry
        return earliest

    def next_wakeup(self, out_ids) -> datetime | None:
        """Earliest instant (UTC) at which some condition's verdict could
        change on its own: a running FOR duration, the next `time.at`
        minute window, or a cooldown elapsing. None when nothing is
        pending. The controller schedules a point-in-time wakeup here."""
        now_utc = dt_util.utcnow()
        now_local = dt_util.now()
        candidates: list[datetime] = []
        for_expiry = self.next_for_expiry()
        if for_expiry:
            candidates.append(for_expiry)
        for cond in self._conditions.values():
            if not isinstance(cond, dict) or cond.get("enabled") is False:
                continue
            if cond.get("type") == "time" and cond.get(CONF_AT):
                parts = str(cond[CONF_AT]).split(":")
                weekdays = cond.get(CONF_WEEKDAYS)
                for add_days in range(8):
                    day = now_local + timedelta(days=add_days)
                    if weekdays and _WEEKDAY_KEYS[day.weekday()] not in weekdays:
                        continue
                    target = dt_util.start_of_local_day(day) + timedelta(
                        hours=int(parts[0]),
                        minutes=int(parts[1]),
                        seconds=int(parts[2]) if len(parts) > 2 else 0,
                    )
                    if target > now_local:
                        candidates.append(dt_util.as_utc(target))
                        break
            elif cond.get("type") == "cooldown":
                seconds = float(cond.get(CONF_SECONDS, 0))
                for oid in out_ids:
                    last = self._manager.last_flip_at(oid) if self._manager else None
                    if last is None:
                        continue
                    expiry = last + timedelta(seconds=seconds)
                    if expiry > now_utc:
                        candidates.append(expiry)
        return min(candidates) if candidates else None

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

        raw = await self._evaluate_leaf(cond, ctype, path, out_id)
        return self._apply_for(cond, path, raw)

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
            now_local = dt_util.now()
            weekdays = cond.get(CONF_WEEKDAYS)
            if weekdays and _WEEKDAY_KEYS[now_local.weekday()] not in weekdays:
                return False
            at = cond.get(CONF_AT)
            if at:
                # Hit window: [at, at + 1 minute) local time (seconds honoured
                # as the window start).
                parts = [int(x) for x in at.split(":")]
                target = now_local.replace(
                    hour=parts[0], minute=parts[1],
                    second=parts[2] if len(parts) > 2 else 0, microsecond=0,
                )
                delta = (now_local - target).total_seconds()
                return 0 <= delta < 60
            after = dt_util.parse_time(cond["after"]) if cond.get("after") else None
            before = dt_util.parse_time(cond["before"]) if cond.get("before") else None
            if after is not None and before is not None and after > before:
                # Cross-midnight window (e.g. after 22:00, before 06:00).
                return now_local.time() >= after or now_local.time() <= before
            if after is not None and now_local.time() < after:
                return False
            return before is None or now_local.time() <= before

        if ctype == "sun":
            now = dt_util.now()
            today = now.date()
            after = cond.get("after")
            before = cond.get("before")
            aoff = self._parse_offset(cond.get("after_offset", 0))
            boff = self._parse_offset(cond.get("before_offset", 0))
            ok = True
            if after in ("sunrise", "sunset"):
                ev = self._sun_event(after, today)
                if ev and now < ev + aoff:
                    ok = False
            if before in ("sunrise", "sunset"):
                ev = self._sun_event(before, today)
                if ev and now > ev + boff:
                    ok = False
            return ok

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
