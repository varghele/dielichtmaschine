# tests/unit/test_group_topology.py
"""Deterministic group topology (v1.5 morphing prerequisite, phase 0 of
docs/focus-morphing-plan.md): FixtureGroup.fixture_order/order_mode, the
load snapshot for legacy configs (zero behavior change), spatial sort
for new groups, order survival through the Fixtures tab group rebuild,
and YAML round-trip."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from config.models import (Configuration, Fixture, FixtureGroup,
                           FixtureMode, Universe)


def _fixture(name, x=0.0, y=0.0, group="G"):
    return Fixture(universe=1, address=1, manufacturer="M", model="X",
                   current_mode="Std",
                   available_modes=[FixtureMode(name="Std", channels=1)],
                   name=name, group=group, x=x, y=y)


def _config(fixtures):
    groups = {}
    for f in fixtures:
        for g in f.groups:
            groups.setdefault(g, FixtureGroup(g, [])).fixtures.append(f)
    return Configuration(
        fixtures=fixtures, groups=groups,
        universes={1: Universe(id=1, name="U1", output={})})


class TestApplyOrder:
    def test_manual_snapshot_when_no_stored_order(self):
        group = FixtureGroup("G", [_fixture("b"), _fixture("a")])
        group.apply_fixture_order()
        assert [f.name for f in group.fixtures] == ["b", "a"]  # unchanged
        assert group.fixture_order == ["b", "a"]

    def test_stored_order_reorders(self):
        group = FixtureGroup("G", [_fixture("b"), _fixture("a")],
                             fixture_order=["a", "b"])
        group.apply_fixture_order()
        assert [f.name for f in group.fixtures] == ["a", "b"]

    def test_unknown_names_append_after_ordered(self):
        group = FixtureGroup("G", [_fixture("new"), _fixture("a")],
                             fixture_order=["a"])
        group.apply_fixture_order()
        assert [f.name for f in group.fixtures] == ["a", "new"]

    def test_spatial_sorts_by_x_then_y(self):
        group = FixtureGroup(
            "G", [_fixture("right", x=2.0), _fixture("left", x=-2.0),
                  _fixture("mid-back", x=0.0, y=1.0),
                  _fixture("mid-front", x=0.0, y=-1.0)],
            order_mode="spatial")
        group.apply_fixture_order()
        assert [f.name for f in group.fixtures] == [
            "left", "mid-front", "mid-back", "right"]
        assert group.fixture_order == ["left", "mid-front",
                                       "mid-back", "right"]

    def test_sort_spatially_switches_mode(self):
        group = FixtureGroup("G", [_fixture("b", x=1.0),
                                   _fixture("a", x=-1.0)])
        group.sort_spatially()
        assert group.order_mode == "spatial"
        assert [f.name for f in group.fixtures] == ["a", "b"]

    def test_set_manual_order_pins_explicitly(self):
        group = FixtureGroup("G", [_fixture("a", x=-1.0),
                                   _fixture("b", x=1.0)],
                             order_mode="spatial")
        group.set_manual_order(["b", "a"])
        assert group.order_mode == "manual"
        assert [f.name for f in group.fixtures] == ["b", "a"]


class TestPersistence:
    def test_legacy_config_loads_with_identical_order(self, tmp_path):
        """The zero-behavior-change guarantee: a config with no stored
        order derives exactly today's order and snapshots it."""
        cfg = _config([_fixture("z", x=5.0), _fixture("a", x=-5.0)])
        path = tmp_path / "legacy.yaml"
        cfg.save(str(path))
        # Strip the new keys to simulate a pre-v1.5 file.
        import yaml
        data = yaml.safe_load(open(path, encoding="utf-8"))
        for g in data["groups"].values():
            g.pop("fixture_order", None)
            g.pop("order_mode", None)
        yaml.safe_dump(data, open(path, "w", encoding="utf-8"))

        loaded = Configuration.load(str(path))
        assert [f.name for f in loaded.groups["G"].fixtures] == ["z", "a"]
        assert loaded.groups["G"].fixture_order == ["z", "a"]
        assert loaded.groups["G"].order_mode == "manual"

    def test_round_trip_preserves_order_and_mode(self, tmp_path):
        cfg = _config([_fixture("b", x=1.0), _fixture("a", x=-1.0)])
        cfg.groups["G"].sort_spatially()
        path = tmp_path / "cfg.yaml"
        cfg.save(str(path))
        loaded = Configuration.load(str(path))
        assert loaded.groups["G"].order_mode == "spatial"
        assert [f.name for f in loaded.groups["G"].fixtures] == ["a", "b"]

    def test_stored_manual_order_beats_fixture_list_order(self, tmp_path):
        cfg = _config([_fixture("b"), _fixture("a")])
        cfg.groups["G"].set_manual_order(["a", "b"])
        path = tmp_path / "cfg.yaml"
        cfg.save(str(path))
        loaded = Configuration.load(str(path))
        # fixtures serialize as [b, a] but the group order pins [a, b]
        assert [f.name for f in loaded.groups["G"].fixtures] == ["a", "b"]


class TestTabRebuildSurvival:
    def test_update_groups_preserves_order_and_mode(self, qapp):
        from gui.theme_manager import ThemeManager
        from gui.tabs.fixtures_tab import FixturesTab
        ThemeManager().apply(qapp, "dark")
        cfg = _config([_fixture("b", x=1.0), _fixture("a", x=-1.0)])
        cfg.groups["G"].set_manual_order(["b", "a"])
        tab = FixturesTab(cfg, parent=None)
        tab._update_groups()
        assert [f.name for f in cfg.groups["G"].fixtures] == ["b", "a"]
        assert cfg.groups["G"].order_mode == "manual"

    def test_new_group_via_create_is_spatial(self, qapp):
        from gui.theme_manager import ThemeManager
        from gui.tabs.fixtures_tab import FixturesTab
        ThemeManager().apply(qapp, "dark")
        cfg = _config([_fixture("a")])
        tab = FixturesTab(cfg, parent=None)
        tab._create_group("Fresh")
        assert cfg.groups["Fresh"].order_mode == "spatial"


class TestImportOrdering:
    def test_apply_fixture_list_snapshots_import_order(self):
        from utils.fixture_io import apply_fixture_list
        cfg = _config([])
        fixtures = [_fixture("second", x=9.0), _fixture("first", x=-9.0)]
        apply_fixture_list(cfg, fixtures, replace=True)
        group = cfg.groups["G"]
        # Import order is kept (manual), not spatially re-sorted.
        assert [f.name for f in group.fixtures] == ["second", "first"]
        assert group.fixture_order == ["second", "first"]
