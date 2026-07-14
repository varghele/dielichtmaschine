# utils/timecode/generator.py
"""Synthetic LTC audio (docs/ltc-plan.md phase 0).

The inverse of utils/timecode/ltc.py, implemented INDEPENDENTLY from
the SMPTE 12M spec: this module keeps its own bit-position table
instead of sharing constants with the decoder, so the
generate -> decode round-trip test proves both sides rather than
proving x == x.

Also the bench signal source: there is no timecode generator hardware
on the desk, so :func:`write_ltc_wav` produces the file that gets
played into the line-in from a phone or DAW for the manual checkpoint.
"""

import wave
from typing import List

import numpy as np

from .tc import Timecode

# The fixed sync word occupying bits 64..79, in transmission order.
_SYNC_WORD_BITS = (0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 1)

# Field positions (bit index of the field's LSB, transmission order).
_FRAME_UNITS = 0    # 4 bits
_FRAME_TENS = 8     # 2 bits
_DROP_FRAME_FLAG = 10
_SECOND_UNITS = 16  # 4 bits
_SECOND_TENS = 24   # 3 bits
_MINUTE_UNITS = 32  # 4 bits
_MINUTE_TENS = 40   # 3 bits
_HOUR_UNITS = 48    # 4 bits
_HOUR_TENS = 56     # 2 bits
# User bits, colour-frame flag, binary group flags and the polarity
# correction bit all stay 0: no consumer yet, and the decoder treats
# parity as soft per the plan.


def _frame_bits(tc: Timecode) -> List[int]:
    """The 80 bits of one LTC frame, index = transmission order."""
    bits = [0] * 80

    def put(value: int, pos: int, width: int) -> None:
        for i in range(width):
            bits[pos + i] = (value >> i) & 1

    put(tc.frames % 10, _FRAME_UNITS, 4)
    put(tc.frames // 10, _FRAME_TENS, 2)
    if tc.rate.drop_frame:
        bits[_DROP_FRAME_FLAG] = 1
    put(tc.seconds % 10, _SECOND_UNITS, 4)
    put(tc.seconds // 10, _SECOND_TENS, 3)
    put(tc.minutes % 10, _MINUTE_UNITS, 4)
    put(tc.minutes // 10, _MINUTE_TENS, 3)
    put(tc.hours % 10, _HOUR_UNITS, 4)
    put(tc.hours // 10, _HOUR_TENS, 2)
    bits[64:80] = _SYNC_WORD_BITS
    return bits


def generate_ltc(start: Timecode, seconds: float,
                 sample_rate: int = 44100, amplitude: float = 0.8,
                 polarity: int = 1) -> np.ndarray:
    """Synthesize ``seconds`` of LTC audio starting at ``start``.

    Biphase-mark: the level toggles at every bit-cell boundary, and a
    1 bit toggles once more mid-cell. The rate (and drop-frame
    numbering) comes from ``start.rate``. Returns mono float32 samples;
    ``polarity=-1`` inverts the waveform (a decoder must not care).
    """
    rate = start.rate
    frame_dur = rate.den / rate.num
    n_frames = int(np.ceil(seconds * rate.num / rate.den))
    n_samples = int(round(seconds * sample_rate))

    transitions: List[float] = []
    tc = start
    for k in range(n_frames):
        bits = _frame_bits(tc)
        frame_t0 = k * frame_dur          # from k directly: no accumulation
        bit_dur = frame_dur / 80.0
        for i, bit in enumerate(bits):
            t = frame_t0 + i * bit_dur
            transitions.append(t)
            if bit:
                transitions.append(t + bit_dur / 2.0)
        tc = tc.advanced(1)

    trans_samples = np.asarray(transitions) * sample_rate
    counts = np.searchsorted(trans_samples, np.arange(n_samples),
                             side="right")
    # Idle level is -1; the transition at t=0 flips sample 0 to +1.
    level = np.where(counts % 2 == 1, 1.0, -1.0)
    return (amplitude * float(polarity) * level).astype(np.float32)


def write_ltc_wav(path: str, start: Timecode, seconds: float,
                  sample_rate: int = 44100, amplitude: float = 0.8) -> None:
    """Write an LTC audio file (16-bit mono PCM) for the bench check."""
    samples = generate_ltc(start, seconds, sample_rate=sample_rate,
                           amplitude=amplitude)
    pcm = np.clip(samples * 32767.0, -32768, 32767).astype("<i2")
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm.tobytes())
