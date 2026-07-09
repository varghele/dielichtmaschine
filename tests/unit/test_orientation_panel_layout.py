"""The orientation editor has to fit the Stage tab's right column.

User report: in the Stage tab the orientation editor was not fully
visible and some buttons could only be reached by scrolling sideways.
The cause was a third side-by-side group box (Group Defaults) that
pushed the panel's minimum width past the inspector column, so the
preset buttons ran off the edge behind a horizontal scrollbar.

The fix keeps Presets and Fine Adjustment side by side and drops the
apply-to-group control to its own full-width row beneath them, and the
right column was widened to fit the two sub-panels. These tests pin
both halves so the third-column regression cannot come back.

Geometry is asserted, never fonts: the offscreen platform has no font
database, so glyph widths are meaningless here (docs/qt-gotchas.md).
"""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFrame, QGroupBox, QScrollArea

from gui.dialogs.orientation_dialog import OrientationDialog, OrientationPanel
from gui.tabs.stage_tab import RIGHT_COLUMN_WIDTH


def _group(panel, title):
    for box in panel.findChildren(QGroupBox):
        if box.title() == title:
            return box
    raise AssertionError(f"no group box titled {title!r}")


def _y_span(root, widget):
    """(top, bottom) of widget in root's coordinate space."""
    top = widget.mapTo(root, widget.rect().topLeft()).y()
    return top, top + widget.height()


@pytest.fixture
def hosted(qapp):
    """The panel inside the exact scroll host the Stage tab uses, sized to
    the real inspector column so scrollbar visibility is meaningful."""
    panel = OrientationPanel([], None)
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    scroll.setWidget(panel)
    # The scroll area is the full column; its viewport is a little narrower.
    scroll.resize(RIGHT_COLUMN_WIDTH, 720)
    scroll.show()
    qapp.processEvents()
    yield scroll, panel
    panel.cleanup()
    scroll.deleteLater()


class TestFitsTheColumn:
    def test_min_width_is_within_the_right_column(self, hosted):
        _, panel = hosted
        assert panel.minimumSizeHint().width() <= RIGHT_COLUMN_WIDTH

    def test_no_horizontal_scrollbar_in_the_column(self, hosted):
        """The literal complaint: buttons reachable only by scrolling."""
        scroll, _ = hosted
        assert not scroll.horizontalScrollBar().isVisible()

    def test_presets_and_fine_adjustment_sit_side_by_side(self, hosted):
        _, panel = hosted
        presets = _group(panel, "Presets")
        adjust = _group(panel, "Fine Adjustment")
        p_top, p_bot = _y_span(panel, presets)
        a_top, a_bot = _y_span(panel, adjust)
        # Overlapping vertical spans => same row.
        assert p_top < a_bot and a_top < p_bot

    def test_apply_to_group_is_a_row_below_the_two_panels(self, hosted):
        _, panel = hosted
        presets = _group(panel, "Presets")
        adjust = _group(panel, "Fine Adjustment")
        _, presets_bottom = _y_span(panel, presets)
        _, adjust_bottom = _y_span(panel, adjust)
        cb_top, _ = _y_span(panel, panel.apply_to_group_checkbox)
        assert cb_top >= presets_bottom
        assert cb_top >= adjust_bottom

    def test_there_are_exactly_the_expected_group_boxes(self, hosted):
        """A fourth side-by-side box is what caused the overflow."""
        _, panel = hosted
        titles = {b.title() for b in panel.findChildren(QGroupBox)}
        assert titles == {"3D Preview", "Presets", "Fine Adjustment",
                          "Group Defaults"}

    def test_every_preset_button_is_inside_the_viewport(self, hosted):
        """No button hangs off the right edge (the scrolling complaint)."""
        scroll, panel = hosted
        viewport_right = scroll.viewport().width()
        for name, btn in panel.preset_buttons.items():
            right = btn.mapTo(panel, btn.rect().topRight()).x()
            assert right <= viewport_right, f"{name} button clipped at edge"


class TestInlinePreviewHidden:
    """The Stage tab shows a live 3D visualizer at the top of the same
    column, so the panel's own mini preview is redundant inline and only
    steals room from the controls. It must be hideable, and hiding it must
    not affect the width fit."""

    def test_panel_exposes_the_preview_group(self, qapp):
        panel = OrientationPanel([], None)
        try:
            assert isinstance(panel.preview_group, QGroupBox)
        finally:
            panel.cleanup()
            panel.deleteLater()

    def test_hiding_preview_keeps_the_width_fit(self, qapp):
        panel = OrientationPanel([], None)
        try:
            panel.preview_group.setVisible(False)
            assert panel.preview_group.isHidden()
            assert panel.minimumSizeHint().width() <= RIGHT_COLUMN_WIDTH
        finally:
            panel.cleanup()
            panel.deleteLater()

    def test_stage_tab_hides_the_inline_preview(self, qapp):
        from config.models import Configuration
        from gui.tabs.stage_tab import StageTab
        tab = StageTab(Configuration(), parent=None)
        try:
            assert tab.orientation_panel.preview_group.isHidden()
        finally:
            tab.deleteLater()

    def test_modal_keeps_its_preview(self, qapp):
        dialog = OrientationDialog([], None)
        try:
            assert not dialog.panel.preview_group.isHidden()
        finally:
            dialog.close()
            dialog.deleteLater()


class TestModalStillOpensEverything:
    def test_apply_and_cancel_fit_within_the_minimum_dialog(self, qapp):
        dialog = OrientationDialog([], None)
        try:
            dialog.resize(dialog.minimumSize())
            dialog.show()
            qapp.processEvents()
            for btn in (dialog.cancel_btn, dialog.apply_btn):
                bottom = btn.mapTo(dialog, btn.rect().bottomLeft()).y()
                assert bottom <= dialog.height(), "action button clipped below"
        finally:
            dialog.close()
            dialog.deleteLater()
