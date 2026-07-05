# gui/tabs/stage_tab.py

import subprocess
import sys
import os

from PyQt6 import QtWidgets
from PyQt6.QtCore import Qt, QTimer, QSettings, QEvent
from config.models import Configuration
from .base_tab import BaseTab
from gui.StageView import StageView
from gui.stage_items import FixtureItem
from gui.dialogs.orientation_dialog import OrientationDialog, OrientationPanel
from gui.widgets.embedded_visualizer import EmbeddedVisualizer


class StageTab(BaseTab):
    """Stage layout and fixture positioning tab

    Provides visual stage representation with fixture positioning,
    grid controls, and spot/mark management. Composes the existing
    StageView component with control panel UI.
    """

    def __init__(self, config: Configuration, parent=None):
        """Initialize stage tab

        Args:
            config: Shared Configuration object
            parent: Parent widget (typically MainWindow)
        """
        super().__init__(config, parent)

        # Tab active state (for pausing TCP updates when not visible)
        self._tab_active = False

        # Throttle timer for TCP updates (avoid flooding during drag)
        self._tcp_update_timer = QTimer()
        self._tcp_update_timer.setSingleShot(True)
        self._tcp_update_timer.setInterval(100)  # 100ms throttle
        self._tcp_update_timer.timeout.connect(self._do_tcp_update)
        self._tcp_update_pending = False

    def setup_ui(self):
        """Set up stage visualization UI"""
        # Create main layout for the tab
        main_layout = QtWidgets.QHBoxLayout(self)

        # Left control panel
        control_panel = QtWidgets.QWidget()
        control_layout = QtWidgets.QVBoxLayout(control_panel)
        control_panel.setFixedWidth(250)

        # Stage dimensions group
        dim_group = QtWidgets.QGroupBox("Stage Dimensions")
        dim_layout = QtWidgets.QFormLayout(dim_group)

        self.stage_width = QtWidgets.QSpinBox()
        self.stage_width.setRange(1, 1000)
        self.stage_width.setValue(10)  # Default 10 meters

        self.stage_height = QtWidgets.QSpinBox()
        self.stage_height.setRange(1, 1000)
        self.stage_height.setValue(6)  # Default 6 meters

        dim_layout.addRow("Width (m):", self.stage_width)
        dim_layout.addRow("Depth (m):", self.stage_height)

        # No "Update Stage" button — the spinboxes' valueChanged signal
        # already drives _update_stage live, matching how the grid-size
        # spinbox below works. The button used to fire the same handler
        # and was redundant.

        # Grid controls group
        grid_group = QtWidgets.QGroupBox("Grid Settings")
        grid_layout = QtWidgets.QFormLayout(grid_group)

        self.grid_toggle = QtWidgets.QCheckBox("Show Grid")
        self.grid_toggle.setChecked(True)  # Grid visible by default

        self.grid_size = QtWidgets.QDoubleSpinBox()
        self.grid_size.setRange(0.1, 50)
        self.grid_size.setValue(0.5)  # Default 0.5m grid
        self.grid_size.setSingleStep(0.1)

        self.snap_to_grid = QtWidgets.QCheckBox("Snap to Grid")
        self.snap_to_grid.setChecked(True)  # Enable by default

        grid_layout.addRow(self.grid_toggle)
        grid_layout.addRow("Grid Size (m):", self.grid_size)
        grid_layout.addRow(self.snap_to_grid)

        # View controls — fit the stage plot back to the viewport
        # after the user has zoomed/panned. The 'F' shortcut below
        # (wired in connect_signals) duplicates the button so the
        # user can reset without moving the mouse off the plot.
        view_group = QtWidgets.QGroupBox("View")
        view_layout = QtWidgets.QVBoxLayout(view_group)
        self.fit_view_btn = QtWidgets.QPushButton("Fit View (F)")
        self.fit_view_btn.setToolTip(
            "Reset zoom and pan to fit the whole stage.\n\n"
            "Stage controls:\n"
            "  • Mouse wheel — zoom (around cursor)\n"
            "  • Space + left-drag — pan\n"
            "  • F — fit view"
        )
        view_layout.addWidget(self.fit_view_btn)

        # Stage marks group
        spot_group = QtWidgets.QGroupBox("Stage Marks")
        spot_layout = QtWidgets.QVBoxLayout(spot_group)

        self.add_spot_btn = QtWidgets.QPushButton("Add Mark")
        self.remove_item_btn = QtWidgets.QPushButton("Remove Selected")

        spot_layout.addWidget(self.add_spot_btn)
        spot_layout.addWidget(self.remove_item_btn)

        # Stage layers group — named Z-planes (ground stack / mid-truss /
        # top-truss). Checkbox = visibility; hidden layers disappear from
        # the 2D plot and every 3D preview. Fixtures are assigned via the
        # stage right-click menu ("Assign to Layer").
        layer_group = QtWidgets.QGroupBox("Stage Layers")
        layer_layout = QtWidgets.QVBoxLayout(layer_group)

        self.layer_list = QtWidgets.QListWidget()
        self.layer_list.setMaximumHeight(110)
        self.layer_list.setToolTip(
            "Named Z-planes of the rig. Uncheck a layer to hide its\n"
            "fixtures on the stage plot and in the 3D previews.\n"
            "Assign fixtures via right-click on the stage."
        )
        layer_layout.addWidget(self.layer_list)

        layer_btn_row = QtWidgets.QHBoxLayout()
        self.add_layer_btn = QtWidgets.QPushButton("+")
        self.add_layer_btn.setFixedWidth(32)
        self.add_layer_btn.setToolTip("Add Layer")
        self.remove_layer_btn = QtWidgets.QPushButton("-")
        self.remove_layer_btn.setFixedWidth(32)
        self.remove_layer_btn.setToolTip("Remove Layer (fixtures keep their height)")
        self.edit_layer_btn = QtWidgets.QPushButton("Edit")
        self.edit_layer_btn.setToolTip("Rename the layer or move it to another height")
        layer_btn_row.addWidget(self.add_layer_btn)
        layer_btn_row.addWidget(self.remove_layer_btn)
        layer_btn_row.addWidget(self.edit_layer_btn)
        layer_btn_row.addStretch()
        layer_layout.addLayout(layer_btn_row)

        # Stage planes group — picker for the 6 faces of the stage
        # bounding cuboid. Hovering an entry highlights that face in the
        # embedded 3D preview; clicking selects it persistently; clicking
        # the selected entry again clears. Display-only for now — plane
        # *targeting* from movement blocks is v1.4a.
        from visualizer.renderer.stage_planes import PLANE_NAMES
        plane_group = QtWidgets.QGroupBox("Stage Planes")
        plane_layout = QtWidgets.QVBoxLayout(plane_group)

        self.plane_list = QtWidgets.QListWidget()
        self.plane_list.setMaximumHeight(120)
        self.plane_list.setMouseTracking(True)
        self.plane_list.setToolTip(
            "The 6 faces of the stage bounding box.\n"
            "Hover to preview, click to keep highlighted in the 3D view,\n"
            "click again to clear."
        )
        for plane_name in PLANE_NAMES:
            item = QtWidgets.QListWidgetItem(plane_name)
            item.setData(Qt.ItemDataRole.UserRole, plane_name)
            self.plane_list.addItem(item)
        self._selected_plane = None
        plane_layout.addWidget(self.plane_list)

        # Fixture Orientation group
        orientation_group = QtWidgets.QGroupBox("Fixture Orientation")
        orientation_layout = QtWidgets.QVBoxLayout(orientation_group)

        # Single checkbox — when on, every fixture draws its XYZ
        # axes. The previous two-checkbox UX (selected-only by
        # default, with a separate "Show all" toggle) was non-
        # discoverable: checking only "Show orientation axes" with
        # nothing selected made no visible change, so the user read
        # the whole control as broken.
        self.show_axes_checkbox = QtWidgets.QCheckBox("Show orientation axes")
        self.show_axes_checkbox.setToolTip("Show XYZ axes on every fixture")
        orientation_layout.addWidget(self.show_axes_checkbox)

        # Plot stage group
        plot_group = QtWidgets.QGroupBox("Stage Plot")
        plot_layout = QtWidgets.QVBoxLayout(plot_group)

        self.plot_stage_btn = QtWidgets.QPushButton("Plot Stage")
        plot_layout.addWidget(self.plot_stage_btn)

        # Visualizer group
        visualizer_group = QtWidgets.QGroupBox("3D Visualizer")
        visualizer_layout = QtWidgets.QVBoxLayout(visualizer_group)

        # Launch button
        self.launch_visualizer_btn = QtWidgets.QPushButton("Launch Visualizer")
        self.launch_visualizer_btn.setToolTip("Start the 3D Visualizer application")
        visualizer_layout.addWidget(self.launch_visualizer_btn)

        # TCP status indicator
        tcp_status_layout = QtWidgets.QHBoxLayout()
        tcp_status_layout.addWidget(QtWidgets.QLabel("TCP Server:"))
        self.tcp_status_label = QtWidgets.QLabel()
        self.tcp_status_label.setStyleSheet("font-weight: bold;")
        tcp_status_layout.addWidget(self.tcp_status_label)
        tcp_status_layout.addStretch()
        visualizer_layout.addLayout(tcp_status_layout)

        # Visualizer process reference
        self.visualizer_process = None

        # Timer to update TCP status
        self.tcp_status_timer = QTimer()
        self.tcp_status_timer.timeout.connect(self._update_tcp_status)
        self.tcp_status_timer.start(1000)  # Update every second

        # Initial status update
        self._update_tcp_status()

        # Add groups to control panel in order
        control_layout.addWidget(dim_group)
        control_layout.addWidget(grid_group)
        control_layout.addWidget(view_group)
        control_layout.addWidget(spot_group)
        control_layout.addWidget(layer_group)
        control_layout.addWidget(plane_group)
        control_layout.addWidget(orientation_group)
        control_layout.addWidget(plot_group)
        control_layout.addWidget(visualizer_group)
        control_layout.addStretch()

        # Initialize StageView with configuration (the 2D top-down).
        self.stage_view = StageView(self)
        self.stage_view.set_config(self.config)

        # Right pane stacks the embedded 3D preview over a persistent
        # OrientationPanel (driven from the right-click Set Orientation flow).
        self.embedded_visualizer = EmbeddedVisualizer(self)
        self.embedded_visualizer.set_pop_out_callback(self._launch_visualizer)
        self.embedded_visualizer.set_config(self.config)
        self.embedded_visualizer.set_preview_mode("build")

        # Persistent inline orientation editor — re-bound by the right-click
        # "Set Orientation" flow on selection. Live-edits write through to
        # the bound fixtures via the values_changed hook below.
        self.orientation_panel = OrientationPanel([], self.config, self)
        self.orientation_panel.values_changed.connect(self._on_inline_orientation_changed)

        right_splitter = QtWidgets.QSplitter(Qt.Orientation.Vertical)
        right_splitter.addWidget(self.embedded_visualizer)
        right_splitter.addWidget(self.orientation_panel)
        right_splitter.setStretchFactor(0, 6)
        right_splitter.setStretchFactor(1, 4)
        self._right_splitter = right_splitter

        main_splitter = QtWidgets.QSplitter(Qt.Orientation.Horizontal)
        main_splitter.addWidget(self.stage_view)
        main_splitter.addWidget(right_splitter)
        main_splitter.setStretchFactor(0, 2)
        main_splitter.setStretchFactor(1, 1)
        self._main_splitter = main_splitter

        # Restore persisted splitter sizes if we have them.
        settings = QSettings("QLCShowCreator", "QLCShowCreator")
        main_state = settings.value("stage/main_splitter")
        if main_state is not None:
            try:
                main_splitter.restoreState(main_state)
            except Exception:
                pass
        right_state = settings.value("stage/right_splitter")
        if right_state is not None:
            try:
                right_splitter.restoreState(right_state)
            except Exception:
                pass

        main_layout.addWidget(control_panel)
        main_layout.addWidget(main_splitter, stretch=1)

    def connect_signals(self):
        """Connect widget signals to handlers"""
        # Stage dimension controls - auto-update on change.
        self.stage_width.valueChanged.connect(self._update_stage)
        self.stage_height.valueChanged.connect(self._update_stage)

        # Grid controls
        self.grid_toggle.stateChanged.connect(
            lambda state: self.stage_view.updateGrid(visible=bool(state))
        )
        self.grid_size.valueChanged.connect(self._update_grid_size)
        self.snap_to_grid.stateChanged.connect(
            lambda state: self.stage_view.set_snap_to_grid(bool(state))
        )

        # Connect fixture changes to TCP update (for live visualizer sync)
        # AND broadcast a refresh to every embedded visualizer (Stage,
        # Shows, Live) so the 3D previews on other tabs follow 2D edits.
        self.stage_view.fixtures_changed.connect(self._notify_tcp_update)
        self.stage_view.fixtures_changed.connect(self._broadcast_visualizer_refresh)

        # Spot/mark controls
        self.add_spot_btn.clicked.connect(lambda: self.stage_view.add_spot())
        self.remove_item_btn.clicked.connect(self.stage_view.remove_selected_items)

        # Stage layer controls
        self.add_layer_btn.clicked.connect(self._add_layer)
        self.remove_layer_btn.clicked.connect(self._remove_layer)
        self.edit_layer_btn.clicked.connect(self._edit_layer)
        self.layer_list.itemChanged.connect(self._on_layer_item_changed)

        # Stage plane picker: hover previews, click toggles persistence.
        # The event filter catches the mouse leaving the list so a pure
        # hover (no click) reverts to the persistent selection.
        self.plane_list.itemEntered.connect(self._on_plane_hovered)
        self.plane_list.itemClicked.connect(self._on_plane_clicked)
        self.plane_list.viewport().installEventFilter(self)

        # Stage plot export
        self.plot_stage_btn.clicked.connect(self._export_stage_plot)

        # Visualizer controls
        self.launch_visualizer_btn.clicked.connect(self._launch_visualizer)

        # Orientation display control
        self.show_axes_checkbox.stateChanged.connect(self._on_show_axes_changed)

        # Orientation dialog trigger from right-click menu
        self.stage_view.set_orientation_requested.connect(self._on_set_orientation_requested)

        # Auto-bind the inline orientation panel whenever the user changes
        # the selection on the 2D StageView — single-click on a fixture is
        # enough to start editing it, no right-click required.
        self.stage_view.scene.selectionChanged.connect(self._on_stage_selection_changed)

        # Fit View — button + F shortcut. The shortcut is scoped to this
        # tab (``WidgetWithChildrenShortcut`` on ``self``) so F doesn't
        # collide with the same key in other tabs / inputs and only
        # fires when the user's focus is somewhere in the Stage tab.
        from PyQt6.QtGui import QShortcut, QKeySequence
        self.fit_view_btn.clicked.connect(self.stage_view.fit_to_stage)
        self._fit_shortcut = QShortcut(QKeySequence("F"), self)
        self._fit_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self._fit_shortcut.activated.connect(self.stage_view.fit_to_stage)

    def update_from_config(self):
        """Refresh stage view from configuration"""
        if self.stage_view:
            self.stage_view.set_config(self.config)

        # Load stage dimensions and grid size from config
        if self.config:
            self.stage_width.blockSignals(True)
            self.stage_height.blockSignals(True)
            self.grid_size.blockSignals(True)

            self.stage_width.setValue(int(self.config.stage_width))
            self.stage_height.setValue(int(self.config.stage_height))
            if hasattr(self.config, 'grid_size'):
                self.grid_size.setValue(self.config.grid_size)

            self.stage_width.blockSignals(False)
            self.stage_height.blockSignals(False)
            self.grid_size.blockSignals(False)

            # The StageView keeps its own stage_width_m / stage_depth_m /
            # grid_size_m attributes (defaulted in __init__). set_config
            # above doesn't refresh them, and blockSignals(True) on the
            # spinboxes suppresses the valueChanged → _update_stage path
            # we'd otherwise rely on. Without the explicit calls below
            # the 2D plot stays at the default 10 × 6 m / 0.5 m grid no
            # matter what the loaded YAML says.
            if self.stage_view:
                self.stage_view.updateStage(
                    width_m=float(self.config.stage_width),
                    depth_m=float(self.config.stage_height),
                )
                if hasattr(self.config, 'grid_size'):
                    self.stage_view.updateGrid(size_m=float(self.config.grid_size))

            self._refresh_layer_list()

        self._refresh_embedded_visualizer()

    def save_to_config(self):
        """Save fixture positions and spots back to configuration"""
        if self.stage_view:
            self.stage_view.save_positions_to_config()

    def _update_stage(self):
        """Update stage dimensions from spin box values"""
        width = self.stage_width.value()
        height = self.stage_height.value()

        # Update StageView
        self.stage_view.updateStage(width, height)
        self.stage_view.update_from_config()

        # Update Configuration for TCP sync
        if self.config:
            self.config.stage_width = float(width)
            self.config.stage_height = float(height)

            # Notify TCP server if running (for live visualizer updates)
            self._notify_tcp_update()

        # Push the new dimensions to every embedded 3D preview (Stage's
        # own + Shows + Live). Without this the Shows/Live previews
        # stay stuck on the old stage size until the user manually
        # activates them; even the Stage tab's own preview wouldn't
        # repaint without an explicit refresh because updateStage on
        # its own doesn't emit fixtures_changed.
        self._broadcast_visualizer_refresh()

    def _update_grid_size(self, value: float):
        """Update grid size from spin box value"""
        # Update StageView
        self.stage_view.updateGrid(size_m=value)

        # Update Configuration for TCP sync
        if self.config:
            self.config.grid_size = value

            # Notify TCP server if running (for live visualizer updates)
            self._notify_tcp_update()

    def _launch_visualizer(self):
        """Launch the 3D Visualizer application."""
        # Check if visualizer is already running
        if self.visualizer_process is not None:
            poll_result = self.visualizer_process.poll()
            if poll_result is None:
                # Process is still running
                QtWidgets.QMessageBox.information(
                    self,
                    "Visualizer Running",
                    "The Visualizer is already running."
                )
                return

        # Check if TCP server is running, offer to start it if not
        if not self._ensure_tcp_server_running():
            return

        # Get path to visualizer main.py
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        visualizer_path = os.path.join(project_root, "visualizer", "main.py")

        if not os.path.exists(visualizer_path):
            QtWidgets.QMessageBox.warning(
                self,
                "Visualizer Not Found",
                f"Could not find visualizer at:\n{visualizer_path}"
            )
            return

        try:
            # Launch visualizer as subprocess
            self.visualizer_process = subprocess.Popen(
                [sys.executable, visualizer_path],
                cwd=project_root
            )
            print(f"Visualizer launched (PID: {self.visualizer_process.pid})")
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self,
                "Launch Error",
                f"Failed to launch Visualizer:\n{str(e)}"
            )

    def _ensure_tcp_server_running(self) -> bool:
        """
        Ensure TCP server is running before launching visualizer.

        Returns:
            True if server is running (or was started), False if user cancelled
        """
        try:
            main_window = self.window()
            if not main_window:
                return True  # Can't check, proceed anyway

            shows_tab = getattr(main_window, 'shows_tab', None)
            if not shows_tab:
                return True  # Can't check, proceed anyway

            tcp_server = getattr(shows_tab, 'tcp_server', None)

            # Check if server is running
            if tcp_server and tcp_server.is_running():
                return True  # Already running

            # Server not running - ask user if they want to start it
            reply = QtWidgets.QMessageBox.question(
                self,
                "Start TCP Server?",
                "The TCP server is not running.\n\n"
                "The Visualizer needs the TCP server to receive stage configuration.\n\n"
                "Start the TCP server now?",
                QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
                QtWidgets.QMessageBox.StandardButton.Yes
            )

            if reply == QtWidgets.QMessageBox.StandardButton.Yes:
                # Start the TCP server via ShowsTab
                try:
                    # Use _on_tcp_toggle which handles all the init logic
                    if hasattr(shows_tab, '_on_tcp_toggle'):
                        shows_tab._on_tcp_toggle(True)

                        # Update the checkbox in ShowsTab if it exists
                        tcp_checkbox = getattr(shows_tab, 'tcp_checkbox', None)
                        if tcp_checkbox:
                            tcp_checkbox.blockSignals(True)
                            tcp_checkbox.setChecked(True)
                            tcp_checkbox.blockSignals(False)
                    else:
                        QtWidgets.QMessageBox.warning(
                            self,
                            "Cannot Start Server",
                            "TCP server initialization not available.\n"
                            "Please enable 'Visualizer Server' in the Shows tab."
                        )
                        return False

                    # Verify it started
                    tcp_server = getattr(shows_tab, 'tcp_server', None)
                    if tcp_server and tcp_server.is_running():
                        print("TCP server started successfully")
                        self._update_tcp_status()
                        return True
                    else:
                        QtWidgets.QMessageBox.warning(
                            self,
                            "Server Start Failed",
                            "Failed to start TCP server.\n"
                            "Please check the Shows tab for errors."
                        )
                        return False

                except Exception as e:
                    QtWidgets.QMessageBox.warning(
                        self,
                        "Server Start Failed",
                        f"Failed to start TCP server:\n{str(e)}"
                    )
                    return False
            else:
                # User chose not to start server
                return False

        except Exception as e:
            print(f"Error checking TCP server: {e}")
            return True  # Proceed anyway on error

    def _update_tcp_status(self):
        """Update TCP server status indicator."""
        # Try to get TCP server from ShowsTab via parent (MainWindow)
        tcp_server = None
        try:
            # Navigate up to MainWindow via Qt parent hierarchy
            main_window = self.window()
            if main_window:
                shows_tab = getattr(main_window, 'shows_tab', None)
                if shows_tab:
                    tcp_server = getattr(shows_tab, 'tcp_server', None)
        except Exception:
            pass

        if tcp_server is None:
            self.tcp_status_label.setText("Not initialized")
            self.tcp_status_label.setStyleSheet("color: #666; font-weight: bold;")
        elif not tcp_server.is_running():
            self.tcp_status_label.setText("Stopped")
            self.tcp_status_label.setStyleSheet("color: #f44336; font-weight: bold;")
        else:
            client_count = tcp_server.get_client_count()
            if client_count == 0:
                self.tcp_status_label.setText("Running (no clients)")
                self.tcp_status_label.setStyleSheet("color: #2196F3; font-weight: bold;")
            else:
                self.tcp_status_label.setText(f"Connected ({client_count})")
                self.tcp_status_label.setStyleSheet("color: #4CAF50; font-weight: bold;")

    def on_tab_activated(self):
        """Called when stage tab becomes visible."""
        self._tab_active = True
        # Send current state to visualizer when tab becomes active
        self._notify_tcp_update()
        # Embedded preview defaults to build mode (full-on lighting) on the
        # Stage tab — playback lives in the Shows tab.
        if hasattr(self, "embedded_visualizer") and self.embedded_visualizer is not None:
            self.embedded_visualizer.set_preview_mode("build")
            self._refresh_embedded_visualizer()

    def on_tab_deactivated(self):
        """Called when switching away from stage tab."""
        self._tab_active = False
        # Stop any pending updates
        self._tcp_update_timer.stop()
        self._tcp_update_pending = False
        self._save_splitter_state()

    def _save_splitter_state(self) -> None:
        """Persist the main + right splitter sizes via QSettings so the
        Stage tab opens with the same proportions next session."""
        if not hasattr(self, "_main_splitter") or not hasattr(self, "_right_splitter"):
            return
        settings = QSettings("QLCShowCreator", "QLCShowCreator")
        settings.setValue("stage/main_splitter", self._main_splitter.saveState())
        settings.setValue("stage/right_splitter", self._right_splitter.saveState())

    def _notify_tcp_update(self):
        """Notify TCP server about configuration changes (throttled for live updates)."""
        # Only send updates when tab is active (reduces lag when working on other tabs)
        if not self._tab_active:
            return

        # Use throttle timer to avoid flooding during drag operations
        self._tcp_update_pending = True
        if not self._tcp_update_timer.isActive():
            self._tcp_update_timer.start()

    def _do_tcp_update(self):
        """Actually send the TCP update (called by throttle timer)."""
        if not self._tcp_update_pending:
            return
        self._tcp_update_pending = False

        try:
            # Get shows_tab which hosts the TCP server
            main_window = self.parent()
            while main_window and not hasattr(main_window, 'shows_tab'):
                main_window = main_window.parent()

            if main_window and hasattr(main_window, 'shows_tab'):
                shows_tab = main_window.shows_tab
                tcp_server = getattr(shows_tab, 'tcp_server', None)

                if tcp_server and tcp_server.is_running() and self.config:
                    # Update the server's config and push to clients
                    tcp_server.update_config(self.config)
        except Exception as e:
            print(f"Error notifying TCP server: {e}")

    # ── Stage plot export ─────────────────────────────────────────────

    def _export_stage_plot(self):
        """Plot Stage button: export the rig as a PDF or PNG stage plot.

        Small options dialog (paper size + PNG resolution), then a save
        dialog whose extension picks the format.
        """
        from gui.stage_plot import PAPER_PRESETS, StagePlotRenderer

        if not self.config.fixtures:
            QtWidgets.QMessageBox.warning(
                self, "No Fixtures",
                "Add fixtures before exporting a stage plot."
            )
            return

        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("Export Stage Plot")
        layout = QtWidgets.QFormLayout(dialog)

        paper_combo = QtWidgets.QComboBox()
        paper_combo.addItems(list(PAPER_PRESETS.keys()))
        layout.addRow("Paper size (landscape):", paper_combo)

        dpi_combo = QtWidgets.QComboBox()
        dpi_combo.addItems(["150", "300"])
        dpi_combo.setCurrentText("300")
        dpi_combo.setToolTip("Only used for PNG output; PDF is vector.")
        layout.addRow("PNG resolution (dpi):", dpi_combo)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok |
            QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addRow(buttons)

        if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return

        renderer = StagePlotRenderer(self.config)
        loaded_from = getattr(self.config, '_loaded_from', None)
        default_dir = os.path.dirname(loaded_from) if loaded_from else ""
        default_name = f"{renderer.title}_stage_plot.pdf"
        default_path = os.path.join(default_dir, default_name) if default_dir else default_name

        file_path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Export Stage Plot", default_path,
            "PDF (*.pdf);;PNG (*.png)"
        )
        if not file_path:
            return
        if not os.path.splitext(file_path)[1]:
            file_path += ".pdf"

        try:
            fmt = renderer.render(
                file_path,
                paper=paper_combo.currentText(),
                dpi=int(dpi_combo.currentText()),
            )
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self, "Export Failed",
                f"Could not export the stage plot:\n{e}"
            )
            return

        QtWidgets.QMessageBox.information(
            self, "Exported",
            f"Stage plot exported as {fmt.upper()}:\n{file_path}"
        )

    # ── Stage planes ──────────────────────────────────────────────────

    def eventFilter(self, obj, event):
        """Revert the plane highlight to the persistent selection when
        the mouse leaves the plane list (ends a hover preview)."""
        if (hasattr(self, "plane_list") and obj is self.plane_list.viewport()
                and event.type() == QEvent.Type.Leave):
            self._apply_plane_highlight(self._selected_plane)
        return super().eventFilter(obj, event)

    def _rig_height(self) -> float:
        """Ceiling height of the stage cuboid: the tallest fixture's
        effective Z, floored at 3 m — the same rule autogen's
        compute_stage_planes uses, so the highlighted ceiling matches
        where Auto Mode aims."""
        max_z = 3.0
        for fixture in self.config.fixtures:
            group = self.config.groups.get(fixture.group) if fixture.group else None
            z = fixture.get_effective_z(group)
            if z > max_z:
                max_z = z
        return max_z

    def _apply_plane_highlight(self, name):
        if hasattr(self, "embedded_visualizer") and self.embedded_visualizer is not None:
            self.embedded_visualizer.set_highlighted_plane(name, self._rig_height())

    def _on_plane_hovered(self, item):
        self._apply_plane_highlight(item.data(Qt.ItemDataRole.UserRole))

    def _on_plane_clicked(self, item):
        name = item.data(Qt.ItemDataRole.UserRole)
        if self._selected_plane == name:
            self._selected_plane = None
            self.plane_list.clearSelection()
        else:
            self._selected_plane = name
        self._apply_plane_highlight(self._selected_plane)

    # ── Stage layers ──────────────────────────────────────────────────

    def _refresh_layer_list(self):
        """Rebuild the layer list widget from config.stage_layers."""
        self.layer_list.blockSignals(True)
        self.layer_list.clear()
        for layer in self.config.stage_layers:
            item = QtWidgets.QListWidgetItem(f"{layer.name} ({layer.z_height:g} m)")
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked if layer.visible else Qt.CheckState.Unchecked
            )
            item.setData(Qt.ItemDataRole.UserRole, layer.name)
            self.layer_list.addItem(item)
        self.layer_list.blockSignals(False)

    def _on_layer_item_changed(self, item):
        """Checkbox toggle — flip the layer's visible flag everywhere."""
        layer = self.config.get_stage_layer(item.data(Qt.ItemDataRole.UserRole))
        if layer is None:
            return
        layer.visible = item.checkState() == Qt.CheckState.Checked
        self.stage_view.apply_layer_visibility()
        self._notify_tcp_update()
        self._broadcast_visualizer_refresh()

    def _layer_dialog(self, title, name="", z_height=3.0):
        """Small name + height dialog. Returns (name, z_height) or None."""
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle(title)
        layout = QtWidgets.QFormLayout(dialog)

        name_edit = QtWidgets.QLineEdit(name)
        name_edit.setPlaceholderText("e.g. Top truss")
        layout.addRow("Name:", name_edit)

        z_spin = QtWidgets.QDoubleSpinBox()
        z_spin.setRange(0.0, 100.0)
        z_spin.setSingleStep(0.5)
        z_spin.setValue(z_height)
        layout.addRow("Height (m):", z_spin)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok |
            QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addRow(buttons)

        if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return None
        new_name = name_edit.text().strip()
        if not new_name:
            return None
        return new_name, z_spin.value()

    def _add_layer(self):
        from config.models import StageLayer
        result = self._layer_dialog("Add Stage Layer")
        if result is None:
            return
        name, z_height = result
        if self.config.get_stage_layer(name) is not None:
            QtWidgets.QMessageBox.warning(
                self, "Layer Exists", f"A layer named '{name}' already exists."
            )
            return
        self.config.stage_layers.append(StageLayer(name=name, z_height=z_height))
        self._refresh_layer_list()

    def _selected_layer(self):
        item = self.layer_list.currentItem()
        if item is None:
            return None
        return self.config.get_stage_layer(item.data(Qt.ItemDataRole.UserRole))

    def _edit_layer(self):
        """Rename a layer and/or move it to another height.

        Moving the layer moves everything on it: all assigned fixtures
        get the new height (the truss goes up, the lamps go with it).
        """
        layer = self._selected_layer()
        if layer is None:
            return
        result = self._layer_dialog("Edit Stage Layer", layer.name, layer.z_height)
        if result is None:
            return
        new_name, new_z = result
        if new_name != layer.name and self.config.get_stage_layer(new_name) is not None:
            QtWidgets.QMessageBox.warning(
                self, "Layer Exists", f"A layer named '{new_name}' already exists."
            )
            return

        old_name = layer.name
        z_changed = new_z != layer.z_height
        layer.name = new_name
        layer.z_height = new_z
        for fixture in self.config.fixtures:
            if fixture.layer == old_name:
                fixture.layer = new_name
                if z_changed:
                    fixture.z = new_z
                    fixture.z_uses_group_default = False

        self._refresh_layer_list()
        self.stage_view.update_from_config()
        self._notify_tcp_update()
        self._broadcast_visualizer_refresh()

    def _remove_layer(self):
        """Delete a layer. Fixtures on it lose the assignment but keep
        their current height."""
        layer = self._selected_layer()
        if layer is None:
            return
        assigned = sum(1 for f in self.config.fixtures if f.layer == layer.name)
        if assigned:
            reply = QtWidgets.QMessageBox.question(
                self, "Remove Layer?",
                f"'{layer.name}' has {assigned} fixture(s) assigned.\n\n"
                "Remove the layer? The fixtures keep their height but lose "
                "the layer assignment.",
                QtWidgets.QMessageBox.StandardButton.Yes |
                QtWidgets.QMessageBox.StandardButton.No
            )
            if reply != QtWidgets.QMessageBox.StandardButton.Yes:
                return
        for fixture in self.config.fixtures:
            if fixture.layer == layer.name:
                fixture.layer = ""
        self.config.stage_layers.remove(layer)
        self._refresh_layer_list()
        self.stage_view.update_from_config()
        self._notify_tcp_update()
        self._broadcast_visualizer_refresh()

    def _on_show_axes_changed(self, state):
        """Handle show orientation axes checkbox change.

        Toggling a class-level attribute doesn't dirty any individual
        QGraphicsItem, so ``viewport().update()`` alone wasn't
        reliably getting the items to re-paint in the live app — each
        item keeps its own bounding-rect-based dirty tracking and
        treats itself as "still clean" when nothing about *itself*
        changed. Calling ``item.update()`` on every fixture is the
        canonical way to force a per-item repaint; ``scene.update()``
        adds the viewport-level invalidation as defence in depth.
        """
        FixtureItem.show_orientation_axes = bool(state)
        scene = self.stage_view.scene
        for item in scene.items():
            item.update()
        scene.update()

    def _on_set_orientation_requested(self, fixture_items: list):
        """Handle right-click "Set Orientation" — re-bind the inline panel.

        Replaces the legacy modal flow. The persistent OrientationPanel in
        the right-side splitter rebinds to the selected fixtures and live-
        edits write through via :meth:`_on_inline_orientation_changed`.
        """
        if not fixture_items:
            return
        self._inline_orientation_fixtures = list(fixture_items)
        self.orientation_panel.set_fixtures(self._inline_orientation_fixtures)

    def _on_stage_selection_changed(self):
        """Re-bind the inline orientation panel to whatever fixtures are
        currently selected on the 2D StageView. Empty selection → panel
        shows "No fixture selected" and disables its inputs.
        """
        selected = [
            item for item in self.stage_view.scene.selectedItems()
            if isinstance(item, FixtureItem)
        ]
        self._inline_orientation_fixtures = selected
        self.orientation_panel.set_fixtures(selected)

    def _on_inline_orientation_changed(self):
        """Slot fired by OrientationPanel.values_changed — push edits live
        to the currently-bound fixtures, the config, and any group default."""
        fixture_items = getattr(self, "_inline_orientation_fixtures", None)
        if not fixture_items:
            return
        values = self.orientation_panel.get_orientation_values()
        self._apply_orientation_to_fixtures(fixture_items, values)

    def _open_orientation_dialog(self):
        """Modal-dialog fallback. No longer wired to the right-click flow,
        but kept for any future multi-edit-confirm path that wants Apply/
        Cancel semantics."""
        fixture_items = getattr(self, '_pending_orientation_fixtures', None)
        if not fixture_items:
            return

        self._pending_orientation_fixtures = None

        dialog = OrientationDialog(fixture_items, self.config, self)
        if dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            self._apply_orientation_to_fixtures(fixture_items, dialog.get_orientation_values())

    def _apply_orientation_to_fixtures(self, fixture_items: list, values: dict) -> None:
        """Write a values dict (mounting, yaw, pitch, roll, z_height,
        apply_to_group) back to the fixture items, the config, and group
        defaults if requested. Shared by the inline panel and the modal."""
        for fixture_item in fixture_items:
            fixture_item.mounting = values['mounting']
            fixture_item.rotation_angle = values['yaw']  # yaw maps to rotation_angle
            fixture_item.pitch = values['pitch']
            fixture_item.roll = values['roll']
            fixture_item.z_height = values['z_height']
            fixture_item.orientation_uses_group_default = False
            fixture_item.z_uses_group_default = False
            fixture_item.update()

            if self.config:
                config_fixture = next(
                    (f for f in self.config.fixtures if f.name == fixture_item.fixture_name),
                    None
                )
                if config_fixture:
                    config_fixture.mounting = values['mounting']
                    config_fixture.yaw = values['yaw']
                    config_fixture.pitch = values['pitch']
                    config_fixture.roll = values['roll']
                    config_fixture.z = values['z_height']
                    config_fixture.orientation_uses_group_default = False
                    config_fixture.z_uses_group_default = False

        if values.get('apply_to_group') and self.config:
            groups = set(f.group for f in fixture_items if hasattr(f, 'group') and f.group)
            selected_fixture_names = {f.fixture_name for f in fixture_items}

            for group_name in groups:
                if group_name in self.config.groups:
                    group = self.config.groups[group_name]
                    group.default_mounting = values['mounting']
                    group.default_yaw = values['yaw']
                    group.default_pitch = values['pitch']
                    group.default_roll = values['roll']
                    group.default_z_height = values['z_height']

                    for config_fixture in self.config.fixtures:
                        if (config_fixture.group == group_name and
                                config_fixture.name not in selected_fixture_names):
                            if config_fixture.orientation_uses_group_default:
                                config_fixture.mounting = values['mounting']
                                config_fixture.yaw = values['yaw']
                                config_fixture.pitch = values['pitch']
                                config_fixture.roll = values['roll']
                            if config_fixture.z_uses_group_default:
                                config_fixture.z = values['z_height']

                            if config_fixture.name in self.stage_view.fixtures:
                                stage_item = self.stage_view.fixtures[config_fixture.name]
                                if config_fixture.orientation_uses_group_default:
                                    stage_item.mounting = values['mounting']
                                    stage_item.rotation_angle = values['yaw']
                                    stage_item.pitch = values['pitch']
                                    stage_item.roll = values['roll']
                                if config_fixture.z_uses_group_default:
                                    stage_item.z_height = values['z_height']
                                stage_item.update()

        self.stage_view.save_positions_to_config()
        self._notify_tcp_update()
        self._broadcast_visualizer_refresh()

    def _refresh_embedded_visualizer(self) -> None:
        """Push the latest config to the embedded 3D preview. Cheap to call
        repeatedly — RenderEngine batches GL state internally."""
        if hasattr(self, "embedded_visualizer") and self.embedded_visualizer is not None:
            self.embedded_visualizer.set_config(self.config)

    def _broadcast_visualizer_refresh(self) -> None:
        """Ask MainWindow to refresh every embedded visualizer (Stage,
        Shows, Live). Used after stage edits / fixture moves so all
        three 3D previews stay in sync — without it, only Stage tab's
        preview tracks edits made on the 2D Stage view, and the Shows /
        Live previews go stale until the user manually activates them.

        Falls back to a local-only refresh if MainWindow doesn't expose
        the central method (e.g. tab being driven from a test harness).
        """
        main_window = self.window()
        broadcast = getattr(main_window, "on_visualizer_config_changed", None)
        if callable(broadcast):
            broadcast()
        else:
            self._refresh_embedded_visualizer()
