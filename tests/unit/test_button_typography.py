"""Buttons speak in one voice per row.

The user's report: "in the structure and in the timeline, there are
multiple font inconsistencies between buttons". The cause was the
[role="primary"] rule pinning the *display* family (Barlow Condensed)
onto sentence-case buttons, so a single toolbar could show Barlow
Condensed ("Save"), Barlow bold ("+ Add Light Lane") and Barlow regular
("Inspector") side by side.

The rule now: the display family belongs to uppercase CTAs only, which
carry role="cta-accent" (filled) or role="cta-outline" (bordered).
Everything else is the UI family at weight 600.

Fonts must never be asserted through widget.font() - the app-wide
QWidget font-family QSS rule beats setFont() depending on polish order
(docs/qt-gotchas.md). Assert the role property and the theme rule.
"""

import os
import re

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from gui.theme_tokens import render_theme

# Roles whose text is rendered in Barlow Condensed. Their button text is
# uppercase by convention, so the condensed caps read as a deliberate CTA.
DISPLAY_ROLES = {"cta-accent", "cta-outline"}
# Roles that must stay in the UI family: they sit next to plain buttons.
UI_FONT_ROLES = {"primary", "success", "destructive", "add-tile"}


def _rule_body(qss: str, selector: str) -> str:
    """Return the declarations of the first `selector { ... }` block."""
    match = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", qss)
    assert match, f"{selector} missing from the theme"
    return match.group(1)


@pytest.mark.parametrize("theme", ["dark", "light"])
class TestThemeRules:
    def test_display_roles_pin_the_display_family(self, theme):
        qss = render_theme(theme)
        for role in DISPLAY_ROLES:
            body = _rule_body(qss, f'QPushButton[role="{role}"]')
            assert "font-family" in body, f"{role} must pin its family"

    def test_ui_font_roles_do_not_override_the_family(self, theme):
        """A filled button is a color, not a typeface."""
        qss = render_theme(theme)
        for role in UI_FONT_ROLES:
            body = _rule_body(qss, f'QPushButton[role="{role}"]')
            assert "font-family" not in body, (
                f'QPushButton[role="{role}"] pins a font family; it would '
                "clash with the plain buttons beside it")

    def test_the_base_button_pins_one_weight(self, theme):
        """Filled and plain buttons used to differ (bold vs regular)."""
        body = _rule_body(qss := render_theme(theme), "QPushButton")
        assert "font-weight: 600" in body
        for role in ("success", "destructive", "primary"):
            assert "font-weight" not in _rule_body(
                qss, f'QPushButton[role="{role}"]'), (
                f"{role} re-declares a weight and breaks the row")


def _buttons(widget):
    from PyQt6.QtWidgets import QPushButton
    return widget.findChildren(QPushButton)


def _roles(widget):
    return {b: (b.property("role") or "") for b in _buttons(widget)}


class TestTabsAgreeWithTheRule:
    """Uppercase text and the display family travel together."""

    @pytest.fixture
    def tabs(self, qapp):
        from config.models import Configuration
        from gui.tabs.structure_tab import StructureTab
        from gui.tabs.shows_tab import ShowsTab

        config = Configuration()
        built = [StructureTab(config, parent=None), ShowsTab(config, parent=None)]
        yield built
        for tab in built:
            tab.deleteLater()

    def test_display_role_buttons_are_uppercase(self, tabs):
        for tab in tabs:
            for button, role in _roles(tab).items():
                if role in DISPLAY_ROLES and button.text():
                    assert button.text() == button.text().upper(), (
                        f"{button.text()!r} carries role={role} but is not "
                        "uppercase, so the condensed caps look like a bug")

    def test_sentence_case_buttons_never_take_a_display_role(self, tabs):
        for tab in tabs:
            for button, role in _roles(tab).items():
                text = button.text()
                if text and text != text.upper():
                    assert role not in DISPLAY_ROLES, f"{text!r} -> {role}"

    def test_every_button_role_is_one_the_theme_knows(self, tabs):
        qss = render_theme("dark")
        for tab in tabs:
            for button, role in _roles(tab).items():
                if role:
                    assert f'[role="{role}"]' in qss, (
                        f"{button.text()!r} uses an unstyled role {role!r}")


class TestCallSitesMigrated:
    """The loud caps CTAs moved off role=primary onto role=cta-accent."""

    def test_fixtures_add_button(self, qapp):
        from config.models import Configuration
        from gui.tabs.fixtures_tab import FixturesTab
        tab = FixturesTab(Configuration(), parent=None)
        try:
            assert tab.add_btn.text() == "+ ADD FIXTURE"
            assert tab.add_btn.property("role") == "cta-accent"
        finally:
            tab.deleteLater()

    def test_home_call_to_action_pair(self, qapp):
        from gui.widgets.home_screen import HomeScreen
        home = HomeScreen(parent=None)
        try:
            assert home.template_btn.property("role") == "cta-accent"
            assert home.open_btn.property("role") == "cta-outline"
        finally:
            home.deleteLater()

    def test_timeline_toolbar_shares_one_family(self, qapp):
        """SAVE / AUTOGEN / INSPECTOR / + LANE / POP OUT.

        Autogen is the sole accent-filled CTA (cta-accent); the other
        text actions read uniform as bordered display caps (cta-outline);
        the Add action stays the success color. (Texts compacted to the
        timeline v3 mock wording in stage T1.)
        """
        from config.models import Configuration
        from gui.tabs.shows_tab import ShowsTab
        tab = ShowsTab(Configuration(), parent=None)
        try:
            assert tab.autogen_btn.property("role") == "cta-accent"
            assert tab.save_btn.property("role") == "cta-outline"
            assert tab.inspector_btn.property("role") == "cta-outline"
            assert tab.add_lane_btn.property("role") == "success"
            assert tab.pane_popout_btn.text() == "POP OUT"
            assert tab.pane_popout_btn.property("role") == "cta-outline"
            # Display-caps CTAs carry uppercase text.
            assert tab.autogen_btn.text() == "AUTOGEN"
            assert tab.save_btn.text() == "SAVE"
            assert tab.inspector_btn.text() == "INSPECTOR"
        finally:
            tab.deleteLater()
