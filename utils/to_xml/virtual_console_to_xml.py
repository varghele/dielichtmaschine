# utils/to_xml/virtual_console_to_xml.py
# Generates Virtual Console XML for QLC+ workspace

import xml.etree.ElementTree as ET
from typing import Dict, List, Tuple, Any, Optional
from config.models import Configuration, FixtureGroup, FixtureGroupCapabilities
from utils.effects_utils import get_channels_by_property
from utils.sublane_presets import COLOUR_PRESETS, DIMMER_PRESETS, MOVEMENT_PRESETS, SPECIAL_PRESETS
from utils.yoke import export_aim_dmx  # noqa: F401 (aiming moved to the yoke helper)
from utils.to_xml.preset_scenes_to_xml import MOVEMENT_PRESETS_POS


# Constants
VC_BLACK_BACKGROUND = "4278190080"  # ARGB 0xFF000000
VC_WHITE_FOREGROUND = "4294967295"  # ARGB 0xFFFFFFFF
VC_BLACK_FOREGROUND = "4278190080"  # ARGB 0xFF000000 (black text for colored buttons)
VC_DARK_GREY_BACKGROUND = "4282664004"  # ARGB 0xFF404044 (dark grey for sliders)
VC_INVALID_FUNCTION = "4294967295"  # ID for no function

# Layout constants
SLIDER_WIDTH = 60
SLIDER_HEIGHT = 200
XYPAD_SIZE = 200
BUTTON_SIZE = 40
BUTTON_SPACING = 10
GROUP_PADDING = 20
SECTION_SPACING = 30
FRAME_HEADER_HEIGHT = 30
SHOW_BUTTON_SIZE = 75
SPEED_DIAL_WIDTH = 200
SPEED_DIAL_HEIGHT = 175


def create_appearance(
    parent: ET.Element,
    frame_style: str = "None",
    fg_color: str = "Default",
    bg_color: str = "Default",
    bg_image: str = "None",
    font: str = "Default"
) -> ET.Element:
    """Create standard Appearance element for VC widgets."""
    appearance = ET.SubElement(parent, "Appearance")
    ET.SubElement(appearance, "FrameStyle").text = frame_style
    ET.SubElement(appearance, "ForegroundColor").text = fg_color
    ET.SubElement(appearance, "BackgroundColor").text = bg_color
    ET.SubElement(appearance, "BackgroundImage").text = bg_image
    ET.SubElement(appearance, "Font").text = font
    return appearance


def create_window_state(
    parent: ET.Element,
    visible: bool = True,
    x: int = 0,
    y: int = 0,
    width: int = 100,
    height: int = 100
) -> ET.Element:
    """Create WindowState element for positioning."""
    window_state = ET.SubElement(parent, "WindowState")
    window_state.set("Visible", "True" if visible else "False")
    window_state.set("X", str(x))
    window_state.set("Y", str(y))
    window_state.set("Width", str(width))
    window_state.set("Height", str(height))
    return window_state


def create_vc_button(
    parent: ET.Element,
    widget_id: int,
    caption: str,
    function_id: int,
    x: int,
    y: int,
    width: int = BUTTON_SIZE,
    height: int = BUTTON_SIZE,
    action: str = "Toggle",
    bg_color: str = "Default",
    fg_color: str = "Default",
    font: str = "Default"
) -> ET.Element:
    """Create a Virtual Console Button widget."""
    button = ET.SubElement(parent, "Button")
    button.set("Caption", caption)
    button.set("ID", str(widget_id))
    button.set("Icon", "")

    create_window_state(button, True, x, y, width, height)
    create_appearance(button, "None", fg_color, bg_color, "None", font)

    func = ET.SubElement(button, "Function")
    func.set("ID", str(function_id))

    ET.SubElement(button, "Action").text = action

    intensity = ET.SubElement(button, "Intensity")
    intensity.set("Adjust", "False")
    intensity.text = "100"

    return button


def create_vc_slider(
    parent: ET.Element,
    widget_id: int,
    caption: str,
    x: int,
    y: int,
    width: int = SLIDER_WIDTH,
    height: int = SLIDER_HEIGHT,
    slider_mode: str = "Level",
    channels: List[Tuple[int, int]] = None,  # [(fixture_id, channel_num), ...]
    playback_function_id: int = None,
    bg_color: str = "Default"
) -> ET.Element:
    """Create a Virtual Console Slider widget."""
    slider = ET.SubElement(parent, "Slider")
    slider.set("Caption", caption)
    slider.set("ID", str(widget_id))
    slider.set("WidgetStyle", "Slider")
    slider.set("InvertedAppearance", "false")
    slider.set("CatchValues", "true")

    create_window_state(slider, True, x, y, width, height)
    create_appearance(slider, "Sunken", "Default", bg_color)

    mode = ET.SubElement(slider, "SliderMode")
    mode.set("ValueDisplayStyle", "Exact")
    mode.set("ClickAndGoType", "None")
    mode.set("Monitor", "false")
    mode.text = slider_mode

    if slider_mode in ("Level", "Submaster") and channels:
        level = ET.SubElement(slider, "Level")
        level.set("LowLimit", "0")
        level.set("HighLimit", "255")
        # Submasters default to fully open (255); Level sliders default to 0
        level.set("Value", "255" if slider_mode == "Submaster" else "0")

        for fixture_id, channel in channels:
            ch = ET.SubElement(level, "Channel")
            ch.set("Fixture", str(fixture_id))
            ch.text = str(channel)

    playback = ET.SubElement(slider, "Playback")
    func = ET.SubElement(playback, "Function")
    if playback_function_id is not None:
        func.text = str(playback_function_id)
    else:
        func.text = VC_INVALID_FUNCTION

    return slider


def create_vc_xypad(
    parent: ET.Element,
    widget_id: int,
    caption: str,
    x: int,
    y: int,
    width: int = XYPAD_SIZE,
    height: int = XYPAD_SIZE,
    fixtures: List[Tuple[int, int, int]] = None,  # [(fixture_id, pan_ch, tilt_ch), ...]
    efx_presets: List[Tuple[str, int]] = None,  # [(efx_name, function_id), ...]
    position_presets: List[Tuple[str, int]] = None,  # [(position_name, function_id), ...]
    bg_color: str = "Default",
    fixture_obj: Any = None  # Actual fixture object for calculating positions
) -> ET.Element:
    """Create a Virtual Console XY Pad widget with embedded presets."""
    xypad = ET.SubElement(parent, "XYPad")
    xypad.set("Caption", caption)
    xypad.set("ID", str(widget_id))
    xypad.set("InvertedAppearance", "0")

    create_window_state(xypad, True, x, y, width, height)
    create_appearance(xypad, "Sunken", "Default", bg_color)

    # Add fixtures (using normalized 0-1 range, not channel numbers)
    if fixtures:
        for fixture_id, pan_ch, tilt_ch in fixtures:
            fix = ET.SubElement(xypad, "Fixture")
            fix.set("ID", str(fixture_id))
            fix.set("Head", "0")

            # X-axis (Pan) - normalized 0-1 range
            x_axis = ET.SubElement(fix, "Axis")
            x_axis.set("ID", "X")
            x_axis.set("LowLimit", "0")
            x_axis.set("HighLimit", "1")
            x_axis.set("Reverse", "False")

            # Y-axis (Tilt) - normalized 0-1 range
            y_axis = ET.SubElement(fix, "Axis")
            y_axis.set("ID", "Y")
            y_axis.set("LowLimit", "0")
            y_axis.set("HighLimit", "1")
            y_axis.set("Reverse", "False")

    # Pan and Tilt positions
    pan = ET.SubElement(xypad, "Pan")
    pan.set("Position", "0")

    tilt = ET.SubElement(xypad, "Tilt")
    tilt.set("Position", "0")

    # Add EFX presets
    preset_id_counter = 0
    if efx_presets:
        for efx_name, func_id in efx_presets:
            preset = ET.SubElement(xypad, "Preset")
            preset.set("ID", str(preset_id_counter))

            ET.SubElement(preset, "Type").text = "EFX"
            ET.SubElement(preset, "Name").text = efx_name
            ET.SubElement(preset, "FuncID").text = str(func_id)

            preset_id_counter += 1

    # Add Position presets
    if position_presets and fixture_obj:
        # Calculate actual DMX values for each position preset
        for position_name, func_id in position_presets:
            preset = ET.SubElement(xypad, "Preset")
            preset.set("ID", str(preset_id_counter))

            ET.SubElement(preset, "Type").text = "Position"
            ET.SubElement(preset, "Name").text = position_name

            # Extract the position type from the full name (e.g., "Group - Center" -> "Center")
            pos_type = position_name.split(" - ")[-1] if " - " in position_name else position_name

            # Get target world coordinates from MOVEMENT_PRESETS_POS
            target_pos = MOVEMENT_PRESETS_POS.get(pos_type, {"x": 0.0, "y": 0.0, "z": 2.0})
            target_x = target_pos.get("x", 0.0)
            target_y = target_pos.get("y", 0.0)
            target_z = target_pos.get("z", 2.0)

            # Get fixture position and orientation
            fixture_x = getattr(fixture_obj, 'x', 0.0)
            fixture_y = getattr(fixture_obj, 'y', 0.0)
            fixture_z = getattr(fixture_obj, 'z', 3.0)
            mounting = getattr(fixture_obj, 'mounting', 'hanging')
            yaw = getattr(fixture_obj, 'yaw', 0.0)
            pitch = getattr(fixture_obj, 'pitch', 0.0)
            roll = getattr(fixture_obj, 'roll', 0.0)

            # Aim like native output: solver at the definition's real
            # ranges, converted to the real yoke (utils/yoke).
            from utils.yoke import export_aim_dmx
            pan_dmx, tilt_dmx = export_aim_dmx(
                fixture_obj, fixture_z, (target_x, target_y, target_z),
                mounting, yaw, pitch, roll)

            # Set X and Y as actual DMX values (0-255 range)
            ET.SubElement(preset, "X").text = str(pan_dmx)
            ET.SubElement(preset, "Y").text = str(tilt_dmx)

            preset_id_counter += 1
    elif position_presets:
        # Fallback if no fixture object provided
        for position_name, func_id in position_presets:
            preset = ET.SubElement(xypad, "Preset")
            preset.set("ID", str(preset_id_counter))
            ET.SubElement(preset, "Type").text = "Position"
            ET.SubElement(preset, "Name").text = position_name
            ET.SubElement(preset, "X").text = "127"
            ET.SubElement(preset, "Y").text = "127"
            preset_id_counter += 1

    return xypad


def create_vc_frame(
    parent: ET.Element,
    widget_id: int,
    caption: str,
    x: int,
    y: int,
    width: int,
    height: int,
    collapsed: bool = False,
    bg_color: str = "Default",
    show_header: bool = True,
    fg_color: str = "Default"
) -> ET.Element:
    """Create a Virtual Console Frame container widget."""
    frame = ET.SubElement(parent, "Frame")
    frame.set("Caption", caption)
    frame.set("ID", str(widget_id))

    create_window_state(frame, True, x, y, width, height)
    create_appearance(frame, "Sunken", fg_color, bg_color)

    ET.SubElement(frame, "AllowChildren").text = "True"
    ET.SubElement(frame, "AllowResize").text = "True"
    ET.SubElement(frame, "ShowHeader").text = "True" if show_header else "False"
    ET.SubElement(frame, "ShowEnableButton").text = "True"
    ET.SubElement(frame, "Collapsed").text = "True" if collapsed else "False"
    ET.SubElement(frame, "Disabled").text = "False"

    return frame


def create_vc_solo_frame(
    parent: ET.Element,
    widget_id: int,
    caption: str,
    x: int,
    y: int,
    width: int,
    height: int,
    fg_color: str = "Default",
    bg_color: str = "Default"
) -> ET.Element:
    """Create a SoloFrame (only one child button can be active)."""
    frame = ET.SubElement(parent, "SoloFrame")
    frame.set("Caption", caption)
    frame.set("ID", str(widget_id))

    create_window_state(frame, True, x, y, width, height)
    create_appearance(frame, "Sunken", fg_color, bg_color)

    ET.SubElement(frame, "AllowChildren").text = "True"
    ET.SubElement(frame, "AllowResize").text = "True"
    ET.SubElement(frame, "ShowHeader").text = "True"
    ET.SubElement(frame, "ShowEnableButton").text = "True"
    ET.SubElement(frame, "Mixing").text = "False"
    ET.SubElement(frame, "Collapsed").text = "False"
    ET.SubElement(frame, "Disabled").text = "False"

    return frame


def create_vc_speed_dial(
    parent: ET.Element,
    widget_id: int,
    caption: str,
    x: int,
    y: int,
    width: int = SPEED_DIAL_WIDTH,
    height: int = SPEED_DIAL_HEIGHT,
    functions: List[int] = None,
    bg_color: str = "Default",
    fg_color: str = "Default"
) -> ET.Element:
    """Create a SpeedDial widget for BPM/tempo control."""
    dial = ET.SubElement(parent, "SpeedDial")
    dial.set("Caption", caption)
    dial.set("ID", str(widget_id))

    create_window_state(dial, True, x, y, width, height)
    create_appearance(dial, "Sunken", fg_color, bg_color)

    # Time value (default 500ms = 120 BPM)
    ET.SubElement(dial, "Time").text = "500"

    # Visibility mask (show all elements)
    ET.SubElement(dial, "VisibilityMask").text = "63"

    # Reset factor
    ET.SubElement(dial, "ResetFactorOnDialChange").text = "0"

    # Add functions if provided
    if functions:
        for func_id in functions:
            func = ET.SubElement(dial, "Function")
            func.set("ID", str(func_id))

            fade_in = ET.SubElement(func, "FadeIn")
            fade_in.set("Multiplier", "1")
            fade_in.set("Mode", "Multiplier")

            fade_out = ET.SubElement(func, "FadeOut")
            fade_out.set("Multiplier", "1")
            fade_out.set("Mode", "Multiplier")

            duration = ET.SubElement(func, "Duration")
            duration.set("Multiplier", "1")
            duration.set("Mode", "Multiplier")

    # Absolute value control
    abs_val = ET.SubElement(dial, "AbsoluteValue")
    abs_val.set("Min", "100")
    abs_val.set("Max", "10000")

    # Tap tempo
    ET.SubElement(dial, "Tap")

    return dial


def get_fixture_channels_for_preset(
    fixture,
    fixture_definitions: Dict[str, Any],
    preset_names: List[str]
) -> Tuple[Dict[str, List[int]], int]:
    """Get channels matching specific presets for a fixture.

    Returns:
        Tuple of (channels_dict, total_channels)
        channels_dict maps preset names to lists of channel numbers
    """
    fixture_key = f"{fixture.manufacturer}_{fixture.model}"
    fixture_def = fixture_definitions.get(fixture_key)

    if not fixture_def:
        return {}, 0

    mode = next((m for m in fixture_def.get('modes', [])
                 if m['name'] == fixture.current_mode), None)
    if not mode:
        return {}, 0

    total_channels = len(mode.get('channels', []))
    channels_info = get_channels_by_property(fixture_def, fixture.current_mode, preset_names)

    # Convert to simple dict
    channels_dict = {}
    for preset, channel_list in channels_info.items():
        channels_dict[preset] = [c['channel'] for c in channel_list]

    return channels_dict, total_channels


def get_color_wheel_channel(fixture, fixture_definitions: Dict[str, Any]) -> Optional[int]:
    """Get the color wheel channel number for a fixture, if it has one."""
    fixture_key = f"{fixture.manufacturer}_{fixture.model}"
    fixture_def = fixture_definitions.get(fixture_key)

    if not fixture_def:
        return None

    mode = next((m for m in fixture_def.get('modes', [])
                 if m['name'] == fixture.current_mode), None)
    if not mode:
        return None

    # Find a channel with group="Colour" or group="Color"
    for channel_mapping in mode.get('channels', []):
        channel_number = channel_mapping.get('number')
        channel_name = channel_mapping.get('name')

        # Find the channel definition
        channel_def = next((ch for ch in fixture_def.get('channels', [])
                           if ch.get('name') == channel_name), None)

        if channel_def:
            group = channel_def.get('group', '')
            if group and group.lower() in ['colour', 'color']:
                return channel_number

    return None


def _create_button_frame(
    parent: ET.Element,
    widget_id: int,
    title: str,
    buttons: List[Tuple[str, int, str]],  # [(display_name, func_id, bg_color), ...]
    x: int,
    y: int,
    buttons_per_row: int = 5,
    fg_color: str = "Default",
    bg_color: str = "Default",
    solo: bool = False
) -> Tuple[ET.Element, int, int, int]:
    """Create a frame containing preset buttons.

    Args:
        solo: If True, create a SoloFrame where only one button can be active at a time.
              Useful for color presets where selecting one should deactivate others.

    Returns:
        Tuple of (frame_element, next_widget_id, frame_width, frame_height)
    """
    if not buttons:
        return None, widget_id, 0, 0

    num_buttons = len(buttons)
    num_rows = (num_buttons + buttons_per_row - 1) // buttons_per_row
    buttons_in_widest_row = min(num_buttons, buttons_per_row)

    frame_width = buttons_in_widest_row * (BUTTON_SIZE + 5) + GROUP_PADDING * 2
    frame_height = num_rows * (BUTTON_SIZE + 5) + FRAME_HEADER_HEIGHT + GROUP_PADDING * 2

    if solo:
        frame = create_vc_solo_frame(
            parent, widget_id, title,
            x, y, frame_width, frame_height,
            fg_color, bg_color
        )
    else:
        frame = create_vc_frame(
            parent, widget_id, title,
            x, y, frame_width, frame_height,
            show_header=True, bg_color=bg_color, fg_color=fg_color
        )
    widget_id += 1

    btn_x = GROUP_PADDING
    btn_y = FRAME_HEADER_HEIGHT + GROUP_PADDING
    btn_count = 0

    for display_name, func_id, bg_color in buttons:
        # All buttons use black bold text for better readability
        button_fg_color = VC_BLACK_FOREGROUND
        button_font = "Arial,12,-1,5,75,0,0,0,0,0,Bold"  # Bold font

        create_vc_button(
            frame, widget_id, display_name, func_id,
            btn_x, btn_y, BUTTON_SIZE, BUTTON_SIZE, "Toggle", bg_color, button_fg_color, button_font
        )
        widget_id += 1
        btn_count += 1
        btn_x += BUTTON_SIZE + 5

        if btn_count % buttons_per_row == 0:
            btn_x = GROUP_PADDING
            btn_y += BUTTON_SIZE + 5

    return frame, widget_id, frame_width, frame_height


def generate_group_controls(
    parent: ET.Element,
    group_name: str,
    group: FixtureGroup,
    capabilities: FixtureGroupCapabilities,
    fixture_id_map: Dict[int, int],
    fixture_definitions: Dict[str, Any],
    widget_id_counter: int,
    x_offset: int,
    y_offset: int,
    preset_functions: Dict[str, int] = None,
    dark_mode: bool = False
) -> Tuple[ET.Element, int, int]:
    """Generate all controls for a fixture group based on capabilities.

    Creates sliders, XY pad, and grouped preset button frames.

    Returns:
        Tuple of (frame_element, next_widget_id, total_width_used)
    """
    # Set colors based on dark mode
    slider_bg_color = VC_DARK_GREY_BACKGROUND if dark_mode else "Default"
    frame_bg_color = VC_DARK_GREY_BACKGROUND if dark_mode else "Default"
    frame_fg_color = VC_WHITE_FOREGROUND if dark_mode else "Default"

    # Collect channels for all fixtures in group
    dimmer_channels = []  # [(fixture_id, channel), ...]
    red_channels = []
    green_channels = []
    blue_channels = []
    white_channels = []
    color_wheel_channels = []
    focus_channels = []
    zoom_channels = []
    pan_tilt_fixtures = []  # [(fixture_id, pan_ch, tilt_ch), ...]

    for fixture in group.fixtures:
        fixture_id = fixture_id_map.get((fixture.universe, fixture.address))
        if fixture_id is None:
            continue

        all_presets = (
            list(DIMMER_PRESETS) + list(COLOUR_PRESETS) +
            list(MOVEMENT_PRESETS) + list(SPECIAL_PRESETS)
        )
        channels_dict, _ = get_fixture_channels_for_preset(
            fixture, fixture_definitions, all_presets
        )

        # Dimmer
        for ch in channels_dict.get("IntensityMasterDimmer", []):
            dimmer_channels.append((fixture_id, ch))
        for ch in channels_dict.get("IntensityDimmer", []):
            dimmer_channels.append((fixture_id, ch))

        # RGB(W)
        for ch in channels_dict.get("IntensityRed", []):
            red_channels.append((fixture_id, ch))
        for ch in channels_dict.get("IntensityGreen", []):
            green_channels.append((fixture_id, ch))
        for ch in channels_dict.get("IntensityBlue", []):
            blue_channels.append((fixture_id, ch))
        for ch in channels_dict.get("IntensityWhite", []):
            white_channels.append((fixture_id, ch))

        # Color wheel (if no RGB)
        if not red_channels and not green_channels and not blue_channels:
            color_ch = get_color_wheel_channel(fixture, fixture_definitions)
            if color_ch is not None:
                color_wheel_channels.append((fixture_id, color_ch))

        # Special
        for ch in channels_dict.get("BeamFocusNearFar", []):
            focus_channels.append((fixture_id, ch))
        for ch in channels_dict.get("BeamFocusFarNear", []):
            focus_channels.append((fixture_id, ch))
        for ch in channels_dict.get("BeamZoomSmallBig", []):
            zoom_channels.append((fixture_id, ch))
        for ch in channels_dict.get("BeamZoomBigSmall", []):
            zoom_channels.append((fixture_id, ch))

        # Movement (pan/tilt)
        pan_ch = channels_dict.get("PositionPan", [None])[0] if channels_dict.get("PositionPan") else None
        tilt_ch = channels_dict.get("PositionTilt", [None])[0] if channels_dict.get("PositionTilt") else None
        if pan_ch is not None and tilt_ch is not None:
            pan_tilt_fixtures.append((fixture_id, pan_ch, tilt_ch))

    # Determine if we have RGB or color wheel
    has_rgb = bool(red_channels or green_channels or blue_channels)
    has_color_wheel = bool(color_wheel_channels)
    has_xypad = bool(pan_tilt_fixtures)

    # Categorize preset buttons
    color_buttons = []  # [(display_name, func_id, bg_color), ...]
    position_buttons = []
    pattern_buttons = []

    # Color map for button backgrounds
    color_bg_map = {
        "red": "4294901760",      # ARGB red
        "green": "4278255360",    # ARGB green
        "blue": "4278190335",     # ARGB blue
        "white": "4294967295",    # ARGB white
        "amber": "4294945536",    # ARGB amber
        "cyan": "4278255615",     # ARGB cyan
        "magenta": "4294902015",  # ARGB magenta
        "yellow": "4294967040",   # ARGB yellow
        "uv": "4286578816",       # ARGB purple-ish for UV
        "blackout": "4278190080", # ARGB black
    }

    if preset_functions:
        for key, func_id in preset_functions.items():
            display_name = key.split("_", 1)[1] if "_" in key else key

            if key.startswith("Color_"):
                bg_color = color_bg_map.get(display_name.lower(), "Default")
                color_buttons.append((display_name, func_id, bg_color))
            elif key.startswith("Position_"):
                position_buttons.append((display_name, func_id, "Default"))
            elif key.startswith("Pattern_"):
                pattern_buttons.append((display_name, func_id, "Default"))
            # Skip Intensity_ presets

    # Calculate layout dimensions
    num_sliders = 0
    if dimmer_channels:
        num_sliders += 1
    if has_rgb:
        num_sliders += len([c for c in [red_channels, green_channels, blue_channels, white_channels] if c])
    # Remove color wheel slider - use preset buttons instead
    if focus_channels:
        num_sliders += 1
    if zoom_channels:
        num_sliders += 1

    slider_section_width = num_sliders * (SLIDER_WIDTH + 5) if num_sliders > 0 else 0

    # Calculate XY pad height based on position presets
    # Each preset button takes ~25 pixels, base pad needs 200 pixels
    num_position_presets = len(position_buttons)
    PRESET_BUTTON_HEIGHT = 25
    xypad_height = XYPAD_SIZE + (num_position_presets * PRESET_BUTTON_HEIGHT) if has_xypad else XYPAD_SIZE

    # Pattern buttons will be stacked vertically (1 per row) next to XY pad
    pattern_buttons_per_row = 1
    pattern_frame_width = (BUTTON_SIZE + GROUP_PADDING * 2) if pattern_buttons else 0
    pattern_frame_height = len(pattern_buttons) * (BUTTON_SIZE + 5) + FRAME_HEADER_HEIGHT + GROUP_PADDING if pattern_buttons else 0

    # XY pad section includes pattern buttons to its right
    xypad_and_patterns_width = (XYPAD_SIZE + 10 + pattern_frame_width) if has_xypad else pattern_frame_width

    # Color buttons placed to the RIGHT (side-by-side), 5 per row = 2 rows for 10 colors
    color_buttons_per_row = 5
    num_color_rows = (len(color_buttons) + color_buttons_per_row - 1) // color_buttons_per_row if color_buttons else 0
    color_buttons_in_widest = min(len(color_buttons), color_buttons_per_row) if color_buttons else 0
    color_frame_width = color_buttons_in_widest * (BUTTON_SIZE + 5) + GROUP_PADDING * 2 if color_buttons else 0
    color_frame_height = num_color_rows * (BUTTON_SIZE + 5) + FRAME_HEADER_HEIGHT + GROUP_PADDING * 2 if color_buttons else 0

    # All sections in one horizontal row: sliders | XY pad | patterns | colors
    controls_width = slider_section_width + xypad_and_patterns_width
    if color_buttons:
        controls_width += color_frame_width + 10  # 10px gap before color frame

    # Total frame dimensions
    frame_width = max(150, controls_width + GROUP_PADDING * 2)

    # For groups with color buttons, match slider height to color frame height
    # This makes the frame more compact (wider, not taller)
    effective_slider_height = SLIDER_HEIGHT
    if color_buttons and color_frame_height > 0:
        effective_slider_height = color_frame_height

    # Height = max of all sections (everything in one row)
    section_heights = []
    if num_sliders > 0:
        section_heights.append(effective_slider_height)
    if has_xypad:
        section_heights.append(xypad_height)
    if pattern_buttons:
        section_heights.append(pattern_frame_height)
    if color_buttons:
        section_heights.append(color_frame_height)
    controls_height = max(section_heights) if section_heights else 0

    frame_height = FRAME_HEADER_HEIGHT + GROUP_PADDING + controls_height + GROUP_PADDING

    # Create main frame for this group
    frame = create_vc_frame(
        parent, widget_id_counter, group_name,
        x_offset, y_offset, frame_width, frame_height,
        bg_color=frame_bg_color,
        fg_color=frame_fg_color
    )
    widget_id_counter += 1

    # Current position within frame
    current_x = GROUP_PADDING
    current_y = FRAME_HEADER_HEIGHT + GROUP_PADDING

    # Create sliders (use effective_slider_height to match color frame when present)
    if dimmer_channels:
        create_vc_slider(
            frame, widget_id_counter, "Dimmer",
            current_x, current_y, SLIDER_WIDTH, effective_slider_height,
            "Level", dimmer_channels, None, slider_bg_color
        )
        widget_id_counter += 1
        current_x += SLIDER_WIDTH + 5

    if has_rgb:
        if red_channels:
            create_vc_slider(
                frame, widget_id_counter, "Red",
                current_x, current_y, SLIDER_WIDTH, effective_slider_height,
                "Level", red_channels, None, slider_bg_color
            )
            widget_id_counter += 1
            current_x += SLIDER_WIDTH + 5

        if green_channels:
            create_vc_slider(
                frame, widget_id_counter, "Green",
                current_x, current_y, SLIDER_WIDTH, effective_slider_height,
                "Level", green_channels, None, slider_bg_color
            )
            widget_id_counter += 1
            current_x += SLIDER_WIDTH + 5

        if blue_channels:
            create_vc_slider(
                frame, widget_id_counter, "Blue",
                current_x, current_y, SLIDER_WIDTH, effective_slider_height,
                "Level", blue_channels, None, slider_bg_color
            )
            widget_id_counter += 1
            current_x += SLIDER_WIDTH + 5

        if white_channels:
            create_vc_slider(
                frame, widget_id_counter, "White",
                current_x, current_y, SLIDER_WIDTH, effective_slider_height,
                "Level", white_channels, None, slider_bg_color
            )
            widget_id_counter += 1
            current_x += SLIDER_WIDTH + 5

    if capabilities.has_special:
        if focus_channels:
            create_vc_slider(
                frame, widget_id_counter, "Focus",
                current_x, current_y, SLIDER_WIDTH, effective_slider_height,
                "Level", focus_channels, None, slider_bg_color
            )
            widget_id_counter += 1
            current_x += SLIDER_WIDTH + 5

        if zoom_channels:
            create_vc_slider(
                frame, widget_id_counter, "Zoom",
                current_x, current_y, SLIDER_WIDTH, effective_slider_height,
                "Level", zoom_channels, None, slider_bg_color
            )
            widget_id_counter += 1
            current_x += SLIDER_WIDTH + 5

    # Create XY Pad for movement (with position presets only)
    if pan_tilt_fixtures:
        # Collect Position presets for the XY Pad (no patterns)
        position_presets = []

        if preset_functions:
            for key, func_id in preset_functions.items():
                if key.startswith("Position_"):
                    # Extract position name and add as position preset
                    position_name = key.split("_", 1)[1]
                    position_presets.append((f"{group_name} - {position_name}", func_id))

        # Get first fixture for position calculations
        first_fixture = group.fixtures[0] if group.fixtures else None

        create_vc_xypad(
            frame, widget_id_counter, "XY Pad",
            current_x, current_y, XYPAD_SIZE, xypad_height,
            pan_tilt_fixtures,
            efx_presets=None,  # No patterns in XY pad
            position_presets=position_presets,
            bg_color=slider_bg_color,
            fixture_obj=first_fixture
        )
        widget_id_counter += 1
        current_x += XYPAD_SIZE + 5

        # Pattern buttons frame - stacked vertically next to XY pad
        if pattern_buttons:
            _, widget_id_counter, _, _ = _create_button_frame(
                frame, widget_id_counter, "Patterns",
                pattern_buttons, current_x, current_y, pattern_buttons_per_row, frame_fg_color, frame_bg_color
            )
            current_x += pattern_frame_width + 10

    # Colors frame - placed to the RIGHT of sliders/xypad/patterns (side-by-side layout)
    if color_buttons:
        _, widget_id_counter, _, h = _create_button_frame(
            frame, widget_id_counter, "Colors",
            color_buttons, current_x, current_y, color_buttons_per_row, frame_fg_color, frame_bg_color,
            solo=True
        )

    return frame, widget_id_counter, frame_width


def build_virtual_console(
    root: ET.Element,
    engine: ET.Element,
    config: Configuration,
    fixture_id_map: Dict[int, int],
    fixture_definitions: Dict[str, Any],
    capabilities_map: Dict[str, FixtureGroupCapabilities],
    options: Dict[str, bool],
    show_function_ids: Dict[str, int] = None,
    preset_function_map: Dict[str, Dict[str, int]] = None,
    master_presets: Dict[str, int] = None,
    widget_id_start: int = 0
) -> int:
    """Build the complete Virtual Console section.

    Args:
        root: Workspace root element
        engine: Engine element
        config: Configuration object
        fixture_id_map: Fixture ID mapping
        fixture_definitions: Fixture definitions
        capabilities_map: Dict mapping group names to capabilities
        options: Export options dict
        show_function_ids: Dict mapping show names to function IDs
        preset_function_map: Dict of preset function IDs by group
        master_presets: Flat dict {preset_key: func_id} with Scene_/Color_/Effect_/Movement_ prefixes
        widget_id_start: Starting widget ID

    Returns:
        Next available widget ID
    """
    widget_id = widget_id_start

    # Create VirtualConsole element
    vc = ET.SubElement(root, "VirtualConsole")

    # Main frame
    main_frame = ET.SubElement(vc, "Frame")
    main_frame.set("Caption", "")

    # Set appearance (dark mode if requested)
    bg_color = VC_BLACK_BACKGROUND if options.get('dark_mode') else "Default"
    fg_color = VC_WHITE_FOREGROUND if options.get('dark_mode') else "Default"
    frame_bg_color = VC_DARK_GREY_BACKGROUND if options.get('dark_mode') else "Default"  # For sub-frames
    create_appearance(main_frame, "None", fg_color, bg_color)

    # Constants for Virtual Console usable area (QLC+ has UI elements around edges)
    SCREEN_WIDTH = 1805
    SCREEN_HEIGHT = 995
    MARGIN = 10

    current_y = MARGIN

    # Shows section (SoloFrame at top with margins) — uses larger buttons
    if options.get('show_buttons') and show_function_ids:
        num_shows = len(show_function_ids)
        available_width = SCREEN_WIDTH - (2 * MARGIN)
        buttons_per_row = max(1, (available_width - GROUP_PADDING * 2) // (SHOW_BUTTON_SIZE + BUTTON_SPACING))

        num_rows = (num_shows + buttons_per_row - 1) // buttons_per_row
        solo_frame_height = (SHOW_BUTTON_SIZE + BUTTON_SPACING) * num_rows + FRAME_HEADER_HEIGHT + GROUP_PADDING * 2
        solo_frame_width = available_width

        solo_frame = create_vc_solo_frame(
            main_frame, widget_id, "Shows",
            MARGIN, current_y, solo_frame_width, solo_frame_height,
            fg_color, frame_bg_color
        )
        widget_id += 1

        btn_x = GROUP_PADDING
        btn_y = FRAME_HEADER_HEIGHT + GROUP_PADDING
        btn_count = 0

        for show_name, func_id in show_function_ids.items():
            button = create_vc_button(
                solo_frame, widget_id, show_name, func_id,
                btn_x, btn_y, SHOW_BUTTON_SIZE, SHOW_BUTTON_SIZE, "Toggle", "Default",
                VC_BLACK_FOREGROUND, "Arial,14,-1,5,75,0,0,0,0,0,Bold"
            )

            # Add MIDI trigger input if configured for this show
            show = config.songs.get(show_name)
            if show and show.trigger_device and show.trigger_channel >= 0:
                # Find the universe ID for this trigger device
                for midi_dev in getattr(config, 'midi_input_devices', []):
                    if midi_dev.name == show.trigger_device:
                        trigger_input = ET.SubElement(button, "Input")
                        trigger_input.set("Universe", str(midi_dev.universe_id))
                        trigger_input.set("Channel", str(show.trigger_channel - 1))
                        # TODO: make LowerValue/UpperValue/UpperParams configurable
                        trigger_input.set("LowerValue", "1")
                        trigger_input.set("UpperValue", "26")
                        trigger_input.set("UpperParams", "6")
                        break

            widget_id += 1
            btn_count += 1
            btn_x += SHOW_BUTTON_SIZE + BUTTON_SPACING

            if btn_count % buttons_per_row == 0:
                btn_x = GROUP_PADDING
                btn_y += SHOW_BUTTON_SIZE + BUTTON_SPACING

        current_y += solo_frame_height + SECTION_SPACING

    # --- Compute right column width before laying out groups ---
    GROUP_MASTER_SLIDER_HEIGHT = 150
    INNER_SPACING = 5  # Spacing between sub-sections inside MC frame

    has_speed_dial = options.get('speed_dial', False)

    # Preset button styling (display name, ARGB background)
    preset_color_map = {
        "Scene_Warm_White": ("Warm Wh", "4294945536"),
        "Scene_Cool_Blue": ("Cool Bl", "4278200063"),
        "Scene_Sunset": ("Sunset", "4294932480"),
        "Scene_Deep_Night": ("Night", "4278452479"),
        "Scene_Fire": ("Fire", "4294901760"),
        "Scene_Blue_Amber": ("Bl/Amb", "4278255615"),
        "Scene_Forest": ("Forest", "4278240512"),
        "Scene_Rainbow": ("Rainbow", "4294967295"),
        "Color_Red": ("Red", "4294901760"),
        "Color_Blue": ("Blue", "4278190335"),
        "Color_Green": ("Green", "4278255360"),
        "Color_White": ("White", "4294967295"),
        "Color_Amber": ("Amber", "4294945536"),
        "Effect_Strobe": ("Strobe", "4294967295"),
        "Effect_Random_Strobe": ("Rnd Strb", "4294961120"),
        "Effect_Twinkle": ("Twinkle", "4294957568"),
        "Effect_Starfall": ("Starfall", "4278255615"),
        "Effect_Ping_Pong": ("PngPng", "4294902015"),
        "Effect_Party": ("Party", "4294967040"),
        "Effect_Pulse": ("Pulse", "4278255360"),
        "Effect_Sparkle": ("Sparkle", "4294967295"),
    }

    # Categorize presets by section
    scene_buttons = []
    color_buttons_master = []
    effect_buttons = []

    if master_presets:
        for key, func_id in master_presets.items():
            display_name, bg_val = preset_color_map.get(key, (key.split("_", 1)[-1], "Default"))
            entry = (display_name, func_id, bg_val)
            if key.startswith("Scene_"):
                scene_buttons.append(entry)
            elif key.startswith("Color_"):
                color_buttons_master.append(entry)
            elif key.startswith("Effect_"):
                effect_buttons.append(entry)

    # --- Calculate Master Control frame dimensions ---
    # Each button row: all buttons in one horizontal row
    def _row_frame_width(buttons):
        if not buttons:
            return 0
        return len(buttons) * (BUTTON_SIZE + 5) + GROUP_PADDING * 2

    def _row_frame_height():
        return (BUTTON_SIZE + 5) + FRAME_HEADER_HEIGHT + GROUP_PADDING * 2

    # Group masters width (sliders in a row)
    num_group_sliders = len(config.groups) if config.groups else 0
    gm_slider_row_width = num_group_sliders * (SLIDER_WIDTH + 5) if num_group_sliders > 0 else 0

    # Button row widths
    scene_row_w = _row_frame_width(scene_buttons)
    color_row_w = _row_frame_width(color_buttons_master)
    effect_row_w = _row_frame_width(effect_buttons)
    row_h = _row_frame_height() if any([scene_buttons, color_buttons_master, effect_buttons]) else 0

    # Master frame width = max of all content rows + padding
    master_inner_width = max(gm_slider_row_width, scene_row_w, color_row_w, effect_row_w)
    right_column_width = master_inner_width + GROUP_PADDING * 2 if master_inner_width > 0 else 0

    # Ensure minimum width for speed dial (placed below master frame)
    if has_speed_dial:
        right_column_width = max(right_column_width, SPEED_DIAL_WIDTH + GROUP_PADDING * 2)

    # Left column available width for group controls
    if right_column_width > 0:
        left_column_width = SCREEN_WIDTH - right_column_width - SECTION_SPACING - 2 * MARGIN
    else:
        left_column_width = SCREEN_WIDTH - 2 * MARGIN

    groups_start_y = current_y  # Remember where group controls start

    # Group controls section - grid layout in left column
    if options.get('group_controls'):
        group_frames = []

        for group_name, group in config.groups.items():
            if not group.fixtures:
                continue

            capabilities = capabilities_map.get(group_name, FixtureGroupCapabilities())

            if not any([capabilities.has_dimmer, capabilities.has_colour,
                       capabilities.has_movement, capabilities.has_special]):
                continue

            group_presets = preset_function_map.get(group_name, {}) if preset_function_map else {}

            frame, new_widget_id, frame_width = generate_group_controls(
                main_frame, group_name, group, capabilities,
                fixture_id_map, fixture_definitions, widget_id,
                0, 0, group_presets,
                options.get('dark_mode', False)
            )

            frame_height = 0
            for child in frame:
                if child.tag == "WindowState":
                    frame_height = int(child.get("Height", 0))
                    break

            group_frames.append((frame, frame_width, frame_height, new_widget_id))
            widget_id = new_widget_id

        # Pack group frames into rows using first-fit decreasing bin packing,
        # fitting narrow frames alongside wide ones. Packing is constrained to
        # the LEFT column only: the right column (Master frame + SpeedDial) is
        # reserved at x >= right_column_x, and left_column_width already leaves
        # a SECTION_SPACING gap before it, so frames packed here can never
        # intrude into that band.
        #
        # Note: there is intentionally no full-screen-width re-pack on vertical
        # overflow. Such a re-pack only ever changes the layout when a right
        # column is reserved (otherwise left_column_width == full width already)
        # -- and in exactly that case it drove group frames into the Master
        # frame / SpeedDial, producing overlapping widgets. If the packed rows
        # are taller than the screen, that's fine: QLC+ scrolls the VC canvas
        # and Properties/Size below is computed from the real content bounds.
        rows = []  # [[(frame, width, height), ...], ...]
        remaining = list(group_frames)

        # Sort widest first for better packing
        remaining.sort(key=lambda f: f[1], reverse=True)

        while remaining:
            row = [remaining.pop(0)]
            row_used_width = row[0][1]

            i = 0
            while i < len(remaining):
                f = remaining[i]
                if row_used_width + SECTION_SPACING + f[1] <= left_column_width:
                    row.append(f)
                    row_used_width += SECTION_SPACING + f[1]
                    remaining.pop(i)
                else:
                    i += 1

            rows.append(row)

        # Place rows
        group_y = current_y
        for row in rows:
            row_height = max(f[2] for f in row)
            group_x = MARGIN

            for frame, frame_width, frame_height, _ in row:
                for child in frame:
                    if child.tag == "WindowState":
                        child.set("X", str(group_x))
                        child.set("Y", str(group_y))
                        break
                group_x += frame_width + SECTION_SPACING

            group_y += row_height + SECTION_SPACING

        current_y = group_y

    # --- Right column: single "Master" frame, same pattern as group frames ---
    # Group frames work: Frame with sliders + SoloFrame children (no nesting of Frame inside Frame)
    # Master frame replicates this: group master sliders + Scenes/Colors/Effects SoloFrames
    right_column_x = SCREEN_WIDTH - right_column_width - MARGIN
    right_column_y = groups_start_y

    if master_presets or has_speed_dial or num_group_sliders > 0:
        available_height = SCREEN_HEIGHT - right_column_y - MARGIN

        # Collect preset sections
        preset_sections = []
        if scene_buttons:
            preset_sections.append(("Scenes", scene_buttons, True))
        if color_buttons_master:
            preset_sections.append(("Colors", color_buttons_master, False))
        if effect_buttons:
            preset_sections.append(("Effects", effect_buttons, True))

        # Calculate master frame height: sliders on top, button rows below
        actual_gm_slider_height = GROUP_MASTER_SLIDER_HEIGHT
        slider_row_height = actual_gm_slider_height if num_group_sliders > 0 else 0

        button_section_heights = []
        for title, buttons, solo in preset_sections:
            h = (BUTTON_SIZE + 5) + FRAME_HEADER_HEIGHT + GROUP_PADDING * 2
            button_section_heights.append(h)

        button_total = sum(button_section_heights) + max(0, len(button_section_heights) - 1) * INNER_SPACING
        gap_after_sliders = INNER_SPACING if slider_row_height > 0 and button_total > 0 else 0

        master_frame_h = (FRAME_HEADER_HEIGHT + GROUP_PADDING
                         + slider_row_height + gap_after_sliders
                         + button_total
                         + GROUP_PADDING)

        # Overflow prevention: shrink slider height if needed
        if master_frame_h > available_height and slider_row_height > 0:
            overflow = master_frame_h - available_height
            actual_gm_slider_height = max(80, GROUP_MASTER_SLIDER_HEIGHT - overflow)
            slider_row_height = actual_gm_slider_height
            master_frame_h = (FRAME_HEADER_HEIGHT + GROUP_PADDING
                             + slider_row_height + gap_after_sliders
                             + button_total
                             + GROUP_PADDING)

        master_frame_h = min(master_frame_h, available_height)

        # Calculate width: max of slider row and widest button row
        slider_row_width = num_group_sliders * (SLIDER_WIDTH + 5) if num_group_sliders > 0 else 0
        max_button_row_width = 0
        for title, buttons, solo in preset_sections:
            w = len(buttons) * (BUTTON_SIZE + 5) + GROUP_PADDING * 2
            max_button_row_width = max(max_button_row_width, w)
        master_frame_w = max(slider_row_width, max_button_row_width) + GROUP_PADDING * 2

        # Create the master frame — same as create_vc_frame used by group controls
        master_frame = create_vc_frame(
            main_frame, widget_id, "Master",
            right_column_x, right_column_y, master_frame_w, master_frame_h,
            bg_color=frame_bg_color, fg_color=fg_color
        )
        widget_id += 1

        current_inner_x = GROUP_PADDING
        current_inner_y = FRAME_HEADER_HEIGHT + GROUP_PADDING

        # --- Group master sliders directly in the frame (like Dimmer/R/G/B in group frames) ---
        for group_name, group in config.groups.items():
            group_dimmer_channels = []
            for fixture in group.fixtures:
                fixture_id = fixture_id_map.get((fixture.universe, fixture.address))
                if fixture_id is None:
                    continue
                channels_dict, _ = get_fixture_channels_for_preset(
                    fixture, fixture_definitions, list(DIMMER_PRESETS)
                )
                for ch in channels_dict.get("IntensityMasterDimmer", []):
                    group_dimmer_channels.append((fixture_id, ch))
                for ch in channels_dict.get("IntensityDimmer", []):
                    group_dimmer_channels.append((fixture_id, ch))

            if group_dimmer_channels:
                create_vc_slider(
                    master_frame, widget_id, group_name,
                    current_inner_x, current_inner_y, SLIDER_WIDTH, actual_gm_slider_height,
                    "Submaster", group_dimmer_channels, None,
                    VC_DARK_GREY_BACKGROUND if options.get('dark_mode') else "Default"
                )
                widget_id += 1
                current_inner_x += SLIDER_WIDTH + 5

        # Move Y below sliders
        if slider_row_height > 0:
            current_inner_y += slider_row_height + INNER_SPACING

        # --- Scenes, Colors, Effects SoloFrames (like Colors SoloFrame in group frames) ---
        for title, buttons, solo in preset_sections:
            _, widget_id, _, sub_h = _create_button_frame(
                master_frame, widget_id, title,
                buttons, GROUP_PADDING, current_inner_y, len(buttons),
                fg_color, frame_bg_color, solo=solo
            )
            current_inner_y += sub_h + INNER_SPACING

        right_column_y += master_frame_h + INNER_SPACING

    # --- Speed Dial (separate, below master frame) ---
    if has_speed_dial:
        all_show_ids = list(show_function_ids.values()) if show_function_ids else []
        master_chase_efx_ids = []
        if master_presets:
            for key, func_id in master_presets.items():
                if key.startswith("Effect_"):
                    master_chase_efx_ids.append(func_id)
        all_speed_dial_ids = all_show_ids + master_chase_efx_ids

        speed_dial_bg = VC_DARK_GREY_BACKGROUND if options.get('dark_mode') else "Default"
        speed_dial_fg = VC_WHITE_FOREGROUND if options.get('dark_mode') else "Default"

        create_vc_speed_dial(
            main_frame, widget_id, "Tap BPM",
            right_column_x, right_column_y, SPEED_DIAL_WIDTH, SPEED_DIAL_HEIGHT,
            all_speed_dial_ids if all_speed_dial_ids else None,
            speed_dial_bg, speed_dial_fg
        )
        widget_id += 1
        right_column_y += SPEED_DIAL_HEIGHT + INNER_SPACING

    # Track right column bottom for dynamic sizing
    right_column_bottom = right_column_y

    # Dynamic Properties Size - compute from actual content bounds, clamped to 1920x1080
    content_width = SCREEN_WIDTH + MARGIN
    if right_column_width > 0:
        content_width = right_column_x + right_column_width + MARGIN
    content_height = max(current_y, right_column_bottom) + MARGIN

    props_width = min(1920, max(800, content_width))
    props_height = min(1080, max(600, content_height))

    # Properties
    properties = ET.SubElement(vc, "Properties")
    size = ET.SubElement(properties, "Size")
    size.set("Width", str(props_width))
    size.set("Height", str(props_height))

    grand_master = ET.SubElement(properties, "GrandMaster")
    grand_master.set("ChannelMode", "Intensity")
    grand_master.set("ValueMode", "Reduce")
    grand_master.set("SliderMode", "Normal")

    return widget_id
