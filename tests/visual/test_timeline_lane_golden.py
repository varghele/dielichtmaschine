"""Golden screenshot for the timeline lane visuals (timeline v3,
stages T2 + T3 - docs/timeline-v3-plan.md).

Renders a populated LightLaneWidget: the 260px header column
(group-color left edge, Barlow Condensed name, N FIX count, the
M / S / TARGETS / + BLOCK chip row, DIM/COL/MOV sub-lane labels stacked
under the chips) plus three restyled effect blocks in the timeline:

- an unselected block crossing a part boundary (group-colour tint,
  header strip "BASE · STATIC" + "BARS 1-3", a painted colour gradient
  segment "COL #E17126 → MAGENTA", an empty MOV row "- · -")
- a selected block inside one part (part-colour tint, accent border +
  glow + check in the strip, "FADE 208" / "COL #E17126" /
  "MOV · FIGURE-8" segments)
- a narrow block whose labels elide with "…" instead of overflowing

Colors, geometry and layout are pinned; regenerate intended changes:

    QLC_REGEN_GOLDENS=1 pytest tests/visual/test_timeline_lane_golden.py

review the image diff, and commit the new golden.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from config.models import (
    Configuration, ColourBlock, DimmerBlock, Fixture, FixtureGroup,
    FixtureGroupCapabilities, FixtureMode, LightBlock, MovementBlock,
    ShowPart, Universe,
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
    """One group of 3 fixtures with a cyan data color (distinct from
    the gold/purple part colors so the tint source is visible)."""
    fixtures = [_make_fixture(f"PAR {i}", "Front", 1 + i * 10) for i in range(3)]
    return Configuration(
        fixtures=fixtures,
        groups={"Front": FixtureGroup("Front", fixtures, color="#4ECBD4")},
        universes={1: Universe(id=1, name="U1", output={})},
    )


def _song_structure():
    """VERSE (2 bars, gold) then CHORUS (8 bars, purple), 4/4 @ 120 -
    bars are 2s each, part boundary at 4s."""
    from timeline.song_structure import SongStructure

    structure = SongStructure()
    structure.load_from_show_parts([
        ShowPart(name="VERSE", color="#D9A441", signature="4/4",
                 bpm=120.0, num_bars=2, transition="instant"),
        ShowPart(name="CHORUS", color="#C95FD0", signature="4/4",
                 bpm=120.0, num_bars=8, transition="instant"),
    ])
    return structure


def test_timeline_lane_golden(qapp, lane_config):
    """Full lane: T2 header column plus T3 block anatomy (muted tint
    body, 16px header strip with bar range, labelled sub-row segments,
    painted colour gradient, empty-row placeholder, accent selection
    chrome, elision on the narrow block)."""
    from gui.theme_manager import ThemeManager
    from timeline.light_lane import LightLane
    from timeline_ui.light_lane_widget import LightLaneWidget

    ThemeManager().apply(qapp, "dark")

    lane = LightLane(name="Front Pars", fixture_targets=["Front"])
    # Block 1: crosses the VERSE/CHORUS boundary -> group-colour tint.
    # Colour row = two contiguous blocks -> painted gradient + arrow
    # label; MOV row stays empty -> "- · -" placeholder.
    lane.light_blocks.append(LightBlock(
        start_time=0.0, end_time=5.0, effect_name="verse.wash",
        dimmer_blocks=[DimmerBlock(start_time=0.0, end_time=5.0,
                                   intensity=200.0)],
        colour_blocks=[
            ColourBlock(start_time=0.0, end_time=2.5,
                        red=225, green=113, blue=38),
            ColourBlock(start_time=2.5, end_time=5.0,
                        red=255, green=0, blue=255),
        ],
    ))
    # Block 2: fully inside CHORUS -> part-colour tint; selected.
    lane.light_blocks.append(LightBlock(
        start_time=5.5, end_time=8.5, effect_name="chorus.hit",
        dimmer_blocks=[DimmerBlock(start_time=5.5, end_time=8.5,
                                   intensity=208.0, effect_type="fade")],
        colour_blocks=[ColourBlock(start_time=5.5, end_time=8.5, red=225,
                                   green=113, blue=38)],
        movement_blocks=[MovementBlock(start_time=5.5, end_time=8.5,
                                       effect_type="figure_8")],
    ))
    # Block 3: too narrow for its labels -> everything elides inside.
    lane.light_blocks.append(LightBlock(
        start_time=9.0, end_time=9.7, effect_name="chorus.stab",
        dimmer_blocks=[DimmerBlock(start_time=9.0, end_time=9.7,
                                   intensity=255.0, effect_type="pulse",
                                   effect_speed="1/2")],
    ))

    widget = LightLaneWidget(
        lane=lane, fixture_groups=list(lane_config.groups),
        config=lane_config)
    try:
        # Synthetic fixtures resolve no definition, so pin the sublane
        # layout explicitly (same trick as test_timeline_block_golden).
        widget.capabilities = FixtureGroupCapabilities(
            has_dimmer=True, has_colour=True,
            has_movement=True, has_special=False)
        widget.num_sublanes = 3
        widget.sublane_height = 50
        widget.refresh_sublane_labels()
        widget.mute_button.setChecked(True)
        widget.solo_button.setChecked(True)

        widget.timeline_widget.num_sublanes = 3
        widget.timeline_widget.sublane_height = 50
        widget.timeline_widget.capabilities = widget.capabilities
        widget.timeline_widget.set_song_structure(_song_structure())
        widget.timeline_widget.setFixedSize(620, 150)

        for block_widget in widget.light_block_widgets:
            block_widget.update_position()
        # Select the second block: accent border + glow + strip check.
        widget.light_block_widgets[1].set_multi_selected(True)

        widget.setFixedSize(940, 165)
        compare_to_golden(widget.grab().toImage(), "timeline_lane_dark")
    finally:
        widget.deleteLater()
