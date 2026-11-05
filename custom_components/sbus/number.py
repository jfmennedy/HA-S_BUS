"""Number platform: writable PCD registers (setpoints, limits, ...)."""

from __future__ import annotations

import struct
from typing import TYPE_CHECKING
from typing import Any

from homeassistant.components.number import NumberEntity
from homeassistant.components.number import NumberMode
from homeassistant.exceptions import HomeAssistantError

from .const import CONF_DATA_TYPE
from .const import CONF_FACTOR
from .const import CONF_MAX
from .const import CONF_MIN
from .const import CONF_UNIT
from .const import CONF_WRITABLE
from .const import DATA_TYPE_FLOAT
from .const import DATA_TYPE_SIGNED
from .const import DATA_TYPE_UNSIGNED
from .const import DOMAIN
from .datapoints import convert_register
from .datapoints import decimals_for_factor
from .datapoints import get_registers
from .datapoints import unit_classes
from .entity import SBusEntity
from .sbus_protocol import SBusProtocolError

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .coordinator import SBusDataUpdateCoordinator
    from .sbus_protocol import SBusProtocolBase

_INT32_MIN = -(2**31)
_INT32_MAX = 2**31 - 1
_UINT32_MAX = 2**32 - 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up writable registers as number entities."""
    data = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        SBusRegisterNumber(
            data["coordinator"], data["device_info"], config, data["protocol"]
        )
        for config in get_registers(entry)
        if config.get(CONF_WRITABLE)
    )


def value_to_raw(value: float, data_type: str, factor: float) -> int:
    """Convert a displayed value back to the raw 32 bit register value."""
    if data_type == DATA_TYPE_FLOAT:
        return struct.unpack("!I", struct.pack("!f", value / factor))[0]
    raw = round(value / factor)
    if data_type == DATA_TYPE_UNSIGNED:
        if not 0 <= raw <= _UINT32_MAX:
            msg = f"Value {value} out of range for an unsigned register"
            raise HomeAssistantError(msg)
        return raw
    if not _INT32_MIN <= raw <= _INT32_MAX:
        msg = f"Value {value} out of range for a signed register"
        raise HomeAssistantError(msg)
    return raw & 0xFFFFFFFF


class SBusRegisterNumber(SBusEntity, NumberEntity):
    """A writable PCD register."""

    _data_key = "registers"
    _unique_prefix = "register_number"
    _attr_mode = NumberMode.BOX

    def __init__(
        self,
        coordinator: SBusDataUpdateCoordinator,
        device_info: dict[str, Any],
        config: dict[str, Any],
        protocol: SBusProtocolBase,
    ) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator, device_info, config)
        self._protocol = protocol
        self._data_type: str = config.get(CONF_DATA_TYPE) or DATA_TYPE_SIGNED
        self._factor = float(config.get(CONF_FACTOR) or 1.0)
        unit = config.get(CONF_UNIT) or None
        self._attr_native_unit_of_measurement = unit
        device_class, _state_class = unit_classes(unit)
        # Number entities only support some device classes; temperature works
        self._attr_device_class = device_class if unit == "°C" else None
        self._attr_native_step = self._factor if self._factor < 1 else 1
        if self._data_type == DATA_TYPE_FLOAT:
            self._attr_native_step = 10 ** -max(2, decimals_for_factor(self._factor))
        if self._data_type == DATA_TYPE_UNSIGNED:
            default_min, default_max = 0, _UINT32_MAX * self._factor
        else:
            default_min = _INT32_MIN * self._factor
            default_max = _INT32_MAX * self._factor
        minimum, maximum = config.get(CONF_MIN), config.get(CONF_MAX)
        self._attr_native_min_value = default_min if minimum is None else minimum
        self._attr_native_max_value = default_max if maximum is None else maximum

    @property
    def native_value(self) -> float | int | None:
        """Return the current register value."""
        raw = self._raw
        if raw is None:
            return None
        return convert_register(raw, self._data_type, self._factor)

    async def async_set_native_value(self, value: float) -> None:
        """Write the value to the PCD."""
        raw = value_to_raw(value, self._data_type, self._factor)
        try:
            await self._protocol.write_register(self._address, raw)
        except SBusProtocolError as err:
            msg = f"Failed to write register R{self._address}: {err}"
            raise HomeAssistantError(msg) from err
        await self.coordinator.async_request_refresh()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra attributes."""
        return {**super().extra_state_attributes, "raw_value": self._raw}
