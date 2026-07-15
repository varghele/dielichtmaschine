# unified_sequence.py
# Functions for creating unified QLC+ sequences that combine all effect types

import math
import xml.etree.ElementTree as ET
from typing import List, Dict, Any, Optional, Tuple
from utils.effects_utils import get_channels_by_property, find_closest_color_dmx
from utils.yoke import export_aim_dmx  # noqa: F401 (aiming moved to the yoke helper)
from utils.to_xml.step_compaction import compact_step_values
from effects.timing import movement_total_cycles


def _map_rgb_to_color_wheel(r: int, g: int, b: int) -> int:
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
    closest_value = 5  # Default to white

    for wr, wg, wb, dmx_value in wheel_colors:
        distance = ((r - wr) ** 2 + (g - wg) ** 2 + (b - wb) ** 2) ** 0.5
        if distance < min_distance:
            min_distance = distance
            closest_value = dmx_value

    return closest_value


def calculate_unified_step_grid(
    dimmer_blocks: List,
    colour_blocks: List,
    movement_blocks: List,
    special_blocks: List,
    bpm: float,
    signature: str = "4/4"
) -> Tuple[List[float], int]:
    """
    Calculate a unified step timing grid that covers all effect blocks.

    Uses the highest resolution needed (movement effects typically need more steps).

    Args:
        dimmer_blocks: List of DimmerBlock objects
        colour_blocks: List of ColourBlock objects
        movement_blocks: List of MovementBlock objects
        special_blocks: List of SpecialBlock objects
        bpm: Beats per minute
        signature: Time signature (e.g., "4/4")

    Returns:
        Tuple of (step_times_ms, step_duration_ms):
            step_times_ms: List of step start times in milliseconds
            step_duration_ms: Duration of each step in milliseconds
    """
    # Find the overall time range
    all_blocks = dimmer_blocks + colour_blocks + movement_blocks + special_blocks
    if not all_blocks:
        return [], 0

    start_time = min(b.start_time for b in all_blocks)
    end_time = max(b.end_time for b in all_blocks)
    total_duration_s = end_time - start_time
    total_duration_ms = int(total_duration_s * 1000)

    if total_duration_ms <= 0:
        return [], 0

    # Determine the step resolution based on the fastest effect
    # Movement effects need ~24 steps/second for smooth motion
    # Dimmer effects typically need 1-8 steps per beat

    MAX_STEPS_PER_SECOND = 24
    MIN_STEP_DURATION_MS = 40  # Don't go faster than 25 steps/second

    # Calculate steps needed for movement effects (highest resolution)
    movement_steps_needed = 0
    for block in movement_blocks:
        block_duration = block.end_time - block.start_time
        if block.effect_type != "static":
            # Dynamic movement needs many steps
            movement_steps_needed = max(movement_steps_needed, int(block_duration * MAX_STEPS_PER_SECOND))
        else:
            # Static movement only needs 1 step
            movement_steps_needed = max(movement_steps_needed, 1)

    # Calculate steps needed for dimmer effects
    # We need to calculate the minimum step interval required across all effects
    # then apply that to the total duration
    min_step_interval_ms = total_duration_ms  # Start with max (will be reduced)
    numerator, denominator = map(int, signature.split('/'))
    beats_per_bar = (numerator * 4) / denominator
    ms_per_beat = 60000 / bpm

    for block in dimmer_blocks:
        # Parse speed multiplier
        speed = block.effect_speed
        if '/' in speed:
            num, denom = map(int, speed.split('/'))
            speed_mult = num / denom
        else:
            speed_mult = float(speed)

        # Calculate the step interval needed for this effect type
        if block.effect_type == "static":
            # Static effects only need steps at block boundaries
            # We'll handle this with block boundary detection below
            pass
        elif block.effect_type == "strobe":
            # Strobe needs fast steps - half beat per toggle
            step_interval = (ms_per_beat / speed_mult) / 2
            min_step_interval_ms = min(min_step_interval_ms, step_interval)
        elif block.effect_type == "stroke":
            # Stroke effects need fine steps to show exponential decay
            # At minimum, 8 steps per stroke cycle for decent decay curve
            stroke_cycle_ms = ms_per_beat / speed_mult  # one beat per stroke
            step_interval = stroke_cycle_ms / 8  # 8 steps per stroke for smooth decay
            step_interval = max(step_interval, MIN_STEP_DURATION_MS)
            min_step_interval_ms = min(min_step_interval_ms, step_interval)
        elif block.effect_type in ("ping_pong", "random_stroke", "chase"):
            # Ping pong, random stroke, and chase have smooth animations that need fine steps
            # Similar to stroke, use 8-10 steps per fixture transition for smooth animation
            beat_ms = ms_per_beat / speed_mult  # one beat per fixture
            step_interval = beat_ms / 10  # 10 steps per beat for smooth animation
            step_interval = max(step_interval, MIN_STEP_DURATION_MS)
            min_step_interval_ms = min(min_step_interval_ms, step_interval)
        elif block.effect_type in ("pulse", "wave", "heartbeat"):
            # Smooth animated effects need fine steps for visual quality
            # Use ~16 steps per bar for smooth sine waves and heartbeat pattern
            bar_ms = ms_per_beat * 4  # Assuming 4/4 time
            cycle_ms = bar_ms / speed_mult
            step_interval = cycle_ms / 16  # 16 steps per cycle
            step_interval = max(step_interval, MIN_STEP_DURATION_MS)
            min_step_interval_ms = min(min_step_interval_ms, step_interval)
        elif block.effect_type == "sparkle":
            # Sparkle needs ~2 samples per sparkle transition for smooth interpolation
            # Sparkle step duration = 200ms / speed_mult; sample at half that
            step_interval = (0.1 / speed_mult) * 1000  # 100ms / speed_mult
            step_interval = max(step_interval, MIN_STEP_DURATION_MS)
            min_step_interval_ms = min(min_step_interval_ms, step_interval)
        elif block.effect_type == "waterfall":
            # Waterfall needs fine steps to capture smooth drift animation
            # Same resolution as ping_pong: 10 steps per beat
            beat_ms_wf = ms_per_beat / speed_mult
            step_interval = beat_ms_wf / 10
            step_interval = max(step_interval, MIN_STEP_DURATION_MS)
            min_step_interval_ms = min(min_step_interval_ms, step_interval)
        else:
            # Other effects
            # One step per beat is usually sufficient
            step_interval = ms_per_beat / speed_mult
            min_step_interval_ms = min(min_step_interval_ms, step_interval)

    # Ensure minimum step interval is reasonable
    min_step_interval_ms = max(min_step_interval_ms, MIN_STEP_DURATION_MS)

    # Calculate dimmer steps needed based on total duration and minimum interval
    dimmer_steps_needed = int(total_duration_ms / min_step_interval_ms) if min_step_interval_ms > 0 else 1

    # Use the maximum steps needed
    total_steps = max(movement_steps_needed, dimmer_steps_needed, 1)

    # Cap at reasonable limits
    max_steps = int(total_duration_ms / MIN_STEP_DURATION_MS)
    total_steps = min(total_steps, max_steps, 512)  # Hard cap at 512 steps
    total_steps = max(total_steps, 1)

    # Calculate step duration
    step_duration_ms = total_duration_ms // total_steps
    step_duration_ms = max(step_duration_ms, MIN_STEP_DURATION_MS)

    # Recalculate total steps based on step duration
    total_steps = total_duration_ms // step_duration_ms

    # Generate step times
    step_times_ms = []
    for i in range(total_steps):
        step_times_ms.append(int(start_time * 1000) + i * step_duration_ms)

    return step_times_ms, step_duration_ms


def sample_dimmer_at_time(
    time_s: float,
    dimmer_blocks: List,
    fixture_idx: int,
    total_fixtures: int,
    step_idx: int,
    total_steps: int,
    bpm: float = 120.0,
    max_intensity: int = 255
) -> Optional[int]:
    """
    Sample the dimmer intensity at a given time.

    Args:
        time_s: Time in seconds
        dimmer_blocks: List of DimmerBlock objects
        fixture_idx: Index of this fixture in the group (for per-fixture effects)
        total_fixtures: Total number of fixtures in the group
        step_idx: Current step index (for animated effects)
        total_steps: Total number of steps
        bpm: Beats per minute for timing calculations
        max_intensity: Maximum intensity for this group (0-255), scales proportionally

    Returns:
        Intensity value (0-255) or None if no dimmer block at this time
    """
    # Find the dimmer block at this time
    active_block = None
    for block in dimmer_blocks:
        if block.start_time <= time_s < block.end_time:
            active_block = block
            break

    if not active_block:
        return None

    base_intensity = int(int(active_block.intensity) * max_intensity / 255)
    effect_type = active_block.effect_type

    # Calculate relative position within the block
    block_duration = active_block.end_time - active_block.start_time
    relative_time = (time_s - active_block.start_time) / block_duration if block_duration > 0 else 0

    if effect_type == "static":
        return base_intensity

    elif effect_type == "strobe":
        # Alternate between intensity and 0
        # Parse speed
        speed = active_block.effect_speed
        if '/' in speed:
            num, denom = map(int, speed.split('/'))
            speed_mult = num / denom
        else:
            speed_mult = float(speed)

        # Calculate strobe phase using BPM timing (matches ArtNet implementation)
        time_in_block = time_s - active_block.start_time
        strobe_hz = 2.0 * speed_mult  # Strobe at 2Hz * speed_mult
        phase = (time_in_block * strobe_hz) % 1.0
        # 50% duty cycle
        if phase < 0.5:
            return base_intensity
        else:
            return 0

    elif effect_type == "sparkle":
        # Sparkle effect: smooth random intensity variations per fixture
        # Matches ArtNet implementation in dmx_manager.py
        import random
        import hashlib

        # Parse speed multiplier
        speed = active_block.effect_speed
        if '/' in speed:
            num, denom = map(int, speed.split('/'))
            speed_mult = num / denom
        else:
            speed_mult = float(speed)

        time_in_block = time_s - active_block.start_time

        # Time per "twinkle step" - how often a new random target is chosen
        # 200ms base, adjusted by speed (matches ArtNet)
        twinkle_step_duration = 0.2 / speed_mult

        # Calculate current and next step for interpolation
        step_float = time_in_block / twinkle_step_duration
        current_twinkle_step = int(step_float)
        next_twinkle_step = current_twinkle_step + 1
        # How far through the transition (0.0 to 1.0)
        transition_progress = step_float - current_twinkle_step

        # Get current target intensity (deterministic random based on fixture + step)
        seed_str = f"fixture_{fixture_idx}_{current_twinkle_step}"
        seed_hash = int(hashlib.md5(seed_str.encode()).hexdigest()[:8], 16)
        random.seed(seed_hash)
        current_variation = random.random() * 0.7 + 0.3  # 30% to 100%

        # Get next target intensity
        seed_str = f"fixture_{fixture_idx}_{next_twinkle_step}"
        seed_hash = int(hashlib.md5(seed_str.encode()).hexdigest()[:8], 16)
        random.seed(seed_hash)
        next_variation = random.random() * 0.7 + 0.3  # 30% to 100%

        # Smooth interpolation using smoothstep function
        t = transition_progress
        smooth_t = t * t * (3 - 2 * t)
        variation = current_variation + (next_variation - current_variation) * smooth_t

        return int(base_intensity * variation)

    elif effect_type == "ping_pong":
        # Ping pong: one fixture lights up at a time, bouncing back and forth
        # INSTANT attack (on the beat), smooth fade out until next fixture
        speed = active_block.effect_speed
        if '/' in speed:
            num, denom = map(int, speed.split('/'))
            speed_mult = num / denom
        else:
            speed_mult = float(speed)

        time_in_block = time_s - active_block.start_time

        if total_fixtures <= 1:
            # Single fixture - just stay on
            return base_intensity

        # Calculate timing based on BPM: each fixture gets one beat at speed 1
        seconds_per_beat = 60.0 / bpm
        time_per_fixture = seconds_per_beat / speed_mult

        # Total time for one full ping-pong cycle (0→N-1→0)
        # For N fixtures: N-1 steps forward, N-1 steps back = 2*(N-1) beats
        steps_in_cycle = (total_fixtures - 1) * 2
        cycle_time = time_per_fixture * steps_in_cycle

        # Get current time within the cycle
        time_in_cycle = time_in_block % cycle_time

        # Which "step" are we on? (each step = one fixture's turn)
        current_step = time_in_cycle / time_per_fixture
        step_index = int(current_step)
        time_within_step = (current_step - step_index) * time_per_fixture

        # Convert step index to fixture index (ping-pong pattern)
        # Steps 0,1,2,...,N-2 go forward (fixtures 0,1,2,...,N-1)
        # Steps N-1,N,...,2N-3 go backward (fixtures N-2,N-3,...,1)
        if step_index < (total_fixtures - 1):
            # Going forward
            active_fixture = step_index
        else:
            # Going backward
            active_fixture = steps_in_cycle - step_index

        # Calculate intensity multiplier for this fixture
        if fixture_idx == active_fixture:
            # This is the active fixture - instant full brightness
            # with smooth decay over the beat
            # Decay: start at 100%, end at ~20% by end of beat
            decay_progress = time_within_step / time_per_fixture if time_per_fixture > 0 else 0
            # Use exponential decay for smooth falloff
            intensity_multiplier = 0.2 + 0.8 * math.exp(-decay_progress * 3)
        elif fixture_idx == (active_fixture - 1) or fixture_idx == (active_fixture + 1):
            # Adjacent fixture - might have residual glow from previous beat
            # Determine which direction we're going to find the "previous" fixture
            if step_index < (total_fixtures - 1):
                # Going forward, previous is active_fixture - 1
                prev_fixture = active_fixture - 1
            else:
                # Going backward, previous is active_fixture + 1
                prev_fixture = active_fixture + 1

            if fixture_idx == prev_fixture and time_within_step < time_per_fixture * 0.3:
                # Short tail from previous fixture (first 30% of beat only)
                tail_progress = time_within_step / (time_per_fixture * 0.3) if time_per_fixture > 0 else 1
                intensity_multiplier = 0.3 * (1.0 - tail_progress)
            else:
                intensity_multiplier = 0.0
        else:
            # Not active, not adjacent - off
            intensity_multiplier = 0.0

        return int(base_intensity * intensity_multiplier)

    elif effect_type == "random_stroke":
        # Random stroke: one fixture lights up at a time in shuffled order
        # When all fixtures have been lit, reshuffle (like a deck of cards)
        import random

        speed = active_block.effect_speed
        if '/' in speed:
            num, denom = map(int, speed.split('/'))
            speed_mult = num / denom
        else:
            speed_mult = float(speed)

        time_in_block = time_s - active_block.start_time

        if total_fixtures <= 1:
            # Single fixture - just stay on
            return base_intensity

        # Calculate timing based on BPM: each fixture gets one beat at speed 1
        seconds_per_beat = 60.0 / bpm
        time_per_fixture = seconds_per_beat / speed_mult

        # Time for one full cycle (all fixtures once)
        cycle_time = time_per_fixture * total_fixtures

        # Which cycle are we in?
        cycle_number = int(time_in_block / cycle_time)

        # Time within current cycle
        time_in_cycle = time_in_block % cycle_time

        # Which step within the cycle?
        current_step = time_in_cycle / time_per_fixture
        step_index = int(current_step)
        time_within_step = (current_step - step_index) * time_per_fixture

        # Generate shuffled order deterministically based on block start time + cycle
        seed = int(active_block.start_time * 1000) + cycle_number
        rng = random.Random(seed)
        shuffled_indices = list(range(total_fixtures))
        rng.shuffle(shuffled_indices)

        # Which fixture is active at this step?
        active_fixture = shuffled_indices[step_index % total_fixtures]

        # Calculate intensity multiplier for this fixture
        if fixture_idx == active_fixture:
            # This is the active fixture - instant full brightness with smooth decay
            decay_progress = time_within_step / time_per_fixture if time_per_fixture > 0 else 0
            intensity_multiplier = 0.2 + 0.8 * math.exp(-decay_progress * 3)
        else:
            # Not active - off
            intensity_multiplier = 0.0

        return int(base_intensity * intensity_multiplier)

    elif effect_type == "chase":
        # Chase effect: a light with fading tail moves through fixtures, bouncing back and forth
        # chase_scope="fixture" (was snake): runs per fixture group
        # chase_scope="global" (was zigzag): treats ALL fixtures as one continuous chain
        # 4 beats = full cycle (forward + backward)
        # Tail spans approximately half the fixtures
        speed = active_block.effect_speed
        if '/' in speed:
            num, denom = map(int, speed.split('/'))
            speed_mult = num / denom
        else:
            speed_mult = float(speed)

        time_in_block = time_s - active_block.start_time

        if total_fixtures <= 1:
            return base_intensity

        # Tail spans half the fixtures
        tail_length = max(1, total_fixtures // 2)

        # 4 beats = full cycle (forward + backward)
        seconds_per_beat = 60.0 / bpm
        time_per_pass = (seconds_per_beat * 2) / speed_mult  # 2 beats per pass
        cycle_time = time_per_pass * 2  # Full cycle

        # Current position in cycle
        time_in_cycle = time_in_block % cycle_time

        # Calculate head position (0 to total_fixtures-1, bouncing)
        if time_in_cycle < time_per_pass:
            # Forward pass
            progress = time_in_cycle / time_per_pass
            head_position = progress * (total_fixtures - 1)
            going_forward = True
        else:
            # Backward pass
            progress = (time_in_cycle - time_per_pass) / time_per_pass
            head_position = (total_fixtures - 1) * (1.0 - progress)
            going_forward = False

        # Calculate distance from head for this fixture (considering direction)
        if going_forward:
            distance = head_position - fixture_idx
        else:
            distance = fixture_idx - head_position

        # Calculate intensity based on distance
        if distance < -0.5:
            # Ahead of head - off
            intensity_multiplier = 0.0
        elif distance < 0.5:
            # At head - full intensity
            intensity_multiplier = 1.0
        elif distance <= tail_length:
            # In tail - fade based on distance
            fade_factor = 1.0 - (distance / (tail_length + 1))
            intensity_multiplier = fade_factor * 0.8  # Max 80% for tail
        else:
            # Beyond tail - off
            intensity_multiplier = 0.0

        return int(base_intensity * intensity_multiplier)

    elif effect_type == "waterfall":
        # Waterfall effect: light cascades through fixtures with smooth tail
        # Uses block.direction ("down" or "up") to determine cascade direction
        # Matches ArtNet implementation in dmx_manager.py
        import hashlib

        speed = active_block.effect_speed
        if '/' in speed:
            num, denom = map(int, speed.split('/'))
            speed_mult = num / denom
        else:
            speed_mult = float(speed)

        time_in_block = time_s - active_block.start_time

        if total_fixtures <= 1:
            return base_intensity

        # Calculate timing based on BPM: each fixture gets one beat at speed 1
        seconds_per_beat = 60.0 / bpm
        time_per_step = seconds_per_beat / speed_mult

        # Calculate random offset for this fixture (slowly drifting)
        # Use fixture_idx as seed since we don't have fixture name here
        seed_str = f"waterfall_fixture_{fixture_idx}"
        name_hash = int(hashlib.md5(seed_str.encode()).hexdigest()[:8], 16)
        base_offset = (name_hash % 1000) / 1000.0  # 0.0 to 1.0

        # Slowly drifting component (changes over ~30 seconds)
        drift_period = 30.0
        drift_phase = (time_s / drift_period) * 2 * math.pi
        drift_seed = (name_hash % 997) / 997.0 * 2 * math.pi
        drift_amount = 0.3 * math.sin(drift_phase + drift_seed)  # +/- 0.3 cycle drift

        total_offset = base_offset + drift_amount

        # Full cycle time = total_fixtures beats (one per fixture)
        cycle_time = time_per_step * total_fixtures

        # Current position in cycle (0 to total_fixtures), with offset
        cycle_progress = (time_in_block / cycle_time + total_offset) % 1.0
        head_position = cycle_progress * total_fixtures  # 0 to total_fixtures

        # For direction="down": head moves from last fixture (N-1) to first (0)
        # For direction="up": head moves from first fixture (0) to last (N-1)
        direction = getattr(active_block, 'direction', 'down')
        if direction == "down":
            head_position = (total_fixtures - 1) - head_position
        # For direction="up", head_position is already 0 to N-1

        # Calculate distance from head using circular/wrapped distance
        # This creates a continuous seamless loop where the tail wraps around
        if direction == "down":
            raw_distance = fixture_idx - head_position
        else:  # direction="up"
            raw_distance = head_position - fixture_idx

        # Use modulo to wrap the distance for continuous effect
        circular_distance = raw_distance % total_fixtures

        # Normalize and apply exponential decay
        normalized_dist = circular_distance / total_fixtures
        intensity_multiplier = math.exp(-1.5 * normalized_dist)

        return int(base_intensity * intensity_multiplier)

    elif effect_type == "stroke":
        # Stroke effect: instant attack, decay over the beat duration
        # One stroke per beat at speed 1, decay takes the full beat
        speed = active_block.effect_speed
        if '/' in speed:
            num, denom = map(int, speed.split('/'))
            speed_mult = num / denom
        else:
            speed_mult = float(speed)

        time_in_block = time_s - active_block.start_time

        seconds_per_beat = 60.0 / bpm

        # Time between strokes (one beat at speed 1)
        time_per_stroke = seconds_per_beat / speed_mult

        # Decay takes the full beat duration
        decay_time = time_per_stroke

        # Calculate position within current stroke cycle
        time_in_cycle = time_in_block % time_per_stroke

        # Calculate intensity based on decay (full beat duration)
        decay_progress = time_in_cycle / decay_time
        # Exponential decay: e^(-3) ≈ 0.05
        intensity_multiplier = math.exp(-decay_progress * 3)

        return int(base_intensity * intensity_multiplier)

    elif effect_type == "pulse":
        # Pulse effect: all fixtures fade in/out together smoothly in a sine curve
        # One full pulse cycle per bar at speed 1
        speed = active_block.effect_speed
        if '/' in speed:
            num, denom = map(int, speed.split('/'))
            speed_mult = num / denom
        else:
            speed_mult = float(speed)

        time_in_block = time_s - active_block.start_time

        # Calculate timing: one breath cycle per bar at speed 1
        seconds_per_beat = 60.0 / bpm
        seconds_per_bar = seconds_per_beat * 4  # Assuming 4/4 time
        cycle_time = seconds_per_bar / speed_mult

        # Calculate phase in the breathing cycle (0 to 2*pi)
        phase = (time_in_block / cycle_time) * 2 * math.pi

        # Minimum intensity floor (30% of base)
        floor = 0.3

        # Sine wave for smooth breathing: floor + (1-floor) * (sin(phase) + 1) / 2
        # This gives a smooth oscillation between floor and 1.0
        brightness = floor + (1 - floor) * (math.sin(phase) + 1) / 2

        return int(base_intensity * brightness)

    elif effect_type == "wave":
        # Wave effect: intensity wave travels across fixtures like a stadium wave
        # One wave cycle per bar at speed 1
        speed = active_block.effect_speed
        if '/' in speed:
            num, denom = map(int, speed.split('/'))
            speed_mult = num / denom
        else:
            speed_mult = float(speed)

        time_in_block = time_s - active_block.start_time

        if total_fixtures <= 1:
            # Single fixture - just use breathing pattern
            seconds_per_beat = 60.0 / bpm
            seconds_per_bar = seconds_per_beat * 4
            cycle_time = seconds_per_bar / speed_mult
            phase = (time_in_block / cycle_time) * 2 * math.pi
            brightness = (math.sin(phase) + 1) / 2
            return int(base_intensity * brightness)

        # Calculate timing: one wave cycle per bar at speed 1
        seconds_per_beat = 60.0 / bpm
        seconds_per_bar = seconds_per_beat * 4
        cycle_time = seconds_per_bar / speed_mult

        # Wavelength: how many fixtures the wave spans (half the fixtures)
        wavelength = max(2, total_fixtures / 2)

        # Calculate wave position for this fixture at this time
        # Wave moves from left to right (direction = "right")
        time_progress = time_in_block / cycle_time
        wave_pos = 2 * math.pi * (fixture_idx / wavelength - time_progress)

        # Sine wave intensity (0 to 1)
        brightness = (math.sin(wave_pos) + 1) / 2

        return int(base_intensity * brightness)

    elif effect_type == "heartbeat":
        # Heartbeat effect: double-pulse pattern (bump-bump... pause... bump-bump)
        # One heartbeat cycle per bar at speed 1
        # Timing: Beat1 up (10%), Beat1 down (10%), Beat2 up (10%), Beat2 down (20%), Rest (50%)
        speed = active_block.effect_speed
        if '/' in speed:
            num, denom = map(int, speed.split('/'))
            speed_mult = num / denom
        else:
            speed_mult = float(speed)

        time_in_block = time_s - active_block.start_time

        # Calculate timing: one heartbeat cycle per bar at speed 1
        seconds_per_beat = 60.0 / bpm
        seconds_per_bar = seconds_per_beat * 4
        cycle_time = seconds_per_bar / speed_mult

        # Position within current cycle (0 to 1)
        cycle_pos = (time_in_block % cycle_time) / cycle_time

        # Minimum intensity floor (20% of base)
        floor = 0.2

        # Calculate beat level based on position in cycle
        if cycle_pos < 0.10:
            # Beat 1 up: quick fade up to 100%
            beat_level = floor + (1.0 - floor) * (cycle_pos / 0.10)
        elif cycle_pos < 0.20:
            # Beat 1 down: quick fade to 60%
            beat_level = 1.0 - (1.0 - 0.6) * ((cycle_pos - 0.10) / 0.10)
        elif cycle_pos < 0.30:
            # Beat 2 up: quick fade up to 80%
            beat_level = 0.6 + (0.8 - 0.6) * ((cycle_pos - 0.20) / 0.10)
        elif cycle_pos < 0.50:
            # Beat 2 down: fade down to floor
            beat_level = 0.8 - (0.8 - floor) * ((cycle_pos - 0.30) / 0.20)
        else:
            # Rest: stay at floor
            beat_level = floor

        return int(base_intensity * beat_level)

    # Default: static
    return base_intensity


def sample_movement_at_time(
    time_s: float,
    movement_blocks: List,
    fixture_idx: int,
    total_fixtures: int,
    step_idx: int,
    total_steps: int,
    bpm: float = 120.0,
    signature: str = "4/4",
    config: Any = None,
    fixture: Any = None
) -> Optional[Tuple[int, int]]:
    """
    Sample the pan/tilt position at a given time.

    Args:
        time_s: Time in seconds
        movement_blocks: List of MovementBlock objects
        fixture_idx: Index of this fixture in the group
        total_fixtures: Total number of fixtures in the group
        step_idx: Current step index
        total_steps: Total number of steps
        bpm: Beats per minute for timing calculations
        signature: Time signature (e.g., "4/4")
        config: Configuration object (for spot lookup)
        fixture: Fixture object (for position and orientation)

    Returns:
        Tuple of (pan, tilt) values (0-255) or None if no movement block at this time
    """
    # Find the movement block at this time
    active_block = None
    for block in movement_blocks:
        if block.start_time <= time_s < block.end_time:
            active_block = block
            break

    if not active_block:
        return None

    effect_type = active_block.effect_type

    # Check if we have a target spot - if so, calculate pan/tilt to point at it
    if active_block.target_spot_name and config and fixture and hasattr(config, 'spots'):
        spot = config.spots.get(active_block.target_spot_name)
        if spot:
            # Get effective orientation (considering group defaults)
            group = config.groups.get(fixture.group) if fixture.group else None
            mounting, yaw, pitch, roll = fixture.get_effective_orientation(group)
            fixture_z = fixture.get_effective_z(group)

            # Aim with the solver at the definition's real ranges,
            # UNCONVERTED: the shape math below runs in solver DMX
            # space (exactly like the native renderer), and the WHOLE
            # step converts to the real yoke at the end
            # (convert_solver_dmx) - so QLC+ playback traces the same
            # figure the app and the rig do. Before 2026-07-13 only
            # the centre was converted and the pattern oscillated in
            # solver space around it, a mixed frame that traced the
            # wrong figure on a real head.
            from utils.yoke import export_solver_aim_dmx
            pan_dmx, tilt_dmx = export_solver_aim_dmx(
                fixture, fixture_z, (spot.x, spot.y, spot.z),
                mounting, yaw, pitch, roll)

            # Use calculated values as center position
            center_pan = float(pan_dmx)
            center_tilt = float(tilt_dmx)
        else:
            # Spot not found, fall back to manual values
            center_pan = active_block.pan
            center_tilt = active_block.tilt
    else:
        # No target spot, use manual values
        center_pan = active_block.pan
        center_tilt = active_block.tilt
    pan_amplitude = active_block.pan_amplitude
    tilt_amplitude = active_block.tilt_amplitude
    pan_min = active_block.pan_min
    pan_max = active_block.pan_max
    tilt_min = active_block.tilt_min
    tilt_max = active_block.tilt_max

    # Parse speed
    speed = active_block.effect_speed
    if '/' in speed:
        num, denom = map(int, speed.split('/'))
        speed_mult = num / denom
    else:
        speed_mult = float(speed)

    # Calculate timing based on BPM (matches ArtNet implementation)
    seconds_per_beat = 60.0 / bpm
    numerator, denominator = map(int, signature.split('/'))
    beats_per_bar = (numerator * 4) / denominator
    seconds_per_bar = seconds_per_beat * beats_per_bar

    # Calculate time within block
    block_duration = active_block.end_time - active_block.start_time
    time_in_block = time_s - active_block.start_time

    # Calculate relative position for progress (0 to 1)
    progress = time_in_block / block_duration if block_duration > 0 else 0

    # Shared movement rate (matches ArtNet preview + shows_to_xml export).
    total_cycles = movement_total_cycles(block_duration, seconds_per_bar, speed_mult)

    # Calculate phase offset for this fixture
    if active_block.phase_offset_enabled:
        fixture_phase = (fixture_idx * active_block.phase_offset_degrees) * math.pi / 180.0
    else:
        fixture_phase = 0.0

    # Calculate angle based on progress and total cycles
    t = 2 * math.pi * total_cycles * progress + fixture_phase

    # Calculate position based on effect type
    if effect_type == "static":
        pan = center_pan
        tilt = center_tilt

    elif effect_type == "circle":
        pan = center_pan + pan_amplitude * math.cos(t)
        tilt = center_tilt + tilt_amplitude * math.sin(t)

    elif effect_type == "diamond":
        phase = (progress * total_cycles * 4) % 4
        corner = int(phase)
        local_t = phase - corner
        corners = [
            (center_pan, center_tilt - tilt_amplitude),
            (center_pan + pan_amplitude, center_tilt),
            (center_pan, center_tilt + tilt_amplitude),
            (center_pan - pan_amplitude, center_tilt),
        ]
        start = corners[corner % 4]
        end = corners[(corner + 1) % 4]
        pan = start[0] + local_t * (end[0] - start[0])
        tilt = start[1] + local_t * (end[1] - start[1])

    elif effect_type == "square":
        phase = (progress * total_cycles * 4) % 4
        corner = int(phase)
        local_t = phase - corner
        corners = [
            (center_pan - pan_amplitude, center_tilt - tilt_amplitude),
            (center_pan + pan_amplitude, center_tilt - tilt_amplitude),
            (center_pan + pan_amplitude, center_tilt + tilt_amplitude),
            (center_pan - pan_amplitude, center_tilt + tilt_amplitude),
        ]
        start = corners[corner % 4]
        end = corners[(corner + 1) % 4]
        pan = start[0] + local_t * (end[0] - start[0])
        tilt = start[1] + local_t * (end[1] - start[1])

    elif effect_type == "triangle":
        phase = (progress * total_cycles * 3) % 3
        corner = int(phase)
        local_t = phase - corner
        corners = [
            (center_pan, center_tilt - tilt_amplitude),
            (center_pan + pan_amplitude * 0.866, center_tilt + tilt_amplitude * 0.5),
            (center_pan - pan_amplitude * 0.866, center_tilt + tilt_amplitude * 0.5),
        ]
        start = corners[corner % 3]
        end = corners[(corner + 1) % 3]
        pan = start[0] + local_t * (end[0] - start[0])
        tilt = start[1] + local_t * (end[1] - start[1])

    elif effect_type == "figure_8":
        pan = center_pan + pan_amplitude * math.sin(t)
        tilt = center_tilt + tilt_amplitude * math.sin(2 * t)

    elif effect_type == "lissajous":
        try:
            ratio_parts = active_block.lissajous_ratio.split(':')
            freq_pan = int(ratio_parts[0])
            freq_tilt = int(ratio_parts[1])
        except (ValueError, IndexError):
            freq_pan, freq_tilt = 1, 2
        pan = center_pan + pan_amplitude * math.sin(freq_pan * t)
        tilt = center_tilt + tilt_amplitude * math.sin(freq_tilt * t)

    elif effect_type == "random":
        pan = center_pan + pan_amplitude * (
            0.5 * math.sin(3 * t) + 0.3 * math.sin(7 * t) + 0.2 * math.sin(11 * t)
        )
        tilt = center_tilt + tilt_amplitude * (
            0.5 * math.sin(5 * t) + 0.3 * math.sin(11 * t) + 0.2 * math.sin(13 * t)
        )

    elif effect_type == "bounce":
        bounce_t = progress * total_cycles * 4
        pan_t = abs((bounce_t % 2) - 1)
        tilt_t = abs(((bounce_t + 0.5) % 2) - 1)
        pan = center_pan - pan_amplitude + 2 * pan_amplitude * pan_t
        tilt = center_tilt - tilt_amplitude + 2 * tilt_amplitude * tilt_t

    else:
        pan = center_pan
        tilt = center_tilt

    # Apply clipping to boundaries (solver DMX space, like the native
    # renderer's clamp).
    pan = max(pan_min, min(pan_max, pan))
    tilt = max(tilt_min, min(tilt_max, tilt))

    # Convert the finished solver-space step to the fixture's real
    # yoke - the per-step equivalent of the arbiter's hardware pass.
    if fixture is not None:
        from utils.yoke import convert_solver_dmx
        return convert_solver_dmx(fixture, pan, tilt)
    return (int(pan), int(tilt))


def sample_colour_at_time(
    time_s: float,
    colour_blocks: List
) -> Optional[Dict[str, int]]:
    """
    Sample the color values at a given time.

    Args:
        time_s: Time in seconds
        colour_blocks: List of ColourBlock objects

    Returns:
        Dict with color values or None if no colour block at this time
    """
    # Find the colour block at this time
    active_block = None
    for block in colour_blocks:
        if block.start_time <= time_s < block.end_time:
            active_block = block
            break

    if not active_block:
        return None

    return {
        'red': int(active_block.red),
        'green': int(active_block.green),
        'blue': int(active_block.blue),
        'white': int(active_block.white),
        'amber': int(active_block.amber),
        'cyan': int(active_block.cyan),
        'magenta': int(active_block.magenta),
        'yellow': int(active_block.yellow),
        'uv': int(active_block.uv),
        'color_wheel': active_block.color_wheel_position
    }


def sample_special_at_time(
    time_s: float,
    special_blocks: List
) -> Optional[Dict[str, Any]]:
    """
    Sample the special effect values at a given time.

    Args:
        time_s: Time in seconds
        special_blocks: List of SpecialBlock objects

    Returns:
        Dict with special values or None if no special block at this time
    """
    # Find the special block at this time
    active_block = None
    for block in special_blocks:
        if block.start_time <= time_s < block.end_time:
            active_block = block
            break

    if not active_block:
        return None

    return {
        'gobo_index': active_block.gobo_index,
        'gobo_rotation': int(active_block.gobo_rotation),
        'focus': int(active_block.focus),
        'zoom': int(active_block.zoom),
        'prism_enabled': active_block.prism_enabled,
        'prism_rotation': int(active_block.prism_rotation)
    }


def build_unified_step(
    step_idx: int,
    time_s: float,
    step_duration_ms: int,
    fixtures: List,
    fixture_id_map: Dict,
    fixture_definitions: Dict,
    dimmer_blocks: List,
    colour_blocks: List,
    movement_blocks: List,
    special_blocks: List,
    total_steps: int,
    all_lane_fixtures: List = None,  # Full fixture list for cross-group effects
    bpm: float = 120.0,  # BPM for timing calculations
    signature: str = "4/4",  # Time signature for movement calculations
    config: Any = None,  # Configuration object for spot targeting
    export_overrides: dict = None
) -> ET.Element:
    """
    Build a single unified step with all channel values for all fixtures.

    Args:
        step_idx: Step index
        time_s: Time in seconds for this step
        step_duration_ms: Step duration in milliseconds
        fixtures: List of fixture objects for THIS track
        fixture_id_map: Dict mapping (universe, address) to fixture IDs
        fixture_definitions: Dict of fixture definitions
        dimmer_blocks: List of DimmerBlock objects
        colour_blocks: List of ColourBlock objects
        movement_blocks: List of MovementBlock objects
        special_blocks: List of SpecialBlock objects
        total_steps: Total number of steps in the sequence
        all_lane_fixtures: Full fixture list for cross-group effects (ping-pong, waterfall)
        bpm: BPM for timing calculations
        signature: Time signature for movement calculations
        config: Configuration object for spot targeting

    Returns:
        ET.Element for the Step
    """
    # Use all_lane_fixtures for effect calculations (cross-group effects)
    if all_lane_fixtures is None:
        all_lane_fixtures = fixtures

    total_fixtures_for_effects = len(all_lane_fixtures)

    # Build a lookup to find global fixture index from fixture object
    fixture_to_global_idx = {id(f): idx for idx, f in enumerate(all_lane_fixtures)}

    step = ET.Element("Step")
    step.set("Number", str(step_idx))
    step.set("FadeIn", "0")
    step.set("Hold", str(step_duration_ms))
    step.set("FadeOut", "0")

    values = []
    total_channel_count = 0

    for fixture_idx, fixture in enumerate(fixtures):
        fixture_id = fixture_id_map.get((fixture.universe, fixture.address))
        if fixture_id is None:
            continue

        # Get fixture definition
        fixture_key = f"{fixture.manufacturer}_{fixture.model}"
        fixture_def = fixture_definitions.get(fixture_key)
        if not fixture_def:
            continue

        channel_values = []

        # Get all channel mappings for this fixture
        all_presets = [
            "PositionPan", "PositionPanFine", "PositionTilt", "PositionTiltFine",
            "IntensityMasterDimmer", "IntensityDimmer",
            "IntensityRed", "IntensityGreen", "IntensityBlue", "IntensityWhite",
            "IntensityAmber", "IntensityCyan", "IntensityMagenta", "IntensityYellow", "IntensityUV",
            "ColorMacro", "ColorWheel", "Colour",  # Colour is group name for color wheel channels
            "GoboWheel", "Gobo", "GoboIndex",
            "GoboWheelRotation", "GoboRotation",
            "BeamFocusNearFar", "BeamFocusFarNear",
            "BeamZoomSmallBig", "BeamZoomBigSmall",
            "Prism", "PrismRotation",
            "ShutterStrobeSlowFast", "ShutterStrobeFastSlow",
            "SpeedPanTiltSlowFast", "SpeedPanTiltFastSlow"
        ]

        channels_dict = get_channels_by_property(fixture_def, fixture.current_mode, all_presets)
        if not channels_dict:
            values.append(f"{fixture_id}:")
            continue

        # Get global fixture index for cross-group effects (ping-pong, waterfall)
        global_fixture_idx = fixture_to_global_idx.get(id(fixture), fixture_idx)

        # Sample all effect types at this time
        # Use global_fixture_idx and total_fixtures_for_effects for cross-group effects
        _max_intensity = export_overrides.get('group_max_intensity', 255) if export_overrides else 255
        dimmer_value = sample_dimmer_at_time(time_s, dimmer_blocks, global_fixture_idx, total_fixtures_for_effects, step_idx, total_steps, bpm, max_intensity=_max_intensity)
        movement_values = sample_movement_at_time(time_s, movement_blocks, global_fixture_idx, total_fixtures_for_effects, step_idx, total_steps, bpm, signature, config, fixture)
        colour_values = sample_colour_at_time(time_s, colour_blocks)
        special_values = sample_special_at_time(time_s, special_blocks)

        # Find the active dimmer block to check for twinkle effect
        active_dimmer_block = None
        for block in dimmer_blocks:
            if block.start_time <= time_s < block.end_time:
                active_dimmer_block = block
                break

        # Set default values if no block is active
        if dimmer_value is None:
            dimmer_value = 0  # Default to off

        # If there's a dimmer value but no color block, default to white for RGB fixtures
        # This ensures pixel bars show the dimmer effect even without explicit color
        if colour_values is None and dimmer_value > 0:
            colour_values = {
                'red': 255,
                'green': 255,
                'blue': 255,
                'white': 255,
                'amber': 0,
                'cyan': 0,
                'magenta': 0,
                'yellow': 0,
                'uv': 0,
                'color_wheel': 0
            }

        # Build channel values

        # Pan/Tilt
        if movement_values:
            pan, tilt = movement_values
            for preset in ["PositionPan"]:
                if preset in channels_dict:
                    for ch in channels_dict[preset]:
                        channel_values.append(f"{ch['channel']},{pan}")
                        total_channel_count += 1
            for preset in ["PositionTilt"]:
                if preset in channels_dict:
                    for ch in channels_dict[preset]:
                        channel_values.append(f"{ch['channel']},{tilt}")
                        total_channel_count += 1

        # Check if fixture has RGB channels (for pixelbar twinkle handling)
        has_rgb_channels = any(
            preset in channels_dict for preset in ["IntensityRed", "IntensityGreen", "IntensityBlue"]
        )
        num_rgb_segments = len(channels_dict.get("IntensityRed", [])) if "IntensityRed" in channels_dict else 0

        # For pixelbars with sparkle or waterfall effect: set master dimmer to full intensity
        # The effect modulation is applied to the color channels instead
        is_pixelbar_sparkle = (
            active_dimmer_block and
            active_dimmer_block.effect_type == "sparkle" and
            has_rgb_channels and
            num_rgb_segments > 1
        )
        is_pixelbar_waterfall = (
            active_dimmer_block and
            active_dimmer_block.effect_type == "waterfall" and
            has_rgb_channels and
            num_rgb_segments > 1
        )

        # Dimmer
        for preset in ["IntensityMasterDimmer", "IntensityDimmer"]:
            if preset in channels_dict:
                for ch in channels_dict[preset]:
                    # For pixelbar twinkle/waterfall, set dimmer to block's base intensity
                    # (effect modulation happens in color channels)
                    if is_pixelbar_sparkle or is_pixelbar_waterfall:
                        dimmer_to_use = int(int(active_dimmer_block.intensity) * _max_intensity / 255)
                    else:
                        dimmer_to_use = dimmer_value
                    channel_values.append(f"{ch['channel']},{dimmer_to_use}")
                    total_channel_count += 1
                break  # Only use one dimmer preset

        # Color channels
        if colour_values:
            # Re-check RGB channels (already checked above, but keep consistent structure)
            has_rgb_channels = any(
                preset in channels_dict for preset in ["IntensityRed", "IntensityGreen", "IntensityBlue"]
            )
            # Check for color wheel - can be ColorMacro, ColorWheel preset, or Colour group
            has_color_wheel = any(
                preset in channels_dict for preset in ["ColorMacro", "ColorWheel", "Colour"]
            )

            # Apply RGB channels if fixture has them
            if has_rgb_channels:
                # Check if fixture has a white channel
                has_white_channel = "IntensityWhite" in channels_dict

                # Get base color values
                red_val = colour_values.get('red', 0)
                green_val = colour_values.get('green', 0)
                blue_val = colour_values.get('blue', 0)
                white_val = colour_values.get('white', 0)

                # RGBW to RGB conversion: if fixture has no white channel,
                # add the white value to R, G, B to approximate the color
                if not has_white_channel and white_val > 0:
                    red_val = min(255, red_val + white_val)
                    green_val = min(255, green_val + white_val)
                    blue_val = min(255, blue_val + white_val)
                    white_val = 0  # Clear white since we've converted it

                color_mappings = [
                    ("IntensityRed", red_val),
                    ("IntensityGreen", green_val),
                    ("IntensityBlue", blue_val),
                    ("IntensityWhite", white_val),
                    ("IntensityAmber", colour_values.get('amber', 0)),
                    ("IntensityCyan", colour_values.get('cyan', 0)),
                    ("IntensityMagenta", colour_values.get('magenta', 0)),
                    ("IntensityYellow", colour_values.get('yellow', 0)),
                    ("IntensityUV", colour_values.get('uv', 0)),
                ]

                # For pixelbar twinkle, each segment gets an independent random intensity
                if is_pixelbar_sparkle:
                    # Calculate per-segment twinkle intensities (matches ArtNet implementation)
                    import random
                    import hashlib

                    speed = active_dimmer_block.effect_speed
                    if '/' in speed:
                        num, denom = map(int, speed.split('/'))
                        speed_mult = num / denom
                    else:
                        speed_mult = float(speed)

                    time_in_block = time_s - active_dimmer_block.start_time
                    twinkle_step_duration = 0.2 / speed_mult
                    step_float = time_in_block / twinkle_step_duration
                    current_twinkle_step = int(step_float)
                    next_twinkle_step = current_twinkle_step + 1
                    transition_progress = step_float - current_twinkle_step

                    segment_intensities = []
                    for seg_idx in range(num_rgb_segments):
                        # Current target intensity
                        seed_str = f"fixture_{fixture_idx}_seg{seg_idx}_{current_twinkle_step}"
                        seed_hash = int(hashlib.md5(seed_str.encode()).hexdigest()[:8], 16)
                        random.seed(seed_hash)
                        current_variation = random.random() * 0.7 + 0.3

                        # Next target intensity
                        seed_str = f"fixture_{fixture_idx}_seg{seg_idx}_{next_twinkle_step}"
                        seed_hash = int(hashlib.md5(seed_str.encode()).hexdigest()[:8], 16)
                        random.seed(seed_hash)
                        next_variation = random.random() * 0.7 + 0.3

                        # Smooth interpolation
                        t = transition_progress
                        smooth_t = t * t * (3 - 2 * t)
                        variation = current_variation + (next_variation - current_variation) * smooth_t
                        segment_intensities.append(variation)

                    # Apply per-segment color values with twinkle
                    for preset, base_value in color_mappings:
                        if preset in channels_dict:
                            for seg_idx, ch in enumerate(channels_dict[preset]):
                                # Scale color value by segment's twinkle intensity
                                twinkle_factor = segment_intensities[seg_idx] if seg_idx < len(segment_intensities) else 1.0
                                scaled_value = int(base_value * twinkle_factor)
                                channel_values.append(f"{ch['channel']},{scaled_value}")
                                total_channel_count += 1

                elif is_pixelbar_waterfall:
                    # Calculate per-segment waterfall intensities (matches ArtNet implementation)
                    import hashlib

                    speed = active_dimmer_block.effect_speed
                    if '/' in speed:
                        num, denom = map(int, speed.split('/'))
                        speed_mult = num / denom
                    else:
                        speed_mult = float(speed)

                    time_in_block = time_s - active_dimmer_block.start_time
                    effect_type = active_dimmer_block.effect_type

                    # Calculate timing based on BPM: each segment gets one beat at speed 1
                    seconds_per_beat = 60.0 / bpm
                    time_per_step = seconds_per_beat / speed_mult

                    # Calculate random offset for this fixture (slowly drifting)
                    seed_str = f"waterfall_fixture_{global_fixture_idx}"
                    name_hash = int(hashlib.md5(seed_str.encode()).hexdigest()[:8], 16)
                    base_offset = (name_hash % 1000) / 1000.0  # 0.0 to 1.0

                    # Slowly drifting component (changes over ~30 seconds)
                    drift_period = 30.0
                    drift_phase = (time_s / drift_period) * 2 * math.pi
                    drift_seed = (name_hash % 997) / 997.0 * 2 * math.pi
                    drift_amount = 0.3 * math.sin(drift_phase + drift_seed)  # +/- 0.3 cycle drift

                    total_offset = base_offset + drift_amount

                    # Full cycle time = num_segments beats
                    cycle_time = time_per_step * num_rgb_segments

                    # Current position in cycle (0 to num_segments), with offset
                    cycle_progress = (time_in_block / cycle_time + total_offset) % 1.0
                    head_position = cycle_progress * num_rgb_segments  # 0 to num_segments

                    # For direction="down": head moves from last segment (N-1) to first (0)
                    # For direction="up": head moves from first segment (0) to last (N-1)
                    direction = getattr(active_dimmer_block, 'direction', 'down')
                    if direction == "down":
                        head_position = (num_rgb_segments - 1) - head_position
                    # For direction="up", head_position is already 0 to N-1

                    # Calculate intensity for each segment using circular/wrapped distance
                    segment_intensities = []
                    for seg_idx in range(num_rgb_segments):
                        # Calculate distance from head to this segment
                        if direction == "down":
                            raw_distance = seg_idx - head_position
                        else:  # direction="up"
                            raw_distance = head_position - seg_idx

                        # Use modulo to wrap the distance for continuous effect
                        circular_distance = raw_distance % num_rgb_segments

                        # Normalize and apply exponential decay
                        normalized_dist = circular_distance / num_rgb_segments
                        intensity_factor = math.exp(-1.5 * normalized_dist)
                        segment_intensities.append(intensity_factor)

                    # Apply per-segment color values with waterfall
                    for preset, base_value in color_mappings:
                        if preset in channels_dict:
                            for seg_idx, ch in enumerate(channels_dict[preset]):
                                # Scale color value by segment's waterfall intensity
                                waterfall_factor = segment_intensities[seg_idx] if seg_idx < len(segment_intensities) else 1.0
                                scaled_value = int(base_value * waterfall_factor)
                                channel_values.append(f"{ch['channel']},{scaled_value}")
                                total_channel_count += 1

                else:
                    # No twinkle/waterfall or single segment - apply uniform values
                    for preset, value in color_mappings:
                        if preset in channels_dict:
                            for ch in channels_dict[preset]:
                                channel_values.append(f"{ch['channel']},{value}")
                                total_channel_count += 1

            # Color wheel - for fixtures with color wheel channel
            if has_color_wheel:
                color_wheel = colour_values.get('color_wheel', 0)

                # If fixture has color wheel but no RGB, convert RGB to color wheel position
                # using the fixture's actual color capabilities
                if not has_rgb_channels and color_wheel == 0:
                    # Convert RGB values to hex color string
                    r = colour_values.get('red', 255)
                    g = colour_values.get('green', 255)
                    b = colour_values.get('blue', 255)
                    hex_color = f"#{r:02X}{g:02X}{b:02X}"

                    # Use fixture-specific color wheel mapping
                    matched_color = find_closest_color_dmx(channels_dict, hex_color, fixture_def)
                    if matched_color is not None:
                        color_wheel = matched_color
                    else:
                        # Fall back to generic mapping if fixture has no color capabilities
                        color_wheel = _map_rgb_to_color_wheel(r, g, b)

                color_channels_set = set()  # Track which channels we've already set
                for preset in ["ColorMacro", "ColorWheel", "Colour"]:
                    if preset in channels_dict:
                        for ch in channels_dict[preset]:
                            ch_num = ch['channel']
                            if ch_num not in color_channels_set:
                                channel_values.append(f"{ch_num},{color_wheel}")
                                total_channel_count += 1
                                color_channels_set.add(ch_num)
                        break

        # Special effects
        if special_values:
            # Gobo
            gobo_value = min(255, special_values.get('gobo_index', 0) * 25)
            for preset in ["GoboWheel", "Gobo", "GoboIndex"]:
                if preset in channels_dict:
                    for ch in channels_dict[preset]:
                        channel_values.append(f"{ch['channel']},{gobo_value}")
                        total_channel_count += 1
                    break

            # Gobo rotation
            gobo_rot = special_values.get('gobo_rotation', 0)
            for preset in ["GoboWheelRotation", "GoboRotation"]:
                if preset in channels_dict:
                    for ch in channels_dict[preset]:
                        channel_values.append(f"{ch['channel']},{gobo_rot}")
                        total_channel_count += 1
                    break

            # Focus
            focus = special_values.get('focus', 127)
            for preset in ["BeamFocusNearFar", "BeamFocusFarNear"]:
                if preset in channels_dict:
                    for ch in channels_dict[preset]:
                        channel_values.append(f"{ch['channel']},{focus}")
                        total_channel_count += 1
                    break

            # Zoom
            zoom = special_values.get('zoom', 127)
            for preset in ["BeamZoomSmallBig", "BeamZoomBigSmall"]:
                if preset in channels_dict:
                    for ch in channels_dict[preset]:
                        channel_values.append(f"{ch['channel']},{zoom}")
                        total_channel_count += 1
                    break

            # Prism
            prism_value = 128 if special_values.get('prism_enabled', False) else 0
            if "Prism" in channels_dict:
                for ch in channels_dict["Prism"]:
                    channel_values.append(f"{ch['channel']},{prism_value}")
                    total_channel_count += 1

        # Build fixture value string
        if channel_values:
            values.append(f"{fixture_id}:{','.join(channel_values)}")
        else:
            values.append(f"{fixture_id}:")

    # Drop zero-valued channels to match QLC+'s native saver convention
    # (engine/src/chaserstep.cpp:293). Absent channels render as 0 in the
    # scene, so playback is byte-identical and the file is ~30% smaller.
    compacted_values, nonzero_count = compact_step_values(values)
    step.set("Values", str(nonzero_count))
    step.text = ":".join(compacted_values)

    return step


def generate_unified_sequence_steps(
    fixtures: List,
    fixture_id_map: Dict,
    fixture_definitions: Dict,
    light_block,  # LightBlock object
    bpm: float,
    signature: str = "4/4",
    all_lane_fixtures: List = None,  # All fixtures in the lane for cross-group effects
    config: Any = None,  # Configuration object for spot targeting
    export_overrides: dict = None
) -> List[ET.Element]:
    """
    Generate unified sequence steps for a light block.

    Combines all effect types (dimmer, colour, movement, special) into
    a single sequence with synchronized timing.

    Args:
        fixtures: List of fixture objects for THIS track (one fixture group)
        fixture_id_map: Dict mapping (universe, address) to fixture IDs
        fixture_definitions: Dict of fixture definitions
        light_block: LightBlock object containing all effect blocks
        bpm: Beats per minute
        signature: Time signature
        all_lane_fixtures: All fixtures in the lane (for cross-group effects like ping-pong)
                          If None, uses fixtures (single-group behavior)
        config: Configuration object for spot targeting

    Returns:
        List of Step ET.Elements
    """
    # For cross-group effects, use the full lane fixture list
    if all_lane_fixtures is None:
        all_lane_fixtures = fixtures
    dimmer_blocks = light_block.dimmer_blocks if hasattr(light_block, 'dimmer_blocks') else []
    colour_blocks = light_block.colour_blocks if hasattr(light_block, 'colour_blocks') else []
    movement_blocks = light_block.movement_blocks if hasattr(light_block, 'movement_blocks') else []
    special_blocks = light_block.special_blocks if hasattr(light_block, 'special_blocks') else []

    # Debug: Log block counts
    print(f"        [unified_sequence] dimmer={len(dimmer_blocks)}, colour={len(colour_blocks)}, movement={len(movement_blocks)}, special={len(special_blocks)}")

    # Calculate the unified step grid
    step_times_ms, step_duration_ms = calculate_unified_step_grid(
        dimmer_blocks, colour_blocks, movement_blocks, special_blocks, bpm, signature
    )

    print(f"        [unified_sequence] step_times_ms count={len(step_times_ms)}, step_duration_ms={step_duration_ms}")

    if not step_times_ms:
        print(f"        [unified_sequence] Returning empty - no step times calculated")
        return []

    total_steps = len(step_times_ms)
    steps = []

    for step_idx, step_time_ms in enumerate(step_times_ms):
        time_s = step_time_ms / 1000.0

        step = build_unified_step(
            step_idx=step_idx,
            time_s=time_s,
            step_duration_ms=step_duration_ms,
            fixtures=fixtures,
            fixture_id_map=fixture_id_map,
            fixture_definitions=fixture_definitions,
            dimmer_blocks=dimmer_blocks,
            colour_blocks=colour_blocks,
            movement_blocks=movement_blocks,
            special_blocks=special_blocks,
            total_steps=total_steps,
            all_lane_fixtures=all_lane_fixtures,  # Pass full fixture list for cross-group effects
            bpm=bpm,  # Pass BPM for timing-based effects like ping-pong
            signature=signature,  # Pass signature for movement timing
            config=config,  # Pass config for spot targeting
            export_overrides=export_overrides
        )

        steps.append(step)

    # Merge consecutive steps with identical values to reduce file size
    merged_steps = merge_identical_steps(steps)

    return merged_steps


def merge_identical_steps(steps: List[ET.Element]) -> List[ET.Element]:
    """
    Merge consecutive steps that have identical channel values.

    This optimization reduces file size and improves QLC+ performance by
    combining steps where nothing changes into single steps with longer hold times.

    Args:
        steps: List of Step ET.Elements

    Returns:
        List of merged Step ET.Elements with renumbered step indices
    """
    if not steps or len(steps) <= 1:
        return steps

    merged = []
    current_step = steps[0]
    current_values = current_step.text
    current_hold = int(current_step.get("Hold", 0))

    for next_step in steps[1:]:
        next_values = next_step.text
        next_hold = int(next_step.get("Hold", 0))

        if next_values == current_values:
            # Same values - merge by adding hold times
            current_hold += next_hold
        else:
            # Different values - save current step and start new one
            merged_step = ET.Element("Step")
            merged_step.set("Number", str(len(merged)))
            merged_step.set("FadeIn", current_step.get("FadeIn", "0"))
            merged_step.set("Hold", str(current_hold))
            merged_step.set("FadeOut", current_step.get("FadeOut", "0"))
            merged_step.set("Values", current_step.get("Values", "0"))
            merged_step.text = current_values
            merged.append(merged_step)

            # Start tracking the new step
            current_step = next_step
            current_values = next_values
            current_hold = next_hold

    # Don't forget the last step
    merged_step = ET.Element("Step")
    merged_step.set("Number", str(len(merged)))
    merged_step.set("FadeIn", current_step.get("FadeIn", "0"))
    merged_step.set("Hold", str(current_hold))
    merged_step.set("FadeOut", current_step.get("FadeOut", "0"))
    merged_step.set("Values", current_step.get("Values", "0"))
    merged_step.text = current_values
    merged.append(merged_step)

    return merged
