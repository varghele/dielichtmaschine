# tests/unit/test_live_engine.py
"""utils/artnet/live_engine.py - the Live tab's clock-driven playback
engine (docs/live-output-plan.md phase 2).

Pure infrastructure tests against a REAL private DMXManager (mock
fixture definition, no sockets, no Qt): the looping beat clock replays
staged synthetic lanes at the live bpm, a tempo change rescales without
a phase jump or a lane rebuild, pause freezes the exact frame, kill
drops the claims, and the private manager's safe-idle floor is
suppressed (emit_safe_idle=False) so a staged lane claims ONLY what its
blocks drive.

Fixture layout (shared mock def, base address 0): dimmer 0, RGBW 1-4,
pan 5, tilt 6, fines 7-8, gobo 9. Timing used throughout: build bpm
120 (blocks in seconds at 0.5 s/beat), loop 4 beats = 2.0 s of block
time; block A (dimmer 255) covers 0-1 s, block B (dimmer 100) 1-2 s.
"""

import pytest

from config.models import (
    ColourBlock, Configuration, DimmerBlock, Fixture, FixtureMode,
    LightBlock, Universe,
)
from utils.artnet.dmx_manager import DMXManager
from utils.artnet.live_engine import LiveEngine, OnePartStructure, SLOTS

DIMMER, RED, GREEN, BLUE, WHITE, PAN = 0, 1, 2, 3, 4, 5


def _fixture(name="MH1", address=1):
    return Fixture(
        universe=1, address=address, manufacturer="TestMfr",
        model="TestModel", name=name, group="G", current_mode="Standard",
        available_modes=[FixtureMode(name="Standard", channels=10)],
        type="MH",
    )


def _config(fixtures):
    return Configuration(
        fixtures=fixtures, groups={},
        universes={1: Universe(id=1, name="U1", output={})},
    )


def _factory(config, mock_fixture_def):
    """manager_factory the gui will mirror: private manager, safe idle
    suppressed."""
    definitions = {"TestMfr_TestModel": mock_fixture_def}
    return lambda structure: DMXManager(
        config, definitions, structure, emit_safe_idle=False)


def _ab_lane(fixtures):
    """One LightBlock: dimmer A (255) 0-1 s, dimmer B (100) 1-2 s."""
    block = LightBlock(start_time=0.0, end_time=2.0, effect_name="")
    block.dimmer_blocks.append(
        DimmerBlock(start_time=0.0, end_time=1.0, intensity=255.0))
    block.dimmer_blocks.append(
        DimmerBlock(start_time=1.0, end_time=2.0, intensity=100.0))
    return (fixtures, [block])


def _engine(mock_fixture_def, fixtures=None):
    fixtures = fixtures or [_fixture()]
    config = _config(fixtures)
    engine = LiveEngine(_factory(config, mock_fixture_def))
    return engine, fixtures


class TestOnePartStructure:
    def test_constant_bpm_everywhere(self):
        structure = OnePartStructure(97.0)
        assert structure.get_bpm_at_time(0.0) == 97.0
        assert structure.get_bpm_at_time(1234.5) == 97.0


class TestLoopClock:
    def test_staged_lane_loops_at_the_beat_rate(self, qapp,
                                                mock_fixture_def):
        engine, fixtures = _engine(mock_fixture_def)
        engine.set_bpm(120)                 # 0.5 s per beat
        engine.stage("effect", [_ab_lane(fixtures)],
                     loop_beats=4, bpm=120)
        # First render anchors the clock at beat 0 -> block A.
        values, mask = engine.render(10.0)[1]
        assert mask[DIMMER] and values[DIMMER] == 255
        # +1.0 s = 2 beats -> t = 1.0 s -> block B.
        values, _ = engine.render(11.0)[1]
        assert values[DIMMER] == 100
        # +2.0 s = one full 4-beat loop -> back to block A.
        values, _ = engine.render(12.0)[1]
        assert values[DIMMER] == 255
        # Mid-A on the second loop (beat 1 -> t = 0.5 s).
        values, _ = engine.render(12.5)[1]
        assert values[DIMMER] == 255

    def test_bpm_change_rescales_without_restaging(self, qapp,
                                                   mock_fixture_def):
        engine, fixtures = _engine(mock_fixture_def)
        engine.set_bpm(120)
        engine.stage("effect", [_ab_lane(fixtures)],
                     loop_beats=4, bpm=120)
        engine.render(0.0)                  # anchor at beat 0
        engine.set_bpm(240)                 # double time
        # +0.5 s at 240 bpm = 2 beats -> t = 1.0 s -> block B (at the
        # staging tempo this would still be inside block A).
        values, _ = engine.render(0.5)[1]
        assert values[DIMMER] == 100

    def test_claims_are_exactly_the_staged_channels(self, qapp,
                                                    mock_fixture_def):
        engine, fixtures = _engine(mock_fixture_def)
        engine.stage("effect", [_ab_lane(fixtures)],
                     loop_beats=4, bpm=120)
        _, mask = engine.render(0.0)[1]
        assert mask[DIMMER]
        # No safe-idle floor: pan/tilt/colour stay unclaimed so the
        # show underneath keeps them.
        assert mask[PAN] == 0
        assert mask[RED] == 0

    def test_unknown_slot_and_bad_clock_are_rejected(self, qapp,
                                                     mock_fixture_def):
        engine, fixtures = _engine(mock_fixture_def)
        with pytest.raises(ValueError):
            engine.stage("nope", [_ab_lane(fixtures)],
                         loop_beats=4, bpm=120)
        with pytest.raises(ValueError):
            engine.stage("effect", [_ab_lane(fixtures)],
                         loop_beats=0, bpm=120)


class TestPauseAndKill:
    def test_pause_freezes_the_frame_and_the_clock(self, qapp,
                                                   mock_fixture_def):
        engine, fixtures = _engine(mock_fixture_def)
        engine.set_bpm(120)
        engine.stage("effect", [_ab_lane(fixtures)],
                     loop_beats=4, bpm=120)
        engine.render(0.0)
        engine.pause("effect")
        # The frozen frame keeps streaming while time passes...
        frozen = engine.render(1.0)
        assert frozen[1][0][DIMMER] == 255      # still block A
        assert engine.render(50.0) == frozen
        # ...and resuming continues from the paused position, not from
        # the wall clock (the pause did not advance the loop).
        engine.pause("effect", False)
        values, _ = engine.render(100.0)[1]     # re-anchor tick
        assert values[DIMMER] == 255
        values, _ = engine.render(101.0)[1]     # +2 beats -> block B
        assert values[DIMMER] == 100

    def test_kill_drops_the_claims(self, qapp, mock_fixture_def):
        engine, fixtures = _engine(mock_fixture_def)
        engine.stage("effect", [_ab_lane(fixtures)],
                     loop_beats=4, bpm=120)
        assert engine.render(0.0)
        engine.kill("effect")
        assert engine.render(0.1) == {}
        assert not engine.is_active("effect")

    def test_restage_replaces_the_slot(self, qapp, mock_fixture_def):
        engine, fixtures = _engine(mock_fixture_def)
        engine.stage("effect", [_ab_lane(fixtures)],
                     loop_beats=4, bpm=120)
        engine.render(0.7)
        block = LightBlock(start_time=0.0, end_time=2.0, effect_name="")
        block.dimmer_blocks.append(
            DimmerBlock(start_time=0.0, end_time=2.0, intensity=42.0))
        engine.stage("effect", [(fixtures, [block])],
                     loop_beats=4, bpm=120)
        # The new loop starts at beat 0 regardless of the old clock.
        values, _ = engine.render(0.9)[1]
        assert values[DIMMER] == 42


class TestConcurrentSlots:
    def test_effect_and_intensity_slots_merge(self, qapp,
                                              mock_fixture_def):
        engine, fixtures = _engine(mock_fixture_def)
        colour = LightBlock(start_time=0.0, end_time=2.0, effect_name="")
        colour.colour_blocks.append(
            ColourBlock(start_time=0.0, end_time=2.0, red=255.0))
        engine.stage("effect", [(fixtures, [colour])],
                     loop_beats=4, bpm=120)
        engine.stage("intensity", [_ab_lane(fixtures)],
                     loop_beats=4, bpm=120)
        values, mask = engine.render(0.0)[1]
        assert mask[RED] and values[RED] == 255     # effect colour
        assert mask[DIMMER] and values[DIMMER] == 255   # intensity dim
        assert engine.active_slots() == ["effect", "intensity"]

    def test_later_slot_overrides_on_the_same_channel(self, qapp,
                                                      mock_fixture_def):
        engine, fixtures = _engine(mock_fixture_def)
        engine.stage("effect", [_ab_lane(fixtures)],
                     loop_beats=4, bpm=120)            # dimmer 255
        block = LightBlock(start_time=0.0, end_time=2.0, effect_name="")
        block.dimmer_blocks.append(
            DimmerBlock(start_time=0.0, end_time=2.0, intensity=100.0))
        engine.stage("intensity", [(fixtures, [block])],
                     loop_beats=4, bpm=120)
        values, _ = engine.render(0.0)[1]
        # SLOTS order: intensity overrides effect on the shared channel.
        assert values[DIMMER] == 100
        engine.kill("intensity")
        values, _ = engine.render(0.1)[1]
        assert values[DIMMER] == 255


class TestSafeIdleFlag:
    def test_private_manager_claims_nothing_when_idle(
            self, qapp, mock_fixture_def):
        config = _config([_fixture()])
        manager = _factory(config, mock_fixture_def)(
            OnePartStructure(120))
        manager.update_dmx(0.0)
        _, mask = manager.get_frame(1)
        assert not any(mask)

    def test_playback_default_still_claims_the_idle_floor(
            self, qapp, mock_fixture_def):
        config = _config([_fixture()])
        manager = DMXManager(config,
                             {"TestMfr_TestModel": mock_fixture_def})
        manager.update_dmx(0.0)
        _, mask = manager.get_frame(1)
        # Playback behaviour unchanged: pan/tilt centred and claimed.
        assert mask[PAN]

    def test_slots_constant_is_the_documented_trio(self):
        assert SLOTS == ("effect", "intensity", "movement")
