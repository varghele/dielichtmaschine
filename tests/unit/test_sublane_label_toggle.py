"""The 'sub-lane labels' deep setting (timeline v3, stage T2).

The DIM / COL / MOV / SPC sub-lane purpose labels live in the lane
HEADER column (LightLaneWidget.sublane_labels_widget); the canvas no
longer paints them (TimelineWidget.draw_sublane_labels was removed).
The checkable Settings-menu action persists the QSettings key
``timeline/show_sublane_labels`` (default True) and the refresh path
(ShowsTab.refresh_sublane_labels_setting -> timeline_widget.update())
re-applies it to the header column via the widget's
``sublane_labels_setting_hook``.

QSettings is hermetic in the suite (tests/conftest.py isolates it), so
flipping the key here is safe.
"""

from __future__ import annotations

import os
import types

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_KEY = "timeline/show_sublane_labels"


def _make_lane_widget(config):
    from config.models import FixtureGroupCapabilities
    from timeline.light_lane import LightLane
    from timeline_ui.light_lane_widget import LightLaneWidget

    lane = LightLane(name="Test Lane", fixture_targets=["TestGroup"])
    widget = LightLaneWidget(
        lane=lane, fixture_groups=list(config.groups.keys()), config=config)
    # Synthetic fixtures resolve no definition -> pin capabilities so the
    # header actually has label rows (same trick as the golden tests).
    widget.capabilities = FixtureGroupCapabilities(
        has_dimmer=True, has_colour=True,
        has_movement=False, has_special=False)
    widget.num_sublanes = widget._count_sublanes()
    widget.refresh_sublane_labels()
    return widget


def test_header_labels_shown_by_default(qapp, sample_configuration):
    """Default (no key set) -> the header label column is visible."""
    from utils.app_settings import app_settings

    app_settings().remove(_KEY)  # default True
    widget = _make_lane_widget(sample_configuration)
    try:
        assert not widget.sublane_labels_widget.isHidden()
        assert [lbl.text() for lbl in widget.sublane_labels] == ["DIM", "COL"]
    finally:
        app_settings().remove(_KEY)
        widget.deleteLater()


def test_key_off_hides_the_header_label_column(qapp, sample_configuration):
    from utils.app_settings import app_settings

    app_settings().setValue(_KEY, False)
    widget = _make_lane_widget(sample_configuration)
    try:
        assert widget.sublane_labels_widget.isHidden()
    finally:
        app_settings().remove(_KEY)
        widget.deleteLater()


def test_refresh_route_reapplies_the_setting(qapp, sample_configuration):
    """ShowsTab.refresh_sublane_labels_setting() calls
    ``timeline_widget.update()`` on each lane; the widget's
    sublane_labels_setting_hook must re-apply the key to the header."""
    from utils.app_settings import app_settings

    app_settings().remove(_KEY)
    widget = _make_lane_widget(sample_configuration)
    try:
        assert not widget.sublane_labels_widget.isHidden()

        app_settings().setValue(_KEY, False)
        widget.timeline_widget.update()  # the shows-tab refresh path
        assert widget.sublane_labels_widget.isHidden()

        app_settings().setValue(_KEY, True)
        widget.timeline_widget.update()
        assert not widget.sublane_labels_widget.isHidden()
    finally:
        app_settings().remove(_KEY)
        widget.deleteLater()


def test_canvas_no_longer_draws_sublane_labels(qapp):
    """The in-canvas painted labels are gone: the draw path was removed
    outright, not just short-circuited."""
    from timeline_ui.timeline_widget import TimelineWidget

    assert not hasattr(TimelineWidget, "draw_sublane_labels")


def test_settings_action_exists_and_is_checkable(qapp):
    from PyQt6.QtWidgets import QMainWindow
    from gui.Ui_MainWindow import Ui_MainWindow

    window = QMainWindow()
    try:
        ui = Ui_MainWindow()
        ui.setupUi(window)
        action = ui.actionShowSublaneLabels
        assert action.isCheckable()
        assert action in ui.menuSettings.actions()
        assert action.text() == "Show timeline sub-lane labels"
    finally:
        window.deleteLater()


def test_action_handler_persists_key_and_repaints(qapp):
    """MainWindow._on_toggle_sublane_labels writes the key and repaints
    the Show Timeline lanes."""
    from gui.gui import MainWindow
    from utils.app_settings import app_settings

    calls = []
    fake = types.SimpleNamespace(
        shows_tab=types.SimpleNamespace(
            refresh_sublane_labels_setting=lambda: calls.append(True)))

    try:
        MainWindow._on_toggle_sublane_labels(fake, False)
        assert app_settings().value(_KEY, True, type=bool) is False
        assert calls == [True]

        MainWindow._on_toggle_sublane_labels(fake, True)
        assert app_settings().value(_KEY, True, type=bool) is True
        assert calls == [True, True]
    finally:
        app_settings().remove(_KEY)
