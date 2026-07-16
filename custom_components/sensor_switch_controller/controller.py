"""Controller manager – orchestrates sensors, conditions, outputs."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_interval

from .condition_engine import ConditionEngine
from .const import (
    CONF_CONDITIONS,
    CONF_LOGGING,
    CONF_OUTPUTS,
    CONF_SCAN_INTERVAL,
    CONF_SENSORS,
    DOMAIN,
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

        self._entities: dict[str, Any] = {}
        self._remove_interval = None

    async def async_setup(self) -> None:
        """Start polling."""
        self._remove_interval = async_track_time_interval(
            self.hass, self._async_evaluate, self.scan_interval
        )
        self.hass.async_create_task(self._async_evaluate(None))

    async def async_unload(self) -> None:
        """Stop polling."""
        if self._remove_interval:
            self._remove_interval()
        await self.logger.close()

    async def async_reload(self) -> None:
        """Reload configuration after options change."""
        self.options = self.entry.options
        self.sensors = self.options.get(CONF_SENSORS, [])
        self.conditions = self.options.get(CONF_CONDITIONS, [])
        self.outputs = self.options.get(CONF_OUTPUTS, [])
        self.logging_enabled = self.options.get(CONF_LOGGING, False)

        # Rebuild engine
        self.engine = ConditionEngine(self.hass, self.conditions)

        # Rebuild logger
        await self.logger.close()
        self.logger = DecisionLogger(
            self.hass, self.name, self.entry.entry_id, enabled=self.logging_enabled
        )

        # Update scan interval
        new_interval = timedelta(
            seconds=self.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        )
        if new_interval != self.scan_interval:
            self.scan_interval = new_interval
            if self._remove_interval:
                self._remove_interval()
            self._remove_interval = async_track_time_interval(
                self.hass, self._async_evaluate, self.scan_interval
            )

        _LOGGER.info("Controller '%s' reloaded with new options", self.name)

    def register_entity(self, entity_id: str, entity) -> None:
        """Allow switch/binary_sensor to register themselves."""
        self._entities[entity_id] = entity

    @callback
    async def _async_evaluate(self, _now) -> None:
        """Evaluate all outputs."""
        readings = {}
        for sensor_cfg in self.sensors:
            eid = sensor_cfg.get("entity_id")
            state = self.hass.states.get(eid)
            readings[eid] = state.state if state else None

        for out_cfg in self.outputs:
            out_id = out_cfg.get("entity_id")
            entity = self._entities.get(out_id)
            if not entity:
                continue

            on_ids = out_cfg.get("on_conditions", [])
            off_ids = out_cfg.get("off_conditions", [])

            on_met = self.engine.evaluate_any(on_ids)
            off_met = self.engine.evaluate_any(off_ids)

            decision = None
            if off_met:
                decision = "off"
                if entity.is_on:
                    await entity.async_controller_turn_off()
            elif on_met:
                decision = "on"
                if not entity.is_on:
                    await entity.async_controller_turn_on()
            else:
                decision = "hold"

            if self.logging_enabled:
                await self.logger.log(
                    output=out_cfg.get("name"),
                    readings=readings,
                    on_met=on_met,
                    off_met=off_met,
                    decision=decision,
                )

    async def async_force_evaluate(self) -> None:
        """Public API for manual trigger."""
        await self._async_evaluate(None)
