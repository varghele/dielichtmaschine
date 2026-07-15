# utils/timecode/ltc.py
"""Streaming LTC decoder (docs/ltc-plan.md phase 0).

Audio samples in, :class:`LTCFrame` stream out. Feed arbitrary block
sizes; all state carries across calls. The decoder needs no a-priori
frame rate: biphase-mark is decoded from zero-crossing intervals
against an adaptive bit-cell period, which also makes it immune to
polarity, amplitude and tape-style rate wobble. A one-pole DC blocker
in front handles offset inputs.

Framing: an 80-bit shift register hunts for the SMPTE sync word (bits
64..79); on a match the previous 64 bits are the frame. Parity/flag
bits are ignored (soft, per the plan) - real-world generators get them
wrong constantly. Reverse play is deliberately not handled.
"""

from dataclasses import dataclass
from typing import List, Optional

import numpy as np
from scipy.signal import lfilter

from .tc import FPS_24, FPS_25, FPS_30, FPS_2997_DF, FrameRate, Timecode

# Sync word as an integer with bit 64 of the frame at the LSB
# (transmission order 0011 1111 1111 1101 -> 0xBFFC arrival-packed).
_SYNC_WORD = 0xBFFC

# DC blocker: y[n] = x[n] - x[n-1] + 0.995 y[n-1].
_DC_B = np.array([1.0, -1.0])
_DC_A = np.array([1.0, -0.995])

# Bit-cell period sanity range: 80 cells per frame at 23..31 fps.
_MIN_FPS, _MAX_FPS = 23.0, 31.0

# EMA gain for the adaptive period estimate.
_PERIOD_GAIN = 0.05


@dataclass(frozen=True)
class LTCFrame:
    """One decoded LTC frame.

    ``end_sample`` is the absolute sample index (fractional, since
    crossings are interpolated) of the frame's final transition -
    phase 1's chase uses it for sub-block arrival timing.
    """
    hours: int
    minutes: int
    seconds: int
    frames: int
    drop_frame: bool
    user_bits: int
    end_sample: float

    def timecode(self, rate: FrameRate) -> Timecode:
        return Timecode(self.hours, self.minutes, self.seconds,
                        self.frames, rate)

    def label(self) -> str:
        sep = ";" if self.drop_frame else ":"
        return (f"{self.hours:02d}:{self.minutes:02d}:{self.seconds:02d}"
                f"{sep}{self.frames:02d}")


class LTCDecoder:
    """Streaming biphase-mark LTC decoder with adaptive cell tracking."""

    def __init__(self, sample_rate: int = 44100):
        self.sample_rate = sample_rate
        # DC blocker state + last filtered sample (for crossings that
        # straddle a feed() boundary).
        self._dc_zi = np.zeros(1)
        self._tail: Optional[float] = None
        self._samples_seen = 0
        # Adaptive bit-cell period (samples); None until bootstrapped.
        self._period: Optional[float] = None
        self._warmup: List[float] = []
        # Crossing / bit assembly state.
        self._last_cross: Optional[float] = None
        self._pending_half = False
        self._reg = 0
        self._bits_since_reset = 0
        # Rate inference.
        self._prev_frame_no: Optional[int] = None
        self._max_frame_no = -1
        self._nominal: Optional[int] = None
        self._df_seen = False
        # Counters (diagnostics).
        self.frames_decoded = 0
        self.framing_errors = 0

    # -- public ----------------------------------------------------------

    def feed(self, samples: np.ndarray) -> List[LTCFrame]:
        """Consume audio, return every frame completed within it."""
        x = np.asarray(samples, dtype=np.float64).ravel()
        if x.size == 0:
            return []
        y, self._dc_zi = lfilter(_DC_B, _DC_A, x, zi=self._dc_zi)

        if self._tail is not None:
            y = np.concatenate(([self._tail], y))
            base = self._samples_seen - 1
        else:
            base = self._samples_seen

        out: List[LTCFrame] = []
        sign = y >= 0.0
        for i in np.nonzero(sign[1:] != sign[:-1])[0]:
            y0, y1 = y[i], y[i + 1]
            frac = y0 / (y0 - y1) if y0 != y1 else 0.5
            self._on_crossing(base + i + frac, out)

        self._tail = float(y[-1])
        self._samples_seen += x.size
        return out

    @property
    def cell_period_samples(self) -> Optional[float]:
        return self._period

    @property
    def fps_estimate(self) -> Optional[float]:
        """Raw frame rate implied by the measured cell period."""
        if not self._period:
            return None
        return self.sample_rate / (80.0 * self._period)

    @property
    def rate_guess(self) -> Optional[FrameRate]:
        """Best current FrameRate: numbering wrap + drop-frame flag when
        seen, cell-cadence snap until then (which cannot tell 29.97
        from 30 without the flag - we do not support non-drop 29.97)."""
        nominal = self._nominal
        if nominal is None:
            est = self.fps_estimate
            if est is None:
                return None
            nominal = min((24, 25, 30), key=lambda n: abs(n - est))
        if nominal == 30:
            return FPS_2997_DF if self._df_seen else FPS_30
        return {24: FPS_24, 25: FPS_25}.get(nominal)

    # -- crossing pipeline -------------------------------------------------

    def _on_crossing(self, pos: float, out: List[LTCFrame]) -> None:
        if self._last_cross is None:
            self._last_cross = pos
            return
        dt = pos - self._last_cross
        if self._period is not None and dt < 0.25 * self._period:
            return  # chatter near a real transition: pretend it never happened
        self._last_cross = pos

        if self._period is None:
            self._bootstrap(dt)
            return

        t = self._period
        if dt < 0.75 * t:
            # Half cell: two in a row make a 1.
            if self._pending_half:
                self._pending_half = False
                self._push_bit(1, pos, out)
                self._period += _PERIOD_GAIN * (2.0 * dt - t)
            else:
                self._pending_half = True
        elif dt < 1.6 * t:
            if self._pending_half:
                # A lone half cell cannot happen in biphase-mark: slip.
                self._pending_half = False
                self._bits_since_reset = 0
                self.framing_errors += 1
            self._push_bit(0, pos, out)
            self._period += _PERIOD_GAIN * (dt - t)
        else:
            # Gap (dropout / silence): framing is gone, hunt afresh.
            self._pending_half = False
            self._bits_since_reset = 0
            self.framing_errors += 1

        lo = self.sample_rate / (80.0 * _MAX_FPS)
        hi = self.sample_rate / (80.0 * _MIN_FPS)
        self._period = min(max(self._period, lo), hi)

    def _bootstrap(self, dt: float) -> None:
        """Estimate the initial cell period from an interval histogram:
        the full-cell cluster sits at twice the half-cell cluster, and
        any real LTC frame contains both."""
        hi = self.sample_rate / (80.0 * _MIN_FPS)
        if dt > 4.0 * hi:
            return  # leading silence, not signal
        self._warmup.append(dt)
        if len(self._warmup) < 60:
            return
        arr = np.sort(np.asarray(self._warmup))
        p10 = arr[int(0.1 * (len(arr) - 1))]
        p90 = arr[int(0.9 * (len(arr) - 1))]
        if p90 > 1.45 * p10:
            self._period = float(p90)
            self._warmup = []
        else:
            self._warmup = self._warmup[-40:]

    # -- bits to frames -----------------------------------------------------

    def _push_bit(self, bit: int, pos: float, out: List[LTCFrame]) -> None:
        self._reg = (self._reg >> 1) | (bit << 79)
        self._bits_since_reset += 1
        if self._bits_since_reset >= 80 and (self._reg >> 64) == _SYNC_WORD:
            frame = self._decode_register(pos)
            if frame is not None:
                out.append(frame)
                self.frames_decoded += 1

    def _decode_register(self, end_sample: float) -> Optional[LTCFrame]:
        r = self._reg
        f = ((r >> 8) & 0x3) * 10 + (r & 0xF)
        s = ((r >> 24) & 0x7) * 10 + ((r >> 16) & 0xF)
        m = ((r >> 40) & 0x7) * 10 + ((r >> 32) & 0xF)
        h = ((r >> 56) & 0x3) * 10 + ((r >> 48) & 0xF)
        if f > 29 or s > 59 or m > 59 or h > 23:
            # BCD garbage that happened to carry a sync pattern.
            self.framing_errors += 1
            return None
        drop = bool((r >> 10) & 1)
        user = 0
        for n, lsb in enumerate((4, 12, 20, 28, 36, 44, 52, 60)):
            user |= ((r >> lsb) & 0xF) << (4 * n)

        # Numbering inference: a wrap (frame number falls) pins the
        # nominal rate at max-seen + 1.
        if self._prev_frame_no is not None and f < self._prev_frame_no:
            if self._max_frame_no + 1 in (24, 25, 30):
                self._nominal = self._max_frame_no + 1
        self._prev_frame_no = f
        self._max_frame_no = max(self._max_frame_no, f)
        if drop:
            self._df_seen = True

        return LTCFrame(h, m, s, f, drop, user, end_sample)
