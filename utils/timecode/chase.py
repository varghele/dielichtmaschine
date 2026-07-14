# utils/timecode/chase.py
"""Timecode chase: an LTC frame stream becomes a continuous clock
(docs/ltc-plan.md phase 1).

Feed decoded frames with their arrival times; ask ``position(now)``
for the current spot on the incoming timeline. Everything takes
explicit ``now`` values - no hidden clock reads - so the whole state
machine is deterministic under test (the same rule the beat tracker
and the live engine follow).

States:
- NO_SIGNAL: never locked, lock lost, or freewheel expired.
- LOCKED: enough consecutive coherent frames; the clock is a small
  linear fit (offset + rate) over the recent frames, so arrival jitter
  from audio-block granularity does not wobble the playhead.
- FREEWHEEL: signal stopped while locked; extrapolate at exactly 1.0x
  from the last good frame for a grace window, then give up.

A frame that lands far from the fit's prediction is a JUMP (a desk
locate): the fit resets and ``consume_jump()`` reports it once - the
runner decides what a jump means. Lock then re-acquires within
``n_lock`` frames (~130 ms), which is why a jump briefly reads as
NO_SIGNAL.
"""

from collections import deque
from enum import Enum
from typing import Deque, Optional, Tuple

from .ltc import LTCFrame
from .tc import FrameRate, Timecode


class ChaseState(Enum):
    NO_SIGNAL = "no_signal"
    LOCKED = "locked"
    FREEWHEEL = "freewheel"


class TimecodeChase:
    """Turns (LTCFrame, arrival_time) pairs into a chaseable clock."""

    def __init__(self, rate: FrameRate, n_lock: int = 4,
                 fit_window: int = 8, freewheel_s: float = 2.0,
                 jump_threshold_s: float = 1.0,
                 max_rate_dev: float = 0.05,
                 miss_tolerance_frames: float = 3.0):
        self.rate = rate
        self.n_lock = n_lock
        self.freewheel_s = freewheel_s
        self.jump_threshold_s = jump_threshold_s
        self.max_rate_dev = max_rate_dev
        self.miss_tolerance_s = miss_tolerance_frames * rate.den / rate.num

        self._hist: Deque[Tuple[float, float]] = deque(maxlen=fit_window)
        self._coherent = 0
        self._locked = False
        self._slope = 1.0
        self._offset = 0.0
        self._jumped = False
        self._last_tc: Optional[Timecode] = None
        self._last_tc_s = 0.0
        self._last_arrival: Optional[float] = None

    # -- input -----------------------------------------------------------

    def feed(self, frame: LTCFrame, arrival: float) -> None:
        """One decoded frame and the moment (monotonic seconds) its
        last transition hit the audio input."""
        try:
            tc = frame.timecode(self.rate)
        except ValueError:
            # A label that does not exist at this rate (e.g. a dropped
            # drop-frame number): decoder garbage, breaks coherence.
            self._coherent = 0
            return
        tc_s = tc.to_seconds()

        if self._locked:
            if abs(tc_s - self._predict(arrival)) > self.jump_threshold_s:
                # A locate: throw the fit away and start re-locking
                # from this frame; report it exactly once.
                self._jumped = True
                self._locked = False
                self._hist.clear()
                self._coherent = 1
            else:
                self._coherent += 1
        else:
            if (self._last_tc is not None
                    and tc == self._last_tc.advanced(1)):
                self._coherent += 1
            else:
                self._coherent = 1
                self._hist.clear()

        self._hist.append((arrival, tc_s))
        self._last_tc = tc
        self._last_tc_s = tc_s
        self._last_arrival = arrival

        if not self._locked and self._coherent >= self.n_lock:
            self._locked = True
        if self._locked:
            self._refit()

    # -- output ----------------------------------------------------------

    def state(self, now: float) -> ChaseState:
        return self._phase(now)

    def position(self, now: float) -> Optional[float]:
        """Seconds on the incoming timeline, or None without signal."""
        phase = self._phase(now)
        if phase is ChaseState.NO_SIGNAL:
            return None
        if phase is ChaseState.LOCKED:
            return self._predict(now)
        # Freewheel: exactly 1.0x from the last good frame.
        return self._last_tc_s + (now - self._last_arrival)

    def consume_jump(self) -> bool:
        """True once per detected jump, then cleared."""
        jumped, self._jumped = self._jumped, False
        return jumped

    @property
    def fitted_rate(self) -> float:
        """Incoming-timecode seconds per wall second (clamped fit)."""
        return self._slope

    @property
    def last_timecode(self) -> Optional[Timecode]:
        """The most recent frame's label (for status displays)."""
        return self._last_tc

    # -- internals ---------------------------------------------------------

    def _phase(self, now: float) -> ChaseState:
        if not self._locked or self._last_arrival is None:
            return ChaseState.NO_SIGNAL
        gap = now - self._last_arrival
        if gap <= self.miss_tolerance_s:
            return ChaseState.LOCKED
        if gap <= self.miss_tolerance_s + self.freewheel_s:
            return ChaseState.FREEWHEEL
        # Freewheel expired: lock is gone until frames return.
        self._locked = False
        self._coherent = 0
        self._hist.clear()
        return ChaseState.NO_SIGNAL

    def _predict(self, now: float) -> float:
        return self._offset + self._slope * now

    def _refit(self) -> None:
        n = len(self._hist)
        if n < 2:
            self._slope = 1.0
            self._offset = self._last_tc_s - self._last_arrival
            return
        mean_a = sum(a for a, _ in self._hist) / n
        mean_t = sum(t for _, t in self._hist) / n
        var = sum((a - mean_a) ** 2 for a, _ in self._hist)
        cov = sum((a - mean_a) * (t - mean_t) for a, t in self._hist)
        slope = cov / var if var > 0 else 1.0
        slope = min(max(slope, 1.0 - self.max_rate_dev),
                    1.0 + self.max_rate_dev)
        self._slope = slope
        self._offset = mean_t - slope * mean_a
