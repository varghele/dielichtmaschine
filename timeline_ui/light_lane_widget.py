# timeline_ui/light_lane_widget.py
# Light lane widget for displaying and editing light effect lanes
# Adapted from midimaker_and_show_structure/ui/lane_widget.py

from PyQt6.QtWidgets import (QWidget, QHBoxLayout, QVBoxLayout, QLabel,
                             QPushButton, QCheckBox, QLineEdit, QFrame,
                             QScrollArea, QComboBox, QMessageBox)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QUndoStack
from .timeline_widget import TimelineWidget
from .light_block_widget import LightBlockWidget
from .undo_commands import InsertRiffCommand, DeleteBlockCommand, AddBlockCommand
from timeline.light_lane import LightLane


class LightLaneWidget(QFrame):
    """Widget for displaying and editing a light lane.

    Shows lane controls on the left (name, fixture group, mute/solo)
    and a scrollable timeline with effect blocks on the right.
    """

    remove_requested = pyqtSignal(object)  # Emits self when remove requested
    scroll_position_changed = pyqtSignal(int)  # Emits horizontal scroll position
    zoom_changed = pyqtSignal(float)  # Emits zoom factor
    playhead_moved = pyqtSignal(float)  # Emits playhead position
    block_edited = pyqtSignal()  # Emitted when any block is edited (for auto-save)

    def __init__(self, lane: LightLane, fixture_groups: list = None, parent=None, config=None):
        """Create a new light lane widget.

        Args:
            lane: LightLane instance to display
            fixture_groups: List of available fixture group names
            parent: Parent widget
            config: Configuration object (for capability detection)
        """
        super().__init__(parent)
        self.lane = lane
        self.fixture_groups = fixture_groups or []
        self.light_block_widgets = []
        self.main_window = parent
        self.config = config

        # Detect capabilities and calculate sublane layout
        self.capabilities = self._detect_group_capabilities()
        self.num_sublanes = self._count_sublanes()
        self.sublane_height = 50  # Height per sublane in pixels
        self.min_lane_height = 105  # Minimum height to accommodate control panel

        self.setFrameStyle(QFrame.Shape.Box)
        self.setLineWidth(1)

        # Dynamic height based on number of sublanes, with minimum for control panel
        # Add buffer for margins and padding
        buffer_height = 15  # Extra space for layout margins
        total_height = max(self.min_lane_height, self.num_sublanes * self.sublane_height + buffer_height)
        self.setMinimumHeight(total_height)
        self.setMaximumHeight(total_height)

        # Background tint from `LightLaneWidget` selector in the active theme.

        self.setup_ui()

    def setup_ui(self):
        main_layout = QHBoxLayout(self)

        # Build the two pieces — controls on the left, timeline on the right.
        # When this widget is embedded in TimelineGrid, detach_pieces() tears
        # this layout down and hands both children over.
        self.controls_widget = self.create_controls_widget()
        main_layout.addWidget(self.controls_widget)
        self._apply_group_border()

        # Timeline section (right side) - scrollable
        self.timeline_scroll = QScrollArea()
        self.timeline_widget = TimelineWidget()

        # Configure sublanes
        self.timeline_widget.num_sublanes = self.num_sublanes
        self.timeline_widget.sublane_height = self.sublane_height
        self.timeline_widget.capabilities = self.capabilities
        # Timeline height should exactly fit sublanes (no buffer needed here)
        timeline_height = self.num_sublanes * self.sublane_height
        self.timeline_widget.setMinimumHeight(timeline_height)
        self.timeline_widget.setMaximumHeight(timeline_height)  # Prevent vertical growth

        self.timeline_widget.zoom_changed.connect(self.zoom_changed.emit)
        self.timeline_widget.zoom_changed.connect(self.on_timeline_zoom_changed)
        self.timeline_widget.playhead_moved.connect(self.playhead_moved.emit)
        self.timeline_widget.paste_requested.connect(self.paste_effect_at_time)
        self.timeline_widget.riff_dropped.connect(self.on_riff_dropped)

        # Create light block widgets for existing blocks
        for block in self.lane.light_blocks:
            self.create_light_block_widget(block)

        self.timeline_scroll.setWidget(self.timeline_widget)
        self.timeline_scroll.setWidgetResizable(False)
        self.timeline_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.timeline_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        # Connect scroll events
        self.timeline_scroll.horizontalScrollBar().valueChanged.connect(
            self.scroll_position_changed.emit)

        main_layout.addWidget(self.timeline_scroll, 1)

    def detach_pieces(self):
        """Return (header_widget, stripe_widget) for embedding in TimelineGrid.

        After this call ``self`` no longer renders its own UI — the inner
        scrollarea is gone and ``controls_widget`` / ``timeline_widget`` are
        free to be re-parented. The lane's logic (block widgets, signals,
        riff drop, paste, undo) keeps working because it lives on the
        timeline widget and on ``self`` itself.
        """
        if hasattr(self, "timeline_scroll") and self.timeline_scroll is not None:
            self.timeline_scroll.takeWidget()
            self.timeline_scroll.setParent(None)
            self.timeline_scroll = None
        return self.controls_widget, self.timeline_widget

    def create_controls_widget(self):
        """Create the lane controls section."""
        widget = QWidget()
        # Object-name + WA_StyledBackground so the theme's
        # `QWidget#LightLaneHeader` rule paints the bg after the
        # controls widget is detached and re-parented into TimelineGrid.
        widget.setObjectName("LightLaneHeader")
        widget.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        widget.setFixedWidth(320)

        # Outer layout: the control rows on the left, plus a slim
        # right-aligned column of sublane micro-labels (DIM / COL /
        # MOV / SPC) on the header's right edge (North Star lane
        # anatomy, slice T1). The column lists the active sublanes in
        # the same top-to-bottom order as the timeline stripe rows.
        outer = QHBoxLayout(widget)
        outer.setSpacing(6)

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        outer.addLayout(layout, 1)

        self.sublane_labels_widget = QWidget(widget)
        self.sublane_labels_widget.setObjectName("LaneSublaneLabels")
        self.sublane_labels_widget.setFixedWidth(34)
        self._sublane_labels_layout = QVBoxLayout(self.sublane_labels_widget)
        self._sublane_labels_layout.setContentsMargins(0, 0, 0, 0)
        self._sublane_labels_layout.setSpacing(0)
        outer.addWidget(self.sublane_labels_widget)
        self.sublane_labels = []
        self.refresh_sublane_labels()

        # Row 1: Name and remove button — visuals from active theme.
        name_layout = QHBoxLayout()

        name_label = QLabel("Name:")
        name_label.setStyleSheet("font-weight: bold; font-size: 12px;")
        name_layout.addWidget(name_label)

        self.name_edit = QLineEdit(self.lane.name)
        self.name_edit.textChanged.connect(self.on_name_changed)
        name_layout.addWidget(self.name_edit)

        self.remove_button = QPushButton("×")
        self.remove_button.setFixedSize(25, 25)
        # density=compact gives tight padding so "×" fits in 25×25; role
        # still drives the destructive color. Two independent property axes.
        # ("size" would collide with Qt's QSize Q_PROPERTY — don't use it.)
        self.remove_button.setProperty("density", "compact")
        self.remove_button.setProperty("role", "destructive")
        self.remove_button.clicked.connect(lambda: self.remove_requested.emit(self))
        name_layout.addWidget(self.remove_button)

        layout.addLayout(name_layout)

        # Row 2: Fixture targets
        targets_layout = QHBoxLayout()

        targets_label = QLabel("Targets:")
        targets_label.setStyleSheet("font-weight: bold; font-size: 12px;")
        targets_layout.addWidget(targets_label)

        # Read-only display label — give it an objectName so the theme can
        # style it like a disabled lineedit if we want to refine later.
        self.targets_display = QLabel()
        self.targets_display.setObjectName("LightLaneTargets")
        self._update_targets_display()
        targets_layout.addWidget(self.targets_display, 1)

        self.edit_targets_btn = QPushButton("...")
        self.edit_targets_btn.setFixedWidth(30)
        self.edit_targets_btn.clicked.connect(self.open_target_selection)
        targets_layout.addWidget(self.edit_targets_btn)

        layout.addLayout(targets_layout)

        # Row 3: Mute, Solo, Add Block
        controls_layout = QHBoxLayout()

        # Mute button — base look from theme; :checked goes red.
        # density=compact gives tight padding so "M" fits 30×25.
        self.mute_button = QPushButton("M")
        self.mute_button.setFixedSize(30, 25)
        self.mute_button.setCheckable(True)
        self.mute_button.setChecked(self.lane.muted)
        self.mute_button.setProperty("density", "compact")
        self.mute_button.setStyleSheet(
            "QPushButton:checked { background-color: #d32f2f; color: white; "
            "border-color: #b71c1c; }"
        )
        self.mute_button.toggled.connect(self.on_mute_toggled)
        controls_layout.addWidget(self.mute_button)

        # Solo button — base look from theme; :checked goes amber.
        self.solo_button = QPushButton("S")
        self.solo_button.setFixedSize(30, 25)
        self.solo_button.setCheckable(True)
        self.solo_button.setChecked(self.lane.solo)
        self.solo_button.setProperty("density", "compact")
        self.solo_button.setStyleSheet(
            "QPushButton:checked { background-color: #FFC107; color: #222; "
            "border-color: #FFA000; }"
        )
        self.solo_button.toggled.connect(self.on_solo_toggled)
        controls_layout.addWidget(self.solo_button)

        controls_layout.addSpacing(10)

        # Snap checkbox
        self.snap_checkbox = QCheckBox("Snap")
        self.snap_checkbox.setChecked(True)
        self.snap_checkbox.setStyleSheet("font-size: 12px;")
        self.snap_checkbox.toggled.connect(self.on_snap_toggled)
        controls_layout.addWidget(self.snap_checkbox)

        controls_layout.addStretch()

        # Add Block button
        self.add_block_button = QPushButton("Add Block")
        self.add_block_button.setMinimumHeight(25)
        self.add_block_button.setProperty("role", "success")
        self.add_block_button.clicked.connect(self.add_light_block)
        controls_layout.addWidget(self.add_block_button)

        layout.addLayout(controls_layout)

        return widget

    def _detect_group_capabilities(self):
        """Detect capabilities from all fixture targets."""
        from config.models import FixtureGroupCapabilities
        from utils.target_resolver import detect_targets_capabilities

        # If no config provided, return default (all capabilities)
        if not self.config:
            return FixtureGroupCapabilities(True, True, True, True)

        # If no targets, return default
        if not self.lane.fixture_targets:
            return FixtureGroupCapabilities(True, True, True, True)

        # Detect capabilities across all targets (union)
        return detect_targets_capabilities(self.lane.fixture_targets, self.config)

    def _count_sublanes(self):
        """Count number of active sublanes."""
        count = 0
        # Show dimmer sublane if has dimmer OR colour (dimmer controls RGB intensity for no-dimmer fixtures)
        if self.capabilities.has_dimmer or self.capabilities.has_colour:
            count += 1
        if self.capabilities.has_colour:
            count += 1
        if self.capabilities.has_movement:
            count += 1
        if self.capabilities.has_special:
            count += 1
        return max(1, count)  # At least 1 sublane

    def get_sublane_index(self, sublane_type: str) -> int:
        """Get the row index (0-based) for a sublane type.

        Args:
            sublane_type: "dimmer", "colour", "movement", or "special"

        Returns:
            Row index, or 0 if not found
        """
        index = 0

        if sublane_type == "dimmer":
            # Show dimmer sublane if has dimmer OR colour (dimmer controls RGB for no-dimmer fixtures)
            if self.capabilities.has_dimmer or self.capabilities.has_colour:
                return index
            else:
                return 0
        # Advance index if dimmer sublane is shown
        if self.capabilities.has_dimmer or self.capabilities.has_colour:
            index += 1

        if sublane_type == "colour":
            if self.capabilities.has_colour:
                return index
            else:
                return 0
        if self.capabilities.has_colour:
            index += 1

        if sublane_type == "movement":
            if self.capabilities.has_movement:
                return index
            else:
                return 0
        if self.capabilities.has_movement:
            index += 1

        if sublane_type == "special":
            if self.capabilities.has_special:
                return index
            else:
                return 0

        return 0  # Fallback

    def sublane_label_rows(self):
        """Ordered (sublane_type, text) pairs for the active sublanes,
        top to bottom - the same row order get_sublane_index assigns."""
        rows = []
        # Dimmer row shows when the group has dimmer OR colour (dimmer
        # drives RGB intensity for no-dimmer fixtures) - mirrors
        # _count_sublanes / get_sublane_index exactly.
        if self.capabilities.has_dimmer or self.capabilities.has_colour:
            rows.append(("dimmer", "DIM"))
        if self.capabilities.has_colour:
            rows.append(("colour", "COL"))
        if self.capabilities.has_movement:
            rows.append(("movement", "MOV"))
        if self.capabilities.has_special:
            rows.append(("special", "SPC"))
        return rows

    def refresh_sublane_labels(self):
        """Rebuild the DIM / COL / MOV / SPC micro-label column from the
        current capabilities (North Star lane anatomy, slice T1). Called
        at construction and whenever capabilities are re-detected
        (on_targets_changed / update_fixture_groups)."""
        layout = getattr(self, "_sublane_labels_layout", None)
        if layout is None:
            return
        # Deferred import: the gui package imports timeline_ui at module
        # load, so a top-level import here would be circular.
        from gui.typography import MicroLabel

        while layout.count():
            item = layout.takeAt(0)
            child = item.widget()
            if child is not None:
                child.deleteLater()

        self.sublane_labels = []
        for sublane_type, text in self.sublane_label_rows():
            label = MicroLabel(text)
            label.setProperty("sublane_type", sublane_type)
            label.setAlignment(Qt.AlignmentFlag.AlignRight
                               | Qt.AlignmentFlag.AlignVCenter)
            # Equal stretch per label: one slot per sublane row, so the
            # column tracks the stripe's row order and spacing evenly
            # within the header's fixed layout.
            layout.addWidget(label, 1)
            self.sublane_labels.append(label)

    def set_song_structure(self, song_structure):
        """Set song structure for this lane's timeline."""
        self.timeline_widget.set_song_structure(song_structure)

    def set_playhead_position(self, position: float):
        """Set playhead position for this lane's timeline."""
        self.timeline_widget.set_playhead_position(position)

    def set_zoom_factor(self, zoom_factor: float):
        """Set zoom factor for this lane's timeline."""
        self.timeline_widget.set_zoom_factor(zoom_factor)

        # Update light block positions
        for block_widget in self.light_block_widgets:
            block_widget.update_position()

    def sync_scroll_position(self, position: int):
        """Sync scroll position with master timeline."""
        self.timeline_scroll.horizontalScrollBar().setValue(position)

    def update_bpm(self, bpm: float):
        """Update BPM for grid calculations."""
        self.timeline_widget.set_bpm(bpm)

    def create_light_block_widget(self, block):
        """Create a widget for a light block."""
        block_widget = LightBlockWidget(block, self.timeline_widget, self)
        block_widget.remove_requested.connect(self.remove_light_block_widget)
        block_widget.position_changed.connect(self.on_block_position_changed)
        block_widget.duration_changed.connect(self.on_block_duration_changed)
        block_widget.block_edited.connect(self.block_edited)  # Forward to lane signal

        self.light_block_widgets.append(block_widget)
        block_widget.show()

    def add_light_block(self):
        """Add a new light block at the current playhead position."""
        from config.models import DimmerBlock, ColourBlock, MovementBlock, SpecialBlock

        start_time = self.timeline_widget.playhead_position
        end_time = start_time + 4.0  # Default 4 second duration

        # Create sublane blocks based on capabilities
        dimmer_block = None
        colour_block = None
        movement_block = None
        special_block = None

        # Create dimmer block if has dimmer OR colour (dimmer controls RGB for no-dimmer fixtures)
        if self.capabilities.has_dimmer or self.capabilities.has_colour:
            dimmer_block = DimmerBlock(
                start_time=start_time,
                end_time=end_time,
                intensity=255.0
            )

        if self.capabilities.has_colour:
            colour_block = ColourBlock(
                start_time=start_time,
                end_time=end_time,
                color_mode="RGB",
                red=255.0,
                green=255.0,
                blue=255.0
            )

        if self.capabilities.has_movement:
            movement_block = MovementBlock(
                start_time=start_time,
                end_time=end_time,
                pan=127.5,
                tilt=127.5
            )

        if self.capabilities.has_special:
            special_block = SpecialBlock(
                start_time=start_time,
                end_time=end_time
            )

        # Create the light block with sublane blocks
        block = self.lane.add_light_block_with_sublanes(
            start_time=start_time,
            end_time=end_time,
            effect_name="",
            dimmer_block=dimmer_block,
            colour_block=colour_block,
            movement_block=movement_block,
            special_block=special_block
        )
        self.create_light_block_widget(block)

    def remove_light_block_widget(self, block_widget, use_undo=True):
        """Remove a light block widget and its data.

        Args:
            block_widget: The widget to remove
            use_undo: If True, use undo command (default). Set False for internal use.
        """
        block = block_widget.block
        undo_stack = self._get_undo_stack() if use_undo else None

        if undo_stack:
            # Use undo command
            cmd = DeleteBlockCommand(self, block, "Delete Block")
            undo_stack.push(cmd)
        else:
            # Direct removal
            self.lane.remove_light_block(block)
            self.light_block_widgets.remove(block_widget)
            block_widget.deleteLater()

    def on_timeline_zoom_changed(self, zoom_factor):
        """Handle timeline zoom changes."""
        for block_widget in self.light_block_widgets:
            block_widget.update_position()

    def on_block_position_changed(self, block_widget, new_start_time):
        """Handle block position change."""
        # Block's start_time is already updated in the widget
        pass

    def on_block_duration_changed(self, block_widget, new_duration):
        """Handle block duration change."""
        # Block's duration is already updated in the widget
        pass

    # Event handlers
    def on_name_changed(self, text):
        self.lane.name = text

    def group_color(self):
        """Public accessor: the lane's group color as '#rrggbb' or None.
        Used by the header border and by LightBlockWidget's envelope
        frame/tint (North Star block anatomy)."""
        return self._group_border_color()

    def _group_border_color(self):
        """The lane's group color: first target's group, resolved
        against the config. None when unresolvable."""
        if not self.config or not self.lane.fixture_targets:
            return None
        from utils.target_resolver import parse_target
        group_name, _ = parse_target(self.lane.fixture_targets[0])
        group = self.config.groups.get(group_name) if self.config.groups else None
        return getattr(group, "color", None) or None

    def _apply_group_border(self):
        """3px group-color left border on the lane header (North Star
        lane anatomy). Group colors are data colors, so a widget-local
        rule is the sanctioned override of the theme's header rule;
        only border-left is set, background stays with the theme."""
        if not hasattr(self, "controls_widget") or self.controls_widget is None:
            return
        color = self._group_border_color() or "transparent"
        self.controls_widget.setStyleSheet(
            f"QWidget#LightLaneHeader {{ border-left: 3px solid {color}; }}"
        )

    def _update_targets_display(self):
        """Update the targets display label."""
        self._apply_group_border()
        targets = self.lane.fixture_targets
        if not targets:
            self.targets_display.setText("(none)")
            self.targets_display.setToolTip("")
            return

        from utils.target_resolver import get_target_display_name

        if len(targets) == 1:
            display_text = get_target_display_name(targets[0], self.config) if self.config else targets[0]
            self.targets_display.setText(display_text)
        else:
            first = get_target_display_name(targets[0], self.config) if self.config else targets[0]
            self.targets_display.setText(f"{first} (+{len(targets) - 1} more)")

        # Full list in tooltip
        if self.config:
            tooltip_lines = [get_target_display_name(t, self.config) for t in targets]
            self.targets_display.setToolTip("\n".join(tooltip_lines))
        else:
            self.targets_display.setToolTip("\n".join(targets))

    def open_target_selection(self):
        """Open the target selection dialog."""
        from timeline_ui.target_selection_dialog import TargetSelectionDialog
        from PyQt6.QtWidgets import QDialog

        if not self.config:
            return

        dialog = TargetSelectionDialog(
            current_targets=self.lane.fixture_targets,
            config=self.config,
            parent=self
        )

        if dialog.exec() == QDialog.DialogCode.Accepted:
            new_targets = dialog.get_selected_targets()
            self.on_targets_changed(new_targets)

    def on_targets_changed(self, targets):
        """Handle fixture targets change - update capabilities and sublanes."""
        self.lane.fixture_targets = targets
        self._update_targets_display()

        # Re-detect capabilities for the new targets
        self.capabilities = self._detect_group_capabilities()
        old_num_sublanes = self.num_sublanes
        self.num_sublanes = self._count_sublanes()

        # Update timeline widget with new sublane configuration
        self.timeline_widget.num_sublanes = self.num_sublanes
        self.timeline_widget.capabilities = self.capabilities

        # Header micro-labels track the active sublanes (slice T1)
        self.refresh_sublane_labels()

        # Only rebuild layout if sublane count changed
        if self.num_sublanes != old_num_sublanes:
            # Update heights
            buffer_height = 40
            total_height = max(self.min_lane_height, self.num_sublanes * self.sublane_height + buffer_height)
            self.setMinimumHeight(total_height)
            self.setMaximumHeight(total_height)

            timeline_height = self.num_sublanes * self.sublane_height
            self.timeline_widget.setMinimumHeight(timeline_height)
            self.timeline_widget.setMaximumHeight(timeline_height)

        # Trigger repaint
        self.timeline_widget.update()
        self.update()

        # Emit block_edited to trigger auto-save
        self.block_edited.emit()

    def on_mute_toggled(self, checked):
        self.lane.muted = checked
        self.update_mute_button_style()

    def on_solo_toggled(self, checked):
        self.lane.solo = checked
        self.update_solo_button_style()

    def on_snap_toggled(self, checked):
        self.timeline_widget.set_snap_to_grid(checked)
        for block_widget in self.light_block_widgets:
            block_widget.set_snap_to_grid(checked)

    def update_mute_button_style(self):
        """Backwards-compat no-op; the :checked CSS handles state visuals."""
        pass

    def update_solo_button_style(self):
        """Backwards-compat no-op; the :checked CSS handles state visuals."""
        pass

    def paste_effect_at_time(self, target_time: float):
        """Paste copied effect at the specified time.

        Args:
            target_time: Start time for the pasted effect
        """
        from timeline_ui.effect_clipboard import paste_effect, has_multi_clipboard_data, paste_multiple_effects

        # Check if we have multi-clipboard data
        if has_multi_clipboard_data():
            # Need to paste to multiple lanes - delegate to ShowsTab
            shows_tab = self._get_shows_tab()
            if shows_tab:
                # Get all lane widgets from shows_tab
                lane_widgets = shows_tab.lane_widgets
                results = paste_multiple_effects(target_time, lane_widgets)
                for lane_widget, new_block in results:
                    # Add to lane data
                    lane_widget.lane.light_blocks.append(new_block)
                    # Create widget
                    lane_widget.create_light_block_widget(new_block)
                if results:
                    shows_tab.save_to_config()
                return

        # Single effect paste
        new_block = paste_effect(target_time)
        if new_block is None:
            return

        # Add to lane data
        self.lane.light_blocks.append(new_block)

        # Create widget for the new block
        self.create_light_block_widget(new_block)

    def _get_shows_tab(self):
        """Get the ShowsTab parent widget if available."""
        # Walk up the parent chain to find ShowsTab (has lane_widgets)
        widget = self.parent()
        while widget is not None:
            if hasattr(widget, 'lane_widgets') and hasattr(widget, 'save_to_config'):
                return widget
            widget = widget.parent()
        return None

    def update_fixture_groups(self, fixture_groups: list):
        """Update the available fixture groups list.

        Also refreshes capabilities since fixtures in groups may have changed.

        Args:
            fixture_groups: List of fixture group names
        """
        self.fixture_groups = fixture_groups

        # Update the targets display (names may have changed)
        self._update_targets_display()

        # Refresh local capabilities (fixtures may have been added/removed from groups)
        self.capabilities = self._detect_group_capabilities()
        self.timeline_widget.capabilities = self.capabilities

        # Header micro-labels track the active sublanes (slice T1)
        self.refresh_sublane_labels()

    def set_riff_library(self, riff_library):
        """Set the riff library for this lane.

        Args:
            riff_library: RiffLibrary instance
        """
        self.riff_library = riff_library

    def on_riff_dropped(self, riff_path: str, drop_time: float):
        """Handle a riff being dropped onto the timeline.

        Args:
            riff_path: Path to riff like "category/name"
            drop_time: Time position where riff was dropped
        """
        # Get riff library from main window
        riff_library = getattr(self, 'riff_library', None)
        if not riff_library:
            # Try to get from main window
            main_window = self.window()
            if hasattr(main_window, 'riff_library'):
                riff_library = main_window.riff_library

        if not riff_library:
            print(f"Error: No riff library available")
            return

        # Get the riff
        riff = riff_library.get_riff(riff_path)
        if not riff:
            print(f"Error: Riff not found: {riff_path}")
            return

        # Check compatibility with fixture group
        if self.config and self.lane.fixture_group in self.config.groups:
            group = self.config.groups[self.lane.fixture_group]
            is_compatible, reason = riff.is_compatible_with(group)
            if not is_compatible:
                QMessageBox.warning(
                    self,
                    "Incompatible Riff",
                    f"Cannot drop riff '{riff.name}' on this lane.\n{reason}"
                )
                return

        # Get song structure for BPM conversion
        song_structure = self.timeline_widget.song_structure
        if not song_structure:
            # Create a simple mock for constant BPM
            class SimpleSongStructure:
                def __init__(self, bpm):
                    self.bpm = bpm
                def get_bpm_at_time(self, time):
                    return self.bpm
            song_structure = SimpleSongStructure(self.timeline_widget.bpm)

        # Convert riff to LightBlock
        new_block = riff.to_light_block(drop_time, song_structure)

        # Find overlapping blocks (for undo)
        removed_blocks = self._get_overlapping_blocks(new_block.start_time, new_block.end_time)

        # Get undo stack from main window
        undo_stack = self._get_undo_stack()

        if undo_stack is not None:
            # Use undo command
            cmd = InsertRiffCommand(
                self, new_block, removed_blocks,
                f"Insert Riff: {riff.name}"
            )
            undo_stack.push(cmd)
        else:
            # Fallback: direct manipulation without undo
            self._remove_overlapping_blocks(new_block.start_time, new_block.end_time)
            self.lane.light_blocks.append(new_block)
            self.create_light_block_widget(new_block)

        # Emit block edited signal for auto-save
        self.block_edited.emit()

    def _get_undo_stack(self) -> QUndoStack:
        """Get the undo stack from the main window.

        Returns:
            QUndoStack or None if not available
        """
        # First try window() which should return the top-level window
        main_window = self.window()
        if hasattr(main_window, 'get_undo_stack'):
            return main_window.get_undo_stack()
        if hasattr(main_window, 'undo_stack'):
            return main_window.undo_stack

        # Fallback: traverse parent chain to find MainWindow
        parent = self.parent()
        while parent is not None:
            if hasattr(parent, 'get_undo_stack'):
                return parent.get_undo_stack()
            if hasattr(parent, 'undo_stack'):
                return parent.undo_stack
            parent = parent.parent()

        return None

    def _get_overlapping_blocks(self, start_time: float, end_time: float) -> list:
        """Get blocks that overlap with the given time range.

        Args:
            start_time: Start of range
            end_time: End of range

        Returns:
            List of overlapping LightBlock objects
        """
        overlapping = []
        for block in self.lane.light_blocks:
            if block.start_time < end_time and block.end_time > start_time:
                overlapping.append(block)
        return overlapping

    def _remove_overlapping_blocks(self, start_time: float, end_time: float):
        """Remove blocks that overlap with the given time range.

        Args:
            start_time: Start of range
            end_time: End of range
        """
        blocks_to_remove = []

        for block in self.lane.light_blocks:
            # Check if block overlaps with range
            if block.start_time < end_time and block.end_time > start_time:
                blocks_to_remove.append(block)

        # Remove overlapping blocks and their widgets
        for block in blocks_to_remove:
            # Find and remove the widget
            widget_to_remove = None
            for widget in self.light_block_widgets:
                if widget.block is block:
                    widget_to_remove = widget
                    break

            if widget_to_remove:
                self.light_block_widgets.remove(widget_to_remove)
                widget_to_remove.deleteLater()

            # Remove from lane data
            self.lane.light_blocks.remove(block)

    def get_blocks_in_time_range(self, start_time: float, end_time: float) -> list:
        """Get block widgets that intersect with the given time range.

        Args:
            start_time: Start of time range
            end_time: End of time range

        Returns:
            List of LightBlockWidget instances that overlap with the range
        """
        intersecting = []
        for widget in self.light_block_widgets:
            block_start, block_end = widget.get_block_time_bounds()
            # Check for intersection
            if block_start < end_time and block_end > start_time:
                intersecting.append(widget)
        return intersecting

    def get_all_block_widgets(self) -> list:
        """Get all block widgets in this lane.

        Returns:
            List of all LightBlockWidget instances
        """
        return list(self.light_block_widgets)
