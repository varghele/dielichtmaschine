# utils/movement_migration.py
"""Movement-block migration to world-space targets (v1.5a phase 1 of
docs/focus-morphing-plan.md).

Legacy movement blocks store their aim as raw solver-space pan/tilt DMX
values - rig-specific numbers that break the moment the show plays on a
different rig (the morphing design's portability contract, design doc
section 2). This module traces where each such block's CENTRE beam
actually lands on the stage, using the solver's FORWARD pass (the exact
inverse of utils/orientation.calculate_pan_tilt), and proposes that
landing point as the block's ``target_point``.

Pure and Qt-free: :func:`plan_migration` only reads the config and
returns a report; nothing changes until :func:`apply_migration` writes
the confirmed entries. The GUI wraps the pair in a confirmation dialog
(Tools > Convert Movement to World Targets...). The pan/tilt values are
KEPT as authored fallback - resolution priority (plane > spot > point >
manual) means the new point simply wins.

Geometry: the beam is intersected with the stage bounding volume from
autogen.spatial.compute_stage_planes. CAREFUL - those planes live in
spatial.py's own 0..D depth convention (CLAUDE.md coordinate-frames
note); everything here converts them once into the centred stage frame
that fixtures, spots and target_point use (X centred, Y centred with
the audience negative, Z up). A beam that leaves the volume through the
Ceiling face never hit a surface (pointing at the sky) and is reported
as skipped; a fixture parked outside the stage footprint still lands on
the venue floor when its beam points down (infinite z=0 plane).
"""

import math
from dataclasses import dataclass
from typing import List, Optional, Tuple

import numpy as np

from utils import user_warnings
from utils.orientation import fixture_rotation_matrix

#: fixtures further than this from the group's centroid landing point
#: get a divergence warning on the report entry (metres).
DIVERGENCE_WARN_M = 1.0

_EPS = 1e-9


# ---------------------------------------------------------------------------
# Solver forward pass
# ---------------------------------------------------------------------------

def solver_dmx_to_degrees(pan_dmx: float, tilt_dmx: float,
                          pan_range: float, tilt_range: float
                          ) -> Tuple[float, float]:
    """Inverse of pan_tilt_to_dmx's 8-bit encode (127 = centre) - the
    same decode utils/yoke.convert_solver_dmx uses."""
    pan_deg = (float(pan_dmx) - 127.0) / 127.0 * (pan_range / 2.0)
    tilt_deg = (float(tilt_dmx) - 127.0) / 127.0 * (tilt_range / 2.0)
    return pan_deg, tilt_deg


def beam_direction(yaw: float, pitch: float, roll: float,
                   pan_deg: float, tilt_deg: float) -> np.ndarray:
    """Unit beam direction in STAGE coordinates for solver pan/tilt.

    The exact forward model calculate_pan_tilt inverts: the local beam
    after tilt t and pan p is [cos(t)cos(p), cos(t)sin(p), sin(t)],
    rotated into the scene frame by the ONE rotation convention
    (fixture_rotation_matrix), then scene (a, b, c) -> stage (a, c, b).
    """
    p = math.radians(pan_deg)
    t = math.radians(tilt_deg)
    local = np.array([math.cos(t) * math.cos(p),
                      math.cos(t) * math.sin(p),
                      math.sin(t)])
    scene = fixture_rotation_matrix(yaw, pitch, roll) @ local
    return np.array([scene[0], scene[2], scene[1]])


# ---------------------------------------------------------------------------
# Stage volume
# ---------------------------------------------------------------------------

def stage_bounds(config) -> Tuple[float, float, float, float, float, float]:
    """(xmin, xmax, ymin, ymax, zmin, zmax) of the stage bounding volume
    in the CENTRED stage frame, derived from compute_stage_planes (which
    itself uses a 0..D depth convention - converted here, once)."""
    from autogen.spatial import compute_stage_planes
    planes = {p.name: p for p in compute_stage_planes(config)}
    half_w = float(planes["Right"].point[0])
    depth = float(planes["Back"].point[1])       # 0..D convention
    max_z = float(planes["Ceiling"].point[2])
    return (-half_w, half_w, -depth / 2.0, depth / 2.0, 0.0, max_z)


def trace_beam(origin, direction, bounds):
    """Where a beam from ``origin`` along ``direction`` lands on the
    stage volume.

    Returns ``((x, y, z), face_name)`` for the point where the beam
    LEAVES the bounding volume (slab method; for the usual
    fixture-inside-the-volume case that is the floor or a wall), or
    ``(None, reason)`` when it never lands: the Ceiling face is not a
    surface (the beam points at the sky), and a beam that misses the
    volume entirely only lands if it points down onto the infinite
    venue-floor plane z=0.
    """
    xmin, xmax, ymin, ymax, zmin, zmax = bounds
    slabs = (("Left", "Right", xmin, xmax, 0),
             ("Front", "Back", ymin, ymax, 1),
             ("Floor", "Ceiling", zmin, zmax, 2))
    t_enter = -math.inf
    t_exit = math.inf
    exit_face = None
    for neg_name, pos_name, lo, hi, axis in slabs:
        o = float(origin[axis])
        d = float(direction[axis])
        if abs(d) < _EPS:
            if o < lo - _EPS or o > hi + _EPS:
                return None, "beam runs parallel outside the stage volume"
            continue
        t_lo = (lo - o) / d
        t_hi = (hi - o) / d
        t_near, t_far = min(t_lo, t_hi), max(t_lo, t_hi)
        t_enter = max(t_enter, t_near)
        if t_far < t_exit:
            t_exit = t_far
            exit_face = pos_name if d > 0 else neg_name
    if t_exit <= max(t_enter, 0.0):
        # Outside the volume aiming away from it (a fixture ON the
        # ceiling plane pointing up lands here too, with t_exit == 0).
        # A downward beam still lands on the venue floor (the z=0 plane
        # extends beyond the stage footprint); an upward one points at
        # the sky; a horizontal one never hits a surface.
        if float(direction[2]) < -_EPS:
            t = (0.0 - float(origin[2])) / float(direction[2])
            if t > _EPS:
                point = tuple(float(origin[i]) + t * float(direction[i])
                              for i in range(3))
                return point, "Floor"
        if float(direction[2]) > _EPS:
            return None, "beam points at the sky"
        return None, "beam never reaches the stage volume"
    if exit_face == "Ceiling":
        return None, "beam points at the sky"
    point = tuple(float(origin[i]) + t_exit * float(direction[i])
                  for i in range(3))
    return point, exit_face


# ---------------------------------------------------------------------------
# Per-block trace
# ---------------------------------------------------------------------------

@dataclass
class BlockMigration:
    """One movement block's report row (and apply target)."""
    song: str
    lane: str
    start_time: float
    end_time: float
    status: str                     # "converted" | "skipped"
    point: Optional[Tuple[float, float, float]] = None
    surface: str = ""               # stage face the centroid landed on
    reason: str = ""                # why skipped
    divergence: float = 0.0         # max fixture spread from centroid (m)
    warning: str = ""               # divergence / partial-hit note
    block: object = None            # the MovementBlock (apply writes it)

    @property
    def time_range(self) -> str:
        return f"{self.start_time:.1f}-{self.end_time:.1f}s"

    def result_text(self) -> str:
        """One-line human summary for the confirmation dialog."""
        if self.status == "converted":
            x, y, z = self.point
            text = f"-> ({x:.2f}, {y:.2f}, {z:.2f}) m on {self.surface}"
            if self.warning:
                text += f" · {self.warning}"
            return text
        return f"skipped: {self.reason}"


def _mover_fixtures(lane, config) -> list:
    """The lane's aimable fixtures. Typed movers (MH / WASH, the same
    test autogen/spatial uses) win; when a lane's groups carry movement
    capability but no fixture is typed, all lane fixtures count."""
    from utils.position_presets import group_has_movers
    from utils.target_resolver import parse_target, resolve_targets_unique

    fixtures = resolve_targets_unique(lane.fixture_targets, config)
    movers = [f for f in fixtures
              if getattr(f, "type", "") in ("MH", "WASH")]
    if movers:
        return movers
    for target in lane.fixture_targets:
        group_name, _ = parse_target(target)
        group = config.groups.get(group_name)
        if group is not None and group_has_movers(group):
            return fixtures
    return []


def _trace_block(song_name: str, lane, block, fixtures, bounds,
                 config) -> BlockMigration:
    entry = BlockMigration(song=song_name, lane=lane.name,
                           start_time=block.start_time,
                           end_time=block.end_time,
                           status="skipped", block=block)
    if not fixtures:
        entry.reason = "no moving fixtures resolve from the lane targets"
        return entry

    from utils.yoke import physical_ranges

    hits = []       # (point, face)
    misses = []     # reasons
    for fixture in fixtures:
        group = config.groups.get(fixture.group) if fixture.group else None
        _, yaw, pitch, roll = fixture.get_effective_orientation(group)
        fixture_z = fixture.get_effective_z(group)
        pan_range, tilt_range = physical_ranges(fixture.manufacturer,
                                                fixture.model)
        pan_deg, tilt_deg = solver_dmx_to_degrees(
            block.pan, block.tilt, pan_range, tilt_range)
        direction = beam_direction(yaw, pitch, roll, pan_deg, tilt_deg)
        point, face = trace_beam(
            (fixture.x, fixture.y, fixture_z), direction, bounds)
        if point is None:
            misses.append(face)
        else:
            hits.append((point, face))

    if not hits:
        entry.reason = misses[0] if misses else "beam never lands"
        return entry

    centroid = tuple(
        sum(point[i] for point, _ in hits) / len(hits) for i in range(3))
    divergence = max(
        math.dist(point, centroid) for point, _ in hits)

    notes = []
    if divergence > DIVERGENCE_WARN_M:
        notes.append(f"beam landings spread {divergence:.1f} m "
                     f"from the group centre")
    if misses:
        notes.append(f"{len(misses)} of {len(fixtures)} fixtures "
                     f"never hit a surface")

    entry.status = "converted"
    entry.point = tuple(round(v, 3) for v in centroid)
    entry.surface = hits[0][1]
    entry.divergence = divergence
    entry.warning = "; ".join(notes)
    return entry


# ---------------------------------------------------------------------------
# Plan + apply
# ---------------------------------------------------------------------------

def _has_world_target(block) -> bool:
    return bool(block.target_spot_name
                or getattr(block, "target_plane_name", None)
                or getattr(block, "target_point", None))


def plan_migration(config, song_names=None) -> List[BlockMigration]:
    """Trace every convertible movement block; MUTATES NOTHING.

    A block is convertible when it carries no world target yet (no
    spot, no plane, no point) - blocks that already aim at the world
    are not part of the migration and do not appear in the report.
    ``song_names`` limits the sweep (None = all songs).
    """
    bounds = stage_bounds(config)
    entries: List[BlockMigration] = []
    for song_name, song in config.songs.items():
        if song_names is not None and song_name not in song_names:
            continue
        timeline = getattr(song, "timeline_data", None)
        if timeline is None:
            continue
        for lane in timeline.lanes:
            fixtures = _mover_fixtures(lane, config)
            for envelope in lane.light_blocks:
                for block in envelope.movement_blocks:
                    if _has_world_target(block):
                        continue
                    entries.append(_trace_block(
                        song_name, lane, block, fixtures, bounds, config))
    return entries


def apply_migration(config, entries: List[BlockMigration]) -> int:
    """Write the converted entries' points into their blocks.

    Runs on the in-memory config only - the user saves manually, and
    reloading the config discards the conversion. Pan/tilt stay as the
    authored fallback. Skipped blocks (and divergence notes) go to
    user_warnings (category "migration") so Help > Warnings shows what
    the conversion could not do. Returns the number of blocks written.
    """
    applied = 0
    with user_warnings.operation("Convert movement to world targets"):
        for entry in entries:
            where = f"{entry.song} · {entry.lane} · {entry.time_range}"
            if entry.status == "converted" and entry.block is not None:
                entry.block.target_point = [float(v) for v in entry.point]
                entry.block.modified = True
                applied += 1
                if entry.warning:
                    user_warnings.warn(f"{where}: {entry.warning}",
                                       category="migration")
            else:
                user_warnings.warn(f"{where}: {entry.reason}",
                                   category="migration")
    return applied
