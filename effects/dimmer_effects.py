import math
import random
import hashlib
from typing import Dict, Callable

from effects.types import DimmerContext, DimmerResult


# ──────────────────────────────────────────────
# Helper functions
# ──────────────────────────────────────────────

def _chase_bounce_calc(time_in_block, seconds_per_beat, speed_multiplier, num_items):
    """Shared bounce logic for chase effect.

    Returns (head_position, going_forward).
    """
    time_per_pass = (seconds_per_beat * 2) / speed_multiplier
    cycle_time = time_per_pass * 2
    time_in_cycle = time_in_block % cycle_time

    if time_in_cycle < time_per_pass:
        progress = time_in_cycle / time_per_pass
        head_position = progress * (num_items - 1)
        going_forward = True
    else:
        progress = (time_in_cycle - time_per_pass) / time_per_pass
        head_position = (num_items - 1) * (1.0 - progress)
        going_forward = False

    return head_position, going_forward


def _chase_tail_intensity(distance, tail_length):
    """Calculate intensity based on distance from chase head."""
    if distance < -0.5:
        return 0.0
    elif distance < 0.5:
        return 1.0
    elif distance <= tail_length:
        fade_factor = 1.0 - (distance / (tail_length + 1))
        return fade_factor * 0.8
    else:
        return 0.0


def _segmented_or_scalar(ctx, intensity_multiplier):
    """Return segment list or scalar based on fixture type."""
    if ctx.is_segmented:
        return DimmerResult(segment_intensities=[intensity_multiplier] * ctx.num_segments)
    else:
        return DimmerResult(intensity_multiplier=intensity_multiplier)


# ──────────────────────────────────────────────
# Effect functions (alphabetical by rudiment name)
# ──────────────────────────────────────────────

def cascade(ctx: DimmerContext) -> DimmerResult:
    """Accumulative build followed by sharp release. One-shot over block duration."""
    if ctx.block_duration <= 0:
        return DimmerResult(intensity_multiplier=1.0)

    progress = ctx.time_in_block / ctx.block_duration
    build_fraction = ctx.build_fraction

    if progress < build_fraction:
        # Build phase: ramp up
        build_progress = progress / build_fraction
        intensity_multiplier = build_progress
    else:
        # Release phase: sharp drop
        release_progress = (progress - build_fraction) / (1.0 - build_fraction)
        intensity_multiplier = max(0.0, 1.0 - release_progress * 3)

    return _segmented_or_scalar(ctx, intensity_multiplier)


def chase(ctx: DimmerContext) -> DimmerResult:
    """Sequential fixture activation bouncing back and forth (4 beat cycle).

    scope="fixture": each fixture's segments animate independently (was snake).
    scope="global": all fixtures treated as one continuous chain (was zigzag).
    """
    seconds_per_beat = 60.0 / ctx.bpm

    if ctx.chase_scope == "global":
        # Global scope: all segments across all fixtures as one chain
        if ctx.is_segmented:
            num_segments = ctx.num_segments
            total_segments = num_segments * ctx.total_fixtures
            global_segment_offset = ctx.fixture_index * num_segments
            tail_length = max(1, total_segments // 2)

            head_position, going_forward = _chase_bounce_calc(
                ctx.time_in_block, seconds_per_beat, ctx.speed_multiplier, total_segments
            )

            segment_intensities = []
            for seg_idx in range(num_segments):
                global_seg_pos = global_segment_offset + seg_idx
                if going_forward:
                    distance = head_position - global_seg_pos
                else:
                    distance = global_seg_pos - head_position
                segment_intensities.append(_chase_tail_intensity(distance, tail_length))

            return DimmerResult(segment_intensities=segment_intensities)
        else:
            tail_length = max(1, ctx.total_fixtures // 2)
            head_position, going_forward = _chase_bounce_calc(
                ctx.time_in_block, seconds_per_beat, ctx.speed_multiplier, ctx.total_fixtures
            )
            if going_forward:
                distance = head_position - ctx.fixture_index
            else:
                distance = ctx.fixture_index - head_position
            return DimmerResult(intensity_multiplier=_chase_tail_intensity(distance, tail_length))
    else:
        # Fixture scope: each fixture animates independently
        if ctx.is_segmented:
            num_segments = ctx.num_segments
            tail_length = max(1, num_segments // 2)

            head_position, going_forward = _chase_bounce_calc(
                ctx.time_in_block, seconds_per_beat, ctx.speed_multiplier, num_segments
            )

            segment_intensities = []
            for seg_idx in range(num_segments):
                if going_forward:
                    distance = head_position - seg_idx
                else:
                    distance = seg_idx - head_position
                segment_intensities.append(_chase_tail_intensity(distance, tail_length))

            return DimmerResult(segment_intensities=segment_intensities)
        else:
            tail_length = max(1, ctx.total_fixtures // 2)
            head_position, going_forward = _chase_bounce_calc(
                ctx.time_in_block, seconds_per_beat, ctx.speed_multiplier, ctx.total_fixtures
            )
            if going_forward:
                distance = head_position - ctx.fixture_index
            else:
                distance = ctx.fixture_index - head_position
            return DimmerResult(intensity_multiplier=_chase_tail_intensity(distance, tail_length))


def fade(ctx: DimmerContext) -> DimmerResult:
    """Linear intensity ramp over block duration. One-shot.

    direction="in": ramp from 0 to 1.
    direction="out": ramp from 1 to 0.
    """
    if ctx.block_duration <= 0:
        return DimmerResult(intensity_multiplier=1.0)

    progress = ctx.time_in_block / ctx.block_duration
    progress = max(0.0, min(1.0, progress))

    if ctx.direction == "out":
        intensity_multiplier = 1.0 - progress
    else:
        intensity_multiplier = progress

    return _segmented_or_scalar(ctx, intensity_multiplier)


def fill(ctx: DimmerContext) -> DimmerResult:
    """Fills from center outward, then unfills back (4 beat cycle)."""
    seconds_per_beat = 60.0 / ctx.bpm

    if ctx.is_segmented:
        num_segments = ctx.num_segments
        time_per_phase = (seconds_per_beat * 2) / ctx.speed_multiplier
        cycle_time = time_per_phase * 2
        time_in_cycle = ctx.time_in_block % cycle_time

        if time_in_cycle < time_per_phase:
            fill_progress = time_in_cycle / time_per_phase
        else:
            fill_progress = 1.0 - ((time_in_cycle - time_per_phase) / time_per_phase)

        center = (num_segments - 1) / 2.0
        max_distance = center
        current_fill_distance = fill_progress * max_distance

        segment_intensities = []
        for seg_idx in range(num_segments):
            distance_from_center = abs(seg_idx - center)

            if distance_from_center <= current_fill_distance:
                if current_fill_distance > 0 and distance_from_center > current_fill_distance - 1:
                    edge_progress = current_fill_distance - distance_from_center
                    intensity_factor = min(1.0, edge_progress + 0.2)
                else:
                    intensity_factor = 1.0
            else:
                intensity_factor = 0.0

            segment_intensities.append(intensity_factor)

        return DimmerResult(segment_intensities=segment_intensities)
    else:
        time_per_phase = (seconds_per_beat * 2) / ctx.speed_multiplier
        cycle_time = time_per_phase * 2
        time_in_cycle = ctx.time_in_block % cycle_time

        if time_in_cycle < time_per_phase:
            intensity_multiplier = 1.0
        else:
            intensity_multiplier = 0.0

        return DimmerResult(intensity_multiplier=intensity_multiplier)


def heartbeat(ctx: DimmerContext) -> DimmerResult:
    """Double-pulse pattern (bump-bump... pause...), one cycle per bar."""
    seconds_per_beat = 60.0 / ctx.bpm
    seconds_per_bar = seconds_per_beat * 4
    cycle_time = seconds_per_bar / ctx.speed_multiplier

    cycle_pos = (ctx.time_in_block % cycle_time) / cycle_time
    floor = 0.2

    if cycle_pos < 0.10:
        beat_level = floor + (1.0 - floor) * (cycle_pos / 0.10)
    elif cycle_pos < 0.20:
        beat_level = 1.0 - (1.0 - 0.6) * ((cycle_pos - 0.10) / 0.10)
    elif cycle_pos < 0.30:
        beat_level = 0.6 + (0.8 - 0.6) * ((cycle_pos - 0.20) / 0.10)
    elif cycle_pos < 0.50:
        beat_level = 0.8 - (0.8 - floor) * ((cycle_pos - 0.30) / 0.20)
    else:
        beat_level = floor

    return _segmented_or_scalar(ctx, beat_level)


def ping_pong(ctx: DimmerContext) -> DimmerResult:
    """One fixture lights up at a time, bouncing back and forth with smooth fade."""
    if ctx.total_fixtures <= 1:
        intensity_multiplier = 1.0
    else:
        seconds_per_beat = 60.0 / ctx.bpm
        time_per_fixture = seconds_per_beat / ctx.speed_multiplier

        steps_in_cycle = (ctx.total_fixtures - 1) * 2
        cycle_time = time_per_fixture * steps_in_cycle

        time_in_cycle = ctx.time_in_block % cycle_time
        current_step = time_in_cycle / time_per_fixture
        step_index = int(current_step)
        time_within_step = (current_step - step_index) * time_per_fixture

        if step_index < (ctx.total_fixtures - 1):
            active_fixture = step_index
        else:
            active_fixture = steps_in_cycle - step_index

        if ctx.fixture_index == active_fixture:
            decay_progress = time_within_step / time_per_fixture
            intensity_multiplier = 0.2 + 0.8 * math.exp(-decay_progress * 3)
        elif ctx.fixture_index == (active_fixture - 1) or ctx.fixture_index == (active_fixture + 1):
            prev_fixture = active_fixture - 1 if step_index < (ctx.total_fixtures - 1) else active_fixture + 1
            if ctx.fixture_index == prev_fixture and time_within_step < time_per_fixture * 0.3:
                tail_progress = time_within_step / (time_per_fixture * 0.3)
                intensity_multiplier = 0.3 * (1.0 - tail_progress)
            else:
                intensity_multiplier = 0.0
        else:
            intensity_multiplier = 0.0

    return _segmented_or_scalar(ctx, intensity_multiplier)


def pulse(ctx: DimmerContext) -> DimmerResult:
    """Smooth sine breathing, one cycle per bar. Optional per-fixture phase spread."""
    seconds_per_beat = 60.0 / ctx.bpm
    seconds_per_bar = seconds_per_beat * 4
    cycle_time = seconds_per_bar / ctx.speed_multiplier

    # Optional per-fixture phase offset
    if ctx.phase_offset_per_fixture and ctx.total_fixtures > 1:
        phase_offset = (ctx.fixture_index / ctx.total_fixtures) * cycle_time
    else:
        phase_offset = 0.0

    phase = ((ctx.time_in_block + phase_offset) / cycle_time) * 2 * math.pi
    floor = 0.3
    intensity_multiplier = floor + (1 - floor) * (math.sin(phase) + 1) / 2

    return _segmented_or_scalar(ctx, intensity_multiplier)


def random_stroke(ctx: DimmerContext) -> DimmerResult:
    """One fixture lights up at a time in shuffled order (deck of cards)."""
    if ctx.total_fixtures <= 1:
        intensity_multiplier = 1.0
    else:
        seconds_per_beat = 60.0 / ctx.bpm
        time_per_fixture = seconds_per_beat / ctx.speed_multiplier
        cycle_time = time_per_fixture * ctx.total_fixtures
        cycle_number = int(ctx.time_in_block / cycle_time)
        time_in_cycle = ctx.time_in_block % cycle_time
        current_step = time_in_cycle / time_per_fixture
        step_index = int(current_step)
        time_within_step = (current_step - step_index) * time_per_fixture

        seed = int(ctx.block_start_time * 1000) + cycle_number
        rng = random.Random(seed)
        shuffled_indices = list(range(ctx.total_fixtures))
        rng.shuffle(shuffled_indices)

        active_fixture = shuffled_indices[step_index % ctx.total_fixtures]

        if ctx.fixture_index == active_fixture:
            decay_progress = time_within_step / time_per_fixture
            intensity_multiplier = 0.2 + 0.8 * math.exp(-decay_progress * 3)
        else:
            intensity_multiplier = 0.0

    return _segmented_or_scalar(ctx, intensity_multiplier)


def sparkle(ctx: DimmerContext) -> DimmerResult:
    """Each segment/channel gets independent random intensity with smooth transitions."""
    step_duration = 0.2 / ctx.speed_multiplier
    step_float = ctx.time_in_block / step_duration
    current_step = int(step_float)
    next_step = current_step + 1
    transition_progress = step_float - current_step

    # Local Random instances: this runs on the arbiter thread and must
    # never reseed the global RNG other code draws from.
    segment_intensities = []
    for seg_idx in range(ctx.num_segments):
        seed_str = f"{ctx.fixture_name}_seg{seg_idx}_{current_step}"
        seed_hash = int(hashlib.md5(seed_str.encode()).hexdigest()[:8], 16)
        current_variation = random.Random(seed_hash).random() * 0.7 + 0.3

        seed_str = f"{ctx.fixture_name}_seg{seg_idx}_{next_step}"
        seed_hash = int(hashlib.md5(seed_str.encode()).hexdigest()[:8], 16)
        next_variation = random.Random(seed_hash).random() * 0.7 + 0.3

        t = transition_progress
        smooth_t = t * t * (3 - 2 * t)
        variation = current_variation + (next_variation - current_variation) * smooth_t
        segment_intensities.append(variation)

    return DimmerResult(segment_intensities=segment_intensities)


def static(ctx: DimmerContext) -> DimmerResult:
    """All fixtures at constant intensity."""
    return DimmerResult(intensity_multiplier=1.0)


def strobe(ctx: DimmerContext) -> DimmerResult:
    """Rapid on/off flashing at calculated frequency."""
    strobe_hz = 2.0 * ctx.speed_multiplier
    phase = (ctx.time_in_block * strobe_hz) % 1.0
    multiplier = 1.0 if phase < 0.5 else 0.0
    return DimmerResult(intensity_multiplier=multiplier)


def stroke(ctx: DimmerContext) -> DimmerResult:
    """Instant attack to full intensity, decay over the beat."""
    seconds_per_beat = 60.0 / ctx.bpm
    time_per_hit = seconds_per_beat / ctx.speed_multiplier
    time_in_cycle = ctx.time_in_block % time_per_hit

    decay_progress = time_in_cycle / time_per_hit
    intensity_multiplier = math.exp(-decay_progress * 3)

    return _segmented_or_scalar(ctx, intensity_multiplier)


def throb(ctx: DimmerContext) -> DimmerResult:
    """Sharp attack to full, exponential decay to 70% floor, synced to BPM."""
    seconds_per_beat = 60.0 / ctx.bpm
    time_per_pulse = seconds_per_beat / ctx.speed_multiplier
    time_in_cycle = ctx.time_in_block % time_per_pulse

    min_intensity = 0.7
    decay_progress = time_in_cycle / time_per_pulse
    intensity_multiplier = min_intensity + (1.0 - min_intensity) * math.exp(-decay_progress * 4)

    return _segmented_or_scalar(ctx, intensity_multiplier)


def waterfall(ctx: DimmerContext) -> DimmerResult:
    """Light cascades through segments with drifting offset.

    direction="down": head moves from last to first segment.
    direction="up": head moves from first to last segment.
    """
    seconds_per_beat = 60.0 / ctx.bpm
    time_per_step = seconds_per_beat / ctx.speed_multiplier
    direction_down = (ctx.direction == "down")

    if ctx.is_segmented:
        num_segments = ctx.num_segments

        name_hash = int(hashlib.md5(ctx.fixture_name.encode()).hexdigest()[:8], 16)
        base_offset = (name_hash % 1000) / 1000.0

        drift_period = 30.0
        current_time = ctx.block_start_time + ctx.time_in_block
        drift_phase = (current_time / drift_period) * 2 * math.pi
        drift_seed = (name_hash % 997) / 997.0 * 2 * math.pi
        drift_amount = 0.3 * math.sin(drift_phase + drift_seed)

        total_offset = base_offset + drift_amount

        cycle_time = time_per_step * num_segments
        cycle_progress = (ctx.time_in_block / cycle_time + total_offset) % 1.0
        head_position = cycle_progress * num_segments

        if direction_down:
            head_position = (num_segments - 1) - head_position

        segment_intensities = []
        for seg_idx in range(num_segments):
            if direction_down:
                raw_distance = seg_idx - head_position
            else:
                raw_distance = head_position - seg_idx

            circular_distance = raw_distance % num_segments
            normalized_dist = circular_distance / num_segments
            intensity_factor = math.exp(-1.5 * normalized_dist)
            segment_intensities.append(intensity_factor)

        return DimmerResult(segment_intensities=segment_intensities)
    else:
        return DimmerResult(intensity_multiplier=1.0)


def wave(ctx: DimmerContext) -> DimmerResult:
    """Intensity wave travels across fixtures like a stadium wave, one cycle per bar."""
    seconds_per_beat = 60.0 / ctx.bpm
    seconds_per_bar = seconds_per_beat * 4
    cycle_time = seconds_per_bar / ctx.speed_multiplier

    wavelength = max(2, ctx.total_fixtures / 2)
    time_progress = ctx.time_in_block / cycle_time
    wave_pos = 2 * math.pi * (ctx.fixture_index / wavelength - time_progress)
    intensity_multiplier = (math.sin(wave_pos) + 1) / 2

    return _segmented_or_scalar(ctx, intensity_multiplier)


# ──────────────────────────────────────────────
# Registry
# ──────────────────────────────────────────────

DIMMER_REGISTRY: Dict[str, Callable[[DimmerContext], DimmerResult]] = {
    "static": static,
    "stroke": stroke,
    "throb": throb,
    "ping_pong": ping_pong,
    "chase": chase,
    "wave": wave,
    "waterfall": waterfall,
    "fill": fill,
    "random_stroke": random_stroke,
    "sparkle": sparkle,
    "pulse": pulse,
    "strobe": strobe,
    "fade": fade,
    "cascade": cascade,
    "heartbeat": heartbeat,
}
