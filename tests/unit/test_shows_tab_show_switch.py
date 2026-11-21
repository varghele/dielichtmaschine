"""Regression test for the lane-cleanup race that caused the floating-rectangle
+ native crash on show switch in the Shows tab.

Symptom (May 2026, archive/conf_v9.yaml):
- Loading a config and then switching shows in the Shows tab left a
  phantom "floating rectangle" from the previous show's lane.
- On Windows the same action terminated the process with native
  STATUS_STACK_BUFFER_OVERRUN (exit code 0xC0000409), no Python
  traceback.

Root cause: `_load_show` called `QApplication.processEvents()` *inside*
the lane-creation loop. Deferred `deleteLater` calls from the prior
`_clear_light_lanes()` would fire mid-build, racing against new lane
widgets being inserted into the TimelineGrid layout. The half-deleted
widget receiving a paint event was the native-crash trigger. Fix: drain
deferred deletes BEFORE adding the new lanes, and don't pump events
during the add loop.

We test at the TimelineGrid + LightLaneWidget layer rather than the
whole ShowsTab, because constructing ShowsTab headlessly hangs on the
embedded-OpenGL visualizer and audio-engine init. The TimelineGrid lane
lifecycle is where the bug actually lives, and exercising it directly is
both faster and more focused.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _make_light_lane(name: str):
    from config.models import LightLane as LightLaneModel
    from timeline.light_lane import LightLane
    model = LightLaneModel(name=name, fixture_targets=[], light_blocks=[])
    return LightLane.from_data_model(model)


def _make_lane_widget(qapp, lane_name: str):
    from timeline_ui.light_lane_widget import LightLaneWidget
    return LightLaneWidget(_make_light_lane(lane_name), fixture_groups=["TestGroup"])


def test_timeline_grid_add_remove_round_trip(qapp):
    """Adding and removing lanes should leave the grid's internal row list
    consistent with what was added."""
    from PyQt6.QtWidgets import QApplication
    from gui.theme_manager import ThemeManager
    from timeline_ui.timeline_grid import TimelineGrid

    ThemeManager().apply(qapp, "dark")
    grid = TimelineGrid()

    try:
        a1 = _make_lane_widget(qapp, "A1")
        a2 = _make_lane_widget(qapp, "A2")
        grid.add_light_lane(a1)
        grid.add_light_lane(a2)
        QApplication.processEvents()
        assert len(grid.light_lanes()) == 2

        # Remove both
        grid.remove_light_lane(a1)
        grid.remove_light_lane(a2)
        QApplication.processEvents()
        assert len(grid.light_lanes()) == 0, \
            "TimelineGrid.light_lanes() should be empty after removal"
    finally:
        grid.deleteLater()
        QApplication.processEvents()


def test_add_light_lane_hides_empty_shell(qapp):
    """After add_light_lane detaches a lane's header + stripe into the grid, the
    now-empty LightLaneWidget shell must be hidden — otherwise its themed QFrame
    lingers at (0,0) over the tab as a stray panel (the top-left 'blob' bug)."""
    from PyQt6.QtWidgets import QApplication
    from gui.theme_manager import ThemeManager
    from timeline_ui.timeline_grid import TimelineGrid

    ThemeManager().apply(qapp, "dark")
    grid = TimelineGrid()
    try:
        lane = _make_lane_widget(qapp, "A1")
        lane.show()  # mimic the shell being visible as a child of the tab
        QApplication.processEvents()
        assert not lane.isHidden()

        grid.add_light_lane(lane)
        QApplication.processEvents()
        assert lane.isHidden(), \
            "emptied lane shell must be hidden after add_light_lane (blob bug)"
    finally:
        grid.deleteLater()
        QApplication.processEvents()


def test_clear_then_add_no_phantom_rows(qapp):
    """The bug fingerprint: remove all lanes, then immediately add a different
    set, and confirm only the new lanes remain in the grid. Replicates the
    `_load_show` sequence (clear -> add) that produced the floating rectangle."""
    from PyQt6.QtWidgets import QApplication
    from gui.theme_manager import ThemeManager
    from timeline_ui.timeline_grid import TimelineGrid

    ThemeManager().apply(qapp, "dark")
    grid = TimelineGrid()

    try:
        # Show A: 3 lanes
        show_a_widgets = [_make_lane_widget(qapp, f"A{i}") for i in range(3)]
        for w in show_a_widgets:
            grid.add_light_lane(w)
        QApplication.processEvents()
        assert len(grid.light_lanes()) == 3

        # Clear (mimics _clear_light_lanes)
        for w in show_a_widgets:
            grid.remove_light_lane(w)
        QApplication.processEvents()
        assert len(grid.light_lanes()) == 0, \
            "After clearing all lanes the grid still holds rows from show A"

        # Show B: 2 different lanes
        show_b_widgets = [_make_lane_widget(qapp, f"B{i}") for i in range(2)]
        for w in show_b_widgets:
            grid.add_light_lane(w)
        QApplication.processEvents()

        assert len(grid.light_lanes()) == 2, \
            (f"After loading show B expected 2 lanes, got {len(grid.light_lanes())}"
             f" - phantom show A lanes leaked into the grid layout.")
        names = [w.lane.name for w in grid.light_lanes()]
        assert names == ["B0", "B1"], \
            f"Grid lanes are not show B's: {names}"
    finally:
        grid.deleteLater()
        QApplication.processEvents()


def test_repeated_switches_dont_leak_rows(qapp):
    """Bug occasionally only manifests after several switches in a row.
    Bounce between two lane sets a few times and confirm the row count
    matches the latest set each round."""
    from PyQt6.QtWidgets import QApplication
    from gui.theme_manager import ThemeManager
    from timeline_ui.timeline_grid import TimelineGrid

    ThemeManager().apply(qapp, "dark")
    grid = TimelineGrid()

    try:
        for round_ in range(4):
            # Load A
            a_widgets = [_make_lane_widget(qapp, f"A{i}_{round_}") for i in range(3)]
            for w in a_widgets:
                grid.add_light_lane(w)
            QApplication.processEvents()
            assert len(grid.light_lanes()) == 3, \
                f"Round {round_} (A): expected 3, got {len(grid.light_lanes())}"

            # Clear A
            for w in a_widgets:
                grid.remove_light_lane(w)
            QApplication.processEvents()
            assert len(grid.light_lanes()) == 0, \
                f"Round {round_}: lanes leaked after clearing A"

            # Load B
            b_widgets = [_make_lane_widget(qapp, f"B{i}_{round_}") for i in range(2)]
            for w in b_widgets:
                grid.add_light_lane(w)
            QApplication.processEvents()
            assert len(grid.light_lanes()) == 2, \
                f"Round {round_} (B): expected 2, got {len(grid.light_lanes())}"

            # Clear B for next round
            for w in b_widgets:
                grid.remove_light_lane(w)
            QApplication.processEvents()
    finally:
        grid.deleteLater()
        QApplication.processEvents()


def test_pump_events_mid_add_doesnt_corrupt_count(qapp):
    """Direct test for the `_load_show` race: pump events mid-add (which is
    what the buggy code did via QApplication.processEvents() inside the
    loop). If pending deleteLater calls from a prior clear are still in
    the queue, this is when they fire, and the layout state can drift.
    The fix is to drain events BEFORE the add loop starts."""
    from PyQt6.QtWidgets import QApplication
    from gui.theme_manager import ThemeManager
    from timeline_ui.timeline_grid import TimelineGrid

    ThemeManager().apply(qapp, "dark")
    grid = TimelineGrid()

    try:
        # Seed with show A and clear (queues deleteLater)
        show_a = [_make_lane_widget(qapp, f"A{i}") for i in range(3)]
        for w in show_a:
            grid.add_light_lane(w)
        for w in show_a:
            grid.remove_light_lane(w)
        # NOTE: no processEvents here yet - the deleteLater is still queued.

        # Now add show B WHILE pumping events between each add (the race the
        # buggy code created with its in-loop processEvents):
        show_b = [_make_lane_widget(qapp, f"B{i}") for i in range(3)]
        for w in show_b:
            grid.add_light_lane(w)
            QApplication.processEvents()  # pending deleteLater for show A fires here

        assert len(grid.light_lanes()) == 3, \
            (f"After racy add loop expected 3 show-B lanes, got {len(grid.light_lanes())}."
             " Pending show-A deleteLater corrupted the grid row list.")
        names = sorted(w.lane.name for w in grid.light_lanes())
        assert names == ["B0", "B1", "B2"], \
            f"Grid lanes are not show B's: {names}"
    finally:
        grid.deleteLater()
        QApplication.processEvents()
