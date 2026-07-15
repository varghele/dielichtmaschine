"""
ThemeManager - render Qt stylesheet themes and persist the user's choice.

Themes are token dicts in ``gui/theme_tokens.py`` rendered through the
single QSS template ``resources/themes/theme.qss.template``. Adding a
new theme is a matter of adding a token dict to ``THEMES`` there. The
chosen name is stored via ``QSettings`` under ``ui/theme`` so it
survives restarts.
"""

from typing import Optional

from PyQt6.QtWidgets import QApplication

from gui.theme_tokens import THEMES, render_theme
from utils.app_settings import app_settings


_SETTINGS_KEY = "ui/theme"
_DEFAULT_THEME = "dark"


class ThemeManager:
    """Apply and persist Qt stylesheet themes."""

    def available_themes(self) -> list:
        """Return the list of theme names recognised by the manager."""
        return list(THEMES)

    def current(self) -> Optional[str]:
        """Read the persisted theme name. None if never set."""
        value = app_settings().value(_SETTINGS_KEY, type=str)
        return value or None

    def set_current(self, name: str) -> None:
        """Persist the chosen theme name."""
        app_settings().setValue(_SETTINGS_KEY, name)

    def apply(self, app: QApplication, name: str) -> bool:
        """Render the theme's tokens through the QSS template and apply it.

        Deliberately does NOT persist the choice: apply() is called by
        tests and by startup, and persisting here let a test run
        overwrite the user's saved theme (the "app keeps opening light"
        bug). Persist explicitly via set_current() on user action.

        After loading the stylesheet, all top-level widgets are unpolished
        and re-polished so dynamic-property selectors (e.g. status pills
        keyed off a ``status`` property) re-evaluate. Returns False if the
        template cannot be read or rendered.
        """
        if name not in self.available_themes():
            print(f"ThemeManager: unknown theme '{name}', falling back to '{_DEFAULT_THEME}'")
            name = _DEFAULT_THEME

        try:
            qss = render_theme(name)
        except (OSError, KeyError, ValueError) as e:
            print(f"ThemeManager: failed to render theme '{name}': {e}")
            return False

        app.setStyleSheet(qss)
        # Force re-polishing of every widget so dynamic properties like
        # `status="on"` pick up the new theme's selectors.
        for widget in app.allWidgets():
            style = widget.style()
            if style:
                style.unpolish(widget)
                style.polish(widget)
            widget.update()

        return True
