# utils/tcp/protocol.py
# Protocol definition for Show Creator <-> Visualizer communication

import json
import os
import sys
import xml.etree.ElementTree as ET
from enum import Enum
from typing import Dict, List, Any, Optional, Tuple
from config.models import Configuration, Fixture, FixtureGroup
from utils.fixture_capabilities import get_capabilities_for_fixture


class MessageType(Enum):
    """Message types for Visualizer protocol."""
    STAGE = "stage"
    FIXTURES = "fixtures"
    GROUPS = "groups"
    UPDATE = "update"
    HEARTBEAT = "heartbeat"
    ACK = "ack"


# Cache for parsed fixture definitions
_fixture_definition_cache: Dict[Tuple[str, str], Dict] = {}

# Gobo pattern keyword mapping
# Maps keywords found in gobo capability text to procedural pattern IDs
GOBO_PATTERN_KEYWORDS = {
    # Pattern 0: Open (no gobo)
    'open': 0,
    'no gobo': 0,
    'white': 0,
    'clear': 0,

    # Pattern 1: Dots/circles
    'dot': 1,
    'circle': 1,
    'spot': 1,
    'bubble': 1,
    'ring': 1,

    # Pattern 2: Star
    'star': 2,
    'burst': 2,

    # Pattern 3: Lines/bars
    'line': 3,
    'bar': 3,
    'stripe': 3,
    'beam': 3,

    # Pattern 4: Triangle
    'triangle': 4,
    'prism': 4,

    # Pattern 5: Cross/plus
    'cross': 5,
    'plus': 5,

    # Pattern 6: Generic breakup (default)
    'breakup': 6,
    'break': 6,
    'shatter': 6,
}


def _infer_gobo_pattern(gobo_name: str) -> int:
    """
    Infer the procedural pattern ID from a gobo name.

    Args:
        gobo_name: Name of the gobo (e.g., "Gobo 1", "Star", "Circle dots")

    Returns:
        Pattern ID (0-6), defaults to 6 (generic breakup) for unrecognized patterns
    """
    name_lower = gobo_name.lower()

    # Check each keyword
    for keyword, pattern_id in GOBO_PATTERN_KEYWORDS.items():
        if keyword in name_lower:
            return pattern_id

    # Check for numbered gobos (Gobo 1, Gobo 2, etc.) - map to rotating patterns
    import re
    match = re.search(r'gobo\s*(\d+)', name_lower)
    if match:
        gobo_num = int(match.group(1))
        # Cycle through patterns 1-6 for numbered gobos
        return ((gobo_num - 1) % 6) + 1

    # Default to generic breakup pattern
    return 6


def _find_element(parent, tag: str, ns: Dict[str, str] = None):
    """Find child element by tag name, handling namespace variations."""
    # Extract the base tag name (handle XPath prefixes like .//)
    xpath_prefix = ''
    base_tag = tag
    if tag.startswith('.//'):
        xpath_prefix = './/'
        base_tag = tag[3:]
    elif tag.startswith('./'):
        xpath_prefix = './'
        base_tag = tag[2:]

    # Try with namespace dict first (empty prefix approach)
    if ns:
        elem = parent.find(tag, ns)
        if elem is not None:
            return elem

    # Try without namespace (works for some ElementTree versions)
    elem = parent.find(tag)
    if elem is not None:
        return elem

    # Try with explicit namespace URI in tag
    ns_uri = 'http://www.qlcplus.org/FixtureDefinition'
    elem = parent.find(f'{xpath_prefix}{{{ns_uri}}}{base_tag}')
    return elem


def _findall_elements(parent, tag: str, ns: Dict[str, str] = None):
    """Find all child elements by tag name, handling namespace variations."""
    # Extract the base tag name (handle XPath prefixes like .//)
    xpath_prefix = ''
    base_tag = tag
    if tag.startswith('.//'):
        xpath_prefix = './/'
        base_tag = tag[3:]
    elif tag.startswith('./'):
        xpath_prefix = './'
        base_tag = tag[2:]

    # Try with namespace dict first
    if ns:
        elems = parent.findall(tag, ns)
        if elems:
            return elems

    # Try without namespace
    elems = parent.findall(tag)
    if elems:
        return elems

    # Try with explicit namespace URI in tag
    ns_uri = 'http://www.qlcplus.org/FixtureDefinition'
    elems = parent.findall(f'{xpath_prefix}{{{ns_uri}}}{base_tag}')
    return elems if elems else []


def _get_qxf_fixture_dirs() -> List[str]:
    """Get list of directories containing QXF fixture files."""
    dirs = []

    # Project custom fixtures
    project_custom = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'custom_fixtures')
    if os.path.exists(project_custom):
        dirs.append(project_custom)

    if sys.platform.startswith('linux'):
        dirs.append(os.path.expanduser('~/.qlcplus/Fixtures'))
        dirs.append('/usr/share/qlcplus/Fixtures')
    elif sys.platform == 'win32':
        dirs.append(os.path.join(os.path.expanduser('~'), 'QLC+', 'Fixtures'))
        dirs.append('C:\\QLC+\\Fixtures')
        dirs.append('C:\\QLC+5\\Fixtures')
    elif sys.platform == 'darwin':
        dirs.append(os.path.expanduser('~/Library/Application Support/QLC+/Fixtures'))
        dirs.append('/Applications/QLC+.app/Contents/Resources/Fixtures')

    return dirs


def _find_qxf_file(manufacturer: str, model: str) -> Optional[str]:
    """Find QXF file for a given manufacturer and model."""
    for dir_path in _get_qxf_fixture_dirs():
        if not os.path.exists(dir_path):
            continue

        # Check direct files in directory
        for item in os.listdir(dir_path):
            item_path = os.path.join(dir_path, item)

            if item.endswith('.qxf') and os.path.isfile(item_path):
                # Check if this file matches
                try:
                    tree = ET.parse(item_path)
                    root = tree.getroot()
                    ns = {'': 'http://www.qlcplus.org/FixtureDefinition'}
                    file_mfr = root.find('.//Manufacturer', ns)
                    file_model = root.find('.//Model', ns)
                    if file_mfr is not None and file_model is not None:
                        if file_mfr.text == manufacturer and file_model.text == model:
                            return item_path
                except:
                    pass

            elif os.path.isdir(item_path):
                # Check subdirectory
                for fixture_file in os.listdir(item_path):
                    if fixture_file.endswith('.qxf'):
                        fixture_path = os.path.join(item_path, fixture_file)
                        try:
                            tree = ET.parse(fixture_path)
                            root = tree.getroot()
                            ns = {'': 'http://www.qlcplus.org/FixtureDefinition'}
                            file_mfr = root.find('.//Manufacturer', ns)
                            file_model = root.find('.//Model', ns)
                            if file_mfr is not None and file_model is not None:
                                if file_mfr.text == manufacturer and file_model.text == model:
                                    return fixture_path
                        except:
                            pass

    return None


def _parse_qxf_for_visualizer(manufacturer: str, model: str, mode_name: str) -> Dict[str, Any]:
    """
    Parse QXF file to extract data needed for visualizer.

    Returns dict with:
    - physical: {width, height, depth} in meters
    - layout: {width, height} segment count
    - beam_angle: degrees (for spots/moving heads)
    - pan_max, tilt_max: degrees (for moving heads)
    - fixture_type: derived type (BAR, MH, WASH, SUNSTRIP, PAR)
    - channel_mapping: dict mapping channel numbers to functions
    """
    cache_key = (manufacturer, model)
    if cache_key in _fixture_definition_cache:
        cached = _fixture_definition_cache[cache_key]
        # Return mode-specific channel mapping
        result = cached.copy()
        if mode_name in cached.get('modes', {}):
            result['channel_mapping'] = cached['modes'][mode_name]
        return result

    result = {
        'physical': {'width': 0.3, 'height': 0.3, 'depth': 0.2},  # Default 30cm cube
        'layout': {'width': 1, 'height': 1},
        'beam_angle': 25.0,
        'pan_max': 0.0,
        'tilt_max': 0.0,
        'fixture_type': 'PAR',
        'channel_mapping': {},
        'modes': {},
        'power_consumption': 100.0,  # Default 100W
        'is_led': False,
        'lumens': 0.0,  # Computed after LED classification
    }

    qxf_path = _find_qxf_file(manufacturer, model)
    if not qxf_path:
        _fixture_definition_cache[cache_key] = result
        return result

    try:
        tree = ET.parse(qxf_path)
        root = tree.getroot()
        # Use explicit namespace prefix for reliable matching
        ns = {'qlc': 'http://www.qlcplus.org/FixtureDefinition'}
        # Also support default namespace for some ElementTree versions
        ns_default = {'': 'http://www.qlcplus.org/FixtureDefinition'}

        # Parse fixture type from <Type> element (initial hint, may be refined by channel analysis)
        type_elem = _find_element(root, './/Type', ns)
        type_text = type_elem.text if type_elem is not None else ''
        is_led_bar_type = 'LED Bar' in type_text or 'Sunstrip' in type_text.lower()

        # Initial type based on XML (will be refined after channel analysis)
        if 'Moving Head' in type_text:
            result['fixture_type'] = 'MH'
        elif 'Color Changer' in type_text or 'Wash' in type_text.lower():
            result['fixture_type'] = 'WASH'
        elif is_led_bar_type:
            result['fixture_type'] = 'BAR'  # May be refined to WASH or SUNSTRIP later
        else:
            result['fixture_type'] = 'PAR'

        # Parse Physical section
        physical = _find_element(root, './/Physical', ns)
        if physical is not None:
            dims = _find_element(physical, 'Dimensions', ns)
            if dims is not None:
                # Dimensions in QXF are in mm, convert to meters
                width = float(dims.get('Width', 300)) / 1000.0
                height = float(dims.get('Height', 300)) / 1000.0
                depth = float(dims.get('Depth', 200)) / 1000.0
                result['physical'] = {'width': width, 'height': height, 'depth': depth}

            lens = _find_element(physical, 'Lens', ns)
            if lens is not None:
                deg_min = float(lens.get('DegreesMin', 0))
                deg_max = float(lens.get('DegreesMax', 0))
                if deg_max > 0:
                    result['beam_angle'] = deg_max
                elif deg_min > 0:
                    result['beam_angle'] = deg_min

            focus = _find_element(physical, 'Focus', ns)
            if focus is not None:
                result['pan_max'] = float(focus.get('PanMax', 0))
                result['tilt_max'] = float(focus.get('TiltMax', 0))

            layout = _find_element(physical, 'Layout', ns)
            if layout is not None:
                result['layout'] = {
                    'width': int(layout.get('Width', 1)),
                    'height': int(layout.get('Height', 1))
                }

            # Parse Technical section for PowerConsumption
            technical = _find_element(physical, 'Technical', ns)
            if technical is not None:
                power_str = technical.get('PowerConsumption', '100')
                try:
                    result['power_consumption'] = float(power_str)
                except (ValueError, TypeError):
                    result['power_consumption'] = 100.0

        # Build channel name to preset mapping and extract color wheel capabilities
        channel_presets = {}
        color_wheel_colors = []  # List of {min, max, color} for color wheel

        # Find all Channel elements (try multiple namespace approaches)
        channels = _findall_elements(root, './/Channel', ns)
        if not channels:
            # Try iterating over all elements to find Channel
            channels = [elem for elem in root.iter() if elem.tag.endswith('Channel') and elem.get('Name')]

        for channel in channels:
            ch_name = channel.get('Name', '')
            ch_preset = channel.get('Preset', '')
            if ch_name and ch_preset:
                channel_presets[ch_name] = ch_preset

            # Check if this is a color wheel channel
            ch_name_lower = ch_name.lower()
            group = _find_element(channel, 'Group', ns)
            is_color_channel = (
                (group is not None and group.text == 'Colour') or
                ('color' in ch_name_lower or 'colour' in ch_name_lower)
            ) and not any(x in ch_name_lower for x in ['red', 'green', 'blue', 'white'])

            if is_color_channel:
                # Extract color capabilities
                capabilities = _findall_elements(channel, 'Capability', ns)
                if not capabilities:
                    # Try iterating to find Capability children
                    capabilities = [elem for elem in channel if elem.tag.endswith('Capability')]

                for cap in capabilities:
                    dmx_min = int(cap.get('Min', 0))
                    dmx_max = int(cap.get('Max', 0))
                    color_hex = cap.get('Res1') or cap.get('Color1')

                    # Skip rotation/rainbow effects
                    cap_text = cap.text or ''
                    if 'rainbow' in cap_text.lower() or 'rotation' in cap_text.lower():
                        continue

                    if color_hex and color_hex.startswith('#'):
                        color_wheel_colors.append({
                            'min': dmx_min,
                            'max': dmx_max,
                            'color': color_hex
                        })

        if color_wheel_colors:
            result['color_wheel'] = color_wheel_colors
            print(f"  Parsed {len(color_wheel_colors)} color wheel entries")

        # Extract gobo wheel capabilities
        gobo_wheel_entries = []

        for channel in channels:
            ch_name = channel.get('Name', '')
            ch_name_lower = ch_name.lower()

            # Check if this is a gobo channel
            group = _find_element(channel, 'Group', ns)
            is_gobo_channel = (
                (group is not None and group.text == 'Gobo') or
                'gobo' in ch_name_lower
            ) and 'rotation' not in ch_name_lower and 'rot' not in ch_name_lower

            if is_gobo_channel:
                # Extract gobo capabilities
                capabilities = _findall_elements(channel, 'Capability', ns)
                if not capabilities:
                    capabilities = [elem for elem in channel if elem.tag.endswith('Capability')]

                for cap in capabilities:
                    dmx_min = int(cap.get('Min', 0))
                    dmx_max = int(cap.get('Max', 0))
                    cap_text = (cap.text or '').strip()

                    # Skip shake/rotation/rainbow entries
                    cap_lower = cap_text.lower()
                    if any(x in cap_lower for x in ['shake', 'rotation', 'rainbow', 'spin', 'scroll']):
                        continue

                    # Infer pattern from gobo name
                    pattern_id = _infer_gobo_pattern(cap_text)

                    gobo_wheel_entries.append({
                        'min': dmx_min,
                        'max': dmx_max,
                        'name': cap_text,
                        'pattern': pattern_id
                    })

        if gobo_wheel_entries:
            result['gobo_wheel'] = gobo_wheel_entries
            print(f"  Parsed {len(gobo_wheel_entries)} gobo wheel entries")

        # Parse each mode's channel mapping and Head tags (for pixel segments)
        modes = _findall_elements(root, './/Mode', ns)
        if not modes:
            modes = [elem for elem in root.iter() if elem.tag.endswith('Mode') and elem.get('Name')]

        result['pixel_segments'] = {}  # mode_name -> list of segment channel lists

        for mode in modes:
            mode_name_attr = mode.get('Name', '')
            mode_channels = {}

            mode_channel_elems = _findall_elements(mode, 'Channel', ns)
            if not mode_channel_elems:
                mode_channel_elems = [elem for elem in mode if elem.tag.endswith('Channel')]

            # Build channel number -> name mapping for this mode
            channel_num_to_name = {}
            for ch_elem in mode_channel_elems:
                ch_num = int(ch_elem.get('Number', 0))
                ch_name = ch_elem.text or ''
                channel_num_to_name[ch_num] = ch_name

                # Get preset from channel definition
                preset = channel_presets.get(ch_name, '')

                # Map preset to function
                func = _preset_to_function(preset, ch_name)
                if func:
                    mode_channels[ch_num] = func

            result['modes'][mode_name_attr] = mode_channels

            # Parse Head tags for pixel segment mapping
            # Each Head contains channel numbers for one segment (RGBW)
            heads = _findall_elements(mode, 'Head', ns)
            if not heads:
                heads = [elem for elem in mode if elem.tag.endswith('Head')]

            if heads:
                segments = []
                for head in heads:
                    # Get channel numbers in this head
                    head_channels = _findall_elements(head, 'Channel', ns)
                    if not head_channels:
                        head_channels = [elem for elem in head if elem.tag.endswith('Channel')]

                    segment_data = {'channels': [], 'red': None, 'green': None, 'blue': None, 'white': None}
                    for ch_elem in head_channels:
                        ch_num = int(ch_elem.text) if ch_elem.text else 0
                        segment_data['channels'].append(ch_num)

                        # Determine color function from channel name
                        ch_name = channel_num_to_name.get(ch_num, '')
                        ch_name_lower = ch_name.lower()
                        if 'red' in ch_name_lower:
                            segment_data['red'] = ch_num
                        elif 'green' in ch_name_lower:
                            segment_data['green'] = ch_num
                        elif 'blue' in ch_name_lower:
                            segment_data['blue'] = ch_num
                        elif 'white' in ch_name_lower:
                            segment_data['white'] = ch_num

                    segments.append(segment_data)

                result['pixel_segments'][mode_name_attr] = segments

        # Refine fixture type based on channel analysis for LED bar types
        # Check for PIXELBAR: multi-segment with per-segment RGBW control
        if result['fixture_type'] == 'BAR' and result['layout']['width'] > 1:
            # Multi-segment bar - check if it has per-segment RGBW channels
            # This makes it a PIXELBAR, not a simple BAR
            import re
            has_pixel_channels = False
            for ch_name in channel_presets.keys():
                if re.search(r'(Red|Green|Blue|White)\s+(LED\s+)?\d+', ch_name):
                    has_pixel_channels = True
                    break

            if has_pixel_channels:
                result['fixture_type'] = 'PIXELBAR'

        # For non-PIXELBAR types, apply legacy logic
        if result['fixture_type'] == 'BAR':
            # Check if it has RGB channels and/or dimmer
            has_rgb = False
            has_dimmer = False
            for mode_data in result['modes'].values():
                for func in mode_data.values():
                    if func in ('red', 'green', 'blue'):
                        has_rgb = True
                    if func == 'dimmer':
                        has_dimmer = True
                if has_rgb and has_dimmer:
                    break

            # Single-segment RGB + dimmer = WASH fixture
            # Multi-segment is already handled as PIXELBAR above
            if has_rgb and has_dimmer and result['layout']['width'] == 1:
                result['fixture_type'] = 'WASH'
            elif not has_rgb:
                # No RGB = dimmer-only sunstrip
                result['fixture_type'] = 'SUNSTRIP'

        # Classify LED vs conventional for lumen estimation
        # Heuristic 1: "LED" in model name
        model_upper = model.upper()
        is_led = 'LED' in model_upper
        # Heuristic 2: Has RGBW channels (typical of LED fixtures)
        if not is_led:
            for mode_data in result['modes'].values():
                funcs = set(mode_data.values())
                if {'red', 'green', 'blue', 'white'}.issubset(funcs):
                    is_led = True
                    break
        # Heuristic 3: Moving heads are nearly all LED-based
        if not is_led and result['fixture_type'] == 'MH':
            is_led = True

        result['is_led'] = is_led

        # Estimate lumens from power consumption
        # LED: ~100 lumens/watt, Conventional (halogen): ~17.5 lumens/watt
        efficiency = 100.0 if is_led else 17.5
        result['lumens'] = result['power_consumption'] * efficiency

        _fixture_definition_cache[cache_key] = result

        # Return with specific mode's channel mapping
        if mode_name in result['modes']:
            result['channel_mapping'] = result['modes'][mode_name]

        return result

    except Exception as e:
        print(f"Error parsing QXF {qxf_path}: {e}")
        _fixture_definition_cache[cache_key] = result
        return result


def _preset_to_function(preset: str, channel_name: str) -> Optional[str]:
    """Map QXF preset to a function name for the visualizer."""
    preset_lower = preset.lower() if preset else ''
    name_lower = channel_name.lower() if channel_name else ''

    # Intensity/Color presets
    if 'intensityred' in preset_lower or 'red' in name_lower:
        return 'red'
    if 'intensitygreen' in preset_lower or ('green' in name_lower and 'preset' not in name_lower):
        return 'green'
    if 'intensityblue' in preset_lower or 'blue' in name_lower:
        return 'blue'
    if 'intensitywhite' in preset_lower or 'white' in name_lower:
        return 'white'
    if 'intensityamber' in preset_lower or 'amber' in name_lower:
        return 'amber'
    if 'intensitydimmer' in preset_lower or 'dimmer' in name_lower or 'master' in name_lower:
        return 'dimmer'

    # Movement presets
    if 'positionpan' in preset_lower:
        if 'fine' in preset_lower or 'fine' in name_lower:
            return 'pan_fine'
        return 'pan'
    if 'positiontilt' in preset_lower:
        if 'fine' in preset_lower or 'fine' in name_lower:
            return 'tilt_fine'
        return 'tilt'

    # Shutter/strobe
    if 'shutter' in preset_lower or 'strobe' in name_lower:
        return 'shutter'

    # Special
    # Check for gobo rotation before gobo (more specific first)
    if ('gobo' in name_lower and ('rot' in name_lower or 'spin' in name_lower)) or \
       'goboindex' in preset_lower:
        return 'gobo_rotation'
    if 'gobo' in preset_lower or 'gobo' in name_lower:
        return 'gobo'
    if 'prism' in preset_lower or 'prism' in name_lower:
        return 'prism'
    if 'focus' in preset_lower or 'focus' in name_lower:
        return 'focus'
    if 'zoom' in preset_lower or 'zoom' in name_lower:
        return 'zoom'

    # Color wheel - detect by name (Color, Colour) but not RGB intensity channels
    if ('colour' in name_lower or 'color' in name_lower) and not any(
        x in name_lower for x in ['red', 'green', 'blue', 'white', 'amber', 'uv', 'lime']
    ):
        return 'color_wheel'

    return None


class VisualizerProtocol:
    """
    Protocol for sending configuration data to Visualizer via TCP.

    Messages are JSON-formatted with a newline delimiter.
    """

    @staticmethod
    def create_stage_message(config: Configuration) -> str:
        """
        Create stage dimensions message.

        Args:
            config: Configuration with stage settings

        Returns:
            JSON string with newline delimiter
        """
        message = {
            "type": MessageType.STAGE.value,
            "width": config.stage_width,
            "height": config.stage_height,
            "grid_size": config.grid_size
        }
        return json.dumps(message) + "\n"

    @staticmethod
    def build_fixtures_payload(config: Configuration) -> list:
        """Build the list-of-dicts payload that the visualizer's fixture
        manager expects. Used by both :meth:`create_fixtures_message` (which
        wraps it for TCP) and the in-process embedded visualizer (which
        consumes it directly to skip the JSON round-trip).
        """
        fixtures_data = []

        for fixture in config.fixtures:
            # Fixtures on hidden stage layers are omitted from every 3D
            # preview (embedded + standalone via TCP). They still patch,
            # output DMX, and export — this is display-only.
            if hasattr(config, 'is_fixture_visible') and not config.is_fixture_visible(fixture):
                continue

            # Get QXF metadata for this fixture
            qxf_data = _parse_qxf_for_visualizer(
                fixture.manufacturer,
                fixture.model,
                fixture.current_mode
            )

            # Get group for effective orientation and z values
            group = config.groups.get(fixture.group) if fixture.group else None
            mounting, yaw, pitch, roll = fixture.get_effective_orientation(group)
            fixture_z = fixture.get_effective_z(group)

            fixture_info = {
                "name": fixture.name,
                "manufacturer": fixture.manufacturer,
                "model": fixture.model,
                "mode": fixture.current_mode,
                "universe": fixture.universe,
                "address": fixture.address,
                "position": {
                    "x": fixture.x,
                    "y": fixture.y,
                    "z": fixture_z  # Use effective Z (considers group default)
                },
                "orientation": {
                    "mounting": mounting,  # Use effective orientation
                    "yaw": yaw,
                    "pitch": pitch,
                    "roll": roll
                },
                # QXF-derived data for visualizer (legacy renderer fields).
                "fixture_type": qxf_data.get('fixture_type', fixture.type),
                "physical": qxf_data.get('physical', {'width': 0.3, 'height': 0.3, 'depth': 0.2}),
                "layout": qxf_data.get('layout', {'width': 1, 'height': 1}),
                "beam_angle": qxf_data.get('beam_angle', 25.0),
                "pan_max": qxf_data.get('pan_max', 0.0),
                "tilt_max": qxf_data.get('tilt_max', 0.0),
                "channel_mapping": qxf_data.get('channel_mapping', {}),
                "color_wheel": qxf_data.get('color_wheel', []),
                "gobo_wheel": qxf_data.get('gobo_wheel', []),
                # Per-segment channel mapping for PIXELBAR fixtures
                "pixel_segments": qxf_data.get('pixel_segments', {}).get(fixture.current_mode, []),
                # Brightness data for realistic intensity scaling
                "lumens": qxf_data.get('lumens', 10000.0),
                # Phase D: composable-renderer capabilities (live FixtureCapabilities
                # object). Stripped before JSON serialization in
                # ``create_fixtures_message``; the in-process embedded visualizer
                # consumes this directly.
                "capabilities": get_capabilities_for_fixture(fixture),
            }
            fixtures_data.append(fixture_info)

        return fixtures_data

    @staticmethod
    def create_fixtures_message(config: Configuration) -> str:
        """
        Create fixtures list message with full metadata for visualizer.

        Args:
            config: Configuration with fixtures

        Returns:
            JSON string with newline delimiter
        """
        # Strip the live ``capabilities`` field — it's a Python dataclass
        # (not JSON-serializable) used by the in-process composable renderer.
        # The standalone TCP visualizer consumes only the legacy fields.
        payload = VisualizerProtocol.build_fixtures_payload(config)
        json_payload = [
            {k: v for k, v in fx.items() if k != 'capabilities'} for fx in payload
        ]
        message = {
            "type": MessageType.FIXTURES.value,
            "fixtures": json_payload,
        }
        return json.dumps(message) + "\n"

    @staticmethod
    def create_groups_message(config: Configuration) -> str:
        """
        Create groups message.

        Args:
            config: Configuration with groups

        Returns:
            JSON string with newline delimiter
        """
        groups_data = []

        for group_name, group in config.groups.items():
            group_info = {
                "name": group_name,
                "color": group.color,
                "fixtures": [fixture.name for fixture in group.fixtures]
            }
            groups_data.append(group_info)

        message = {
            "type": MessageType.GROUPS.value,
            "groups": groups_data
        }
        return json.dumps(message) + "\n"

    @staticmethod
    def create_update_message(update_type: str, data: Dict[str, Any]) -> str:
        """
        Create update notification message.

        Args:
            update_type: Type of update (e.g., "fixture_moved", "config_changed")
            data: Update-specific data

        Returns:
            JSON string with newline delimiter
        """
        message = {
            "type": MessageType.UPDATE.value,
            "update_type": update_type,
            "data": data
        }
        return json.dumps(message) + "\n"

    @staticmethod
    def create_heartbeat_message() -> str:
        """
        Create heartbeat message to keep connection alive.

        Returns:
            JSON string with newline delimiter
        """
        message = {
            "type": MessageType.HEARTBEAT.value,
            "timestamp": None  # Will be filled by server
        }
        return json.dumps(message) + "\n"

    @staticmethod
    def create_ack_message(original_type: str) -> str:
        """
        Create acknowledgment message.

        Args:
            original_type: Type of message being acknowledged

        Returns:
            JSON string with newline delimiter
        """
        message = {
            "type": MessageType.ACK.value,
            "ack_type": original_type
        }
        return json.dumps(message) + "\n"

    @staticmethod
    def parse_message(data: str) -> Dict[str, Any]:
        """
        Parse incoming JSON message.

        Args:
            data: JSON string (with or without newline)

        Returns:
            Parsed message dictionary
        """
        return json.loads(data.strip())

    @staticmethod
    def serialize_full_config(config: Configuration) -> List[str]:
        """
        Serialize complete configuration as a sequence of messages.

        Args:
            config: Configuration to serialize

        Returns:
            List of JSON message strings
        """
        messages = []

        # Send stage dimensions first
        messages.append(VisualizerProtocol.create_stage_message(config))

        # Send fixtures
        messages.append(VisualizerProtocol.create_fixtures_message(config))

        # Send groups
        messages.append(VisualizerProtocol.create_groups_message(config))

        return messages
