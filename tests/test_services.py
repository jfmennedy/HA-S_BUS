"""Tests for the S-Bus services against a fake PCD."""

from __future__ import annotations

import asyncio
import struct

import pytest
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sbus.const import DOMAIN

from .test_sbus_protocol import STATION
from .test_sbus_protocol import FakePCD


@pytest.fixture
async def setup_pcd(hass, enable_custom_integrations, socket_enabled):  # noqa: ARG001
    """Set up the integration against a fake PCD on localhost."""
    loop = asyncio.get_running_loop()
    transport, pcd = await loop.create_datagram_endpoint(
        FakePCD, local_addr=("127.0.0.1", 0)
    )
    port = transport.get_extra_info("sockname")[1]
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "protocol_type": "ether_sbus",
            "connection_type": "udp",
            "host": "127.0.0.1",
            "port": port,
            "station": STATION,
            "scan_interval": 30,
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    device = dr.async_get(hass).async_get_device(
        {(DOMAIN, f"127.0.0.1:{port}:{STATION}")}
    )
    yield pcd, device
    await hass.config_entries.async_unload(entry.entry_id)
    transport.close()


async def test_read_register_returns_values(hass, setup_pcd) -> None:
    """read_register returns raw, signed, hex and float values."""
    pcd, device = setup_pcd
    pcd.registers[3171] = 1234
    pcd.registers[3203] = 0xFFFFFFFF
    pcd.registers[3219] = struct.unpack("!I", struct.pack("!f", 21.5))[0]

    result = {}
    for address in (3171, 3203, 3219):
        response = await hass.services.async_call(
            DOMAIN,
            "read_register",
            {"device_id": device.id, "start_address": float(address), "count": 1},
            blocking=True,
            return_response=True,
        )
        result.update(response["registers"])

    assert result["R3171"]["value"] == 1234
    assert result["R3203"]["signed"] == -1
    assert result["R3203"]["hex"] == "0xFFFFFFFF"
    assert result["R3219"]["float_ieee"] == 21.5


async def test_read_and_write_flag(hass, setup_pcd) -> None:
    """write_flag/read_flag roundtrip through the services."""
    _pcd, device = setup_pcd
    await hass.services.async_call(
        DOMAIN,
        "write_flag",
        {"device_id": device.id, "address": 5, "value": True},
        blocking=True,
    )
    response = await hass.services.async_call(
        DOMAIN,
        "read_flag",
        {"device_id": device.id, "start_address": 4, "count": 2},
        blocking=True,
        return_response=True,
    )
    assert response == {"flags": {"F4": False, "F5": True}}


async def test_read_register_error(hass, setup_pcd) -> None:
    """A timeout is reported to the user instead of only being logged."""
    pcd, device = setup_pcd
    pcd.silent = True
    protocol = next(
        d["protocol"] for d in hass.data[DOMAIN].values() if isinstance(d, dict)
    )
    protocol._max_retries = 1  # noqa: SLF001
    protocol.timeout = 0.2
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            DOMAIN,
            "read_register",
            {"device_id": device.id, "start_address": 1},
            blocking=True,
            return_response=True,
        )
