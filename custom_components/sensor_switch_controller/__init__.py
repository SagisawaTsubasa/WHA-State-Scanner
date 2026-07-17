"""The Sensor Switch Controller integration."""

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall

from .const import DOMAIN, PLATFORMS
from .controller import ControllerManager

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up from a config entry."""
    manager = ControllerManager(hass, entry)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = manager
    await manager.async_setup()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_update_listener))

    if not hass.services.has_service(DOMAIN, "force_evaluate"):
        async def _handle_force_evaluate(call: ServiceCall) -> None:
            entity_id = call.data["entity_id"]
            for manager in hass.data.get(DOMAIN, {}).values():
                if not isinstance(manager, ControllerManager):
                    continue
                for entity in manager.entities.values():
                    if entity.entity_id == entity_id:
                        await manager.async_force_evaluate()
                        return
            _LOGGER.warning("force_evaluate: no controller entity %s", entity_id)

        hass.services.async_register(DOMAIN, "force_evaluate", _handle_force_evaluate)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    manager: ControllerManager = hass.data[DOMAIN].pop(entry.entry_id, None)
    if manager:
        await manager.async_unload()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update."""
    manager: ControllerManager = hass.data[DOMAIN].get(entry.entry_id)
    if manager:
        await manager.async_reload()
