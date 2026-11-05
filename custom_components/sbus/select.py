"""Select platform: adjustable selection values with DDC Suite texts."""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.exceptions import HomeAssistantError

from .const import CONF_DATA_TYPE
from .const import DATA_TYPE_SIGNED
from .const import DOMAIN
from .datapoints import convert_register
from .datapoints import get_registers
from .entity import SBusEntity
from .entity import register_kind
from .entity import value_texts
from .number import value_to_raw
from .sbus_protocol import SBusProtocolError

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .coordinator import SBusDataUpdateCoordinator
    from .sbus_protocol import SBusProtocolBase


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up adjustable selection values (e.g. pump HMI: Auto/Aus/Ein)."""
    data = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        SBusRegisterSelect(
            data["coordinator"], data["device_info"], config, data["protocol"]
        )
        for config in get_registers(entry)
        if register_kind(config) == "register_select"
    )


class SBusRegisterSelect(SBusEntity, SelectEntity):
    """A writable PCD register with value texts."""

    _data_key = "registers"
    _unique_prefix = "register_select"

    def __init__(
        self,
        coordinator: SBusDataUpdateCoordinator,
        device_info: dict[str, Any],
        config: dict[str, Any],
        protocol: SBusProtocolBase,
    ) -> None:
        """Initialize the select entity."""
        super().__init__(coordinator, device_info, config)
        self._protocol = protocol
        self._data_type: str = config.get(CONF_DATA_TYPE) or DATA_TYPE_SIGNED
        self._texts = value_texts(config)
        self._values = {text: value for value, text in self._texts.items()}

    @property
    def _value(self) -> int | None:
        raw = self._raw
        if raw is None:
            return None
        return int(convert_register(raw, self._data_type, 1))

    @property
    def options(self) -> list[str]:
        """Texts from the library; an unknown current value is offered as number."""
        options = list(self._texts.values())
        value = self._value
        if value is not None and value not in self._texts:
            options.append(str(value))
        return options

    @property
    def current_option(self) -> str | None:
        """Return the text of the current value."""
        value = self._value
        if value is None:
            return None
        return self._texts.get(value, str(value))

    async def async_select_option(self, option: str) -> None:
        """Write the value of the chosen text to the PCD."""
        value = self._values.get(option)
        if value is None:
            try:
                value = int(option)
            except ValueError as err:
                msg = f"Unknown option {option!r}"
                raise HomeAssistantError(msg) from err
        raw = value_to_raw(value, self._data_type, 1)
        try:
            await self._protocol.write_register(self._address, raw)
        except SBusProtocolError as err:
            msg = f"Failed to write register R{self._address}: {err}"
            raise HomeAssistantError(msg) from err
        await self.coordinator.async_request_refresh()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra attributes."""
        return {**super().extra_state_attributes, "raw_value": self._value}
