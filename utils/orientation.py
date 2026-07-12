# utils/orientation.py
# Orientation utilities for fixture rotation matrices and pan/tilt calculations

import math
import numpy as np
from typing import Tuple, Optional


# ---------------------------------------------------------------------------
# Mounting presets (restored 2026-07-13 to the pre-rebrand convention)
#
# ABSOLUTE fixture orientations, as (yaw, pitch, roll) in degrees. The
# stored yaw/pitch/roll on a Fixture / FixtureGroup ARE these angles -
# nothing adds a hidden base rotation on top; `mounting` is the label of
# the preset those angles came from.
#
# These are BODY-ORIENTATION angles: they say how the chassis SITS
# (which way is up, which face is against the wall), not where the beam
# points at pan/tilt-home. A moving head's actual aim comes from the
# pan/tilt solve (calculate_pan_tilt), which the visualizer reproduces
# with the same matrix - so the closed loop lands the beam on target for
# ANY body orientation. The rotation convention every consumer uses:
#   R = Ry(yaw) @ Rx(pitch) @ Rz(roll), applied to the chassis, in the
#   scene frame stage (x, y, z_height) -> scene (x, z_height, y).
# Stage frame: +X stage right, +Y upstage (the AUDIENCE is -Y), +Z up.
#
# HISTORY - do not "re-fix" this by beam-direction reasoning again.
# On 2026-07-12 (commit c5c72c1) this table was replaced with a set
# derived by asking "where must the pan/tilt-HOME beam point" (hanging ->
# straight down, etc.). That was the wrong lens: hanging is a body flip,
# not a home-beam direction, and the change broke every mover rig that
# had been correct before the rebrand (verified against real fixtures by
# the user, 2026-07-13). The pre-rebrand values below are the ones that
# actually behave like the real world; hanging is a +90 pitch that flips
# the chassis to hang from the truss.
#
# Configs written by the 2026-07-12 version (or with all-zero angles) are
# corrected on config load - see migrate_orientation_angles.
# ---------------------------------------------------------------------------
MOUNTING_PRESET_ANGLES = {
    'hanging':    (0.0, 90.0, 0.0),    # chassis flipped, hung from truss
    'standing':   (0.0, -90.0, 0.0),   # chassis upright on the deck
    'wall_left':  (-90.0, 0.0, 0.0),   # base against the stage-left wall
    'wall_right': (90.0, 0.0, 0.0),    # base against the stage-right wall
    'wall_back':  (0.0, 0.0, 0.0),     # base against the back wall
    'wall_front': (180.0, 0.0, 0.0),   # base downstage, facing upstage
}

DEFAULT_MOUNTING = 'hanging'

# The wrong 2026-07-12 "beam-direction" table (commit c5c72c1), kept ONLY
# so config load can recognise angles that version wrote and correct them
# back to the table above. Never use these to orient anything.
_BEAM_MATH_ANGLES = {
    'hanging':    (0.0, 0.0, -90.0),
    'standing':   (0.0, 0.0, 90.0),
    'wall_left':  (0.0, 0.0, 0.0),
    'wall_right': (180.0, 0.0, 0.0),
    'wall_back':  (90.0, 0.0, 0.0),
    'wall_front': (-90.0, 0.0, 0.0),
}


def preset_angles(mounting: str) -> Tuple[float, float, float]:
    """The absolute (yaw, pitch, roll) for a mounting preset."""
    return MOUNTING_PRESET_ANGLES.get(
        mounting, MOUNTING_PRESET_ANGLES[DEFAULT_MOUNTING])


def _same_angles(a, b, tol: float = 0.01) -> bool:
    return all(abs(x - y) <= tol for x, y in zip(a, b))


def migrate_orientation_angles(mounting: str, yaw: float, pitch: float,
                               roll: float) -> Tuple[float, float, float]:
    """Bring one stored orientation up to the canonical table.

    Rewrites the angles to :func:`preset_angles` when they are the ones
    a broken version wrote for this mounting, namely:

    - EXACTLY the wrong 2026-07-12 "beam-direction" preset for this
      mounting (:data:`_BEAM_MATH_ANGLES`) - a config saved by that
      version, so its damage is undone on the next load.
    - ALL ZERO - a fixture placed but never given an explicit
      orientation; take the mounting's preset so a `hanging` fixture
      actually hangs.

    Anything else is a deliberate custom orientation and is left alone.
    Idempotent: the canonical angles are neither all-zero (except
    wall_back, which maps to itself) nor any beam-math value.
    """
    angles = (yaw, pitch, roll)
    if mounting not in MOUNTING_PRESET_ANGLES:
        return angles
    if _same_angles(angles, (0.0, 0.0, 0.0)) or \
            _same_angles(angles, _BEAM_MATH_ANGLES[mounting]):
        return preset_angles(mounting)
    return angles


def fixture_rotation_matrix(yaw: float, pitch: float,
                            roll: float) -> np.ndarray:
    """The fixture's absolute orientation as a 3x3 matrix in the scene
    frame: R = Ry(yaw) @ Rx(pitch) @ Rz(roll).

    THE one rotation convention. The visualizer's beam chain
    (visualizer/renderer/composable_fixtures._compute_beam_dir_world)
    and :func:`calculate_pan_tilt` below both build exactly this, so a
    beam aimed by the solver lands where the renderer draws it.
    """
    y, p, r = math.radians(yaw), math.radians(pitch), math.radians(roll)
    Ry = np.array([[math.cos(y), 0, math.sin(y)],
                   [0, 1, 0],
                   [-math.sin(y), 0, math.cos(y)]])
    Rx = np.array([[1, 0, 0],
                   [0, math.cos(p), -math.sin(p)],
                   [0, math.sin(p), math.cos(p)]])
    Rz = np.array([[math.cos(r), -math.sin(r), 0],
                   [math.sin(r), math.cos(r), 0],
                   [0, 0, 1]])
    return Ry @ Rx @ Rz


def beam_direction_stage(yaw: float, pitch: float,
                         roll: float) -> np.ndarray:
    """Where a fixture with this orientation points at pan=0, tilt=0,
    as a unit vector in STAGE coordinates (+X stage right, +Y upstage,
    +Z up). This is only the pan/tilt-HOME rest direction - it is NOT
    what a mounting preset "means" (presets are body orientations; a
    mover's real aim comes from the pan/tilt solve). Kept for tests and
    diagnostics."""
    scene = fixture_rotation_matrix(yaw, pitch, roll) @ np.array([1.0, 0.0,
                                                                  0.0])
    # scene (a, b, c) -> stage (a, c, b): the renderer maps stage Y to
    # scene Z and stage Z (height) to scene Y.
    return np.array([scene[0], scene[2], scene[1]])


def calculate_pan_tilt(
    fixture_x: float, fixture_y: float, fixture_z: float,
    target_x: float, target_y: float, target_z: float,
    mounting: str, yaw: float, pitch: float, roll: float,
    pan_range: float = 540.0, tilt_range: float = 270.0
) -> Tuple[float, float]:
    """
    Calculate pan and tilt angles for a fixture to point at a world position.

    Uses the same coordinate system as the visualizer:
    - Stage coordinates: X=right, Y=toward audience, Z=up
    - Visualizer 3D: X=right, Y=up, Z=depth (stage Y -> 3D Z, stage Z -> 3D Y)
    - Fixture local: beam points +X at pan=0, tilt=0
    - Pan rotates around local Z, Tilt rotates around local Y (negative)

    Args:
        fixture_x, fixture_y, fixture_z: Fixture position in stage space (meters)
        target_x, target_y, target_z: Target position in stage space (meters)
        mounting: Mounting preset name (not currently used - orientation is explicit)
        yaw, pitch, roll: Fixture orientation angles (degrees) - already includes mounting
        pan_range: Total pan range in degrees (default 540)
        tilt_range: Total tilt range in degrees (default 270)

    Returns:
        Tuple of (pan_degrees, tilt_degrees) where:
        - pan_degrees: Pan angle in degrees (0 = center/home)
        - tilt_degrees: Tilt angle in degrees (0 = center/home)
    """
    # Calculate direction vector from fixture to target in stage coordinates
    dx_stage = target_x - fixture_x
    dy_stage = target_y - fixture_y
    dz_stage = target_z - fixture_z

    length = math.sqrt(dx_stage*dx_stage + dy_stage*dy_stage + dz_stage*dz_stage)
    if length < 0.001:  # Target is at fixture position
        return 0.0, 0.0

    # Normalize direction
    dx_stage /= length
    dy_stage /= length
    dz_stage /= length

    # Convert to visualizer 3D coordinates (Y-up):
    # Stage X -> 3D X, Stage Y -> 3D Z, Stage Z -> 3D Y
    target_dir_3d = np.array([dx_stage, dz_stage, dy_stage])

    # Fixture orientation, in the ONE convention (same matrix the
    # visualizer's beam chain builds); transpose = world -> local.
    fixture_orientation = fixture_rotation_matrix(yaw, pitch, roll)

    # Transform target direction to fixture-local space
    local_dir = fixture_orientation.T @ target_dir_3d

    # Now we need to find pan and tilt such that:
    # pan_mat @ tilt_mat @ [1, 0, 0] = local_dir
    #
    # In visualizer: tilt rotates around Y by -angle, pan rotates around Z
    # After tilt t: [cos(t), 0, sin(t)]
    # After pan p: [cos(t)*cos(p), cos(t)*sin(p), sin(t)]
    #
    # Matching to local_dir = [lx, ly, lz]:
    # sin(t) = lz -> t = asin(lz)
    # cos(t)*sin(p) = ly, cos(t)*cos(p) = lx -> p = atan2(ly, lx)

    lx, ly, lz = local_dir

    # Calculate tilt angle
    # Clamp lz to [-1, 1] to avoid asin domain errors
    lz_clamped = max(-1.0, min(1.0, lz))
    tilt_rad = math.asin(lz_clamped)
    tilt_degrees = math.degrees(tilt_rad)

    # Calculate pan angle
    cos_tilt = math.cos(tilt_rad)
    if abs(cos_tilt) < 0.001:
        # Beam is pointing straight up or down, pan is undefined
        pan_degrees = 0.0
    else:
        pan_rad = math.atan2(ly, lx)
        pan_degrees = math.degrees(pan_rad)

    # Clamp to fixture's range
    half_pan = pan_range / 2
    half_tilt = tilt_range / 2
    pan_degrees = max(-half_pan, min(half_pan, pan_degrees))
    tilt_degrees = max(-half_tilt, min(half_tilt, tilt_degrees))

    return pan_degrees, tilt_degrees


def pan_tilt_to_dmx(
    pan_degrees: float, tilt_degrees: float,
    pan_range: float = 540.0, tilt_range: float = 270.0,
    pan_inverted: bool = False, tilt_inverted: bool = False
) -> Tuple[int, int]:
    """
    Convert pan/tilt angles to DMX values (0-255).

    Args:
        pan_degrees: Pan angle in degrees (0 = center)
        tilt_degrees: Tilt angle in degrees (0 = center)
        pan_range: Total pan range in degrees
        tilt_range: Total tilt range in degrees
        pan_inverted: Whether pan direction is inverted
        tilt_inverted: Whether tilt direction is inverted

    Returns:
        Tuple of (pan_dmx, tilt_dmx) values in range 0-255
    """
    # Convert from degrees to 0-255 DMX range
    # 0 degrees = 127 (center), -half_range = 0, +half_range = 255
    half_pan = pan_range / 2
    half_tilt = tilt_range / 2

    # Normalize to -1 to 1 range
    pan_normalized = pan_degrees / half_pan if half_pan > 0 else 0
    tilt_normalized = tilt_degrees / half_tilt if half_tilt > 0 else 0

    # Apply inversion if needed
    if pan_inverted:
        pan_normalized = -pan_normalized
    if tilt_inverted:
        tilt_normalized = -tilt_normalized

    # Convert to 0-255 (127 = center)
    pan_dmx = int(127 + pan_normalized * 127)
    tilt_dmx = int(127 + tilt_normalized * 127)

    # Clamp to valid range
    pan_dmx = max(0, min(255, pan_dmx))
    tilt_dmx = max(0, min(255, tilt_dmx))

    return pan_dmx, tilt_dmx


# REMOVED 2026-07-12: get_rotation_matrix / get_beam_direction /
# get_fill_direction / is_fixture_pointing_down. They built a THIRD
# rotation convention (ZYX with yaw around a Z-up axis, plus a hidden
# base rotation added on top of the caller's angles) that contradicted
# the one the visualizer and calculate_pan_tilt actually use, and no
# production code called them - only their own tests did. They are the
# reason the mounting presets were never noticed to be wrong. Use
# fixture_rotation_matrix / beam_direction_stage instead.


def get_direction_for_tilt_calculation(mounting: str) -> str:
    """
    Get the legacy direction value ('UP' or 'DOWN') for tilt calculations.

    This is used for backwards compatibility with existing effect code
    that uses 'UP'/'DOWN' direction values.

    Args:
        mounting: Mounting preset name

    Returns:
        'UP' or 'DOWN' based on mounting preset
    """
    # Standing fixtures point up, everything else points down
    if mounting == 'standing':
        return 'UP'
    return 'DOWN'
