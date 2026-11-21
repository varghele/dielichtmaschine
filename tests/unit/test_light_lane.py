# tests/unit/test_light_lane.py
"""Unit tests for timeline/light_lane.py - runtime LightLane class."""

from config.models import LightBlock, DimmerBlock, ColourBlock
from config.models import LightLane as LightLaneModel
from timeline.light_lane import LightLane


class TestLightLaneCreation:

    def test_basic_creation(self):
        lane = LightLane(name="Test Lane", fixture_targets=["Group1"])
        assert lane.name == "Test Lane"
        assert lane.fixture_targets == ["Group1"]
        assert lane.muted is False
        assert lane.solo is False
        assert lane.light_blocks == []

    def test_default_targets(self):
        lane = LightLane(name="Empty")
        assert lane.fixture_targets == []

    def test_fixture_group_backward_compat_getter(self):
        lane = LightLane(name="Test", fixture_targets=["Front Wash"])
        assert lane.fixture_group == "Front Wash"

    def test_fixture_group_backward_compat_empty(self):
        lane = LightLane(name="Test", fixture_targets=[])
        assert lane.fixture_group == ""

    def test_fixture_group_backward_compat_setter(self):
        lane = LightLane(name="Test", fixture_targets=["Old"])
        lane.fixture_group = "New"
        assert lane.fixture_targets == ["New"]


class TestAddLightBlock:

    def test_add_light_block_legacy(self):
        lane = LightLane(name="Test", fixture_targets=["G1"])
        block = lane.add_light_block(2.0, 4.0, "bars.static", {"color": "red"})
        assert block.start_time == 2.0
        assert block.end_time == 6.0
        assert block.effect_name == "bars.static"
        assert len(lane.light_blocks) == 1

    def test_add_light_block_with_sublanes(self):
        lane = LightLane(name="Test", fixture_targets=["G1"])
        dimmer = DimmerBlock(start_time=0, end_time=4, intensity=200)
        colour = ColourBlock(start_time=0, end_time=4, red=255)
        block = lane.add_light_block_with_sublanes(
            0, 4, "effect",
            dimmer_blocks=[dimmer],
            colour_blocks=[colour]
        )
        assert len(block.dimmer_blocks) == 1
        assert len(block.colour_blocks) == 1
        assert block.dimmer_blocks[0].intensity == 200

    def test_add_light_block_with_legacy_single_sublane(self):
        lane = LightLane(name="Test", fixture_targets=["G1"])
        dimmer = DimmerBlock(start_time=0, end_time=4, intensity=128)
        block = lane.add_light_block_with_sublanes(
            0, 4, "effect",
            dimmer_block=dimmer
        )
        assert len(block.dimmer_blocks) == 1
        assert block.dimmer_blocks[0].intensity == 128


class TestRemoveLightBlock:

    def test_remove_existing(self):
        lane = LightLane(name="Test", fixture_targets=["G1"])
        block = lane.add_light_block(0, 4, "effect")
        assert len(lane.light_blocks) == 1
        lane.remove_light_block(block)
        assert len(lane.light_blocks) == 0

    def test_remove_nonexistent(self):
        lane = LightLane(name="Test", fixture_targets=["G1"])
        other = LightBlock(start_time=0, end_time=4, effect_name="other")
        lane.remove_light_block(other)  # Should not raise
        assert len(lane.light_blocks) == 0


class TestGetBlockAtTime:

    def test_finds_block(self):
        lane = LightLane(name="Test", fixture_targets=["G1"])
        block = lane.add_light_block(2.0, 4.0, "effect")
        found = lane.get_block_at_time(3.0)
        assert found is block

    def test_returns_none_when_empty(self):
        lane = LightLane(name="Test", fixture_targets=["G1"])
        assert lane.get_block_at_time(5.0) is None

    def test_returns_none_outside_range(self):
        lane = LightLane(name="Test", fixture_targets=["G1"])
        lane.add_light_block(2.0, 4.0, "effect")
        assert lane.get_block_at_time(0.0) is None
        assert lane.get_block_at_time(7.0) is None


class TestGetBlocksInRange:

    def test_finds_overlapping(self):
        lane = LightLane(name="Test", fixture_targets=["G1"])
        b1 = lane.add_light_block(0, 4, "e1")
        b2 = lane.add_light_block(3, 4, "e2")
        b3 = lane.add_light_block(10, 2, "e3")
        found = lane.get_blocks_in_range(2.0, 5.0)
        assert b1 in found
        assert b2 in found
        assert b3 not in found

    def test_empty_range(self):
        lane = LightLane(name="Test", fixture_targets=["G1"])
        lane.add_light_block(0, 4, "e1")
        found = lane.get_blocks_in_range(10.0, 20.0)
        assert found == []


class TestDataModelConversion:

    def test_to_data_model(self):
        lane = LightLane(name="Lane1", fixture_targets=["G1", "G2"])
        lane.muted = True
        lane.add_light_block(0, 4, "effect")
        model = lane.to_data_model()
        assert model.name == "Lane1"
        assert model.fixture_targets == ["G1", "G2"]
        assert model.muted is True
        assert len(model.light_blocks) == 1

    def test_from_data_model(self):
        model = LightLaneModel(
            name="Lane2",
            fixture_targets=["Front"],
            muted=False,
            solo=True,
            light_blocks=[LightBlock(start_time=1, end_time=5, effect_name="t")]
        )
        lane = LightLane.from_data_model(model)
        assert lane.name == "Lane2"
        assert lane.fixture_targets == ["Front"]
        assert lane.solo is True
        assert len(lane.light_blocks) == 1

    def test_roundtrip(self):
        lane = LightLane(name="RT", fixture_targets=["G1"])
        lane.muted = True
        lane.add_light_block(2.0, 3.0, "test_effect")
        model = lane.to_data_model()
        restored = LightLane.from_data_model(model)
        assert restored.name == "RT"
        assert restored.fixture_targets == ["G1"]
        assert restored.muted is True
        assert len(restored.light_blocks) == 1
