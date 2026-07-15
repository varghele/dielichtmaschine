"""Unit tests for the swing-amount grid feature (timeline v3 stage T1).

Swing is an AMOUNT in [0, 1] now, not a boolean: 0.0 keeps the straight
grid, 1.0 is the full triplet feel (off-beat at 2/3 of the beat) and
intermediate amounts interpolate the off-beat shift linearly. Covers:
- The pure ``swing_warp`` fraction map (endpoints + monotonicity) and
  the ``swing_ratio`` amount -> off-beat-ratio interpolation.
- ``TimelineWidget.set_swing`` amount fan-in (including bool
  backward-compat) and its effect on ``find_nearest_beat_time`` snap
  targets.
- ``TimelineGrid.set_swing`` fans the amount out to master + audio +
  light lanes, including lanes added after swing was set.
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
    # The eighth-note off-beat moves from 1/2 to 2/3 at the full ratio.
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


def test_swing_ratio_interpolates_linearly():
    from timeline_ui.timeline_widget import SWING_RATIO, swing_ratio

    # 0 = straight (off-beat stays at 1/2), 1 = full triplet (2/3).
    assert swing_ratio(0.0) == 0.5
    assert abs(swing_ratio(1.0) - SWING_RATIO) < 1e-12
    # Linear in between: 50% sits at 7/12.
    assert abs(swing_ratio(0.5) - 7.0 / 12.0) < 1e-12
    assert abs(swing_ratio(0.25) - (0.5 + 0.25 / 6.0)) < 1e-12
    # Bools keep the old on/off semantics; out-of-range clamps.
    assert abs(swing_ratio(True) - SWING_RATIO) < 1e-12
    assert swing_ratio(False) == 0.5
    assert abs(swing_ratio(1.5) - SWING_RATIO) < 1e-12
    assert swing_ratio(-0.2) == 0.5


def test_swing_ratio_zero_makes_warp_identity():
    from timeline_ui.timeline_widget import swing_ratio, swing_warp

    r0 = swing_ratio(0.0)
    for f in (0.0, 0.1, 0.25, 0.5, 0.75, 0.9):
        assert abs(swing_warp(f, r0) - f) < 1e-12


def test_set_swing_stores_clamped_amount(qapp):
    from timeline_ui.timeline_widget import TimelineWidget

    tw = TimelineWidget()
    try:
        assert tw.swing_amount == 0.0
        tw.set_swing(0.5)
        assert tw.swing_amount == 0.5
        # Bool backward-compat: True == 1.0, False == 0.0.
        tw.set_swing(True)
        assert tw.swing_amount == 1.0
        tw.set_swing(False)
        assert tw.swing_amount == 0.0
        # Out-of-range clamps.
        tw.set_swing(2.0)
        assert tw.swing_amount == 1.0
        tw.set_swing(-1.0)
        assert tw.swing_amount == 0.0
    finally:
        tw.deleteLater()


def test_full_swing_off_beat_snaps_to_two_thirds(qapp):
    """With swing amount 1.0 and subdivision 2 (1/2-beat grid), the
    off-beat snap target sits at 2/3 of the beat - exactly the old
    boolean triplet behaviour."""
    from timeline_ui.timeline_widget import TimelineWidget

    tw = TimelineWidget()
    tw.set_song_structure(_make_song_structure(bpm=120.0))  # beat = 0.5s
    tw.set_grid_subdivision(2.0)
    try:
        # Amount 0: a time in the middle of beat 0 snaps to the half-beat
        # (0.25s).
        tw.set_swing(0.0)
        assert abs(tw.find_nearest_beat_time(0.24) - 0.25) < 1e-6

        # Amount 1: the same region snaps to 2/3 of the beat (0.5 * 2/3).
        tw.set_swing(1.0)
        target = 0.5 * (2.0 / 3.0)  # 0.3333s
        assert abs(tw.find_nearest_beat_time(0.30) - target) < 1e-6
        assert abs(tw.find_nearest_beat_time(0.34) - target) < 1e-6

        # The beat boundary itself is never moved by swing.
        assert abs(tw.find_nearest_beat_time(0.02) - 0.0) < 1e-6
        assert abs(tw.find_nearest_beat_time(0.48) - 0.5) < 1e-6
    finally:
        tw.deleteLater()


def test_half_swing_off_beat_snaps_to_seven_twelfths(qapp):
    """Amount 0.5 puts the off-beat halfway between straight (1/2) and
    triplet (2/3): 7/12 of the beat."""
    from timeline_ui.timeline_widget import TimelineWidget

    tw = TimelineWidget()
    tw.set_song_structure(_make_song_structure(bpm=120.0))  # beat = 0.5s
    tw.set_grid_subdivision(2.0)
    tw.set_swing(0.5)
    try:
        target = 0.5 * (7.0 / 12.0)  # 0.2916667s
        assert abs(tw.find_nearest_beat_time(0.27) - target) < 1e-6
        assert abs(tw.find_nearest_beat_time(0.31) - target) < 1e-6
    finally:
        tw.deleteLater()


def test_swing_fallback_path_without_structure(qapp):
    from timeline_ui.timeline_widget import TimelineWidget

    tw = TimelineWidget()  # no song structure -> bare-BPM snap
    tw.set_grid_subdivision(2.0)
    tw.set_swing(1.0)
    try:
        # 120 BPM default -> beat 0.5s, off-beat target 2/3 == 0.3333s.
        target = 0.5 * (2.0 / 3.0)
        assert abs(tw.find_nearest_beat_time(0.31) - target) < 1e-6
    finally:
        tw.deleteLater()


def test_timeline_grid_fans_swing_amount_to_audio_and_lanes(qapp):
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
        grid.set_swing(0.75)
        assert master.timeline_widget.swing_amount == 0.75
        assert audio.timeline_widget.swing_amount == 0.75
        assert lane.timeline_widget.swing_amount == 0.75

        grid.set_swing(0.0)
        assert master.timeline_widget.swing_amount == 0.0
        assert lane.timeline_widget.swing_amount == 0.0
    finally:
        grid.deleteLater()
        master.deleteLater()
        audio.deleteLater()
        lane.deleteLater()


def test_late_added_lane_inherits_swing_amount(qapp):
    from timeline.light_lane import LightLane
    from timeline_ui import (
        LightLaneWidget, MasterTimelineContainer, TimelineGrid,
    )

    grid = TimelineGrid()
    master = MasterTimelineContainer()
    grid.set_master(master)
    grid.set_swing(0.5)  # swing already set when the lane joins

    lane_model = LightLane(name="L1", fixture_targets=["TestGroup"])
    lane = LightLaneWidget(lane_model, ["TestGroup"])
    grid.add_light_lane(lane)

    try:
        assert lane.timeline_widget.swing_amount == 0.5
    finally:
        grid.deleteLater()
        master.deleteLater()
        lane.deleteLater()
