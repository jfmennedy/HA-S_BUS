"""PG5 project import and data point selection in the options flow."""

from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path
from unittest.mock import patch

import pytest
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sbus.const import DOMAIN
from custom_components.sbus.number import value_to_raw

from .test_sbus_protocol import STATION
from .test_sbus_protocol import FakePCD

FIXTURES = Path(__file__).parent / "fixtures" / "pg5"
# Upload ids are UUIDs in Home Assistant
FUP_ID = "00000000-0000-0000-0000-00000000f0f0"
MAP_ID = "00000000-0000-0000-0000-00000000a0a0"
LIB_ID = "00000000-0000-0000-0000-00000000b1b1"


@pytest.fixture
def uploads(tmp_path):
    """Fake the HA file upload: file ids are fixture names or tmp files."""
    files: dict[str, Path] = {
        "fup": FIXTURES / "Demo.fup",
        "map": FIXTURES / "Demo.map",
        "library": FIXTURES / "Demo_idx.zip",
    }
    ids = {FUP_ID: "fup", MAP_ID: "map", LIB_ID: "library"}

    @contextlib.contextmanager
    def fake_process(_hass, file_id):
        yield files[ids[file_id]]

    with patch(
        "custom_components.sbus.config_flow.process_uploaded_file", fake_process
    ):
        yield files


@pytest.fixture
async def pcd_entry(hass, enable_custom_integrations, socket_enabled):  # noqa: ARG001
    """Integration set up against a fake PCD with the demo program's values."""
    loop = asyncio.get_running_loop()
    transport, pcd = await loop.create_datagram_endpoint(
        FakePCD, local_addr=("127.0.0.1", 0)
    )
    pcd.registers.update({3187: 329, 1790: 200, 3300: 412})
    pcd.flags.update({4358: False, 3317: True})
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "protocol_type": "ether_sbus",
            "connection_type": "udp",
            "host": "127.0.0.1",
            "port": transport.get_extra_info("sockname")[1],
            "station": STATION,
            "timeout": 0.5,
        },
        options={
            "registers": [
                {
                    "address": 3187,
                    "name": "Pufferspeicher Oben",
                    "data_type": "signed",
                    "factor": 0.1,
                    "unit": "°C",
                }
            ],
            "flags": [],
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    yield pcd, entry
    await hass.config_entries.async_unload(entry.entry_id)
    transport.close()


async def _menu(hass, entry, step):
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert step in result["menu_options"], result["menu_options"]
    return await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": step}
    )


async def _import(hass, entry, *, library=False):
    result = await _menu(hass, entry, "import_project")
    files = {"fup": FUP_ID, "map": MAP_ID}
    if library:
        files["library"] = LIB_ID
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], files
    )
    assert result["step_id"] == "import_done", result.get("errors")
    placeholders = result["description_placeholders"]
    result = await hass.config_entries.options.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    return placeholders


async def _select(hass, entry, group, symbols, *, parameters=False):
    result = await _menu(hass, entry, "select_group")
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"group": group, "mode": "points", "parameters": parameters}
    )
    assert result["step_id"] == "select_points"
    offered = [o["value"] for o in result["data_schema"].schema["points"].config["options"]]
    preselected = result["data_schema"]({})["points"]
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"points": symbols}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    return offered, preselected


def _entity(hass, domain, entry, address, kind):
    identity = f"127.0.0.1:{entry.data['port']}:{STATION}"
    return er.async_get(hass).async_get_entity_id(
        domain, DOMAIN, f"{identity}_{kind}_{address}"
    )


async def test_import_and_select(hass, pcd_entry, uploads) -> None:  # noqa: ARG001
    """Import, pick sensor/alarm/setpoint/enable, write the setpoint."""
    pcd, entry = pcd_entry
    placeholders = await _import(hass, entry)
    assert placeholders["points"] == "15"
    assert placeholders["groups"] == "H01, S01"
    # the manual register got the symbol of its address
    assert entry.options["registers"][0]["symbol"] == "S01.Speicher.Temp2.Fühler.Istwert"

    offered, preselected = await _select(
        hass,
        entry,
        "S01",
        ["S01.Speicher.Temp2.Fühler.Istwert", "S01.Speicher.Temp2.Fühler.SmGwOben"],
    )
    # operating values only, the manual register is ticked already
    assert offered[:2] == [
        "S01.Speicher.Temp2.Fühler.Istwert",
        "S01.Speicher.Temp2.Fühler.SmGwOben",
    ]
    assert "S01.Speicher.Temp2.Fühler.FilterZeit" not in offered
    assert "S01.ZIRK.UWP.iBetrieb_DI" not in offered
    assert preselected == ["S01.Speicher.Temp2.Fühler.Istwert"]
    # the manual register keeps its name
    sensor = hass.states.get(_entity(hass, "sensor", entry, 3187, "register"))
    assert sensor.name.endswith("Pufferspeicher Oben")
    assert float(sensor.state) == pytest.approx(32.9)
    assert sensor.attributes["symbol"] == "S01.Speicher.Temp2.Fühler.Istwert"
    assert hass.states.get(_entity(hass, "binary_sensor", entry, 4358, "flag")).state == "off"

    offered, _ = await _select(
        hass, entry, "H01", ["H01.Anlage.Sollwert", "H01.Anlage.Freigabe"]
    )
    assert "H01.Anlage.UhrEin" not in offered  # parameter, hidden by default

    number_id = _entity(hass, "number", entry, 1790, "register_number")
    state = hass.states.get(number_id)
    assert float(state.state) == pytest.approx(20.0)
    assert (state.attributes["min"], state.attributes["max"], state.attributes["step"]) == (0.0, 90.0, 0.1)
    await hass.services.async_call(
        "number", "set_value", {"entity_id": number_id, "value": 21.5}, blocking=True
    )
    assert pcd.registers[1790] == 215

    switch_id = _entity(hass, "switch", entry, 3317, "flag_switch")
    assert hass.states.get(switch_id).state == "on"
    # S01 entities are still there after choosing H01
    assert _entity(hass, "binary_sensor", entry, 4358, "flag")


async def test_parameters_and_deselect(hass, pcd_entry, uploads) -> None:  # noqa: ARG001
    """Parameters can be shown; unticking removes the entity."""
    _pcd, entry = pcd_entry
    await _import(hass, entry)
    offered, preselected = await _select(
        hass, entry, "S01", ["S01.Speicher.Temp2.Fühler.GwOben"], parameters=True
    )
    assert "S01.Speicher.Temp2.Fühler.FilterZeit" in offered
    assert preselected == ["S01.Speicher.Temp2.Fühler.Istwert"]
    assert _entity(hass, "sensor", entry, 3187, "register") is None
    assert _entity(hass, "number", entry, 3184, "register_number")


async def test_reimport_moves_addresses(hass, pcd_entry, uploads, tmp_path) -> None:
    """After a rebuild with new addresses the entities follow their symbols."""
    _pcd, entry = pcd_entry
    await _import(hass, entry)
    entity_id = _entity(hass, "sensor", entry, 3187, "register")

    moved = tmp_path / "Moved.map"
    moved.write_bytes(
        (FIXTURES / "Demo.map").read_bytes().replace(b"R    3187", b"R    3300")
    )
    uploads["map"] = moved
    placeholders = await _import(hass, entry)
    assert placeholders["moved"] == "1"

    assert entry.options["registers"][0]["address"] == 3300
    assert _entity(hass, "sensor", entry, 3300, "register") == entity_id
    assert float(hass.states.get(entity_id).state) == pytest.approx(41.2)


async def test_invalid_upload(hass, pcd_entry, uploads) -> None:  # noqa: ARG001
    """Swapped files are reported."""
    _pcd, entry = pcd_entry
    uploads["fup"], uploads["map"] = uploads["map"], uploads["fup"]
    result = await _menu(hass, entry, "import_project")
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"fup": FUP_ID, "map": MAP_ID}
    )
    assert result["errors"] == {"base": "invalid_project"}


@pytest.mark.parametrize(
    ("value", "data_type", "factor", "raw"),
    [
        (21.5, "signed", 0.1, 215),
        (-5.5, "signed", 0.1, 0xFFFFFFC9),
        (7, "unsigned", 1, 7),
        (21.5, "float", 1, 0x41AC0000),
    ],
)
def test_value_to_raw(value, data_type, factor, raw) -> None:
    """Displayed values are converted back to raw register values."""
    assert value_to_raw(value, data_type, factor) == raw


async def _select_parts(hass, entry, group, parts, *, parameters=False):
    result = await _menu(hass, entry, "select_group")
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"group": group, "mode": "parts", "parameters": parameters}
    )
    assert result["step_id"] == "select_parts"
    options = {
        o["value"]: o["label"]
        for o in result["data_schema"].schema["parts"].config["options"]
    }
    preselected = result["data_schema"]({})["parts"]
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"parts": parts}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    return options, preselected


async def test_select_plant_part(hass, pcd_entry, uploads) -> None:  # noqa: ARG001
    """A whole plant part is taken over and becomes its own device."""
    _pcd, entry = pcd_entry
    await _import(hass, entry)
    options, preselected = await _select_parts(hass, entry, "S01", ["S01:zirkuwp"])
    assert options == {
        "S01:speichertemp2": "S01 Speicher Temp. 2 – 2",
        "S01:zirkuwp": "S01 Zirk. UWP – 6 (1 ✎)",  # iBetrieb_DI, HMI: no operating values
    }
    assert preselected == []  # Speicher Temp. 2 is only partly configured

    devices = dr.async_get(hass)
    identity = f"127.0.0.1:{entry.data['port']}:{STATION}"
    pcd = devices.async_get_device({(DOMAIN, identity)})
    pump = devices.async_get_device({(DOMAIN, f"{identity}#S01:zirkuwp")})
    assert (pump.name, pump.model, pump.via_device_id) == (
        "S01 Zirk. UWP",
        "DDC_COPUMP270",
        pcd.id,
    )
    entities = er.async_entries_for_device(er.async_get(hass), pump.id)
    assert sorted((e.domain, e.original_name) for e in entities) == [
        ("binary_sensor", "Betrieb"),
        ("binary_sensor", "BrmSm"),
        ("binary_sensor", "Steuerung.Sperre"),
        ("binary_sensor", "Störungen.Sperre"),
        ("number", "Schaltung"),
        ("sensor", "Zustand"),
    ]
    brm = hass.states.get(_entity(hass, "binary_sensor", entry, 4382, "flag"))
    assert brm.name == "S01 Zirk. UWP BrmSm"
    assert brm.attributes["description"] == "Störmeldung Betriebsrückmeldung fehlt"

    # The manual register moved to its plant part and keeps its name
    sensor = er.async_get(hass).async_get(_entity(hass, "sensor", entry, 3187, "register"))
    assert devices.async_get(sensor.device_id).name == "S01 Speicher Temp. 2"
    assert sensor.original_name == "Pufferspeicher Oben"

    # Unticking the complete part removes entities and device
    _options, preselected = await _select_parts(hass, entry, "S01", [])
    assert preselected == ["S01:zirkuwp"]
    assert devices.async_get_device({(DOMAIN, f"{identity}#S01:zirkuwp")}) is None
    assert _entity(hass, "binary_sensor", entry, 4382, "flag") is None
    assert _entity(hass, "sensor", entry, 3187, "register")  # not part of it


async def test_library_texts(hass, pcd_entry, uploads) -> None:  # noqa: ARG001
    """With the DDC Suite library: readable names, select, text sensor, state text."""
    pcd, entry = pcd_entry
    pcd.registers.update({3249: 1, 3260: 2})
    pcd.flags.update({4398: False, 4382: True})
    await _import(hass, entry, library=True)
    await _select_parts(hass, entry, "S01", ["S01:zirkuwp"], parameters=True)

    hmi_id = _entity(hass, "select", entry, 3249, "register_select")
    hmi = hass.states.get(hmi_id)
    assert hmi.name == "S01 Zirk. UWP HMI Niederprior"
    assert (hmi.state, hmi.attributes["options"]) == ("Auto", ["Auto", "Aus", "Ein"])
    await hass.services.async_call(
        "select", "select_option", {"entity_id": hmi_id, "option": "Ein"}, blocking=True
    )
    assert pcd.registers[3249] == 3
    assert hass.states.get(hmi_id).state == "Ein"

    state = hass.states.get(_entity(hass, "sensor", entry, 3260, "register"))
    assert (state.name, state.state) == ("S01 Zirk. UWP Betriebszustand", "Störung")
    assert "unit_of_measurement" not in state.attributes

    lock = hass.states.get(_entity(hass, "binary_sensor", entry, 4398, "flag"))
    assert (lock.name, lock.state, lock.attributes["state_text"]) == (
        "S01 Zirk. UWP Motorstörungen",
        "off",
        "keine",
    )
    alarm = hass.states.get(_entity(hass, "binary_sensor", entry, 4382, "flag"))
    assert alarm.name == "S01 Zirk. UWP Betriebsmeldung Meldungszustand"
    assert alarm.attributes["state_text"] == "STÖRUNG"

    # A value the library doesn't know is shown as number, not hidden
    pcd.registers[3249] = 7
    pcd.registers[3260] = 9
    await hass.data[DOMAIN][entry.entry_id]["coordinator"].async_refresh()
    await hass.async_block_till_done()
    hmi = hass.states.get(hmi_id)
    assert (hmi.state, hmi.attributes["options"]) == ("7", ["Auto", "Aus", "Ein", "7"])
    assert hass.states.get(_entity(hass, "sensor", entry, 3260, "register")).state == "9"

    # Re-import without library keeps the texts
    await _import(hass, entry)
    assert hass.states.get(hmi_id).attributes["options"] == ["Auto", "Aus", "Ein", "7"]


async def test_invalid_library(hass, pcd_entry, uploads) -> None:  # noqa: ARG001
    """A damaged ZIP is reported."""
    _pcd, entry = pcd_entry
    broken = FIXTURES / "Demo.map"  # not a ZIP, not an idx
    uploads["library"] = broken
    result = await _menu(hass, entry, "import_project")
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"fup": FUP_ID, "map": MAP_ID, "library": LIB_ID}
    )
    assert result["errors"] == {"base": "invalid_project"}


async def test_broken_zip(hass, pcd_entry, uploads, tmp_path) -> None:  # noqa: ARG001
    """A ZIP that can't be opened is reported as invalid library."""
    _pcd, entry = pcd_entry
    broken = tmp_path / "broken.zip"
    broken.write_bytes(b"PK\x03\x04 this is not a zip")
    uploads["library"] = broken
    result = await _menu(hass, entry, "import_project")
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"fup": FUP_ID, "map": MAP_ID, "library": LIB_ID}
    )
    assert result["errors"] == {"base": "invalid_library"}
