# tests/unit/test_world_targets.py
"""World-space movement targets (v1.5a phase 1 of
docs/focus-morphing-plan.md): the ad-hoc target_point on MovementBlock
resolves exactly like an equivalent named spot in BOTH resolution paths
(native DMX renderer and .qxw export sampler), the export gains the
world-plane path the native renderer already had, and the new field
round-trips through YAML. Resolution priority: plane > spot > point >
manual pan/tilt."""

import pytest

from config.models import (Configuration, Fixture, FixtureGroup,
                           FixtureMode, MovementBlock, Spot, Universe)


def _fixture(manufacturer="NoSuchMfr_worldtargets", name="MH1"):
    # No resolvable definition: convert_solver_dmx is identity, so the
    # tests compare solver-space values directly.
    return Fixture(
        universe=1, address=1, manufacturer=manufacturer, model="StepMover",
        name=name, group="Movers", current_mode="Standard",
        available_modes=[FixtureMode(name="Standard", channels=10)],
        type="MH", x=-1.0, y=0.0, z=4.0,
    )


def _config(fixture):
    config = Configuration(
        fixtures=[fixture],
        groups={"Movers": FixtureGroup(name="Movers", fixtures=[fixture])},
        universes={1: Universe(id=1, name="U1", output={})},
    )
    config.spots = {"Mark": Spot(name="Mark", x=1.0, y=-2.0, z=0.0)}
    return config


def _sample(config, fixture, block, time_s=0.0):
    from utils.to_xml.unified_sequence import sample_movement_at_time
    return sample_movement_at_time(
        time_s, [block], fixture_idx=0, total_fixtures=1,
        step_idx=0, total_steps=1, bpm=120.0, signature="4/4",
        config=config, fixture=fixture)


def _block(**overrides):
    params = dict(start_time=0.0, end_time=8.0, effect_type="static")
    params.update(overrides)
    return MovementBlock(**params)


class TestExportPointTargets:
    def test_point_aims_exactly_like_the_equivalent_spot(self):
        fixture = _fixture()
        config = _config(fixture)
        via_spot = _sample(config, fixture, _block(target_spot_name="Mark"))
        via_point = _sample(config, fixture,
                            _block(target_point=[1.0, -2.0, 0.0]))
        assert via_point == via_spot

    def test_point_beats_manual_pan_tilt(self):
        fixture = _fixture()
        config = _config(fixture)
        manual = _sample(config, fixture, _block(pan=10.0, tilt=10.0))
        pointed = _sample(config, fixture,
                          _block(pan=10.0, tilt=10.0,
                                 target_point=[1.0, -2.0, 0.0]))
        assert pointed != manual

    def test_spot_beats_point(self):
        fixture = _fixture()
        config = _config(fixture)
        both = _block(target_spot_name="Mark",
                      target_point=[-3.0, 2.0, 1.5])
        assert _sample(config, fixture, both) == _sample(
            config, fixture, _block(target_spot_name="Mark"))

    def test_shape_oscillates_around_the_point_aim(self):
        fixture = _fixture()
        config = _config(fixture)
        centre = _sample(config, fixture,
                         _block(target_point=[1.0, -2.0, 0.0]))
        circle = _block(target_point=[1.0, -2.0, 0.0],
                        effect_type="circle", pan_amplitude=30.0,
                        tilt_amplitude=20.0)
        # t=0 on a circle: pan = centre + amplitude, tilt = centre.
        pan, tilt = _sample(config, fixture, circle, time_s=0.0)
        assert abs(pan - (centre[0] + 30)) <= 1
        assert abs(tilt - centre[1]) <= 1


class TestExportPlaneTargets:
    def test_plane_target_exports_and_beats_everything(self):
        from autogen.spatial import compute_stage_planes
        fixture = _fixture()
        config = _config(fixture)
        planes = {p.name for p in compute_stage_planes(config)}
        assert planes, "config must yield stage planes"
        plane_name = sorted(planes)[0]
        block = _block(target_plane_name=plane_name,
                       target_spot_name="Mark", effect_type="circle",
                       pan_amplitude=20.0, tilt_amplitude=20.0)
        got = _sample(config, fixture, block)
        spot_only = _sample(config, fixture,
                            _block(target_spot_name="Mark",
                                   effect_type="circle",
                                   pan_amplitude=20.0,
                                   tilt_amplitude=20.0))
        assert got is not None
        assert 0 <= got[0] <= 255 and 0 <= got[1] <= 255
        assert got != spot_only  # the plane path won

    def test_plane_samples_move_over_time(self):
        from autogen.spatial import compute_stage_planes
        fixture = _fixture()
        config = _config(fixture)
        plane_name = sorted(p.name
                            for p in compute_stage_planes(config))[0]
        block = _block(target_plane_name=plane_name, effect_type="circle",
                       pan_amplitude=40.0, tilt_amplitude=40.0)
        a = _sample(config, fixture, block, time_s=0.0)
        b = _sample(config, fixture, block, time_s=1.0)
        assert a != b


class TestNativePointTargets:
    def _pan_tilt_after(self, manager, fmap, block):
        manager.clear_all_dmx()
        manager._apply_movement_block(fmap, block, 0.0, 0, 1)
        state = manager.dmx_state[fmap.fixture.universe]
        pan_ch = fmap.pan_channels[0]
        tilt_ch = fmap.tilt_channels[0]
        return state[pan_ch], state[tilt_ch]

    def test_dmx_manager_point_matches_equivalent_spot(
            self, mock_fixture_def):
        from utils.artnet.dmx_manager import DMXManager
        fixture = _fixture(manufacturer="TestMfr")
        fixture.model = "TestModel"
        config = _config(fixture)
        manager = DMXManager(config,
                             {"TestMfr_TestModel": mock_fixture_def})
        fmap = manager.fixture_maps[fixture.name]
        via_spot = self._pan_tilt_after(
            manager, fmap, _block(target_spot_name="Mark"))
        via_point = self._pan_tilt_after(
            manager, fmap, _block(target_point=[1.0, -2.0, 0.0]))
        manual = self._pan_tilt_after(
            manager, fmap, _block(pan=10.0, tilt=10.0))
        assert via_point == via_spot
        assert via_point != manual


class TestSerialization:
    def test_target_point_round_trips(self):
        block = _block(target_point=[1.0, -2.5, 0.25])
        loaded = MovementBlock.from_dict(block.to_dict())
        assert loaded.target_point == [1.0, -2.5, 0.25]

    def test_absent_point_stays_none(self):
        loaded = MovementBlock.from_dict(_block().to_dict())
        assert loaded.target_point is None
        legacy = MovementBlock.from_dict({"start_time": 0, "end_time": 1})
        assert legacy.target_point is None


class TestDanglingSpotFallThrough:
    def test_dangling_spot_name_falls_through_to_point(
            self, mock_fixture_def):
        """A spot name that does not resolve in THIS config (a morphed
        show on rig B carrying rig A's spot names) must continue down
        the documented priority chain to target_point - never jump to
        rig A's raw pan/tilt (2026-07-16 fix; raw values pointed the
        venue movers anywhere but the stage)."""
        from utils.artnet.dmx_manager import DMXManager
        fixture = _fixture(manufacturer="TestMfr")
        fixture.model = "TestModel"
        config = _config(fixture)
        manager = DMXManager(config,
                             {"TestMfr_TestModel": mock_fixture_def})
        fmap = manager.fixture_maps[fixture.name]
        helper = TestNativePointTargets()
        via_point = helper._pan_tilt_after(
            manager, fmap, _block(target_point=[1.0, -2.0, 0.0]))
        dangling = helper._pan_tilt_after(
            manager, fmap, _block(target_spot_name="NoSuchSpot",
                                  target_point=[1.0, -2.0, 0.0],
                                  pan=10.0, tilt=10.0))
        manual = helper._pan_tilt_after(
            manager, fmap, _block(pan=10.0, tilt=10.0))
        assert dangling == via_point
        assert dangling != manual
