"""Lane header sublane micro-labels (North Star lane anatomy, slice T1).

Each timeline lane header lists its active sublanes as DIM / COL /
MOV / SPC micro-labels in a right-edge column, top to bottom in the
same row order the timeline stripe uses (get_sublane_index). The
labels rebuild whenever capabilities are re-detected.

Note: the synthetic TestMfr/TestModel fixtures resolve no fixture
definition, so capability detection yields all-False and the widget
starts with zero labels. Tests pin capabilities explicitly and call
refresh_sublane_labels(), the same hook on_targets_changed and
update_fixture_groups use (pattern from
tests/visual/test_golden_screenshots.py::test_timeline_block_golden).
"""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from timeline.light_lane import LightLane


def _make_lane_widget(config, targets=("TestGroup",)):
    from timeline_ui.light_lane_widget import LightLaneWidget
    lane = LightLane(name="Test Lane", fixture_targets=list(targets))
    return LightLaneWidget(
        lane=lane, fixture_groups=list(config.groups.keys()), config=config)


def _set_capabilities(widget, *, dimmer=False, colour=False,
                      movement=False, special=False):
    """Pin capabilities explicitly, then run the refresh hook."""
    from config.models import FixtureGroupCapabilities
    widget.capabilities = FixtureGroupCapabilities(
        has_dimmer=dimmer, has_colour=colour,
        has_movement=movement, has_special=special)
    widget.num_sublanes = widget._count_sublanes()
    widget.refresh_sublane_labels()


def _label_texts(widget):
    return [label.text() for label in widget.sublane_labels]


class TestSublaneLabels:
    def test_synthetic_config_detects_no_capabilities(self, qapp,
                                                      sample_configuration):
        """Baseline: synthetic fixtures resolve no definition, so the
        header starts with no sublane labels (no active capability)."""
        widget = _make_lane_widget(sample_configuration)
        try:
            assert _label_texts(widget) == []
        finally:
            widget.deleteLater()

    def test_all_capabilities_show_all_labels(self, qapp,
                                              sample_configuration):
        widget = _make_lane_widget(sample_configuration)
        try:
            _set_capabilities(widget, dimmer=True, colour=True,
                              movement=True, special=True)
            assert _label_texts(widget) == ["DIM", "COL", "MOV", "SPC"]
        finally:
            widget.deleteLater()

    def test_dimmer_only(self, qapp, sample_configuration):
        widget = _make_lane_widget(sample_configuration)
        try:
            _set_capabilities(widget, dimmer=True)
            assert _label_texts(widget) == ["DIM"]
        finally:
            widget.deleteLater()

    def test_colour_implies_dimmer_row(self, qapp, sample_configuration):
        """Colour-only groups still get a DIM row (dimmer drives RGB
        intensity for no-dimmer fixtures) - mirrors _count_sublanes."""
        widget = _make_lane_widget(sample_configuration)
        try:
            _set_capabilities(widget, colour=True)
            assert _label_texts(widget) == ["DIM", "COL"]
        finally:
            widget.deleteLater()

    def test_movement_and_special_only(self, qapp, sample_configuration):
        widget = _make_lane_widget(sample_configuration)
        try:
            _set_capabilities(widget, movement=True, special=True)
            assert _label_texts(widget) == ["MOV", "SPC"]
        finally:
            widget.deleteLater()

    def test_labels_update_on_capability_change(self, qapp,
                                                sample_configuration):
        widget = _make_lane_widget(sample_configuration)
        try:
            _set_capabilities(widget, dimmer=True, colour=True,
                              movement=True, special=True)
            assert _label_texts(widget) == ["DIM", "COL", "MOV", "SPC"]
            _set_capabilities(widget, dimmer=True)
            assert _label_texts(widget) == ["DIM"]
        finally:
            widget.deleteLater()

    def test_order_matches_get_sublane_index(self, qapp,
                                             sample_configuration):
        """Each label's position in the column equals the stripe row
        index get_sublane_index assigns to its sublane type."""
        widget = _make_lane_widget(sample_configuration)
        try:
            _set_capabilities(widget, dimmer=True, colour=True,
                              movement=True, special=True)
            for position, label in enumerate(widget.sublane_labels):
                sublane_type = label.property("sublane_type")
                assert position == widget.get_sublane_index(sublane_type), (
                    f"label {label.text()!r} sits at row {position} but "
                    f"get_sublane_index({sublane_type!r}) says "
                    f"{widget.get_sublane_index(sublane_type)}"
                )
        finally:
            widget.deleteLater()

    def test_labels_are_micro_role(self, qapp, sample_configuration):
        """Labels use the micro voice: role property drives the theme's
        text-secondary color; text renders as tracked mono caps."""
        widget = _make_lane_widget(sample_configuration)
        try:
            _set_capabilities(widget, dimmer=True, colour=True)
            assert widget.sublane_labels, "expected at least one label"
            for label in widget.sublane_labels:
                assert label.property("role") == "micro"
        finally:
            widget.deleteLater()

    def test_targets_change_refreshes_labels(self, qapp,
                                             sample_configuration):
        """on_targets_changed re-detects capabilities and rebuilds the
        label column. Synthetic configs detect all-False, so labels
        pinned beforehand must be cleared by the re-detection."""
        widget = _make_lane_widget(sample_configuration)
        try:
            _set_capabilities(widget, dimmer=True, colour=True)
            assert _label_texts(widget) == ["DIM", "COL"]
            widget.on_targets_changed(["TestGroup"])
            assert _label_texts(widget) == []
        finally:
            widget.deleteLater()
