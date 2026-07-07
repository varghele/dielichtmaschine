"""Group-color lane borders (North Star lane anatomy, component pass C3).

Each timeline lane header carries a 3px left border in its target
group's color; the border is a data color, applied as a widget-local
rule so the theme keeps owning the header background.
"""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from timeline.light_lane import LightLane


def _make_lane_widget(config, targets):
    from timeline_ui.light_lane_widget import LightLaneWidget
    lane = LightLane(name="Test Lane", fixture_targets=targets)
    return LightLaneWidget(
        lane=lane, fixture_groups=list(config.groups.keys()), config=config)


class TestLaneGroupBorder:
    def test_header_carries_group_color_border(self, qapp,
                                                sample_configuration):
        sample_configuration.groups["TestGroup"].color = "#D9A441"
        widget = _make_lane_widget(sample_configuration, ["TestGroup"])
        try:
            qss = widget.controls_widget.styleSheet()
            assert "border-left: 3px solid #D9A441" in qss
        finally:
            widget.deleteLater()

    def test_indexed_target_resolves_to_its_group(self, qapp,
                                                  sample_configuration):
        sample_configuration.groups["TestGroup"].color = "#4ECBD4"
        widget = _make_lane_widget(sample_configuration, ["TestGroup:0"])
        try:
            assert "#4ECBD4" in widget.controls_widget.styleSheet()
        finally:
            widget.deleteLater()

    def test_unknown_group_gets_transparent_border(self, qapp,
                                                   sample_configuration):
        widget = _make_lane_widget(sample_configuration, ["NoSuchGroup"])
        try:
            assert "transparent" in widget.controls_widget.styleSheet()
        finally:
            widget.deleteLater()

    def test_border_updates_when_targets_change(self, qapp,
                                                sample_configuration):
        from config.models import FixtureGroup
        sample_configuration.groups["TestGroup"].color = "#D9A441"
        sample_configuration.groups["Other"] = FixtureGroup(
            "Other", [], color="#C95FD0")
        widget = _make_lane_widget(sample_configuration, ["TestGroup"])
        try:
            widget.on_targets_changed(["Other"])
            assert "#C95FD0" in widget.controls_widget.styleSheet()
        finally:
            widget.deleteLater()

    def test_no_config_is_safe(self, qapp):
        from timeline_ui.light_lane_widget import LightLaneWidget
        lane = LightLane(name="Bare", fixture_targets=["X"])
        widget = LightLaneWidget(lane=lane, fixture_groups=["X"])
        try:
            assert "transparent" in widget.controls_widget.styleSheet()
        finally:
            widget.deleteLater()
