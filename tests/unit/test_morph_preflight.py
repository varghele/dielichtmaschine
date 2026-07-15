# tests/unit/test_morph_preflight.py
"""Pre-flight checklist model (design doc 7, phase 5 of the plan):
generation order and contents from plan + setlist, the fix-and-re-test
loop, persistence with completion state, and the export guard
(incomplete and stale-after-calibration cases)."""

import pytest

from config.models import (Configuration, DimmerBlock, Fixture,
                           FixtureGroup, FixtureGroupCapabilities,
                           FixtureMode, LightBlock, LightLane,
                           MovementBlock, ShowPart, Song, Spot,
                           TimelineData, Universe)
from utils.morph.plan import MorphEdge, MorphPlan
from utils.morph.preflight import (PreflightChecklist, PreflightItem,
                                   export_guard_message,
                                   generate_checklist)


def _fixture(name, group="G"):
    return Fixture(universe=1, address=1, manufacturer="M", model="X",
                   current_mode="Std",
                   available_modes=[FixtureMode(name="Std", channels=1)],
                   name=name, group=group)


def _rig():
    lane = LightLane(name="Pars", fixture_targets=["G"], light_blocks=[
        LightBlock(0.0, 16.0, "x",
                   dimmer_blocks=[DimmerBlock(0.0, 16.0)],
                   movement_blocks=[MovementBlock(
                       0.0, 16.0, target_spot_name="Centre")])])
    song = Song(name="S",
                parts=[ShowPart(name="All", color="#fff", signature="4/4",
                                bpm=120.0, num_bars=8,
                                transition="instant")],
                timeline_data=TimelineData(lanes=[lane]))
    a = Configuration(fixtures=[_fixture("p")],
                      groups={"G": FixtureGroup("G", [_fixture("p")])},
                      universes={1: Universe(id=1, name="U", output={})})
    a.songs = {"S": song}
    b = Configuration(
        fixtures=[_fixture("w", "WASH"), _fixture("m", "MOVERS")],
        groups={"WASH": FixtureGroup(
                    "WASH", [_fixture("w", "WASH")],
                    capabilities=FixtureGroupCapabilities(
                        has_dimmer=True, has_colour=True)),
                "MOVERS": FixtureGroup(
                    "MOVERS", [_fixture("m", "MOVERS")],
                    capabilities=FixtureGroupCapabilities(
                        has_dimmer=True, has_movement=True))},
        universes={1: Universe(id=1, name="U", output={})})
    b.spots = {"Centre": Spot(name="Centre", x=0.0, y=0.0, z=0.0)}
    b.songs = {}
    plan = MorphPlan(edges=[
        MorphEdge(source_lane_id=lane.lane_id, source_lane_name="Pars",
                  sublane="dimmer", target_group="WASH"),
        MorphEdge(source_lane_id=lane.lane_id, source_lane_name="Pars",
                  sublane="colour", target_group="WASH"),
        MorphEdge(source_lane_id=lane.lane_id, source_lane_name="Pars",
                  sublane="movement", target_group="MOVERS"),
    ])
    return a, plan, b


class TestGeneration:
    def test_order_and_contents(self):
        a, plan, b = _rig()
        checklist = generate_checklist(a, plan, b)
        kinds = [item.kind for item in checklist.items]
        # flash first (dimmer/colour-routed groups only, design doc
        # 7.3 - MOVERS gets movement only, so no flash), then
        # aim/focus, colour sanity, final scrub
        assert kinds == ["flash", "spot_verify",
                         "focus_capture", "colour_sanity", "scrub"]
        aim = [i for i in checklist.items if i.kind == "spot_verify"][0]
        assert aim.group == "MOVERS"
        assert aim.drive_state == {"group": "MOVERS",
                                   "action": "aim_spot",
                                   "spot": "Centre"}

    def test_manual_regenerate_generates_no_items(self):
        a, plan, b = _rig()
        for edge in plan.edges:
            edge.mode = "regenerate"
            edge.regenerate_strategy = "manual"
        checklist = generate_checklist(a, plan, b)
        assert [i.kind for i in checklist.items] == ["scrub"]


class TestChecklistState:
    def test_fix_and_retest_loop(self):
        a, plan, b = _rig()
        checklist = generate_checklist(a, plan, b)
        first = checklist.items[0]
        checklist.mark_done(first.item_id, result="ok", stamp="16:42")
        assert first.done and first.completed_at == "16:42"
        checklist.reopen(first.item_id)
        assert not first.done and first.result == ""

    def test_complete_requires_every_item(self):
        a, plan, b = _rig()
        checklist = generate_checklist(a, plan, b)
        assert not checklist.complete
        for item in checklist.items:
            checklist.mark_done(item.item_id)
        assert checklist.complete

    def test_round_trip(self, tmp_path):
        a, plan, b = _rig()
        checklist = generate_checklist(a, plan, b)
        checklist.plan_hash = "p" * 8
        checklist.mark_done(checklist.items[0].item_id, stamp="12:00")
        path = tmp_path / "venue.preflight.yaml"
        checklist.save(str(path))
        loaded = PreflightChecklist.load(str(path))
        assert loaded.plan_hash == "p" * 8
        assert loaded.items[0].done
        assert loaded.items[1].done is False
        assert loaded.items[0].drive_state == \
            checklist.items[0].drive_state

    def test_default_path_sits_next_to_the_config(self):
        assert PreflightChecklist.default_path(
            r"C:\gigs\venue.lms").endswith("venue.preflight.yaml")


class TestExportGuard:
    def _saved(self, tmp_path, complete, completed_hash=""):
        a, plan, b = _rig()
        checklist = generate_checklist(a, plan, b)
        if complete:
            for item in checklist.items:
                checklist.mark_done(item.item_id)
            checklist.completed_target_hash = completed_hash
        path = tmp_path / "venue.preflight.yaml"
        checklist.save(str(path))
        return str(path)

    def test_no_checklist_no_warning(self, tmp_path):
        assert export_guard_message(
            str(tmp_path / "ghost.yaml"), "abc") is None

    def test_incomplete_warns_hard(self, tmp_path):
        path = self._saved(tmp_path, complete=False)
        message = export_guard_message(path, "abc")
        assert message and "INCOMPLETE" in message

    def test_stale_after_calibration_warns(self, tmp_path):
        path = self._saved(tmp_path, complete=True,
                           completed_hash="old-hash")
        message = export_guard_message(path, "new-hash")
        assert message and "changed AFTER" in message

    def test_complete_and_current_is_clear(self, tmp_path):
        path = self._saved(tmp_path, complete=True,
                           completed_hash="same")
        assert export_guard_message(path, "same") is None
