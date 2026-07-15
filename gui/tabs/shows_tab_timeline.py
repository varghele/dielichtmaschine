# gui/tabs/shows_tab_timeline.py
# Timeline-based show editor tab

import os
from PyQt6 import QtWidgets, QtCore
from PyQt6.QtWidgets import (QVBoxLayout, QHBoxLayout, QWidget, QPushButton,
                             QComboBox, QLabel, QScrollArea, QCheckBox,
                             QMessageBox, QDialog)
from PyQt6.QtCore import Qt

from config.models import Configuration, Song, TimelineData, LightBlock
from config.models import LightLane as LightLaneModel
from .base_tab import BaseTab
from timeline.song_structure import SongStructure
from timeline.playback_engine import PlaybackEngine
from timeline.light_lane import LightLane
from timeline_ui.master_timeline_widget import MasterTimelineContainer
from timeline_ui.light_lane_widget import LightLaneWidget


class ShowsTabTimeline(BaseTab):
    """Timeline-based show editor tab.

    Provides a DAW-style timeline interface for programming light shows
    with lanes for different fixture groups and effect blocks.
    """

    def __init__(self, config: Configuration, parent=None):
        """Initialize shows tab.

        Args:
            config: Shared Configuration object
            parent: Parent widget (typically MainWindow)
        """
        self.effects_dir = "effects"
        self.project_root = os.getcwd()
        self.playback_engine = None
        self.song_structure = None
        self.lane_widgets = []
        self.lanes = []  # Runtime LightLane objects
        super().__init__(config, parent)

    def setup_ui(self):
        """Set up timeline interface."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)

        # Top toolbar
        toolbar = self.create_toolbar()
        layout.addWidget(toolbar)

        # Master timeline
        self.master_timeline = MasterTimelineContainer()
        self.master_timeline.playhead_moved.connect(self.on_playhead_moved)
        self.master_timeline.scroll_position_changed.connect(self.sync_lane_scrolls)
        self.master_timeline.zoom_changed.connect(self.on_zoom_changed)
        layout.addWidget(self.master_timeline)

        # Lanes container (scrollable)
        self.lanes_scroll = QScrollArea()
        self.lanes_widget = QWidget()
        self.lanes_layout = QVBoxLayout(self.lanes_widget)
        self.lanes_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.lanes_layout.setSpacing(5)
        self.lanes_layout.setContentsMargins(5, 5, 5, 5)
        self.lanes_layout.addStretch()  # Push lanes to top

        self.lanes_scroll.setWidget(self.lanes_widget)
        self.lanes_scroll.setWidgetResizable(True)
        self.lanes_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.lanes_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.lanes_scroll.setStyleSheet("""
            QScrollArea {
                background-color: #1e1e1e;
                border: 1px solid #333;
            }
        """)

        layout.addWidget(self.lanes_scroll, 1)

        # Initialize playback engine
        self.playback_engine = PlaybackEngine()
        self.playback_engine.position_changed.connect(self.on_playback_position_changed)
        self.playback_engine.playback_started.connect(self.on_playback_started)
        self.playback_engine.playback_stopped.connect(self.on_playback_stopped)
        self.playback_engine.playback_halted.connect(self.on_playback_halted)

    def create_toolbar(self):
        """Create top toolbar with controls."""
        toolbar = QWidget()
        toolbar.setStyleSheet("background-color: #2d2d2d; border-radius: 4px;")
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(10, 5, 10, 5)

        # Show selector
        show_label = QLabel("Show:")
        show_label.setStyleSheet("color: white; font-weight: bold;")
        toolbar_layout.addWidget(show_label)

        self.show_combo = QComboBox()
        self.show_combo.setMinimumWidth(200)
        self.show_combo.setStyleSheet("""
            QComboBox {
                background-color: #3d3d3d;
                color: white;
                border: 1px solid #555;
                border-radius: 3px;
                padding: 5px;
            }
        """)
        self.show_combo.currentTextChanged.connect(self.on_show_changed)
        toolbar_layout.addWidget(self.show_combo)

        toolbar_layout.addSpacing(20)

        # Playback controls
        self.play_btn = QPushButton("▶")
        self.play_btn.setFixedSize(40, 30)
        self.play_btn.clicked.connect(self.on_play_clicked)
        self.play_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                font-size: 16px;
                border: none;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #66BB6A;
            }
        """)
        toolbar_layout.addWidget(self.play_btn)

        self.halt_btn = QPushButton("❚❚")
        self.halt_btn.setFixedSize(40, 30)
        self.halt_btn.clicked.connect(self.on_halt_clicked)
        self.halt_btn.setStyleSheet("""
            QPushButton {
                background-color: #FF9800;
                color: white;
                font-size: 14px;
                border: none;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #FFB74D;
            }
        """)
        toolbar_layout.addWidget(self.halt_btn)

        self.stop_btn = QPushButton("⏹")
        self.stop_btn.setFixedSize(40, 30)
        self.stop_btn.clicked.connect(self.on_stop_clicked)
        self.stop_btn.setStyleSheet("""
            QPushButton {
                background-color: #f44336;
                color: white;
                font-size: 14px;
                border: none;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #EF5350;
            }
        """)
        toolbar_layout.addWidget(self.stop_btn)

        toolbar_layout.addSpacing(20)

        # Snap to grid
        self.snap_checkbox = QCheckBox("Snap to Grid")
        self.snap_checkbox.setChecked(True)
        self.snap_checkbox.setStyleSheet("color: white;")
        self.snap_checkbox.toggled.connect(self.on_snap_toggled)
        toolbar_layout.addWidget(self.snap_checkbox)

        toolbar_layout.addStretch()

        # Add lane button
        self.add_lane_btn = QPushButton("+ Add Lane")
        self.add_lane_btn.clicked.connect(self.show_add_lane_dialog)
        self.add_lane_btn.setStyleSheet("""
            QPushButton {
                background-color: #2196F3;
                color: white;
                font-weight: bold;
                border: none;
                border-radius: 4px;
                padding: 8px 15px;
            }
            QPushButton:hover {
                background-color: #42A5F5;
            }
        """)
        toolbar_layout.addWidget(self.add_lane_btn)

        return toolbar

    def connect_signals(self):
        """Connect widget signals to handlers."""
        pass  # Signals connected in setup_ui

    def update_from_config(self):
        """Refresh shows from configuration."""
        # Update show combo box
        current_show = self.show_combo.currentText()
        self.show_combo.blockSignals(True)
        self.show_combo.clear()
        self.show_combo.addItems(sorted(self.config.songs.keys()))

        # Restore selection if possible
        if current_show and current_show in self.config.songs:
            self.show_combo.setCurrentText(current_show)

        self.show_combo.blockSignals(False)

        # Update current show if one is selected
        if self.show_combo.currentText():
            self.on_show_changed(self.show_combo.currentText())

    def on_show_changed(self, show_name: str):
        """Load selected show into timeline."""
        if not show_name or show_name not in self.config.songs:
            return

        show = self.config.songs[show_name]

        # Create song structure from show parts
        self.song_structure = SongStructure()
        self.song_structure.load_from_show_parts(show.parts)

        # Set song structure on timeline widget
        self.master_timeline.timeline_widget.set_song_structure(self.song_structure)
        self.playback_engine.set_song_structure(self.song_structure)

        # Load or create timeline data
        if show.timeline_data is None:
            # Migrate from old ShowEffect format or create empty
            show.timeline_data = self.migrate_from_effects(show)

        # Clear existing lanes
        self.clear_lanes()

        # Create lane widgets from timeline data
        for lane_data in show.timeline_data.lanes:
            lane = LightLane.from_data_model(lane_data)
            self.add_lane_widget(lane)

        # Update playback engine
        self.playback_engine.set_lanes(self.lanes)

    def migrate_from_effects(self, show: Song) -> TimelineData:
        """Convert old ShowEffect format to timeline lanes.

        Creates one lane per fixture group with blocks at show part times.

        Args:
            show: Show to migrate

        Returns:
            New TimelineData
        """
        timeline_data = TimelineData()

        # Build song structure for timing
        temp_structure = SongStructure()
        temp_structure.load_from_show_parts(show.parts)

        # Group effects by fixture group
        effects_by_group = {}
        for effect in show.effects:
            if effect.fixture_group not in effects_by_group:
                effects_by_group[effect.fixture_group] = []
            effects_by_group[effect.fixture_group].append(effect)

        # Create one lane per fixture group
        for group_name, group_effects in effects_by_group.items():
            lane_model = LightLaneModel(
                name=f"{group_name}",
                fixture_group=group_name
            )

            # Convert each effect to a light block
            for effect in group_effects:
                # Find the corresponding show part
                part = next((p for p in temp_structure.parts
                            if p.name == effect.show_part), None)
                if part and effect.effect:  # Only create block if effect is set
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
                    lane_model.light_blocks.append(block)

            timeline_data.lanes.append(lane_model)

        return timeline_data

    def clear_lanes(self):
        """Clear all lane widgets."""
        for widget in self.lane_widgets:
            self.lanes_layout.removeWidget(widget)
            widget.deleteLater()
        self.lane_widgets.clear()
        self.lanes.clear()

    def add_lane_widget(self, lane: LightLane):
        """Add a lane widget to the timeline.

        Args:
            lane: LightLane instance
        """
        # Get available fixture groups
        fixture_groups = list(self.config.groups.keys())

        # Create widget
        lane_widget = LightLaneWidget(lane, fixture_groups, self, config=self.config)
        lane_widget.remove_requested.connect(self.remove_lane)
        lane_widget.scroll_position_changed.connect(self.sync_master_scroll)
        lane_widget.zoom_changed.connect(self.sync_master_zoom)
        lane_widget.playhead_moved.connect(self.on_playhead_moved)

        # Set song structure
        if self.song_structure:
            lane_widget.set_song_structure(self.song_structure)

        self.lanes.append(lane)
        self.lane_widgets.append(lane_widget)

        # Insert before the stretch
        insert_index = self.lanes_layout.count() - 1
        self.lanes_layout.insertWidget(insert_index, lane_widget)

    def remove_lane(self, lane_widget):
        """Remove a lane widget.

        Args:
            lane_widget: LightLaneWidget to remove
        """
        if lane_widget.lane in self.lanes:
            self.lanes.remove(lane_widget.lane)
        if lane_widget in self.lane_widgets:
            self.lane_widgets.remove(lane_widget)
        self.lanes_layout.removeWidget(lane_widget)
        lane_widget.deleteLater()

        # Update playback engine
        self.playback_engine.set_lanes(self.lanes)

    def show_add_lane_dialog(self):
        """Show dialog to add a new lane."""
        # Get available fixture groups
        fixture_groups = list(self.config.groups.keys())

        if not fixture_groups:
            QMessageBox.warning(
                self, "No Groups",
                "No fixture groups available. Please create fixture groups first."
            )
            return

        # Simple dialog to select fixture group
        dialog = QDialog(self)
        dialog.setWindowTitle("Add Lane")
        dialog.setMinimumWidth(300)

        layout = QVBoxLayout(dialog)

        # Group selection
        group_layout = QHBoxLayout()
        group_layout.addWidget(QLabel("Fixture Group:"))
        group_combo = QComboBox()
        group_combo.addItems(fixture_groups)
        group_layout.addWidget(group_combo, 1)
        layout.addLayout(group_layout)

        # Buttons
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok |
            QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec() == QDialog.DialogCode.Accepted:
            group_name = group_combo.currentText()
            lane = LightLane(
                name=group_name,
                fixture_targets=[group_name] if group_name else []
            )
            self.add_lane_widget(lane)
            self.playback_engine.set_lanes(self.lanes)

    def save_to_config(self):
        """Save timeline data back to configuration."""
        current_show = self.show_combo.currentText()
        if not current_show or current_show not in self.config.songs:
            return

        show = self.config.songs[current_show]

        # Create new timeline data from current lanes
        timeline_data = TimelineData()
        for lane in self.lanes:
            timeline_data.lanes.append(lane.to_data_model())

        show.timeline_data = timeline_data

        # Also update legacy ShowEffect format for backwards compatibility
        self._update_legacy_effects(show)

    def _update_legacy_effects(self, show: Song):
        """Update legacy ShowEffect list from timeline data.

        Args:
            show: Show to update
        """
        from config.models import ShowEffect

        show.effects.clear()

        if not show.timeline_data or not self.song_structure:
            return

        for lane_model in show.timeline_data.lanes:
            for block in lane_model.light_blocks:
                # Find which show part this block falls into
                part = self.song_structure.get_part_at_time(block.start_time)
                if part and block.effect_name:
                    effect = ShowEffect(
                        show_part=part.name,
                        fixture_group=lane_model.fixture_group,
                        effect=block.effect_name,
                        speed=block.parameters.get('speed', '1'),
                        color=block.parameters.get('color', ''),
                        intensity=block.parameters.get('intensity', 200),
                        spot=block.parameters.get('spot', '')
                    )
                    show.effects.append(effect)

    # Playback controls
    def on_play_clicked(self):
        """Handle play button click."""
        self.playback_engine.play()

    def on_halt_clicked(self):
        """Handle halt/pause button click."""
        self.playback_engine.halt()

    def on_stop_clicked(self):
        """Handle stop button click."""
        self.playback_engine.stop()

    def on_playback_started(self):
        """Handle playback started."""
        self.play_btn.setText("⏸")

    def on_playback_halted(self):
        """Handle playback paused."""
        self.play_btn.setText("▶")

    def on_playback_stopped(self):
        """Handle playback stopped."""
        self.play_btn.setText("▶")

    def on_playback_position_changed(self, position: float):
        """Handle playback position change."""
        self.master_timeline.set_playhead_position(position)
        for lane_widget in self.lane_widgets:
            lane_widget.set_playhead_position(position)

    def on_playhead_moved(self, position: float):
        """Handle user moving playhead."""
        self.playback_engine.set_position(position)

    def on_snap_toggled(self, checked: bool):
        """Handle snap to grid toggle."""
        self.master_timeline.set_snap_to_grid(checked)
        for lane_widget in self.lane_widgets:
            lane_widget.snap_checkbox.setChecked(checked)

    def on_tab_activated(self):
        """Called when tab becomes visible. Refresh show list from config."""
        self.update_from_config()

    # Scroll/zoom synchronization
    def sync_lane_scrolls(self, position: int):
        """Sync scroll position across all lane timelines."""
        for lane_widget in self.lane_widgets:
            lane_widget.sync_scroll_position(position)

    def sync_master_scroll(self, position: int):
        """Sync master timeline scroll when lane is scrolled."""
        self.master_timeline.sync_scroll_position(position)

        # Sync all other lanes
        sender = self.sender()
        for lane_widget in self.lane_widgets:
            if lane_widget != sender:
                lane_widget.sync_scroll_position(position)

    def on_zoom_changed(self, zoom_factor: float):
        """Handle zoom change from master timeline."""
        for lane_widget in self.lane_widgets:
            lane_widget.set_zoom_factor(zoom_factor)

    def sync_master_zoom(self, zoom_factor: float):
        """Sync master timeline zoom when lane is zoomed."""
        self.master_timeline.set_zoom_factor(zoom_factor)

        # Sync all other lanes
        sender = self.sender()
        for lane_widget in self.lane_widgets:
            if lane_widget != sender:
                lane_widget.set_zoom_factor(zoom_factor)

    def import_show_structure(self):
        """Import show structure from CSV files.

        Called by main window when importing show structure.
        """
        # This delegates to the configuration import and then refreshes
        self.update_from_config()
