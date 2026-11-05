"""Imported PG5 project: storage and matching against configured data points.

Only the evaluated data point list is stored (Home Assistant storage,
``.storage/sbus.<entry_id>.project``), not the uploaded files.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING
from typing import Any

from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.storage import Store

from .const import CONF_ADDRESS
from .const import CONF_DATA_TYPE
from .const import CONF_FACTOR
from .const import CONF_MAX
from .const import CONF_MIN
from .const import CONF_NAME
from .const import CONF_SYMBOL
from .const import CONF_UNIT
from .const import CONF_WRITABLE
from .const import DATA_TYPE_SIGNED
from .const import DOMAIN
from .pg5 import KIND_FLAG
from .pg5 import KIND_REGISTER

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

STORAGE_VERSION = 1


def _store(hass: HomeAssistant, entry_id: str) -> Store[dict[str, Any]]:
    return Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry_id}.project")


async def async_load_project(
    hass: HomeAssistant, entry_id: str
) -> dict[str, Any] | None:
    """Return the stored project ({"name", "points": [...]}) or None."""
    return await _store(hass, entry_id).async_load()


async def async_save_project(
    hass: HomeAssistant, entry_id: str, name: str, points: list[dict[str, Any]]
) -> None:
    """Store the evaluated data points of a project."""
    await _store(hass, entry_id).async_save({"name": name, "points": points})


async def async_remove_project(hass: HomeAssistant, entry_id: str) -> None:
    """Delete the stored project."""
    await _store(hass, entry_id).async_remove()


def point_to_config(point: dict[str, Any]) -> dict[str, Any]:
    """Build the option entry for a project data point."""
    name = f"{point['group']} {point['label']} {point['variable']}".strip()
    if point["kind"] == KIND_FLAG:
        return {
            CONF_ADDRESS: point["address"],
            CONF_NAME: name,
            CONF_WRITABLE: point["writable"],
            CONF_SYMBOL: point["symbol"],
        }
    return {
        CONF_ADDRESS: point["address"],
        CONF_NAME: name,
        CONF_DATA_TYPE: DATA_TYPE_SIGNED,
        CONF_FACTOR: point["factor"],
        CONF_UNIT: point["unit"],
        CONF_WRITABLE: point["writable"],
        CONF_MIN: point["minimum"],
        CONF_MAX: point["maximum"],
        CONF_SYMBOL: point["symbol"],
    }


def remap_to_project(
    configs: list[dict[str, Any]],
    points: list[dict[str, Any]],
    kind: str,
) -> tuple[list[dict[str, Any]], dict[int, int], list[str]]:
    """Align configured data points with a (re-)imported project.

    * entries with a symbol get the symbol's current address (PG5 may assign
      new addresses when the program is rebuilt),
    * entries without a symbol get one if a project point has their address.

    Returns the updated entries, a mapping old -> new address for entries
    that moved, and the symbols that no longer exist in the project.
    """
    by_symbol = {p["symbol"]: p for p in points if p["kind"] == kind}
    by_address = {p["address"]: p for p in points if p["kind"] == kind}
    updated: list[dict[str, Any]] = []
    moved: dict[int, int] = {}
    missing: list[str] = []
    for original in configs:
        config = dict(original)
        symbol = config.get(CONF_SYMBOL)
        if symbol:
            point = by_symbol.get(symbol)
            if point is None:
                missing.append(symbol)
            elif point["address"] != config[CONF_ADDRESS]:
                moved[config[CONF_ADDRESS]] = point["address"]
                config[CONF_ADDRESS] = point["address"]
        elif (point := by_address.get(config[CONF_ADDRESS])) is not None:
            config[CONF_SYMBOL] = point["symbol"]
        updated.append(config)
    return updated, moved, missing


def apply_selection(
    configs: list[dict[str, Any]],
    shown: list[dict[str, Any]],
    selected: set[str],
) -> list[dict[str, Any]]:
    """Apply the user's selection for the shown project points of one kind.

    Shown points that are selected are added (existing entries, e.g. with a
    custom name, are kept); shown points that are not selected are removed.
    Entries outside the shown list stay untouched.
    """
    shown_symbols = {p["symbol"] for p in shown}
    shown_addresses = {p["address"]: p["symbol"] for p in shown}
    result: list[dict[str, Any]] = []
    present: set[str] = set()
    for config in configs:
        symbol = config.get(CONF_SYMBOL) or shown_addresses.get(config[CONF_ADDRESS])
        if symbol not in shown_symbols:
            result.append(config)
        elif symbol in selected:  # deselected entries are dropped
            present.add(symbol)
            result.append({**config, CONF_SYMBOL: symbol})
    result.extend(
        point_to_config(p)
        for p in shown
        if p["symbol"] in selected and p["symbol"] not in present
    )
    return result


def kind_of(point: dict[str, Any]) -> str:
    """Return the option key for a project point."""
    return "registers" if point["kind"] == KIND_REGISTER else "flags"


_UNIQUE_ID = re.compile(
    r"^(?P<identity>.+?)_(?P<kind>register_number|register|flag_switch|flag)"
    r"_(?P<address>\d+)$"
)


def migrate_entity_addresses(
    hass: HomeAssistant, entry_id: str, moved: dict[str, dict[int, int]]
) -> None:
    """Move entities to new addresses after a re-import.

    ``moved`` maps the unique id kind ("register", "flag", ...) to
    ``{old address: new address}``. Renaming happens in two steps so
    swapped addresses don't collide; entity ids and history are kept.
    """
    registry = er.async_get(hass)
    renames: list[tuple[str, str]] = []
    for entity in er.async_entries_for_config_entry(registry, entry_id):
        match = _UNIQUE_ID.match(entity.unique_id)
        if not match:
            continue
        old = int(match["address"])
        new = moved.get(match["kind"], {}).get(old)
        if new is not None and new != old:
            renames.append(
                (entity.entity_id, f"{match['identity']}_{match['kind']}_{new}")
            )
    for entity_id, new_unique_id in renames:
        registry.async_update_entity(
            entity_id, new_unique_id=f"{new_unique_id}__moving"
        )
    for entity_id, new_unique_id in renames:
        registry.async_update_entity(entity_id, new_unique_id=new_unique_id)
