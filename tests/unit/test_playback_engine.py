# tests/unit/test_playback_engine.py
"""Unit tests for timeline/playback_engine.py - playback control."""

import pytest
from unittest.mock import MagicMock
from config.models import ShowPart
from timeline.song_structure import SongStructure
from timeline.playback_engine import PlaybackEngine
from timeline.light_lane import LightLane


@pytest.fixture
def qapp():
    """Create a QApplication instance for the test."""
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture
def engine(qapp):
    return PlaybackEngine()


@pytest.fixture
def song_structure():
    parts = [
        ShowPart(name="Intro", color="#FFF", signature="4/4",
                 bpm=120.0, num_bars=4, transition="instant"),
    ]
    ss = SongStructure()
    ss.load_from_show_parts(parts)
    return ss


class TestInitialState:

    def test_defaults(self, engine):
        assert engine.current_position == 0.0
        assert engine.is_playing is False
        assert engine.bpm == 120.0
        assert engine.snap_to_grid is True
        assert engine.lanes == []
        assert engine.song_structure is None

    def test_block_tracking_empty(self, engine):
        assert len(engine._triggered_blocks) == 0
        assert len(engine._ended_blocks) == 0


class TestSetters:

    def test_set_bpm(self, engine):
        engine.set_bpm(140.0)
        assert engine.bpm == 140.0

    def test_set_snap(self, engine):
        engine.set_snap_to_grid(False)
        assert engine.snap_to_grid is False

    def test_set_song_structure(self, engine, song_structure):
        engine.set_song_structure(song_structure)
        assert engine.song_structure is song_structure

    def test_set_lanes(self, engine):
        lane = LightLane(name="Test", fixture_targets=["G1"])
        engine.set_lanes([lane])
        assert len(engine.lanes) == 1


class TestPlayHaltStop:

    def test_play(self, engine):
        spy = MagicMock()
        engine.playback_started.connect(spy)
        engine.play()
        assert engine.is_playing is True
        spy.assert_called_once()

    def test_play_when_already_playing(self, engine):
        engine.play()
        spy = MagicMock()
        engine.playback_started.connect(spy)
        engine.play()  # Should not emit again
        spy.assert_not_called()

    def test_halt(self, engine):
        engine.play()
        spy = MagicMock()
        engine.playback_halted.connect(spy)
        engine.halt()
        assert engine.is_playing is False
        spy.assert_called_once()

    def test_halt_when_not_playing(self, engine):
        spy = MagicMock()
        engine.playback_halted.connect(spy)
        engine.halt()
        spy.assert_not_called()

    def test_stop_resets_position(self, engine):
        engine.set_position(5.0)
        engine.play()
        spy = MagicMock()
        engine.playback_stopped.connect(spy)
        engine.stop()
        assert engine.is_playing is False
        assert engine.current_position == 0.0
        spy.assert_called_once()

    def test_stop_clears_block_tracking(self, engine):
        engine._triggered_blocks.add(123)
        engine._ended_blocks.add(456)
        engine.stop()
        assert len(engine._triggered_blocks) == 0
        assert len(engine._ended_blocks) == 0


class TestSetPosition:

    def test_set_position(self, engine):
        spy = MagicMock()
        engine.position_changed.connect(spy)
        engine.set_position(10.0)
        assert engine.current_position == 10.0
        spy.assert_called_once_with(10.0)

    def test_negative_clamped(self, engine):
        engine.set_position(-5.0)
        assert engine.current_position == 0.0

    def test_set_position_clears_tracking(self, engine):
        engine._triggered_blocks.add(1)
        engine.set_position(5.0)
        assert len(engine._triggered_blocks) == 0


class TestGetCurrentBpm:

    def test_default_bpm(self, engine):
        assert engine.get_current_bpm() == 120.0

    def test_custom_bpm(self, engine):
        engine.set_bpm(90.0)
        assert engine.get_current_bpm() == 90.0

    def test_from_song_structure(self, engine, song_structure):
        engine.set_song_structure(song_structure)
        engine.set_position(0.0)
        assert engine.get_current_bpm() == 120.0


class TestGetTotalDuration:

    def test_default_duration(self, engine):
        assert engine.get_total_duration() == 300.0  # 5 minutes default

    def test_from_song_structure(self, engine, song_structure):
        engine.set_song_structure(song_structure)
        assert engine.get_total_duration() == song_structure.get_total_duration()


class TestProcessLaneEvents:

    def test_muted_lanes_skipped(self, engine):
        lane = LightLane(name="Muted", fixture_targets=["G1"])
        lane.muted = True
        lane.add_light_block(0, 4, "effect")
        engine.set_lanes([lane])
        engine.set_position(2.0)
        engine.process_lane_events()
        # No blocks should be triggered for muted lanes
        assert len(engine._triggered_blocks) == 0

    def test_solo_mode(self, engine):
        lane1 = LightLane(name="Solo", fixture_targets=["G1"])
        lane1.solo = True
        lane1.add_light_block(0, 4, "e1")

        lane2 = LightLane(name="Normal", fixture_targets=["G2"])
        lane2.add_light_block(0, 4, "e2")

        engine.set_lanes([lane1, lane2])
        engine.set_position(2.0)
        engine.process_lane_events()
        # Only solo lane's blocks should trigger
        assert len(engine._triggered_blocks) == 1