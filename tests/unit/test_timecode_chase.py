"""Timecode chase state machine (utils/timecode/chase.py, phase 1).

Everything runs on explicit fake arrival times - no real clock, no
audio. Frames are hand-built LTCFrames; arrival jitter and rate skew
are simulated by spacing the arrivals.
"""

import numpy as np
import pytest

from utils.timecode import (
    FPS_25, FPS_2997_DF, ChaseState, LTCFrame, TimecodeChase, Timecode,
)

DUR_25 = 1.0 / 25.0
BASE = 1000.0  # arbitrary monotonic origin: the chase must not care


def make_frames(start_text, n, rate=FPS_25):
    start = Timecode.parse(start_text, rate)
    out = []
    for i in range(n):
        t = start.advanced(i)
        out.append(LTCFrame(t.hours, t.minutes, t.seconds, t.frames,
                            rate.drop_frame, 0, 0.0))
    return out


def feed_run(chase, frames, t0=BASE, spacing=DUR_25, jitter=None):
    """Feed frames spaced ``spacing`` apart; returns the last arrival."""
    arrival = t0
    for i, f in enumerate(frames):
        arrival = t0 + i * spacing
        if jitter is not None:
            arrival += jitter[i]
        chase.feed(f, arrival)
    return arrival


class TestLockAcquisition:

    def test_no_signal_until_n_coherent_frames(self):
        chase = TimecodeChase(FPS_25)
        frames = make_frames("00:01:00:00", 4)
        feed_run(chase, frames[:3])
        now = BASE + 3 * DUR_25
        assert chase.state(now) is ChaseState.NO_SIGNAL
        assert chase.position(now) is None
        chase.feed(frames[3], BASE + 3 * DUR_25)
        assert chase.state(now) is ChaseState.LOCKED
        assert chase.position(now) is not None

    def test_incoherent_frames_never_lock(self):
        chase = TimecodeChase(FPS_25)
        # Frame numbers that never follow one another.
        for i, text in enumerate(("00:01:00:00", "00:02:00:00",
                                  "00:03:00:00", "00:04:00:00",
                                  "00:05:00:00", "00:06:00:00")):
            f = make_frames(text, 1)[0]
            chase.feed(f, BASE + i * DUR_25)
        assert chase.state(BASE + 6 * DUR_25) is ChaseState.NO_SIGNAL

    def test_invalid_labels_break_coherence_not_the_chase(self):
        # A dropped drop-frame number decoded from a noisy stream must
        # not crash or count toward the lock.
        chase = TimecodeChase(FPS_2997_DF)
        bad = LTCFrame(0, 1, 0, 0, True, 0, 0.0)   # 00:01:00;00 not a label
        chase.feed(bad, BASE)
        frames = make_frames("00:00:30;00", 6, FPS_2997_DF)
        last = feed_run(chase, frames, t0=BASE + 1.0,
                        spacing=1001 / 30000)
        assert chase.state(last) is ChaseState.LOCKED


class TestPositionTracking:

    def test_position_matches_the_timeline(self):
        chase = TimecodeChase(FPS_25)
        start = Timecode.parse("00:10:00:00", FPS_25)
        frames = make_frames("00:10:00:00", 25)
        last = feed_run(chase, frames)
        # Query mid-frame, a quarter frame after the last arrival.
        now = last + DUR_25 / 4
        truth = start.to_seconds() + (now - BASE)
        assert chase.position(now) == pytest.approx(truth, abs=DUR_25)

    def test_tracks_two_percent_rate_skew(self):
        chase = TimecodeChase(FPS_25)
        start = Timecode.parse("00:10:00:00", FPS_25)
        frames = make_frames("00:10:00:00", 125)   # 5 s of timecode
        spacing = DUR_25 / 1.02                    # signal runs 2% fast
        last = feed_run(chase, frames, spacing=spacing)
        truth = start.advanced(124).to_seconds()
        assert chase.position(last) == pytest.approx(truth, abs=DUR_25)
        assert chase.fitted_rate == pytest.approx(1.02, abs=0.005)

    def test_arrival_jitter_does_not_wobble_the_clock(self):
        rng = np.random.default_rng(7)
        chase = TimecodeChase(FPS_25)
        start = Timecode.parse("00:10:00:00", FPS_25)
        n = 50
        jitter = rng.uniform(-0.015, 0.015, n)
        jitter[0] = 0.0
        feed_run(chase, make_frames("00:10:00:00", n), jitter=jitter)
        now = BASE + (n - 1) * DUR_25          # clean wall time
        truth = start.to_seconds() + (now - BASE)
        assert chase.position(now) == pytest.approx(truth, abs=DUR_25)

    def test_extreme_skew_clamps_the_rate(self):
        chase = TimecodeChase(FPS_25)
        frames = make_frames("00:10:00:00", 50)
        feed_run(chase, frames, spacing=DUR_25 / 1.2)  # 20% fast
        assert chase.fitted_rate == pytest.approx(1.05)

    def test_drop_frame_positions_use_real_seconds(self):
        rate = FPS_2997_DF
        dur = 1001 / 30000
        chase = TimecodeChase(rate)
        start = Timecode.parse("00:00:59;20", rate)
        frames = make_frames("00:00:59;20", 30, rate)  # crosses the drop
        last = feed_run(chase, frames, spacing=dur)
        truth = start.advanced(29).to_seconds()
        assert chase.position(last) == pytest.approx(truth, abs=dur)


class TestFreewheelAndRecovery:

    def _locked_chase(self):
        chase = TimecodeChase(FPS_25)
        start = Timecode.parse("00:10:00:00", FPS_25)
        frames = make_frames("00:10:00:00", 10)
        last = feed_run(chase, frames)
        return chase, start.advanced(9).to_seconds(), last

    def test_freewheel_extrapolates_at_unity(self):
        chase, last_tc_s, last = self._locked_chase()
        now = last + 0.5
        assert chase.state(now) is ChaseState.FREEWHEEL
        assert chase.position(now) == pytest.approx(last_tc_s + 0.5,
                                                    abs=1e-9)

    def test_freewheel_expires_to_no_signal(self):
        chase, _, last = self._locked_chase()
        now = last + 3 * DUR_25 + 2.0 + 0.05
        assert chase.state(now) is ChaseState.NO_SIGNAL
        assert chase.position(now) is None

    def test_relock_after_silence(self):
        chase, _, last = self._locked_chase()
        assert chase.state(last + 10.0) is ChaseState.NO_SIGNAL
        # Signal returns 10 s later, timecode kept running meanwhile.
        frames = make_frames("00:10:11:00", 4)
        resume = feed_run(chase, frames, t0=last + 10.0)
        assert chase.state(resume) is ChaseState.LOCKED
        truth = Timecode.parse("00:10:11:00", FPS_25).advanced(3).to_seconds()
        assert chase.position(resume) == pytest.approx(truth, abs=DUR_25)

    def test_short_dropout_within_freewheel_relocks_seamlessly(self):
        chase, _, last = self._locked_chase()
        # 1 s hole; timecode continued in real time, so the returning
        # frames match the old fit: no jump, no relock gap.
        frames = make_frames("00:10:01:10", 3)   # 10.4 s + 1 s = 25+10 frames on
        resume = feed_run(chase, frames, t0=last + 1.0 + DUR_25)
        assert chase.state(resume) is ChaseState.LOCKED
        assert not chase.consume_jump()


class TestJumps:

    def test_locate_reports_a_jump_once(self):
        chase = TimecodeChase(FPS_25)
        feed_run(chase, make_frames("00:10:00:00", 10))
        last = BASE + 9 * DUR_25
        # The desk locates 10 minutes ahead; frames keep flowing.
        jump_frames = make_frames("00:20:00:00", 5)
        resume = feed_run(chase, jump_frames, t0=last + DUR_25)
        assert chase.consume_jump()
        assert not chase.consume_jump()          # reported exactly once
        assert chase.state(resume) is ChaseState.LOCKED
        truth = Timecode.parse("00:20:00:00", FPS_25).advanced(4).to_seconds()
        assert chase.position(resume) == pytest.approx(truth, abs=DUR_25)

    def test_backward_locate_is_a_jump_too(self):
        chase = TimecodeChase(FPS_25)
        feed_run(chase, make_frames("00:10:00:00", 10))
        last = BASE + 9 * DUR_25
        feed_run(chase, make_frames("00:01:00:00", 5), t0=last + DUR_25)
        assert chase.consume_jump()

    def test_relock_needs_coherence_after_a_jump(self):
        chase = TimecodeChase(FPS_25)
        feed_run(chase, make_frames("00:10:00:00", 10))
        last = BASE + 9 * DUR_25
        chase.feed(make_frames("00:20:00:00", 1)[0], last + DUR_25)
        # One stray frame is not a lock.
        assert chase.state(last + 2 * DUR_25) is ChaseState.NO_SIGNAL
        assert chase.consume_jump()
