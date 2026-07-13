# tests/unit/test_orientation.py
"""Unit tests for utils/orientation.py - the mounting presets, the one
rotation convention, and pan/tilt calculations.

The mounting presets are BODY orientations (how the chassis sits), not
home-beam directions - see the module comment in utils/orientation.py.
They are pinned here by their exact angle values (restored 2026-07-13 to
the pre-rebrand convention after the 2026-07-12 beam-direction table
broke real mover rigs). What actually matters for aiming - that a mover
lands its beam on the target, not its mirror image - is pinned
end-to-end by TestAimingEndToEnd, which closes the solve+render loop.
"""

import math
import pytest
import numpy as np
from utils.orientation import (
    MOUNTING_PRESET_ANGLES,
    calculate_pan_tilt,
    fixture_rotation_matrix,
    migrate_orientation_angles,
    pan_tilt_to_dmx,
    pan_tilt_to_dmx16,
    preset_angles,
    get_direction_for_tilt_calculation,
)


class TestMountingPresets:
    """The presets are the pre-rebrand body orientations (restored
    2026-07-13). Pinned by value so the 2026-07-12 beam-direction table
    can never silently come back."""

    @pytest.mark.parametrize("mounting,angles", [
        ('hanging',    (0.0, 90.0, 0.0)),    # chassis flipped, hung
        ('standing',   (0.0, -90.0, 0.0)),   # chassis upright
        ('wall_left',  (-90.0, 0.0, 0.0)),
        ('wall_right', (90.0, 0.0, 0.0)),
        # back/front were swapped in the pre-rebrand table; user-verified
        # 2026-07-13: yaw 180 faces the audience (back wall mount).
        ('wall_back',  (180.0, 0.0, 0.0)),
        ('wall_front', (0.0, 0.0, 0.0)),
    ], ids=lambda v: v if isinstance(v, str) else "")
    def test_preset_values(self, mounting, angles):
        assert preset_angles(mounting) == angles

    def test_all_presets_defined(self):
        assert set(MOUNTING_PRESET_ANGLES) == {
            'hanging', 'standing', 'wall_left', 'wall_right',
            'wall_back', 'wall_front'}

    def test_hanging_is_a_pitch_flip_not_the_beam_math_roll(self):
        # The 2026-07-12 regression stored hanging as roll -90 (a
        # home-beam-points-down value); the real convention is a +90
        # pitch that flips the chassis to hang. Guard against reverting.
        assert preset_angles('hanging') == (0.0, 90.0, 0.0)
        assert preset_angles('standing') == (0.0, -90.0, 0.0)


class TestFixtureRotationMatrix:

    def test_returns_3x3(self):
        assert fixture_rotation_matrix(0, 0, 0).shape == (3, 3)

    def test_is_orthogonal(self):
        R = fixture_rotation_matrix(45, 30, 15)
        np.testing.assert_allclose(R @ R.T, np.eye(3), atol=1e-10)

    def test_determinant_is_one(self):
        # A proper rotation, never a reflection.
        R = fixture_rotation_matrix(90, 45, 10)
        assert abs(np.linalg.det(R) - 1.0) < 1e-10


class TestMigration:
    """Configs written before the fix carry `mounting` next to zeroed
    angles (or the old dialog's angles); load rewrites them."""

    def test_zeroed_angles_take_the_preset(self):
        assert migrate_orientation_angles('hanging', 0.0, 0.0, 0.0) == \
            preset_angles('hanging')
        assert migrate_orientation_angles('wall_back', 0.0, 0.0, 0.0) == \
            preset_angles('wall_back')

    def test_beam_math_angles_are_corrected(self):
        # Configs saved by the broken 2026-07-12 version stored the
        # beam-direction values; load must correct them back.
        assert migrate_orientation_angles('hanging', 0.0, 0.0, -90.0) == \
            preset_angles('hanging')          # -> (0, 90, 0)
        assert migrate_orientation_angles('standing', 0.0, 0.0, 90.0) == \
            preset_angles('standing')         # -> (0, -90, 0)
        assert migrate_orientation_angles('wall_back', 90.0, 0.0, 0.0) == \
            preset_angles('wall_back')        # -> (180, 0, 0)

    def test_swapped_wall_pair_is_corrected(self):
        # The pre-rebrand table (and the brief 2026-07-13 revert) had
        # wall_back and wall_front carrying each other's yaw. Configs
        # saved with either value heal on load: wall_back stored as
        # zeros hits the zero rule; wall_front stored as yaw 180 hits
        # the swapped-wall rule.
        assert migrate_orientation_angles('wall_back', 0.0, 0.0, 0.0) == \
            (180.0, 0.0, 0.0)
        assert migrate_orientation_angles('wall_front', 180.0, 0.0, 0.0) == \
            (0.0, 0.0, 0.0)
        # A yaw-180 wall_back (the NEW canonical value) is left alone.
        assert migrate_orientation_angles('wall_back', 180.0, 0.0, 0.0) == \
            (180.0, 0.0, 0.0)

    def test_custom_orientation_is_left_alone(self):
        assert migrate_orientation_angles('hanging', 33.0, 12.0, -5.0) == \
            (33.0, 12.0, -5.0)

    def test_is_idempotent(self):
        for mounting in MOUNTING_PRESET_ANGLES:
            once = migrate_orientation_angles(mounting,
                                              *preset_angles(mounting))
            twice = migrate_orientation_angles(mounting, *once)
            assert once == preset_angles(mounting)
            assert twice == once

    def test_unknown_mounting_is_left_alone(self):
        assert migrate_orientation_angles('bogus', 0.0, 0.0, 0.0) == \
            (0.0, 0.0, 0.0)


class TestPanTiltToDmx:

    def test_center_position(self):
        pan_dmx, tilt_dmx = pan_tilt_to_dmx(0.0, 0.0)
        assert pan_dmx == 127
        assert tilt_dmx == 127

    def test_max_pan(self):
        pan_dmx, tilt_dmx = pan_tilt_to_dmx(270.0, 0.0, pan_range=540.0)
        assert pan_dmx == 254  # 127 + 127

    def test_min_pan(self):
        pan_dmx, tilt_dmx = pan_tilt_to_dmx(-270.0, 0.0, pan_range=540.0)
        assert pan_dmx == 0

    def test_clamping(self):
        pan_dmx, tilt_dmx = pan_tilt_to_dmx(999.0, -999.0)
        assert 0 <= pan_dmx <= 255
        assert 0 <= tilt_dmx <= 255

    def test_pan_inversion(self):
        pan_normal, _ = pan_tilt_to_dmx(90.0, 0.0, pan_range=540.0)
        pan_inverted, _ = pan_tilt_to_dmx(90.0, 0.0, pan_range=540.0, pan_inverted=True)
        # Normal should be > 127, inverted should be < 127
        assert pan_normal > 127
        assert pan_inverted < 127

    def test_tilt_inversion(self):
        _, tilt_normal = pan_tilt_to_dmx(0.0, 45.0, tilt_range=270.0)
        _, tilt_inverted = pan_tilt_to_dmx(0.0, 45.0, tilt_range=270.0, tilt_inverted=True)
        assert tilt_normal > 127
        assert tilt_inverted < 127


class TestCalculatePanTilt:

    def test_target_at_fixture_returns_zero(self):
        """When target == fixture position, should return (0, 0)."""
        pan, tilt = calculate_pan_tilt(5, 3, 4, 5, 3, 4, 'hanging', 0, 0, 0)
        assert pan == 0.0
        assert tilt == 0.0

    def test_returns_tuple_of_two(self):
        result = calculate_pan_tilt(0, 0, 3, 5, 5, 0, 'hanging', 0, -90, 0)
        assert len(result) == 2

    def test_result_within_range(self):
        pan, tilt = calculate_pan_tilt(0, 0, 5, 3, 3, 0, 'hanging', 0, -90, 0)
        assert -270 <= pan <= 270
        assert -135 <= tilt <= 135


class TestPanTiltToDmx16:
    """16-bit encode: coarse + fine, decoded as coarse*256 + fine by
    the visualizer's MovementComponent and real fixtures alike."""

    def test_center_is_exact_half_travel(self):
        pan_c, pan_f, tilt_c, tilt_f = pan_tilt_to_dmx16(0.0, 0.0)
        assert (pan_c * 256 + pan_f) == 32768   # 32768/65535 = 0.5
        assert (tilt_c * 256 + tilt_f) == 32768

    def test_extremes_hit_the_rails(self):
        pan_c, pan_f, tilt_c, tilt_f = pan_tilt_to_dmx16(270.0, -135.0)
        assert (pan_c, pan_f) == (255, 255)     # +half range -> 65535
        assert (tilt_c, tilt_f) == (0, 0)       # -half range -> 0

    def test_clamps_beyond_range(self):
        pan_c, pan_f, _, _ = pan_tilt_to_dmx16(9999.0, 0.0)
        assert (pan_c, pan_f) == (255, 255)

    def test_inversion(self):
        normal = pan_tilt_to_dmx16(90.0, 0.0)
        inverted = pan_tilt_to_dmx16(90.0, 0.0, pan_inverted=True)
        # Mirrored around the centre of travel (rounding may split a
        # half-step either way).
        total = (normal[0] * 256 + normal[1]) + \
            (inverted[0] * 256 + inverted[1])
        assert total in (65535, 65536)

    def test_round_trip_accuracy_beats_8_bit(self):
        # 21.8 deg pan on a 540 range: the 8-bit step is ~2.1 deg; the
        # 16-bit decode must come back within one 16-bit step.
        pan_deg = 21.8
        pan_c, pan_f, _, _ = pan_tilt_to_dmx16(pan_deg, 0.0, 540.0, 270.0)
        decoded = ((pan_c * 256 + pan_f) / 65535.0 - 0.5) * 540.0
        assert abs(decoded - pan_deg) < 540.0 / 65535 + 1e-9

    def test_coarse_stays_close_to_the_8_bit_encode(self):
        # The legacy 8-bit encoder spans 0..254 (127 +- 127) while the
        # 16-bit coarse byte spans the full 0..255, so the two may
        # differ by up to 2 steps - close enough that swapping in
        # 16-bit cannot jump the aim, just refine it.
        for pan in (-200.0, -21.8, 0.0, 45.0, 180.0):
            coarse16 = pan_tilt_to_dmx16(pan, 0.0)[0]
            coarse8 = pan_tilt_to_dmx(pan, 0.0)[0]
            assert abs(coarse16 - coarse8) <= 2


def _aimed_beam_stage(fixture_xyz, target_xyz, mounting):
    """Where a fixture ACTUALLY ends up pointing, in stage coordinates,
    after the solver aims it: run calculate_pan_tilt, then rebuild the
    beam the way the renderer does (R @ pan @ tilt @ +X) and convert
    back to stage. This is the end-to-end aiming contract - it closes
    the loop the visualizer draws."""
    yaw, pitch, roll = preset_angles(mounting)
    pan_deg, tilt_deg = calculate_pan_tilt(
        *fixture_xyz, *target_xyz, mounting, yaw, pitch, roll)

    p, t = math.radians(pan_deg), math.radians(tilt_deg)
    # tilt about Y by -t, then pan about Z, applied to local +X.
    local = np.array([math.cos(t) * math.cos(p),
                      math.cos(t) * math.sin(p),
                      math.sin(t)])
    scene = fixture_rotation_matrix(yaw, pitch, roll) @ local
    return np.array([scene[0], scene[2], scene[1]])   # scene -> stage


class TestAimingEndToEnd:
    """A hanging mover aimed at a stage point must actually look at it -
    not at its mirror image. Stage frame: +X right, +Y upstage, +Z up."""

    @pytest.mark.parametrize("target,description", [
        ((3.0, 0.0, 0.0), "stage right"),
        ((-3.0, 0.0, 0.0), "stage left"),
        ((0.0, -3.0, 0.0), "downstage / audience"),
        ((0.0, 3.0, 0.0), "upstage / back"),
        ((2.0, -2.0, 1.0), "off-axis, raised"),
    ], ids=lambda v: v if isinstance(v, str) else "")
    def test_hanging_mover_looks_at_its_target(self, target, description):
        fixture = (0.0, 0.0, 6.0)      # hung above centre stage
        beam = _aimed_beam_stage(fixture, target, 'hanging')
        want = np.array(target) - np.array(fixture)
        want = want / np.linalg.norm(want)
        np.testing.assert_allclose(beam, want, atol=1e-6)

    def test_the_beam_is_not_mirrored_in_x(self):
        # The user-visible symptom: aim stage-right, beam goes stage-left.
        beam = _aimed_beam_stage((0.0, 0.0, 6.0), (3.0, 0.0, 0.0), 'hanging')
        assert beam[0] > 0, "a target at +X must produce a beam toward +X"

    def test_the_beam_is_not_mirrored_in_depth(self):
        # Aim at the audience, the beam must not fly upstage.
        beam = _aimed_beam_stage((0.0, 0.0, 6.0), (0.0, -4.0, 0.0), 'hanging')
        assert beam[1] < 0, "a target toward the audience must aim -Y"


class TestGetDirectionForTiltCalculation:

    def test_standing_returns_up(self):
        assert get_direction_for_tilt_calculation('standing') == 'UP'

    def test_hanging_returns_down(self):
        assert get_direction_for_tilt_calculation('hanging') == 'DOWN'

    def test_wall_returns_down(self):
        assert get_direction_for_tilt_calculation('wall_left') == 'DOWN'
        assert get_direction_for_tilt_calculation('wall_right') == 'DOWN'
        assert get_direction_for_tilt_calculation('wall_back') == 'DOWN'
        assert get_direction_for_tilt_calculation('wall_front') == 'DOWN'