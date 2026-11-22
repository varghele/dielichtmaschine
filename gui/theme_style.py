"""Token-built widget stylesheets that follow theme switches.

Inline ``setStyleSheet`` strings are baked: a theme switch re-renders
the APP stylesheet (ThemeManager.apply) but leaves every widget-local
sheet exactly as it was written. A widget whose local sheet mixes data
(a user-picked fill) with chrome (its border) therefore keeps the old
theme's chrome after View > Theme, unless something re-builds it.

``bind_style(widget, build)`` is that something: ``build(tokens)``
returns the sheet for a token dict, it is applied now, and an event
filter re-applies it on every ``QEvent.StyleChange`` (which
``app.setStyleSheet`` sends to every widget). Re-binding replaces the
builder, so state changes (a new swatch colour, a new status) just
bind again.

Chrome that carries no data belongs in the template instead
(``resources/themes/theme.qss.template``, keyed by objectName or a
dynamic property); ``tests/unit/test_theme_lint.py`` keeps colour
literals out of every ``setStyleSheet`` call.
"""

from typing import Callable

from PyQt6.QtCore import QEvent, QObject
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QApplication, QWidget

from gui.theme_tokens import THEMES

_BUILD_ATTR = "_theme_style_build"
_FILTER_ATTR = "_theme_style_filtered"


def active_theme_name() -> str:
    """Name of the theme currently applied to the app.

    ThemeManager.apply deliberately does not persist, so the applied
    stylesheet is the only reliable record of the active theme: the
    light theme's window colour only ever appears in the light sheet.
    Falls back to dark (also before the first apply). Not
    ThemeManager.current(): View > Theme applies BEFORE it persists, so
    a StyleChange handler reading the settings store sees the old theme.
    """
    app = QApplication.instance()
    qss = app.styleSheet() if app is not None else ""
    light = THEMES.get("light")
    if light is not None and light["window"] in qss:
        return "light"
    return "dark"


def active_tokens() -> dict:
    """Token dict of the theme currently applied to the app (see
    active_theme_name)."""
    return THEMES[active_theme_name()]


def token_color(key: str, alpha: int = 255) -> QColor:
    """An active-theme token as a QColor, optionally with an alpha
    (painters: the numeric QColor literals became tokens, the alpha of
    each use stays with the code)."""
    color = QColor(active_tokens()[key])
    if alpha != 255:
        color.setAlpha(alpha)
    return color


class _ThemeRestyler(QObject):
    """Re-applies a bound builder when its widget's style changes."""

    def eventFilter(self, obj, event):  # noqa: N802 (Qt API)
        if event.type() == QEvent.Type.StyleChange:
            _apply(obj)
        return False


_RESTYLER = None


def _restyler() -> _ThemeRestyler:
    global _RESTYLER
    if _RESTYLER is None:
        _RESTYLER = _ThemeRestyler()
    return _RESTYLER


def _apply(widget: QWidget) -> None:
    build = getattr(widget, _BUILD_ATTR, None)
    if build is None:
        return
    sheet = build(active_tokens())
    # setStyleSheet itself sends StyleChange: only write on a real
    # change, or the filter would recurse.
    if widget.styleSheet() != sheet:
        widget.setStyleSheet(sheet)


def bind_style(widget: QWidget, build: Callable[[dict], str]) -> None:
    """Style ``widget`` with ``build(active_tokens())`` now and after
    every theme switch. Calling it again replaces the builder."""
    setattr(widget, _BUILD_ATTR, build)
    if not getattr(widget, _FILTER_ATTR, False):
        setattr(widget, _FILTER_ATTR, True)
        widget.installEventFilter(_restyler())
    _apply(widget)


def unbind_style(widget: QWidget):
    """Drop the widget's bound builder and clear its sheet; returns the
    builder (None if there was none) so the caller can re-bind it."""
    build = getattr(widget, _BUILD_ATTR, None)
    setattr(widget, _BUILD_ATTR, None)
    widget.setStyleSheet("")
    return build
