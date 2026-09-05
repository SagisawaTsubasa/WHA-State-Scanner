"""Binary sensor platform."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo

from .const import CONF_OUTPUTS, DOMAIN, OUTPUT_BINARY_SENSOR
from .controller import ControllerManager


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities
) -> None:
    """Set up binary sensors."""
    manager: ControllerManager = hass.data[DOMAIN][entry.entry_id]
    outputs = entry.options.get(CONF_OUTPUTS, [])
    entities = [
        SensorBinarySensor(hass, manager, entry, out)
        for out in outputs
        if isinstance(out, dict)
        and out.get("type") == OUTPUT_BINARY_SENSOR
        and out.get("entity_id")
    ]
    async_add_entities(entities)


class SensorBinarySensor(BinarySensorEntity):
    """Read-only logic state."""

    _attr_should_poll = False

    def __init__(self, hass, manager: ControllerManager, entry: ConfigEntry, out_cfg: dict) -> None:
        """Init."""
        self.hass = hass
        self._manager = manager
        self._out_id = out_cfg["entity_id"]
        self._attr_name = out_cfg.get("name")
        self._attr_unique_id = f"{entry.entry_id}_{out_cfg.get('entity_id')}"
        self._attr_is_on = False
        manager.register_entity(self._out_id, self)

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._manager.entry.entry_id)},
            name=self._manager.name,
            manufacturer="Sensor Switch Controller",
        )

    async def async_added_to_hass(self) -> None:
        """Notify the manager so the first evaluation can be triggered."""
        await super().async_added_to_hass()
        self._manager.async_entity_added(self._out_id)

    async def async_will_remove_from_hass(self) -> None:
        """Drop the stale entity reference from the manager."""
        await super().async_will_remove_from_hass()
        self._manager.unregister_entity(self._out_id)

    async def async_controller_turn_on(self) -> None:
        self._attr_is_on = True
        self.async_write_ha_state()

    async def async_controller_turn_off(self) -> None:
        self._attr_is_on = False
        self.async_write_ha_state()
