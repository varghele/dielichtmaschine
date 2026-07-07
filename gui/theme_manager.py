"""
ThemeManager — load Qt stylesheet themes and persist the user's choice.

Themes live as `.qss` files in `resources/themes/`. Adding a new theme is a
matter of dropping a new `.qss` file there and updating ``available_themes``.
The chosen name is stored via ``QSettings`` under ``ui/theme`` so it survives
restarts.
"""

import os
from typing import Optional

from PyQt6.QtWidgets import QApplication

from utils.app_settings import app_settings
from utils.paths import get_project_root


_SETTINGS_KEY = "ui/theme"
_DEFAULT_THEME = "dark"


class ThemeManager:
    """Apply and persist Qt stylesheet themes."""

    def available_themes(self) -> list:
        """Return the list of theme names recognised by the manager."""
        return ["dark", "light"]

    def current(self) -> Optional[str]:
        """Read the persisted theme name. None if never set."""
        value = app_settings().value(_SETTINGS_KEY, type=str)
        return value or None

    def set_current(self, name: str) -> None:
        """Persist the chosen theme name."""
        app_settings().setValue(_SETTINGS_KEY, name)

    def apply(self, app: QApplication, name: str) -> bool:
        """Load ``resources/themes/<name>.qss`` and apply it to ``app``.

        After loading the stylesheet, all top-level widgets are unpolished
        and re-polished so dynamic-property selectors (e.g. status pills
        keyed off a ``status`` property) re-evaluate. Returns False if the
        theme file is missing.
        """
        if name not in self.available_themes():
            print(f"ThemeManager: unknown theme '{name}', falling back to '{_DEFAULT_THEME}'")
            name = _DEFAULT_THEME

        path = os.path.join(get_project_root(), "resources", "themes", f"{name}.qss")
        if not os.path.isfile(path):
            print(f"ThemeManager: stylesheet not found at {path}")
            return False

        try:
            with open(path, "r", encoding="utf-8") as f:
                qss = f.read()
        except OSError as e:
            print(f"ThemeManager: failed to read {path}: {e}")
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

        self.set_current(name)
        return True
