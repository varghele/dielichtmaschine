# tests/unit/test_models.py
"""Unit tests for config/models.py - data model classes."""

import os
import pytest
from config.models import (
    Fixture, FixtureMode, FixtureGroup, FixtureGroupCapabilities, Spot,
    DimmerBlock, ColourBlock, MovementBlock, SpecialBlock,
    LightBlock, LightLane, Song, ShowPart, ShowEffect,
    Configuration, Universe, TimelineData
)


class TestFixture:

    def test_creation_defaults(self):
        f = Fixture(universe=0, address=1, manufacturer="M", model="Mo",
                    name="F1", group="G", current_mode="Std",
                    available_modes=[FixtureMode(name="Std", channels=6)])
        assert f.type == "PAR"
        assert f.x == 0.0
        assert f.mounting == "hanging"
        assert f.orientation_uses_group_default is True
        assert f.z_uses_group_default is True

    def test_effective_orientation_own(self):
        f = Fixture(universe=0, address=1, manufacturer="M", model="Mo",
                    name="F1", group="G", current_mode="Std",
                    available_modes=[], mounting="standing",
                    yaw=10.0, pitch=20.0, roll=30.0,
                    orientation_uses_group_default=False)
        m, y, p, r = f.get_effective_orientation(None)
        assert m == "standing"
        assert y == 10.0

    def test_effective_orientation_group(self, sample_fixture_group):
        f = Fixture(universe=0, address=1, manufacturer="M", model="Mo",
                    name="F1", group="G", current_mode="Std",
                    available_modes=[], orientation_uses_group_default=True)
        m, y, p, r = f.get_effective_orientation(sample_fixture_group)
        assert m == sample_fixture_group.default_mounting
        assert y == sample_fixture_group.default_yaw

    def test_effective_z_own(self):
        f = Fixture(universe=0, address=1, manufacturer="M", model="Mo",
                    name="F1", group="G", current_mode="Std",
                    available_modes=[], z=5.0, z_uses_group_default=False)
        assert f.get_effective_z(None) == 5.0

    def test_effective_z_group(self, sample_fixture_group):
        f = Fixture(universe=0, address=1, manufacturer="M", model="Mo",
                    name="F1", group="G", current_mode="Std",
                    available_modes=[], z=5.0, z_uses_group_default=True)
        assert f.get_effective_z(sample_fixture_group) == sample_fixture_group.default_z_height


class TestFixtureGroupCapabilities:

    def test_to_dict_from_dict_roundtrip(self):
        caps = FixtureGroupCapabilities(has_dimmer=True, has_colour=True,
                                         has_movement=False, has_special=True)
        d = caps.to_dict()
        caps2 = FixtureGroupCapabilities.from_dict(d)
        assert caps2.has_dimmer is True
        assert caps2.has_colour is True
        assert caps2.has_movement is False
        assert caps2.has_special is True

    def test_defaults_all_false(self):
        caps = FixtureGroupCapabilities()
        assert caps.has_dimmer is False
        assert caps.has_colour is False


class TestDimmerBlock:

    def test_creation_defaults(self):
        b = DimmerBlock(start_time=0.0, end_time=4.0)
        assert b.intensity == 255.0
        assert b.effect_type == "static"
        assert b.effect_speed == "1"
        assert b.modified is False

    def test_roundtrip(self):
        b = DimmerBlock(start_time=1.0, end_time=5.0, intensity=128.0,
                        effect_type="strobe", effect_speed="2")
        d = b.to_dict()
        b2 = DimmerBlock.from_dict(d)
        assert b2.start_time == 1.0
        assert b2.intensity == 128.0
        assert b2.effect_type == "strobe"


class TestColourBlock:

    def test_creation_defaults(self):
        b = ColourBlock(start_time=0.0, end_time=4.0)
        assert b.color_mode == "RGB"
        assert b.red == 0.0

    def test_custom_values(self):
        b = ColourBlock(start_time=0, end_time=1, red=255, green=128, blue=64)
        assert b.red == 255
        assert b.green == 128

    def test_roundtrip(self):
        b = ColourBlock(start_time=0, end_time=4, color_mode="Wheel",
                        color_wheel_position=5, red=200)
        d = b.to_dict()
        b2 = ColourBlock.from_dict(d)
        assert b2.color_mode == "Wheel"
        assert b2.color_wheel_position == 5
        assert b2.red == 200


class TestMovementBlock:

    def test_defaults(self):
        b = MovementBlock(start_time=0, end_time=4)
        assert b.pan == 127.5
        assert b.tilt == 127.5
        assert b.effect_type == "static"
        assert b.lissajous_ratio == "1:2"
        assert b.target_spot_name is None

    def test_roundtrip(self):
        b = MovementBlock(start_time=0, end_time=4, pan=100, tilt=200,
                          effect_type="circle", lissajous_ratio="2:3",
                          phase_offset_enabled=True, phase_offset_degrees=45.0)
        d = b.to_dict()
        b2 = MovementBlock.from_dict(d)
        assert b2.pan == 100
        assert b2.effect_type == "circle"
        assert b2.lissajous_ratio == "2:3"
        assert b2.phase_offset_enabled is True


class TestSpecialBlock:

    def test_defaults(self):
        b = SpecialBlock(start_time=0, end_time=4)
        assert b.gobo_index == 0
        assert b.focus == 127.5
        assert b.zoom == 127.5
        assert b.prism_enabled is False

    def test_roundtrip(self):
        b = SpecialBlock(start_time=0, end_time=4, gobo_index=3,
                         prism_enabled=True, focus=200)
        d = b.to_dict()
        b2 = SpecialBlock.from_dict(d)
        assert b2.gobo_index == 3
        assert b2.prism_enabled is True
        assert b2.focus == 200


class TestLightBlock:

    def test_get_duration(self):
        b = LightBlock(start_time=2.0, end_time=6.0, effect_name="test")
        assert b.get_duration() == 4.0

    def test_update_envelope_bounds(self):
        b = LightBlock(start_time=0, end_time=0, effect_name="test",
                       dimmer_blocks=[DimmerBlock(start_time=1.0, end_time=5.0)],
                       colour_blocks=[ColourBlock(start_time=0.5, end_time=3.0)])
        b.update_envelope_bounds()
        assert b.start_time == 0.5
        assert b.end_time == 5.0

    def test_roundtrip_with_sublanes(self):
        b = LightBlock(start_time=0, end_time=10, effect_name="test",
                       dimmer_blocks=[DimmerBlock(start_time=0, end_time=10, intensity=200)],
                       movement_blocks=[MovementBlock(start_time=0, end_time=10, pan=100)])
        d = b.to_dict()
        b2 = LightBlock.from_dict(d)
        assert len(b2.dimmer_blocks) == 1
        assert b2.dimmer_blocks[0].intensity == 200
        assert len(b2.movement_blocks) == 1
        assert b2.movement_blocks[0].pan == 100

    def test_legacy_duration_format(self):
        """from_dict with no end_time calculates from duration."""
        d = {"start_time": 2.0, "duration": 3.0, "effect_name": "legacy"}
        b = LightBlock.from_dict(d)
        assert b.start_time == 2.0
        assert b.end_time == 5.0

    def test_legacy_singular_sublane_migration(self):
        """from_dict migrates dimmer_block (singular) to dimmer_blocks list."""
        d = {"start_time": 0, "end_time": 4, "effect_name": "test",
             "dimmer_block": {"start_time": 0, "end_time": 4, "intensity": 128}}
        b = LightBlock.from_dict(d)
        assert len(b.dimmer_blocks) == 1
        assert b.dimmer_blocks[0].intensity == 128

    def test_riff_fields(self):
        b = LightBlock(start_time=0, end_time=4, effect_name="riff:test",
                       riff_source="builds/test", riff_version="1.0")
        d = b.to_dict()
        b2 = LightBlock.from_dict(d)
        assert b2.riff_source == "builds/test"
        assert b2.riff_version == "1.0"


class TestLightLaneModel:

    def test_fixture_targets(self):
        lane = LightLane(name="Test", fixture_targets=["Group1", "Group2"])
        assert lane.fixture_targets == ["Group1", "Group2"]

    def test_fixture_group_backward_compat(self):
        lane = LightLane(name="Test", fixture_targets=["Group1"])
        assert lane.fixture_group == "Group1"
        lane.fixture_group = "NewGroup"
        assert lane.fixture_targets == ["NewGroup"]

    def test_roundtrip(self):
        lane = LightLane(name="Lane1", fixture_targets=["G1"], muted=True)
        lane.light_blocks.append(LightBlock(start_time=0, end_time=4, effect_name="t"))
        d = lane.to_dict()
        lane2 = LightLane.from_dict(d)
        assert lane2.name == "Lane1"
        assert lane2.fixture_targets == ["G1"]
        assert lane2.muted is True
        assert len(lane2.light_blocks) == 1

    def test_legacy_fixture_group_migration(self):
        d = {"name": "L", "fixture_group": "OldGroup", "light_blocks": []}
        lane = LightLane.from_dict(d)
        assert lane.fixture_targets == ["OldGroup"]


class TestSpot:

    def test_creation(self):
        s = Spot(name="Center", x=5.0, y=3.0, z=0.0)
        assert s.name == "Center"
        assert s.x == 5.0
        assert s.z == 0.0

    def test_defaults(self):
        s = Spot(name="S")
        assert s.x == 0.0
        assert s.y == 0.0
        assert s.z == 0.0


class TestShowPart:

    def test_creation(self):
        p = ShowPart(name="Intro", color="#FF0000", signature="4/4",
                     bpm=120.0, num_bars=4, transition="instant")
        assert p.name == "Intro"
        assert p.bpm == 120.0
        assert p.start_time == 0.0
        assert p.duration == 0.0


class TestConfiguration:

    def test_save_load_roundtrip(self, sample_fixture, sample_fixture_group, temp_dir):
        config = Configuration(
            fixtures=[sample_fixture],
            groups={"TestGroup": sample_fixture_group},
            universes={0: Universe(id=0, name="Universe 0", output={})},
            spots={"Center": Spot(name="Center", x=5.0, y=3.0)},
            workspace_path="/test/path"
        )
        filepath = os.path.join(temp_dir, "test_config.yaml")
        config.save(filepath)
        loaded = Configuration.load(filepath)
        assert len(loaded.fixtures) == 1
        assert loaded.fixtures[0].name == "Test Fixture 1"
        assert "TestGroup" in loaded.groups
        assert 0 in loaded.universes
        assert "Center" in loaded.spots
        assert loaded.spots["Center"].x == 5.0
        assert loaded.workspace_path == "/test/path"

    def test_ensure_universes_for_fixtures(self, sample_fixture):
        config = Configuration(fixtures=[sample_fixture], universes={})
        created = config.ensure_universes_for_fixtures()
        assert created is True
        assert sample_fixture.universe in config.universes

    def test_ensure_universes_no_fixtures(self):
        config = Configuration(fixtures=[], universes={})
        assert config.ensure_universes_for_fixtures() is False

    def test_stage_defaults(self):
        config = Configuration()
        assert config.stage_width == 10.0
        assert config.stage_height == 6.0
        assert config.grid_size == 0.5
