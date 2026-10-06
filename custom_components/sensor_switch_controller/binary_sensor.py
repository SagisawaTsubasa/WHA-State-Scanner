"""Binary sensor platform — read-only logic state per controller output."""

from __future__ import annotations

import logging

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo

from .const import DOMAIN, OUTPUT_BINARY_SENSOR
from .controller import ControllerManager

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities
) -> None:
    """Set up binary sensors for every output of every enabled controller."""
    hub = hass.data[DOMAIN]
    entities = []
    for controller_id, manager in hub.managers.items():
        for out in manager.outputs:
            if (
                isinstance(out, dict)
                and out.get("type") == OUTPUT_BINARY_SENSOR
                and out.get("entity_id")
            ):
                entities.append(SensorBinarySensor(hass, manager, controller_id, out))
    async_add_entities(entities)


class SensorBinarySensor(BinarySensorEntity):
    """Read-only logic state."""

    _attr_should_poll = False

    def __init__(
        self,
        hass: HomeAssistant,
        manager: ControllerManager,
        controller_id: str,
        out_cfg: dict,
    ) -> None:
        """Init."""
        self.hass = hass
        self._manager = manager
        self._controller_id = controller_id
        self._out_id = out_cfg["entity_id"]
        self._attr_name = out_cfg.get("name")
        self._attr_unique_id = f"{controller_id}_{out_cfg['entity_id']}"
        self._attr_is_on = False
        manager.register_entity(self._out_id, self)

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._controller_id)},
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

    @property
    def extra_state_attributes(self) -> dict:
        return {
            "controller_id": self._controller_id,
            "controller_name": self._manager.name,
            "trigger_count": len(self._manager.triggers),
        }

    async def async_controller_turn_on(self) -> bool:
        """Called by the controller; binary sensors always accept writes."""
        self._attr_is_on = True
        self.async_write_ha_state()
        return True

    async def async_controller_turn_off(self) -> bool:
        """Called by the controller; binary sensors always accept writes."""
        self._attr_is_on = False
        self.async_write_ha_state()
        return True
