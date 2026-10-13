# tests/unit/test_playhead_dirty_rect.py
"""Playback repaint discipline (2026-07-16 lag fix): moving the
playhead must invalidate only narrow strips around the old and new
line, never the whole canvas - the visual tick calls
set_playhead_position on every stripe at ~30 FPS, and full-canvas
updates cost ~137 ms per tick on a real project (UI thread
saturation). Zoom and explicit update() keep full repaints."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication


def _flush(qapp, n=4):
    for _ in range(n):
        qapp.processEvents()


class _PaintSpy:
    """Mixin factory: subclass a widget class to record paint regions."""

    @staticmethod
    def wrap(widget_cls, *args, **kwargs):
        class Spy(widget_cls):
            def __init__(self, *a, **k):
                self.paint_regions = []
                super().__init__(*a, **k)

            def paintEvent(self, event):
                self.paint_regions.append(event.region().boundingRect())
                super().paintEvent(event)

        return Spy(*args, **kwargs)


class TestPlayheadDirtyRects:

    def _drive(self, qapp, widget, positions):
        widget.resize(1200, 90)
        widget.show()
        _flush(qapp)
        widget.paint_regions.clear()
        for pos in positions:
            widget.set_playhead_position(pos)
            _flush(qapp)
        return list(widget.paint_regions)

    def test_timeline_widget_playhead_moves_paint_narrow(self, qapp):
        from timeline_ui.timeline_widget import TimelineWidget
        widget = _PaintSpy.wrap(TimelineWidget)
        # Consecutive playback ticks: small forward steps.
        regions = self._drive(qapp, widget,
                              [1.0, 1.033, 1.066, 1.1, 1.133])
        assert regions, "playhead moves must repaint something"
        widest = max(r.width() for r in regions)
        assert widest < 80, (
            f"playhead tick repainted {widest}px wide - the dirty-rect "
            f"discipline regressed to (near-)full-canvas updates")

    def test_master_widget_playhead_moves_paint_narrow(self, qapp):
        from timeline_ui.master_timeline_widget import MasterTimelineWidget
        widget = _PaintSpy.wrap(MasterTimelineWidget)
        regions = self._drive(qapp, widget,
                              [2.0, 2.033, 2.066, 2.1])
        assert regions
        # Two strips + the tick gap may coalesce into one region at the
        # ruler's zoom; anything near full width is the regression.
        widest = max(r.width() for r in regions)
        assert widest < 400, (
            f"master playhead tick repainted {widest}px wide")

    def test_unchanged_position_paints_nothing(self, qapp):
        from timeline_ui.timeline_widget import TimelineWidget
        widget = _PaintSpy.wrap(TimelineWidget)
        widget.resize(1200, 90)
        widget.show()
        _flush(qapp)
        widget.set_playhead_position(3.0)
        _flush(qapp)
        widget.paint_regions.clear()
        widget.set_playhead_position(3.0)      # no movement
        _flush(qapp)
        assert widget.paint_regions == []

    def test_full_update_still_repaints_everything(self, qapp):
        from timeline_ui.timeline_widget import TimelineWidget
        widget = _PaintSpy.wrap(TimelineWidget)
        widget.resize(1200, 90)
        widget.show()
        _flush(qapp)
        widget.paint_regions.clear()
        widget.update()                        # zoom/edit-style repaint
        _flush(qapp)
        assert widget.paint_regions
        assert max(r.width() for r in widget.paint_regions) >= 1200
