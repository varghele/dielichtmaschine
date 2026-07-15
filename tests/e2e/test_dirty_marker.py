"""The unsaved-changes marker (Reaper-style asterisk on the topbar
filename + window title).

Truth = the content fingerprint vs the last MANUAL save/load: any edit
path raises it (no undo command needed - the undo stack only covers
timeline blocks), an autosave backup never clears it, a real save
does.
"""

import pytest


def _force_tick(window):
    window._dirty_ticks = 0        # bypass the 5-tick throttle
    window._update_toolbar_status()


class TestDirtyMarker:

    def test_fresh_window_is_clean(self, main_window):
        _force_tick(main_window)
        assert not main_window.is_config_dirty()
        assert not main_window.windowTitle().endswith(" *")
        assert main_window.topbar.filename_label.text() == \
            "NO PROJECT LOADED"     # MicroLabel speaks in caps

    def test_any_edit_raises_the_asterisk(self, main_window):
        # A config edit that never touches the undo stack.
        main_window.config.setlist.name = "Edited"
        _force_tick(main_window)
        assert main_window.is_config_dirty()
        assert main_window.windowTitle().endswith(" *")
        assert main_window.topbar.filename_label.text() == "UNTITLED *"
        assert "Ctrl+S" in main_window.topbar.filename_label.toolTip()

    def test_manual_save_clears_it(self, main_window, tmp_path,
                                   monkeypatch):
        from PyQt6.QtWidgets import QMessageBox
        monkeypatch.setattr(QMessageBox, "information",
                            staticmethod(lambda *a, **k: None))
        main_window.config.setlist.name = "Edited"
        main_window.config_path = str(tmp_path / "marker.lms")
        main_window.save_configuration()
        assert not main_window.is_config_dirty()
        _force_tick(main_window)
        assert not main_window.windowTitle().endswith(" *")
        assert main_window.topbar.filename_label.text() == "MARKER.LMS"
        assert main_window.topbar.filename_label.toolTip() == ""

    def test_autosave_backup_does_not_clear_it(self, main_window,
                                               tmp_path):
        # Sidecar backups land next to the project file, so point the
        # project into tmp before triggering one.
        main_window.config_path = str(tmp_path / "marker.lms")
        main_window.config.setlist.name = "Edited again"
        assert main_window._autosave.maybe_backup() is not None
        assert main_window.is_config_dirty()
        _force_tick(main_window)
        assert main_window.windowTitle().endswith(" *")
        assert main_window.topbar.filename_label.text() == "MARKER.LMS *"

    def test_undo_boundary_refreshes_immediately(self, main_window):
        main_window.config.setlist.name = "Edited"
        # No tick needed: the undo hook recomputes on the spot (and
        # deliberately ignores the stack's own clean flag).
        main_window._on_undo_clean_changed(False)
        assert main_window.windowTitle().endswith(" *")
        main_window.config.setlist.name = ""
        main_window._mark_config_clean()
        main_window._on_undo_clean_changed(False)
        assert not main_window.windowTitle().endswith(" *")
