"""Golden screenshot for the timeline lane visuals (North Star lane
anatomy, items 1 and 2 of docs/timeline-styling-review.md).

Renders a populated LightLaneWidget: the header (group-color left
border, Barlow Condensed name, N FIX count, DIM/COL sublane labels,
Mute/Solo chips) plus two effect blocks in the timeline, one with a
selected sublane block. Colors, geometry and layout are pinned; text
content is not (offscreen QPA font caveat, see harness).

Regenerate intended changes with:

    QLC_REGEN_GOLDENS=1 pytest tests/visual/test_timeline_lane_golden.py

review the image diff, and commit the new golden.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from config.models import (
    Configuration, ColourBlock, DimmerBlock, Fixture, FixtureGroup,
    FixtureGroupCapabilities, FixtureMode, LightBlock, Universe,
)
from tests.visual.harness import compare_to_golden


def _make_fixture(name, group, address):
    return Fixture(
        universe=1, address=address,
        manufacturer="TestMfr", model="TestModel",
        name=name, group=group,
        current_mode="Standard",
        available_modes=[FixtureMode(name="Standard", channels=10)],
        type="PAR",
    )


@pytest.fixture
def lane_config():
    """One group of 3 fixtures with a warm data color."""
    fixtures = [_make_fixture(f"PAR {i}", "Front", 1 + i * 10) for i in range(3)]
    return Configuration(
        fixtures=fixtures,
        groups={"Front": FixtureGroup("Front", fixtures, color="#D9A441")},
        universes={1: Universe(id=1, name="U1", output={})},
    )


def test_timeline_lane_golden(qapp, lane_config):
    """Full lane: group-color header border, name + N FIX count,
    sublane label column, Mute/Solo chips, and two group-tinted effect
    blocks (one with a selected colour sublane)."""
    from gui.theme_manager import ThemeManager
    from timeline.light_lane import LightLane
    from timeline_ui.light_lane_widget import LightLaneWidget

    ThemeManager().apply(qapp, "dark")

    lane = LightLane(name="Front Pars", fixture_targets=["Front"])
    lane.light_blocks.append(LightBlock(
        start_time=0.0, end_time=2.0, effect_name="verse.wash",
        dimmer_blocks=[DimmerBlock(start_time=0.0, end_time=2.0,
                                   intensity=200.0)],
        colour_blocks=[ColourBlock(start_time=0.0, end_time=2.0, red=217,
                                   green=164, blue=65)],
    ))
    lane.light_blocks.append(LightBlock(
        start_time=3.0, end_time=5.0, effect_name="chorus.hit",
        dimmer_blocks=[DimmerBlock(start_time=3.0, end_time=5.0,
                                   intensity=255.0)],
        colour_blocks=[ColourBlock(start_time=3.0, end_time=5.0, red=240,
                                   green=86, blue=46)],
    ))

    widget = LightLaneWidget(
        lane=lane, fixture_groups=list(lane_config.groups),
        config=lane_config)
    try:
        # Synthetic fixtures resolve no definition, so pin the sublane
        # layout explicitly (same trick as test_timeline_block_golden).
        widget.capabilities = FixtureGroupCapabilities(
            has_dimmer=True, has_colour=True,
            has_movement=False, has_special=False)
        widget.num_sublanes = 2
        widget.sublane_height = 50
        widget.refresh_sublane_labels()
        widget.mute_button.setChecked(True)
        widget.solo_button.setChecked(True)

        widget.timeline_widget.num_sublanes = 2
        widget.timeline_widget.sublane_height = 50
        widget.timeline_widget.capabilities = widget.capabilities
        widget.timeline_widget.setFixedSize(400, 100)

        for block_widget in widget.light_block_widgets:
            block_widget.update_position()
        # Select the second block's colour sublane so the accent
        # selection border renders.
        second = widget.light_block_widgets[1]
        second.selected_sublane_type = "colour"
        second.selected_sublane_block = second.block.colour_blocks[0]
        second.update()

        widget.setFixedSize(720, 115)
        compare_to_golden(widget.grab().toImage(), "timeline_lane_dark")
    finally:
        widget.deleteLater()
