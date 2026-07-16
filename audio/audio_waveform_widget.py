"""
Audio waveform visualization widget.
Displays waveform envelope as semi-transparent overlay on timeline.
"""

from PyQt6.QtWidgets import QWidget
from PyQt6.QtGui import QPainter, QColor, QPen, QPixmap, QPolygonF
from PyQt6.QtCore import Qt, QPointF, QThread, pyqtSignal
from typing import Optional
import numpy as np

from .audio_file import AudioFile
from .waveform_analyzer import WaveformAnalyzer, WaveformData


class AudioLoaderThread(QThread):
    """Background thread for loading audio files"""

    audio_loaded = pyqtSignal(object)  # Emits AudioFile
    error_occurred = pyqtSignal(str)  # Emits error message

    def __init__(self, file_path: str):
        super().__init__()
        self.file_path = file_path

    def run(self):
        """Load audio file in background"""
        try:
            audio_file = AudioFile()
            success = audio_file.load(self.file_path)
            if success:
                self.audio_loaded.emit(audio_file)
            else:
                self.error_occurred.emit(f"Failed to load audio file: {self.file_path}")
        except Exception as e:
            self.error_occurred.emit(f"Audio loading error: {str(e)}")


class WaveformGeneratorThread(QThread):
    """Background thread for waveform generation"""

    waveform_ready = pyqtSignal(object)  # Emits WaveformData
    error_occurred = pyqtSignal(str)  # Emits error message

    def __init__(self, audio_file: AudioFile, analyzer: WaveformAnalyzer):
        super().__init__()
        self.audio_file = audio_file
        self.analyzer = analyzer

    def run(self):
        """Generate waveform data in background"""
        try:
            waveform_data = self.analyzer.analyze_file(self.audio_file)
            if waveform_data:
                self.waveform_ready.emit(waveform_data)
            else:
                self.error_occurred.emit("Failed to generate waveform data")
        except Exception as e:
            self.error_occurred.emit(f"Waveform generation error: {str(e)}")


class AudioWaveformWidget(QWidget):
    """Widget that displays audio waveform on timeline"""

    def __init__(self, parent=None):
        super().__init__(parent)

        self.waveform_data: Optional[WaveformData] = None
        self.audio_file: Optional[AudioFile] = None
        self.analyzer = WaveformAnalyzer()

        # Display parameters
        self.pixels_per_second = 60  # Base display resolution
        self.zoom_factor = 1.0
        self.scroll_offset = 0  # Horizontal scroll offset in pixels

        # Visual styling
        self.waveform_color = QColor(100, 150, 255, 120)  # Semi-transparent blue
        self.background_color = QColor(30, 30, 30, 50)  # Very subtle background

        # Loading state
        self.is_loading = False
        self.load_error: Optional[str] = None

        # Background thread
        self.generator_thread: Optional[WaveformGeneratorThread] = None

        # Set minimum height
        self.setMinimumHeight(80)

    def load_audio_file(self, audio_file: AudioFile):
        """
        Load and analyze an audio file for waveform display

        Args:
            audio_file: Loaded AudioFile object
        """
        if not audio_file.is_loaded():
            self.load_error = "Audio file not loaded"
            self.update()
            return

        self.audio_file = audio_file
        self.is_loading = True
        self.load_error = None
        self.update()

        # Start background generation
        self.generator_thread = WaveformGeneratorThread(audio_file, self.analyzer)
        self.generator_thread.waveform_ready.connect(self.on_waveform_ready)
        self.generator_thread.error_occurred.connect(self.on_waveform_error)
        self.generator_thread.start()

    def on_waveform_ready(self, waveform_data: WaveformData):
        """Handle waveform data ready"""
        self.waveform_data = waveform_data
        self.is_loading = False
        self.update()

    def on_waveform_error(self, error_message: str):
        """Handle waveform generation error"""
        self.load_error = error_message
        self.is_loading = False
        self.update()

    def set_zoom_factor(self, zoom_factor: float):
        """Update zoom level"""
        self.zoom_factor = zoom_factor
        self.update()

    def set_scroll_offset(self, offset: int):
        """Update scroll offset"""
        self.scroll_offset = offset
        self.update()

    def time_to_pixel(self, time_seconds: float) -> int:
        """Convert time to pixel position"""
        return int(time_seconds * self.pixels_per_second * self.zoom_factor)

    def pixel_to_time(self, pixel: int) -> float:
        """Convert pixel position to time"""
        return pixel / (self.pixels_per_second * self.zoom_factor)

    def paintEvent(self, event):
        """Draw the waveform"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        width = self.width()
        height = self.height()

        # Draw subtle background
        painter.fillRect(0, 0, width, height, self.background_color)

        # Handle loading/error states
        if self.is_loading:
            self.draw_loading_state(painter, width, height)
            return

        if self.load_error:
            self.draw_error_state(painter, width, height)
            return

        if not self.waveform_data or not self.audio_file:
            self.draw_no_audio_state(painter, width, height)
            return

        # Draw the waveform from the render cache: the widget spans the
        # FULL song canvas and sits under the playhead overlay, so
        # playback's ~30 FPS strip invalidations repaint slices of it -
        # rebuilding the peak polygon in Python cost ~60 ms per tick on
        # a real project (2026-07-16 lag fix). The polygon renders once
        # per (size, zoom, scroll, data) into a pixmap; ticks just blit
        # the exposed slice.
        key = (width, height, self.zoom_factor, self.scroll_offset,
               id(self.waveform_data))
        cached = getattr(self, "_render_cache", None)
        if cached is None or cached[0] != key:
            pixmap = QPixmap(width, height)
            pixmap.fill(Qt.GlobalColor.transparent)
            cache_painter = QPainter(pixmap)
            cache_painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            self.draw_waveform(cache_painter, width, height)
            cache_painter.end()
            cached = (key, pixmap)
            self._render_cache = cached
        painter.drawPixmap(event.rect(), cached[1], event.rect())

    def draw_waveform(self, painter: QPainter, width: int, height: int):
        """Draw the actual waveform"""
        if not self.waveform_data:
            return

        # Get appropriate peak data for current zoom
        pixels_per_second = self.pixels_per_second * self.zoom_factor
        peaks = self.waveform_data.get_peaks_for_zoom(pixels_per_second)

        if not peaks or len(peaks.min_peaks) == 0:
            return

        # Calculate visible time range
        visible_start_time = self.pixel_to_time(self.scroll_offset)
        visible_end_time = self.pixel_to_time(self.scroll_offset + width)

        # Calculate peak indices for visible range
        samples_per_peak = peaks.resolution
        sample_rate = self.waveform_data.sample_rate

        start_peak_idx = int(visible_start_time * sample_rate / samples_per_peak)
        end_peak_idx = int(visible_end_time * sample_rate / samples_per_peak) + 1

        # Clamp to valid range
        start_peak_idx = max(0, start_peak_idx)
        end_peak_idx = min(len(peaks.min_peaks), end_peak_idx)

        if start_peak_idx >= end_peak_idx:
            return

        # Create polygon for waveform envelope
        top_points = []
        bottom_points = []

        center_y = height / 2
        scale = height / 2.5  # Leave some margin

        for i in range(start_peak_idx, end_peak_idx):
            # Calculate time and x position for this peak
            peak_time = (i * samples_per_peak) / sample_rate
            x = self.time_to_pixel(peak_time) - self.scroll_offset

            # Get peak values
            min_val = peaks.min_peaks[i]
            max_val = peaks.max_peaks[i]

            # Scale to widget coordinates
            top_y = center_y - (max_val * scale)
            bottom_y = center_y - (min_val * scale)

            top_points.append(QPointF(x, top_y))
            bottom_points.append(QPointF(x, bottom_y))

        # Create closed polygon (top line forward, bottom line backward)
        polygon = QPolygonF(top_points + list(reversed(bottom_points)))

        # Draw filled waveform
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self.waveform_color)
        painter.drawPolygon(polygon)

        # Draw outline for clarity
        outline_color = QColor(self.waveform_color)
        outline_color.setAlpha(200)
        painter.setPen(QPen(outline_color, 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPolyline(QPolygonF(top_points))
        painter.drawPolyline(QPolygonF(bottom_points))

    def draw_loading_state(self, painter: QPainter, width: int, height: int):
        """Draw loading indicator"""
        painter.setPen(QColor(200, 200, 200))
        painter.drawText(0, 0, width, height, Qt.AlignmentFlag.AlignCenter,
                         "Generating waveform...")

    def draw_error_state(self, painter: QPainter, width: int, height: int):
        """Draw error message"""
        painter.setPen(QColor(255, 100, 100))
        painter.drawText(0, 0, width, height, Qt.AlignmentFlag.AlignCenter,
                         f"Error: {self.load_error}")

    def draw_no_audio_state(self, painter: QPainter, width: int, height: int):
        """Draw placeholder when no audio loaded"""
        painter.setPen(QColor(150, 150, 150))
        painter.drawText(0, 0, width, height, Qt.AlignmentFlag.AlignCenter,
                         "No audio loaded")

    def set_waveform_color(self, color: QColor):
        """Set the color for waveform display"""
        self.waveform_color = color
        self.update()

    def cleanup(self):
        """Cleanup resources"""
        if self.generator_thread and self.generator_thread.isRunning():
            self.generator_thread.quit()
            self.generator_thread.wait()
