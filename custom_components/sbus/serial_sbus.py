"""Serial-S-Bus protocol implementation for SAIA PCD controllers.

This module implements Serial-S-Bus communication over USB or TCP serial bridges.
"""

from __future__ import annotations

import asyncio
import logging
import struct

from .const import ATTR_ACK
from .const import ATTR_REQUEST
from .const import DEFAULT_BAUDRATE
from .const import DEFAULT_TIMEOUT
from .const import SBUS_ESCAPE_CHAR
from .const import SBUS_FRAME_START
from .sbus_protocol_base import ACK_DATA_SIZE
from .sbus_protocol_base import SBusConnectionError
from .sbus_protocol_base import SBusCRCError
from .sbus_protocol_base import SBusProtocolBase
from .sbus_protocol_base import SBusProtocolError
from .sbus_protocol_base import SBusTimeoutError

_LOGGER = logging.getLogger(__name__)


class SerialSBusProtocol(SBusProtocolBase):
    """Serial-S-Bus Protocol implementation.

    Implements S-Bus communication over serial connections (USB or TCP/IP serial bridges).
    """

    def __init__(
        self,
        port: str,
        station: int,
        baudrate: int = DEFAULT_BAUDRATE,
        use_tcp: bool = False,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        """Initialize Serial-S-Bus protocol.

        Args:
            port: Serial port path (e.g., /dev/ttyUSB0) or host:port for TCP
            station: Station address (0-253)
            baudrate: Baud rate for serial communication
            use_tcp: Use TCP/IP serial bridge instead of direct serial
            timeout: Communication timeout in seconds

        """
        super().__init__(station, timeout)
        self.port = port
        self.baudrate = baudrate
        self.use_tcp = use_tcp
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._serial = None

    @property
    def endpoint_id(self) -> str:
        """Identity of the configured endpoint (port, station)."""
        return f"{self.port}:{self.station}"

    async def connect(self) -> None:
        """Establish connection to the S-Bus device via Serial-S-Bus."""
        if self.use_tcp:
            await self._connect_tcp_serial()
        else:
            await self._connect_serial()

    async def _connect_serial(self) -> None:
        """Establish direct serial connection."""
        try:
            import serialx  # noqa: PLC0415
        except ImportError as err:
            msg = "serialx is required for serial connections"
            raise ImportError(msg) from err

        # serialx defaults to 8 data bits, no parity, 1 stop bit, which is what
        # S-Bus data mode (SM2) needs; only url and baudrate are passed so the
        # call works with every serialx release since 1.0.
        try:
            self._reader, self._writer = await serialx.open_serial_connection(
                url=self.port,
                baudrate=self.baudrate,
            )
        except (OSError, serialx.SerialException) as err:
            msg = f"Could not open serial port {self.port}: {err}"
            raise SBusConnectionError(msg) from err

        _LOGGER.debug(
            "Connected to %s at %d baud (station %d)",
            self.port,
            self.baudrate,
            self.station,
        )

    async def _connect_tcp_serial(self) -> None:
        """Establish TCP serial bridge connection."""
        # Parse host:port from port string
        if ":" in self.port:
            host, port_str = self.port.rsplit(":", 1)
            port = int(port_str)
        else:
            msg = f"Invalid TCP serial address: {self.port}. Expected format: host:port"
            raise ValueError(msg)

        try:
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(host, port), timeout=self.timeout
            )
        except (OSError, TimeoutError) as err:
            reason = "timed out" if isinstance(err, TimeoutError) else str(err)
            msg = f"Could not connect to serial bridge {self.port} ({reason})"
            raise SBusConnectionError(msg) from err

        _LOGGER.debug(
            "Connected to %s via TCP serial bridge (station %d)",
            self.port,
            self.station,
        )

    async def disconnect(self) -> None:
        """Close connection to the S-Bus device."""
        if self._writer:
            self._writer.close()
            await self._writer.wait_closed()
            self._writer = None
            self._reader = None

        _LOGGER.debug(
            "Disconnected from %s (station %d)",
            self.port,
            self.station,
        )

    @classmethod
    def build_serial_frame(cls, pdu: bytes, attribute: int = ATTR_REQUEST) -> bytes:
        """Wrap a PDU into a Serial-S-Bus data mode (SM2) frame.

        Frame layout: ``FS(0xB5) attribute PDU crc(2)``. The CRC covers the
        unstuffed frame starting with FS; everything after FS is byte
        stuffed (0xB5 -> 0xC5 0x00, 0xC5 -> 0xC5 0x01).
        """
        body = bytes([attribute]) + pdu
        crc = cls.calculate_crc(bytes([SBUS_FRAME_START]) + body)
        body += struct.pack("!H", crc)
        stuffed = bytearray([SBUS_FRAME_START])
        for byte in body:
            if byte == SBUS_FRAME_START:
                stuffed += bytes([SBUS_ESCAPE_CHAR, 0x00])
            elif byte == SBUS_ESCAPE_CHAR:
                stuffed += bytes([SBUS_ESCAPE_CHAR, 0x01])
            else:
                stuffed.append(byte)
        return bytes(stuffed)

    async def _read_unstuffed_byte(self) -> int:
        """Read one byte from the stream and resolve byte stuffing."""
        assert self._reader is not None
        byte = (await self._reader.readexactly(1))[0]
        if byte == SBUS_FRAME_START:
            msg = "Unexpected frame start inside telegram"
            raise SBusProtocolError(msg)
        if byte != SBUS_ESCAPE_CHAR:
            return byte
        escaped = (await self._reader.readexactly(1))[0]
        if escaped == 0x00:
            return SBUS_FRAME_START
        if escaped == 0x01:
            return SBUS_ESCAPE_CHAR
        msg = f"Invalid escape sequence C5 {escaped:02X}"
        raise SBusProtocolError(msg)

    async def _read_frame(self, data_size: int) -> tuple[int, bytes]:
        """Read and validate one data mode reply frame."""
        assert self._reader is not None
        # Skip everything up to the frame start
        while (await self._reader.readexactly(1))[0] != SBUS_FRAME_START:
            pass
        attribute = await self._read_unstuffed_byte()
        size = ACK_DATA_SIZE if attribute == ATTR_ACK else data_size
        body = bytearray([attribute])
        for _ in range(size + 2):
            body.append(await self._read_unstuffed_byte())

        received_crc = struct.unpack("!H", body[-2:])[0]
        calculated_crc = self.calculate_crc(bytes([SBUS_FRAME_START]) + body[:-2])
        if received_crc != calculated_crc:
            msg = f"CRC mismatch: expected {calculated_crc:04X}, got {received_crc:04X}"
            raise SBusCRCError(msg)
        return attribute, bytes(body[1:-2])

    async def _send_and_receive(
        self, pdu: bytes, data_size: int | None
    ) -> tuple[int, bytes]:
        """Send a PDU as Serial-S-Bus data mode frame and receive the reply.

        Raises:
            SBusTimeoutError: If communication times out

        """
        if not self._reader or not self._writer:
            await self.connect()
        assert self._reader is not None
        assert self._writer is not None

        if data_size is None:
            # Data mode frames carry no length; without knowing the reply
            # size the end of the reply can't be detected.
            msg = "Replies of unknown length are not supported on Serial-S-Bus"
            raise SBusProtocolError(msg)

        frame = self.build_serial_frame(pdu)
        _LOGGER.debug("Sending serial frame: %s", frame.hex())

        # Drop stale bytes from an earlier, timed out request
        buffer = getattr(self._reader, "_buffer", None)
        if isinstance(buffer, bytearray):
            buffer.clear()

        self._writer.write(frame)
        await self._writer.drain()

        try:
            async with asyncio.timeout(self.timeout):
                attribute, data = await self._read_frame(data_size)
        except (TimeoutError, asyncio.IncompleteReadError) as err:
            msg = f"Timeout waiting for response from {self.port}"
            raise SBusTimeoutError(msg) from err
        _LOGGER.debug("Received serial reply: attr=%02X data=%s", attribute, data.hex())
        return attribute, data
