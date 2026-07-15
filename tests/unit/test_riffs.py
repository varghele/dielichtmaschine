# tests/unit/test_riffs.py
"""Unit tests for riff data models and RiffLibrary."""

import pytest
import os
import json
import tempfile
import shutil
from dataclasses import asdict

from config.models import (
    Riff, RiffDimmerBlock, RiffColourBlock, RiffMovementBlock, RiffSpecialBlock,
    LightBlock, DimmerBlock, ColourBlock, MovementBlock, SpecialBlock,
    Fixture, FixtureMode, FixtureGroup
)
from riffs.riff_library import RiffLibrary


# =============================================================================
# Fixtures (pytest fixtures, not lighting fixtures!)
# =============================================================================

@pytest.fixture
def sample_riff_dimmer_block():
    """Create a sample RiffDimmerBlock."""
    return RiffDimmerBlock(
        start_beat=0.0,
        end_beat=4.0,
        intensity=200.0,
        strobe_speed=0.0,
        effect_type="pulse",
        effect_speed="2"
    )


@pytest.fixture
def sample_riff_colour_block():
    """Create a sample RiffColourBlock."""
    return RiffColourBlock(
        start_beat=0.0,
        end_beat=4.0,
        color_mode="RGB",
        red=255.0,
        green=128.0,
        blue=64.0
    )


@pytest.fixture
def sample_riff_movement_block():
    """Create a sample RiffMovementBlock."""
    return RiffMovementBlock(
        start_beat=0.0,
        end_beat=4.0,
        pan=127.5,
        tilt=200.0,
        effect_type="circle",
        effect_speed="1"
    )


@pytest.fixture
def sample_riff_special_block():
    """Create a sample RiffSpecialBlock."""
    return RiffSpecialBlock(
        start_beat=0.0,
        end_beat=4.0,
        gobo_index=3,
        prism_enabled=True
    )


@pytest.fixture
def sample_riff(sample_riff_dimmer_block, sample_riff_colour_block,
                sample_riff_movement_block, sample_riff_special_block):
    """Create a sample Riff with all block types."""
    return Riff(
        name="test_riff",
        category="tests",
        description="A test riff for unit tests",
        length_beats=4.0,
        signature="4/4",
        fixture_types=["MH"],
        dimmer_blocks=[sample_riff_dimmer_block],
        colour_blocks=[sample_riff_colour_block],
        movement_blocks=[sample_riff_movement_block],
        special_blocks=[sample_riff_special_block],
        tags=["test", "unit"],
        author="pytest",
        version="1.0"
    )


@pytest.fixture
def universal_riff():
    """Create a universal riff compatible with any fixture."""
    return Riff(
        name="universal_fade",
        category="generic",
        description="Universal dimmer fade",
        length_beats=2.0,
        fixture_types=[],  # Empty = universal
        dimmer_blocks=[
            RiffDimmerBlock(start_beat=0.0, end_beat=2.0, intensity=255.0)
        ]
    )


@pytest.fixture
def moving_head_fixture():
    """Create a moving head fixture."""
    return Fixture(
        universe=1,
        address=1,
        manufacturer="Test",
        model="MH Test",
        name="MH1",
        group="Moving Heads",
        current_mode="14ch",
        available_modes=[FixtureMode("14ch", 14)],
        type="MH"
    )


@pytest.fixture
def par_fixture():
    """Create a PAR fixture."""
    return Fixture(
        universe=1,
        address=50,
        manufacturer="Test",
        model="PAR Test",
        name="PAR1",
        group="PARs",
        current_mode="4ch",
        available_modes=[FixtureMode("4ch", 4)],
        type="PAR"
    )


@pytest.fixture
def fixture_group_mh(moving_head_fixture):
    """Create a fixture group with moving head."""
    return FixtureGroup(
        name="Moving Heads",
        fixtures=[moving_head_fixture]
    )


@pytest.fixture
def fixture_group_par(par_fixture):
    """Create a fixture group with PAR."""
    return FixtureGroup(
        name="PARs",
        fixtures=[par_fixture]
    )


@pytest.fixture
def temp_riffs_dir():
    """Create a temporary directory for riffs testing."""
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    shutil.rmtree(temp_dir)


class MockSongStructure:
    """Mock song structure for beat-to-time conversion tests."""

    def __init__(self, bpm: float = 120.0):
        self.bpm = bpm

    def get_bpm_at_time(self, time: float) -> float:
        return self.bpm


class VariableBpmSongStructure:
    """Mock song structure with BPM change at 10 seconds."""

    def get_bpm_at_time(self, time: float) -> float:
        if time < 10.0:
            return 120.0
        else:
            return 140.0


# =============================================================================
# RiffDimmerBlock Tests
# =============================================================================

class TestRiffDimmerBlock:
    """Tests for RiffDimmerBlock dataclass."""

    def test_creation_defaults(self):
        """Test RiffDimmerBlock with default values."""
        block = RiffDimmerBlock(start_beat=0.0, end_beat=4.0)
        assert block.start_beat == 0.0
        assert block.end_beat == 4.0
        assert block.intensity == 255.0
        assert block.strobe_speed == 0.0
        assert block.iris == 255.0
        assert block.effect_type == "static"
        assert block.effect_speed == "1"

    def test_creation_custom_values(self, sample_riff_dimmer_block):
        """Test RiffDimmerBlock with custom values."""
        block = sample_riff_dimmer_block
        assert block.intensity == 200.0
        assert block.effect_type == "pulse"
        assert block.effect_speed == "2"

    def test_to_dict(self, sample_riff_dimmer_block):
        """Test serialization to dictionary."""
        d = sample_riff_dimmer_block.to_dict()
        assert d["start_beat"] == 0.0
        assert d["end_beat"] == 4.0
        assert d["intensity"] == 200.0
        assert d["effect_type"] == "pulse"

    def test_from_dict(self):
        """Test deserialization from dictionary."""
        data = {
            "start_beat": 1.0,
            "end_beat": 3.0,
            "intensity": 180.0,
            "strobe_speed": 5.0,
            "effect_type": "strobe",
            "effect_speed": "4"
        }
        block = RiffDimmerBlock.from_dict(data)
        assert block.start_beat == 1.0
        assert block.end_beat == 3.0
        assert block.intensity == 180.0
        assert block.strobe_speed == 5.0
        assert block.effect_type == "strobe"
        assert block.effect_speed == "4"

    def test_roundtrip_serialization(self, sample_riff_dimmer_block):
        """Test that to_dict -> from_dict preserves data."""
        d = sample_riff_dimmer_block.to_dict()
        restored = RiffDimmerBlock.from_dict(d)
        assert restored.start_beat == sample_riff_dimmer_block.start_beat
        assert restored.end_beat == sample_riff_dimmer_block.end_beat
        assert restored.intensity == sample_riff_dimmer_block.intensity
        assert restored.effect_type == sample_riff_dimmer_block.effect_type


# =============================================================================
# RiffColourBlock Tests
# =============================================================================

class TestRiffColourBlock:
    """Tests for RiffColourBlock dataclass."""

    def test_creation_defaults(self):
        """Test RiffColourBlock with default values."""
        block = RiffColourBlock(start_beat=0.0, end_beat=2.0)
        assert block.color_mode == "RGB"
        assert block.red == 255.0
        assert block.green == 255.0
        assert block.blue == 255.0
        assert block.white == 0.0

    def test_to_dict(self, sample_riff_colour_block):
        """Test serialization to dictionary."""
        d = sample_riff_colour_block.to_dict()
        assert d["red"] == 255.0
        assert d["green"] == 128.0
        assert d["blue"] == 64.0

    def test_from_dict(self):
        """Test deserialization from dictionary."""
        data = {
            "start_beat": 0.0,
            "end_beat": 4.0,
            "color_mode": "HSV",
            "hue": 180.0,
            "saturation": 100.0,
            "value": 255.0
        }
        block = RiffColourBlock.from_dict(data)
        assert block.color_mode == "HSV"
        assert block.hue == 180.0


# =============================================================================
# RiffMovementBlock Tests
# =============================================================================

class TestRiffMovementBlock:
    """Tests for RiffMovementBlock dataclass."""

    def test_creation_defaults(self):
        """Test RiffMovementBlock with default values."""
        block = RiffMovementBlock(start_beat=0.0, end_beat=4.0)
        assert block.pan == 127.5
        assert block.tilt == 127.5
        assert block.effect_type == "static"
        assert block.interpolate_from_previous is True  # Default is True

    def test_movement_effect_params(self):
        """Test movement effect parameters."""
        block = RiffMovementBlock(
            start_beat=0.0,
            end_beat=8.0,
            effect_type="circle",
            pan_amplitude=50.0,
            tilt_amplitude=30.0,
            phase_offset_enabled=True,
            phase_offset_degrees=90.0
        )
        assert block.effect_type == "circle"
        assert block.pan_amplitude == 50.0
        assert block.phase_offset_degrees == 90.0

    def test_roundtrip_serialization(self, sample_riff_movement_block):
        """Test serialization roundtrip."""
        d = sample_riff_movement_block.to_dict()
        restored = RiffMovementBlock.from_dict(d)
        assert restored.pan == sample_riff_movement_block.pan
        assert restored.tilt == sample_riff_movement_block.tilt
        assert restored.effect_type == sample_riff_movement_block.effect_type


# =============================================================================
# RiffSpecialBlock Tests
# =============================================================================

class TestRiffSpecialBlock:
    """Tests for RiffSpecialBlock dataclass."""

    def test_creation_defaults(self):
        """Test RiffSpecialBlock with default values."""
        block = RiffSpecialBlock(start_beat=0.0, end_beat=4.0)
        assert block.gobo_index == 0
        assert block.gobo_rotation == 0.0
        assert block.focus == 127.5  # Center position
        assert block.zoom == 127.5   # Center position
        assert block.prism_enabled is False

    def test_special_effects(self):
        """Test special block with effects."""
        block = RiffSpecialBlock(
            start_beat=0.0,
            end_beat=4.0,
            gobo_index=5,
            gobo_rotation=128.0,
            prism_enabled=True,
            prism_rotation=64.0
        )
        assert block.gobo_index == 5
        assert block.prism_enabled is True


# =============================================================================
# Riff Tests
# =============================================================================

class TestRiff:
    """Tests for Riff dataclass."""

    def test_creation(self, sample_riff):
        """Test Riff creation."""
        assert sample_riff.name == "test_riff"
        assert sample_riff.category == "tests"
        assert sample_riff.length_beats == 4.0
        assert len(sample_riff.dimmer_blocks) == 1
        assert len(sample_riff.colour_blocks) == 1
        assert len(sample_riff.movement_blocks) == 1
        assert len(sample_riff.special_blocks) == 1

    def test_to_dict(self, sample_riff):
        """Test Riff serialization."""
        d = sample_riff.to_dict()
        assert d["name"] == "test_riff"
        assert d["length_beats"] == 4.0
        assert len(d["dimmer_blocks"]) == 1
        assert "test" in d["tags"]

    def test_from_dict(self, sample_riff):
        """Test Riff deserialization."""
        d = sample_riff.to_dict()
        restored = Riff.from_dict(d)
        assert restored.name == sample_riff.name
        assert restored.category == sample_riff.category
        assert len(restored.dimmer_blocks) == len(sample_riff.dimmer_blocks)
        assert restored.dimmer_blocks[0].intensity == sample_riff.dimmer_blocks[0].intensity

    def test_json_roundtrip(self, sample_riff):
        """Test JSON serialization roundtrip."""
        json_str = json.dumps(sample_riff.to_dict())
        data = json.loads(json_str)
        restored = Riff.from_dict(data)
        assert restored.name == sample_riff.name


# =============================================================================
# Fixture Compatibility Tests
# =============================================================================

class TestRiffCompatibility:
    """Tests for riff-fixture compatibility checking."""

    def test_universal_riff_compatibility(self, universal_riff, fixture_group_mh, fixture_group_par):
        """Universal riffs should be compatible with any fixture."""
        is_compat, reason = universal_riff.is_compatible_with(fixture_group_mh)
        assert is_compat is True
        assert reason == ""

        is_compat, reason = universal_riff.is_compatible_with(fixture_group_par)
        assert is_compat is True

    def test_mh_riff_compatible_with_mh(self, sample_riff, fixture_group_mh):
        """MH riff should be compatible with MH fixture group."""
        is_compat, reason = sample_riff.is_compatible_with(fixture_group_mh)
        assert is_compat is True

    def test_mh_riff_incompatible_with_par(self, sample_riff, fixture_group_par):
        """MH riff should not be compatible with PAR fixture group."""
        is_compat, reason = sample_riff.is_compatible_with(fixture_group_par)
        assert is_compat is False
        assert "MH" in reason

    def test_empty_fixture_group(self, sample_riff):
        """Test compatibility with empty fixture group."""
        empty_group = FixtureGroup(name="Empty", fixtures=[])
        is_compat, reason = sample_riff.is_compatible_with(empty_group)
        assert is_compat is False

    # ----- Phase D: chassis-normalized compatibility -----

    def test_chassis_keyed_riff_matches_legacy_mh_group(self, fixture_group_mh):
        """A riff using ``moving_yoke`` (Chassis enum name) should match a
        group whose fixtures have legacy ``type=='MH'``."""
        riff = Riff(name="Yoke riff", fixture_types=["moving_yoke"])
        is_compat, _ = riff.is_compatible_with(fixture_group_mh)
        assert is_compat is True

    def test_legacy_pixelbar_and_sunstrip_collapse_to_bar_chassis(self, fixture_group_par):
        """A riff requiring ``["PIXELBAR"]`` collapses to Chassis.BAR; a PAR
        group has Chassis.PAR fixtures and should NOT match."""
        riff = Riff(name="Pixel riff", fixture_types=["PIXELBAR"])
        is_compat, _ = riff.is_compatible_with(fixture_group_par)
        assert is_compat is False

    def test_wash_legacy_string_matches_par_chassis(self, fixture_group_par):
        """Legacy ``WASH`` collapses to Chassis.PAR (per chassis_from_legacy_type),
        so a riff requiring WASH matches a PAR group."""
        riff = Riff(name="Wash riff", fixture_types=["WASH"])
        is_compat, _ = riff.is_compatible_with(fixture_group_par)
        assert is_compat is True

    def test_chassis_name_case_insensitive(self, fixture_group_mh):
        riff = Riff(name="Yoke riff upper", fixture_types=["MOVING_YOKE"])
        is_compat, _ = riff.is_compatible_with(fixture_group_mh)
        assert is_compat is True


# =============================================================================
# Beat-to-Time Conversion Tests
# =============================================================================

class TestBeatToTimeConversion:
    """Tests for Riff.to_light_block() beat-to-time conversion."""

    def test_constant_bpm_conversion(self, sample_riff):
        """Test conversion with constant 120 BPM."""
        song = MockSongStructure(bpm=120.0)
        light_block = sample_riff.to_light_block(start_time=0.0, song_structure=song)

        # At 120 BPM, 1 beat = 0.5 seconds, 4 beats = 2.0 seconds
        assert light_block.start_time == 0.0
        assert abs(light_block.end_time - 2.0) < 0.01

        # Check sublane blocks converted correctly
        assert len(light_block.dimmer_blocks) == 1
        dimmer = light_block.dimmer_blocks[0]
        assert dimmer.start_time == 0.0
        assert abs(dimmer.end_time - 2.0) < 0.01
        assert dimmer.intensity == 200.0

    def test_conversion_with_offset_start(self, sample_riff):
        """Test conversion starting at non-zero time."""
        song = MockSongStructure(bpm=120.0)
        light_block = sample_riff.to_light_block(start_time=10.0, song_structure=song)

        # Should start at 10.0 seconds
        assert light_block.start_time == 10.0
        # End should be 10.0 + 2.0 = 12.0 seconds
        assert abs(light_block.end_time - 12.0) < 0.01

    def test_different_bpm(self, universal_riff):
        """Test conversion at different BPM values."""
        # At 60 BPM, 1 beat = 1.0 second
        song_60 = MockSongStructure(bpm=60.0)
        block_60 = universal_riff.to_light_block(0.0, song_60)
        assert abs(block_60.end_time - 2.0) < 0.01  # 2 beats at 60 BPM

        # At 180 BPM, 1 beat = 0.333 seconds
        song_180 = MockSongStructure(bpm=180.0)
        block_180 = universal_riff.to_light_block(0.0, song_180)
        assert abs(block_180.end_time - 0.667) < 0.01  # 2 beats at 180 BPM

    def test_riff_source_set(self, sample_riff):
        """Test that riff_source and riff_version are set correctly."""
        song = MockSongStructure(bpm=120.0)
        light_block = sample_riff.to_light_block(0.0, song)

        assert light_block.riff_source == "tests/test_riff"
        assert light_block.riff_version == "1.0"
        assert light_block.modified is False

    def test_effect_name_set(self, sample_riff):
        """Test that effect name is set from riff name."""
        song = MockSongStructure(bpm=120.0)
        light_block = sample_riff.to_light_block(0.0, song)

        assert light_block.effect_name == "riff:test_riff"

    def test_all_sublane_types_converted(self, sample_riff):
        """Test that all sublane block types are converted."""
        song = MockSongStructure(bpm=120.0)
        light_block = sample_riff.to_light_block(0.0, song)

        assert len(light_block.dimmer_blocks) == 1
        assert len(light_block.colour_blocks) == 1
        assert len(light_block.movement_blocks) == 1
        assert len(light_block.special_blocks) == 1

        # Check colour values preserved
        colour = light_block.colour_blocks[0]
        assert colour.red == 255.0
        assert colour.green == 128.0
        assert colour.blue == 64.0

        # Check movement values preserved
        movement = light_block.movement_blocks[0]
        assert movement.pan == 127.5
        assert movement.tilt == 200.0

        # Check special values preserved
        special = light_block.special_blocks[0]
        assert special.gobo_index == 3
        assert special.prism_enabled is True


# =============================================================================
# RiffLibrary Tests
# =============================================================================

class TestRiffLibrary:
    """Tests for RiffLibrary class."""

    def test_init_empty_directory(self, temp_riffs_dir):
        """Test initialization with empty directory."""
        library = RiffLibrary(temp_riffs_dir)
        assert len(library) == 0
        assert library.get_categories() == []

    def test_save_and_load_riff(self, temp_riffs_dir, sample_riff):
        """Test saving and loading a riff."""
        library = RiffLibrary(temp_riffs_dir)

        # Save riff
        filepath = library.save_riff(sample_riff, "tests")
        assert os.path.exists(filepath)
        assert filepath.endswith(".json")

        # Check it's in the library
        assert "tests/test_riff" in library
        loaded = library.get_riff("tests/test_riff")
        assert loaded is not None
        assert loaded.name == "test_riff"

    def test_save_creates_category_directory(self, temp_riffs_dir, sample_riff):
        """Test that save creates category directory if needed."""
        library = RiffLibrary(temp_riffs_dir)
        library.save_riff(sample_riff, "new_category")

        category_dir = os.path.join(temp_riffs_dir, "new_category")
        assert os.path.isdir(category_dir)

    def test_get_categories(self, temp_riffs_dir, sample_riff, universal_riff):
        """Test getting category list."""
        library = RiffLibrary(temp_riffs_dir)
        library.save_riff(sample_riff, "tests")
        library.save_riff(universal_riff, "generic")

        categories = library.get_categories()
        assert "tests" in categories
        assert "generic" in categories

    def test_get_riffs_in_category(self, temp_riffs_dir, sample_riff, universal_riff):
        """Test getting riffs in a specific category."""
        library = RiffLibrary(temp_riffs_dir)
        library.save_riff(sample_riff, "tests")
        library.save_riff(universal_riff, "tests")

        riffs = library.get_riffs_in_category("tests")
        assert len(riffs) == 2

    def test_search_by_name(self, temp_riffs_dir, sample_riff, universal_riff):
        """Test searching riffs by name."""
        library = RiffLibrary(temp_riffs_dir)
        library.save_riff(sample_riff)
        library.save_riff(universal_riff)

        results = library.search("test")
        assert len(results) == 1
        assert results[0].name == "test_riff"

    def test_search_by_tag(self, temp_riffs_dir, sample_riff):
        """Test searching riffs by tag."""
        library = RiffLibrary(temp_riffs_dir)
        library.save_riff(sample_riff)

        results = library.search("unit")
        assert len(results) == 1
        assert results[0].name == "test_riff"

    def test_get_compatible_riffs(self, temp_riffs_dir, sample_riff, universal_riff,
                                   fixture_group_mh, fixture_group_par):
        """Test getting compatible riffs for fixture group."""
        library = RiffLibrary(temp_riffs_dir)
        library.save_riff(sample_riff)  # MH only
        library.save_riff(universal_riff)  # Universal

        # MH group should get both
        mh_riffs = library.get_compatible_riffs(fixture_group_mh)
        assert len(mh_riffs) == 2

        # PAR group should only get universal
        par_riffs = library.get_compatible_riffs(fixture_group_par)
        assert len(par_riffs) == 1
        assert par_riffs[0].name == "universal_fade"

    def test_delete_riff(self, temp_riffs_dir, sample_riff):
        """Test deleting a riff."""
        library = RiffLibrary(temp_riffs_dir)
        filepath = library.save_riff(sample_riff, "tests")

        assert "tests/test_riff" in library
        assert os.path.exists(filepath)

        # Delete
        result = library.delete_riff("tests/test_riff")
        assert result is True
        assert "tests/test_riff" not in library
        assert not os.path.exists(filepath)

    def test_delete_nonexistent_riff(self, temp_riffs_dir):
        """Test deleting a riff that doesn't exist."""
        library = RiffLibrary(temp_riffs_dir)
        result = library.delete_riff("nonexistent/riff")
        assert result is False

    def test_refresh(self, temp_riffs_dir, sample_riff):
        """Test refreshing library from disk."""
        library = RiffLibrary(temp_riffs_dir)
        library.save_riff(sample_riff)

        # Create new library instance (simulates external change)
        library2 = RiffLibrary(temp_riffs_dir)
        assert len(library2) == 1

        # Manually delete the file
        filepath = os.path.join(temp_riffs_dir, "tests", "test_riff.json")
        os.remove(filepath)

        # Refresh should pick up the change
        library.refresh()
        assert len(library) == 0

    def test_get_all_riffs(self, temp_riffs_dir, sample_riff, universal_riff):
        """Test getting all riffs."""
        library = RiffLibrary(temp_riffs_dir)
        library.save_riff(sample_riff, "tests")
        library.save_riff(universal_riff, "generic")

        all_riffs = library.get_all_riffs()
        assert len(all_riffs) == 2

    def test_contains(self, temp_riffs_dir, sample_riff):
        """Test __contains__ method."""
        library = RiffLibrary(temp_riffs_dir)
        library.save_riff(sample_riff, "tests")

        assert "tests/test_riff" in library
        assert "tests/nonexistent" not in library


# =============================================================================
# LightBlock Riff Fields Tests
# =============================================================================

class TestLightBlockRiffFields:
    """Tests for riff-related fields on LightBlock."""

    def test_riff_source_serialization(self):
        """Test that riff_source is serialized correctly."""
        block = LightBlock(
            start_time=0.0,
            end_time=4.0,
            effect_name="riff:test",
            riff_source="builds/strobe_build",
            riff_version="1.0"
        )
        d = block.to_dict()
        assert d["riff_source"] == "builds/strobe_build"
        assert d["riff_version"] == "1.0"

    def test_riff_source_deserialization(self):
        """Test that riff_source is deserialized correctly."""
        data = {
            "start_time": 0.0,
            "end_time": 4.0,
            "effect_name": "riff:test",
            "riff_source": "fills/color_chase",
            "riff_version": "2.0",
            "modified": True
        }
        block = LightBlock.from_dict(data)
        assert block.riff_source == "fills/color_chase"
        assert block.riff_version == "2.0"
        assert block.modified is True

    def test_riff_fields_optional(self):
        """Test that riff fields are optional (None by default)."""
        block = LightBlock(
            start_time=0.0,
            end_time=4.0,
            effect_name="manual_effect"
        )
        assert block.riff_source is None
        assert block.riff_version is None
        assert block.modified is False


# =============================================================================
# Integration Tests
# =============================================================================

class TestRiffIntegration:
    """Integration tests for the complete riff workflow."""

    def test_create_save_load_convert_workflow(self, temp_riffs_dir):
        """Test complete workflow: create riff, save, load, convert to LightBlock."""
        # Create a riff
        riff = Riff(
            name="integration_test",
            category="tests",
            length_beats=8.0,
            dimmer_blocks=[
                RiffDimmerBlock(start_beat=0.0, end_beat=4.0, intensity=255.0),
                RiffDimmerBlock(start_beat=4.0, end_beat=8.0, intensity=128.0)
            ],
            colour_blocks=[
                RiffColourBlock(start_beat=0.0, end_beat=8.0, red=255.0, green=0.0, blue=0.0)
            ]
        )

        # Save to library
        library = RiffLibrary(temp_riffs_dir)
        library.save_riff(riff, "tests")

        # Create new library instance (simulates app restart)
        library2 = RiffLibrary(temp_riffs_dir)
        loaded = library2.get_riff("tests/integration_test")

        assert loaded is not None
        assert loaded.name == "integration_test"
        assert len(loaded.dimmer_blocks) == 2

        # Convert to LightBlock
        song = MockSongStructure(bpm=120.0)
        light_block = loaded.to_light_block(start_time=5.0, song_structure=song)

        # At 120 BPM, 8 beats = 4 seconds
        assert light_block.start_time == 5.0
        assert abs(light_block.end_time - 9.0) < 0.01

        # Check dimmer blocks converted
        assert len(light_block.dimmer_blocks) == 2
        assert light_block.dimmer_blocks[0].intensity == 255.0
        assert light_block.dimmer_blocks[1].intensity == 128.0

        # Second dimmer block should start at 5.0 + 2.0 = 7.0 (4 beats at 120 BPM)
        assert abs(light_block.dimmer_blocks[1].start_time - 7.0) < 0.01

    def test_multiple_riffs_same_category(self, temp_riffs_dir):
        """Test multiple riffs in the same category."""
        library = RiffLibrary(temp_riffs_dir)

        for i in range(5):
            riff = Riff(
                name=f"riff_{i}",
                category="batch",
                length_beats=4.0,
                dimmer_blocks=[RiffDimmerBlock(start_beat=0.0, end_beat=4.0)]
            )
            library.save_riff(riff, "batch")

        assert len(library.get_riffs_in_category("batch")) == 5
        assert len(library) == 5


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


# =============================================================================
# Tag search + parse_tags (riff tagging, v1.3)
# =============================================================================

class TestParseTags:
    """parse_tags: comma-separated user input -> clean tag list."""

    def test_splits_strips_and_drops_empties(self):
        from riffs.riff_library import parse_tags
        assert parse_tags(" punchy , chorus ,, slow ") == \
            ["punchy", "chorus", "slow"]

    def test_strips_leading_hash(self):
        from riffs.riff_library import parse_tags
        assert parse_tags("#punchy, # chorus") == ["punchy", "chorus"]

    def test_dedupes_case_insensitively_keeping_first_spelling(self):
        from riffs.riff_library import parse_tags
        assert parse_tags("Chorus, punchy, #chorus, PUNCHY") == \
            ["Chorus", "punchy"]

    def test_empty_input(self):
        from riffs.riff_library import parse_tags
        assert parse_tags("") == []
        assert parse_tags(None) == []


class TestTagSearch:
    """Library search over tags, incl. the '#tag' tags-only scope."""

    def _library_with_tags(self, temp_riffs_dir):
        from config.models import Riff
        library = RiffLibrary(temp_riffs_dir)
        library.save_riff(Riff(name="warm_wash", tags=["chorus", "slow"]),
                          "loops")
        library.save_riff(Riff(name="chorus_hit", tags=["punchy"]),
                          "fills")
        library.save_riff(Riff(name="strobe_burst", tags=[]), "drops")
        return library

    def test_plain_query_matches_names_and_tags(self, temp_riffs_dir):
        library = self._library_with_tags(temp_riffs_dir)
        names = {r.name for r in library.search("chorus")}
        # 'chorus' hits the TAG on warm_wash and the NAME of chorus_hit.
        assert names == {"warm_wash", "chorus_hit"}

    def test_hash_query_matches_tags_only(self, temp_riffs_dir):
        library = self._library_with_tags(temp_riffs_dir)
        names = {r.name for r in library.search("#chorus")}
        assert names == {"warm_wash"}, \
            "a #tag query must not drag in name matches"

    def test_bare_hash_matches_nothing(self, temp_riffs_dir):
        library = self._library_with_tags(temp_riffs_dir)
        assert library.search("#") == []

    def test_tags_survive_the_save_load_round_trip(self, temp_riffs_dir):
        from config.models import Riff
        library = RiffLibrary(temp_riffs_dir)
        library.save_riff(Riff(name="tagged", tags=["a", "B"]), "loops")
        reloaded = RiffLibrary(temp_riffs_dir)
        assert reloaded.get_riff("loops/tagged").tags == ["a", "B"]
