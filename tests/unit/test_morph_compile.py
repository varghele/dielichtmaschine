# tests/unit/test_morph_compile.py
"""The morph compile engine (v1.5b phase 2, docs/design-show-morphing.md
sections 3 and 5): plan round-trip + validation, routing with fan-out,
transforms, static fan-in resolution (dimmer HTP, priority LTP,
clip-vs-drop), the specials same-definition rule, regeneration
strategies, interval-union envelopes (blocks never split), lineage +
provenance, determinism, and re-morph with protection + the
destroyed-hand-edits manifest."""

import copy

import pytest

from config.models import (ColourBlock, Configuration, DimmerBlock, Fixture,
                           FixtureGroup, FixtureGroupCapabilities,
                           FixtureMode, LightBlock, LightLane, MovementBlock,
                           ShowPart, Song, SpecialBlock, TimelineData,
                           Universe)
from utils.morph.compile import (MorphReport, apply_morph, compile_setlist,
                                 compile_song, pending_destruction)
from utils.morph.plan import MorphEdge, MorphPlan, PlanError


def _fixture(name, x=0.0, manufacturer="M", model="X", group="G"):
    return Fixture(universe=1, address=1, manufacturer=manufacturer,
                   model=model, current_mode="Std",
                   available_modes=[FixtureMode(name="Std", channels=1)],
                   name=name, group=group, x=x)


def _config(groups: dict, songs=None) -> Configuration:
    fixtures = [f for fx in groups.values() for f in fx]
    cfg = Configuration(
        fixtures=fixtures,
        groups={name: FixtureGroup(name, list(fx))
                for name, fx in groups.items()},
        universes={1: Universe(id=1, name="U1", output={})},
    )
    cfg.songs = songs or {}
    return cfg


def _song(name="S", lanes=None):
    return Song(name=name,
                parts=[ShowPart(name="All", color="#fff", signature="4/4",
                                bpm=120.0, num_bars=8,
                                transition="instant")],
                timeline_data=TimelineData(lanes=lanes or []))


def _lane(name, targets, dimmer=(), colour=(), movement=(), special=()):
    return LightLane(name=name, fixture_targets=list(targets),
                     light_blocks=[LightBlock(
                         start_time=0.0, end_time=16.0, effect_name="x",
                         dimmer_blocks=list(dimmer),
                         colour_blocks=list(colour),
                         movement_blocks=list(movement),
                         special_blocks=list(special))])


def _edge(lane, sublane, target, **kw):
    return MorphEdge(source_lane_id=lane.lane_id,
                     source_lane_name=lane.name, sublane=sublane,
                     target_group=target, **kw)


@pytest.fixture
def rig_pair():
    """Source config A (one lane on PARS) and target config B (WASH +
    BLINDER groups)."""
    lane = _lane("Pars", ["PARS"],
                 dimmer=[DimmerBlock(0.0, 8.0, intensity=200.0,
                                     effect_type="chase"),
                         DimmerBlock(8.0, 16.0, intensity=120.0)],
                 colour=[ColourBlock(0.0, 16.0, red=255.0)])
    a = _config({"PARS": [_fixture("p1"), _fixture("p2")]},
                songs={"S": _song(lanes=[lane])})
    b = _config({"WASH": [_fixture("w1", x=-1.0, group="WASH"),
                          _fixture("w2", x=1.0, group="WASH")],
                 "BLINDER": [_fixture("b1", group="BLINDER")]})
    return a, b, lane


class TestPlanPersistence:
    def test_round_trip(self, tmp_path, rig_pair):
        _a, _b, lane = rig_pair
        plan = MorphPlan(name="venue", seed=7, edges=[
            _edge(lane, "dimmer", "WASH", mode="copy_transform",
                  transforms=[{"type": "intensity_scale", "factor": 0.5}],
                  priority=2)])
        path = tmp_path / "venue.morphplan.yaml"
        plan.save(str(path))
        loaded = MorphPlan.load(str(path))
        assert loaded.seed == 7
        assert loaded.edges[0].transforms == [
            {"type": "intensity_scale", "factor": 0.5}]
        assert loaded.edges[0].edge_id == plan.edges[0].edge_id

    def test_not_a_plan_raises(self, tmp_path):
        path = tmp_path / "nope.yaml"
        path.write_text("just: yaml", encoding="utf-8")
        with pytest.raises(PlanError):
            MorphPlan.load(str(path))

    def test_validation_catches_the_lot(self, rig_pair):
        a, b, lane = rig_pair
        plan = MorphPlan(edges=[
            _edge(lane, "smoke", "WASH"),                       # sublane
            _edge(lane, "dimmer", "NOPE"),                      # group
            _edge(lane, "dimmer", "WASH",
                  transforms=[{"type": "intensity_scale"}],     # param
                  mode="copy_transform"),
            _edge(lane, "dimmer", "WASH",
                  transforms=[{"type": "warp"}],                # kind
                  mode="copy_transform"),
            MorphEdge(source_lane_id="ghost", source_lane_name="?",
                      sublane="dimmer", target_group="WASH"),   # lane
        ])
        problems = plan.validate(source_config=a, target_config=b)
        assert len(problems) == 5


class TestRouting:
    def test_copy_routes_and_tags_provenance(self, rig_pair):
        a, b, lane = rig_pair
        plan = MorphPlan(edges=[_edge(lane, "dimmer", "WASH")])
        result = compile_setlist(a, plan, b)
        song = result.songs["S"]
        (out_lane,) = song.timeline_data.lanes
        assert out_lane.name == "WASH"
        assert out_lane.fixture_targets == ["WASH"]
        blocks = [d for lb in out_lane.light_blocks
                  for d in lb.dimmer_blocks]
        assert len(blocks) == 2
        assert all(lb.provenance.startswith("morphed:")
                   for lb in out_lane.light_blocks)
        assert song.lineage["plan_hash"]

    def test_fan_out_feeds_two_groups(self, rig_pair):
        a, b, lane = rig_pair
        plan = MorphPlan(edges=[_edge(lane, "dimmer", "WASH"),
                                _edge(lane, "dimmer", "BLINDER")])
        result = compile_setlist(a, plan, b)
        names = {l.name for l in result.songs["S"].timeline_data.lanes}
        assert names == {"WASH", "BLINDER"}

    def test_unrouted_streams_are_reported_never_silent(self, rig_pair):
        a, b, lane = rig_pair
        plan = MorphPlan(edges=[_edge(lane, "dimmer", "WASH")])
        result = compile_setlist(a, plan, b)
        notes = " ".join(e.message for e in result.report.of_kind("note"))
        assert "unrouted source stream: 'Pars' colour" in notes

    def test_determinism_same_input_same_output(self, rig_pair):
        a, b, lane = rig_pair
        plan = MorphPlan(edges=[_edge(lane, "dimmer", "WASH"),
                                _edge(lane, "colour", "WASH")])
        one = compile_setlist(a, plan, copy.deepcopy(b))
        two = compile_setlist(a, plan, copy.deepcopy(b))
        assert one.songs["S"].to_dict() == two.songs["S"].to_dict()


class TestTransforms:
    def test_intensity_scale(self, rig_pair):
        a, b, lane = rig_pair
        plan = MorphPlan(edges=[_edge(
            lane, "dimmer", "WASH", mode="copy_transform",
            transforms=[{"type": "intensity_scale", "factor": 0.5}])])
        result = compile_setlist(a, plan, b)
        blocks = [d for lb in
                  result.songs["S"].timeline_data.lanes[0].light_blocks
                  for d in lb.dimmer_blocks]
        assert sorted(d.intensity for d in blocks) == [60.0, 100.0]
        # the source config is never mutated
        src = [d for lb in lane.light_blocks for d in lb.dimmer_blocks]
        assert sorted(d.intensity for d in src) == [120.0, 200.0]

    def test_mirror_flips_dimmer_direction(self, rig_pair):
        a, b, _lane_ = rig_pair
        lane = _lane("Chase", ["PARS"], dimmer=[
            DimmerBlock(0.0, 8.0, effect_type="waterfall",
                        direction="down")])
        a.songs["S"] = _song(lanes=[lane])
        plan = MorphPlan(edges=[_edge(lane, "dimmer", "WASH",
                                      mode="copy_transform",
                                      transforms=[{"type": "mirror"}])])
        result = compile_setlist(a, plan, b)
        (block,) = [d for lb in
                    result.songs["S"].timeline_data.lanes[0].light_blocks
                    for d in lb.dimmer_blocks]
        assert block.direction == "up"

    def test_phase_offset_on_movement(self, rig_pair):
        a, b, _l = rig_pair
        lane = _lane("Movers", ["PARS"], movement=[
            MovementBlock(0.0, 8.0, effect_type="circle")])
        a.songs["S"] = _song(lanes=[lane])
        plan = MorphPlan(edges=[_edge(
            lane, "movement", "WASH", mode="copy_transform",
            transforms=[{"type": "phase_offset", "amount": 0.5}])])
        result = compile_setlist(a, plan, b)
        (block,) = [m for lb in
                    result.songs["S"].timeline_data.lanes[0].light_blocks
                    for m in lb.movement_blocks]
        assert block.phase_offset_enabled
        assert block.phase_offset_degrees == 180.0

    def test_spatial_subset_materializes_a_group(self, rig_pair):
        a, b, lane = rig_pair
        plan = MorphPlan(edges=[_edge(
            lane, "dimmer", "WASH", mode="copy_transform",
            transforms=[{"type": "spatial_subset",
                         "selector": "left-half"}])])
        result = compile_setlist(a, plan, b)
        (out_lane,) = result.songs["S"].timeline_data.lanes
        assert out_lane.name == "WASH (left half)"
        subset = b.groups["WASH (left half)"]
        assert [f.name for f in subset.fixtures] == ["w1"]


class TestFanIn:
    def test_dimmer_htp_keeps_the_brighter_block(self, rig_pair):
        a, b, _l = rig_pair
        bright = _lane("Bright", ["PARS"],
                       dimmer=[DimmerBlock(0.0, 8.0, intensity=250.0,
                                           effect_type="chase")])
        dim = _lane("Dim", ["PARS"],
                    dimmer=[DimmerBlock(0.0, 8.0, intensity=90.0,
                                        effect_type="pulse")])
        a.songs["S"] = _song(lanes=[bright, dim])
        plan = MorphPlan(edges=[_edge(bright, "dimmer", "WASH"),
                                _edge(dim, "dimmer", "WASH")])
        result = compile_setlist(a, plan, b)
        blocks = [d for lb in
                  result.songs["S"].timeline_data.lanes[0].light_blocks
                  for d in lb.dimmer_blocks]
        assert [d.intensity for d in blocks] == [250.0]
        assert result.report.of_kind("fanin_loss")

    def test_static_dimmer_loser_is_clipped_not_dropped(self, rig_pair):
        a, b, _l = rig_pair
        winner = _lane("Win", ["PARS"],
                       dimmer=[DimmerBlock(4.0, 8.0, intensity=250.0)])
        loser = _lane("Lose", ["PARS"],
                      dimmer=[DimmerBlock(0.0, 12.0, intensity=90.0)])
        a.songs["S"] = _song(lanes=[winner, loser])
        plan = MorphPlan(edges=[_edge(winner, "dimmer", "WASH"),
                                _edge(loser, "dimmer", "WASH")])
        result = compile_setlist(a, plan, b)
        blocks = sorted((d.start_time, d.end_time, d.intensity)
                        for lb in
                        result.songs["S"].timeline_data.lanes[0].light_blocks
                        for d in lb.dimmer_blocks)
        assert blocks == [(0.0, 4.0, 90.0), (4.0, 8.0, 250.0),
                          (8.0, 12.0, 90.0)]

    def test_movement_priority_drops_whole_loser(self, rig_pair):
        a, b, _l = rig_pair
        high = _lane("High", ["PARS"], movement=[
            MovementBlock(0.0, 8.0, effect_type="circle")])
        low = _lane("Low", ["PARS"], movement=[
            MovementBlock(4.0, 12.0, effect_type="bounce")])
        a.songs["S"] = _song(lanes=[high, low])
        plan = MorphPlan(edges=[
            _edge(high, "movement", "WASH", priority=5),
            _edge(low, "movement", "WASH", priority=1)])
        result = compile_setlist(a, plan, b)
        blocks = [m for lb in
                  result.songs["S"].timeline_data.lanes[0].light_blocks
                  for m in lb.movement_blocks]
        assert [m.effect_type for m in blocks] == ["circle"]
        loss = result.report.of_kind("fanin_loss")
        assert loss and "never clipped" in loss[0].message


class TestSpecialsRule:
    def test_same_definition_routes_different_drops(self):
        src_fix = [_fixture("s1", manufacturer="Mfr", model="Spot")]
        same = [_fixture("t1", manufacturer="Mfr", model="Spot",
                         group="SAME")]
        other = [_fixture("t2", manufacturer="Other", model="Wash",
                          group="OTHER")]
        lane = _lane("Specials", ["G"], special=[
            SpecialBlock(0.0, 8.0, gobo_index=2)])
        a = _config({"G": src_fix}, songs={"S": _song(lanes=[lane])})
        b = _config({"SAME": same, "OTHER": other})
        plan = MorphPlan(edges=[_edge(lane, "special", "SAME"),
                                _edge(lane, "special", "OTHER")])
        result = compile_setlist(a, plan, b)
        names = {l.name for l in result.songs["S"].timeline_data.lanes}
        assert names == {"SAME"}
        assert result.report.of_kind("dropped_special")


class TestRegeneration:
    def _plan(self, lane, strategy, **kw):
        return MorphPlan(edges=[_edge(lane, "movement", "WASH",
                                      mode="regenerate",
                                      regenerate_strategy=strategy, **kw)])

    def test_manual_emits_nothing_but_reports(self, rig_pair):
        a, b, lane = rig_pair
        result = compile_setlist(a, self._plan(lane, "manual"), b)
        assert result.songs["S"].timeline_data.lanes == []
        assert "intentionally empty" in \
            result.report.of_kind("regenerated")[0].message

    def test_static_default_spans_the_song(self, rig_pair):
        a, b, lane = rig_pair
        result = compile_setlist(a, self._plan(lane, "static_default"), b)
        (block,) = [m for lb in
                    result.songs["S"].timeline_data.lanes[0].light_blocks
                    for m in lb.movement_blocks]
        assert block.effect_type == "circle"
        assert block.end_time == pytest.approx(16.0)  # 8 bars @120 4/4
        assert (block.target_plane_name or block.target_point)

    def test_derive_from_intensity_maps_rudiments(self, rig_pair):
        a, b, lane = rig_pair
        result = compile_setlist(
            a, self._plan(lane, "derive_from_intensity"), b)
        blocks = [m for lb in
                  result.songs["S"].timeline_data.lanes[0].light_blocks
                  for m in lb.movement_blocks]
        # chase -> bounce, static -> circle (the source's two blocks)
        assert sorted(m.effect_type for m in blocks) == \
            ["bounce", "circle"]
        assert [m.start_time for m in sorted(
            blocks, key=lambda x: x.start_time)] == [0.0, 8.0]

    def test_autogen_fails_clearly_until_the_cache_lands(self, rig_pair):
        a, b, lane = rig_pair
        result = compile_setlist(a, self._plan(lane, "autogen"), b)
        errors = result.report.of_kind("error")
        assert errors and "downgrade" in errors[0].message


class TestEnvelopes:
    def test_disjoint_clusters_become_separate_envelopes(self, rig_pair):
        a, b, _l = rig_pair
        lane = _lane("Sparse", ["PARS"], dimmer=[
            DimmerBlock(0.0, 4.0, intensity=200.0),
            DimmerBlock(12.0, 16.0, intensity=200.0)])
        a.songs["S"] = _song(lanes=[lane])
        plan = MorphPlan(edges=[_edge(lane, "dimmer", "WASH")])
        result = compile_setlist(a, plan, b)
        envelopes = result.songs["S"].timeline_data.lanes[0].light_blocks
        assert [(e.start_time, e.end_time) for e in envelopes] == \
            [(0.0, 4.0), (12.0, 16.0)]
        assert all(len(e.dimmer_blocks) == 1 for e in envelopes)

    def test_overlapping_sublanes_share_one_envelope(self, rig_pair):
        a, b, lane = rig_pair
        plan = MorphPlan(edges=[_edge(lane, "dimmer", "WASH"),
                                _edge(lane, "colour", "WASH")])
        result = compile_setlist(a, plan, b)
        (envelope,) = \
            result.songs["S"].timeline_data.lanes[0].light_blocks
        assert len(envelope.dimmer_blocks) == 2
        assert len(envelope.colour_blocks) == 1
        assert envelope.name.startswith("morph:")


class TestReMorph:
    def _morphed_config(self, rig_pair):
        a, b, lane = rig_pair
        plan = MorphPlan(edges=[_edge(lane, "dimmer", "WASH")])
        result = compile_setlist(a, plan, b)
        apply_morph(result, b, plan)
        return a, b, lane, plan

    def test_apply_writes_songs_into_b(self, rig_pair):
        _a, b, _lane_, _plan = self._morphed_config(rig_pair)
        assert "S" in b.songs
        assert b.songs["S"].lineage["plan_hash"]

    def test_hand_edits_block_the_replace_until_forced(self, rig_pair):
        a, b, lane, plan = self._morphed_config(rig_pair)
        block = b.songs["S"].timeline_data.lanes[0].light_blocks[0]
        block.provenance = "hand_edited"
        result = compile_setlist(a, plan, b)
        manifest = pending_destruction(result, b, plan)
        assert manifest and "hand-edited block" in manifest[0]
        with pytest.raises(ValueError):
            apply_morph(result, b, plan)
        destroyed = apply_morph(result, b, plan, force=True)
        assert destroyed == manifest

    def test_protected_target_lane_survives_re_morph(self, rig_pair):
        a, b, lane, plan = self._morphed_config(rig_pair)
        edited = b.songs["S"].timeline_data.lanes[0]
        edited.light_blocks[0].provenance = "hand_edited"
        plan.protected_target_lanes = ["WASH"]
        result = compile_setlist(a, plan, b)
        assert pending_destruction(result, b, plan) == []
        apply_morph(result, b, plan)
        (kept,) = b.songs["S"].timeline_data.lanes
        assert kept.light_blocks[0].provenance == "hand_edited"
