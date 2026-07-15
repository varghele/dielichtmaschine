# tests/unit/test_morph_wizard.py
"""The Morph to Venue wizard (v1.5b phase 4): dry-run isolation (review
compiles into a deep copy; cancel changes nothing), the commit force
flow over the destroyed-hand-edits manifest, plan save/load through the
dialog with config_hash stamping, and the non-blocking rig-changed
banner. Offscreen; file dialogs never open (tests call the plain
methods)."""

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


def _wizard(qapp, source, target, lane=None):
    from gui.dialogs.morph_wizard import MorphWizard
    wizard = MorphWizard(source, source_path="master.lms")
    wizard.set_target_config(target, "venue.lms")
    if lane is not None:
        wizard.patchbay.add_edge(lane.lane_id, "dimmer", "WASH")
        wizard.patchbay.add_edge(lane.lane_id, "colour", "WASH")
    return wizard


class TestDryRunIsolation:
    def test_review_never_touches_the_real_target(self, qapp,
                                                  source_and_target):
        source, target, lane = source_and_target
        wizard = _wizard(qapp, source, target, lane)
        before = config_hash(target)
        wizard._enter_review()
        assert config_hash(target) == before
        assert target.songs == {}
        # The dry run itself did compile.
        assert "S" in wizard._dry_result.songs

    def test_cancel_changes_nothing(self, qapp, source_and_target):
        source, target, lane = source_and_target
        source_before = config_hash(source)
        target_before = config_hash(target)
        wizard = _wizard(qapp, source, target, lane)
        wizard._enter_review()
        wizard.reject()
        assert config_hash(source) == source_before
        assert config_hash(target) == target_before

    def test_commit_mutates_the_real_target(self, qapp, source_and_target):
        source, target, lane = source_and_target
        wizard = _wizard(qapp, source, target, lane)
        wizard._enter_review()
        assert wizard.commit() is True
        assert wizard.committed
        assert "S" in target.songs
        assert target.songs["S"].lineage["plan_hash"]
        # Second commit is a no-op.
        assert wizard.commit() is False


class TestForceFlow:
    def _committed_pair(self, qapp, source_and_target):
        source, target, lane = source_and_target
        wizard = _wizard(qapp, source, target, lane)
        assert wizard.commit() is True
        # The operator edits a morphed block in the target afterwards.
        block = target.songs["S"].timeline_data.lanes[0].light_blocks[0]
        block.provenance = "hand_edited"
        return source, target, lane, wizard.plan

    def test_declined_manifest_blocks_the_apply(self, qapp,
                                                source_and_target,
                                                monkeypatch):
        source, target, lane, plan = self._committed_pair(
            qapp, source_and_target)
        from gui.dialogs.morph_wizard import MorphWizard
        wizard = MorphWizard(source)
        wizard.set_target_config(target)
        wizard.set_plan(plan)
        asked = {}
        monkeypatch.setattr(
            MorphWizard, "_confirm_destruction",
            lambda self, manifest: asked.setdefault("m", manifest) and False)
        assert wizard.commit() is False
        assert asked["m"] and "hand-edited block" in asked["m"][0]
        block = target.songs["S"].timeline_data.lanes[0].light_blocks[0]
        assert block.provenance == "hand_edited"    # survived

    def test_confirmed_manifest_replaces(self, qapp, source_and_target,
                                         monkeypatch):
        source, target, lane, plan = self._committed_pair(
            qapp, source_and_target)
        from gui.dialogs.morph_wizard import MorphWizard
        wizard = MorphWizard(source)
        wizard.set_target_config(target)
        wizard.set_plan(plan)
        monkeypatch.setattr(MorphWizard, "_confirm_destruction",
                            lambda self, manifest: True)
        assert wizard.commit() is True
        block = target.songs["S"].timeline_data.lanes[0].light_blocks[0]
        assert block.provenance.startswith("morphed:")

    def test_protected_lane_never_asks(self, qapp, source_and_target,
                                       monkeypatch):
        source, target, lane, plan = self._committed_pair(
            qapp, source_and_target)
        plan.protected_target_lanes = ["WASH"]
        from gui.dialogs.morph_wizard import MorphWizard
        wizard = MorphWizard(source)
        wizard.set_target_config(target)
        wizard.set_plan(plan)
        monkeypatch.setattr(
            MorphWizard, "_confirm_destruction",
            lambda self, manifest: pytest.fail("must not ask"))
        assert wizard.commit() is True
        block = target.songs["S"].timeline_data.lanes[0].light_blocks[0]
        assert block.provenance == "hand_edited"    # frozen lane


class TestPlanPersistence:
    def test_save_stamps_hashes_and_loads_back(self, qapp, tmp_path,
                                               source_and_target):
        source, target, lane = source_and_target
        wizard = _wizard(qapp, source, target, lane)
        path = str(tmp_path / "venue.morphplan.yaml")
        wizard.save_plan_to(path)

        loaded = MorphPlan.load(path)
        assert loaded.source_hash == config_hash(source)
        assert loaded.target_hash == config_hash(target)
        assert loaded.created
        assert len(loaded.edges) == 2

        again = _wizard(qapp, source, copy.deepcopy(target))
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
        wizard = _wizard(qapp, source, target, lane)
        assert wizard.commit() is True             # mutates target
        path = str(tmp_path / "venue.morphplan.yaml")
        wizard.save_plan_to(path)
        assert MorphPlan.load(path).target_hash == pristine_hash

    def test_changed_rig_shows_nonblocking_banner(self, qapp, tmp_path,
                                                  source_and_target):
        source, target, lane = source_and_target
        wizard = _wizard(qapp, source, target, lane)
        path = str(tmp_path / "venue.morphplan.yaml")
        wizard.save_plan_to(path)

        # The venue rig grows a fixture after the plan was authored.
        target.fixtures.append(_fixture("w2", group="WASH"))
        target.groups["WASH"].fixtures.append(target.fixtures[-1])

        stale = _wizard(qapp, source, target)
        stale.load_plan_file(path)
        assert stale.banner.isVisibleTo(stale)
        assert "target" in stale.banner.text()
        # Non-blocking: the flow continues.
        assert stale.next_btn.isEnabled()
        stale._enter_review()
        assert "S" in stale._dry_result.songs
