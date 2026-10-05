"""Config flow — creates the single global entry.

Since 0.4.0 all controller editing lives in the web panel; the flow only
creates the one entry that hosts the store, platforms and panel.
"""

from __future__ import annotations

from homeassistant import config_entries

from .const import DOMAIN, ENTRY_TITLE


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the single-entry config flow."""

    VERSION = 2

    async def async_step_user(self, user_input=None):
        """Create the single global entry on confirm."""
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        if user_input is not None:
            return self.async_create_entry(title=ENTRY_TITLE, data={})
        return self.async_show_form(step_id="user")
