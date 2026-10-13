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
    """Edges key by GROUP SELECTOR (design doc 5.2), so the helper takes
    a lane only for convenience and reads its first target."""
    return MorphEdge(source_group=lane.fixture_targets[0], sublane=sublane,
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
            MorphEdge(source_group="ghost",
                      sublane="dimmer", target_group="WASH"),   # source group
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


class TestSetlistWidePlan:
    """Edges key by GROUP SELECTOR, so ONE edge covers the whole setlist
    (design doc 5.2: "lanes are keyed by group targets, which are
    consistent across songs in a config").

    Format 1 keyed by per-song lane uuid, which forced the user to draw
    the same wire once per song - a real 12-song gig needed 293 edges to
    express 39 distinct wires. Changed 2026-08-08."""

    def _two_song_source(self):
        lane1 = _lane("Pars", ["PARS"],
                      dimmer=[DimmerBlock(0.0, 16.0, intensity=200.0)])
        lane2 = _lane("Pars", ["PARS"],
                      dimmer=[DimmerBlock(0.0, 8.0, intensity=120.0)])
        a = _config({"PARS": [_fixture("p1")]},
                    songs={"One": _song("One", lanes=[lane1]),
                           "Two": _song("Two", lanes=[lane2])})
        return a, lane1, lane2

    def test_one_edge_covers_every_song(self):
        a, lane1, lane2 = self._two_song_source()
        b = _config({"WASH": [_fixture("w1", group="WASH")]})
        # ONE edge, not one per song - that is the whole point.
        plan = MorphPlan(edges=[_edge(lane1, "dimmer", "WASH")])
        result = compile_setlist(a, plan, b)
        assert not result.report.has_errors
        assert set(result.songs) == {"One", "Two"}
        for name, lane in (("One", lane1), ("Two", lane2)):
            (out,) = result.songs[name].timeline_data.lanes
            blocks = [d for lb in out.light_blocks for d in lb.dimmer_blocks]
            src = [d for lb in lane.light_blocks for d in lb.dimmer_blocks]
            assert len(blocks) == len(src), name

    def test_group_in_no_song_still_errors(self):
        a, lane1, _ = self._two_song_source()
        b = _config({"WASH": [_fixture("w1", group="WASH")]})
        plan = MorphPlan(edges=[
            _edge(lane1, "dimmer", "WASH"),
            MorphEdge(source_group="GHOST", sublane="dimmer",
                      target_group="WASH"),
        ])
        result = compile_setlist(a, plan, b)
        errors = result.report.of_kind("error")
        assert errors and "not in the source config" in errors[0].format()

    def test_song_without_that_group_notes_rather_than_errors(self):
        """A rig-level edge naturally covers groups some songs do not
        use. That is ordinary, and must not read as a failure."""
        lane1 = _lane("Pars", ["PARS"], dimmer=[DimmerBlock(0.0, 8.0)])
        lane2 = _lane("Movers", ["MOVERS"], dimmer=[DimmerBlock(0.0, 8.0)])
        a = _config({"PARS": [_fixture("p1")],
                     "MOVERS": [_fixture("m1", group="MOVERS")]},
                    songs={"One": _song("One", lanes=[lane1]),
                           "Two": _song("Two", lanes=[lane2])})
        b = _config({"WASH": [_fixture("w1", group="WASH")]})
        plan = MorphPlan(edges=[_edge(lane1, "dimmer", "WASH")])
        result = compile_setlist(a, plan, b)
        assert not result.report.has_errors
        notes = " ".join(n.format() for n in result.report.of_kind("note"))
        assert "has no lane in this song" in notes

    def test_two_lanes_on_one_group_merge_rather_than_one_winning(self):
        """User decision 2026-08-08: within a song, several lanes sharing
        a selector merge and fan-in resolution settles them (doc 3.3)."""
        first = _lane("Pars A", ["PARS"], dimmer=[DimmerBlock(0.0, 4.0)])
        second = _lane("Pars B", ["PARS"], dimmer=[DimmerBlock(8.0, 12.0)])
        a = _config({"PARS": [_fixture("p1")]},
                    songs={"One": _song("One", lanes=[first, second])})
        b = _config({"WASH": [_fixture("w1", group="WASH")]})
        plan = MorphPlan(edges=[_edge(first, "dimmer", "WASH")])
        result = compile_setlist(a, plan, b)
        assert not result.report.has_errors
        (out,) = result.songs["One"].timeline_data.lanes
        blocks = [d for lb in out.light_blocks for d in lb.dimmer_blocks]
        assert len(blocks) == 2, "both lanes' streams should survive"


class TestAudioCarryOver:
    def test_morphed_song_keeps_the_source_audio(self):
        """Fresh lanes, same music: the morph must not silence the
        timeline (regression 2026-07-16 - TimelineData was rebuilt
        empty and the audio reference vanished)."""
        lane = _lane("Pars", ["PARS"],
                     dimmer=[DimmerBlock(0.0, 16.0, intensity=200.0)])
        song = _song(lanes=[lane])
        song.timeline_data.audio_file_path = "light_track.mp3"
        a = _config({"PARS": [_fixture("p1")]}, songs={"S": song})
        b = _config({"WASH": [_fixture("w1", group="WASH")]})
        plan = MorphPlan(edges=[_edge(lane, "dimmer", "WASH")])
        result = compile_setlist(a, plan, b)
        assert result.songs["S"].timeline_data.audio_file_path == \
            "light_track.mp3"


class TestSpotBaking:
    """Movement blocks aiming at NAMED spots (2026-07-16): a spot the
    target rig lacks bakes into a world point from the SOURCE spot's
    position; a same-named target spot wins so venue re-aiming keeps
    working; a spot in neither config is reported and left alone."""

    def _movement_source(self, spot=None):
        from config.models import MovementBlock, Spot
        lane = _lane("Movers", ["MH"],
                     movement=[MovementBlock(0.0, 16.0,
                                             effect_type="circle",
                                             target_spot_name="DS CENTRE")])
        a = _config({"MH": [_fixture("m1", group="MH")]},
                    songs={"S": _song(lanes=[lane])})
        if spot is not None:
            a.spots = {"DS CENTRE": spot}
        return a, lane

    def test_dangling_spot_bakes_to_source_position(self):
        from config.models import Spot
        a, lane = self._movement_source(Spot(name="DS CENTRE", x=1.5,
                                             y=-3.0, z=0.5))
        b = _config({"HEADS": [_fixture("h1", group="HEADS")]})
        plan = MorphPlan(edges=[_edge(lane, "movement", "HEADS")])
        result = compile_setlist(a, plan, b)
        (out_lane,) = result.songs["S"].timeline_data.lanes
        (mb,) = [m for lb in out_lane.light_blocks
                 for m in lb.movement_blocks]
        assert mb.target_point == [1.5, -3.0, 0.5]
        assert mb.target_spot_name is None
        notes = " ".join(e.message
                         for e in result.report.of_kind("transform"))
        assert "re-anchored" in notes

    def test_same_named_target_spot_wins(self):
        from config.models import Spot
        a, lane = self._movement_source(Spot(name="DS CENTRE", x=1.5,
                                             y=-3.0, z=0.5))
        b = _config({"HEADS": [_fixture("h1", group="HEADS")]})
        b.spots = {"DS CENTRE": Spot(name="DS CENTRE", x=9.0, y=9.0,
                                     z=9.0)}
        plan = MorphPlan(edges=[_edge(lane, "movement", "HEADS")])
        result = compile_setlist(a, plan, b)
        (out_lane,) = result.songs["S"].timeline_data.lanes
        (mb,) = [m for lb in out_lane.light_blocks
                 for m in lb.movement_blocks]
        assert mb.target_spot_name == "DS CENTRE"
        assert not getattr(mb, "target_point", None)

    def test_spot_in_neither_config_is_reported(self):
        a, lane = self._movement_source(spot=None)
        b = _config({"HEADS": [_fixture("h1", group="HEADS")]})
        plan = MorphPlan(edges=[_edge(lane, "movement", "HEADS")])
        result = compile_setlist(a, plan, b)
        notes = " ".join(e.message for e in result.report.of_kind("note"))
        assert "exists in neither config" in notes


class TestSetlistAdoption:
    """The setlist is the gig: a target without one adopts the source
    setlist (order, triggers, pause looks) filtered to morphed songs;
    a target WITH a setlist keeps its own (2026-07-16 - a rig-only
    venue used to end up with songs but no way to run them)."""

    def _source_with_setlist(self):
        from config.models import SetlistEntry
        lane = _lane("Pars", ["PARS"],
                     dimmer=[DimmerBlock(0.0, 16.0, intensity=200.0)])
        a = _config({"PARS": [_fixture("p1")]},
                    songs={"S": _song(lanes=[lane])})
        a.setlist.entries = [SetlistEntry(song="S"),
                             SetlistEntry(song="NotMorphed")]
        a.setlist.entries[0].trigger.mode = "smpte"
        a.setlist.entries[0].trigger.timecode = "01:00:02:00"
        return a, lane

    def test_empty_target_setlist_adopts_the_source(self):
        a, lane = self._source_with_setlist()
        b = _config({"WASH": [_fixture("w1", group="WASH")]})
        plan = MorphPlan(edges=[_edge(lane, "dimmer", "WASH")])
        result = compile_setlist(a, plan, b)
        apply_morph(result, b, plan, force=True)
        assert [e.song for e in b.setlist.entries] == ["S"]
        assert b.setlist.entries[0].trigger.mode == "smpte"
        assert b.setlist.entries[0].trigger.timecode == "01:00:02:00"
        # Deep copy: editing the venue trigger must not touch the master.
        b.setlist.entries[0].trigger.timecode = "09:09:09:09"
        assert a.setlist.entries[0].trigger.timecode == "01:00:02:00"

    def test_existing_target_setlist_wins(self):
        from config.models import SetlistEntry
        a, lane = self._source_with_setlist()
        b = _config({"WASH": [_fixture("w1", group="WASH")]})
        b.setlist.entries = [SetlistEntry(song="VenueOpener")]
        plan = MorphPlan(edges=[_edge(lane, "dimmer", "WASH")])
        result = compile_setlist(a, plan, b)
        apply_morph(result, b, plan, force=True)
        assert [e.song for e in b.setlist.entries] == ["VenueOpener"]


class TestFormat1Migration:
    """Format-1 plans keyed edges by per-song lane uuid, so the same wire
    was repeated once per song. migrate_legacy_edges() collapses them
    onto group selectors on load (2026-08-08, user decision).

    Sized from the real 12-song gig that exposed this: 293 edges
    expressing 39 distinct wires, all 14 (selector, sublane) keys routing
    identically in every song.
    """

    def _multi_song_source(self, songs=6):
        lanes = {}
        made = {}
        for i in range(songs):
            lane = _lane("Pars", ["PARS"],
                         dimmer=[DimmerBlock(0.0, 8.0, intensity=200.0)])
            lanes[f"S{i}"] = lane
            made[f"S{i}"] = _song(f"S{i}", lanes=[lane])
        return _config({"PARS": [_fixture("p1")]}, songs=made), lanes

    def _legacy(self, lane, sublane, target):
        """An edge as format 1 wrote it: keyed by the lane uuid."""
        return MorphEdge.from_dict({
            "source_lane_id": lane.lane_id,
            "source_lane_name": "Pars",
            "sublane": sublane,
            "target_group": target,
        })

    def test_per_song_duplicates_collapse_to_one_edge(self):
        a, lanes = self._multi_song_source()
        plan = MorphPlan(edges=[self._legacy(lane, "dimmer", "WASH")
                                for lane in lanes.values()])
        assert plan.needs_migration()
        assert len(plan.edges) == 6

        dropped = plan.migrate_legacy_edges(a)

        assert dropped == 5
        assert len(plan.edges) == 1
        assert plan.edges[0].source_group == "PARS"
        assert not plan.needs_migration()

    def test_migrated_plan_still_compiles_every_song(self):
        """The collapse must not lose coverage - one edge now drives all
        six songs, which is the entire point."""
        a, lanes = self._multi_song_source()
        b = _config({"WASH": [_fixture("w1", group="WASH")]})
        plan = MorphPlan(edges=[self._legacy(lane, "dimmer", "WASH")
                                for lane in lanes.values()])
        result = compile_setlist(a, plan, b)
        assert not result.report.has_errors
        assert set(result.songs) == set(lanes)
        for name in lanes:
            (out,) = result.songs[name].timeline_data.lanes
            assert [d for lb in out.light_blocks for d in lb.dimmer_blocks]

    def test_compile_migrates_and_says_so(self):
        a, lanes = self._multi_song_source()
        b = _config({"WASH": [_fixture("w1", group="WASH")]})
        plan = MorphPlan(edges=[self._legacy(lane, "dimmer", "WASH")
                                for lane in lanes.values()])
        result = compile_setlist(a, plan, b)
        notes = " ".join(n.format() for n in result.report.of_kind("note"))
        assert "migrated from format 1" in notes

    def test_distinct_wires_are_preserved_not_merged(self):
        """Collapsing must only drop DUPLICATES. Different targets off
        the same source are fan-out (design doc 3), and must survive."""
        a, lanes = self._multi_song_source(songs=3)
        plan = MorphPlan(edges=(
            [self._legacy(lane, "dimmer", "WASH") for lane in lanes.values()]
            + [self._legacy(lane, "dimmer", "SPOT") for lane in lanes.values()]
            + [self._legacy(lane, "colour", "WASH") for lane in lanes.values()]
        ))
        assert len(plan.edges) == 9
        plan.migrate_legacy_edges(a)
        wires = {(e.source_group, e.sublane, e.target_group)
                 for e in plan.edges}
        assert wires == {("PARS", "dimmer", "WASH"),
                         ("PARS", "dimmer", "SPOT"),
                         ("PARS", "colour", "WASH")}

    def test_unresolvable_legacy_edge_is_kept_and_flagged(self):
        """A lane id in no song must not be silently discarded - the
        user authored that routing and deserves to be told."""
        a, lanes = self._multi_song_source(songs=2)
        plan = MorphPlan(edges=[MorphEdge.from_dict({
            "source_lane_id": "ghost-uuid", "source_lane_name": "?",
            "sublane": "dimmer", "target_group": "WASH"})])
        plan.migrate_legacy_edges(a)
        assert len(plan.edges) == 1
        problems = plan.validate(source_config=a)
        assert any("needs migrate_legacy_edges" in p for p in problems)

    def test_saved_plan_is_format_2_and_drops_lane_keys(self):
        a, lanes = self._multi_song_source(songs=2)
        plan = MorphPlan(edges=[self._legacy(lane, "dimmer", "WASH")
                                for lane in lanes.values()])
        plan.migrate_legacy_edges(a)
        data = plan.to_dict()
        assert data["morphplan"] == 2
        assert "source_lane_id" not in data["edges"][0]
        assert data["edges"][0]["source_group"] == "PARS"

    def test_collapse_broadens_coverage_to_every_song(self):
        """Union semantics, decided 2026-08-08 after measuring the real
        gig: format 1 gave each song a DIFFERENT subset of the wires (the
        SBD plan ranged from 1 to 36 of 39, because auto-suggest gated
        each song on that song's lane content). Collapsing applies every
        wire to every song, which CHANGES compiled output - 9 of 12 SBD
        songs moved. That is intended: the per-song gaps were an artifact
        of being forced to wire per song, not a design.
        """
        rich = _lane("Pars", ["PARS"], dimmer=[DimmerBlock(0.0, 8.0)])
        poor = _lane("Pars", ["PARS"], dimmer=[DimmerBlock(0.0, 8.0)])
        a = _config({"PARS": [_fixture("p1")]},
                    songs={"Rich": _song("Rich", lanes=[rich]),
                           "Poor": _song("Poor", lanes=[poor])})
        b = _config({"WASH": [_fixture("w1", group="WASH")]})
        # Format 1: only "Rich" was ever wired.
        plan = MorphPlan(edges=[self._legacy(rich, "dimmer", "WASH")])
        plan.migrate_legacy_edges(a)

        result = compile_setlist(a, plan, b)
        assert not result.report.has_errors
        # "Poor" now renders too, off the same single edge.
        for name in ("Rich", "Poor"):
            (out,) = result.songs[name].timeline_data.lanes
            assert [d for lb in out.light_blocks
                    for d in lb.dimmer_blocks], f"{name} should render"
