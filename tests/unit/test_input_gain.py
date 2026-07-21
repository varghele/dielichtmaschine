# tests/unit/test_input_gain.py
"""The Auto mode input gain stage (2026-07-21).

audio/live_input.py carries the whole signal side: the capture callback
applies a linear gain before the ring buffer (so the analyzer, its
silence gate and the engine see the gained signal) and records the
pre-gain block peak for the UI level meter; the module-level helpers
are the pure math the tab wires to the GAIN control (log slider
mapping, dB meter mapping, the AUTO measure-and-set computation).

No PortAudio anywhere: LiveAudioInput is constructed but never
initialized, and the callback is driven directly with known blocks.
The LTC input service builds its own LiveAudioInput and never calls
set_gain - the default-1.0 test pins that isolation.
"""

import numpy as np
import pytest

from audio.live_input import (AUTO_GAIN_FLOOR, AUTO_GAIN_TARGET_PEAK,
                              GAIN_MAX, GAIN_MIN, LiveAudioInput,
                              compute_auto_gain, gain_to_slider,
                              level_to_fraction, slider_to_gain)


class _QuietStatus:
    """A falsy callback status (the callback checks ``if status:``)."""

    input_overflow = False

    def __bool__(self):
        return False


class TestAutoGainMath:

    def test_silence_refuses(self):
        assert compute_auto_gain(0.0) is None
        assert compute_auto_gain(AUTO_GAIN_FLOOR / 2.0) is None

    def test_quiet_source_clamps_to_max(self):
        # 0.0025 peak wants 100x; the clamp caps at +20 dB.
        assert compute_auto_gain(0.0025) == GAIN_MAX

    def test_loud_source_dampens(self):
        gain = compute_auto_gain(0.9)
        assert gain == pytest.approx(AUTO_GAIN_TARGET_PEAK / 0.9)
        assert gain < 1.0

    def test_on_target_is_unity(self):
        assert compute_auto_gain(AUTO_GAIN_TARGET_PEAK) == pytest.approx(1.0)


class TestSliderMapping:

    def test_endpoints_and_centre(self):
        assert slider_to_gain(0.0) == pytest.approx(GAIN_MIN)
        assert slider_to_gain(0.5) == pytest.approx(1.0)
        assert slider_to_gain(1.0) == pytest.approx(GAIN_MAX)
        assert gain_to_slider(1.0) == pytest.approx(0.5)

    def test_round_trip(self):
        for gain in (0.1, 0.25, 1.0, 3.3, 10.0):
            assert slider_to_gain(gain_to_slider(gain)) == \
                pytest.approx(gain)

    def test_out_of_range_clamps(self):
        assert gain_to_slider(1000.0) == 1.0
        assert slider_to_gain(2.0) == pytest.approx(GAIN_MAX)


class TestLevelToFraction:

    def test_anchor_points(self):
        assert level_to_fraction(0.0) == 0.0
        assert level_to_fraction(1e-3) == pytest.approx(0.0)   # -60 dBFS
        assert level_to_fraction(1.0) == 1.0
        # -12 dBFS sits at 80% of a [-60, 0] scale.
        assert level_to_fraction(0.25) == pytest.approx(0.8, abs=0.01)

    def test_over_unity_saturates(self):
        assert level_to_fraction(2.0) == 1.0


class TestCallbackGainStage:

    @pytest.fixture
    def live_input(self):
        source = LiveAudioInput(sample_rate=44100, channels=1,
                                buffer_size=512)
        yield source
        source.cleanup()

    def _block(self, value=0.5, frames=512):
        block = np.full((frames, 1), value, dtype=np.float32)
        block[10, 0] = -0.75          # the peak, negative on purpose
        return block

    def test_unity_gain_writes_verbatim(self, live_input):
        block = self._block()
        live_input._input_callback(block, block.shape[0], None,
                                   _QuietStatus())
        written = live_input.ring_buffer.read_latest(block.shape[0])
        np.testing.assert_array_equal(written, block)

    def test_gain_scales_the_ring_not_the_source(self, live_input):
        live_input.set_gain(2.0)
        block = self._block()
        original = block.copy()
        live_input._input_callback(block, block.shape[0], None,
                                   _QuietStatus())
        written = live_input.ring_buffer.read_latest(block.shape[0])
        np.testing.assert_allclose(written, original * 2.0, rtol=1e-6)
        # PortAudio's buffer must never be mutated in place.
        np.testing.assert_array_equal(block, original)

    def test_raw_peak_is_pre_gain(self, live_input):
        live_input.set_gain(4.0)
        block = self._block()
        live_input._input_callback(block, block.shape[0], None,
                                   _QuietStatus())
        assert live_input.raw_peak() == pytest.approx(0.75)

    def test_set_gain_clamps(self, live_input):
        live_input.set_gain(1000.0)
        assert live_input.gain() == GAIN_MAX
        live_input.set_gain(0.0)
        assert live_input.gain() == GAIN_MIN

    def test_ltc_isolation_default_is_unity(self):
        # The LTC service constructs its own LiveAudioInput and never
        # touches gain - a fresh instance must be transparent.
        source = LiveAudioInput()
        assert source.gain() == 1.0
        source.cleanup()
