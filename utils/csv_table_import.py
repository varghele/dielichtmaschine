# utils/csv_table_import.py
"""CSV lighting-table import (ROADMAP v1.4): read whatever spreadsheet a
venue hands over and map its columns onto the app's rig fields.

The v1.1 fixture-list CSV import (utils/fixture_io.py) expects the
app's own column layout; this module handles foreign sheets. Pure
logic, no Qt - the import wizard (gui/dialogs/csv_import_wizard.py) is
a thin shell over these functions:

- ``sniff_csv(path)``: delimiter (comma/semicolon/tab; csv.Sniffer with
  a counting fallback), tolerant encoding (utf-8-sig, then cp1252, then
  latin-1) and header-row detection, plus the parsed rows. Detection
  results can be overridden per keyword argument (the wizard's manual
  override combo/checkbox re-runs this).
- ``guess_mapping(header)``: case-insensitive auto-guess of which CSV
  column feeds which of OUR fields (exact match first, substring
  second, no column claimed twice).
- ``apply_mapping(rows, mapping)``: one normalized dict per data row.
- ``build_fixtures(records)``: Fixture objects with the same semantics
  as the fixture-list CSV import (synthesized single mode that library
  resolution upgrades, PAR default type); rows that cannot become a
  fixture come back as error strings, never silently dropped.
- ``resolve_fixtures(fixtures)``: delegates to the existing resolution
  pipeline (utils/fixture_io.resolve_modes_from_library) and reports
  which models the library resolves and which are missing.

Nothing here touches a Configuration. The wizard hands the resolved
fixtures to ``utils/fixture_io.apply_fixture_list`` (the same
Replace/Add semantics as File > Import Fixture List) only after the
user confirms.
"""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from config.models import Fixture, FixtureMode

# The rig fields a foreign sheet can feed, in wizard display order.
# ``position`` is the venue's hang position (FOH truss, LX1, boom SL);
# it lands on Fixture.layer - apply_fixture_list synthesizes a stage
# layer per unknown name, so positions survive into the stage setup.
FIELDS: List[Tuple[str, str]] = [
    ("name", "Name"),
    ("manufacturer", "Manufacturer"),
    ("model", "Model"),
    ("mode", "Mode"),
    ("universe", "Universe"),
    ("address", "Address"),
    ("group", "Group"),
    ("position", "Position"),
]
REQUIRED_FIELDS: Tuple[str, ...] = ("manufacturer", "model")

# Manufacturer/model are matched verbatim against the library (QLC+
# model names can carry trailing spaces), so apply_mapping does not
# strip them.
_VERBATIM_FIELDS = frozenset({"manufacturer", "model"})

_DELIMITERS = ",;\t"
_ENCODINGS = ("utf-8-sig", "cp1252", "latin-1")

# Auto-guess keywords per field. Order matters twice over: fields are
# assigned top-down (a claimed column is never reused), and within a
# field an exact header match beats a substring hit - so a sheet with
# both "Model" and "Mode" columns maps each to its own field even
# though "mode" is a substring of "model".
_GUESS_KEYWORDS: List[Tuple[str, Tuple[str, ...]]] = [
    ("manufacturer", ("manufacturer", "make", "brand")),
    ("model", ("model", "fixture", "type")),
    ("name", ("name", "label")),
    ("universe", ("universe", "univ")),
    ("address", ("address", "addr", "dmx")),
    ("mode", ("mode",)),
    ("group", ("group",)),
    ("position", ("position", "pos", "purpose")),
]


@dataclass
class SniffResult:
    """Everything the wizard's first page shows and the later steps eat."""
    delimiter: str
    encoding: str
    has_header: bool
    header: List[str]              # column names for the mapping UI
    rows: List[List[str]]          # data rows (header row excluded)
    raw_rows: List[List[str]] = field(default_factory=list)  # as parsed


@dataclass
class ResolutionReport:
    """What the library made of the imported models."""
    warnings: List[str]
    resolved: List[Tuple[str, str]]   # (manufacturer, model) found
    missing: List[Tuple[str, str]]    # not found; synthesized mode kept

    def is_resolved(self, fixture: Fixture) -> bool:
        return (fixture.manufacturer, fixture.model) not in set(self.missing)


# ---------------------------------------------------------------------------
# Sniffing
# ---------------------------------------------------------------------------

def read_csv_text(path: str) -> Tuple[str, str]:
    """Decode the file tolerantly. Returns (text, encoding_used).

    utf-8-sig first (also eats a BOM), then cp1252 (Excel's Windows
    default, covers umlauts), then latin-1 (never fails).
    """
    with open(path, "rb") as f:
        raw = f.read()
    for encoding in _ENCODINGS[:-1]:
        try:
            return raw.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    return raw.decode(_ENCODINGS[-1]), _ENCODINGS[-1]


def detect_delimiter(sample: str) -> str:
    """csv.Sniffer over comma/semicolon/tab, falling back to counting
    candidates in the first non-empty line (comma when all else fails)."""
    try:
        return csv.Sniffer().sniff(sample, delimiters=_DELIMITERS).delimiter
    except csv.Error:
        pass
    for line in sample.splitlines():
        if line.strip():
            counts = {d: line.count(d) for d in _DELIMITERS}
            best = max(counts, key=counts.get)
            if counts[best] > 0:
                return best
            break
    return ","


def _looks_numeric(cell: str) -> bool:
    cell = cell.strip()
    if not cell:
        return False
    try:
        float(cell.replace(",", "."))
        return True
    except ValueError:
        return False


def detect_header(rows: List[List[str]]) -> bool:
    """Heuristic: the first row is a header when it carries text but no
    numbers (venue sheets always number something - address, universe,
    count). The wizard's checkbox overrides misreads."""
    if not rows:
        return False
    first = rows[0]
    if not any(cell.strip() for cell in first):
        return False
    return not any(_looks_numeric(cell) for cell in first)


def sniff_csv(path: str, delimiter: Optional[str] = None,
              has_header: Optional[bool] = None) -> SniffResult:
    """Parse a foreign CSV. ``delimiter``/``has_header`` override the
    detection (the wizard's manual controls re-run this).

    Raises OSError for unreadable paths and csv.Error for content that
    is not a delimited text file at all (binary junk, stray NULs); the
    wizard turns both into a warning box."""
    text, encoding = read_csv_text(path)
    if delimiter is None:
        delimiter = detect_delimiter(text[:8192])
    raw_rows = [row for row in csv.reader(io.StringIO(text),
                                          delimiter=delimiter)]
    raw_rows = [row for row in raw_rows if any(cell.strip() for cell in row)]
    if has_header is None:
        has_header = detect_header(raw_rows)

    width = max((len(row) for row in raw_rows), default=0)
    if has_header and raw_rows:
        header = [cell.strip() or f"Column {i + 1}"
                  for i, cell in enumerate(raw_rows[0])]
        rows = raw_rows[1:]
    else:
        header = []
        rows = raw_rows
    header += [f"Column {i + 1}" for i in range(len(header), width)]

    return SniffResult(delimiter=delimiter, encoding=encoding,
                       has_header=has_header, header=header, rows=rows,
                       raw_rows=raw_rows)


# ---------------------------------------------------------------------------
# Mapping
# ---------------------------------------------------------------------------

def guess_mapping(header: List[str]) -> Dict[str, Optional[int]]:
    """Auto-guess which column feeds each field. Case-insensitive; per
    field an exact header match wins over a substring hit; a column is
    claimed at most once (field order in _GUESS_KEYWORDS is priority)."""
    normalized = [h.strip().lower() for h in header]
    mapping: Dict[str, Optional[int]] = {key: None for key, _ in FIELDS}
    claimed: set = set()
    for fld, keywords in _GUESS_KEYWORDS:
        index = None
        for keyword in keywords:                     # exact pass
            for i, name in enumerate(normalized):
                if i not in claimed and name == keyword:
                    index = i
                    break
            if index is not None:
                break
        if index is None:                            # substring pass
            for keyword in keywords:
                for i, name in enumerate(normalized):
                    if i not in claimed and keyword in name:
                        index = i
                        break
                if index is not None:
                    break
        if index is not None:
            mapping[fld] = index
            claimed.add(index)
    return mapping


def apply_mapping(rows: List[List[str]],
                  mapping: Dict[str, Optional[int]]) -> List[Dict[str, str]]:
    """Project rows through the mapping: one dict per row with every
    field key present ('' where unmapped or the row is short). Values
    are stripped except manufacturer/model, which the library matches
    verbatim (trailing spaces are significant in QLC+ names)."""
    records = []
    for row in rows:
        record: Dict[str, str] = {}
        for fld, _label in FIELDS:
            index = mapping.get(fld)
            value = row[index] if index is not None and index < len(row) else ""
            record[fld] = value if fld in _VERBATIM_FIELDS else value.strip()
        records.append(record)
    return records


# ---------------------------------------------------------------------------
# Fixtures + resolution
# ---------------------------------------------------------------------------

def _parse_int(value: str, default: int, field_name: str) -> int:
    value = value.strip()
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        try:
            return int(float(value.replace(",", ".")))
        except ValueError:
            raise ValueError(f"{field_name} {value!r} is not a number") from None


def build_fixtures(records: List[Dict[str, str]]) -> Tuple[List[Fixture], List[str]]:
    """Turn mapped records into Fixture objects, mirroring the
    fixture-list CSV import: a single synthesized mode (upgraded by
    resolve_fixtures where the library knows the model), PAR default
    type, name defaulting to the model. Universe/address default to 1
    when the sheet has no such column (the Fixtures tab flags the
    resulting overlaps). Returns (fixtures, errors); a bad row becomes
    an error string, never a silent drop. All-empty rows are skipped.
    """
    fixtures: List[Fixture] = []
    errors: List[str] = []
    for i, record in enumerate(records, start=1):
        if not any(value.strip() for value in record.values()):
            continue
        manufacturer = record.get("manufacturer", "")
        model = record.get("model", "")
        if not manufacturer.strip() or not model.strip():
            errors.append(f"Row {i}: manufacturer and model are required")
            continue
        try:
            universe = _parse_int(record.get("universe", ""), 1, "universe")
            address = _parse_int(record.get("address", ""), 1, "address")
        except ValueError as e:
            errors.append(f"Row {i}: {e}")
            continue
        mode = record.get("mode", "") or "Default"
        fixtures.append(Fixture(
            universe=universe,
            address=address,
            manufacturer=manufacturer,
            model=model,
            name=record.get("name", "") or model.strip(),
            group=record.get("group", ""),
            layer=record.get("position", ""),
            current_mode=mode,
            available_modes=[FixtureMode(name=mode, channels=1)],
            type="PAR",
            # A venue table carries no orientation/height; leave the
            # group-default flags on so the target config's groups
            # position the fixtures.
        ))
    return fixtures, errors


def resolve_fixtures(fixtures: List[Fixture]) -> ResolutionReport:
    """Run the imported fixtures through the EXISTING resolution
    pipeline (utils/fixture_io.resolve_modes_from_library): synthesized
    modes are swapped for the real definition's mode list where the
    library knows the model. The report says which models resolved and
    which are missing (those keep the synthesized mode - visible, not
    dropped)."""
    from utils.fixture_io import resolve_modes_from_library
    from utils.fixture_library import get_definition

    warnings = resolve_modes_from_library(fixtures)
    resolved: List[Tuple[str, str]] = []
    missing: List[Tuple[str, str]] = []
    for manufacturer, model in sorted({(f.manufacturer, f.model)
                                       for f in fixtures}):
        if get_definition(manufacturer, model) is not None:
            resolved.append((manufacturer, model))
        else:
            missing.append((manufacturer, model))
    return ResolutionReport(warnings=warnings, resolved=resolved,
                            missing=missing)
