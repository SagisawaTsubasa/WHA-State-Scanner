# -*- coding: utf-8 -*-
"""SensorBinarySensor behavior pins (F-333/F-340 face ②).

The stub ``BinarySensorEntity`` base is a bare class (no property
accessors), so the pins assert the ``_attr_*`` fields the real Entity base
exposes — the semantics under test live in the integration class itself:
unique-id shape (the {cid}_{out_id} contract the registry sweep relies on,
F-332), registration, and the always-accept write path (binary sensors
have no manual-override gate).
"""

from __future__ import annotations

import asyncio
import types

from custom_components.sensor_switch_controller.binary_sensor import (
    SensorBinarySensor,
)
from homeassistant.components.binary_sensor import BinarySensorEntity


async def _noop(self):
    return None


# The stub Entity base has no lifecycle hooks — the real Entity base does
# (default no-ops). Fill them so super() calls in the integration resolve;
# this mirrors the real base class, it does not fake behavior under test.
if not hasattr(BinarySensorEntity, "async_added_to_hass"):
    BinarySensorEntity.async_added_to_hass = _noop
if not hasattr(BinarySensorEntity, "async_will_remove_from_hass"):
    BinarySensorEntity.async_will_remove_from_hass = _noop

OUT_ID = "ssc_" + "a" * 8
CID = "ctrl_ab12cd34"


class _ManagerStub:
    def __init__(self):
        self.registered: dict = {}
        self.unregistered: list = []
        self.name = "ctrl-test"
        self.triggers: list = []

    def register_entity(self, out_id, entity):
        self.registered[out_id] = entity

    def unregister_entity(self, out_id):
        self.unregistered.append(out_id)


def _make_entity():
    hass = types.SimpleNamespace()
    mgr = _ManagerStub()
    ent = SensorBinarySensor(
        hass, mgr, CID, {"entity_id": OUT_ID, "name": "Out X"}
    )
    # the stub base has no async_write_ha_state; the behavior under test is
    # the _attr_ mutation + return value, not the HA state write
    ent.async_write_ha_state = lambda: None
    return ent, mgr


def test_unique_id_shape_and_registration():
    """unique_id = {controller_id}_{out_id} (F-332 sweep contract); the
    entity registers itself on the manager at construction."""
    ent, mgr = _make_entity()
    assert ent._attr_unique_id == f"{CID}_{OUT_ID}", ent._attr_unique_id
    assert ent._attr_name == "Out X"
    assert mgr.registered == {OUT_ID: ent}, mgr.registered
    assert ent._attr_is_on is False, "the read-only logic state starts off"


def test_controller_writes_always_accepted():
    """Binary sensors have no override gate: both controller writes are
    accepted (return True) and flip the state."""
    ent, _mgr = _make_entity()
    assert asyncio.run(ent.async_controller_turn_on()) is True
    assert ent._attr_is_on is True
    assert asyncio.run(ent.async_controller_turn_off()) is True
    assert ent._attr_is_on is False


def test_unregistration_and_attributes():
    """will-remove drops the manager reference; the state attributes expose
    the controller identity."""
    ent, mgr = _make_entity()
    asyncio.run(ent.async_will_remove_from_hass())
    assert mgr.unregistered == [OUT_ID], mgr.unregistered
    attrs = ent.extra_state_attributes
    assert attrs["controller_id"] == CID
    assert attrs["controller_name"] == "ctrl-test"
