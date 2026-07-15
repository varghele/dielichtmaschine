# utils/target_resolver.py
# Utilities for resolving lane targets to fixture lists

from typing import List, Tuple, Optional, Set

from utils import user_warnings

# Track warnings to avoid spamming the same message repeatedly
_warned_groups: Set[str] = set()
_warned_indices: Set[Tuple[str, int]] = set()


def reset_warnings():
    """Reset warning tracking (call when config changes)."""
    global _warned_groups, _warned_indices
    _warned_groups.clear()
    _warned_indices.clear()


def parse_target(target: str) -> Tuple[str, Optional[int]]:
    """Parse a target string into group name and optional fixture index.

    Args:
        target: Target string like "Front Wash" or "Moving Heads:2"

    Returns:
        Tuple of (group_name, fixture_index or None)
    """
    if ":" in target:
        group_name, index_str = target.rsplit(":", 1)
        try:
            index = int(index_str)
            return (group_name, index)
        except ValueError:
            # Not a valid index, treat whole string as group name
            return (target, None)
    return (target, None)


def format_target(group_name: str, fixture_index: Optional[int] = None) -> str:
    """Format a target string from components.

    Args:
        group_name: Name of the fixture group
        fixture_index: Optional 0-indexed fixture position

    Returns:
        Target string like "Front Wash" or "Moving Heads:2"
    """
    if fixture_index is not None:
        return f"{group_name}:{fixture_index}"
    return group_name


def resolve_target(target: str, config) -> List:
    """Resolve a single target string to a list of fixtures.

    Args:
        target: Target string like "Front Wash" or "Moving Heads:2"
        config: Configuration object with groups dict

    Returns:
        List of Fixture objects (may be empty if target invalid)
    """
    global _warned_groups, _warned_indices

    group_name, index = parse_target(target)

    if group_name not in config.groups:
        if group_name not in _warned_groups:
            _warned_groups.add(group_name)
            available = list(config.groups.keys())
            user_warnings.warn(
                f"Group '{group_name}' not found. "
                f"Available groups: {available}",
                category="targets")
        return []

    fixtures = config.groups[group_name].fixtures

    if index is not None:
        if 0 <= index < len(fixtures):
            return [fixtures[index]]
        else:
            warn_key = (group_name, index)
            if warn_key not in _warned_indices:
                _warned_indices.add(warn_key)
                user_warnings.warn(
                    f"Fixture index {index} out of range for "
                    f"'{group_name}' (has {len(fixtures)} fixtures)",
                    category="targets")
            return []

    return list(fixtures)


def resolve_targets(targets: List[str], config) -> List:
    """Resolve multiple target strings to a combined fixture list.

    Args:
        targets: List of target strings
        config: Configuration object with groups dict

    Returns:
        List of Fixture objects (may contain duplicates)
    """
    all_fixtures = []
    for target in targets:
        all_fixtures.extend(resolve_target(target, config))
    return all_fixtures


def resolve_targets_unique(targets: List[str], config) -> List:
    """Resolve targets to unique fixtures, preserving first occurrence order.

    Args:
        targets: List of target strings
        config: Configuration object with groups dict

    Returns:
        List of unique Fixture objects in order of first occurrence
    """
    seen = set()
    unique_fixtures = []
    for target in targets:
        for fixture in resolve_target(target, config):
            fixture_id = id(fixture)
            if fixture_id not in seen:
                seen.add(fixture_id)
                unique_fixtures.append(fixture)
    return unique_fixtures


def detect_targets_capabilities(targets: List[str], config, fixture_definitions: dict = None):
    """Detect combined capabilities across all targets (union).

    Args:
        targets: List of target strings
        config: Configuration object with groups dict
        fixture_definitions: Optional dict of fixture definitions

    Returns:
        FixtureGroupCapabilities with union of all target capabilities
    """
    from config.models import FixtureGroupCapabilities
    from utils.fixture_utils import detect_fixture_group_capabilities

    fixtures = resolve_targets_unique(targets, config)
    if not fixtures:
        # Default to all capabilities if no valid fixtures
        return FixtureGroupCapabilities(
            has_dimmer=True,
            has_colour=True,
            has_movement=True,
            has_special=True
        )

    return detect_fixture_group_capabilities(fixtures, fixture_definitions)


def validate_targets(targets: List[str], config) -> List[str]:
    """Validate targets and return list of warning messages.

    Args:
        targets: List of target strings
        config: Configuration object with groups dict

    Returns:
        List of warning strings (empty if all valid)
    """
    warnings = []
    for target in targets:
        group_name, index = parse_target(target)

        if group_name not in config.groups:
            warnings.append(f"Group '{group_name}' does not exist")
        elif index is not None:
            num_fixtures = len(config.groups[group_name].fixtures)
            if index < 0 or index >= num_fixtures:
                warnings.append(f"Fixture index {index} out of range for '{group_name}' (has {num_fixtures} fixtures)")

    return warnings


def get_target_display_name(target: str, config) -> str:
    """Get a human-readable display name for a target.

    Args:
        target: Target string like "Front Wash" or "Moving Heads:2"
        config: Configuration object with groups dict

    Returns:
        Display name like "Front Wash" or "Moving Heads: MH Left"
    """
    group_name, index = parse_target(target)

    if group_name not in config.groups:
        return f"{target} (missing)"

    if index is None:
        return group_name

    fixtures = config.groups[group_name].fixtures
    if 0 <= index < len(fixtures):
        fixture_name = fixtures[index].name or f"Fixture {index + 1}"
        return f"{group_name}: {fixture_name}"
    else:
        return f"{target} (invalid)"
