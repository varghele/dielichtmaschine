# gui/tabs/shows_tab.py
# Timeline-based show management tab

import os
import csv
from PyQt6.QtWidgets import (QVBoxLayout, QHBoxLayout, QComboBox, QPushButton,
                             QLabel, QSlider, QScrollArea, QWidget, QFrame,
                             QSplitter, QSizePolicy, QInputDialog, QMessageBox, QCheckBox,
                             QApplication, QDialog)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QPoint, QRect
from PyQt6.QtGui import QShortcut, QKeySequence
from config.models import Configuration, Show, ShowPart, TimelineData, LightBlock, ShowEffect
from timeline.song_structure import SongStructure
from timeline.light_lane import LightLane
from utils.fixture_utils import load_fixture_definitions_from_qlc, get_cached_fixture_definitions
from timeline_ui import (MasterTimelineContainer, LightLaneWidget, AudioLaneWidget,
                         TimelineGrid)
from timeline_ui.selection_manager import SelectionManager
from timeline_ui.selection_overlay import SelectionOverlay
from timeline_ui.effect_clipboard import (copy_multiple_effects, paste_multiple_effects,
                                          has_multi_clipboard_data, has_clipboard_data,
                                          paste_effect)
from gui.progress_manager import get_progress_manager
from gui.widgets.embedded_visualizer import EmbeddedVisualizer
from timeline_ui.riff_browser_widget import RiffBrowserPanel
from .base_tab import BaseTab

# Try to import simple audio player (pygame-based) - preferred for performance
try:
    from audio.simple_audio_player import SimpleAudioPlayer, PYGAME_AVAILABLE
    SIMPLE_AUDIO_AVAILABLE = PYGAME_AVAILABLE
except ImportError:
    SIMPLE_AUDIO_AVAILABLE = False

# Try to import legacy audio components - fallback if pygame not available
try:
    from audio.audio_file import AudioFile
    from audio.audio_engine import AudioEngine
    from audio.audio_mixer import AudioMixer
    from audio.playback_synchronizer import PlaybackSynchronizer
    from audio.device_manager import DeviceManager
    AUDIO_AVAILABLE = True
except ImportError:
    AUDIO_AVAILABLE = False

# Try to import ArtNet components - may not be available
try:
    from utils.artnet import ShowsArtNetController
    ARTNET_AVAILABLE = True
except ImportError:
    ARTNET_AVAILABLE = False

# Try to import TCP components - may not be available
try:
    from utils.tcp import VisualizerTCPServer
    TCP_AVAILABLE = True
except ImportError:
    TCP_AVAILABLE = False


class ShowsTab(BaseTab):
    """Timeline-based show management tab.

    Provides a visual timeline interface for managing show structure,
    audio tracks, and light effect lanes with full playback support.
    """

    def __init__(self, config: Configuration, parent=None):
        """Initialize shows tab.

        Args:
            config: Shared Configuration object
            parent: Parent widget (typically MainWindow)
        """
        # Initialize state before super().__init__
        self.song_structure = None
        self.lane_widgets = []
        self.current_show_name = ""
        self.is_playing = False
        self.playhead_position = 0.0
        self._is_activating = False
        self._config_dirty = True

        # Audio components (lazy init)
        # Simple audio player (pygame-based) - preferred for performance
        self.simple_audio_player = None
        self.use_simple_audio = SIMPLE_AUDIO_AVAILABLE  # Use pygame if available
        # Legacy audio components (sounddevice-based) - fallback
        self.audio_engine = None
        self.audio_mixer = None
        self.playback_sync = None
        self.device_manager = None

        # ArtNet controller (lazy init)
        self.artnet_controller = None
        self.artnet_enabled = True  # Default to enabled

        # TCP server for Visualizer (lazy init)
        self.tcp_server = None
        self.tcp_enabled = True  # Default to enabled

        # Playback timer
        self.playback_timer = QTimer()
        self.playback_timer.setInterval(16)  # ~60 FPS
        self.playback_timer.timeout.connect(self._update_playback)

        # Visual update throttling - reduce UI repaint frequency during playback
        # ArtNet updates happen every frame, but visual playhead updates are throttled
        self._visual_update_counter = 0
        self._visual_update_interval = 2  # Update visuals every 2 frames (~30 FPS)

        # Generation inspector
        self._generation_report = None
        self._inspector_window = None

        # Selection manager for multi-select
        self.selection_manager = SelectionManager()

        # Selection state for rubber-band
        self._is_selecting = False
        self._selection_start_global = QPoint()
        self._selection_extend = False
        self._selection_source_timeline = None
        self._selection_overlay = None
        # Tracks which button initiated the marquee. Right-button finalisation
        # shows a context menu with bulk-delete; left-button just selects.
        self._selection_button = Qt.MouseButton.LeftButton
        # For right-button marquee: defer overlay start until drag threshold met,
        # so a plain right-click still falls through to the native context menu.
        self._right_press_pending = False
        self._right_press_pos = QPoint()
        self._right_press_timeline = None
        self._suppress_next_context_menu = False
        self._marquee_drag_threshold_px = 6

        super().__init__(config, parent)

    def setup_ui(self):
        """Set up the timeline-based UI."""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(8)

        # Top toolbar
        toolbar = self._create_toolbar()
        main_layout.addLayout(toolbar)

        # Master + audio + light lanes share a single horizontal scrollbar
        # and a single column boundary inside TimelineGrid. We still keep
        # references to the lane widgets themselves so signals/methods on
        # them keep working — TimelineGrid just owns their visual layout.
        self.master_timeline = MasterTimelineContainer()
        self.audio_lane = AudioLaneWidget()
        self.timeline_grid = TimelineGrid()
        self.timeline_grid.set_master(self.master_timeline)
        self.timeline_grid.set_audio_lane(self.audio_lane)

        # Right-side embedded 3D preview. While playback is running and
        # the ArtNet controller is wired up, the preview mirrors the show
        # via the local_dmx_callback path (no TCP/ArtNet round-trip).
        # When stopped, it falls back to build mode so the user always
        # sees their fixtures lit. The standalone visualizer subprocess
        # keeps working unchanged for QLC+ interop.
        self.embedded_visualizer = EmbeddedVisualizer(self)
        self.embedded_visualizer.set_pop_out_callback(self._launch_visualizer)
        self.embedded_visualizer.set_config(self.config)
        self.embedded_visualizer.set_preview_mode("build")

        # Inline riff browser under the visualizer. Reuses the shared
        # RiffLibrary instance from MainWindow so we don't double-load
        # the disk catalog. The global QDockWidget version stays for the
        # Structure tab; gui.py hides it on the Shows tab so the user
        # doesn't see two copies.
        riff_library = self._get_shared_riff_library()
        self.embedded_riff_panel = RiffBrowserPanel(riff_library, self)

        # Right pane: visualizer (~16:9 top) + riff panel (fills below).
        right_splitter = QSplitter(Qt.Orientation.Vertical)
        right_splitter.addWidget(self.embedded_visualizer)
        right_splitter.addWidget(self.embedded_riff_panel)
        right_splitter.setStretchFactor(0, 0)
        right_splitter.setStretchFactor(1, 1)
        right_splitter.setCollapsible(0, True)
        right_splitter.setCollapsible(1, True)
        self._right_splitter = right_splitter

        # Outer splitter: timeline (left) | right pane. Collapsible so
        # the user can drag the right pane shut for full timeline width.
        # Sizes persist via QSettings under `shows/main_splitter` and
        # `shows/right_splitter`.
        self._main_splitter = QSplitter(Qt.Orientation.Horizontal)
        self._main_splitter.addWidget(self.timeline_grid)
        self._main_splitter.addWidget(right_splitter)
        self._main_splitter.setStretchFactor(0, 1)
        self._main_splitter.setStretchFactor(1, 0)
        self._main_splitter.setCollapsible(0, False)
        self._main_splitter.setCollapsible(1, True)
        self._restore_splitter_states()
        self._main_splitter.splitterMoved.connect(self._save_main_splitter_state)
        right_splitter.splitterMoved.connect(self._save_right_splitter_state)
        main_layout.addWidget(self._main_splitter, 1)

        # Create selection overlay for rubber-band selection (parented to self for proper stacking)
        self._selection_overlay = SelectionOverlay(self)
        self._selection_overlay.hide()

        # Bottom playback controls
        playback_bar = self._create_playback_controls()
        main_layout.addLayout(playback_bar)

    def _create_toolbar(self):
        """Create the top toolbar with show selection and lane controls."""
        toolbar = QHBoxLayout()
        toolbar.setSpacing(10)

        # Show selection
        show_label = QLabel("Show:")
        show_label.setStyleSheet("font-weight: bold;")
        toolbar.addWidget(show_label)

        self.show_combo = QComboBox()
        self.show_combo.setMinimumWidth(150)
        toolbar.addWidget(self.show_combo)

        toolbar.addSpacing(20)

        # Add lane button
        self.add_lane_btn = QPushButton("+ Add Light Lane")
        self.add_lane_btn.setProperty("role", "success")
        toolbar.addWidget(self.add_lane_btn)

        toolbar.addSpacing(10)

        # Auto-generate button
        self.autogen_btn = QPushButton("Auto-Generate")
        self.autogen_btn.setProperty("role", "primary")
        self.autogen_btn.setToolTip("Automatically generate light show from audio analysis")
        toolbar.addWidget(self.autogen_btn)

        # Inspector toggle (checkable — uses default theme :checked styling)
        self.inspector_btn = QPushButton("Inspector")
        self.inspector_btn.setCheckable(True)
        self.inspector_btn.setEnabled(False)
        self.inspector_btn.setToolTip("Show generation decision inspector (requires auto-generated show)")
        toolbar.addWidget(self.inspector_btn)

        toolbar.addSpacing(20)

        # Zoom control
        zoom_label = QLabel("Zoom:")
        toolbar.addWidget(zoom_label)

        self.zoom_slider = QSlider(Qt.Orientation.Horizontal)
        self.zoom_slider.setRange(10, 500)  # 0.1x to 5.0x
        self.zoom_slider.setValue(100)  # 1.0x default
        self.zoom_slider.setFixedWidth(120)
        toolbar.addWidget(self.zoom_slider)

        self.zoom_label = QLabel("1.0x")
        self.zoom_label.setFixedWidth(40)
        toolbar.addWidget(self.zoom_label)

        toolbar.addStretch()

        # Save button
        self.save_btn = QPushButton("Save")
        self.save_btn.setProperty("role", "primary")
        toolbar.addWidget(self.save_btn)

        return toolbar

    def _create_playback_controls(self):
        """Create bottom playback control bar."""
        controls = QHBoxLayout()
        controls.setSpacing(10)

        # Playback buttons (transport — colors from active theme via role props).
        self.play_btn = QPushButton("Play")
        self.play_btn.setFixedWidth(70)
        self.play_btn.setProperty("role", "success")
        controls.addWidget(self.play_btn)

        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setFixedWidth(70)
        self.stop_btn.setProperty("role", "destructive")
        controls.addWidget(self.stop_btn)

        controls.addSpacing(20)

        # Time display — styled by `#TimeReadout` rule in the active theme.
        self.time_label = QLabel("00:00.00")
        self.time_label.setObjectName("TimeReadout")
        self.time_label.setFixedWidth(100)
        controls.addWidget(self.time_label)

        controls.addSpacing(10)

        # Position slider
        self.position_slider = QSlider(Qt.Orientation.Horizontal)
        self.position_slider.setRange(0, 1000)
        self.position_slider.setValue(0)
        controls.addWidget(self.position_slider, 1)

        # Total time display
        self.total_time_label = QLabel("/ 00:00")
        self.total_time_label.setObjectName("TimeReadoutSecondary")
        controls.addWidget(self.total_time_label)

        return controls

    def connect_signals(self):
        """Connect widget signals to handlers."""
        # Toolbar
        self.show_combo.currentTextChanged.connect(self._on_show_changed)
        self.add_lane_btn.clicked.connect(self._add_new_lane)
        self.autogen_btn.clicked.connect(self._on_autogenerate)
        self.inspector_btn.toggled.connect(self._on_inspector_toggled)
        self.zoom_slider.valueChanged.connect(self._on_zoom_changed)
        self.save_btn.clicked.connect(self.save_to_config)

        # Playback controls
        self.play_btn.clicked.connect(self._toggle_playback)
        self.stop_btn.clicked.connect(self._stop_playback)
        self.position_slider.sliderPressed.connect(self._on_position_slider_pressed)
        self.position_slider.sliderReleased.connect(self._on_position_slider_released)
        self.position_slider.valueChanged.connect(self._on_position_slider_changed)

        # TimelineGrid is the single source of truth for playhead/zoom/audio
        # signals — its internals route from whichever lane originated the
        # change. No more cross-wiring between separate scroll areas.
        self.timeline_grid.playhead_moved.connect(self._on_playhead_moved)
        self.timeline_grid.zoom_changed.connect(self._on_external_zoom_changed)
        self.timeline_grid.audio_file_changed.connect(self._on_audio_file_loaded)

        # Keyboard shortcuts for selection operations
        self._setup_selection_shortcuts()

    def update_from_config(self):
        """Refresh timeline from configuration."""
        # Update show combo
        current = self.show_combo.currentText()
        self.show_combo.blockSignals(True)
        self.show_combo.clear()
        self.show_combo.addItems(sorted(self.config.shows.keys()))
        if current and current in self.config.shows:
            self.show_combo.setCurrentText(current)
        elif self.config.shows:
            self.show_combo.setCurrentIndex(0)
        self.show_combo.blockSignals(False)

        # Load current show
        self._load_show(self.show_combo.currentText())
        self._config_dirty = False

    def on_tab_activated(self):
        """Called when tab becomes visible. Only reload if config changed."""
        if self._is_activating:
            return
        try:
            self._is_activating = True
            if self._config_dirty:
                self._config_dirty = False
                self.update_from_config()
        finally:
            self._is_activating = False

    def mark_config_dirty(self):
        """Mark that config has changed externally and needs reload on next activation."""
        self._config_dirty = True

    def update_fixture_groups_only(self):
        """Lightweight update when only fixture groups changed.

        Updates lane group combos without recreating the entire timeline.
        Called by on_groups_changed for better performance.
        """
        fixture_groups = list(self.config.groups.keys())
        for lane_widget in self.lane_widgets:
            lane_widget.update_fixture_groups(fixture_groups)

        # Update ArtNet controller fixture mappings so new fixtures are tracked
        if self.artnet_controller:
            self.artnet_controller.update_fixtures()
        # Refresh the embedded visualizer's fixture set so newly-added /
        # removed fixtures appear (or vanish) in the 3D preview too.
        if hasattr(self, "embedded_visualizer") and self.embedded_visualizer:
            self.embedded_visualizer.set_config(self.config)

    def _on_show_changed(self, show_name: str):
        """Handle show selection change."""
        if self.current_show_name:
            self.save_to_config()
        self._load_show(show_name)
        if self.parent() and hasattr(self.parent(), 'on_show_selected'):
            self.parent().on_show_selected(show_name, 'shows')

    def _on_audio_file_loaded(self, file_path: str):
        """Handle audio file loaded.

        Copies the audio file to the local audiofiles/ folder if not already there,
        then updates the audio player with the local copy.
        """
        import shutil

        local_path = file_path
        basename = os.path.basename(file_path)

        # Copy to local audiofiles folder if shows_directory is set
        if self.config.shows_directory:
            audiofiles_dir = os.path.join(self.config.shows_directory, "audiofiles")
            local_path = os.path.join(audiofiles_dir, basename)

            # Check if file is already in the audiofiles folder
            if os.path.normpath(file_path) != os.path.normpath(local_path):
                # Create audiofiles directory if needed
                os.makedirs(audiofiles_dir, exist_ok=True)

                # Copy the file to local folder
                try:
                    if os.path.exists(file_path):
                        shutil.copy2(file_path, local_path)
                        print(f"Copied audio file to: {local_path}")

                        # Update the audio lane to use the local copy
                        self.audio_lane.audio_file_path = local_path
                        self.audio_lane.file_path_edit.setText(basename)
                        self.audio_lane.file_path_edit.setToolTip(local_path)
                except Exception as e:
                    print(f"Failed to copy audio file: {e}")
                    local_path = file_path  # Fall back to original

            # Update the show's timeline_data to store just the filename
            if self.current_show_name and self.current_show_name in self.config.shows:
                show = self.config.shows[self.current_show_name]
                if show.timeline_data:
                    show.timeline_data.audio_file_path = basename
                    print(f"Stored audio filename in show: {basename}")

        # Update simple audio player if it exists
        if self.simple_audio_player:
            try:
                self.simple_audio_player.load(local_path)
                print(f"SimpleAudioPlayer loaded: {basename}")
            except Exception as e:
                print(f"Failed to load audio in SimpleAudioPlayer: {e}")

        # Update the legacy audio mixer if it exists (engine already initialized)
        elif self.audio_mixer:
            audio_file = self.audio_lane.get_audio_file()
            if audio_file:
                # Remove old audio and add new one
                self.audio_mixer.remove_lane("audio")
                self.audio_mixer.add_lane("audio", audio_file, 1.0)
                print(f"Audio mixer updated with: {basename}")

    def _load_show(self, show_name: str):
        """Load show into timeline."""
        # Stop playback
        self._stop_playback()

        if not show_name or show_name not in self.config.shows:
            self._clear_timeline()
            return

        self.current_show_name = show_name
        show = self.config.shows[show_name]

        # Convert old effects if no timeline data
        if show.timeline_data is None and show.effects:
            self._convert_effects_to_timeline(show)

        # Build song structure from show parts
        self.song_structure = SongStructure()
        self.song_structure.load_from_show_parts(show.parts)

        # Set song structure on all timelines
        self.master_timeline.timeline_widget.set_song_structure(self.song_structure)
        self.audio_lane.set_song_structure(self.song_structure)

        # Update ArtNet controller with new song structure
        if self.artnet_controller:
            self.artnet_controller.set_song_structure(self.song_structure)

        # Update TCP server with new configuration
        if self.tcp_server and self.tcp_server.is_running():
            self.tcp_server.update_config(self.config)

        # Update total time display
        total_duration = self.song_structure.get_total_duration() if self.song_structure else 0
        self.total_time_label.setText(f"/ {self._format_time(total_duration)}")

        # Clear and rebuild light lanes. Drain deferred deletes from the
        # previous show's lane widgets BEFORE adding new ones - otherwise a
        # pending deleteLater can fire mid-rebuild and leave the layout
        # half-built with a phantom row from the old show.
        self._clear_light_lanes()
        QApplication.processEvents()

        if show.timeline_data:
            # Load audio file if available, or clear if not
            if show.timeline_data.audio_file_path:
                audio_filename = show.timeline_data.audio_file_path
                basename = os.path.basename(audio_filename)

                # Resolve via Configuration.audio_bundle_dir which tries
                # <config_dir>/audiofiles/ first, then falls back to
                # <shows_directory>/audiofiles/ for legacy configs. Same
                # helper the Structure tab uses, so audio resolution is
                # consistent across tabs.
                bundle_dir = self.config.audio_bundle_dir()
                local_audio_path = (
                    os.path.join(bundle_dir, basename)
                    if bundle_dir and basename else None
                )

                # Priority 1: bundle dir lookup
                if local_audio_path and os.path.exists(local_audio_path):
                    print(f"Using local audio file: {local_audio_path}")
                    self.audio_lane.load_audio_file(local_audio_path)
                    # Migrate old absolute paths to filename-only on first read.
                    if os.path.isabs(audio_filename):
                        show.timeline_data.audio_file_path = basename
                        print(f"Stored audio filename in show: {basename}")
                # Priority 2: legacy absolute path stored directly in YAML
                elif os.path.isabs(audio_filename) and os.path.exists(audio_filename):
                    print(f"Using audio file from original path: {audio_filename}")
                    self.audio_lane.load_audio_file(audio_filename)
                # Priority 3: not found anywhere
                else:
                    print(f"Audio file not found for '{audio_filename}' "
                          f"(bundle dir: {bundle_dir})")
                    self.audio_lane.clear_audio()
                    if self.audio_mixer:
                        self.audio_mixer.remove_lane("audio")
            else:
                # No audio for this show, clear it
                self.audio_lane.clear_audio()
                # Also clear the mixer
                if self.audio_mixer:
                    self.audio_mixer.remove_lane("audio")

            # Create lane widgets. Don't pump events inside this loop -
            # any pending deleteLater from _clear_light_lanes above would
            # fire mid-build and corrupt the layout.
            for lane_data in show.timeline_data.lanes:
                runtime_lane = LightLane.from_data_model(lane_data)
                self._add_lane_widget(runtime_lane)

            # Update ArtNet controller with loaded lanes
            if self.artnet_controller:
                self.artnet_controller.set_light_lanes(
                    [widget.lane for widget in self.lane_widgets]
                )
        else:
            # No timeline data, clear audio
            self.audio_lane.clear_audio()
            if self.audio_mixer:
                self.audio_mixer.remove_lane("audio")

    def _clear_timeline(self):
        """Clear all timeline data."""
        self.current_show_name = ""
        self.song_structure = None
        self._clear_light_lanes()
        self.master_timeline.timeline_widget.set_song_structure(None)
        self.audio_lane.set_song_structure(None)

    def _clear_light_lanes(self):
        """Remove all light lane widgets.

        Order matters: hide first to avoid the widget receiving paint
        events after we've disconnected its signals and removed it from
        the layout, setParent(None) to detach immediately (deleteLater
        alone is deferred and can leave a phantom widget visible until
        Qt processes the event queue), then deleteLater for the actual
        Python-side cleanup. This pattern fixed a native crash on Windows
        (STATUS_STACK_BUFFER_OVERRUN) where a paint event arriving for a
        deleted-but-still-visible widget tore through PyQt's binding.
        """
        for lane_widget in self.lane_widgets:
            try:
                lane_widget.remove_requested.disconnect()
                lane_widget.zoom_changed.disconnect()
                lane_widget.playhead_moved.disconnect()
                lane_widget.block_edited.disconnect()
            except (TypeError, RuntimeError):
                pass  # Signal already disconnected or widget deleted
            lane_widget.hide()
            self.timeline_grid.remove_light_lane(lane_widget)
            lane_widget.setParent(None)
            lane_widget.deleteLater()
        self.lane_widgets.clear()

    def _add_lane_widget(self, lane: LightLane):
        """Add a lane widget for the given lane data."""
        # Get fixture groups from config
        fixture_groups = list(self.config.groups.keys())

        lane_widget = LightLaneWidget(lane, fixture_groups, self, config=self.config)
        lane_widget.set_song_structure(self.song_structure)
        lane_widget.set_zoom_factor(self.zoom_slider.value() / 100.0)
        lane_widget.set_playhead_position(self.playhead_position)

        # Connect signals — TimelineGrid handles horizontal scroll sync, so
        # the per-lane scroll_position_changed wiring is gone.
        lane_widget.remove_requested.connect(self._remove_lane_widget)
        lane_widget.zoom_changed.connect(self._on_external_zoom_changed)
        lane_widget.playhead_moved.connect(self._on_playhead_moved)
        lane_widget.block_edited.connect(self.save_to_config)  # Auto-save on effect edit

        # Install event filter on timeline widget for rubber-band selection.
        lane_widget.timeline_widget.installEventFilter(self)
        lane_widget.timeline_widget.setMouseTracking(True)

        # Hand the lane's pieces over to the grid; this also re-parents header
        # and stripe and inserts a new aligned row.
        self.timeline_grid.add_light_lane(lane_widget)
        self.lane_widgets.append(lane_widget)

    def _add_new_lane(self):
        """Add a new empty light lane."""
        if not self.current_show_name:
            QMessageBox.warning(
                self,
                "No Show Selected",
                "Please select or create a show first before adding lanes.",
                QMessageBox.StandardButton.Ok
            )
            return

        # Show status indicator
        progress = get_progress_manager()
        if progress:
            progress.start_status("Creating lane...", 0)  # Indeterminate

        # Create new lane with default name (no default targets - user selects them)
        lane_num = len(self.lane_widgets) + 1

        lane = LightLane(f"Lane {lane_num}")
        self._add_lane_widget(lane)

        # Update ArtNet controller with the new lane list
        if self.artnet_controller:
            self.artnet_controller.set_light_lanes(
                [widget.lane for widget in self.lane_widgets]
            )

        if progress:
            progress.finish_status()

    def _on_autogenerate(self):
        """Open auto-generation dialog and generate show."""
        if not self.current_show_name:
            QMessageBox.warning(self, "No Show Selected",
                "Please select a show first.", QMessageBox.StandardButton.Ok)
            return

        show = self.config.shows.get(self.current_show_name)
        if not show or not show.parts:
            QMessageBox.warning(self, "No Song Structure",
                "The show has no song parts defined. Add parts in the Structure tab first.",
                QMessageBox.StandardButton.Ok)
            return

        # Get audio file path
        audio_path = self.audio_lane.get_audio_file_path() if hasattr(self, 'audio_lane') else None
        if not audio_path:
            QMessageBox.warning(self, "No Audio File",
                "Load an audio file first for analysis.",
                QMessageBox.StandardButton.Ok)
            return

        # Resolve audio path
        import os
        if not os.path.isabs(audio_path):
            shows_dir = self.config.shows_directory or "shows"
            audio_path = os.path.join(shows_dir, "audiofiles", audio_path)

        if not os.path.exists(audio_path):
            QMessageBox.warning(self, "Audio File Not Found",
                f"Cannot find audio file:\n{audio_path}",
                QMessageBox.StandardButton.Ok)
            return

        # Check for fixture groups
        if not self.config.groups:
            QMessageBox.warning(self, "No Fixture Groups",
                "Define fixture groups in the Fixtures tab first.",
                QMessageBox.StandardButton.Ok)
            return

        # Open config dialog
        from gui.dialogs.autogen_dialog import AutogenDialog, AutogenWorker
        dialog = AutogenDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        autogen_config = dialog.result_config
        key_signature = dialog.result_key_signature
        song_palette = dialog.result_palette

        # Build song structure
        song_structure = SongStructure()
        song_structure.load_from_show_parts(show.parts)

        # Disable button during generation
        self.autogen_btn.setEnabled(False)
        self.autogen_btn.setText("Generating...")

        # Run in background thread
        self._autogen_worker = AutogenWorker(
            audio_path, song_structure, self.config, autogen_config, key_signature,
            song_palette,
        )
        self._autogen_worker.finished.connect(self._on_autogen_finished)
        self._autogen_worker.error.connect(self._on_autogen_error)
        self._autogen_worker.start()

    def _on_autogen_finished(self, lanes, report=None):
        """Handle generated lanes from background worker."""
        self.autogen_btn.setEnabled(True)
        self.autogen_btn.setText("Auto-Generate")

        # Store generation report for inspector
        self._generation_report = report
        self.inspector_btn.setEnabled(report is not None)

        if not lanes:
            QMessageBox.information(self, "Auto-Generate",
                "No lanes were generated. Check fixture groups and song structure.",
                QMessageBox.StandardButton.Ok)
            return

        # Ask user whether to replace or append
        result = QMessageBox.question(
            self, "Auto-Generate Complete",
            f"Generated {len(lanes)} lanes with light blocks.\n\n"
            "Replace existing lanes or append to them?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel,
        )

        if result == QMessageBox.StandardButton.Cancel:
            return

        if result == QMessageBox.StandardButton.Yes:
            # Replace: remove all existing lanes
            for widget in list(self.lane_widgets):
                self._remove_lane_widget(widget)

        # Add generated lanes
        for lane_data in lanes:
            lane = LightLane(lane_data.name)
            lane.fixture_targets = lane_data.fixture_targets
            lane.light_blocks = lane_data.light_blocks
            self._add_lane_widget(lane)

        # Update ArtNet controller
        if self.artnet_controller:
            self.artnet_controller.set_light_lanes(
                [widget.lane for widget in self.lane_widgets]
            )

        # Save to config
        self.save_to_config()

        QMessageBox.information(self, "Auto-Generate",
            f"Successfully generated {len(lanes)} lanes.",
            QMessageBox.StandardButton.Ok)

    def _on_autogen_error(self, error_msg):
        """Handle auto-generation error."""
        self.autogen_btn.setEnabled(True)
        self.autogen_btn.setText("Auto-Generate")
        QMessageBox.critical(self, "Auto-Generate Error",
            f"Generation failed:\n{error_msg}",
            QMessageBox.StandardButton.Ok)

    def _on_inspector_toggled(self, checked):
        """Toggle the generation inspector window."""
        if checked and self._generation_report:
            from gui.dialogs.generation_inspector import GenerationInspector
            audio_path = self.audio_lane.get_audio_file_path() if hasattr(self, 'audio_lane') else ""
            if audio_path and not os.path.isabs(audio_path):
                shows_dir = self.config.shows_directory or "shows"
                audio_path = os.path.join(shows_dir, "audiofiles", audio_path)
            self._inspector_window = GenerationInspector(
                self._generation_report, audio_path=audio_path or "", parent=self
            )
            self._inspector_window.destroyed.connect(
                lambda: self.inspector_btn.setChecked(False)
            )
            self._inspector_window.show()
        elif self._inspector_window:
            self._inspector_window.close()
            self._inspector_window = None

    def _remove_lane_widget(self, lane_widget: LightLaneWidget):
        """Remove a lane widget."""
        if lane_widget in self.lane_widgets:
            lane_widget.remove_requested.disconnect()
            lane_widget.zoom_changed.disconnect()
            lane_widget.playhead_moved.disconnect()
            lane_widget.block_edited.disconnect()
            self.timeline_grid.remove_light_lane(lane_widget)
            self.lane_widgets.remove(lane_widget)
            lane_widget.deleteLater()

            # Update ArtNet controller with the updated lane list
            if self.artnet_controller:
                self.artnet_controller.set_light_lanes(
                    [widget.lane for widget in self.lane_widgets]
                )

    def _convert_effects_to_timeline(self, show: Show):
        """Convert old ShowEffect data to LightBlock timeline format."""
        if show.timeline_data is None:
            show.timeline_data = TimelineData()

        # Need song structure for timing
        song_structure = SongStructure()
        song_structure.load_from_show_parts(show.parts)

        # Create lane per fixture group
        groups_with_effects = set(e.fixture_group for e in show.effects if e.effect)
        for group_name in groups_with_effects:
            from config.models import LightLane as LightLaneModel
            lane = LightLaneModel(name=group_name, fixture_group=group_name)

            for effect in show.effects:
                if effect.fixture_group != group_name or not effect.effect:
                    continue

                # Find show part to get timing
                part = next((p for p in song_structure.parts if p.name == effect.show_part), None)
                if part:
                    block = LightBlock(
                        start_time=part.start_time,
                        duration=part.duration,
                        effect_name=effect.effect,
                        parameters={
                            'speed': effect.speed,
                            'color': effect.color,
                            'intensity': effect.intensity,
                            'spot': effect.spot
                        }
                    )
                    lane.light_blocks.append(block)

            if lane.light_blocks:
                show.timeline_data.lanes.append(lane)

    def save_to_config(self):
        """Save timeline state to configuration."""
        if not self.current_show_name or self.current_show_name not in self.config.shows:
            return

        show = self.config.shows[self.current_show_name]

        # Ensure timeline_data exists
        if show.timeline_data is None:
            show.timeline_data = TimelineData()

        # Save audio file path
        show.timeline_data.audio_file_path = self.audio_lane.get_audio_file_path()

        # Save lanes from widgets
        show.timeline_data.lanes = []
        for lane_widget in self.lane_widgets:
            lane_data = lane_widget.lane.to_data_model()
            show.timeline_data.lanes.append(lane_data)

    # === Zoom Synchronization (horizontal scroll is owned by TimelineGrid) ===

    def _on_zoom_changed(self, value: int):
        """Handle zoom slider change."""
        zoom_factor = value / 100.0
        self.zoom_label.setText(f"{zoom_factor:.1f}x")
        self._apply_zoom(zoom_factor)

    def _on_external_zoom_changed(self, zoom_factor: float):
        """Handle zoom change from a timeline widget."""
        self.zoom_slider.blockSignals(True)
        self.zoom_slider.setValue(int(zoom_factor * 100))
        self.zoom_slider.blockSignals(False)
        self.zoom_label.setText(f"{zoom_factor:.1f}x")
        self._apply_zoom(zoom_factor)

    def _apply_zoom(self, zoom_factor: float):
        """Apply zoom factor to all timeline widgets."""
        self.master_timeline.set_zoom_factor(zoom_factor)
        self.audio_lane.set_zoom_factor(zoom_factor)
        for lane in self.lane_widgets:
            lane.set_zoom_factor(zoom_factor)

    # === Playhead and Playback ===

    def _on_playhead_moved(self, position: float):
        """Handle playhead position change from timeline click."""
        self.playhead_position = position
        self._update_playhead_display(position)

        # Update all timelines
        self.master_timeline.set_playhead_position(position)
        self.audio_lane.set_playhead_position(position)
        for lane in self.lane_widgets:
            lane.set_playhead_position(position)

    def _update_playhead_display(self, position: float):
        """Update time display and position slider."""
        self.time_label.setText(self._format_time(position))

        if self.song_structure:
            total = self.song_structure.get_total_duration()
            if total > 0:
                slider_pos = int((position / total) * 1000)
                self.position_slider.blockSignals(True)
                self.position_slider.setValue(slider_pos)
                self.position_slider.blockSignals(False)

    def _format_time(self, seconds: float) -> str:
        """Format time as MM:SS.ss"""
        minutes = int(seconds // 60)
        secs = seconds % 60
        return f"{minutes:02d}:{secs:05.2f}"

    def _on_position_slider_pressed(self):
        """Handle position slider press - pause updates during drag."""
        self._slider_dragging = True

    def _on_position_slider_released(self):
        """Handle position slider release - seek to position."""
        self._slider_dragging = False
        if self.song_structure:
            total = self.song_structure.get_total_duration()
            position = (self.position_slider.value() / 1000.0) * total
            self._seek_to(position)

    def _on_position_slider_changed(self, value: int):
        """Handle position slider value change during drag."""
        if hasattr(self, '_slider_dragging') and self._slider_dragging:
            if self.song_structure:
                total = self.song_structure.get_total_duration()
                position = (value / 1000.0) * total
                self.time_label.setText(self._format_time(position))

    def _toggle_playback(self):
        """Toggle play/pause."""
        if self.is_playing:
            self._pause_playback()
        else:
            self._start_playback()

    def _start_playback(self):
        """Start playback."""
        if not self.song_structure:
            return

        self.is_playing = True
        self.play_btn.setText("Pause")

        # Reset visual update counter for consistent timing
        self._visual_update_counter = 0

        # Initialize audio if available
        audio_path = self.audio_lane.get_audio_file_path()
        if audio_path:
            self._init_audio_engine()

            # Try simple audio player first
            if self.simple_audio_player:
                try:
                    # Load file if not already loaded or different file
                    if not self.simple_audio_player.is_loaded():
                        self.simple_audio_player.load(audio_path)
                    self.simple_audio_player.play(self.playhead_position)
                except Exception as e:
                    print(f"SimpleAudioPlayer playback failed: {e}")

            # Fallback to sounddevice engine
            elif self.playback_sync:
                # Try to start audio playback - if it fails, fall back to timer-based
                if not self.playback_sync.on_play_requested(self.playhead_position):
                    print("Audio playback failed, falling back to timer-based playback")
                    # Clean up failed audio engine so it can be reinitialized
                    if self.audio_engine:
                        try:
                            self.audio_engine.cleanup()
                        except Exception:
                            pass
                        self.audio_engine = None
                    self.playback_sync = None

        # Initialize and start ArtNet if enabled
        if ARTNET_AVAILABLE and self.artnet_enabled:
            if self.artnet_controller is None:
                self._init_artnet_controller()
            if self.artnet_controller:
                # Set initial position before starting playback
                self.artnet_controller.update_position(self.playhead_position)
                self.artnet_controller.start_playback()

        # Switch the embedded preview to live so the show drives it via
        # local_dmx_callback. If ArtNet is off the callback never fires
        # and the preview stays on whatever was last shown.
        if hasattr(self, "embedded_visualizer") and self.embedded_visualizer:
            self.embedded_visualizer.set_preview_mode("live")

        self.playback_timer.start()

    def _pause_playback(self):
        """Pause playback."""
        self.is_playing = False
        self.play_btn.setText("Play")
        self.playback_timer.stop()

        # Pause audio (simple player or sounddevice engine)
        if self.simple_audio_player:
            self.simple_audio_player.pause()
        elif self.playback_sync:
            self.playback_sync.on_pause_requested()

        # Pause ArtNet output
        if self.artnet_controller:
            self.artnet_controller.pause_playback()

    def _stop_playback(self):
        """Stop playback and reset position."""
        self.is_playing = False
        self.play_btn.setText("Play")
        self.playback_timer.stop()

        # Stop audio (simple player or sounddevice engine)
        if self.simple_audio_player:
            self.simple_audio_player.stop()
        elif self.playback_sync:
            self.playback_sync.on_stop_requested()

        # Stop ArtNet output
        if self.artnet_controller:
            self.artnet_controller.stop_playback()

        # Drop the embedded preview back to build mode so every fixture
        # is visible again instead of frozen on the last live DMX frame.
        if hasattr(self, "embedded_visualizer") and self.embedded_visualizer:
            self.embedded_visualizer.set_preview_mode("build")

        self._seek_to(0.0)

    def _seek_to(self, position: float):
        """Seek to a specific position."""
        self.playhead_position = position
        self._on_playhead_moved(position)

        # Seek audio (simple player or sounddevice engine)
        if self.simple_audio_player:
            self.simple_audio_player.seek(position)
        elif self.playback_sync:
            self.playback_sync.on_seek_requested(position)

    def _get_current_position(self) -> float:
        """Get current playback position (sample-accurate if audio available).

        Used by ArtNet controller to get fresh position on each DMX update.

        Returns:
            Current position in seconds
        """
        if self.simple_audio_player and self.is_playing:
            return self.simple_audio_player.get_current_position()
        elif self.playback_sync and self.is_playing:
            return self.playback_sync.get_accurate_position()
        return self.playhead_position

    def _update_playback(self):
        """Called by timer during playback to update position."""
        if not self.is_playing or not self.song_structure:
            return

        # Get position from audio if available, otherwise use timer
        if self.simple_audio_player and self.simple_audio_player.is_playing():
            position = self.simple_audio_player.get_current_position()
        elif self.playback_sync:
            position = self.playback_sync.get_accurate_position()
        else:
            # Fallback: increment by timer interval
            position = self.playhead_position + 0.016  # 16ms

        total = self.song_structure.get_total_duration()
        if position >= total:
            self._stop_playback()
            return

        self.playhead_position = position

        # Update ArtNet controller position FIRST (high priority, every frame)
        if self.artnet_controller:
            self.artnet_controller.update_position(position)

        # Throttle visual updates to reduce UI repaint overhead
        self._visual_update_counter += 1
        if self._visual_update_counter >= self._visual_update_interval:
            self._visual_update_counter = 0

            # Update time display and slider
            self._update_playhead_display(position)

            # Update all timeline playheads
            self.master_timeline.set_playhead_position(position)
            self.audio_lane.set_playhead_position(position)
            for lane in self.lane_widgets:
                lane.set_playhead_position(position)

            # Update inspector dashboard
            if self._inspector_window and self._inspector_window.isVisible():
                self._inspector_window.update_position(position)

    def _init_audio_engine(self):
        """Initialize audio engine on first use.

        Prefers SimpleAudioPlayer (pygame) for better performance.
        Falls back to sounddevice-based engine if pygame not available.
        """
        # Try simple audio player first (pygame-based, much faster)
        if self.use_simple_audio and SIMPLE_AUDIO_AVAILABLE:
            if self.simple_audio_player is None:
                try:
                    self.simple_audio_player = SimpleAudioPlayer()

                    # Get buffer size from settings if available
                    buffer_size = 2048
                    if hasattr(self, 'audio_settings') and self.audio_settings:
                        buffer_size = self.audio_settings.get('buffer_size', 2048)

                    if not self.simple_audio_player.initialize(buffer_size=buffer_size):
                        raise Exception("pygame mixer initialization failed")

                    # Load audio file if available
                    audio_path = self.audio_lane.get_audio_file_path()
                    if audio_path:
                        self.simple_audio_player.load(audio_path)

                    # Connect volume slider to simple audio player
                    # Disconnect any previous connections first
                    try:
                        self.audio_lane.volume_slider.valueChanged.disconnect()
                    except TypeError:
                        pass  # No connections to disconnect
                    self.audio_lane.volume_slider.valueChanged.connect(
                        lambda v: self.simple_audio_player.set_volume(v / 100.0) if self.simple_audio_player else None
                    )
                    # Set initial volume
                    initial_volume = self.audio_lane.volume_slider.value() / 100.0
                    self.simple_audio_player.set_volume(initial_volume)

                    print("Using SimpleAudioPlayer (pygame) for audio playback")
                    return  # Success with simple player

                except Exception as e:
                    print(f"SimpleAudioPlayer failed: {e}, falling back to sounddevice engine")
                    self.simple_audio_player = None
                    self.use_simple_audio = False

        # Fallback to sounddevice-based engine
        if not AUDIO_AVAILABLE:
            return

        if self.audio_engine is None:
            try:
                self.device_manager = DeviceManager()
                self.audio_engine = AudioEngine()
                self.audio_mixer = AudioMixer()

                # Apply stored audio settings if available
                device_index = None
                if hasattr(self, 'audio_settings') and self.audio_settings:
                    device_index = self.audio_settings.get('device_index')
                    sample_rate = self.audio_settings.get('sample_rate', 44100)
                    buffer_size = self.audio_settings.get('buffer_size', 512)
                    self.audio_engine.sample_rate = sample_rate
                    self.audio_engine.buffer_size = buffer_size

                # Initialize audio engine with device
                if not self.audio_engine.initialize(device_index=device_index):
                    raise Exception("Audio device initialization failed")

                self.playback_sync = PlaybackSynchronizer(
                    self.audio_engine, self.audio_mixer
                )

                # Load audio file into mixer
                audio_file = self.audio_lane.get_audio_file()
                if audio_file:
                    self.audio_mixer.add_lane("audio", audio_file, 1.0)

                # Connect volume/mute
                self.audio_lane.volume_slider.valueChanged.connect(
                    lambda v: self.audio_mixer.update_lane_volume("audio", v / 100.0) if self.audio_mixer else None
                )
                self.audio_lane.mute_button.toggled.connect(
                    lambda m: self.audio_mixer.set_mute_state("audio", m) if self.audio_mixer else None
                )

                print("Using sounddevice for audio playback")

            except Exception as e:
                print(f"Failed to initialize audio engine: {e}")
                self.audio_engine = None
                self.playback_sync = None

    def apply_audio_settings(self, settings: dict):
        """Apply audio settings from settings dialog.

        Args:
            settings: Dict with device_index, sample_rate, buffer_size
        """
        self.audio_settings = settings

        # If audio engine exists, reinitialize with new settings
        if self.audio_engine:
            was_playing = self.is_playing
            if was_playing:
                self._pause_playback()

            # Cleanup and reinitialize
            try:
                self.audio_engine.cleanup()
            except Exception:
                pass

            self.audio_engine = None
            self.playback_sync = None

            # Reinitialize with new settings
            self._init_audio_engine()

            if was_playing:
                self._start_playback()

    def _init_artnet_controller(self):
        """Initialize ArtNet controller on first use."""
        if not ARTNET_AVAILABLE:
            return

        if self.artnet_controller is None:
            try:
                # Ensure universes exist for all fixtures (auto-create for visualizer if needed)
                self.config.ensure_universes_for_fixtures()

                # Load fixture definitions with full channel data
                models_in_config = {(f.manufacturer, f.model) for f in self.config.fixtures}
                fixture_defs = load_fixture_definitions_from_qlc(models_in_config)

                # Create controller. The local_dmx_callback feeds the
                # embedded visualizer in-process so the right-side preview
                # mirrors what's being broadcast over ArtNet — no TCP
                # round-trip. Wrap in a guard so a torn-down visualizer
                # doesn't blow up the DMX thread mid-show.
                def _feed_embedded(universe: int, dmx_bytes: bytes) -> None:
                    vis = getattr(self, "embedded_visualizer", None)
                    if vis is not None:
                        vis.feed_dmx(universe, dmx_bytes)

                self.artnet_controller = ShowsArtNetController(
                    config=self.config,
                    fixture_definitions=fixture_defs,
                    song_structure=self.song_structure,
                    target_ip="255.255.255.255",  # Broadcast
                    local_dmx_callback=_feed_embedded,
                )

                # Set light lanes
                self.artnet_controller.set_light_lanes(
                    [widget.lane for widget in self.lane_widgets]
                )

                # Set position callback for sample-accurate sync
                # This allows ArtNet to get fresh audio position on each DMX update
                self.artnet_controller.set_position_callback(self._get_current_position)

                # Enable output if checkbox is checked
                if self.artnet_enabled:
                    self.artnet_controller.enable_output()

                print("ArtNet controller initialized")

            except Exception as e:
                print(f"Failed to initialize ArtNet controller: {e}")
                import traceback
                traceback.print_exc()
                self.artnet_controller = None

    def toggle_artnet(self):
        """Toggle ArtNet output on/off. Called from MainWindow toolbar."""
        self._on_artnet_toggle(not self.artnet_enabled)

    def toggle_tcp(self):
        """Toggle TCP server on/off. Called from MainWindow toolbar."""
        self._on_tcp_toggle(not self.tcp_enabled)

    def _on_artnet_toggle(self, checked: bool):
        """Handle ArtNet toggle."""
        self.artnet_enabled = checked

        if checked:
            # Initialize and enable
            if self.artnet_controller is None:
                self._init_artnet_controller()
            elif self.artnet_controller:
                self.artnet_controller.enable_output()
                # Update song structure and lanes
                self.artnet_controller.set_song_structure(self.song_structure)
                self.artnet_controller.set_light_lanes(
                    [widget.lane for widget in self.lane_widgets]
                )
        else:
            # Disable
            if self.artnet_controller:
                self.artnet_controller.disable_output()

    def _init_tcp_server(self):
        """Initialize TCP server for Visualizer."""
        if not TCP_AVAILABLE:
            return

        if self.tcp_server is None:
            try:
                # Create server
                self.tcp_server = VisualizerTCPServer(
                    config=self.config,
                    port=9000  # Default port
                )

                # Connect signals
                self.tcp_server.client_connected.connect(self._on_tcp_client_connected)
                self.tcp_server.client_disconnected.connect(self._on_tcp_client_disconnected)
                self.tcp_server.error_occurred.connect(self._on_tcp_error)

                # Start server if enabled
                if self.tcp_enabled:
                    self.tcp_server.start()

                print("TCP server initialized")

            except Exception as e:
                print(f"Failed to initialize TCP server: {e}")
                import traceback
                traceback.print_exc()
                self.tcp_server = None

    def _on_tcp_toggle(self, checked: bool):
        """Handle TCP server toggle."""
        self.tcp_enabled = checked

        if checked:
            # Initialize and start
            if self.tcp_server is None:
                self._init_tcp_server()
            elif self.tcp_server and not self.tcp_server.is_running():
                self.tcp_server.start()
        else:
            # Stop server
            if self.tcp_server and self.tcp_server.is_running():
                self.tcp_server.stop()

    def _on_tcp_client_connected(self, client_addr: str):
        """Handle TCP client connection."""
        print(f"Visualizer connected: {client_addr}")

    def _on_tcp_client_disconnected(self, client_addr: str):
        """Handle TCP client disconnection."""
        print(f"Visualizer disconnected: {client_addr}")

    def _on_tcp_error(self, error_msg: str):
        """Handle TCP server error."""
        print(f"TCP server error: {error_msg}")

    # ── Embedded visualizer plumbing ──────────────────────────────────

    def _launch_visualizer(self):
        """Pop-out callback for the embedded visualizer. Launches the
        standalone visualizer subprocess via the existing Stage tab logic
        so QLC+ interop / TCP / ArtNet to the standalone view stays the
        same — we just delegate the heavy lifting."""
        main_window = self.window()
        stage_tab = getattr(main_window, "stage_tab", None) if main_window else None
        launcher = getattr(stage_tab, "_launch_visualizer", None) if stage_tab else None
        if callable(launcher):
            launcher()
            return
        # Fallback: minimal subprocess launch in case the Stage tab is
        # somehow unavailable. Mirrors stage_tab._launch_visualizer's core
        # behaviour without the user prompts.
        import subprocess
        import sys
        project_root = os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        )
        visualizer_path = os.path.join(project_root, "visualizer", "main.py")
        if os.path.exists(visualizer_path):
            subprocess.Popen([sys.executable, visualizer_path], cwd=project_root)

    def _get_shared_riff_library(self):
        """Return MainWindow's RiffLibrary instance (preferred) or build
        a local one. Sharing avoids re-scanning the riffs/ directory
        twice and keeps the embedded panel in sync with the global dock."""
        main_window = self.window()
        lib = getattr(main_window, "riff_library", None) if main_window else None
        if lib is not None:
            return lib
        # Fallback: stand-alone construction (mostly for tests / dev runs
        # that instantiate ShowsTab without a MainWindow).
        from riffs.riff_library import RiffLibrary
        return RiffLibrary()

    def _restore_splitter_states(self) -> None:
        """Restore both splitter sizes from QSettings.

        Defaults — main: timeline ~1000 / right pane ~520; right: vis
        ~290 / riff fills below. 520×290 is roughly 16:9 so the
        visualizer reads as a wide preview rather than a tall column.
        """
        from utils.app_settings import app_settings
        settings = app_settings()

        main_state = settings.value("shows/main_splitter")
        if main_state is not None:
            try:
                self._main_splitter.restoreState(main_state)
            except Exception:
                self._main_splitter.setSizes([1000, 520])
        else:
            self._main_splitter.setSizes([1000, 520])

        right_state = settings.value("shows/right_splitter")
        if right_state is not None:
            try:
                self._right_splitter.restoreState(right_state)
            except Exception:
                self._right_splitter.setSizes([290, 600])
        else:
            self._right_splitter.setSizes([290, 600])

    def _save_main_splitter_state(self, *_args) -> None:
        from utils.app_settings import app_settings
        settings = app_settings()
        settings.setValue("shows/main_splitter", self._main_splitter.saveState())

    def _save_right_splitter_state(self, *_args) -> None:
        from utils.app_settings import app_settings
        settings = app_settings()
        settings.setValue("shows/right_splitter", self._right_splitter.saveState())

    def cleanup(self):
        """Clean up audio and ArtNet resources."""
        self._stop_playback()

        # Clean up simple audio player
        if self.simple_audio_player:
            try:
                self.simple_audio_player.cleanup()
            except Exception:
                pass
            self.simple_audio_player = None

        # Clean up legacy audio engine
        if self.audio_engine:
            try:
                self.audio_engine.shutdown()
            except Exception:
                pass
            self.audio_engine = None
            self.audio_mixer = None
            self.playback_sync = None

        # Clean up ArtNet
        if self.artnet_controller:
            try:
                self.artnet_controller.cleanup()
            except Exception:
                pass
            self.artnet_controller = None

        # Clean up TCP server
        if self.tcp_server:
            try:
                self.tcp_server.stop()
            except Exception:
                pass
            self.tcp_server = None

        # Clean up embedded visualizer (stops its FPS timer; the GL
        # surface is destroyed via Qt's normal child teardown).
        if hasattr(self, "embedded_visualizer") and self.embedded_visualizer:
            try:
                self.embedded_visualizer.cleanup()
            except Exception:
                pass

        self.audio_lane.cleanup()

    def on_tab_deactivated(self):
        """Called when leaving the tab."""
        self._pause_playback()
        self.save_to_config()

    def import_show_structure(self):
        """Import show structures from CSV files in the shows directory.

        Expected CSV format:
        showpart,color,signature,bpm,num_bars,transition

        Creates Show objects with ShowPart data and adds them to configuration.
        """
        # Get project root (parent of gui directory)
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        shows_dir = os.path.join(project_root, "shows")

        # Check if shows directory exists
        if not os.path.exists(shows_dir):
            raise FileNotFoundError(f"Shows directory not found: {shows_dir}")

        # Count imported shows
        imported_count = 0

        # Scan for all show structure CSV files
        csv_files = [f for f in os.listdir(shows_dir) if f.endswith('.csv')]

        if not csv_files:
            raise FileNotFoundError(f"No CSV files found in {shows_dir}")

        for file in csv_files:
            show_name = os.path.splitext(file)[0]  # Remove .csv extension
            structure_file = os.path.join(shows_dir, file)

            # Check if show already exists in configuration
            if show_name in self.config.shows:
                show = self.config.shows[show_name]
                # Clear existing parts to reload from CSV
                show.parts.clear()
            else:
                # Create new Show object with timeline data
                show = Show(
                    name=show_name,
                    parts=[],
                    effects=[],
                    timeline_data=TimelineData()
                )
                self.config.shows[show_name] = show

            # Read CSV and create show parts
            with open(structure_file, 'r') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    # Create ShowPart from CSV row
                    show_part = ShowPart(
                        name=row['showpart'],
                        color=row['color'],
                        signature=row['signature'],
                        bpm=float(row['bpm']),
                        num_bars=int(row['num_bars']),
                        transition=row['transition']
                    )
                    # Add part to show
                    show.parts.append(show_part)

                    # Create empty effects for each fixture group
                    for group_name in self.config.groups.keys():
                        # Check if an effect already exists for this show part and group
                        existing_effect = None
                        for effect in show.effects:
                            if (effect.show_part == show_part.name and
                                    effect.fixture_group == group_name):
                                existing_effect = effect
                                break

                        # Only create new effect if none exists
                        if existing_effect is None:
                            effect = ShowEffect(
                                show_part=show_part.name,
                                fixture_group=group_name,
                                effect="",
                                speed="1",
                                color="",
                                intensity=200,
                                spot=""
                            )
                            show.effects.append(effect)

            imported_count += 1

        # Update show combo box with newly imported shows
        self.show_combo.blockSignals(True)
        self.show_combo.clear()
        self.show_combo.addItems(sorted(self.config.shows.keys()))
        if self.config.shows:
            self.show_combo.setCurrentIndex(0)
        self.show_combo.blockSignals(False)

        # Load the first show if available
        if self.show_combo.currentText():
            self._load_show(self.show_combo.currentText())

        print(f"Successfully imported {imported_count} show(s) from {shows_dir}")

    # === Selection/Rubber-Band Methods ===

    def _setup_selection_shortcuts(self):
        """Set up keyboard shortcuts for selection operations."""
        # Ctrl+C - Copy selected blocks
        copy_shortcut = QShortcut(QKeySequence.StandardKey.Copy, self)
        copy_shortcut.activated.connect(self._copy_selected_blocks)

        # Ctrl+V - Paste at playhead
        paste_shortcut = QShortcut(QKeySequence.StandardKey.Paste, self)
        paste_shortcut.activated.connect(self._paste_at_playhead)

        # Delete - Delete selected blocks
        delete_shortcut = QShortcut(QKeySequence.StandardKey.Delete, self)
        delete_shortcut.activated.connect(self._delete_selected_blocks)

        # Backspace - Also delete selected blocks
        backspace_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Backspace), self)
        backspace_shortcut.activated.connect(self._delete_selected_blocks)

        # Escape - Clear selection
        escape_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        escape_shortcut.activated.connect(self._clear_selection)

        # Ctrl+A - Select all blocks
        select_all_shortcut = QShortcut(QKeySequence.StandardKey.SelectAll, self)
        select_all_shortcut.activated.connect(self._select_all_blocks)

    def eventFilter(self, obj, event):
        """Filter events for rubber-band selection on timeline widgets."""
        from PyQt6.QtCore import QEvent
        from timeline_ui import TimelineWidget

        # Find which lane this widget belongs to (could be timeline widget or viewport)
        source_lane = None
        timeline_widget = None

        for lane_widget in self.lane_widgets:
            if lane_widget.timeline_widget is obj:
                source_lane = lane_widget
                timeline_widget = obj
                break
            # NOTE: pre-TimelineGrid (refactor 985b2fb, 2026-05-07) the lane
            # widget owned its own QScrollArea (`timeline_scroll`) and the
            # mouse/click events came in via its viewport. After the
            # TimelineGrid refactor, `detach_pieces()` nulls `timeline_scroll`
            # because the timeline_widget is now hosted directly by the
            # grid's shared scroll area. Accessing `.viewport()` on None was
            # the source of a native STATUS_STACK_BUFFER_OVERRUN crash on
            # show switch: Qt dispatches mouse/paint events to this filter,
            # the filter hits None.viewport(), and PyQt6 escalates the
            # AttributeError into a native fatal on Windows. Guard against
            # the None case to preserve any legacy detached lanes from
            # breaking, but the branch should be a no-op now.
            scroll = getattr(lane_widget, "timeline_scroll", None)
            if scroll is not None and scroll.viewport() is obj:
                source_lane = lane_widget
                timeline_widget = lane_widget.timeline_widget
                break

        if source_lane is None:
            return super().eventFilter(obj, event)

        if event.type() == QEvent.Type.MouseButtonPress:
            if event.button() == Qt.MouseButton.LeftButton:
                pos = event.position().toPoint()
                if obj is not timeline_widget:
                    pos = timeline_widget.mapFrom(obj, pos)
                if self._is_click_on_empty_space_in_timeline(timeline_widget, pos):
                    self._selection_button = Qt.MouseButton.LeftButton
                    self._start_rubber_band_selection(timeline_widget, pos, event)
                    return True  # Consume to prevent playhead movement
            elif event.button() == Qt.MouseButton.RightButton:
                pos = event.position().toPoint()
                if obj is not timeline_widget:
                    pos = timeline_widget.mapFrom(obj, pos)
                # Defer marquee start — a plain right-click should still open
                # the native Paste context menu. Track the press; activate only
                # if the user actually drags.
                if self._is_click_on_empty_space_in_timeline(timeline_widget, pos):
                    self._right_press_pending = True
                    self._right_press_pos = pos
                    self._right_press_timeline = timeline_widget
                # Don't consume — let contextMenuEvent fire later if no drag.

        elif event.type() == QEvent.Type.MouseMove:
            # Right-button drag: lazily start the marquee once threshold is met.
            if self._right_press_pending and (event.buttons() & Qt.MouseButton.RightButton):
                pos = event.position().toPoint()
                if obj is not self._right_press_timeline:
                    pos = self._right_press_timeline.mapFromGlobal(obj.mapToGlobal(pos))
                if (pos - self._right_press_pos).manhattanLength() >= self._marquee_drag_threshold_px:
                    self._right_press_pending = False
                    self._selection_button = Qt.MouseButton.RightButton
                    self._start_rubber_band_selection(
                        self._right_press_timeline, self._right_press_pos, event
                    )
                    self._update_rubber_band_selection(self._selection_source_timeline, pos)
                    return True

            if self._is_selecting:
                pos = event.position().toPoint()
                if obj is not self._selection_source_timeline:
                    pos = self._selection_source_timeline.mapFromGlobal(obj.mapToGlobal(pos))
                self._update_rubber_band_selection(self._selection_source_timeline, pos)
                return True

        elif event.type() == QEvent.Type.MouseButtonRelease:
            if event.button() == Qt.MouseButton.LeftButton and self._is_selecting:
                self._finish_rubber_band_selection(event)
                return True
            if event.button() == Qt.MouseButton.RightButton:
                if self._is_selecting and self._selection_button == Qt.MouseButton.RightButton:
                    # Drag-marquee was active. Finalise and show bulk-delete menu.
                    self._finish_rubber_band_selection(event)
                    self._suppress_next_context_menu = True
                    self._show_marquee_context_menu(event.globalPosition().toPoint())
                    return True
                # No drag occurred — clear the pending state and let the
                # native Paste contextMenuEvent fire normally.
                self._right_press_pending = False

        elif event.type() == QEvent.Type.ContextMenu:
            if self._suppress_next_context_menu:
                self._suppress_next_context_menu = False
                return True

        return super().eventFilter(obj, event)

    def _is_click_on_empty_space_in_timeline(self, timeline_widget, pos: QPoint) -> bool:
        """Check if a click position in a timeline widget is on empty space.

        Args:
            timeline_widget: The TimelineWidget being clicked
            pos: Position relative to timeline_widget

        Returns:
            True if clicking on empty space (not on a block)
        """
        # Find the lane widget for this timeline
        for lane_widget in self.lane_widgets:
            if lane_widget.timeline_widget is timeline_widget:
                # Check if position is on any block widget
                for block_widget in lane_widget.light_block_widgets:
                    # Map pos to block widget coordinates
                    block_pos = block_widget.mapFrom(timeline_widget, pos)
                    if block_widget.rect().contains(block_pos):
                        return False  # Clicked on a block
                return True  # Clicked on empty space in this lane

        return True  # Default to empty space

    def _start_rubber_band_selection(self, timeline_widget, pos: QPoint, event):
        """Start rubber-band selection.

        Args:
            timeline_widget: The timeline widget where selection started
            pos: Start position relative to timeline_widget
            event: The mouse event
        """
        # Check for Shift modifier to extend selection
        extend = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)

        if not extend:
            # Clear existing selection if not Shift+drag
            self.selection_manager.clear_selection()

        self._is_selecting = True
        self._selection_extend = extend
        self._selection_source_timeline = timeline_widget

        # Grab mouse to ensure we get all move/release events
        timeline_widget.grabMouse()

        # Store the global position for the selection start
        global_pos = timeline_widget.mapToGlobal(pos)
        self._selection_start_global = global_pos

        # Position the overlay over the timeline grid (covers stripes + headers).
        scroll_rect = self.timeline_grid.geometry()
        self._selection_overlay.setGeometry(scroll_rect)
        self._selection_overlay.show()
        self._selection_overlay.raise_()

        # Convert to overlay-relative coordinates
        overlay_pos = self._selection_overlay.mapFromGlobal(global_pos)
        self._selection_overlay.start_selection(overlay_pos)

    def _update_rubber_band_selection(self, timeline_widget, pos: QPoint):
        """Update rubber-band selection rectangle.

        Args:
            timeline_widget: The timeline widget receiving the mouse move
            pos: Current position relative to timeline_widget
        """
        if not self._is_selecting:
            return

        # Convert to global then to overlay coordinates
        global_pos = timeline_widget.mapToGlobal(pos)
        overlay_pos = self._selection_overlay.mapFromGlobal(global_pos)

        self._selection_overlay.update_selection(overlay_pos)

        # Highlight blocks that intersect with the selection
        self._highlight_blocks_in_selection()

    def _finish_rubber_band_selection(self, event):
        """Finish rubber-band selection.

        Args:
            event: The mouse event
        """
        if not self._is_selecting:
            return

        # Release mouse grab
        if self._selection_source_timeline:
            self._selection_source_timeline.releaseMouse()

        # Finalize selection
        self._selection_overlay.finish_selection()

        # Select all highlighted blocks
        self._finalize_selection()

        # Reset state
        self._is_selecting = False
        self._selection_overlay.hide()
        self._selection_source_timeline = None

    def _highlight_blocks_in_selection(self):
        """Highlight blocks that intersect with the current selection rectangle."""
        # Get selection rectangle in overlay coordinates
        rect = self._selection_overlay.get_selection_rect()

        # Convert rectangle corners to time values
        start_time, end_time = self._overlay_rect_to_time_range(rect)

        if start_time is None or end_time is None:
            return

        # For each lane, check if it intersects with the selection rectangle vertically
        for lane_widget in self.lane_widgets:
            # Get lane's position in overlay coordinates (use the lane widget itself, not just timeline)
            lane_rect = self._get_lane_rect_in_overlay(lane_widget)

            # Check Y overlap between selection rect and lane
            y_overlap = (rect.top() <= lane_rect.bottom() and
                        rect.bottom() >= lane_rect.top())

            if not y_overlap:
                # Lane doesn't intersect - remove highlight from its blocks
                for block in lane_widget.get_all_block_widgets():
                    if not self.selection_manager.is_selected(block):
                        block.set_multi_selected(False)
                continue

            # Get blocks in time range for this lane
            blocks_in_range = lane_widget.get_blocks_in_time_range(start_time, end_time)

            # Highlight matching blocks
            for block in blocks_in_range:
                block.set_multi_selected(True)

            # Remove highlight from blocks not in range (unless already selected)
            for block in lane_widget.get_all_block_widgets():
                if block not in blocks_in_range and not self.selection_manager.is_selected(block):
                    block.set_multi_selected(False)

    def _finalize_selection(self):
        """Finalize the selection by adding all highlighted blocks to selection manager."""
        # Get selection rectangle in overlay coordinates
        rect = self._selection_overlay.get_selection_rect()

        # Convert to time range
        start_time, end_time = self._overlay_rect_to_time_range(rect)

        if start_time is None or end_time is None:
            return

        blocks_to_select = []

        for lane_widget in self.lane_widgets:
            # Check Y overlap using the lane widget rect (not just timeline)
            lane_rect = self._get_lane_rect_in_overlay(lane_widget)

            y_overlap = (rect.top() <= lane_rect.bottom() and
                        rect.bottom() >= lane_rect.top())

            if not y_overlap:
                continue

            # Get blocks in time range
            blocks = lane_widget.get_blocks_in_time_range(start_time, end_time)
            blocks_to_select.extend(blocks)

        # Add to selection manager
        if blocks_to_select:
            self.selection_manager.select_multiple(blocks_to_select, self._selection_extend)

    def _get_timeline_rect_in_overlay(self, lane_widget) -> QRect:
        """Get a lane's timeline widget rectangle in overlay coordinates.

        Args:
            lane_widget: LightLaneWidget instance

        Returns:
            QRect of timeline widget in overlay coordinates
        """
        timeline = lane_widget.timeline_widget
        # Get timeline's global position
        global_top_left = timeline.mapToGlobal(QPoint(0, 0))
        global_bottom_right = timeline.mapToGlobal(QPoint(timeline.width(), timeline.height()))

        # Convert to overlay coordinates
        overlay_top_left = self._selection_overlay.mapFromGlobal(global_top_left)
        overlay_bottom_right = self._selection_overlay.mapFromGlobal(global_bottom_right)

        return QRect(overlay_top_left, overlay_bottom_right)

    def _get_lane_rect_in_overlay(self, lane_widget) -> QRect:
        """Get a lane widget's rectangle in overlay coordinates.

        Inside TimelineGrid the LightLaneWidget itself is a hollow logical
        container — its visual geometry now lives on its timeline widget.
        Use the timeline widget's bounds for Y-overlap detection.
        """
        timeline = lane_widget.timeline_widget
        global_top_left = timeline.mapToGlobal(QPoint(0, 0))
        global_bottom_right = timeline.mapToGlobal(QPoint(timeline.width(), timeline.height()))

        overlay_top_left = self._selection_overlay.mapFromGlobal(global_top_left)
        overlay_bottom_right = self._selection_overlay.mapFromGlobal(global_bottom_right)

        return QRect(overlay_top_left, overlay_bottom_right)

    def _overlay_rect_to_time_range(self, rect: QRect):
        """Convert a rectangle in overlay coordinates to a time range.

        Args:
            rect: Rectangle in overlay coordinates

        Returns:
            Tuple of (start_time, end_time) or (None, None) if conversion fails
        """
        if not self.lane_widgets:
            return (None, None)

        # Use first lane's timeline widget for coordinate conversion
        lane_widget = self.lane_widgets[0]
        timeline = lane_widget.timeline_widget

        # Convert overlay rect corners to timeline coordinates
        overlay_left = QPoint(rect.left(), rect.top())
        overlay_right = QPoint(rect.right(), rect.top())

        global_left = self._selection_overlay.mapToGlobal(overlay_left)
        global_right = self._selection_overlay.mapToGlobal(overlay_right)

        timeline_left = timeline.mapFromGlobal(global_left)
        timeline_right = timeline.mapFromGlobal(global_right)

        # Convert pixel positions to time
        x_start = timeline_left.x()
        x_end = timeline_right.x()

        # Clamp to valid range
        x_start = max(0, x_start)
        x_end = max(0, x_end)

        # Ensure start < end
        if x_start > x_end:
            x_start, x_end = x_end, x_start

        # Convert pixels to time using timeline's conversion method
        start_time = timeline.pixel_to_time(x_start)
        end_time = timeline.pixel_to_time(x_end)

        return (start_time, end_time)

    def _copy_selected_blocks(self):
        """Copy selected blocks to clipboard."""
        selected = self.selection_manager.get_selected_blocks()
        if selected:
            copy_multiple_effects(selected)
            print(f"Copied {len(selected)} block(s) to clipboard")

    def _paste_at_playhead(self):
        """Paste clipboard blocks at playhead position."""
        if has_multi_clipboard_data():
            # Paste multiple blocks
            results = paste_multiple_effects(self.playhead_position, self.lane_widgets)
            for lane_widget, new_block in results:
                # Add to lane data
                lane_widget.lane.light_blocks.append(new_block)
                # Create widget
                lane_widget.create_light_block_widget(new_block)

            if results:
                print(f"Pasted {len(results)} block(s)")
                self.save_to_config()

        elif has_clipboard_data():
            # Paste single block - use first lane or currently focused lane
            if self.lane_widgets:
                target_lane = self.lane_widgets[0]
                new_block = paste_effect(self.playhead_position)
                if new_block:
                    target_lane.lane.light_blocks.append(new_block)
                    target_lane.create_light_block_widget(new_block)
                    print("Pasted 1 block")
                    self.save_to_config()

    def _show_marquee_context_menu(self, global_pos: QPoint):
        """Show the bulk-action menu after a right-button marquee finalises.

        Currently offers delete-N for the marquee selection. Cancel just clears.
        """
        from PyQt6.QtWidgets import QMenu

        selected = self.selection_manager.get_selected_blocks()
        count = len(selected)

        menu = QMenu(self)
        if count == 0:
            empty = menu.addAction("No effects in selection")
            empty.setEnabled(False)
        else:
            label = "Delete Effect" if count == 1 else f"Delete {count} Effects"
            delete = menu.addAction(label)
            delete.triggered.connect(self._delete_selected_blocks)
            menu.addSeparator()
            cancel = menu.addAction("Cancel")
            cancel.triggered.connect(self.selection_manager.clear_selection)
        menu.exec(global_pos)

    def _delete_selected_blocks(self):
        """Delete all selected blocks."""
        selected = self.selection_manager.get_selected_blocks()
        if not selected:
            return

        count = len(selected)

        for block_widget in selected:
            # Find the lane widget this block belongs to
            lane_widget = block_widget.lane_widget
            if lane_widget:
                # Remove from selection first
                self.selection_manager.remove_block(block_widget)
                # Remove the block (without using undo to avoid issues)
                lane_widget.remove_light_block_widget(block_widget, use_undo=False)

        print(f"Deleted {count} block(s)")
        self.save_to_config()

    def _clear_selection(self):
        """Clear all selection."""
        self.selection_manager.clear_selection()

        # Also cancel any in-progress rubber-band
        if self._is_selecting:
            # Release mouse grab
            if self._selection_source_timeline:
                self._selection_source_timeline.releaseMouse()
            self._is_selecting = False
            self._selection_source_timeline = None
            self._selection_overlay.cancel_selection()
            self._selection_overlay.hide()

    def _select_all_blocks(self):
        """Select all blocks in all lanes."""
        all_blocks = []
        for lane_widget in self.lane_widgets:
            all_blocks.extend(lane_widget.get_all_block_widgets())

        if all_blocks:
            self.selection_manager.select_multiple(all_blocks, extend=False)
            print(f"Selected {len(all_blocks)} block(s)")
