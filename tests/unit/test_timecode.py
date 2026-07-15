"""SMPTE timecode math (utils/timecode/tc.py, docs/ltc-plan.md phase 0).

All arithmetic is frame-count based; the drop-frame vectors here are
the canonical ones (the minute boundary drops 02, the ten-minute
boundary does not).
"""

import pytest

from utils.timecode import (
    FPS_24, FPS_25, FPS_30, FPS_2997_DF, SUPPORTED_RATES, Timecode,
)
from utils.timecode.tc import frames_in_day


class TestParseAndFormat:

    def test_parse_round_trips_all_rates(self):
        for rate in SUPPORTED_RATES:
            tc = Timecode.parse("01:23:45:11", rate)
            assert (tc.hours, tc.minutes, tc.seconds, tc.frames) == \
                (1, 23, 45, 11)
            assert Timecode.parse(str(tc), rate) == tc

    def test_drop_frame_formats_with_semicolon(self):
        assert str(Timecode(0, 1, 0, 2, FPS_2997_DF)) == "00:01:00;02"
        assert str(Timecode(0, 1, 0, 2, FPS_30)) == "00:01:00:02"

    def test_parse_accepts_semicolon_separator(self):
        tc = Timecode.parse("00:10:00;00", FPS_2997_DF)
        assert tc.frames == 0

    def test_parse_rejects_garbage(self):
        for bad in ("", "1:2:3", "aa:bb:cc:dd", "00:00:00:00:00", "12000"):
            with pytest.raises(ValueError):
                Timecode.parse(bad, FPS_25)

    def test_field_ranges_enforced(self):
        with pytest.raises(ValueError):
            Timecode(24, 0, 0, 0, FPS_25)      # hours
        with pytest.raises(ValueError):
            Timecode(0, 60, 0, 0, FPS_25)      # minutes
        with pytest.raises(ValueError):
            Timecode(0, 0, 60, 0, FPS_25)      # seconds
        with pytest.raises(ValueError):
            Timecode(0, 0, 0, 25, FPS_25)      # frames at 25 fps
        with pytest.raises(ValueError):
            Timecode(0, 0, 0, -1, FPS_25)

    def test_dropped_frame_numbers_are_invalid(self):
        # Minute not divisible by 10: frames 00 and 01 do not exist.
        for f in (0, 1):
            with pytest.raises(ValueError):
                Timecode(0, 1, 0, f, FPS_2997_DF)
        # Every 10th minute keeps them.
        assert Timecode(0, 10, 0, 0, FPS_2997_DF).frames == 0
        # And they are perfectly fine outside second 0.
        assert Timecode(0, 1, 1, 0, FPS_2997_DF).frames == 0
        # Non-drop 30 keeps them everywhere.
        assert Timecode(0, 1, 0, 0, FPS_30).frames == 0


class TestFrameCountArithmetic:

    def test_frame_count_round_trip(self):
        for rate in SUPPORTED_RATES:
            for count in (0, 1, 1799, 1800, 17981, 17982, 107892,
                          frames_in_day(rate) - 1):
                tc = Timecode.from_frame_count(count, rate)
                assert tc.to_frame_count() == count, (rate, count)

    def test_df_minute_boundary_drops_two_numbers(self):
        tc = Timecode.parse("00:00:59;29", FPS_2997_DF)
        assert str(tc.advanced(1)) == "00:01:00;02"

    def test_df_ten_minute_boundary_drops_nothing(self):
        tc = Timecode.parse("00:09:59;29", FPS_2997_DF)
        assert str(tc.advanced(1)) == "00:10:00;00"

    def test_non_drop_minute_boundary(self):
        tc = Timecode.parse("00:00:59:29", FPS_30)
        assert str(tc.advanced(1)) == "00:01:00:00"

    def test_advanced_backwards(self):
        tc = Timecode.parse("00:01:00;02", FPS_2997_DF)
        assert str(tc.advanced(-1)) == "00:00:59;29"

    def test_wraps_at_24_hours(self):
        for rate in SUPPORTED_RATES:
            last = Timecode(23, 59, 59, rate.nominal - 1, rate)
            assert last.advanced(1) == Timecode(0, 0, 0, 0, rate)
            assert Timecode(0, 0, 0, 0, rate).advanced(-1) == last

    def test_df_hour_count_matches_known_value(self):
        # 01:00:00;00 = 108000 numbering frames minus 2 per dropped
        # minute (54 of the 60 minutes) = 107892.
        tc = Timecode.parse("01:00:00;00", FPS_2997_DF)
        assert tc.to_frame_count() == 107892


class TestRealTime:

    def test_whole_second_rates_are_exact(self):
        assert Timecode.parse("00:00:01:00", FPS_25).to_seconds() == 1.0
        assert Timecode.parse("01:00:00:00", FPS_24).to_seconds() == 3600.0

    def test_df_tracks_the_wall_clock(self):
        # One labelled hour of drop-frame is 3599.9964.. real seconds:
        # the numbering intentionally hugs the wall clock.
        secs = Timecode.parse("01:00:00;00", FPS_2997_DF).to_seconds()
        assert secs == pytest.approx(107892 * 1001 / 30000)
        assert abs(secs - 3600.0) < 0.01

    def test_seconds_round_trip(self):
        for rate in SUPPORTED_RATES:
            for count in (0, 7, 1799, 123456):
                tc = Timecode.from_frame_count(count, rate)
                assert Timecode.from_seconds(tc.to_seconds(), rate) == tc
