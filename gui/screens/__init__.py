"""Fullscreen takeover screens (North Star cards 11x).

Unlike gui/tabs, these are standalone top-level windows that cover the
whole display: the screensaver / pause screen lives here, and future
takeover surfaces (loader, venue-check kiosk) join it.
"""

from gui.screens.screensaver import ScreensaverWindow

__all__ = ["ScreensaverWindow"]
