"""The SAIA S-Bus integration."""

from __future__ import annotations

import logging
import re
import struct
from typing import TYPE_CHECKING

from homeassistant.const import CONF_HOST
from homeassistant.const import CONF_PORT
from homeassistant.const import Platform
from homeassistant.core import SupportsResponse
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.core import ServiceCall
    from homeassistant.core import ServiceResponse

from .const import ATTR_ADDRESS
from .const import ATTR_COUNT
from .const import ATTR_START_ADDRESS
from .const import ATTR_VALUE
from .const import CONF_ADDRESS
from .const import CONF_SCAN_INTERVAL
from .const import CONF_STATION
from .const import CONF_WRITABLE
from .const import DEFAULT_SCAN_INTERVAL
from .const import DEFAULT_STATION
from .const import DOMAIN
from .const import SERVICE_READ_FLAG
from .const import SERVICE_READ_REGISTER
from .const import SERVICE_WRITE_FLAG
from .const import SERVICE_WRITE_REGISTER
from .coordinator import SBusDataUpdateCoordinator
from .datapoints import get_flags
from .datapoints import get_registers
from .entity import unique_id
from .sbus_protocol import SBusProtocolError
from .sbus_protocol import create_sbus_protocol

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BINARY_SENSOR, Platform.SWITCH]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up SAIA S-Bus from a config entry."""
    scan_interval = entry.options.get(
        CONF_SCAN_INTERVAL, entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    )
    registers = get_registers(entry)
    flags = get_flags(entry)

    # Create S-Bus protocol instance using factory
    protocol = create_sbus_protocol(entry.data)

    try:
        # Connect to device
        await protocol.connect()

        # Verify connection by reading device info
        device_info = await protocol.get_device_info()

        _LOGGER.info(
            "Connected to S-Bus device: %s (S/N: %s) via %s",
            device_info.get("product_type", "Unknown"),
            device_info.get("firmware_version") or "unknown firmware",
            entry.data.get("protocol_type", "Ether-S-Bus"),
        )

    except SBusProtocolError as err:
        await protocol.disconnect()
        protocol_info = entry.data.get("protocol_type", "S-Bus")
        connection_info = entry.data.get(CONF_HOST, entry.data.get("serial_port", "device"))
        msg = f"Failed to connect to {protocol_info} device at {connection_info}: {err}"
        raise ConfigEntryNotReady(msg) from err

    # Create data update coordinator
    coordinator = SBusDataUpdateCoordinator(
        hass,
        protocol,
        int(scan_interval),
        register_addresses=[int(r[CONF_ADDRESS]) for r in registers],
        flag_addresses=[int(f[CONF_ADDRESS]) for f in flags],
    )

    # Fetch initial data
    await coordinator.async_config_entry_first_refresh()

    # Store coordinator and protocol
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "coordinator": coordinator,
        "protocol": protocol,
        "device_info": device_info,
    }

    _migrate_identity(hass, entry, device_info["identity"])

    # Register device in device registry
    device_registry = dr.async_get(hass)
    device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, device_info["identity"])},
        name=device_info.get("product_type", "SAIA PCD"),
        manufacturer="SAIA-Burgess Controls",
        model=device_info.get("pcd_type") or "SAIA PCD",
        sw_version=device_info.get("firmware_version"),
        # S-Bus provides no serial number; clear values from older versions
        serial_number=None,
    )

    _remove_stale_entities(hass, entry, device_info["identity"], registers, flags)

    # Set up platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))

    # Register services
    def _get_protocols(call: ServiceCall) -> list:
        """Return the protocol instances targeted by a service call."""
        device_ids = call.data.get("device_id") or []
        if isinstance(device_ids, str):
            device_ids = [device_ids]
        registry = dr.async_get(hass)
        entry_ids = {
            entry_id
            for device_id in device_ids
            if (device := registry.async_get(device_id))
            for entry_id in device.config_entries
        }
        protocols = [
            data["protocol"]
            for entry_id, data in hass.data[DOMAIN].items()
            if isinstance(data, dict)
            and "protocol" in data
            and (not entry_ids or entry_id in entry_ids)
        ]
        if not protocols:
            msg = "No S-Bus device found for this action"
            raise HomeAssistantError(msg)
        return protocols

    async def handle_read_register(call: ServiceCall) -> ServiceResponse:
        """Handle read_register service call."""
        start_address = int(call.data[ATTR_START_ADDRESS])
        count = int(call.data.get(ATTR_COUNT, 1))
        protocol_instance = _get_protocols(call)[0]
        try:
            values = await protocol_instance.read_registers(start_address, count)
        except SBusProtocolError as err:
            msg = f"Failed to read registers R{start_address}: {err}"
            raise HomeAssistantError(msg) from err
        _LOGGER.debug("Read registers R%d+%d: %s", start_address, count, values)
        return {
            "registers": {
                f"R{start_address + i}": {
                    "value": value,
                    "signed": value - 0x100000000 if value & 0x80000000 else value,
                    "hex": f"0x{value:08X}",
                    "float_ieee": round(struct.unpack("!f", struct.pack("!I", value))[0], 6),
                }
                for i, value in enumerate(values)
            }
        }

    async def handle_write_register(call: ServiceCall) -> None:
        """Handle write_register service call."""
        address = int(call.data[ATTR_ADDRESS])
        value = int(call.data[ATTR_VALUE])
        try:
            for protocol_instance in _get_protocols(call):
                await protocol_instance.write_register(address, value)
        except SBusProtocolError as err:
            msg = f"Failed to write register R{address}: {err}"
            raise HomeAssistantError(msg) from err

    async def handle_read_flag(call: ServiceCall) -> ServiceResponse:
        """Handle read_flag service call."""
        start_address = int(call.data[ATTR_START_ADDRESS])
        count = int(call.data.get(ATTR_COUNT, 1))
        protocol_instance = _get_protocols(call)[0]
        try:
            values = await protocol_instance.read_flags(start_address, count)
        except SBusProtocolError as err:
            msg = f"Failed to read flags F{start_address}: {err}"
            raise HomeAssistantError(msg) from err
        return {"flags": {f"F{start_address + i}": v for i, v in enumerate(values)}}

    async def handle_write_flag(call: ServiceCall) -> None:
        """Handle write_flag service call."""
        address = int(call.data[ATTR_ADDRESS])
        value = bool(call.data[ATTR_VALUE])
        try:
            for protocol_instance in _get_protocols(call):
                await protocol_instance.write_flag(address, value)
        except SBusProtocolError as err:
            msg = f"Failed to write flag F{address}: {err}"
            raise HomeAssistantError(msg) from err

    # Register services only once
    if not hass.services.has_service(DOMAIN, SERVICE_READ_REGISTER):
        hass.services.async_register(
            DOMAIN,
            SERVICE_READ_REGISTER,
            handle_read_register,
            supports_response=SupportsResponse.OPTIONAL,
        )

    if not hass.services.has_service(DOMAIN, SERVICE_WRITE_REGISTER):
        hass.services.async_register(
            DOMAIN,
            SERVICE_WRITE_REGISTER,
            handle_write_register,
        )

    if not hass.services.has_service(DOMAIN, SERVICE_READ_FLAG):
        hass.services.async_register(
            DOMAIN,
            SERVICE_READ_FLAG,
            handle_read_flag,
            supports_response=SupportsResponse.OPTIONAL,
        )

    if not hass.services.has_service(DOMAIN, SERVICE_WRITE_FLAG):
        hass.services.async_register(
            DOMAIN,
            SERVICE_WRITE_FLAG,
            handle_write_flag,
        )

    return True


_UNIQUE_ID_RE = re.compile(r"^(?P<serial>.+)_(?P<kind>register|flag_switch|flag)_(?P<address>\d+)$")


def _migrate_identity(hass: HomeAssistant, entry: ConfigEntry, serial: str) -> None:
    """Move entities, device and entry to a changed device identity.

    The identity changes e.g. from the old "UNKNOWN" placeholder to the
    endpoint based fallback, or when a serial number becomes readable.
    Updating the unique ids keeps entity ids, names, areas and history.
    """
    entity_registry = er.async_get(hass)
    for entity in er.async_entries_for_config_entry(entity_registry, entry.entry_id):
        match = _UNIQUE_ID_RE.match(entity.unique_id)
        if not match or match["serial"] == serial:
            continue
        new_unique_id = f"{serial}_{match['kind']}_{match['address']}"
        if entity_registry.async_get_entity_id(entity.domain, DOMAIN, new_unique_id):
            continue
        _LOGGER.info(
            "Migrating %s from unique id %s to %s",
            entity.entity_id,
            entity.unique_id,
            new_unique_id,
        )
        entity_registry.async_update_entity(
            entity.entity_id, new_unique_id=new_unique_id
        )

    device_registry = dr.async_get(hass)
    new_identifier = (DOMAIN, serial)
    for device in dr.async_entries_for_config_entry(device_registry, entry.entry_id):
        if new_identifier in device.identifiers:
            continue
        if device_registry.async_get_device(identifiers={new_identifier}):
            continue
        device_registry.async_update_device(
            device.id,
            new_identifiers={
                new_identifier,
                *(i for i in device.identifiers if i[0] != DOMAIN),
            },
        )

    if entry.unique_id != serial and not any(
        other.unique_id == serial
        for other in hass.config_entries.async_entries(DOMAIN)
        if other.entry_id != entry.entry_id
    ):
        hass.config_entries.async_update_entry(entry, unique_id=serial)


def _remove_stale_entities(
    hass: HomeAssistant,
    entry: ConfigEntry,
    serial: str,
    registers: list[dict],
    flags: list[dict],
) -> None:
    """Remove entities whose data point is no longer configured."""
    expected = {unique_id(serial, "register", int(r[CONF_ADDRESS])) for r in registers}
    expected |= {
        unique_id(
            serial,
            "flag_switch" if f.get(CONF_WRITABLE) else "flag",
            int(f[CONF_ADDRESS]),
        )
        for f in flags
    }
    registry = er.async_get(hass)
    for entity in er.async_entries_for_config_entry(registry, entry.entry_id):
        if entity.unique_id not in expected:
            registry.async_remove(entity.entity_id)


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry when the options (data points) change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    # Unload platforms
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        # Shutdown coordinator and disconnect protocol
        data = hass.data[DOMAIN].pop(entry.entry_id)
        coordinator = data["coordinator"]
        await coordinator.async_shutdown()

        _LOGGER.info("Disconnected from S-Bus device")

    return unload_ok
