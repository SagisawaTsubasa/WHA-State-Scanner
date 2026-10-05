"""The sensor_switch_controller integration.

Single config entry hosting: the controller Store (hub), the output
platforms for all controllers, the sidebar web panel and REST API.
"""

from __future__ import annotations

import logging

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ENTITY_ID
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN, PLATFORMS
from .hub import ScannerHub
from .web import async_setup_web, async_unload_web

_LOGGER = logging.getLogger(__name__)

SERVICE_FORCE_EVALUATE = "force_evaluate"
FORCE_EVALUATE_SCHEMA = vol.Schema(
    {vol.Required(CONF_ENTITY_ID): cv.entity_id}
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up the single global entry."""
    hub = hass.data.get(DOMAIN)
    if hub is None:
        hub = ScannerHub(hass)
        hass.data[DOMAIN] = hub
        await hub.async_load()
    hub.set_entry(entry.entry_id)

    hub.build_managers()
    entry.async_on_unload(hub.teardown_managers)
    await async_setup_web(hass)
    _register_services(hass)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Accept pre-0.4.0 entries: controller data now lives in the Store.

    Old entries carry the wizard payload in data/options which the new
    runtime ignores. Tagging the first of them with the domain unique_id
    also makes the config flow's already-configured guard cover it; the
    version bump stops this hook from re-running every start.
    """
    updates: dict = {}
    if entry.unique_id is None and _domain_unique_id_free(hass):
        updates["unique_id"] = DOMAIN
    if entry.version != 2:
        updates["version"] = 2
    if updates:
        hass.config_entries.async_update_entry(entry, **updates)
    return True


@callback
def _domain_unique_id_free(hass: HomeAssistant) -> bool:
    """True when no entry already owns the DOMAIN unique_id."""
    return hass.config_entries.async_entry_for_domain_unique_id(DOMAIN, DOMAIN) is None


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry when its config changes (platform/entity rebuild)."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload the entry; the hub object survives so the API keeps answering."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hub = hass.data.get(DOMAIN)
        if hub:
            hub.teardown_managers()
        async_unload_web(hass)
    return unload_ok


def _register_services(hass: HomeAssistant) -> None:
    """Register the force_evaluate service once per HA run."""
    if hass.services.has_service(DOMAIN, SERVICE_FORCE_EVALUATE):
        return

    async def async_force_evaluate(call: ServiceCall) -> None:
        hub = hass.data.get(DOMAIN)
        if hub is None:
            _LOGGER.warning("force_evaluate called but the integration is unloaded")
            return
        entity_id = call.data[CONF_ENTITY_ID]
        manager = hub.manager_for_entity(entity_id)
        if manager is None:
            _LOGGER.warning(
                "force_evaluate: %s is not an output entity of this integration",
                entity_id,
            )
            return
        out_id = hub.output_id_for_entity(manager, entity_id)
        if out_id is None:
            return
        await manager.async_evaluate_output(out_id)

    hass.services.async_register(
        DOMAIN,
        SERVICE_FORCE_EVALUATE,
        async_force_evaluate,
        schema=FORCE_EVALUATE_SCHEMA,
    )
