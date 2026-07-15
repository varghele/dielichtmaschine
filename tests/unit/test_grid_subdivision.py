"""Unit tests for the master-timeline grid subdivision feature.

The master timeline no longer carries its own Snap checkbox or Grid
combobox: the toolbar's global GRID / SNAP / SWING chips are the single
controls and fan out through ``TimelineGrid`` to master + audio + every
lane. Covers:
- ``MasterTimelineContainer.set_grid_subdivision`` pushes the value into
  the underlying ``MasterTimelineWidget`` (grid drawing) with no combobox
  and no ``subdivision_changed`` signal of its own.
- ``TimelineGrid`` fans the subdivision / snap out to the audio lane and
  every light lane (including ones added *after* the user picked a fine
  setting).
- ``TimelineWidget.find_nearest_beat_time`` honours the lane's
  ``grid_subdivision`` so block placement / drag snap to the same grid the
  user sees.
- The swing AMOUNT (timeline v3 stage T1: 0.0 off, 1.0 = the old full
  triplet feel, linear in between) moves the snapped pixel positions:
  the exact x targets are pinned for 0%, 50% and 100%.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _make_song_structure():
    from config.models import ShowPart
    from timeline.song_structure import SongStructure

    parts = [ShowPart(name="A", color="#FFF", signature="4/4",
                      bpm=120.0, num_bars=4, transition="instant")]
    ss = SongStructure()
    ss.load_from_show_parts(parts)
    return ss


def test_master_has_no_snap_or_grid_controls(qapp):
    """The master's own Snap checkbox + Grid combobox were removed - the
    toolbar chips are the single global controls now."""
    from timeline_ui.master_timeline_widget import MasterTimelineContainer

    container = MasterTimelineContainer()
    try:
        assert not hasattr(container, "snap_checkbox")
        assert not hasattr(container, "subdivision_combo")
        assert not hasattr(container, "subdivision_label")
        # And no leftover control signals on the container.
        assert not hasattr(container, "subdivision_changed")
        assert not hasattr(container, "snap_changed")
    finally:
        container.deleteLater()


def test_set_grid_subdivision_pushes_into_master_drawing(qapp):
    """set_grid_subdivision still drives the master widget's grid drawing
    (no combobox to sync, no signal to emit)."""
    from timeline_ui.master_timeline_widget import MasterTimelineContainer

    container = MasterTimelineContainer()
    try:
        assert container.timeline_widget.grid_subdivision == 1.0
        container.set_grid_subdivision(4.0)
        assert container.timeline_widget.grid_subdivision == 4.0
        container.set_grid_subdivision(0.25)
        assert container.timeline_widget.grid_subdivision == 0.25
    finally:
        container.deleteLater()


def test_timeline_grid_fans_subdivision_to_audio_and_lanes(qapp):
    from timeline.light_lane import LightLane
    from timeline_ui import (
        AudioLaneWidget, LightLaneWidget, MasterTimelineContainer, TimelineGrid,
    )

    grid = TimelineGrid()
    master = MasterTimelineContainer()
    audio = AudioLaneWidget()
    grid.set_master(master)
    grid.set_audio_lane(audio)

    lane_model = LightLane(name="L1", fixture_targets=["TestGroup"])
    lane = LightLaneWidget(lane_model, ["TestGroup"])
    grid.add_light_lane(lane)

    try:
        # The toolbar's global GRID control drives this on the grid.
        grid.set_grid_subdivision(2.0)
        assert master.timeline_widget.grid_subdivision == 2.0
        assert audio.timeline_widget.grid_subdivision == 2.0
        assert lane.timeline_widget.grid_subdivision == 2.0

        grid.set_grid_subdivision(4.0)  # 1/4-beat
        assert master.timeline_widget.grid_subdivision == 4.0
        assert audio.timeline_widget.grid_subdivision == 4.0
        assert lane.timeline_widget.grid_subdivision == 4.0
    finally:
        grid.deleteLater()
        master.deleteLater()
        audio.deleteLater()
        lane.deleteLater()


def test_late_added_light_lane_inherits_current_subdivision(qapp):
    """If the user picks 1/4-beat then adds a new lane, the new lane must
    inherit the current subdivision instead of starting at 1.
    """
    from timeline.light_lane import LightLane
    from timeline_ui import (
        LightLaneWidget, MasterTimelineContainer, TimelineGrid,
    )

    grid = TimelineGrid()
    master = MasterTimelineContainer()
    grid.set_master(master)

    # Master is already at 1/4-beat when the new lane joins.
    master.set_grid_subdivision(4.0)

    lane_model = LightLane(name="L1", fixture_targets=["TestGroup"])
    lane = LightLaneWidget(lane_model, ["TestGroup"])
    grid.add_light_lane(lane)

    try:
        assert lane.timeline_widget.grid_subdivision == 4.0
    finally:
        grid.deleteLater()
        master.deleteLater()
        lane.deleteLater()


def test_find_nearest_beat_time_uses_lane_subdivision(qapp):
    """``TimelineWidget.find_nearest_beat_time`` is what every drag/drop /
    paste / playhead-set goes through. It must reflect the lane's current
    ``grid_subdivision`` so the snap matches the visible grid.
    """
    from timeline_ui.timeline_widget import TimelineWidget

    tw = TimelineWidget()
    tw.set_song_structure(_make_song_structure())
    try:
        # 120 BPM, beat=0.5s. 0.27 → on-beat 0.5 at subdivision=1.
        tw.set_grid_subdivision(1)
        assert abs(tw.find_nearest_beat_time(0.27) - 0.5) < 1e-6

        # Same target → half-beat 0.25 at subdivision=2.
        tw.set_grid_subdivision(2)
        assert abs(tw.find_nearest_beat_time(0.27) - 0.25) < 1e-6

        # And quarter-beat 0.25 at subdivision=4 (target 0.27 rounds down).
        tw.set_grid_subdivision(4)
        assert abs(tw.find_nearest_beat_time(0.27) - 0.25) < 1e-6

        # 0.13 → 0.125 at quarter-beat (the sixteenth-note grid line).
        assert abs(tw.find_nearest_beat_time(0.13) - 0.125) < 1e-6

        # Coarse grid: subdivision 0.25 == a line every 4 beats. Beat=0.5s so
        # a step is 2.0s. A time near beat 3 (1.5s, i.e. 0.75 of a step)
        # snaps up to beat 4 (2.0s).
        tw.set_grid_subdivision(0.25)
        assert abs(tw.find_nearest_beat_time(1.5) - 2.0) < 1e-6
        assert abs(tw.find_nearest_beat_time(1.4) - 2.0) < 1e-6

        # Fine grid: subdivision 16 == 1/16-beat steps (0.03125s). 0.10 snaps
        # to the nearest 1/16-beat line.
        tw.set_grid_subdivision(16.0)
        step = 0.5 / 16.0
        expected = round(0.10 / step) * step
        assert abs(tw.find_nearest_beat_time(0.10) - expected) < 1e-6
    finally:
        tw.deleteLater()


def test_find_nearest_beat_time_fallback_path_uses_subdivision(qapp):
    """No song structure loaded → falls back to bare-BPM snap; subdivision
    must apply there too so the empty-state behaves consistently.
    """
    from timeline_ui.timeline_widget import TimelineWidget

    tw = TimelineWidget()  # No set_song_structure call.
    try:
        # 120 BPM default → 0.5s/beat. At subdivision=2, 0.27 → 0.25.
        tw.set_grid_subdivision(2)
        assert abs(tw.find_nearest_beat_time(0.27) - 0.25) < 1e-6
    finally:
        tw.deleteLater()


def test_swing_amount_moves_the_snapped_pixel_positions(qapp):
    """Pin the actual snapped x positions on the 1/2-beat grid at 120 BPM
    (beat = 0.5s, zoom 1.0 -> 60 px/s):

    - amount 0.0 (off): off-beat at 1/2 beat = 0.25s -> x = 15.0 px
    - amount 0.5: off-beat at 7/12 beat = 0.2916667s -> x = 17.5 px
    - amount 1.0: off-beat at 2/3 beat = 0.3333s -> x = 20.0 px (the old
      boolean triplet position, so blocks snap exactly as before at 100%)
    """
    from timeline_ui.timeline_widget import TimelineWidget

    tw = TimelineWidget()
    tw.set_song_structure(_make_song_structure())
    tw.set_grid_subdivision(2.0)
    try:
        assert tw.pixels_per_second == 60

        tw.set_swing(0.0)
        snapped = tw.find_nearest_beat_time(0.27)
        assert abs(snapped - 0.25) < 1e-6
        assert abs(tw.time_to_pixel(snapped) - 15.0) < 1e-4

        tw.set_swing(0.5)
        snapped = tw.find_nearest_beat_time(0.27)
        assert abs(snapped - 0.5 * (7.0 / 12.0)) < 1e-6
        assert abs(tw.time_to_pixel(snapped) - 17.5) < 1e-4

        tw.set_swing(1.0)
        snapped = tw.find_nearest_beat_time(0.30)
        assert abs(snapped - 0.5 * (2.0 / 3.0)) < 1e-6
        assert abs(tw.time_to_pixel(snapped) - 20.0) < 1e-4

        # Beat/bar lines never move, whatever the amount.
        assert abs(tw.find_nearest_beat_time(0.02) - 0.0) < 1e-6
        assert abs(tw.find_nearest_beat_time(0.48) - 0.5) < 1e-6
    finally:
        tw.deleteLater()


def test_global_snap_fans_out_to_master_and_lanes(qapp):
    """The toolbar's global SNAP chip drives TimelineGrid.set_snap_to_grid,
    which fans out to the master ruler + every lane's timeline + the
    per-lane snap checkbox so the visible state stays consistent."""
    from timeline.light_lane import LightLane
    from timeline_ui import (
        LightLaneWidget, MasterTimelineContainer, TimelineGrid,
    )

    grid = TimelineGrid()
    master = MasterTimelineContainer()
    grid.set_master(master)

    lane_model = LightLane(name="L1", fixture_targets=["TestGroup"])
    lane = LightLaneWidget(lane_model, ["TestGroup"])
    grid.add_light_lane(lane)

    try:
        # Default: snap is on everywhere.
        assert master.timeline_widget.snap_to_grid is True
        assert lane.timeline_widget.snap_to_grid is True
        assert lane.snap_checkbox.isChecked() is True

        # Global SNAP turned off from the grid.
        grid.set_snap_to_grid(False)
        assert master.timeline_widget.snap_to_grid is False
        assert lane.timeline_widget.snap_to_grid is False
        # Per-lane checkbox mirrors the global state.
        assert lane.snap_checkbox.isChecked() is False
    finally:
        grid.deleteLater()
        master.deleteLater()
        lane.deleteLater()


def test_per_lane_snap_is_an_individual_override(qapp):
    """A lane's own snap checkbox toggles only that lane, not the master or
    its siblings (the individual control the user wants)."""
    from timeline.light_lane import LightLane
    from timeline_ui import (
        LightLaneWidget, MasterTimelineContainer, TimelineGrid,
    )

    grid = TimelineGrid()
    master = MasterTimelineContainer()
    grid.set_master(master)

    a = LightLaneWidget(LightLane(name="A", fixture_targets=["TestGroup"]),
                        ["TestGroup"])
    b = LightLaneWidget(LightLane(name="B", fixture_targets=["TestGroup"]),
                        ["TestGroup"])
    grid.add_light_lane(a)
    grid.add_light_lane(b)

    try:
        a.snap_checkbox.setChecked(False)
        assert a.timeline_widget.snap_to_grid is False
        # The other lane and the master are untouched.
        assert b.timeline_widget.snap_to_grid is True
        assert master.timeline_widget.snap_to_grid is True
    finally:
        grid.deleteLater()
        master.deleteLater()
        a.deleteLater()
        b.deleteLater()


def test_master_header_uses_two_row_layout_after_detach(qapp):
    """detach_pieces must produce a header that's a 2-row stack (title row
    + info row). Pin the QVBoxLayout shape so future refactors don't
    quietly revert to a single-row layout.
    """
    from PyQt6.QtWidgets import QVBoxLayout
    from timeline_ui.master_timeline_widget import MasterTimelineContainer

    master = MasterTimelineContainer()
    try:
        header, _stripe = master.detach_pieces()
        layout = header.layout()
        assert isinstance(layout, QVBoxLayout), \
            "Master header must be a QVBoxLayout (title row + info row)"
        # Two children: a title QHBoxLayout and the info_widget directly.
        assert layout.count() == 2
        assert master.info_widget.parent() is header
    finally:
        master.deleteLater()
