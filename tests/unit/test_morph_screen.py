# tests/unit/test_morph_screen.py
"""The Morph to Venue screen (v1.5b phase 4, rehosted from the modal
wizard 2026-07-16): dry-run isolation (review compiles into a deep
copy; discarding changes nothing), the commit force flow over the
destroyed-hand-edits manifest, plan save/load through the screen with
config_hash stamping, the non-blocking rig-changed banner, and the
keep/discard exit gate. Offscreen; file dialogs never open (tests call
the plain methods)."""

import copy

import pytest

from config.models import (ColourBlock, Configuration, DimmerBlock, Fixture,
                           FixtureGroup, FixtureGroupCapabilities,
                           FixtureMode, LightBlock, LightLane, ShowPart,
                           Song, TimelineData, Universe)
from utils.morph.plan import MorphPlan, config_hash


def _fixture(name, group="G"):
    return Fixture(universe=1, address=1, manufacturer="M", model="X",
                   current_mode="Std",
                   available_modes=[FixtureMode(name="Std", channels=1)],
                   name=name, group=group)


def _group(name, fixtures, caps):
    group = FixtureGroup(name, fixtures)
    group.capabilities = FixtureGroupCapabilities(
        has_dimmer="dimmer" in caps, has_colour="colour" in caps,
        has_movement="movement" in caps, has_special="special" in caps)
    return group


def _config(groups, songs=None):
    fixtures = [f for g in groups for f in g.fixtures]
    cfg = Configuration(fixtures=fixtures,
                        groups={g.name: g for g in groups},
                        universes={1: Universe(id=1, name="U1", output={})})
    cfg.songs = songs or {}
    return cfg


@pytest.fixture
def source_and_target():
    lane = LightLane(
        name="Pars", fixture_targets=["PARS"],
        light_blocks=[LightBlock(
            start_time=0.0, end_time=16.0, effect_name="x",
            dimmer_blocks=[DimmerBlock(0.0, 16.0, intensity=200.0)],
            colour_blocks=[ColourBlock(0.0, 16.0, red=255.0)])])
    song = Song(name="S",
                parts=[ShowPart(name="All", color="#fff", signature="4/4",
                                bpm=120.0, num_bars=8,
                                transition="instant")],
                timeline_data=TimelineData(lanes=[lane]))
    source = _config([_group("PARS", [_fixture("p1")],
                             {"dimmer", "colour"})],
                     songs={"S": song})
    target = _config([_group("WASH", [_fixture("w1", group="WASH")],
                             {"dimmer", "colour"})])
    return source, target, lane


def _screen(qapp, source, target, lane=None):
    from gui.screens.morph_screen import MorphScreen
    screen = MorphScreen(source, source_path="master.lms")
    screen.set_target_config(target, "venue.lms")
    if lane is not None:
        screen.patchbay.add_edge(lane.fixture_targets[0], "dimmer", "WASH")
        screen.patchbay.add_edge(lane.fixture_targets[0], "colour", "WASH")
    return screen


class TestDryRunIsolation:
    def test_review_never_touches_the_real_target(self, qapp,
                                                  source_and_target):
        source, target, lane = source_and_target
        screen = _screen(qapp, source, target, lane)
        before = config_hash(target)
        screen._enter_review()
        assert config_hash(target) == before
        assert target.songs == {}
        # The dry run itself did compile.
        assert "S" in screen._dry_result.songs

    def test_discard_changes_nothing(self, qapp, source_and_target,
                                     monkeypatch):
        source, target, lane = source_and_target
        source_before = config_hash(source)
        target_before = config_hash(target)
        screen = _screen(qapp, source, target, lane)
        screen._enter_review()
        from gui.screens.morph_screen import MorphScreen
        monkeypatch.setattr(MorphScreen, "_confirm_exit",
                            lambda self: "discard")
        closed = []
        screen.closed.connect(lambda: closed.append(True))
        screen.request_exit()
        screen.shutdown()
        assert closed == [True]
        assert config_hash(source) == source_before
        assert config_hash(target) == target_before

    def test_commit_mutates_the_real_target(self, qapp, source_and_target):
        source, target, lane = source_and_target
        screen = _screen(qapp, source, target, lane)
        screen._enter_review()
        assert screen.commit() is True
        assert screen.committed
        assert "S" in target.songs
        assert target.songs["S"].lineage["plan_hash"]
        # Second commit is a no-op.
        assert screen.commit() is False


class TestForceFlow:
    def _committed_pair(self, qapp, source_and_target):
        source, target, lane = source_and_target
        screen = _screen(qapp, source, target, lane)
        assert screen.commit() is True
        # The operator edits a morphed block in the target afterwards.
        block = target.songs["S"].timeline_data.lanes[0].light_blocks[0]
        block.provenance = "hand_edited"
        return source, target, lane, screen.plan

    def test_declined_manifest_blocks_the_apply(self, qapp,
                                                source_and_target,
                                                monkeypatch):
        source, target, lane, plan = self._committed_pair(
            qapp, source_and_target)
        from gui.screens.morph_screen import MorphScreen
        screen = MorphScreen(source)
        screen.set_target_config(target)
        screen.set_plan(plan)
        asked = {}
        monkeypatch.setattr(
            MorphScreen, "_confirm_destruction",
            lambda self, manifest: asked.setdefault("m", manifest) and False)
        assert screen.commit() is False
        assert asked["m"] and "hand-edited block" in asked["m"][0]
        block = target.songs["S"].timeline_data.lanes[0].light_blocks[0]
        assert block.provenance == "hand_edited"    # survived

    def test_confirmed_manifest_replaces(self, qapp, source_and_target,
                                         monkeypatch):
        source, target, lane, plan = self._committed_pair(
            qapp, source_and_target)
        from gui.screens.morph_screen import MorphScreen
        screen = MorphScreen(source)
        screen.set_target_config(target)
        screen.set_plan(plan)
        monkeypatch.setattr(MorphScreen, "_confirm_destruction",
                            lambda self, manifest: True)
        assert screen.commit() is True
        block = target.songs["S"].timeline_data.lanes[0].light_blocks[0]
        assert block.provenance.startswith("morphed:")

    def test_protected_lane_never_asks(self, qapp, source_and_target,
                                       monkeypatch):
        source, target, lane, plan = self._committed_pair(
            qapp, source_and_target)
        plan.protected_target_lanes = ["WASH"]
        from gui.screens.morph_screen import MorphScreen
        screen = MorphScreen(source)
        screen.set_target_config(target)
        screen.set_plan(plan)
        monkeypatch.setattr(
            MorphScreen, "_confirm_destruction",
            lambda self, manifest: pytest.fail("must not ask"))
        assert screen.commit() is True
        block = target.songs["S"].timeline_data.lanes[0].light_blocks[0]
        assert block.provenance == "hand_edited"    # frozen lane


class TestPlanPersistence:
    def test_save_stamps_hashes_and_loads_back(self, qapp, tmp_path,
                                               source_and_target):
        source, target, lane = source_and_target
        screen = _screen(qapp, source, target, lane)
        path = str(tmp_path / "venue.morphplan.yaml")
        screen.save_plan_to(path)

        loaded = MorphPlan.load(path)
        assert loaded.source_hash == config_hash(source)
        assert loaded.target_hash == config_hash(target)
        assert loaded.created
        assert len(loaded.edges) == 2

        again = _screen(qapp, source, copy.deepcopy(target))
        again.load_plan_file(path)
        assert len(again.patchbay.plan.edges) == 2
        assert not again.banner.isVisibleTo(again)   # hashes still match

    def test_plan_pins_the_pristine_rig_even_after_commit(
            self, qapp, tmp_path, source_and_target):
        """The target hash must identify the rig the plan was authored
        against, NOT the committed (morphed) target - otherwise every
        saved plan reads as 'rig changed' on its first re-morph."""
        source, target, lane = source_and_target
        pristine_hash = config_hash(target)
        screen = _screen(qapp, source, target, lane)
        assert screen.commit() is True             # mutates target
        path = str(tmp_path / "venue.morphplan.yaml")
        screen.save_plan_to(path)
        assert MorphPlan.load(path).target_hash == pristine_hash

    def test_changed_rig_shows_nonblocking_banner(self, qapp, tmp_path,
                                                  source_and_target):
        source, target, lane = source_and_target
        screen = _screen(qapp, source, target, lane)
        path = str(tmp_path / "venue.morphplan.yaml")
        screen.save_plan_to(path)

        # The venue rig grows a fixture after the plan was authored.
        target.fixtures.append(_fixture("w2", group="WASH"))
        target.groups["WASH"].fixtures.append(target.fixtures[-1])

        stale = _screen(qapp, source, target)
        stale.load_plan_file(path)
        assert stale.banner.isVisibleTo(stale)
        assert "target" in stale.banner.text()
        # Non-blocking: the flow continues.
        assert stale.next_btn.isEnabled()
        stale._enter_review()
        assert "S" in stale._dry_result.songs


class TestExitGate:
    """EXIT semantics of the modeless screen: a wired, uncommitted plan
    asks keep/discard; committed or empty flows close silently."""

    def _signals(self, screen):
        fired = {"leave": 0, "closed": 0}
        screen.leave_requested.connect(
            lambda: fired.__setitem__("leave", fired["leave"] + 1))
        screen.closed.connect(
            lambda: fired.__setitem__("closed", fired["closed"] + 1))
        return fired

    def test_empty_flow_closes_without_asking(self, qapp,
                                              source_and_target,
                                              monkeypatch):
        source, target, _lane = source_and_target
        screen = _screen(qapp, source, target)          # no edges wired
        from gui.screens.morph_screen import MorphScreen
        monkeypatch.setattr(
            MorphScreen, "_confirm_exit",
            lambda self: pytest.fail("must not ask on an empty flow"))
        fired = self._signals(screen)
        screen.request_exit()
        assert fired == {"leave": 0, "closed": 1}

    def test_wired_flow_keep_leaves_state_alive(self, qapp,
                                                source_and_target,
                                                monkeypatch):
        source, target, lane = source_and_target
        screen = _screen(qapp, source, target, lane)
        from gui.screens.morph_screen import MorphScreen
        monkeypatch.setattr(MorphScreen, "_confirm_exit",
                            lambda self: "keep")
        fired = self._signals(screen)
        screen.request_exit()
        assert fired == {"leave": 1, "closed": 0}
        assert len(screen.plan.edges) == 2              # state survives

    def test_wired_flow_cancel_stays(self, qapp, source_and_target,
                                     monkeypatch):
        source, target, lane = source_and_target
        screen = _screen(qapp, source, target, lane)
        from gui.screens.morph_screen import MorphScreen
        monkeypatch.setattr(MorphScreen, "_confirm_exit",
                            lambda self: "cancel")
        fired = self._signals(screen)
        screen.request_exit()
        assert fired == {"leave": 0, "closed": 0}

    def test_committed_flow_closes_without_asking(self, qapp,
                                                  source_and_target,
                                                  monkeypatch):
        source, target, lane = source_and_target
        screen = _screen(qapp, source, target, lane)
        assert screen.commit() is True
        from gui.screens.morph_screen import MorphScreen
        monkeypatch.setattr(
            MorphScreen, "_confirm_exit",
            lambda self: pytest.fail("must not ask after commit"))
        fired = self._signals(screen)
        screen.request_exit()
        assert fired == {"leave": 0, "closed": 1}


class TestScrubStrip:
    """RENDER SCRUB batches the whole song into ONE forward pass per rig
    instead of re-rendering per slider position (2026-08-08).

    Measured on a real 4:39 song: one still 90% in costs 7.1 s and
    twenty stills spread across the whole song cost 7.3 s, because the
    expense is the DMX forward walk, not the pixels. Rendering per
    slider tick paid that walk again every time."""

    def test_frames_every_two_seconds_plus_the_end(self, qapp,
                                                   source_and_target):
        from gui.screens.morph_screen import PREVIEW_STRIP_INTERVAL_S
        source, target, lane = source_and_target
        screen = _screen(qapp, source, target, lane)
        times = screen.strip_times(16.0)
        assert times[:3] == [0.0, 2.0, 4.0]
        assert PREVIEW_STRIP_INTERVAL_S == 2.0
        # The last moment of the song is always covered, so the end of
        # the slider is never a blank.
        assert times[-1] >= 15.0

    def test_empty_song_asks_for_no_frames(self, qapp, source_and_target):
        source, target, lane = source_and_target
        screen = _screen(qapp, source, target, lane)
        assert screen.strip_times(0.0) == []

    def test_scrub_picks_the_nearest_rendered_frame(self, qapp,
                                                    source_and_target):
        source, target, lane = source_and_target
        screen = _screen(qapp, source, target, lane)
        screen._preview_strip = {"song": "S", "times": [0.0, 2.0, 4.0],
                                 "src": {}, "dst": {}}
        assert screen.nearest_strip_time(2.4) == 2.0
        assert screen.nearest_strip_time(3.1) == 4.0
        assert screen.nearest_strip_time(99.0) == 4.0

    def test_no_strip_means_no_frame(self, qapp, source_and_target):
        source, target, lane = source_and_target
        screen = _screen(qapp, source, target, lane)
        assert screen.nearest_strip_time(1.0) is None

    def test_switching_song_drops_the_strip(self, qapp, source_and_target):
        """A strip belongs to one song; showing another song's frames
        would be a quietly wrong preview."""
        source, target, lane = source_and_target
        screen = _screen(qapp, source, target, lane)
        screen._preview_strip = {"song": "S", "times": [0.0], "src": {},
                                 "dst": {}}
        screen.preview_song_combo.addItem("Other")
        screen.preview_song_combo.setCurrentIndex(
            screen.preview_song_combo.count() - 1)
        assert screen._preview_strip == {}

    def test_scrubbing_never_starts_a_render(self, qapp, source_and_target,
                                             monkeypatch):
        """The whole point of batching: the slider reads the cache."""
        from utils.morph import preview as morph_preview
        source, target, lane = source_and_target
        screen = _screen(qapp, source, target, lane)
        called = []
        monkeypatch.setattr(morph_preview, "render_strip",
                            lambda *a, **k: called.append(a))
        monkeypatch.setattr(morph_preview, "render_pair",
                            lambda *a, **k: called.append(a))
        screen.preview_slider.setRange(0, 200)
        for value in (10, 50, 120, 200):
            screen.preview_slider.setValue(value)
        assert called == []
