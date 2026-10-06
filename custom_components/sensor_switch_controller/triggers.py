"""Trigger framework: registers the evaluation triggers of one controller.

Every configured trigger funnels into ``on_fire``; the controller debounces
those callbacks and runs one full evaluation. Semantics stay level-based —
triggers only decide *when* to evaluate, never *what* the result is.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from homeassistant.const import CONF_ATTRIBUTE, CONF_ENTITY_ID
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.event import (
    async_track_point_in_time,
    async_track_state_change_event,
    async_track_sunrise,
    async_track_sunset,
    async_track_time_interval,
)
from homeassistant.util import dt as dt_util

from .const import (
    CONF_AT,
    CONF_EVERY_SECONDS,
    CONF_FROM,
    CONF_OFFSET,
    CONF_TO,
    TRG_HOMEASSISTANT,
    TRG_STATE,
    TRG_SUN,
    TRG_TIME,
)

_LOGGER = logging.getLogger(__name__)


def _match_filter(value, expected) -> bool:
    """Match a from/to filter: None filter matches everything.

    Values are compared stringified so numeric attribute values (e.g.
    brightness 0) match string expectations ("0").
    """
    if expected is None:
        return True
    if isinstance(expected, list):
        return str(value) in [str(e) for e in expected]
    return str(value) == str(expected)


class TriggerManager:
    """Owns every listener of one controller's trigger list."""

    def __init__(
        self,
        hass: HomeAssistant,
        triggers: list[dict],
        on_fire: callback,
    ) -> None:
        """Initialize. ``on_fire(description)`` is invoked (debounced by the
        controller) whenever any enabled trigger fires."""
        self.hass = hass
        self._configs = triggers
        self._on_fire = on_fire
        self._unsubs: list[CALLBACK_TYPE] = []
        self._register_errors = 0
        self._started = False

    @property
    def register_errors(self) -> int:
        """Triggers that failed to register (surfaced in the panel)."""
        return self._register_errors

    @property
    def configs(self) -> list[dict]:
        return self._configs

    def async_setup(self, pool_entity_ids: list[str]) -> None:
        """Register listeners for every enabled trigger."""
        if self._started:
            return
        self._started = True
        for trg in self._configs:
            if not trg.get("enabled", True):
                continue
            try:
                self._async_register(trg, pool_entity_ids)
            except Exception:
                self._register_errors += 1
                _LOGGER.exception(
                    "Failed to register trigger %s", trg.get("id", "<unknown>")
                )

    @callback
    def async_unload(self) -> None:
        """Cancel every listener."""
        for unsub in self._unsubs:
            try:
                unsub()
            except (TypeError, ValueError, RuntimeError):
                pass
        self._unsubs.clear()
        self._started = False

    # ------------------------------------------------------------------

    @callback
    def _async_register(self, trg: dict, pool_entity_ids: list[str]) -> None:
        ttype = trg.get("type")

        if ttype == TRG_STATE:
            entity_id = trg.get(CONF_ENTITY_ID) or None
            if entity_id:
                targets = [entity_id]
            else:
                targets = list(pool_entity_ids)
            if not targets:
                _LOGGER.debug(
                    "State trigger %s has no targets (empty pool); skipped",
                    trg.get("id"),
                )
                return
            self._unsubs.append(
                async_track_state_change_event(
                    self.hass, targets, self._make_state_cb(trg)
                )
            )

        elif ttype == TRG_TIME:
            at = trg.get(CONF_AT)
            if at:
                self._unsubs.append(self._schedule_daily_at(at, self._make_cb(trg)))
            else:
                every = int(trg.get(CONF_EVERY_SECONDS, 0))
                if every <= 0:
                    _LOGGER.warning(
                        "Time trigger %s without at/every_seconds; skipped",
                        trg.get("id"),
                    )
                    return
                self._unsubs.append(
                    async_track_time_interval(
                        self.hass, self._make_cb(trg), timedelta(seconds=every)
                    )
                )

        elif ttype == TRG_SUN:
            event = trg.get("event", "sunrise")
            offset = timedelta(seconds=int(trg.get(CONF_OFFSET, 0)))
            tracker = (
                async_track_sunrise if event == "sunrise" else async_track_sunset
            )
            # These helpers re-arm themselves for every following day.
            self._unsubs.append(tracker(self.hass, self._make_cb(trg), offset))

        elif ttype == TRG_HOMEASSISTANT:
            from homeassistant.helpers.start import async_at_started

            self._unsubs.append(
                async_at_started(self.hass, self._make_cb(trg))
            )

        else:
            _LOGGER.warning("Unknown trigger type %r; skipped", ttype)

    @callback
    def _make_cb(self, trg: dict):
        description = trg.get("label") or trg.get("id", trg.get("type", "?"))

        @callback
        def _fire(_now_or_event=None) -> None:
            self._on_fire(description)

        return _fire

    @callback
    def _make_state_cb(self, trg: dict):
        attribute = trg.get(CONF_ATTRIBUTE)
        from_filter = trg.get(CONF_FROM)
        to_filter = trg.get(CONF_TO)
        description = trg.get("label") or trg.get("id", "state")

        @callback
        def _on_event(event) -> None:
            old_state = event.data.get("old_state")
            new_state = event.data.get("new_state")
            # HA semantics: with `attribute:` set, from/to match the attribute
            # value (stringified) instead of the entity state string.
            if attribute is not None:
                old_val = str(old_state.attributes.get(attribute)) if old_state else None
                new_val = str(new_state.attributes.get(attribute)) if new_state else None
                if new_val == old_val:
                    return
            else:
                old_val = old_state.state if old_state else None
                new_val = new_state.state if new_state else None
                if old_val == new_val:
                    return
            if not _match_filter(old_val, from_filter):
                return
            if not _match_filter(new_val, to_filter):
                return
            self._on_fire(description)

        return _on_event

    @callback
    def _schedule_daily_at(self, at: str, fire_cb) -> CALLBACK_TYPE:
        """Schedule a daily fire at ``at`` (HH:MM[:SS]), re-arming forever."""
        parts = at.split(":")
        hour, minute = int(parts[0]), int(parts[1])
        second = int(parts[2]) if len(parts) > 2 else 0
        holder: list[CALLBACK_TYPE] = []

        @callback
        def _fire_and_rearm(now: datetime) -> None:
            holder.clear()  # fired handle is done
            fire_cb(now)
            _rearm()

        def _rearm() -> None:
            now = dt_util.now()
            day_start = dt_util.start_of_local_day(now)
            target = day_start + timedelta(hours=hour, minutes=minute, seconds=second)
            if target <= now:
                target = dt_util.start_of_local_day(now + timedelta(days=1)) + timedelta(
                    hours=hour, minutes=minute, seconds=second
                )
            holder.append(
                async_track_point_in_time(self.hass, _fire_and_rearm, target)
            )

        _rearm()

        @callback
        def _cancel() -> None:
            while holder:
                handle = holder.pop()
                try:
                    handle()
                except (TypeError, ValueError, RuntimeError):
                    pass

        return _cancel
