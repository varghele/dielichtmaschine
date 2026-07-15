# gui/stage_plot.py
"""Stage plot export: the rig plot a touring engineer hands to the venue.

Draws directly from the Configuration onto any QPaintDevice — vector PDF
via QPdfWriter or raster PNG via QImage — independent of the interactive
StageView (no selection chrome, no theme colors, print-friendly white
background).

Contents: title block (config name, date, stage dims, scale, fixture
count), the stage rectangle with grid + meter labels + AUDIENCE edge
marker, every fixture as its chassis symbol in group color with an
orientation tick and a name + universe.address(+layer) label, stage
marks (spots), and a legend column listing groups, stage layers, and a
scale bar. Labels avoid each other and the symbols via a greedy
candidate-position search (choose_label_rect).

Orientation matches the Stage tab's 2D view: negative stage-Y (the
audience side) is the bottom edge of the plot.
"""

from __future__ import annotations

import datetime
import os
from typing import List, Optional

from PyQt6.QtCore import QMarginsF, QRectF, Qt
from PyQt6.QtGui import (
    QBrush, QColor, QFont, QImage, QPageLayout, QPageSize, QPainter,
    QPdfWriter, QPen,
)

from utils.fixture_capabilities import chassis_from_legacy_type
from gui.stage_items import projected_bar_angle_2d
from gui.widgets.fixture_icons import (
    ACCENT_LAMPS,
    ACCENT_PIXELS,
    paint_fixture_icon,
)

# Landscape paper presets: name -> (width_mm, height_mm, QPageSize id).
PAPER_PRESETS = {
    "A4": (297.0, 210.0, QPageSize.PageSizeId.A4),
    "A3": (420.0, 297.0, QPageSize.PageSizeId.A3),
    "A2": (594.0, 420.0, QPageSize.PageSizeId.A2),
}

_BAR_TYPES = ("BAR", "PIXELBAR", "SUNSTRIP")


def plot_fixture_angle(fixture_type: str, yaw: float, pitch: float,
                       roll: float) -> float:
    """Screen rotation (degrees) a fixture symbol's facing/beam is drawn
    with on the plot.

    Matches the Stage tab's FixtureItem._paint_rotation. The plot renders
    the audience/front (negative stage-Y) at the BOTTOM, and only fixture
    POSITION was mirrored by that flip; the drawn direction must be
    mirrored too or a front-aimed beam points upstage. A vertical
    reflection composed with rotate(a) equals rotate(-a) for a facing
    along the horizontal (local +X) axis, so we negate the un-mirrored
    facing angle. Bars project their full orientation via
    projected_bar_angle_2d; everything else faces yaw + 90 (the icon's
    beam tick sits on local +X)."""
    is_bar = fixture_type in _BAR_TYPES
    base = (projected_bar_angle_2d(yaw, pitch, roll) if is_bar
            else yaw + 90)
    return -base


def choose_label_rect(anchor: QRectF, label_w: float, label_h: float,
                      occupied: List[QRectF], gap: float = 2.0) -> QRectF:
    """Pick a label rectangle near ``anchor`` that avoids ``occupied``.

    Greedy: try below, above, right, left, then the four diagonals; the
    first candidate that intersects nothing wins. If everything
    collides, fall back to "below" — an overlapping label beats a
    missing one on a crowded plot.
    """
    cx = anchor.center().x()
    below = QRectF(cx - label_w / 2, anchor.bottom() + gap, label_w, label_h)
    candidates = [
        below,
        QRectF(cx - label_w / 2, anchor.top() - gap - label_h, label_w, label_h),
        QRectF(anchor.right() + gap, anchor.center().y() - label_h / 2, label_w, label_h),
        QRectF(anchor.left() - gap - label_w, anchor.center().y() - label_h / 2, label_w, label_h),
        QRectF(anchor.right() + gap, anchor.bottom() + gap, label_w, label_h),
        QRectF(anchor.left() - gap - label_w, anchor.bottom() + gap, label_w, label_h),
        QRectF(anchor.right() + gap, anchor.top() - gap - label_h, label_w, label_h),
        QRectF(anchor.left() - gap - label_w, anchor.top() - gap - label_h, label_w, label_h),
    ]
    for rect in candidates:
        if not any(rect.intersects(o) for o in occupied):
            return rect
    return below


def nice_label_step(ppm: float, min_px: float) -> float:
    """Smallest step from {1, 2, 5, 10, ...} meters whose spacing on
    paper is at least ``min_px``."""
    step = 1.0
    while step * ppm < min_px:
        step *= 2 if str(step)[0] in "15" else 2.5
    return step


class StagePlotRenderer:
    """Renders a Configuration as a printable stage plot."""

    def __init__(self, config, title: str = ""):
        self.config = config
        if not title:
            loaded_from = getattr(config, '_loaded_from', None)
            title = (os.path.splitext(os.path.basename(loaded_from))[0]
                     if loaded_from else "Stage Plot")
        self.title = title

    # ── Entry points ──────────────────────────────────────────────────

    def render(self, path: str, paper: str = "A4", dpi: int = 300) -> str:
        """Render to ``path``; format from the extension (.pdf / .png).
        Returns the format string."""
        ext = os.path.splitext(path)[1].lower()
        if ext == ".pdf":
            self.render_pdf(path, paper)
            return "pdf"
        if ext == ".png":
            self.render_png(path, paper, dpi)
            return "png"
        raise ValueError(f"Unsupported extension: {ext!r}. Use .pdf or .png.")

    def render_pdf(self, path: str, paper: str = "A4") -> None:
        w_mm, h_mm, page_id = PAPER_PRESETS[paper]
        writer = QPdfWriter(path)
        writer.setTitle(self.title)
        writer.setResolution(300)
        writer.setPageSize(QPageSize(page_id))
        writer.setPageOrientation(QPageLayout.Orientation.Landscape)
        writer.setPageMargins(QMarginsF(0, 0, 0, 0))

        painter = QPainter(writer)
        try:
            px_per_mm = 300 / 25.4
            self._paint(painter, w_mm * px_per_mm, h_mm * px_per_mm, px_per_mm)
        finally:
            painter.end()

    def render_png(self, path: str, paper: str = "A4", dpi: int = 300) -> None:
        w_mm, h_mm, _ = PAPER_PRESETS[paper]
        px_per_mm = dpi / 25.4
        image = QImage(int(w_mm * px_per_mm), int(h_mm * px_per_mm),
                       QImage.Format.Format_ARGB32)
        image.fill(QColor(255, 255, 255))

        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        try:
            self._paint(painter, image.width(), image.height(), px_per_mm)
        finally:
            painter.end()
        if not image.save(path):
            raise IOError(f"Could not write {path}")

    # ── Layout + drawing ──────────────────────────────────────────────

    def _font(self, mm_size: float, px_per_mm: float, bold: bool = False) -> QFont:
        # Brand family (registered by gui.fonts at app start / the visual
        # test conftest); Qt falls back to a system sans if unregistered.
        font = QFont("Barlow")
        font.setPixelSize(max(4, int(mm_size * px_per_mm)))
        font.setBold(bold)
        return font

    def _paint(self, painter: QPainter, page_w: float, page_h: float,
               px_per_mm: float) -> None:
        mm = px_per_mm
        margin = 8 * mm
        title_h = 13 * mm
        legend_w = 54 * mm

        black = QColor(20, 20, 20)
        gray = QColor(150, 150, 150)
        painter.fillRect(QRectF(0, 0, page_w, page_h), QColor(255, 255, 255))

        plot_rect = QRectF(
            margin, margin + title_h,
            page_w - 2 * margin - legend_w - 4 * mm,
            page_h - 2 * margin - title_h,
        )
        legend_rect = QRectF(
            plot_rect.right() + 4 * mm, margin + title_h,
            legend_w, page_h - 2 * margin - title_h,
        )

        # Stage-to-paper scale: fit stage (plus breathing room for the
        # meter labels) into the plot area.
        stage_w = float(self.config.stage_width or 10.0)
        stage_d = float(self.config.stage_height or 6.0)
        pad = 9 * mm
        ppm = min(
            (plot_rect.width() - 2 * pad) / stage_w,
            (plot_rect.height() - 2 * pad) / stage_d,
        )
        scale_den = max(1, round(1000.0 / (ppm / mm)))

        self._draw_title_block(painter, page_w, margin, title_h, mm,
                               stage_w, stage_d, scale_den, black, gray)
        origin_x = plot_rect.center().x()
        origin_y = plot_rect.center().y()
        self._draw_stage(painter, origin_x, origin_y, stage_w, stage_d,
                         ppm, mm, black, gray)
        self._draw_stage_elements(painter, origin_x, origin_y, ppm, mm, gray)
        occupied = self._draw_fixtures(painter, origin_x, origin_y, ppm, mm, black)
        self._draw_spots(painter, origin_x, origin_y, ppm, mm, black, occupied)
        self._draw_legend(painter, legend_rect, mm, ppm, black, gray)

    def _draw_stage_elements(self, painter, ox, oy, ppm, mm, gray) -> None:
        """Static stage elements (risers, wedges, truss shapes, ...)
        under the fixtures: SVG symbol at its real footprint, plus the
        user label if set. Hidden-layer elements are skipped like
        hidden-layer fixtures."""
        elements = getattr(self.config, "stage_elements", None) or []
        if not elements:
            return
        from PyQt6.QtSvg import QSvgRenderer
        from utils.stage_element_catalog import symbol_path

        for element in elements:
            if element.layer:
                layer = self.config.get_stage_layer(element.layer)
                if layer is not None and not layer.visible:
                    continue
            x = ox + element.x * ppm
            y = oy - element.y * ppm
            w = element.width * ppm
            d = element.depth * ppm

            painter.save()
            painter.translate(x, y)
            painter.rotate(element.rotation)
            renderer = QSvgRenderer(symbol_path(element.kind))
            body = QRectF(-w / 2, -d / 2, w, d)
            if renderer.isValid():
                renderer.render(painter, body)
            else:
                painter.setPen(QPen(gray, 0.25 * mm, Qt.PenStyle.DashLine))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRect(body)
            painter.restore()

            if element.label:
                painter.setPen(QPen(gray, 0.2 * mm))
                painter.setFont(self._font(2.2, mm))
                painter.drawText(
                    QRectF(x - 20 * mm, y + d / 2 + 0.5 * mm, 40 * mm, 4 * mm),
                    Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                    element.label)

    def _draw_title_block(self, painter, page_w, margin, title_h, mm,
                          stage_w, stage_d, scale_den, black, gray) -> None:
        painter.setPen(QPen(black, 0.3 * mm))
        painter.setFont(self._font(4.5, mm, bold=True))
        painter.drawText(
            QRectF(margin, margin, page_w - 2 * margin, 6 * mm),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            f"{self.title} · Stage Plot",
        )
        painter.setFont(self._font(2.6, mm))
        painter.setPen(QPen(QColor(80, 80, 80), 0.2 * mm))
        subtitle = (
            f"Stage {stage_w:g} m × {stage_d:g} m    "
            f"Scale ≈ 1:{scale_den}    "
            f"{len(self.config.fixtures)} fixtures    "
            f"{datetime.date.today().isoformat()}"
        )
        painter.drawText(
            QRectF(margin, margin + 6 * mm, page_w - 2 * margin, 5 * mm),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            subtitle,
        )
        painter.setPen(QPen(gray, 0.2 * mm))
        painter.drawLine(
            int(margin), int(margin + title_h - 1.5 * mm),
            int(page_w - margin), int(margin + title_h - 1.5 * mm),
        )

    def _draw_stage(self, painter, ox, oy, stage_w, stage_d, ppm, mm,
                    black, gray) -> None:
        hw, hd = stage_w / 2 * ppm, stage_d / 2 * ppm
        stage_rect = QRectF(ox - hw, oy - hd, 2 * hw, 2 * hd)

        # Grid first (light), then the outline on top.
        grid_m = float(getattr(self.config, 'grid_size', 0.5) or 0.5)
        painter.setPen(QPen(QColor(225, 225, 225), 0.15 * mm))
        step = grid_m * ppm
        x = ox
        while x <= stage_rect.right() + 0.5:
            painter.drawLine(int(x), int(stage_rect.top()), int(x), int(stage_rect.bottom()))
            painter.drawLine(int(2 * ox - x), int(stage_rect.top()),
                             int(2 * ox - x), int(stage_rect.bottom()))
            x += step
        y = oy
        while y <= stage_rect.bottom() + 0.5:
            painter.drawLine(int(stage_rect.left()), int(y), int(stage_rect.right()), int(y))
            painter.drawLine(int(stage_rect.left()), int(2 * oy - y),
                             int(stage_rect.right()), int(2 * oy - y))
            y += step

        painter.setPen(QPen(black, 0.4 * mm))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(stage_rect)

        # Meter labels along the top (X) and left (Y) edges, centered on
        # 0 like the Stage tab. The plot is flipped so the audience sits
        # at the bottom, so the X numbers live along the TOP edge and the
        # AUDIENCE marker owns the bottom band.
        painter.setFont(self._font(2.2, mm))
        painter.setPen(QPen(QColor(100, 100, 100), 0.2 * mm))
        label_step = nice_label_step(ppm, 8 * mm)

        m = 0.0
        while m <= stage_w / 2 + 0.01:
            for sign in ((1,) if m == 0 else (1, -1)):
                x = ox + sign * m * ppm
                painter.drawText(
                    QRectF(x - 5 * mm, stage_rect.top() - 4 * mm, 10 * mm, 3.5 * mm),
                    int(Qt.AlignmentFlag.AlignCenter),
                    f"{sign * m:g}",
                )
            m += label_step
        m = 0.0
        while m <= stage_d / 2 + 0.01:
            for sign in ((1,) if m == 0 else (1, -1)):
                y = oy - sign * m * ppm
                painter.drawText(
                    QRectF(stage_rect.left() - 8.5 * mm, y - 1.75 * mm, 8 * mm, 3.5 * mm),
                    int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
                    f"{sign * m:g}",
                )
            m += label_step

        # Audience edge marker. Negative stage-Y is the front, which the
        # Stage tab (and therefore this plot) draws at the bottom. The X
        # meter labels now sit along the TOP edge, so this marker owns the
        # bottom band on its own.
        painter.setFont(self._font(2.8, mm, bold=True))
        painter.setPen(QPen(QColor(120, 120, 120), 0.2 * mm))
        painter.drawText(
            self._audience_marker_rect(stage_rect, mm),
            int(Qt.AlignmentFlag.AlignCenter),
            "▼  AUDIENCE  ▼",
        )

    @staticmethod
    def _audience_marker_rect(stage_rect: QRectF, mm: float) -> QRectF:
        """Rect for the AUDIENCE edge marker. Negative stage-Y is the
        front, drawn at the BOTTOM of the plot (matching the Stage tab),
        so the marker sits below the stage's bottom edge. The X meter
        labels moved to the top edge, so the bottom band is its own."""
        return QRectF(stage_rect.left(), stage_rect.bottom() + 4.5 * mm,
                      stage_rect.width(), 4 * mm)

    def _layer_index(self) -> dict:
        """Layer name -> short marker ('L1', 'L2', ...)."""
        return {
            layer.name: f"L{i + 1}"
            for i, layer in enumerate(getattr(self.config, 'stage_layers', []))
        }

    def _draw_fixtures(self, painter, ox, oy, ppm, mm, black) -> List[QRectF]:
        """Draw symbols first, then labels (so no symbol paints over a
        label). Returns the occupied rects for the spot pass to respect."""
        layer_marker = self._layer_index()
        symbol_size = 5.5 * mm
        occupied: List[QRectF] = []
        label_jobs = []

        for fixture in self.config.fixtures:
            group = self.config.groups.get(fixture.group) if fixture.group else None
            group_color = QColor(group.color) if group else QColor(160, 160, 160)
            _, yaw, pitch, roll = fixture.get_effective_orientation(group)

            x = ox + fixture.x * ppm
            y = oy - fixture.y * ppm

            is_bar = fixture.type in _BAR_TYPES
            angle = plot_fixture_angle(fixture.type, yaw, pitch, roll)

            painter.save()
            painter.translate(x, y)
            painter.rotate(angle)
            painter.setPen(QPen(black, 0.25 * mm))
            painter.setBrush(group_color)
            chassis = chassis_from_legacy_type(fixture.type)
            accent = (ACCENT_PIXELS if fixture.type == "PIXELBAR"
                      else ACCENT_LAMPS if fixture.type == "SUNSTRIP" else None)
            # Mapped types draw their North Star stage-plot symbol in the
            # group color; unknown types keep the legacy primitives (accent
            # only applies there).
            paint_fixture_icon(painter, chassis, symbol_size, accent=accent,
                               fixture_type=fixture.type)
            # Orientation tick: short line out of the symbol along the
            # facing direction (+X in the rotated frame).
            tick_from = symbol_size * (1.0 if is_bar else 0.5)
            painter.drawLine(int(tick_from), 0, int(tick_from + 1.8 * mm), 0)
            painter.restore()

            half = symbol_size * (1.0 if is_bar else 0.5)
            occupied.append(QRectF(x - half, y - half, 2 * half, 2 * half))

            line1 = fixture.name
            line2 = f"U{fixture.universe}.{fixture.address}"
            if fixture.layer and fixture.layer in layer_marker:
                line2 += f"  {layer_marker[fixture.layer]}"
            label_jobs.append((x, y, half, line1, line2))

        painter.setPen(QPen(black, 0.2 * mm))
        name_font = self._font(2.2, mm, bold=True)
        addr_font = self._font(2.0, mm)
        name_metrics_w = 0.62 * name_font.pixelSize()  # rough per-char width

        for x, y, half, line1, line2 in label_jobs:
            label_w = max(len(line1), len(line2) + 1) * name_metrics_w
            label_h = 2 * 1.25 * name_font.pixelSize()
            anchor = QRectF(x - half, y - half, 2 * half, 2 * half)
            rect = choose_label_rect(anchor, label_w, label_h, occupied, gap=0.8 * mm)
            occupied.append(rect)

            painter.setFont(name_font)
            painter.drawText(
                QRectF(rect.x(), rect.y(), rect.width(), rect.height() / 2),
                int(Qt.AlignmentFlag.AlignCenter), line1,
            )
            painter.setFont(addr_font)
            painter.drawText(
                QRectF(rect.x(), rect.y() + rect.height() / 2, rect.width(), rect.height() / 2),
                int(Qt.AlignmentFlag.AlignCenter), line2,
            )
        return occupied

    def _draw_spots(self, painter, ox, oy, ppm, mm, black,
                    occupied: List[QRectF]) -> None:
        from gui.widgets.fixture_icons import _paint_symbol_icon

        # Spike marks wear the brand accent on the plot too (the plot
        # already prints group colours, so colour is at home here).
        from gui.theme_tokens import THEMES
        ink = QColor(THEMES["dark"]["accent"])
        painter.setPen(QPen(ink, 0.3 * mm))
        painter.setFont(self._font(2.0, mm))
        size = 1.6 * mm
        box = 4.4 * mm  # spike-mark symbol box (bigger than the old X)
        for name, spot in getattr(self.config, 'spots', {}).items():
            x = ox + spot.x * ppm
            y = oy - spot.y * ppm
            # The spike-mark symbol (screen 04 asset); primitive X as
            # the fallback if the SVG is missing.
            painter.save()
            painter.translate(x, y)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(ink))
            drew = _paint_symbol_icon(painter, "spike-mark", box)
            painter.restore()
            if not drew:
                painter.setPen(QPen(ink, 0.3 * mm))
                painter.drawLine(int(x - size), int(y - size),
                                 int(x + size), int(y + size))
                painter.drawLine(int(x - size), int(y + size),
                                 int(x + size), int(y - size))
            painter.setPen(QPen(ink, 0.3 * mm))
            anchor = QRectF(x - size, y - size, 2 * size, 2 * size)
            rect = choose_label_rect(anchor, len(name) * 1.4 * mm, 3 * mm,
                                     occupied, gap=0.6 * mm)
            occupied.append(rect)
            painter.drawText(rect, int(Qt.AlignmentFlag.AlignCenter), name)

    def _draw_legend(self, painter, rect: QRectF, mm, ppm, black, gray) -> None:
        x = rect.x()
        y = rect.y()
        row_h = 4.6 * mm
        swatch = 3.2 * mm

        def heading(text):
            nonlocal y
            painter.setFont(self._font(2.8, mm, bold=True))
            painter.setPen(QPen(black, 0.2 * mm))
            painter.drawText(QRectF(x, y, rect.width(), row_h),
                             int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                             text)
            y += row_h

        def row(text, color=None):
            nonlocal y
            text_x = x
            if color is not None:
                painter.setPen(QPen(black, 0.15 * mm))
                painter.setBrush(QColor(color))
                painter.drawRect(QRectF(x, y + (row_h - swatch) / 2, swatch, swatch))
                text_x = x + swatch + 1.5 * mm
            painter.setFont(self._font(2.3, mm))
            painter.setPen(QPen(QColor(60, 60, 60), 0.15 * mm))
            painter.drawText(QRectF(text_x, y, rect.right() - text_x, row_h),
                             int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                             text)
            y += row_h

        if self.config.groups:
            heading("Groups")
            for name, group in self.config.groups.items():
                count = len(group.fixtures)
                role = f", {group.lighting_role}" if group.lighting_role else ""
                row(f"{name} ({count}{role})", color=group.color)
            y += 2 * mm

        layers = getattr(self.config, 'stage_layers', [])
        if layers:
            heading("Layers")
            marker = self._layer_index()
            for layer in layers:
                count = sum(1 for f in self.config.fixtures if f.layer == layer.name)
                row(f"{marker[layer.name]} = {layer.name} ({layer.z_height:g} m, {count})")
            y += 2 * mm

        # Scale bar: as many whole meters as fit in ~35 mm.
        bar_meters = max(1, int((35 * mm) / ppm))
        bar_px = bar_meters * ppm
        heading("Scale")
        painter.setPen(QPen(black, 0.4 * mm))
        painter.drawLine(int(x), int(y + 2 * mm), int(x + bar_px), int(y + 2 * mm))
        for tick_x in (x, x + bar_px):
            painter.drawLine(int(tick_x), int(y + 1 * mm), int(tick_x), int(y + 3 * mm))
        painter.setFont(self._font(2.3, mm))
        painter.drawText(QRectF(x, y + 3.2 * mm, bar_px, 4 * mm),
                         int(Qt.AlignmentFlag.AlignCenter), f"{bar_meters} m")
