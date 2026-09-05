"""Controller manager – orchestrates sensors, conditions, outputs."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_time_interval

from .condition_engine import ConditionEngine
from .const import (
    CONF_CONDITIONS,
    CONF_LOGGING,
    CONF_OUTPUTS,
    CONF_SCAN_INTERVAL,
    CONF_SENSORS,
    DEFAULT_SCAN_INTERVAL,
)
from .logbook import DecisionLogger

_LOGGER = logging.getLogger(__name__)


class ControllerManager:
    """Manages one controller instance."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        self.hass = hass
        self.entry = entry
        self.options = entry.options

        self.name = entry.title
        self.scan_interval = timedelta(
            seconds=self.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        )
        self.sensors = self.options.get(CONF_SENSORS, [])
        self.conditions = self.options.get(CONF_CONDITIONS, [])
        self.outputs = self.options.get(CONF_OUTPUTS, [])
        self.logging_enabled = self.options.get(CONF_LOGGING, False)

        self.engine = ConditionEngine(hass, self.conditions)
        self.logger = DecisionLogger(
            hass, self.name, entry.entry_id, enabled=self.logging_enabled
        )

        # Registered output entities, keyed by the stable internal output id
        # (out_cfg["entity_id"], e.g. "ssc_<hex>") — the same key used for
        # lookups during evaluation.
        self._entities: dict[str, Any] = {}
        self._expected_out_ids = {
            out["entity_id"]
            for out in self.outputs
            if isinstance(out, dict) and out.get("entity_id")
        }
        self._added_out_ids: set[str] = set()
        self._first_eval_pending = True
        self._remove_interval = None
        self._warned_bad_sensors = False

    async def async_setup(self) -> None:
        """Start polling and schedule a one-off old-log cleanup.

        The first evaluation is deferred until the platform entities have
        been registered (see ``async_entity_added``) so it does not idle.
        """
        self._remove_interval = async_track_time_interval(
            self.hass, self._async_evaluate, self.scan_interval
        )
        self.hass.async_create_task(self.logger.async_cleanup())

    async def async_unload(self) -> None:
        """Stop polling and drop all entity references."""
        if self._remove_interval:
            self._remove_interval()
            self._remove_interval = None
        self._entities.clear()
        self._added_out_ids.clear()
        self._first_eval_pending = False

    # ------------------------------------------------------------------
    # Entity registration
    # ------------------------------------------------------------------

    def register_entity(self, out_id: str, entity) -> None:
        """Register an output entity under its stable internal id."""
        self._entities[out_id] = entity

    def unregister_entity(self, out_id: str) -> None:
        """Drop an entity reference (called on entity removal)."""
        self._entities.pop(out_id, None)
        self._added_out_ids.discard(out_id)

    def async_entity_added(self, out_id: str) -> None:
        """Notify the manager that an output entity finished adding to hass.

        Once every expected output entity is present, the first evaluation
        is triggered instead of idling for up to one scan interval.
        """
        self._added_out_ids.add(out_id)
        if (
            self._first_eval_pending
            and self._expected_out_ids
            and self._expected_out_ids <= self._added_out_ids
        ):
            self._first_eval_pending = False
            self.hass.async_create_task(self._async_evaluate(None))

    @property
    def entities(self) -> dict[str, Any]:
        """Expose registered output entities (read-only view)."""
        return self._entities

    # ------------------------------------------------------------------
    # Evaluation
    # ------------------------------------------------------------------

    def _async_read_sensors(self) -> dict[str, Any]:
        """Collect current states of the configured sensor pool."""
        readings: dict[str, Any] = {}
        for sensor_cfg in self.sensors:
            if not isinstance(sensor_cfg, dict):
                continue
            eid = sensor_cfg.get("entity_id")
            if not eid:
                if not self._warned_bad_sensors:
                    self._warned_bad_sensors = True
                    _LOGGER.warning(
                        "Sensor entry without entity_id is skipped: %r", sensor_cfg
                    )
                continue
            state = self.hass.states.get(eid)
            readings[eid] = state.state if state else None
        return readings

    async def _async_evaluate(self, _now: Any) -> None:
        """Evaluate all outputs; one output failing never blocks the rest."""
        self._first_eval_pending = False
        readings = self._async_read_sensors()

        records: list[dict] = []
        for out_cfg in self.outputs:
            if not isinstance(out_cfg, dict):
                continue
            try:
                record = await self._async_evaluate_output(out_cfg, readings)
            except Exception:
                _LOGGER.exception(
                    "Error evaluating output '%s'", out_cfg.get("name", "<unknown>")
                )
                continue
            if record is not None:
                records.append(record)

        if self.logging_enabled and records:
            await self.logger.log_cycle(records)

    async def _async_evaluate_output(
        self, out_cfg: dict, readings: dict[str, Any]
    ) -> dict | None:
        """Evaluate one output and apply its action. Returns a log record."""
        out_id = out_cfg.get("entity_id")
        if not out_id:
            _LOGGER.warning(
                "Output without entity_id is skipped: %r", out_cfg.get("name")
            )
            return None

        entity = self._entities.get(out_id)
        if entity is None:
            return None
        if getattr(entity, "entity_id", None) is None:
            # Entity object exists but has not been added to hass yet.
            return None

        on_ids = out_cfg.get("on_conditions", [])
        off_ids = out_cfg.get("off_conditions", [])

        on_met = await self.engine.evaluate_any(on_ids)
        off_met = await self.engine.evaluate_any(off_ids)

        decision = "hold"
        if off_met:
            decision = "off"
            if entity.is_on:
                await entity.async_controller_turn_off()
        elif on_met:
            decision = "on"
            if not entity.is_on:
                await entity.async_controller_turn_on()

        return {
            "output": out_cfg.get("name"),
            "decision": decision,
            "on_met": on_met,
            "off_met": off_met,
            "readings": readings,
        }

    async def async_evaluate_output(self, out_id: str) -> None:
        """Evaluate only the output identified by its internal id (service API)."""
        out_cfg = next(
            (
                out
                for out in self.outputs
                if isinstance(out, dict) and out.get("entity_id") == out_id
            ),
            None,
        )
        if out_cfg is None:
            _LOGGER.warning("Unknown output id '%s'; nothing to evaluate", out_id)
            return
        readings = self._async_read_sensors()
        try:
            record = await self._async_evaluate_output(out_cfg, readings)
        except Exception:
            _LOGGER.exception(
                "Error evaluating output '%s'", out_cfg.get("name", out_id)
            )
            return
        if record is not None and self.logging_enabled:
            await self.logger.log_cycle([record])
