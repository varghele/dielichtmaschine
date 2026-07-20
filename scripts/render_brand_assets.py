#!/usr/bin/env python3
"""Render the README banner and the GitHub social preview.

The right-hand column is the machine's RATING PLATE (2026-07-20
decision): only verifiable claims - protocols, standards, formats,
version, license, platforms - never adjectives ("beat-genau",
"volumetrisch" came off). The version stamps from utils.app_identity
at render time, so re-run this after a release bump:

    python scripts/render_brand_assets.py

Outputs (committed):
    resources/brand/readme-banner-1600x400.png
    resources/brand/social-preview-1280x640.png

Drawing uses the BUNDLED fonts (Barlow Condensed ExtraBold, IBM Plex
Mono) via the app's own registration, so output is reproducible on any
machine with the repo checked out.
"""

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from PyQt6.QtCore import Qt, QPointF, QRectF
from PyQt6.QtGui import QColor, QFont, QImage, QPainter, QPen

BG = QColor("#1b1b1e")
GRID = QColor("#212123")
CREAM = QColor("#f4f1ea")
ACCENT = QColor("#f0562e")
GREY = QColor("#8d9299")
DIM = QColor("#5c6068")

GRID_STEP = 40

#: The rating plate (README banner, right column, top to bottom).
#: Colour convention (2026-07-20): SHIPPED capabilities in CREAM,
#: outstanding ones in DIM grey - the plate never claims more than the
#: wire delivers today. Each line is a list of (text, colour) segments
#: drawn right-aligned as one run.
def plate_lines(version: str):
    return [
        [("ARTNET", CREAM), (" / E1.31 / DMX", DIM)],
        [("SYNC: ", GREY), ("LTC / SMPTE", CREAM), (" / MTC / MIDI", DIM)],
        [("COMPATIBLE WITH: ", GREY),
         ("GDTF · DIN SPEC 15800 · QLC+", CREAM)],
        [(f"v{version} · GPL-3.0 · WINDOWS / LINUX", GREY)],
    ]


def _mono(px: int, weight=QFont.Weight.Medium, tracking=1.6) -> QFont:
    font = QFont("IBM Plex Mono")
    font.setPixelSize(px)
    font.setWeight(weight)
    font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, tracking)
    return font


def _display(px: int) -> QFont:
    font = QFont("Barlow Condensed")
    font.setPixelSize(px)
    font.setWeight(QFont.Weight.ExtraBold)
    font.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 103)
    return font


def _fill_background(p: QPainter, w: int, h: int) -> None:
    p.fillRect(0, 0, w, h, BG)
    pen = QPen(GRID, 1)
    p.setPen(pen)
    for x in range(GRID_STEP, w, GRID_STEP):
        p.drawLine(x, 0, x, h)
    for y in range(GRID_STEP, h, GRID_STEP):
        p.drawLine(0, y, w, y)
    # corner registration crosses
    p.setPen(QPen(DIM, 2))
    for cx, cy in ((32, 32), (w - 32, h - 32)):
        p.drawLine(cx - 8, cy, cx + 8, cy)
        p.drawLine(cx, cy - 8, cx, cy + 8)


def _draw_glyph(p: QPainter, cx: float, cy: float, radius: float) -> None:
    """The glyph ring, replicated from resources/brand/glyph-ring.svg
    (outer r30 #5c6068 / dashed r21 #f4f1ea w8 dash 8.24 rot -11.25 /
    centre r6 accent), scaled so the outer circle has ``radius``."""
    s = radius / 30.0
    p.save()
    p.translate(cx, cy)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(DIM, 1.5 * s))
    p.drawEllipse(QPointF(0, 0), 30 * s, 30 * s)
    pen = QPen(CREAM, 8 * s)
    # Flat caps: the default square cap extends every dash by half the
    # (thick) pen width each side and the segments merge into a ring.
    pen.setCapStyle(Qt.PenCapStyle.FlatCap)
    pen.setDashPattern([8.24 / 8.0, 8.24 / 8.0])
    p.setPen(pen)
    p.save()
    p.rotate(-11.25)
    p.drawEllipse(QPointF(0, 0), 21 * s, 21 * s)
    p.restore()
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(ACCENT)
    p.drawEllipse(QPointF(0, 0), 6 * s, 6 * s)
    p.restore()


def render_banner(version: str) -> QImage:
    w, h = 1600, 400
    img = QImage(w, h, QImage.Format.Format_RGB32)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    _fill_background(p, w, h)

    _draw_glyph(p, 160, 200, 72)

    p.setPen(CREAM)
    p.setFont(_display(96))
    p.drawText(QRectF(270, 100, 760, 160),
               Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
               "DIE LICHTMASCHINE")

    p.fillRect(QRectF(270, 247, 110, 6), ACCENT)
    p.setPen(CREAM)
    p.setFont(_mono(17, QFont.Weight.DemiBold, tracking=7.0))
    p.drawText(QRectF(400, 236, 400, 28),
               Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
               "ES WERDE LICHT")

    font = _mono(14, tracking=1.4)
    p.setFont(font)
    from PyQt6.QtGui import QFontMetricsF
    metrics = QFontMetricsF(font)
    right_edge = 1520.0
    y = 150
    for segments in plate_lines(version):
        x = right_edge - sum(metrics.horizontalAdvance(t)
                             for t, _c in segments)
        for text, colour in segments:
            p.setPen(colour)
            p.drawText(QRectF(x, y, 820, 22),
                       Qt.AlignmentFlag.AlignLeft
                       | Qt.AlignmentFlag.AlignVCenter, text)
            x += metrics.horizontalAdvance(text)
        y += 27
    p.end()
    return img


def render_social(version: str) -> QImage:
    w, h = 1280, 640
    img = QImage(w, h, QImage.Format.Format_RGB32)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    _fill_background(p, w, h)

    _draw_glyph(p, w / 2, 218, 57)

    p.setPen(CREAM)
    p.setFont(_display(96))
    p.drawText(QRectF(0, 300, w, 110), Qt.AlignmentFlag.AlignCenter,
               "DIE LICHTMASCHINE")

    p.setFont(_mono(16, QFont.Weight.DemiBold, tracking=7.0))
    metrics_rect = QRectF(0, 412, w, 26)
    p.setPen(CREAM)
    p.drawText(metrics_rect, Qt.AlignmentFlag.AlignCenter,
               "ES WERDE LICHT")
    # accent dashes flanking the tagline
    p.fillRect(QRectF(w / 2 - 195 - 90, 422, 90, 5), ACCENT)
    p.fillRect(QRectF(w / 2 + 195, 422, 90, 5), ACCENT)

    p.setPen(GREY)
    p.setFont(_mono(13, tracking=1.6))
    p.drawText(QRectF(0, 462, w, 22), Qt.AlignmentFlag.AlignCenter,
               "GPL-3.0 · ARTNET / E1.31 / DMX · GDTF · QLC+ · "
               "dielichtmaschine.de")
    p.end()
    return img


def main() -> None:
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from gui.fonts import register_brand_fonts
    register_brand_fonts()
    from utils.app_identity import APP_VERSION

    out_dir = os.path.join(PROJECT_ROOT, "resources", "brand")
    banner = os.path.join(out_dir, "readme-banner-1600x400.png")
    social = os.path.join(out_dir, "social-preview-1280x640.png")
    assert render_banner(APP_VERSION).save(banner)
    assert render_social(APP_VERSION).save(social)
    print(f"rendered v{APP_VERSION}:")
    print(f"   {banner}")
    print(f"   {social}")


if __name__ == "__main__":
    main()
