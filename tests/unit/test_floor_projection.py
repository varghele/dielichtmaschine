"""Tests for visualizer/renderer/floor_projection.py (Phase D Stage 2).

Pure-Python tests of the intersection math + falloff. The
:class:`FloorProjectionComponent` itself owns GL resources and is exercised
in Stage 3's visual regression harness.
"""

from __future__ import annotations

import math

import glm
import pytest

from visualizer.renderer.floor_projection import (
    DEFAULT_BEAM_LENGTH_M,
    compute_distance_falloff,
    compute_floor_intersection,
)


# ---------------------------------------------------------------------------
# compute_floor_intersection
# ---------------------------------------------------------------------------


class TestComputeFloorIntersection:

    def test_straight_down_beam_lands_directly_below_lens(self):
        # Lens 3m up, beam pointing straight down.
        lens = glm.vec3(2.0, 3.0, 4.0)
        beam_dir = glm.vec3(0.0, -1.0, 0.0)
        result = compute_floor_intersection(lens, beam_dir, beam_angle_deg=15.0)

        assert result is not None
        # Hit position is directly below the lens (X, Z preserved; Y=0).
        assert result.hit_pos.x == pytest.approx(2.0)
        assert result.hit_pos.y == pytest.approx(0.0, abs=1e-6)
        assert result.hit_pos.z == pytest.approx(4.0)

        # At straight-down incidence, ellipse is a circle: major == minor.
        assert result.major_radius == pytest.approx(result.minor_radius)

    def test_oblique_beam_produces_stretched_ellipse(self):
        # Lens 3m up, beam slanted 45° forward + down (normalized).
        lens = glm.vec3(0.0, 3.0, 0.0)
        beam_dir = glm.normalize(glm.vec3(1.0, -1.0, 0.0))
        result = compute_floor_intersection(lens, beam_dir, beam_angle_deg=15.0)

        assert result is not None
        # Major axis stretched along beam direction.
        assert result.major_radius > result.minor_radius
        # Hit lands forward of the lens (positive X).
        assert result.hit_pos.x > 0.0

    def test_horizontal_beam_returns_none(self):
        # Beam parallel to floor — never reaches Y=0.
        lens = glm.vec3(0.0, 3.0, 0.0)
        beam_dir = glm.vec3(1.0, 0.0, 0.0)
        assert compute_floor_intersection(lens, beam_dir, beam_angle_deg=15.0) is None

    def test_upward_beam_returns_none(self):
        lens = glm.vec3(0.0, 3.0, 0.0)
        beam_dir = glm.vec3(0.0, 1.0, 0.0)
        assert compute_floor_intersection(lens, beam_dir, beam_angle_deg=15.0) is None

    def test_beam_past_max_length_returns_none(self):
        # Lens 100m up — would need t=100 to reach floor, but beam_length=5.
        lens = glm.vec3(0.0, 100.0, 0.0)
        beam_dir = glm.vec3(0.0, -1.0, 0.0)
        assert compute_floor_intersection(
            lens, beam_dir, beam_angle_deg=15.0, beam_length_m=5.0,
        ) is None

    def test_lens_below_floor_returns_none(self):
        # Negative Y lens — t would be negative.
        lens = glm.vec3(0.0, -1.0, 0.0)
        beam_dir = glm.vec3(0.0, -1.0, 0.0)
        assert compute_floor_intersection(lens, beam_dir, beam_angle_deg=15.0) is None

    def test_major_radius_capped_at_5x(self):
        # Very shallow incidence: cos_angle near zero, would blow up without
        # the cap. Use a low lens + shallow beam so t stays under beam_length.
        lens = glm.vec3(0.0, 0.1, 0.0)
        # ~5° below horizontal — very shallow (cos_angle ≈ 0.087, < 0.2 cap).
        beam_dir = glm.normalize(glm.vec3(1.0, -0.087, 0.0))
        result = compute_floor_intersection(lens, beam_dir, beam_angle_deg=15.0)
        assert result is not None
        assert result.major_radius <= result.minor_radius * 5.0 + 1e-6

    def test_rotation_angle_aligns_with_beam_xz(self):
        # Beam pointing down + along +X: rotation_angle_deg = 90° (atan2(1, 0)).
        lens = glm.vec3(0.0, 3.0, 0.0)
        beam_dir = glm.normalize(glm.vec3(1.0, -1.0, 0.0))
        result = compute_floor_intersection(lens, beam_dir, beam_angle_deg=15.0)
        assert result is not None
        # atan2(beam_xz.x=1, beam_xz.y=0) = 90°
        assert result.rotation_angle_deg == pytest.approx(90.0)


# ---------------------------------------------------------------------------
# compute_distance_falloff
# ---------------------------------------------------------------------------


class TestComputeDistanceFalloff:

    def test_short_distance_high_falloff(self):
        # Lens 1m up, straight down → distance=1, falloff=1 - (1/5)*0.3 = 0.94
        lens = glm.vec3(0.0, 1.0, 0.0)
        beam_dir = glm.vec3(0.0, -1.0, 0.0)
        falloff = compute_distance_falloff(lens, beam_dir, beam_length_m=5.0)
        assert falloff == pytest.approx(0.94)

    def test_floor_at_max_distance(self):
        lens = glm.vec3(0.0, 5.0, 0.0)
        beam_dir = glm.vec3(0.0, -1.0, 0.0)
        falloff = compute_distance_falloff(lens, beam_dir, beam_length_m=5.0)
        # 1 - (5/5)*0.3 = 0.7
        assert falloff == pytest.approx(0.7)

    def test_falloff_clamped_at_0_5_minimum(self):
        # Way past max distance — clamps at 0.5
        lens = glm.vec3(0.0, 100.0, 0.0)
        beam_dir = glm.vec3(0.0, -1.0, 0.0)
        falloff = compute_distance_falloff(lens, beam_dir, beam_length_m=5.0)
        assert falloff == 0.5

    def test_upward_beam_uses_max_distance(self):
        # Upward beam: distance = beam_length, falloff = 0.7
        lens = glm.vec3(0.0, 1.0, 0.0)
        beam_dir = glm.vec3(0.0, 1.0, 0.0)
        falloff = compute_distance_falloff(lens, beam_dir, beam_length_m=5.0)
        assert falloff == pytest.approx(0.7)


# ---------------------------------------------------------------------------
# Default constant
# ---------------------------------------------------------------------------


def test_default_beam_length_matches_legacy():
    """Legacy MovingHeadRenderer used 5m for beam length / floor intersection range."""
    assert DEFAULT_BEAM_LENGTH_M == 5.0
