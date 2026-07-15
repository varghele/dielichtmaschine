# tests/unit/test_export_cli.py
"""utils/export_cli.py - the headless `export` subcommand (ROADMAP
v1.3 "Headless export CLI"). Exercises the argparse contract and the
real export end to end on a bundled demo rig; no Qt, no subprocess
(main.py's dispatch is a two-line branch above the PyQt imports)."""

import os
import shutil

import pytest

from utils.export_cli import (
    build_parser, default_output_path, run_export_cli,
)

REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", ".."))
CLUB_BAND = os.path.join(REPO_ROOT, "demos", "rigs", "club_band.yaml")


def _read(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


class TestArguments:
    def test_help_exits_zero(self, capsys):
        with pytest.raises(SystemExit) as exc:
            build_parser().parse_args(["--help"])
        assert exc.value.code == 0
        assert "--qlc-version" in capsys.readouterr().out

    def test_unknown_version_is_a_usage_error(self):
        with pytest.raises(SystemExit) as exc:
            build_parser().parse_args([CLUB_BAND, "--qlc-version", "3.0"])
        assert exc.value.code == 2

    def test_default_output_path_sits_next_to_the_config(self):
        assert default_output_path("/somewhere/venue_a.yaml") == \
            os.path.abspath("/somewhere/venue_a.qxw")


class TestExport:
    def test_exports_a_demo_rig(self, tmp_path, capsys):
        out = str(tmp_path / "club_band.qxw")
        assert run_export_cli([CLUB_BAND, "--out", out]) == 0
        text = _read(out)
        # Default target stamp, real patch content, full VC.
        assert "<Version>4.14.4</Version>" in text
        assert "<FixtureID>" in text or "<Fixture>" in text
        assert "Button" in text
        assert f"Workspace written to {out}" in capsys.readouterr().out

    def test_qlc_version_stamp(self, tmp_path):
        out = str(tmp_path / "v5.qxw")
        assert run_export_cli(
            [CLUB_BAND, "--out", out, "--qlc-version", "5.2.1"]) == 0
        assert "<Version>5.2.1</Version>" in _read(out)

    def test_no_vc_skips_the_virtual_console_widgets(self, tmp_path):
        out = str(tmp_path / "novc.qxw")
        assert run_export_cli([CLUB_BAND, "--out", out, "--no-vc"]) == 0
        text = _read(out)
        # The minimal backwards-compatible VC section remains, but none
        # of the generated control widgets.
        assert "<VirtualConsole>" in text
        assert "Button" not in text

    def test_default_output_lands_next_to_the_config(self, tmp_path):
        config_copy = tmp_path / "my_rig.yaml"
        shutil.copyfile(CLUB_BAND, config_copy)
        assert run_export_cli([str(config_copy)]) == 0
        assert (tmp_path / "my_rig.qxw").is_file()

    def test_missing_config_fails_with_exit_1(self, tmp_path, capsys):
        assert run_export_cli([str(tmp_path / "ghost.yaml")]) == 1
        assert "config not found" in capsys.readouterr().err

    def test_missing_output_dir_fails_with_exit_1(self, tmp_path, capsys):
        out = str(tmp_path / "no_such_dir" / "x.qxw")
        assert run_export_cli([CLUB_BAND, "--out", out]) == 1
        assert "output directory not found" in capsys.readouterr().err

    def test_unloadable_config_fails_with_exit_1(self, tmp_path, capsys):
        bad = tmp_path / "broken.yaml"
        bad.write_text("{ not valid yaml: [", encoding="utf-8")
        assert run_export_cli([str(bad)]) == 1
        assert "could not load" in capsys.readouterr().err
