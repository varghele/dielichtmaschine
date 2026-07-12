"""The native .lms project extension (v1.3).

Contract:
- .lms is the native project extension; the on-disk format is plain YAML,
  so a Configuration round-trips through a .lms path exactly as through a
  .yaml path (the extension is cosmetic - load/save key off the path).
- The file-dialog name filters offer .lms as the default for saving and
  accept .lms plus the legacy .yaml/.yml for opening.
- ensure_project_ext appends .lms only when the user typed a bare name.
- project_path_from_argv picks the launch project from argv, skipping
  flags (the file-association / command-line open path).
"""

from __future__ import annotations

import os

from config.models import Configuration, Spot, Universe
from utils import app_identity


class TestProjectConstants:

    def test_native_extension_is_lms(self):
        assert app_identity.PROJECT_EXT == ".lms"

    def test_legacy_extensions_still_recognised(self):
        assert ".lms" in app_identity.PROJECT_EXTENSIONS
        assert ".yaml" in app_identity.PROJECT_EXTENSIONS
        assert ".yml" in app_identity.PROJECT_EXTENSIONS


class TestDialogFilters:

    def test_open_filter_accepts_native_and_legacy(self):
        f = app_identity.project_open_filter()
        assert "*.lms" in f
        assert "*.yaml" in f
        assert "*.yml" in f
        # A catch-all so an oddly-named project is still reachable.
        assert "*)" in f

    def test_save_filter_leads_with_native(self):
        f = app_identity.project_save_filter()
        # The first entry is the default suffix Qt applies; it must be .lms.
        first_entry = f.split(";;")[0]
        assert "*.lms" in first_entry
        assert "*.yaml" not in first_entry
        # .yaml stays available as a secondary choice.
        assert "*.yaml" in f


class TestEnsureProjectExt:

    def test_bare_name_gets_lms(self):
        assert app_identity.ensure_project_ext("my_show") == "my_show.lms"

    def test_bare_path_gets_lms(self):
        got = app_identity.ensure_project_ext(os.path.join("dir", "my_show"))
        assert got == os.path.join("dir", "my_show.lms")

    def test_explicit_lms_unchanged(self):
        assert app_identity.ensure_project_ext("my_show.lms") == "my_show.lms"

    def test_explicit_yaml_kept(self):
        # A user who deliberately typed .yaml keeps it (interop / preference).
        assert app_identity.ensure_project_ext("my_show.yaml") == "my_show.yaml"

    def test_other_extension_kept(self):
        assert app_identity.ensure_project_ext("my_show.txt") == "my_show.txt"

    def test_empty_stays_empty(self):
        assert app_identity.ensure_project_ext("") == ""


class TestProjectPathFromArgv:

    def test_picks_first_positional(self):
        assert app_identity.project_path_from_argv(["show.lms"]) == "show.lms"

    def test_skips_flags(self):
        argv = ["--profile", "show.lms"]
        assert app_identity.project_path_from_argv(argv) == "show.lms"

    def test_none_when_only_flags(self):
        assert app_identity.project_path_from_argv(["--profile"]) is None

    def test_none_when_empty(self):
        assert app_identity.project_path_from_argv([]) is None

    def test_first_positional_wins(self):
        argv = ["-x", "a.lms", "b.lms"]
        assert app_identity.project_path_from_argv(argv) == "a.lms"


class TestLmsRoundTrip:
    """A .lms file is YAML content; it must load exactly like a .yaml one."""

    def _sample_config(self):
        return Configuration(
            fixtures=[],
            groups={},
            universes={0: Universe(id=0, name="Universe 0", output={})},
            spots={"Center": Spot(name="Center", x=5.0, y=3.0)},
            workspace_path="/test/path",
        )

    def test_saves_and_loads_through_lms(self, tmp_path):
        config = self._sample_config()
        path = str(tmp_path / "my_project.lms")
        config.save(path)
        assert os.path.isfile(path)
        loaded = Configuration.load(path)
        assert 0 in loaded.universes
        assert loaded.spots["Center"].x == 5.0
        assert loaded.workspace_path == "/test/path"

    def test_lms_and_yaml_bytes_are_identical(self, tmp_path):
        # Same content, two extensions -> byte-identical files (proves the
        # extension carries no format meaning).
        config = self._sample_config()
        lms_path = str(tmp_path / "p.lms")
        yaml_path = str(tmp_path / "p.yaml")
        config.save(lms_path)
        config.save(yaml_path)
        with open(lms_path, "rb") as a, open(yaml_path, "rb") as b:
            assert a.read() == b.read()
