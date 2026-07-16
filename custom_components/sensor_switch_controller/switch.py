"""Switch platform."""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo

from .const import CONF_OUTPUTS, DOMAIN, OUTPUT_SWITCH
from .controller import ControllerManager


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities
) -> None:
    """Set up switches."""
    manager: ControllerManager = hass.data[DOMAIN][entry.entry_id]
    outputs = entry.options.get(CONF_OUTPUTS, [])
    entities = []
    for out in outputs:
        if out.get("type") == OUTPUT_SWITCH:
            entities.append(SensorSwitch(hass, manager, entry, out))
    async_add_entities(entities)


class SensorSwitch(SwitchEntity):
    """Logic switch driven by controller."""

    _attr_should_poll = False
    _attr_icon = "mdi:toggle-switch"

    def __init__(self, hass, manager: ControllerManager, entry: ConfigEntry, out_cfg: dict) -> None:
        """Init."""
        self.hass = hass
        self._manager = manager
        self._config = out_cfg
        self._attr_name = out_cfg.get("name")
        self._attr_unique_id = f"{entry.entry_id}_{out_cfg.get('entity_id')}"
        self._attr_is_on = False
        self._manual_override = out_cfg.get("manual_override", False)
        self._controller_lock = False
        manager.register_entity(self._attr_unique_id, self)

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._manager.entry.entry_id)},
            name=self._manager.name,
            manufacturer="Sensor Switch Controller",
        )

    @property
    def extra_state_attributes(self) -> dict:
        return {
            "manual_override": self._manual_override,
            "scan_interval_seconds": int(self._manager.scan_interval.total_seconds()),
        }

    async def async_controller_turn_on(self) -> None:
        if self._manual_override and self._attr_is_on:
            return
        self._controller_lock = True
        self._attr_is_on = True
        self.async_write_ha_state()
        self._controller_lock = False

    async def async_controller_turn_off(self) -> None:
        if self._manual_override and not self._attr_is_on:
            return
        self._controller_lock = True
        self._attr_is_on = False
        self.async_write_ha_state()
        self._controller_lock = False

    async def async_turn_on(self, **kwargs) -> None:
        self._attr_is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        self._attr_is_on = False
        self.async_write_ha_state()
