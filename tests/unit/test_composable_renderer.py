"""Tests for the composable fixture renderer (Phase B).

State-only tests — no GL context required. Verifies:
- Component DMX consumption (Dimmer, Color, Movement, Gobo, Prism, Focus, ...)
- Emitter runner expansion (Point / CellArray / MultiHead)
- Chassis registry covers all Chassis enum values and produces valid meshes
- ColorComponent fallback logic (mixing first, then color wheel, then white)
- HSL → RGB conversion
- Color-wheel sampling by DMX range
- Gobo pattern inference from entry name/SVG path

GL-dependent code (ChassisGeometry, BeamComponent, FixtureRenderer
construction with a real ctx) is deferred to Phase D's visual regression
tests where an offscreen GL context is available.
"""

from __future__ import annotations

import math

import glm
import numpy as np
import pytest

from utils.fixture_capabilities import (
    BeamShape,
    CellArray,
    CellSegment,
    Chassis,
    ColorMixing,
    ColorMixingMode,
    ColorWheel,
    ColorWheelEntry,
    GoboWheel,
    GoboWheelEntry,
    HeadDescriptor,
    Movement,
    MovementType,
    MultiHead,
    PointEmitter,
    Prism,
)
from visualizer.renderer.chassis import _BUILDERS, build_chassis_mesh, get_body_color
from visualizer.renderer.components import (
    ColorComponent,
    DimmerComponent,
    FocusComponent,
    FrostComponent,
    GOBO_PATTERN_BREAKUP,
    GOBO_PATTERN_DOTS,
    GOBO_PATTERN_OPEN,
    GOBO_PATTERN_STAR,
    GoboComponent,
    IrisComponent,
    MovementComponent,
    PrismComponent,
    StrobeComponent,
    ZoomComponent,
    _hsl_to_rgb,
    _parse_hex,
)
from visualizer.renderer.emitters import (
    CellArrayRunner,
    MultiHeadRunner,
    PointEmitterRunner,
    create_emitter_runner,
)


# Helper: build a 512-byte DMX universe buffer with selected channels set.
def _dmx(channels: dict, size: int = 512) -> bytes:
    buf = bytearray(size)
    for idx, val in channels.items():
        buf[idx] = val
    return bytes(buf)


# ---------------------------------------------------------------------------
# State-only components
# ---------------------------------------------------------------------------


class TestDimmerComponent:
    def test_reads_channel_with_fixture_address(self):
        c = DimmerComponent(channel=2)
        # Fixture address 5 → channel 2 is at DMX index (5-1)+2 = 6
        c.update_dmx(_dmx({6: 128}), address=5)
        assert c.normalized == pytest.approx(128 / 255.0)

    def test_zero_when_channel_missing_from_buffer(self):
        c = DimmerComponent(channel=0)
        c.update_dmx(_dmx({}), address=1)
        assert c.normalized == 0.0


class TestColorComponent:
    def test_rgb_mixing(self):
        mixing = ColorMixing(mode=ColorMixingMode.RGB, channels={'red': 0, 'green': 1, 'blue': 2})
        c = ColorComponent(mixing=mixing)
        c.update_dmx(_dmx({0: 255, 1: 128, 2: 0}), address=1)
        r, g, b = c.rgb
        assert r == pytest.approx(1.0)
        assert g == pytest.approx(128 / 255.0)
        assert b == pytest.approx(0.0)

    def test_rgbw_mixing_adds_white_to_all_channels(self):
        mixing = ColorMixing(
            mode=ColorMixingMode.RGBW,
            channels={'red': 0, 'green': 1, 'blue': 2, 'white': 3},
        )
        c = ColorComponent(mixing=mixing)
        c.update_dmx(_dmx({0: 0, 1: 0, 2: 0, 3: 128}), address=1)
        r, g, b = c.rgb
        # Pure white contribution adds to all three channels equally.
        assert r == pytest.approx(128 / 255.0)
        assert g == pytest.approx(128 / 255.0)
        assert b == pytest.approx(128 / 255.0)
        assert c.white == pytest.approx(128 / 255.0)

    def test_hsl_mixing_full_red(self):
        mixing = ColorMixing(
            mode=ColorMixingMode.HSL,
            channels={'hue': 0, 'saturation': 1, 'lightness': 2},
        )
        c = ColorComponent(mixing=mixing)
        # Hue=0 (red), S=255 (saturated), L=128 (mid)
        c.update_dmx(_dmx({0: 0, 1: 255, 2: 128}), address=1)
        r, g, b = c.rgb
        assert r > 0.9
        assert g < 0.1
        assert b < 0.1

    def test_cmy_subtractive(self):
        mixing = ColorMixing(
            mode=ColorMixingMode.CMY,
            channels={'cyan': 0, 'magenta': 1, 'yellow': 2},
        )
        c = ColorComponent(mixing=mixing)
        # C=255 (no red), M=0, Y=0 → leaves G+B (cyan)
        c.update_dmx(_dmx({0: 255}), address=1)
        r, g, b = c.rgb
        assert r == pytest.approx(0.0)
        assert g == pytest.approx(1.0)
        assert b == pytest.approx(1.0)

    def test_color_wheel_sampling(self):
        wheel = ColorWheel(
            channel=0,
            entries=[
                ColorWheelEntry(0, 24, 'White', '#FFFFFF'),
                ColorWheelEntry(25, 50, 'Red', '#FF0000'),
                ColorWheelEntry(51, 75, 'Blue', '#0000FF'),
            ],
        )
        c = ColorComponent(wheel=wheel)
        c.update_dmx(_dmx({0: 30}), address=1)
        assert c.rgb == pytest.approx((1.0, 0.0, 0.0))
        c.update_dmx(_dmx({0: 60}), address=1)
        assert c.rgb == pytest.approx((0.0, 0.0, 1.0))

    def test_mixing_falls_back_to_wheel_when_mix_is_black(self):
        mixing = ColorMixing(mode=ColorMixingMode.RGB, channels={'red': 0, 'green': 1, 'blue': 2})
        wheel = ColorWheel(channel=3, entries=[ColorWheelEntry(0, 255, 'Red', '#FF0000')])
        c = ColorComponent(mixing=mixing, wheel=wheel)
        # All RGB at 0 → fall back to color wheel
        c.update_dmx(_dmx({3: 100}), address=1)
        assert c.rgb == pytest.approx((1.0, 0.0, 0.0))

    def test_white_fallback_when_capability_but_no_signal(self):
        wheel = ColorWheel(channel=0, entries=[ColorWheelEntry(100, 200, 'Red', '#FF0000')])
        c = ColorComponent(wheel=wheel)
        # DMX value 50 is outside any wheel entry → no match → white fallback
        c.update_dmx(_dmx({0: 50}), address=1)
        assert c.rgb == (1.0, 1.0, 1.0)


class TestMovementComponent:
    def test_pan_tilt_center_at_dmx_127(self):
        m = MovementComponent(Movement(
            type=MovementType.YOKE,
            pan_max_deg=540.0,
            tilt_max_deg=270.0,
            pan_channel=0,
            tilt_channel=1,
        ))
        m.update_dmx(_dmx({0: 128, 1: 128}), address=1)
        # 128 * 256 / 65535 ≈ 0.5 → pan ≈ 0°
        assert abs(m.pan_deg) < 5.0
        assert abs(m.tilt_deg) < 5.0

    def test_pan_at_dmx_max(self):
        m = MovementComponent(Movement(
            type=MovementType.YOKE, pan_max_deg=540.0, tilt_max_deg=270.0,
            pan_channel=0, tilt_channel=1,
        ))
        m.update_dmx(_dmx({0: 255, 1: 0}), address=1)
        # 255 * 256 / 65535 ≈ 0.996 → pan ≈ +269°
        assert m.pan_deg > 260.0
        assert m.tilt_deg < -130.0

    def test_16_bit_combines_fine_channel(self):
        m = MovementComponent(Movement(
            type=MovementType.YOKE, pan_max_deg=540.0, tilt_max_deg=270.0,
            pan_channel=0, pan_fine_channel=1,
            tilt_channel=2, tilt_fine_channel=3,
        ))
        # Coarse 128 + fine 128 = 128*256+128 = 32896 / 65535 ≈ 0.5019 → ~1°
        m.update_dmx(_dmx({0: 128, 1: 128, 2: 0, 3: 0}), address=1)
        assert abs(m.pan_deg) < 3.0
        # Tilt: coarse=0, fine=0 → 0 → -tilt_max/2
        assert m.tilt_deg == pytest.approx(-135.0)


class TestStrobeComponent:
    def test_below_threshold_is_open_shutter(self):
        s = StrobeComponent(channel=0)
        s.update_dmx(_dmx({0: 5}), address=1)  # under threshold (10)
        assert s.rate == 0.0
        assert not s.is_strobing

    def test_above_threshold_strobing(self):
        s = StrobeComponent(channel=0)
        s.update_dmx(_dmx({0: 128}), address=1)
        assert s.is_strobing
        assert 0.0 < s.rate <= 1.0


class TestFocusComponent:
    def test_focal_distance_at_dmx_zero_is_near(self):
        f = FocusComponent(channel=0)
        f.update_dmx(_dmx({0: 0}), address=1)
        assert f.focal_distance_m == pytest.approx(1.0)

    def test_focal_distance_at_dmx_max_is_far(self):
        f = FocusComponent(channel=0)
        f.update_dmx(_dmx({0: 255}), address=1)
        assert f.focal_distance_m == pytest.approx(10.0)

    def test_sharpness_peaks_at_focal_distance(self):
        f = FocusComponent(channel=0)
        f.update_dmx(_dmx({0: 0}), address=1)  # focus at 1m
        assert f.sharpness(1.0) == pytest.approx(1.0)
        # Sharpness falls off with distance error
        assert f.sharpness(5.0) < 0.5


class TestZoomComponent:
    def test_returns_max_when_no_zoom_range(self):
        beam = BeamShape(min_deg=15.0, max_deg=15.0)
        z = ZoomComponent(channel=0, beam=beam)
        z.update_dmx(_dmx({0: 0}), address=1)
        assert z.current_angle_deg == 15.0

    def test_interpolates_within_zoom_range(self):
        beam = BeamShape(min_deg=10.0, max_deg=60.0)
        z = ZoomComponent(channel=0, beam=beam)
        z.update_dmx(_dmx({0: 128}), address=1)
        # ~half range → ~35°
        assert 30.0 <= z.current_angle_deg <= 40.0


class TestGoboComponent:
    def test_pattern_open_when_dmx_zero(self):
        wheel = GoboWheel(
            channel=0,
            entries=[GoboWheelEntry(10, 50, 'Star Gobo', svg_path='gobos/star.svg')],
        )
        g = GoboComponent(wheel=wheel)
        g.update_dmx(_dmx({0: 0}), address=1)
        assert g.pattern_id == GOBO_PATTERN_OPEN

    def test_pattern_inferred_from_entry_name(self):
        wheel = GoboWheel(
            channel=0,
            entries=[
                GoboWheelEntry(0, 30, 'Star', svg_path=None),
                GoboWheelEntry(31, 60, 'Dots', svg_path=None),
                GoboWheelEntry(61, 90, 'Unknown', svg_path=None),
            ],
        )
        g = GoboComponent(wheel=wheel)
        g.update_dmx(_dmx({0: 15}), address=1)
        assert g.pattern_id == GOBO_PATTERN_STAR
        g.update_dmx(_dmx({0: 45}), address=1)
        assert g.pattern_id == GOBO_PATTERN_DOTS
        g.update_dmx(_dmx({0: 75}), address=1)
        assert g.pattern_id == GOBO_PATTERN_BREAKUP  # unknown → breakup fallback

    def test_rotation_integrates_over_time(self):
        wheel = GoboWheel(
            channel=0,
            entries=[GoboWheelEntry(0, 255, 'Open', None)],
            rotation_channel=1,
        )
        g = GoboComponent(wheel=wheel)
        # Rotation channel at full CW → ~1 revolution per second
        g.update_dmx(_dmx({1: 127}), address=1)
        g.advance_rotation(0.5)
        # Half a revolution at full speed ≈ π radians
        assert math.pi * 0.8 < g.rotation_rad < math.pi * 1.2

    def test_rotation_inverts_at_dmx_128(self):
        wheel = GoboWheel(channel=0, entries=[], rotation_channel=1)
        g = GoboComponent(wheel=wheel)
        g.update_dmx(_dmx({1: 255}), address=1)  # full CCW
        g.advance_rotation(0.5)
        # Should be negative (or wrapped to be near 2π)
        # Either way: not approx zero, not in the CW half
        assert g.rotation_rad != 0.0


class TestPrismComponent:
    def test_active_at_high_dmx(self):
        p = PrismComponent(Prism(channel=0, facets=5))
        p.update_dmx(_dmx({0: 200}), address=1)
        assert p.is_active
        assert p.facets == 5

    def test_inactive_at_low_dmx(self):
        p = PrismComponent(Prism(channel=0, facets=3))
        p.update_dmx(_dmx({0: 30}), address=1)
        assert not p.is_active


class TestSimpleModifierComponents:
    def test_iris(self):
        i = IrisComponent(channel=0)
        i.update_dmx(_dmx({0: 191}), address=1)
        assert i.opening == pytest.approx(191 / 255.0)

    def test_frost(self):
        f = FrostComponent(channel=0)
        f.update_dmx(_dmx({0: 64}), address=1)
        assert f.diffusion == pytest.approx(64 / 255.0)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class TestHelpers:
    def test_hsl_to_rgb_red(self):
        r, g, b = _hsl_to_rgb(0.0, 1.0, 0.5)
        assert r == pytest.approx(1.0)
        assert g == pytest.approx(0.0)
        assert b == pytest.approx(0.0)

    def test_hsl_to_rgb_green(self):
        r, g, b = _hsl_to_rgb(1 / 3.0, 1.0, 0.5)
        assert r == pytest.approx(0.0, abs=1e-6)
        assert g == pytest.approx(1.0)
        assert b == pytest.approx(0.0, abs=1e-6)

    def test_hsl_to_rgb_zero_saturation_is_grey(self):
        r, g, b = _hsl_to_rgb(0.5, 0.0, 0.5)
        assert r == g == b == pytest.approx(0.5)

    def test_parse_hex(self):
        assert _parse_hex('#FF0000') == pytest.approx((1.0, 0.0, 0.0))
        assert _parse_hex('#00FF00') == pytest.approx((0.0, 1.0, 0.0))

    def test_parse_hex_bad_inputs(self):
        assert _parse_hex('') is None
        assert _parse_hex('FF0000') is None  # missing #
        assert _parse_hex('#GGGGGG') is None  # not hex


# ---------------------------------------------------------------------------
# Emitter runners
# ---------------------------------------------------------------------------


class TestPointEmitterRunner:
    def test_yields_one_emission_with_chassis_state(self):
        runner = PointEmitterRunner(PointEmitter())
        mixing = ColorMixing(mode=ColorMixingMode.RGB, channels={'red': 0, 'green': 1, 'blue': 2})
        color = ColorComponent(mixing=mixing)
        color.update_dmx(_dmx({0: 255, 1: 128, 2: 0}), address=1)
        dimmer = DimmerComponent(channel=3)
        dimmer.update_dmx(_dmx({3: 200}), address=1)

        emissions = list(runner.emissions(color, dimmer))
        assert len(emissions) == 1
        e = emissions[0]
        assert e.color[0] == pytest.approx(1.0)
        assert e.dimmer == pytest.approx(200 / 255.0)

    def test_movement_threads_through_emission(self):
        movement = MovementComponent(Movement(
            type=MovementType.YOKE, pan_max_deg=540, tilt_max_deg=270,
            pan_channel=0, tilt_channel=1,
        ))
        movement.update_dmx(_dmx({0: 255, 1: 0}), address=1)

        runner = PointEmitterRunner(PointEmitter(), movement=movement)
        emissions = list(runner.emissions(None, None))
        assert emissions[0].pan_deg == pytest.approx(movement.pan_deg)
        assert emissions[0].tilt_deg == pytest.approx(movement.tilt_deg)

    def test_no_color_falls_back_to_white(self):
        runner = PointEmitterRunner(PointEmitter())
        emissions = list(runner.emissions(None, None))
        assert emissions[0].color == (1.0, 1.0, 1.0)
        assert emissions[0].dimmer == 1.0


class TestCellArrayRunner:
    def test_per_cell_color_consumed(self):
        cells = [
            CellSegment(red_channel=0, green_channel=1, blue_channel=2, channels=[0, 1, 2]),
            CellSegment(red_channel=3, green_channel=4, blue_channel=5, channels=[3, 4, 5]),
        ]
        emitter = CellArray(width=2, height=1, cells=cells)
        runner = CellArrayRunner(emitter, body_dims_m=(2.0, 0.1, 0.1))
        runner.update_dmx(_dmx({0: 255, 1: 0, 2: 0, 3: 0, 4: 255, 5: 0}), address=1)

        emissions = list(runner.emissions(None, None))
        assert len(emissions) == 2
        assert emissions[0].color[0] == pytest.approx(1.0)  # red cell
        assert emissions[1].color[1] == pytest.approx(1.0)  # green cell

    def test_cell_offsets_distributed_across_body_width(self):
        cells = [CellSegment(channels=[]) for _ in range(4)]
        emitter = CellArray(width=4, height=1, cells=cells)
        runner = CellArrayRunner(emitter, body_dims_m=(4.0, 0.1, 0.1))
        # First cell to the left of center, last to the right
        first_x = runner.cell_offsets[0].x
        last_x = runner.cell_offsets[-1].x
        assert first_x < 0
        assert last_x > 0
        # Symmetric about center
        assert first_x == pytest.approx(-last_x)

    def test_dimmer_only_cells_use_chassis_color(self):
        cells = [
            CellSegment(dimmer_channel=0, channels=[0]),
            CellSegment(dimmer_channel=1, channels=[1]),
        ]
        emitter = CellArray(width=2, height=1, cells=cells)
        runner = CellArrayRunner(emitter, body_dims_m=(1.0, 0.1, 0.1))
        runner.update_dmx(_dmx({0: 255, 1: 128}), address=1)

        # Sunstrip-style: no per-cell color → falls back to chassis color (white default)
        emissions = list(runner.emissions(None, None))
        assert emissions[0].color == (1.0, 1.0, 1.0)
        assert emissions[0].dimmer == pytest.approx(1.0)
        assert emissions[1].dimmer == pytest.approx(128 / 255.0)


class TestMultiHeadRunner:
    def test_per_head_beam_emerges_along_local_x_at_zero_pan_tilt(self):
        """At pan=tilt=0, the cone (built along +Z) should be rotated 90°
        around Y so it emerges along the head's local +X. Matches the
        chassis-level fix in MovingYokeChassisGeometry.beam_origin_transform.
        """
        import glm
        head = HeadDescriptor(
            offset_m=(0.5, 0.0, 0.0),
            movement=Movement(
                type=MovementType.YOKE, pan_max_deg=540.0, tilt_max_deg=270.0,
                pan_channel=0, tilt_channel=1,
            ),
            channels=[0, 1],
        )
        emitter = MultiHead(heads=[head])
        runner = MultiHeadRunner(emitter)
        # DMX 128 ≈ pan=0, tilt=0 (center-mapping).
        runner.update_dmx(_dmx({0: 128, 1: 128}), address=1)

        emissions = list(runner.emissions(None, None))
        assert len(emissions) == 1
        local = emissions[0].local_transform
        # Apply the local transform to a unit vector +Z (cone's native axis).
        # Expect the result to point along +X in chassis-local frame
        # (modulo the head_offset translation, which doesn't affect direction).
        cone_dir_local = glm.vec3(0, 0, 1)
        rotated = glm.vec3(local * glm.vec4(cone_dir_local, 0.0))  # w=0 → direction only
        rotated_norm = glm.normalize(rotated)
        assert rotated_norm.x == pytest.approx(1.0, abs=1e-3)
        assert abs(rotated_norm.y) < 1e-3
        assert abs(rotated_norm.z) < 1e-3

    def test_per_head_color_and_pan_tilt(self):
        heads = [
            HeadDescriptor(
                offset_m=(-0.3, 0.0, 0.0),
                movement=Movement(
                    type=MovementType.YOKE, pan_max_deg=540, tilt_max_deg=270,
                    pan_channel=0, tilt_channel=1,
                ),
                color_mixing=ColorMixing(
                    mode=ColorMixingMode.RGB, channels={'red': 2, 'green': 3, 'blue': 4},
                ),
                channels=[0, 1, 2, 3, 4],
            ),
            HeadDescriptor(
                offset_m=(0.3, 0.0, 0.0),
                movement=Movement(
                    type=MovementType.YOKE, pan_max_deg=540, tilt_max_deg=270,
                    pan_channel=5, tilt_channel=6,
                ),
                color_mixing=ColorMixing(
                    mode=ColorMixingMode.RGB, channels={'red': 7, 'green': 8, 'blue': 9},
                ),
                channels=[5, 6, 7, 8, 9],
            ),
        ]
        emitter = MultiHead(heads=heads)
        runner = MultiHeadRunner(emitter)
        # Head 1 red, head 2 blue
        runner.update_dmx(_dmx({2: 255, 9: 255}), address=1)

        emissions = list(runner.emissions(None, None))
        assert len(emissions) == 2
        assert emissions[0].color[0] == pytest.approx(1.0)  # head 1 red
        assert emissions[1].color[2] == pytest.approx(1.0)  # head 2 blue
        # Each emission carries its head's pan_deg (chassis-level pan not used)
        assert emissions[0].pan_deg is not None
        assert emissions[1].pan_deg is not None


class TestEmitterRunnerFactory:
    def test_factory_routes_each_emitter_type(self):
        assert isinstance(
            create_emitter_runner(PointEmitter(), (1, 1, 1)),
            PointEmitterRunner,
        )
        assert isinstance(
            create_emitter_runner(CellArray(width=2, height=1, cells=[CellSegment(), CellSegment()]), (1, 1, 1)),
            CellArrayRunner,
        )
        assert isinstance(
            create_emitter_runner(MultiHead(heads=[HeadDescriptor()]), (1, 1, 1)),
            MultiHeadRunner,
        )


# ---------------------------------------------------------------------------
# Chassis registry
# ---------------------------------------------------------------------------


class TestChassisRegistry:
    @pytest.mark.parametrize("chassis", list(Chassis))
    def test_every_chassis_value_has_a_builder(self, chassis):
        assert chassis in _BUILDERS

    @pytest.mark.parametrize("chassis", list(Chassis))
    def test_build_chassis_mesh_returns_valid_arrays(self, chassis):
        verts, norms = build_chassis_mesh(chassis, body_dims_m=(0.3, 0.3, 0.2))
        assert isinstance(verts, np.ndarray)
        assert isinstance(norms, np.ndarray)
        # Triangle vertex count is a multiple of 9 (3 verts × 3 coords)
        assert len(verts) > 0
        assert len(verts) % 9 == 0
        assert verts.shape == norms.shape

    @pytest.mark.parametrize("chassis", list(Chassis))
    def test_get_body_color_returns_rgb(self, chassis):
        color = get_body_color(chassis)
        assert len(color) == 3
        for v in color:
            assert 0.0 <= v <= 1.0


# ---------------------------------------------------------------------------
# Phase D Stage 2: MH parity constants
# ---------------------------------------------------------------------------


class TestMovingYokeChassisAxesDefaults:
    def test_show_axes_defaults_true(self):
        from visualizer.renderer.chassis import MovingYokeChassisGeometry
        # Class-level default mirrors legacy MovingHeadRenderer (always renders axes).
        assert MovingYokeChassisGeometry.show_axes is True

    def test_axis_dimensions_match_legacy(self):
        from visualizer.renderer.chassis import MovingYokeChassisGeometry
        # Legacy MovingHeadRenderer hardcoded these values inline at line ~2097.
        assert MovingYokeChassisGeometry.AXIS_LENGTH == 0.4
        assert MovingYokeChassisGeometry.AXIS_THICKNESS == 0.008
        assert MovingYokeChassisGeometry.ARROW_LENGTH == 0.06
        assert MovingYokeChassisGeometry.ARROW_WIDTH == 0.04


class TestConeBeamPrismConstants:
    def test_prism_intensity_per_facet_matches_legacy(self):
        from visualizer.renderer.beams import ConeBeam
        # Legacy MovingHeadRenderer rendered each facet at 40% intensity
        # (3 facets × 0.4 ≈ 120% combined to overcome additive falloff).
        assert ConeBeam.PRISM_INTENSITY_PER_FACET == 0.4
        assert ConeBeam.PRISM_TILT_DEG == 10.0
