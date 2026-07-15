# tests/unit/test_movement_migration.py
"""Movement-to-world-target migration converter (v1.5a phase 1 of
docs/focus-morphing-plan.md, utils/movement_migration.py).

The load-bearing check is the CLOSED LOOP: aim a mover at a known world
point with the inverse solver (calculate_pan_tilt -> pan_tilt_to_dmx,
exactly what authoring produced historically), store the DMX pair on a
movement block, run the converter's forward trace, and the proposed
target_point must land back on the original point within 8-bit DMX
quantization. Plus: multi-fixture centroid + divergence warning,
sky-pointing skip, report contents, and the apply step's semantics
(pan/tilt kept, in-memory only, user_warnings per skip)."""

import math

import pytest

from config.models import (Configuration, Fixture, FixtureGroup,
                           FixtureMode, LightBlock, LightLane,
                           MovementBlock, Song, TimelineData)
from utils.movement_migration import (BlockMigration, apply_migration,
                                      beam_direction, plan_migration,
                                      solver_dmx_to_degrees, stage_bounds,
                                      trace_beam)
from utils.orientation import calculate_pan_tilt, pan_tilt_to_dmx

# No resolvable definition -> 540/270 range fallback everywhere, and
# convert_solver_dmx stays identity (same trick as test_world_targets).
MFR = "NoSuchMfr_migration"

# One 8-bit DMX step is 540/254 deg of pan; at the few-metre throws the
# fixtures below use, a half-step each on pan and tilt lands well under
# half a metre from the exact point.
TOLERANCE_M = 0.5


def _mover(name, x, y, z=4.0, yaw=0.0, pitch=90.0, roll=0.0):
    """A hanging-preset mover with EXPLICIT orientation (no group
    default indirection - the trace must read the same angles the
    solver aimed with)."""
    return Fixture(
        universe=1, address=1, manufacturer=MFR, model="StepMover",
        name=name, group="Movers", current_mode="Standard",
        available_modes=[FixtureMode(name="Standard", channels=10)],
        type="MH", x=x, y=y, z=z,
        mounting="hanging", yaw=yaw, pitch=pitch, roll=roll,
        orientation_uses_group_default=False, z_uses_group_default=False,
    )


def _config(fixtures):
    return Configuration(
        fixtures=list(fixtures),
        groups={"Movers": FixtureGroup(name="Movers",
                                       fixtures=list(fixtures))},
        stage_width=10.0, stage_height=6.0,
    )


def _with_song(config, block, lane_name="Movers"):
    lane = LightLane(name=lane_name, fixture_targets=["Movers"])
    lane.light_blocks.append(LightBlock(
        start_time=block.start_time, end_time=block.end_time,
        effect_name="", movement_blocks=[block]))
    config.songs["Song A"] = Song(
        name="Song A", timeline_data=TimelineData(lanes=[lane]))
    return config


def _aim_dmx(fixture, target):
    """The DMX pair legacy authoring would have stored for this aim."""
    pan_deg, tilt_deg = calculate_pan_tilt(
        fixture.x, fixture.y, fixture.z,
        target[0], target[1], target[2],
        fixture.mounting, fixture.yaw, fixture.pitch, fixture.roll,
        540.0, 270.0)
    return pan_tilt_to_dmx(pan_deg, tilt_deg, 540.0, 270.0)


def _block(pan, tilt, **overrides):
    params = dict(start_time=0.0, end_time=8.0, effect_type="static",
                  pan=float(pan), tilt=float(tilt))
    params.update(overrides)
    return MovementBlock(**params)


class TestForwardTrace:
    def test_closed_loop_lands_on_the_aimed_floor_point(self):
        fixture = _mover("MH1", x=-1.0, y=0.0)
        target = (1.0, -2.0, 0.0)
        pan_dmx, tilt_dmx = _aim_dmx(fixture, target)
        config = _with_song(_config([fixture]), _block(pan_dmx, tilt_dmx))

        entries = plan_migration(config)
        assert len(entries) == 1
        entry = entries[0]
        assert entry.status == "converted"
        assert entry.surface == "Floor"
        assert math.dist(entry.point, target) < TOLERANCE_M

    def test_closed_loop_is_exact_without_quantization(self):
        """The forward pass is the true inverse of calculate_pan_tilt:
        feeding exact degrees (not 8-bit DMX) back through
        beam_direction + trace_beam recovers the target to float
        precision."""
        fixture = _mover("MH1", x=-1.0, y=0.0)
        target = (2.5, 1.0, 0.0)
        pan_deg, tilt_deg = calculate_pan_tilt(
            fixture.x, fixture.y, fixture.z, *target,
            fixture.mounting, fixture.yaw, fixture.pitch, fixture.roll,
            540.0, 270.0)
        direction = beam_direction(fixture.yaw, fixture.pitch,
                                   fixture.roll, pan_deg, tilt_deg)
        bounds = stage_bounds(_config([fixture]))
        point, face = trace_beam((fixture.x, fixture.y, fixture.z),
                                 direction, bounds)
        assert face == "Floor"
        assert math.dist(point, target) < 1e-6

    def test_dmx_degree_decode_matches_the_yoke_convention(self):
        assert solver_dmx_to_degrees(127, 127, 540, 270) == (0.0, 0.0)
        pan, tilt = solver_dmx_to_degrees(254, 0, 540, 270)
        assert pan == pytest.approx(270.0)
        assert tilt == pytest.approx(-135.0)

    def test_wall_hit_reports_the_wall(self):
        """A horizontal beam lands on a bounding wall, not the floor.
        Hanging preset (pitch +90) leaves the home beam along +X."""
        fixture = _mover("MH1", x=0.0, y=0.0, z=2.0)
        config = _with_song(_config([fixture]), _block(127, 127))
        entries = plan_migration(config)
        assert entries[0].status == "converted"
        assert entries[0].surface == "Right"
        assert entries[0].point[0] == pytest.approx(5.0)

    def test_sky_pointing_block_is_skipped(self):
        """Aim the mover at a point straight above it: the beam leaves
        the volume through the Ceiling face and never hits a surface."""
        fixture = _mover("MH1", x=0.0, y=0.0, z=2.0)
        pan_dmx, tilt_dmx = _aim_dmx(fixture, (0.0, 0.0, 10.0))
        config = _with_song(_config([fixture]), _block(pan_dmx, tilt_dmx))
        entries = plan_migration(config)
        assert entries[0].status == "skipped"
        assert "sky" in entries[0].reason
        assert entries[0].point is None


class TestGroupCentroid:
    def test_two_fixture_centroid_averages_the_landings(self):
        """Same DMX on two fixtures 1 m apart: the landings shift with
        the fixture offset, the centroid sits between them, and 0.5 m
        of spread stays under the 1 m warning threshold."""
        left = _mover("MH L", x=-0.5, y=0.0)
        right = _mover("MH R", x=0.5, y=0.0)
        # Aim straight down from the midpoint's perspective: with the
        # hanging preset, tilt raising the beam to -Z is the same DMX
        # for both fixtures; each lands directly under itself.
        pan_dmx, tilt_dmx = _aim_dmx(left, (-0.5, 0.0, 0.0))
        config = _with_song(_config([left, right]),
                            _block(pan_dmx, tilt_dmx))
        entries = plan_migration(config)
        entry = entries[0]
        assert entry.status == "converted"
        assert entry.point[0] == pytest.approx(0.0, abs=TOLERANCE_M)
        assert entry.divergence == pytest.approx(0.5, abs=0.1)
        assert entry.warning == ""

    def test_divergent_landings_carry_a_warning(self):
        """Fixtures 6 m apart landing 3 m from the centroid must warn
        (the centroid is still written - the operator decides)."""
        left = _mover("MH L", x=-3.0, y=0.0)
        right = _mover("MH R", x=3.0, y=0.0)
        pan_dmx, tilt_dmx = _aim_dmx(left, (-3.0, 0.0, 0.0))
        config = _with_song(_config([left, right]),
                            _block(pan_dmx, tilt_dmx))
        entry = plan_migration(config)[0]
        assert entry.status == "converted"
        assert entry.divergence > 1.0
        assert "spread" in entry.warning


class TestScope:
    def test_blocks_with_world_targets_are_not_touched(self):
        fixture = _mover("MH1", x=0.0, y=0.0)
        config = _config([fixture])
        lane = LightLane(name="Movers", fixture_targets=["Movers"])
        lane.light_blocks.append(LightBlock(
            start_time=0.0, end_time=8.0, effect_name="",
            movement_blocks=[
                _block(127, 127, target_spot_name="Mark"),
                _block(127, 127, target_plane_name="Floor"),
                _block(127, 127, target_point=[1.0, 1.0, 0.0]),
                _block(127, 127),  # the only convertible one
            ]))
        config.songs["Song A"] = Song(
            name="Song A", timeline_data=TimelineData(lanes=[lane]))
        entries = plan_migration(config)
        assert len(entries) == 1

    def test_lane_without_movers_is_skipped_with_reason(self):
        par = Fixture(
            universe=1, address=1, manufacturer=MFR, model="Par",
            name="PAR 1", group="Pars", current_mode="Standard",
            available_modes=[FixtureMode(name="Standard", channels=10)],
            type="PAR", x=0.0, y=0.0, z=0.0)
        config = Configuration(
            fixtures=[par],
            groups={"Pars": FixtureGroup(name="Pars", fixtures=[par])},
            stage_width=10.0, stage_height=6.0)
        lane = LightLane(name="Pars", fixture_targets=["Pars"])
        lane.light_blocks.append(LightBlock(
            start_time=0.0, end_time=8.0, effect_name="",
            movement_blocks=[_block(127, 127)]))
        config.songs["Song A"] = Song(
            name="Song A", timeline_data=TimelineData(lanes=[lane]))
        entry = plan_migration(config)[0]
        assert entry.status == "skipped"
        assert "no moving fixtures" in entry.reason

    def test_song_filter_limits_the_sweep(self):
        fixture = _mover("MH1", x=0.0, y=0.0)
        config = _with_song(_config([fixture]), _block(127, 127))
        assert plan_migration(config, song_names=set()) == []
        assert len(plan_migration(config, song_names={"Song A"})) == 1

    def test_report_carries_song_lane_and_time_range(self):
        fixture = _mover("MH1", x=0.0, y=0.0)
        config = _with_song(_config([fixture]),
                            _block(127, 127, start_time=4.0, end_time=12.0))
        entry = plan_migration(config)[0]
        assert entry.song == "Song A"
        assert entry.lane == "Movers"
        assert entry.time_range == "4.0-12.0s"
        assert "->" in entry.result_text()


class TestApply:
    def _entries(self):
        fixture = _mover("MH1", x=-1.0, y=0.0)
        target = (1.0, -2.0, 0.0)
        pan_dmx, tilt_dmx = _aim_dmx(fixture, target)
        sky_dmx = _aim_dmx(fixture, (-1.0, 0.0, 10.0))
        config = _config([fixture])
        lane = LightLane(name="Movers", fixture_targets=["Movers"])
        aimed = _block(pan_dmx, tilt_dmx)
        sky = _block(*sky_dmx, start_time=8.0, end_time=16.0)
        lane.light_blocks.append(LightBlock(
            start_time=0.0, end_time=16.0, effect_name="",
            movement_blocks=[aimed, sky]))
        config.songs["Song A"] = Song(
            name="Song A", timeline_data=TimelineData(lanes=[lane]))
        return config, aimed, sky

    def test_plan_mutates_nothing(self):
        config, aimed, sky = self._entries()
        plan_migration(config)
        assert aimed.target_point is None
        assert sky.target_point is None

    def test_apply_writes_points_and_keeps_pan_tilt(self):
        config, aimed, sky = self._entries()
        pan_before, tilt_before = aimed.pan, aimed.tilt
        entries = plan_migration(config)
        applied = apply_migration(config, entries)
        assert applied == 1
        assert aimed.target_point is not None
        assert math.dist(aimed.target_point, (1.0, -2.0, 0.0)) \
            < TOLERANCE_M
        assert (aimed.pan, aimed.tilt) == (pan_before, tilt_before)
        assert aimed.modified is True
        assert sky.target_point is None

    def test_apply_warns_per_skipped_block(self):
        from utils import user_warnings
        config, _aimed, _sky = self._entries()
        entries = plan_migration(config)
        log = user_warnings.get_log()
        log.clear()
        try:
            apply_migration(config, entries)
            migration = [e for e in log.entries()
                         if e.category == "migration"]
            assert len(migration) == 1
            assert "sky" in migration[0].message
            assert "Song A" in migration[0].message
            name, run_entries = log.last_operation()
            assert name == "Convert movement to world targets"
            assert len(run_entries) == 1
        finally:
            log.clear()


class TestTraceBeamGeometry:
    BOUNDS = (-5.0, 5.0, -3.0, 3.0, 0.0, 4.0)

    def test_straight_down_hits_the_floor(self):
        point, face = trace_beam((1.0, 1.0, 4.0), (0.0, 0.0, -1.0),
                                 self.BOUNDS)
        assert face == "Floor"
        assert point == pytest.approx((1.0, 1.0, 0.0))

    def test_straight_up_is_sky(self):
        point, reason = trace_beam((0.0, 0.0, 2.0), (0.0, 0.0, 1.0),
                                   self.BOUNDS)
        assert point is None
        assert "sky" in reason

    def test_front_wall_faces_the_audience(self):
        point, face = trace_beam((0.0, 0.0, 2.0), (0.0, -1.0, 0.0),
                                 self.BOUNDS)
        assert face == "Front"
        assert point == pytest.approx((0.0, -3.0, 2.0))

    def test_outside_fixture_pointing_down_lands_on_the_venue_floor(self):
        """A FOH truss mover outside the stage footprint still lands on
        the z=0 plane even though it never enters the stage volume."""
        point, face = trace_beam((0.0, -6.0, 4.0), (0.0, -0.1, -1.0),
                                 self.BOUNDS)
        assert face == "Floor"
        assert point[2] == pytest.approx(0.0)
        assert point[1] < -6.0

    def test_outside_fixture_pointing_away_never_lands(self):
        point, reason = trace_beam((0.0, -6.0, 4.0), (0.0, -1.0, 0.5),
                                   self.BOUNDS)
        assert point is None
