# tests/unit/test_morph_checker_cli.py
"""Completeness checker (design doc 6) + the headless morph CLI: the
coverage table, gap detection against group capabilities, the unrouted
mirror view, and the end-to-end morph-from-disk path with report file,
validation exit and the --force destruction gate."""

import pytest

from config.models import (ColourBlock, Configuration, DimmerBlock, Fixture,
                           FixtureGroup, FixtureGroupCapabilities,
                           FixtureMode, LightBlock, LightLane, ShowPart,
                           Song, TimelineData, Universe)
from utils.morph.checker import check, group_capabilities
from utils.morph.plan import MorphEdge, MorphPlan


def _fixture(name, group="G"):
    return Fixture(universe=1, address=1, manufacturer="M", model="X",
                   current_mode="Std",
                   available_modes=[FixtureMode(name="Std", channels=1)],
                   name=name, group=group)


def _config(groups, songs=None, caps=None):
    cfg = Configuration(
        fixtures=[f for fx in groups.values() for f in fx],
        groups={n: FixtureGroup(n, list(fx), capabilities=(caps or {}).get(n))
                for n, fx in groups.items()},
        universes={1: Universe(id=1, name="U1", output={})})
    cfg.songs = songs or {}
    return cfg


def _song(lanes):
    return Song(name="S",
                parts=[ShowPart(name="All", color="#fff", signature="4/4",
                                bpm=120.0, num_bars=8,
                                transition="instant")],  # 16 s
                timeline_data=TimelineData(lanes=lanes))


def _lane(name, dimmer_spans=(), colour_spans=()):
    return LightLane(name=name, fixture_targets=["G"], light_blocks=[
        LightBlock(start_time=0.0, end_time=16.0, effect_name="x",
                   dimmer_blocks=[DimmerBlock(s, e) for s, e in dimmer_spans],
                   colour_blocks=[ColourBlock(s, e) for s, e in colour_spans])])


def _edge(lane, sublane, target, **kw):
    return MorphEdge(source_lane_id=lane.lane_id,
                     source_lane_name=lane.name, sublane=sublane,
                     target_group=target, **kw)


class TestChecker:
    def test_coverage_fractions_and_gap_rows(self):
        lane = _lane("Pars", dimmer_spans=[(0.0, 8.0)])   # 50% of 16 s
        a = _config({"G": [_fixture("p")]}, songs={"S": _song([lane])})
        caps = FixtureGroupCapabilities(has_dimmer=True, has_colour=True)
        b = _config({"WASH": [_fixture("w", "WASH")]},
                    caps={"WASH": caps})
        plan = MorphPlan(edges=[_edge(lane, "dimmer", "WASH")])
        result = check(a, plan, b)
        rows = {(r.target_group, r.sublane): r for r in result.coverage}
        assert rows[("WASH", "dimmer")].percent == 50
        assert rows[("WASH", "colour")].percent == 0   # capability, no feed
        gaps = result.gaps(group_capabilities(b))
        assert [(g.target_group, g.sublane) for g in gaps] == \
            [("WASH", "colour")]

    def test_overlapping_spans_union_not_sum(self):
        lane = _lane("Pars", dimmer_spans=[(0.0, 10.0), (6.0, 16.0)])
        a = _config({"G": [_fixture("p")]}, songs={"S": _song([lane])})
        b = _config({"WASH": [_fixture("w", "WASH")]})
        plan = MorphPlan(edges=[_edge(lane, "dimmer", "WASH")])
        result = check(a, plan, b)
        row = [r for r in result.coverage
               if r.sublane == "dimmer"][0]
        assert row.percent == 100

    def test_unrouted_mirror_view(self):
        lane = _lane("Pars", dimmer_spans=[(0.0, 8.0)],
                     colour_spans=[(0.0, 4.0)])
        a = _config({"G": [_fixture("p")]}, songs={"S": _song([lane])})
        b = _config({"WASH": [_fixture("w", "WASH")]})
        plan = MorphPlan(edges=[_edge(lane, "dimmer", "WASH")])
        result = check(a, plan, b)
        assert result.unrouted_sources == [("S", "Pars", "colour", 1)]

    def test_regenerate_counts_as_full_coverage(self):
        lane = _lane("Pars", dimmer_spans=[(0.0, 16.0)])
        a = _config({"G": [_fixture("p")]}, songs={"S": _song([lane])})
        b = _config({"WASH": [_fixture("w", "WASH")]})
        plan = MorphPlan(edges=[
            _edge(lane, "movement", "WASH", mode="regenerate",
                  regenerate_strategy="static_default")])
        result = check(a, plan, b)
        row = [r for r in result.coverage if r.sublane == "movement"][0]
        assert row.percent == 100

    def test_manual_regenerate_promises_nothing(self):
        lane = _lane("Pars", dimmer_spans=[(0.0, 16.0)])
        a = _config({"G": [_fixture("p")]}, songs={"S": _song([lane])})
        b = _config({"WASH": [_fixture("w", "WASH")]})
        plan = MorphPlan(edges=[
            _edge(lane, "movement", "WASH", mode="regenerate",
                  regenerate_strategy="manual")])
        result = check(a, plan, b)
        row = [r for r in result.coverage if r.sublane == "movement"][0]
        assert row.percent == 0


class TestMorphCli:
    def _write_pair(self, tmp_path):
        lane = _lane("Pars", dimmer_spans=[(0.0, 8.0)])
        a = _config({"G": [_fixture("p")]}, songs={"S": _song([lane])})
        b = _config({"WASH": [_fixture("w", "WASH")]})
        src = tmp_path / "gig.lms"
        dst = tmp_path / "venue.lms"
        a.save(str(src))
        b.save(str(dst))
        # lane_id changes on save/load? No - it serializes. Reload to
        # key the plan by the PERSISTED lane id.
        a2 = Configuration.load(str(src))
        lane2 = a2.songs["S"].timeline_data.lanes[0]
        plan = MorphPlan(edges=[_edge(lane2, "dimmer", "WASH")])
        plan_path = tmp_path / "venue.morphplan.yaml"
        plan.save(str(plan_path))
        return src, dst, plan_path

    def test_end_to_end_writes_project_and_report(self, tmp_path, capsys):
        from utils.morph_cli import run_morph_cli
        src, dst, plan_path = self._write_pair(tmp_path)
        out = tmp_path / "morphed.lms"
        report = tmp_path / "report.md"
        code = run_morph_cli([str(src), "--plan", str(plan_path),
                              "--target", str(dst), "--out", str(out),
                              "--report", str(report)])
        assert code == 0
        assert "Morphed 1 song(s)" in capsys.readouterr().out
        assert report.read_text(encoding="utf-8").startswith("# Morph")
        morphed = Configuration.load(str(out))
        assert morphed.songs["S"].lineage["app_version"]
        assert morphed.songs["S"].timeline_data.lanes[0].name == "WASH"

    def test_invalid_plan_exits_2(self, tmp_path, capsys):
        from utils.morph_cli import run_morph_cli
        src, dst, plan_path = self._write_pair(tmp_path)
        plan = MorphPlan.load(str(plan_path))
        plan.edges[0].target_group = "NOPE"
        plan.save(str(plan_path))
        code = run_morph_cli([str(src), "--plan", str(plan_path),
                              "--target", str(dst), "--out",
                              str(tmp_path / "x.lms")])
        assert code == 2
        assert "not in the target config" in capsys.readouterr().err

    def test_missing_file_exits_1(self, tmp_path, capsys):
        from utils.morph_cli import run_morph_cli
        code = run_morph_cli([str(tmp_path / "ghost.lms"), "--plan",
                              str(tmp_path / "p.yaml"), "--target",
                              str(tmp_path / "t.lms"), "--out",
                              str(tmp_path / "o.lms")])
        assert code == 1


class TestGroupCapabilityDetection:
    """group_capabilities without STORED capabilities (every real
    loaded config - nothing persists them): detect from the fixture
    definitions; assume-everything survives only for fixtures whose
    definitions cannot be found (2026-07-16, the fix that turned the
    patchbay gating on for real projects)."""

    def _bare_group_config(self, manufacturer, model):
        fixture = Fixture(universe=1, address=1, manufacturer=manufacturer,
                          model=model, current_mode="Std",
                          available_modes=[FixtureMode(name="Std",
                                                       channels=6)],
                          name="f1", group="G")
        cfg = Configuration(
            fixtures=[fixture],
            groups={"G": FixtureGroup("G", [fixture])},   # caps = None
            universes={1: Universe(id=1, name="U1", output={})})
        cfg.songs = {}
        return cfg

    def test_real_definition_gates(self):
        # A static RGB wash must NOT offer POSITION (the bundled
        # Stairville definition has no pan/tilt channels).
        cfg = self._bare_group_config("Stairville",
                                      "Wild Wash Pro 648 RGB LED")
        caps = group_capabilities(cfg)["G"]
        assert "dimmer" in caps and "colour" in caps
        assert "movement" not in caps

    def test_mover_definition_keeps_movement(self):
        cfg = self._bare_group_config("Varytec", "Hero Spot 60")
        caps = group_capabilities(cfg)["G"]
        assert "movement" in caps

    def test_unknown_definition_stays_conservative(self):
        cfg = self._bare_group_config("M", "X")
        assert group_capabilities(cfg)["G"] == \
            {"dimmer", "colour", "movement", "special"}

    def test_stored_capabilities_still_win(self):
        cfg = self._bare_group_config("Stairville",
                                      "Wild Wash Pro 648 RGB LED")
        cfg.groups["G"].capabilities = FixtureGroupCapabilities(
            has_dimmer=True)
        assert group_capabilities(cfg)["G"] == {"dimmer"}
