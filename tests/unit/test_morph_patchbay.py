# tests/unit/test_morph_patchbay.py
"""The morph patchbay widget (v1.5b phase 4, mockup 6d): capability
gated docking, lane-level patches (dashed fan-out), edge mode /
transform / priority operations, the lock round-trip into
plan.protected_target_lanes, auto-suggest (role first, capability
overlap second, add-only), the live checker strip data, and the
editor's hand-edit provenance hook. All through the widget's plain
model methods - no mouse events, offscreen platform."""

import pytest

from config.models import (ColourBlock, Configuration, DimmerBlock, Fixture,
                           FixtureGroup, FixtureGroupCapabilities,
                           FixtureMode, LightBlock, LightLane, MovementBlock,
                           ShowPart, Song, TimelineData, Universe)
from utils.morph.plan import MorphPlan


def _fixture(name, x=0.0, group="G"):
    return Fixture(universe=1, address=1, manufacturer="M", model="X",
                   current_mode="Std",
                   available_modes=[FixtureMode(name="Std", channels=1)],
                   name=name, group=group, x=x)


def _group(name, fixtures, caps, role=""):
    group = FixtureGroup(name, fixtures, lighting_role=role)
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


def _song(name="S", lanes=None):
    return Song(name=name,
                parts=[ShowPart(name="All", color="#fff", signature="4/4",
                                bpm=120.0, num_bars=8,
                                transition="instant")],
                timeline_data=TimelineData(lanes=lanes or []))


def _lane(name, targets, dimmer=(), colour=(), movement=()):
    return LightLane(name=name, fixture_targets=list(targets),
                     light_blocks=[LightBlock(
                         start_time=0.0, end_time=16.0, effect_name="x",
                         dimmer_blocks=list(dimmer),
                         colour_blocks=list(colour),
                         movement_blocks=list(movement))])


@pytest.fixture
def rigs():
    """Source: a PARS lane (dimmer + colour) and a MOVERS lane
    (dimmer + movement). Target: WASH (dimmer+colour, backbone role),
    SPOT (dimmer+movement, movement role), STROBE (dimmer only)."""
    pars = _lane("Pars", ["PARS"],
                 dimmer=[DimmerBlock(0.0, 16.0, intensity=200.0)],
                 colour=[ColourBlock(0.0, 16.0, red=255.0)])
    movers = _lane("Movers", ["MOVERS"],
                   dimmer=[DimmerBlock(0.0, 8.0, intensity=180.0)],
                   movement=[MovementBlock(0.0, 8.0,
                                           effect_type="circle")])
    source = _config(
        [_group("PARS", [_fixture("p1")], {"dimmer", "colour"},
                role="backbone"),
         _group("MOVERS", [_fixture("m1", group="MOVERS")],
                {"dimmer", "movement"}, role="movement")],
        songs={"S": _song(lanes=[pars, movers])})
    target = _config(
        [_group("WASH", [_fixture("w1", group="WASH"),
                         _fixture("w2", x=1.0, group="WASH")],
                {"dimmer", "colour"}, role="backbone"),
         _group("SPOT", [_fixture("s1", group="SPOT")],
                {"dimmer", "movement"}, role="movement"),
         _group("STROBE", [_fixture("b1", group="STROBE")],
                {"dimmer"})])
    return source, target, pars, movers


@pytest.fixture
def patchbay(qapp, rigs):
    from gui.dialogs.morph_patchbay import MorphPatchbay
    source, target, _pars, _movers = rigs
    return MorphPatchbay(source, target)


class TestCapabilityGating:
    def test_matching_capability_docks(self, patchbay, rigs):
        _s, _t, pars, _m = rigs
        edge = patchbay.add_edge(pars.lane_id, "colour", "WASH")
        assert edge is not None
        assert edge.mode == "copy"
        assert patchbay.plan.edges == [edge]

    def test_missing_target_capability_is_refused(self, patchbay, rigs):
        _s, _t, pars, _m = rigs
        assert patchbay.add_edge(pars.lane_id, "colour", "STROBE") is None
        assert patchbay.plan.edges == []

    def test_empty_source_stream_is_refused(self, patchbay, rigs):
        # The PARS lane carries no special blocks; BEAM cannot wire.
        _s, _t, pars, _m = rigs
        assert patchbay.add_edge(pars.lane_id, "special", "WASH") is None

    def test_duplicate_edge_is_refused(self, patchbay, rigs):
        _s, _t, pars, _m = rigs
        assert patchbay.add_edge(pars.lane_id, "dimmer", "WASH")
        assert patchbay.add_edge(pars.lane_id, "dimmer", "WASH") is None
        assert len(patchbay.plan.edges) == 1

    def test_empty_movement_wires_as_regenerate(self, patchbay, rigs):
        # PARS has no movement -> the ghost POSITION chip's contract.
        _s, _t, pars, movers = rigs
        ghost = patchbay.add_edge(pars.lane_id, "movement", "SPOT")
        assert ghost.mode == "regenerate"
        assert ghost.regenerate_strategy == "manual"
        real = patchbay.add_edge(movers.lane_id, "movement", "SPOT")
        assert real.mode == "copy"


class TestLanePatch:
    def test_fans_out_to_shared_capabilities_only(self, patchbay, rigs):
        _s, _t, pars, _m = rigs
        added = patchbay.add_lane_patch(pars.lane_id, "WASH")
        assert sorted(e.sublane for e in added) == ["colour", "dimmer"]
        assert patchbay.is_lane_patch(pars.lane_id, "WASH")

    def test_single_stream_patch_is_not_marked(self, patchbay, rigs):
        _s, _t, pars, _m = rigs
        added = patchbay.add_lane_patch(pars.lane_id, "STROBE")
        assert [e.sublane for e in added] == ["dimmer"]
        assert not patchbay.is_lane_patch(pars.lane_id, "STROBE")

    def test_marker_clears_with_the_last_edge(self, patchbay, rigs):
        _s, _t, pars, _m = rigs
        added = patchbay.add_lane_patch(pars.lane_id, "WASH")
        for edge in added:
            patchbay.remove_edge(edge.edge_id)
        assert not patchbay.is_lane_patch(pars.lane_id, "WASH")
        assert patchbay.plan.edges == []

    def test_loaded_plan_derives_the_marker(self, qapp, rigs):
        from gui.dialogs.morph_patchbay import MorphPatchbay
        source, target, pars, _m = rigs
        first = MorphPatchbay(source, target)
        first.add_lane_patch(pars.lane_id, "WASH")
        second = MorphPatchbay(source, target, plan=first.plan)
        assert second.is_lane_patch(pars.lane_id, "WASH")


class TestEdgeOperations:
    def test_transform_flips_mode_and_replaces_same_kind(self, patchbay,
                                                         rigs):
        _s, _t, pars, _m = rigs
        edge = patchbay.add_edge(pars.lane_id, "dimmer", "WASH")
        patchbay.set_transform(edge.edge_id, "intensity_scale", factor=0.5)
        assert edge.mode == "copy_transform"
        patchbay.set_transform(edge.edge_id, "intensity_scale", factor=0.8)
        assert edge.transforms == [
            {"type": "intensity_scale", "factor": 0.8}]

    def test_transform_vocabulary_is_enforced(self, patchbay, rigs):
        _s, _t, pars, _m = rigs
        edge = patchbay.add_edge(pars.lane_id, "dimmer", "WASH")
        with pytest.raises(ValueError):
            patchbay.set_transform(edge.edge_id, "warp")
        with pytest.raises(ValueError):
            patchbay.set_transform(edge.edge_id, "intensity_scale")

    def test_clearing_the_last_transform_restores_copy(self, patchbay,
                                                       rigs):
        _s, _t, pars, _m = rigs
        edge = patchbay.add_edge(pars.lane_id, "dimmer", "WASH")
        patchbay.set_transform(edge.edge_id, "mirror")
        patchbay.clear_transform(edge.edge_id, "mirror")
        assert edge.transforms == []
        assert edge.mode == "copy"

    def test_priority_bumps_and_floors_at_zero(self, patchbay, rigs):
        _s, _t, pars, _m = rigs
        edge = patchbay.add_edge(pars.lane_id, "dimmer", "WASH")
        patchbay.bump_priority(edge.edge_id, +1)
        patchbay.bump_priority(edge.edge_id, +1)
        assert edge.priority == 2
        for _ in range(5):
            patchbay.bump_priority(edge.edge_id, -1)
        assert edge.priority == 0

    def test_regenerate_mode_with_strategy(self, patchbay, rigs):
        _s, _t, _pars, movers = rigs
        edge = patchbay.add_edge(movers.lane_id, "movement", "SPOT")
        patchbay.set_edge_mode(edge.edge_id, "regenerate",
                               "derive_from_intensity")
        assert edge.mode == "regenerate"
        assert edge.regenerate_strategy == "derive_from_intensity"


class TestLock:
    def test_round_trips_protected_target_lanes(self, patchbay):
        patchbay.set_lock("WASH", True)
        assert patchbay.plan.protected_target_lanes == ["WASH"]
        assert patchbay.is_locked("WASH")
        patchbay.set_lock("SPOT", True)
        assert patchbay.plan.protected_target_lanes == ["SPOT", "WASH"]
        patchbay.set_lock("WASH", False)
        assert patchbay.plan.protected_target_lanes == ["SPOT"]
        assert not patchbay.is_locked("WASH")


class TestAutoSuggest:
    def test_prefers_matching_role_then_overlap(self, patchbay, rigs):
        _s, _t, pars, movers = rigs
        added = patchbay.auto_suggest()
        wires = {(e.source_lane_name, e.sublane, e.target_group)
                 for e in added}
        assert wires == {("Pars", "dimmer", "WASH"),
                         ("Pars", "colour", "WASH"),
                         ("Movers", "dimmer", "SPOT"),
                         ("Movers", "movement", "SPOT")}

    def test_only_valid_edges(self, patchbay):
        from utils.morph.checker import group_capabilities
        caps = group_capabilities(patchbay.target_config)
        for edge in patchbay.auto_suggest():
            assert edge.sublane in caps[edge.target_group]
            assert patchbay.lane_content(
                edge.source_lane_id).get(edge.sublane)

    def test_adds_only_and_never_repeats(self, patchbay, rigs):
        _s, _t, pars, _m = rigs
        manual = patchbay.add_edge(pars.lane_id, "dimmer", "STROBE")
        first = patchbay.auto_suggest()
        assert manual in patchbay.plan.edges       # untouched
        assert patchbay.auto_suggest() == []       # nothing new
        assert len(patchbay.plan.edges) == 1 + len(first)


class TestCheckerStrip:
    def test_gap_on_an_unrouted_capability(self, patchbay, rigs):
        _s, _t, _pars, movers = rigs
        patchbay.add_edge(movers.lane_id, "dimmer", "SPOT")
        summary = {(g, s): (p, gap)
                   for g, s, p, gap in patchbay.coverage_summary()}
        assert summary[("SPOT", "dimmer")] == (50, False)  # 8s of 16s
        assert summary[("SPOT", "movement")] == (0, True)  # the gap

    def test_full_coverage_is_not_a_gap(self, patchbay, rigs):
        _s, _t, pars, _m = rigs
        patchbay.add_lane_patch(pars.lane_id, "WASH")
        summary = {(g, s): (p, gap)
                   for g, s, p, gap in patchbay.coverage_summary()}
        assert summary[("WASH", "dimmer")] == (100, False)
        assert summary[("WASH", "colour")] == (100, False)


class TestHandEditHook:
    """Design doc 5.3: the editor flips morphed provenance on touch."""

    def _stub(self, block):
        from timeline_ui.light_block_widget import LightBlockWidget

        class WidgetStub:
            _flip_morph_provenance = \
                LightBlockWidget._flip_morph_provenance
            _mark_hand_edit = LightBlockWidget._mark_hand_edit

        stub = WidgetStub()
        stub.block = block
        return stub

    def test_morphed_block_flips_to_hand_edited(self, qapp):
        block = LightBlock(start_time=0.0, end_time=4.0, effect_name="x",
                           provenance="morphed:abc123")
        stub = self._stub(block)
        stub._mark_hand_edit()
        assert block.provenance == "hand_edited"
        assert block.modified is True

    def test_authored_block_is_never_tagged(self, qapp):
        block = LightBlock(start_time=0.0, end_time=4.0, effect_name="x")
        stub = self._stub(block)
        stub._mark_hand_edit()
        assert block.provenance == ""
        assert block.modified is True

    def test_envelope_drag_flip_leaves_modified_alone(self, qapp):
        block = LightBlock(start_time=0.0, end_time=4.0, effect_name="x",
                           provenance="morphed:abc123")
        stub = self._stub(block)
        stub._flip_morph_provenance()
        assert block.provenance == "hand_edited"
        assert block.modified is False

    def test_every_edit_path_routes_through_the_hook(self):
        """No editor path may set block.modified directly: the single
        allowed assignment lives inside _mark_hand_edit itself."""
        import inspect
        import timeline_ui.light_block_widget as module
        source = inspect.getsource(module)
        assert source.count("self.block.modified = True") == 1
