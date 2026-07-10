# utils/pause_show_generator.py
# Generates the auto-generated PAUSE show at export time.

from typing import Optional, Dict

from config.models import (
    Configuration, Song, ShowPart, TimelineData, LightLane, LightBlock,
    DimmerBlock, ColourBlock, MovementBlock, FixtureGroupCapabilities,
)

# PAUSE show duration in seconds (7 minutes)
PAUSE_DURATION = 420.0
PAUSE_BPM = 120.0
PAUSE_SIGNATURE = "4/4"
# 7 min at 120 BPM = 840 beats = 210 bars (4/4)
PAUSE_NUM_BARS = 210


def _hex_to_rgb(hex_color: str):
    """Convert hex color string to (r, g, b) tuple (0-255)."""
    hex_color = hex_color.lstrip('#')
    if len(hex_color) != 6:
        return 0, 0, 255  # fallback blue
    return (
        int(hex_color[0:2], 16),
        int(hex_color[2:4], 16),
        int(hex_color[4:6], 16),
    )


def generate_pause_show(
    config: Configuration,
    fixture_definitions: dict,
    capabilities_map: Dict[str, FixtureGroupCapabilities],
) -> Optional[Song]:
    """Generate the PAUSE show from config.pause_show settings.

    Returns a Show object ready to be exported, or None if not enabled / no groups.
    """
    if not config.pause_show or not config.pause_show.enabled:
        return None
    if not config.groups:
        return None

    r, g, b = _hex_to_rgb(config.pause_show.color)

    # Single show part spanning full duration
    part = ShowPart(
        name="PAUSE",
        color=config.pause_show.color,
        signature=PAUSE_SIGNATURE,
        bpm=PAUSE_BPM,
        num_bars=PAUSE_NUM_BARS,
        transition="instant",
    )

    lanes = []
    for group_name, group in config.groups.items():
        if not group.fixtures:
            continue

        caps = capabilities_map.get(group_name, FixtureGroupCapabilities())
        has_movement = caps.has_movement

        # Colour block — same for all groups
        colour_block = ColourBlock(
            start_time=0.0,
            end_time=PAUSE_DURATION,
            color_mode="RGB",
            red=float(r),
            green=float(g),
            blue=float(b),
        )

        # Dimmer block — waterfall for non-movers, static for movers
        if has_movement:
            dimmer_block = DimmerBlock(
                start_time=0.0,
                end_time=PAUSE_DURATION,
                intensity=255.0,
                effect_type="static",
            )
        else:
            dimmer_block = DimmerBlock(
                start_time=0.0,
                end_time=PAUSE_DURATION,
                intensity=255.0,
                effect_type="waterfall",
                effect_speed="1/4",
                direction="down",
            )

        # Movement block — lissajous for movers only
        movement_blocks = []
        if has_movement:
            movement_blocks.append(MovementBlock(
                start_time=0.0,
                end_time=PAUSE_DURATION,
                pan=127.5,
                tilt=127.5,
                effect_type="lissajous",
                effect_speed="1/4",
                pan_amplitude=35.0,
                tilt_amplitude=35.0,
                lissajous_ratio="1:2",
                phase_offset_enabled=True,
                phase_offset_degrees=45.0,
            ))

        light_block = LightBlock(
            start_time=0.0,
            end_time=PAUSE_DURATION,
            effect_name="pause.ambient",
            dimmer_blocks=[dimmer_block],
            colour_blocks=[colour_block],
            movement_blocks=movement_blocks,
        )

        lane = LightLane(
            name=group_name,
            fixture_targets=[group_name],
            light_blocks=[light_block],
        )
        lanes.append(lane)

    if not lanes:
        return None

    timeline = TimelineData(lanes=lanes)

    return Song(
        name="PAUSE",
        parts=[part],
        timeline_data=timeline,
        trigger_device=config.pause_show.trigger_device,
        trigger_channel=config.pause_show.trigger_channel,
    )
