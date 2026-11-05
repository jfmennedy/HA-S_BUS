"""Tests for reading PG5 projects (Fupla file + linker map)."""

from __future__ import annotations

from pathlib import Path

import pytest

from custom_components.sbus.pg5 import PG5ParseError
from custom_components.sbus.pg5 import decode
from custom_components.sbus.pg5 import parse_map
from custom_components.sbus.pg5 import parse_project

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
    }

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
