"""View > Theme on the live main window restyles the token-built chrome.

The v1.5.6 theme sweep follow-up: inline stylesheets are baked, so a
widget-local sheet built from the tokens at construction kept the old
theme's colours after a runtime switch (the Stage plan's title block,
legend and badge, the Fixtures table tints, the Structure part cards,
the master timeline readout, the riff cards, the Auto engine log, the
Shows/Auto pane chevrons inked from the persisted, not yet updated,
theme). They are now bound (gui.theme_style.bind_style) or re-run by
the owning tab on StyleChange.

The broad check scans every widget-local stylesheet in the window for
a value that only the OLD theme uses; the targeted checks pin the
surfaces that were fixed, so a regression names its widget.
"""

import os

import pytest
from PyQt6.QtCore import QEvent
from PyQt6.QtGui import QColor
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QWidget

from gui.theme_tokens import DARK, LIGHT
from tests.e2e.conftest import (TAB_AUTO, TAB_CONFIG, TAB_FIXTURES,
                                TAB_SHOWS, TAB_STAGE, TAB_STRUCTURE,
                                goto_tab, project_path)

DEMO = "demos/shows/club_band.lms"


def _only_in(tokens: dict, other: dict) -> set:
    """Colour values one theme uses and the other never does."""
    others = {v.upper() for v in other.values() if isinstance(v, str)}
    return {v.upper() for v in tokens.values()
            if isinstance(v, str) and v.startswith("#")
            and v.upper() not in others}


def _flush():
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
    QApplication.processEvents()


def _load_demo(window):
    window.open_recent_config(project_path(DEMO))
    for _ in range(250):
        if window.config.songs:
            break
        QTest.qWait(20)
    assert window.config.songs, "demo project did not load"
    for tab in (TAB_CONFIG, TAB_FIXTURES, TAB_STAGE, TAB_STRUCTURE,
                TAB_SHOWS, TAB_AUTO):
        goto_tab(window, tab)
    _flush()


def _stale_sheets(window, old: dict, new: dict) -> list:
    """Widget-local sheets in the main window carrying ``old``-only
    colours. Separate windows (dialogs) are skipped: the modal ones
    read the tokens once by design, nothing can switch while they are
    open (a closed loading-progress dialog lingers as a child)."""
    stale = _only_in(old, new)
    out = []
    for widget in [window] + window.findChildren(QWidget):
        if widget.window() is not window:
            continue
        sheet = widget.styleSheet().upper()
        hits = sorted(v for v in stale if v in sheet)
        if hits:
            out.append(f"{type(widget).__name__}"
                       f"#{widget.objectName() or '-'}: {hits}")
    return out


def _icon_ink(icon) -> str:
    """The opaque stroke colour of a line icon, as #RRGGBB."""
    image = icon.pixmap(16, 16).toImage()
    for y in range(image.height()):
        for x in range(image.width()):
            colour = image.pixelColor(x, y)
            if colour.alpha() == 255:
                return colour.name().upper()
    raise AssertionError("icon paints nothing opaque")


@pytest.fixture
def themed_window(main_window):
    _load_demo(main_window)
    yield main_window
    # Never leak light into the rest of the session (token painters
    # read the GLOBAL stylesheet).
    main_window._set_theme("dark")
    _flush()


@pytest.fixture(params=[("dark", "light"), ("light", "dark")],
                ids=["dark-to-light", "light-to-dark"])
def switch(request, qapp):
    """(start, target); the start theme is applied BEFORE the window
    is built, so its widgets are constructed in it."""
    from gui.theme_manager import ThemeManager
    start, target = request.param
    ThemeManager().apply(qapp, start)
    yield start, target
    ThemeManager().apply(qapp, "dark")


def test_no_widget_keeps_the_old_theme_after_a_switch(switch, main_window):
    themes = {"dark": DARK, "light": LIGHT}
    start, target = switch
    window = main_window
    _load_demo(window)
    assert not _stale_sheets(window, themes[target], themes[start]), \
        "precondition: the window was built in the start theme"
    window._set_theme(target)
    _flush()
    stale = _stale_sheets(window, themes[start], themes[target])
    try:
        assert not stale, (
            f"widget-local sheets still carry {start}-only colours after "
            f"switching to {target} (bind them: gui.theme_style.bind_style):"
            "\n  " + "\n  ".join(stale))
    finally:
        window._set_theme("dark")
        _flush()


class TestSwitchedSurfaces:
    """dark -> light on the surfaces the follow-up fixed."""

    @pytest.fixture
    def window(self, themed_window):
        themed_window._set_theme("light")
        _flush()
        return themed_window

    def test_stage_plan_chrome(self, window):
        stage = window.stage_tab
        assert stage._tokens is LIGHT
        assert LIGHT["raised"] in stage.title_block.styleSheet()
        assert LIGHT["border"] in stage.title_name.styleSheet()
        assert LIGHT["text"] in stage.title_name.styleSheet()
        assert LIGHT["accent_line"] in stage.active_layer_badge.styleSheet()
        assert LIGHT["text_secondary"] in \
            stage.legend_active_label.styleSheet()
        for section in stage.sections.values():
            assert section._color == LIGHT["text_secondary"]
        assert _icon_ink(stage.export_rider_btn.icon()) == \
            LIGHT["text_secondary"].upper()

    def test_orientation_rotate_buttons_keep_their_padding(self, window):
        panel_buttons = [b for b in window.stage_tab.findChildren(QWidget)
                         if getattr(b, "text", lambda: "")() == "+90°"]
        assert panel_buttons
        for button in panel_buttons:
            sheet = button.styleSheet()
            assert "padding: 4px 2px;" in sheet
            assert "background-color: #" in sheet

    def test_fixtures_table_tints(self, window):
        from gui.tabs.fixtures_tab import COL_FIXTURE, group_tint_color
        fixtures = window.fixtures_tab
        assert fixtures._tokens is LIGHT
        fixture = window.config.fixtures[0]
        group = window.config.groups[fixture.groups[0]]
        expected = group_tint_color(QColor(group.color),
                                    QColor(LIGHT["panel"])).name()
        item = fixtures.table.item(0, COL_FIXTURE)
        assert item.background().color().name() == expected
        assert item.foreground().color().name().upper() == \
            LIGHT["text"].upper()

    def test_structure_part_cards(self, window):
        structure = window.structure_tab
        assert structure._tokens is LIGHT
        assert structure._cards
        assert LIGHT["text_secondary"] in structure._cards[0].styleSheet()

    def test_master_timeline_readout(self, window):
        # The container hands its pieces to the timeline grid and is
        # itself parentless: reach it through the Shows tab.
        info = window.shows_tab.master_timeline.info_widget
        assert LIGHT["text_secondary"] in info.styleSheet()

    def test_riff_cards(self, window):
        from timeline_ui.riff_browser_widget import RiffItemWidget
        cards = window.findChildren(RiffItemWidget)
        if not cards:
            pytest.skip("no riffs in this checkout's library")
        for card in cards:
            assert LIGHT["raised"] in card.styleSheet()

    def test_auto_engine_log_and_meter(self, window):
        from gui.tabs.auto_tab import _Bar
        auto = window.auto_tab
        auto._engine_log_view.render_entries([("00:01", "msg", False),
                                               ("00:02", "hit", True)])
        window._set_theme("dark")
        window._set_theme("light")
        _flush()
        sheets = [w.styleSheet()
                  for w in auto._engine_log_view.findChildren(QWidget)]
        assert any(s.startswith(f"color: {LIGHT['text_disabled']};")
                   for s in sheets)
        assert any(s.startswith(f"color: {LIGHT['accent_line']};")
                   for s in sheets)
        contrast = [b for b in auto.findChildren(_Bar)
                    if b._fill_role == "text_secondary"]
        assert contrast, "contrast meter reads its fill at paint time"

    def test_pane_chevrons_follow_the_applied_theme(self, window):
        """_set_theme applies before it persists: the StyleChange
        re-ink must read the APPLIED theme, not the settings store."""
        shows = window.shows_tab
        assert _icon_ink(shows.pane_toggle_btn.icon()) == \
            LIGHT["text_secondary"].upper()
        assert _icon_ink(window.auto_tab._pane_toggle_btn.icon()) == \
            LIGHT["text_secondary"].upper()


def test_initial_render_unchanged_by_binding(main_window):
    """A bound sheet is the same string the baked one was (the pixel
    proof of the follow-up rests on it): spot-check the stage title
    block against the literal it used to be."""
    stage = main_window.stage_tab
    assert stage.title_block.styleSheet() == (
        "#StageTitleBlock {"
        f" background-color: {DARK['raised']};"
        f" border: 1px solid {DARK['border']}; }}")


def test_demo_is_present():
    assert os.path.isfile(project_path(DEMO))
