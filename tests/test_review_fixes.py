"""Tests for robustness fixes from code review (frames, TCP, Profi-S-Bus, identity)."""

from __future__ import annotations

import asyncio
import socket
import struct

import pytest
from homeassistant.data_entry_flow import FlowResultType

from custom_components.sbus.const import CMD_READ_FLAG
from custom_components.sbus.const import CMD_WRITE_FLAG
from custom_components.sbus.const import DOMAIN
from custom_components.sbus.ether_sbus import EtherSBusProtocol
from custom_components.sbus.profi_sbus import ProfiSBusProtocol
from custom_components.sbus.sbus_protocol_base import SBusConnectionError
from custom_components.sbus.sbus_protocol_base import SBusProtocolBase
from custom_components.sbus.sbus_protocol_base import SBusProtocolError
from custom_components.sbus.sbus_protocol_base import SBusTimeoutError

from .test_sbus_protocol import STATION
from .test_sbus_protocol import FakePCD


def _free_port() -> int:
    """Return a localhost TCP port nobody listens on."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _reply_for(pcd: FakePCD, request: bytes, sequence: int | None = None) -> bytes:
    """Build the Ether-S-Bus reply the fake PCD would send for a request."""
    seq, _attr, pdu = SBusProtocolBase.parse_ether_frame(request)
    attr, data = pcd._handle(pdu[1], pdu[2:])  # noqa: SLF001
    return SBusProtocolBase.build_ether_frame(
        seq if sequence is None else sequence, data, attr
    )


# ----------------------------------------------------------------------
# Comment 1: version / protocol type are validated
# ----------------------------------------------------------------------


@pytest.mark.parametrize("offset", [4, 5])
def test_other_version_or_type_accepted(offset: int) -> None:
    """Replies with another version/type byte are accepted (real PCDs vary)."""
    frame = bytearray(SBusProtocolBase.build_ether_frame(7, b"\x00" * 4, 0x01))
    frame[offset] = 0x7F
    body = bytes(frame[:-2])
    frame[-2:] = struct.pack("!H", SBusProtocolBase.calculate_crc(body))
    assert SBusProtocolBase.parse_ether_frame(bytes(frame)) == (7, 0x01, b"\x00" * 4)


# ----------------------------------------------------------------------
# Comments 3/4: TCP stream handling
# ----------------------------------------------------------------------


@pytest.fixture
async def tcp_pcd(socket_enabled):  # noqa: ARG001
    """Fake PCD speaking Ether-S-Bus over TCP; behaviour set per test."""
    pcd = FakePCD()
    pcd.registers[100] = 4711
    mode = {"value": "normal"}
    connections = {"count": 0}

    async def handle(reader, writer) -> None:
        connections["count"] += 1
        try:
            while True:
                length = int.from_bytes(await reader.readexactly(4), "big")
                request = length.to_bytes(4, "big") + await reader.readexactly(
                    length - 4
                )
                reply = _reply_for(pcd, request)
                if mode["value"] == "damaged_first":
                    writer.write(reply[:-2] + b"\xff\xff")
                    mode["value"] = "normal"
                elif mode["value"] == "bad_length":
                    writer.write(b"\xff\xff\xff\xff" + reply[4:])
                    mode["value"] = "normal"
                    await writer.drain()
                    continue
                writer.write(reply)
                await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    protocol = EtherSBusProtocol(
        "127.0.0.1", port, STATION, use_tcp=True, timeout=0.5
    )
    await protocol.connect()
    yield protocol, mode, connections
    await protocol.disconnect()
    server.close()


async def test_tcp_damaged_frame_skipped(tcp_pcd) -> None:
    """A CRC-damaged frame before the real reply is skipped."""
    protocol, mode, _ = tcp_pcd
    mode["value"] = "damaged_first"
    assert await protocol.read_registers(100, 1) == [4711]


async def test_tcp_invalid_length_reconnects(tcp_pcd) -> None:
    """An invalid length drops the connection; the next request works again."""
    protocol, mode, connections = tcp_pcd
    mode["value"] = "bad_length"
    with pytest.raises(SBusProtocolError, match="frame length"):
        await protocol.read_registers(100, 1)
    assert protocol._writer is None  # noqa: SLF001
    assert await protocol.read_registers(100, 1) == [4711]
    assert connections["count"] == 2


async def test_tcp_refused_is_connection_error(socket_enabled) -> None:  # noqa: ARG001
    """A refused TCP connection raises SBusConnectionError with a UDP hint."""
    protocol = EtherSBusProtocol(
        "127.0.0.1", _free_port(), STATION, use_tcp=True, timeout=1
    )
    with pytest.raises(SBusConnectionError, match="UDP"):
        await protocol.connect()


# ----------------------------------------------------------------------
# Comments 2/6: Profi-S-Bus gateway
# ----------------------------------------------------------------------


async def test_profi_stale_and_split_replies(socket_enabled) -> None:  # noqa: ARG001
    """Stale replies are skipped and split gateway frames are reassembled."""
    pcd = FakePCD()
    pcd.registers[7] = 99

    async def handle(reader, writer) -> None:
        try:
            while True:
                header = await reader.readexactly(2)
                request = await reader.readexactly(header[1])
                seq = SBusProtocolBase.parse_ether_frame(request)[0]
                stale = _reply_for(pcd, request, sequence=(seq - 1) & 0xFFFF)
                writer.write(bytes([header[0], len(stale)]) + stale)
                reply = bytes([header[0], len(stale)]) + _reply_for(pcd, request)
                writer.write(reply[:5])  # split across TCP segments
                await writer.drain()
                await asyncio.sleep(0.05)
                writer.write(reply[5:])
                await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError):
            pass

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    protocol = ProfiSBusProtocol("127.0.0.1", port, STATION, timeout=1)
    await protocol.connect()
    try:
        pcd.registers[7] = 99
        assert await protocol.read_registers(7, 1) == [99]
        pcd.registers[7] = 100
        assert await protocol.read_registers(7, 1) == [100]
    finally:
        await protocol.disconnect()
        server.close()


# ----------------------------------------------------------------------
# Comments 5/7: device information
# ----------------------------------------------------------------------


@pytest.fixture
async def udp_pcd(socket_enabled):  # noqa: ARG001
    """Fake PCD over UDP."""
    loop = asyncio.get_running_loop()
    transport, pcd = await loop.create_datagram_endpoint(
        FakePCD, local_addr=("127.0.0.1", 0)
    )
    port = transport.get_extra_info("sockname")[1]
    protocol = EtherSBusProtocol("127.0.0.1", port, STATION, timeout=0.2)
    protocol._max_retries = 1  # noqa: SLF001
    await protocol.connect()
    yield pcd, protocol, port
    await protocol.disconnect()
    transport.close()


async def test_device_info_unreachable(udp_pcd) -> None:
    """A PCD answering neither the version nor a register is unreachable."""
    pcd, protocol, _port = udp_pcd
    pcd.silent = True
    with pytest.raises(SBusTimeoutError):
        await protocol.get_device_info()


@pytest.mark.parametrize("mode", ["nak", "ignore"])
async def test_device_info_without_program_version(udp_pcd, mode: str) -> None:
    """PCDs without Read Program Version are still set up (register check)."""
    pcd, protocol, port = udp_pcd
    if mode == "nak":
        pcd.program_version = None
    else:
        pcd.ignore_program_version = True
    info = await protocol.get_device_info()
    assert info["identity"] == f"127.0.0.1:{port}:{STATION}"
    assert info["pcd_type"] is None
    assert info["firmware_version"] is None


# ----------------------------------------------------------------------
# Comment 8: chunked flag reads are atomic
# ----------------------------------------------------------------------


async def test_chunked_flag_read_is_atomic(udp_pcd) -> None:
    """A write issued during a multi-telegram flag read waits for the read."""
    pcd, protocol, _port = udp_pcd
    read = asyncio.create_task(protocol.read_flags(0, 300))
    await asyncio.sleep(0)  # read has taken the lock
    write = asyncio.create_task(protocol.write_flag(5, True))
    flags = await read
    await write
    assert flags[5] is False
    commands = [
        SBusProtocolBase.parse_ether_frame(r)[2][1] for r in pcd.requests
    ]
    assert commands == [CMD_READ_FLAG, CMD_READ_FLAG, CMD_READ_FLAG, CMD_WRITE_FLAG]


# ----------------------------------------------------------------------
# Config flow: refused TCP connection
# ----------------------------------------------------------------------


async def test_config_flow_tcp_refused(
    hass,
    enable_custom_integrations,  # noqa: ARG001
    socket_enabled,  # noqa: ARG001
) -> None:
    """A refused TCP connection shows a dedicated error suggesting UDP."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"protocol_type": "ether_sbus"}
    )
    assert result["step_id"] == "ether_sbus"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "connection_type": "tcp",
            "host": "127.0.0.1",
            "port": _free_port(),
            "station": STATION,
            "scan_interval": 30,
        },
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect_tcp"}
