"""Controller manager – orchestrates sensors, conditions, outputs.

Since 0.4.0 a manager is keyed by a stable ``ctrl_<hex>`` id and configured
from a plain controller dict (stored in the domain-level Store by
``hub.ScannerHub``), not from a per-controller config entry.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import dt as dt_util

from .condition_engine import ConditionEngine
from .const import (
    CONF_CONDITIONS,
    CONF_LOGGING,
    CONF_OUTPUTS,
    CONF_SCAN_INTERVAL,
    CONF_SENSORS,
    DEFAULT_SCAN_INTERVAL,
)
from .decision_log import DecisionLogger

_LOGGER = logging.getLogger(__name__)


class ControllerManager:
    """Manages one controller instance."""

    def __init__(
        self, hass: HomeAssistant, controller_id: str, config: dict
    ) -> None:
        """Initialize."""
        self.hass = hass
        self.controller_id = controller_id
        self.config = config

        self.name = config.get("name", controller_id)
        self.enabled = config.get("enabled", True)
        self.scan_interval = timedelta(
            seconds=config.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        )
        self.sensors = config.get(CONF_SENSORS, [])
        self.conditions = config.get(CONF_CONDITIONS, [])
        self.outputs = config.get(CONF_OUTPUTS, [])
        self.logging_enabled = config.get(CONF_LOGGING, False)

        self.engine = ConditionEngine(hass, self.conditions)
        self.logger = DecisionLogger(
            hass, self.name, controller_id, enabled=self.logging_enabled
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

        # Latest evaluation result per output, served to the web panel.
        self.last_results: dict[str, dict] = {}
        self.last_cycle: str | None = None

    async def async_setup(self) -> None:
        """Start polling and schedule a one-off old-log cleanup.

        The first evaluation is deferred until the platform entities have
        been registered (see ``async_entity_added``) so it does not idle.
        """
        self._remove_interval = async_track_time_interval(
            self.hass, self._async_evaluate, self.scan_interval
        )
        self.hass.async_create_task(self.logger.async_cleanup())

    def async_unload(self) -> None:
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
                record, _details = await self._async_evaluate_output(out_cfg, readings)
            except Exception:
                _LOGGER.exception(
                    "Error evaluating output '%s'", out_cfg.get("name", "<unknown>")
                )
                continue
            if not record:
                # Output entity not registered yet — nothing evaluated.
                continue
            records.append(record)

        if self.logging_enabled and records:
            await self.logger.log_cycle(records)

    async def _async_evaluate_output(
        self, out_cfg: dict, readings: dict[str, Any], detailed: bool = False
    ) -> tuple[dict, dict | None]:
        """Evaluate one output and apply its action.

        Returns ``(record, details)``; ``details`` is populated only when
        ``detailed`` is set (web trial-run) and carries per-condition results.
        """
        out_id = out_cfg.get("entity_id")
        if not out_id:
            _LOGGER.warning(
                "Output without entity_id is skipped: %r", out_cfg.get("name")
            )
            return {}, None

        entity = self._entities.get(out_id)
        if entity is None:
            return {}, None
        if getattr(entity, "entity_id", None) is None:
            # Entity object exists but has not been added to hass yet.
            return {}, None

        on_ids = out_cfg.get("on_conditions", [])
        off_ids = out_cfg.get("off_conditions", [])

        on_details: dict[str, bool] | None = None
        off_details: dict[str, bool] | None = None
        if detailed:
            on_met, on_details = await self.engine.evaluate_detailed(on_ids)
            off_met, off_details = await self.engine.evaluate_detailed(off_ids)
        else:
            on_met = await self.engine.evaluate_any(on_ids)
            off_met = await self.engine.evaluate_any(off_ids)

        decision = "hold"
        applied = False
        overridden = False
        if off_met:
            decision = "off"
            if entity.is_on:
                if await entity.async_controller_turn_off():
                    applied = True
                else:
                    overridden = True
        elif on_met:
            decision = "on"
            if not entity.is_on:
                if await entity.async_controller_turn_on():
                    applied = True
                else:
                    overridden = True

        record = {
            "output": out_cfg.get("name"),
            "decision": decision,
            "on_met": on_met,
            "off_met": off_met,
            "applied": applied,
            "override": overridden,
            "readings": readings,
        }

        self.last_results[out_id] = {
            "entity_id": entity.entity_id,
            "state": "on" if entity.is_on else "off",
            "decision": decision,
            "on_met": on_met,
            "off_met": off_met,
            "applied": applied,
            "override": overridden,
            "evaluated_at": dt_util.now().isoformat(),
        }
        self.last_cycle = dt_util.now().isoformat()

        if not detailed:
            return record, None
        return record, {
            "decision": decision,
            "on_met": on_met,
            "off_met": off_met,
            "on_conditions": on_details or {},
            "off_conditions": off_details or {},
        }

    def runtime_snapshot(self) -> dict:
        """Live view of this controller for the web panel."""
        return {
            "outputs": dict(self.last_results),
            "last_cycle": self.last_cycle,
            "scan_interval_seconds": int(self.scan_interval.total_seconds()),
        }

    async def async_evaluate_with_details(self) -> dict:
        """Run one evaluation cycle now and return per-condition results.

        Semantically identical to a polling tick (writes are applied, the
        cycle is logged); the extra detail powers the editor trial-run view.
        """
        readings = self._async_read_sensors()
        outputs: dict[str, dict] = {}
        conditions: dict[str, bool] = {}
        records: list[dict] = []
        for out_cfg in self.outputs:
            if not isinstance(out_cfg, dict):
                continue
            try:
                record, details = await self._async_evaluate_output(
                    out_cfg, readings, detailed=True
                )
            except Exception:
                _LOGGER.exception(
                    "Error evaluating output '%s'", out_cfg.get("name", "<unknown>")
                )
                continue
            if not record:
                continue
            records.append(record)
            outputs[out_cfg["entity_id"]] = details or {}
            for key in ("on_conditions", "off_conditions"):
                conditions.update((details or {}).get(key) or {})

        if self.logging_enabled and records:
            await self.logger.log_cycle(records)

        return {"readings": readings, "outputs": outputs, "conditions": conditions}

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
            record, _details = await self._async_evaluate_output(out_cfg, readings)
        except Exception:
            _LOGGER.exception(
                "Error evaluating output '%s'", out_cfg.get("name", out_id)
            )
            return
        if record and self.logging_enabled:
            await self.logger.log_cycle([record])
