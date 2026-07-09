"""Autosave / crash-recovery core logic."""

import os
import types
from unittest.mock import MagicMock

import pytest

from utils.autosave import (
    AutosaveManager, backup_path_for, find_recoverable,
)


def test_sidecar_path_for_a_saved_project(tmp_path):
    project = str(tmp_path / "show.yaml")
    assert backup_path_for(project, str(tmp_path)) == project + ".autosave"


def test_untitled_backup_when_unsaved(tmp_path):
    path = backup_path_for(None, str(tmp_path))
    assert path == os.path.join(str(tmp_path), "untitled.autosave.yaml")


def test_maybe_backup_writes_only_when_content_changed(tmp_path):
    project = str(tmp_path / "show.yaml")
    content = {"v": "a"}
    written = []
    mgr = AutosaveManager(
        save_fn=lambda p: written.append(p) or open(p, "w").close(),
        fingerprint_fn=lambda: content["v"],
        current_path=lambda: project,
        fallback_dir=str(tmp_path))
    mgr.prime()  # current content is clean

    assert mgr.maybe_backup() is None          # unchanged -> no write
    assert written == []

    content["v"] = "b"
    path = mgr.maybe_backup()
    assert path == project + ".autosave"
    assert os.path.exists(path)

    # Unchanged again -> no second write.
    assert mgr.maybe_backup() is None


def test_clear_removes_backup_and_marks_clean(tmp_path):
    project = str(tmp_path / "show.yaml")
    content = {"v": "a"}
    mgr = AutosaveManager(
        save_fn=lambda p: open(p, "w").close(),
        fingerprint_fn=lambda: content["v"],
        current_path=lambda: project,
        fallback_dir=str(tmp_path))
    content["v"] = "b"
    backup = mgr.maybe_backup()
    assert os.path.exists(backup)
    mgr.clear()
    assert not os.path.exists(backup)
    # After a save, unchanged content must not immediately re-backup.
    assert mgr.maybe_backup() is None


def test_recoverable_when_backup_is_newer_than_project(tmp_path):
    project = tmp_path / "show.yaml"
    project.write_text("old")
    backup = tmp_path / "show.yaml.autosave"
    backup.write_text("newer")
    # Make the backup strictly newer.
    os.utime(str(project), (1000, 1000))
    os.utime(str(backup), (2000, 2000))
    assert find_recoverable(str(project), str(tmp_path)) == str(backup)


def test_not_recoverable_when_project_is_newer(tmp_path):
    """A save wrote the project after the last autosave: nothing pending."""
    project = tmp_path / "show.yaml"
    project.write_text("saved")
    backup = tmp_path / "show.yaml.autosave"
    backup.write_text("older")
    os.utime(str(backup), (1000, 1000))
    os.utime(str(project), (2000, 2000))
    assert find_recoverable(str(project), str(tmp_path)) is None


def test_not_recoverable_when_no_backup(tmp_path):
    project = tmp_path / "show.yaml"
    project.write_text("x")
    assert find_recoverable(str(project), str(tmp_path)) is None


def test_untitled_backup_is_always_recoverable_if_present(tmp_path):
    (tmp_path / "untitled.autosave.yaml").write_text("work")
    assert find_recoverable(None, str(tmp_path)) == os.path.join(
        str(tmp_path), "untitled.autosave.yaml")


def test_end_to_end_with_a_real_config(tmp_path):
    """Edit -> backup -> recover -> save clears it, with a real
    Configuration and the same asdict fingerprint gui.py uses."""
    from dataclasses import asdict
    from config.models import Configuration, Universe

    project = str(tmp_path / "show.yaml")
    cfg = Configuration(universes={0: Universe(id=0, name="U0", output={})})
    cfg.save(project)

    mgr = AutosaveManager(
        save_fn=lambda p: cfg.save(p),
        fingerprint_fn=lambda: hash(repr(asdict(cfg))),
        current_path=lambda: project,
        fallback_dir=str(tmp_path))
    mgr.prime()
    assert mgr.maybe_backup() is None            # unchanged since save

    cfg.universes[1] = Universe(id=1, name="U1", output={})
    backup = mgr.maybe_backup()
    assert backup and os.path.exists(backup)
    os.utime(project, (1000, 1000))
    os.utime(backup, (2000, 2000))
    assert find_recoverable(project, str(tmp_path)) == backup

    recovered = Configuration.load(backup)
    assert 1 in recovered.universes            # the unsaved edit survived

    cfg.save(project)
    mgr.clear()
    assert not os.path.exists(backup)
    assert find_recoverable(project, str(tmp_path)) is None


# ---------------------------------------------------------------------------
# Launch recovery (MainWindow._offer_launch_recovery), tested against a fake
# self so no heavy MainWindow is built (same pattern as test_visualizer_sync).
# ---------------------------------------------------------------------------

def _fake_window():
    from config.models import Configuration
    return types.SimpleNamespace(
        config=Configuration(), config_path=None,
        _rebind_tabs_to_config=MagicMock(),
        show_pages=MagicMock())


def _write_untitled_backup(tmp_path):
    from config.models import Configuration, Universe
    cfg = Configuration(universes={0: Universe(id=0, name="U0", output={})})
    backup = os.path.join(str(tmp_path), "untitled.autosave.yaml")
    cfg.save(backup)
    return backup


@pytest.fixture
def _isolated_autosave(tmp_path, monkeypatch):
    monkeypatch.setenv("QLC_AUTOSAVE_DIR", str(tmp_path))
    from utils.app_settings import app_settings
    yield tmp_path
    app_settings().remove("autosave/last_project")


def test_launch_recovery_recovers_when_confirmed(qapp, _isolated_autosave,
                                                 monkeypatch):
    from PyQt6.QtWidgets import QMessageBox
    from gui.gui import MainWindow
    from utils.app_settings import app_settings

    _write_untitled_backup(_isolated_autosave)
    app_settings().setValue("autosave/last_project", "")  # untitled session
    monkeypatch.setattr(
        QMessageBox, "question",
        staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))

    fake = _fake_window()
    MainWindow._offer_launch_recovery(fake)

    assert 0 in fake.config.universes            # recovered content
    assert fake.config_path is None              # stays untitled
    fake._rebind_tabs_to_config.assert_called_once()
    fake.show_pages.assert_called_once()


def test_launch_recovery_declined_changes_nothing(qapp, _isolated_autosave,
                                                  monkeypatch):
    from PyQt6.QtWidgets import QMessageBox
    from gui.gui import MainWindow
    from utils.app_settings import app_settings

    _write_untitled_backup(_isolated_autosave)
    app_settings().setValue("autosave/last_project", "")
    monkeypatch.setattr(
        QMessageBox, "question",
        staticmethod(lambda *a, **k: QMessageBox.StandardButton.No))

    fake = _fake_window()
    MainWindow._offer_launch_recovery(fake)

    assert fake.config.universes == {}
    fake._rebind_tabs_to_config.assert_not_called()


def test_launch_recovery_no_backup_is_silent(qapp, _isolated_autosave,
                                             monkeypatch):
    from PyQt6.QtWidgets import QMessageBox
    from gui.gui import MainWindow

    def _boom(*a, **k):
        raise AssertionError("must not prompt when there is nothing to recover")

    monkeypatch.setattr(QMessageBox, "question", staticmethod(_boom))
    fake = _fake_window()
    MainWindow._offer_launch_recovery(fake)  # no backup present -> returns
    fake._rebind_tabs_to_config.assert_not_called()


def test_launch_recovery_skips_when_a_project_is_already_open(
        qapp, _isolated_autosave, monkeypatch):
    from PyQt6.QtWidgets import QMessageBox
    from gui.gui import MainWindow
    from utils.app_settings import app_settings

    _write_untitled_backup(_isolated_autosave)
    app_settings().setValue("autosave/last_project", "")

    def _boom(*a, **k):
        raise AssertionError("must not prompt once something is loaded")

    monkeypatch.setattr(QMessageBox, "question", staticmethod(_boom))
    fake = _fake_window()
    fake.config_path = "/some/open/project.yaml"  # already working on a file
    MainWindow._offer_launch_recovery(fake)
    fake._rebind_tabs_to_config.assert_not_called()
