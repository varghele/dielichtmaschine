"""Fixture capability detection for the visualizer renderer.

Replaces the 6-string ``determine_fixture_type`` cascade with a richer
capability-based model. Reads a QXF fixture definition + a mode name and
produces a :class:`FixtureCapabilities` instance describing what the
fixture can do.

Phase A of the fixture-rewrite (see ``docs/fixture_taxonomy.md``). Phase B
will build the composable renderer on top of this; Phase D ports the
existing consumers (renderer dispatch, 2D icon, 3D preview, group
constraints, build_fixtures_payload) to switch on :class:`Chassis`
instead of the legacy ``fixture_type`` string.

The detection pass is preset-first: ``<Channel Preset="...">`` is the
ground truth, channel-name string matching is a last-resort fallback.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple


QLC_NS = {'': 'http://www.qlcplus.org/FixtureDefinition'}


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class Chassis(Enum):
    """Body shape — drives 2D icon, 3D mesh, group constraints."""
    PAR = "par"
    BAR = "bar"
    PANEL = "panel"
    MOVING_YOKE = "moving_yoke"
    SCANNER = "scanner"
    EFFECT = "effect"
    PARTICLE = "particle"
    LASER = "laser"
    OTHER = "other"


class MovementType(Enum):
    """From ``<Physical><Focus Type="...">``."""
    YOKE = "yoke"      # body rotates (typical moving head)
    MIRROR = "mirror"  # mirror reflects beam (scanner)
    BARREL = "barrel"  # rotating barrel scanner
    FIXED = "fixed"    # no movement


class ColorMixingMode(Enum):
    """Additive/subtractive color-channel layout."""
    RGB = "rgb"
    RGBW = "rgbw"
    RGBA = "rgba"
    RGBAW = "rgbaw"
    RGBWAUV = "rgbwauv"
    CMY = "cmy"
    HSL = "hsl"
    HSI = "hsi"
    HSV = "hsv"


# ---------------------------------------------------------------------------
# Sub-dataclasses
# ---------------------------------------------------------------------------


@dataclass
class Movement:
    type: MovementType
    pan_max_deg: float = 0.0
    tilt_max_deg: float = 0.0
    pan_channel: Optional[int] = None
    pan_fine_channel: Optional[int] = None
    tilt_channel: Optional[int] = None
    tilt_fine_channel: Optional[int] = None


@dataclass
class ColorMixing:
    mode: ColorMixingMode
    channels: Dict[str, int] = field(default_factory=dict)
    """Map of color-component name → mode-local channel index.

    Component names: ``red``, ``green``, ``blue``, ``white``, ``amber``,
    ``uv``, ``lime``, ``cyan``, ``magenta``, ``yellow``, ``hue``,
    ``saturation``, ``lightness``, ``intensity``, ``value``.
    """


@dataclass
class ColorWheelEntry:
    dmx_min: int
    dmx_max: int
    name: str
    hex_color: Optional[str] = None  # "#RRGGBB" if present


@dataclass
class ColorWheel:
    channel: int                       # mode-local channel index
    entries: List[ColorWheelEntry] = field(default_factory=list)


@dataclass
class GoboWheelEntry:
    dmx_min: int
    dmx_max: int
    name: str
    is_shake: bool = False
    svg_path: Optional[str] = None     # Res1 (e.g. "SGM/gobo00123.svg")


@dataclass
class GoboWheel:
    channel: int
    entries: List[GoboWheelEntry] = field(default_factory=list)
    rotation_channel: Optional[int] = None


@dataclass
class Prism:
    channel: int
    facets: int = 3                    # PrismEffectOn Res1 (integer string)
    rotation_channel: Optional[int] = None


@dataclass
class BeamShape:
    """Beam optics from ``<Physical><Lens>``."""
    min_deg: float = 0.0
    max_deg: float = 0.0

    @property
    def is_zoom(self) -> bool:
        return self.max_deg > 0 and self.min_deg != self.max_deg

    @property
    def has_optics(self) -> bool:
        return self.max_deg > 0


# ---------------------------------------------------------------------------
# Emitters (sealed-union style — discriminate by isinstance)
# ---------------------------------------------------------------------------


@dataclass
class Emitter:
    """Base class. Subclasses describe what the renderer iterates over."""


@dataclass
class PointEmitter(Emitter):
    """Single emission point at the chassis origin."""


@dataclass
class CellSegment:
    """One cell of a :class:`CellArray`. Channel indices are mode-local."""
    red_channel: Optional[int] = None
    green_channel: Optional[int] = None
    blue_channel: Optional[int] = None
    white_channel: Optional[int] = None
    amber_channel: Optional[int] = None
    uv_channel: Optional[int] = None
    dimmer_channel: Optional[int] = None
    channels: List[int] = field(default_factory=list)


@dataclass
class CellArray(Emitter):
    """``W*H`` individually-addressable cells (pixel bar, pixel matrix, sunstrip)."""
    width: int
    height: int
    cells: List[CellSegment] = field(default_factory=list)
    """Length ``width * height``, row-major (left-to-right, top-to-bottom)."""


@dataclass
class HeadDescriptor:
    """One head of a multi-head fixture, with its own movement and color."""
    offset_m: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    movement: Optional[Movement] = None
    color_mixing: Optional[ColorMixing] = None
    color_wheel: Optional[ColorWheel] = None
    dimmer_channel: Optional[int] = None
    gobo_wheel: Optional[GoboWheel] = None
    prism: Optional[Prism] = None
    channels: List[int] = field(default_factory=list)


@dataclass
class MultiHead(Emitter):
    """N sub-fixtures sharing one chassis (moving-head bar, spider, centipede)."""
    heads: List[HeadDescriptor] = field(default_factory=list)


@dataclass
class ParticlePlume(Emitter):
    """Hazer/smoke/fog. Renderer impl deferred to v2."""
    density_channel: Optional[int] = None


@dataclass
class LaserVector(Emitter):
    """ILDA-style laser. Renderer impl deferred to v2."""
    x_channel: Optional[int] = None
    y_channel: Optional[int] = None
    color_channel: Optional[int] = None
    pattern_channel: Optional[int] = None


# ---------------------------------------------------------------------------
# Main capability dataclass
# ---------------------------------------------------------------------------


@dataclass
class FixtureCapabilities:
    """Complete renderer-facing description of one mode of one fixture."""

    # Identity & classification
    chassis: Chassis
    qlc_type: str
    mode_name: str

    # Movement (chassis-level; per-head movement lives on HeadDescriptor)
    movement: Optional[Movement] = None

    # Color (chassis-level; per-head color lives on HeadDescriptor)
    color_mixing: Optional[ColorMixing] = None
    color_wheel: Optional[ColorWheel] = None

    # Intensity
    dimmer_channel: Optional[int] = None
    strobe_channel: Optional[int] = None
    iris_channel: Optional[int] = None
    frost_channel: Optional[int] = None
    focus_channel: Optional[int] = None
    zoom_channel: Optional[int] = None

    # Beam
    beam: BeamShape = field(default_factory=BeamShape)

    # Pattern / image
    gobo_wheel: Optional[GoboWheel] = None
    gobo2_wheel: Optional[GoboWheel] = None
    animation_wheel: bool = False
    prism: Optional[Prism] = None

    # Emitter
    emitter: Emitter = field(default_factory=PointEmitter)

    # Physical (meters; layout in segments)
    body_dims_m: Tuple[float, float, float] = (0.3, 0.3, 0.2)
    layout: Tuple[int, int] = (1, 1)
    power_consumption_w: float = 100.0
    lumens_estimate: float = 0.0

    # Total DMX channel count for this mode
    channel_count: int = 0


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


def detect_capabilities(
    qxf_root: ET.Element,
    mode_name: str,
) -> FixtureCapabilities:
    """Detect renderer capabilities for one mode of a QXF fixture.

    Args:
        qxf_root: The ``<FixtureDefinition>`` root element.
        mode_name: ``<Mode Name="...">`` to detect for.

    Returns:
        A populated :class:`FixtureCapabilities`. Falls back to safe
        defaults (PAR chassis + PointEmitter) if the mode is missing or
        the file is malformed.
    """
    qlc_type = _find_text(qxf_root, './/Type') or 'Other'

    # 1. Global channel definitions (Name → ChannelDef)
    channel_defs = _parse_channel_defs(qxf_root)

    # 2. Find the requested mode
    mode_elem = _find_mode(qxf_root, mode_name)
    if mode_elem is None:
        # Best-effort fallback: empty caps with chassis from type
        return FixtureCapabilities(
            chassis=_chassis_from_type(qlc_type, has_movement=False, has_cells=False, layout=(1, 1)),
            qlc_type=qlc_type,
            mode_name=mode_name,
        )

    # 3. Build mode channel layout: index → ChannelDef
    mode_channels = _parse_mode_channels(mode_elem, channel_defs)

    # 4. Physical: fixture-level + mode-level merge (mode wins)
    body_dims_m, layout, beam, focus_type, pan_max, tilt_max, power_w, lumens_qxf = \
        _parse_physical(qxf_root, mode_elem)

    # 5. Parse <Head> blocks and build the emitter first. Channels claimed by
    #    cells/heads belong to those scopes — they must be excluded from
    #    chassis-level detection so per-cell RGB isn't mistaken for a
    #    chassis-wide RGB mix.
    heads = _parse_heads(mode_elem)
    emitter = _build_emitter(
        heads=heads,
        mode_channels=mode_channels,
        layout=layout,
    )
    claimed = _claimed_channels(emitter)
    chassis_channels = [mc for mc in mode_channels if mc.index not in claimed]

    # 6. Detect chassis-level capabilities from unclaimed channels only
    movement = _detect_movement(chassis_channels, focus_type, pan_max, tilt_max)
    color_mixing = _detect_color_mixing(chassis_channels)
    color_wheel = _detect_color_wheel(chassis_channels)
    dimmer_channel = _find_first_preset(chassis_channels, _DIMMER_PRESETS, _DIMMER_NAMES)
    strobe_channel = _detect_strobe_channel(chassis_channels)
    iris_channel = _find_first_preset(chassis_channels, ('BeamIris',), ('iris',))
    frost_channel = _find_first_preset(chassis_channels, ('BeamFrost',), ('frost',))
    focus_channel = _find_first_preset(chassis_channels, ('BeamFocusNearFar', 'BeamFocusFarNear'), ('focus',))
    zoom_channel = _find_first_preset(chassis_channels, ('BeamZoomBigSmall', 'BeamZoomSmallBig'), ('zoom',))
    gobo_wheel, gobo2_wheel = _detect_gobo_wheels(chassis_channels)
    prism = _detect_prism(chassis_channels)

    # 7. Pick the chassis based on type + capability signals
    has_movement = movement is not None and movement.type != MovementType.FIXED
    has_cells = isinstance(emitter, CellArray) and (emitter.width > 1 or emitter.height > 1)
    chassis = _chassis_from_type(qlc_type, has_movement=has_movement, has_cells=has_cells, layout=layout)

    # 8. Lumens estimate (very rough — LED vs halogen efficiency)
    lumens = _estimate_lumens(lumens_qxf, power_w, channel_defs)

    return FixtureCapabilities(
        chassis=chassis,
        qlc_type=qlc_type,
        mode_name=mode_name,
        movement=movement,
        color_mixing=color_mixing,
        color_wheel=color_wheel,
        dimmer_channel=dimmer_channel,
        strobe_channel=strobe_channel,
        iris_channel=iris_channel,
        frost_channel=frost_channel,
        focus_channel=focus_channel,
        zoom_channel=zoom_channel,
        beam=beam,
        gobo_wheel=gobo_wheel,
        gobo2_wheel=gobo2_wheel,
        prism=prism,
        emitter=emitter,
        body_dims_m=body_dims_m,
        layout=layout,
        power_consumption_w=power_w,
        lumens_estimate=lumens,
        channel_count=len(mode_channels),
    )


# ---------------------------------------------------------------------------
# Internal: channel parsing
# ---------------------------------------------------------------------------


@dataclass
class _Capability:
    dmx_min: int
    dmx_max: int
    preset: Optional[str]
    name: str
    res1: Optional[str]
    res2: Optional[str]


@dataclass
class _ChannelDef:
    name: str
    preset: Optional[str]
    group: Optional[str]
    capabilities: List[_Capability]


@dataclass
class _ModeChannel:
    index: int                   # mode-local channel number (0-based)
    name: str                    # channel definition name
    defn: Optional[_ChannelDef]  # may be None for malformed files

    @property
    def preset(self) -> str:
        return (self.defn.preset if self.defn and self.defn.preset else '') or ''

    @property
    def preset_lower(self) -> str:
        return self.preset.lower()

    @property
    def name_lower(self) -> str:
        return self.name.lower()


def _parse_channel_defs(root: ET.Element) -> Dict[str, _ChannelDef]:
    defs: Dict[str, _ChannelDef] = {}
    for ch in _findall(root, './/Channel'):
        # Skip <Channel> elements that are *references* inside <Mode>/<Head>
        # (they have a Number attribute, the global ones don't).
        if ch.get('Number') is not None:
            continue
        name = ch.get('Name', '')
        if not name:
            continue
        preset = ch.get('Preset') or None
        group_elem = _find(ch, 'Group')
        group = group_elem.text if group_elem is not None and group_elem.text else None

        caps: List[_Capability] = []
        for cap in _findall(ch, 'Capability'):
            try:
                dmx_min = int(cap.get('Min', 0))
                dmx_max = int(cap.get('Max', 0))
            except (TypeError, ValueError):
                continue
            caps.append(_Capability(
                dmx_min=dmx_min,
                dmx_max=dmx_max,
                preset=cap.get('Preset') or None,
                name=(cap.text or '').strip(),
                res1=cap.get('Res1') or None,
                res2=cap.get('Res2') or None,
            ))
        defs[name] = _ChannelDef(name=name, preset=preset, group=group, capabilities=caps)
    return defs


def _find_mode(root: ET.Element, mode_name: str) -> Optional[ET.Element]:
    for mode in _findall(root, './/Mode'):
        if mode.get('Name') == mode_name:
            return mode
    return None


def _parse_mode_channels(
    mode: ET.Element,
    channel_defs: Dict[str, _ChannelDef],
) -> List[_ModeChannel]:
    """Return ``<Mode>`` channels sorted by Number, defaulting missing nums in-order."""
    by_index: Dict[int, _ModeChannel] = {}
    fallback_index = 0
    for ch in _findall(mode, 'Channel'):
        name = (ch.text or '').strip()
        if not name:
            continue
        num_str = ch.get('Number')
        if num_str is not None:
            try:
                idx = int(num_str)
            except ValueError:
                idx = fallback_index
                fallback_index += 1
        else:
            idx = fallback_index
            fallback_index += 1
        by_index[idx] = _ModeChannel(index=idx, name=name, defn=channel_defs.get(name))
    return [by_index[k] for k in sorted(by_index)]


def _parse_physical(
    root: ET.Element,
    mode: ET.Element,
) -> Tuple[Tuple[float, float, float], Tuple[int, int], BeamShape, str, float, float, float, float]:
    """Merge fixture-level + mode-level ``<Physical>`` (mode wins per-field).

    Returns (body_dims_m, layout, beam, focus_type, pan_max, tilt_max,
    power_w, lumens_from_qxf).
    """
    body_dims_m = (0.3, 0.3, 0.2)
    layout = (1, 1)
    beam = BeamShape()
    focus_type = 'Fixed'
    pan_max = 0.0
    tilt_max = 0.0
    power_w = 100.0
    lumens_qxf = 0.0

    for source in (_find(root, 'Physical'), _find(mode, 'Physical')):
        if source is None:
            continue

        dims = _find(source, 'Dimensions')
        if dims is not None:
            # QXF dimensions are in millimetres.
            body_dims_m = (
                _as_float(dims.get('Width'), body_dims_m[0] * 1000) / 1000.0,
                _as_float(dims.get('Height'), body_dims_m[1] * 1000) / 1000.0,
                _as_float(dims.get('Depth'), body_dims_m[2] * 1000) / 1000.0,
            )

        lens = _find(source, 'Lens')
        if lens is not None:
            beam = BeamShape(
                min_deg=_as_float(lens.get('DegreesMin'), 0.0),
                max_deg=_as_float(lens.get('DegreesMax'), 0.0),
            )

        focus = _find(source, 'Focus')
        if focus is not None:
            focus_type = focus.get('Type', focus_type)
            pan_max = _as_float(focus.get('PanMax'), pan_max)
            tilt_max = _as_float(focus.get('TiltMax'), tilt_max)

        lay = _find(source, 'Layout')
        if lay is not None:
            layout = (
                int(_as_float(lay.get('Width'), layout[0])),
                int(_as_float(lay.get('Height'), layout[1])),
            )

        technical = _find(source, 'Technical')
        if technical is not None:
            power_w = _as_float(technical.get('PowerConsumption'), power_w)

        bulb = _find(source, 'Bulb')
        if bulb is not None:
            lumens_qxf = _as_float(bulb.get('Lumens'), lumens_qxf)

    return body_dims_m, layout, beam, focus_type, pan_max, tilt_max, power_w, lumens_qxf


# ---------------------------------------------------------------------------
# Internal: capability detectors
# ---------------------------------------------------------------------------


_DIMMER_PRESETS = ('IntensityMasterDimmer', 'IntensityDimmer')
_DIMMER_NAMES = ('dimmer', 'master', 'intensity')

_COLOR_PRESETS = {
    'red':    ('IntensityRed',),
    'green':  ('IntensityGreen',),
    'blue':   ('IntensityBlue',),
    'white':  ('IntensityWhite',),
    'amber':  ('IntensityAmber',),
    'uv':     ('IntensityUV',),
    'lime':   ('IntensityLime',),
    'cyan':   ('IntensityCyan',),
    'magenta': ('IntensityMagenta',),
    'yellow': ('IntensityYellow',),
    'hue':    ('IntensityHue',),
    'saturation': ('IntensitySaturation',),
    'lightness': ('IntensityLightness',),
    'value':  ('IntensityValue',),
}


def _detect_movement(
    mode_channels: List[_ModeChannel],
    focus_type: str,
    pan_max: float,
    tilt_max: float,
) -> Optional[Movement]:
    pan_ch = _find_first_preset(mode_channels, ('PositionPan',), ('pan',), exclude_substr=('fine',))
    pan_fine = _find_first_preset(mode_channels, ('PositionPanFine',), ('pan fine', 'panfine'))
    tilt_ch = _find_first_preset(mode_channels, ('PositionTilt',), ('tilt',), exclude_substr=('fine',))
    tilt_fine = _find_first_preset(mode_channels, ('PositionTiltFine',), ('tilt fine', 'tiltfine'))

    if pan_ch is None and tilt_ch is None:
        return None

    focus_lower = (focus_type or '').lower()
    if focus_lower == 'mirror':
        mtype = MovementType.MIRROR
    elif focus_lower == 'barrel':
        mtype = MovementType.BARREL
    elif focus_lower == 'fixed':
        # Channels exist but Physical says no movement — trust the channels.
        mtype = MovementType.YOKE
    else:
        mtype = MovementType.YOKE

    return Movement(
        type=mtype,
        pan_max_deg=pan_max or 540.0,    # sensible default for unspecified MH
        tilt_max_deg=tilt_max or 270.0,
        pan_channel=pan_ch,
        pan_fine_channel=pan_fine,
        tilt_channel=tilt_ch,
        tilt_fine_channel=tilt_fine,
    )


def _detect_color_mixing(mode_channels: List[_ModeChannel]) -> Optional[ColorMixing]:
    """Detect additive/HSL color mixing from the set of Intensity* presets in the mode."""
    found: Dict[str, int] = {}
    for component, presets in _COLOR_PRESETS.items():
        idx = _find_first_preset(mode_channels, presets, name_substr=())
        if idx is not None:
            found[component] = idx

    if not found:
        return None

    has = lambda *names: all(n in found for n in names)

    # Order matters: more-specific layouts first.
    if has('red', 'green', 'blue', 'white', 'amber', 'uv'):
        mode = ColorMixingMode.RGBWAUV
    elif has('red', 'green', 'blue', 'amber', 'white'):
        mode = ColorMixingMode.RGBAW
    elif has('red', 'green', 'blue', 'amber'):
        mode = ColorMixingMode.RGBA
    elif has('red', 'green', 'blue', 'white'):
        mode = ColorMixingMode.RGBW
    elif has('red', 'green', 'blue'):
        mode = ColorMixingMode.RGB
    elif has('cyan', 'magenta', 'yellow'):
        mode = ColorMixingMode.CMY
    elif has('hue', 'saturation', 'lightness'):
        mode = ColorMixingMode.HSL
    elif has('hue', 'saturation') and 'value' in found:
        mode = ColorMixingMode.HSV
    elif has('hue', 'saturation'):
        mode = ColorMixingMode.HSI
    else:
        # Fragmentary set — keep the components but pick the closest known mode.
        if 'red' in found and 'green' in found and 'blue' in found:
            mode = ColorMixingMode.RGB
        else:
            return None  # not enough to call it color mixing

    return ColorMixing(mode=mode, channels=found)


def _detect_color_wheel(mode_channels: List[_ModeChannel]) -> Optional[ColorWheel]:
    """A channel with Group=Colour (or ColorMacro caps) that isn't an intensity-color channel."""
    for mc in mode_channels:
        if mc.defn is None:
            continue
        if mc.preset.startswith('Intensity'):
            continue  # IntensityRed/Green/... are mixing components, not wheels
        group = (mc.defn.group or '').lower()
        is_color_group = group in ('colour', 'color')
        has_color_macro = any(cap.preset == 'ColorMacro' for cap in mc.defn.capabilities)
        # Some fixtures name the wheel "Color" without group or preset — accept the name.
        name_says_color = (
            ('color' in mc.name_lower or 'colour' in mc.name_lower)
            and not any(x in mc.name_lower for x in ('red', 'green', 'blue', 'white', 'amber', 'uv', 'lime', 'cyan', 'magenta', 'yellow'))
        )
        if not (is_color_group or has_color_macro or name_says_color):
            continue

        entries: List[ColorWheelEntry] = []
        for cap in mc.defn.capabilities:
            cap_lower = cap.name.lower()
            if any(skip in cap_lower for skip in ('rainbow', 'rotation', 'sound', 'change')):
                continue
            hex_color = cap.res1 if (cap.res1 and cap.res1.startswith('#')) else None
            entries.append(ColorWheelEntry(
                dmx_min=cap.dmx_min,
                dmx_max=cap.dmx_max,
                name=cap.name,
                hex_color=hex_color,
            ))
        if entries:
            return ColorWheel(channel=mc.index, entries=entries)
    return None


def _detect_strobe_channel(mode_channels: List[_ModeChannel]) -> Optional[int]:
    """Strobe lives either on a dedicated channel or in a sub-range of a shutter channel."""
    for mc in mode_channels:
        if mc.preset in ('ShutterStrobeSlowFast', 'ShutterStrobe'):
            return mc.index
        if mc.defn is None:
            continue
        # Shutter channels often have a StrobeSlowToFast sub-range capability.
        for cap in mc.defn.capabilities:
            if cap.preset and 'Strobe' in cap.preset:
                return mc.index
        if 'strobe' in mc.name_lower:
            return mc.index
    return None


def _detect_gobo_wheels(
    mode_channels: List[_ModeChannel],
) -> Tuple[Optional[GoboWheel], Optional[GoboWheel]]:
    wheels: List[GoboWheel] = []
    rotation_index: Optional[int] = None
    for mc in mode_channels:
        if mc.defn is None:
            continue
        group = (mc.defn.group or '').lower()
        has_gobo_macro = any(cap.preset in ('GoboMacro', 'GoboShakeMacro') for cap in mc.defn.capabilities)
        name_says_gobo = 'gobo' in mc.name_lower
        is_rotation = 'rotat' in mc.name_lower or 'spin' in mc.name_lower or mc.preset in (
            'RotationClockwiseSlowToFast', 'RotationCounterClockwiseSlowToFast', 'GoboIndexFast',
        )

        if not (group == 'gobo' or has_gobo_macro or name_says_gobo):
            continue

        if is_rotation and not has_gobo_macro:
            rotation_index = mc.index
            continue

        entries: List[GoboWheelEntry] = []
        for cap in mc.defn.capabilities:
            cap_lower = cap.name.lower()
            if any(skip in cap_lower for skip in ('rainbow', 'rotation', 'spin', 'scroll')):
                continue
            entries.append(GoboWheelEntry(
                dmx_min=cap.dmx_min,
                dmx_max=cap.dmx_max,
                name=cap.name,
                is_shake=(cap.preset == 'GoboShakeMacro') or 'shake' in cap_lower,
                svg_path=cap.res1 if cap.res1 and not cap.res1.startswith('#') else None,
            ))
        if entries:
            wheels.append(GoboWheel(channel=mc.index, entries=entries))

    if not wheels:
        return None, None

    # Attach rotation to the first wheel.
    wheels[0].rotation_channel = rotation_index
    if len(wheels) == 1:
        return wheels[0], None
    return wheels[0], wheels[1]


def _detect_prism(mode_channels: List[_ModeChannel]) -> Optional[Prism]:
    prism_channel: Optional[int] = None
    facets = 3
    rotation_channel: Optional[int] = None
    for mc in mode_channels:
        if mc.defn is None:
            continue
        name_says_prism = 'prism' in mc.name_lower
        has_prism_cap = any(
            cap.preset in ('PrismEffectOn', 'PrismEffectOff') for cap in mc.defn.capabilities
        )
        if not (name_says_prism or has_prism_cap):
            continue

        if 'rotat' in mc.name_lower or 'spin' in mc.name_lower:
            rotation_channel = mc.index
            continue

        prism_channel = mc.index
        for cap in mc.defn.capabilities:
            if cap.preset == 'PrismEffectOn' and cap.res1:
                try:
                    facets = int(cap.res1)
                except ValueError:
                    pass

    if prism_channel is None:
        return None
    return Prism(channel=prism_channel, facets=facets, rotation_channel=rotation_channel)


# ---------------------------------------------------------------------------
# Internal: emitter derivation
# ---------------------------------------------------------------------------


def _parse_heads(mode: ET.Element) -> List[List[int]]:
    """Return list of head→channel-index lists. Empty if no ``<Head>`` blocks."""
    heads: List[List[int]] = []
    for head in _findall(mode, 'Head'):
        indices: List[int] = []
        for ch in _findall(head, 'Channel'):
            txt = (ch.text or '').strip()
            if not txt:
                continue
            try:
                indices.append(int(txt))
            except ValueError:
                continue
        if indices:
            heads.append(indices)
    return heads


def _build_emitter(
    heads: List[List[int]],
    mode_channels: List[_ModeChannel],
    layout: Tuple[int, int],
) -> Emitter:
    """Decide PointEmitter / CellArray / MultiHead based on ``<Head>`` blocks and channel layout."""
    by_index = {mc.index: mc for mc in mode_channels}

    if heads:
        # Any head with its own Pan/Tilt → MultiHead (moving-head bar).
        per_head_movement: List[Optional[Movement]] = [
            _head_movement(head_channels, by_index) for head_channels in heads
        ]
        any_head_moves = any(m is not None for m in per_head_movement)

        if any_head_moves:
            descriptors: List[HeadDescriptor] = []
            for head_channels, head_move in zip(heads, per_head_movement):
                descriptors.append(HeadDescriptor(
                    movement=head_move,
                    color_mixing=_head_color_mixing(head_channels, by_index),
                    dimmer_channel=_head_dimmer(head_channels, by_index),
                    channels=list(head_channels),
                ))
            descriptors = _assign_head_offsets(descriptors, layout)
            return MultiHead(heads=descriptors)

        # Heads without movement → CellArray (each head is a cell).
        cells = [_cell_from_channels(head_channels, by_index) for head_channels in heads]
        width, height = _layout_for_cells(layout, len(cells))
        return CellArray(width=width, height=height, cells=cells)

    # No <Head> blocks: look for per-cell name pattern "Red 1 / Green 1 / Blue 1 / ..."
    inferred_cells = _infer_cells_by_name(mode_channels)
    if inferred_cells:
        width, height = _layout_for_cells(layout, len(inferred_cells))
        return CellArray(width=width, height=height, cells=inferred_cells)

    # No <Head> blocks AND layout > 1 AND dimmer-only with one dimmer per cell
    # (covers a sunstrip variant that omits <Head> blocks).
    if (layout[0] > 1 or layout[1] > 1):
        dimmers = [mc for mc in mode_channels if mc.preset in _DIMMER_PRESETS]
        has_color = any(
            mc.preset in {p for presets in _COLOR_PRESETS.values() for p in presets}
            for mc in mode_channels
        )
        if not has_color and len(dimmers) >= 2 and len(dimmers) == layout[0] * layout[1]:
            cells = [CellSegment(dimmer_channel=mc.index, channels=[mc.index]) for mc in dimmers]
            return CellArray(width=layout[0], height=layout[1], cells=cells)

    return PointEmitter()


def _claimed_channels(emitter: Emitter) -> set[int]:
    """Mode-local channel indices owned by an emitter's cells/heads.

    Chassis-level capability detection ignores these — per-cell RGB must
    not be mistaken for a chassis-wide RGB mix.
    """
    claimed: set[int] = set()
    if isinstance(emitter, CellArray):
        for cell in emitter.cells:
            claimed.update(cell.channels)
    elif isinstance(emitter, MultiHead):
        for head in emitter.heads:
            claimed.update(head.channels)
    return claimed


def _head_movement(head_channels: List[int], by_index: Dict[int, _ModeChannel]) -> Optional[Movement]:
    pan = _head_find_preset(head_channels, by_index, ('PositionPan',), exclude=('fine',))
    pan_fine = _head_find_preset(head_channels, by_index, ('PositionPanFine',))
    tilt = _head_find_preset(head_channels, by_index, ('PositionTilt',), exclude=('fine',))
    tilt_fine = _head_find_preset(head_channels, by_index, ('PositionTiltFine',))
    if pan is None and tilt is None:
        return None
    return Movement(
        type=MovementType.YOKE,
        pan_max_deg=540.0,
        tilt_max_deg=270.0,
        pan_channel=pan,
        pan_fine_channel=pan_fine,
        tilt_channel=tilt,
        tilt_fine_channel=tilt_fine,
    )


def _head_color_mixing(head_channels: List[int], by_index: Dict[int, _ModeChannel]) -> Optional[ColorMixing]:
    found: Dict[str, int] = {}
    for component, presets in _COLOR_PRESETS.items():
        idx = _head_find_preset(head_channels, by_index, presets)
        if idx is not None:
            found[component] = idx
    if not found:
        return None
    # Same layout-detection logic as chassis-level — keep simple here.
    if all(c in found for c in ('red', 'green', 'blue', 'white')):
        m = ColorMixingMode.RGBW
    elif all(c in found for c in ('red', 'green', 'blue')):
        m = ColorMixingMode.RGB
    else:
        return None
    return ColorMixing(mode=m, channels=found)


def _head_dimmer(head_channels: List[int], by_index: Dict[int, _ModeChannel]) -> Optional[int]:
    return _head_find_preset(head_channels, by_index, _DIMMER_PRESETS)


def _head_find_preset(
    head_channels: List[int],
    by_index: Dict[int, _ModeChannel],
    presets: Tuple[str, ...],
    exclude: Tuple[str, ...] = (),
) -> Optional[int]:
    presets_lower = tuple(p.lower() for p in presets)
    for idx in head_channels:
        mc = by_index.get(idx)
        if mc is None:
            continue
        if any(p == mc.preset_lower for p in presets_lower):
            if exclude and any(e in mc.preset_lower or e in mc.name_lower for e in exclude):
                continue
            return idx
    return None


def _cell_from_channels(head_channels: List[int], by_index: Dict[int, _ModeChannel]) -> CellSegment:
    cell = CellSegment(channels=list(head_channels))
    for idx in head_channels:
        mc = by_index.get(idx)
        if mc is None:
            continue
        preset = mc.preset
        if preset == 'IntensityRed':
            cell.red_channel = idx
        elif preset == 'IntensityGreen':
            cell.green_channel = idx
        elif preset == 'IntensityBlue':
            cell.blue_channel = idx
        elif preset == 'IntensityWhite':
            cell.white_channel = idx
        elif preset == 'IntensityAmber':
            cell.amber_channel = idx
        elif preset == 'IntensityUV':
            cell.uv_channel = idx
        elif preset in _DIMMER_PRESETS:
            cell.dimmer_channel = idx
    return cell


_PIXEL_NAME_RE = re.compile(r'(red|green|blue|white|amber|uv)\s*(?:led\s*)?(\d+)', re.IGNORECASE)


def _infer_cells_by_name(mode_channels: List[_ModeChannel]) -> List[CellSegment]:
    """Group channels by trailing numeric suffix in their name (e.g. ``Red 1, Green 1, Blue 1, White 1``)."""
    buckets: Dict[int, CellSegment] = {}
    for mc in mode_channels:
        match = _PIXEL_NAME_RE.search(mc.name_lower)
        if not match:
            continue
        component, num_str = match.group(1).lower(), match.group(2)
        cell_idx = int(num_str)
        cell = buckets.setdefault(cell_idx, CellSegment())
        cell.channels.append(mc.index)
        if component == 'red':
            cell.red_channel = mc.index
        elif component == 'green':
            cell.green_channel = mc.index
        elif component == 'blue':
            cell.blue_channel = mc.index
        elif component == 'white':
            cell.white_channel = mc.index
        elif component == 'amber':
            cell.amber_channel = mc.index
        elif component == 'uv':
            cell.uv_channel = mc.index
    if not buckets:
        return []
    return [buckets[k] for k in sorted(buckets)]


def _layout_for_cells(layout: Tuple[int, int], cell_count: int) -> Tuple[int, int]:
    """Pick the (W, H) that best matches ``cell_count`` cells, falling back to ``(N, 1)``."""
    w, h = layout
    if w * h == cell_count and cell_count > 0:
        return w, h
    if cell_count > 0:
        return cell_count, 1
    return w, h


def _assign_head_offsets(
    descriptors: List[HeadDescriptor],
    layout: Tuple[int, int],
) -> List[HeadDescriptor]:
    """Evenly space heads along the bar's local X axis.

    Per the §8 Q5 decision: auto from ``<Layout Width=N>``; manual override
    can be applied per-fixture later (Phase D, by overwriting offsets after
    detection).
    """
    n = len(descriptors)
    if n <= 1:
        return descriptors
    # Distribute across [-0.5, 0.5] of the layout width (in units; renderer scales by body width).
    for i, desc in enumerate(descriptors):
        offset_x = (i - (n - 1) / 2.0) / max(n, 1)
        desc.offset_m = (offset_x, 0.0, 0.0)
    return descriptors


# ---------------------------------------------------------------------------
# Internal: chassis classification
# ---------------------------------------------------------------------------


def _chassis_from_type(
    qlc_type: str,
    has_movement: bool,
    has_cells: bool,
    layout: Tuple[int, int],
) -> Chassis:
    t = (qlc_type or '').lower()

    # Movement wins (some odd fixtures declare Type="Other" but have Pan/Tilt).
    if has_movement:
        return Chassis.MOVING_YOKE

    if 'moving head' in t or t == 'lyre':
        return Chassis.MOVING_YOKE
    if 'scanner' in t:
        return Chassis.SCANNER
    if 'strobe' in t:
        return Chassis.PAR
    if 'hazer' in t or 'smoke' in t or 'fog' in t:
        return Chassis.PARTICLE
    if 'laser' in t:
        return Chassis.LASER
    if 'effect' in t or 'flower' in t:
        return Chassis.EFFECT
    if 'led matrix' in t:
        return Chassis.PANEL
    if 'dimmer' in t or 'fan' in t:
        return Chassis.OTHER
    if 'led bar' in t or 'sunstrip' in t:
        return Chassis.BAR
    if 'color changer' in t or 'wash' in t or 'color wheel' in t:
        # A "Color Changer" with a multi-cell layout that we have per-cell control over → PANEL.
        if has_cells and layout[1] > 1:
            return Chassis.PANEL
        return Chassis.PAR

    # Unknown type: infer from layout/cells if possible.
    if has_cells:
        return Chassis.PANEL if layout[1] > 1 else Chassis.BAR
    return Chassis.OTHER


# ---------------------------------------------------------------------------
# Internal: misc helpers
# ---------------------------------------------------------------------------


def _find(parent: ET.Element, tag: str) -> Optional[ET.Element]:
    """Find immediate or descendant child, tolerant of missing namespace."""
    found = parent.find(tag, QLC_NS)
    if found is None:
        found = parent.find(tag)
    return found


def _findall(parent: ET.Element, tag: str) -> List[ET.Element]:
    found = parent.findall(tag, QLC_NS)
    if not found:
        found = parent.findall(tag)
    return found


def _find_text(parent: ET.Element, tag: str) -> Optional[str]:
    elem = _find(parent, tag)
    return elem.text if elem is not None and elem.text else None


def _as_float(value: Optional[str], default: float) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _find_first_preset(
    mode_channels: List[_ModeChannel],
    presets: Tuple[str, ...],
    name_substr: Tuple[str, ...] = (),
    exclude_substr: Tuple[str, ...] = (),
) -> Optional[int]:
    """Return the mode-local index of the first channel matching any preset.

    Falls back to substring matching on channel names if no preset hits.
    """
    presets_lower = tuple(p.lower() for p in presets)
    # Preset pass.
    for mc in mode_channels:
        if mc.preset_lower in presets_lower:
            if exclude_substr and any(e in mc.preset_lower or e in mc.name_lower for e in exclude_substr):
                continue
            return mc.index
    # Name fallback.
    for mc in mode_channels:
        if not mc.preset and any(s in mc.name_lower for s in name_substr):
            if exclude_substr and any(e in mc.name_lower for e in exclude_substr):
                continue
            return mc.index
    return None


# ---------------------------------------------------------------------------
# Legacy bridge — temporary mapping from the 6-string fixture_type to Chassis.
# ---------------------------------------------------------------------------
#
# Phase C consumers (FixtureItem.paint, OrientationDialog) still receive the
# legacy ``fixture_type`` string. They use this helper to translate it into a
# Chassis enum value. Phase D removes the helper once :class:`Fixture` carries
# ``chassis`` directly (populated at config load time via detect_capabilities).


_LEGACY_TYPE_TO_CHASSIS: Dict[str, Chassis] = {
    'MH': Chassis.MOVING_YOKE,
    'PAR': Chassis.PAR,
    # WASH was a renderer hint in the 6-string enum (no movement, single
    # source RGB(W) wash). In the new model it's just a PAR-shaped fixture
    # with NoOptics — chassis-wise it's PAR.
    'WASH': Chassis.PAR,
    'BAR': Chassis.BAR,
    'PIXELBAR': Chassis.BAR,
    'SUNSTRIP': Chassis.BAR,
}


def chassis_from_legacy_type(legacy_type: Optional[str]) -> Chassis:
    """Map the legacy 6-string ``fixture_type`` to a :class:`Chassis` value.

    Bridge for Phase C consumers that still hold a legacy string. Returns
    :attr:`Chassis.OTHER` for unknown / missing input — callers can use
    that as a "placeholder" cue.
    """
    if not legacy_type:
        return Chassis.OTHER
    return _LEGACY_TYPE_TO_CHASSIS.get(legacy_type, Chassis.OTHER)


# ---------------------------------------------------------------------------
# Cached lookup — Phase D bridge between Fixture and FixtureCapabilities.
# ---------------------------------------------------------------------------
#
# ``Fixture`` doesn't carry capabilities (would force a YAML schema bump and
# the data is derivable from the QXF). Instead, callers ask the module for a
# cached :class:`FixtureCapabilities` keyed by (manufacturer, model, mode).
#
# Cache is invalidated when the fixture-definition cache in
# ``fixture_utils.py`` is cleared (e.g. when QXF files change on disk).


_FIXTURE_CAPABILITIES_CACHE: Dict[Tuple[str, str, str], 'FixtureCapabilities'] = {}


def clear_capabilities_cache() -> None:
    """Drop all cached :class:`FixtureCapabilities`. Call after QXF file changes."""
    _FIXTURE_CAPABILITIES_CACHE.clear()


def get_capabilities_for_fixture(fixture) -> 'FixtureCapabilities':
    """Return the cached :class:`FixtureCapabilities` for a fixture's current mode.

    On a cache miss, locates the fixture's ``.qxf`` file via the same search
    paths used elsewhere (project ``custom_fixtures``, then platform-specific
    QLC+ fixture directories), parses it, and runs :func:`detect_capabilities`.

    Returns a safe-default ``FixtureCapabilities`` (chassis=OTHER, no
    components) if the QXF can't be located or parsed.
    """
    key = (fixture.manufacturer, fixture.model, fixture.current_mode)
    cached = _FIXTURE_CAPABILITIES_CACHE.get(key)
    if cached is not None:
        return cached

    qxf_root = _find_and_parse_qxf(fixture.manufacturer, fixture.model)
    if qxf_root is None:
        caps = _safe_default_capabilities(fixture.current_mode)
    else:
        caps = detect_capabilities(qxf_root, fixture.current_mode)

    _FIXTURE_CAPABILITIES_CACHE[key] = caps
    return caps


def _safe_default_capabilities(mode_name: str) -> 'FixtureCapabilities':
    """Empty ``FixtureCapabilities`` for fixtures whose QXF isn't found."""
    return FixtureCapabilities(
        chassis=Chassis.OTHER,
        qlc_type='',
        mode_name=mode_name or '',
    )


def _find_and_parse_qxf(manufacturer: str, model: str) -> Optional[ET.Element]:
    """Locate and parse the fixture's .qxf via the unified fixture library.

    Discovery, duplicate resolution (bundled custom_fixtures/ wins), and
    parse caching all live in :mod:`utils.fixture_library`; this returns
    the parsed root for :func:`detect_capabilities` or ``None``.
    """
    from utils.fixture_library import get_definition
    defn = get_definition(manufacturer, model)
    return defn.root if defn is not None else None


def _estimate_lumens(qxf_lumens: float, power_w: float, channel_defs: Dict[str, _ChannelDef]) -> float:
    """Use the QXF-declared lumens if present; else estimate from power.

    LED at ~100 lm/W, halogen/discharge at ~25 lm/W. Detection is rough —
    we assume LED if the fixture has any IntensityRed/Green/Blue presets.
    """
    if qxf_lumens > 0:
        return qxf_lumens
    is_led = any(
        defn.preset in ('IntensityRed', 'IntensityGreen', 'IntensityBlue', 'IntensityWhite')
        for defn in channel_defs.values()
    )
    return power_w * (100.0 if is_led else 25.0)
