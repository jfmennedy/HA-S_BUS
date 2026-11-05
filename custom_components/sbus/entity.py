"""Base entity for the SAIA S-Bus integration."""

from __future__ import annotations

from typing import Any

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_ADDRESS
from .const import CONF_NAME
from .const import CONF_SYMBOL
from .const import DOMAIN
from .coordinator import SBusDataUpdateCoordinator


class SBusEntity(CoordinatorEntity[SBusDataUpdateCoordinator]):
    """Common base for register and flag entities."""

    _attr_has_entity_name = True
    _data_key: str  # "registers" or "flags"
    _unique_prefix: str  # e.g. "register", "flag", "flag_switch"

    def __init__(
        self,
        coordinator: SBusDataUpdateCoordinator,
        device_info: dict[str, Any],
        config: dict[str, Any],
    ) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self._config = config
        self._address: int = int(config[CONF_ADDRESS])
        self._attr_name = config.get(CONF_NAME) or None
        self._attr_unique_id = unique_id(
            device_info["identity"], self._unique_prefix, self._address
        )
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_info["identity"])},
            name=device_info.get("product_type", "SAIA PCD"),
            manufacturer="SAIA-Burgess Controls",
            model=device_info.get("pcd_type") or "SAIA PCD",
            sw_version=device_info.get("firmware_version"),
        )

    @property
    def _raw(self) -> Any:
        """Return the raw value from the coordinator."""
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get(self._data_key, {}).get(self._address)

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return super().available and self._raw is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra attributes."""
        attributes = {"address": self._address, "type": self._data_key[:-1]}
        if symbol := self._config.get(CONF_SYMBOL):
            attributes["symbol"] = symbol
        return attributes


def unique_id(serial: str, prefix: str, address: int) -> str:
    """Build the unique id of a data point entity."""
    return f"{serial}_{prefix}_{address}"
