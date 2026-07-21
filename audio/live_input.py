"""
Live audio input capture using sounddevice.
Captures audio from an input device into a ring buffer for real-time analysis.

Carries the Auto mode INPUT GAIN stage (2026-07-21): the callback applies a
linear gain to every block before it enters the ring buffer, so the analyzer,
its silence gate and everything downstream see the gained signal - and
records the pre-gain block peak so the UI can meter what the microphone
physically picks up. The LTC input service constructs its own LiveAudioInput
whose gain stays at the 1.0 default, so timecode decoding is never touched.
"""

import math

import sounddevice as sd
import numpy as np
from typing import Optional
from .ring_buffer import AudioRingBuffer

# Input gain bounds: exactly +/-20 dB. Wide enough to rescue a quiet
# lavalier or tame a hot desk feed, narrow enough that AUTO can never
# turn an empty room into pure noise gain.
GAIN_MIN = 0.1
GAIN_MAX = 10.0

#: AUTO gain aims the measured peak at -12 dBFS: the conventional
#: recording set-point - headroom for transients louder than the
#: measurement window saw, far above the analyzer's silence gate.
AUTO_GAIN_TARGET_PEAK = 0.25

#: Below this raw peak (-60 dBFS) AUTO refuses to set a gain at all -
#: there is nothing to normalize, only noise to amplify.
AUTO_GAIN_FLOOR = 1e-3


def compute_auto_gain(raw_peak: float) -> Optional[float]:
    """The gain that puts ``raw_peak`` at the -12 dBFS target, clamped
    to [GAIN_MIN, GAIN_MAX]; None when the source is effectively silent
    (never rail a dead room to +20 dB)."""
    if raw_peak < AUTO_GAIN_FLOOR:
        return None
    return min(GAIN_MAX, max(GAIN_MIN, AUTO_GAIN_TARGET_PEAK / raw_peak))


def level_to_fraction(peak: float) -> float:
    """Peak amplitude -> meter fill fraction, linear-in-dB over
    [-60, 0] dBFS. A linear-amplitude bar would crush everything quieter
    than -20 dBFS into the bottom tenth of the bar - exactly the "is my
    quiet source arriving" range the meter exists for."""
    if peak <= 0.0:
        return 0.0
    db = 20.0 * math.log10(min(1.0, peak))
    return max(0.0, min(1.0, 1.0 + db / 60.0))


def gain_to_slider(gain: float) -> float:
    """Linear gain -> slider position 0..1 (log mapping, 0.5 == 0 dB)."""
    gain = min(GAIN_MAX, max(GAIN_MIN, gain))
    return (20.0 * math.log10(gain) + 20.0) / 40.0


def slider_to_gain(value: float) -> float:
    """Slider position 0..1 -> linear gain (log mapping, 0.5 == 0 dB)."""
    value = min(1.0, max(0.0, value))
    return 10.0 ** ((value * 40.0 - 20.0) / 20.0)


class LiveAudioInput:
    """Captures live audio from an input device into a ring buffer.

    Separate from AudioEngine (output-only) to avoid ASIO exclusivity issues
    where some drivers cannot open the same device for both input and output.
    """

    def __init__(self, sample_rate: int = 44100, channels: int = 1,
                 buffer_size: int = 512, ring_buffer_seconds: float = 5.0):
        """
        Args:
            sample_rate: Input sample rate in Hz
            channels: Number of input channels (1=mono, recommended for analysis)
            buffer_size: Frames per callback buffer
            ring_buffer_seconds: Ring buffer duration in seconds
        """
        self.sample_rate = sample_rate
        self.channels = channels
        self.buffer_size = buffer_size

        self._ring_buffer = AudioRingBuffer(
            max_seconds=ring_buffer_seconds,
            sample_rate=sample_rate,
            channels=channels,
        )
        self._stream: Optional[sd.InputStream] = None
        self._is_initialized = False

        # Input gain stage. Plain-float loads/stores are GIL-atomic, so
        # the callback and the UI thread share these without a lock
        # (matching the callback's minimal-GIL-hold contract). The
        # scratch buffer keeps the gain multiply allocation-free.
        self._gain = 1.0
        self._raw_peak = 0.0
        self._gain_scratch = np.empty((buffer_size, channels),
                                      dtype=np.float32)

    @property
    def ring_buffer(self) -> AudioRingBuffer:
        """Access the ring buffer containing captured audio."""
        return self._ring_buffer

    def set_gain(self, gain: float) -> None:
        """Set the input gain (linear, clamped to [GAIN_MIN, GAIN_MAX]).
        Applied in the capture callback before the ring buffer, so the
        analyzer and everything downstream see the gained signal."""
        self._gain = float(min(GAIN_MAX, max(GAIN_MIN, gain)))

    def gain(self) -> float:
        """The current linear input gain."""
        return self._gain

    def raw_peak(self) -> float:
        """Max |sample| of the most recent callback block, PRE-gain -
        what the microphone physically delivered. 0.0 before the first
        block. The UI meters the post-gain level as raw_peak() * gain()
        (peak is linear, so this equals measuring after the multiply)."""
        return self._raw_peak

    def initialize(self, device_index: Optional[int] = None) -> bool:
        """Initialize the input stream.

        Args:
            device_index: Input device to use (None = default)

        Returns:
            True if initialization successful
        """
        try:
            if self._is_initialized:
                return True

            self._stream = sd.InputStream(
                samplerate=self.sample_rate,
                blocksize=self.buffer_size,
                device=device_index,
                channels=self.channels,
                dtype='float32',
                callback=self._input_callback,
            )

            self._is_initialized = True
            return True

        except Exception as e:
            print(f"Failed to initialize live audio input: {e}")
            self.cleanup()
            return False

    def start(self) -> bool:
        """Start capturing audio.

        Returns:
            True if capture started successfully
        """
        if not self._is_initialized or not self._stream:
            return False

        try:
            if not self._stream.active:
                self._ring_buffer.clear()
                self._stream.start()
            return True
        except Exception as e:
            print(f"Failed to start live audio input: {e}")
            return False

    def stop(self) -> None:
        """Stop capturing audio."""
        if self._stream and self._stream.active:
            try:
                self._stream.abort()
            except Exception as e:
                print(f"Error stopping live audio input: {e}")

    def cleanup(self) -> None:
        """Release all resources."""
        self.stop()

        if self._stream:
            try:
                self._stream.close()
            except Exception:
                pass
            self._stream = None

        self._is_initialized = False

    def is_active(self) -> bool:
        """Check if currently capturing."""
        return self._stream is not None and self._stream.active

    def _input_callback(self, indata, frames, time, status):
        """sounddevice input callback — writes captured audio to ring buffer.

        Must be fast: no allocations, no blocking I/O, minimal GIL hold time.
        """
        if status:
            if status.input_overflow:
                pass  # Dropped frames, acceptable for live monitoring
            else:
                print(f"Live input status: {status}")

        # Pre-gain block peak for the UI level meter (single float
        # store: GIL-atomic, no lock).
        self._raw_peak = float(np.max(np.abs(indata))) if indata.size \
            else 0.0

        # Apply the gain stage, then write to the ring buffer. Never
        # mutate indata in place - it is PortAudio's buffer.
        gain = self._gain
        if gain == 1.0:
            self._ring_buffer.write(indata)
        elif indata.shape[0] <= self._gain_scratch.shape[0]:
            out = self._gain_scratch[:indata.shape[0]]
            np.multiply(indata, gain, out=out)
            self._ring_buffer.write(out)
        else:
            self._ring_buffer.write(indata * gain)
