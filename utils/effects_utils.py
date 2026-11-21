import logging

logger = logging.getLogger(__name__)

def get_channels_by_property(fixture_def, mode_name, properties):
    """
    Extracts channels with specific properties from a fixture definition
    Parameters:
        fixture_def: Dictionary containing fixture definition
        mode_name: Name of the mode to check
        properties: List of properties to look for
    Returns:
        dict: Dictionary of channel numbers by property
    """
    channels = {}

    # Find the specified mode from modes list
    mode = next((m for m in fixture_def['modes'] if m['name'] == mode_name), None)

    if not mode:
        return channels

    # For each channel in the mode
    for channel_mapping in mode['channels']:
        channel_number = channel_mapping['number']
        channel_name = channel_mapping['name']

        # Find the channel definition
        channel_def = next((ch for ch in fixture_def['channels'] if ch['name'] == channel_name), None)

        if not channel_def:
            continue

        # Check preset property
        if channel_def.get('preset') in properties:
            if channel_def['preset'] not in channels:
                channels[channel_def['preset']] = []
            channels[channel_def['preset']].append({
                'channel': channel_number
            })

        # Check group property
        if channel_def.get('group') in properties:
            if channel_def['group'] not in channels:
                channels[channel_def['group']] = []
            channels[channel_def['group']].append({
                'channel': channel_number
            })

        # Check capabilities for properties
        for capability in channel_def.get('capabilities', []):
            if capability.get('preset') in properties:
                if capability['preset'] not in channels:
                    channels[capability['preset']] = []
                channels[capability['preset']].append({
                    'channel': channel_number,
                    'min': capability.get('min'),
                    'max': capability.get('max')
                })

    return channels


def find_closest_color_dmx(channels_dict, hex_color, fixture_def=None):
    """
    Find the closest color match in the fixture's ColorMacro channel

    Parameters:
        channels_dict: Dictionary of channels by property
        hex_color: Target color as hex string (e.g. "#FF0000")
        fixture_def: Full fixture definition to search if colors not in channels_dict
    Returns:
        int: DMX value for the closest matching color
    """
    if not hex_color:
        return None

    # Remove '#' if present and normalize
    if hex_color.startswith('#'):
        hex_color = hex_color[1:]
    hex_color = hex_color.upper()

    # Convert the target hex color to RGB
    try:
        r = int(hex_color[0:2], 16)
        g = int(hex_color[2:4], 16)
        b = int(hex_color[4:6], 16)
    except (ValueError, IndexError):
        return None

    # Find all color capabilities across all relevant channels
    color_capabilities = []

    # First check ColorMacro channels from channels_dict
    if 'ColorMacro' in channels_dict:
        for channel in channels_dict['ColorMacro']:
            for capability in channel.get('capabilities', []):
                if 'color' in capability and capability['color']:
                    color_capabilities.append(capability)

    # If no colors found in ColorMacro, search through all channels in fixture_def
    if not color_capabilities and fixture_def:
        for channel in fixture_def.get('channels', []):
            # Look for any channel in the Color group or with color capabilities
            if channel.get('group') == 'Colour' or channel.get('name') == 'Color':
                for capability in channel.get('capabilities', []):
                    if 'color' in capability:
                        color_capabilities.append(capability)

    # If still no colors found, try searching all channels for any color information
    if not color_capabilities and fixture_def:
        for channel in fixture_def.get('channels', []):
            for capability in channel.get('capabilities', []):
                if 'color' in capability:
                    color_capabilities.append(capability)

    # Find the closest color match
    best_match = None
    min_distance = float('inf')

    for capability in color_capabilities:
        color_val = capability.get('color', '')

        # Skip SVG files and non-hex values
        if color_val.endswith('.svg') or not color_val.startswith('#'):
            continue

        # Remove '#' if present
        if color_val.startswith('#'):
            color_val = color_val[1:]

        # Convert fixture color to RGB
        try:
            c_r = int(color_val[0:2], 16)
            c_g = int(color_val[2:4], 16)
            c_b = int(color_val[4:6], 16)
        except (ValueError, IndexError):
            continue

        # Calculate color distance (Euclidean distance in RGB space)
        distance = ((r - c_r) ** 2 + (g - c_g) ** 2 + (b - c_b) ** 2) ** 0.5

        if distance < min_distance:
            min_distance = distance
            # Get the middle of the DMX range for this color
            dmx_value = (int(capability['min']) + int(capability['max'])) // 2
            best_match = dmx_value
            logger.debug(f"Found color match: {capability.get('name')} (distance: {distance:.2f}) - DMX: {dmx_value}")

    return best_match
