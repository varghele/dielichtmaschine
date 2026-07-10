"""North Star lane visuals: token-derived Mute/Solo chips, group-color
sublane fills, the header fixture count (items 1 and 2 of
docs/timeline-styling-review.md), and the timeline v3 stage T3 block
label/format helpers (docs/timeline-v3-plan.md).

These assert token-derived colors and QColors, never widget.styleSheet()
font families, per the styling brief.
"""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtGui import QColor

from config.models import (
    ColourBlock, DimmerBlock, FixtureGroupCapabilities, LightBlock,
    ShowPart,
)
from gui.theme_tokens import THEMES
from timeline.light_lane import LightLane
from timeline_ui.light_block_widget import (
    EMPTY_SUBROW_TEXT, bar_index_at, bar_range_label, block_header_label,
    block_kind_label, colour_segment_label, dimmer_segment_label, elided,
    movement_segment_label, part_containing_span, special_segment_label,
)


def _make_lane_widget(config, targets):
    from timeline_ui.light_lane_widget import LightLaneWidget
    lane = LightLane(name="Test Lane", fixture_targets=list(targets))
    return LightLaneWidget(
        lane=lane, fixture_groups=list(config.groups.keys()), config=config)


class TestMuteSoloChips:
    """Mute/Solo are the lane-chip role: the mono family and compact
    padding are pinned in the theme (the app-wide QWidget font-family
    rule beats setFont, docs/qt-gotchas.md), accent outline when
    checked - so every chip in the lane header reads as one family.
    Assert the role and the theme rule, never widget.styleSheet()."""

    def test_mute_chip_is_lane_chip(self, qapp, sample_configuration):
        widget = _make_lane_widget(sample_configuration, ["TestGroup"])
        try:
            assert widget.mute_button.property("role") == "lane-chip"
            # No leftover per-chip inline stylesheet (Material red is gone).
            assert widget.mute_button.styleSheet() == ""
        finally:
            widget.deleteLater()

    def test_solo_chip_is_lane_chip(self, qapp, sample_configuration):
        widget = _make_lane_widget(sample_configuration, ["TestGroup"])
        try:
            assert widget.solo_button.property("role") == "lane-chip"
            assert widget.solo_button.styleSheet() == ""
        finally:
            widget.deleteLater()

    def test_lane_chip_theme_rule(self):
        """Checked = accent outline; the mono family is pinned in the
        rule itself so the chips survive the app-wide font rule."""
        from gui.theme_tokens import render_theme
        qss = render_theme("dark")
        assert 'QPushButton[role="lane-chip"]:checked' in qss
        body = qss.split('QPushButton[role="lane-chip"] {', 1)[1]
        body = body.split("}", 1)[0]
        assert "font-family" in body
        assert THEMES["dark"]["accent"] in qss


class TestLaneHeaderStructure:
    """Timeline v3 lane header (stage T2): 260px column, name + N FIX
    row, chip row M / S / TARGETS / + BLOCK, and the DIM/COL/... label
    column stacked under the chips."""

    def _pinned(self, config, **caps):
        from config.models import FixtureGroupCapabilities
        widget = _make_lane_widget(config, ["TestGroup"])
        widget.capabilities = FixtureGroupCapabilities(
            has_dimmer=caps.get("dimmer", True),
            has_colour=caps.get("colour", True),
            has_movement=caps.get("movement", False),
            has_special=caps.get("special", False))
        widget.num_sublanes = widget._count_sublanes()
        widget.refresh_sublane_labels()
        return widget

    def test_header_column_is_260px(self, qapp, sample_configuration):
        from timeline_ui.timeline_widget import HEADER_COLUMN_WIDTH
        widget = _make_lane_widget(sample_configuration, ["TestGroup"])
        try:
            assert HEADER_COLUMN_WIDTH == 260
            assert widget.controls_widget.width() == 260
        finally:
            widget.deleteLater()

    def test_shared_width_constant_used_everywhere(self):
        """Audio lane, master timeline and the grid all import the one
        constant so every track's canvas stays column-aligned."""
        from timeline_ui import (
            audio_lane_widget, master_timeline_widget, timeline_grid,
            timeline_widget,
        )
        assert audio_lane_widget.HEADER_COLUMN_WIDTH is \
            timeline_widget.HEADER_COLUMN_WIDTH
        assert master_timeline_widget.HEADER_COLUMN_WIDTH is \
            timeline_widget.HEADER_COLUMN_WIDTH
        assert timeline_grid._HEADER_COLUMN_WIDTH is \
            timeline_widget.HEADER_COLUMN_WIDTH

    def test_row1_name_and_fix_count(self, qapp, sample_configuration):
        widget = _make_lane_widget(sample_configuration, ["TestGroup"])
        try:
            assert widget.name_edit.text() == "Test Lane"
            expected = len(sample_configuration.groups["TestGroup"].fixtures)
            assert widget.fix_count_label.text() == f"{expected} FIX"
            assert widget.fix_count_label.property("role") == "micro"
        finally:
            widget.deleteLater()

    def test_chip_row_roles_and_texts(self, qapp, sample_configuration):
        widget = _make_lane_widget(sample_configuration, ["TestGroup"])
        try:
            for chip in (widget.mute_button, widget.solo_button,
                         widget.targets_chip, widget.add_block_button):
                assert chip.property("role") == "lane-chip"
            assert widget.mute_button.text() == "M"
            assert widget.solo_button.text() == "S"
            # U+2193 drop indicator: the mock's ▾ is not in the brand
            # fonts (tofu on offscreen), the arrow is.
            assert widget.targets_chip.text() == "TARGETS ↓"
            assert widget.add_block_button.text() == "+ BLOCK"
            # Only M/S toggle; TARGETS and + BLOCK are plain actions.
            assert widget.mute_button.isCheckable()
            assert widget.solo_button.isCheckable()
            assert not widget.targets_chip.isCheckable()
            assert not widget.add_block_button.isCheckable()
            # Legacy alias kept for callers that drive the old name.
            assert widget.edit_targets_btn is widget.targets_chip
        finally:
            widget.deleteLater()

    def test_header_sublane_labels_match_lane_sublanes(self, qapp,
                                                       sample_configuration):
        widget = self._pinned(sample_configuration,
                              dimmer=True, colour=True, movement=True)
        try:
            assert widget.num_sublanes == 3
            assert len(widget.sublane_labels) == widget.num_sublanes
            assert [l.text() for l in widget.sublane_labels] == \
                ["DIM", "COL", "MOV"]
            # Column order matches the stripe row order.
            for row, label in enumerate(widget.sublane_labels):
                assert row == widget.get_sublane_index(
                    label.property("sublane_type"))
        finally:
            widget.deleteLater()

    def test_lane_without_movement_has_no_mov_label(self, qapp,
                                                    sample_configuration):
        widget = self._pinned(sample_configuration,
                              dimmer=True, colour=True, movement=False)
        try:
            assert "MOV" not in [l.text() for l in widget.sublane_labels]
        finally:
            widget.deleteLater()

    def test_setting_toggle_hides_header_labels(self, qapp,
                                                sample_configuration):
        from utils.app_settings import app_settings
        key = "timeline/show_sublane_labels"
        app_settings().remove(key)
        widget = self._pinned(sample_configuration)
        try:
            assert not widget.sublane_labels_widget.isHidden()
            app_settings().setValue(key, False)
            widget.timeline_widget.update()  # shows-tab refresh path
            assert widget.sublane_labels_widget.isHidden()
        finally:
            app_settings().remove(key)
            widget.deleteLater()

    def test_canvas_label_path_removed(self):
        from timeline_ui.timeline_widget import TimelineWidget
        assert not hasattr(TimelineWidget, "draw_sublane_labels")

    def test_snap_state_still_syncs_without_visible_checkbox(
            self, qapp, sample_configuration):
        """The per-lane snap checkbox is hidden (the toolbar SNAP chip is
        the single visible control) but keeps driving the timeline."""
        widget = _make_lane_widget(sample_configuration, ["TestGroup"])
        try:
            assert widget.snap_checkbox.isHidden()
            widget.snap_checkbox.setChecked(False)
            assert widget.timeline_widget.snap_to_grid is False
            widget.snap_checkbox.setChecked(True)
            assert widget.timeline_widget.snap_to_grid is True
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


# ── Timeline v3 stage T3: block label/format helpers ─────────────────────


def _structure():
    """VERSE (2 bars, gold) + CHORUS (8 bars, purple), 4/4 @ 120 BPM:
    bars are 2s each, the part boundary sits at 4s."""
    from timeline.song_structure import SongStructure

    structure = SongStructure()
    structure.load_from_show_parts([
        ShowPart(name="VERSE", color="#D9A441", signature="4/4",
                 bpm=120.0, num_bars=2, transition="instant"),
        ShowPart(name="CHORUS", color="#C95FD0", signature="4/4",
                 bpm=120.0, num_bars=8, transition="instant"),
    ])
    return structure


class TestSegmentLabels:
    """Compact mono sub-row labels ("PULSE 1/2", "FADE 208",
    "COL #E17126 → MAGENTA", "MOV · FIGURE-8", honest SPC)."""

    def test_dimmer_default_speed_shows_intensity(self):
        assert dimmer_segment_label("fade", "1", 208.0) == "FADE 208"
        assert dimmer_segment_label("static", "1", 255.0) == "STATIC 255"

    def test_dimmer_non_default_speed_shows_rate(self):
        assert dimmer_segment_label("pulse", "1/2", 208.0) == "PULSE 1/2"
        assert dimmer_segment_label("strobe", "4", 213.0) == "STROBE 4"

    def test_dimmer_effect_name_shortening(self):
        assert dimmer_segment_label(
            "ping_pong_smooth", "1", 100.0) == "PING PONG 100"

    def test_movement_label(self):
        assert movement_segment_label("figure_8") == "MOV · FIGURE-8"
        assert movement_segment_label("static") == "MOV · STATIC"

    def test_special_label_is_honest(self):
        assert special_segment_label(0, False) == "SPC · BEAM"
        assert special_segment_label(2, False) == "SPC · GOBO 2"
        assert special_segment_label(0, True) == "SPC · PRISM"
        assert special_segment_label(2, True) == "SPC · GOBO 2 + PRISM"

    def test_colour_label_hex(self):
        assert colour_segment_label((225, 113, 38, 0)) == "COL #E17126"

    def test_colour_label_named(self):
        assert colour_segment_label((255, 0, 0, 0)) == "COL RED"
        # White channel counts as white when RGB is dark.
        assert colour_segment_label((0, 0, 0, 255)) == "COL WHITE"

    def test_colour_label_gradient(self):
        assert colour_segment_label(
            (225, 113, 38, 0), (255, 0, 255, 0)) == "COL #E17126 → MAGENTA"

    def test_empty_subrow_placeholder(self):
        assert EMPTY_SUBROW_TEXT == "- · -"


class TestBlockHeaderLabel:
    """Header strip left text: "BASE · PULSE" style, "*" when modified,
    check when selected."""

    def test_default_name_and_kind(self):
        assert block_header_label(None, "PULSE") == "BASE · PULSE"

    def test_custom_name_uppercased(self):
        assert block_header_label("Chorus", "FADE") == "CHORUS · FADE"

    def test_no_kind_is_name_only(self):
        assert block_header_label(None, "") == "BASE"

    def test_modified_and_selected_marks(self):
        assert block_header_label("Chorus", "FADE",
                                  modified=True) == "CHORUS · FADE *"
        assert block_header_label("Chorus", "FADE",
                                  selected=True) == "CHORUS · FADE ✓"

    def test_kind_from_first_dimmer_effect(self):
        block = LightBlock(
            start_time=0.0, end_time=1.0, effect_name="verse.wash",
            dimmer_blocks=[DimmerBlock(start_time=0.0, end_time=1.0,
                                       effect_type="pulse")])
        assert block_kind_label(block) == "PULSE"

    def test_kind_falls_back_to_effect_name_function(self):
        block = LightBlock(start_time=0.0, end_time=1.0,
                           effect_name="verse.wash")
        assert block_kind_label(block) == "WASH"


class TestBarRangeLabel:
    """Bar range derivation: 1-based bars accumulated across parts,
    end bar = last bar the block reaches into."""

    def test_bar_index_accumulates_across_parts(self):
        structure = _structure()
        assert bar_index_at(structure, 0.0) == 1
        assert bar_index_at(structure, 2.1) == 2
        assert bar_index_at(structure, 4.0) == 3  # first CHORUS bar
        assert bar_index_at(structure, 19.9) == 10

    def test_span_across_parts(self):
        assert bar_range_label(_structure(), 0.0, 5.0) == "BARS 1-3"

    def test_span_within_part(self):
        assert bar_range_label(_structure(), 5.5, 8.5) == "BARS 3-5"

    def test_block_ending_on_bar_line_does_not_claim_next_bar(self):
        assert bar_range_label(_structure(), 0.0, 2.0) == "BAR 1"

    def test_no_structure_is_empty(self):
        assert bar_range_label(None, 0.0, 5.0) == ""
        assert bar_index_at(None, 0.0) is None


class TestPartContainment:
    """The block-tint rule: part colour only when the block sits fully
    inside one part region."""

    def test_block_inside_part(self):
        part = part_containing_span(_structure(), 5.5, 8.5)
        assert part is not None and part.name == "CHORUS"

    def test_block_crossing_parts_has_no_part(self):
        assert part_containing_span(_structure(), 0.0, 5.0) is None

    def test_exact_part_span_counts_as_inside(self):
        part = part_containing_span(_structure(), 4.0, 20.0)
        assert part is not None and part.name == "CHORUS"

    def test_no_structure(self):
        assert part_containing_span(None, 0.0, 1.0) is None


class TestBlockBaseColor:
    """Widget-level colour source: part colour inside a part, group
    colour otherwise (deterministic, mock 06b rule)."""

    def _widget_with_block(self, config, start, end, structure=None):
        config.groups["TestGroup"].color = "#4ECBD4"
        widget = _make_lane_widget(config, ["TestGroup"])
        widget.capabilities = FixtureGroupCapabilities(
            has_dimmer=True, has_colour=True,
            has_movement=False, has_special=False)
        if structure is not None:
            widget.timeline_widget.set_song_structure(structure)
        block = LightBlock(
            start_time=start, end_time=end, effect_name="x",
            dimmer_blocks=[DimmerBlock(start_time=start, end_time=end)])
        widget.lane.light_blocks.append(block)
        widget.create_light_block_widget(block)
        return widget, widget.light_block_widgets[-1]

    def test_part_colour_when_inside_part(self, qapp, sample_configuration):
        widget, bw = self._widget_with_block(
            sample_configuration, 5.5, 8.5, structure=_structure())
        try:
            assert bw.block_base_color() == QColor("#C95FD0")
            # Non-colour sub-row fills follow the same source.
            assert bw.sublane_fill_color("dimmer") == QColor("#C95FD0")
        finally:
            widget.deleteLater()

    def test_group_colour_when_crossing_parts(self, qapp,
                                              sample_configuration):
        widget, bw = self._widget_with_block(
            sample_configuration, 0.0, 5.0, structure=_structure())
        try:
            assert bw.block_base_color() == QColor("#4ECBD4")
        finally:
            widget.deleteLater()

    def test_group_colour_without_structure(self, qapp,
                                            sample_configuration):
        widget, bw = self._widget_with_block(sample_configuration, 0.0, 2.0)
        try:
            assert bw.block_base_color() == QColor("#4ECBD4")
        finally:
            widget.deleteLater()


class TestColourGradientTarget:
    """A colour segment gradients into the next colour block only when
    they meet seamlessly and differ in colour."""

    def _widget(self, config, colour_blocks):
        widget = _make_lane_widget(config, ["TestGroup"])
        widget.capabilities = FixtureGroupCapabilities(
            has_dimmer=True, has_colour=True,
            has_movement=False, has_special=False)
        block = LightBlock(start_time=0.0, end_time=4.0, effect_name="x",
                           colour_blocks=colour_blocks)
        widget.lane.light_blocks.append(block)
        widget.create_light_block_widget(block)
        return widget, widget.light_block_widgets[-1]

    def test_contiguous_different_colours_gradient(self, qapp,
                                                   sample_configuration):
        first = ColourBlock(start_time=0.0, end_time=2.0, red=255)
        second = ColourBlock(start_time=2.0, end_time=4.0, blue=255)
        widget, bw = self._widget(sample_configuration, [first, second])
        try:
            assert bw._colour_gradient_target(first) is second
            assert bw._colour_gradient_target(second) is None  # last block
            assert bw._sublane_segment_text(first, "colour") == \
                "COL RED → BLUE"
        finally:
            widget.deleteLater()

    def test_gap_breaks_the_gradient(self, qapp, sample_configuration):
        first = ColourBlock(start_time=0.0, end_time=1.5, red=255)
        second = ColourBlock(start_time=2.0, end_time=4.0, blue=255)
        widget, bw = self._widget(sample_configuration, [first, second])
        try:
            assert bw._colour_gradient_target(first) is None
            assert bw._sublane_segment_text(first, "colour") == "COL RED"
        finally:
            widget.deleteLater()

    def test_same_colour_has_no_gradient(self, qapp, sample_configuration):
        first = ColourBlock(start_time=0.0, end_time=2.0, red=255)
        second = ColourBlock(start_time=2.0, end_time=4.0, red=255)
        widget, bw = self._widget(sample_configuration, [first, second])
        try:
            assert bw._colour_gradient_target(first) is None
        finally:
            widget.deleteLater()


class TestElision:
    """Labels elide with "…" instead of painting outside their segment."""

    def _metrics(self):
        from PyQt6.QtGui import QFontMetrics
        from gui.typography import mono_font
        return QFontMetrics(mono_font(7))

    def test_long_text_elides_within_width(self, qapp):
        metrics = self._metrics()
        text = "COL #E17126 → MAGENTA"
        assert metrics.horizontalAdvance(text) > 60
        out = elided(metrics, text, 60)
        assert out.endswith("…")
        assert metrics.horizontalAdvance(out) <= 60

    def test_fitting_text_is_unchanged(self, qapp):
        metrics = self._metrics()
        assert elided(metrics, "FADE 208", 500) == "FADE 208"

    def test_nothing_fits_returns_empty(self, qapp):
        metrics = self._metrics()
        assert elided(metrics, "FADE 208", 2) == ""
        assert elided(metrics, "", 100) == ""
        assert elided(metrics, "FADE 208", 0) == ""
