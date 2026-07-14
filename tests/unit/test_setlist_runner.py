"""Setlist timecode runner (utils/timecode/runner.py, phase 3 policy).

Pure-policy tests against a fake transport, plus the plan's
no-hardware end to end: generated LTC audio through the real decoder
and chase drives a two-song setlist.
"""

import numpy as np
import pytest

from config.models import PauseLook, Setlist, SetlistEntry, SongTrigger
from utils.timecode import (
    FPS_25, LTCDecoder, SetlistTimecodeRunner, TimecodeChase, Timecode,
    generate_ltc,
)

DURATIONS = {"Opener": 180.0, "Ballad": 240.0, "Closer": 200.0}


class FakeTransport:
    def __init__(self):
        self.calls = []
        self._position = 0.0
        self.loaded = None
        self.playing = False

    def load_song(self, name):
        self.calls.append(("load", name))
        self.loaded = name

    def play_at(self, seconds):
        self.calls.append(("play", round(seconds, 3)))
        self._position = seconds
        self.playing = True

    def seek(self, seconds):
        self.calls.append(("seek", round(seconds, 3)))
        self._position = seconds

    def stop(self):
        self.calls.append(("stop",))
        self.playing = False

    def position(self):
        return self._position


def smpte_entry(song, timecode):
    return SetlistEntry(song=song,
                        trigger=SongTrigger(mode="smpte", timecode=timecode),
                        pause_after=PauseLook())


def make_runner(entries, transport=None, durations=DURATIONS):
    transport = transport or FakeTransport()
    setlist = Setlist(name="Set", entries=entries, sync_mode="smpte")
    runner = SetlistTimecodeRunner(setlist, transport,
                                   duration_of=lambda n: durations[n],
                                   rate=FPS_25)
    return runner, transport


STANDARD = [
    smpte_entry("Opener", "01:00:00:00"),    # 3600 .. 3780
    smpte_entry("Ballad", "01:10:00:00"),    # 4200 .. 4440
    smpte_entry("Closer", "01:20:00:00"),    # 4800 .. 5000
]


class TestResolution:

    def test_windows_are_built_sorted(self):
        runner, _ = make_runner(list(reversed(STANDARD)))
        assert [w[2] for w in runner.windows] == \
            ["Opener", "Ballad", "Closer"]

    def test_before_between_and_after(self):
        runner, _ = make_runner(STANDARD)
        assert runner.resolve(3599.0) is None                 # before
        assert runner.resolve(3900.0) is None                 # between
        assert runner.resolve(5300.0) is None                 # after
        assert runner.resolve(3600.0) == ("Opener", 0.0)
        name, pos = runner.resolve(4210.5)
        assert name == "Ballad"
        assert pos == pytest.approx(10.5)

    def test_window_end_is_exclusive(self):
        runner, _ = make_runner(STANDARD)
        assert runner.resolve(3780.0) is None                 # 3600+180

    def test_non_smpte_entries_are_invisible(self):
        entries = [
            smpte_entry("Opener", "01:00:00:00"),
            SetlistEntry(song="Ballad",
                         trigger=SongTrigger(mode="midi_pc", value=3)),
        ]
        runner, _ = make_runner(entries)
        assert [w[2] for w in runner.windows] == ["Opener"]

    def test_broken_timecode_is_skipped_and_named(self):
        entries = [smpte_entry("Opener", "01:00:00:00"),
                   smpte_entry("Ballad", "not a timecode")]
        runner, _ = make_runner(entries)
        assert runner.skipped == ["Ballad"]
        assert [w[2] for w in runner.windows] == ["Opener"]

    def test_overlap_latest_start_wins(self):
        entries = [smpte_entry("Opener", "01:00:00:00"),     # ..3780
                   smpte_entry("Ballad", "01:02:00:00")]     # 3720..
        runner, _ = make_runner(entries)
        assert runner.resolve(3730.0)[0] == "Ballad"
        assert runner.resolve(3700.0)[0] == "Opener"


class TestTransportPolicy:

    def test_fires_a_song_mid_window(self):
        runner, transport = make_runner(STANDARD)
        runner.update(3660.0)                       # 60 s into Opener
        assert transport.calls == [("load", "Opener"), ("play", 60.0)]

    def test_small_drift_is_left_alone(self):
        runner, transport = make_runner(STANDARD)
        runner.update(3660.0)
        transport._position = 60.05                 # 50 ms ahead
        runner.update(3660.05)                      # tc also moved on
        assert not any(c[0] == "seek" for c in transport.calls)

    def test_large_drift_seeks_once(self):
        runner, transport = make_runner(STANDARD)
        runner.update(3660.0)
        transport._position = 59.0                  # a second behind
        runner.update(3660.2)
        seeks = [c for c in transport.calls if c[0] == "seek"]
        assert seeks == [("seek", 60.2)]

    def test_first_update_outside_windows_stops_manual_playback(self):
        runner, transport = make_runner(STANDARD)
        transport.playing = True                    # operator had hit play
        runner.update(3000.0)
        assert transport.calls == [("stop",)]
        # And it does not spam stop on every later tick.
        runner.update(3001.0)
        assert transport.calls == [("stop",)]

    def test_window_exit_stops_and_next_window_fires(self):
        runner, transport = make_runner(STANDARD)
        runner.update(3700.0)                       # Opener
        runner.update(3900.0)                       # gap
        runner.update(4200.0)                       # Ballad opens
        kinds = [c[0] for c in transport.calls]
        assert kinds == ["load", "play", "stop", "load", "play"]
        assert transport.loaded == "Ballad"

    def test_a_locate_lands_wherever_it_lands(self):
        runner, transport = make_runner(STANDARD)
        runner.update(3660.0)                       # Opener at 60 s
        runner.update(4300.0)                       # desk locates into Ballad
        assert transport.calls[-2:] == [("load", "Ballad"), ("play", 100.0)]

    def test_no_signal_never_stops_the_show(self):
        runner, transport = make_runner(STANDARD)
        runner.update(3660.0)
        n_calls = len(transport.calls)
        runner.update(None)                         # cable pulled
        runner.update(None)
        assert len(transport.calls) == n_calls      # nothing happened
        assert runner.current_song == "Opener"

    def test_rebuild_picks_up_setlist_edits(self):
        runner, transport = make_runner(STANDARD[:1])
        assert len(runner.windows) == 1
        runner.setlist.entries.append(smpte_entry("Ballad", "01:10:00:00"))
        runner.rebuild()
        assert len(runner.windows) == 2


class TestEndToEndWithRealChase:
    """The plan's no-hardware proof: generated LTC -> decoder -> chase
    -> runner against a two-song setlist. Song 1 fires at its start
    timecode, the playhead tracks within a frame, song 2 fires when
    its window opens."""

    def test_two_songs_fire_and_track(self):
        entries = [smpte_entry("Opener", "01:00:00:05"),
                   smpte_entry("Ballad", "01:00:00:10")]
        durations = {"Opener": 0.16, "Ballad": 60.0}  # Opener: 4 frames
        transport = FakeTransport()
        runner, _ = make_runner(entries, transport, durations)

        # 2 s of LTC starting just before the first window.
        start = Timecode.parse("01:00:00:00", FPS_25)
        audio = generate_ltc(start, 2.0)
        decoder = LTCDecoder()
        chase = TimecodeChase(FPS_25)

        chunk = 2205                                # 50 ms drains
        base = 500.0
        for i in range(0, len(audio), chunk):
            now = base + (i + chunk) / 44100.0
            for frame in decoder.feed(audio[i:i + chunk]):
                lag = (i + chunk - frame.end_sample) / 44100.0
                chase.feed(frame, now - lag)
            runner.update(chase.position(now))

        kinds = [c[0] for c in transport.calls]
        # Opener fired, its 0.16 s window closed (stop), Ballad fired.
        assert kinds.count("load") == 2
        assert transport.loaded == "Ballad"
        assert "stop" in kinds

        # The playhead tracked within a frame: final position matches
        # the timecode delta into Ballad's window.
        final_now = base + len(audio) / 44100.0
        t = chase.position(final_now)
        expected_pos = t - Timecode.parse("01:00:00:10",
                                          FPS_25).to_seconds()
        drift = transport.position() - expected_pos
        assert abs(drift) <= 0.08 + 1.0 / 25.0
