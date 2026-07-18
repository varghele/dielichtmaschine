# tests/visual/test_720p_layout.py
"""Every tab stays functional on a small (720p) screen.

The real MainWindow, demo project loaded, forced to 1280x720 the way a
small laptop would size it. Per tab: (1) the tab's minimumSizeHint
must FIT the viewport the shell leaves it - Qt propagates tab minimums
through the stack into the WINDOW minimum, and Windows enforces that
via WM_GETMINMAXINFO, so a tab that wants more than the screen keeps
the whole window from fitting the display at all; (2) a golden
screenshot pins how the squeezed layout actually renders.

History: as probed 2026-07-18, STRUCTURE wanted 642px of height
against the ~614 the shell leaves at 720p and LIVE wanted 1458x970 -
together they pushed the window minimum to 1462x1020, so a 720p
display could not show the whole app. Fixed the same day with
explicit 720p minimum-size floors on the LIVE pools host and the
STRUCTURE centre column (the floors override the layouts' demanded
minimums; the squeezed renders are pinned by the goldens here). A tab
that regresses past its viewport fails its fit test again - add an
xfail mark in TABS only with a plan to remove it.

Construction mirrors tests/e2e/conftest.main_window (ShowsTab does
not construct headlessly without the stubs); the scene library is
injected in-test because scenes/ categories are machine-local data.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from tests.visual.harness import compare_to_golden

W, H = 1280, 720

#: (tab index, golden slug, known-720p-overflow reason or None)
TABS = [
    (0, "configuration", None),
    (1, "fixtures", None),
    (2, "stage", None),
    (3, "structure", None),
    (4, "shows", None),
    (5, "auto", None),
    (6, "live", None),
]


def _tab_params():
    for index, slug, overflow in TABS:
        marks = ()
        if overflow:
            marks = (pytest.mark.xfail(strict=True, reason=overflow),)
        yield pytest.param(index, slug, id=slug, marks=marks)


@pytest.fixture(scope="module")
def small_window(qapp):
    """The real shell at 1280x720 with the demo project open.

    Module-scoped: MainWindow construction is expensive and every test
    only switches tabs. monkeypatch is function-scoped, so the e2e
    stubs ride a manual MonkeyPatch that undoes at teardown.
    """
    from _pytest.monkeypatch import MonkeyPatch
    from PyQt6.QtCore import QEvent
    from PyQt6.QtWidgets import QApplication

    from gui.theme_manager import ThemeManager
    from tests.e2e.conftest import _install_headless_stubs, \
        _warm_fixture_cache

    mp = MonkeyPatch()
    _install_headless_stubs(mp)
    _warm_fixture_cache()
    ThemeManager().apply(qapp, "dark")

    from gui.gui import MainWindow
    window = MainWindow()
    window.status_timer.stop()
    window.shows_tab.artnet_enabled = False
    window.shows_tab.tcp_enabled = False
    mp.setattr(window, "_launch_visualizer", lambda *a, **k: None,
               raising=False)

    # Machine-independent SCENES pool (scenes/ categories are local
    # gig data): the same in-test library the Live golden uses.
    from config.models import Scene
    from scenes.scene_library import SceneLibrary
    scene_lib = SceneLibrary(scenes_directory=os.path.join(
        os.path.dirname(__file__), "no_such_scenes_dir"))
    for name, cat, color in (("Warm Wash", "looks", "#F0562E"),
                             ("Cold Snap", "looks", "#4ECBD4")):
        scene_lib.add_scene(Scene(name=name, category=cat, color=color),
                            category=cat)
    window.scene_library = scene_lib
    window.live_tab.set_scene_library(scene_lib)

    demo = os.path.join(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))),
        "demos", "shows", "club_band.lms")
    window.open_recent_config(demo)
    # The open flow defers the actual load through a 100 ms
    # QTimer.singleShot; processEvents() alone does not advance the
    # clock, so whether the project was loaded by grab time depended
    # on wall time spent elsewhere (the goldens raced run-to-run).
    # qWait pumps AND waits - block until the load really happened.
    from PyQt6.QtTest import QTest
    for _ in range(200):
        if window.config.songs:
            break
        QTest.qWait(20)
    assert window.config.songs, \
        "the demo project did not load in the 720p fixture"
    window.page_stack.setCurrentWidget(window.tabWidget)

    # The WINDOW minimum a real WM would enforce, before we override
    # it to force the small geometry (test_window_minimum reads this).
    natural_min = window.minimumSizeHint()

    window.setMinimumSize(1, 1)
    window.resize(W, H)
    window.show()
    for _ in range(20):
        QApplication.processEvents()

    window._natural_min = natural_min
    try:
        yield window
    finally:
        for tab in (window.shows_tab, window.stage_tab, window.auto_tab):
            try:
                tab.cleanup()
            except Exception:
                pass
        window.deleteLater()
        QApplication.sendPostedEvents(None,
                                      QEvent.Type.DeferredDelete.value)
        QApplication.processEvents()
        mp.undo()


def _open_tab(window, index):
    from PyQt6.QtWidgets import QApplication
    window.tabWidget.setCurrentIndex(index)
    for _ in range(15):
        QApplication.processEvents()
    return window.tabWidget.widget(index)


@pytest.mark.parametrize("index, slug", _tab_params())
def test_tab_fits_720p(small_window, index, slug):
    """The tab's minimum layout size fits the viewport the shell
    leaves it at 1280x720 - the condition for the window being able to
    exist on a 720p screen with this tab usable."""
    tab = _open_tab(small_window, index)
    hint = tab.minimumSizeHint()
    assert hint.width() <= tab.width() and hint.height() <= tab.height(), (
        f"{slug}: minimumSizeHint {hint.width()}x{hint.height()} exceeds "
        f"the {tab.width()}x{tab.height()} viewport at {W}x{H} - this "
        f"tab pushes the window minimum beyond a 720p screen"
    )


@pytest.mark.parametrize(
    "index, slug",
    [pytest.param(i, s, id=s) for i, s, _ in TABS])
def test_tab_golden_720p(small_window, index, slug):
    """How the tab actually renders squeezed to 720p (including the
    currently-overflowing ones - pinned so they cannot silently get
    worse while they wait for their layout pass)."""
    _open_tab(small_window, index)
    compare_to_golden(small_window.grab().toImage(),
                      f"720p_{slug}_dark")


def test_window_minimum_fits_a_720p_screen(small_window):
    """The WM-enforced window minimum (minimumSizeHint with no
    explicit override) fits a 1280x720 display - THE small-screen
    guarantee; every tab minimum feeds it through the tab stack."""
    natural = small_window._natural_min
    assert natural.width() <= W and natural.height() <= H, (
        f"window effective minimum {natural.width()}x{natural.height()} "
        f"exceeds {W}x{H}"
    )
