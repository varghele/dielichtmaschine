"""
Auto-mode metrics tracker — scrolling 30-second chart of audio features.

QPainter-based widget showing flux, rms, transient, richness, vocal,
centroid, and contrast as color-coded polylines.
"""

from collections import deque
from PyQt6.QtWidgets import QWidget
from PyQt6.QtCore import QPointF
from PyQt6.QtGui import QPainter, QPen, QColor, QFont

from audio.realtime_spectral import LiveFeatureFrame


# 30 seconds at 20Hz UI updates
_BUFFER_SIZE = 600

_METRIC_COLORS = {
    'flux':      QColor(255, 100, 100),   # red
    'rms':       QColor(100, 255, 100),   # green
    'transient': QColor(100, 100, 255),   # blue
    'richness':  QColor(255, 200, 50),    # yellow
    'vocal':     QColor(200, 100, 255),   # purple
    'centroid':  QColor(50, 220, 220),    # cyan
    'contrast':  QColor(255, 150, 50),    # orange
}

_METRICS = ['flux', 'rms', 'transient', 'richness', 'vocal', 'centroid', 'contrast']


class AutoMetricsTracker(QWidget):
    """Scrolling line chart of audio features over the last 30 seconds."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(130)
        self.setMinimumWidth(200)

        self._buffers: dict = {m: deque(maxlen=_BUFFER_SIZE) for m in _METRICS}

    def append_frame(self, frame: LiveFeatureFrame):
        """Append a feature frame (called at 20Hz from UI timer)."""
        self._buffers['flux'].append(frame.flux)
        self._buffers['rms'].append(frame.rms)
        self._buffers['transient'].append(frame.transient)
        self._buffers['richness'].append(frame.richness)
        self._buffers['vocal'].append(frame.vocal)
        self._buffers['centroid'].append(frame.centroid)
        self._buffers['contrast'].append(frame.contrast)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        h = self.height()

        # Background
        painter.fillRect(0, 0, w, h, QColor(20, 20, 30))

        # Chart area (leave room for legend at top)
        legend_h = 16
        chart_top = legend_h + 2
        chart_h = h - chart_top - 2

        # Grid lines
        pen = QPen(QColor(50, 50, 60))
        pen.setWidth(1)
        painter.setPen(pen)
        for frac in [0.25, 0.5, 0.75]:
            y = chart_top + chart_h * (1.0 - frac)
            painter.drawLine(0, int(y), w, int(y))

        # Draw metric lines
        for metric in _METRICS:
            buf = self._buffers[metric]
            n = len(buf)
            if n < 2:
                continue

            color = _METRIC_COLORS[metric]
            pen = QPen(color)
            pen.setWidth(1)
            painter.setPen(pen)

            points = []
            for i, val in enumerate(buf):
                x = (i / (_BUFFER_SIZE - 1)) * w
                y = chart_top + chart_h * (1.0 - max(0.0, min(1.0, val)))
                points.append(QPointF(x, y))

            # Shift points to right-align (latest sample at right edge)
            offset = w - (n / (_BUFFER_SIZE - 1)) * w
            shifted = [QPointF(p.x() + offset, p.y()) for p in points]

            for i in range(len(shifted) - 1):
                painter.drawLine(shifted[i], shifted[i + 1])

        # Legend
        font = QFont("Monospace", 7)
        painter.setFont(font)
        x_pos = 4
        for metric in _METRICS:
            color = _METRIC_COLORS[metric]
            painter.setPen(QPen(color))
            label = metric[:4]
            painter.drawText(x_pos, legend_h - 3, label)
            x_pos += 32

        painter.end()
