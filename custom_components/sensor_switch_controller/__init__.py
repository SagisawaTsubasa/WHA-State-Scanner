"""The Sensor Switch Controller integration."""

from __future__ import annotations

import logging

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN, PLATFORMS
from .controller import ControllerManager

_LOGGER = logging.getLogger(__name__)

SERVICE_FORCE_EVALUATE = "force_evaluate"

FORCE_EVALUATE_SCHEMA = vol.Schema(
    {vol.Required("entity_id"): cv.entity_id}
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up from a config entry."""
    manager = ControllerManager(hass, entry)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = manager
    await manager.async_setup()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_update_listener))

    if not hass.services.has_service(DOMAIN, SERVICE_FORCE_EVALUATE):

        async def _handle_force_evaluate(call: ServiceCall) -> None:
            target = call.data["entity_id"]
            for manager in list(hass.data.get(DOMAIN, {}).values()):
                if not isinstance(manager, ControllerManager):
                    continue
                for out_id, entity in manager.entities.items():
                    if getattr(entity, "entity_id", None) == target:
                        await manager.async_evaluate_output(out_id)
                        return
            _LOGGER.warning("force_evaluate: no controller entity %s", target)

        hass.services.async_register(
            DOMAIN,
            SERVICE_FORCE_EVALUATE,
            _handle_force_evaluate,
            schema=FORCE_EVALUATE_SCHEMA,
        )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    manager = hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    if manager:
        await manager.async_unload()
    if not hass.data.get(DOMAIN):
        hass.services.async_remove(DOMAIN, SERVICE_FORCE_EVALUATE)
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update by reloading the whole entry.

    A full reload lets the platforms create/remove output entities to match
    the new options, instead of only rebuilding the engine.
    """
    await hass.config_entries.async_reload(entry.entry_id)
