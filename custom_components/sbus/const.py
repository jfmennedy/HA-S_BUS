"""Constants for the SAIA S-Bus integration."""

from typing import Final

# Integration domain
DOMAIN: Final = "sbus"

# Configuration keys
CONF_HOST: Final = "host"
CONF_PORT: Final = "port"
CONF_STATION: Final = "station"
CONF_SCAN_INTERVAL: Final = "scan_interval"
CONF_PROTOCOL_TYPE: Final = "protocol_type"
CONF_SERIAL_PORT: Final = "serial_port"
CONF_BAUDRATE: Final = "baudrate"
CONF_CONNECTION_TYPE: Final = "connection_type"

# Protocol types
PROTOCOL_ETHER_SBUS: Final = "ether_sbus"
PROTOCOL_SERIAL_SBUS: Final = "serial_sbus"
PROTOCOL_PROFI_SBUS: Final = "profi_sbus"

# Connection types for Serial-S-Bus
CONNECTION_TYPE_USB: Final = "usb"
CONNECTION_TYPE_TCP_SERIAL: Final = "tcp_serial"
CONNECTION_TYPE_TCP: Final = "tcp"
CONNECTION_TYPE_UDP: Final = "udp"

# Default values
DEFAULT_PORT_UDP: Final = 5050
DEFAULT_PORT_TCP: Final = 5050
DEFAULT_STATION: Final = 0
DEFAULT_SCAN_INTERVAL: Final = 30
DEFAULT_TIMEOUT: Final = 5
DEFAULT_BAUDRATE: Final = 9600

# Available baudrates for Serial-S-Bus
BAUDRATES: Final = [1200, 2400, 4800, 9600, 19200, 38400, 57600, 115200]

# S-Bus Protocol Constants
SBUS_FRAME_START: Final = 0xB5
SBUS_ESCAPE_CHAR: Final = 0xC5
SBUS_BROADCAST_ADDR: Final = 255

# Ether-S-Bus header
ETHER_SBUS_HEADER_SIZE: Final = 8  # length(4) version(1) type(1) sequence(2)
ETHER_SBUS_VERSION: Final = 0x01
ETHER_SBUS_PROTOCOL_TYPE: Final = 0x00

# Attribute bytes
ATTR_REQUEST: Final = 0x00
ATTR_RESPONSE: Final = 0x01
ATTR_ACK: Final = 0x02

# Opcodes for S-Bus commands
CMD_READ_COUNTER: Final = 0x00
CMD_READ_FLAG: Final = 0x02
CMD_READ_INPUT: Final = 0x03
CMD_READ_RTC: Final = 0x04
CMD_READ_OUTPUT: Final = 0x05
CMD_READ_REGISTER: Final = 0x06
CMD_READ_TIMER: Final = 0x07
CMD_WRITE_COUNTER: Final = 0x0A
CMD_WRITE_FLAG: Final = 0x0B
CMD_WRITE_RTC: Final = 0x0C
CMD_WRITE_OUTPUT: Final = 0x0D
CMD_WRITE_REGISTER: Final = 0x0E
CMD_WRITE_TIMER: Final = 0x0F
CMD_READ_PROGRAM_VERSION: Final = 0x20
CMD_READ_DB: Final = 0x96
CMD_WRITE_DB: Final = 0x97


# Entity platforms
PLATFORMS: Final = ["sensor", "binary_sensor", "switch"]

# Services
SERVICE_READ_REGISTER: Final = "read_register"
SERVICE_WRITE_REGISTER: Final = "write_register"
SERVICE_READ_FLAG: Final = "read_flag"
SERVICE_WRITE_FLAG: Final = "write_flag"

# Protocol limits and validation
MAX_REGISTER_ADDRESS: Final = 9999
MAX_REGISTER_COUNT: Final = 32
MAX_REGISTER_VALUE: Final = 0xFFFFFFFF
MAX_FLAG_COUNT: Final = 1024
MAX_STATION_ADDRESS: Final = 253

# Error messages
ERROR_CANNOT_CONNECT: Final = "cannot_connect"
ERROR_CANNOT_CONNECT_TCP: Final = "cannot_connect_tcp"
ERROR_INVALID_AUTH: Final = "invalid_auth"
ERROR_UNKNOWN: Final = "unknown"
ERROR_TIMEOUT: Final = "timeout"
ERROR_CRC_ERROR: Final = "crc_error"
ERROR_SERIAL_PORT_NOT_FOUND: Final = "serial_port_not_found"
ERROR_INVALID_PROTOCOL: Final = "invalid_protocol"

# Attributes
ATTR_ADDRESS: Final = "address"
ATTR_VALUE: Final = "value"
ATTR_COUNT: Final = "count"
ATTR_START_ADDRESS: Final = "start_address"
ATTR_DEVICE_TYPE: Final = "device_type"
ATTR_FIRMWARE_VERSION: Final = "firmware_version"
ATTR_SERIAL_NUMBER: Final = "serial_number"

# Configurable data points (stored in the config entry options)
CONF_REGISTERS: Final = "registers"
CONF_FLAGS: Final = "flags"
CONF_ADDRESS: Final = "address"
CONF_NAME: Final = "name"
CONF_DATA_TYPE: Final = "data_type"
CONF_FACTOR: Final = "factor"
CONF_UNIT: Final = "unit"
CONF_WRITABLE: Final = "writable"
CONF_SYMBOL: Final = "symbol"
CONF_MIN: Final = "min"
CONF_MAX: Final = "max"

DATA_TYPE_UNSIGNED: Final = "unsigned"
DATA_TYPE_SIGNED: Final = "signed"
DATA_TYPE_FLOAT: Final = "float"
DATA_TYPES: Final = [DATA_TYPE_SIGNED, DATA_TYPE_UNSIGNED, DATA_TYPE_FLOAT]

# Units offered in the options flow (any other unit can be typed in)
UNITS: Final = ["°C", "%", "bar", "Pa", "kWh", "Wh", "kW", "W", "m³", "m³/h", "l/h", "V", "A", "h"]

# Data points used when nothing has been configured yet (pre 0.4.0 behaviour)
LEGACY_REGISTERS: Final = range(10)
LEGACY_FLAGS: Final = range(32)
LEGACY_SWITCHES: Final = range(8)
