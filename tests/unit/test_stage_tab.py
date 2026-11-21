"""
StageTab regressions — orientation-axes UX, theme-driven stage chrome.

The chrome colours come from QSS via ``StageView`` qproperty rules
(``qproperty-stageFillColor`` etc.) declared as ``pyqtProperty(QColor)``
on the class. Adding a new theme means filling these in for the new
theme stylesheet — no Python edit required.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_show_orientation_axes_checkbox_toggles_class_attribute(qapp, sample_configuration):
    """Single ``Show orientation axes`` checkbox flips
    ``FixtureItem.show_orientation_axes`` directly. Pre-fix UX had two
    checkboxes where checking only this one with no fixture selected
    made no visible change — the user read the whole control as
    broken. Pin the simplified contract: one checkbox, one class flag,
    no per-fixture selection gating."""
    from gui.theme_manager import ThemeManager
    from gui.tabs.stage_tab import StageTab
    from gui.stage_items import FixtureItem

    ThemeManager().apply(qapp, "dark")
    FixtureItem.show_orientation_axes = False

    tab = StageTab(sample_configuration, parent=None)
    try:
        # The redundant "Show all axes" checkbox is gone.
        assert not hasattr(tab, "show_all_axes_checkbox"), (
            "show_all_axes_checkbox should have been removed — it "
            "existed only to compensate for the original selection-"
            "gated default that confused the user."
        )

        # The single checkbox flips the class flag on every state change.
        tab.show_axes_checkbox.setChecked(True)
        qapp.processEvents()
        assert FixtureItem.show_orientation_axes is True

        tab.show_axes_checkbox.setChecked(False)
        qapp.processEvents()
        assert FixtureItem.show_orientation_axes is False
    finally:
        FixtureItem.show_orientation_axes = False
        tab.deleteLater()


def test_show_all_axes_class_attribute_is_gone(qapp, sample_configuration):
    """``FixtureItem.show_all_axes`` was the second-checkbox
    selection-gating flag. The single-checkbox UX has no use for it
    and the paint() method no longer reads it — verify the attribute
    is removed so a reintroduction can't silently bring back the
    confusing UX."""
    from gui.stage_items import FixtureItem

    assert not hasattr(FixtureItem, "show_all_axes")


def test_orientation_axes_actually_render_when_enabled(qapp, sample_configuration):
    """End-to-end render test: when ``show_orientation_axes`` is True,
    the red X-axis line (RGB ≈ 255, 80, 80) is actually present in
    the rendered scene. Before this test we trusted the gate change
    without proving the paint flow works — a pixel-level check rules
    out 'the painter state is wrong' or 'the bounding rect clips it'
    bugs in one go."""
    from PyQt6.QtCore import QRectF
    from PyQt6.QtGui import QImage, QPainter
    from gui.theme_manager import ThemeManager
    from gui.tabs.stage_tab import StageTab
    from gui.stage_items import FixtureItem

    ThemeManager().apply(qapp, "dark")
    FixtureItem.show_orientation_axes = False

    tab = StageTab(sample_configuration, parent=None)
    try:
        # Make sure the view has at least one fixture to render.
        view = tab.stage_view
        view.update_from_config()
        qapp.processEvents()
        assert view.scene.items(), (
            "stage view has no items to render — sample_configuration "
            "must seed at least one fixture for this test to mean anything."
        )

        def _has_red_axis_pixels() -> bool:
            """Render the scene and look for the bright-red axis pen
            colour (QPen(QColor(255, 80, 80), 2) at fixtures.py:407)
            — exact RGB so neither the centre-axis red lines (drawn
            by the view's drawBackground in scene-rect coordinates)
            nor the fixture-symbol red colours collide.
            """
            scene_rect = view.scene.itemsBoundingRect()
            if scene_rect.isEmpty():
                scene_rect = QRectF(-100, -100, 400, 400)
            else:
                scene_rect = scene_rect.adjusted(-40, -40, 40, 40)
            img = QImage(
                int(scene_rect.width()), int(scene_rect.height()),
                QImage.Format.Format_ARGB32,
            )
            img.fill(0)
            p = QPainter(img)
            try:
                view.scene.render(p, target=QRectF(img.rect()), source=scene_rect)
            finally:
                p.end()

            for y in range(img.height()):
                for x in range(img.width()):
                    px = img.pixelColor(x, y)
                    if (px.red(), px.green(), px.blue()) == (255, 80, 80):
                        return True
            return False

        # With axes off, no red axis pixels in the items area.
        # (The centre axes red line lives in the view's drawBackground,
        # not in the scene render, so scene.render() doesn't include it.)
        assert not _has_red_axis_pixels(), (
            "red axis pixels appeared in the scene render with the "
            "checkbox OFF — the gate isn't actually gating anything."
        )

        # Turn axes on and render again.
        FixtureItem.show_orientation_axes = True
        for item in view.scene.items():
            item.update()
        qapp.processEvents()

        assert _has_red_axis_pixels(), (
            "red axis pixels missing from the scene render with the "
            "checkbox ON. Likely causes: the gate isn't seeing the "
            "class-attribute change; the bounding rect is clipping the "
            "axes; or the painter state is wrong when "
            "_draw_orientation_axes runs."
        )
    finally:
        FixtureItem.show_orientation_axes = False
        tab.deleteLater()


def test_clicking_checkbox_repaints_live_viewport(qapp, sample_configuration):
    """End-to-end: clicking the checkbox must repaint the *live*
    viewport (the actual visible scene) so the user sees the axes
    appear immediately.

    The previous implementation only called ``viewport().update()``
    after flipping the class attribute. That schedules a viewport
    paint event, but each ``QGraphicsItem`` keeps its own dirty
    tracking — toggling a class-level attribute doesn't dirty any
    item, so the items' cached drawings were re-used and the axes
    never appeared in the live view (even though scene.render() to
    a fresh QImage *did* show them, which is why earlier tests
    passed but the bug stayed live). The handler now calls
    ``item.update()`` on every scene item AND ``scene.update()``,
    which forces a real repaint.

    To distinguish "the user sees the axes" from "the rendering path
    works in isolation", this test grabs the viewport widget's
    pixmap rather than asking the scene to render itself.
    """
    from PyQt6.QtCore import Qt
    from gui.theme_manager import ThemeManager
    from gui.tabs.stage_tab import StageTab
    from gui.stage_items import FixtureItem

    ThemeManager().apply(qapp, "dark")
    FixtureItem.show_orientation_axes = False

    tab = StageTab(sample_configuration, parent=None)
    try:
        # Force a real viewport size so grab() produces a non-empty
        # pixmap in offscreen mode.
        tab.resize(900, 600)
        tab.stage_view.resize(700, 500)
        tab.show()
        for _ in range(5):
            qapp.processEvents()
        # Make sure at least one fixture lives inside the viewport.
        view = tab.stage_view
        view.update_from_config()
        view.fitInView(view.scene.itemsBoundingRect().adjusted(-40, -40, 40, 40))
        for _ in range(5):
            qapp.processEvents()

        def _viewport_has_axis_red() -> bool:
            """Grab the live viewport pixmap and look for the axis-pen
            red ``(255, 80, 80)`` (allowing 2-channel tolerance for any
            antialiasing along the line edges)."""
            pix = view.viewport().grab()
            img = pix.toImage()
            for y in range(0, img.height(), 2):
                for x in range(0, img.width(), 2):
                    px = img.pixelColor(x, y)
                    if (
                        abs(px.red() - 255) <= 2
                        and abs(px.green() - 80) <= 2
                        and abs(px.blue() - 80) <= 2
                    ):
                        return True
            return False

        # Programmatic click → handler fires → axes should appear.
        tab.show_axes_checkbox.click()
        for _ in range(5):
            qapp.processEvents()

        assert tab.show_axes_checkbox.isChecked()
        assert FixtureItem.show_orientation_axes is True

        # Live viewport must now show the axes. If this fails the
        # handler isn't actually repainting the items, even though
        # scene.render() in another test would still show axes.
        assert _viewport_has_axis_red(), (
            "Clicking 'Show orientation axes' didn't repaint the "
            "live viewport — items kept their cached drawings. "
            "Handler needs to call item.update() on every fixture, "
            "not just viewport().update()."
        )
    finally:
        FixtureItem.show_orientation_axes = False
        tab.hide()
        tab.deleteLater()


def test_stage_view_qss_qproperty_overrides(qapp, sample_configuration):
    """Theme stylesheets push colours into StageView via
    ``qproperty-stageFillColor`` (etc.) — pin that the QSS engine
    actually applies them. Otherwise the stage chrome stays at its
    Python-side fallback colours and the dark theme would still look
    bright.

    Qt processes ``qproperty-*`` rules during widget polishing, which
    happens lazily on first show. We force a polish here so the test
    doesn't depend on the widget actually being visible.
    """
    from gui.theme_manager import ThemeManager
    from gui.tabs.stage_tab import StageTab

    ThemeManager().apply(qapp, "dark")
    tab = StageTab(sample_configuration, parent=None)
    try:
        view = tab.stage_view
        view.style().unpolish(view)
        view.style().polish(view)

        # Dark theme defines a dark fill for the stage rectangle —
        # the rectangle should NOT be the original (240, 240, 240)
        # light grey which is what the Python fallback uses.
        fill = view.stageFillColor
        assert fill.lightness() < 100, (
            f"StageView.stageFillColor came out at lightness "
            f"{fill.lightness()} ({fill.name()}) under the dark theme. "
            "Either the QSS rule isn't applying, or the fallback "
            "value leaked through. Check `StageView { qproperty-"
            "stageFillColor: ...; }` in dark.qss."
        )
        text = view.fixtureTextColor
        assert text.lightness() > 150, (
            f"StageView.fixtureTextColor came out at lightness "
            f"{text.lightness()} ({text.name()}) under the dark theme — "
            "fixture labels would be invisible against the dark fill."
        )
    finally:
        tab.deleteLater()


def test_stage_view_widget_background_is_dark(qapp, sample_configuration):
    """The QGraphicsView widget itself (the area around the stage
    rectangle, including the 40-px padding) must follow the dark
    theme. The original ``QWidget { color: ... }`` rule only set
    text colour — without an explicit ``StageView {
    background-color: ...; }`` rule the view rendered with the
    OS-default light background, which leaked around the stage
    rectangle and looked 'still bright' to the user.
    """
    from gui.theme_manager import ThemeManager
    from gui.tabs.stage_tab import StageTab

    ThemeManager().apply(qapp, "dark")
    tab = StageTab(sample_configuration, parent=None)
    try:
        # Effective background colour from the active stylesheet on
        # the view widget itself. Reading it via property() also
        # confirms the stylesheet engine has polished the widget.
        view = tab.stage_view
        view.show()
        qapp.processEvents()
        bg = view.palette().color(view.backgroundRole())
        # A correctly-themed dark view has lightness < 50 (#1e1e1e is
        # ~30). The OS default is roughly white (~240+).
        assert bg.lightness() < 80, (
            f"StageView widget background is too light "
            f"({bg.lightness()}, {bg.name()}) — the dark theme isn't "
            "covering the area around the stage rectangle."
        )
    finally:
        view.hide()
        tab.deleteLater()
