# utils/timecode/tc.py
"""SMPTE timecode values and frame-rate math (docs/ltc-plan.md phase 0).

All arithmetic happens on integer FRAME COUNTS, never on float seconds,
so a chase that runs for an hour cannot drift by float accumulation.

Drop-frame (29.97) drops frame NUMBERS, not frames: the signal is a
steady 30000/1001 frames per second, and the numbering skips 00 and 01
at the start of every minute not divisible by ten so the label stays
within earshot of the wall clock. Supported rates: 24, 25, 30 and
29.97 drop-frame; 23.976 and non-drop 29.97 are rare on stage and
deliberately absent.
"""

import re
from dataclasses import dataclass
from typing import Tuple


@dataclass(frozen=True)
class FrameRate:
    """One supported SMPTE rate: numbering base plus the actual rate.

    ``nominal`` is the frame NUMBERING per second (24, 25 or 30);
    ``num / den`` is the true frame rate in frames per real second
    (30000/1001 for 29.97 drop-frame, whole numbers otherwise).
    """
    nominal: int
    drop_frame: bool
    num: int
    den: int

    @property
    def fps(self) -> float:
        return self.num / self.den

    @property
    def separator(self) -> str:
        """Display convention: ';' before the frame field marks drop-frame."""
        return ";" if self.drop_frame else ":"

    def __str__(self) -> str:
        return "29.97df" if self.drop_frame else str(self.nominal)


FPS_24 = FrameRate(24, False, 24, 1)
FPS_25 = FrameRate(25, False, 25, 1)
FPS_30 = FrameRate(30, False, 30, 1)
FPS_2997_DF = FrameRate(30, True, 30000, 1001)

SUPPORTED_RATES: Tuple[FrameRate, ...] = (FPS_24, FPS_25, FPS_30, FPS_2997_DF)

# Drop-frame constants (numbering base 30 only): 2 frame numbers vanish
# per minute except every tenth minute.
_DF_DROP = 2

_TC_RE = re.compile(r"^(\d{1,2}):(\d{1,2}):(\d{1,2})[:;](\d{1,2})$")


def _df_frames_per_minute(nominal: int) -> int:
    return 60 * nominal - _DF_DROP            # 1798


def _df_frames_per_10min(nominal: int) -> int:
    return 10 * 60 * nominal - 9 * _DF_DROP   # 17982


def frames_in_day(rate: FrameRate) -> int:
    """Frame COUNT of exactly 24 hours at this rate's numbering."""
    if rate.drop_frame:
        return _df_frames_per_10min(rate.nominal) * 6 * 24
    return 24 * 3600 * rate.nominal


@dataclass(frozen=True)
class Timecode:
    """An SMPTE timecode label at a specific rate.

    Immutable; use :meth:`advanced` for arithmetic. Frame numbers that
    do not exist (out of range, or dropped numbers in a drop-frame
    minute) raise at construction so an invalid label can never
    circulate.
    """
    hours: int
    minutes: int
    seconds: int
    frames: int
    rate: FrameRate

    def __post_init__(self):
        if not (0 <= self.hours <= 23 and 0 <= self.minutes <= 59
                and 0 <= self.seconds <= 59
                and 0 <= self.frames < self.rate.nominal):
            raise ValueError(f"timecode field out of range: {self!r}")
        if (self.rate.drop_frame and self.seconds == 0
                and self.minutes % 10 != 0 and self.frames < _DF_DROP):
            raise ValueError(
                f"frame {self.frames:02d} is a dropped number at "
                f"{self.hours:02d}:{self.minutes:02d} (drop-frame)")

    # -- text ---------------------------------------------------------

    @classmethod
    def parse(cls, text: str, rate: FrameRate) -> "Timecode":
        """Parse ``HH:MM:SS:FF`` (also accepts ';' before the frames)."""
        m = _TC_RE.match(text.strip())
        if not m:
            raise ValueError(f"not a timecode: {text!r}")
        h, mi, s, f = (int(g) for g in m.groups())
        return cls(h, mi, s, f, rate)

    def __str__(self) -> str:
        return (f"{self.hours:02d}:{self.minutes:02d}:{self.seconds:02d}"
                f"{self.rate.separator}{self.frames:02d}")

    # -- frame-count arithmetic ----------------------------------------

    def to_frame_count(self) -> int:
        """Frames since 00:00:00:00, accounting for dropped numbers."""
        nominal = self.rate.nominal
        base = ((self.hours * 60 + self.minutes) * 60
                + self.seconds) * nominal + self.frames
        if self.rate.drop_frame:
            total_minutes = self.hours * 60 + self.minutes
            base -= _DF_DROP * (total_minutes - total_minutes // 10)
        return base

    @classmethod
    def from_frame_count(cls, count: int, rate: FrameRate) -> "Timecode":
        """Inverse of :meth:`to_frame_count`; wraps at 24 hours."""
        count %= frames_in_day(rate)
        nominal = rate.nominal
        if not rate.drop_frame:
            f = count % nominal
            total_s = count // nominal
            return cls(total_s // 3600, (total_s // 60) % 60,
                       total_s % 60, f, rate)
        # Drop-frame: within each 10-minute chunk, minute 0 keeps all
        # 1800 numbers, minutes 1..9 run 02..29 within their first
        # second (1798 numbers each).
        fp10 = _df_frames_per_10min(nominal)
        fp1 = _df_frames_per_minute(nominal)
        tens, rem = divmod(count, fp10)
        if rem < 60 * nominal:
            minute, number = 0, rem
        else:
            k = rem - 60 * nominal
            minute = 1 + k // fp1
            number = _DF_DROP + k % fp1
        total_minutes = tens * 10 + minute
        return cls(total_minutes // 60, total_minutes % 60,
                   number // nominal, number % nominal, rate)

    def advanced(self, n_frames: int) -> "Timecode":
        """This timecode plus ``n_frames`` (negative allowed), wrapping
        at 24 hours."""
        return self.from_frame_count(self.to_frame_count() + n_frames,
                                     self.rate)

    # -- real time ------------------------------------------------------

    def to_seconds(self) -> float:
        """Elapsed real seconds since 00:00:00:00."""
        return self.to_frame_count() * self.rate.den / self.rate.num

    @classmethod
    def from_seconds(cls, seconds: float, rate: FrameRate) -> "Timecode":
        """The timecode label of the frame nearest ``seconds``."""
        return cls.from_frame_count(
            int(round(seconds * rate.num / rate.den)), rate)
