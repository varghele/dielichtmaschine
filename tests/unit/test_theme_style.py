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
        "separator_glyph", "legacy_dialog_text", "patchbay_halo"])
    def test_ink_roles_read_on_the_light_window(self, role):
        assert _contrast(LIGHT[role], LIGHT["window"]) >= 4.5, role

    @pytest.mark.parametrize("role,palette", [
        ("legacy_dialog_bg", "window"),
        ("legacy_dialog_field", "raised"),
        ("legacy_dialog_border", "border"),
        ("legacy_dialog_text", "text"),
        ("legacy_dialog_log_bg", "raised"),
        ("separator_glyph", "text"),
        ("patchbay_rule", "border"),
        ("patchbay_chip_border", "border"),
        ("meter_track", "border"),
    ])
    def test_light_roles_come_from_the_light_palette(self, role, palette):
        assert LIGHT[role] == LIGHT[palette]

    def test_no_light_surface_role_is_a_dark_surface(self):
        for role in ("legacy_dialog_bg", "legacy_dialog_field",
                     "legacy_dialog_log_bg", "meter_track"):
            assert _luminance(LIGHT[role]) > 0.5, role

    def test_dark_keeps_its_historic_values(self):
        """The fix is light-only: the dark theme renders as before."""
        assert DARK["separator_glyph"] == "#ffffff"
        assert DARK["legacy_dialog_bg"] == "#3d3d3d"
        assert DARK["meter_track"] == "#2D2D2D"
        assert DARK["patchbay_halo"] == "#F4F1EA"
