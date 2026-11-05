"""Tests for configuring registers and flags in the options flow."""

from __future__ import annotations

import asyncio

import pytest
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sbus.const import DOMAIN
from custom_components.sbus.datapoints import build_blocks
from custom_components.sbus.datapoints import convert_register

from .test_sbus_protocol import STATION
from .test_sbus_protocol import FakePCD



@pytest.fixture
async def pcd_entry(hass, enable_custom_integrations, socket_enabled):  # noqa: ARG001
    """Set up the integration against a fake PCD."""
    loop = asyncio.get_running_loop()
    transport, pcd = await loop.create_datagram_endpoint(
        FakePCD, local_addr=("127.0.0.1", 0)
    )
    pcd.registers[3219] = 325
    pcd.registers[3171] = 0xFFFFFFF6  # -10
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "protocol_type": "ether_sbus",
            "connection_type": "udp",
            "host": "127.0.0.1",
            "port": transport.get_extra_info("sockname")[1],
            "station": STATION,
            "scan_interval": 30,
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    yield pcd, entry
    await hass.config_entries.async_unload(entry.entry_id)
    transport.close()


async def _options(hass, entry, step: str, user_input: dict) -> dict:
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.MENU
    assert step in result["menu_options"]
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": step}
    )
    if step in ("edit_register",):
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"register": "0"}
        )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input
    )
    await hass.async_block_till_done()
    return result


def _identity(entry) -> str:
    return f"127.0.0.1:{entry.data['port']}:{STATION}"


def _entity_id(hass, domain: str, unique: str) -> str | None:
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    return er.async_get(hass).async_get_entity_id(
        domain, DOMAIN, f"{_identity(entry)}_{unique}"
    )


async def test_legacy_entities_without_configuration(hass, pcd_entry) -> None:
    """Without configuration the old default entities exist."""
    _pcd, entry = pcd_entry
    entities = er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    assert len(entities) == 10 + 32 + 8


async def test_add_temperature_register(hass, pcd_entry) -> None:
    """Adding R 3219 creates a temperature sensor and removes legacy entities."""
    _pcd, entry = pcd_entry
    result = await _options(
        hass,
        entry,
        "add_register",
        {
            "address": 3219.0,
            "name": "Vorlauf",
            "data_type": "signed",
            "factor": 0.1,
            "unit": "°C",
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY

    entity_id = _entity_id(hass, "sensor", "register_3219")
    state = hass.states.get(entity_id)
    assert float(state.state) == pytest.approx(32.5)
    assert state.attributes["unit_of_measurement"] == "°C"
    assert state.attributes["device_class"] == "temperature"
    assert state.attributes["raw_value"] == 325

    entities = er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    assert [e.unique_id for e in entities] == [f"{_identity(entry)}_register_3219"]

    # Duplicate address is rejected
    result = await _options(
        hass,
        entry,
        "add_register",
        {"address": 3219, "name": "x", "data_type": "signed", "factor": 1},
    )
    assert result["errors"] == {"address": "address_exists"}


async def test_edit_and_remove_register(hass, pcd_entry) -> None:
    """A register can be edited and removed again."""
    _pcd, entry = pcd_entry
    await _options(
        hass,
        entry,
        "add_register",
        {"address": 3171, "name": "Wert", "data_type": "unsigned", "factor": 1},
    )
    await _options(
        hass,
        entry,
        "edit_register",
        {"address": 3171, "name": "Wert", "data_type": "signed", "factor": 1},
    )
    assert hass.states.get(_entity_id(hass, "sensor", "register_3171")).state == "-10"

    await _options(hass, entry, "remove_registers", {"registers": ["0"]})
    assert _entity_id(hass, "sensor", "register_3171") is None


async def test_flag_switch(hass, pcd_entry) -> None:
    """A writable flag becomes a switch that writes to the PCD."""
    pcd, entry = pcd_entry
    await _options(
        hass, entry, "add_flag", {"address": 42, "name": "Pumpe", "writable": True}
    )
    await _options(
        hass, entry, "add_flag", {"address": 43, "name": "Störung", "writable": False}
    )
    switch_id = _entity_id(hass, "switch", "flag_switch_42")
    assert hass.states.get(switch_id).state == "off"
    assert hass.states.get(_entity_id(hass, "binary_sensor", "flag_43")).state == "off"

    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": switch_id}, blocking=True
    )
    await hass.async_block_till_done()
    assert pcd.flags[42] is True
    assert hass.states.get(switch_id).state == "on"


async def test_scan_interval_setting(hass, pcd_entry) -> None:
    """Changing the scan interval keeps configured data points."""
    _pcd, entry = pcd_entry
    await _options(hass, entry, "settings", {"scan_interval": 60})
    assert entry.options["scan_interval"] == 60
    assert "registers" not in entry.options  # still legacy mode


def test_build_blocks() -> None:
    """Close addresses share a telegram, distant ones do not."""
    assert build_blocks([3219, 3171, 3203], 32, 4) == [(3171, 1), (3203, 1), (3219, 1)]
    assert build_blocks([10, 12, 13], 32, 4) == [(10, 4)]
    assert build_blocks(range(40), 32, 4) == [(0, 32), (32, 8)]


def test_convert_register() -> None:
    """Raw register values are converted by data type and factor."""
    assert convert_register(325, "signed", 0.1) == pytest.approx(32.5)
    assert convert_register(0xFFFFFFF6, "signed", 1) == -10
    assert convert_register(0x41AC0000, "float", 1) == pytest.approx(21.5)
