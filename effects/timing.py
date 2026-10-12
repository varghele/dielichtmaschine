def parse_speed(speed: str) -> float:
    """Parse speed string to multiplier.

    Args:
        speed: Speed string like "1", "2", "1/2", "1/4"

    Returns:
        Speed multiplier as float
    """
    if '/' in speed:
        parts = speed.split('/')
        try:
            return float(parts[0]) / float(parts[1])
        except (ValueError, ZeroDivisionError):
            return 1.0
    else:
        try:
            return float(speed)
        except ValueError:
            return 1.0


# How many full movement-shape cycles occur per bar at effect speed "1".
# Movement authored at 1 cycle/bar read as ~4x too fast in practice, so the
# default is one cycle per 4 bars (0.25); effect-speed multipliers scale from
# there ("2" -> one cycle per 2 bars, "1/2" -> one per 8 bars).
MOVEMENT_CYCLES_PER_BAR = 0.25


# Movement counts time in BEATS: one "bar" of the cycle rate above is
# always 4 beats, whatever the song part's time signature (decision
# 2026-10-12). Native playback always worked this way; the export used
# to measure the bar in the part's meter, so a 2/4 part exported its
# movement twice as fast as the rig played it. Dimmer effects count in
# beats too.
MOVEMENT_BEATS_PER_BAR = 4


def movement_seconds_per_bar(bpm: float) -> float:
    """Length of the movement cycle-rate "bar" at ``bpm`` (4 beats)."""
    return 60.0 / bpm * MOVEMENT_BEATS_PER_BAR


def movement_total_cycles(block_duration: float, seconds_per_bar: float, speed_multiplier: float) -> float:
    """Number of full movement-shape cycles across a movement block.

    Single source of truth shared by the real-time DMX path and both QLC+
    exporters so preview and exported ``.qxw`` stay in lockstep. Returns 0 for
    non-positive durations.
    """
    if block_duration <= 0 or seconds_per_bar <= 0:
        return 0.0
    return (block_duration / seconds_per_bar) * speed_multiplier * MOVEMENT_CYCLES_PER_BAR


def get_bpm(song_structure, current_time: float) -> float:
    """Get BPM from song structure, defaulting to 120.

    Args:
        song_structure: SongStructure instance or None
        current_time: Current playback time in seconds

    Returns:
        BPM as float
    """
    if song_structure:
        return song_structure.get_bpm_at_time(current_time)
    return 120.0
