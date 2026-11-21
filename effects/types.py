from dataclasses import dataclass
from typing import List, Optional


@dataclass
class DimmerContext:
    """All inputs a dimmer effect needs to compute intensity."""
    time_in_block: float
    block_duration: float
    intensity: float              # 0-255
    speed_multiplier: float
    bpm: float
    fixture_index: int
    total_fixtures: int
    num_segments: int
    fixture_name: str
    block_start_time: float
    is_segmented: bool
    # Rudiment parameters
    direction: str = "down"               # "down"/"up" (waterfall), "in"/"out" (fade)
    chase_scope: str = "fixture"          # "fixture" or "global" (chase)
    phase_offset_per_fixture: bool = False # per-fixture phase spread (pulse)
    build_fraction: float = 0.7           # build portion of cascade (0.0-1.0)


@dataclass
class DimmerResult:
    """Output from a dimmer effect computation.

    For non-segmented fixtures, intensity_multiplier is used (0.0-1.0).
    For segmented fixtures, segment_intensities takes precedence (list of 0.0-1.0).
    """
    intensity_multiplier: float = 1.0
    segment_intensities: Optional[List[float]] = None


@dataclass
class MovementContext:
    """All inputs a movement shape needs to compute pan/tilt."""
    t: float                      # angle in radians
    progress: float               # 0.0-1.0 through block
    total_cycles: float
    center_pan: float
    center_tilt: float
    pan_amplitude: float
    tilt_amplitude: float
    fixture_index: int
    total_fixtures: int
    phase_offset_enabled: bool
    phase_offset_degrees: float
    lissajous_ratio: str


@dataclass
class MovementResult:
    """Output from a movement shape computation."""
    pan: float
    tilt: float
