"""Profi-S-Bus protocol implementation for SAIA PCD controllers.

This module implements Profi-S-Bus communication (Profibus compatible).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging

from .const import DEFAULT_TIMEOUT
from .sbus_protocol_base import SBusProtocolBase
from .sbus_protocol_base import SBusConnectionError
from .sbus_protocol_base import SBusProtocolError
from .sbus_protocol_base import SBusTimeoutError

_LOGGER = logging.getLogger(__name__)

# Placeholder gateway header: Profibus address, telegram length
GATEWAY_HEADER_SIZE = 2


class ProfiSBusProtocol(SBusProtocolBase):
    """Profi-S-Bus Protocol implementation.

    Implements S-Bus communication over Profibus.
    Note: This requires specific Profibus hardware and drivers.
    """

    def __init__(
        self,
        host: str,
        port: int,
        station: int,
        profibus_address: int = 0,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        """Initialize Profi-S-Bus protocol.

        Args:
            host: Profibus gateway hostname or IP address
            port: Gateway port number
            station: Station address (0-253)
            profibus_address: Profibus node address
            timeout: Communication timeout in seconds

        """
        super().__init__(station, timeout)
        self.host = host
        self.port = port
        self.profibus_address = profibus_address
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._sequence_number = 0

    @property
    def endpoint_id(self) -> str:
        """Identity of the configured endpoint (gateway, Profibus address, station)."""
        return f"{self.host}:{self.port}:{self.profibus_address}:{self.station}"

    async def connect(self) -> None:
        """Establish connection to the S-Bus device via Profi-S-Bus.

        This connects to a Profibus gateway that handles the actual
        Profibus communication.
        """
        try:
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port),
                timeout=self.timeout,
            )
        except (OSError, TimeoutError) as err:
            reason = "timed out" if isinstance(err, TimeoutError) else str(err)
            msg = f"Could not connect to Profibus gateway {self.host}:{self.port} ({reason})"
            raise SBusConnectionError(msg) from err

        _LOGGER.debug(
            "Connected to Profibus gateway %s:%d (station %d, profibus addr %d)",
            self.host,
            self.port,
            self.station,
            self.profibus_address,
        )

    async def disconnect(self) -> None:
        """Close connection to the S-Bus device."""
        if self._writer:
            writer = self._writer
            self._writer = None
            self._reader = None
            writer.close()
            with contextlib.suppress(OSError):
                await writer.wait_closed()

        _LOGGER.debug(
            "Disconnected from %s:%d (station %d)",
            self.host,
            self.port,
            self.station,
        )

    async def _send_and_receive(self, pdu: bytes, data_size: int | None) -> tuple[int, bytes]:  # noqa: ARG002
        """Send a PDU via the Profibus gateway and receive the reply.

        Profi-S-Bus uses the same frame layout as Ether-S-Bus. Gateway
        frames are read completely (length prefixed), invalid frames and
        replies with a foreign sequence number are skipped.

        Raises:
            SBusTimeoutError: If communication times out

        """
        if not self._reader or not self._writer:
            await self.connect()
        assert self._reader is not None
        assert self._writer is not None

        self._sequence_number = (self._sequence_number + 1) % 65536
        sequence = self._sequence_number
        telegram = self.build_ether_frame(sequence, pdu)
        _LOGGER.debug("Sending Profibus telegram: %s", telegram.hex())

        try:
            self._writer.write(self._wrap_profibus(telegram))
            await self._writer.drain()
            async with asyncio.timeout(self.timeout):
                while True:
                    response = await self._read_gateway_frame()
                    _LOGGER.debug("Received Profibus response: %s", response.hex())
                    try:
                        reply_seq, attribute, data = self.parse_ether_frame(response)
                    except SBusProtocolError as err:
                        _LOGGER.debug("Ignoring invalid Profi-S-Bus frame: %s", err)
                        continue
                    if reply_seq == sequence:
                        return attribute, data
                    _LOGGER.debug(
                        "Ignoring reply with sequence %d (expected %d)",
                        reply_seq,
                        sequence,
                    )
        except (TimeoutError, OSError, asyncio.IncompleteReadError) as err:
            await self.disconnect()
            msg = f"Timeout waiting for response from {self.host}:{self.port}"
            raise SBusTimeoutError(msg) from err

    async def _read_gateway_frame(self) -> bytes:
        """Read one complete gateway frame and return the S-Bus telegram.

        Gateway framing (placeholder, see _wrap_profibus): address (1 byte),
        telegram length (1 byte), telegram.
        """
        assert self._reader is not None
        header = await self._reader.readexactly(GATEWAY_HEADER_SIZE)
        return await self._reader.readexactly(header[1])

    def _wrap_profibus(self, telegram: bytes) -> bytes:
        """Wrap S-Bus telegram with Profibus gateway protocol.

        Args:
            telegram: S-Bus telegram

        Returns:
            Wrapped telegram for Profibus gateway

        Note:
            This is a placeholder implementation. The actual wrapping depends
            on the specific Profibus gateway being used.
        """
        # Example header: destination address, length
        header = bytes([self.profibus_address, len(telegram)])
        return header + telegram
