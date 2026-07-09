"""North Star lane visuals: token-derived Mute/Solo chips, group-color
sublane fills, and the header fixture count (items 1 and 2 of
docs/timeline-styling-review.md).

These assert token-derived colors and QColors, never widget.styleSheet()
font families, per the styling brief.
"""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtGui import QColor

from config.models import (
    ColourBlock, DimmerBlock, FixtureGroupCapabilities, LightBlock,
)
from gui.theme_tokens import THEMES
from timeline.light_lane import LightLane


def _make_lane_widget(config, targets):
    from timeline_ui.light_lane_widget import LightLaneWidget
    lane = LightLane(name="Test Lane", fixture_targets=list(targets))
    return LightLaneWidget(
        lane=lane, fixture_groups=list(config.groups.keys()), config=config)


class TestMuteSoloChips:
    """Checked state uses brand tokens (accent), never Material red/amber."""

    def test_mute_chip_uses_accent_tokens(self, qapp, sample_configuration):
        widget = _make_lane_widget(sample_configuration, ["TestGroup"])
        try:
            qss = widget.mute_button.styleSheet()
            assert ":checked" in qss
            assert THEMES["dark"]["accent"] in qss
            # The old Material red/amber must be gone.
            assert "#d32f2f" not in qss.lower()
            assert "#ffc107" not in qss.lower()
        finally:
            widget.deleteLater()

    def test_solo_chip_is_filled_accent(self, qapp, sample_configuration):
        widget = _make_lane_widget(sample_configuration, ["TestGroup"])
        try:
            qss = widget.solo_button.styleSheet()
            assert THEMES["dark"]["accent"] in qss
            assert THEMES["dark"]["on_accent"] in qss
            assert "#ffc107" not in qss.lower()
        finally:
            widget.deleteLater()

    def test_mute_and_solo_are_distinct(self, qapp, sample_configuration):
        widget = _make_lane_widget(sample_configuration, ["TestGroup"])
        try:
            assert widget.mute_button.styleSheet() != widget.solo_button.styleSheet()
        finally:
            widget.deleteLater()


class TestFixtureCount:
    def test_counts_all_fixtures_in_group(self, qapp, sample_configuration):
        widget = _make_lane_widget(sample_configuration, ["TestGroup"])
        try:
            expected = len(sample_configuration.groups["TestGroup"].fixtures)
            assert widget._fixture_count() == expected
            assert widget.fix_count_label.text() == f"{expected} FIX"
        finally:
            widget.deleteLater()

    def test_no_targets_is_zero(self, qapp, sample_configuration):
        widget = _make_lane_widget(sample_configuration, [])
        try:
            assert widget._fixture_count() == 0
        finally:
            widget.deleteLater()


class TestSublaneFillDerivesFromGroup:
    """Non-colour rows tint in the group data color; colour rows keep the
    block's own RGBW content color."""

    def _block_widget(self, config, group_color):
        config.groups["TestGroup"].color = group_color
        widget = _make_lane_widget(config, ["TestGroup"])
        widget.capabilities = FixtureGroupCapabilities(
            has_dimmer=True, has_colour=True,
            has_movement=False, has_special=False)
        block = LightBlock(
            start_time=0.0, end_time=2.0, effect_name="x",
            dimmer_blocks=[DimmerBlock(start_time=0.0, end_time=2.0,
                                       intensity=200.0)],
            colour_blocks=[ColourBlock(start_time=0.0, end_time=2.0,
                                       red=10, green=200, blue=40)],
        )
        widget.lane.light_blocks.append(block)
        widget.create_light_block_widget(block)
        return widget, widget.light_block_widgets[-1]

    def test_dimmer_fill_is_group_color(self, qapp, sample_configuration):
        widget, bw = self._block_widget(sample_configuration, "#4ECBD4")
        try:
            assert bw.sublane_fill_color("dimmer") == QColor("#4ECBD4")
            assert bw.sublane_fill_color("movement") == QColor("#4ECBD4")
            assert bw.sublane_fill_color("special") == QColor("#4ECBD4")
        finally:
            widget.deleteLater()

    def test_colour_fill_is_block_content_color(self, qapp,
                                                sample_configuration):
        widget, bw = self._block_widget(sample_configuration, "#4ECBD4")
        try:
            cb = bw.block.colour_blocks[0]
            assert bw.sublane_fill_color("colour", cb) == QColor(10, 200, 40)
        finally:
            widget.deleteLater()

    def test_no_group_falls_back_to_brand_neutral(self, qapp,
                                                  sample_configuration):
        """Unresolvable group -> text_secondary brand neutral, not a
        Material color."""
        widget, bw = self._block_widget(sample_configuration, None)
        try:
            assert bw.sublane_fill_color("dimmer") == QColor(
                THEMES["dark"]["text_secondary"])
        finally:
            widget.deleteLater()
