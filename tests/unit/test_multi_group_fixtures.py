# tests/unit/test_multi_group_fixtures.py
"""Multi-group fixtures, stage 1 (docs/multi-group-fixtures-plan.md).

Pins the model change: `Fixture.groups: List[str]` is the source of
truth (groups[0] = primary, first group wins), `Fixture.group` is a
compat property (getter = primary, setter REPLACES the list), legacy
single-group YAML/JSON migrates on load, saves dual-write `groups` plus
the legacy `group` key, and every group-membership derivation puts a
fixture in EVERY group it lists.
"""

from __future__ import annotations

import os

import pytest
import yaml

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from config.models import (
    Configuration, Fixture, FixtureGroup, FixtureMode, fixture_asdict,
)


def make_fixture(name="F1", **kwargs):
    defaults = dict(
        universe=1, address=1, manufacturer="TestMfr", model="TestModel",
        name=name, current_mode="Standard",
        available_modes=[FixtureMode(name="Standard", channels=6)],
    )
    defaults.update(kwargs)
    return Fixture(**defaults)


# ---------------------------------------------------------------------------
# Field + property semantics
# ---------------------------------------------------------------------------

class TestGroupsFieldAndProperty:

    def test_default_is_ungrouped(self):
        f = make_fixture()
        assert f.groups == []
        assert f.group == ""

    def test_groups_list_and_primary(self):
        f = make_fixture(groups=["A", "B"])
        assert f.groups == ["A", "B"]
        # groups[0] is the primary group (first group wins).
        assert f.group == "A"

    def test_setter_replaces_whole_list(self):
        f = make_fixture(groups=["A", "B"])
        f.group = "C"
        assert f.groups == ["C"]

    def test_setter_empty_string_clears(self):
        f = make_fixture(groups=["A", "B"])
        f.group = ""
        assert f.groups == []

    def test_groups_list_is_directly_mutable(self):
        f = make_fixture(groups=["A"])
        f.groups.append("B")
        assert f.group == "A"
        assert f.groups == ["A", "B"]


class TestConstructorCompat:

    def test_legacy_group_keyword(self):
        f = make_fixture(group="X")
        assert f.groups == ["X"]
        assert f.group == "X"

    def test_legacy_group_empty_string(self):
        f = make_fixture(group="")
        assert f.groups == []

    def test_groups_keyword(self):
        f = make_fixture(groups=["X", "Y"])
        assert f.groups == ["X", "Y"]

    def test_groups_wins_over_legacy_group(self):
        # Dual-written dicts carry both; `groups` is the source of truth.
        f = make_fixture(group="Old", groups=["A", "B"])
        assert f.groups == ["A", "B"]

    def test_dual_keys_with_empty_groups_fall_back_to_group(self):
        f = make_fixture(group="Solo", groups=[])
        assert f.groups == ["Solo"]

    def test_groups_none_is_defensively_empty(self):
        # A YAML `groups:` key that is present but null.
        f = make_fixture(groups=None)
        assert f.groups == []

    def test_equality_between_legacy_and_new_construction(self):
        assert make_fixture(group="X") == make_fixture(groups=["X"])


# ---------------------------------------------------------------------------
# asdict / fingerprint / dual-write dict
# ---------------------------------------------------------------------------

class TestSerializationDicts:

    def test_asdict_emits_groups_not_legacy_group(self):
        from dataclasses import asdict
        d = asdict(make_fixture(groups=["A", "B"]))
        assert d["groups"] == ["A", "B"]
        # `group` is an InitVar + property, not a field: asdict skips it.
        assert "group" not in d

    def test_autosave_fingerprint_path(self):
        """gui.py fingerprints via hash(repr(asdict(config)))."""
        from dataclasses import asdict
        config = Configuration(fixtures=[make_fixture(groups=["A", "B"])])
        fp1 = hash(repr(asdict(config)))
        config.fixtures[0].groups.append("C")
        fp2 = hash(repr(asdict(config)))
        assert fp1 != fp2

    def test_fixture_asdict_dual_writes_legacy_group(self):
        d = fixture_asdict(make_fixture(groups=["A", "B"]))
        assert d["groups"] == ["A", "B"]
        assert d["group"] == "A"

    def test_fixture_asdict_ungrouped(self):
        d = fixture_asdict(make_fixture())
        assert d["groups"] == []
        assert d["group"] == ""


# ---------------------------------------------------------------------------
# Config YAML load migration + save dual-write
# ---------------------------------------------------------------------------

def _fixture_yaml_dict(name, **extra):
    d = {
        "universe": 1, "address": 1, "manufacturer": "TestMfr",
        "model": "TestModel", "name": name, "current_mode": "Standard",
        "available_modes": [{"name": "Standard", "channels": 6}],
    }
    d.update(extra)
    return d


def _write_config_yaml(path, fixtures, groups):
    data = {
        "fixtures": fixtures,
        "groups": {
            name: {"name": name, "color": "#112233", "fixtures": []}
            for name in groups
        },
    }
    with open(path, "w") as f:
        yaml.dump(data, f, default_flow_style=False)


class TestLoadMigration:

    def test_legacy_single_group_migrates_to_list(self, temp_dir):
        path = os.path.join(temp_dir, "legacy.yaml")
        _write_config_yaml(path, [
            _fixture_yaml_dict("Par 1", group="Front"),
            _fixture_yaml_dict("Loose", group=""),
        ], groups=["Front"])

        config = Configuration.load(path)
        by_name = {f.name: f for f in config.fixtures}
        assert by_name["Par 1"].groups == ["Front"]
        assert by_name["Par 1"].group == "Front"
        assert by_name["Loose"].groups == []
        assert [f.name for f in config.groups["Front"].fixtures] == ["Par 1"]

    def test_new_format_groups_loads_as_is(self, temp_dir):
        path = os.path.join(temp_dir, "new.yaml")
        _write_config_yaml(path, [
            _fixture_yaml_dict("Par 1", groups=["Front", "Warm"]),
        ], groups=["Front", "Warm"])

        config = Configuration.load(path)
        assert config.fixtures[0].groups == ["Front", "Warm"]

    def test_dual_written_file_ignores_legacy_key(self, temp_dir):
        path = os.path.join(temp_dir, "dual.yaml")
        _write_config_yaml(path, [
            _fixture_yaml_dict("Par 1", group="Front",
                               groups=["Front", "Warm"]),
        ], groups=["Front", "Warm"])

        config = Configuration.load(path)
        assert config.fixtures[0].groups == ["Front", "Warm"]

    def test_multi_group_fixture_derives_into_both_groups(self, temp_dir):
        """FixtureGroup.fixtures stays derived: a fixture appears in
        every group it lists."""
        path = os.path.join(temp_dir, "multi.yaml")
        _write_config_yaml(path, [
            _fixture_yaml_dict("Par 1", groups=["Front", "Warm"]),
            _fixture_yaml_dict("Par 2", groups=["Front"]),
        ], groups=["Front", "Warm"])

        config = Configuration.load(path)
        front = [f.name for f in config.groups["Front"].fixtures]
        warm = [f.name for f in config.groups["Warm"].fixtures]
        assert front == ["Par 1", "Par 2"]
        assert warm == ["Par 1"]


class TestSaveDualWrite:

    def test_save_writes_groups_and_legacy_group(self, temp_dir):
        config = Configuration(
            fixtures=[make_fixture("Par 1", groups=["Front", "Warm"])],
            groups={"Front": FixtureGroup("Front", [])},
        )
        path = os.path.join(temp_dir, "saved.yaml")
        config.save(path)

        with open(path) as f:
            raw = yaml.safe_load(f)
        fd = raw["fixtures"][0]
        assert fd["groups"] == ["Front", "Warm"]
        assert fd["group"] == "Front"

    def test_save_ungrouped_writes_empty_legacy_group(self, temp_dir):
        config = Configuration(fixtures=[make_fixture("Solo")])
        path = os.path.join(temp_dir, "saved.yaml")
        config.save(path)

        with open(path) as f:
            raw = yaml.safe_load(f)
        fd = raw["fixtures"][0]
        assert fd["groups"] == []
        assert fd["group"] == ""

    def test_groups_section_fixture_dicts_dual_write_too(self, temp_dir):
        fixture = make_fixture("Par 1", groups=["Front"])
        config = Configuration(
            fixtures=[fixture],
            groups={"Front": FixtureGroup("Front", [fixture])},
        )
        path = os.path.join(temp_dir, "saved.yaml")
        config.save(path)

        with open(path) as f:
            raw = yaml.safe_load(f)
        gd = raw["groups"]["Front"]["fixtures"][0]
        assert gd["groups"] == ["Front"]
        assert gd["group"] == "Front"


class TestRoundTrip:

    def test_legacy_file_round_trip_keeps_membership(self, temp_dir):
        """Old single-group YAML -> load -> save -> reload: membership
        survives and the file has gained the `groups` list."""
        legacy = os.path.join(temp_dir, "legacy.yaml")
        _write_config_yaml(legacy, [
            _fixture_yaml_dict("Par 1", group="Front"),
            _fixture_yaml_dict("Loose", group=""),
        ], groups=["Front"])

        config = Configuration.load(legacy)
        resaved = os.path.join(temp_dir, "resaved.yaml")
        config.save(resaved)

        with open(resaved) as f:
            raw = yaml.safe_load(f)
        by_name = {fd["name"]: fd for fd in raw["fixtures"]}
        assert by_name["Par 1"]["groups"] == ["Front"]
        assert by_name["Par 1"]["group"] == "Front"
        assert by_name["Loose"]["groups"] == []

        reloaded = Configuration.load(resaved)
        by_name = {f.name: f for f in reloaded.fixtures}
        assert by_name["Par 1"].groups == ["Front"]
        assert by_name["Loose"].groups == []
        assert [f.name for f in reloaded.groups["Front"].fixtures] == ["Par 1"]

    def test_multi_group_round_trip(self, temp_dir):
        config = Configuration(
            fixtures=[make_fixture("Par 1", groups=["Front", "Warm"])],
            groups={"Front": FixtureGroup("Front", []),
                    "Warm": FixtureGroup("Warm", [])},
        )
        path = os.path.join(temp_dir, "multi.yaml")
        config.save(path)
        reloaded = Configuration.load(path)
        assert reloaded.fixtures[0].groups == ["Front", "Warm"]
        assert reloaded.fixtures[0].group == "Front"
        front = [f.name for f in reloaded.groups["Front"].fixtures]
        warm = [f.name for f in reloaded.groups["Warm"].fixtures]
        assert front == ["Par 1"]
        assert warm == ["Par 1"]


# ---------------------------------------------------------------------------
# Fixtures tab: _update_groups derivation (model semantics, not UI)
# ---------------------------------------------------------------------------

class TestFixturesTabDerivation:

    def test_update_groups_puts_fixture_in_every_listed_group(self, qapp):
        from gui.theme_manager import ThemeManager
        from gui.tabs.fixtures_tab import FixturesTab

        fixture = make_fixture("Par 1", groups=["Front", "Warm"])
        config = Configuration(fixtures=[fixture])
        ThemeManager().apply(qapp, "dark")
        tab = FixturesTab(config, parent=None)
        try:
            tab._update_groups()
            assert set(config.groups) >= {"Front", "Warm"}
            assert fixture in config.groups["Front"].fixtures
            assert fixture in config.groups["Warm"].fixtures
        finally:
            tab.deleteLater()


# ---------------------------------------------------------------------------
# Fixture list JSON import/export (utils/fixture_io.py)
# ---------------------------------------------------------------------------

class TestFixtureListJson:

    def _config(self, groups):
        fixture = make_fixture("Par 1", groups=groups)
        cfg = Configuration(fixtures=[fixture])
        for name in groups:
            cfg.groups.setdefault(name, FixtureGroup(name, []))
            cfg.groups[name].fixtures.append(fixture)
        return cfg

    def test_json_export_dual_writes_and_reimports(self, temp_dir):
        import json
        from utils.fixture_io import (
            read_fixture_list_json, write_fixture_list_json,
        )

        path = os.path.join(temp_dir, "rig.json")
        write_fixture_list_json(path, self._config(["Front", "Warm"]))

        with open(path) as f:
            raw = json.load(f)
        fd = raw["fixtures"][0]
        assert fd["groups"] == ["Front", "Warm"]
        assert fd["group"] == "Front"

        fixtures, _, _ = read_fixture_list_json(path)
        assert fixtures[0].groups == ["Front", "Warm"]

    def test_legacy_json_without_groups_migrates(self, temp_dir):
        import json
        from utils.fixture_io import (
            read_fixture_list_json, write_fixture_list_json,
        )

        path = os.path.join(temp_dir, "rig.json")
        write_fixture_list_json(path, self._config(["Front"]))
        with open(path) as f:
            raw = json.load(f)
        for fd in raw["fixtures"]:
            del fd["groups"]  # simulate a pre-stage-1 export
        with open(path, "w") as f:
            json.dump(raw, f)

        fixtures, _, _ = read_fixture_list_json(path)
        assert fixtures[0].groups == ["Front"]

    def test_apply_fixture_list_buckets_into_every_group(self):
        from utils.fixture_io import apply_fixture_list

        config = Configuration()
        apply_fixture_list(
            config, [make_fixture("Par 1", groups=["Front", "Warm"])])
        assert [f.name for f in config.groups["Front"].fixtures] == ["Par 1"]
        assert [f.name for f in config.groups["Warm"].fixtures] == ["Par 1"]
