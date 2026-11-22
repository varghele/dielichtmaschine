"""Token-built widget stylesheets follow runtime theme switches.

Contract of ``gui/theme_style.py`` (the v1.5.6 theme sweep):

- ``active_tokens()`` names the APPLIED theme (sniffed from the app
  stylesheet, dark before any apply).
- ``bind_style(widget, build)`` applies ``build(tokens)`` now and again
  after every ``ThemeManager.apply``: inline sheets used to stay baked
  in the theme they were written under.
- re-binding replaces the builder; ``unbind_style`` clears the sheet and
  hands the builder back (the Structure tab's ColorButton clears its
  sheet around the colour picker so it cannot cascade into the dialog).

Plus the two template rules the sweep added, keyed by objectName /
dynamic property: the Stage tab TCP status and the time-signature "/".
"""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget

from gui.theme_manager import ThemeManager
from gui.theme_style import active_tokens, bind_style, unbind_style
from gui.theme_tokens import DARK, LIGHT, THEMES, render_theme


@pytest.fixture
def themes(qapp):
    manager = ThemeManager()
    manager.apply(qapp, "dark")
    yield lambda name: manager.apply(qapp, name)
    # Never leak light into other tests on this worker (token painters
    # sniff the global stylesheet).
    manager.apply(qapp, "dark")


class TestActiveTokens:
    def test_follows_the_applied_theme(self, themes):
        themes("light")
        assert active_tokens() is LIGHT
        themes("dark")
        assert active_tokens() is DARK


class TestBindStyle:
    def test_applies_now(self, themes):
        label = QLabel()
        bind_style(label, lambda t: f"color: {t['hint_text']};")
        assert label.styleSheet() == f"color: {DARK['hint_text']};"

    def test_reapplies_on_theme_switch(self, themes):
        label = QLabel()
        bind_style(label, lambda t: f"color: {t['separator_glyph']};"
                                    f" border: 1px solid {t['border']};")
        themes("light")
        assert LIGHT["border"] in label.styleSheet()
        themes("dark")
        assert DARK["border"] in label.styleSheet()

    def test_child_in_a_layout_without_a_python_reference(self, themes):
        """The usual shape in the tabs: the label is only reachable
        through its parent. The builder must survive that."""
        host = QWidget()
        QVBoxLayout(host).addWidget(QLabel("x"))
        bind_style(host.findChild(QLabel),
                   lambda t: f"background: {t['window']};")
        themes("light")
        assert LIGHT["window"] in host.findChild(QLabel).styleSheet()

    def test_rebind_replaces_the_builder(self, themes):
        label = QLabel()
        bind_style(label, lambda t: f"color: {t['text']};")
        bind_style(label, lambda t: f"color: {t['hint_text']};")
        themes("light")
        assert label.styleSheet() == f"color: {LIGHT['hint_text']};"

    def test_unbind_clears_and_returns_the_builder(self, themes):
        label = QLabel()

        def build(t):
            return f"color: {t['text']};"

        bind_style(label, build)
        assert unbind_style(label) is build
        assert label.styleSheet() == ""
        themes("light")
        assert label.styleSheet() == "", "an unbound widget must stay clear"
        bind_style(label, build)
        assert label.styleSheet() == f"color: {LIGHT['text']};"

    def test_unchanged_sheet_is_not_rewritten(self, themes):
        """setStyleSheet sends StyleChange itself; the filter must only
        write on a real change or it would recurse."""
        label = QLabel()
        calls = []

        def build(t):
            calls.append(1)
            return "font-weight: bold;"

        bind_style(label, build)
        themes("dark")
        assert label.styleSheet() == "font-weight: bold;"
        assert len(calls) < 10


class TestTemplateRules:
    def test_rules_exist_in_both_themes(self):
        for name in THEMES:
            qss = render_theme(name)
            assert "QLabel#TimeSignatureSeparator" in qss
            for status in ("idle", "stopped", "running", "connected"):
                assert f'QLabel#StageTcpStatus[status="{status}"]' in qss

    def test_time_signature_separator_is_template_styled(self, qapp):
        from gui.tabs.structure_tab import TimeSignatureWidget
        widget = TimeSignatureWidget("7/8")
        separator = widget.findChild(QLabel, "TimeSignatureSeparator")
        assert separator is not None
        assert separator.styleSheet() == ""

    def test_stage_tcp_status_sets_the_status_property(self, qapp):
        from config.models import Configuration
        from gui.tabs.stage_tab import StageTab

        class Server:
            def __init__(self, running, clients):
                self.running, self.clients = running, clients

            def is_running(self):
                return self.running

            def get_client_count(self):
                return self.clients

        class Shows:
            tcp_server = None

        tab = StageTab(Configuration(), parent=None)
        try:
            tab.tcp_status_timer.stop()
            tab.shows_tab = Shows()
            label = tab.tcp_status_label
            assert label.objectName() == "StageTcpStatus"
            for server, status in ((None, "idle"),
                                   (Server(False, 0), "stopped"),
                                   (Server(True, 0), "running"),
                                   (Server(True, 2), "connected")):
                tab.shows_tab.tcp_server = server
                tab._update_tcp_status()
                assert label.property("status") == status
                assert label.styleSheet() == ""
        finally:
            tab.deleteLater()


def _luminance(hex_color: str) -> float:
    def channel(c: int) -> float:
        c = c / 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def _contrast(a: str, b: str) -> float:
    la, lb = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


class TestLightThemeRoles:
    """The light-theme breakages the sweep exposed: dark-only literals
    (white text, near-black fills and rules, a light halo) that the
    light theme had inherited. Each role now uses the light palette."""

    @pytest.mark.parametrize("role", [
        "separator_glyph", "patchbay_halo"])
    def test_ink_roles_read_on_the_light_window(self, role):
        assert _contrast(LIGHT[role], LIGHT["window"]) >= 4.5, role

    @pytest.mark.parametrize("role,palette", [
        ("separator_glyph", "text"),
        ("patchbay_rule", "border"),
        ("patchbay_chip_border", "border"),
        ("meter_track", "border"),
    ])
    def test_light_roles_come_from_the_light_palette(self, role, palette):
        assert LIGHT[role] == LIGHT[palette]

    def test_no_light_surface_role_is_a_dark_surface(self):
        for role in ("meter_track",):
            assert _luminance(LIGHT[role]) > 0.5, role

    def test_dark_keeps_its_historic_values(self):
        """The fix is light-only: the dark theme renders as before."""
        assert DARK["separator_glyph"] == "#ffffff"
        assert DARK["meter_track"] == "#2D2D2D"
        assert DARK["patchbay_halo"] == "#F4F1EA"


class TestProgressAndRenderDialogsUseTheRegularTokens:
    """The legacy_dialog_* roles kept the pre-rebrand dark look (#3d3d3d
    frame, #2d2d2d fields, white text) on the render and progress
    dialogs; they now sit on the regular surfaces in both themes and the
    roles are gone."""

    def test_no_legacy_dialog_roles_left(self):
        for tokens in (DARK, LIGHT):
            assert not [k for k in tokens if k.startswith("legacy_dialog")]

    @pytest.mark.parametrize("name", ["dark", "light"])
    def test_progress_styles(self, name):
        from gui.progress_manager import (_log_dialog_style,
                                          _modal_progress_style,
                                          _status_bar_meter_style)
        t = THEMES[name]
        modal = _modal_progress_style(t)
        assert f"background-color: {t['window']};" in modal
        assert f"color: {t['text']};" in modal
        assert f"background-color: {t['raised']};" in modal
        log = _log_dialog_style(t)
        assert f"color: {t['text_secondary']};" in log
        assert f"border: 1px solid {t['border']};" in log
        meter = _status_bar_meter_style(t)
        assert f"background-color: {t['raised']};" in meter
        for old in ("#3d3d3d", "#2d2d2d", "#555555", "#1e1e1e", "#cccccc"):
            assert old not in (modal + log + meter).lower()

    @pytest.mark.parametrize("name", ["dark", "light"])
    def test_render_dialog(self, qapp, name):
        from config.models import Configuration
        from gui.dialogs.render_dialog import RenderDialog
        from gui.theme_manager import ThemeManager
        ThemeManager().apply(qapp, name)
        try:
            dialog = RenderDialog(Configuration(), {})
            t = THEMES[name]
            sheet = dialog.styleSheet()
            assert f"QDialog {{ background-color: {t['window']}; }}" in sheet
            assert f"background-color: {t['raised']}; color: {t['text']}" \
                in sheet
            assert f"background-color: {t['border']};" in \
                dialog._render_btn.styleSheet()
            dialog.deleteLater()
        finally:
            ThemeManager().apply(qapp, "dark")

    def test_square_corners(self):
        """Brand radius is 0: the render and progress dialogs used to
        round their frames, fields, bars and buttons by 2-4 px."""
        import re
        from pathlib import Path
        root = Path(__file__).resolve().parents[2]
        for rel in ("gui/dialogs/render_dialog.py", "gui/progress_manager.py"):
            src = (root / rel).read_text(encoding="utf-8")
            assert not re.search(r"border-radius:\s*[1-9]", src), rel

