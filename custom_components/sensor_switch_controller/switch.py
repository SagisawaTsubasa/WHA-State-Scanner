"""Switch platform — one logic switch per controller output."""

from __future__ import annotations

import logging

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo

from .const import DOMAIN, OUTPUT_SWITCH
from .controller import ControllerManager

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities
) -> None:
    """Set up switches for every output of every enabled controller."""
    hub = hass.data[DOMAIN]
    entities = []
    for controller_id, manager in hub.managers.items():
        for out in manager.outputs:
            if (
                isinstance(out, dict)
                and out.get("type") == OUTPUT_SWITCH
                and out.get("entity_id")
            ):
                entities.append(SensorSwitch(hass, manager, controller_id, out))
    async_add_entities(entities)


class SensorSwitch(SwitchEntity):
    """Logic switch driven by controller."""

    _attr_should_poll = False
    _attr_icon = "mdi:toggle-switch"

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
        self._manual_override = out_cfg.get("manual_override", False)
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
            "manual_override": self._manual_override,
            "trigger_count": len(self._manager.triggers),
        }

    async def async_controller_turn_on(self) -> bool:
        """Called by the controller; no-op and False while override is on."""
        if self._manual_override:
            _LOGGER.debug(
                "Output %s is in manual override; controller turn_on ignored",
                self._out_id,
            )
            return False
        self._attr_is_on = True
        self.async_write_ha_state()
        return True

    async def async_controller_turn_off(self) -> bool:
        """Called by the controller; no-op and False while override is on."""
        if self._manual_override:
            _LOGGER.debug(
                "Output %s is in manual override; controller turn_off ignored",
                self._out_id,
            )
            return False
        self._attr_is_on = False
        self.async_write_ha_state()
        return True

    async def async_turn_on(self, **kwargs) -> None:
        """Manual user control — always available, even in override."""
        self._attr_is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        """Manual user control — always available, even in override."""
        self._attr_is_on = False
        self.async_write_ha_state()
