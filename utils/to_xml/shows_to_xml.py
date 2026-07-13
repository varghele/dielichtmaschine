import os
import xml.etree.ElementTree as ET
from config.models import Configuration
from utils.to_xml.step_compaction import compact_step_values
from effects.timing import movement_total_cycles


def add_steps_to_sequence(sequence, steps):
    """Adds steps to a sequence"""
    for step in steps:
        sequence.append(step)

def calculate_start_time(previous_time, signature, bpm, num_bars, transition, previous_bpm=None):
    """
    Calculate the start time in milliseconds with normalized beat calculations
    Parameters:
        previous_time: Previous start time in milliseconds
        signature: Time signature as string (e.g. "4/4")
        bpm: Target BPM for this section
        num_bars: Number of bars
        transition: Type of transition ("instant" or "gradual")
        previous_bpm: BPM of the previous section (needed for gradual transition)
    Returns:
        int: New start time in milliseconds
    """
    numerator, denominator = map(int, signature.split('/'))
    # Normalize to quarter notes for consistent calculation
    beats_per_bar = (numerator * 4) / denominator

    if transition == "instant" or previous_bpm is None:
        milliseconds_per_bar = (60000 / bpm) * beats_per_bar
        return previous_time + int(milliseconds_per_bar * int(num_bars))

    elif transition == "gradual":
        total_time = 0
        for bar in range(int(num_bars)):
            # Using a slightly curved interpolation instead of linear
            progress = (bar / int(num_bars)) ** 0.52  # Adding slight curve to the transition
            current_bpm = previous_bpm + (bpm - previous_bpm) * progress
            milliseconds_per_bar = (60000 / current_bpm) * beats_per_bar
            total_time += milliseconds_per_bar

        return previous_time + int(total_time)

    else:
        raise ValueError(f"Unknown transition type: {transition}")


def calculate_step_timing(signature, start_bpm, end_bpm, num_bars, speed="1", transition="gradual"):
    """
    Calculate step timings and count based on BPM transition
    Parameters:
        signature: Time signature as string (e.g. "4/4")
        start_bpm: Starting BPM
        end_bpm: Target BPM
        num_bars: Number of bars
        speed: Speed multiplier ("1/4", "1/2", "1", "2", "4" etc)
        transition: Type of transition ("instant" or "gradual")
    Returns:
        tuple: (step_timings, total_steps)
            step_timings: List of step durations in milliseconds
            total_steps: Total number of steps needed
    """
    # Convert speed fraction to float
    if isinstance(speed, str) and '/' in speed:
        num, denom = map(int, speed.split('/'))
        speed_multiplier = num / denom
    else:
        speed_multiplier = float(speed)

    # Make sure num_bars is integer
    num_bars = int(num_bars)
    try:
        start_bpm = float(start_bpm)
    except TypeError:
        # Start_bpm can be None Type object
        pass
    end_bpm = float(end_bpm)

    numerator, denominator = map(int, signature.split('/'))
    beats_per_bar = (numerator * 4) / denominator
    total_beats = num_bars * beats_per_bar
    steps_per_beat = speed_multiplier
    total_steps = int(total_beats * steps_per_beat)

    step_timings = []

    if transition == "instant" or start_bpm == end_bpm or start_bpm is None:
        ms_per_beat = 60000 / end_bpm
        ms_per_step = ms_per_beat / steps_per_beat
        step_timings = [ms_per_step] * total_steps


    elif transition == "gradual":
        for bar in range(num_bars):
            # Calculate current and next bar's BPM
            current_progress = (bar / num_bars) ** 0.52
            current_bpm = start_bpm + (end_bpm - start_bpm) * current_progress

            next_progress = ((bar + 1) / num_bars) ** 0.52
            next_bpm = start_bpm + (end_bpm - start_bpm) * next_progress if bar < num_bars - 1 else end_bpm

            # Calculate total time for this bar
            milliseconds_per_bar = (60000 / current_bpm) * beats_per_bar
            steps_in_bar = int(beats_per_bar * steps_per_beat)

            # Calculate step timings with linear decrease
            total_time = 0
            bar_steps = []

            for step in range(steps_in_bar):
                step_progress = step / (steps_in_bar - 1) if steps_in_bar > 1 else 0
                step_bpm = current_bpm + (next_bpm - current_bpm) * step_progress
                ms_per_step = (60000 / step_bpm) / steps_per_beat
                bar_steps.append(ms_per_step)
                total_time += ms_per_step

            # Normalize step timings to fit milliseconds_per_bar
            scaling_factor = milliseconds_per_bar / total_time
            normalized_steps = [step * scaling_factor for step in bar_steps]
            step_timings.extend(normalized_steps)


    else:
        raise ValueError(f"Unknown transition type: {transition}")

    return [int(timing) for timing in step_timings], total_steps


def create_sequence(root, sequence_id, sequence_name, bound_scene_id, bpm=120):
    """
    Creates a Sequence function element
    Parameters:
        root: The root XML element to add the sequence to
        sequence_id: ID of the sequence
        sequence_name: Name of the sequence
        bound_scene_id: ID of the bound scene
        bpm: Beats per minute for timing
    Returns:
        Element: The created sequence element
    """
    sequence = ET.SubElement(root, "Function")
    sequence.set("ID", str(sequence_id))
    sequence.set("Type", "Sequence")
    sequence.set("Name", sequence_name)
    sequence.set("BoundScene", str(bound_scene_id))

    # Calculate default timing based on BPM
    ms_per_beat = 60000 / float(bpm)

    speed = ET.SubElement(sequence, "Speed")
    speed.set("FadeIn", str(int(ms_per_beat * 0.1)))  # 10% of beat time
    speed.set("FadeOut", "0")
    speed.set("Duration", str(int(ms_per_beat)))

    direction = ET.SubElement(sequence, "Direction")
    direction.text = "Forward"

    run_order = ET.SubElement(sequence, "RunOrder")
    run_order.text = "SingleShot"

    speed_modes = ET.SubElement(sequence, "SpeedModes")
    speed_modes.set("FadeIn", "PerStep")
    speed_modes.set("FadeOut", "PerStep")
    speed_modes.set("Duration", "PerStep")

    return sequence


def _convert_dimmer_steps_to_rgb(steps, dimmer_block, colour_blocks, fixture_def, mode_name, fixture_num, fixture_start_id,
                                  fixture_conf=None, fixture_id_map=None):
    """
    Convert dimmer intensity steps to RGB channel steps for fixtures without dimmer capability.

    Args:
        steps: List of Step XML elements with dimmer intensity values
        dimmer_block: The DimmerBlock being processed
        colour_blocks: List of ColourBlocks from the same light block
        fixture_def: Fixture definition dictionary
        mode_name: Current fixture mode name
        fixture_num: Number of fixtures in group
        fixture_start_id: Starting fixture ID (legacy, used if fixture_id_map not provided)
        fixture_conf: List of fixture objects (used with fixture_id_map)
        fixture_id_map: Dict mapping (universe, address) to fixture IDs

    Returns:
        List of Step XML elements with RGB channel values
    """
    from utils.effects_utils import get_channels_by_property

    # Get RGB channels from fixture definition (try different preset names)
    channels_dict = get_channels_by_property(fixture_def, mode_name, ["IntensityRed", "IntensityGreen", "IntensityBlue"])

    if not channels_dict:
        print("Warning: No RGB channels found for fixture without dimmer")
        return steps

    # Verify we have all three RGB channels
    if 'IntensityRed' not in channels_dict or 'IntensityGreen' not in channels_dict or 'IntensityBlue' not in channels_dict:
        print(f"Warning: Missing some RGB channels. Found: {list(channels_dict.keys())}")
        return steps

    # Helper function to find overlapping colour block at a given time
    def get_rgb_at_time(time_seconds):
        """Get RGB values from overlapping colour block, or (0,0,0) if none."""
        for colour_block in colour_blocks:
            if colour_block.start_time <= time_seconds <= colour_block.end_time:
                # Found overlapping colour block
                r = getattr(colour_block, 'red', 0)
                g = getattr(colour_block, 'green', 0)
                b = getattr(colour_block, 'blue', 0)
                return (int(r), int(g), int(b))
        # No overlapping colour block
        return (0, 0, 0)

    # Convert each step
    converted_steps = []
    cumulative_time = 0

    for step in steps:
        # Calculate time of this step (in seconds)
        fade_in = int(step.get("FadeIn", 0))
        hold = int(step.get("Hold", 0))
        step_time = dimmer_block.start_time + (cumulative_time / 1000.0)
        cumulative_time += fade_in + hold

        # Parse intensity values from step
        step_text = step.text if step.text else ""
        # Format: "fixture_id:channel,value:fixture_id:channel,value..."

        # Parse to get intensity for each fixture
        fixture_intensities = {}
        if step_text:
            fixture_parts = step_text.split(':')
            for i in range(0, len(fixture_parts), 2):
                if i + 1 < len(fixture_parts):
                    fixture_id = int(fixture_parts[i])
                    channel_value_pairs = fixture_parts[i + 1].split(',')
                    if len(channel_value_pairs) >= 2:
                        intensity = int(channel_value_pairs[1])
                        fixture_intensities[fixture_id] = intensity

        # Get RGB values at this time
        base_rgb = get_rgb_at_time(step_time)

        # Create new step with RGB values
        new_step = ET.Element("Step")
        new_step.set("Number", step.get("Number"))
        new_step.set("FadeIn", step.get("FadeIn"))
        new_step.set("Hold", step.get("Hold"))
        new_step.set("FadeOut", step.get("FadeOut"))

        # Build RGB values for all fixtures
        values = []
        total_values = 0

        for i in range(fixture_num):
            # Look up actual fixture ID from map, or fall back to offset calculation
            if fixture_id_map and fixture_conf and i < len(fixture_conf):
                fixture = fixture_conf[i]
                fixture_id = fixture_id_map[(fixture.universe, fixture.address)]
            else:
                fixture_id = fixture_start_id + i
            intensity = fixture_intensities.get(fixture_id, 0)

            # Apply RGB values to ALL channel sets (e.g., all 10 segments)
            num_rgb_sets = len(channels_dict['IntensityRed'])
            channel_value_pairs = []

            for seg_idx in range(num_rgb_sets):
                # Determine per-segment intensity based on effect type
                seg_intensity = intensity

                if dimmer_block.effect_type == "sparkle":
                    # Sparkle: Each segment independently randomized
                    # Use step number and segment index as seed for pseudo-random variation
                    import random
                    random.seed(int(step.get("Number")) * 1000 + seg_idx + fixture_id)
                    seg_intensity = random.randint(0, 255)

                elif dimmer_block.effect_type in ["ping_pong", "random_stroke", "chase", "waterfall"]:
                    # Wave pattern: offset intensity based on segment index
                    # Create a wave that moves across segments
                    step_num = int(step.get("Number"))
                    wave_position = (step_num + seg_idx) % num_rgb_sets
                    wave_intensity = abs((wave_position - num_rgb_sets / 2) / (num_rgb_sets / 2))
                    seg_intensity = int(intensity * (1.0 - wave_intensity))

                # For static/strobe: use base intensity (uniform across segments)

                # Scale RGB by segment intensity
                intensity_ratio = seg_intensity / 255.0
                scaled_r = int(base_rgb[0] * intensity_ratio)
                scaled_g = int(base_rgb[1] * intensity_ratio)
                scaled_b = int(base_rgb[2] * intensity_ratio)

                r_ch = channels_dict['IntensityRed'][seg_idx]['channel']
                g_ch = channels_dict['IntensityGreen'][seg_idx]['channel']
                b_ch = channels_dict['IntensityBlue'][seg_idx]['channel']
                channel_value_pairs.extend([f"{r_ch},{scaled_r}", f"{g_ch},{scaled_g}", f"{b_ch},{scaled_b}"])

            channel_values = ",".join(channel_value_pairs)
            total_values += num_rgb_sets * 3

            values.append(f"{fixture_id}:{channel_values}")

        # Drop zero-valued channels (QLC+ saver convention, ~30% smaller .qxw).
        compacted_values, nonzero_count = compact_step_values(values)
        new_step.set("Values", str(nonzero_count))
        new_step.text = ":".join(compacted_values)
        converted_steps.append(new_step)

    return converted_steps


def _map_rgb_to_color_wheel(r, g, b):
    """
    Map RGB color to closest color wheel position.
    Returns DMX value (0-255) for the color wheel channel.

    Common color wheel mapping (approximate):
    - White/Open: 0-10
    - Red: 11-21
    - Orange: 22-32
    - Yellow: 33-53
    - Green: 54-74
    - Cyan/Light Blue: 75-95
    - Blue: 96-116
    - Magenta/Purple: 117-137
    - Pink: 138-158
    """
    # Define common colors on a typical color wheel with their RGB values
    wheel_colors = [
        (255, 255, 255, 5),    # White
        (255, 0, 0, 16),       # Red
        (255, 127, 0, 27),     # Orange
        (255, 255, 0, 43),     # Yellow
        (0, 255, 0, 64),       # Green
        (0, 255, 255, 85),     # Cyan
        (0, 0, 255, 106),      # Blue
        (255, 0, 255, 127),    # Magenta
        (255, 0, 127, 148),    # Pink
    ]

    # Find closest color by Euclidean distance
    min_distance = float('inf')
    closest_value = 0

    for wr, wg, wb, dmx_value in wheel_colors:
        distance = ((r - wr) ** 2 + (g - wg) ** 2 + (b - wb) ** 2) ** 0.5
        if distance < min_distance:
            min_distance = distance
            closest_value = dmx_value

    return closest_value


def _generate_movement_shape_steps(movement_block, fixture_def, mode_name, fixture_conf,
                                    fixture_start_id, bpm, signature, num_bars,
                                    dimmer_block=None, colour_block=None, special_block=None,
                                    fixture_id_map=None):
    """
    Generate movement shape steps for a movement block.

    Supports static positioning and dynamic shapes (circle, diamond, lissajous, etc.)
    with clipping to boundary limits. Also includes dimmer and color channels if
    overlapping blocks are provided.

    Step density is adaptive based on speed setting with a 24 steps/second cap.

    Parameters:
        movement_block: MovementBlock with effect parameters
        fixture_def: Fixture definition dictionary
        mode_name: Current fixture mode name
        fixture_conf: List of fixture configurations
        fixture_start_id: Starting fixture ID for value assignment
        bpm: Beats per minute
        signature: Time signature (e.g., "4/4")
        num_bars: Number of bars for the effect
        dimmer_block: Optional DimmerBlock to include intensity in steps
        colour_block: Optional ColourBlock to include color in steps
        special_block: Optional SpecialBlock to include gobo, prism, etc. in steps

    Returns:
        List of Step elements for QLC+ sequence
    """
    import math
    from utils.effects_utils import get_channels_by_property

    # Get pan/tilt channels
    channels_dict = get_channels_by_property(fixture_def, mode_name, ["PositionPan", "PositionTilt"])
    if not channels_dict:
        return []

    # Get dimmer channels if dimmer_block is provided
    dimmer_channels = []
    dimmer_value = 255
    dimmer_effect_type = "static"
    dimmer_effect_speed = "1"
    if dimmer_block:
        dimmer_dict = get_channels_by_property(fixture_def, mode_name, ["IntensityMasterDimmer", "IntensityDimmer"])
        if dimmer_dict:
            for prop in ["IntensityMasterDimmer", "IntensityDimmer"]:
                if prop in dimmer_dict:
                    dimmer_channels.extend(dimmer_dict[prop])
                    break
        dimmer_value = int(dimmer_block.intensity)
        dimmer_effect_type = dimmer_block.effect_type
        dimmer_effect_speed = dimmer_block.effect_speed

    # Get color channels if colour_block is provided
    color_channels = {}
    color_wheel_channels = []
    color_wheel_value = 0
    if colour_block:
        # Try RGB/RGBW channels first
        color_dict = get_channels_by_property(fixture_def, mode_name,
            ["IntensityRed", "IntensityGreen", "IntensityBlue", "IntensityWhite",
             "IntensityAmber", "IntensityCyan", "IntensityMagenta", "IntensityYellow"])
        if color_dict:
            color_channels = {
                'red': (color_dict.get('IntensityRed', []), int(colour_block.red)),
                'green': (color_dict.get('IntensityGreen', []), int(colour_block.green)),
                'blue': (color_dict.get('IntensityBlue', []), int(colour_block.blue)),
                'white': (color_dict.get('IntensityWhite', []), int(colour_block.white)),
                'amber': (color_dict.get('IntensityAmber', []), int(colour_block.amber)),
                'cyan': (color_dict.get('IntensityCyan', []), int(colour_block.cyan)),
                'magenta': (color_dict.get('IntensityMagenta', []), int(colour_block.magenta)),
                'yellow': (color_dict.get('IntensityYellow', []), int(colour_block.yellow))
            }
        else:
            # Fallback to color wheel if RGB not available
            wheel_dict = get_channels_by_property(fixture_def, mode_name, ["ColorWheel", "ColorMacro"])
            if wheel_dict:
                for prop in ["ColorWheel", "ColorMacro"]:
                    if prop in wheel_dict:
                        color_wheel_channels.extend(wheel_dict[prop])
                        break
                # Map RGB to closest color wheel position
                # Simple mapping: calculate which wheel position is closest to requested RGB
                r, g, b = int(colour_block.red), int(colour_block.green), int(colour_block.blue)
                color_wheel_value = _map_rgb_to_color_wheel(r, g, b)

    # Get special effect channels if special_block is provided
    special_channels = {}
    if special_block:
        special_dict = get_channels_by_property(fixture_def, mode_name,
            ["GoboWheel", "Gobo", "Gobo1", "Gobo2", "PrismRotation", "Prism",
             "BeamFocusNearFar", "BeamZoomSmallBig", "BeamIrisCloseOpen"])
        if special_dict:
            # Map special block values to channels
            if 'GoboWheel' in special_dict or 'Gobo' in special_dict or 'Gobo1' in special_dict:
                gobo_chs = special_dict.get('GoboWheel', special_dict.get('Gobo', special_dict.get('Gobo1', [])))
                if gobo_chs:
                    # Gobo index mapping (typically each gobo is ~20-30 DMX values apart)
                    gobo_value = min(255, special_block.gobo_index * 25)
                    special_channels['gobo'] = (gobo_chs, gobo_value)

            if 'Prism' in special_dict:
                prism_chs = special_dict['Prism']
                prism_value = 128 if special_block.prism_enabled else 0
                special_channels['prism'] = (prism_chs, prism_value)

            if 'BeamFocusNearFar' in special_dict:
                focus_chs = special_dict['BeamFocusNearFar']
                special_channels['focus'] = (focus_chs, int(special_block.focus))

            if 'BeamZoomSmallBig' in special_dict:
                zoom_chs = special_dict['BeamZoomSmallBig']
                special_channels['zoom'] = (zoom_chs, int(special_block.zoom))

    # Get effect parameters
    effect_type = movement_block.effect_type
    center_pan = movement_block.pan
    center_tilt = movement_block.tilt
    pan_amplitude = movement_block.pan_amplitude
    tilt_amplitude = movement_block.tilt_amplitude
    pan_min = movement_block.pan_min
    pan_max = movement_block.pan_max
    tilt_min = movement_block.tilt_min
    tilt_max = movement_block.tilt_max
    lissajous_ratio = getattr(movement_block, 'lissajous_ratio', '1:2')
    phase_offset_enabled = getattr(movement_block, 'phase_offset_enabled', False)
    phase_offset_degrees = getattr(movement_block, 'phase_offset_degrees', 0.0)
    effect_speed = movement_block.effect_speed

    # Convert speed to multiplier
    if '/' in effect_speed:
        num, denom = map(int, effect_speed.split('/'))
        speed_multiplier = num / denom
    else:
        speed_multiplier = float(effect_speed)

    # Calculate timing
    numerator, denominator = map(int, signature.split('/'))
    beats_per_bar = (numerator * 4) / denominator
    seconds_per_beat = 60.0 / bpm
    seconds_per_bar = beats_per_bar * seconds_per_beat

    # Calculate block duration
    block_duration = movement_block.end_time - movement_block.start_time
    block_duration_ms = int(block_duration * 1000)

    # Shared movement rate (matches ArtNet preview + unified_sequence export).
    total_cycles = movement_total_cycles(block_duration, seconds_per_bar, speed_multiplier)

    # Step density constraints
    MAX_STEPS_PER_SECOND = 24  # Maximum to avoid QLC+ overload and jerky movements
    MIN_STEPS_PER_CYCLE = 8    # Minimum for recognizable shapes
    MAX_TOTAL_STEPS = 256      # Absolute maximum

    # Calculate total steps needed
    # For static, we only need 1 step
    if effect_type == "static":
        total_steps = 1
    else:
        # Determine preferred steps per cycle based on speed
        # Slower movements get more steps for smoothness
        # Faster movements get fewer steps (moving heads can't keep up anyway)
        if speed_multiplier <= 0.5:      # Speed 1/4 or 1/2
            preferred_steps_per_cycle = 64
        elif speed_multiplier <= 2.0:    # Speed 1 or 2
            preferred_steps_per_cycle = 32
        else:                             # Speed 4+
            preferred_steps_per_cycle = 16

        # Calculate desired steps for smooth motion
        desired_steps = int(total_cycles * preferred_steps_per_cycle)

        # Apply time-based cap (24 steps/second maximum)
        max_steps_by_time = int(block_duration * MAX_STEPS_PER_SECOND)
        total_steps = min(desired_steps, max_steps_by_time)

        # Ensure minimum steps per cycle for recognizable shapes
        min_steps = max(1, int(total_cycles * MIN_STEPS_PER_CYCLE))
        total_steps = max(total_steps, min_steps)

        # Apply absolute maximum cap
        total_steps = min(total_steps, MAX_TOTAL_STEPS)

    # Calculate step duration
    if total_steps > 0:
        step_duration_ms = block_duration_ms // total_steps
    else:
        step_duration_ms = block_duration_ms

    # Ensure minimum step duration of 20ms
    if step_duration_ms < 20 and total_steps > 1:
        total_steps = block_duration_ms // 20
        step_duration_ms = block_duration_ms // max(1, total_steps)

    # Parse lissajous ratio
    try:
        ratio_parts = lissajous_ratio.split(':')
        freq_pan = int(ratio_parts[0])
        freq_tilt = int(ratio_parts[1])
    except (ValueError, IndexError):
        freq_pan, freq_tilt = 1, 2

    fixture_num = len(fixture_conf) if fixture_conf else 1
    steps = []

    # Count channels per fixture
    pan_channels = channels_dict.get('PositionPan', [])
    tilt_channels = channels_dict.get('PositionTilt', [])
    channels_per_fixture = len(pan_channels) + len(tilt_channels)

    # Add dimmer channels to count
    channels_per_fixture += len(dimmer_channels)

    # Add color channels to count
    for color_name, (color_chs, _) in color_channels.items():
        channels_per_fixture += len(color_chs)

    # Add color wheel channels to count
    channels_per_fixture += len(color_wheel_channels)

    # Add special effect channels to count
    for special_name, (special_chs, _) in special_channels.items():
        channels_per_fixture += len(special_chs)

    for step_idx in range(total_steps):
        step = ET.Element("Step")
        step.set("Number", str(step_idx))
        step.set("FadeIn", "0")
        step.set("Hold", str(step_duration_ms))
        step.set("FadeOut", "0")
        step.set("Values", str(channels_per_fixture * fixture_num))

        values = []

        for fixture_idx, fixture in enumerate(fixture_conf):
            # Look up actual fixture ID from map, or fall back to offset calculation
            if fixture_id_map:
                fixture_id = fixture_id_map[(fixture.universe, fixture.address)]
            else:
                fixture_id = fixture_start_id + fixture_idx

            # Calculate phase offset for this fixture
            if phase_offset_enabled:
                fixture_phase = (fixture_idx * phase_offset_degrees) * math.pi / 180.0
            else:
                fixture_phase = 0.0

            # Calculate position based on effect type
            # t represents the angle in radians, scaled by total_cycles to trace the shape multiple times
            t = 2 * math.pi * total_cycles * step_idx / max(1, total_steps) + fixture_phase

            if effect_type == "static":
                pan = center_pan
                tilt = center_tilt
            elif effect_type == "circle":
                pan = center_pan + pan_amplitude * math.cos(t)
                tilt = center_tilt + tilt_amplitude * math.sin(t)
            elif effect_type == "diamond":
                # Diamond: 4 corners, scaled by total_cycles for multiple traces
                phase = (step_idx / max(1, total_steps)) * 4 * total_cycles
                corner = int(phase) % 4
                local_t = phase - int(phase)
                corners = [
                    (center_pan, center_tilt - tilt_amplitude),
                    (center_pan + pan_amplitude, center_tilt),
                    (center_pan, center_tilt + tilt_amplitude),
                    (center_pan - pan_amplitude, center_tilt),
                ]
                start = corners[corner]
                end = corners[(corner + 1) % 4]
                pan = start[0] + local_t * (end[0] - start[0])
                tilt = start[1] + local_t * (end[1] - start[1])
            elif effect_type == "square":
                # Square: 4 corners, scaled by total_cycles for multiple traces
                phase = (step_idx / max(1, total_steps)) * 4 * total_cycles
                corner = int(phase) % 4
                local_t = phase - int(phase)
                corners = [
                    (center_pan - pan_amplitude, center_tilt - tilt_amplitude),
                    (center_pan + pan_amplitude, center_tilt - tilt_amplitude),
                    (center_pan + pan_amplitude, center_tilt + tilt_amplitude),
                    (center_pan - pan_amplitude, center_tilt + tilt_amplitude),
                ]
                start = corners[corner]
                end = corners[(corner + 1) % 4]
                pan = start[0] + local_t * (end[0] - start[0])
                tilt = start[1] + local_t * (end[1] - start[1])
            elif effect_type == "triangle":
                # Triangle: 3 corners, scaled by total_cycles for multiple traces
                phase = (step_idx / max(1, total_steps)) * 3 * total_cycles
                corner = int(phase) % 3
                local_t = phase - int(phase)
                corners = [
                    (center_pan, center_tilt - tilt_amplitude),
                    (center_pan + pan_amplitude * 0.866, center_tilt + tilt_amplitude * 0.5),
                    (center_pan - pan_amplitude * 0.866, center_tilt + tilt_amplitude * 0.5),
                ]
                start = corners[corner]
                end = corners[(corner + 1) % 3]
                pan = start[0] + local_t * (end[0] - start[0])
                tilt = start[1] + local_t * (end[1] - start[1])
            elif effect_type == "figure_8":
                pan = center_pan + pan_amplitude * math.sin(t)
                tilt = center_tilt + tilt_amplitude * math.sin(2 * t)
            elif effect_type == "lissajous":
                pan = center_pan + pan_amplitude * math.sin(freq_pan * t)
                tilt = center_tilt + tilt_amplitude * math.sin(freq_tilt * t)
            elif effect_type == "random":
                # Pseudo-random smooth motion using multiple sine waves
                pan = center_pan + pan_amplitude * (
                    0.5 * math.sin(3 * t) + 0.3 * math.sin(7 * t) + 0.2 * math.sin(11 * t)
                )
                tilt = center_tilt + tilt_amplitude * (
                    0.5 * math.sin(5 * t) + 0.3 * math.sin(11 * t) + 0.2 * math.sin(13 * t)
                )
            elif effect_type == "bounce":
                # Bouncing pattern using triangle waves, scaled by total_cycles
                bounce_t = (step_idx / max(1, total_steps)) * 4 * total_cycles
                pan_t = abs((bounce_t % 2) - 1)
                tilt_t = abs(((bounce_t + 0.5) % 2) - 1)
                pan = center_pan - pan_amplitude + 2 * pan_amplitude * pan_t
                tilt = center_tilt - tilt_amplitude + 2 * tilt_amplitude * tilt_t
            else:
                # Default to static
                pan = center_pan
                tilt = center_tilt

            # Apply clipping to boundaries (solver DMX space, like the
            # native renderer's clamp)
            pan = max(pan_min, min(pan_max, pan))
            tilt = max(tilt_min, min(tilt_max, tilt))

            # Convert the finished solver-space step to the fixture's
            # real yoke - the per-step equivalent of the arbiter's
            # hardware pass (identity for fixtures without a resolvable
            # definition, so non-mover exports are untouched).
            from utils.yoke import convert_solver_dmx
            pan, tilt = convert_solver_dmx(fixture, pan, tilt)

            # Build channel values for this fixture
            channel_value_pairs = []

            # Add pan/tilt channels
            for pan_ch in pan_channels:
                channel_value_pairs.append(f"{pan_ch['channel']},{int(pan)}")
            for tilt_ch in tilt_channels:
                channel_value_pairs.append(f"{tilt_ch['channel']},{int(tilt)}")

            # Add dimmer channels with dynamic effects support
            if dimmer_channels:
                # Calculate dimmer value based on effect type
                current_dimmer_value = dimmer_value

                if dimmer_effect_type == "strobe":
                    # Strobe effect: alternate between intensity and 0
                    # Speed controls frequency of alternation
                    speed_multiplier = 1.0
                    if '/' in dimmer_effect_speed:
                        num, denom = map(int, dimmer_effect_speed.split('/'))
                        speed_multiplier = num / denom
                    else:
                        speed_multiplier = float(dimmer_effect_speed)

                    # Calculate strobe period in steps
                    steps_per_cycle = max(2, int(8 / speed_multiplier))  # Slower speed = longer period
                    # Use intensity value: alternate between dimmer_value and 0
                    # 50% duty cycle
                    if (step_idx % steps_per_cycle) < (steps_per_cycle / 2):
                        current_dimmer_value = dimmer_value  # On
                    else:
                        current_dimmer_value = 0  # Off

                elif dimmer_effect_type == "sparkle":
                    # Sparkle: random variation around dimmer_value
                    import random
                    random.seed(step_idx + fixture_idx)  # Consistent but varied per step/fixture
                    variation = int(dimmer_value * 0.3 * random.random())
                    current_dimmer_value = max(0, min(255, dimmer_value - variation))

                for dimmer_ch in dimmer_channels:
                    channel_value_pairs.append(f"{dimmer_ch['channel']},{int(current_dimmer_value)}")

            # Add color channels (RGB/RGBW/etc.)
            for color_name, (color_chs, color_value) in color_channels.items():
                for color_ch in color_chs:
                    channel_value_pairs.append(f"{color_ch['channel']},{color_value}")

            # Add color wheel channels (fallback when RGB not available)
            for color_wheel_ch in color_wheel_channels:
                channel_value_pairs.append(f"{color_wheel_ch['channel']},{color_wheel_value}")

            # Add special effect channels (gobo, prism, focus, zoom)
            for special_name, (special_chs, special_value) in special_channels.items():
                for special_ch in special_chs:
                    channel_value_pairs.append(f"{special_ch['channel']},{special_value}")

            channel_values = ",".join(channel_value_pairs)
            values.append(f"{fixture_id}:{channel_values}")

        # Drop zero-valued channels (QLC+ saver convention, ~30% smaller .qxw).
        compacted_values, nonzero_count = compact_step_values(values)
        step.set("Values", str(nonzero_count))
        step.text = ":".join(compacted_values)
        steps.append(step)

    return steps


def create_tracks_from_timeline(show_function, engine, show, config, fixture_id_map,
                                function_id_counter, fixture_definitions,
                                export_overrides: dict = None):
    """
    Creates Track elements from timeline_data (new timeline-based format).

    Parameters:
        show_function: The show Function element to add tracks to
        engine: The engine element for adding scenes
        show: Show object containing show data with timeline_data
        config: Configuration object
        fixture_id_map: Dictionary mapping fixture object IDs to their sequential IDs
        function_id_counter: Current function ID counter
        fixture_definitions: Dictionary of fixture definitions loaded from QLC+
        export_overrides: Optional dict with export-time overrides
    Returns:
        int: Next available function ID
    """
    if export_overrides is None:
        export_overrides = {}
    from timeline.song_structure import SongStructure
    from utils.target_resolver import resolve_targets_unique, validate_targets, detect_targets_capabilities

    # Debug: Show export info
    print(f"\n=== Exporting show: {show.name} ===")
    print(f"  Number of lanes: {len(show.timeline_data.lanes)}")
    print(f"  Available groups: {list(config.groups.keys())}")
    print(f"  fixture_id_map keys: {list(fixture_id_map.keys())[:10]}...")  # First 10

    # Build song structure for timing calculations
    song_structure = SongStructure()
    song_structure.load_from_show_parts(show.parts)

    track_id = 0
    fixture_start_id = 0

    for lane_idx, lane in enumerate(show.timeline_data.lanes):
        # Debug: Lane info
        print(f"\n  Lane {lane_idx}: '{lane.name}'")
        print(f"    fixture_targets attr: {getattr(lane, 'fixture_targets', 'NOT_FOUND')}")
        print(f"    light_blocks count: {len(lane.light_blocks)}")

        # Get fixture targets (with backward compatibility for old fixture_group field)
        targets = getattr(lane, 'fixture_targets', [])
        if not targets and hasattr(lane, 'fixture_group') and lane.fixture_group:
            targets = [lane.fixture_group]

        print(f"    Resolved targets: {targets}")

        if not targets:
            print(f"Warning: Lane '{lane.name}' has no targets, skipping")
            continue

        # Validate and warn about invalid targets
        for warning in validate_targets(targets, config):
            print(f"Warning in lane '{lane.name}': {warning}")

        # Resolve targets to unique fixtures
        resolved_fixtures = resolve_targets_unique(targets, config)
        print(f"    Resolved fixtures count: {len(resolved_fixtures)}")
        for f in resolved_fixtures:
            print(f"      - {f.name}: group='{f.group}', universe={f.universe}, address={f.address}")

        if not resolved_fixtures:
            print(f"Warning: No valid fixtures for lane '{lane.name}', skipping")
            continue

        # Sort all fixtures in the lane by position (x coordinate) for cross-group effects
        # This ensures ping-pong, waterfall, etc. work correctly across fixture groups
        sorted_lane_fixtures = sorted(resolved_fixtures, key=lambda f: f.x)

        # Group fixtures by their fixture group for separate track processing
        # This handles multi-target lanes by creating one track per fixture group
        fixtures_by_group = {}
        for fixture in resolved_fixtures:
            group_name = fixture.group
            if group_name not in fixtures_by_group:
                fixtures_by_group[group_name] = []
            fixtures_by_group[group_name].append(fixture)

        print(f"    fixtures_by_group: {list(fixtures_by_group.keys())}")

        # Process each fixture group as a separate track
        for group_name, group_fixtures in fixtures_by_group.items():
            print(f"\n    Creating track for group: '{group_name}' with {len(group_fixtures)} fixtures")
            # Calculate number of fixtures in this group
            fixture_num = len(group_fixtures)

            # Create a display name for this track
            lane_display_name = group_name

            # Create Track
            track = ET.SubElement(show_function, "Track")
            track.set("ID", str(track_id))
            track.set("Name", lane_display_name.upper())
            track.set("SceneID", str(function_id_counter))
            track.set("isMute", "1" if lane.muted else "0")

            # Create Scene
            scene = ET.SubElement(engine, "Function")
            scene.set("ID", str(function_id_counter))
            scene.set("Type", "Scene")
            scene.set("Name", f"Scene for {show.name} - {lane_display_name}")
            scene.set("Hidden", "True")

            # Add Scene properties
            speed = ET.SubElement(scene, "Speed")
            speed.set("FadeIn", "0")
            speed.set("FadeOut", "0")
            speed.set("Duration", "0")

            # Add ChannelGroupsVal
            ET.SubElement(scene, "ChannelGroupsVal").text = f"{track_id},0"

            # Add FixtureVal for this group's fixtures only
            for fixture in group_fixtures:
                fixture_val = ET.SubElement(scene, "FixtureVal")
                fixture_val.set("ID", str(fixture_id_map[(fixture.universe, fixture.address)]))

                num_channels = next((mode.channels for mode in fixture.available_modes
                                    if mode.name == fixture.current_mode), 0)
                channel_values = ",".join([f"{i},0" for i in range(num_channels)])
                fixture_val.text = channel_values

            function_id_counter += 1

            # Get fixture definition from the first fixture in this group
            first_fixture = group_fixtures[0]
            fixture_key = f"{first_fixture.manufacturer}_{first_fixture.model}"
            fixture_def = fixture_definitions.get(fixture_key)

            # Check capabilities for this specific fixture group
            from utils.fixture_utils import detect_fixture_group_capabilities
            group_capabilities = detect_fixture_group_capabilities(group_fixtures, fixture_definitions)
            has_dimmer = group_capabilities.has_dimmer if group_capabilities else True
            has_colour = group_capabilities.has_colour if group_capabilities else False
            has_movement = group_capabilities.has_movement if group_capabilities else False

            # Build per-group export overrides with group-specific intensity scaling
            track_overrides = dict(export_overrides)
            group_intensity = export_overrides.get('group_intensities', {}).get(group_name, 255)
            track_overrides['group_max_intensity'] = group_intensity

            # Process light blocks using unified sequence approach
            # This creates ONE sequence per LightBlock with ALL effects combined
            from utils.to_xml.unified_sequence import generate_unified_sequence_steps

            print(f"    Processing {len(lane.light_blocks)} light blocks for group '{group_name}' (export intensity: {group_intensity})")

            for block_idx, block in enumerate(lane.light_blocks):
                # Check if this block has any sublane blocks
                has_any_blocks = (
                    block.dimmer_blocks or
                    block.colour_blocks or
                    block.movement_blocks or
                    block.special_blocks
                )

                print(f"      Block {block_idx}: dimmer={len(block.dimmer_blocks)}, colour={len(block.colour_blocks)}, movement={len(block.movement_blocks)}, special={len(block.special_blocks)}, has_any={has_any_blocks}")

                if not has_any_blocks:
                    print(f"      Skipping block {block_idx} - no sublane blocks")
                    continue

                # Find the time range of all blocks in this LightBlock
                all_sublane_blocks = (
                    list(block.dimmer_blocks) +
                    list(block.colour_blocks) +
                    list(block.movement_blocks) +
                    list(block.special_blocks)
                )

                block_start_time = min(b.start_time for b in all_sublane_blocks)
                block_end_time = max(b.end_time for b in all_sublane_blocks)
                block_start_time_ms = int(block_start_time * 1000)

                # Find BPM and song part at block start
                part_at_block = song_structure.get_part_at_time(block_start_time)
                block_bpm = part_at_block.bpm if part_at_block else 120
                block_signature = part_at_block.signature if part_at_block else "4/4"

                # Generate unified sequence steps
                # Pass all_lane_fixtures (sorted by position) for cross-group effects like ping-pong
                print(f"      Generating unified steps: bpm={block_bpm}, signature={block_signature}")
                print(f"        fixtures count: {len(group_fixtures)}, fixture_id_map has {len(fixture_id_map)} entries")
                print(f"        fixture_definitions has {len(fixture_definitions)} entries")
                try:
                    steps = generate_unified_sequence_steps(
                        fixtures=group_fixtures,
                        fixture_id_map=fixture_id_map,
                        fixture_definitions=fixture_definitions,
                        light_block=block,
                        bpm=block_bpm,
                        signature=block_signature,
                        all_lane_fixtures=sorted_lane_fixtures,  # All fixtures in lane for cross-group effects
                        config=config,  # Pass config for spot targeting
                        export_overrides=track_overrides
                    )

                    print(f"      Generated {len(steps) if steps else 0} steps")

                    if not steps:
                        print(f"Warning: No unified steps generated for block at {block_start_time_ms}ms")
                        continue

                except Exception as e:
                    print(f"Error creating unified sequence steps: {e}")
                    import traceback
                    traceback.print_exc()
                    continue

                # Create sequence for this unified block
                sequence_name = f"{show.name}_{lane_display_name}_unified_{block_start_time_ms}"
                sequence = create_sequence(engine, function_id_counter, sequence_name,
                                          scene.get("ID"), block_bpm)
                add_steps_to_sequence(sequence, steps)

                # Create ShowFunction for this block
                show_func = ET.SubElement(track, "ShowFunction")
                show_func.set("ID", str(function_id_counter))
                show_func.set("StartTime", str(block_start_time_ms))

                # Use color based on which effects are present
                if block.movement_blocks:
                    color = "#6496FF"  # Blue for movement
                elif block.colour_blocks:
                    color = "#FF6496"  # Pink for color
                else:
                    color = "#4CAF50"  # Green for dimmer

                show_func.set("Color", color)

                function_id_counter += 1

            fixture_start_id += fixture_num
            track_id += 1

    return function_id_counter


def create_shows(engine, config: Configuration, fixture_id_map: dict, fixture_definitions: dict,
                  export_overrides: dict = None):
    """
    Creates show function elements from Configuration data

    Parameters:
        engine: The engine XML element to add the show functions to
        config: Configuration object containing show data
        fixture_id_map: Dictionary mapping fixture object IDs to their sequential IDs
        fixture_definitions: Dictionary of fixture definitions loaded from QLC+
        export_overrides: Optional dict with export-time overrides (e.g. group_intensities)
    Returns:
        int: Next available function ID
    """
    if export_overrides is None:
        export_overrides = {}
    function_id_counter = 0

    # Process each show in the configuration
    for show_name, show in config.songs.items():
        # Debug info
        has_timeline = show.timeline_data is not None
        has_lanes = has_timeline and len(show.timeline_data.lanes) > 0 if has_timeline else False
        print(f"\n>>> Processing show: {show_name}")
        print(f"    timeline_data exists: {has_timeline}")
        print(f"    lanes count: {len(show.timeline_data.lanes) if has_timeline else 0}")
        print(f"    has_lanes (non-empty): {has_lanes}")

        # Create Function element for the show
        show_function = ET.SubElement(engine, "Function")
        show_function.set("ID", str(function_id_counter))
        show_function.set("Type", "Show")
        show_function.set("Name", show_name)
        function_id_counter += 1

        # Create TimeDivision element
        time_division = ET.SubElement(show_function, "TimeDivision")
        time_division.set("Type", "Time")
        # Use BPM from first show part, or default to 120
        time_division.set("BPM", str(show.parts[0].bpm if show.parts else 120))

        if show.timeline_data and show.timeline_data.lanes:
            print(f"    Using TIMELINE export path")
            function_id_counter = create_tracks_from_timeline(
                show_function,
                engine,
                show,
                config,
                fixture_id_map,
                function_id_counter,
                fixture_definitions,
                export_overrides=export_overrides
            )
            print(f"Successfully created show from timeline: {show_name}")
        else:
            print(f"    Skipping show '{show_name}' - no timeline data")

    return function_id_counter




