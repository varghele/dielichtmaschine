# timeline_ui/audio_lane_widget.py
# Audio lane widget for displaying waveform and audio controls on the timeline

import os
from PyQt6.QtWidgets import (QWidget, QHBoxLayout, QVBoxLayout, QLabel,
                             QPushButton, QSlider, QFrame, QScrollArea,
                             QFileDialog, QLineEdit)
from PyQt6.QtCore import Qt, pyqtSignal
from .timeline_widget import TimelineWidget

# Try to import audio components - may not be available in all installations
try:
    from audio.audio_file import AudioFile
    from audio.audio_waveform_widget import AudioWaveformWidget, AudioLoaderThread
    AUDIO_AVAILABLE = True
except ImportError:
    AUDIO_AVAILABLE = False
    AudioFile = None
    AudioWaveformWidget = None
    AudioLoaderThread = None


class AudioTimelineWidget(TimelineWidget):
    """Timeline widget with embedded waveform display."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.waveform_widget = None
        self.audio_file = None

        if AUDIO_AVAILABLE:
            self.waveform_widget = AudioWaveformWidget(self)
            self.waveform_widget.setStyleSheet("background: transparent;")

    def resizeEvent(self, event):
        """Handle resize to update waveform widget size."""
        super().resizeEvent(event)
        if self.waveform_widget:
            self.waveform_widget.setGeometry(0, 0, self.width(), self.height())

    def set_zoom_factor(self, zoom_factor: float):
        """Set zoom factor and update waveform."""
        super().set_zoom_factor(zoom_factor)
        if self.waveform_widget:
            self.waveform_widget.set_zoom_factor(zoom_factor)

    def load_audio(self, audio_file):
        """Load audio file for waveform display."""
        self.audio_file = audio_file
        if self.waveform_widget and audio_file:
            self.waveform_widget.load_audio_file(audio_file)

    def paintEvent(self, event):
        """Draw timeline with waveform overlay."""
        # Draw base timeline (grid, playhead)
        super().paintEvent(event)
        # Waveform widget draws itself as a child

    def cleanup(self):
        """Clean up resources."""
        if self.waveform_widget:
            self.waveform_widget.cleanup()


class AudioLaneWidget(QFrame):
    """Widget for displaying and controlling the audio lane.

    Shows lane controls on the left (file path, load button, volume, mute)
    and a scrollable timeline with waveform on the right.
    """

    scroll_position_changed = pyqtSignal(int)  # Emits horizontal scroll position
    zoom_changed = pyqtSignal(float)  # Emits zoom factor
    playhead_moved = pyqtSignal(float)  # Emits playhead position
    audio_file_changed = pyqtSignal(str)  # Emits new audio file path

    def __init__(self, parent=None):
        """Create a new audio lane widget.

        Args:
            parent: Parent widget
        """
        super().__init__(parent)
        self.audio_file = None
        self.audio_file_path = ""
        self.audio_loader_thread = None  # Background audio loader
        self._is_loading_audio = False

        self.setFrameStyle(QFrame.Shape.Box)
        self.setLineWidth(1)
        self.setMinimumHeight(100)
        self.setMaximumHeight(140)
        # Background tint from `AudioLaneWidget` selector in the active theme.

        self.setup_ui()

    def setup_ui(self):
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Build the two pieces — controls on the left, timeline on the right.
        # When this widget is embedded in TimelineGrid, detach_pieces() will
        # tear this layout down and hand both children to the grid.
        self.controls_widget = self.create_controls_widget()
        main_layout.addWidget(self.controls_widget)

        self.timeline_scroll = QScrollArea()
        self.timeline_widget = AudioTimelineWidget()
        self.timeline_widget.zoom_changed.connect(self.zoom_changed.emit)
        self.timeline_widget.zoom_changed.connect(self.on_timeline_zoom_changed)
        self.timeline_widget.playhead_moved.connect(self.playhead_moved.emit)

        self.timeline_scroll.setWidget(self.timeline_widget)
        self.timeline_scroll.setWidgetResizable(False)
        self.timeline_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.timeline_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        # Connect scroll events
        self.timeline_scroll.horizontalScrollBar().valueChanged.connect(
            self.scroll_position_changed.emit)
        self.timeline_scroll.horizontalScrollBar().valueChanged.connect(
            self._on_scroll_changed)

        main_layout.addWidget(self.timeline_scroll, 1)

    def detach_pieces(self):
        """Return (header_widget, stripe_widget) for embedding in TimelineGrid.

        After this call ``self`` no longer renders its own UI — the inner
        scrollarea is gone and ``controls_widget`` / ``timeline_widget`` are
        free to be re-parented. Signals on ``self`` keep working because
        they're wired to the timeline widget directly.
        """
        if hasattr(self, "timeline_scroll") and self.timeline_scroll is not None:
            self.timeline_scroll.takeWidget()
            self.timeline_scroll.setParent(None)
            self.timeline_scroll = None
        return self.controls_widget, self.timeline_widget

    def create_controls_widget(self):
        """Create the lane controls section. All visuals come from the
        active theme — only structural styling stays inline."""
        widget = QWidget()
        # Object-name + WA_StyledBackground so the theme's
        # `QWidget#AudioLaneHeader` rule paints the bg after the
        # controls widget is detached and re-parented into TimelineGrid.
        widget.setObjectName("AudioLaneHeader")
        widget.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        widget.setFixedWidth(320)
        layout = QVBoxLayout(widget)
        layout.setSpacing(4)
        layout.setContentsMargins(8, 8, 8, 8)

        # Row 1: Audio label — Barlow Condensed display caps (North Star)
        from gui.typography import DisplayLabel
        title_layout = QHBoxLayout()
        title_label = DisplayLabel("Audio Track", point_size=13)
        title_layout.addWidget(title_label)
        title_layout.addStretch()
        layout.addLayout(title_layout)

        # Row 2: File path and load button
        file_layout = QHBoxLayout()

        self.file_path_edit = QLineEdit()
        self.file_path_edit.setPlaceholderText("No audio file loaded")
        self.file_path_edit.setReadOnly(True)
        file_layout.addWidget(self.file_path_edit, 1)

        self.load_button = QPushButton("LOAD")
        self.load_button.setFixedWidth(56)
        # cta-outline is the shared bordered display-caps role for text
        # actions across the timeline (Save, Inspector, POP OUT); "LOAD"
        # joins them. density=compact tightens padding so the caps fit in
        # the narrow lane-header column.
        self.load_button.setProperty("density", "compact")
        self.load_button.setProperty("role", "cta-outline")
        self.load_button.clicked.connect(self._on_load_clicked)
        file_layout.addWidget(self.load_button)

        layout.addLayout(file_layout)

        # Row 3: Volume and mute controls
        controls_layout = QHBoxLayout()

        # Mute chip - the shared output-select toggle-chip role, matching
        # the light-lane mute/solo chips and the toolbar SNAP/SWING chips
        # (accent outline when active, no per-chip inline stylesheet).
        # density=compact keeps the glyph inside the 30x25 chip. (Don't use
        # "size" as the property name - collides with Qt's QSize property.)
        self.mute_button = QPushButton("M")
        self.mute_button.setFixedSize(30, 25)
        self.mute_button.setCheckable(True)
        self.mute_button.setProperty("density", "compact")
        self.mute_button.setProperty("role", "output-select")
        self.mute_button.toggled.connect(self._on_mute_toggled)
        controls_layout.addWidget(self.mute_button)

        from gui.typography import MicroLabel
        vol_label = MicroLabel("Vol")
        controls_layout.addWidget(vol_label)

        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(100)
        self.volume_slider.setFixedWidth(100)
        self.volume_slider.valueChanged.connect(self._on_volume_changed)
        controls_layout.addWidget(self.volume_slider)

        from gui.typography import mono_font
        self.volume_label = QLabel("100%")
        self.volume_label.setFixedWidth(35)
        self.volume_label.setFont(mono_font(10))
        controls_layout.addWidget(self.volume_label)

        controls_layout.addStretch()

        layout.addLayout(controls_layout)

        return widget

    def _on_load_clicked(self):
        """Handle load button click - open file dialog."""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Audio File",
            "",
            "Audio Files (*.wav *.mp3 *.flac *.ogg);;All Files (*)"
        )
        if file_path:
            self.load_audio_file(file_path)

    def load_audio_file(self, file_path: str):
        """Load an audio file and display its waveform.

        Args:
            file_path: Path to the audio file
        """
        if not AUDIO_AVAILABLE:
            self.file_path_edit.setText("Audio support not available")
            return

        if not os.path.exists(file_path):
            self.file_path_edit.setText(f"File not found: {file_path}")
            return

        # Cancel any ongoing load
        if self.audio_loader_thread and self.audio_loader_thread.isRunning():
            self.audio_loader_thread.quit()
            self.audio_loader_thread.wait()

        self.audio_file_path = file_path
        self._is_loading_audio = True

        # Show loading indicator
        self.file_path_edit.setText(f"Loading {os.path.basename(file_path)}...")
        self.file_path_edit.setToolTip(file_path)
        self.load_button.setEnabled(False)

        # Load audio file in background thread
        self.audio_loader_thread = AudioLoaderThread(file_path)
        self.audio_loader_thread.audio_loaded.connect(self._on_audio_loaded)
        self.audio_loader_thread.error_occurred.connect(self._on_audio_load_error)
        self.audio_loader_thread.start()

    def _on_audio_loaded(self, audio_file: AudioFile):
        """Handle audio file loaded successfully"""
        self._is_loading_audio = False
        self.audio_file = audio_file
        self.file_path_edit.setText(os.path.basename(self.audio_file_path))
        self.load_button.setEnabled(True)

        # Load into timeline widget
        self.timeline_widget.load_audio(self.audio_file)
        self.audio_file_changed.emit(self.audio_file_path)

    def _on_audio_load_error(self, error_message: str):
        """Handle audio loading error"""
        self._is_loading_audio = False
        self.audio_file = None
        self.file_path_edit.setText(f"Error loading file")
        self.file_path_edit.setToolTip(error_message)
        self.load_button.setEnabled(True)
        print(f"Audio load error: {error_message}")

    def clear_audio(self):
        """Clear the current audio file and reset the display."""
        self.audio_file = None
        self.audio_file_path = ""
        self.file_path_edit.setText("")
        self.file_path_edit.setPlaceholderText("No audio file loaded")
        self.file_path_edit.setToolTip("")
        # Clear waveform from timeline
        if hasattr(self.timeline_widget, 'load_audio'):
            self.timeline_widget.load_audio(None)

    def get_audio_file_path(self) -> str:
        """Get the current audio file path."""
        return self.audio_file_path

    def get_audio_file(self):
        """Get the loaded AudioFile object."""
        return self.audio_file

    def _on_volume_changed(self, value: int):
        """Handle volume slider change."""
        self.volume_label.setText(f"{value}%")
        # Volume control will be connected to audio engine by parent

    def _on_mute_toggled(self, checked: bool):
        """Handle mute button toggle. Visuals are driven by the :checked
        rule on the button's persistent stylesheet; this slot only forwards
        the state to whatever consumer the parent has wired up."""
        # Mute state will be connected to audio engine by parent

    def is_muted(self) -> bool:
        """Check if audio is muted."""
        return self.mute_button.isChecked()

    def get_volume(self) -> float:
        """Get current volume as 0.0-1.0."""
        return self.volume_slider.value() / 100.0

    def _on_scroll_changed(self, position: int):
        """Handle scroll position change - update waveform offset."""
        if self.timeline_widget.waveform_widget:
            self.timeline_widget.waveform_widget.set_scroll_offset(position)

    def on_timeline_zoom_changed(self, zoom_factor: float):
        """Handle timeline zoom changes."""
        if self.timeline_widget.waveform_widget:
            self.timeline_widget.waveform_widget.set_zoom_factor(zoom_factor)

    def set_song_structure(self, song_structure):
        """Set song structure for this lane's timeline."""
        self.timeline_widget.set_song_structure(song_structure)

    def set_playhead_position(self, position: float):
        """Set playhead position for this lane's timeline."""
        self.timeline_widget.set_playhead_position(position)

    def set_zoom_factor(self, zoom_factor: float):
        """Set zoom factor for this lane's timeline."""
        self.timeline_widget.set_zoom_factor(zoom_factor)
        if self.timeline_widget.waveform_widget:
            self.timeline_widget.waveform_widget.set_zoom_factor(zoom_factor)

    def sync_scroll_position(self, position: int):
        """Sync scroll position with master timeline."""
        self.timeline_scroll.horizontalScrollBar().setValue(position)

    def cleanup(self):
        """Clean up audio resources."""
        # Stop any running audio loader thread
        if self.audio_loader_thread and self.audio_loader_thread.isRunning():
            self.audio_loader_thread.quit()
            self.audio_loader_thread.wait()

        self.timeline_widget.cleanup()
