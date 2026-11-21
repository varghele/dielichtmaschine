# tests/unit/test_target_resolver.py
"""Unit tests for utils/target_resolver.py - target string resolution."""

import pytest
from config.models import Fixture, FixtureMode, FixtureGroup, Configuration, Universe
from utils.target_resolver import (
    parse_target, resolve_target, resolve_targets,
    resolve_targets_unique, validate_targets, get_target_display_name,
    reset_warnings,
)


@pytest.fixture(autouse=True)
def _reset_warnings():
    """Reset warning tracking before each test."""
    reset_warnings()


@pytest.fixture
def fixtures():
    """Three fixtures for testing."""
    return [
        Fixture(universe=0, address=1, manufacturer="M", model="Mo",
                name="Fix1", group="G", current_mode="Std",
                available_modes=[FixtureMode(name="Std", channels=6)],
                x=0.0, y=0.0),
        Fixture(universe=0, address=7, manufacturer="M", model="Mo",
                name="Fix2", group="G", current_mode="Std",
                available_modes=[FixtureMode(name="Std", channels=6)],
                x=2.0, y=0.0),
        Fixture(universe=0, address=13, manufacturer="M", model="Mo",
                name="Fix3", group="G", current_mode="Std",
                available_modes=[FixtureMode(name="Std", channels=6)],
                x=4.0, y=0.0),
    ]


@pytest.fixture
def config(fixtures):
    group = FixtureGroup(name="Front Wash", fixtures=fixtures)
    return Configuration(
        fixtures=fixtures,
        groups={"Front Wash": group},
        universes={0: Universe(id=0, name="U0", output={})},
    )


class TestParseTarget:

    def test_group_only(self):
        name, index = parse_target("Front Wash")
        assert name == "Front Wash"
        assert index is None

    def test_group_with_index(self):
        name, index = parse_target("Front Wash:2")
        assert name == "Front Wash"
        assert index == 2

    def test_group_with_zero_index(self):
        name, index = parse_target("Moving Heads:0")
        assert name == "Moving Heads"
        assert index == 0

    def test_invalid_index_treated_as_name(self):
        name, index = parse_target("Group:abc")
        assert name == "Group:abc"
        assert index is None

    def test_colon_in_group_name(self):
        """rsplit with maxsplit=1 handles colons in group names."""
        name, index = parse_target("Stage:Left:1")
        assert name == "Stage:Left"
        assert index == 1


class TestResolveTarget:

    def test_whole_group(self, config, fixtures):
        result = resolve_target("Front Wash", config)
        assert len(result) == 3

    def test_single_fixture_by_index(self, config, fixtures):
        result = resolve_target("Front Wash:1", config)
        assert len(result) == 1
        assert result[0] is fixtures[1]

    def test_missing_group(self, config):
        result = resolve_target("Nonexistent", config)
        assert result == []

    def test_out_of_range_index(self, config):
        result = resolve_target("Front Wash:99", config)
        assert result == []


class TestResolveTargets:

    def test_multiple_targets(self, config, fixtures):
        result = resolve_targets(["Front Wash:0", "Front Wash:2"], config)
        assert len(result) == 2
        assert result[0] is fixtures[0]
        assert result[1] is fixtures[2]

    def test_allows_duplicates(self, config):
        result = resolve_targets(["Front Wash", "Front Wash"], config)
        assert len(result) == 6  # 3 + 3

    def test_empty_list(self, config):
        assert resolve_targets([], config) == []


class TestResolveTargetsUnique:

    def test_removes_duplicates(self, config, fixtures):
        result = resolve_targets_unique(["Front Wash", "Front Wash:0"], config)
        # Front Wash gives 3, Front Wash:0 is a duplicate
        assert len(result) == 3

    def test_preserves_order(self, config, fixtures):
        result = resolve_targets_unique(["Front Wash:2", "Front Wash:0"], config)
        assert result[0] is fixtures[2]
        assert result[1] is fixtures[0]


class TestValidateTargets:

    def test_valid_targets(self, config):
        warnings = validate_targets(["Front Wash", "Front Wash:1"], config)
        assert warnings == []

    def test_missing_group(self, config):
        warnings = validate_targets(["Nonexistent"], config)
        assert len(warnings) == 1
        assert "does not exist" in warnings[0]

    def test_out_of_range(self, config):
        warnings = validate_targets(["Front Wash:99"], config)
        assert len(warnings) == 1
        assert "out of range" in warnings[0]


class TestGetTargetDisplayName:

    def test_group_name(self, config):
        assert get_target_display_name("Front Wash", config) == "Front Wash"

    def test_indexed_fixture(self, config):
        name = get_target_display_name("Front Wash:0", config)
        assert "Fix1" in name

    def test_missing_group(self, config):
        name = get_target_display_name("Missing", config)
        assert "missing" in name.lower()

    def test_invalid_index(self, config):
        name = get_target_display_name("Front Wash:99", config)
        assert "invalid" in name.lower()