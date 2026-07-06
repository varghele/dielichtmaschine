"""Tests for utils/fixture_capabilities.py (Phase A of fixture-rewrite).

Each test loads one of the QXF files in ``custom_fixtures/`` and asserts
that detect_capabilities() returns the expected shape: chassis, emitter
type, beam, movement, color mixing/wheel, gobo, prism.

Covers all 6 custom fixtures across multiple modes to exercise:
- Moving head with gobo + prism + color wheel + zoom (Hero Spot 60)
- Pixel bar via <Head> blocks (Sunstrip, Giga Bar 48ch / 51ch)
- Pixel bar via name-pattern inference (Varghele LED BAR — no <Head> tags)
- Single-source RGB wash (Wild Wash 648)
- Single-source RGBW PAR with color wheel (Retro Flat Par)
- HSL mode + RGBW mode + cell mode all on the same fixture (Giga Bar)
"""

from __future__ import annotations

import os
import xml.etree.ElementTree as ET

import pytest

from utils.fixture_capabilities import (
    CellArray,
    Chassis,
    ColorMixingMode,
    FixtureCapabilities,
    MovementType,
    MultiHead,
    PointEmitter,
    chassis_from_legacy_type,
    clear_capabilities_cache,
    detect_capabilities,
    get_capabilities_for_fixture,
)


CUSTOM_FIXTURES = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    'custom_fixtures',
)


def _load(filename: str) -> ET.Element:
    return ET.parse(os.path.join(CUSTOM_FIXTURES, filename)).getroot()


# ---------------------------------------------------------------------------
# Varytec Hero Spot 60 — classic moving head
# ---------------------------------------------------------------------------


def test_hero_spot_60_14_channel():
    root = _load('Varytec-Hero-Spot-60.qxf')
    caps = detect_capabilities(root, '14 Channel')

    assert caps.chassis is Chassis.MOVING_YOKE
    assert caps.qlc_type == 'Moving Head'
    assert caps.channel_count == 14

    # Movement
    assert caps.movement is not None
    assert caps.movement.type is MovementType.YOKE
    assert caps.movement.pan_max_deg == 540.0
    assert caps.movement.tilt_max_deg == 190.0
    assert caps.movement.pan_channel == 0
    assert caps.movement.pan_fine_channel == 1
    assert caps.movement.tilt_channel == 2
    assert caps.movement.tilt_fine_channel == 3

    # Color wheel (the "Color" channel, not RGB mixing — this fixture has no RGB)
    assert caps.color_mixing is None
    assert caps.color_wheel is not None
    assert caps.color_wheel.channel == 7
    # 8 macros (white, red, yellow, light blue, green, amber, violet, blue);
    # rainbow rotation entry is filtered.
    macro_names = [e.name.lower() for e in caps.color_wheel.entries]
    assert any('white' in n for n in macro_names)
    assert any('amber' in n for n in macro_names)
    assert not any('rainbow' in n for n in macro_names)

    # Gobo wheel + rotation
    assert caps.gobo_wheel is not None
    assert caps.gobo_wheel.channel == 8
    assert caps.gobo_wheel.rotation_channel == 9
    gobo_names = [e.name.lower() for e in caps.gobo_wheel.entries]
    assert any('open' in n for n in gobo_names)
    assert sum(1 for e in caps.gobo_wheel.entries if e.is_shake) >= 5
    # SVG paths preserved
    assert any(e.svg_path and 'gobo' in e.svg_path.lower() for e in caps.gobo_wheel.entries)

    # Prism (PrismEffectOn Res1=3)
    assert caps.prism is not None
    assert caps.prism.channel == 11
    assert caps.prism.facets == 3

    # Beam (fixed 15°)
    assert caps.beam.min_deg == 15.0
    assert caps.beam.max_deg == 15.0
    assert not caps.beam.is_zoom

    # Intensity channels
    assert caps.dimmer_channel == 5
    assert caps.strobe_channel == 6  # Shutter channel hosts StrobeSlowToFast sub-range
    assert caps.focus_channel == 10

    # Emitter is a point (single-head moving head)
    assert isinstance(caps.emitter, PointEmitter)

    # Body dimensions (mm → m)
    assert caps.body_dims_m == pytest.approx((0.214, 0.355, 0.144))


def test_hero_spot_60_8_channel_has_no_fine_channels():
    root = _load('Varytec-Hero-Spot-60.qxf')
    caps = detect_capabilities(root, '8 Channel')

    assert caps.chassis is Chassis.MOVING_YOKE
    assert caps.movement is not None
    assert caps.movement.pan_channel == 0
    assert caps.movement.pan_fine_channel is None
    assert caps.movement.tilt_channel == 1
    assert caps.movement.tilt_fine_channel is None
    # 8-channel mode drops the color wheel + gobo wheel entirely
    assert caps.color_wheel is None
    assert caps.gobo_wheel is None
    assert caps.prism is None


# ---------------------------------------------------------------------------
# Showtec Sunstrip Active — dimmer-only pixel bar via <Head> blocks
# ---------------------------------------------------------------------------


def test_sunstrip_10_channel_mode_is_cell_array():
    root = _load('Showtec-Sunstrip-Active.qxf')
    caps = detect_capabilities(root, '10 Channels Mode')

    assert caps.chassis is Chassis.BAR
    assert caps.qlc_type == 'LED Bar (Pixels)'
    assert caps.movement is None
    assert caps.color_mixing is None
    assert caps.color_wheel is None
    assert caps.gobo_wheel is None
    assert caps.prism is None
    # No master dimmer — every dimmer belongs to a cell.
    assert caps.dimmer_channel is None

    assert isinstance(caps.emitter, CellArray)
    assert caps.emitter.width == 10
    assert caps.emitter.height == 1
    assert len(caps.emitter.cells) == 10
    # Each cell is dimmer-only
    for i, cell in enumerate(caps.emitter.cells):
        assert cell.dimmer_channel == i
        assert cell.red_channel is None
        assert cell.green_channel is None

    # Beam: no optics (DegreesMin=Max=0)
    assert not caps.beam.has_optics


def test_sunstrip_1_channel_mode_is_point_emitter():
    root = _load('Showtec-Sunstrip-Active.qxf')
    caps = detect_capabilities(root, '1 Channel Mode')

    assert caps.chassis is Chassis.BAR
    # Only one DMX channel, no <Head> blocks in this mode → PointEmitter.
    assert isinstance(caps.emitter, PointEmitter)
    assert caps.dimmer_channel == 0


# ---------------------------------------------------------------------------
# Varghele LED BAR — RGBW pixel bar inferred from channel names (no <Head> blocks)
# ---------------------------------------------------------------------------


def test_varghele_led_bar_infers_cells_by_name():
    root = _load('Varghele-LED-BAR.qxf')
    caps = detect_capabilities(root, '40 Channels Mode')

    assert caps.chassis is Chassis.BAR
    assert caps.qlc_type == 'LED Bar (Beams)'
    assert caps.movement is None

    # 10 RGBW cells inferred from "Red 1, Green 1, Blue 1, White 1, Red 2, ..." pattern
    assert isinstance(caps.emitter, CellArray)
    assert caps.emitter.width == 10
    assert caps.emitter.height == 1
    assert len(caps.emitter.cells) == 10

    # Verify each cell has its RGBW channels in mode-local index order
    for cell_idx, cell in enumerate(caps.emitter.cells):
        base = cell_idx * 4
        assert cell.red_channel == base
        assert cell.green_channel == base + 1
        assert cell.blue_channel == base + 2
        assert cell.white_channel == base + 3
        assert cell.dimmer_channel is None  # no master dimmer in this mode


# ---------------------------------------------------------------------------
# Stairville Wild Wash Pro 648 — RGB wash with strobe and color macro wheel
# ---------------------------------------------------------------------------


def test_wild_wash_648_6_channel_is_rgb_wash():
    root = _load('Stairville-Wild-Wash-Pro-648-RGB-LED.qxf')
    caps = detect_capabilities(root, '6 Channel')

    # Author tagged Type as "LED Bar (Pixels)" so chassis is BAR — correct shape,
    # even though there's no per-pixel control. The emitter being PointEmitter
    # tells the renderer this is a uniform wash bar.
    assert caps.chassis is Chassis.BAR
    assert caps.qlc_type == 'LED Bar (Pixels)'

    assert isinstance(caps.emitter, PointEmitter)
    assert caps.color_mixing is not None
    assert caps.color_mixing.mode is ColorMixingMode.RGB
    assert caps.color_mixing.channels == {'red': 2, 'green': 3, 'blue': 4}

    assert caps.dimmer_channel == 0
    assert caps.strobe_channel == 1  # "Strobe" channel hosts StrobeSlowToFast sub-range

    # No <Lens> optics → flat-emitting bar.
    assert not caps.beam.has_optics


def test_wild_wash_648_4_channel_detects_color_wheel():
    root = _load('Stairville-Wild-Wash-Pro-648-RGB-LED.qxf')
    caps = detect_capabilities(root, '4 Channel')

    # The "Color Macro" channel (Group=Colour, ColorMacro caps) is a color wheel.
    assert caps.color_wheel is not None
    assert caps.color_wheel.channel == 2
    assert len(caps.color_wheel.entries) >= 10
    macro_hexes = [e.hex_color for e in caps.color_wheel.entries if e.hex_color]
    assert '#ff0000' in macro_hexes
    assert '#0000ff' in macro_hexes


# ---------------------------------------------------------------------------
# Stairville Retro Flat Par 18x12W RGBW — RGBW PAR with dimmer + strobe + color wheel
# ---------------------------------------------------------------------------


def test_retro_flat_par_8_channel():
    root = _load('Stairville-Retro-Flat-Par-18x12W-RGBW-.qxf')
    caps = detect_capabilities(root, '8 Channel')

    assert caps.chassis is Chassis.PAR
    assert caps.qlc_type == 'Color Changer'
    assert caps.movement is None

    assert isinstance(caps.emitter, PointEmitter)
    assert caps.color_mixing is not None
    assert caps.color_mixing.mode is ColorMixingMode.RGBW
    assert caps.color_mixing.channels == {'red': 1, 'green': 2, 'blue': 3, 'white': 4}

    assert caps.dimmer_channel == 0
    assert caps.strobe_channel == 7  # Stroboscope channel with ShutterStrobeSlowFast preset

    # "Colour selection" channel — no per-cap preset, only Group=Colour
    assert caps.color_wheel is not None
    assert caps.color_wheel.channel == 6


# ---------------------------------------------------------------------------
# Varytec Giga Bar — hybrid bar with HSL / RGBW / per-cell modes
# ---------------------------------------------------------------------------


def test_giga_bar_3_channel_is_hsl():
    root = _load('Varytec-Giga-Bar-5-LED-RGBW.qxf')
    caps = detect_capabilities(root, '3 Channels')

    assert caps.chassis is Chassis.BAR
    assert caps.qlc_type == 'LED Bar (Beams)'
    assert isinstance(caps.emitter, PointEmitter)
    assert caps.color_mixing is not None
    assert caps.color_mixing.mode is ColorMixingMode.HSL
    assert caps.color_mixing.channels == {'hue': 0, 'saturation': 1, 'lightness': 2}
    assert caps.dimmer_channel is None


def test_giga_bar_5_channel_is_rgbw_with_dimmer():
    root = _load('Varytec-Giga-Bar-5-LED-RGBW.qxf')
    caps = detect_capabilities(root, '5 Channels')

    assert isinstance(caps.emitter, PointEmitter)
    assert caps.color_mixing.mode is ColorMixingMode.RGBW
    assert caps.color_mixing.channels == {'red': 1, 'green': 2, 'blue': 3, 'white': 4}
    assert caps.dimmer_channel == 0


def test_giga_bar_48_channel_is_cell_array():
    root = _load('Varytec-Giga-Bar-5-LED-RGBW.qxf')
    caps = detect_capabilities(root, '48 Channels')

    assert caps.chassis is Chassis.BAR
    # Chassis-level color mixing is None: the cells own the colors.
    assert caps.color_mixing is None
    assert caps.dimmer_channel is None

    assert isinstance(caps.emitter, CellArray)
    assert caps.emitter.width == 12
    assert caps.emitter.height == 1
    assert len(caps.emitter.cells) == 12

    # First cell: channels 0,1,2,3 → R,G,B,W
    assert caps.emitter.cells[0].red_channel == 0
    assert caps.emitter.cells[0].green_channel == 1
    assert caps.emitter.cells[0].blue_channel == 2
    assert caps.emitter.cells[0].white_channel == 3

    # Cell 8 in the QXF has channels listed in non-sequential order
    # (28, 30, 29, 31 — Red, Blue, Green, White). Preset-based detection
    # must still pick the right channel for each color component.
    cell_8 = caps.emitter.cells[7]
    assert cell_8.red_channel == 28
    assert cell_8.green_channel == 29
    assert cell_8.blue_channel == 30
    assert cell_8.white_channel == 31

    # 48-ch mode has its own <Physical> with Layout 12x1 → mode-level override picked up
    assert caps.layout == (12, 1)
    assert caps.body_dims_m[0] == pytest.approx(1.070)


def test_giga_bar_51_channel_keeps_master_dimmer():
    root = _load('Varytec-Giga-Bar-5-LED-RGBW.qxf')
    caps = detect_capabilities(root, '51 Channels')

    # Chassis-level master dimmer (channel 0) coexists with per-cell RGBW.
    assert caps.dimmer_channel == 0

    assert isinstance(caps.emitter, CellArray)
    assert caps.emitter.width == 12
    assert len(caps.emitter.cells) == 12
    # First cell's R/G/B/W channels are now 1..4 (offset by the master dimmer at 0).
    assert caps.emitter.cells[0].red_channel == 1
    assert caps.emitter.cells[0].green_channel == 2
    assert caps.emitter.cells[0].blue_channel == 3
    assert caps.emitter.cells[0].white_channel == 4


# ---------------------------------------------------------------------------
# Error-tolerance: missing mode / malformed input
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Phase C bridge: legacy 6-string fixture_type → Chassis
# ---------------------------------------------------------------------------


def test_chassis_from_legacy_type_known_strings():
    assert chassis_from_legacy_type('MH') is Chassis.MOVING_YOKE
    assert chassis_from_legacy_type('PAR') is Chassis.PAR
    # WASH was a renderer hint in the 6-string enum; chassis-wise it's PAR.
    assert chassis_from_legacy_type('WASH') is Chassis.PAR
    assert chassis_from_legacy_type('BAR') is Chassis.BAR
    assert chassis_from_legacy_type('PIXELBAR') is Chassis.BAR
    assert chassis_from_legacy_type('SUNSTRIP') is Chassis.BAR


def test_chassis_from_legacy_type_unknown_falls_back_to_other():
    assert chassis_from_legacy_type('UNKNOWN') is Chassis.OTHER
    assert chassis_from_legacy_type('') is Chassis.OTHER
    assert chassis_from_legacy_type(None) is Chassis.OTHER  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Phase D Stage 1.1: cached get_capabilities_for_fixture
# ---------------------------------------------------------------------------


class _StubFixture:
    """Quick stand-in to avoid importing config.models.Fixture (which has many required fields)."""
    def __init__(self, manufacturer: str, model: str, mode: str):
        self.manufacturer = manufacturer
        self.model = model
        self.current_mode = mode


def test_get_capabilities_for_fixture_finds_custom_qxf(monkeypatch):
    # Hermetic: restrict the library to custom_fixtures/. On machines
    # with a populated gdtf_fixtures/, a Share-downloaded GDTF of the
    # same identity wins resolution and carries different mode names
    # (see docs/gdtf-coverage-note.md, mode-name mismatch follow-up).
    from utils import fixture_library as fl
    fl.clear_library_cache()
    monkeypatch.setattr(
        fl, "fixture_search_dirs",
        lambda: [(fl.project_custom_fixtures_dir(), "bundled")])
    clear_capabilities_cache()
    f = _StubFixture("Varytec", "Hero Spot 60", "14 Channel")
    caps = get_capabilities_for_fixture(f)
    fl.clear_library_cache()
    assert caps.chassis is Chassis.MOVING_YOKE
    assert caps.movement is not None
    assert caps.gobo_wheel is not None


def test_get_capabilities_for_fixture_caches_repeated_calls():
    clear_capabilities_cache()
    f = _StubFixture("Showtec", "Sunstrip Active", "10 Channels Mode")
    first = get_capabilities_for_fixture(f)
    second = get_capabilities_for_fixture(f)
    # Cache returns the same object identity on repeat lookup.
    assert first is second


def test_get_capabilities_for_fixture_unknown_returns_safe_default():
    clear_capabilities_cache()
    f = _StubFixture("NoSuchManufacturer", "NoSuchModel", "Standard")
    caps = get_capabilities_for_fixture(f)
    assert caps.chassis is Chassis.OTHER
    assert caps.movement is None
    assert caps.color_mixing is None
    assert caps.channel_count == 0


def test_clear_capabilities_cache_invalidates():
    f = _StubFixture("Varytec", "Hero Spot 60", "14 Channel")
    first = get_capabilities_for_fixture(f)
    clear_capabilities_cache()
    second = get_capabilities_for_fixture(f)
    # New object after invalidation, equal-but-not-same.
    assert first is not second
    assert first.chassis is second.chassis


def test_unknown_mode_returns_safe_defaults():
    root = _load('Varytec-Hero-Spot-60.qxf')
    caps = detect_capabilities(root, 'Nonexistent Mode')

    # Falls back to chassis from <Type>, no detected capabilities.
    assert caps.chassis is Chassis.MOVING_YOKE  # Type says "Moving Head"
    assert caps.movement is None
    assert caps.color_mixing is None
    assert isinstance(caps.emitter, PointEmitter)
    assert caps.channel_count == 0


# ---------------------------------------------------------------------------
# Phase E: real-QXF archetype validation
# ---------------------------------------------------------------------------


def test_mac_aura_standard_is_moving_wash():
    """Moving wash = moving head with RGB(W) + no gobo wheel.

    The §1.4 "moving wash" gap: legacy MovingHeadRenderer hardcodes a gobo
    subsystem on every MH. The composable renderer only instantiates a
    GoboComponent when capabilities.gobo_wheel is present — so a no-gobo MH
    renders cleanly.
    """
    root = _load('Martin-MAC-Aura.qxf')
    caps = detect_capabilities(root, 'Standard')

    assert caps.chassis is Chassis.MOVING_YOKE
    assert caps.qlc_type == 'Moving Head'
    assert isinstance(caps.emitter, PointEmitter)

    # Movement: pan/tilt with fine channels
    assert caps.movement is not None
    assert caps.movement.type is MovementType.YOKE
    assert caps.movement.pan_fine_channel is not None
    assert caps.movement.tilt_fine_channel is not None

    # RGBW color mixing
    assert caps.color_mixing is not None
    assert caps.color_mixing.mode is ColorMixingMode.RGBW

    # The key archetype property: NO gobo wheel.
    assert caps.gobo_wheel is None
    assert caps.prism is None

    # Has a color wheel (LEE filter macros) and a zoom channel.
    assert caps.color_wheel is not None
    assert caps.zoom_channel is not None
    assert caps.dimmer_channel is not None


def test_mac_aura_extended_is_multi_zone():
    """Extended mode adds the Aura halo as a second zone — CellArray(2,1)."""
    root = _load('Martin-MAC-Aura.qxf')
    caps = detect_capabilities(root, 'Extended')

    assert caps.chassis is Chassis.MOVING_YOKE
    # Two zones: Beam (RGBW + dimmer) and Aura (RGB + dimmer)
    assert isinstance(caps.emitter, CellArray)
    assert caps.emitter.width == 2
    assert caps.emitter.height == 1
    assert len(caps.emitter.cells) == 2


def test_magic_blade_r_is_moving_cell_bar():
    """Ayrton MagicBlade-R: chassis-level pan/tilt + 7 RGBW cells along the bar.

    Detected as MOVING_YOKE + CellArray (best fit in the v1 9-chassis
    enum — a dedicated MOVING_BAR chassis is a follow-up). The point is
    that detection produces the right semantic shape: movement + per-cell
    color, no gobo, no prism.
    """
    root = _load('Ayrton-MagicBlade-R.qxf')
    caps = detect_capabilities(root, 'Ex (44ch)')

    assert caps.chassis is Chassis.MOVING_YOKE  # has_movement override
    assert caps.qlc_type == 'LED Bar (Beams)'
    assert caps.movement is not None
    assert caps.movement.type is MovementType.YOKE

    assert isinstance(caps.emitter, CellArray)
    assert caps.emitter.width == 7
    assert caps.emitter.height == 1
    assert len(caps.emitter.cells) == 7
    for cell in caps.emitter.cells:
        assert cell.red_channel is not None
        assert cell.green_channel is not None
        assert cell.blue_channel is not None
        assert cell.white_channel is not None

    # Chassis-level master dimmer.
    assert caps.dimmer_channel is not None
    # No gobo, no prism (it's a moving cell bar, not a spot).
    assert caps.gobo_wheel is None
    assert caps.prism is None


def test_led_matrix_blinder_is_panel_with_5x5_cells():
    """Stairville LED Matrix Blinder 5x5: 25 dimmer-only cells in a 5×5 grid.

    Validates the v1 "pixel matrix" archetype unlocks. Chassis PANEL +
    CellArray(5,5) with per-cell dimmer (no color — it's a monochrome
    blinder).
    """
    root = _load('Stairville-LED-Matrix-Blinder-5x5.qxf')
    caps = detect_capabilities(root, '26-Channel')

    assert caps.chassis is Chassis.PANEL
    assert isinstance(caps.emitter, CellArray)
    assert caps.emitter.width == 5
    assert caps.emitter.height == 5
    assert len(caps.emitter.cells) == 25

    # Master dimmer + 25 per-cell dimmers; no color.
    assert caps.dimmer_channel == 0
    assert caps.color_mixing is None

    # Each cell has a dimmer_channel but no color channels.
    for cell in caps.emitter.cells:
        assert cell.dimmer_channel is not None
        assert cell.red_channel is None
        assert cell.green_channel is None


# ---------------------------------------------------------------------------
# v1 archetype unlocks (synthetic QXFs — not in custom_fixtures/)
# ---------------------------------------------------------------------------


def _qxf(body: str) -> ET.Element:
    """Wrap a fragment in a minimal FixtureDefinition root and parse it."""
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<FixtureDefinition xmlns="http://www.qlcplus.org/FixtureDefinition">'
        f'{body}'
        '</FixtureDefinition>'
    )
    return ET.fromstring(xml)


def test_moving_wash_has_movement_and_zoom_but_no_gobo():
    """A no-gobo moving head (the §1.4 known gap) should detect cleanly."""
    root = _qxf(
        '<Manufacturer>Test</Manufacturer><Model>MovingWash</Model><Type>Moving Head</Type>'
        '<Channel Name="Pan" Preset="PositionPan"/>'
        '<Channel Name="Tilt" Preset="PositionTilt"/>'
        '<Channel Name="Dimmer" Preset="IntensityDimmer"/>'
        '<Channel Name="Red" Preset="IntensityRed"/>'
        '<Channel Name="Green" Preset="IntensityGreen"/>'
        '<Channel Name="Blue" Preset="IntensityBlue"/>'
        '<Channel Name="White" Preset="IntensityWhite"/>'
        '<Channel Name="Zoom" Preset="BeamZoomSmallBig"/>'
        '<Mode Name="8 Channel">'
        '  <Channel Number="0">Pan</Channel>'
        '  <Channel Number="1">Tilt</Channel>'
        '  <Channel Number="2">Dimmer</Channel>'
        '  <Channel Number="3">Red</Channel>'
        '  <Channel Number="4">Green</Channel>'
        '  <Channel Number="5">Blue</Channel>'
        '  <Channel Number="6">White</Channel>'
        '  <Channel Number="7">Zoom</Channel>'
        '</Mode>'
        '<Physical>'
        '  <Dimensions Width="300" Height="400" Depth="200"/>'
        '  <Lens Name="Other" DegreesMin="10" DegreesMax="60"/>'
        '  <Focus Type="Head" PanMax="540" TiltMax="270"/>'
        '</Physical>'
    )
    caps = detect_capabilities(root, '8 Channel')

    assert caps.chassis is Chassis.MOVING_YOKE
    assert caps.movement is not None
    assert caps.color_mixing.mode is ColorMixingMode.RGBW
    assert caps.dimmer_channel == 2
    assert caps.zoom_channel == 7
    assert caps.beam.is_zoom and caps.beam.min_deg == 10.0 and caps.beam.max_deg == 60.0
    # The whole point of the v1 unlock: no gobo wheel is detected, no prism.
    assert caps.gobo_wheel is None
    assert caps.prism is None
    assert isinstance(caps.emitter, PointEmitter)


def test_moving_head_bar_uses_multihead_with_per_head_movement():
    """Ayrton MagicBlade-style bar: N heads each with own pan/tilt + RGBW."""
    head_channel_block = (
        '<Channel Name="Pan{i}" Preset="PositionPan"/>'
        '<Channel Name="Tilt{i}" Preset="PositionTilt"/>'
        '<Channel Name="Red{i}" Preset="IntensityRed"/>'
        '<Channel Name="Green{i}" Preset="IntensityGreen"/>'
        '<Channel Name="Blue{i}" Preset="IntensityBlue"/>'
        '<Channel Name="White{i}" Preset="IntensityWhite"/>'
    )
    n_heads = 4
    channel_defs = ''.join(head_channel_block.format(i=i) for i in range(n_heads))

    mode_channels = []
    head_blocks = []
    ch_num = 0
    for i in range(n_heads):
        head_ids = []
        for suffix in ('Pan', 'Tilt', 'Red', 'Green', 'Blue', 'White'):
            mode_channels.append(f'<Channel Number="{ch_num}">{suffix}{i}</Channel>')
            head_ids.append(ch_num)
            ch_num += 1
        head_blocks.append(
            '<Head>' + ''.join(f'<Channel>{c}</Channel>' for c in head_ids) + '</Head>'
        )

    root = _qxf(
        '<Manufacturer>Test</Manufacturer><Model>MHBar4</Model><Type>Moving Head</Type>'
        + channel_defs
        + '<Mode Name="24 Channel">'
        + ''.join(mode_channels)
        + ''.join(head_blocks)
        + '</Mode>'
        '<Physical>'
        '  <Dimensions Width="900" Height="100" Depth="100"/>'
        '  <Lens Name="Other" DegreesMin="5" DegreesMax="5"/>'
        '  <Focus Type="Head" PanMax="540" TiltMax="270"/>'
        '  <Layout Width="4" Height="1"/>'
        '</Physical>'
    )
    caps = detect_capabilities(root, '24 Channel')

    assert caps.chassis is Chassis.MOVING_YOKE
    assert isinstance(caps.emitter, MultiHead)
    assert len(caps.emitter.heads) == 4

    for i, head in enumerate(caps.emitter.heads):
        assert head.movement is not None
        assert head.movement.type is MovementType.YOKE
        # Channel indices for head i:
        # 6 channels per head, ordered Pan/Tilt/R/G/B/W
        base = i * 6
        assert head.movement.pan_channel == base
        assert head.movement.tilt_channel == base + 1
        assert head.color_mixing is not None
        assert head.color_mixing.mode is ColorMixingMode.RGBW
        assert head.color_mixing.channels == {
            'red': base + 2, 'green': base + 3, 'blue': base + 4, 'white': base + 5,
        }

    # Head offsets distributed along the bar's local X axis.
    offsets_x = [h.offset_m[0] for h in caps.emitter.heads]
    assert offsets_x == sorted(offsets_x)
    assert offsets_x[0] < 0 < offsets_x[-1]

    # No chassis-level movement / color when everything is per-head.
    assert caps.movement is None
    assert caps.color_mixing is None


def test_pixel_matrix_via_heads_yields_cell_array_panel():
    """A 4x3 LED matrix described via 12 <Head> blocks → CellArray(4,3), Chassis=PANEL."""
    channel_defs = ''.join(
        f'<Channel Name="R{i}" Preset="IntensityRed"/>'
        f'<Channel Name="G{i}" Preset="IntensityGreen"/>'
        f'<Channel Name="B{i}" Preset="IntensityBlue"/>'
        for i in range(12)
    )
    mode_channels = []
    head_blocks = []
    ch = 0
    for i in range(12):
        cells_in_head = []
        for component in ('R', 'G', 'B'):
            mode_channels.append(f'<Channel Number="{ch}">{component}{i}</Channel>')
            cells_in_head.append(ch)
            ch += 1
        head_blocks.append(
            '<Head>' + ''.join(f'<Channel>{c}</Channel>' for c in cells_in_head) + '</Head>'
        )

    root = _qxf(
        '<Manufacturer>Test</Manufacturer><Model>Matrix4x3</Model><Type>LED Matrix</Type>'
        + channel_defs
        + '<Mode Name="36 Channel">'
        + ''.join(mode_channels)
        + ''.join(head_blocks)
        + '</Mode>'
        '<Physical>'
        '  <Dimensions Width="400" Height="300" Depth="80"/>'
        '  <Lens Name="Other" DegreesMin="0" DegreesMax="0"/>'
        '  <Focus Type="Fixed" PanMax="0" TiltMax="0"/>'
        '  <Layout Width="4" Height="3"/>'
        '</Physical>'
    )
    caps = detect_capabilities(root, '36 Channel')

    assert caps.chassis is Chassis.PANEL
    assert isinstance(caps.emitter, CellArray)
    assert caps.emitter.width == 4
    assert caps.emitter.height == 3
    assert len(caps.emitter.cells) == 12
    for i, cell in enumerate(caps.emitter.cells):
        base = i * 3
        assert cell.red_channel == base
        assert cell.green_channel == base + 1
        assert cell.blue_channel == base + 2
    # No chassis-level color (per-cell)
    assert caps.color_mixing is None
    assert caps.movement is None
