"""Base S-Bus Protocol implementation for SAIA PCD controllers.

This module provides the base class and common functionality for all
S-Bus protocol variants (Serial-S-Bus, Ether-S-Bus, Profi-S-Bus).

Layering
--------
The base class builds the transport independent part of a request, the
*PDU*::

    <station> <command> <command specific payload>

Each transport wraps the PDU into its own frame (Ether-S-Bus header,
Serial-S-Bus data mode framing, ...), sends it, validates the reply frame
(CRC, sequence number, ...) and hands back the reply as ``(attribute, data)``.
The base class then interprets the reply data.
"""

from __future__ import annotations

import asyncio
import logging
import struct
from abc import ABC
from abc import abstractmethod
from collections.abc import Coroutine
from typing import Any
from typing import ClassVar
from typing import TypeVar

from homeassistant.exceptions import HomeAssistantError

from .const import ATTR_ACK
from .const import ATTR_REQUEST
from .const import ATTR_RESPONSE
from .const import CMD_READ_FLAG
from .const import CMD_READ_PROGRAM_VERSION
from .const import CMD_READ_REGISTER
from .const import CMD_WRITE_FLAG
from .const import CMD_WRITE_REGISTER
from .const import DEFAULT_TIMEOUT
from .const import ETHER_SBUS_HEADER_SIZE
from .const import ETHER_SBUS_PROTOCOL_TYPE
from .const import ETHER_SBUS_VERSION
from .const import MAX_FLAG_COUNT
from .const import MAX_REGISTER_ADDRESS
from .const import MAX_REGISTER_COUNT
from .const import MAX_REGISTER_VALUE

_LOGGER = logging.getLogger(__name__)

# Maximum number of flags per S-Bus telegram (limited by the 1 byte count field)
MAX_FLAGS_PER_TELEGRAM = 128
# Size of an ACK/NAK reply payload
ACK_DATA_SIZE = 2
# Size of the S-Bus CRC
CRC_SIZE = 2
# Length of the CPU type at the start of a "Read Program Version" reply
PCD_TYPE_LENGTH = 5
# Firmware is sent as three digits without dots ("128" = 1.28)
FIRMWARE_DIGITS = 3

_T = TypeVar("_T")


class SBusProtocolError(HomeAssistantError):
    """Base exception for S-Bus protocol errors."""


class SBusTimeoutError(SBusProtocolError):
    """Timeout during S-Bus communication."""


class SBusCRCError(SBusProtocolError):
    """CRC validation error."""


class SBusNakError(SBusProtocolError):
    """The PCD rejected the request (NAK)."""


class SBusConnectionError(SBusProtocolError):
    """The transport connection could not be established."""


def format_pcd_type(raw: str) -> str:
    """Turn the CPU type code into the familiar product prefix.

    "D3M53" -> "PCD3.M53" (a PCD3.M53xx). The code identifies the CPU
    family only, the last digits of the article number are not part of it.
    """
    if len(raw) == PCD_TYPE_LENGTH and raw[0] == "D" and raw[1].isdigit():
        return f"PCD{raw[1]}.{raw[2:]}"
    return raw


def format_firmware(raw: str) -> str:
    """Format the firmware version: "128" -> "1.28"; dotted values stay."""
    if len(raw) == FIRMWARE_DIGITS and raw.isdigit():
        return f"{raw[0]}.{raw[1:]}"
    return raw


def _build_crc_table() -> list[int]:
    """Build the CRC-16-CCITT (polynomial 0x1021) lookup table."""
    table = []
    for i in range(256):
        crc = i << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if crc & 0x8000 else (crc << 1)
        table.append(crc & 0xFFFF)
    return table


class SBusProtocolBase(ABC):
    """Base class for S-Bus Protocol implementations.

    This abstract class provides common functionality for all S-Bus
    protocol variants: Serial-S-Bus, Ether-S-Bus, and Profi-S-Bus.
    """

    # CRC-16-CCITT lookup table
    CRC16_TABLE: ClassVar[list[int]] = _build_crc_table()

    def __init__(self, station: int, timeout: float = DEFAULT_TIMEOUT) -> None:
        """Initialize the S-Bus protocol.

        Args:
            station: Station address (0-253)
            timeout: Communication timeout in seconds

        """
        self.station = station
        self.timeout = timeout
        self._lock = asyncio.Lock()

    @property
    def endpoint_id(self) -> str:
        """Stable identity of the configured endpoint.

        Used as device identity when the PCD does not provide a readable
        serial number. Transports override this with address and station.
        """
        return f"station-{self.station}"

    @abstractmethod
    async def connect(self) -> None:
        """Establish connection to the S-Bus device."""

    @abstractmethod
    async def disconnect(self) -> None:
        """Close connection to the S-Bus device."""

    @abstractmethod
    async def _send_and_receive(
        self, pdu: bytes, data_size: int | None
    ) -> tuple[int, bytes]:
        """Send a request PDU and receive the reply.

        Args:
            pdu: Request PDU (``station, command, payload``), without
                attribute byte, framing and CRC.
            data_size: Expected size of the reply data in bytes for a
                successful request, or None if it is not known in advance.
                Stream transports use it to know how much to read; an
                ACK/NAK reply is always 2 bytes.

        Returns:
            Tuple ``(attribute, data)`` of the validated reply, with framing
            and CRC already removed.

        """

    # ------------------------------------------------------------------
    # CRC
    # ------------------------------------------------------------------

    @staticmethod
    def calculate_crc(data: bytes) -> int:
        """Calculate CRC-16-CCITT checksum for S-Bus.

        Uses CRC-16-CCITT with polynomial 0x1021 and initial value 0x0000
        as specified in the S-Bus protocol documentation.
        """
        crc = 0x0000
        table = SBusProtocolBase.CRC16_TABLE
        for byte in data:
            crc = ((crc << 8) & 0xFFFF) ^ table[(crc >> 8) ^ byte]
        return crc

    # ------------------------------------------------------------------
    # Ether-S-Bus framing (also used by Profi-S-Bus)
    # ------------------------------------------------------------------

    @classmethod
    def build_ether_frame(
        cls, sequence: int, pdu: bytes, attribute: int = ATTR_REQUEST
    ) -> bytes:
        """Wrap a PDU into an Ether-S-Bus frame.

        Frame layout::

            length(4) version(1) type(1) sequence(2) attribute(1) PDU crc(2)

        ``length`` is the size of the complete frame including header and
        CRC; the CRC covers everything from the length field up to the end
        of the PDU.
        """
        length = ETHER_SBUS_HEADER_SIZE + 1 + len(pdu) + CRC_SIZE
        frame = (
            struct.pack(
                "!IBBHB",
                length,
                ETHER_SBUS_VERSION,
                ETHER_SBUS_PROTOCOL_TYPE,
                sequence & 0xFFFF,
                attribute,
            )
            + pdu
        )
        return frame + struct.pack("!H", cls.calculate_crc(frame))

    @classmethod
    def parse_ether_frame(cls, frame: bytes) -> tuple[int, int, bytes]:
        """Validate an Ether-S-Bus reply frame.

        Returns:
            Tuple ``(sequence, attribute, data)``.

        Raises:
            SBusProtocolError: If the frame is malformed.
            SBusCRCError: If the CRC does not match.

        """
        min_size = ETHER_SBUS_HEADER_SIZE + 1 + CRC_SIZE
        if len(frame) < min_size:
            msg = f"Ether-S-Bus frame too short: {len(frame)} bytes"
            raise SBusProtocolError(msg)

        length, version, ptype, sequence, attribute = struct.unpack(
            "!IBBHB", frame[: ETHER_SBUS_HEADER_SIZE + 1]
        )
        if version != ETHER_SBUS_VERSION or ptype != ETHER_SBUS_PROTOCOL_TYPE:
            # Real PCDs don't always echo the values we send, so these fields
            # are not used to reject replies; length, CRC and the sequence
            # number already identify a valid answer to our request.
            _LOGGER.debug(
                "Ether-S-Bus reply with version %02X, type %02X", version, ptype
            )
        if length != len(frame):
            msg = (
                f"Ether-S-Bus length mismatch: header says {length}, "
                f"got {len(frame)} bytes"
            )
            raise SBusProtocolError(msg)

        received_crc = struct.unpack("!H", frame[-CRC_SIZE:])[0]
        calculated_crc = cls.calculate_crc(frame[:-CRC_SIZE])
        if received_crc != calculated_crc:
            msg = f"CRC mismatch: expected {calculated_crc:04X}, got {received_crc:04X}"
            raise SBusCRCError(msg)

        return sequence, attribute, frame[ETHER_SBUS_HEADER_SIZE + 1 : -CRC_SIZE]

    # ------------------------------------------------------------------
    # Request / reply handling
    # ------------------------------------------------------------------

    def _build_pdu(self, cmd: int, payload: bytes) -> bytes:
        """Build a request PDU: ``station, command, payload``."""
        return bytes([self.station & 0xFF, cmd & 0xFF]) + payload

    async def _request_data(
        self, cmd: int, payload: bytes, data_size: int | None, *, locked: bool = False
    ) -> bytes:
        """Send a read request and return the reply data.

        ``locked=True`` means the caller already holds ``self._lock`` (used
        to keep multi-telegram reads atomic).
        """
        pdu = self._build_pdu(cmd, payload)
        if locked:
            attribute, data = await self._send_and_receive(pdu, data_size)
        else:
            async with self._lock:
                attribute, data = await self._send_and_receive(pdu, data_size)

        if attribute == ATTR_ACK:
            self._raise_for_ack(data)
            msg = "PCD answered a read request with ACK instead of data"
            raise SBusProtocolError(msg)
        if attribute != ATTR_RESPONSE:
            msg = f"Invalid attribute byte: {attribute:02X}"
            raise SBusProtocolError(msg)
        if data_size is not None and len(data) != data_size:
            msg = f"Unexpected reply size: expected {data_size} bytes, got {len(data)}"
            raise SBusProtocolError(msg)
        return data

    async def _request_ack(self, cmd: int, payload: bytes) -> None:
        """Send a write request and check the ACK."""
        pdu = self._build_pdu(cmd, payload)
        async with self._lock:
            attribute, data = await self._send_and_receive(pdu, ACK_DATA_SIZE)

        if attribute != ATTR_ACK:
            msg = f"Expected ACK, got attribute {attribute:02X}"
            raise SBusProtocolError(msg)
        self._raise_for_ack(data)

    @staticmethod
    def _raise_for_ack(data: bytes) -> None:
        """Raise SBusNakError if an ACK reply carries a NAK code."""
        if len(data) < ACK_DATA_SIZE:
            msg = f"ACK reply too short: {len(data)} bytes"
            raise SBusProtocolError(msg)
        code = struct.unpack("!H", data[:ACK_DATA_SIZE])[0]
        if code != 0:
            msg = f"PCD rejected the request (NAK code {code})"
            raise SBusNakError(msg)

    @staticmethod
    def _check_register_address(address: int) -> None:
        if not 0 <= address <= MAX_REGISTER_ADDRESS:
            msg = f"Address {address} out of range (0-{MAX_REGISTER_ADDRESS})"
            raise ValueError(msg)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def read_registers(self, address: int, count: int = 1) -> list[int]:
        """Read PCD registers.

        Request payload: ``count-1 (1 byte), address (2 bytes)``.
        Reply data: ``count`` big endian 32 bit values.
        """
        self._check_register_address(address)
        if not 1 <= count <= MAX_REGISTER_COUNT:
            msg = f"Count {count} out of range (1-{MAX_REGISTER_COUNT})"
            raise ValueError(msg)

        payload = struct.pack("!BH", count - 1, address)
        data = await self._request_data(CMD_READ_REGISTER, payload, 4 * count)
        return list(struct.unpack(f"!{count}I", data))

    async def write_register(self, address: int, value: int) -> None:
        """Write a PCD register.

        Request payload: ``byte count + 1 (1 byte), address (2 bytes),
        value (4 bytes)``.
        """
        self._check_register_address(address)
        if not 0 <= value <= MAX_REGISTER_VALUE:
            msg = f"Value {value} out of range (0-{MAX_REGISTER_VALUE})"
            raise ValueError(msg)

        payload = struct.pack("!BHI", 4 + 1, address, value)
        await self._request_ack(CMD_WRITE_REGISTER, payload)

    async def read_flags(self, address: int, count: int = 1) -> list[bool]:
        """Read PCD flags.

        Request payload: ``count-1 (1 byte), address (2 bytes)``.
        Reply data: flags packed into bytes, first flag in bit 0.
        Requests for more than 128 flags are split into several telegrams.
        """
        if not 1 <= count <= MAX_FLAG_COUNT:
            msg = f"Count {count} out of range (1-{MAX_FLAG_COUNT})"
            raise ValueError(msg)
        if address < 0 or address + count - 1 > 0xFFFF:
            msg = f"Flag address range {address}+{count} out of range"
            raise ValueError(msg)

        flags: list[bool] = []
        offset = 0
        # Hold the lock across all telegrams so no write can slip in between
        # and the result is one consistent snapshot.
        async with self._lock:
            while offset < count:
                chunk = min(MAX_FLAGS_PER_TELEGRAM, count - offset)
                payload = struct.pack("!BH", chunk - 1, address + offset)
                data = await self._request_data(
                    CMD_READ_FLAG, payload, (chunk + 7) // 8, locked=True
                )
                flags.extend(bool(data[i // 8] & (1 << (i % 8))) for i in range(chunk))
                offset += chunk
        return flags

    async def write_flag(self, address: int, value: bool) -> None:
        """Write a PCD flag.

        Request payload: ``byte count + 2 (1 byte), address (2 bytes),
        flag count - 1 (1 byte), packed flag data``.
        """
        if not 0 <= address <= 0xFFFF:
            msg = f"Flag address {address} out of range"
            raise ValueError(msg)

        payload = struct.pack("!BHBB", 1 + 2, address, 0, 1 if value else 0)
        await self._request_ack(CMD_WRITE_FLAG, payload)

    async def read_program_version(self) -> tuple[str, str]:
        """Read PCD type and firmware version ("Read Program Version").

        The PCD answers with ASCII text: the CPU type (5 characters,
        e.g. "D3M53") followed by the firmware version (e.g. "128").
        Returned formatted as ("PCD3.M53", "1.28").
        """
        data = await self._request_data(CMD_READ_PROGRAM_VERSION, b"", None)
        text = data.decode("ascii", errors="ignore")
        cpu_type = format_pcd_type(text[:PCD_TYPE_LENGTH].strip("\x00 "))
        firmware = format_firmware(text[PCD_TYPE_LENGTH:].strip("\x00 "))
        _LOGGER.debug("Program version reply %s: type %r, firmware %r", data.hex(), cpu_type, firmware)
        return cpu_type, firmware

    async def get_device_info(self) -> dict[str, Any]:
        """Identify the PCD.

        PCD type and firmware come from the "Read Program Version" command.
        If the PCD doesn't support it, a register read checks that the PCD
        answers at all; only if that fails too the PCD counts as
        unreachable. S-Bus offers no documented way to read a serial
        number, so the configured endpoint (address and station) is the
        device identity.
        """
        cpu_type = ""
        firmware = ""
        try:
            cpu_type, firmware = await self._single_attempt(self.read_program_version())
        except SBusProtocolError as err:
            _LOGGER.debug("PCD does not answer Read Program Version: %s", err)
            await self.read_registers(0, 1)  # reachable at all?

        return {
            "identity": self.endpoint_id,
            "product_type": "SAIA PCD",
            "pcd_type": cpu_type or None,
            "firmware_version": firmware or None,
        }

    async def _single_attempt(self, request: Coroutine[Any, Any, _T]) -> _T:
        """Run a request without the transport's retries (for optional data)."""
        retries = getattr(self, "_max_retries", None)
        if retries is None:
            return await request
        self._max_retries = 1
        try:
            return await request
        finally:
            self._max_retries = retries
