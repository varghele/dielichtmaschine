# utils/gdtf_loader.py
"""GDTF fixture-definition import (Phase 1 of docs/gdtf-integration-plan.md).

Strategy: transpile, don't fork. A ``.gdtf`` file (DIN SPEC 15800, parsed
via ``pygdtf``) is mapped onto an in-memory QLC-format ``FixtureDefinition``
XML root, then run through the exact same canonical parse as a ``.qxf``
file (:func:`utils.fixture_library.definition_from_qxf_root`). Every
downstream consumer - the export/DMX preset resolution, renderer capability
detection, the visualizer payload parse, the legacy type classifier - sees
a normal definition and needs no GDTF awareness.

The mapping:

- GDTF attributes -> QLC channel ``Preset`` strings plus a ``<Group>``
  child, so both the preset-based and the group-based downstream paths
  work (`utils/sublane_presets.py`, `get_channels_by_property`,
  `dmx_manager.FixtureChannelMap`).
- Multi-byte channels (Offset="n,m") -> coarse + ``...Fine`` QLC channels.
- ChannelFunctions / ChannelSets -> ``<Capability Min Max>`` ranges,
  scaled to the coarse byte. Wheel-linked functions resolve slot names
  and slot colors (CIE xyY -> sRGB hex in ``Res1``) so color wheels work.
- Geometry-reference instances (pixel bars, multi-head fixtures) ->
  per-instance channel names ("Red 1", "Red 2", ...) plus ``<Head>``
  blocks and a ``<Physical><Layout>`` grid.
- Beam geometry -> ``<Physical><Lens Degrees...>`` + ``<Bulb Lumens>``
  (real photometric data; replaces the power-estimate heuristic).
- Pan/Tilt physical ranges -> ``<Physical><Focus PanMax TiltMax>``.

The synthesized root is also the Phase 2 QLC+ interop path: serializing
it produces a companion ``.qxf`` for fixtures QLC+ doesn't know.

GDTF-only data (fixture type GUID, geometry tree, 3D model refs) rides on
the returned :class:`FixtureDefinition` for later phases.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Dict, List, Optional, Tuple

from utils.fixture_library import QLC_FIXTURE_NS, FixtureDefinition, definition_from_qxf_root


def _q(tag: str) -> str:
    return f'{{{QLC_FIXTURE_NS}}}{tag}'


# ---------------------------------------------------------------------------
# GDTF attribute -> (QLC preset, QLC group, display name)
# ---------------------------------------------------------------------------
# Attribute names per DIN SPEC 15800 Annex A. Trailing wheel/emitter indices
# are normalized away before lookup (Gobo2 -> Gobo(n), ColorAdd_R stays).

_ATTR_MAP: Dict[str, Tuple[Optional[str], str, str]] = {
    # intensity
    'Dimmer':        ('IntensityDimmer', 'Intensity', 'Dimmer'),
    # position
    'Pan':           ('PositionPan', 'Pan', 'Pan'),
    'Tilt':          ('PositionTilt', 'Tilt', 'Tilt'),
    'PanRotate':     ('PositionPan', 'Pan', 'Pan Rotate'),
    'TiltRotate':    ('PositionTilt', 'Tilt', 'Tilt Rotate'),
    # additive color mixing
    'ColorAdd_R':    ('IntensityRed', 'Colour', 'Red'),
    'ColorAdd_G':    ('IntensityGreen', 'Colour', 'Green'),
    'ColorAdd_B':    ('IntensityBlue', 'Colour', 'Blue'),
    'ColorAdd_W':    ('IntensityWhite', 'Colour', 'White'),
    'ColorAdd_WW':   ('IntensityWhite', 'Colour', 'Warm White'),
    'ColorAdd_CW':   ('IntensityWhite', 'Colour', 'Cold White'),
    'ColorAdd_A':    ('IntensityAmber', 'Colour', 'Amber'),
    'ColorAdd_UV':   ('IntensityUV', 'Colour', 'UV'),
    'ColorAdd_L':    ('IntensityLime', 'Colour', 'Lime'),
    'ColorAdd_I':    ('IntensityIndigo', 'Colour', 'Indigo'),
    'ColorAdd_C':    ('IntensityCyan', 'Colour', 'Cyan'),
    'ColorAdd_M':    ('IntensityMagenta', 'Colour', 'Magenta'),
    'ColorAdd_Y':    ('IntensityYellow', 'Colour', 'Yellow'),
    # subtractive color mixing
    'ColorSub_C':    ('IntensityCyan', 'Colour', 'Cyan'),
    'ColorSub_M':    ('IntensityMagenta', 'Colour', 'Magenta'),
    'ColorSub_Y':    ('IntensityYellow', 'Colour', 'Yellow'),
    # color temperature correction
    'CTO':           ('ColorCTOMixer', 'Colour', 'CTO'),
    'CTC':           ('ColorCTCMixer', 'Colour', 'CTC'),
    'CTB':           ('ColorCTBMixer', 'Colour', 'CTB'),
    # wheels (index-normalized: Color1/Color2 -> Color(n))
    'Color(n)':              ('ColorMacro', 'Colour', 'Color Wheel'),
    'Color(n)WheelSpin':     ('ColorWheel', 'Colour', 'Color Wheel Rotation'),
    'Color(n)WheelIndex':    ('ColorWheel', 'Colour', 'Color Wheel Index'),
    'Gobo(n)':               ('GoboWheel', 'Gobo', 'Gobo Wheel'),
    'Gobo(n)SelectShake':    ('GoboWheel', 'Gobo', 'Gobo Shake'),
    'Gobo(n)WheelSpin':      ('GoboWheel', 'Gobo', 'Gobo Wheel Rotation'),
    'Gobo(n)Pos':            ('GoboIndex', 'Gobo', 'Gobo Rotation'),
    'Gobo(n)PosRotate':      ('GoboIndex', 'Gobo', 'Gobo Rotation'),
    # beam
    'Zoom':          ('BeamZoomSmallBig', 'Beam', 'Zoom'),
    'Focus(n)':      ('BeamFocusNearFar', 'Beam', 'Focus'),
    'Iris':          ('BeamIris', 'Beam', 'Iris'),
    'Frost(n)':      ('BeamFrost', 'Beam', 'Frost'),
    'Prism(n)':      (None, 'Prism', 'Prism'),
    'Prism(n)PosRotate': ('PrismRotationSlowFast', 'Prism', 'Prism Rotation'),
    'Prism(n)Pos':   ('PrismRotationSlowFast', 'Prism', 'Prism Rotation'),
    # shutter / strobe
    'Shutter(n)':            ('ShutterStrobeSlowFast', 'Shutter', 'Strobe'),
    'Shutter(n)Strobe':      ('ShutterStrobeSlowFast', 'Shutter', 'Strobe'),
    'Shutter(n)StrobePulse': ('ShutterStrobeSlowFast', 'Shutter', 'Strobe Pulse'),
    'Shutter(n)StrobeRandom': ('ShutterStrobeRandom', 'Shutter', 'Strobe Random'),
    # speed
    'PanTiltSpeed':  ('SpeedPanTiltSlowFast', 'Speed', 'Pan/Tilt Speed'),
    'PanTiltTime':   ('SpeedPanTiltSlowFast', 'Speed', 'Pan/Tilt Time'),
    # control
    'NoFeature':     ('NoFunction', 'Nothing', 'No Function'),
}

_FINE_CAPABLE = {
    'IntensityDimmer', 'IntensityRed', 'IntensityGreen', 'IntensityBlue',
    'IntensityWhite', 'IntensityAmber', 'IntensityUV', 'IntensityLime',
    'IntensityIndigo', 'IntensityCyan', 'IntensityMagenta', 'IntensityYellow',
    'PositionPan', 'PositionTilt', 'ColorWheel', 'GoboWheel', 'GoboIndex',
    'IntensityMasterDimmer',
}

# Attributes whose per-instance repetition marks a cell/head group
_CELL_ATTRS = {
    'IntensityRed', 'IntensityGreen', 'IntensityBlue', 'IntensityWhite',
    'IntensityAmber', 'IntensityUV', 'IntensityLime', 'IntensityDimmer',
}


def _normalize_attribute(name: str) -> str:
    """Collapse wheel/emitter indices: Gobo2PosRotate -> Gobo(n)PosRotate."""
    import re
    for base in ('Color', 'Gobo', 'Prism', 'Shutter', 'Focus', 'Frost'):
        m = re.match(rf'^{base}(\d+)(.*)$', name)
        if m:
            return f'{base}(n){m.group(2)}'
    return name


def _map_attribute(name: str) -> Tuple[Optional[str], str, str]:
    """(preset, group, display name) for a GDTF attribute name."""
    if name in _ATTR_MAP:
        return _ATTR_MAP[name]
    normalized = _normalize_attribute(name)
    if normalized in _ATTR_MAP:
        return _ATTR_MAP[normalized]
    # Unknown attribute: no preset, effect group, raw name as display name.
    return (None, 'Effect', name)


# ---------------------------------------------------------------------------
# CIE xyY -> sRGB hex (for wheel slot colors)
# ---------------------------------------------------------------------------

def cie_xyy_to_hex(x: float, y: float, Y: float) -> str:
    """Convert CIE 1931 xyY (GDTF wheel slot color) to an sRGB hex string.

    GDTF stores Y as luminance 0..100. Falls back to white for degenerate
    input (y == 0 or all zeros), which matches how previz tools treat
    missing slot colors.
    """
    if y is None or x is None or Y is None or y <= 0:
        return '#FFFFFF'
    Yn = Y / 100.0 if Y > 1.0 else Y
    if Yn <= 0:
        return '#FFFFFF'
    X = (x * Yn) / y
    Z = ((1.0 - x - y) * Yn) / y

    # sRGB D65 matrix
    r = 3.2406 * X - 1.5372 * Yn - 0.4986 * Z
    g = -0.9689 * X + 1.8758 * Yn + 0.0415 * Z
    b = 0.0557 * X - 0.2040 * Yn + 1.0570 * Z

    def _gamma(c: float) -> int:
        c = max(0.0, min(1.0, c))
        c = 1.055 * (c ** (1 / 2.4)) - 0.055 if c > 0.0031308 else 12.92 * c
        return max(0, min(255, round(c * 255)))

    # Normalize so the brightest component saturates (slot colors are
    # chromaticity statements, not absolute luminance).
    peak = max(r, g, b)
    if peak > 1.0:
        r, g, b = r / peak, g / peak, b / peak
    return '#{:02X}{:02X}{:02X}'.format(_gamma(r), _gamma(g), _gamma(b))


# ---------------------------------------------------------------------------
# GDTF -> QLC XML synthesis
# ---------------------------------------------------------------------------

def _scale_to_byte(dmx_value) -> int:
    """Scale a pygdtf DmxValue to the coarse 0..255 byte."""
    value = getattr(dmx_value, 'value', 0) or 0
    byte_count = getattr(dmx_value, 'byte_count', 1) or 1
    if byte_count > 1:
        value >>= 8 * (byte_count - 1)
    return max(0, min(255, int(value)))


def _wheel_by_name(fixture_type, name: Optional[str]):
    if not name:
        return None
    for wheel in getattr(fixture_type, 'wheels', []) or []:
        if getattr(wheel, 'name', None) == str(name):
            return wheel
    return None


def _slot_color_hex(slot) -> Optional[str]:
    color = getattr(slot, 'color', None)
    if color is None:
        return None
    return cie_xyy_to_hex(getattr(color, 'x', None), getattr(color, 'y', None),
                          getattr(color, 'Y', None))


def _break_bases(mode) -> Dict[int, int]:
    """Absolute channel base per DMX break (flattened footprint order)."""
    bases: Dict[int, int] = {}
    base = 0
    for brk in sorted(getattr(mode, 'dmx_breaks', []) or [],
                      key=lambda b: getattr(b, 'dmx_break', 1)):
        break_id = getattr(brk, 'dmx_break', 1)
        bases[break_id] = base
        base += getattr(brk, 'channels_count', 0)
    return bases or {1: 0}


def _channel_functions(gdtf_channel):
    logical = (getattr(gdtf_channel, 'logical_channels', None) or [None])[0]
    if logical is None:
        return []
    return getattr(logical, 'channel_functions', []) or []


def _add_capability(parent: ET.Element, cap_min: int, cap_max: int,
                    text: str, preset: Optional[str] = None,
                    res1: Optional[str] = None) -> None:
    cap = ET.SubElement(parent, _q('Capability'))
    cap.set('Min', str(cap_min))
    cap.set('Max', str(cap_max))
    if preset:
        cap.set('Preset', preset)
    if res1:
        cap.set('Res1', res1)
    cap.text = text


def _emit_capabilities(chan_el: ET.Element, gdtf_channel, fixture_type,
                       qlc_group: str) -> None:
    """<Capability> ranges from ChannelFunctions / ChannelSets."""
    emitted = False
    for func in _channel_functions(gdtf_channel):
        f_from = _scale_to_byte(getattr(func, 'dmx_from', None))
        f_to = _scale_to_byte(getattr(func, 'dmx_to', None))
        if f_to < f_from:
            f_to = f_from
        func_attr = str(getattr(func, 'attribute', '') or '')
        func_name = getattr(func, 'name', None) or func_attr or 'Function'
        wheel = _wheel_by_name(fixture_type, getattr(func, 'wheel', None))

        channel_sets = [
            cs for cs in (getattr(func, 'channel_sets', []) or [])
            if getattr(cs, 'name', None)  # unnamed sets are spacing artifacts
        ]

        if wheel is not None and channel_sets:
            slots = getattr(wheel, 'wheel_slots', []) or []
            for cs in channel_sets:
                cs_from = _scale_to_byte(getattr(cs, 'dmx_from', None))
                cs_to = _scale_to_byte(getattr(cs, 'dmx_to', None))
                if cs_to < cs_from:
                    cs_to = cs_from
                slot_index = getattr(cs, 'wheel_slot_index', None)
                slot = None
                if slot_index is not None and 1 <= slot_index <= len(slots):
                    slot = slots[slot_index - 1]
                slot_name = getattr(cs, 'name', None) or (
                    getattr(slot, 'name', None) if slot is not None else None) or 'Slot'
                res1 = _slot_color_hex(slot) if slot is not None else None
                preset = None
                if qlc_group == 'Colour' and res1:
                    preset = 'ColorMacro'
                elif qlc_group == 'Gobo':
                    preset = 'GoboMacro'
                _add_capability(chan_el, cs_from, cs_to, slot_name,
                                preset=preset, res1=res1)
                emitted = True
        elif channel_sets:
            for cs in channel_sets:
                cs_from = _scale_to_byte(getattr(cs, 'dmx_from', None))
                cs_to = _scale_to_byte(getattr(cs, 'dmx_to', None))
                if cs_to < cs_from:
                    cs_to = cs_from
                preset = None
                if qlc_group == 'Prism' and 'prism' in str(getattr(cs, 'name', '')).lower():
                    preset = 'PrismEffectOn'
                _add_capability(chan_el, cs_from, cs_to,
                                str(getattr(cs, 'name', 'Range')), preset=preset)
                emitted = True
        else:
            preset = None
            if qlc_group == 'Prism' and func_attr.startswith('Prism') \
                    and 'Pos' not in func_attr and f_from > 0:
                preset = 'PrismEffectOn'
            _add_capability(chan_el, f_from, f_to, func_name, preset=preset)
            emitted = True

    if not emitted:
        _add_capability(chan_el, 0, 255, getattr(gdtf_channel, 'name', 'Range') or 'Range')


def _walk_geometries(nodes, visit):
    for node in nodes or []:
        visit(node)
        _walk_geometries(getattr(node, 'geometries', []) or [], visit)


def _collect_beams(fixture_type) -> list:
    import pygdtf
    beams = []
    _walk_geometries(getattr(fixture_type, 'geometries', []) or [],
                     lambda n: beams.append(n) if isinstance(n, pygdtf.GeometryBeam) else None)
    return beams


def _root_dimensions_mm(fixture_type) -> Optional[Tuple[float, float, float]]:
    """Width/Height/Depth in mm from the root geometry's model, if resolvable.

    GDTF model dimensions are meters: Length (X), Width (Y), Height (Z).
    QLC Dimensions are mm: Width (X), Height (Z vertical), Depth (Y).
    """
    geometries = getattr(fixture_type, 'geometries', []) or []
    if not geometries:
        return None
    model_name = getattr(geometries[0], 'model', None)
    if not model_name:
        return None
    for model in getattr(fixture_type, 'models', []) or []:
        if getattr(model, 'name', None) == str(model_name):
            length = float(getattr(model, 'length', 0) or 0)
            width = float(getattr(model, 'width', 0) or 0)
            height = float(getattr(model, 'height', 0) or 0)
            if length > 0 or width > 0 or height > 0:
                return (length * 1000.0, height * 1000.0, width * 1000.0)
    return None


def _physical_range(gdtf_channel) -> Tuple[float, float]:
    funcs = _channel_functions(gdtf_channel)
    if not funcs:
        return (0.0, 0.0)
    lows, highs = [], []
    for f in funcs:
        pf = getattr(getattr(f, 'physical_from', None), 'value', None)
        pt = getattr(getattr(f, 'physical_to', None), 'value', None)
        if pf is not None:
            lows.append(float(pf))
        if pt is not None:
            highs.append(float(pt))
    if not lows or not highs:
        return (0.0, 0.0)
    return (min(lows), max(highs))


def synthesize_qlc_root(fixture_type) -> ET.Element:
    """Build a QLC-format <FixtureDefinition> element tree from a pygdtf
    FixtureType. Namespaced exactly like a real .qxf parse."""
    root = ET.Element(_q('FixtureDefinition'))

    creator = ET.SubElement(root, _q('Creator'))
    ET.SubElement(creator, _q('Name')).text = 'QLC+ Show Creator GDTF import'
    ET.SubElement(creator, _q('Version')).text = str(
        getattr(fixture_type, 'data_version', '1.2'))
    ET.SubElement(root, _q('Manufacturer')).text = getattr(
        fixture_type, 'manufacturer', '') or ''
    ET.SubElement(root, _q('Model')).text = getattr(fixture_type, 'name', '') or ''

    # --- per-mode channel synthesis ------------------------------------
    # QLC has global channels shared by modes; GDTF channels are per-mode.
    # Synthesize globally-unique channel names ("Pan", "Red 1", "Red 1 Fine",
    # "Red 1 (8ch)" on cross-mode collisions with different semantics).
    channel_elements: Dict[str, ET.Element] = {}
    mode_specs = []  # (mode, [(abs_index, channel_name)], [head channel lists])
    any_pan = any_tilt = False
    pan_range = tilt_range = (0.0, 0.0)
    max_heads = 0

    for mode in getattr(fixture_type, 'dmx_modes', []) or []:
        bases = _break_bases(mode)
        entries: List[Tuple[int, str]] = []       # (absolute index, channel name)
        geometry_cells: Dict[str, List[int]] = {}  # geometry -> abs indices
        geometry_order: List[str] = []

        channels = list(getattr(mode, 'dmx_channels', []) or [])

        # First pass: count per-geometry repetition of cell attributes to
        # know which display names need instance numbering.
        attr_geometry_count: Dict[str, set] = {}
        for ch in channels:
            attr = str(getattr(ch, 'attribute', '') or '')
            geometry = str(getattr(ch, 'geometry', '') or '')
            preset, _group, _disp = _map_attribute(attr)
            if preset in _CELL_ATTRS:
                attr_geometry_count.setdefault(attr, set()).add(geometry)
        numbered_attrs = {a for a, gs in attr_geometry_count.items() if len(gs) > 1}
        geometry_index: Dict[str, int] = {}

        for ch in channels:
            offsets = getattr(ch, 'offset', None)
            if not offsets:
                continue  # virtual channel
            attr = str(getattr(ch, 'attribute', '') or '')
            geometry = str(getattr(ch, 'geometry', '') or '')
            preset, group, display = _map_attribute(attr)

            if attr in numbered_attrs:
                if geometry not in geometry_index:
                    geometry_index[geometry] = len(geometry_index) + 1
                display = f'{display} {geometry_index[geometry]}'

            base = bases.get(getattr(ch, 'dmx_break', 1), 0)
            coarse_index = base + (offsets[0] - 1)

            name = display
            # Cross-mode reuse: same name only if it's semantically the same
            # channel; otherwise disambiguate with the mode name.
            if name in channel_elements and \
                    channel_elements[name].get('Preset') != (preset or None):
                name = f'{display} ({getattr(mode, "name", "mode")})'

            if name not in channel_elements:
                chan_el = ET.SubElement(root, _q('Channel'))
                chan_el.set('Name', name)
                if preset:
                    chan_el.set('Preset', preset)
                ET.SubElement(chan_el, _q('Group')).text = group
                _emit_capabilities(chan_el, ch, fixture_type, group)
                channel_elements[name] = chan_el
            entries.append((coarse_index, name))

            # Track pan/tilt physical ranges for <Focus>
            if preset == 'PositionPan':
                any_pan = True
                low, high = _physical_range(ch)
                if (high - low) > (pan_range[1] - pan_range[0]):
                    pan_range = (low, high)
            elif preset == 'PositionTilt':
                any_tilt = True
                low, high = _physical_range(ch)
                if (high - low) > (tilt_range[1] - tilt_range[0]):
                    tilt_range = (low, high)

            # Fine byte(s)
            if len(offsets) > 1:
                fine_preset = f'{preset}Fine' if preset in _FINE_CAPABLE else None
                fine_name = f'{name} Fine'
                if fine_name not in channel_elements:
                    fine_el = ET.SubElement(root, _q('Channel'))
                    fine_el.set('Name', fine_name)
                    if fine_preset:
                        fine_el.set('Preset', fine_preset)
                    ET.SubElement(fine_el, _q('Group')).text = group
                    _add_capability(fine_el, 0, 255, f'{display} fine adjustment')
                    channel_elements[fine_name] = fine_el
                entries.append((base + (offsets[1] - 1), fine_name))

            # Cell grouping for <Head> synthesis
            if preset in _CELL_ATTRS and attr in numbered_attrs:
                if geometry not in geometry_cells:
                    geometry_cells[geometry] = []
                    geometry_order.append(geometry)
                geometry_cells[geometry].append(coarse_index)
                if len(offsets) > 1:
                    geometry_cells[geometry].append(base + (offsets[1] - 1))

        entries.sort(key=lambda e: e[0])
        heads = [sorted(geometry_cells[g]) for g in geometry_order] \
            if len(geometry_order) > 1 else []
        max_heads = max(max_heads, len(heads))
        mode_specs.append((mode, entries, heads))

    # --- fixture type ---------------------------------------------------
    has_cells = max_heads > 1
    if any_pan or any_tilt:
        qlc_type = 'Moving Head'
    elif has_cells:
        qlc_type = 'LED Bar (Pixels)'
    else:
        qlc_type = 'Color Changer'
    ET.SubElement(root, _q('Type')).text = qlc_type

    # --- modes -----------------------------------------------------------
    for mode, entries, heads in mode_specs:
        mode_el = ET.SubElement(root, _q('Mode'))
        mode_el.set('Name', getattr(mode, 'name', None) or 'Default')
        for index, name in entries:
            ch_el = ET.SubElement(mode_el, _q('Channel'))
            ch_el.set('Number', str(index))
            ch_el.text = name
        for head_channels in heads:
            head_el = ET.SubElement(mode_el, _q('Head'))
            for idx in head_channels:
                ET.SubElement(head_el, _q('Channel')).text = str(idx)

    # --- physical ---------------------------------------------------------
    physical = ET.SubElement(root, _q('Physical'))
    bulb = ET.SubElement(physical, _q('Bulb'))
    beams = _collect_beams(fixture_type)
    total_flux = sum(float(getattr(b, 'luminous_flux', 0) or 0) for b in beams)
    bulb.set('Type', 'LED')
    bulb.set('Lumens', str(int(total_flux)))
    bulb.set('ColourTemperature', str(int(
        float(getattr(beams[0], 'color_temperature', 0) or 0)) if beams else 0))

    dims = _root_dimensions_mm(fixture_type)
    dims_el = ET.SubElement(physical, _q('Dimensions'))
    dims_el.set('Weight', '0')
    dims_el.set('Width', str(int(dims[0])) if dims else '0')
    dims_el.set('Height', str(int(dims[1])) if dims else '0')
    dims_el.set('Depth', str(int(dims[2])) if dims else '0')

    lens = ET.SubElement(physical, _q('Lens'))
    lens.set('Name', 'Other')
    beam_angles = [float(getattr(b, 'beam_angle', 0) or 0) for b in beams if b]
    if beam_angles:
        lens.set('DegreesMin', str(min(beam_angles)))
        lens.set('DegreesMax', str(max(beam_angles)))
    else:
        lens.set('DegreesMin', '0')
        lens.set('DegreesMax', '0')

    focus = ET.SubElement(physical, _q('Focus'))
    focus.set('Type', 'Head' if (any_pan or any_tilt) else 'Fixed')
    focus.set('PanMax', str(int(pan_range[1] - pan_range[0])) if any_pan else '0')
    focus.set('TiltMax', str(int(tilt_range[1] - tilt_range[0])) if any_tilt else '0')

    if max_heads > 1:
        layout = ET.SubElement(physical, _q('Layout'))
        layout.set('Width', str(max_heads))
        layout.set('Height', '1')

    technical = ET.SubElement(physical, _q('Technical'))
    technical.set('PowerConsumption', '0')
    technical.set('DmxConnector', '5-pin')

    return root


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def parse_gdtf_file(path: str) -> FixtureDefinition:
    """Parse a .gdtf into the canonical FixtureDefinition.

    Raises on unreadable archives; callers (the fixture library) handle
    and report, same as for invalid .qxf files.
    """
    import pygdtf

    with pygdtf.FixtureType(path) as fixture_type:
        root = synthesize_qlc_root(fixture_type)
        defn = definition_from_qxf_root(root, path)
        defn.source = 'gdtf'
        defn.gdtf_fixture_type_id = getattr(fixture_type, 'fixture_type_id', None)
        return defn
