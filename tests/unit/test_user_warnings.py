# tests/unit/test_user_warnings.py
"""The v1.4 silent-fallback audit: utils/user_warnings (recording,
operation grouping, once-key folding, listeners, log forwarding), the
converted call sites (target resolver, fixture library), and the
Warnings panel (gui/dialogs/warnings_dialog.py)."""

import logging
import os

import pytest

from utils import user_warnings
from utils.user_warnings import MAX_ENTRIES, UserWarningsLog


@pytest.fixture(autouse=True)
def fresh_log(monkeypatch):
    """Every test gets its own shared log (module API included)."""
    log = UserWarningsLog()
    monkeypatch.setattr(user_warnings, "_log", log)
    return log


class TestRecording:
    def test_warn_records_an_entry(self, fresh_log):
        user_warnings.warn("lane skipped", category="export")
        (entry,) = fresh_log.entries()
        assert entry.message == "lane skipped"
        assert entry.category == "export"
        assert entry.operation == ""
        assert entry.count == 1

    def test_forwards_to_the_file_log(self, fresh_log, caplog):
        with caplog.at_level(logging.WARNING, logger="user.warnings"):
            user_warnings.warn("lost fixture", category="output")
        assert "[output] lost fixture" in caplog.text

    def test_capped_at_max_entries(self, fresh_log):
        for i in range(MAX_ENTRIES + 25):
            fresh_log.warn(f"w{i}")
        entries = fresh_log.entries()
        assert len(entries) == MAX_ENTRIES
        assert entries[0].message == "w25"

    def test_once_key_folds_repeats_into_a_count(self, fresh_log):
        for _ in range(44):
            fresh_log.warn("ArtNet send failed", category="output",
                           once_key="artnet")
        (entry,) = fresh_log.entries()
        assert entry.count == 44

    def test_different_once_keys_stay_separate(self, fresh_log):
        fresh_log.warn("u1 down", once_key="u1")
        fresh_log.warn("u2 down", once_key="u2")
        assert len(fresh_log.entries()) == 2


class TestOperations:
    def test_entries_carry_their_operation(self, fresh_log):
        with fresh_log.operation("Export QLC+ workspace"):
            fresh_log.warn("lane skipped")
        (entry,) = fresh_log.entries()
        assert entry.operation == "Export QLC+ workspace"

    def test_last_operation_returns_only_the_latest_run(self, fresh_log):
        with fresh_log.operation("Export"):
            fresh_log.warn("old problem")
        with fresh_log.operation("Export"):
            fresh_log.warn("new problem")
        name, entries = fresh_log.last_operation()
        assert name == "Export"
        assert [e.message for e in entries] == ["new problem"]

    def test_clean_rerun_reports_clean(self, fresh_log):
        with fresh_log.operation("Export"):
            fresh_log.warn("problem")
        with fresh_log.operation("Export"):
            pass
        name, entries = fresh_log.last_operation()
        assert name == "Export" and entries == []

    def test_reentering_an_operation_resets_its_once_keys(self, fresh_log):
        with fresh_log.operation("Export"):
            fresh_log.warn("no RGB", once_key="rgb")
        with fresh_log.operation("Export"):
            fresh_log.warn("no RGB", once_key="rgb")
        assert len(fresh_log.entries()) == 2
        assert all(e.count == 1 for e in fresh_log.entries())

    def test_no_operation_ever(self, fresh_log):
        assert fresh_log.last_operation() == ("", [])

    def test_clear_forgets_everything(self, fresh_log):
        with fresh_log.operation("Export"):
            fresh_log.warn("problem")
        fresh_log.clear()
        assert fresh_log.entries() == []
        assert fresh_log.last_operation() == ("", [])


class TestListeners:
    def test_listener_sees_each_entry(self, fresh_log):
        seen = []
        fresh_log.add_listener(seen.append)
        fresh_log.warn("a")
        fresh_log.warn("b")
        assert [e.message for e in seen] == ["a", "b"]
        fresh_log.remove_listener(seen.append)
        fresh_log.warn("c")
        assert len(seen) == 2

    def test_broken_listener_never_breaks_warn(self, fresh_log):
        def boom(_entry):
            raise RuntimeError("listener bug")
        fresh_log.add_listener(boom)
        fresh_log.warn("still recorded")
        assert len(fresh_log.entries()) == 1


class TestConvertedSites:
    def test_target_resolver_group_not_found(self, fresh_log):
        from utils import target_resolver
        target_resolver.reset_warnings()

        class Cfg:
            groups = {}
        assert target_resolver.resolve_target("Nope Group", Cfg()) == []
        (entry,) = fresh_log.entries()
        assert "Nope Group" in entry.message
        assert entry.category == "targets"
        # the resolver's own dedup keeps repeats out
        target_resolver.resolve_target("Nope Group", Cfg())
        assert len(fresh_log.entries()) == 1
        target_resolver.reset_warnings()

    def test_fixture_library_parse_error(self, fresh_log, tmp_path,
                                         monkeypatch):
        from utils import fixture_library as fl
        bad_dir = tmp_path / "defs"
        bad_dir.mkdir()
        # Header (Manufacturer/Model) parses so the file gets indexed;
        # the malformed tail then breaks the FULL parse - exactly the
        # silent-drop path the audit made visible.
        bad = bad_dir / "Broken-Fixture.qxf"
        bad.write_text(
            "<FixtureDefinition>"
            "<Manufacturer>Broken</Manufacturer>"
            "<Model>Fixture</Model>"
            "<Mode><unclosed></Mode>",
            encoding="utf-8")
        monkeypatch.setattr(fl, "fixture_search_dirs",
                            lambda: [(str(bad_dir), "user-qxf")])
        fl.clear_library_cache()
        try:
            assert fl.get_definition("Broken", "Fixture") is None
        finally:
            fl.clear_library_cache()
        entries = fresh_log.entries()
        assert entries, "parse failure must be recorded"
        assert entries[0].category == "fixture-library"
        assert "Broken-Fixture.qxf" in entries[0].message


class TestWarningsDialog:
    def _log_with_history(self):
        log = UserWarningsLog(clock=lambda: 1_000_000.0)
        log.warn("startup wart", category="fixture-library")
        with log.operation("Export QLC+ workspace"):
            log.warn("lane 'Drums' skipped", category="export")
            log.warn("no RGB", category="export", once_key="rgb")
            log.warn("no RGB", category="export", once_key="rgb")
        return log

    def test_report_shows_last_operation_first(self, qapp):
        from gui.dialogs.warnings_dialog import render_report
        text = render_report(self._log_with_history())
        assert text.index("LAST OPERATION · Export QLC+ workspace") \
            < text.index("ALL RECENT WARNINGS (3)")
        assert "lane 'Drums' skipped" in text
        assert "(x2)" in text  # folded once_key repeats
        assert "startup wart" in text

    def test_clean_session(self, qapp):
        from gui.dialogs.warnings_dialog import render_report
        assert "(none this session)" in render_report(UserWarningsLog())

    def test_dialog_copy_and_clear(self, qapp):
        from gui.dialogs.warnings_dialog import WarningsDialog
        log = self._log_with_history()
        dialog = WarningsDialog(log=log)
        assert "lane 'Drums' skipped" in dialog.text_view.toPlainText()
        dialog._copy()
        assert "lane 'Drums' skipped" in qapp.clipboard().text()
        dialog._clear()
        assert log.entries() == []
        assert "(none this session)" in dialog.text_view.toPlainText()
