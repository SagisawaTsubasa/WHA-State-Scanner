"""Modular condition evaluation engine."""

from __future__ import annotations

import logging
from datetime import timedelta
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

_LOGGER = logging.getLogger(__name__)


class ConditionEngine:
    """Evaluates a library of conditions with FOR-timer support."""

    def __init__(self, hass: HomeAssistant, conditions: list[dict]) -> None:
        """Init."""
        self.hass = hass
        self._conditions = {c["id"]: c for c in conditions}
        self._for_timers: dict[str, Any] = {}

    def evaluate_any(self, cond_ids: list[str]) -> bool:
        """OR across condition IDs."""
        if not cond_ids:
            return False
        return any(self._evaluate_id(cid) for cid in cond_ids)

    def _evaluate_id(self, cid: str) -> bool:
        """Evaluate by condition ID."""
        cond = self._conditions.get(cid)
        if not cond:
            return False
        return self._evaluate_cond(cond, f"id:{cid}")

    def _evaluate_cond(self, cond: dict, path: str) -> bool:
        """Recursive evaluation."""
        ctype = cond.get("type", "and")

        if ctype == "and":
            subs = cond.get("conditions", [])
            for i, sub in enumerate(subs):
                if not self._evaluate_cond(sub, f"{path}.a{i}"):
                    return False
            return True

        if ctype == "or":
            subs = cond.get("conditions", [])
            for i, sub in enumerate(subs):
                if self._evaluate_cond(sub, f"{path}.o{i}"):
                    return True
            return False

        raw = self._evaluate_leaf(cond, ctype)
        return self._apply_for(cond, path, raw)

    def _evaluate_leaf(self, cond: dict, ctype: str) -> bool:
        """Evaluate without FOR."""
        if ctype == "numeric_state":
            eid = cond.get("entity_id")
            state = self.hass.states.get(eid)
            if not state or state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
                return False
            try:
                val = float(state.state)
            except (ValueError, TypeError):
                return False
            above = cond.get("above")
            below = cond.get("below")
            if above is not None and val <= float(above):
                return False
            if below is not None and val >= float(below):
                return False
            return True

        if ctype == "state":
            eid = cond.get("entity_id")
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
            tpl = cond.get(CONF_VALUE_TEMPLATE)
            if not tpl:
                return False
            template = Template(tpl, self.hass)
            try:
                return bool(template.async_render())
            except Exception:
                return False

        if ctype == "time":
            now = dt_util.now().time()
            after = cond.get("after")
            before = cond.get("before")
            if after:
                at = dt_util.parse_time(after)
                if at and now < at:
                    return False
            if before:
                bt = dt_util.parse_time(before)
                if bt and now > bt:
                    return False
            return True

        if ctype == "sun":
            from homeassistant.helpers import sun as sun_helper
            now = dt_util.now()
            after = cond.get("after")
            before = cond.get("before")
            aoff = self._parse_offset(cond.get("after_offset", 0))
            boff = self._parse_offset(cond.get("before_offset", 0))
            ok = True
            if after == "sunrise":
                ev = sun_helper.get_astral_event_date(self.hass, "sunrise", dt_util.now().date())
                if ev and now < ev + aoff:
                    ok = False
            elif after == "sunset":
                ev = sun_helper.get_astral_event_date(self.hass, "sunset", dt_util.now().date())
                if ev and now < ev + aoff:
                    ok = False
            if before == "sunrise":
                ev = sun_helper.get_astral_event_date(self.hass, "sunrise", dt_util.now().date())
                if ev and now > ev + boff:
                    ok = False
            elif before == "sunset":
                ev = sun_helper.get_astral_event_date(self.hass, "sunset", dt_util.now().date())
                if ev and now > ev + boff:
                    ok = False
            return ok

        return False

    def _apply_for(self, cond: dict, path: str, satisfied: bool) -> bool:
        """Apply FOR duration."""
        if not satisfied:
            self._for_timers.pop(path, None)
            return False
        for_cfg = cond.get("for")
        if not for_cfg:
            return True
        duration = self._parse_for(for_cfg)
        if not duration or duration.total_seconds() <= 0:
            return True
        now = dt_util.utcnow()
        if path not in self._for_timers:
            self._for_timers[path] = now
            return False
        return now - self._for_timers[path] >= duration

    def _parse_for(self, cfg) -> timedelta | None:
        if isinstance(cfg, (int, float)):
            return timedelta(seconds=int(cfg))
        if isinstance(cfg, str):
            try:
                return timedelta(seconds=int(cfg))
            except ValueError:
                pass
        if isinstance(cfg, dict):
            return timedelta(
                hours=cfg.get("hours", 0),
                minutes=cfg.get("minutes", 0),
                seconds=cfg.get("seconds", 0),
            )
        return None

    def _parse_offset(self, offset) -> timedelta:
        if isinstance(offset, int):
            return timedelta(seconds=offset)
        if isinstance(offset, float):
            return timedelta(seconds=int(offset))
        if isinstance(offset, str):
            offset = offset.strip()
            neg = offset.startswith("-")
            if neg:
                offset = offset[1:]
            try:
                s = int(offset)
                return timedelta(seconds=-s if neg else s)
            except ValueError:
                pass
            try:
                parts = offset.split(":")
                if len(parts) == 3:
                    td = timedelta(hours=int(parts[0]), minutes=int(parts[1]), seconds=int(parts[2]))
                    return -td if neg else td
            except ValueError:
                pass
        return timedelta(0)
