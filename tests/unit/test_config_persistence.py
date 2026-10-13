# tests/unit/test_config_persistence.py
"""Config persistence hardening (v1.5.5 plan group G7).

Pins four things:

- ``Configuration.save`` is atomic: a failure mid-dump leaves the
  previous file intact and no temp file behind (the autosave path was
  already atomic, a manual Save was not).
- Loading a file written by a NEWER build ignores keys this build does
  not know (warned under "config-load") instead of crashing in
  ``Fixture(**f_data)`` and the other dataclass constructors.
- One primary-group lookup (``config.models.primary_group``) replaces
  the copied ``config.groups.get(fixture.group)`` expressions, and no
  production code writes the replacing ``fixture.group`` setter.
- The Stage tab's "select group" honours secondary memberships.
"""

from __future__ import annotations

import ast
import os
import re
import stat
import sys
from pathlib import Path

import pytest
import yaml

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from config.models import (
    Configuration, Fixture, FixtureGroup, FixtureMode, StageLayer,
    Universe,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
PRODUCTION_DIRS = ("audio", "auto", "autogen", "config", "effects", "gui",
                   "rudiments", "scenes", "timeline", "utils", "visualizer")


def make_fixture(name="F1", **kwargs):
    defaults = dict(
        universe=1, address=1, manufacturer="TestMfr", model="TestModel",
        name=name, current_mode="Standard",
        available_modes=[FixtureMode(name="Standard", channels=6)],
    )
    defaults.update(kwargs)
    return Fixture(**defaults)


def small_config():
    fixtures = [make_fixture("Par 1", groups=["Front"]),
                make_fixture("Par 2", address=7, groups=["Front", "Warm"])]
    return Configuration(
        fixtures=fixtures,
        groups={"Front": FixtureGroup("Front", list(fixtures)),
                "Warm": FixtureGroup("Warm", [fixtures[1]])},
        universes={1: Universe(id=1, name="Universe 1", output={})},
    )


def _production_files():
    for top in PRODUCTION_DIRS:
        base = REPO_ROOT / top
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            yield path


# ---------------------------------------------------------------------------
# Atomic save
# ---------------------------------------------------------------------------

class TestAtomicSave:

    def test_failed_dump_keeps_the_previous_file(self, tmp_path,
                                                 monkeypatch):
        target = tmp_path / "show.yaml"
        small_config().save(str(target))
        before = target.read_bytes()

        import config.models as models
        real_dump = models.yaml.dump

        def torn_dump(data, stream=None, **kwargs):
            # Simulate a crash half-way through the write: some bytes
            # reach the stream, then the dump dies.
            text = real_dump(data, **kwargs)
            if stream is not None:
                stream.write(text[: len(text) // 3])
            raise RuntimeError("disk full")

        monkeypatch.setattr(models.yaml, "dump", torn_dump)
        with pytest.raises(RuntimeError):
            small_config().save(str(target))

        assert target.read_bytes() == before
        assert sorted(p.name for p in tmp_path.iterdir()) == ["show.yaml"]

    def test_save_leaves_no_temp_file_and_round_trips(self, tmp_path):
        target = tmp_path / "show.yaml"
        small_config().save(str(target))
        assert sorted(p.name for p in tmp_path.iterdir()) == ["show.yaml"]
        loaded = Configuration.load(str(target))
        assert [f.name for f in loaded.fixtures] == ["Par 1", "Par 2"]
        assert loaded.fixtures[1].groups == ["Front", "Warm"]

    @pytest.mark.skipif(sys.platform == "win32",
                        reason="POSIX permission bits")
    def test_overwrite_keeps_the_file_mode(self, tmp_path):
        target = tmp_path / "show.yaml"
        small_config().save(str(target))
        os.chmod(target, 0o640)
        small_config().save(str(target))
        assert stat.S_IMODE(os.stat(target).st_mode) == 0o640

    @pytest.mark.skipif(sys.platform == "win32",
                        reason="POSIX permission bits")
    def test_new_file_gets_umask_default_mode(self, tmp_path):
        # A temp-file write must not leak mkstemp's private 0600 onto
        # a freshly created project file: it gets what open('w') gave.
        target = tmp_path / "fresh.yaml"
        small_config().save(str(target))
        reference = tmp_path / "reference.txt"
        reference.write_text("x")
        assert stat.S_IMODE(os.stat(target).st_mode) == \
            stat.S_IMODE(os.stat(reference).st_mode)

    @pytest.mark.skipif(sys.platform == "win32" or os.geteuid() == 0,
                        reason="POSIX permission bits; root bypasses them")
    def test_read_only_file_is_refused_not_replaced(self, tmp_path):
        # A rename only needs a writable directory, so a temp-file save
        # would silently overwrite a file the user made read-only; the
        # old open('w') refused, and so must the atomic writer.
        target = tmp_path / "locked.yaml"
        small_config().save(str(target))
        before = target.read_bytes()
        os.chmod(target, 0o444)
        config = small_config()
        config.fixtures[0].name = "Changed"
        with pytest.raises(PermissionError):
            config.save(str(target))
        assert target.read_bytes() == before
        assert sorted(p.name for p in tmp_path.iterdir()) == ["locked.yaml"]

    @pytest.mark.skipif(sys.platform == "win32", reason="symlinks")
    def test_saving_through_a_symlink_keeps_the_link(self, tmp_path):
        real = tmp_path / "real.yaml"
        small_config().save(str(real))
        link = tmp_path / "link.yaml"
        link.symlink_to(real)
        small_config().save(str(link))
        assert link.is_symlink()
        assert Configuration.load(str(real)).fixtures[0].name == "Par 1"

    def test_save_tracks_the_target_path(self, tmp_path):
        config = small_config()
        target = tmp_path / "show.yaml"
        config.save(str(target))
        assert config._loaded_from == os.path.abspath(str(target))


# ---------------------------------------------------------------------------
# Forward compatibility: unknown keys from newer files
# ---------------------------------------------------------------------------

def _newer_build_yaml(path):
    small_config().save(str(path))
    data = yaml.safe_load(path.read_text())
    data["fixtures"][0]["beam_profile"] = "narrow"   # unknown to us
    data["fixtures"][1]["future_flag"] = True
    data["stage_layers"] = [{"name": "Ground", "z_height": 0.0,
                             "visible": True, "opacity": 0.5}]
    data["stage_elements"] = [{"kind": "riser", "x": 1.0,
                               "material": "steel"}]
    data["spots"] = {"Centre": {"name": "Centre", "x": 0.0, "y": 0.0,
                                "z": 0.0, "colour": "#fff"}}
    data["pause_show"] = {"enabled": True, "fade_ms": 400}
    data["midi_input_devices"] = [{"name": "APC", "uid": "APC",
                                   "profile": "APC", "universe_id": 0,
                                   "channel_map": {}}]
    path.write_text(yaml.safe_dump(data))


class TestUnknownKeys:

    def test_newer_file_loads_and_drops_unknown_keys(self, tmp_path):
        path = tmp_path / "newer.yaml"
        _newer_build_yaml(path)
        config = Configuration.load(str(path))

        assert [f.name for f in config.fixtures] == ["Par 1", "Par 2"]
        assert not hasattr(config.fixtures[0], "beam_profile")
        assert config.fixtures[1].groups == ["Front", "Warm"]
        assert config.stage_layers == [StageLayer("Ground", 0.0, True)]
        assert config.stage_elements[0].kind == "riser"
        assert config.spots["Centre"].x == 0.0
        assert config.pause_show.enabled is True
        assert config.midi_input_devices[0].uid == "APC"

    def test_unknown_keys_are_warned_once_per_kind(self, tmp_path):
        from utils import user_warnings
        user_warnings.get_log().clear()
        path = tmp_path / "newer.yaml"
        _newer_build_yaml(path)
        Configuration.load(str(path))

        messages = [e.message for e in user_warnings.get_log().entries()
                    if e.category == "config-load"]
        fixture_msgs = [m for m in messages if m.startswith("Fixtures:")]
        assert len(fixture_msgs) == 1
        assert "beam_profile" in fixture_msgs[0]
        assert "future_flag" in fixture_msgs[0]
        assert any("opacity" in m for m in messages)
        assert any("material" in m for m in messages)
        user_warnings.get_log().clear()

    def test_legacy_group_key_is_not_reported_as_unknown(self, tmp_path):
        # The dual-written legacy `group` key is an InitVar, not a
        # field; it must keep loading silently.
        from utils import user_warnings
        user_warnings.get_log().clear()
        path = tmp_path / "show.yaml"
        small_config().save(str(path))
        assert "group" in yaml.safe_load(path.read_text())["fixtures"][0]
        Configuration.load(str(path))
        assert not [e for e in user_warnings.get_log().entries()
                    if "ignored" in e.message]


# ---------------------------------------------------------------------------
# Primary group helper + setter audit
# ---------------------------------------------------------------------------

class TestPrimaryGroup:

    def test_returns_the_first_listed_group(self):
        from config.models import primary_group
        config = small_config()
        par2 = config.fixtures[1]
        assert primary_group(config, par2) is config.groups["Front"]
        par2.groups = ["Warm", "Front"]
        assert primary_group(config, par2) is config.groups["Warm"]

    def test_ungrouped_and_dangling_return_none(self):
        from config.models import primary_group
        config = small_config()
        assert primary_group(config, make_fixture("Loose")) is None
        assert primary_group(
            config, make_fixture("Ghost", groups=["Gone"])) is None

    def test_no_copied_primary_group_lookups_remain(self):
        pattern = re.compile(r"groups\.get\(\s*\w+\.group\s*\)")
        offenders = [
            f"{path.relative_to(REPO_ROOT)}:{n}"
            for path in _production_files()
            for n, line in enumerate(
                path.read_text(encoding="utf-8-sig").splitlines(), start=1)
            if pattern.search(line)
        ]
        assert offenders == [], (
            "use config.models.primary_group(config, fixture)")

    def test_no_production_code_writes_the_group_setter(self):
        """The compat setter REPLACES the whole membership list, so a
        UI path that writes it silently drops secondary groups. Only
        the stage plan's FixtureItem (its own attribute, not a Fixture)
        is allowed to assign ``.group``."""
        allowed = {("gui/StageView.py", "fixture_item")}
        offenders = []
        for path in _production_files():
            rel = path.relative_to(REPO_ROOT).as_posix()
            tree = ast.parse(path.read_text(encoding="utf-8-sig"))
            for node in ast.walk(tree):
                targets = []
                if isinstance(node, ast.Assign):
                    targets = node.targets
                elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
                    targets = [node.target]
                for target in targets:
                    if (isinstance(target, ast.Attribute)
                            and target.attr == "group"):
                        owner = ast.unparse(target.value)
                        if (rel, owner) not in allowed \
                                and not (rel == "config/models.py"
                                         and owner == "Fixture"):
                            offenders.append(f"{rel}:{node.lineno}")
        assert offenders == []


# ---------------------------------------------------------------------------
# Stage plan group selection honours secondary memberships
# ---------------------------------------------------------------------------

class TestStageGroupSelection:

    def test_selecting_a_secondary_group_selects_its_members(self, qapp):
        from gui.StageView import StageView
        view = StageView(None)
        try:
            view.set_config(small_config())
            assert {i.fixture_name
                    for i in view.select_group_fixtures("Warm")} == \
                {"Par 2"}
            assert {i.fixture_name
                    for i in view.select_group_fixtures("Front")} == \
                {"Par 1", "Par 2"}
        finally:
            view.deleteLater()
