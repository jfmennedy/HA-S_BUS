"""PCDs that don't answer optional system registers, and identity migration."""

from __future__ import annotations

import asyncio

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sbus.const import DOMAIN
from custom_components.sbus.sbus_protocol_base import SBusProtocolBase

from .test_sbus_protocol import STATION
from .test_sbus_protocol import FakePCD

REGISTER = {
    "address": 3187,
    "name": "Pufferspeicher Oben",
    "data_type": "signed",
    "factor": 0.1,
    "unit": "°C",
}


@pytest.fixture
async def silent_serial_pcd(socket_enabled):  # noqa: ARG001
    """Fake PCD (formerly: one that ignores the old serial number registers)."""
    loop = asyncio.get_running_loop()
    transport, pcd = await loop.create_datagram_endpoint(
        FakePCD, local_addr=("127.0.0.1", 0)
    )
    pcd.ignore_registers = {611, 612}
    pcd.registers[3187] = 329
    yield pcd, transport.get_extra_info("sockname")[1]
    transport.close()


def _entry(port: int, unique_id: str | None) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        unique_id=unique_id,
        data={
            "protocol_type": "ether_sbus",
            "connection_type": "udp",
            "host": "127.0.0.1",
            "port": port,
            "station": STATION,
            "timeout": 0.2,
        },
        options={"registers": [REGISTER], "flags": []},
    )


async def test_setup_when_serial_registers_unanswered(
    hass,
    enable_custom_integrations,  # noqa: ARG001
    silent_serial_pcd,
) -> None:
    """Setup succeeds and the endpoint becomes the identity."""
    _pcd, port = silent_serial_pcd
    entry = _entry(port, None)
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    device = dr.async_get(hass).async_get_device(
        {(DOMAIN, f"127.0.0.1:{port}:{STATION}")}
    )
    assert device is not None
    assert device.model == "D3M53"
    assert device.sw_version == "1.28"
    assert device.serial_number is None


@pytest.mark.parametrize("old_identity", ["UNKNOWN", "0000000000000002"])
async def test_migrates_from_old_identity(
    hass,
    enable_custom_integrations,  # noqa: ARG001
    silent_serial_pcd,
    old_identity: str,
) -> None:
    """Entities and device from older versions keep entity id and history."""
    _pcd, port = silent_serial_pcd
    entry = _entry(port, old_identity)
    entry.add_to_hass(hass)

    device_registry = dr.async_get(hass)
    old_device = device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, old_identity)},
        name="PCD3.M5360",
        serial_number=old_identity,
    )
    entity_registry = er.async_get(hass)
    old_entity = entity_registry.async_get_or_create(
        "sensor",
        DOMAIN,
        f"{old_identity}_register_3187",
        config_entry=entry,
        device_id=old_device.id,
        suggested_object_id="pcd3_m5360_pufferspeicher_oben",
    )
    entity_registry.async_update_entity(old_entity.entity_id, area_id="keller")

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    identity = f"127.0.0.1:{port}:{STATION}"
    assert entry.unique_id == identity

    migrated = entity_registry.async_get(old_entity.entity_id)
    assert migrated.unique_id == f"{identity}_register_3187"
    assert migrated.area_id == "keller"
    state = hass.states.get(old_entity.entity_id)
    assert float(state.state) == pytest.approx(32.9)

    devices = dr.async_entries_for_config_entry(device_registry, entry.entry_id)
    assert [d.id for d in devices] == [old_device.id]
    assert (DOMAIN, identity) in devices[0].identifiers
    assert devices[0].serial_number is None
    assert devices[0].sw_version == "1.28"


async def test_setup_with_pcd_using_other_header_values(
    hass,
    enable_custom_integrations,  # noqa: ARG001
    silent_serial_pcd,
    monkeypatch,
) -> None:
    """A PCD answering with other version/type bytes can be set up."""
    pcd, port = silent_serial_pcd
    original = SBusProtocolBase.build_ether_frame

    def pcd_frame(sequence, pdu, attribute=0):
        frame = bytearray(original(sequence, pdu, attribute))
        if attribute != 0:  # only replies from the PCD
            frame[4], frame[5] = 0x00, 0x01
            frame[-2:] = SBusProtocolBase.calculate_crc(bytes(frame[:-2])).to_bytes(
                2, "big"
            )
        return bytes(frame)

    monkeypatch.setattr(SBusProtocolBase, "build_ether_frame", staticmethod(pcd_frame))
    entry = _entry(port, None)
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
