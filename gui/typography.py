"""Brand typography helpers.

The North Star design uses three text voices (see
design_handoff_lichtmaschine_app/README.md, "Typografie"):

- display: Barlow Condensed 600-800, ALL CAPS, tracked 0.04-0.12em -
  headlines, tab labels, panel titles
- ui: Barlow 400-600 - body text (set app-wide by the QSS template)
- mono: IBM Plex Mono 400-600 - numeric readouts and micro-labels,
  micro-labels tracked 0.1-0.2em

QSS cannot express letter-spacing or text-transform, so tracking and
uppercasing live here. Use these helpers instead of hand-building
QFonts; the QSS template can hook the labels via their ``role``
dynamic property (``display`` / ``micro``) for colors.
"""

from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QLabel

from gui.fonts import FONT_DISPLAY, FONT_MONO


def _apply_tracking(font: QFont, tracking_em: float) -> QFont:
    """Letter-spacing as a fraction of an em (0.06 = +6%)."""
    if tracking_em:
        font.setLetterSpacing(
            QFont.SpacingType.PercentageSpacing, 100.0 + tracking_em * 100.0)
    return font


def display_font(point_size: int, weight: QFont.Weight = QFont.Weight.DemiBold,
                 tracking_em: float = 0.06) -> QFont:
    """Barlow Condensed with tracking; pair with ALL-CAPS text."""
    font = QFont(FONT_DISPLAY, point_size)
    font.setWeight(weight)
    return _apply_tracking(font, tracking_em)


def mono_font(point_size: int, weight: QFont.Weight = QFont.Weight.Medium,
              tracking_em: float = 0.0) -> QFont:
    """IBM Plex Mono for readouts (no tracking) and micro-labels
    (pass 0.1-0.2)."""
    font = QFont(FONT_MONO, point_size)
    font.setWeight(weight)
    return _apply_tracking(font, tracking_em)


class _CapsLabel(QLabel):
    """QLabel that renders its text uppercased (the stored/original
    text stays as set, so translations keep their natural casing)."""

    def setText(self, text: str) -> None:  # noqa: N802 (Qt API)
        super().setText((text or "").upper())


class DisplayLabel(_CapsLabel):
    """Condensed-caps display text (headlines, panel titles, wordmark)."""

    def __init__(self, text: str = "", point_size: int = 15,
                 weight: QFont.Weight = QFont.Weight.DemiBold,
                 tracking_em: float = 0.06, parent=None):
        super().__init__(parent)
        self.setProperty("role", "display")
        self.setFont(display_font(point_size, weight, tracking_em))
        self.setText(text)


class MicroLabel(_CapsLabel):
    """Tiny tracked mono caps (BPM/DMX tags, filenames, status text)."""

    def __init__(self, text: str = "", point_size: int = 8,
                 weight: QFont.Weight = QFont.Weight.Medium,
                 tracking_em: float = 0.12, parent=None):
        super().__init__(parent)
        self.setProperty("role", "micro")
        self.setFont(mono_font(point_size, weight, tracking_em))
        self.setText(text)
