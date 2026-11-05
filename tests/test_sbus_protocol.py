"""Tests for the S-Bus protocol implementation.

The Ether-S-Bus tests run against a small fake PCD that listens on a UDP
socket on localhost and answers like a real SAIA PCD.
"""

from __future__ import annotations

import asyncio
import struct

import pytest

from custom_components.sbus.const import ATTR_ACK
from custom_components.sbus.const import ATTR_RESPONSE
from custom_components.sbus.const import CMD_READ_FLAG
from custom_components.sbus.const import CMD_READ_PROGRAM_VERSION
from custom_components.sbus.const import CMD_READ_REGISTER
from custom_components.sbus.const import CMD_WRITE_FLAG
from custom_components.sbus.const import CMD_WRITE_REGISTER
from custom_components.sbus.ether_sbus import EtherSBusProtocol
from custom_components.sbus.sbus_protocol_base import SBusCRCError
from custom_components.sbus.sbus_protocol_base import SBusNakError
from custom_components.sbus.sbus_protocol_base import SBusProtocolBase
from custom_components.sbus.sbus_protocol_base import SBusTimeoutError
from custom_components.sbus.serial_sbus import SerialSBusProtocol

STATION = 10


# ----------------------------------------------------------------------
# Fake PCD
# ----------------------------------------------------------------------


class FakePCD(asyncio.DatagramProtocol):
    """Minimal Ether-S-Bus server emulating a SAIA PCD."""

    def __init__(self) -> None:
        """Initialize the fake PCD."""
        self.registers: dict[int, int] = {}
        # Reply to "Read Program Version" like digimat-saia's PCD emulation
        # (CPU type 5 chars + firmware); None = PCD doesn't know the command
        self.program_version: bytes | None = b"D3M53" + b"1.28"
        self.ignore_program_version = False
        self.flags: dict[int, bool] = {}
        self.requests: list[bytes] = []
        self.silent = False
        self.answer_with_wrong_sequence_first = False
        self.corrupt_first_answer = False
        self.nak_registers: set[int] = set()
        self.ignore_registers: set[int] = set()
        self.max_answers: int | None = None
        self.transport: asyncio.DatagramTransport | None = None

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        """Store the transport."""
        self.transport = transport  # type: ignore[assignment]

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        """Answer an Ether-S-Bus request."""
        self.requests.append(data)
        if self.silent:
            return
        if self.max_answers is not None:
            if self.max_answers <= 0:
                return
            self.max_answers -= 1
        sequence, attribute, pdu = SBusProtocolBase.parse_ether_frame(data)
        assert attribute == 0x00
        station, cmd, payload = pdu[0], pdu[1], pdu[2:]
        if station != STATION:
            return  # a real PCD ignores telegrams for other stations

        handled = self._handle(cmd, payload)
        if handled is None:
            return
        reply_attr, reply_data = handled
        frame = SBusProtocolBase.build_ether_frame(sequence, reply_data, reply_attr)
        assert self.transport is not None
        if self.answer_with_wrong_sequence_first:
            self.answer_with_wrong_sequence_first = False
            stale = SBusProtocolBase.build_ether_frame(
                (sequence - 1) & 0xFFFF, b"\x00" * len(reply_data), reply_attr
            )
            self.transport.sendto(stale, addr)
        if self.corrupt_first_answer:
            self.corrupt_first_answer = False
            self.transport.sendto(frame[:-2] + b"\xff\xff", addr)
        self.transport.sendto(frame, addr)

    def _handle(self, cmd: int, payload: bytes) -> tuple[int, bytes] | None:
        if cmd == CMD_READ_PROGRAM_VERSION:
            if self.ignore_program_version:
                return None
            if self.program_version is None:
                return ATTR_ACK, b"\x00\x01"  # NAK
            return ATTR_RESPONSE, self.program_version
        if cmd == CMD_READ_REGISTER:
            count = payload[0] + 1
            address = struct.unpack("!H", payload[1:3])[0]
            if any(address + i in self.ignore_registers for i in range(count)):
                return None  # no answer at all, like some PCDs do
            if any(address + i in self.nak_registers for i in range(count)):
                return ATTR_ACK, b"\x00\x01"
            values = [self.registers.get(address + i, 0) for i in range(count)]
            return ATTR_RESPONSE, struct.pack(f"!{count}I", *values)
        if cmd == CMD_READ_FLAG:
            count = payload[0] + 1
            address = struct.unpack("!H", payload[1:3])[0]
            data = bytearray((count + 7) // 8)
            for i in range(count):
                if self.flags.get(address + i):
                    data[i // 8] |= 1 << (i % 8)
            return ATTR_RESPONSE, bytes(data)
        if cmd == CMD_WRITE_REGISTER:
            byte_count, address = payload[0], struct.unpack("!H", payload[1:3])[0]
            assert byte_count == 5
            self.registers[address] = struct.unpack("!I", payload[3:7])[0]
            return ATTR_ACK, b"\x00\x00"
        if cmd == CMD_WRITE_FLAG:
            byte_count, address = payload[0], struct.unpack("!H", payload[1:3])[0]
            assert byte_count == 3
            assert payload[3] == 0  # flag count - 1
            self.flags[address] = bool(payload[4] & 1)
            return ATTR_ACK, b"\x00\x00"
        return ATTR_ACK, b"\x00\x01"  # NAK


@pytest.fixture
async def fake_pcd(socket_enabled):  # noqa: ARG001
    """Start a fake PCD on a random UDP port on localhost."""
    loop = asyncio.get_running_loop()
    transport, pcd = await loop.create_datagram_endpoint(
        FakePCD, local_addr=("127.0.0.1", 0)
    )
    port = transport.get_extra_info("sockname")[1]
    protocol = EtherSBusProtocol("127.0.0.1", port, STATION, timeout=0.3)
    await protocol.connect()
    yield pcd, protocol
    await protocol.disconnect()
    transport.close()


# ----------------------------------------------------------------------
# Framing
# ----------------------------------------------------------------------


def test_crc_known_value() -> None:
    """S-Bus uses CRC-16-CCITT with init 0 (aka CRC-16/XMODEM)."""
    assert SBusProtocolBase.calculate_crc(b"123456789") == 0x31C3


def test_ether_frame_read_register() -> None:
    """Read R 600 on station 0 must produce a valid Ether-S-Bus frame."""
    protocol = EtherSBusProtocol("127.0.0.1", 5050, 0)
    pdu = protocol._build_pdu(CMD_READ_REGISTER, struct.pack("!BH", 0, 600))
    frame = protocol.build_ether_frame(1, pdu)
    assert frame == bytes.fromhex("00000010 0100 0001 00 00 06 00 0258 181f")


def test_parse_ether_frame_crc_error() -> None:
    """A corrupted CRC is detected."""
    frame = SBusProtocolBase.build_ether_frame(5, b"\x00\x00\x00\x01", ATTR_RESPONSE)
    with pytest.raises(SBusCRCError):
        SBusProtocolBase.parse_ether_frame(frame[:-2] + b"\x00\x00")


def test_parse_ether_frame_roundtrip() -> None:
    """Sequence, attribute and data survive a roundtrip."""
    frame = SBusProtocolBase.build_ether_frame(0xBEEF, b"\x01\x02\x03", ATTR_ACK)
    assert SBusProtocolBase.parse_ether_frame(frame) == (
        0xBEEF,
        ATTR_ACK,
        b"\x01\x02\x03",
    )


def test_sequence_wraps() -> None:
    """Sequence numbers wrap at 16 bit."""
    protocol = EtherSBusProtocol("127.0.0.1", 5050, 0)
    protocol._sequence_number = 0xFFFF
    assert protocol._get_next_sequence() == 0


def test_serial_frame_stuffing() -> None:
    """0xB5 and 0xC5 are escaped after the frame start."""
    frame = SerialSBusProtocol.build_serial_frame(bytes([0xB5, 0xC5]))
    assert frame[0] == 0xB5
    assert frame[1:6] == bytes([0x00, 0xC5, 0x00, 0xC5, 0x01])
    assert 0xB5 not in frame[1:]


async def test_serial_read_registers() -> None:
    """Serial-S-Bus reads a stuffed reply frame correctly."""
    protocol = SerialSBusProtocol("/dev/null", STATION)
    reader = asyncio.StreamReader()
    writer = type("W", (), {"write": lambda self, d: None})()

    async def drain() -> None:
        return None

    writer.drain = drain  # type: ignore[attr-defined]
    protocol._reader, protocol._writer = reader, writer  # type: ignore[assignment]

    # Reply: value 0x000000B5 forces stuffing inside the data
    reply = SerialSBusProtocol.build_serial_frame(
        struct.pack("!I", 0xB5), ATTR_RESPONSE
    )
    # Feed the reply after the request was sent (stale input is dropped
    # before sending); leading garbage before the frame start is skipped.
    task = asyncio.create_task(protocol.read_registers(100, 1))
    await asyncio.sleep(0)
    reader.feed_data(b"\x00\x11" + reply)
    assert await task == [0xB5]


# ----------------------------------------------------------------------
# Against the fake PCD
# ----------------------------------------------------------------------


@pytest.mark.enable_socket
async def test_read_registers(fake_pcd) -> None:
    """Registers are read and decoded."""
    pcd, protocol = fake_pcd
    pcd.registers.update({100: 1, 101: 0xFFFFFFFF, 102: 42})
    assert await protocol.read_registers(100, 3) == [1, 0xFFFFFFFF, 42]

    _seq, _attr, pdu = SBusProtocolBase.parse_ether_frame(pcd.requests[-1])
    assert pdu == bytes([STATION, CMD_READ_REGISTER, 2, 0, 100])


@pytest.mark.enable_socket
async def test_write_register(fake_pcd) -> None:
    """A register write is acknowledged and applied."""
    pcd, protocol = fake_pcd
    await protocol.write_register(200, 0xDEADBEEF)
    assert pcd.registers[200] == 0xDEADBEEF


@pytest.mark.enable_socket
async def test_read_and_write_flags(fake_pcd) -> None:
    """Flags are written and read back, including more than 128 at once."""
    pcd, protocol = fake_pcd
    await protocol.write_flag(3, True)
    await protocol.write_flag(130, True)
    flags = await protocol.read_flags(0, 200)
    assert len(flags) == 200
    assert [i for i, f in enumerate(flags) if f] == [3, 130]
    await protocol.write_flag(3, False)
    assert await protocol.read_flags(3, 1) == [False]


@pytest.mark.enable_socket
async def test_get_device_info(fake_pcd) -> None:
    """PCD type and firmware come from Read Program Version."""
    pcd, protocol = fake_pcd
    info = await protocol.get_device_info()
    assert info["pcd_type"] == "D3M53"
    assert info["firmware_version"] == "1.28"
    assert info["identity"] == f"127.0.0.1:{protocol.port}:{STATION}"
    _seq, _attr, pdu = SBusProtocolBase.parse_ether_frame(pcd.requests[0])
    assert pdu == bytes([STATION, CMD_READ_PROGRAM_VERSION])


@pytest.mark.enable_socket
async def test_stale_and_corrupt_replies_ignored(fake_pcd) -> None:
    """Replies with a wrong sequence number or bad CRC are skipped."""
    pcd, protocol = fake_pcd
    pcd.registers[1] = 77
    pcd.answer_with_wrong_sequence_first = True
    pcd.corrupt_first_answer = True
    assert await protocol.read_registers(1, 1) == [77]


@pytest.mark.enable_socket
async def test_timeout_when_pcd_silent(fake_pcd) -> None:
    """No answer leads to SBusTimeoutError after all retries."""
    pcd, protocol = fake_pcd
    pcd.silent = True
    protocol._max_retries = 2
    with pytest.raises(SBusTimeoutError):
        await protocol.read_registers(0, 1)
    assert len(pcd.requests) == 2
    # each retry uses a new sequence number
    seqs = [SBusProtocolBase.parse_ether_frame(r)[0] for r in pcd.requests]
    assert seqs[0] != seqs[1]


@pytest.mark.enable_socket
async def test_get_device_info_raises_when_unreachable(fake_pcd) -> None:
    """An unreachable PCD must fail setup instead of creating an empty device."""
    pcd, protocol = fake_pcd
    pcd.silent = True
    protocol._max_retries = 1
    with pytest.raises(SBusTimeoutError):
        await protocol.get_device_info()


@pytest.mark.enable_socket
async def test_nak(fake_pcd) -> None:
    """A NAK from the PCD raises SBusNakError."""
    _pcd, protocol = fake_pcd
    with pytest.raises(SBusNakError):
        await protocol._request_ack(0x99, b"")


async def test_parameter_validation() -> None:
    """Out of range parameters are rejected before sending."""
    protocol = EtherSBusProtocol("127.0.0.1", 5050, 0)
    with pytest.raises(ValueError):
        await protocol.read_registers(100, 0)
    with pytest.raises(ValueError):
        await protocol.read_registers(100, 33)
    with pytest.raises(ValueError):
        await protocol.read_registers(10000, 1)
    with pytest.raises(ValueError):
        await protocol.write_register(100, -1)
