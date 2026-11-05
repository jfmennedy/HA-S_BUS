"""Sensor platform for SAIA S-Bus integration."""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any

from homeassistant.components.sensor import SensorEntity

from .const import CONF_DATA_TYPE
from .const import CONF_FACTOR
from .const import CONF_UNIT
from .const import CONF_WRITABLE
from .const import DATA_TYPE_FLOAT
from .const import DATA_TYPE_UNSIGNED
from .const import DOMAIN
from .datapoints import convert_register
from .datapoints import decimals_for_factor
from .datapoints import get_registers
from .datapoints import unit_classes
from .entity import SBusEntity

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .coordinator import SBusDataUpdateCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up S-Bus register sensors."""
    data = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        SBusRegisterSensor(data["coordinator"], data["device_info"], config)
        for config in get_registers(entry)
        if not config.get(CONF_WRITABLE)  # writable registers are number entities
    )


class SBusRegisterSensor(SBusEntity, SensorEntity):
    """A PCD register as sensor."""

    _data_key = "registers"
    _unique_prefix = "register"

    def __init__(
        self,
        coordinator: SBusDataUpdateCoordinator,
        device_info: dict[str, Any],
        config: dict[str, Any],
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, device_info, config)
        self._data_type: str = config.get(CONF_DATA_TYPE) or DATA_TYPE_UNSIGNED
        self._factor = float(config.get(CONF_FACTOR) or 1.0)
        unit = config.get(CONF_UNIT) or None
        self._attr_native_unit_of_measurement = unit
        self._attr_device_class, self._attr_state_class = unit_classes(unit)
        if self._data_type == DATA_TYPE_FLOAT:
            self._attr_suggested_display_precision = max(
                2, decimals_for_factor(self._factor)
            )
        else:
            self._attr_suggested_display_precision = decimals_for_factor(self._factor)

    @property
    def native_value(self) -> float | int | None:
        """Return the converted register value."""
        raw = self._raw
        if raw is None:
            return None
        return convert_register(raw, self._data_type, self._factor)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra attributes."""
        return {**super().extra_state_attributes, "raw_value": self._raw}
