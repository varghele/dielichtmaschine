"""Fixture-definition access for export, playback, and group analysis.

Discovery, parsing, and caching live in utils/fixture_library.py (the
Phase 0 unification, see docs/gdtf-integration-plan.md); this module keeps
the historical entry points and the legacy dict shape their consumers
expect, plus the group-level analysis helpers that operate on those dicts.
"""

from utils.fixture_library import (  # noqa: F401  (re-exported: existing import sites)
    determine_fixture_type,
    get_definition,
    clear_library_cache,
)

# Module-level cache for fixture definitions to avoid repeated file system scans.
# Keyed "manufacturer_model" with the legacy dict shape. fixtures_tab checks
# membership on this dict directly; keep the name stable.
_fixture_definitions_cache = {}
_cache_initialized = False


def get_cached_fixture_definitions(models_in_config=None):
    """
    Get fixture definitions from cache, loading only if needed.

    Args:
        models_in_config: Set of (manufacturer, model) tuples to load.
                         If None, returns all cached definitions.

    Returns:
        dict: Dictionary of fixture definitions
    """
    global _fixture_definitions_cache, _cache_initialized

    if models_in_config is None:
        return _fixture_definitions_cache

    # Check if all requested models are already cached
    missing_models = set()
    for model_tuple in models_in_config:
        key = f"{model_tuple[0]}_{model_tuple[1]}"
        alt_key = f"{model_tuple[0]}_{model_tuple[1].replace(' ', '_')}"
        if key not in _fixture_definitions_cache and alt_key not in _fixture_definitions_cache:
            missing_models.add(model_tuple)

    # Load missing models
    if missing_models:
        new_defs = load_fixture_definitions_from_qlc(missing_models, use_cache=False)
        _fixture_definitions_cache.update(new_defs)

    return _fixture_definitions_cache


def clear_fixture_definitions_cache():
    """Clear the fixture definitions cache (useful when fixture files change)."""
    global _fixture_definitions_cache, _cache_initialized
    _fixture_definitions_cache = {}
    _cache_initialized = False
    clear_library_cache()


def load_fixture_definitions_from_qlc(models_in_config, use_cache=True):
    """
    Loads fixture definitions from QLC+ fixture directories

    Parameters:
        models_in_config: Set of (manufacturer, model) tuples to load
    Returns:
        dict: Dictionary of fixture definitions (legacy dict shape)
    """
    fixture_definitions = {}
    for manufacturer, model in models_in_config:
        defn = get_definition(manufacturer, model)
        if defn is not None:
            fixture_definitions[f"{manufacturer}_{model}"] = defn.to_legacy_dict()
    return fixture_definitions


def detect_fixture_group_capabilities(fixtures, fixture_definitions=None):
    """
    Detect sublane capabilities for a fixture group by analyzing fixture definitions.

    Args:
        fixtures: List of Fixture objects in the group
        fixture_definitions: Optional dict of pre-loaded fixture definitions.
                           If None, will use cached definitions.

    Returns:
        FixtureGroupCapabilities object with detected capabilities
    """
    from config.models import FixtureGroupCapabilities
    from utils.sublane_presets import (
        categorize_preset, SublaneType,
        DIMMER_PRESETS, COLOUR_PRESETS, MOVEMENT_PRESETS, SPECIAL_PRESETS
    )

    capabilities = FixtureGroupCapabilities()

    # If no fixture definitions provided, use cache
    if fixture_definitions is None:
        models_in_config = {(f.manufacturer, f.model) for f in fixtures}
        fixture_definitions = get_cached_fixture_definitions(models_in_config)

    # Analyze each fixture in the group
    for fixture in fixtures:
        fixture_key = f"{fixture.manufacturer}_{fixture.model}"

        if fixture_key not in fixture_definitions:
            # Try alternate key format
            fixture_key = f"{fixture.manufacturer}_{fixture.model.replace(' ', '_')}"

        if fixture_key in fixture_definitions:
            fixture_def = fixture_definitions[fixture_key]

            # Check all channels for their presets and group attributes
            for channel in fixture_def.get('channels', []):
                preset = channel.get('preset')
                group = channel.get('group')

                if preset:
                    sublane_type = categorize_preset(preset)

                    if sublane_type == SublaneType.DIMMER:
                        capabilities.has_dimmer = True
                    elif sublane_type == SublaneType.COLOUR:
                        capabilities.has_colour = True
                    elif sublane_type == SublaneType.MOVEMENT:
                        capabilities.has_movement = True
                    elif sublane_type == SublaneType.SPECIAL:
                        capabilities.has_special = True

                # Also check group attribute (e.g., Color wheel channels have group="Colour")
                if group:
                    group_lower = group.lower()
                    if group_lower in ['colour', 'color']:
                        capabilities.has_colour = True
                    elif group_lower in ['intensity', 'shutter']:
                        capabilities.has_dimmer = True
                    elif group_lower in ['pan', 'tilt']:
                        capabilities.has_movement = True
                    elif group_lower in ['gobo', 'prism', 'beam']:
                        capabilities.has_special = True

                # Check capabilities for color presets (ColorMacro, etc.)
                for capability in channel.get('capabilities', []):
                    cap_preset = capability.get('preset', '')
                    if cap_preset and 'Color' in cap_preset:
                        capabilities.has_colour = True
                        break

                # Fallback: check channel name if no preset and no group
                if not preset and not group:
                    channel_name = channel.get('name', '') or ''

                    # Simple heuristics based on channel name
                    if channel_name and any(word in channel_name for word in ['Dimmer', 'Intensity', 'Master', 'Strobe', 'Shutter']):
                        capabilities.has_dimmer = True
                    elif channel_name and any(word in channel_name for word in ['Red', 'Green', 'Blue', 'White', 'Cyan', 'Magenta', 'Yellow', 'Color', 'Hue', 'Saturation']):
                        capabilities.has_colour = True
                    elif channel_name and any(word in channel_name for word in ['Pan', 'Tilt', 'X-Axis', 'Y-Axis']):
                        capabilities.has_movement = True
                    elif channel_name and any(word in channel_name for word in ['Gobo', 'Prism', 'Focus', 'Zoom', 'Beam']):
                        capabilities.has_special = True

    return capabilities


def get_color_wheel_options(fixtures, fixture_definitions=None):
    """
    Extract color wheel options from fixtures that have a color wheel channel.

    Args:
        fixtures: List of Fixture objects in the group
        fixture_definitions: Optional dict of pre-loaded fixture definitions.

    Returns:
        List of (name, dmx_value, hex_color) tuples, or empty list if no color wheel
    """
    # If no fixture definitions provided, use cache
    if fixture_definitions is None:
        models_in_config = {(f.manufacturer, f.model) for f in fixtures}
        fixture_definitions = get_cached_fixture_definitions(models_in_config)

    color_wheel_options = []

    # Check all fixtures - use the first one that has a color wheel
    for fixture in fixtures:
        fixture_key = f"{fixture.manufacturer}_{fixture.model}"

        if fixture_key not in fixture_definitions:
            fixture_key = f"{fixture.manufacturer}_{fixture.model.replace(' ', '_')}"

        if fixture_key in fixture_definitions:
            fixture_def = fixture_definitions[fixture_key]

            # Look for color wheel channels
            for channel in fixture_def.get('channels', []):
                channel_name = channel.get('name', '') or ''
                group = channel.get('group', '') or ''

                # Check if this is a color wheel/macro channel
                is_color_channel = (
                    group == 'Colour' or
                    'Color' in channel_name or
                    'Colour' in channel_name
                )

                if is_color_channel and channel.get('capabilities'):
                    # Extract color options from capabilities
                    for cap in channel['capabilities']:
                        preset = cap.get('preset', '')
                        name = cap.get('name', '') or ''
                        color = cap.get('color')

                        # Skip rotation/rainbow effects
                        if 'Rainbow' in name or 'Rotation' in name:
                            continue

                        # Skip if no meaningful name
                        if not name or name.lower() in ['no function', 'blackout']:
                            continue

                        # Use the middle of the DMX range
                        dmx_value = (cap.get('min', 0) + cap.get('max', 0)) // 2

                        # Ensure we have a hex color
                        if not color or not color.startswith('#'):
                            # Try to infer from name
                            color = _infer_color_from_name(name)

                        if color:
                            color_wheel_options.append((name, dmx_value, color))

                    # Found a color wheel, return options
                    if color_wheel_options:
                        return color_wheel_options

    return color_wheel_options


def _infer_color_from_name(name):
    """Infer hex color from a color name."""
    color_map = {
        'white': '#FFFFFF',
        'red': '#FF0000',
        'green': '#00FF00',
        'blue': '#0000FF',
        'cyan': '#00FFFF',
        'magenta': '#FF00FF',
        'yellow': '#FFFF00',
        'amber': '#FFBF00',
        'orange': '#FF7F00',
        'purple': '#7F00FF',
        'violet': '#EE82EE',
        'pink': '#FF69B4',
        'uv': '#8000FF',
        'lime': '#BFFF00',
        'light blue': '#ADD8E6',
        'aqua': '#00FFFF',
    }

    name_lower = name.lower()
    for color_name, hex_value in color_map.items():
        if color_name in name_lower:
            return hex_value

    return None


def get_fixture_layout(manufacturer: str, model: str) -> dict:
    """
    Get the layout (segment count) for a fixture from its QXF file.

    Args:
        manufacturer: Fixture manufacturer name
        model: Fixture model name

    Returns:
        dict with 'width' and 'height' keys (defaults to 1, 1 if not found)
    """
    defn = get_definition(manufacturer, model)
    if defn is None:
        return {'width': 1, 'height': 1}
    return {'width': defn.layout[0], 'height': defn.layout[1]}
