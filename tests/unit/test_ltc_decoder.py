"""LTC generate -> decode round trip (docs/ltc-plan.md phase 0).

The generator (utils/timecode/generator.py) and the decoder
(utils/timecode/ltc.py) implement the SMPTE 12M bit layout
independently, so these round trips prove both sides.

The decoder is allowed a short lock-in (period bootstrap + first sync
word, at most ~2 frames): assertions demand that the decoded stream
starts within the first LOCK_SLACK frames and is strictly consecutive
from there to the end.
"""

import numpy as np
import pytest

from utils.timecode import (
    FPS_24, FPS_25, FPS_30, FPS_2997_DF, SUPPORTED_RATES,
    LTCDecoder, Timecode, generate_ltc, write_ltc_wav,
)

# Frames the decoder may lose to period bootstrap + sync alignment.
LOCK_SLACK = 3


def decode_all(audio, sample_rate=44100, chunk=1024):
    dec = LTCDecoder(sample_rate=sample_rate)
    frames = []
    for i in range(0, len(audio), chunk):
        frames.extend(dec.feed(audio[i:i + chunk]))
    return dec, frames


def assert_locked_run(frames, start, seconds, slack=LOCK_SLACK):
    """The decode covers [start .. start+seconds) minus lock-in slack,
    strictly consecutively."""
    rate = start.rate
    expected = int(seconds * rate.num / rate.den)
    assert len(frames) >= expected - slack, \
        f"decoded {len(frames)} of ~{expected} frames"
    first = frames[0].timecode(rate)
    offset = first.to_frame_count() - start.to_frame_count()
    assert 0 <= offset <= slack, f"first decoded frame {first} vs {start}"
    for prev, cur in zip(frames, frames[1:]):
        assert cur.timecode(rate) == prev.timecode(rate).advanced(1), \
            f"gap between {prev.label()} and {cur.label()}"


class TestRoundTrip:

    @pytest.mark.parametrize("rate,start_text", [
        (FPS_24, "00:00:58:00"),
        (FPS_25, "00:00:58:00"),
        (FPS_30, "00:00:58:00"),
        (FPS_2997_DF, "00:00:58;00"),   # crosses the 00:01:00;02 drop
    ])
    def test_all_rates_across_a_minute_boundary(self, rate, start_text):
        start = Timecode.parse(start_text, rate)
        audio = generate_ltc(start, 10.0)
        dec, frames = decode_all(audio)
        assert_locked_run(frames, start, 10.0)
        assert dec.framing_errors <= 1  # at most the bootstrap remnant

    def test_one_minute_stream_is_gapless(self):
        start = Timecode.parse("00:59:30:00", FPS_25)  # crosses the hour
        audio = generate_ltc(start, 60.0)
        _, frames = decode_all(audio)
        assert_locked_run(frames, start, 60.0)

    def test_drop_frame_flag_survives(self):
        start = Timecode.parse("00:00:59;00", FPS_2997_DF)
        _, frames = decode_all(generate_ltc(start, 3.0))
        assert frames and all(f.drop_frame for f in frames)
        labels = [f.label() for f in frames]
        assert "00:01:00;02" in labels
        assert "00:01:00;00" not in labels

    def test_user_bits_are_zero_from_our_generator(self):
        _, frames = decode_all(
            generate_ltc(Timecode.parse("10:20:30:00", FPS_25), 2.0))
        assert frames and all(f.user_bits == 0 for f in frames)

    def test_end_sample_tracks_real_time(self):
        rate = FPS_25
        start = Timecode.parse("00:00:00:00", rate)
        _, frames = decode_all(generate_ltc(start, 5.0))
        for f in frames:
            # Frame N ends at (N+1) frame durations into the stream.
            n = f.timecode(rate).to_frame_count()
            expected = (n + 1) * (rate.den / rate.num) * 44100
            assert abs(f.end_sample - expected) < 0.02 * 44100, f.label()


class TestRobustness:

    def _run(self, mutate, rate=FPS_25, seconds=8.0, sample_rate=44100,
             slack=LOCK_SLACK):
        start = Timecode.parse("00:00:58:00", rate)
        audio = generate_ltc(start, seconds, sample_rate=sample_rate)
        audio = mutate(audio.astype(np.float64))
        _, frames = decode_all(audio, sample_rate=sample_rate)
        assert_locked_run(frames, start, seconds, slack=slack)

    def test_inverted_polarity(self):
        self._run(lambda a: -a)

    def test_low_amplitude(self):
        self._run(lambda a: a * (0.05 / 0.8))

    def test_dc_offset(self):
        self._run(lambda a: a + 0.4)

    def test_additive_noise_20db_snr(self):
        rng = np.random.default_rng(42)
        self._run(lambda a: a + rng.normal(0.0, 0.08, a.size))

    def test_48k_sample_rate(self):
        self._run(lambda a: a, sample_rate=48000)

    def test_feeding_odd_chunk_sizes_matches_one_shot(self):
        start = Timecode.parse("00:00:00:00", FPS_30)
        audio = generate_ltc(start, 5.0)
        _, ref = decode_all(audio, chunk=len(audio))
        dec = LTCDecoder()
        got = []
        sizes = [1, 7, 64, 313, 4096]
        i = k = 0
        while i < len(audio):
            n = sizes[k % len(sizes)]
            got.extend(dec.feed(audio[i:i + n]))
            i += n
            k += 1
        assert [f.label() for f in got] == [f.label() for f in ref]
        assert [f.end_sample for f in got] == \
            pytest.approx([f.end_sample for f in ref])

    def test_stream_starting_mid_frame(self):
        start = Timecode.parse("00:00:10:00", FPS_25)
        audio = generate_ltc(start, 6.0)
        # Chop off two thirds of the first frame.
        offset = int(44100 / 25 * 0.66)
        _, frames = decode_all(audio[offset:])
        assert frames
        assert_locked_run(frames, start.advanced(1), 6.0 - 1 / 25,
                          slack=LOCK_SLACK)

    def test_recovers_after_a_dropout(self):
        rate = FPS_25
        start = Timecode.parse("00:00:00:00", rate)
        audio = generate_ltc(start, 10.0).astype(np.float64)
        a, b = int(4.0 * 44100), int(4.2 * 44100)
        audio[a:b] = 0.0
        _, frames = decode_all(audio)
        labels = [f.label() for f in frames]
        # Solid before, solid after, nothing invented inside the hole.
        assert "00:00:03:20" in labels
        assert "00:00:09:20" in labels
        resume = [f for f in frames
                  if f.timecode(rate).to_seconds() > 4.2]
        assert resume, "never recovered after the dropout"
        gap = resume[0].timecode(rate).to_seconds() - 4.2
        assert gap < 0.2, f"took {gap:.2f}s to re-lock"
        for prev, cur in zip(resume, resume[1:]):
            assert cur.timecode(rate) == prev.timecode(rate).advanced(1)


class TestRateInference:

    @pytest.mark.parametrize("rate", SUPPORTED_RATES)
    def test_rate_guess_settles_on_the_truth(self, rate):
        start = Timecode(0, 0, 58, 0, rate)
        dec, _ = decode_all(generate_ltc(start, 3.0))
        assert dec.rate_guess == rate

    def test_fps_estimate_is_close(self):
        dec, _ = decode_all(
            generate_ltc(Timecode(0, 0, 0, 0, FPS_25), 2.0))
        assert dec.fps_estimate == pytest.approx(25.0, rel=0.02)


class TestWavWriter:

    def test_wav_round_trips_through_the_decoder(self, tmp_path):
        import wave

        path = str(tmp_path / "ltc.wav")
        start = Timecode.parse("00:00:00:00", FPS_25)
        write_ltc_wav(path, start, 2.0)
        with wave.open(path, "rb") as w:
            assert w.getnchannels() == 1
            assert w.getframerate() == 44100
            pcm = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2")
        audio = pcm.astype(np.float64) / 32767.0
        _, frames = decode_all(audio)
        assert_locked_run(frames, start, 2.0)
