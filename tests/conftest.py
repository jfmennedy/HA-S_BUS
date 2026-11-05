"""Test fixtures for SAIA S-Bus integration."""

from __future__ import annotations

from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sbus.const import DOMAIN


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """Return a mock config entry."""
    return MockConfigEntry(
        domain=DOMAIN,
        data={
            "host": "192.168.1.100",
            "port": 5050,
            "station": 0,
            "scan_interval": 30,
        },
        unique_id="12345678ABCDEF12",
        title="SAIA PCD (192.168.1.100)",
    )


@pytest.fixture
def mock_sbus_protocol():
    """Mock the S-Bus protocol class."""
    with patch("custom_components.sbus.sbus_protocol.SBusProtocol") as mock:
        protocol = mock.return_value
        protocol.connect = AsyncMock()
        protocol.disconnect = AsyncMock()
        protocol.get_device_info = AsyncMock(
            return_value={
                "firmware_version": 100,
                "product_type": "PCD1.M2120",
                "hw_version": 1,
                "serial_number": "12345678ABCDEF12",
                "identity": "12345678ABCDEF12",
            }
        )
        protocol.read_registers = AsyncMock(return_value=[0] * 10)
        protocol.read_flags = AsyncMock(return_value=[False] * 32)
        protocol.write_register = AsyncMock()
        protocol.write_flag = AsyncMock()
        yield protocol


@pytest.fixture
def mock_udp_transport():
    """Mock UDP transport for socket tests."""
    transport = MagicMock()
    transport.is_closing.return_value = False
    transport.close = MagicMock()
    return transport


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable custom integration loading in tests."""
    return enable_custom_integrations
