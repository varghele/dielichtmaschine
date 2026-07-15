# tests/unit/test_diagnostics.py
"""Help > Diagnostics (ROADMAP v1.4): utils/diagnostics gathering with
guarded probes and the copyable dialog. Driver-touching probes (GL,
audio) are injected - nothing here opens a context or an audio API."""

import pytest

from utils import diagnostics


class FakeArbiter:
    def __init__(self, status):
        self._status = status

    def status(self):
        return self._status


class FakeMainWindow:
    def __init__(self, running=True, config_path="C:/shows/tour.lms",
                 universes=(1, 2)):
        self.config_path = config_path
        self.config = type("Cfg", (), {"universes": list(universes)})()
        self._arbiter = FakeArbiter({
            "running": running,
            "frames_sent": 4242,
            "universe_mapping": {1: 0, 2: 1},
        })

    def output_arbiter(self):
        return self._arbiter


def stub_gather(main_window=None):
    return diagnostics.gather(
        main_window,
        gl_probe=lambda: "FakeGL 4.6",
        audio_probe=lambda: "WASAPI, MME")


def flat(sections):
    return {name: value for _title, rows in sections
            for name, value in rows}


class TestGather:
    def test_all_sections_present(self):
        titles = [t for t, _rows in stub_gather(FakeMainWindow())]
        assert titles == ["Application", "Graphics", "Audio",
                          "Output", "Project"]

    def test_live_state_rows(self):
        rows = flat(stub_gather(FakeMainWindow()))
        assert rows["OpenGL"] == "FakeGL 4.6"
        assert rows["Host APIs"] == "WASAPI, MME"
        assert "4242 frames sent" in rows["ArtNet output"]
        assert "1->0, 2->1" in rows["ArtNet output"]
        assert rows["Configured universes"] == "2"
        assert rows["Project"] == "C:/shows/tour.lms"

    def test_idle_output_and_untitled_project(self):
        window = FakeMainWindow(running=False, config_path=None)
        rows = flat(stub_gather(window))
        assert rows["ArtNet output"] == "idle (loop not running)"
        assert rows["Project"] == "untitled (never saved)"

    def test_no_main_window_degrades(self):
        rows = flat(stub_gather(None))
        assert "no main window" in rows["ArtNet output"]
        assert "no main window" in rows["Project"]
        assert "Configured universes" not in rows

    def test_failing_probe_reports_instead_of_raising(self):
        def boom():
            raise RuntimeError("driver exploded")
        sections = diagnostics.gather(
            None, gl_probe=boom, audio_probe=boom)
        rows = flat(sections)
        assert "RuntimeError: driver exploded" in rows["OpenGL"]
        assert "RuntimeError: driver exploded" in rows["Host APIs"]

    def test_app_section_reads_real_versions(self):
        from utils.app_identity import APP_VERSION
        rows = flat(stub_gather(None))
        assert rows["Version"] == APP_VERSION
        assert "Qt " in rows["Qt"] and "PyQt " in rows["Qt"]
        assert rows["Frozen"] == "no (source)"


class TestMarkdown:
    def test_block_shape(self):
        text = diagnostics.to_markdown(stub_gather(FakeMainWindow()))
        assert text.startswith("### Die Lichtmaschine diagnostics")
        assert "**Application**" in text
        assert "- OpenGL: `FakeGL 4.6`" in text
        assert text.endswith("\n")

    def test_report_is_gather_plus_markdown(self):
        text = diagnostics.report(
            FakeMainWindow(),
            gl_probe=lambda: "FakeGL", audio_probe=lambda: "None")
        assert "- OpenGL: `FakeGL`" in text


class TestDialog:
    def _dialog(self, text="### report"):
        from gui.dialogs.diagnostics_dialog import DiagnosticsDialog
        return DiagnosticsDialog(report_fn=lambda: text)

    def test_shows_the_report(self, qapp):
        dialog = self._dialog("### report\n- a: `b`")
        assert dialog.text_view.toPlainText() == "### report\n- a: `b`"
        assert dialog.text_view.isReadOnly()

    def test_copy_puts_the_block_on_the_clipboard(self, qapp):
        dialog = self._dialog("### block")
        dialog._copy()
        assert qapp.clipboard().text() == "### block"
        assert dialog.copied_label.text() == "Copied."

    def test_failing_report_still_opens(self, qapp):
        from gui.dialogs.diagnostics_dialog import DiagnosticsDialog

        def boom():
            raise RuntimeError("nope")
        dialog = DiagnosticsDialog(report_fn=boom)
        assert "diagnostics failed" in dialog.text_view.toPlainText()
