"""Config flow for SAIA S-Bus integration."""

from __future__ import annotations

import io
import logging
import zipfile
from typing import TYPE_CHECKING
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant import data_entry_flow
from homeassistant.components.file_upload import process_uploaded_file
from homeassistant.const import CONF_HOST
from homeassistant.const import CONF_PORT
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import selector

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.data_entry_flow import FlowResult

from .const import BAUDRATES
from .const import CONF_ADDRESS
from .const import CONF_DATA_TYPE
from .const import CONF_FACTOR
from .const import CONF_FLAGS
from .const import CONF_NAME
from .const import CONF_MAX
from .const import CONF_MIN
from .const import CONF_REGISTERS
from .const import CONF_SYMBOL
from .const import CONF_UNIT
from .const import CONF_WRITABLE
from .const import DATA_TYPE_SIGNED
from .const import DATA_TYPES
from .const import MAX_REGISTER_ADDRESS
from .const import UNITS
from .datapoints import is_configured
from .pg5 import KIND_FLAG
from .pg5 import KIND_REGISTER
from .pg5 import OPERATING_LEVELS
from .pg5 import DataPoint
from .pg5 import PG5ParseError
from .pg5 import decode
from .pg5 import merge_libraries
from .pg5 import parse_project
from .project import apply_selection
from .project import async_load_project
from .project import async_save_project
from .project import migrate_entity_addresses
from .project import plant_parts
from .project import remap_to_project
from .const import CONF_BAUDRATE
from .const import CONF_CONNECTION_TYPE
from .const import CONF_PROTOCOL_TYPE
from .const import CONF_SCAN_INTERVAL
from .const import CONF_SERIAL_PORT
from .const import CONF_STATION
from .const import CONNECTION_TYPE_TCP
from .const import CONNECTION_TYPE_TCP_SERIAL
from .const import CONNECTION_TYPE_UDP
from .const import CONNECTION_TYPE_USB
from .const import DEFAULT_BAUDRATE
from .const import DEFAULT_PORT_TCP
from .const import DEFAULT_PORT_UDP
from .const import DEFAULT_SCAN_INTERVAL
from .const import DEFAULT_STATION
from .const import DOMAIN
from .const import ERROR_CANNOT_CONNECT
from .const import ERROR_CANNOT_CONNECT_TCP
from .const import ERROR_SERIAL_PORT_NOT_FOUND
from .const import ERROR_TIMEOUT
from .const import ERROR_UNKNOWN
from .const import PROTOCOL_ETHER_SBUS
from .const import PROTOCOL_PROFI_SBUS
from .const import PROTOCOL_SERIAL_SBUS
from .sbus_protocol import SBusConnectionError
from .sbus_protocol import SBusProtocolError
from .sbus_protocol import SBusTimeoutError
from .sbus_protocol import create_sbus_protocol

_LOGGER = logging.getLogger(__name__)


async def validate_connection(
    hass: HomeAssistant,
    config: dict[str, Any],
) -> dict[str, Any]:
    """Validate the connection to the S-Bus device.

    Args:
        hass: Home Assistant instance
        config: Configuration dictionary

    Returns:
        Dictionary with device information

    Raises:
        SBusTimeoutError: If connection times out
        SBusProtocolError: For other protocol errors

    """
    protocol = create_sbus_protocol(config)

    try:
        await protocol.connect()
        return await protocol.get_device_info()
    finally:
        await protocol.disconnect()


class SBusConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for SAIA S-Bus."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._protocol_type: str | None = None
        self._connection_type: str | None = None
        self._config_data: dict[str, Any] = {}

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Handle the initial step - protocol selection."""
        if user_input is not None:
            self._protocol_type = user_input[CONF_PROTOCOL_TYPE]
            self._config_data[CONF_PROTOCOL_TYPE] = self._protocol_type

            # Route to appropriate configuration step
            if self._protocol_type == PROTOCOL_ETHER_SBUS:
                return await self.async_step_ether_sbus()
            if self._protocol_type == PROTOCOL_SERIAL_SBUS:
                return await self.async_step_serial_sbus()
            if self._protocol_type == PROTOCOL_PROFI_SBUS:
                return await self.async_step_profi_sbus()

        data_schema = vol.Schema(
            {
                vol.Required(CONF_PROTOCOL_TYPE, default=PROTOCOL_ETHER_SBUS): vol.In(
                    {
                        PROTOCOL_ETHER_SBUS: "Ether-S-Bus (UDP/TCP)",
                        PROTOCOL_SERIAL_SBUS: "Serial-S-Bus (USB/TCP Serial)",
                        PROTOCOL_PROFI_SBUS: "Profi-S-Bus (Profibus)",
                    }
                ),
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
        )

    async def async_step_ether_sbus(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Handle Ether-S-Bus configuration."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._config_data.update(user_input)

            try:
                device_info = await validate_connection(
                    self.hass,
                    self._config_data,
                )

                await self.async_set_unique_id(device_info["identity"])
                self._abort_if_unique_id_configured()

                host = user_input[CONF_HOST]
                title = f"{device_info.get('product_type', 'SAIA PCD')} ({host})"

                return self.async_create_entry(
                    title=title,
                    data=self._config_data,
                )

            except data_entry_flow.AbortFlow:
                raise
            except SBusConnectionError:
                _LOGGER.warning("Could not connect to S-Bus device", exc_info=True)
                errors["base"] = (
                    ERROR_CANNOT_CONNECT_TCP
                    if user_input.get(CONF_CONNECTION_TYPE) == CONNECTION_TYPE_TCP
                    else ERROR_CANNOT_CONNECT
                )
            except SBusTimeoutError:
                _LOGGER.exception("Timeout connecting to S-Bus device")
                errors["base"] = ERROR_TIMEOUT
            except SBusProtocolError:
                _LOGGER.exception("Error connecting to S-Bus device")
                errors["base"] = ERROR_CANNOT_CONNECT
            except Exception:
                _LOGGER.exception("Unexpected error during S-Bus setup")
                errors["base"] = ERROR_UNKNOWN

        data_schema = vol.Schema(
            {
                vol.Required(CONF_CONNECTION_TYPE, default=CONNECTION_TYPE_UDP): vol.In(
                    {
                        CONNECTION_TYPE_UDP: "UDP",
                        CONNECTION_TYPE_TCP: "TCP",
                    }
                ),
                vol.Required(CONF_HOST): str,
                vol.Required(CONF_PORT, default=DEFAULT_PORT_UDP): cv.port,
                vol.Required(CONF_STATION, default=DEFAULT_STATION): vol.All(
                    vol.Coerce(int),
                    vol.Range(min=0, max=253),
                ),
                vol.Optional(
                    CONF_SCAN_INTERVAL,
                    default=DEFAULT_SCAN_INTERVAL,
                ): vol.All(
                    vol.Coerce(int),
                    vol.Range(min=5, max=3600),
                ),
            }
        )

        return self.async_show_form(
            step_id="ether_sbus",
            data_schema=data_schema,
            errors=errors,
            description_placeholders={
                "protocol_type": "Ether-S-Bus",
            },
        )

    async def async_step_serial_sbus(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Handle Serial-S-Bus configuration."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._config_data.update(user_input)

            try:
                device_info = await validate_connection(
                    self.hass,
                    self._config_data,
                )

                await self.async_set_unique_id(device_info["identity"])
                self._abort_if_unique_id_configured()

                serial_port = user_input[CONF_SERIAL_PORT]
                title = f"{device_info.get('product_type', 'SAIA PCD')} ({serial_port})"

                return self.async_create_entry(
                    title=title,
                    data=self._config_data,
                )

            except data_entry_flow.AbortFlow:
                raise
            except SBusConnectionError:
                _LOGGER.warning("Could not connect to S-Bus device", exc_info=True)
                errors["base"] = ERROR_CANNOT_CONNECT
            except SBusTimeoutError:
                _LOGGER.exception("Timeout connecting to S-Bus device")
                errors["base"] = ERROR_TIMEOUT
            except SBusProtocolError:
                _LOGGER.exception("Error connecting to S-Bus device")
                errors["base"] = ERROR_CANNOT_CONNECT
            except FileNotFoundError:
                _LOGGER.exception("Serial port not found")
                errors["base"] = ERROR_SERIAL_PORT_NOT_FOUND
            except Exception:
                _LOGGER.exception("Unexpected error during S-Bus setup")
                errors["base"] = ERROR_UNKNOWN

        data_schema = vol.Schema(
            {
                vol.Required(
                    CONF_CONNECTION_TYPE, default=CONNECTION_TYPE_USB
                ): vol.In(
                    {
                        CONNECTION_TYPE_USB: "USB/Serial",
                        CONNECTION_TYPE_TCP_SERIAL: "TCP Serial Bridge",
                    }
                ),
                vol.Required(CONF_SERIAL_PORT): str,
                vol.Required(CONF_BAUDRATE, default=DEFAULT_BAUDRATE): vol.In(
                    {rate: str(rate) for rate in BAUDRATES}
                ),
                vol.Required(CONF_STATION, default=DEFAULT_STATION): vol.All(
                    vol.Coerce(int),
                    vol.Range(min=0, max=253),
                ),
                vol.Optional(
                    CONF_SCAN_INTERVAL,
                    default=DEFAULT_SCAN_INTERVAL,
                ): vol.All(
                    vol.Coerce(int),
                    vol.Range(min=5, max=3600),
                ),
            }
        )

        return self.async_show_form(
            step_id="serial_sbus",
            data_schema=data_schema,
            errors=errors,
            description_placeholders={
                "protocol_type": "Serial-S-Bus",
                "serial_port_example": "/dev/ttyUSB0 or 192.168.1.100:5050",
            },
        )

    async def async_step_profi_sbus(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Handle Profi-S-Bus configuration."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._config_data.update(user_input)

            try:
                device_info = await validate_connection(
                    self.hass,
                    self._config_data,
                )

                await self.async_set_unique_id(device_info["identity"])
                self._abort_if_unique_id_configured()

                host = user_input[CONF_HOST]
                title = f"{device_info.get('product_type', 'SAIA PCD')} (Profibus @ {host})"

                return self.async_create_entry(
                    title=title,
                    data=self._config_data,
                )

            except data_entry_flow.AbortFlow:
                raise
            except SBusConnectionError:
                _LOGGER.warning("Could not connect to S-Bus device", exc_info=True)
                errors["base"] = ERROR_CANNOT_CONNECT
            except SBusTimeoutError:
                _LOGGER.exception("Timeout connecting to S-Bus device")
                errors["base"] = ERROR_TIMEOUT
            except SBusProtocolError:
                _LOGGER.exception("Error connecting to S-Bus device")
                errors["base"] = ERROR_CANNOT_CONNECT
            except Exception:
                _LOGGER.exception("Unexpected error during S-Bus setup")
                errors["base"] = ERROR_UNKNOWN

        data_schema = vol.Schema(
            {
                vol.Required(CONF_HOST): str,
                vol.Required(CONF_PORT, default=DEFAULT_PORT_TCP): cv.port,
                vol.Required(CONF_STATION, default=DEFAULT_STATION): vol.All(
                    vol.Coerce(int),
                    vol.Range(min=0, max=253),
                ),
                vol.Optional(
                    "profibus_address",
                    default=0,
                ): vol.All(
                    vol.Coerce(int),
                    vol.Range(min=0, max=126),
                ),
                vol.Optional(
                    CONF_SCAN_INTERVAL,
                    default=DEFAULT_SCAN_INTERVAL,
                ): vol.All(
                    vol.Coerce(int),
                    vol.Range(min=5, max=3600),
                ),
            }
        )

        return self.async_show_form(
            step_id="profi_sbus",
            data_schema=data_schema,
            errors=errors,
            description_placeholders={
                "protocol_type": "Profi-S-Bus",
            },
        )

    async def async_step_zeroconf(
        self,
        discovery_info: dict[str, Any],
    ) -> FlowResult:
        """Handle zeroconf discovery of SAIA PCD devices.

        Args:
            discovery_info: Discovery information from zeroconf

        Returns:
            Flow result

        """
        _LOGGER.debug("Zeroconf discovery: %s", discovery_info)

        # Extract host and port from discovery info
        host = discovery_info.get("host")
        port = discovery_info.get("port", DEFAULT_PORT_UDP)
        name = discovery_info.get("name", "")

        if not host:
            return self.async_abort(reason="cannot_connect")

        # Set protocol type to Ether-S-Bus for network discovery
        self._protocol_type = PROTOCOL_ETHER_SBUS
        self._config_data[CONF_PROTOCOL_TYPE] = PROTOCOL_ETHER_SBUS
        self._config_data[CONF_CONNECTION_TYPE] = CONNECTION_TYPE_UDP
        self._config_data[CONF_HOST] = host
        self._config_data[CONF_PORT] = port
        self._config_data[CONF_STATION] = DEFAULT_STATION
        self._config_data[CONF_SCAN_INTERVAL] = DEFAULT_SCAN_INTERVAL

        # Try to get device info for unique ID
        try:
            device_info = await validate_connection(self.hass, self._config_data)
            await self.async_set_unique_id(device_info["identity"])
            self._abort_if_unique_id_configured(
                updates={
                    CONF_HOST: host,
                    CONF_PORT: port,
                }
            )

            # Show confirmation dialog
            self.context["title_placeholders"] = {
                "name": device_info.get("product_type", name or "SAIA PCD"),
                "host": host,
            }
            return await self.async_step_discovery_confirm()

        except Exception as err:
            _LOGGER.debug("Discovery validation failed: %s", err)
            return self.async_abort(reason="cannot_connect")

    async def async_step_ssdp(
        self,
        discovery_info: dict[str, Any],
    ) -> FlowResult:
        """Handle SSDP discovery of SAIA PCD devices.

        Args:
            discovery_info: Discovery information from SSDP

        Returns:
            Flow result

        """
        _LOGGER.debug("SSDP discovery: %s", discovery_info)

        # Extract host from SSDP location URL
        location = discovery_info.get("ssdp_location", "")
        if not location:
            return self.async_abort(reason="cannot_connect")

        # Parse host from URL (e.g., http://192.168.1.100:8080/...)
        try:
            from urllib.parse import urlparse

            parsed = urlparse(location)
            host = parsed.hostname
            if not host:
                return self.async_abort(reason="cannot_connect")
        except Exception as err:
            _LOGGER.error("Failed to parse SSDP location: %s", err)
            return self.async_abort(reason="cannot_connect")

        # Similar to zeroconf discovery
        self._protocol_type = PROTOCOL_ETHER_SBUS
        self._config_data[CONF_PROTOCOL_TYPE] = PROTOCOL_ETHER_SBUS
        self._config_data[CONF_CONNECTION_TYPE] = CONNECTION_TYPE_UDP
        self._config_data[CONF_HOST] = host
        self._config_data[CONF_PORT] = DEFAULT_PORT_UDP
        self._config_data[CONF_STATION] = DEFAULT_STATION
        self._config_data[CONF_SCAN_INTERVAL] = DEFAULT_SCAN_INTERVAL

        try:
            device_info = await validate_connection(self.hass, self._config_data)
            await self.async_set_unique_id(device_info["identity"])
            self._abort_if_unique_id_configured(
                updates={
                    CONF_HOST: host,
                }
            )

            self.context["title_placeholders"] = {
                "name": device_info.get("product_type", "SAIA PCD"),
                "host": host,
            }
            return await self.async_step_discovery_confirm()

        except Exception as err:
            _LOGGER.debug("SSDP validation failed: %s", err)
            return self.async_abort(reason="cannot_connect")

    async def async_step_discovery_confirm(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Confirm discovery and create entry.

        Args:
            user_input: User input from confirmation dialog

        Returns:
            Flow result

        """
        if user_input is not None:
            # User confirmed, create the entry
            title = self.context["title_placeholders"]["name"]
            return self.async_create_entry(
                title=title,
                data=self._config_data,
            )

        # Show confirmation form
        return self.async_show_form(
            step_id="discovery_confirm",
            description_placeholders=self.context.get("title_placeholders", {}),
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Get the options flow for this handler."""
        return SBusOptionsFlow()


class SBusOptionsFlow(config_entries.OptionsFlow):
    """Options: scan interval and the registers/flags to create entities for."""

    def __init__(self) -> None:
        """Initialize the options flow."""
        self._edit_index: int | None = None
        self._project: dict[str, Any] | None = None
        self._import: dict[str, Any] | None = None
        self._group: str | None = None
        self._with_parameters = False

    # -- helpers -------------------------------------------------------

    @property
    def _registers(self) -> list[dict[str, Any]]:
        if not is_configured(self.config_entry):
            return []
        return list(self.config_entry.options.get(CONF_REGISTERS, []))

    @property
    def _flags(self) -> list[dict[str, Any]]:
        if not is_configured(self.config_entry):
            return []
        return list(self.config_entry.options.get(CONF_FLAGS, []))

    def _save(
        self,
        registers: list[dict[str, Any]] | None = None,
        flags: list[dict[str, Any]] | None = None,
        **extra: Any,
    ) -> FlowResult:
        options = dict(self.config_entry.options)
        options[CONF_REGISTERS] = sorted(
            self._registers if registers is None else registers,
            key=lambda r: r[CONF_ADDRESS],
        )
        options[CONF_FLAGS] = sorted(
            self._flags if flags is None else flags, key=lambda f: f[CONF_ADDRESS]
        )
        options.update(extra)
        return self.async_create_entry(title="", data=options)

    @staticmethod
    def _register_label(reg: dict[str, Any]) -> str:
        unit = f" [{reg[CONF_UNIT]}]" if reg.get(CONF_UNIT) else ""
        return f"R {reg[CONF_ADDRESS]} – {reg[CONF_NAME]}{unit}"

    @staticmethod
    def _flag_label(flag: dict[str, Any]) -> str:
        kind = "switch" if flag.get(CONF_WRITABLE) else "binary_sensor"
        return f"F {flag[CONF_ADDRESS]} – {flag[CONF_NAME]} ({kind})"

    @staticmethod
    def _register_schema(defaults: dict[str, Any]) -> vol.Schema:
        return vol.Schema(
            {
                vol.Required(
                    CONF_ADDRESS, default=defaults.get(CONF_ADDRESS, vol.UNDEFINED)
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0,
                        max=MAX_REGISTER_ADDRESS,
                        step=1,
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(
                    CONF_NAME, default=defaults.get(CONF_NAME, vol.UNDEFINED)
                ): selector.TextSelector(),
                vol.Required(
                    CONF_DATA_TYPE, default=defaults.get(CONF_DATA_TYPE, DATA_TYPE_SIGNED)
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=DATA_TYPES,
                        translation_key=CONF_DATA_TYPE,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Required(
                    CONF_FACTOR, default=defaults.get(CONF_FACTOR, 1.0)
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        step="any", mode=selector.NumberSelectorMode.BOX
                    )
                ),
                vol.Optional(
                    CONF_UNIT,
                    description={"suggested_value": defaults.get(CONF_UNIT)},
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=UNITS,
                        custom_value=True,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Required(
                    CONF_WRITABLE, default=bool(defaults.get(CONF_WRITABLE, False))
                ): selector.BooleanSelector(),
            }
        )

    @staticmethod
    def _clean_register(
        user_input: dict[str, Any], current: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Build a register entry; keeps project data (symbol, range) on edit."""
        register = {
            CONF_ADDRESS: int(user_input[CONF_ADDRESS]),
            CONF_NAME: str(user_input[CONF_NAME]).strip(),
            CONF_DATA_TYPE: user_input[CONF_DATA_TYPE],
            CONF_FACTOR: float(user_input[CONF_FACTOR]) or 1.0,
            CONF_UNIT: (user_input.get(CONF_UNIT) or "").strip() or None,
            CONF_WRITABLE: bool(user_input.get(CONF_WRITABLE, False)),
        }
        if current and current.get(CONF_ADDRESS) == register[CONF_ADDRESS]:
            for key in (CONF_SYMBOL, CONF_MIN, CONF_MAX):
                if current.get(key) is not None:
                    register[key] = current[key]
        return register

    # -- steps ---------------------------------------------------------

    async def async_step_init(
        self,
        user_input: dict[str, Any] | None = None,  # noqa: ARG002
    ) -> FlowResult:
        """Show the options menu."""
        self._project = await async_load_project(self.hass, self.config_entry.entry_id)
        menu = ["settings", "import_project"]
        if self._project:
            menu.append("select_group")
        menu.append("add_register")
        if self._registers:
            menu += ["edit_register", "remove_registers"]
        menu.append("add_flag")
        if self._flags:
            menu.append("remove_flags")
        return self.async_show_menu(step_id="init", menu_options=menu)

    async def async_step_settings(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Edit the scan interval."""
        if user_input is not None:
            options = dict(self.config_entry.options)
            options[CONF_SCAN_INTERVAL] = int(user_input[CONF_SCAN_INTERVAL])
            return self.async_create_entry(title="", data=options)

        current = self.config_entry.options.get(
            CONF_SCAN_INTERVAL,
            self.config_entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
        )
        return self.async_show_form(
            step_id="settings",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SCAN_INTERVAL, default=current): vol.All(
                        vol.Coerce(int), vol.Range(min=5, max=3600)
                    ),
                }
            ),
        )

    async def async_step_add_register(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Add a register as sensor."""
        errors: dict[str, str] = {}
        if user_input is not None:
            register = self._clean_register(user_input)
            registers = self._registers
            if any(r[CONF_ADDRESS] == register[CONF_ADDRESS] for r in registers):
                errors[CONF_ADDRESS] = "address_exists"
            else:
                return self._save(registers=[*registers, register])

        return self.async_show_form(
            step_id="add_register",
            data_schema=self._register_schema(user_input or {}),
            errors=errors,
        )

    async def async_step_edit_register(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Choose the register to edit."""
        registers = self._registers
        if user_input is not None:
            self._edit_index = int(user_input["register"])
            return await self.async_step_edit_register_details()

        return self.async_show_form(
            step_id="edit_register",
            data_schema=vol.Schema(
                {
                    vol.Required("register"): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[
                                selector.SelectOptionDict(
                                    value=str(i), label=self._register_label(r)
                                )
                                for i, r in enumerate(registers)
                            ],
                            mode=selector.SelectSelectorMode.LIST,
                        )
                    )
                }
            ),
        )

    async def async_step_edit_register_details(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Edit one register."""
        registers = self._registers
        assert self._edit_index is not None
        current = registers[self._edit_index]
        errors: dict[str, str] = {}
        if user_input is not None:
            register = self._clean_register(user_input, current)
            others = [r for i, r in enumerate(registers) if i != self._edit_index]
            if any(r[CONF_ADDRESS] == register[CONF_ADDRESS] for r in others):
                errors[CONF_ADDRESS] = "address_exists"
            else:
                return self._save(registers=[*others, register])

        return self.async_show_form(
            step_id="edit_register_details",
            data_schema=self._register_schema(user_input or current),
            errors=errors,
        )

    async def async_step_remove_registers(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Remove registers."""
        registers = self._registers
        if user_input is not None:
            remove = {int(i) for i in user_input.get("registers", [])}
            return self._save(
                registers=[r for i, r in enumerate(registers) if i not in remove]
            )

        return self.async_show_form(
            step_id="remove_registers",
            data_schema=vol.Schema(
                {
                    vol.Optional("registers", default=[]): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[
                                selector.SelectOptionDict(
                                    value=str(i), label=self._register_label(r)
                                )
                                for i, r in enumerate(registers)
                            ],
                            multiple=True,
                            mode=selector.SelectSelectorMode.LIST,
                        )
                    )
                }
            ),
        )

    async def async_step_add_flag(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Add a flag as binary sensor or switch."""
        errors: dict[str, str] = {}
        if user_input is not None:
            flag = {
                CONF_ADDRESS: int(user_input[CONF_ADDRESS]),
                CONF_NAME: str(user_input[CONF_NAME]).strip(),
                CONF_WRITABLE: bool(user_input.get(CONF_WRITABLE, False)),
            }
            flags = self._flags
            if any(f[CONF_ADDRESS] == flag[CONF_ADDRESS] for f in flags):
                errors[CONF_ADDRESS] = "address_exists"
            else:
                return self._save(flags=[*flags, flag])

        defaults = user_input or {}
        return self.async_show_form(
            step_id="add_flag",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_ADDRESS, default=defaults.get(CONF_ADDRESS, vol.UNDEFINED)
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=0,
                            max=65535,
                            step=1,
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                    vol.Required(
                        CONF_NAME, default=defaults.get(CONF_NAME, vol.UNDEFINED)
                    ): selector.TextSelector(),
                    vol.Required(
                        CONF_WRITABLE, default=defaults.get(CONF_WRITABLE, False)
                    ): selector.BooleanSelector(),
                }
            ),
            errors=errors,
        )

    async def async_step_remove_flags(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Remove flags."""
        flags = self._flags
        if user_input is not None:
            remove = {int(i) for i in user_input.get("flags", [])}
            return self._save(flags=[f for i, f in enumerate(flags) if i not in remove])

        return self.async_show_form(
            step_id="remove_flags",
            data_schema=vol.Schema(
                {
                    vol.Optional("flags", default=[]): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[
                                selector.SelectOptionDict(
                                    value=str(i), label=self._flag_label(f)
                                )
                                for i, f in enumerate(flags)
                            ],
                            multiple=True,
                            mode=selector.SelectSelectorMode.LIST,
                        )
                    )
                }
            ),
        )

    # -- PG5 project ---------------------------------------------------

    async def async_step_import_project(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Upload Fupla file and linker map of the PG5 project."""
        errors: dict[str, str] = {}
        placeholders = {"error": ""}
        if user_input is not None:
            try:
                fup, map_, library_texts = await self.hass.async_add_executor_job(
                    _read_uploads,
                    self.hass,
                    user_input["fup"],
                    user_input["map"],
                    user_input.get("library"),
                )
                library = merge_libraries(library_texts) if library_texts else None
                if library_texts and not library:
                    raise PG5ParseError("No FBox entries in the library files")  # noqa: TRY301
                points = await self.hass.async_add_executor_job(
                    parse_project, fup, map_, library
                )
            except zipfile.BadZipFile:
                errors["base"] = "invalid_library"
            except PG5ParseError as err:
                errors["base"] = "invalid_project"
                placeholders["error"] = str(err)
            except (OSError, ValueError) as err:
                _LOGGER.warning("Could not read uploaded PG5 files: %s", err)
                errors["base"] = "upload_failed"
            else:
                if not points:
                    errors["base"] = "empty_project"
                else:
                    return await self._finish_import(points)

        return self.async_show_form(
            step_id="import_project",
            data_schema=vol.Schema(
                {
                    vol.Required("fup"): selector.FileSelector(
                        selector.FileSelectorConfig(accept=".fup")
                    ),
                    vol.Required("map"): selector.FileSelector(
                        selector.FileSelectorConfig(accept=".map")
                    ),
                    vol.Optional("library"): selector.FileSelector(
                        selector.FileSelectorConfig(accept=".zip,.idx")
                    ),
                }
            ),
            errors=errors,
            description_placeholders=placeholders,
        )

    async def _finish_import(self, points: list[DataPoint]) -> FlowResult:
        """Store the project and align configured data points with it."""
        data = [p.as_dict() for p in points]
        if not any(p["title"] or p["options"] for p in data):
            # No library uploaded this time: keep texts from the last import
            previous = await async_load_project(self.hass, self.config_entry.entry_id)
            texts = {
                p["symbol"]: (p.get("title"), p.get("options"))
                for p in (previous or {}).get("points", [])
            }
            for point in data:
                if point["symbol"] in texts:
                    point["title"], point["options"] = texts[point["symbol"]]
        await async_save_project(
            self.hass, self.config_entry.entry_id, "PG5 project", data
        )
        registers, moved_r, missing_r = remap_to_project(
            self._registers, data, KIND_REGISTER
        )
        flags, moved_f, missing_f = remap_to_project(self._flags, data, KIND_FLAG)
        migrate_entity_addresses(
            self.hass,
            self.config_entry.entry_id,
            {"register": moved_r, "register_number": moved_r, "register_select": moved_r,
             "flag": moved_f, "flag_switch": moved_f},
        )
        groups = sorted({p.group for p in points})
        self._import = {
            "registers": registers,
            "flags": flags,
            "placeholders": {
                "points": str(len(points)),
                "groups": ", ".join(groups),
                "moved": str(len(moved_r) + len(moved_f)),
                "missing": ", ".join(missing_r + missing_f) or "–",
            },
        }
        return await self.async_step_import_done()

    async def async_step_import_done(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Show the import result."""
        assert self._import is not None
        if user_input is not None:
            if is_configured(self.config_entry) or self._import["registers"] or self._import["flags"]:
                return self._save(
                    registers=self._import["registers"], flags=self._import["flags"]
                )
            return self.async_create_entry(title="", data=dict(self.config_entry.options))
        return self.async_show_form(
            step_id="import_done",
            data_schema=vol.Schema({}),
            description_placeholders=self._import["placeholders"],
        )

    def _points(self) -> list[dict[str, Any]]:
        return list((self._project or {}).get("points", []))

    async def async_step_select_group(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Choose the plant (first part of the symbol, e.g. "S01")."""
        if user_input is not None:
            self._group = user_input["group"]
            self._with_parameters = bool(user_input.get("parameters", False))
            if user_input.get("mode") == "parts":
                return await self.async_step_select_parts()
            return await self.async_step_select_points()

        counts: dict[str, list[int]] = {}
        for point in self._points():
            operating = point["level"] in OPERATING_LEVELS
            counts.setdefault(point["group"], [0, 0])[0 if operating else 1] += 1
        options = [
            selector.SelectOptionDict(
                value=group, label=f"{group} ({values[0]} / {values[0] + values[1]})"
            )
            for group, values in sorted(counts.items())
        ]
        return self.async_show_form(
            step_id="select_group",
            data_schema=vol.Schema(
                {
                    vol.Required("group"): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=options, mode=selector.SelectSelectorMode.LIST
                        )
                    ),
                    vol.Required("mode", default="parts"): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=["parts", "points"],
                            translation_key="selection_mode",
                            mode=selector.SelectSelectorMode.LIST,
                        )
                    ),
                    vol.Required("parameters", default=False): selector.BooleanSelector(),
                }
            ),
        )

    def _shown(self) -> list[dict[str, Any]]:
        """Project points of the chosen plant, filtered by the level switch."""
        return [
            p
            for p in self._points()
            if p["group"] == self._group
            and (self._with_parameters or p["level"] in OPERATING_LEVELS)
        ]

    def _configured_symbols(self, shown: list[dict[str, Any]]) -> set[str]:
        """Shown points that are configured already (by address)."""
        registers = {r[CONF_ADDRESS] for r in self._registers}
        flags = {f[CONF_ADDRESS] for f in self._flags}
        return {
            p["symbol"]
            for p in shown
            if p["address"] in (registers if p["kind"] == KIND_REGISTER else flags)
        }

    def _save_selection(
        self, shown: list[dict[str, Any]], selected: set[str]
    ) -> FlowResult:
        return self._save(
            registers=apply_selection(
                self._registers, [p for p in shown if p["kind"] == KIND_REGISTER], selected
            ),
            flags=apply_selection(
                self._flags, [p for p in shown if p["kind"] == KIND_FLAG], selected
            ),
        )

    async def async_step_select_parts(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Take over whole plant parts (e.g. "Zirk. UWP") with all data points."""
        shown = self._shown()
        parts = plant_parts(self._points())
        by_part: dict[str, list[dict[str, Any]]] = {}
        for point in shown:
            by_part.setdefault(parts[point["symbol"]]["part"], []).append(point)
        configured = self._configured_symbols(shown)
        complete = {
            key
            for key, members in by_part.items()
            if all(p["symbol"] in configured for p in members)
        }

        if user_input is not None:
            chosen = set(user_input.get("parts", []))
            selected = set(configured)
            for key, members in by_part.items():
                symbols = {p["symbol"] for p in members}
                if key in chosen:
                    selected |= symbols
                elif key in complete:  # unticked: remove the whole part
                    selected -= symbols
            return self._save_selection(shown, selected)

        options = []
        for key, members in sorted(
            by_part.items(), key=lambda item: parts[item[1][0]["symbol"]]["device_name"]
        ):
            info = parts[members[0]["symbol"]]
            writable = sum(1 for p in members if p["writable"])
            label = f"{info['device_name']} – {len(members)}"
            if writable:
                label += f" ({writable} ✎)"
            options.append(selector.SelectOptionDict(value=key, label=label))
        return self.async_show_form(
            step_id="select_parts",
            data_schema=vol.Schema(
                {
                    vol.Optional("parts", default=sorted(complete)): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=options,
                            multiple=True,
                            mode=selector.SelectSelectorMode.LIST,
                        )
                    ),
                }
            ),
            description_placeholders={"group": self._group or ""},
        )

    async def async_step_select_points(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Tick the data points of the chosen plant."""
        shown = self._shown()

        if user_input is not None:
            return self._save_selection(shown, set(user_input.get("points", [])))

        configured = self._configured_symbols(shown)
        selected = [p["symbol"] for p in shown if p["symbol"] in configured]
        options = [
            selector.SelectOptionDict(value=p["symbol"], label=_point_label(p))
            for p in shown
        ]
        return self.async_show_form(
            step_id="select_points",
            data_schema=vol.Schema(
                {
                    vol.Optional("points", default=selected): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=options,
                            multiple=True,
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    ),
                }
            ),
            description_placeholders={"group": self._group or "", "count": str(len(shown))},
        )


def _read_uploads(
    hass: HomeAssistant, fup_id: str, map_id: str, library_id: str | None
) -> tuple[str, str, list[str]]:
    """Read the uploaded files (runs in the executor); they are deleted afterwards.

    The library is a ZIP with the DDC Suite .idx files or a single .idx.
    """
    with process_uploaded_file(hass, fup_id) as fup_path:
        fup = decode(fup_path.read_bytes())
    with process_uploaded_file(hass, map_id) as map_path:
        map_ = decode(map_path.read_bytes())
    library: list[str] = []
    if library_id:
        with process_uploaded_file(hass, library_id) as library_path:
            data = library_path.read_bytes()
        if data[:2] == b"PK":
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                library = [
                    decode(archive.read(name))
                    for name in archive.namelist()
                    if name.lower().endswith(".idx")
                ]
        else:
            library = [decode(data)]
    return fup, map_, library


def _point_label(point: dict[str, Any]) -> str:
    """Label for the selection list."""
    description = point["description"]
    if len(description) > 70:  # noqa: PLR2004
        description = description[:69] + "…"
    writable = " ✎" if point["writable"] else ""
    label = f"{point['label']} – {point.get('title') or point['variable']}"
    if description:
        label += f": {description}"
    return f"{label} ({point['kind']} {point['address']}){writable}"

