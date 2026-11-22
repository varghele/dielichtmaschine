# tests/unit/test_config_migrations.py
"""Project file ``schema_version`` and the ordered migration steps.

Pins:

- ``config/migrations.py`` STEPS are contiguous (one step per version,
  0 -> CURRENT), uniquely named, and ``migrate`` runs exactly the
  pending ones in order: all of them for a version 0 (unstamped) file,
  none for a current file.
- A newer-than-this-build stamp loads best effort and warns; a garbage
  stamp is treated as 0 and warns.
- Every save (YAML, .lms, autosave) stamps CURRENT, and the stamp gates
  the steps (a stamped file is not migrated again).
- The version 0 -> 1 step reproduces the pre-versioning load: legacy
  ``shows:`` -> ``songs``, fixture ``group:`` -> ``groups``, deprecated
  ``direction`` / ``rotation`` dropped.
- Every legacy fixture and demo loads to the same model as its re-save.
"""

from __future__ import annotations

import os
import pickle
from dataclasses import asdict
from pathlib import Path

import pytest
import yaml

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from config import migrations
from config.migrations import (
    CURRENT_SCHEMA_VERSION, SCHEMA_VERSION_KEY, STEPS, MigrationStep,
    migrate, read_version, steps_between,
)
from config.models import (
    Configuration, Fixture, FixtureGroup, FixtureMode, Universe,
)
from utils import user_warnings
from utils.autosave import write_snapshot

REPO_ROOT = Path(__file__).resolve().parents[2]
LEGACY_FIXTURE = REPO_ROOT / "tests" / "fixtures" / "legacy_band_midsize.yaml"
PROJECT_FILES = sorted(
    list((REPO_ROOT / "tests" / "fixtures").glob("*.yaml"))
    + list((REPO_ROOT / "demos" / "rigs").glob("*.lms"))
    + list((REPO_ROOT / "demos" / "shows").glob("*.lms"))
    + list((REPO_ROOT / "demos" / "reference").glob("*.yaml")))


def _config():
    mode = FixtureMode(name="Standard", channels=6)
    fixtures = [
        Fixture(universe=1, address=1, manufacturer="TestMfr",
                model="TestModel", name="Par 1", current_mode="Standard",
                available_modes=[mode], groups=["Front"]),
        Fixture(universe=1, address=7, manufacturer="TestMfr",
                model="TestModel", name="Par 2", current_mode="Standard",
                available_modes=[mode], groups=["Front", "Warm"]),
    ]
    return Configuration(
        fixtures=fixtures,
        groups={"Front": FixtureGroup("Front", list(fixtures)),
                "Warm": FixtureGroup("Warm", [fixtures[1]])},
        universes={1: Universe(id=1, name="Universe 1", output={})},
    )


def _load_messages(path):
    user_warnings.get_log().clear()
    config = Configuration.load(str(path))
    messages = [e.message for e in user_warnings.get_log().entries()
                if e.category == "config-load"]
    user_warnings.get_log().clear()
    return config, messages


def _raw(path):
    return yaml.safe_load(Path(path).read_text())


def _model(config):
    return asdict(config)


# ---------------------------------------------------------------------------
# The step table
# ---------------------------------------------------------------------------

class TestStepTable:

    def test_steps_are_contiguous_from_zero_to_current(self):
        assert [s.from_version for s in STEPS] == \
            list(range(CURRENT_SCHEMA_VERSION))

    def test_step_names_are_unique(self):
        names = [s.name for s in STEPS]
        assert len(names) == len(set(names))

    def test_v0_needs_every_step_and_current_needs_none(self):
        assert steps_between(0, CURRENT_SCHEMA_VERSION) == STEPS
        assert steps_between(CURRENT_SCHEMA_VERSION,
                             CURRENT_SCHEMA_VERSION) == []


class TestMigrateRunner:

    @pytest.fixture
    def recorded(self, monkeypatch):
        calls = []
        steps = [MigrationStep(n, f"s{n}",
                               lambda data, n=n: calls.append(n))
                 for n in range(3)]
        monkeypatch.setattr(migrations, "STEPS", steps)
        monkeypatch.setattr(migrations, "CURRENT_SCHEMA_VERSION", 3)
        return calls

    def test_unstamped_file_runs_all_steps_in_order(self, recorded):
        data = {"fixtures": []}
        assert migrations.migrate(data) == (0, [])
        assert recorded == [0, 1, 2]

    def test_partial_version_runs_only_the_pending_steps(self, recorded):
        migrations.migrate({SCHEMA_VERSION_KEY: 1})
        assert recorded == [1, 2]

    def test_current_file_runs_no_step(self, recorded):
        data = {SCHEMA_VERSION_KEY: 3}
        assert migrations.migrate(data) == (3, [])
        assert recorded == []
        assert SCHEMA_VERSION_KEY not in data

    def test_newer_file_runs_no_step_and_warns(self, recorded):
        version, warnings = migrations.migrate({SCHEMA_VERSION_KEY: 9})
        assert version == 9 and recorded == []
        assert len(warnings) == 1 and "newer version" in warnings[0]

    @pytest.mark.parametrize("garbage", ["abc", "1", 1.5, True, -1, None,
                                         [1]])
    def test_garbage_stamp_is_version_zero_with_a_warning(self, garbage,
                                                          recorded):
        version, warnings = migrations.migrate(
            {SCHEMA_VERSION_KEY: garbage})
        assert version == 0
        assert recorded == [0, 1, 2]
        assert len(warnings) == 1 and "unreadable schema_version" in \
            warnings[0]

    def test_missing_stamp_is_silent(self):
        assert read_version({}) == (0, None)


# ---------------------------------------------------------------------------
# Version 0 -> 1: the pre-versioning raw-key renames
# ---------------------------------------------------------------------------

class TestV0LegacyKeys:

    def test_shows_key_becomes_songs(self):
        data = {"shows": {"A": {}}}
        migrate(data)
        assert data == {"songs": {"A": {}}}

    def test_songs_wins_over_a_stray_shows_key(self):
        data = {"songs": {"A": {}}, "shows": {"B": {}}}
        migrate(data)
        assert data == {"songs": {"A": {}}, "shows": {"B": {}}}

    @pytest.mark.parametrize("fixture, groups", [
        ({"group": "Front"}, ["Front"]),
        ({"group": ""}, []),
        ({"group": "Front", "groups": None}, ["Front"]),
        ({"group": "Front", "groups": []}, ["Front"]),
        ({"group": "Front", "groups": ["Back", "Wash"]}, ["Back", "Wash"]),
        ({"groups": ["Back"]}, ["Back"]),
    ])
    def test_group_key_follows_the_constructor_rule(self, fixture, groups):
        data = {"fixtures": [dict(fixture)]}
        migrate(data)
        assert "group" not in data["fixtures"][0]
        assert data["fixtures"][0]["groups"] == groups
        # Same answer as the constructor keyword it replaces for files.
        via_init = Fixture(universe=1, address=1, manufacturer="M",
                           model="M", name="F", current_mode="m",
                           available_modes=[], **fixture)
        assert via_init.groups == groups

    def test_direction_and_rotation_are_dropped(self):
        data = {"fixtures": [{"name": "F", "direction": "down",
                              "rotation": 90}]}
        migrate(data)
        assert data["fixtures"] == [{"name": "F"}]

    def test_empty_and_null_sections_are_fine(self):
        for data in ({}, {"fixtures": None}, {"fixtures": []}):
            migrate(data)


# ---------------------------------------------------------------------------
# Save stamps CURRENT; load honours the stamp
# ---------------------------------------------------------------------------

class TestStampOnSave:

    @pytest.mark.parametrize("name", ["project.yaml", "project.lms"])
    def test_save_stamps_current_and_round_trips(self, tmp_path, name):
        path = tmp_path / name
        _config().save(str(path))
        assert _raw(path)[SCHEMA_VERSION_KEY] == CURRENT_SCHEMA_VERSION
        loaded, messages = _load_messages(path)
        assert messages == []
        assert [f.groups for f in loaded.fixtures] == \
            [["Front"], ["Front", "Warm"]]

    def test_autosave_snapshot_is_stamped(self, tmp_path):
        path = tmp_path / "project.lms.autosave"
        write_snapshot(pickle.dumps(_config()), str(path))
        assert _raw(path)[SCHEMA_VERSION_KEY] == CURRENT_SCHEMA_VERSION

    def test_the_stamp_is_not_a_model_attribute(self, tmp_path):
        path = tmp_path / "project.yaml"
        _config().save(str(path))
        loaded = Configuration.load(str(path))
        assert not hasattr(loaded, SCHEMA_VERSION_KEY)

    def test_newer_file_loads_best_effort_and_warns(self, tmp_path):
        path = tmp_path / "newer.yaml"
        _config().save(str(path))
        data = _raw(path)
        data[SCHEMA_VERSION_KEY] = CURRENT_SCHEMA_VERSION + 5
        path.write_text(yaml.safe_dump(data))
        loaded, messages = _load_messages(path)
        assert [f.name for f in loaded.fixtures] == ["Par 1", "Par 2"]
        assert len([m for m in messages if "newer version" in m]) == 1

    def test_garbage_stamp_runs_the_legacy_steps_and_warns(self, tmp_path):
        data = _raw(LEGACY_FIXTURE)
        data[SCHEMA_VERSION_KEY] = "one"
        path = tmp_path / "garbage.yaml"
        path.write_text(yaml.safe_dump(data))
        loaded, messages = _load_messages(path)
        assert loaded.songs, "legacy shows: must still migrate to songs"
        assert any("unreadable schema_version" in m for m in messages)

    def test_the_stamp_gates_the_v0_step(self, tmp_path):
        # A legacy file falsely stamped CURRENT skips the renames: proof
        # the steps key off the stamp and not off key sniffing.
        data = _raw(LEGACY_FIXTURE)
        assert "shows" in data and "songs" not in data
        data[SCHEMA_VERSION_KEY] = CURRENT_SCHEMA_VERSION
        path = tmp_path / "stamped.yaml"
        path.write_text(yaml.safe_dump(data))
        loaded, _ = _load_messages(path)
        assert loaded.songs == {}


# ---------------------------------------------------------------------------
# Legacy fixtures and demos load to the same model as their re-save
# ---------------------------------------------------------------------------

class TestLegacyFilesLoadIdentically:

    def test_the_corpus_is_found(self):
        assert LEGACY_FIXTURE in PROJECT_FILES
        assert len(PROJECT_FILES) >= 11
        # The legacy fixture is the version 0 coverage: keep it unstamped.
        # (Regenerated demos get stamped, which is fine.)
        assert SCHEMA_VERSION_KEY not in _raw(LEGACY_FIXTURE)

    @pytest.mark.parametrize("path", PROJECT_FILES,
                             ids=lambda p: f"{p.parent.name}/{p.name}")
    def test_loads_like_its_stamped_resave(self, path, tmp_path):
        first, messages = _load_messages(path)
        assert messages == []
        resaved = tmp_path / path.name
        first.save(str(resaved))
        assert _raw(resaved)[SCHEMA_VERSION_KEY] == CURRENT_SCHEMA_VERSION
        second, messages = _load_messages(resaved)
        assert messages == []
        a, b = _model(first), _model(second)
        # shows_directory heals to the file's own directory when the
        # stored one does not exist; the copy lives elsewhere.
        a.pop("shows_directory"), b.pop("shows_directory")
        assert a == b

    def test_legacy_band_midsize_pins(self):
        config, _ = _load_messages(LEGACY_FIXTURE)
        assert config.songs
        assert all(f.groups for f in config.fixtures)
        assert config.setlist.entries
