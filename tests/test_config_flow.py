# -*- coding: utf-8 -*-
"""Config flow regression pins (F-333/F-340 face ①).

The integration's flow is a single-entry gate: unique-id collision =>
``_abort_if_unique_id_configured`` raises AbortFlow("already_configured"),
which the real HA flow manager converts into an abort result. The conftest
stub mirrors that raise semantics, so the tests assert the exception path
exactly (no fake abort-result shape).
"""

from __future__ import annotations

import asyncio

import pytest

from custom_components.sensor_switch_controller.config_flow import ConfigFlow
from homeassistant.data_entry_flow import AbortFlow

DOMAIN = "sensor_switch_controller"


def test_first_call_shows_form():
    """user_input=None → show the user form (no entry created)."""
    flow = ConfigFlow()
    result = asyncio.run(flow.async_step_user(None))
    assert result == {"type": "form", "step_id": "user"}, result


def test_first_entry_creates_entry():
    """Unique id not configured yet → create the single global entry."""
    flow = ConfigFlow()
    flow._configured_ids = {"some_other_domain"}
    result = asyncio.run(flow.async_step_user({}))
    assert result["type"] == "create_entry", result
    assert result["title"], result


def test_second_entry_aborts_already_configured():
    """The unique id (DOMAIN) is already configured → AbortFlow with the
    canonical "already_configured" reason (F-333 face ①)."""
    flow = ConfigFlow()
    flow._configured_ids = {DOMAIN}
    with pytest.raises(AbortFlow) as excinfo:
        asyncio.run(flow.async_step_user({}))
    assert excinfo.value.reason == "already_configured"
