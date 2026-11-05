"""Ether-S-Bus protocol implementation for SAIA PCD controllers.

This module implements Ether-S-Bus (UDP/TCP) communication.
"""

from __future__ import annotations

import asyncio
import logging

from .const import DEFAULT_TIMEOUT
from .sbus_protocol_base import SBusProtocolBase
from .sbus_protocol_base import SBusConnectionError
from .sbus_protocol_base import SBusProtocolError
from .sbus_protocol_base import SBusTimeoutError

# Upper bound for a sane Ether-S-Bus frame (largest S-Bus reply is well below)
MAX_FRAME_SIZE = 1024

_LOGGER = logging.getLogger(__name__)


class EtherSBusProtocol(SBusProtocolBase):
    """Ether-S-Bus Protocol implementation (UDP/TCP).

    Implements S-Bus communication over Ether-S-Bus using UDP or TCP transport.
    Includes sequence number management for reliable packet tracking.
    """

    def __init__(
        self,
        host: str,
        port: int,
        station: int,
        use_tcp: bool = False,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        """Initialize Ether-S-Bus protocol.

        Args:
            host: Device hostname or IP address
            port: UDP/TCP port number
            station: Station address (0-253)
            use_tcp: Use TCP instead of UDP
            timeout: Communication timeout in seconds

        """
        super().__init__(station, timeout)
        self.host = host
        self.port = port
        self.use_tcp = use_tcp
        self._transport: asyncio.DatagramTransport | asyncio.Transport | None = None
        self._protocol: _EtherSBusDatagramProtocol | None = None
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._sequence_number: int = 0
        self._max_retries: int = 3

    @property
    def endpoint_id(self) -> str:
        """Identity of the configured endpoint (host, port, station)."""
        return f"{self.host}:{self.port}:{self.station}"

    async def connect(self) -> None:
        """Establish connection to the S-Bus device via Ether-S-Bus."""
        if self.use_tcp:
            await self._connect_tcp()
        else:
            await self._connect_udp()

    async def _connect_udp(self) -> None:
        """Establish UDP connection."""
        loop = asyncio.get_running_loop()

        def protocol_factory() -> _EtherSBusDatagramProtocol:
            """Create protocol instance."""
            self._protocol = _EtherSBusDatagramProtocol()
            return self._protocol

        try:
            transport, _ = await loop.create_datagram_endpoint(
                protocol_factory,
                remote_addr=(self.host, self.port),
            )
        except OSError as err:
            msg = f"Could not open UDP socket to {self.host}:{self.port}: {err}"
            raise SBusConnectionError(msg) from err
        self._transport = transport  # type: ignore[assignment]

        _LOGGER.debug(
            "Connected to %s:%d via UDP (station %d)",
            self.host,
            self.port,
            self.station,
        )

    async def _connect_tcp(self) -> None:
        """Establish TCP connection."""
        try:
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port),
                timeout=self.timeout,
            )
        except (OSError, TimeoutError) as err:
            reason = "timed out" if isinstance(err, TimeoutError) else str(err)
            msg = (
                f"Could not connect via TCP to {self.host}:{self.port} ({reason}). "
                "Ether-S-Bus normally uses UDP"
            )
            raise SBusConnectionError(msg) from err

        _LOGGER.debug(
            "Connected to %s:%d via TCP (station %d)",
            self.host,
            self.port,
            self.station,
        )

    async def disconnect(self) -> None:
        """Close connection to the S-Bus device."""
        if self.use_tcp and self._writer:
            writer = self._writer
            self._writer = None
            self._reader = None
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                pass
        elif self._transport:
            self._transport.close()
            self._transport = None
            self._protocol = None

        _LOGGER.debug(
            "Disconnected from %s:%d (station %d)",
            self.host,
            self.port,
            self.station,
        )

    async def _send_and_receive(self, pdu: bytes, data_size: int | None) -> tuple[int, bytes]:
        """Send a PDU wrapped in an Ether-S-Bus frame and return the reply.

        Retries on timeout with exponential backoff. Every attempt uses a
        new sequence number; only a reply carrying the sequence number of
        the current request is accepted, so late answers to an earlier
        attempt are discarded.

        Raises:
            SBusTimeoutError: If communication times out after all retries

        """
        last_error: SBusTimeoutError | None = None
        for attempt in range(self._max_retries):
            sequence = self._get_next_sequence()
            frame = self.build_ether_frame(sequence, pdu)
            try:
                if self.use_tcp:
                    return await self._send_and_receive_tcp(frame, sequence)
                return await self._send_and_receive_udp(frame, sequence)
            except SBusTimeoutError as err:
                last_error = err
                if attempt < self._max_retries - 1:
                    wait_time = 0.5 * (2**attempt)
                    _LOGGER.debug(
                        "Retry %d/%d after timeout, waiting %.1fs",
                        attempt + 1,
                        self._max_retries,
                        wait_time,
                    )
                    await asyncio.sleep(wait_time)

        # Logged once per outage by the coordinator; keep this at debug level
        _LOGGER.debug(
            "No answer from %s:%d (station %d) after %d attempts",
            self.host,
            self.port,
            self.station,
            self._max_retries,
        )
        msg = (
            f"No answer from {self.host}:{self.port} (station {self.station}) "
            f"after {self._max_retries} attempts"
        )
        raise SBusTimeoutError(msg) from last_error

    def _get_next_sequence(self) -> int:
        """Get next sequence number for Ether-S-Bus packets (0-65535, wraps)."""
        self._sequence_number = (self._sequence_number + 1) % 65536
        return self._sequence_number

    async def _send_and_receive_udp(
        self, frame: bytes, sequence: int
    ) -> tuple[int, bytes]:
        """Send and receive via UDP."""
        if not self._transport or not self._protocol:
            await self._connect_udp()
        assert self._transport is not None
        assert isinstance(self._protocol, _EtherSBusDatagramProtocol)

        self._protocol.clear_response()
        _LOGGER.debug("Sending UDP frame: %s", frame.hex())
        self._transport.sendto(frame)  # type: ignore[union-attr]

        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.timeout
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                msg = f"Timeout waiting for response from {self.host}:{self.port}"
                raise SBusTimeoutError(msg)
            try:
                data = await asyncio.wait_for(
                    self._protocol.get_response(), timeout=remaining
                )
            except TimeoutError as err:
                msg = f"Timeout waiting for response from {self.host}:{self.port}"
                raise SBusTimeoutError(msg) from err

            _LOGGER.debug("Received UDP frame: %s", data.hex())
            try:
                reply_seq, attribute, payload = self.parse_ether_frame(data)
            except SBusProtocolError as err:
                _LOGGER.debug("Ignoring invalid Ether-S-Bus frame: %s", err)
                continue
            if reply_seq != sequence:
                _LOGGER.debug(
                    "Ignoring reply with sequence %d (expected %d)",
                    reply_seq,
                    sequence,
                )
                continue
            return attribute, payload

    async def _send_and_receive_tcp(
        self, frame: bytes, sequence: int
    ) -> tuple[int, bytes]:
        """Send and receive via TCP."""
        if not self._reader or not self._writer:
            await self._connect_tcp()
        assert self._reader is not None
        assert self._writer is not None

        _LOGGER.debug("Sending TCP frame: %s", frame.hex())
        try:
            self._writer.write(frame)
            await self._writer.drain()
            async with asyncio.timeout(self.timeout):
                while True:
                    length_bytes = await self._reader.readexactly(4)
                    length = int.from_bytes(length_bytes, "big")
                    if not 4 < length <= MAX_FRAME_SIZE:
                        # The rest of the stream can't be framed any more:
                        # drop the connection so the next request starts clean.
                        await self.disconnect()
                        msg = f"Invalid Ether-S-Bus frame length {length}"
                        raise SBusProtocolError(msg)
                    data = length_bytes + await self._reader.readexactly(length - 4)
                    _LOGGER.debug("Received TCP frame: %s", data.hex())
                    try:
                        reply_seq, attribute, payload = self.parse_ether_frame(data)
                    except SBusProtocolError as err:
                        # Length-delimited, so the stream is still in sync
                        _LOGGER.debug("Ignoring invalid Ether-S-Bus frame: %s", err)
                        continue
                    if reply_seq == sequence:
                        return attribute, payload
                    _LOGGER.debug(
                        "Ignoring reply with sequence %d (expected %d)",
                        reply_seq,
                        sequence,
                    )
        except (TimeoutError, OSError, asyncio.IncompleteReadError) as err:
            # The stream may be out of sync now, start over with a fresh connection
            await self.disconnect()
            msg = f"Timeout waiting for response from {self.host}:{self.port}"
            raise SBusTimeoutError(msg) from err


class _EtherSBusDatagramProtocol(asyncio.DatagramProtocol):
    """Internal protocol handler for UDP communication."""

    def __init__(self) -> None:
        """Initialize the protocol handler."""
        self._response_queue: asyncio.Queue[bytes] = asyncio.Queue()
        self._transport: asyncio.DatagramTransport | None = None

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        """Called when connection is established."""
        self._transport = transport  # type: ignore[assignment]

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        """Called when a datagram is received."""
        _LOGGER.debug("Received datagram from %s:%d: %s", addr[0], addr[1], data.hex())
        self._response_queue.put_nowait(data)

    def error_received(self, exc: Exception) -> None:
        """Called when an error is received."""
        # e.g. ICMP "port unreachable" while the PCD restarts; the request
        # then times out and is retried, so this is not worth an error entry
        _LOGGER.debug("Datagram error received: %s", exc)

    async def get_response(self) -> bytes:
        """Wait for and return the next response."""
        return await self._response_queue.get()

    def clear_response(self) -> None:
        """Clear any pending responses in the queue."""
        while not self._response_queue.empty():
            try:
                self._response_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
