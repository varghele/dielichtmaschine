"""
Qt signal bridge for real-time spectral features.
Subscribes to RealtimeSpectralAnalyzer and re-emits features
as Qt signals, safe for connecting to GUI slots from the main thread.
"""

from PyQt6.QtCore import QObject, pyqtSignal
from audio.realtime_spectral import RealtimeSpectralAnalyzer, LiveFeatureFrame
from audio.ring_buffer import AudioRingBuffer


class LiveFeatureBridge(QObject):
    """Bridges the analysis thread to the Qt event loop.

    Usage:
        bridge = LiveFeatureBridge(analyzer)
        bridge.feature_updated.connect(my_widget.on_feature)
        bridge.start(ring_buffer)
    """

    feature_updated = pyqtSignal(object)  # emits LiveFeatureFrame

    def __init__(self, analyzer: RealtimeSpectralAnalyzer, parent=None):
        super().__init__(parent)
        self._analyzer = analyzer

    def start(self, ring_buffer: AudioRingBuffer) -> None:
        """Start analysis and begin emitting signals."""
        self._analyzer.subscribe(self._on_feature)
        self._analyzer.start(ring_buffer)

    def stop(self) -> None:
        """Stop analysis and disconnect."""
        self._analyzer.unsubscribe(self._on_feature)
        self._analyzer.stop()

    def _on_feature(self, frame: LiveFeatureFrame) -> None:
        """Called on the analysis thread — emits Qt signal (thread-safe)."""
        self.feature_updated.emit(frame)
