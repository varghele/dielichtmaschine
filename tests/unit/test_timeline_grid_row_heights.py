# tests/unit/test_timeline_grid_row_heights.py
"""Grid row heights for embedded light lanes (fix 2026-07-16): a
dimmer-only lane's stripe is a single 50 px sublane band, and the grid
used to take that as the ROW height - the header's name row and the
M/S chip row got crushed and mute/solo were unreachable (found on the
SBD Sunstrips lane). The row must fit the header's control panel
(min_lane_height), with headers and stripes - separate columns -
always sharing the same height."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from config.models import Configuration, Fixture, FixtureGroup, \
    FixtureMode, Universe
from timeline.light_lane import LightLane


def _suns_config():
    """One group of Sunstrips - the bundled definition is dimmer-only,
    so the lane renders a single sublane."""
    fixtures = [Fixture(universe=1, address=1 + i * 10,
                        manufacturer="Showtec", model="Sunstrip Active",
                        current_mode="10 Channels Mode",
                        available_modes=[FixtureMode(
                            name="10 Channels Mode", channels=10)],
                        name=f"SUN{i + 1}", group="SUNS")
                for i in range(2)]
    cfg = Configuration(
        fixtures=fixtures,
        groups={"SUNS": FixtureGroup("SUNS", fixtures)},
        universes={1: Universe(id=1, name="U1", output={})})
    cfg.songs = {}
    return cfg


def _lane_widget(config, targets):
    from timeline_ui.light_lane_widget import LightLaneWidget
    lane = LightLane(name="Suns", fixture_targets=targets)
    return LightLaneWidget(lane=lane,
                           fixture_groups=list(config.groups.keys()),
                           config=config)


class TestGridRowHeights:

    def test_dimmer_only_lane_keeps_its_control_panel(self, qapp):
        from PyQt6.QtWidgets import QApplication
        from timeline_ui.timeline_grid import TimelineGrid

        widget = _lane_widget(_suns_config(), ["SUNS"])
        assert widget.num_sublanes == 1, \
            "precondition drifted: Sunstrips must be a 1-sublane lane"
        grid = TimelineGrid()
        grid.add_light_lane(widget)
        row = grid._lane_rows[-1]
        try:
            assert row["header"].minimumHeight() >= widget.min_lane_height
            assert row["stripe"].minimumHeight() == \
                row["header"].minimumHeight()

            # The point of the height: mute/solo stay inside the header.
            grid.resize(900, 400)
            grid.show()
            for _ in range(3):
                QApplication.processEvents()
            header = row["header"]
            for button in (widget.mute_button, widget.solo_button):
                bottom = button.mapTo(header,
                                      button.rect().bottomLeft()).y()
                assert 0 < bottom <= header.height(), (
                    f"{button.text()} chip ends at {bottom}px in a "
                    f"{header.height()}px header")
        finally:
            grid.hide()
            grid.deleteLater()
            QApplication.processEvents()

    def test_multi_sublane_lane_height_unchanged(self, qapp):
        """Full-capability lanes (no config = assume everything) keep
        their stripe-driven height - the fix only lifts short rows."""
        from PyQt6.QtWidgets import QApplication
        from timeline_ui.timeline_grid import TimelineGrid

        from timeline_ui.light_lane_widget import LightLaneWidget
        widget = LightLaneWidget(
            lane=LightLane(name="Full", fixture_targets=["G"]),
            fixture_groups=["G"])          # config=None -> 4 sublanes
        assert widget.num_sublanes == 4
        grid = TimelineGrid()
        grid.add_light_lane(widget)
        row = grid._lane_rows[-1]
        try:
            expected = widget.num_sublanes * widget.sublane_height
            assert row["stripe"].minimumHeight() == expected
            assert row["header"].minimumHeight() == expected
        finally:
            grid.deleteLater()
            QApplication.processEvents()
