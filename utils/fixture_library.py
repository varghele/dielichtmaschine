# utils/fixture_library.py
"""Single source of truth for fixture-definition discovery, parsing, caching.

Phase 0 of the GDTF integration plan (docs/gdtf-integration-plan.md).
Before this module existed, QXF XML was parsed in five separate places and
the QLC+ library search paths were duplicated five times, with diverging
path lists and diverging duplicate-resolution order. Everything now funnels
through here:

- :func:`fixture_search_dirs` is the one list of search directories
  (bundled ``custom_fixtures/`` first, then the platform QLC+ dirs; the
  union of every variant the old implementations used).
- :func:`parse_fixture_file` is the one QXF parse, producing the canonical
  :class:`FixtureDefinition`.
- :func:`get_definition` / :func:`find_fixture_file` are the one
  (manufacturer, model) lookup, first-match-wins in search-dir priority
  order, with positive and negative caching.
- :meth:`FixtureDefinition.to_legacy_dict` reproduces the historical dict
  shape consumed by ``get_channels_by_property`` and the export/DMX paths,
  minus one known wart: the old parser's ``.//Channel`` XPath also swept up
  the per-mode ``<Channel Number=..>`` reference elements, so legacy dicts
  carried junk ``{'name': None, ...}`` channel entries. The canonical model
  keeps only real channel definitions; every consumer matches channels by
  name, so the junk entries were unreachable.

Fixture identity is the verbatim ``(manufacturer, model)`` string pair.
QLC+ model names can carry trailing spaces; nothing here strips or
normalises them.

The parsed XML root stays available on :attr:`FixtureDefinition.root` for
the analysis passes that read QXF details beyond the structured fields
(capability detection for the renderer, the visualizer payload parse).
They share this module's discovery, parse, and cache instead of their own.

GDTF (Phase 1) plugs in as a second producer of :class:`FixtureDefinition`;
consumers of this module are format-agnostic.
"""

from __future__ import annotations

import os
import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Dict, Iterator, List, Optional, Set, Tuple

from utils.gdtf_data import GdtfData  # noqa: F401  (typing for FixtureDefinition.gdtf)

QLC_FIXTURE_NS = 'http://www.qlcplus.org/FixtureDefinition'
_NS = {'': QLC_FIXTURE_NS}

# Color name to RGB mapping for standard colors (capability color inference).
COLOR_NAME_TO_RGB = {
    "White": "#FFFFFF",
    "Red": "#FF0000",
    "Green": "#00FF00",
    "Blue": "#0000FF",
    "Cyan": "#00FFFF",
    "Magenta": "#FF00FF",
    "Yellow": "#FFFF00",
    "Amber": "#FFBF00",
    "Orange": "#FF7F00",
    "Purple": "#7F00FF",
    "Pink": "#FF007F",
    "UV": "#8000FF",
    "Lime": "#BFFF00",
}


# ---------------------------------------------------------------------------
# Canonical definition model
# ---------------------------------------------------------------------------

@dataclass
class CapabilityDef:
    """One <Capability> range of a channel."""
    min: int
    max: int
    preset: Optional[str]
    name: Optional[str]           # element text, verbatim (may be None)
    color: Optional[str] = None   # hex or resource string, when derivable
    has_color: bool = False       # tri-state fidelity: the legacy parser
                                  # could emit an explicit None color


@dataclass
class ChannelDef:
    """One global <Channel> definition."""
    name: str
    preset: Optional[str]
    group: Optional[str]
    capabilities: List[CapabilityDef] = field(default_factory=list)


@dataclass
class ModeChannelRef:
    """One <Channel Number=..> reference inside a <Mode>."""
    number: int
    name: Optional[str]


@dataclass
class ModeDef:
    """One <Mode>: ordered channel refs plus <Head> cell groupings."""
    name: str
    channels: List[ModeChannelRef] = field(default_factory=list)
    heads: List[List[int]] = field(default_factory=list)


@dataclass
class FixtureDefinition:
    """Canonical fixture definition, format-agnostic.

    Produced by the QXF parse and by the GDTF loader (which transpiles
    into the same QLC-format XML, see utils/gdtf_loader.py). ``root``
    carries the (real or synthesized) QLC-format XML for analysis passes
    that need details beyond the structured fields.
    """
    path: str
    manufacturer: str
    model: str
    qlc_type: str                 # raw <Type> text ('' if absent)
    legacy_type: str              # determine_fixture_type() result
    layout: Tuple[int, int]       # <Physical><Layout> cell grid, (1, 1) default
    pan_max: float = 0.0          # <Physical><Focus PanMax>, 0 = not declared
    tilt_max: float = 0.0         # <Physical><Focus TiltMax>, 0 = not declared
    channels: List[ChannelDef] = field(default_factory=list)
    modes: List[ModeDef] = field(default_factory=list)
    root: Optional[ET.Element] = None
    source: str = 'qxf'           # 'qxf' | 'gdtf'
    gdtf_fixture_type_id: Optional[str] = None  # GDTF FixtureTypeID GUID
    gdtf: Optional['GdtfData'] = None
    """GDTF-native data (geometry tree, 3D model refs, photometrics,
    full-resolution physical values) - the richer lane that bypasses the
    transpiled channel model. None for .qxf-sourced definitions; see
    utils/gdtf_data.py."""

    @property
    def key(self) -> Tuple[str, str]:
        return (self.manufacturer, self.model)

    def mode(self, mode_name: str) -> Optional[ModeDef]:
        return next((m for m in self.modes if m.name == mode_name), None)

    def to_legacy_dict(self) -> dict:
        """The historical fixture-definition dict shape.

        Consumed by get_channels_by_property, the to_xml exporters, the
        live DMX channel map, and detect_fixture_group_capabilities.
        """
        return {
            'manufacturer': self.manufacturer,
            'model': self.model,
            'physical': {'pan_max': self.pan_max, 'tilt_max': self.tilt_max},
            'channels': [
                {
                    'name': ch.name,
                    'preset': ch.preset,
                    'group': ch.group,
                    'capabilities': [
                        (
                            {'min': c.min, 'max': c.max, 'preset': c.preset,
                             'name': c.name, 'color': c.color}
                            if c.has_color else
                            {'min': c.min, 'max': c.max, 'preset': c.preset,
                             'name': c.name}
                        )
                        for c in ch.capabilities
                    ],
                }
                for ch in self.channels
            ],
            'modes': [
                {
                    'name': m.name,
                    'channels': [
                        {'number': ref.number, 'name': ref.name}
                        for ref in m.channels
                    ],
                }
                for m in self.modes
            ],
        }

    def summary(self) -> dict:
        """The browser-dialog details shape."""
        return {
            'manufacturer': self.manufacturer,
            'model': self.model,
            'type': self.legacy_type,
            'modes': [(m.name, len(m.channels)) for m in self.modes],
        }


# ---------------------------------------------------------------------------
# XML helpers (namespaced first, bare fallback)
# ---------------------------------------------------------------------------

def _find(parent, path: str):
    el = parent.find(path, _NS)
    if el is None:
        el = parent.find(path)
    return el


def _findall(parent, path: str):
    elems = parent.findall(path, _NS)
    if not elems:
        elems = parent.findall(path)
    return elems


def _find_text(parent, path: str) -> Optional[str]:
    el = _find(parent, path)
    return el.text if el is not None else None


# ---------------------------------------------------------------------------
# QXF parse
# ---------------------------------------------------------------------------

def parse_fixture_file(path: str) -> FixtureDefinition:
    """Parse one fixture file (.qxf or .gdtf) into the canonical model.

    Raises on invalid files. GDTF archives are transpiled into the same
    QLC-format model by utils/gdtf_loader.py.
    """
    if path.lower().endswith('.gdtf'):
        from utils.gdtf_loader import parse_gdtf_file
        return parse_gdtf_file(path)
    return definition_from_qxf_root(ET.parse(path).getroot(), path)


def definition_from_qxf_root(root: ET.Element, path: str) -> FixtureDefinition:
    """Build the canonical model from a QLC-format XML root.

    Shared by the .qxf parse and the GDTF transpiler (which synthesizes
    an equivalent root), so both formats go through identical extraction.
    """
    manufacturer = _find_text(root, './/Manufacturer')
    model = _find_text(root, './/Model')
    if manufacturer is None or model is None:
        raise ValueError(f"missing Manufacturer/Model in {path}")

    channels: List[ChannelDef] = []
    for channel in _findall(root, 'Channel'):
        caps: List[CapabilityDef] = []
        for cap in _findall(channel, 'Capability'):
            cap_def = CapabilityDef(
                min=int(cap.get('Min')),
                max=int(cap.get('Max')),
                preset=cap.get('Preset'),
                name=cap.text,
            )
            # Color extraction, verbatim semantics of the historical parser
            # (including the Color2-present-but-Color1-taken wart).
            if cap.get('Color1') or cap.get('Color2'):
                cap_def.color = cap.get('Color1')
                cap_def.has_color = True
            elif cap.get('Res1'):
                cap_def.color = cap.get('Res1')
                cap_def.has_color = True
            elif cap.text and any(c in cap.text for c in COLOR_NAME_TO_RGB):
                for color_name, hex_value in COLOR_NAME_TO_RGB.items():
                    if color_name.lower() in cap.text.lower():
                        cap_def.color = hex_value
                        cap_def.has_color = True
                        break
            caps.append(cap_def)
        channels.append(ChannelDef(
            name=channel.get('Name'),
            preset=channel.get('Preset'),
            group=_find_text(channel, 'Group'),
            capabilities=caps,
        ))

    modes: List[ModeDef] = []
    for mode in _findall(root, 'Mode'):
        refs = [
            ModeChannelRef(number=int(ch.get('Number')), name=ch.text)
            for ch in _findall(mode, 'Channel')
        ]
        heads = [
            [int(ch.text) for ch in _findall(head, 'Channel')]
            for head in _findall(mode, 'Head')
        ]
        modes.append(ModeDef(name=mode.get('Name'), channels=refs, heads=heads))

    layout = (1, 1)
    pan_max = tilt_max = 0.0
    physical = _find(root, './/Physical')
    if physical is not None:
        layout_el = _find(physical, 'Layout')
        if layout_el is not None:
            layout = (int(layout_el.get('Width', 1)),
                      int(layout_el.get('Height', 1)))
        focus_el = _find(physical, 'Focus')
        if focus_el is not None:
            try:
                pan_max = float(focus_el.get('PanMax') or 0.0)
                tilt_max = float(focus_el.get('TiltMax') or 0.0)
            except (TypeError, ValueError):
                pan_max = tilt_max = 0.0

    return FixtureDefinition(
        path=path,
        manufacturer=manufacturer,
        model=model,
        qlc_type=_find_text(root, './/Type') or '',
        legacy_type=determine_fixture_type(root),
        layout=layout,
        pan_max=pan_max,
        tilt_max=tilt_max,
        channels=channels,
        modes=modes,
        root=root,
    )


# ---------------------------------------------------------------------------
# Search directories and file iteration
# ---------------------------------------------------------------------------

def project_custom_fixtures_dir() -> str:
    """The bundled custom_fixtures/ directory (repo root / PyInstaller dir)."""
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        'custom_fixtures')


def project_gdtf_fixtures_dir() -> str:
    """The gdtf_fixtures/ directory next to custom_fixtures/.

    Drop .gdtf files here to use them. (Settings > Fixture Libraries
    adds a per-user GDTF directory that ranks above this project-local
    folder; both are scanned.)
    """
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        'gdtf_fixtures')


def _user_library_dirs() -> Tuple[Optional[str], Optional[str]]:
    """The user's configured (gdtf_dir, qxf_dir) from Settings, or
    (None, None) when the settings store is unavailable (Qt missing in
    a stripped environment must never break definition lookup)."""
    try:
        from utils.app_settings import user_gdtf_dir, user_qxf_dir
        return user_gdtf_dir(), user_qxf_dir()
    except Exception:
        return None, None


def fixture_search_dirs() -> List[Tuple[str, str]]:
    """All fixture directories as (path, source) in priority order.

    source is 'user-gdtf' / 'user-qxf' for the user's own library
    directories (Settings > Fixture Libraries, utils/app_settings.py),
    'gdtf' for gdtf_fixtures/, 'bundled' for custom_fixtures/,
    'library' for QLC+ dirs. Priority: user GDTF > project
    gdtf_fixtures/ > bundled custom_fixtures/ > user QXF > platform
    QLC+ dirs - GDTF first because when both formats define the same
    (manufacturer, model) the GDTF definition wins (it carries strictly
    more information), and the user's directories beat the shipped ones
    within each format. The QLC+ list is the union of every variant the
    five pre-unification implementations used; non-existent directories
    are simply skipped by the scanners (the user defaults in app-data
    exist only once something is downloaded/copied there).
    """
    user_gdtf, user_qxf = _user_library_dirs()

    dirs: List[Tuple[str, str]] = []
    if user_gdtf and os.path.exists(user_gdtf):
        dirs.append((user_gdtf, 'user-gdtf'))
    gdtf = project_gdtf_fixtures_dir()
    if os.path.exists(gdtf):
        dirs.append((gdtf, 'gdtf'))
    custom = project_custom_fixtures_dir()
    if os.path.exists(custom):
        dirs.append((custom, 'bundled'))
    if user_qxf and os.path.exists(user_qxf):
        dirs.append((user_qxf, 'user-qxf'))

    if sys.platform.startswith('linux'):
        dirs.append((os.path.expanduser('~/.qlcplus/Fixtures'), 'library'))
        dirs.append((os.path.expanduser('~/.qlcplus/fixtures'), 'library'))
        dirs.append(('/usr/share/qlcplus/Fixtures', 'library'))
        dirs.append(('/usr/share/qlcplus/fixtures', 'library'))
    elif sys.platform == 'win32':
        dirs.append((os.path.join(os.path.expanduser('~'), 'QLC+', 'Fixtures'), 'library'))
        dirs.append(('C:\\QLC+\\Fixtures', 'library'))
        dirs.append(('C:\\QLC+5\\Fixtures', 'library'))
    elif sys.platform == 'darwin':
        dirs.append((os.path.expanduser('~/Library/Application Support/QLC+/Fixtures'), 'library'))
        dirs.append((os.path.expanduser('~/Library/Application Support/QLC+/fixtures'), 'library'))
        dirs.append(('/Applications/QLC+.app/Contents/Resources/Fixtures', 'library'))

    return dirs


FIXTURE_FILE_EXTENSIONS = ('.qxf', '.gdtf')


def iter_fixture_files(dirs: Optional[List[Tuple[str, str]]] = None) -> Iterator[Tuple[str, str]]:
    """Yield (path, source) for every fixture file reachable from the
    search dirs (.qxf and .gdtf)."""
    if dirs is None:
        dirs = fixture_search_dirs()
    for dir_path, source in dirs:
        if not os.path.exists(dir_path):
            continue
        for walk_root, _subdirs, files in os.walk(dir_path):
            for fname in files:
                if fname.lower().endswith(FIXTURE_FILE_EXTENSIONS):
                    yield os.path.join(walk_root, fname), source


def all_fixture_files() -> List[dict]:
    """Every reachable .qxf as the browser-dialog dict shape.

    manufacturer is the containing directory's basename and model the file
    stem (display hints only; the authoritative strings come from the parse).
    """
    entries = []
    for path, source in iter_fixture_files():
        entries.append({
            'manufacturer': os.path.basename(os.path.dirname(path)),
            'model': os.path.splitext(os.path.basename(path))[0],
            'path': path,
            'source': source,
        })
    return entries


# ---------------------------------------------------------------------------
# (manufacturer, model) index and definition cache
# ---------------------------------------------------------------------------
#
# First match wins, in fixture_search_dirs() priority order (bundled
# custom_fixtures/ beats the QLC+ library). Header reads are incremental:
# a lookup scans only until it finds its target, remembering every header
# it saw on the way, so later lookups resume instead of rescanning.

_path_index: Dict[Tuple[str, str], Optional[str]] = {}
_scanned_paths: Set[str] = set()
_full_scan_done = False
_definition_cache: Dict[Tuple[str, str], Optional[FixtureDefinition]] = {}


def clear_library_cache() -> None:
    """Drop all discovery and parse caches (after fixture files change)."""
    global _full_scan_done
    _path_index.clear()
    _scanned_paths.clear()
    _definition_cache.clear()
    _qxf_twin_cache.clear()
    _full_scan_done = False


def _read_header(path: str) -> Tuple[Optional[str], Optional[str]]:
    """Cheap (manufacturer, model) read, early exit; format-dispatched."""
    if path.lower().endswith('.gdtf'):
        return _read_gdtf_header(path)
    mfr = model = None
    try:
        for _event, elem in ET.iterparse(path, events=('end',)):
            tag = elem.tag.rsplit('}', 1)[-1]
            if tag == 'Manufacturer':
                mfr = elem.text
            elif tag == 'Model':
                model = elem.text
            if mfr is not None and model is not None:
                break
    except (ET.ParseError, OSError):
        return None, None
    return mfr, model


def _read_gdtf_header(path: str) -> Tuple[Optional[str], Optional[str]]:
    """(Manufacturer, Name) from a .gdtf's description.xml, without pygdtf.

    GDTF identity for library purposes is (Manufacturer, Name); Name is
    the model string.
    """
    import zipfile
    try:
        with zipfile.ZipFile(path) as archive:
            with archive.open('description.xml') as fh:
                for _event, elem in ET.iterparse(fh, events=('start',)):
                    if elem.tag.rsplit('}', 1)[-1] == 'FixtureType':
                        return elem.get('Manufacturer'), elem.get('Name')
    except (zipfile.BadZipFile, KeyError, ET.ParseError, OSError):
        return None, None
    return None, None


def find_fixture_file(manufacturer: str, model: str) -> Optional[str]:
    """Path of the winning .qxf for (manufacturer, model), or None."""
    global _full_scan_done
    key = (manufacturer, model)
    if key in _path_index:
        return _path_index[key]
    if _full_scan_done:
        _path_index[key] = None
        return None

    for path, _source in iter_fixture_files():
        if path in _scanned_paths:
            continue
        _scanned_paths.add(path)
        header = _read_header(path)
        if header[0] is None or header[1] is None:
            continue
        _path_index.setdefault(header, path)
        if header == key:
            return path

    _full_scan_done = True
    _path_index.setdefault(key, None)
    return _path_index[key]


def get_definition(manufacturer: str, model: str) -> Optional[FixtureDefinition]:
    """Cached canonical definition for (manufacturer, model), or None."""
    key = (manufacturer, model)
    if key in _definition_cache:
        return _definition_cache[key]

    path = find_fixture_file(manufacturer, model)
    defn: Optional[FixtureDefinition] = None
    if path is not None:
        try:
            defn = parse_fixture_file(path)
        except ET.ParseError as e:
            print(f"Error parsing fixture file {path}: {e}")
        except Exception as e:
            print(f"Error processing fixture file {path}: {e}")

    _definition_cache[key] = defn
    return defn


def iter_definitions() -> Iterator[FixtureDefinition]:
    """Parse every reachable fixture file, first-wins on duplicate identity.

    Full-library sweep for scan-all consumers (workspace import). Parse
    failures are reported and skipped, matching the historical behaviour.
    """
    seen: Set[Tuple[str, str]] = set()
    for path, _source in iter_fixture_files():
        try:
            defn = parse_fixture_file(path)
        except Exception as e:
            print(f"Error parsing fixture file {path}: {e}")
            continue
        if defn.key in seen:
            continue
        seen.add(defn.key)
        yield defn


# ---------------------------------------------------------------------------
# QLC+ interop: companion .qxf for GDTF-sourced definitions
# ---------------------------------------------------------------------------
#
# QLC+ has no GDTF import. A GDTF-sourced FixtureDefinition carries a
# synthesized QLC-format root, so serializing it yields a .qxf that QLC+
# can load; the .qxw exporter writes one next to the workspace for every
# GDTF fixture that has no same-identity .qxf in the library.

_qxf_twin_cache: Dict[Tuple[str, str], Optional[str]] = {}


def find_qxf_twin(manufacturer: str, model: str) -> Optional[str]:
    """Path of a real .qxf for this identity, ignoring .gdtf files.

    Unlike :func:`find_fixture_file` (format-agnostic, GDTF first), this
    answers the interop question "does QLC+'s own library already know
    this fixture". Memoized; cleared with :func:`clear_library_cache`.
    """
    key = (manufacturer, model)
    if key in _qxf_twin_cache:
        return _qxf_twin_cache[key]
    result = None
    for path, _source in iter_fixture_files():
        if not path.lower().endswith('.qxf'):
            continue
        header = _read_header(path)
        if header == key:
            result = path
            break
    _qxf_twin_cache[key] = result
    return result


def serialize_definition_to_qxf(defn: FixtureDefinition) -> str:
    """QLC+ .qxf file text for a definition's (real or synthesized) root."""
    if defn.root is None:
        raise ValueError(f"definition for {defn.key} carries no XML root")
    import xml.dom.minidom as minidom
    ET.register_namespace('', QLC_FIXTURE_NS)
    rough = ET.tostring(defn.root, encoding='unicode')
    pretty = minidom.parseString(rough).toprettyxml(indent=' ')
    # Drop minidom's XML declaration line; emit QLC+'s header instead.
    body = '\n'.join(
        line for line in pretty.split('\n')[1:] if line.strip()
    )
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<!DOCTYPE FixtureDefinition>\n'
            f'{body}\n')


def companion_qxf_filename(manufacturer: str, model: str) -> str:
    """QLC+-convention filename (Manufacturer-Model.qxf, sanitized)."""
    raw = f"{manufacturer}-{model}"
    safe = re.sub(r'[^A-Za-z0-9._-]+', '-', raw).strip('-')
    return f"{safe}.qxf"


# ---------------------------------------------------------------------------
# Legacy 6-string type classifier (moved verbatim from utils/fixture_utils.py;
# fixture_utils re-exports it for the existing import sites)
# ---------------------------------------------------------------------------

def determine_fixture_type(fixture_def):
    """
    Determine fixture type based on its channels across all modes
    Parameters:
        fixture_def: The fixture definition root element
    """
    ns = {'': QLC_FIXTURE_NS}

    def _find_element(parent, tag):
        """Find element with or without namespace."""
        elem = parent.find(tag, ns)
        if elem is None:
            elem = parent.find(tag)
        return elem

    # First check the XML Type tag for explicit type hints
    type_elem = _find_element(fixture_def, './/Type')
    xml_type = type_elem.text.lower() if type_elem is not None and type_elem.text else ""

    # Check for layout (indicates multi-segment fixture)
    physical = _find_element(fixture_def, './/Physical')
    layout_width = 1
    if physical is not None:
        layout = _find_element(physical, 'Layout')
        if layout is not None:
            layout_width = int(layout.get('Width', 1))

    # Detect if this is an LED bar type from XML (may be overridden by channel analysis)
    is_led_bar_type = 'led bar' in xml_type or 'sunstrip' in xml_type

    # Initialize sets for channel types
    movement_channels = set()
    color_channels = set()
    dimmer_channels = set()

    # Get all channels and their properties
    for channel in fixture_def.findall('.//Channel', ns):
        channel_name = channel.get('Name', '')

        # Check for movement channels
        if 'Pan' in channel_name or 'Tilt' in channel_name:
            movement_channels.add(channel_name)

        # Check for color channels
        if any(color in channel_name for color in ['Red', 'Green', 'Blue', 'White']):
            color_channels.add(channel_name)

        # Check for dimmer
        if 'Dimmer' in channel_name:
            dimmer_channels.add(channel_name)

    # Determine fixture type based on capabilities
    has_movement = len(movement_channels) > 0
    has_rgbw = all(any(color in ch for ch in color_channels)
                   for color in ['Red', 'Green', 'Blue', 'White'])
    has_rgb = all(any(color in ch for ch in color_channels)
                  for color in ['Red', 'Green', 'Blue'])
    has_dimmer = len(dimmer_channels) > 0

    # Check for individual pixel control (e.g., "Red LED 1", "Red LED 2", etc.)
    # This indicates a PIXELBAR with per-segment RGBW control
    pixel_channels = [ch for ch in color_channels
                      if re.search(r'(Red|Green|Blue|White)\s+(LED\s+)?\d+', ch)]
    has_individual_pixels = len(pixel_channels) >= 4  # At least one RGBW segment

    # Count how many unique segment numbers we have
    segment_numbers = set()
    for ch in pixel_channels:
        match = re.search(r'\d+', ch)
        if match:
            segment_numbers.add(match.group())
    num_pixel_segments = len(segment_numbers)

    # Count total RGB/RGBW channel sets to distinguish WASH from PIXELBAR
    # A WASH has ONE set (Red, Green, Blue), a PIXELBAR has MULTIPLE sets
    # Count by looking for base color channels without numbers
    base_red_channels = [ch for ch in color_channels if 'Red' in ch and not re.search(r'\d+', ch)]
    base_green_channels = [ch for ch in color_channels if 'Green' in ch and not re.search(r'\d+', ch)]
    base_blue_channels = [ch for ch in color_channels if 'Blue' in ch and not re.search(r'\d+', ch)]
    has_single_rgb_set = (len(base_red_channels) == 1 and
                          len(base_green_channels) == 1 and
                          len(base_blue_channels) == 1)

    # Priority-based fixture type detection:
    if has_movement:
        return "MH"  # Moving Head
    elif has_individual_pixels and num_pixel_segments > 1:
        # Has individual pixel channels for multiple segments (e.g., "Red LED 1-12")
        # This is a PIXELBAR - multi-segment bar with per-segment RGBW control
        return "PIXELBAR"
    elif is_led_bar_type and has_single_rgb_set and (has_rgb or has_rgbw):
        # XML Type says "LED Bar" but only has ONE set of RGB channels
        # This is a WASH, not a PIXELBAR (Layout describes physical LEDs, not DMX segments)
        return "WASH"
    elif is_led_bar_type and num_pixel_segments > 1:
        # XML Type says "LED Bar" with multiple numbered pixel channels
        return "PIXELBAR"
    elif is_led_bar_type and (has_rgb or has_rgbw):
        # XML Type says "LED Bar" with RGB/RGBW - default to BAR
        return "BAR"
    elif layout_width > 1 and num_pixel_segments > 1:
        # Multi-segment fixture with actual per-pixel DMX control
        return "PIXELBAR"
    elif is_led_bar_type or (layout_width > 1 and not (has_rgb or has_rgbw)):
        # LED bar type or multi-segment WITHOUT RGB - likely a sunstrip (dimmer-only)
        return "SUNSTRIP"
    elif (has_rgbw or has_rgb) and has_dimmer:
        # RGB/RGBW fixture with dimmer - WASH fixture
        return "WASH"
    elif has_rgb or has_rgbw:
        # RGB/RGBW without clear classification - default to BAR
        return "BAR"
    else:
        return "PAR"  # Default type
