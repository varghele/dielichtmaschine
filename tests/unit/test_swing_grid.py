"""Unit tests for the triplet-swing grid feature.

Covers:
- The pure ``swing_warp`` fraction map (endpoints + monotonicity).
- ``TimelineWidget.set_swing`` fan-in and its effect on
  ``find_nearest_beat_time`` snap targets (off-beat lands on 2/3 of the
  beat, not 1/2).
- ``TimelineGrid.set_swing`` fans the state out to master + audio + light
  lanes, including lanes added after swing was turned on.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _make_song_structure(bpm=120.0):
    from config.models import ShowPart
    from timeline.song_structure import SongStructure

    parts = [ShowPart(name="A", color="#FFF", signature="4/4",
                      bpm=bpm, num_bars=4, transition="instant")]
    ss = SongStructure()
    ss.load_from_show_parts(parts)
    return ss


def test_swing_warp_endpoints_and_monotonic():
    from timeline_ui.timeline_widget import swing_warp

    # Beat/bar lines (fraction 0) are unaffected.
    assert swing_warp(0.0) == 0.0
    # The eighth-note off-beat moves from 1/2 to 2/3.
    assert abs(swing_warp(0.5) - (2.0 / 3.0)) < 1e-12
    # Approaches 1 at the top of the beat.
    assert abs(swing_warp(0.999999) - 1.0) < 1e-3

    # Strictly monotonic increasing across [0, 1).
    prev = -1.0
    f = 0.0
    while f < 1.0:
        val = swing_warp(f)
        assert val > prev, f"not increasing at f={f}"
        prev = val
        f += 0.01


def test_swing_warp_first_half_is_linear_to_ratio():
    from timeline_ui.timeline_widget import swing_warp

    r = 2.0 / 3.0
    # f=0.25 -> halfway into the first (compressed) half -> r/2.
    assert abs(swing_warp(0.25) - r / 2.0) < 1e-12
    # f=0.75 -> halfway into the second (stretched) half -> r + (1-r)/2.
    assert abs(swing_warp(0.75) - (r + (1.0 - r) / 2.0)) < 1e-12


def test_set_swing_toggles_flag_on_widget(qapp):
    from timeline_ui.timeline_widget import TimelineWidget

    tw = TimelineWidget()
    try:
        assert tw.swing_enabled is False
        tw.set_swing(True)
        assert tw.swing_enabled is True
        tw.set_swing(False)
        assert tw.swing_enabled is False
    finally:
        tw.deleteLater()


def test_swing_off_beat_snaps_to_two_thirds(qapp):
    """With swing on and subdivision 2 (1/2-beat grid), the off-beat snap
    target sits at 2/3 of the beat, not 1/2."""
    from timeline_ui.timeline_widget import TimelineWidget

    tw = TimelineWidget()
    tw.set_song_structure(_make_song_structure(bpm=120.0))  # beat = 0.5s
    tw.set_grid_subdivision(2.0)
    try:
        # Swing OFF: a time in the middle of beat 0 snaps to the half-beat
        # (0.25s).
        tw.set_swing(False)
        assert abs(tw.find_nearest_beat_time(0.24) - 0.25) < 1e-6

        # Swing ON: the same region snaps to 2/3 of the beat (0.5 * 2/3).
        tw.set_swing(True)
        target = 0.5 * (2.0 / 3.0)  # 0.3333s
        assert abs(tw.find_nearest_beat_time(0.30) - target) < 1e-6
        assert abs(tw.find_nearest_beat_time(0.34) - target) < 1e-6

        # The beat boundary itself is never moved by swing.
        assert abs(tw.find_nearest_beat_time(0.02) - 0.0) < 1e-6
        assert abs(tw.find_nearest_beat_time(0.48) - 0.5) < 1e-6
    finally:
        tw.deleteLater()


def test_swing_fallback_path_without_structure(qapp):
    from timeline_ui.timeline_widget import TimelineWidget

    tw = TimelineWidget()  # no song structure -> bare-BPM snap
    tw.set_grid_subdivision(2.0)
    tw.set_swing(True)
    try:
        # 120 BPM default -> beat 0.5s, off-beat target 2/3 == 0.3333s.
        target = 0.5 * (2.0 / 3.0)
        assert abs(tw.find_nearest_beat_time(0.31) - target) < 1e-6
    finally:
        tw.deleteLater()


def test_timeline_grid_fans_swing_to_audio_and_lanes(qapp):
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
        grid.set_swing(True)
        assert master.timeline_widget.swing_enabled is True
        assert audio.timeline_widget.swing_enabled is True
        assert lane.timeline_widget.swing_enabled is True

        grid.set_swing(False)
        assert master.timeline_widget.swing_enabled is False
        assert lane.timeline_widget.swing_enabled is False
    finally:
        grid.deleteLater()
        master.deleteLater()
        audio.deleteLater()
        lane.deleteLater()


def test_late_added_lane_inherits_swing(qapp):
    from timeline.light_lane import LightLane
    from timeline_ui import (
        LightLaneWidget, MasterTimelineContainer, TimelineGrid,
    )

    grid = TimelineGrid()
    master = MasterTimelineContainer()
    grid.set_master(master)
    grid.set_swing(True)  # swing already on when the lane joins

    lane_model = LightLane(name="L1", fixture_targets=["TestGroup"])
    lane = LightLaneWidget(lane_model, ["TestGroup"])
    grid.add_light_lane(lane)

    try:
        assert lane.timeline_widget.swing_enabled is True
    finally:
        grid.deleteLater()
        master.deleteLater()
        lane.deleteLater()
