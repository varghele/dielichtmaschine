"""The hidden 'sub-lane purpose labels' deep setting.

The faint labels drawn at the start of each timeline sub-lane row
(dimmer / colour / movement / special) can be switched off via a
checkable Settings-menu action, persisted to the QSettings key
``timeline/show_sublane_labels`` (default True). The render path in
``TimelineWidget.draw_sublane_labels`` reads the flag and skips drawing
when it is off.

QSettings is hermetic in the suite (tests/conftest.py isolates it), so
flipping the key here is safe.
"""

from __future__ import annotations

import os
import types

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_KEY = "timeline/show_sublane_labels"


def _timeline_widget(qapp):
    from config.models import FixtureGroupCapabilities
    from gui.theme_manager import ThemeManager
    from timeline_ui.timeline_widget import TimelineWidget

    ThemeManager().apply(qapp, "dark")
    tw = TimelineWidget()
    tw.num_sublanes = 2
    tw.sublane_height = 50
    tw.capabilities = FixtureGroupCapabilities(
        has_dimmer=True, has_colour=True,
        has_movement=False, has_special=False)
    tw.setFixedSize(400, 100)
    return tw


def _grab(tw):
    from tests.visual.harness import qimage_to_array
    return qimage_to_array(tw.grab().toImage())


def test_labels_drawn_by_default(qapp):
    """Default (no key set) -> labels render, so the on/off grabs differ."""
    import numpy as np
    from utils.app_settings import app_settings

    app_settings().remove(_KEY)  # default True
    tw = _timeline_widget(qapp)
    try:
        on = _grab(tw)

        app_settings().setValue(_KEY, False)
        tw.update()
        off = _grab(tw)

        assert not np.array_equal(on, off), \
            "sub-lane labels did not change when the flag was toggled"
    finally:
        app_settings().remove(_KEY)
        tw.deleteLater()


def test_render_path_reads_the_flag(qapp):
    """With the flag off the label chip area (top-left) is left untouched,
    matching a widget that has no sub-lanes to label."""
    import numpy as np
    from utils.app_settings import app_settings

    tw = _timeline_widget(qapp)
    try:
        app_settings().setValue(_KEY, False)
        tw.update()
        off = _grab(tw)

        # A single-sublane widget never draws the labels either; the
        # top-left label region must match between the two.
        tw.num_sublanes = 1
        tw.update()
        baseline = _grab(tw)

        region = np.s_[0:24, 0:70]  # the first label chip's area
        assert np.array_equal(off[region], baseline[region])
    finally:
        app_settings().remove(_KEY)
        tw.deleteLater()


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
