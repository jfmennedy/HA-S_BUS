"""Tests for reading PG5 projects (Fupla file + linker map)."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from custom_components.sbus.pg5 import PG5ParseError
from custom_components.sbus.pg5 import decode
from custom_components.sbus.pg5 import merge_libraries
from custom_components.sbus.pg5 import parse_map
from custom_components.sbus.pg5 import parse_project
from custom_components.sbus.project import plant_parts

FIXTURES = Path(__file__).parent / "fixtures" / "pg5"


def _read(name: str) -> str:
    return decode((FIXTURES / name).read_bytes())


def test_parse_map() -> None:
    """Same-line and two-line symbols; page headers between name and address."""
    symbols = parse_map(_read("Demo.map"))
    assert symbols["___ETR___"] == ("F", 4427)
    assert symbols["__DBSTRC__"] == ("R", 3286)
    assert symbols["S01.Speicher.Temp2.Fühler.Istwert"] == ("R", 3187)
    assert symbols["S01.Speicher.Temp2.Fühler.SmGwOben"] == ("F", 4358)
    assert symbols["H01.Anlage.Prog"] == ("FB", 5)
    assert "__DYNAMICS__.__FIRST_FLAG__" not in symbols


def test_parse_project() -> None:
    """Fupla descriptions, formats, units and access are joined with addresses."""
    points = {p.symbol: p for p in parse_project(_read("Demo.fup"), _read("Demo.map"))}
    assert set(points) == {
        "S01.Speicher.Temp2.Fühler.Istwert",
        "S01.Speicher.Temp2.Fühler.SmGwOben",
        "S01.Speicher.Temp2.Fühler.GwOben",
        "S01.Speicher.Temp2.Fühler.FilterZeit",
        "H01.Anlage.Freigabe",
        "H01.Anlage.Sollwert",
        "H01.Anlage.UhrEin",
        "S01.ZIRK.UWP.Steuerung.Betrieb",
        "S01.ZIRK.UWP.Steuerung.Schaltung",
        "S01.ZIRK.UWP.Steuerung.Sperre",
        "S01.ZIRK.UWP.Störungen.BrmSm",
        "S01.ZIRK.UWP.Störungen.Sperre",
        "S01.ZIRK.UWP.iBetrieb_DI",
        "S01.ZIRK.UWP.Steuerung.HMI",
        "S01.ZIRK.UWP.Steuerung.Zustand",
    }
    assert points["S01.ZIRK.UWP.Steuerung.Schaltung"].fbox_type == "DDC_COPUMP270"
    assert points["S01.ZIRK.UWP.iBetrieb_DI"].fbox_type is None

    actual = points["S01.Speicher.Temp2.Fühler.Istwert"]
    assert (actual.kind, actual.address, actual.level) == ("R", 3187, 1)
    assert actual.name == "S01 Speicher Temp. 2 Istwert"
    assert actual.description == 'Physikalischer Wert des Sensors = Ausgang "Iw"'
    assert (actual.factor, actual.unit, actual.writable) == (0.1, "°C", False)
    assert actual.operating

    limit = points["S01.Speicher.Temp2.Fühler.GwOben"]
    assert limit.writable
    assert (limit.unit, limit.minimum, limit.maximum) == ("°C", -2000000.0, 2000000.0)
    assert not limit.operating

    filter_time = points["S01.Speicher.Temp2.Fühler.FilterZeit"]
    assert filter_time.level == 5
    assert filter_time.unit is None  # commissioning values get no unit

    alarm = points["S01.Speicher.Temp2.Fühler.SmGwOben"]
    assert (alarm.kind, alarm.writable, alarm.factor) == ("F", False, 1.0)

    setpoint = points["H01.Anlage.Sollwert"]
    assert setpoint.writable
    assert (setpoint.factor, setpoint.minimum, setpoint.maximum) == (0.1, 0.0, 90.0)
    assert setpoint.unit is None  # FBox has no unit code

    assert points["H01.Anlage.Freigabe"].writable
    assert points["H01.Anlage.UhrEin"].factor == 1.0  # %1H is a time HHMM


def test_invalid_files() -> None:
    """Files of the wrong kind are rejected."""
    with pytest.raises(PG5ParseError):
        parse_map(_read("Demo.fup"))
    with pytest.raises(PG5ParseError):
        parse_project(_read("Demo.map"), _read("Demo.map"))


def test_plant_parts() -> None:
    """FBoxes with one description and internal symbols form one plant part."""
    points = [p.as_dict() for p in parse_project(_read("Demo.fup"), _read("Demo.map"))]
    parts = plant_parts(points)
    pump = {s: i for s, i in parts.items() if "ZIRK.UWP" in s}
    assert len(pump) == 8
    assert {i["part"] for i in pump.values()} == {"S01:zirkuwp"}
    info = pump["S01.ZIRK.UWP.Steuerung.Betrieb"]
    assert (info["device_name"], info["model"], info["short_name"]) == (
        "S01 Zirk. UWP",
        "DDC_COPUMP270",
        "Betrieb",
    )
    # "Sperre" exists in both FBoxes of the part
    assert pump["S01.ZIRK.UWP.Steuerung.Sperre"]["short_name"] == "Steuerung.Sperre"
    assert pump["S01.ZIRK.UWP.Störungen.Sperre"]["short_name"] == "Störungen.Sperre"
    sensor = parts["S01.Speicher.Temp2.Fühler.Istwert"]
    assert sensor["device_name"] == "S01 Speicher Temp. 2"
    assert sensor["model"] == "DDC_ANSENSOR270"


def _library():
    with zipfile.ZipFile(FIXTURES / "Demo_idx.zip") as archive:
        return merge_libraries(
            [decode(archive.read(n)) for n in archive.namelist() if n.endswith(".idx")]
        )


def test_parse_library() -> None:
    """Titles, value texts, remarks and repeated titles in the .idx files."""
    library = _library()
    pump = library["DDC_COPUMP270"]
    assert pump["HMI"] == ("HMI Niederprior", [(1, "Auto"), (2, "Aus"), (3, "Ein")])
    assert pump["Zust"] == ("Betriebszustand", [(0, "Aus"), (1, "Betrieb"), (2, "Störung")])
    assert pump["Sperr"] == ("Motorstörungen", [(0, "keine"), (1, "STÖRUNG")])
    assert pump["Schalt"] == ("Schaltungen", [])
    assert "BACnet" not in pump  # FBox setting, not a resource
    alarm = library["DDC_ALMOT1SP270"]
    assert alarm["BrmSm"][0] == "Betriebsmeldung Meldungszustand"
    assert alarm["Sperr"][0] == "Motorschutz Meldungszustand"
    assert library["DDC_ANSENSOR270"]["GwHi"][0] == "Grenzwert überschreiten"


def test_project_with_library() -> None:
    """Data points get title and value texts; part names use the titles."""
    points = parse_project(_read("Demo.fup"), _read("Demo.map"), _library())
    by_symbol = {p.symbol: p for p in points}
    hmi = by_symbol["S01.ZIRK.UWP.Steuerung.HMI"]
    assert (hmi.title, hmi.options) == (
        "HMI Niederprior",
        [[1, "Auto"], [2, "Aus"], [3, "Ein"]],
    )
    assert by_symbol["S01.ZIRK.UWP.iBetrieb_DI"].title is None
    names = {
        s: i["short_name"]
        for s, i in plant_parts([p.as_dict() for p in points]).items()
        if "ZIRK" in s
    }
    assert names == {
        "S01.ZIRK.UWP.Steuerung.Betrieb": "Rückmeldung",
        "S01.ZIRK.UWP.Steuerung.Schaltung": "Schaltungen",
        "S01.ZIRK.UWP.Steuerung.Sperre": "Motorstörungen",
        "S01.ZIRK.UWP.Steuerung.HMI": "HMI Niederprior",
        "S01.ZIRK.UWP.Steuerung.Zustand": "Betriebszustand",
        "S01.ZIRK.UWP.Störungen.BrmSm": "Betriebsmeldung Meldungszustand",
        "S01.ZIRK.UWP.Störungen.Sperre": "Motorschutz Meldungszustand",
        "S01.ZIRK.UWP.iBetrieb_DI": "iBetrieb_DI",
    }
