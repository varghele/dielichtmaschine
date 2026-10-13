"""Tests for the extracted effects module."""

import math
import pytest

from effects.types import DimmerContext, DimmerResult, MovementContext, MovementResult
from effects.timing import parse_speed, get_bpm, movement_total_cycles, MOVEMENT_CYCLES_PER_BAR
from effects.dimmer_effects import (
    DIMMER_REGISTRY, static, strobe, sparkle, ping_pong,
    random_stroke, waterfall, chase, fill,
    pulse, stroke, wave,
    heartbeat, throb, fade, cascade,
)
from effects.movement_effects import (
    MOVEMENT_REGISTRY, circle, diamond, square, triangle,
    figure_8, lissajous, random_movement, bounce,
    static as movement_static,
)


class TestMovementRate:
    """Movement runs at one cycle per 4 bars at speed 1 (rate cut 4x)."""

    def test_default_is_quarter_cycle_per_bar(self):
        assert MOVEMENT_CYCLES_PER_BAR == 0.25

    def test_one_cycle_per_four_bars_at_speed_1(self):
        # 4 bars long, 2s per bar, speed 1 -> exactly one full cycle.
        assert movement_total_cycles(8.0, 2.0, 1.0) == pytest.approx(1.0)

    def test_speed_multiplier_scales_rate(self):
        # speed 2 doubles the rate; speed 1/2 halves it.
        assert movement_total_cycles(8.0, 2.0, 2.0) == pytest.approx(2.0)
        assert movement_total_cycles(8.0, 2.0, 0.5) == pytest.approx(0.5)

    def test_four_times_slower_than_one_cycle_per_bar(self):
        # A single bar at speed 1 yields a quarter cycle (was 1.0 before the fix).
        assert movement_total_cycles(2.0, 2.0, 1.0) == pytest.approx(0.25)

    def test_non_positive_duration_is_zero(self):
        assert movement_total_cycles(0.0, 2.0, 1.0) == 0.0
        assert movement_total_cycles(8.0, 0.0, 1.0) == 0.0


def _make_dimmer_ctx(**overrides):
    """Create a DimmerContext with sensible defaults."""
    defaults = dict(
        time_in_block=0.5,
        block_duration=4.0,
        intensity=255.0,
        speed_multiplier=1.0,
        bpm=120.0,
        fixture_index=0,
        total_fixtures=4,
        num_segments=8,
        fixture_name="TestFixture",
        block_start_time=10.0,
        is_segmented=False,
    )
    defaults.update(overrides)
    return DimmerContext(**defaults)


def _make_movement_ctx(**overrides):
    """Create a MovementContext with sensible defaults."""
    defaults = dict(
        t=math.pi / 2,
        progress=0.25,
        total_cycles=4.0,
        center_pan=127.5,
        center_tilt=127.5,
        pan_amplitude=50.0,
        tilt_amplitude=50.0,
        fixture_index=0,
        total_fixtures=4,
        phase_offset_enabled=False,
        phase_offset_degrees=0.0,
        lissajous_ratio="1:2",
    )
    defaults.update(overrides)
    return MovementContext(**defaults)


# ──────────────────────────────────────────────
# Timing helpers
# ──────────────────────────────────────────────

class TestParseSpeed:
    def test_integer(self):
        assert parse_speed("1") == 1.0
        assert parse_speed("2") == 2.0
        assert parse_speed("4") == 4.0

    def test_fraction(self):
        assert parse_speed("1/2") == 0.5
        assert parse_speed("1/4") == 0.25
        assert parse_speed("1/8") == 0.125

    def test_invalid(self):
        assert parse_speed("abc") == 1.0
        assert parse_speed("1/0") == 1.0

    def test_float_string(self):
        assert parse_speed("0.5") == 0.5


class TestGetBpm:
    def test_none_song_structure(self):
        assert get_bpm(None, 5.0) == 120.0

    def test_with_song_structure(self):
        class MockSS:
            def get_bpm_at_time(self, t):
                return 140.0
        assert get_bpm(MockSS(), 5.0) == 140.0


# ──────────────────────────────────────────────
# Registry completeness
# ──────────────────────────────────────────────

class TestRegistries:
    def test_dimmer_registry_has_all_15(self):
        expected = {
            "static", "stroke", "throb", "ping_pong", "chase",
            "wave", "waterfall", "fill", "random_stroke", "sparkle",
            "pulse", "strobe", "fade", "cascade", "heartbeat",
        }
        assert set(DIMMER_REGISTRY.keys()) == expected

    def test_movement_registry_has_all_11(self):
        expected = {
            "static", "circle", "diamond", "square", "triangle",
            "figure_8", "lissajous", "random", "bounce",
            "linear_sweep", "fan",
        }
        assert set(MOVEMENT_REGISTRY.keys()) == expected

    def test_all_dimmer_effects_return_dimmer_result(self):
        ctx = _make_dimmer_ctx()
        for name, fn in DIMMER_REGISTRY.items():
            result = fn(ctx)
            assert isinstance(result, DimmerResult), f"{name} returned {type(result)}"

    def test_all_movement_effects_return_movement_result(self):
        ctx = _make_movement_ctx()
        for name, fn in MOVEMENT_REGISTRY.items():
            result = fn(ctx)
            assert isinstance(result, MovementResult), f"{name} returned {type(result)}"


# ──────────────────────────────────────────────
# Dimmer effects
# ──────────────────────────────────────────────

class TestStaticDimmer:
    def test_returns_full(self):
        result = static(_make_dimmer_ctx())
        assert result.intensity_multiplier == 1.0
        assert result.segment_intensities is None


class TestStrobe:
    def test_on_phase(self):
        # At t=0, strobe_hz=2, phase=0 → on
        result = strobe(_make_dimmer_ctx(time_in_block=0.0))
        assert result.intensity_multiplier == 1.0

    def test_off_phase(self):
        # At t=0.3, strobe_hz=2, phase=0.6 → off
        result = strobe(_make_dimmer_ctx(time_in_block=0.3))
        assert result.intensity_multiplier == 0.0

    def test_speed_affects_frequency(self):
        # speed_multiplier=2 → strobe_hz=4 → period=0.25s
        # At t=0.1, phase=(0.1*4)%1.0=0.4 → on
        result = strobe(_make_dimmer_ctx(time_in_block=0.1, speed_multiplier=2.0))
        assert result.intensity_multiplier == 1.0


class TestSparkle:
    def test_returns_segment_intensities(self):
        ctx = _make_dimmer_ctx(is_segmented=True, num_segments=4)
        result = sparkle(ctx)
        assert result.segment_intensities is not None
        assert len(result.segment_intensities) == 4
        for v in result.segment_intensities:
            assert 0.3 <= v <= 1.0

    def test_non_segmented_also_returns_segments(self):
        ctx = _make_dimmer_ctx(is_segmented=False, num_segments=2)
        result = sparkle(ctx)
        assert result.segment_intensities is not None
        assert len(result.segment_intensities) == 2

    def test_deterministic(self):
        ctx = _make_dimmer_ctx(time_in_block=1.0, fixture_name="FixA")
        r1 = sparkle(ctx)
        r2 = sparkle(ctx)
        assert r1.segment_intensities == r2.segment_intensities


class TestPingPong:
    def test_single_fixture(self):
        ctx = _make_dimmer_ctx(total_fixtures=1)
        result = ping_pong(ctx)
        assert result.intensity_multiplier == 1.0

    def test_segmented_returns_segments(self):
        ctx = _make_dimmer_ctx(is_segmented=True, num_segments=4, total_fixtures=1)
        result = ping_pong(ctx)
        assert result.segment_intensities is not None
        assert len(result.segment_intensities) == 4


class TestThrob:
    def test_at_beat_start_is_full(self):
        result = throb(_make_dimmer_ctx(time_in_block=0.0))
        assert result.intensity_multiplier == pytest.approx(1.0)

    def test_decays_but_not_below_floor(self):
        result = throb(_make_dimmer_ctx(time_in_block=10.0))
        assert result.intensity_multiplier >= 0.7


class TestStroke:
    def test_at_start_is_full(self):
        result = stroke(_make_dimmer_ctx(time_in_block=0.0))
        assert result.intensity_multiplier == pytest.approx(1.0)

    def test_decays_toward_zero(self):
        # At end of beat, should be near 0
        seconds_per_beat = 60.0 / 120.0  # 0.5s
        result = stroke(_make_dimmer_ctx(time_in_block=0.49))
        assert result.intensity_multiplier < 0.1


class TestPulse:
    def test_varies_over_bar(self):
        results = []
        for t in [0.0, 0.5, 1.0, 1.5]:
            r = pulse(_make_dimmer_ctx(time_in_block=t))
            results.append(r.intensity_multiplier)
        # Should not all be the same
        assert len(set(round(v, 2) for v in results)) > 1
        # All within bounds
        for v in results:
            assert 0.3 <= v <= 1.0


class TestHeartbeat:
    def test_floor_during_rest(self):
        # Rest phase is cycle_pos > 0.5
        # At 120 BPM, bar = 2s, cycle_time = 2s, cycle_pos at t=1.5 => 0.75
        result = heartbeat(_make_dimmer_ctx(time_in_block=1.5))
        assert result.intensity_multiplier == pytest.approx(0.2)


class TestWaterfall:
    def test_segmented_returns_segments(self):
        ctx = _make_dimmer_ctx(is_segmented=True, num_segments=8)
        result = waterfall(ctx)
        assert result.segment_intensities is not None
        assert len(result.segment_intensities) == 8

    # Non-segmented fixtures: one sweep across the lane's fixtures, one
    # beat (0.5 s at 120 BPM, speed 1) per fixture (decision 2026-10-12;
    # it used to be static natively while the export cascaded).

    @staticmethod
    def _levels(time_s, direction="down", total=4):
        return [waterfall(_make_dimmer_ctx(
            is_segmented=False, fixture_index=i, total_fixtures=total,
            time_in_block=time_s, direction=direction)).intensity_multiplier
            for i in range(total)]

    def test_non_segmented_down_starts_at_the_last_fixture(self):
        levels = self._levels(0.0)
        assert levels.index(max(levels)) == 3
        assert max(levels) == pytest.approx(1.0)

    def test_non_segmented_head_steps_one_fixture_per_beat(self):
        heads = [max(range(4), key=self._levels(beat * 0.5).__getitem__)
                 for beat in range(5)]
        assert heads == [3, 2, 1, 0, 3]

    def test_non_segmented_up_runs_the_other_way(self):
        heads = [max(range(4), key=self._levels(beat * 0.5, "up").__getitem__)
                 for beat in range(5)]
        assert heads == [0, 1, 2, 3, 0]

    def test_non_segmented_has_a_decaying_tail_not_a_blackout(self):
        levels = self._levels(0.0)
        assert all(0.2 < level <= 1.0 for level in levels)
        # Behind the head (down: towards higher indices, wrapping) the
        # level falls off monotonically.
        assert levels[3] > levels[0] > levels[1] > levels[2]

    def test_single_fixture_stays_static(self):
        assert self._levels(0.37, total=1) == [1.0]


class TestChase:
    def test_segmented(self):
        ctx = _make_dimmer_ctx(is_segmented=True, num_segments=8)
        result = chase(ctx)
        assert result.segment_intensities is not None
        assert len(result.segment_intensities) == 8

    def test_fixture_based(self):
        ctx = _make_dimmer_ctx(is_segmented=False, fixture_index=0, total_fixtures=4)
        result = chase(ctx)
        assert result.segment_intensities is None
        assert 0.0 <= result.intensity_multiplier <= 1.0


class TestFill:
    def test_segmented(self):
        ctx = _make_dimmer_ctx(is_segmented=True, num_segments=8)
        result = fill(ctx)
        assert result.segment_intensities is not None
        assert len(result.segment_intensities) == 8


class TestFade:
    def test_returns_dimmer_result(self):
        ctx = _make_dimmer_ctx()
        result = fade(ctx)
        assert isinstance(result, DimmerResult)

    def test_intensity_in_range(self):
        ctx = _make_dimmer_ctx(time_in_block=0.5)
        result = fade(ctx)
        assert 0.0 <= result.intensity_multiplier <= 1.0


class TestCascade:
    def test_returns_dimmer_result(self):
        ctx = _make_dimmer_ctx()
        result = cascade(ctx)
        assert isinstance(result, DimmerResult)

    def test_segmented_returns_segments(self):
        ctx = _make_dimmer_ctx(is_segmented=True, num_segments=8)
        result = cascade(ctx)
        assert result.segment_intensities is not None
        assert len(result.segment_intensities) == 8


# ──────────────────────────────────────────────
# Movement effects
# ──────────────────────────────────────────────

class TestStaticMovement:
    def test_returns_center(self):
        ctx = _make_movement_ctx(center_pan=100.0, center_tilt=200.0)
        result = movement_static(ctx)
        assert result.pan == 100.0
        assert result.tilt == 200.0


class TestCircle:
    def test_at_t_zero(self):
        ctx = _make_movement_ctx(t=0.0, center_pan=127.5, center_tilt=127.5, pan_amplitude=50.0, tilt_amplitude=50.0)
        result = circle(ctx)
        assert result.pan == pytest.approx(177.5)  # cos(0) = 1
        assert result.tilt == pytest.approx(127.5)  # sin(0) = 0

    def test_at_t_pi_half(self):
        ctx = _make_movement_ctx(t=math.pi / 2)
        result = circle(ctx)
        assert result.pan == pytest.approx(127.5, abs=0.1)  # cos(pi/2) ≈ 0
        assert result.tilt == pytest.approx(177.5, abs=0.1)  # sin(pi/2) = 1


class TestDiamond:
    def test_at_progress_zero(self):
        ctx = _make_movement_ctx(progress=0.0, total_cycles=1.0, center_pan=127.5, center_tilt=127.5)
        result = diamond(ctx)
        # At phase=0, corner=0, local_t=0 → top corner
        assert result.pan == pytest.approx(127.5)
        assert result.tilt == pytest.approx(77.5)  # center - amplitude


class TestFigure8:
    def test_at_t_zero(self):
        ctx = _make_movement_ctx(t=0.0)
        result = figure_8(ctx)
        assert result.pan == pytest.approx(127.5)  # sin(0)=0
        assert result.tilt == pytest.approx(127.5)  # sin(0)=0


class TestLissajous:
    def test_default_ratio(self):
        ctx = _make_movement_ctx(t=math.pi / 4, lissajous_ratio="1:2")
        result = lissajous(ctx)
        expected_pan = 127.5 + 50.0 * math.sin(1 * math.pi / 4)
        expected_tilt = 127.5 + 50.0 * math.sin(2 * math.pi / 4)
        assert result.pan == pytest.approx(expected_pan)
        assert result.tilt == pytest.approx(expected_tilt)


class TestBounce:
    def test_produces_values_in_range(self):
        ctx = _make_movement_ctx(progress=0.3, total_cycles=2.0)
        result = bounce(ctx)
        assert 77.5 <= result.pan <= 177.5
        assert 77.5 <= result.tilt <= 177.5


class TestRandomMovement:
    def test_smooth_variation(self):
        results = []
        for t_val in [0.0, 0.5, 1.0, 2.0]:
            ctx = _make_movement_ctx(t=t_val)
            results.append(random_movement(ctx))
        # Values should vary
        pans = [r.pan for r in results]
        assert len(set(round(p, 2) for p in pans)) > 1
