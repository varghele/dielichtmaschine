# unified_sequence.py
# Functions for creating unified QLC+ sequences that combine all effect types

import math
import xml.etree.ElementTree as ET
from typing import List, Dict, Any, Optional, Tuple
from config.models import primary_group
from utils.effects_utils import get_channels_by_property, find_closest_color_dmx
from utils.yoke import export_aim_dmx  # noqa: F401 (aiming moved to the yoke helper)
from utils.to_xml.step_compaction import compact_step_values
from effects import (
    DIMMER_REGISTRY, MOVEMENT_REGISTRY, DimmerContext, DimmerResult,
    MovementContext, parse_speed,
)
from effects.timing import movement_seconds_per_bar, movement_total_cycles


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
        speed_mult = parse_speed(block.effect_speed)

        # Calculate the step interval needed for this effect type
        if block.effect_type == "static":
            # Static effects only need steps at block boundaries
            # We'll handle this with block boundary detection below
            pass
        elif block.effect_type == "strobe":
            # Strobe needs fast steps - half beat per toggle
            step_interval = (ms_per_beat / speed_mult) / 2
            min_step_interval_ms = min(min_step_interval_ms, step_interval)
        elif block.effect_type in ("stroke", "throb"):
            # Stroke and throb need fine steps to show the per-beat decay
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
        elif block.effect_type in ("pulse", "wave", "heartbeat", "fade", "cascade"):
            # Smooth animated effects need fine steps for visual quality
            # Use ~16 steps per bar for smooth sine waves, the heartbeat
            # pattern and the fade / cascade ramps
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


def _dimmer_context(
    active_block,
    time_s: float,
    fixture_idx: int,
    total_fixtures: int,
    bpm: float,
    fixture_name: str,
    num_segments: int = 1,
    is_segmented: bool = False
) -> DimmerContext:
    """The DimmerContext the native renderer builds for the same block
    and instant (utils/artnet/dmx_manager._apply_dimmer_block), so the
    export samples the very effect functions that go on the wire."""
    return DimmerContext(
        time_in_block=time_s - active_block.start_time,
        block_duration=active_block.end_time - active_block.start_time,
        intensity=active_block.intensity,
        speed_multiplier=parse_speed(active_block.effect_speed),
        bpm=bpm,
        fixture_index=fixture_idx,
        total_fixtures=total_fixtures,
        num_segments=num_segments,
        fixture_name=fixture_name,
        block_start_time=active_block.start_time,
        is_segmented=is_segmented,
        direction=getattr(active_block, 'direction', 'down'),
        chase_scope=getattr(active_block, 'chase_scope', 'fixture'),
        phase_offset_per_fixture=getattr(
            active_block, 'phase_offset_per_fixture', False),
        build_fraction=getattr(active_block, 'build_fraction', 0.7),
    )


def _run_dimmer_effect(ctx: DimmerContext, effect_type: str) -> DimmerResult:
    """Dispatch like the native renderer: unknown effects are static."""
    effect_fn = DIMMER_REGISTRY.get(effect_type, DIMMER_REGISTRY["static"])
    return effect_fn(ctx)


_COLOUR_SEGMENT_PRESETS = ("IntensityRed", "IntensityGreen",
                           "IntensityBlue", "IntensityWhite")


def _segmented_dimmer_plan(fixture, channels_dict, active_block, time_s,
                           fixture_idx, total_fixtures, bpm, max_intensity):
    """How a dimmer effect lands on a segmented fixture, mirroring the
    native renderer's classification and result handling
    (utils/artnet/dmx_manager._apply_dimmer_block / _apply_dimmer_result).

    Returns ``(segment_factors, master_override, dimmer_per_channel)``:

    - colour-segmented bar: ``segment_factors`` scales each segment's
      colour channels and ``master_override`` is the dimmer value (the
      block level); a scalar result is spread over the segments on
      PIXELBAR / BAR only, like native;
    - dimmer-only segments (sunstrips): ``dimmer_per_channel`` holds one
      value per dimmer channel;
    - anything else: all three None, the per-fixture path applies.
    """
    if active_block is None:
        return None, None, None
    fixture_type = getattr(fixture, "type", "") or ""
    if fixture_type not in ("PIXELBAR", "BAR", "SUNSTRIP"):
        return None, None, None
    dimmer_channels = []
    for preset in ("IntensityMasterDimmer", "IntensityDimmer"):
        if preset in channels_dict:
            dimmer_channels = channels_dict[preset]
            break
    has_color_segments = bool(channels_dict.get("IntensityRed")
                              or channels_dict.get("IntensityWhite"))
    if not (has_color_segments or len(dimmer_channels) > 1):
        return None, None, None

    if has_color_segments:
        num_segments = max(max(len(channels_dict.get(p, []))
                               for p in _COLOUR_SEGMENT_PRESETS), 1)
    else:
        num_segments = len(dimmer_channels)
    ctx = _dimmer_context(active_block, time_s, fixture_idx, total_fixtures,
                          bpm, fixture.name, num_segments=num_segments,
                          is_segmented=True)
    result = _run_dimmer_effect(ctx, active_block.effect_type)
    base = int(int(active_block.intensity) * max_intensity / 255)

    if result.segment_intensities is not None:
        if has_color_segments:
            return list(result.segment_intensities), base, None
        return None, None, [int(base * f) for f in result.segment_intensities]
    if has_color_segments and fixture_type in ("PIXELBAR", "BAR"):
        return [result.intensity_multiplier] * num_segments, base, None
    if has_color_segments:
        # SUNSTRIP-typed fixture with colour cells and a scalar result:
        # native takes the regular per-fixture path.
        return None, None, None
    value = int(base * result.intensity_multiplier)
    return None, None, [value] * len(dimmer_channels)


def sample_dimmer_at_time(
    time_s: float,
    dimmer_blocks: List,
    fixture_idx: int,
    total_fixtures: int,
    step_idx: int,
    total_steps: int,
    bpm: float = 120.0,
    max_intensity: int = 255,
    fixture_name: Optional[str] = None
) -> Optional[int]:
    """
    Sample the dimmer intensity at a given time.

    The effect itself comes from effects.DIMMER_REGISTRY, the same
    functions the native renderer puts on the wire, evaluated for a
    non-segmented fixture (pixel-bar segments are handled in
    build_unified_step).

    Args:
        time_s: Time in seconds
        dimmer_blocks: List of DimmerBlock objects
        fixture_idx: Index of this fixture in the group (for per-fixture effects)
        total_fixtures: Total number of fixtures in the group
        step_idx: Current step index (for animated effects)
        total_steps: Total number of steps
        bpm: Beats per minute for timing calculations
        max_intensity: Maximum intensity for this group (0-255), scales proportionally
        fixture_name: Fixture name; seeds the random effects (sparkle)
            exactly like native playback. Falls back to the index.

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

    if fixture_name is None:
        fixture_name = f"fixture_{fixture_idx}"
    ctx = _dimmer_context(active_block, time_s, fixture_idx, total_fixtures,
                          bpm, fixture_name)
    result = _run_dimmer_effect(ctx, effect_type)
    # A non-segmented fixture with one dimmer channel: the native
    # renderer uses the first per-channel intensity when an effect
    # (sparkle) returns a list.
    if result.segment_intensities:
        multiplier = result.segment_intensities[0]
    else:
        multiplier = result.intensity_multiplier
    return int(base_intensity * multiplier)


def _solver_aim(config, fixture, target):
    """Solver-convention 8-bit aim at a world target, real ranges."""
    from utils.yoke import export_solver_aim_dmx
    group = primary_group(config, fixture)
    mounting, yaw, pitch, roll = fixture.get_effective_orientation(group)
    fixture_z = fixture.get_effective_z(group)
    return export_solver_aim_dmx(fixture, fixture_z, target,
                                 mounting, yaw, pitch, roll)


def _stage_planes_for(config):
    """Stage planes for world-space movement export, cached per config
    (compute_stage_planes walks the whole rig; exports sample hundreds
    of steps)."""
    cache = getattr(config, '_export_stage_planes', None)
    if cache is None:
        from autogen.spatial import compute_stage_planes
        cache = {plane.name: plane
                 for plane in compute_stage_planes(config)}
        try:
            config._export_stage_planes = cache
        except AttributeError:
            pass
    return cache


def _solver_shape_position(t, progress, total_cycles, active_block,
                           center_pan, center_tilt,
                           pan_amplitude, tilt_amplitude,
                           fixture_idx, total_fixtures):
    """The movement shape in solver DMX space (shared by the
    centre-based paths and, normalized, by the world-plane path):
    effects.MOVEMENT_REGISTRY, the same shape functions the native
    renderer puts on the wire. Unknown shapes park on the centre."""
    ctx = MovementContext(
        t=t, progress=progress, total_cycles=total_cycles,
        center_pan=center_pan, center_tilt=center_tilt,
        pan_amplitude=pan_amplitude, tilt_amplitude=tilt_amplitude,
        fixture_index=fixture_idx, total_fixtures=total_fixtures,
        phase_offset_enabled=active_block.phase_offset_enabled,
        phase_offset_degrees=active_block.phase_offset_degrees,
        lissajous_ratio=active_block.lissajous_ratio,
    )
    shape_fn = MOVEMENT_REGISTRY.get(active_block.effect_type,
                                     MOVEMENT_REGISTRY["static"])
    result = shape_fn(ctx)
    return result.pan, result.tilt


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

    # Check if we have a target spot - if so, calculate pan/tilt to point at it
    spot = None
    if active_block.target_spot_name and config and fixture and hasattr(config, 'spots'):
        spot = config.spots.get(active_block.target_spot_name)
    point = getattr(active_block, 'target_point', None)
    if spot:
        # Aim with the solver at the definition's real ranges,
        # UNCONVERTED: the shape math below runs in solver DMX
        # space (exactly like the native renderer), and the WHOLE
        # step converts to the real yoke at the end
        # (convert_solver_dmx) - so QLC+ playback traces the same
        # figure the app and the rig do. Before 2026-07-13 only
        # the centre was converted and the pattern oscillated in
        # solver space around it, a mixed frame that traced the
        # wrong figure on a real head.
        pan_dmx, tilt_dmx = _solver_aim(
            config, fixture, (spot.x, spot.y, spot.z))

        # Use calculated values as center position
        center_pan = float(pan_dmx)
        center_tilt = float(tilt_dmx)
    elif point and config and fixture:
        # Ad-hoc world point (v1.5a): a spot without a name. A spot
        # NAME this config does not know (a morphed show carrying rig
        # A's names) falls through to here too, like the native
        # renderer (plane > spot > point > manual).
        pan_dmx, tilt_dmx = _solver_aim(
            config, fixture, (point[0], point[1], point[2]))
        center_pan = float(pan_dmx)
        center_tilt = float(tilt_dmx)
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

    speed_mult = parse_speed(active_block.effect_speed)

    # Movement counts in beats (4 per bar unit) whatever the meter, the
    # same rule native playback uses (effects.timing); ``signature`` no
    # longer changes the cycle rate.
    seconds_per_bar = movement_seconds_per_bar(bpm)

    # Calculate time within block
    block_duration = active_block.end_time - active_block.start_time
    time_in_block = time_s - active_block.start_time

    # Calculate relative position for progress (0 to 1)
    progress = time_in_block / block_duration if block_duration > 0 else 0

    # Shared movement rate (matches ArtNet preview + shows_to_xml export).
    total_cycles = movement_total_cycles(block_duration, seconds_per_bar, speed_mult)

    # Calculate phase offset for this fixture (t-based shapes; the
    # polygon shapes apply it from progress inside the registry)
    if active_block.phase_offset_enabled and total_fixtures > 1:
        fixture_phase = (fixture_idx * active_block.phase_offset_degrees) * math.pi / 180.0
    else:
        fixture_phase = 0.0

    # Calculate angle based on progress and total cycles
    t = 2 * math.pi * total_cycles * progress + fixture_phase

    # World-space plane rendering (v1.5a: export parity with the native
    # renderer, which has had this path since the plane work): the shape
    # runs NORMALIZED, its offsets land on the plane in metres, and each
    # step's world target aims per fixture at the real ranges. Takes
    # priority over spot/point/manual centres, matching dmx_manager.
    plane = None
    if getattr(active_block, 'target_plane_name', None) and config and fixture:
        plane = _stage_planes_for(config).get(active_block.target_plane_name)
    if plane is not None:
        norm_pan, norm_tilt = _solver_shape_position(
            t, progress, total_cycles, active_block,
            127.5, 127.5, 50.0, 50.0, fixture_idx, total_fixtures)
        u_offset = (norm_pan - 127.5) / 50.0
        v_offset = (norm_tilt - 127.5) / 50.0
        # Same DMX-units -> metres convention as the native renderer.
        amplitude_meters = active_block.pan_amplitude / 20.0
        target = tuple(
            plane.point[i]
            + u_offset * amplitude_meters * plane.u_axis[i]
            + v_offset * amplitude_meters * plane.v_axis[i]
            for i in range(3))
        pan, tilt = (float(v) for v in _solver_aim(config, fixture, target))
    else:
        pan, tilt = _solver_shape_position(
            t, progress, total_cycles, active_block,
            center_pan, center_tilt, pan_amplitude, tilt_amplitude,
            fixture_idx, total_fixtures)

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
        'lime': int(active_block.lime),
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
            "IntensityLime",
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
        dimmer_value = sample_dimmer_at_time(time_s, dimmer_blocks, global_fixture_idx, total_fixtures_for_effects, step_idx, total_steps, bpm, max_intensity=_max_intensity, fixture_name=fixture.name)
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

        # No colour block: no colour channels, so a dimmer alone leaves an
        # RGB fixture dark, like native playback (decision 2026-10-13;
        # the export used to light it full white).

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

        # Segmented fixtures (pixel bars, sunstrips): every dimmer effect
        # runs per segment, classified exactly like the native renderer
        # (utils/artnet/dmx_manager._apply_dimmer_block / _apply_dimmer_result).
        segment_factors, master_override, dimmer_per_channel = (
            _segmented_dimmer_plan(
                fixture, channels_dict, active_dimmer_block, time_s,
                global_fixture_idx, total_fixtures_for_effects, bpm,
                _max_intensity))

        # Dimmer
        for preset in ["IntensityMasterDimmer", "IntensityDimmer"]:
            if preset in channels_dict:
                for seg_idx, ch in enumerate(channels_dict[preset]):
                    if dimmer_per_channel is not None:
                        dimmer_to_use = (dimmer_per_channel[seg_idx]
                                         if seg_idx < len(dimmer_per_channel) else 0)
                    elif master_override is not None:
                        # Colour-segmented bar: the master holds the block
                        # level, the effect modulates the colour channels.
                        dimmer_to_use = master_override
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
                    ("IntensityLime", colour_values.get('lime', 0)),
                ]

                # Colour-segmented bars: each segment's colour is scaled by
                # its intensity from the shared effect (see the plan above).
                if segment_factors is not None:
                    segment_intensities = segment_factors

                    # Scale every segment's colour by its intensity
                    for preset, base_value in color_mappings:
                        if preset in channels_dict:
                            for seg_idx, ch in enumerate(channels_dict[preset]):
                                factor = segment_intensities[seg_idx] if seg_idx < len(segment_intensities) else 1.0
                                scaled_value = int(base_value * factor)
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
