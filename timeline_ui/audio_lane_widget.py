# timeline_ui/audio_lane_widget.py
# Audio lane widget for displaying waveform and audio controls on the timeline

import os
from PyQt6.QtWidgets import (QWidget, QHBoxLayout, QVBoxLayout, QLabel,
                             QPushButton, QSlider, QFrame, QScrollArea,
                             QFileDialog, QLineEdit)
from PyQt6.QtCore import Qt, pyqtSignal
from .timeline_widget import TimelineWidget, HEADER_COLUMN_WIDTH

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


# Row height of the compact audio row (timeline v3 stage T4, screen 06b).
COMPACT_AUDIO_ROW_HEIGHT = 44


class _ElidedFileLabel(QLabel):
    """Middle-elided filename readout for the compact audio header.

    Drop-in for the QLineEdit the full-size header uses: it keeps the
    setText / setToolTip / setPlaceholderText / setReadOnly surface the
    call sites drive (gui/tabs/shows_tab.py sets the filename and
    tooltip on ``file_path_edit`` directly), so the attribute name and
    its contracts survive the compact restyle. ``text()`` returns the
    full un-elided string; only the painted text is elided.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._full_text = ""
        self._placeholder = ""

    def setText(self, text):  # noqa: N802 (Qt API)
        self._full_text = text or ""
        self._update_display()

    def text(self):  # noqa: N802 (Qt API)
        return self._full_text

    def setPlaceholderText(self, text):  # noqa: N802 (QLineEdit shim)
        self._placeholder = text or ""
        self._update_display()

    def placeholderText(self):  # noqa: N802 (QLineEdit shim)
        return self._placeholder

    def setReadOnly(self, _read_only):  # noqa: N802 (QLineEdit shim)
        pass

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_display()

    def _update_display(self):
        shown = self._full_text or self._placeholder
        metrics = self.fontMetrics()
        available = max(0, self.width() - 2)
        super().setText(metrics.elidedText(
            shown, Qt.TextElideMode.ElideMiddle, available))


class AudioLaneWidget(QFrame):
    """Widget for displaying and controlling the audio lane.

    Shows lane controls on the left (file path, load button, volume, mute)
    and a scrollable timeline with waveform on the right.

    ``compact=True`` (Shows tab, timeline v3 stage T4) shrinks the row to
    44px: the header cell carries "AUDIO" + a middle-elided filename on
    one mono line and the M / volume / LOAD controls on a second, and the
    playhead joins the unified accent line. Every control attribute
    (``file_path_edit``, ``load_button``, ``mute_button``,
    ``volume_slider``, ``volume_label``) keeps its name and behaviour.
    ``embedded_row_height`` tells TimelineGrid the row height to pin.
    """

    scroll_position_changed = pyqtSignal(int)  # Emits horizontal scroll position
    zoom_changed = pyqtSignal(float)  # Emits zoom factor
    playhead_moved = pyqtSignal(float)  # Emits playhead position
    audio_file_changed = pyqtSignal(str)  # Emits new audio file path

    def __init__(self, parent=None, compact=False):
        """Create a new audio lane widget.

        Args:
            parent: Parent widget
            compact: Timeline v3 44px row (Shows tab); default keeps the
                full-size lane the Structure tab embeds.
        """
        super().__init__(parent)
        self.audio_file = None
        self.audio_file_path = ""
        self.audio_loader_thread = None  # Background audio loader
        self._is_loading_audio = False
        self.compact = compact
        self.embedded_row_height = COMPACT_AUDIO_ROW_HEIGHT if compact else None

        self.setFrameStyle(QFrame.Shape.Box)
        self.setLineWidth(1)
        if compact:
            self.setMinimumHeight(COMPACT_AUDIO_ROW_HEIGHT)
            self.setMaximumHeight(COMPACT_AUDIO_ROW_HEIGHT)
        else:
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
        if self.compact:
            # Unified 2px accent playhead + a stripe that can shrink to
            # the 44px row (the TimelineWidget base floor is 60).
            self.timeline_widget.playhead_accent = True
            self.timeline_widget.setMinimumHeight(COMPACT_AUDIO_ROW_HEIGHT)
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
        if self.compact:
            return self._create_compact_controls_widget()
        widget = QWidget()
        # Object-name + WA_StyledBackground so the theme's
        # `QWidget#AudioLaneHeader` rule paints the bg after the
        # controls widget is detached and re-parented into TimelineGrid.
        widget.setObjectName("AudioLaneHeader")
        widget.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        widget.setFixedWidth(HEADER_COLUMN_WIDTH)
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

    def _create_compact_controls_widget(self):
        """The 44px header cell (timeline v3, mock 06b): "AUDIO" + the
        middle-elided filename on one mono line, M / volume / LOAD as
        compact chips on a second. Same attribute names and signal
        wiring as the full-size header - only the chrome shrinks."""
        from gui.typography import MicroLabel, mono_font

        widget = QWidget()
        widget.setObjectName("AudioLaneHeader")
        widget.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        widget.setFixedWidth(HEADER_COLUMN_WIDTH)
        layout = QVBoxLayout(widget)
        layout.setSpacing(2)
        layout.setContentsMargins(12, 3, 8, 3)

        # Row 1: AUDIO caption + middle-elided filename.
        file_row = QHBoxLayout()
        file_row.setSpacing(8)
        file_row.addWidget(MicroLabel("Audio", point_size=8))

        self.file_path_edit = _ElidedFileLabel()
        self.file_path_edit.setFont(mono_font(8))
        self.file_path_edit.setProperty("role", "micro")
        self.file_path_edit.setPlaceholderText("No audio file loaded")
        self.file_path_edit.setReadOnly(True)
        file_row.addWidget(self.file_path_edit, 1)
        layout.addLayout(file_row)

        # Row 2: mute chip, volume slider + readout, LOAD chip.
        controls_row = QHBoxLayout()
        controls_row.setSpacing(4)

        self.mute_button = QPushButton("M")
        self.mute_button.setFixedSize(26, 18)
        self.mute_button.setCheckable(True)
        self.mute_button.setFont(mono_font(8))
        self.mute_button.setProperty("density", "compact")
        self.mute_button.setProperty("role", "output-select")
        self.mute_button.setToolTip("Mute audio")
        self.mute_button.toggled.connect(self._on_mute_toggled)
        controls_row.addWidget(self.mute_button)

        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(100)
        self.volume_slider.setFixedWidth(70)
        self.volume_slider.setFixedHeight(16)
        self.volume_slider.setToolTip("Audio volume")
        self.volume_slider.valueChanged.connect(self._on_volume_changed)
        controls_row.addWidget(self.volume_slider)

        self.volume_label = QLabel("100%")
        self.volume_label.setFixedWidth(32)
        self.volume_label.setFont(mono_font(8))
        controls_row.addWidget(self.volume_label)

        controls_row.addStretch()

        self.load_button = QPushButton("LOAD")
        self.load_button.setFixedWidth(56)
        self.load_button.setFixedHeight(18)
        self.load_button.setProperty("density", "compact")
        self.load_button.setProperty("role", "cta-outline")
        self.load_button.clicked.connect(self._on_load_clicked)
        controls_row.addWidget(self.load_button)

        layout.addLayout(controls_row)

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
            self.load_audio_file(file_path, force=True)

    def load_audio_file(self, file_path: str, force: bool = False):
        """Load an audio file and display its waveform.

        Args:
            file_path: Path to the audio file
            force: Reload even when ``file_path`` is already loaded or
                loading. The explicit LOAD action passes True (the user
                may be re-picking a file that changed on disk); config
                refresh paths leave it False - Structure tab activation
                re-runs the whole song load, and re-decoding the same
                audio plus re-analyzing the waveform on every tab visit
                cost real time on real projects AND left the waveform
                row mid-load whenever the visit was brief.
        """
        if not AUDIO_AVAILABLE:
            self.file_path_edit.setText("Audio support not available")
            return

        if not os.path.exists(file_path):
            self.file_path_edit.setText(f"File not found: {file_path}")
            return

        if not force and file_path == self.audio_file_path and (
                self._is_loading_audio or self.audio_file is not None):
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
