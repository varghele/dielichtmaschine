"""Convert rudiment selections into concrete sublane blocks."""

from typing import Dict, Any, Optional

from config.models import DimmerBlock, MovementBlock
from rudiments.registry import INTENSITY_RUDIMENTS, MOVEMENT_RUDIMENTS


def rudiment_to_dimmer_block(
    rudiment_name: str,
    params: Dict[str, Any],
    start_time: float,
    end_time: float,
) -> DimmerBlock:
    """Convert an intensity rudiment to a DimmerBlock.

    Args:
        rudiment_name: Registered rudiment name (e.g. "chase", "pulse")
        params: Override parameters (intensity, speed, direction, etc.)
        start_time: Block start time in seconds
        end_time: Block end time in seconds

    Returns:
        A DimmerBlock configured for this rudiment
    """
    # Each converter reads its own table: "static" is both an intensity
    # and a movement rudiment, and the shared get_rudiment() prefers the
    # intensity one.
    rudiment = INTENSITY_RUDIMENTS.get(rudiment_name)
    if rudiment is None:
        raise ValueError(f"Unknown intensity rudiment: {rudiment_name}")

    # Build defaults from rudiment parameter definitions
    defaults = {p.name: p.default for p in rudiment.parameters}
    merged = {**defaults, **params}

    # Map rudiment parameters to DimmerBlock fields
    block = DimmerBlock(
        start_time=start_time,
        end_time=end_time,
        intensity=merged.get("intensity", 1.0) * 255.0,
        effect_type=rudiment.effect_function,
        effect_speed=str(merged.get("speed", 1.0)),
        direction=merged.get("direction", "down"),
        chase_scope=merged.get("chase_scope", "fixture"),
        phase_offset_per_fixture=merged.get("phase_offset_per_fixture", False),
        build_fraction=merged.get("build_fraction", 0.7),
    )

    return block


def rudiment_to_movement_block(
    rudiment_name: str,
    params: Dict[str, Any],
    start_time: float,
    end_time: float,
    target_spot_name: Optional[str] = None,
    target_plane_name: Optional[str] = None,
) -> MovementBlock:
    """Convert a movement rudiment to a MovementBlock.

    Args:
        rudiment_name: Registered rudiment name (e.g. "circle", "diamond")
        params: Override parameters (amplitude, speed, etc.)
        start_time: Block start time in seconds
        end_time: Block end time in seconds
        target_spot_name: Optional spot name for auto pan/tilt targeting
        target_plane_name: Optional plane name for world-space movement

    Returns:
        A MovementBlock configured for this rudiment
    """
    rudiment = MOVEMENT_RUDIMENTS.get(rudiment_name)
    if rudiment is None:
        raise ValueError(f"Unknown movement rudiment: {rudiment_name}")

    defaults = {p.name: p.default for p in rudiment.parameters}
    merged = {**defaults, **params}

    amplitude = merged.get("amplitude", 50.0)

    block = MovementBlock(
        start_time=start_time,
        end_time=end_time,
        pan=merged.get("pan", 127.5),
        tilt=merged.get("tilt", 127.5),
        effect_type=rudiment.effect_function,
        effect_speed=str(merged.get("speed", 1.0)),
        pan_amplitude=amplitude,
        tilt_amplitude=amplitude,
        lissajous_ratio=merged.get("freq_ratio", "1:2"),
        target_spot_name=target_spot_name,
        target_plane_name=target_plane_name,
    )

    return block
