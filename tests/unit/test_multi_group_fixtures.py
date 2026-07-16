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


# ---------------------------------------------------------------------------
# Stage 3: group consumers (capabilities, autogen, live state, export)
# ---------------------------------------------------------------------------

def _multi_group_config(temp_dir, groups=("Front", "Warm")):
    """A config whose single fixture is a member of every listed group,
    loaded through Configuration.load so the derived FixtureGroup.fixtures
    lists are exactly what every consumer sees at runtime."""
    path = os.path.join(temp_dir, "consumers.yaml")
    _write_config_yaml(path, [
        _fixture_yaml_dict("Par 1", groups=list(groups)),
    ], groups=list(groups))
    return Configuration.load(path)


class TestCapabilityDetectionPerGroup:
    """create_workspace builds capabilities_map per group from the derived
    FixtureGroup.fixtures. A shared fixture must contribute its channels
    to EVERY group it is in, not only the primary."""

    DEFS = {
        "TestMfr_TestModel": {
            "channels": [
                {"name": "Dimmer", "preset": "IntensityDimmer"},
                {"name": "Red", "preset": "IntensityRed"},
            ],
        },
    }

    def test_shared_fixture_contributes_to_both_groups(self, temp_dir):
        from utils.fixture_utils import detect_fixture_group_capabilities

        config = _multi_group_config(temp_dir)
        # "Warm" contains ONLY the shared fixture: any capability seen
        # there can only have come from the secondary membership.
        for name in ("Front", "Warm"):
            fixtures = config.groups[name].fixtures
            assert [f.name for f in fixtures] == ["Par 1"]
            caps = detect_fixture_group_capabilities(fixtures, self.DEFS)
            assert caps.has_dimmer, f"{name} lost the shared fixture's dimmer"
            assert caps.has_colour, f"{name} lost the shared fixture's colour"


class TestAutogenBucketing:
    """classify_fixture_groups drives lane creation (one lane per group).
    A fixture in two groups must make BOTH groups classifiable, so both
    get an autogen lane and the fixture receives blocks from each."""

    def test_shared_fixture_classifies_both_groups(self, temp_dir):
        from autogen.spatial import classify_fixture_groups

        config = _multi_group_config(temp_dir)
        classifications = classify_fixture_groups(config)

        assert "Front" in classifications
        assert "Warm" in classifications, (
            "secondary group was skipped as empty: the shared fixture did "
            "not contribute to it")
        # Both classifications are computed from the same (single) fixture,
        # so their spatial zone must match.
        assert classifications["Front"].zone == classifications["Warm"].zone


class TestLiveStateGroups:
    """The Live tab rebuilds its SELECT tiles and submaster bank from
    config.groups; a shared fixture's secondary group must get a
    submaster and resolve a level like any other group."""

    def test_update_from_config_seeds_every_membership_group(self, temp_dir,
                                                              qapp):
        from gui.tabs.live_tab import LiveState

        config = _multi_group_config(temp_dir)
        state = LiveState()
        state.update_from_config(config.groups.keys())

        assert set(state.submasters) == {"Front", "Warm"}
        assert state.group_level("Front") == 1.0
        assert state.group_level("Warm") == 1.0
        # Tile counts come from the derived membership.
        assert len(config.groups["Warm"].fixtures) == 1


# ---------------------------------------------------------------------------
# Stage 4: timeline group-centric lanes (lane targets, indexed targets,
# lane capabilities, FIX count, autogen generator lanes)
# ---------------------------------------------------------------------------

def _shared_fixture_config(temp_dir):
    """Three fixtures in patch order: 'Solo A' (Front only), 'Shared'
    (Front AND Warm), 'Solo B' (Warm only). Loaded through
    Configuration.load so the derived FixtureGroup.fixtures lists are
    exactly what lanes see at runtime:

        Front = [Solo A, Shared]   (Shared at index 1)
        Warm  = [Shared, Solo B]   (Shared at index 0)
    """
    path = os.path.join(temp_dir, "lanes.yaml")
    _write_config_yaml(path, [
        _fixture_yaml_dict("Solo A", groups=["Front"]),
        _fixture_yaml_dict("Shared", groups=["Front", "Warm"]),
        _fixture_yaml_dict("Solo B", groups=["Warm"]),
    ], groups=["Front", "Warm"])
    return Configuration.load(path)


class TestLaneTargetResolution:
    """The core stage-4 promise: two lanes targeting groups A and B, a
    fixture in both groups resolves into BOTH lanes (the lane-level path
    every timeline/export/playback consumer uses)."""

    def test_shared_fixture_resolves_into_both_lanes(self, temp_dir):
        from utils.target_resolver import resolve_targets

        config = _shared_fixture_config(temp_dir)
        shared = next(f for f in config.fixtures if f.name == "Shared")

        lane_a_targets = ["Front"]  # autogen-style: one lane per group
        lane_b_targets = ["Warm"]
        resolved_a = resolve_targets(lane_a_targets, config)
        resolved_b = resolve_targets(lane_b_targets, config)

        assert any(f is shared for f in resolved_a)
        assert any(f is shared for f in resolved_b)
        assert [f.name for f in resolved_a] == ["Solo A", "Shared"]
        assert [f.name for f in resolved_b] == ["Shared", "Solo B"]

    def test_resolve_targets_unique_dedups_shared_fixture_in_one_lane(
            self, temp_dir):
        """A single lane targeting BOTH groups addresses the shared
        fixture once (this is the export path: shows_to_xml and the
        ArtNet controllers resolve per lane via resolve_targets_unique)."""
        from utils.target_resolver import resolve_targets, resolve_targets_unique

        config = _shared_fixture_config(temp_dir)
        targets = ["Front", "Warm"]
        # Raw resolution sees the fixture once per membership...
        assert [f.name for f in resolve_targets(targets, config)] == \
            ["Solo A", "Shared", "Shared", "Solo B"]
        # ...the unique path collapses it to one instance per lane.
        unique = resolve_targets_unique(targets, config)
        assert [f.name for f in unique] == ["Solo A", "Shared", "Solo B"]
        assert len(unique) == len({id(f) for f in unique})


class TestIndexedTargetSemantics:
    """`Group:N` means position N in that group's DERIVED fixture list
    (config.fixtures patch order filtered by membership). A shared
    fixture's index therefore differs per group; each resolves to the
    same fixture object."""

    def test_shared_fixture_index_differs_per_group(self, temp_dir):
        from utils.target_resolver import resolve_target

        config = _shared_fixture_config(temp_dir)
        shared = next(f for f in config.fixtures if f.name == "Shared")

        front_hit = resolve_target("Front:1", config)
        warm_hit = resolve_target("Warm:0", config)
        assert len(front_hit) == 1 and front_hit[0] is shared
        assert len(warm_hit) == 1 and warm_hit[0] is shared
        # And the non-shared neighbours stay addressable around it.
        assert resolve_target("Front:0", config)[0].name == "Solo A"
        assert resolve_target("Warm:1", config)[0].name == "Solo B"

    def test_indexed_target_validation_uses_derived_length(self, temp_dir):
        from utils.target_resolver import validate_targets

        config = _shared_fixture_config(temp_dir)
        assert validate_targets(["Front:1", "Warm:0"], config) == []
        warnings = validate_targets(["Warm:2"], config)
        assert len(warnings) == 1 and "out of range" in warnings[0]

    def test_display_name_resolves_per_group_index(self, temp_dir):
        from utils.target_resolver import get_target_display_name

        config = _shared_fixture_config(temp_dir)
        assert get_target_display_name("Front:1", config) == "Front: Shared"
        assert get_target_display_name("Warm:0", config) == "Warm: Shared"

    def test_derivation_order_is_patch_order_in_both_paths(self, temp_dir,
                                                           qapp):
        """Indexed targets are only stable if every derivation path
        orders a group's fixtures identically: config.fixtures (patch)
        order. Configuration.load and fixtures_tab._update_groups must
        agree."""
        from gui.theme_manager import ThemeManager
        from gui.tabs.fixtures_tab import FixturesTab

        config = _shared_fixture_config(temp_dir)
        loaded_order = {
            name: [f.name for f in group.fixtures]
            for name, group in config.groups.items()
        }
        assert loaded_order == {"Front": ["Solo A", "Shared"],
                                "Warm": ["Shared", "Solo B"]}

        ThemeManager().apply(qapp, "dark")
        tab = FixturesTab(config, parent=None)
        try:
            tab._update_groups()
            rebuilt_order = {
                name: [f.name for f in group.fixtures]
                for name, group in config.groups.items()
            }
            assert rebuilt_order == loaded_order
        finally:
            tab.deleteLater()


class TestLaneCapabilitiesSharedFixture:
    """Lane capability detection (detect_targets_capabilities is what
    LightLaneWidget._detect_group_capabilities calls) must include the
    shared fixture's capabilities in EVERY lane that targets one of its
    groups."""

    DEFS = {
        "TestMfr_TestModel": {
            "channels": [
                {"name": "Dimmer", "preset": "IntensityDimmer"},
                {"name": "Red", "preset": "IntensityRed"},
            ],
        },
    }

    def test_both_lanes_detect_shared_fixture_capabilities(self, temp_dir):
        from utils.target_resolver import detect_targets_capabilities

        config = _multi_group_config(temp_dir)  # one fixture, two groups
        for lane_targets in (["Front"], ["Warm"]):
            caps = detect_targets_capabilities(
                lane_targets, config, self.DEFS)
            assert caps.has_dimmer, f"lane {lane_targets} lost the dimmer"
            assert caps.has_colour, f"lane {lane_targets} lost the colour"


class TestLaneFixtureCountSharedFixture:
    """The lane header's N FIX label counts DISTINCT fixtures the lane
    targets (LightLaneWidget._fixture_count docstring). A multi-group
    fixture counts once in each of its groups' lanes, and once per lane
    even when one lane reaches it through several of its groups."""

    def _lane_widget(self, config, targets, qapp):
        from timeline.light_lane import LightLane
        from timeline_ui.light_lane_widget import LightLaneWidget
        lane = LightLane(name="Lane", fixture_targets=list(targets))
        return LightLaneWidget(
            lane=lane, fixture_groups=list(config.groups.keys()),
            config=config)

    def test_counts_once_in_each_groups_lane(self, temp_dir, qapp):
        config = _shared_fixture_config(temp_dir)
        for targets, expected in ((["Front"], 2), (["Warm"], 2)):
            widget = self._lane_widget(config, targets, qapp)
            try:
                assert widget._fixture_count() == expected
                assert widget.fix_count_label.text() == f"{expected} FIX"
            finally:
                widget.deleteLater()

    def test_lane_targeting_both_groups_counts_shared_once(self, temp_dir,
                                                           qapp):
        """3 distinct fixtures across Front+Warm; the shared one must
        not be double-counted just because both its groups are
        targeted."""
        config = _shared_fixture_config(temp_dir)
        widget = self._lane_widget(config, ["Front", "Warm"], qapp)
        try:
            assert widget._fixture_count() == 3
        finally:
            widget.deleteLater()

    def test_indexed_targets_to_same_fixture_count_once(self, temp_dir,
                                                        qapp):
        config = _shared_fixture_config(temp_dir)
        widget = self._lane_widget(config, ["Front:1", "Warm:0"], qapp)
        try:
            assert widget._fixture_count() == 1
        finally:
            widget.deleteLater()

    def test_out_of_range_indexed_target_counts_nothing(self, temp_dir,
                                                        qapp):
        config = _shared_fixture_config(temp_dir)
        widget = self._lane_widget(config, ["Warm:9"], qapp)
        try:
            assert widget._fixture_count() == 0
        finally:
            widget.deleteLater()


class TestGeneratorLanesSharedFixture:
    """generate_show builds one lane per classified group; a shared
    fixture must land in BOTH groups' lanes' resolved targets (audio
    analysis is stubbed - lane construction is what is under test)."""

    def test_generator_lanes_cover_every_membership(self, temp_dir,
                                                    monkeypatch):
        import autogen.generator as generator
        from audio.spectral_analysis import SectionAnalysis, SongAnalysis
        from config.models import ShowPart
        from timeline.song_structure import SongStructure
        from utils.target_resolver import resolve_targets

        config = _shared_fixture_config(temp_dir)
        shared = next(f for f in config.fixtures if f.name == "Shared")

        structure = SongStructure()
        structure.load_from_show_parts([
            ShowPart(name="Verse 1", color="#123456", signature="4/4",
                     bpm=120.0, num_bars=4, transition="instant"),
        ])

        def fake_analyze(audio_path, song_structure):
            sections = [
                SectionAnalysis(
                    name=part.name, start_time=part.start_time,
                    end_time=part.start_time + part.duration,
                    spectral_flux_avg=0.5, transient_sharpness=0.5,
                    spectral_richness=0.8, vocal_presence=0.2,
                    spectral_centroid_avg=2000.0, rms_energy=0.7,
                    spectral_contrast_avg=0.5,
                )
                for part in song_structure.parts
            ]
            last = song_structure.parts[-1]
            return SongAnalysis(
                sections=sections,
                duration=last.start_time + last.duration)

        monkeypatch.setattr(generator, "analyze_song", fake_analyze)

        # The inspector frame features are best-effort (try/except in
        # generate_show); stub them so no real librosa load is attempted.
        def fake_frame_features(audio_path):
            raise FileNotFoundError(audio_path)

        import audio.spectral_analysis as spectral_analysis
        monkeypatch.setattr(spectral_analysis, "compute_frame_features",
                            fake_frame_features)

        lanes, _report = generator.generate_show(
            "nonexistent.wav", structure, config)

        by_group = {}
        for lane in lanes:
            assert lane.fixture_targets, f"lane {lane.name} untargeted"
            by_group[lane.fixture_targets[0]] = lane
        assert {"Front", "Warm"} <= set(by_group)

        for group in ("Front", "Warm"):
            resolved = resolve_targets(by_group[group].fixture_targets,
                                       config)
            assert any(f is shared for f in resolved), (
                f"shared fixture missing from the {group} lane's "
                "resolved targets")


class TestWorkspaceExportMultiGroup:
    """Export decision (plan stage 3): groups reach the .qxw as
    per-capability ChannelsGroup lists, VC group controls and preset
    scenes, all built from the derived membership; the exporter never
    writes QLC+ <FixtureGroup> elements. QLC+ accepts the same fixture
    channel in any number of ChannelsGroups, so a multi-group fixture is
    emitted per-group while staying patched exactly once."""

    VC_OPTIONS = {
        "generate_vc": True,
        "group_controls": True,
        "scene_presets": False,
        "movement_presets": False,
        "show_buttons": False,
        "speed_dial": False,
        "master_presets": False,
        "dark_mode": False,
    }

    def _export_club_band_with_shared_fixture(self, tmp_path):
        import xml.etree.ElementTree as ET
        from utils.create_workspace import create_qlc_workspace

        repo_root = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", ".."))
        config = Configuration.load(
            os.path.join(repo_root, "demos", "rigs", "club_band.lms"))
        shared = next(f for f in config.fixtures if f.name == "Front PARs 1")
        assert shared.groups == ["Front PARs"]
        shared.groups.append("Back Wash")

        # Round-trip through save/load so the derived FixtureGroup lists
        # are rebuilt exactly the way a user-edited config would be.
        path = str(tmp_path / "club_band_multi.yaml")
        config.save(path)
        config = Configuration.load(path)
        assert "Front PARs 1" in [
            f.name for f in config.groups["Back Wash"].fixtures]

        out = str(tmp_path / "workspace.qxw")
        create_qlc_workspace(config, self.VC_OPTIONS, output_path=out)

        tree = ET.parse(out)  # parse-back: the export is well-formed XML
        root = tree.getroot()
        for el in root.iter():
            if "}" in el.tag:
                el.tag = el.tag.split("}", 1)[1]
        return config, root

    def test_shared_fixture_patched_once_and_in_both_groups(self, tmp_path):
        config, root = self._export_club_band_with_shared_fixture(tmp_path)
        engine = root.find("Engine")

        # Patched exactly once: <Fixture> elements come from
        # config.fixtures, not from group membership.
        fixture_elems = engine.findall("Fixture")
        assert len(fixture_elems) == len(config.fixtures)
        shared_ids = [fe.find("ID").text for fe in fixture_elems
                      if fe.find("Name").text == "Front PARs 1"]
        assert len(shared_ids) == 1
        shared_id = shared_ids[0]

        # The shared fixture's channels appear in the ChannelsGroups of
        # BOTH groups (per-group emission through derived membership).
        groups_containing = set()
        for cg in engine.findall("ChannelsGroup"):
            group_name = cg.get("Name", "").rsplit(" - ", 1)[0]
            ids = (cg.text or "").split(",")[0::2]
            if shared_id in ids:
                groups_containing.add(group_name)
        assert {"Front PARs", "Back Wash"} <= groups_containing

        # And no QLC+ <FixtureGroup> elements are emitted at all (the
        # single-membership-shaped structure we deliberately avoid).
        assert engine.findall("FixtureGroup") == []
