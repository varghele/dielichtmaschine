"""2D icon library for fixtures.

Primary path (North Star slice S1): the design handoff's stage-plot
symbol set. Each mapped legacy fixture ``type`` string renders its
``resources/stageplot/<symbol>.svg`` (48x48 viewBox, single-color line
art) with the stroke token ``#8d9299`` substituted by the fixture's
group color (taken from the painter's current brush). Used by
``FixtureItem.paint`` (Stage tab) and ``gui/stage_plot.py`` (printable
plot).

Fallback path: the original hand-painted chassis primitives, kept for
unknown / unmapped types and for callers that pass only a
:class:`Chassis` (no ``fixture_type``).

Conventions:
- Icons are drawn centered at the painter's local origin ``(0, 0)``.
- ``size`` is the nominal width of the bounding box; the BAR variants
  (legacy primitives AND the led-bar / pixel-bar / sunstrip symbols)
  extend to ``2 * size`` along X to read as elongated.
- The painter's existing brush + pen drive the body fill + outline of
  the legacy primitives; the SVG symbols take the brush color as their
  stroke color (alpha becomes painter opacity, so the selected state's
  translucent brush still reads).
- Symbol orientation: the SVGs put the beam tick at the top ("up").
  Non-bar symbols are rotated +90 degrees at paint time so the tick
  lands on local +X, the facing direction the legacy MOVING_YOKE
  triangle and the stage plot's orientation tick already use. Callers
  keep rotating the painter by yaw exactly as before.
- :func:`paint_fixture_icon` accepts an optional ``accent`` kwarg so a
  plain ``Chassis.BAR`` can render with the legacy "pixels" or "lamps"
  ornament when the caller knows the fixture has per-cell control
  (fallback path only; the symbols carry their own cell ornaments).
"""

from __future__ import annotations

import os
from typing import Dict, Optional, Tuple

from PyQt6.QtCore import QByteArray, QPointF, QRectF, Qt
from PyQt6.QtGui import QBrush, QColor, QImage, QPainter, QPen, QPixmap

from utils.fixture_capabilities import Chassis
from utils.paths import get_project_root


# Accent values understood by paint_fixture_icon.
ACCENT_PIXELS = 'pixels'   # colored cells inside a BAR (PIXELBAR / pixel matrix)
ACCENT_LAMPS = 'lamps'     # white lamp circles inside a BAR (SUNSTRIP)


# ---------------------------------------------------------------------------
# Stage-plot symbol set (design handoff, North Star slice S1)
# ---------------------------------------------------------------------------

# Legacy fixture ``type`` string -> symbol file stem in resources/stageplot/.
# The legacy enum has no pixel-matrix / blinder / strobe / scanner / laser
# strings yet; those symbols ship in resources/stageplot/ ready for the
# richer taxonomy.
STAGEPLOT_SYMBOL_BY_TYPE: Dict[str, str] = {
    'PAR': 'par',
    'MH': 'moving-head-spot',
    'WASH': 'moving-wash',
    'BAR': 'led-bar',
    'PIXELBAR': 'pixel-bar',
    'SUNSTRIP': 'sunstrip',
}

# Symbols whose artwork is a full-width bar: rendered into a 2*size box
# (length along local X) and NOT rotated by the tick convention, so the
# bar's length axis matches the legacy BAR primitives.
_BAR_SYMBOLS = frozenset({'led-bar', 'pixel-bar', 'sunstrip'})

# The single stroke/fill color token used by every handoff SVG.
_SYMBOL_COLOR_TOKENS = ('#8d9299', '#8D9299')

# Rasterize at 3x the target box so scaled-down draws (and PDF embeds)
# stay crisp; mirrors the 1x/2x/3x ladder in gui/icons.py.
_SYMBOL_SUPERSAMPLE = 3

_symbol_svg_cache: Dict[str, Optional[str]] = {}
_symbol_pixmap_cache: Dict[Tuple[str, int, int], QPixmap] = {}


def stageplot_dir() -> str:
    return os.path.join(get_project_root(), 'resources', 'stageplot')


def stageplot_symbol_path(name: str) -> str:
    return os.path.join(stageplot_dir(), f'{name}.svg')


def symbol_for_fixture_type(fixture_type: Optional[str]) -> Optional[str]:
    """Symbol file stem for a legacy fixture type string, or None."""
    if not fixture_type:
        return None
    return STAGEPLOT_SYMBOL_BY_TYPE.get(fixture_type)


def clear_symbol_caches() -> None:
    """Drop cached SVG text + rendered pixmaps (tests / file changes)."""
    _symbol_svg_cache.clear()
    _symbol_pixmap_cache.clear()


def _load_symbol_svg(name: str) -> Optional[str]:
    if name in _symbol_svg_cache:
        return _symbol_svg_cache[name]
    try:
        with open(stageplot_symbol_path(name), 'r', encoding='utf-8') as f:
            svg = f.read()
    except OSError:
        svg = None
    _symbol_svg_cache[name] = svg
    return svg


def _symbol_pixmap(name: str, color: QColor, px: int) -> Optional[QPixmap]:
    """Rasterized symbol with the color token substituted, cached per
    (symbol, opaque RGB, pixel size). Alpha is applied at draw time via
    painter opacity so translucent variants share the cache entry."""
    key = (name, color.rgb(), px)
    cached = _symbol_pixmap_cache.get(key)
    if cached is not None:
        return cached

    svg = _load_symbol_svg(name)
    if svg is None:
        return None

    from PyQt6.QtSvg import QSvgRenderer

    hex_color = QColor(color.rgb()).name()  # opaque #rrggbb
    for token in _SYMBOL_COLOR_TOKENS:
        svg = svg.replace(token, hex_color)
    renderer = QSvgRenderer(QByteArray(svg.encode('utf-8')))
    if not renderer.isValid():
        return None

    image = QImage(px, px, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    p = QPainter(image)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(p)
    p.end()

    pixmap = QPixmap.fromImage(image)
    _symbol_pixmap_cache[key] = pixmap
    return pixmap


def _paint_symbol_icon(painter: QPainter, symbol: str, size: float) -> bool:
    """Draw one stage-plot symbol centered at the origin. Returns False
    when the SVG is missing/invalid so the caller can fall back."""
    color = painter.brush().color()
    is_bar = symbol in _BAR_SYMBOLS
    box = size * 2 if is_bar else size
    px = max(8, int(round(box * _SYMBOL_SUPERSAMPLE)))
    pixmap = _symbol_pixmap(symbol, color, px)
    if pixmap is None:
        return False

    painter.save()
    if color.alpha() < 255:
        painter.setOpacity(painter.opacity() * color.alpha() / 255.0)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    if not is_bar:
        # Beam tick points "up" (-Y) in the artwork; rotate so it lands
        # on local +X, the facing direction the callers' yaw rotation
        # assumes (legacy triangle / stage-plot tick convention).
        painter.rotate(90.0)
    target = QRectF(-box / 2, -box / 2, box, box)
    painter.drawPixmap(target, pixmap, QRectF(pixmap.rect()))
    painter.restore()
    return True


def paint_fixture_icon(
    painter: QPainter,
    chassis: Chassis,
    size: float,
    *,
    accent: Optional[str] = None,
    fixture_type: Optional[str] = None,
) -> bool:
    """Paint the fixture icon centered at the painter's origin.

    When ``fixture_type`` maps to a stage-plot symbol (North Star set),
    the SVG renders in the painter's brush color and the function
    returns True. Otherwise the legacy hand-painted chassis primitive
    is drawn (brush + pen contract unchanged) and False is returned, so
    callers can tell which visual language was used (e.g. to draw their
    own selection ring around the line symbols).

    Args:
        painter: Active QPainter. Brush + pen are the body fill + outline
            (legacy path); the brush color is the stroke color (symbol path).
        chassis: Fallback icon when no symbol maps.
        size: Nominal size in painter units (existing FixtureItem uses 30px).
        accent: Optional accent for the legacy BAR — ``"pixels"`` (colored
            cells) or ``"lamps"`` (white lamp circles). Other chassis and
            the symbol path ignore it.
        fixture_type: Legacy fixture ``type`` string (``"PAR"``, ``"MH"``,
            ...). Optional; chassis-only callers keep the legacy visuals.
    """
    symbol = symbol_for_fixture_type(fixture_type)
    if symbol is not None and _paint_symbol_icon(painter, symbol, size):
        return True

    if chassis is Chassis.PAR:
        _paint_par_icon(painter, size)
    elif chassis is Chassis.BAR:
        _paint_bar_icon(painter, size, accent=accent)
    elif chassis is Chassis.PANEL:
        _paint_panel_icon(painter, size)
    elif chassis is Chassis.MOVING_YOKE:
        _paint_moving_yoke_icon(painter, size)
    elif chassis is Chassis.SCANNER:
        _paint_scanner_icon(painter, size)
    elif chassis is Chassis.EFFECT:
        _paint_effect_icon(painter, size)
    elif chassis is Chassis.PARTICLE:
        _paint_particle_icon(painter, size)
    elif chassis is Chassis.LASER:
        _paint_laser_icon(painter, size)
    else:
        _paint_other_icon(painter, size)
    return False


# ---------------------------------------------------------------------------
# Legacy fallback primitives (unknown / unmapped types keep these)
# ---------------------------------------------------------------------------


def _paint_par_icon(painter: QPainter, size: float) -> None:
    """PAR — circle. Existing FixtureItem PAR visual."""
    painter.drawEllipse(QRectF(-size / 2, -size / 2, size, size))


def _paint_bar_icon(
    painter: QPainter,
    size: float,
    *,
    accent: Optional[str] = None,
) -> None:
    """BAR — elongated rectangle (2:1 aspect by way of size×2 width).

    Optional accent draws cell squares (``"pixels"``) or lamp circles
    (``"lamps"``) inside the bar, mirroring the legacy PIXELBAR/SUNSTRIP
    visuals. The caller is expected to opt into accent only when the
    underlying fixture actually has per-cell DMX or per-cell dimmer.
    """
    bar_height = size / 3
    bar_width = size * 2
    painter.drawRect(QRectF(-size, -bar_height / 2, bar_width, bar_height))

    if accent == ACCENT_PIXELS:
        _draw_pixel_accents(painter, size, bar_width)
    elif accent == ACCENT_LAMPS:
        _draw_lamp_accents(painter, size, bar_width)


def _draw_pixel_accents(painter: QPainter, size: float, bar_width: float) -> None:
    """Six alternating-color squares inside a BAR — PIXELBAR cue."""
    painter.save()
    segment_count = 6
    spacing = (bar_width * 0.85) / segment_count
    start_x = -size * 0.85 + spacing / 2
    seg_size = spacing * 0.7
    colors = [
        QColor(255, 100, 100),
        QColor(100, 255, 100),
        QColor(100, 100, 255),
        QColor(255, 255, 100),
        QColor(255, 100, 255),
        QColor(100, 255, 255),
    ]
    for i in range(segment_count):
        x = start_x + i * spacing - seg_size / 2
        painter.setBrush(QBrush(colors[i % len(colors)]))
        painter.drawRect(QRectF(x, -seg_size / 2, seg_size, seg_size))
    painter.restore()


def _draw_lamp_accents(painter: QPainter, size: float, bar_width: float) -> None:
    """Five small circles inside a BAR — SUNSTRIP cue."""
    painter.save()
    bulb_count = 5
    spacing = (bar_width * 0.85) / bulb_count
    start_x = -size * 0.85 + spacing / 2
    bulb_radius = 3.0
    for i in range(bulb_count):
        x = start_x + i * spacing
        painter.drawEllipse(QRectF(x - bulb_radius, -bulb_radius, bulb_radius * 2, bulb_radius * 2))
    painter.restore()


def _paint_panel_icon(painter: QPainter, size: float) -> None:
    """PANEL — square (LED matrix / video panel)."""
    painter.drawRect(QRectF(-size / 2, -size / 2, size, size))


# ---------------------------------------------------------------------------
# Moving fixtures
# ---------------------------------------------------------------------------


def _paint_moving_yoke_icon(painter: QPainter, size: float) -> None:
    """Moving head — circle + direction triangle. Mirrors legacy MH visual."""
    painter.drawEllipse(QRectF(-size / 2, -size / 2, size, size))
    triangle = [
        QPointF(size / 2, 0),
        QPointF(0, -size / 4),
        QPointF(0, size / 4),
    ]
    painter.drawPolygon(triangle)


def _paint_scanner_icon(painter: QPainter, size: float) -> None:
    """Scanner — square with a small protruding mirror cue on +X."""
    half = size / 2
    painter.drawRect(QRectF(-half, -half, size, size))
    # Mirror cue: small triangle on the +X edge
    painter.save()
    mirror_w = size * 0.18
    triangle = [
        QPointF(half, -mirror_w / 2),
        QPointF(half + mirror_w, 0),
        QPointF(half, mirror_w / 2),
    ]
    painter.drawPolygon(triangle)
    painter.restore()


# ---------------------------------------------------------------------------
# Effect / particle / laser / other
# ---------------------------------------------------------------------------


def _paint_effect_icon(painter: QPainter, size: float) -> None:
    """Effect — hexagon (centipede / derby / sweeper variants)."""
    half = size / 2
    h = half * 0.866  # cos(30°) ≈ 0.866
    hexagon = [
        QPointF(half, 0),
        QPointF(half / 2, -h),
        QPointF(-half / 2, -h),
        QPointF(-half, 0),
        QPointF(-half / 2, h),
        QPointF(half / 2, h),
    ]
    painter.drawPolygon(hexagon)


def _paint_particle_icon(painter: QPainter, size: float) -> None:
    """Particle — three overlapping circles forming a cloud silhouette."""
    r = size * 0.32
    centers = [
        QPointF(-size * 0.22, size * 0.05),
        QPointF(0.0, -size * 0.10),
        QPointF(size * 0.22, size * 0.05),
    ]
    for c in centers:
        painter.drawEllipse(QRectF(c.x() - r, c.y() - r, r * 2, r * 2))


def _paint_laser_icon(painter: QPainter, size: float) -> None:
    """Laser — triangle pointing +X."""
    half = size / 2
    triangle = [
        QPointF(half, 0),
        QPointF(-half * 0.6, -half),
        QPointF(-half * 0.6, half),
    ]
    painter.drawPolygon(triangle)


def _paint_other_icon(painter: QPainter, size: float) -> None:
    """Unknown / dimmer pack / fan — square with a "?" glyph."""
    half = size / 2
    painter.drawRect(QRectF(-half, -half, size, size))
    painter.save()
    pen = painter.pen()
    text_pen = QPen(QColor(220, 220, 220))
    text_pen.setWidthF(max(1.0, pen.widthF()))
    painter.setPen(text_pen)
    font = painter.font()
    font.setPointSizeF(max(8.0, size * 0.5))
    font.setBold(True)
    painter.setFont(font)
    painter.drawText(
        QRectF(-half, -half, size, size),
        int(Qt.AlignmentFlag.AlignCenter),
        '?',
    )
    painter.restore()
