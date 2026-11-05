"""Read data points from a Saia PG5 project.

Two files of a built PG5 project are combined:

* the linker map (``Lst/<project>.map``) lists every public symbol with
  its type and absolute address, e.g. ``S01.Speicher.Temp2.Fühler.Istwert``
  = R 3187. Addresses of FBox resources are assigned at build time, so the
  map is the only reliable source for them.
* the Fupla file (``<name>.fup``, INI-like text) holds the FBox instances:
  a description for every symbol (``HSYM`` entries, prefixed with the
  DDC Suite level "(1)" main value, "(4)" setting, "(5)" commissioning),
  the FBox label ("Speicher Temp. 2"), the display format of each
  variable ("%1p" = one decimal), whether it is adjustable ("a") or
  view-only ("v"), its range and the FBox's unit code.

This module has no Home Assistant dependencies.
"""

from __future__ import annotations

import re
from dataclasses import asdict
from dataclasses import dataclass
from typing import Any

ENCODING = "cp1252"  # PG5 writes Windows-1252

KIND_REGISTER = "R"
KIND_FLAG = "F"
SUPPORTED_KINDS = (KIND_REGISTER, KIND_FLAG)

# DDC Suite levels in the descriptions: (1)-(3) operating values (actual
# values, setpoints, states, alarms), (4) settings, (5) commissioning
OPERATING_LEVELS = (1, 2, 3)

# DDC Suite unit codes (gUnit*). Only codes that could be verified are mapped.
UNIT_CODES = {1: "%", 10: "°C"}

_MAP_SYMBOL = re.compile(
    r"^(?P<name>\S+)?\s+(?P<kind>[A-Z]+)\s+(?P<address>\d+)(?:\.\.\d+)?\s+\d+#"
)
_HSYM = re.compile(r"^HSYM\d+=(?P<rest>.*)$", re.MULTILINE)
_SECTION = re.compile(r"^\[(?P<head>[^\]\r\n]+)\]\s*$", re.MULTILINE)
_AV = re.compile(
    r"^av\d+=(?P<access>[av]) (?P<var>\w+) \d+ (?P<format>%\w+)"
    r"(?: =(?P<default>\S+))?(?: \{(?P<range>[^}]*)\})?",
    re.MULTILINE,
)
_DESCRIPT = re.compile(r'^av\d+=a Descript %T ="[^"]*":"(?P<text>[^"]*)"', re.MULTILINE)
_UNIT = re.compile(r"^av\d+=a gUnitL? %s =(?P<code>\d+)", re.MULTILINE)
_LEVEL = re.compile(r"^\((?P<level>\d)\)\s*")
_DECIMALS = re.compile(r"^%(?P<decimals>\d)p$")


class PG5ParseError(ValueError):
    """The files are not a PG5 linker map / Fupla file."""


@dataclass(slots=True)
class DataPoint:
    """One register or flag of the PG5 project."""

    symbol: str
    kind: str
    address: int
    group: str
    label: str
    variable: str
    level: int | None
    description: str
    writable: bool
    factor: float
    unit: str | None
    minimum: float | None
    maximum: float | None
    fbox_type: str | None = None
    # From the DDC Suite library (.idx): readable title and value texts
    title: str | None = None
    options: list[list[Any]] | None = None

    @property
    def operating(self) -> bool:
        """True for operating values (levels 1-3), False for parameters."""
        return self.level in OPERATING_LEVELS

    @property
    def name(self) -> str:
        """Entity name, e.g. "S01 Speicher Temp. 2 Istwert"."""
        return f"{self.group} {self.label} {self.variable}".strip()

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON serializable dict."""
        return asdict(self)


def parse_map(text: str) -> dict[str, tuple[str, int]]:
    """Return ``{symbol: (kind, address)}`` from a PG5 linker map."""
    lines = text.splitlines()
    try:
        start = lines.index("PUBLIC SYMBOLS") + 1
    except ValueError as err:
        msg = "No 'PUBLIC SYMBOLS' section found, is this a PG5 linker map?"
        raise PG5ParseError(msg) from err

    symbols: dict[str, tuple[str, int]] = {}
    pending: str | None = None
    for line in lines[start:]:
        match = _MAP_SYMBOL.match(line)
        if match:
            name = match["name"] or pending
            if name:
                symbols[name] = (match["kind"], int(match["address"]))
            pending = None
            continue
        stripped = line.strip()
        # Long names stand alone on a line, the address follows indented.
        # Page headers ("SAIA PG5 LINKER ...", "User: ...") contain spaces.
        if stripped and not line[0].isspace() and " " not in stripped:
            pending = stripped
        elif stripped and not line[0].isspace():
            continue  # page header, keep a pending name
        elif stripped:
            pending = None  # value without type (e.g. __DYNAMICS__ constants)
    return symbols


@dataclass(slots=True)
class _FBoxVariable:
    fbox_type: str
    var: str
    label: str
    access: str
    format: str
    range: str | None
    unit_code: int | None


def _parse_fbox_variables(text: str) -> dict[int, _FBoxVariable]:
    """Return FBox information per HSYM id from the FBox sections."""
    variables: dict[int, _FBoxVariable] = {}
    heads = list(_SECTION.finditer(text))
    for index, head in enumerate(heads):
        end = heads[index + 1].start() if index + 1 < len(heads) else len(text)
        body = text[head.end() : end]
        resources = re.search(r"^S=(?P<items>.*)$", body, re.MULTILINE)
        if not resources:
            continue
        descript = _DESCRIPT.search(body)
        label = descript["text"].strip() if descript else ""
        unit = _UNIT.search(body)
        unit_code = int(unit["code"]) if unit else None
        av = {m["var"]: m for m in _AV.finditer(body)}
        for item in resources["items"].split():
            key, _, ident = item.partition("=")
            var, _, _type = key.rpartition("_")
            if not ident.isdigit() or not var:
                continue
            spec = av.get(var)
            variables[int(ident)] = _FBoxVariable(
                fbox_type=head["head"].split()[0].lstrip("_"),
                var=var,
                label=label,
                access=spec["access"] if spec else "v",
                format=spec["format"] if spec else "",
                range=spec["range"] if spec else None,
                unit_code=unit_code,
            )
    return variables


def _scale(fmt: str) -> float:
    match = _DECIMALS.match(fmt)
    return 10 ** -int(match["decimals"]) if match else 1.0


def _range(spec: str | None, factor: float) -> tuple[float | None, float | None]:
    if not spec or ".." not in spec:
        return None, None
    low, _, high = spec.partition("..")
    try:
        return round(int(low) * factor, 6), round(int(high) * factor, 6)
    except ValueError:
        return None, None


def parse_project(
    fup_text: str, map_text: str, library: Library | None = None
) -> list[DataPoint]:
    """Combine Fupla file and linker map into data points with addresses.

    With a DDC Suite library (see ``parse_library``) the data points also
    get the readable title and value texts of the FBox adjust window.
    """
    addresses = parse_map(map_text)
    if "[FILEHEADER]" not in fup_text:
        msg = "No [FILEHEADER] section found, is this a Fupla (.fup) file?"
        raise PG5ParseError(msg)
    fbox = _parse_fbox_variables(fup_text)

    points: dict[str, DataPoint] = {}
    for match in _HSYM.finditer(fup_text):
        fields = match["rest"].rstrip("\r").split("\t")
        if len(fields) < 3 or not fields[0].isdigit():  # noqa: PLR2004
            continue
        ident, symbol, kind = int(fields[0]), fields[1].strip(), fields[2].strip()
        description = fields[6].strip() if len(fields) > 6 else ""  # noqa: PLR2004
        if kind not in SUPPORTED_KINDS or symbol not in addresses:
            continue
        map_kind, address = addresses[symbol]
        if map_kind != kind:
            continue

        level_match = _LEVEL.match(description)
        level = int(level_match["level"]) if level_match else None
        if level_match:
            description = description[level_match.end() :]

        info = fbox.get(ident)
        parts = symbol.split(".")
        factor = _scale(info.format) if info and kind == KIND_REGISTER else 1.0
        minimum, maximum = _range(info.range if info else None, factor)
        unit = None
        if info and info.unit_code is not None and factor < 1 and level in (1, 2, 3, 4):
            unit = UNIT_CODES.get(info.unit_code)

        points[symbol] = DataPoint(
            symbol=symbol,
            kind=kind,
            address=address,
            group=parts[0],
            label=(info.label if info and info.label else ".".join(parts[1:-1])),
            variable=parts[-1],
            level=level,
            description=description,
            writable=bool(info and info.access == "a"),
            factor=factor,
            unit=unit,
            minimum=minimum,
            maximum=maximum,
            fbox_type=info.fbox_type if info else None,
        )
        if info and library:
            entry = library.get(info.fbox_type, {}).get(info.var)
            _apply_library(points[symbol], entry)
    return sorted(points.values(), key=lambda p: (p.group, p.label, p.symbol))


def _apply_library(
    point: DataPoint, entry: tuple[str, list[tuple[int, str]]] | None
) -> None:
    """Add title and value texts from the library to a data point."""
    if not entry:
        return
    point.title = entry[0] or None
    if entry[1]:
        point.options = [[value, text] for value, text in entry[1]]


def decode(data: bytes) -> str:
    """Decode a PG5 file."""
    return data.decode(ENCODING, errors="replace")


# ----------------------------------------------------------------------------
# DDC Suite FBox library (.idx)
# ----------------------------------------------------------------------------

# {fbox type without leading "_": {variable: (title, [(value, text), ...])}}
Library = dict[str, dict[str, tuple[str, list[tuple[int, str]]]]]

_IDX_SECTION = re.compile(r"^\[_?(?P<type>\w+)\]\s*$", re.MULTILINE)
_IDX_ENTRY = re.compile(r"^(?P<var>\w+) \d+=(?P<text>.*)$", re.MULTILINE)
_IDX_VALUE = re.compile(r"^(?P<value>-?\d+)\)(?P<text>.*)$")
_IDX_HEADING = re.compile(r"^c\w*=\[\s*-+\s*(?P<text>.*?)\s*-+\s*\]")


def _clean_title(text: str) -> str:
    """ "... Außentemperaturgrenzwert " -> "Außentemperaturgrenzwert"."""
    return text.strip().lstrip(".").strip()


def parse_library(text: str) -> Library:
    """Read the adjust window texts of a DDC Suite library index (.idx).

    Lines look like ``HMI 0=HMI Niederprior\\R)z.B. HMI\\1)Auto\\2)Aus``:
    variable, title, an optional remark ("R)") and value texts ("1)Auto").
    """
    library: Library = {}
    heads = list(_IDX_SECTION.finditer(text))
    for index, head in enumerate(heads):
        end = heads[index + 1].start() if index + 1 < len(heads) else len(text)
        found: list[tuple[str, str, str, list[tuple[int, str]]]] = []
        heading = ""
        for line in text[head.end() : end].splitlines():
            section = _IDX_HEADING.match(line)
            if section:
                heading = section["text"].strip()
                continue
            match = _IDX_ENTRY.match(line)
            if not match:
                continue
            title, *parts = match["text"].rstrip("\r").split("\\")
            found.append((match["var"], _clean_title(title), heading, _values(parts)))
        if found:
            library.setdefault(head["type"], {}).update(_disambiguate(found))
    return library


def _values(parts: list[str]) -> list[tuple[int, str]]:
    """ "1)Auto", "2)Aus" -> [(1, "Auto"), (2, "Aus")]; remarks ("R)...") skipped."""
    values = []
    for part in parts:
        value = _IDX_VALUE.match(part)
        if value:
            values.append((int(value["value"]), value["text"].strip()))
    return values


def _disambiguate(
    found: list[tuple[str, str, str, list[tuple[int, str]]]],
) -> dict[str, tuple[str, list[tuple[int, str]]]]:
    """Titles that occur twice in one FBox ("Meldungszustand" for every
    alarm) get the heading of their block: "Motorschutz Meldungszustand".
    """
    counts: dict[str, int] = {}
    for item in found:
        counts[item[1]] = counts.get(item[1], 0) + 1
    return {
        var: (f"{block} {title}" if counts[title] > 1 and block else title, values)
        for var, title, block, values in found
    }


def merge_libraries(texts: list[str]) -> Library:
    """Parse and merge several .idx files."""
    library: Library = {}
    for text in texts:
        for fbox_type, entries in parse_library(text).items():
            library.setdefault(fbox_type, {}).update(entries)
    return library

