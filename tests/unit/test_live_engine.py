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
    ColourBlock, Configuration, DimmerBlock, Fixture, FixtureGroup,
    FixtureMode, LightBlock, Riff, RiffDimmerBlock, Universe,
)
from utils.artnet.dmx_manager import DMXManager
from utils.artnet.live_engine import (
    LiveEngine, LiveGroupEffectsBinder, OnePartStructure, SLOTS,
)

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
    """manager_factory the gui mirrors: private manager, safe idle
    suppressed, movement's spot-overlay config honoured."""
    definitions = {"TestMfr_TestModel": mock_fixture_def}
    return lambda structure, config_override=None: DMXManager(
        config_override if config_override is not None else config,
        definitions, structure, emit_safe_idle=False)


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
            engine.stage("nope:Left", [_ab_lane(fixtures)],
                         loop_beats=4, bpm=120)
        with pytest.raises(ValueError):
            engine.stage("effect", [_ab_lane(fixtures)],
                         loop_beats=0, bpm=120)
        # Namespaced slots of a known category are valid (per-group
        # effects, 2026-07-22).
        engine.stage("effect:Left", [_ab_lane(fixtures)],
                     loop_beats=4, bpm=120)
        assert engine.is_active("effect:Left")


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


class TestGroupSlots:
    """The dynamic slot namespace (per-group effects, 2026-07-22):
    "category:suffix" slots with independent loop lengths, clocks and
    pause flags, deterministic merge order, kill_prefix, phase_from."""

    def _two_group_engine(self, mock_fixture_def):
        left = _fixture("MH1", 1)
        right = _fixture("MH2", 11)
        config = _config([left, right])
        engine = LiveEngine(_factory(config, mock_fixture_def))
        return engine, [left], [right]

    def _flat_lane(self, fixtures, intensity, seconds):
        block = LightBlock(start_time=0.0, end_time=seconds,
                           effect_name="")
        block.dimmer_blocks.append(DimmerBlock(
            start_time=0.0, end_time=seconds, intensity=intensity))
        return (fixtures, [block])

    def test_different_loop_lengths_coexist(self, qapp,
                                            mock_fixture_def):
        engine, left, right = self._two_group_engine(mock_fixture_def)
        engine.set_bpm(120)
        engine.stage("effect:A", [_ab_lane(left)],
                     loop_beats=4, bpm=120)          # 255/100 halves
        block = LightBlock(start_time=0.0, end_time=4.0, effect_name="")
        block.dimmer_blocks.append(DimmerBlock(
            start_time=0.0, end_time=2.0, intensity=200.0))
        block.dimmer_blocks.append(DimmerBlock(
            start_time=2.0, end_time=4.0, intensity=50.0))
        engine.stage("effect:B", [(right, [block])],
                     loop_beats=8, bpm=120)          # 8-beat loop
        engine.render(0.0)
        # +2.0 s: the 4-beat loop wrapped (255 again); the 8-beat loop
        # is at beat 4 -> its second half (50).
        values, _ = engine.render(2.0)[1]
        assert values[DIMMER] == 255
        assert values[10 + DIMMER] == 50

    def test_merge_order_is_category_then_name(self, qapp,
                                               mock_fixture_def):
        engine, left, _right = self._two_group_engine(mock_fixture_def)
        # Two group slots on the SAME fixture channel: sorted suffix
        # wins within the category; bare intensity beats both.
        engine.stage("effect:A", [self._flat_lane(left, 10.0, 2.0)],
                     loop_beats=4, bpm=120)
        engine.stage("effect:B", [self._flat_lane(left, 20.0, 2.0)],
                     loop_beats=4, bpm=120)
        values, _ = engine.render(0.0)[1]
        assert values[DIMMER] == 20                 # B after A
        engine.stage("intensity", [self._flat_lane(left, 30.0, 2.0)],
                     loop_beats=4, bpm=120)
        values, _ = engine.render(0.1)[1]
        assert values[DIMMER] == 30                 # category order
        assert engine.active_slots() == ["effect:A", "effect:B",
                                         "intensity"]

    def test_pause_freezes_one_group_slot_only(self, qapp,
                                               mock_fixture_def):
        engine, left, right = self._two_group_engine(mock_fixture_def)
        engine.set_bpm(120)
        engine.stage("effect:A", [_ab_lane(left)], loop_beats=4, bpm=120)
        engine.stage("effect:B", [_ab_lane(right)], loop_beats=4,
                     bpm=120)
        engine.render(0.0)
        engine.pause("effect:A")
        values, _ = engine.render(1.0)[1]           # +2 beats
        assert values[DIMMER] == 255                # A frozen at beat 0
        assert values[10 + DIMMER] == 100           # B moved on

    def test_kill_prefix_drops_the_family_only(self, qapp,
                                               mock_fixture_def):
        engine, left, right = self._two_group_engine(mock_fixture_def)
        engine.stage("effect:A", [_ab_lane(left)], loop_beats=4, bpm=120)
        engine.stage("effect:B", [_ab_lane(right)], loop_beats=4,
                     bpm=120)
        engine.stage("intensity", [self._flat_lane(left, 30.0, 2.0)],
                     loop_beats=4, bpm=120)
        engine.kill_prefix("effect")
        assert engine.active_slots() == ["intensity"]

    def test_phase_from_adopts_the_donor_clock(self, qapp,
                                               mock_fixture_def):
        engine, left, right = self._two_group_engine(mock_fixture_def)
        engine.set_bpm(120)
        engine.stage("effect:A", [_ab_lane(left)], loop_beats=4, bpm=120)
        engine.render(0.0)
        engine.render(1.2)                          # A at beat 2.4 -> 100
        engine.stage("effect:B", [_ab_lane(right)], loop_beats=4,
                     bpm=120, phase_from="effect:A")
        values, _ = engine.render(1.3)[1]
        assert values[DIMMER] == 100                # A undisturbed
        assert values[10 + DIMMER] == 100           # B joined in phase


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


def _riff():
    """Pulse: dimmer 255 for beats 0-2, dimmer 100 for beats 2-4. At
    build bpm 120 that is seconds 0-1 and 1-2 - the same A/B timing as
    _ab_lane."""
    riff = Riff(name="Pulse", category="basics", length_beats=4.0)
    riff.dimmer_blocks.append(
        RiffDimmerBlock(start_beat=0.0, end_beat=2.0, intensity=255.0))
    riff.dimmer_blocks.append(
        RiffDimmerBlock(start_beat=2.0, end_beat=4.0, intensity=100.0))
    return riff


def _second_riff():
    """Wave: an 8-beat dimmer riff (200 / 50 halves) - a DIFFERENT
    loop length than _riff's 4 beats, for coexistence tests."""
    riff = Riff(name="Wave", category="basics", length_beats=8.0)
    riff.dimmer_blocks.append(
        RiffDimmerBlock(start_beat=0.0, end_beat=4.0, intensity=200.0))
    riff.dimmer_blocks.append(
        RiffDimmerBlock(start_beat=4.0, end_beat=8.0, intensity=50.0))
    return riff


class TestEffectsBinder:
    """LiveGroupEffectsBinder: LiveState's PER-GROUP effects drive one
    engine slot per group ("effect:<group>") - different riffs on
    different groups simultaneously, selection scopes STAGING only.
    Exercised through the REAL LiveState mutators (stage_effect,
    set_selection, toggle_pause, kill_playback, fire_next)."""

    def _bound(self, mock_fixture_def):
        from gui.tabs.live_tab import LiveState
        from utils.artnet.live_engine import LiveGroupEffectsBinder
        mh1 = _fixture("MH1", 1)
        mh2 = _fixture("MH2", 11)
        config = Configuration(
            fixtures=[mh1, mh2],
            groups={"Left": FixtureGroup(name="Left", fixtures=[mh1]),
                    "Right": FixtureGroup(name="Right", fixtures=[mh2])},
            universes={1: Universe(id=1, name="U1", output={})},
        )
        engine = LiveEngine(_factory(config, mock_fixture_def))
        state = LiveState()
        state.update_from_config(config.groups.keys())
        riffs = {"basics/Pulse": _riff(), "basics/Wave": _second_riff()}
        binder = LiveGroupEffectsBinder(
            state, engine,
            config_provider=lambda: config,
            riff_provider=riffs.get,
        )
        state.state_changed.connect(binder.sync)
        # The signal holds bound methods weakly: the caller must keep
        # the binder referenced or it silently stops syncing (gui.py
        # stores it as a window attribute for the same reason).
        return state, engine, binder

    def test_fired_effect_plays_on_the_selected_group(
            self, qapp, mock_fixture_def):
        state, engine, _binder = self._bound(mock_fixture_def)
        state.set_selection(["Left"])
        state.stage_effect("basics/Pulse")
        values, mask = engine.render(0.0)[1]
        assert mask[DIMMER] and values[DIMMER] == 255   # MH1, beat 0
        assert mask[10 + DIMMER] == 0                   # Right silent
        # +1.0 s at the default 120 bpm = 2 beats -> the 100 half.
        values, _ = engine.render(1.0)[1]
        assert values[DIMMER] == 100
        # Full 4-beat loop -> back to 255.
        values, _ = engine.render(2.0)[1]
        assert values[DIMMER] == 255

    def test_groups_run_different_riffs_simultaneously(
            self, qapp, mock_fixture_def):
        """The headline scenario: stage on drums, reselect, stage
        another on movers - both run, the first undisturbed."""
        state, engine, _binder = self._bound(mock_fixture_def)
        state.set_selection(["Left"])
        state.stage_effect("basics/Pulse")
        engine.render(0.0)
        engine.render(0.7)                  # Left mid-loop (beat 1.4)
        state.set_selection(["Right"])      # deselect Left: keeps running
        state.stage_effect("basics/Wave")
        values, mask = engine.render(0.8)[1]
        assert mask[DIMMER] and mask[10 + DIMMER]
        assert values[DIMMER] == 255        # Pulse, still first half
        assert values[10 + DIMMER] == 200   # Wave, fresh loop
        # Left was NOT restarted: +0.5 s from 0.8 = 1.3 s total = 2.6
        # beats -> Pulse's 100 half; a restart at 0.8 would still be
        # in the 255 half at 1.3.
        values, _ = engine.render(1.3)[1]
        assert values[DIMMER] == 100

    def test_join_adopts_the_running_phase(self, qapp,
                                           mock_fixture_def):
        """A group joining a running riff starts IN PHASE with it
        (phase_from) instead of at beat 0 - and the running group's
        clock is undisturbed."""
        state, engine, _binder = self._bound(mock_fixture_def)
        state.set_selection(["Left"])
        state.stage_effect("basics/Pulse")
        engine.render(0.0)
        engine.render(1.2)                  # Left at beat 2.4 -> 100 half
        state.set_selection(["Left", "Right"])
        state.stage_effect("basics/Pulse")  # Right joins (Left keeps key)
        values, mask = engine.render(1.3)[1]
        assert mask[DIMMER] and mask[10 + DIMMER]
        assert values[DIMMER] == 100        # Left undisturbed, 100 half
        assert values[10 + DIMMER] == 100   # Right joined IN PHASE

    def test_second_touch_releases_the_selected_groups(
            self, qapp, mock_fixture_def):
        state, engine, _binder = self._bound(mock_fixture_def)
        state.set_selection(["Left"])
        state.stage_effect("basics/Pulse")
        assert engine.render(0.0)
        state.stage_effect("basics/Pulse")              # toggle off
        assert engine.render(0.1) == {}
        assert not engine.is_active("effect:Left")

    def test_no_selection_touch_is_a_no_op(self, qapp,
                                           mock_fixture_def):
        """The positions pattern: staging with nothing selected does
        NOT latch a pending effect - silence until a group is selected
        AND the effect is touched."""
        state, engine, _binder = self._bound(mock_fixture_def)
        state.stage_effect("basics/Pulse")              # nothing selected
        assert state.effects == {}
        assert engine.render(0.0) == {}
        state.set_selection(["Right"])                  # still silent
        assert engine.render(0.1) == {}
        state.stage_effect("basics/Pulse")              # now it starts
        values, mask = engine.render(0.2)[1]
        assert mask[10 + DIMMER] and values[10 + DIMMER] == 255

    def test_deselection_keeps_the_effect_running(self, qapp,
                                                  mock_fixture_def):
        """Selection scopes staging, never playback."""
        state, engine, _binder = self._bound(mock_fixture_def)
        state.set_selection(["Left"])
        state.stage_effect("basics/Pulse")
        assert engine.render(0.0)
        state.set_selection([])                         # clear selection
        values, mask = engine.render(0.1)[1]
        assert mask[DIMMER] and values[DIMMER] == 255   # still running

    def test_pause_row_freezes_and_resumes_the_riff(self, qapp,
                                                    mock_fixture_def):
        state, engine, _binder = self._bound(mock_fixture_def)
        state.set_selection(["Left"])
        state.stage_effect("basics/Pulse")
        engine.render(0.0)
        index = next(i for i, r in enumerate(state.running)
                     if r["kind"] == "effect")
        state.toggle_pause(index)
        frozen = engine.render(5.0)
        assert frozen[1][0][DIMMER] == 255              # held at beat 0
        assert engine.render(60.0) == frozen
        state.toggle_pause(index)                       # resume
        engine.render(100.0)                            # re-anchor
        values, _ = engine.render(101.0)[1]             # +2 beats
        assert values[DIMMER] == 100

    def test_record_pause_freezes_all_its_groups_only(
            self, qapp, mock_fixture_def):
        """Pulse on Left+Right (one record), Wave would be elsewhere -
        pausing the record freezes BOTH its group slots; other slots
        keep looping."""
        state, engine, _binder = self._bound(mock_fixture_def)
        state.set_selection(["Left", "Right"])
        state.stage_effect("basics/Pulse")
        engine.render(0.0)
        index = next(i for i, r in enumerate(state.running)
                     if r["kind"] == "effect")
        state.toggle_pause(index)
        values, _ = engine.render(5.0)[1]
        assert values[DIMMER] == 255                    # both frozen
        assert values[10 + DIMMER] == 255

    def test_kill_row_clears_the_output(self, qapp, mock_fixture_def):
        state, engine, _binder = self._bound(mock_fixture_def)
        state.set_selection(["Left"])
        state.stage_effect("basics/Pulse")
        assert engine.render(0.0)
        index = next(i for i, r in enumerate(state.running)
                     if r["kind"] == "effect")
        state.kill_playback(index)
        assert "Left" not in state.effects
        assert engine.render(0.1) == {}

    def test_kill_one_record_spares_the_other_riff(
            self, qapp, mock_fixture_def):
        state, engine, _binder = self._bound(mock_fixture_def)
        state.set_selection(["Left"])
        state.stage_effect("basics/Pulse")
        state.set_selection(["Right"])
        state.stage_effect("basics/Wave")
        index = next(i for i, r in enumerate(state.running)
                     if r["kind"] == "effect"
                     and r["key"] == "basics/Pulse")
        state.kill_playback(index)
        values, mask = engine.render(0.0)[1]
        assert mask[DIMMER] == 0                        # Pulse gone
        assert mask[10 + DIMMER]                        # Wave survives
        assert values[10 + DIMMER] == 200
        assert state.effects == {"Right": "basics/Wave"}

    def test_go_promotes_the_queue_head(self, qapp, mock_fixture_def):
        state, engine, _binder = self._bound(mock_fixture_def)
        state.set_selection(["Left"])
        state.enqueue("effect", "basics/Pulse", "Pulse")
        assert engine.render(0.0) == {}                 # queued, not live
        state.fire_next()                               # GO
        values, mask = engine.render(0.1)[1]
        assert mask[DIMMER] and values[DIMMER] == 255

    def test_tap_tempo_follows_without_restaging(self, qapp,
                                                 mock_fixture_def):
        state, engine, _binder = self._bound(mock_fixture_def)
        state.set_selection(["Left"])
        state.stage_effect("basics/Pulse")
        engine.render(0.0)                              # anchor, beat 0
        state.set_bpm(240)                              # TAP doubles it
        values, _ = engine.render(0.5)[1]               # 2 beats now
        assert values[DIMMER] == 100

    def test_unknown_riff_key_silences_only_its_group(
            self, qapp, mock_fixture_def):
        state, engine, _binder = self._bound(mock_fixture_def)
        state.set_selection(["Left"])
        state.stage_effect("basics/Pulse")
        state.set_selection(["Right"])
        state.stage_effect("basics/Ghost")              # unknown key
        values, mask = engine.render(0.0)[1]
        assert mask[DIMMER] and values[DIMMER] == 255   # Left plays
        assert mask[10 + DIMMER] == 0                   # Right silent
        assert engine.is_active("effect:Left")
        assert not engine.is_active("effect:Right")

    def test_release_all_kills_every_group_slot(self, qapp,
                                                mock_fixture_def):
        state, engine, _binder = self._bound(mock_fixture_def)
        state.set_selection(["Left"])
        state.stage_effect("basics/Pulse")
        state.set_selection(["Right"])
        state.stage_effect("basics/Wave")
        assert engine.render(0.0)
        state.release_all()
        assert engine.render(0.1) == {}
        assert state.effects == {}


class TestIntensityBinder:
    """The per-group binder on the "intensity" slot family
    (2026-07-22): each group's dimmer riff runs CONCURRENTLY with its
    colour riff, and intensity slots override effect slots on shared
    channels (category order)."""

    def _bound(self, mock_fixture_def):
        from config.models import RiffColourBlock
        from gui.tabs.live_tab import LiveState
        from utils.artnet.live_engine import LiveGroupEffectsBinder
        mh1 = _fixture("MH1", 1)
        config = Configuration(
            fixtures=[mh1],
            groups={"Left": FixtureGroup(name="Left", fixtures=[mh1])},
            universes={1: Universe(id=1, name="U1", output={})},
        )
        engine = LiveEngine(_factory(config, mock_fixture_def))
        state = LiveState()
        state.update_from_config(["Left"])
        colour_riff = Riff(name="RedWash", category="looks",
                           length_beats=4.0)
        colour_riff.colour_blocks.append(
            RiffColourBlock(start_beat=0.0, end_beat=4.0, red=255.0))
        dim_riff = _riff()      # dimmer 255 / 100 halves
        riffs = {"looks/RedWash": colour_riff,
                 "intensity/Pulse": dim_riff}
        effects = LiveGroupEffectsBinder(
            state, engine, config_provider=lambda: config,
            riff_provider=riffs.get)
        intensity = LiveGroupEffectsBinder(
            state, engine, config_provider=lambda: config,
            riff_provider=riffs.get,
            category="intensity", state_attr="intensities",
            record_kind="intensity")
        state.state_changed.connect(effects.sync)
        state.state_changed.connect(intensity.sync)
        return state, engine, (effects, intensity)

    def test_dimmer_riff_runs_under_the_colour_riff(
            self, qapp, mock_fixture_def):
        state, engine, _binders = self._bound(mock_fixture_def)
        state.set_selection(["Left"])
        state.stage_effect("looks/RedWash")
        state.stage_intensity("intensity/Pulse")
        values, mask = engine.render(0.0)[1]
        assert values[RED] == 255                # effect slot colour
        assert mask[DIMMER] and values[DIMMER] == 255   # intensity dim
        assert engine.active_slots() == ["effect:Left",
                                         "intensity:Left"]
        # The intensity riff keeps looping on its own clock.
        values, _ = engine.render(1.0)[1]
        assert values[DIMMER] == 100
        assert values[RED] == 255

    def test_kill_and_pause_address_their_own_slot(
            self, qapp, mock_fixture_def):
        state, engine, _binders = self._bound(mock_fixture_def)
        state.set_selection(["Left"])
        state.stage_effect("looks/RedWash")
        state.stage_intensity("intensity/Pulse")
        engine.render(0.0)
        index = next(i for i, r in enumerate(state.running)
                     if r["kind"] == "intensity")
        state.kill_playback(index)
        values, mask = engine.render(0.1)[1]
        assert mask[DIMMER] == 0                 # dimmer released
        assert values[RED] == 255                # colour still runs
        assert engine.active_slots() == ["effect:Left"]


class TestDimmerConjunction:
    """The bench finding after phase 5: a held swatch pinned the
    dimmer flat over the running intensity pattern, and a pattern
    with no busk claim pumped against a closed shutter (the LIVE
    blackout floor claims nothing). The busk layer now yields its
    static dimmer to engine dimmer groups (FLASH still forces full)
    and opens their shutters."""

    SHUTTER = 10   # extra channel appended to the shared mock def

    def _shutter_def(self, mock_fixture_def):
        import copy
        definition = copy.deepcopy(mock_fixture_def)
        definition["channels"].append(
            {"name": "Shutter", "preset": "ShutterStrobeOpen",
             "group": "Shutter", "capabilities": []})
        definition["modes"][0]["channels"].append(
            {"number": self.SHUTTER, "name": "Shutter"})
        return definition

    def _stack(self, mock_fixture_def):
        from config.models import RiffColourBlock
        from gui.tabs.live_tab import COLOUR_SWATCHES, LiveState
        from utils.artnet.dmx_manager import FixtureChannelMap
        from utils.artnet.live_layer import LiveBuskLayer
        definition = self._shutter_def(mock_fixture_def)
        mh1 = _fixture("MH1", 1)
        config = Configuration(
            fixtures=[mh1],
            groups={"Left": FixtureGroup(name="Left", fixtures=[mh1])},
            universes={1: Universe(id=1, name="U1", output={})},
        )
        engine = LiveEngine(_factory(config, definition))
        state = LiveState()
        state.update_from_config(["Left"])
        colour_riff = Riff(name="RedWash", category="looks",
                           length_beats=4.0)
        colour_riff.colour_blocks.append(
            RiffColourBlock(start_beat=0.0, end_beat=4.0, red=255.0))
        riffs = {"intensity/Pulse": _riff(),
                 "looks/RedWash": colour_riff}
        from utils.artnet.live_engine import LiveGroupEffectsBinder
        effects = LiveGroupEffectsBinder(
            state, engine, config_provider=lambda: config,
            riff_provider=riffs.get)
        intensity = LiveGroupEffectsBinder(
            state, engine, config_provider=lambda: config,
            riff_provider=riffs.get,
            category="intensity", state_attr="intensities",
            record_kind="intensity")
        state.state_changed.connect(effects.sync)
        state.state_changed.connect(intensity.sync)
        layer = LiveBuskLayer(
            state, config_provider=lambda: config,
            swatches=COLOUR_SWATCHES, engine=engine,
            dimmer_groups_provider=lambda: (effects.dimmer_groups()
                                            | intensity.dimmer_groups()))
        layer.set_fixture_maps(
            {"MH1": FixtureChannelMap(mh1, definition, config)})
        return state, layer, (effects, intensity)

    def test_swatch_dimmer_yields_to_the_intensity_pattern(
            self, qapp, mock_fixture_def):
        state, layer, _binders = self._stack(mock_fixture_def)
        state.set_selection(["Left"])
        state.stage_colour("red")
        state.stage_intensity("intensity/Pulse")
        values, mask = layer.render(0.0)[1]
        assert values[RED] == 0xFF               # the swatch colour holds
        assert mask[self.SHUTTER] and values[self.SHUTTER] == 255
        # +1.0 s = pattern half B: the dimmer MOVES with the pattern
        # instead of sitting pinned at the swatch's static 255.
        values, _ = layer.render(1.0)[1]
        assert values[DIMMER] == 100
        assert values[RED] == 0xFF

    def test_flash_still_forces_full(self, qapp, mock_fixture_def):
        state, layer, _binders = self._stack(mock_fixture_def)
        state.set_selection(["Left"])
        state.stage_intensity("intensity/Pulse")
        state.set_flash("Left", True)
        layer.render(0.0)
        values, _ = layer.render(1.0)[1]          # pattern half B...
        assert values[DIMMER] == 255              # ...but FLASH wins

    def test_pattern_alone_gets_an_open_shutter(self, qapp,
                                                mock_fixture_def):
        state, layer, _binders = self._stack(mock_fixture_def)
        state.set_selection(["Left"])
        state.stage_intensity("intensity/Pulse")    # no busk claim at all
        values, mask = layer.render(0.0)[1]
        assert mask[DIMMER] and values[DIMMER] == 255
        assert mask[self.SHUTTER] and values[self.SHUTTER] == 255

    def test_colour_only_riff_keeps_the_busk_dimmer(
            self, qapp, mock_fixture_def):
        state, layer, _binders = self._stack(mock_fixture_def)
        state.set_selection(["Left"])
        state.stage_colour("red")
        state.stage_effect("looks/RedWash")       # NO dimmer sublanes
        values, mask = layer.render(1.0)[1]
        # dimmer_groups is empty: the swatch's static dimmer applies.
        assert mask[DIMMER] and values[DIMMER] == 255


class TestEngineUnderBuskLayer:
    """The busk layer composes the engine frame BELOW its explicit
    writes (a touched swatch beats the running riff on that group)."""

    def _layered(self, mock_fixture_def):
        from gui.tabs.live_tab import COLOUR_SWATCHES, LiveState
        from utils.artnet.dmx_manager import FixtureChannelMap
        from utils.artnet.live_layer import LiveBuskLayer
        mh1 = _fixture("MH1", 1)
        config = Configuration(
            fixtures=[mh1],
            groups={"Left": FixtureGroup(name="Left", fixtures=[mh1])},
            universes={1: Universe(id=1, name="U1", output={})},
        )
        engine = LiveEngine(_factory(config, mock_fixture_def))
        state = LiveState()
        state.update_from_config(["Left"])
        layer = LiveBuskLayer(state, config_provider=lambda: config,
                              swatches=COLOUR_SWATCHES, engine=engine)
        layer.set_fixture_maps(
            {"MH1": FixtureChannelMap(mh1, mock_fixture_def, config)})
        return state, engine, layer, [mh1]

    def test_engine_frame_passes_through_an_idle_programmer(
            self, qapp, mock_fixture_def):
        state, engine, layer, fixtures = self._layered(mock_fixture_def)
        engine.stage("effect", [_ab_lane(fixtures)],
                     loop_beats=4, bpm=120)
        values, mask = layer.render(0.0)[1]
        assert mask[DIMMER] and values[DIMMER] == 255

    def test_busk_write_overlays_the_engine_frame(self, qapp,
                                                  mock_fixture_def):
        state, engine, layer, fixtures = self._layered(mock_fixture_def)
        colour = LightBlock(start_time=0.0, end_time=2.0, effect_name="")
        colour.colour_blocks.append(
            ColourBlock(start_time=0.0, end_time=2.0, red=255.0))
        engine.stage("effect", [(fixtures, [colour])],
                     loop_beats=4, bpm=120)
        state.selected = {"Left"}
        state.stage_colour("cyan")                      # 4ECBD4
        values, mask = layer.render(0.0)[1]
        # The riff claimed RED=255; the swatch claim wins on top.
        assert values[RED] == 0x4E
        assert values[GREEN] == 0xCB
        assert mask[DIMMER] and values[DIMMER] == 255   # busk dimmer

    def test_no_engine_stays_the_old_contract(self, qapp,
                                              mock_fixture_def):
        from gui.tabs.live_tab import COLOUR_SWATCHES, LiveState
        from utils.artnet.dmx_manager import FixtureChannelMap
        from utils.artnet.live_layer import LiveBuskLayer
        mh1 = _fixture("MH1", 1)
        config = Configuration(
            fixtures=[mh1],
            groups={"Left": FixtureGroup(name="Left", fixtures=[mh1])},
            universes={1: Universe(id=1, name="U1", output={})},
        )
        state = LiveState()
        state.update_from_config(["Left"])
        layer = LiveBuskLayer(state, config_provider=lambda: config,
                              swatches=COLOUR_SWATCHES)
        layer.set_fixture_maps(
            {"MH1": FixtureChannelMap(mh1, mock_fixture_def, config)})
        assert layer.render(0.0) == {}


class TestMovementBinder:
    """LiveMovementBinder: MOVEMENT SHAPES trace the registry rudiment
    around the held-position anchor through the real solver path
    (docs/live-output-plan.md phase 4). The oracle rebuilds the same
    MovementContext the playback resolve builds and compares DMX."""

    TILT, PAN_FINE = 6, 7

    def _bound(self, mock_fixture_def, spots=None):
        from config.models import Spot
        from gui.tabs.live_tab import LiveState
        from utils.artnet.live_engine import LiveMovementBinder
        mover = _fixture("MH1", 1)
        par = _fixture("PAR1", 11)
        par.type = "PAR"
        config = Configuration(
            fixtures=[mover, par],
            groups={"Movers": FixtureGroup(name="Movers",
                                           fixtures=[mover]),
                    "Pars": FixtureGroup(name="Pars", fixtures=[par])},
            universes={1: Universe(id=1, name="U1", output={})},
        )
        if spots:
            config.spots = {name: Spot(name=name, x=x, y=y, z=z)
                            for name, (x, y, z) in spots.items()}
        engine = LiveEngine(_factory(config, mock_fixture_def))
        state = LiveState()
        state.update_from_config(config.groups.keys(),
                                 spot_names=list(spots or ()))
        binder = LiveMovementBinder(
            state, engine, config_provider=lambda: config)
        state.state_changed.connect(binder.sync)
        return state, engine, binder, config

    @staticmethod
    def _expected(shape, fixture, anchor, beat_pos, radius=0.75):
        """The DMX pan/tilt the WORLD-PLANE movement path produces for
        a shape orbiting ``anchor`` (radius in meters, horizontal
        plane) at loop position ``beat_pos`` (build bpm 120, 16-beat
        loop = exactly one shape cycle). Mirrors
        dmx_manager._apply_movement_block's plane branch."""
        import math
        from effects import MOVEMENT_REGISTRY, MovementContext
        from utils.orientation import calculate_pan_tilt, pan_tilt_to_dmx
        progress = beat_pos / 16.0
        ctx = MovementContext(
            t=2 * math.pi * 1.0 * progress, progress=progress,
            total_cycles=1.0,
            center_pan=127.5, center_tilt=127.5,
            pan_amplitude=50.0, tilt_amplitude=50.0,
            fixture_index=0, total_fixtures=1,
            phase_offset_enabled=False, phase_offset_degrees=0.0,
            lissajous_ratio="1:2",
        )
        result = MOVEMENT_REGISTRY[shape](ctx)
        u_off = (result.pan - 127.5) / 50.0
        v_off = (result.tilt - 127.5) / 50.0
        target = (anchor[0] + u_off * radius,
                  anchor[1] + v_off * radius,
                  anchor[2])
        mounting, yaw, pitch, roll = \
            fixture.get_effective_orientation(None)
        pan_deg, tilt_deg = calculate_pan_tilt(
            fixture_x=fixture.x, fixture_y=fixture.y,
            fixture_z=fixture.get_effective_z(None),
            target_x=target[0], target_y=target[1], target_z=target[2],
            mounting=mounting, yaw=yaw, pitch=pitch, roll=roll,
            pan_range=540.0, tilt_range=270.0,
        )
        pan_dmx, tilt_dmx = pan_tilt_to_dmx(
            pan_deg, tilt_deg, 540.0, 270.0)
        return (int(max(0.0, min(255.0, float(pan_dmx)))),
                int(max(0.0, min(255.0, float(tilt_dmx)))))

    def test_circle_traces_around_the_centre_anchor(
            self, qapp, mock_fixture_def):
        from utils.position_presets import (
            compute_presets, resolve_position_target,
        )
        state, engine, binder, config = self._bound(mock_fixture_def)
        state.set_selection(["Movers"])
        state.stage_shape("circle")
        presets = {p.preset_id: p for p in compute_presets(config)}
        target = resolve_position_target(
            config, presets, "preset:centre", config.fixtures[0])
        # Beat 0, then a quarter cycle later (4 beats = 2.0 s at 120).
        values, mask = engine.render(0.0)[1]
        assert mask[PAN] and mask[self.TILT]
        expected = self._expected("circle", config.fixtures[0],
                                  target, 0.0)
        assert (values[PAN], values[self.TILT]) == expected
        values, _ = engine.render(2.0)[1]
        quarter = self._expected("circle", config.fixtures[0],
                                 target, 4.0)
        assert (values[PAN], values[self.TILT]) == quarter
        assert quarter != expected                      # it moved

    def test_anchor_follows_the_held_position(self, qapp,
                                              mock_fixture_def):
        spots = {"Riser": (1.0, 1.5, 0.6)}
        state, engine, binder, config = self._bound(mock_fixture_def,
                                                    spots=spots)
        state.set_selection(["Movers"])
        state.stage_position("mark:Riser", "Riser")
        state.stage_shape("circle")
        values, _ = engine.render(0.0)[1]
        expected = self._expected("circle", config.fixtures[0],
                                  (1.0, 1.5, 0.6), 0.0)
        assert (values[PAN], values[self.TILT]) == expected
        assert binder.active_groups() == frozenset({"Movers"})

    def test_release_and_non_mover_scope_stay_silent(
            self, qapp, mock_fixture_def):
        state, engine, binder, config = self._bound(mock_fixture_def)
        state.set_selection(["Movers"])
        state.stage_shape("circle")
        assert engine.render(0.0)
        state.stage_shape("circle")             # release
        assert engine.render(0.1) == {}
        assert binder.active_groups() == frozenset()
        state.set_selection(["Pars"])           # no movers in scope
        state.stage_shape("circle")
        assert engine.render(0.2) == {}

    def test_shape_claims_pan_tilt_only(self, qapp, mock_fixture_def):
        state, engine, binder, config = self._bound(mock_fixture_def)
        state.set_selection(["Movers"])
        state.stage_shape("bounce")
        _, mask = engine.render(0.0)[1]
        assert mask[PAN] and mask[self.TILT]
        assert mask[DIMMER] == 0                # shapes can run dark
        assert mask[RED] == 0

    def test_transient_anchors_never_touch_the_real_config(
            self, qapp, mock_fixture_def):
        state, engine, binder, config = self._bound(mock_fixture_def)
        state.set_selection(["Movers"])
        state.stage_shape("circle")
        engine.render(0.0)
        assert not getattr(config, "spots", None), \
            "anchors must not leak into the saved config"
        assert not getattr(config, "live_shape_planes", None)

    def test_stagger_fans_the_heads_around_the_loop(
            self, qapp, mock_fixture_def):
        from gui.tabs.live_tab import LiveState
        from utils.artnet.live_engine import LiveMovementBinder
        mh1 = _fixture("MH1", 1)          # x = 0.0 (default)
        mh2 = _fixture("MH2", 11)
        mh1.x, mh2.x = -1.0, 1.0
        config = Configuration(
            fixtures=[mh1, mh2],
            groups={"Movers": FixtureGroup(name="Movers",
                                           fixtures=[mh1, mh2])},
            universes={1: Universe(id=1, name="U1", output={})},
        )
        engine = LiveEngine(_factory(config, mock_fixture_def))
        state = LiveState()
        state.update_from_config(["Movers"])
        binder = LiveMovementBinder(state, engine,
                                    config_provider=lambda: config)
        state.state_changed.connect(binder.sync)
        state.set_selection(["Movers"])
        state.stage_shape("circle")
        # Unison (stagger 0): both heads trace the same phase.
        values, _ = engine.render(0.0)[1]
        at_zero_1 = self._expected("circle", mh1, (0.0, 0.0, 1.5), 0.0)
        at_zero_2 = self._expected("circle", mh2, (0.0, 0.0, 1.5), 0.0)
        assert (values[PAN], values[6]) == at_zero_1
        assert (values[10 + PAN], values[10 + 6]) == at_zero_2
        # Full stagger: head 2 of 2 leads by HALF the 16-beat loop.
        state.set_shape_stagger(100)
        values, _ = engine.render(0.1)[1]     # restaged, fresh beat 0
        assert (values[PAN], values[6]) == at_zero_1
        half_lap_2 = self._expected("circle", mh2, (0.0, 0.0, 1.5), 8.0)
        assert (values[10 + PAN], values[10 + 6]) == half_lap_2
        assert half_lap_2 != at_zero_2

    def test_orbit_radius_follows_the_size_chips(self, qapp,
                                                 mock_fixture_def):
        # The SIZE control is physical: changing it restages the shape
        # at the new radius in meters.
        state, engine, binder, config = self._bound(mock_fixture_def)
        state.set_selection(["Movers"])
        state.stage_shape("circle")
        engine.render(0.0)
        state.set_shape_size(1.5)             # the L chip
        values, _ = engine.render(0.1)[1]
        large = self._expected("circle", config.fixtures[0],
                               (0.0, 0.0, 1.5), 0.0, radius=1.5)
        small = self._expected("circle", config.fixtures[0],
                               (0.0, 0.0, 1.5), 0.0, radius=0.75)
        assert (values[PAN], values[6]) == large
        assert large != small

    def test_busk_position_claim_suppressed_for_covered_groups(
            self, qapp, mock_fixture_def):
        from gui.tabs.live_tab import COLOUR_SWATCHES
        from utils.artnet.dmx_manager import FixtureChannelMap
        from utils.artnet.live_layer import LiveBuskLayer
        spots = {"Riser": (1.0, 1.5, 0.6)}
        state, engine, binder, config = self._bound(mock_fixture_def,
                                                    spots=spots)
        layer = LiveBuskLayer(
            state, config_provider=lambda: config,
            swatches=COLOUR_SWATCHES, engine=engine,
            shape_groups_provider=binder.active_groups)
        layer.set_fixture_maps(
            {"MH1": FixtureChannelMap(config.fixtures[0],
                                      mock_fixture_def, config)})
        state.set_selection(["Movers"])
        state.stage_position("mark:Riser", "Riser")
        # Position alone: the busk aim claims coarse AND fine bytes.
        values, mask = layer.render(0.0)[1]
        assert mask[PAN] and mask[self.PAN_FINE]
        # Shape staged: the anchor claim yields to the orbit - the
        # engine's coarse write reaches the frame and the fines are
        # unclaimed again (a static aim on top would freeze the orbit).
        state.stage_shape("circle")
        values, mask = layer.render(0.1)[1]
        assert mask[PAN]
        assert mask[self.PAN_FINE] == 0
        expected = self._expected("circle", config.fixtures[0],
                                  (1.0, 1.5, 0.6), 0.0)
        assert (values[PAN], values[self.TILT]) == expected
