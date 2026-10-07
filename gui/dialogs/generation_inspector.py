# gui/dialogs/generation_inspector.py
# Live dashboard showing auto-generation decisions during playback

import html
import math
import colorsys
from typing import Optional, List

import numpy as np

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QSplitter, QSizePolicy,
)
from PyQt6.QtCore import Qt, QRectF, QPointF
from PyQt6.QtGui import (
    QPainter, QPen, QColor, QBrush, QPainterPath, QFont, QFontMetrics,
    QImage, QPixmap,
)

from autogen.report import GenerationReport, SectionReport


# ── Color constants ──────────────────────────────────────

COLORS = {
    "flux": QColor(220, 60, 60),       # red
    "transient": QColor(230, 140, 30),  # orange
    "richness": QColor(50, 180, 50),    # green
    "vocal": QColor(160, 80, 200),      # purple
    "centroid": QColor(60, 180, 220),   # cyan
    "energy": QColor(255, 200, 60, 60), # yellow, transparent
}

ROLE_COLORS = {
    "full": QColor(60, 180, 80),       # green
    "groove": QColor(60, 120, 220),    # blue
    "fill": QColor(230, 140, 40),      # orange
}

SCORE_COLORS = {
    "envelope": QColor(70, 130, 220),   # blue
    "flux_fit": QColor(60, 180, 80),    # green
    "rep_rate": QColor(230, 140, 40),   # orange
    "coherence": QColor(160, 80, 200),  # purple
}

BG_DARK = QColor(30, 30, 35)
BG_PANEL = QColor(40, 40, 48)
TEXT_COLOR = QColor(200, 200, 210)
GRID_COLOR = QColor(60, 60, 70)
CURSOR_COLOR = QColor(255, 40, 40)
HIGHLIGHT_COLOR = QColor(255, 255, 255, 50)


# ── Audio Features Timeline ─────────────────────────────

class AudioFeaturesWidget(QWidget):
    """Stacked line plots of audio features over song duration with playhead cursor."""

    FEATURE_KEYS = ["flux", "transient", "richness", "vocal", "centroid"]

    def __init__(self, report: GenerationReport, parent=None):
        super().__init__(parent)
        self.report = report
        self.cursor_time = 0.0
        self.setMinimumHeight(140)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        # Visibility toggles (all on by default); energy is always shown
        self._visible = {k: True for k in self.FEATURE_KEYS}
        # Legend hit rects: filled in paintEvent, used by mousePressEvent
        self._legend_rects = {}

        # Pre-compute feature paths
        self._paths = {}
        self._energy_path = None
        self._build_paths()

    def _build_paths(self):
        """Pre-compute feature point arrays from report data (called once).

        Uses per-beat data if available (smooth curves), falls back to
        section-level data (flat steps) if not.
        """
        if not self.report.sections:
            return
        self._total_time = max(s.end_time for s in self.report.sections)
        if self._total_time <= 0:
            return

        # Prefer continuous frame-level data (smoothed, ~800 points)
        if self.report.frame_times:
            times = self.report.frame_times
            features = {
                "flux": list(zip(times, self.report.frame_flux)),
                "transient": list(zip(times, self.report.frame_transient)),
                "richness": list(zip(times, self.report.frame_richness)),
                "vocal": list(zip(times, self.report.frame_vocal)),
                "centroid": list(zip(times, self.report.frame_centroid)),
            }
        else:
            # Fallback: section-level (one point per section)
            features = {
                "flux": [(s.start_time, s.spectral_flux) for s in self.report.sections],
                "transient": [(s.start_time, s.transient_sharpness) for s in self.report.sections],
                "richness": [(s.start_time, s.spectral_richness) for s in self.report.sections],
                "vocal": [(s.start_time, s.vocal_presence) for s in self.report.sections],
                "centroid": [(s.start_time, s.spectral_centroid) for s in self.report.sections],
            }

        # Normalize centroid to 0-1 range
        centroids = [v for _, v in features["centroid"]]
        if centroids:
            c_min, c_max = min(centroids), max(centroids)
            if c_max > c_min:
                features["centroid"] = [(t, (v - c_min) / (c_max - c_min)) for t, v in features["centroid"]]
            else:
                features["centroid"] = [(t, 0.5) for t, _ in features["centroid"]]

        self._features = features

        # Energy filled area (section-level — per-beat energy isn't meaningful
        # since energy is a relative ranking across sections)
        self._energy_points = [
            (s.start_time, s.relative_energy) for s in self.report.sections
        ]

    def update_cursor(self, time: float):
        self.cursor_time = time
        self.update()

    def mousePressEvent(self, event):
        """Toggle feature visibility when clicking a legend label."""
        pos = event.position()
        for key, rect in self._legend_rects.items():
            if rect.contains(pos):
                self._visible[key] = not self._visible[key]
                self.update()
                return

    def paintEvent(self, event):
        if not self.report.sections:
            return

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self.width(), self.height()
        margin_left, margin_top, margin_right, margin_bottom = 50, 16, 10, 20
        plot_w = w - margin_left - margin_right
        plot_h = h - margin_top - margin_bottom

        if plot_w <= 0 or plot_h <= 0:
            p.end()
            return

        total_time = getattr(self, '_total_time', 0)
        if total_time <= 0:
            p.end()
            return

        # Background
        p.fillRect(0, 0, w, h, BG_PANEL)

        # Section backgrounds (alternating shade)
        for i, sec in enumerate(self.report.sections):
            x1 = margin_left + (sec.start_time / total_time) * plot_w
            x2 = margin_left + (sec.end_time / total_time) * plot_w
            shade = QColor(50, 50, 58) if i % 2 == 0 else QColor(42, 42, 50)
            p.fillRect(QRectF(x1, margin_top, x2 - x1, plot_h), shade)

            # Section name label
            p.setPen(QPen(QColor(140, 140, 150), 1))
            p.setFont(QFont("Arial", 7))
            label_w = x2 - x1
            if label_w > 20:
                p.drawText(QRectF(x1 + 2, 1, label_w - 4, margin_top),
                           Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                           sec.name)

        # Energy filled area
        if hasattr(self, '_energy_points') and self._energy_points:
            energy_path = QPainterPath()
            pts = self._energy_points
            energy_path.moveTo(margin_left + (pts[0][0] / total_time) * plot_w,
                               margin_top + plot_h)
            for t, v in pts:
                x = margin_left + (t / total_time) * plot_w
                y = margin_top + plot_h - v * plot_h
                energy_path.lineTo(x, y)
            # Close to bottom-right
            energy_path.lineTo(margin_left + (pts[-1][0] / total_time) * plot_w,
                               margin_top + plot_h)
            energy_path.closeSubpath()
            p.fillPath(energy_path, QBrush(COLORS["energy"]))

        # Feature lines (only visible ones)
        if hasattr(self, '_features'):
            for key, points in self._features.items():
                if not self._visible.get(key, True):
                    continue
                color = COLORS.get(key, QColor(200, 200, 200))
                pen = QPen(color, 1.5)
                p.setPen(pen)
                path = QPainterPath()
                for j, (t, v) in enumerate(points):
                    x = margin_left + (t / total_time) * plot_w
                    y = margin_top + plot_h - v * plot_h
                    if j == 0:
                        path.moveTo(x, y)
                    else:
                        path.lineTo(x, y)
                p.drawPath(path)

        # Y-axis labels
        p.setPen(QPen(TEXT_COLOR, 1))
        p.setFont(QFont("Arial", 7))
        for val in [0.0, 0.5, 1.0]:
            y = margin_top + plot_h - val * plot_h
            p.drawText(QRectF(0, y - 8, margin_left - 4, 16),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                       f"{val:.1f}")
            p.setPen(QPen(GRID_COLOR, 1, Qt.PenStyle.DotLine))
            p.drawLine(QPointF(margin_left, y), QPointF(w - margin_right, y))
            p.setPen(QPen(TEXT_COLOR, 1))

        # Legend (clickable toggles)
        legend_x = margin_left + 4
        legend_y = margin_top + 4
        font = QFont("Arial", 7)
        p.setFont(font)
        fm = QFontMetrics(font)
        self._legend_rects = {}
        for key in self.FEATURE_KEYS:
            visible = self._visible.get(key, True)
            color = COLORS[key]
            item_w = fm.horizontalAdvance(key) + 22
            # Hit rect for this legend item
            self._legend_rects[key] = QRectF(legend_x - 2, legend_y - 2, item_w + 4, 14)
            if visible:
                p.setPen(QPen(color, 2))
                p.drawLine(QPointF(legend_x, legend_y + 4), QPointF(legend_x + 12, legend_y + 4))
                p.setPen(QPen(TEXT_COLOR, 1))
            else:
                # Dimmed + strikethrough for hidden features
                dimmed = QColor(color.red(), color.green(), color.blue(), 60)
                p.setPen(QPen(dimmed, 1))
                p.drawLine(QPointF(legend_x, legend_y + 4), QPointF(legend_x + 12, legend_y + 4))
                p.setPen(QPen(QColor(120, 120, 130), 1))
            p.drawText(QPointF(legend_x + 15, legend_y + 8), key)
            legend_x += item_w

        # Playhead cursor
        cursor_x = margin_left + (self.cursor_time / total_time) * plot_w
        p.setPen(QPen(CURSOR_COLOR, 2))
        p.drawLine(QPointF(cursor_x, margin_top), QPointF(cursor_x, margin_top + plot_h))

        p.end()


# ── 3D Flux / Transient Plot ─────────────────────────────

class FluxPlot3DWidget(QWidget):
    """3D trajectory plot: X=time, Y=flux, Z=transient sharpness.

    QPainter-based with manual perspective projection and orbit camera.
    Pre-computes projected points on camera change; cursor updates are cheap.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._times = []
        self._flux = []
        self._transient = []
        self._sections = []       # list of SectionReport for coloring/boundaries
        self._total_time = 0.0
        self.cursor_time = 0.0
        self._data_loaded = False

        # Camera
        self._yaw = -0.5          # radians
        self._pitch = 0.4
        self._zoom = 1.0
        self._camera_dist = 4.0
        self._focal = 2.0

        # Interaction
        self._dragging = False
        self._last_mouse = QPointF()

        # Cached projected points
        self._projected = []      # list of (screen_x, screen_y, section_idx)
        self._needs_reproject = True

        self.setMinimumHeight(180)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)

    def set_data(self, times, flux, transient, sections):
        """Load pre-computed frame features and section info."""
        self._times = times
        self._flux = flux
        self._transient = transient
        self._sections = sections
        self._total_time = times[-1] if times else 0.0
        self._data_loaded = bool(times)
        self._needs_reproject = True
        self.update()

    def update_cursor(self, time: float):
        self.cursor_time = time
        self.update()

    # ── 3D projection ──────────────────────────────

    def _project(self, x3d, y3d, z3d):
        """Project normalized 3D coords to screen 2D."""
        cy, sy = math.cos(self._yaw), math.sin(self._yaw)
        cp, sp = math.cos(self._pitch), math.sin(self._pitch)

        # Center data around origin
        x = x3d - 0.5
        y = y3d
        z = z3d - 0.5

        # Yaw (around Y axis)
        rx = x * cy - z * sy
        rz = x * sy + z * cy

        # Pitch (around X axis)
        ry = y * cp - rz * sp
        rz2 = y * sp + rz * cp

        # Perspective
        dist = self._camera_dist / self._zoom + rz2
        if dist < 0.1:
            dist = 0.1
        scale = self._focal / dist

        w, h = self.width(), self.height()
        sx = w / 2 + rx * scale * w * 0.35
        sy = h / 2 - ry * scale * h * 0.35
        return sx, sy, dist

    def _reproject(self):
        """Recompute all projected points (called on camera change)."""
        if not self._data_loaded:
            self._projected = []
            return

        total = self._total_time if self._total_time > 0 else 1.0
        self._projected = []
        for i in range(len(self._times)):
            x3d = self._times[i] / total           # 0-1 normalized time
            y3d = self._flux[i]                     # 0-1
            z3d = self._transient[i]                # 0-1
            sx, sy, depth = self._project(x3d, y3d, z3d)

            # Determine which section this point belongs to
            sec_idx = self._section_index_at(self._times[i])
            self._projected.append((sx, sy, sec_idx, depth))

        self._needs_reproject = False

    def _section_index_at(self, time):
        for i, sec in enumerate(self._sections):
            if sec.start_time <= time < sec.end_time:
                return i
        return len(self._sections) - 1 if self._sections else 0

    # ── Section colors ─────────────────────────────

    _SECTION_PALETTE = [
        QColor(220, 80, 80), QColor(80, 180, 220), QColor(100, 200, 100),
        QColor(220, 180, 60), QColor(180, 100, 220), QColor(220, 130, 70),
        QColor(100, 220, 200), QColor(200, 100, 150), QColor(150, 180, 80),
    ]

    def _section_color(self, idx):
        return self._SECTION_PALETTE[idx % len(self._SECTION_PALETTE)]

    # ── Mouse interaction ──────────────────────────

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._last_mouse = event.position()

    def mouseReleaseEvent(self, event):
        self._dragging = False

    def mouseMoveEvent(self, event):
        if self._dragging:
            delta = event.position() - self._last_mouse
            self._yaw -= delta.x() * 0.008
            self._pitch += delta.y() * 0.008
            self._pitch = max(-1.2, min(1.2, self._pitch))
            self._last_mouse = event.position()
            self._needs_reproject = True
            self.update()

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        if delta > 0:
            self._zoom *= 1.1
        else:
            self._zoom /= 1.1
        self._zoom = max(0.3, min(5.0, self._zoom))
        self._needs_reproject = True
        self.update()

    # ── Paint ──────────────────────────────────────

    def paintEvent(self, event):
        if self._needs_reproject:
            self._reproject()

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self.width(), self.height()
        p.fillRect(0, 0, w, h, BG_PANEL)

        if not self._projected:
            p.setPen(QPen(TEXT_COLOR, 1))
            p.setFont(QFont("Arial", 10))
            p.drawText(QRectF(0, 0, w, h), Qt.AlignmentFlag.AlignCenter,
                       "Loading audio data...")
            p.end()
            return

        # Draw 3D axes
        self._draw_axes(p)

        # Draw section boundaries as vertical lines
        self._draw_section_boundaries(p)

        # Draw the data path
        self._draw_data_path(p)

        # Draw playhead cursor
        self._draw_cursor(p)

        # Legend
        self._draw_legend(p)

        p.end()

    def _draw_axes(self, p):
        """Draw 3D axis lines with labels."""
        origin = self._project(0, 0, 0)
        x_end = self._project(1, 0, 0)
        y_end = self._project(0, 1, 0)
        z_end = self._project(0, 0, 1)

        axes = [
            (origin, x_end, "Time", QColor(200, 80, 80)),
            (origin, y_end, "Flux", QColor(80, 200, 80)),
            (origin, z_end, "Transient", QColor(80, 80, 200)),
        ]

        p.setFont(QFont("Arial", 8, QFont.Weight.Bold))
        for (ox, oy, _), (ex, ey, _), label, color in axes:
            p.setPen(QPen(color, 1.5))
            p.drawLine(QPointF(ox, oy), QPointF(ex, ey))
            p.setPen(QPen(color.lighter(150), 1))
            p.drawText(QPointF(ex + 4, ey - 4), label)

        # Grid lines on the floor (Y=0 plane)
        p.setPen(QPen(GRID_COLOR, 0.5))
        for i in range(11):
            t = i / 10.0
            # Lines along X at various Z
            sx1, sy1, _ = self._project(t, 0, 0)
            sx2, sy2, _ = self._project(t, 0, 1)
            p.drawLine(QPointF(sx1, sy1), QPointF(sx2, sy2))
            # Lines along Z at various X
            sx1, sy1, _ = self._project(0, 0, t)
            sx2, sy2, _ = self._project(1, 0, t)
            p.drawLine(QPointF(sx1, sy1), QPointF(sx2, sy2))

    def _draw_section_boundaries(self, p):
        """Draw vertical lines at section boundaries."""
        if not self._sections or self._total_time <= 0:
            return

        p.setFont(QFont("Arial", 6))
        for i, sec in enumerate(self._sections):
            t_norm = sec.start_time / self._total_time
            color = self._section_color(i)

            # Vertical line from floor to Y=1
            sx1, sy1, _ = self._project(t_norm, 0, 0)
            sx2, sy2, _ = self._project(t_norm, 0.8, 0)
            p.setPen(QPen(QColor(color.red(), color.green(), color.blue(), 80), 1,
                          Qt.PenStyle.DashLine))
            p.drawLine(QPointF(sx1, sy1), QPointF(sx2, sy2))

            # Section label
            p.setPen(QPen(color, 1))
            p.drawText(QPointF(sx2 + 2, sy2), sec.name[:8])

    def _draw_data_path(self, p):
        """Draw the 3D data trajectory as a colored polyline."""
        if len(self._projected) < 2:
            return

        prev_sx, prev_sy, prev_sec, _ = self._projected[0]
        for i in range(1, len(self._projected)):
            sx, sy, sec_idx, _ = self._projected[i]
            color = self._section_color(sec_idx)
            p.setPen(QPen(color, 1.5))
            p.drawLine(QPointF(prev_sx, prev_sy), QPointF(sx, sy))
            prev_sx, prev_sy = sx, sy

    def _draw_cursor(self, p):
        """Draw playhead as a vertical line at current time."""
        if self._total_time <= 0:
            return

        t_norm = self.cursor_time / self._total_time

        # Draw a vertical line from floor to Y=1 at the cursor time
        cx1, cy1, _ = self._project(t_norm, 0, 0)
        cx2, cy2, _ = self._project(t_norm, 1.0, 0)
        p.setPen(QPen(CURSOR_COLOR, 2))
        p.drawLine(QPointF(cx1, cy1), QPointF(cx2, cy2))

        # Also draw a cross-hair on the Z axis
        cx3, cy3, _ = self._project(t_norm, 0, 0)
        cx4, cy4, _ = self._project(t_norm, 0, 1.0)
        p.setPen(QPen(QColor(CURSOR_COLOR.red(), CURSOR_COLOR.green(),
                              CURSOR_COLOR.blue(), 100), 1))
        p.drawLine(QPointF(cx3, cy3), QPointF(cx4, cy4))

    def _draw_legend(self, p):
        """Draw axis legend in corner."""
        p.setFont(QFont("Arial", 7))
        x, y = 6, self.height() - 36
        for label, color in [("X: Time", QColor(200, 80, 80)),
                              ("Y: Flux", QColor(80, 200, 80)),
                              ("Z: Transient", QColor(80, 80, 200))]:
            p.setPen(QPen(color, 2))
            p.drawLine(QPointF(x, y + 4), QPointF(x + 12, y + 4))
            p.setPen(QPen(TEXT_COLOR, 1))
            p.drawText(QPointF(x + 15, y + 8), label)
            y += 12


# ── Mel Spectrogram ────────────────────────────────────

# Magma-like colormap (dark → purple → orange → yellow)
_MAGMA_STOPS = [
    (0.00, (0, 0, 4)),
    (0.15, (30, 10, 60)),
    (0.30, (80, 18, 123)),
    (0.45, (140, 30, 115)),
    (0.60, (200, 60, 80)),
    (0.75, (240, 120, 40)),
    (0.90, (252, 195, 60)),
    (1.00, (252, 253, 191)),
]


def _magma_color(t: float) -> tuple:
    """Interpolate magma colormap at position t (0-1)."""
    t = max(0.0, min(1.0, t))
    for i in range(len(_MAGMA_STOPS) - 1):
        t0, c0 = _MAGMA_STOPS[i]
        t1, c1 = _MAGMA_STOPS[i + 1]
        if t0 <= t <= t1:
            f = (t - t0) / (t1 - t0)
            return (
                int(c0[0] + f * (c1[0] - c0[0])),
                int(c0[1] + f * (c1[1] - c0[1])),
                int(c0[2] + f * (c1[2] - c0[2])),
            )
    return _MAGMA_STOPS[-1][1]


class MelSpectrogramWidget(QWidget):
    """2D mel spectrogram heatmap with playhead cursor and frequency axis."""

    def __init__(self, report: GenerationReport, parent=None):
        super().__init__(parent)
        self.report = report
        self.cursor_time = 0.0
        self._pixmap = None
        self._total_time = 0.0
        self._margin_left = 50
        self._margin_top = 4
        self._margin_right = 10
        self._margin_bottom = 4
        self.setMinimumHeight(120)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._build_image()

    def _build_image(self):
        """Convert mel spectrogram dB array to a QPixmap (called once)."""
        mel_db = self.report.mel_spectrogram_db
        mel_times = self.report.mel_times
        mel_freqs = self.report.mel_frequencies
        if mel_db is None or mel_times is None:
            return

        self._total_time = float(mel_times[-1]) if len(mel_times) > 0 else 0.0
        self._mel_freqs = mel_freqs
        n_mels, n_frames = mel_db.shape

        # Normalize dB to 0-1 (mel_db is negative, ref=max → range ~ -80 to 0)
        db_min, db_max = float(np.min(mel_db)), float(np.max(mel_db))
        db_range = db_max - db_min if db_max > db_min else 1.0
        norm = (mel_db - db_min) / db_range  # 0-1

        # Build RGBA image (n_mels × n_frames) — flip vertically so low freq = bottom
        img_data = np.zeros((n_mels, n_frames, 4), dtype=np.uint8)
        for row in range(n_mels):
            for col in range(n_frames):
                r, g, b = _magma_color(norm[n_mels - 1 - row, col])
                img_data[row, col] = [r, g, b, 255]

        qimg = QImage(
            img_data.data, n_frames, n_mels,
            n_frames * 4, QImage.Format.Format_RGBA8888,
        )
        # Keep a reference to img_data so it's not garbage collected
        self._img_data = img_data
        self._pixmap = QPixmap.fromImage(qimg)

    def update_cursor(self, time: float):
        self.cursor_time = time
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self.width(), self.height()
        ml, mt, mr, mb = self._margin_left, self._margin_top, self._margin_right, self._margin_bottom
        plot_w = w - ml - mr
        plot_h = h - mt - mb

        p.fillRect(0, 0, w, h, BG_PANEL)

        if self._pixmap is None or plot_w <= 0 or plot_h <= 0:
            p.setPen(QPen(TEXT_COLOR, 1))
            p.setFont(QFont("Arial", 9))
            p.drawText(QRectF(0, 0, w, h), Qt.AlignmentFlag.AlignCenter,
                       "No spectrogram data")
            p.end()
            return

        # Draw scaled spectrogram
        target = QRectF(ml, mt, plot_w, plot_h)
        p.drawPixmap(target.toRect(), self._pixmap)

        # Frequency axis labels
        if self._mel_freqs is not None and len(self._mel_freqs) > 0:
            p.setPen(QPen(TEXT_COLOR, 1))
            p.setFont(QFont("Arial", 7))
            freq_labels = [100, 500, 1000, 2000, 5000, 10000]
            max_freq = float(self._mel_freqs[-1])
            min_freq = float(self._mel_freqs[0])
            for freq in freq_labels:
                if freq < min_freq or freq > max_freq:
                    continue
                # Mel scale position (approximate log mapping)
                frac = np.log2(max(1, freq) / max(1, min_freq)) / np.log2(max(1, max_freq) / max(1, min_freq))
                y = mt + plot_h - frac * plot_h
                label = f"{freq // 1000}k" if freq >= 1000 else str(freq)
                p.drawText(QRectF(0, y - 8, ml - 4, 16),
                           Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                           label)
                p.setPen(QPen(QColor(255, 255, 255, 30), 0.5))
                p.drawLine(QPointF(ml, y), QPointF(w - mr, y))
                p.setPen(QPen(TEXT_COLOR, 1))

        # Playhead cursor
        if self._total_time > 0:
            cursor_x = ml + (self.cursor_time / self._total_time) * plot_w
            p.setPen(QPen(CURSOR_COLOR, 2))
            p.drawLine(QPointF(cursor_x, mt), QPointF(cursor_x, mt + plot_h))

        p.end()


# ── Group Activation Grid ───────────────────────────────

class GroupActivationWidget(QWidget):
    """Heatmap grid: groups x sections, colored by role, opacity by weight."""

    def __init__(self, report: GenerationReport, parent=None):
        super().__init__(parent)
        self.report = report
        self.current_section_idx = -1
        self.selected_group = None
        self.setMinimumHeight(100)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    # Signal for when user clicks a group (for rudiment score panel)
    group_selected_callback = None

    def set_section(self, idx: int):
        if idx != self.current_section_idx:
            self.current_section_idx = idx
            self.update()

    def mousePressEvent(self, event):
        """Click on a cell to select that group for the score panel."""
        if not self.report.group_names or not self.report.sections:
            return
        margin_left = 80
        margin_top = 16
        n_groups = len(self.report.group_names)
        n_sections = len(self.report.sections)
        cell_w = (self.width() - margin_left - 10) / max(1, n_sections)
        cell_h = (self.height() - margin_top - 4) / max(1, n_groups)

        row = int((event.position().y() - margin_top) / cell_h)
        if 0 <= row < n_groups:
            self.selected_group = self.report.group_names[row]
            self.update()
            if self.group_selected_callback:
                self.group_selected_callback(self.selected_group)

    def paintEvent(self, event):
        if not self.report.sections or not self.report.group_names:
            return

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self.width(), self.height()
        margin_left, margin_top = 80, 16
        n_groups = len(self.report.group_names)
        n_sections = len(self.report.sections)

        cell_w = (w - margin_left - 10) / max(1, n_sections)
        cell_h = (h - margin_top - 4) / max(1, n_groups)

        p.fillRect(0, 0, w, h, BG_PANEL)

        # Section name headers
        p.setFont(QFont("Arial", 7))
        p.setPen(QPen(TEXT_COLOR, 1))
        for col, sec in enumerate(self.report.sections):
            x = margin_left + col * cell_w
            p.save()
            p.translate(x + cell_w / 2, margin_top - 2)
            p.rotate(-45)
            p.drawText(QPointF(0, 0), sec.name[:8])
            p.restore()

        # Grid cells
        for row, group_name in enumerate(self.report.group_names):
            # Group label
            y = margin_top + row * cell_h
            p.setPen(QPen(TEXT_COLOR, 1))
            p.setFont(QFont("Arial", 7))
            label_rect = QRectF(2, y, margin_left - 6, cell_h)
            p.drawText(label_rect,
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                       group_name[:12])

            for col, sec in enumerate(self.report.sections):
                x = margin_left + col * cell_w
                gr = sec.group_reports.get(group_name)
                if gr and gr.weight > 0:
                    base_color = ROLE_COLORS.get(gr.role, QColor(100, 100, 100))
                    alpha = int(80 + gr.weight * 175)  # 80-255
                    color = QColor(base_color.red(), base_color.green(),
                                   base_color.blue(), alpha)
                else:
                    color = QColor(50, 50, 55, 120)

                p.fillRect(QRectF(x + 1, y + 1, cell_w - 2, cell_h - 2), color)

                # Role letter
                if gr and gr.weight > 0:
                    p.setPen(QPen(QColor(255, 255, 255, 180), 1))
                    p.setFont(QFont("Arial", 7, QFont.Weight.Bold))
                    label = gr.role[0].upper()  # F, G, or f
                    p.drawText(QRectF(x, y, cell_w, cell_h),
                               Qt.AlignmentFlag.AlignCenter, label)

        # Highlight current section column
        if 0 <= self.current_section_idx < n_sections:
            x = margin_left + self.current_section_idx * cell_w
            p.setPen(QPen(QColor(255, 255, 255), 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(QRectF(x, margin_top, cell_w, n_groups * cell_h))

        # Highlight selected group row
        if self.selected_group and self.selected_group in self.report.group_names:
            row = self.report.group_names.index(self.selected_group)
            y = margin_top + row * cell_h
            p.setPen(QPen(QColor(255, 255, 100), 1.5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(QRectF(margin_left, y, n_sections * cell_w, cell_h))

        p.end()


# ── Rudiment Match Scores ───────────────────────────────

class RudimentScoresWidget(QWidget):
    """Horizontal stacked bar chart for top 5 rudiment candidates."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scores = []
        self._selected_rudiment = ""
        self._group_name = ""
        self.setMinimumHeight(100)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_data(self, scores, selected_rudiment: str, group_name: str):
        self._scores = scores[:5] if scores else []
        self._selected_rudiment = selected_rudiment
        self._group_name = group_name
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self.width(), self.height()
        p.fillRect(0, 0, w, h, BG_PANEL)

        if not self._scores:
            p.setPen(QPen(TEXT_COLOR, 1))
            p.setFont(QFont("Arial", 9))
            p.drawText(QRectF(0, 0, w, h), Qt.AlignmentFlag.AlignCenter,
                       "Click a group cell to see match scores")
            p.end()
            return

        # Header
        p.setPen(QPen(TEXT_COLOR, 1))
        p.setFont(QFont("Arial", 8, QFont.Weight.Bold))
        p.drawText(QPointF(4, 12), f"Match scores: {self._group_name}")

        margin_top = 20
        margin_left = 90
        bar_h = min(18, (h - margin_top - 4) / max(1, len(self._scores)))
        max_bar_w = w - margin_left - 60

        for i, entry in enumerate(self._scores):
            y = margin_top + i * bar_h
            is_selected = (entry.rudiment_name == self._selected_rudiment)

            # Rudiment name label
            p.setPen(QPen(QColor(255, 255, 200) if is_selected else TEXT_COLOR, 1))
            p.setFont(QFont("Arial", 7, QFont.Weight.Bold if is_selected else QFont.Weight.Normal))
            p.drawText(QRectF(2, y, margin_left - 4, bar_h),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                       entry.rudiment_name)

            # Stacked bar segments
            x = margin_left
            segments = [
                ("envelope", entry.envelope_similarity),
                ("flux_fit", entry.flux_level_fit),
                ("rep_rate", entry.repetition_rate_fit),
                ("coherence", entry.coherence_score),
            ]
            for seg_key, seg_val in segments:
                seg_w = seg_val * max_bar_w * 0.25  # Each dimension up to 25% of bar
                color = SCORE_COLORS.get(seg_key, QColor(150, 150, 150))
                p.fillRect(QRectF(x, y + 2, seg_w, bar_h - 4), color)
                x += seg_w

            # Total score label
            p.setPen(QPen(TEXT_COLOR, 1))
            p.setFont(QFont("Arial", 7))
            p.drawText(QPointF(x + 4, y + bar_h - 4), f"{entry.total_score:.2f}")

            # Selection highlight border
            if is_selected:
                p.setPen(QPen(QColor(255, 255, 100), 1.5))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRect(QRectF(margin_left, y + 1, x - margin_left, bar_h - 2))

        # Legend
        legend_y = h - 14
        legend_x = margin_left
        p.setFont(QFont("Arial", 6))
        for key, label in [("envelope", "envelope"), ("flux_fit", "flux"),
                           ("rep_rate", "rep.rate"), ("coherence", "coherence")]:
            color = SCORE_COLORS[key]
            p.fillRect(QRectF(legend_x, legend_y, 8, 8), color)
            p.setPen(QPen(TEXT_COLOR, 1))
            p.drawText(QPointF(legend_x + 10, legend_y + 8), label)
            legend_x += QFontMetrics(p.font()).horizontalAdvance(label) + 18

        p.end()


# ── Color Palette Wheel ─────────────────────────────────

class ColorPaletteWidget(QWidget):
    """Color wheel with song palette and current section colors highlighted."""

    def __init__(self, report: GenerationReport, parent=None):
        super().__init__(parent)
        self.report = report
        self._current_colors = []
        self.setMinimumSize(120, 120)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_section_colors(self, colors: list):
        self._current_colors = colors
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self.width(), self.height()
        p.fillRect(0, 0, w, h, BG_PANEL)

        # Header
        p.setPen(QPen(TEXT_COLOR, 1))
        p.setFont(QFont("Arial", 8, QFont.Weight.Bold))
        p.drawText(QPointF(4, 12), "Color Palette")

        # Wheel center and radius
        cx = w / 2
        cy = h / 2 + 8
        radius = min(w, h - 20) / 2 - 16

        if radius < 20:
            p.end()
            return

        # Draw hue ring
        for deg in range(360):
            color = QColor.fromHslF(deg / 360.0, 0.7, 0.5)
            p.setPen(QPen(color, 2))
            rad = math.radians(deg)
            x1 = cx + (radius - 4) * math.cos(rad)
            y1 = cy + (radius - 4) * math.sin(rad)
            x2 = cx + radius * math.cos(rad)
            y2 = cy + radius * math.sin(rad)
            p.drawLine(QPointF(x1, y1), QPointF(x2, y2))

        # Song palette dots
        for color_tuple in self.report.song_palette_rgb:
            self._draw_color_dot(p, cx, cy, radius, color_tuple, size=8, outline=QColor(180, 180, 180))

        # Current section colors (larger, highlighted)
        for color_tuple in self._current_colors:
            self._draw_color_dot(p, cx, cy, radius, color_tuple, size=12, outline=QColor(255, 255, 255))

        p.end()

    def _draw_color_dot(self, p, cx, cy, radius, rgb_tuple, size=8, outline=None):
        """Draw a dot at the HSL position of the given RGB color."""
        r, g, b = [c / 255.0 for c in rgb_tuple[:3]]
        h_val, l_val, s_val = colorsys.rgb_to_hls(r, g, b)

        # Position on wheel: hue = angle, saturation = distance from center
        angle = h_val * 2 * math.pi
        dist = s_val * (radius - 10) * 0.7 + 10  # Min distance from center
        x = cx + dist * math.cos(angle)
        y = cy + dist * math.sin(angle)

        color = QColor(int(r * 255), int(g * 255), int(b * 255))
        p.setBrush(QBrush(color))
        if outline:
            p.setPen(QPen(outline, 1.5))
        else:
            p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(x, y), size / 2, size / 2)


# ── Main Inspector Window ───────────────────────────────

class GenerationInspector(QWidget):
    """Live dashboard showing auto-generation decisions during playback."""

    def __init__(self, report: GenerationReport, audio_path: str = "", parent=None):
        super().__init__(parent)
        self.report = report
        self._audio_path = audio_path
        self._current_section_idx = -1
        self._selected_group = None

        self.setWindowTitle("Generation Inspector")
        self.setWindowFlags(Qt.WindowType.Window)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.resize(900, 750)

        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)

        # Top: Audio features timeline (full width)
        self.audio_widget = AudioFeaturesWidget(self.report)
        layout.addWidget(self.audio_widget, stretch=3)

        # Mel spectrogram (full width, below features)
        self.spectrogram_widget = MelSpectrogramWidget(self.report)
        layout.addWidget(self.spectrogram_widget, stretch=2)

        # Bottom: 2x2 grid via splitters
        bottom_splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left column
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(2)

        self.activation_widget = GroupActivationWidget(self.report)
        self.activation_widget.group_selected_callback = self._on_group_selected
        left_layout.addWidget(self.activation_widget, stretch=3)

        self.color_widget = ColorPaletteWidget(self.report)
        left_layout.addWidget(self.color_widget, stretch=2)

        bottom_splitter.addWidget(left_widget)

        # Right column
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(2)

        self.scores_widget = RudimentScoresWidget()
        right_layout.addWidget(self.scores_widget, stretch=3)

        self.info_label = QLabel()
        self.info_label.setWordWrap(True)
        self.info_label.setStyleSheet(
            f"background-color: {BG_PANEL.name()}; color: {TEXT_COLOR.name()}; "
            f"padding: 6px; font-family: monospace; font-size: 9pt;"
        )
        self.info_label.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.info_label.setText("Waiting for playback...")
        right_layout.addWidget(self.info_label, stretch=2)

        bottom_splitter.addWidget(right_widget)
        bottom_splitter.setSizes([450, 450])

        layout.addWidget(bottom_splitter, stretch=5)

    def update_position(self, time: float):
        """Called from ShowsTab at ~30Hz during playback."""
        # Always update cursors (cheap)
        self.audio_widget.update_cursor(time)
        self.spectrogram_widget.update_cursor(time)

        # Find current section
        section = self.report.get_section_at(time)
        if section is None:
            return

        new_idx = self.report.sections.index(section)
        if new_idx == self._current_section_idx:
            return  # Same section — skip full redraw

        self._current_section_idx = new_idx
        self._update_section(section)

    def _update_section(self, section: SectionReport):
        """Full update when section changes."""
        self.activation_widget.set_section(self._current_section_idx)
        self.color_widget.set_section_colors(section.color_rgb)

        # Update scores for selected group (or first active group)
        if self._selected_group and self._selected_group in section.group_reports:
            group_name = self._selected_group
        else:
            # Pick first active group
            group_name = next(
                (n for n, gr in section.group_reports.items() if gr.weight > 0),
                next(iter(section.group_reports), "")
            )
            self._selected_group = group_name

        # Always refresh: a section without group reports must clear the
        # previous section's bars, not leave them under the new section.
        self._update_scores_for_group(section, group_name)

        # Update info panel
        self._update_info(section)

    def _on_group_selected(self, group_name: str):
        """Called when user clicks a group in the activation grid."""
        self._selected_group = group_name
        if 0 <= self._current_section_idx < len(self.report.sections):
            section = self.report.sections[self._current_section_idx]
            self._update_scores_for_group(section, group_name)

    def _update_scores_for_group(self, section: SectionReport, group_name: str):
        gr = section.group_reports.get(group_name) if group_name else None
        if gr:
            self.scores_widget.set_data(
                gr.match_scores, gr.groove_rudiment, group_name
            )
        else:
            # No decision for this group here (inactive in this section,
            # or no group at all): show the empty state rather than the
            # previous group's or section's scores.
            self.scores_widget.set_data([], "", group_name or "")

    def _update_info(self, section: SectionReport):
        """Build the section info text panel."""
        lines = []
        # Names are user text rendered as rich text: escape them so a
        # "Front & Back" or "<Wash>" group neither vanishes nor breaks
        # the table markup. str() first: a None field rendered as
        # "None" before and must not crash the panel now.
        def esc(value) -> str:
            return html.escape(str(value))
        lines.append(f"<b>{esc(section.name)}</b>")
        lines.append(f"Energy: <b>{section.relative_energy:.2f}</b> | "
                      f"Flux: {section.spectral_flux:.2f} | "
                      f"Transient: {section.transient_sharpness:.2f}")
        lines.append(f"Richness: {section.spectral_richness:.2f} | "
                      f"Vocal: {section.vocal_presence:.2f} | "
                      f"Centroid: {section.spectral_centroid:.0f}")
        lines.append(f"Movement: <b>{esc(section.movement_shape)}</b> "
                      f"(amp={section.movement_amplitude:.0f}, "
                      f"target={esc(section.movement_target or 'none')})")
        lines.append("")
        lines.append("<table cellspacing='2' style='font-size:8pt'>")
        lines.append("<tr><td><b>Group</b></td><td><b>Groove</b></td>"
                      "<td><b>Fill</b></td><td><b>Role</b></td>"
                      "<td><b>Wt</b></td><td><b>Spd</b></td></tr>")

        for name, gr in section.group_reports.items():
            if gr.weight <= 0:
                role_str = "<span style='color:#666'>off</span>"
            else:
                role_color = {"full": "#4b4", "groove": "#48c", "fill": "#e84"}.get(gr.role, "#888")
                role_str = f"<span style='color:{role_color}'>{esc(gr.role)}</span>"

            lines.append(
                f"<tr><td>{esc(name[:10])}</td>"
                f"<td>{esc(gr.groove_rudiment)} <span style='color:#888'>({esc(gr.groove_category)})</span></td>"
                f"<td>{esc(gr.fill_rudiment)}</td>"
                f"<td>{role_str}</td>"
                f"<td>{gr.weight:.1f}</td>"
                f"<td>{esc(gr.effect_speed)}</td></tr>"
            )

        lines.append("</table>")
        self.info_label.setText("<br>".join(lines))
