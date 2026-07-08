# gui/gui.py
# Refactored MainWindow using tab components

import os
import sys
from PyQt6 import QtWidgets
from PyQt6.QtWidgets import QMainWindow, QFileDialog, QMessageBox
from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtGui import QUndoStack, QKeySequence, QAction
from config.models import Configuration
from utils.create_workspace import create_qlc_workspace
from gui.Ui_MainWindow import Ui_MainWindow
from gui.tabs import (ConfigurationTab, FixturesTab, AutoTab, ShowsTab,
                       StageTab, StructureTab)
from gui.audio_settings_dialog import AudioSettingsDialog
from gui.dialogs.workspace_options_dialog import WorkspaceOptionsDialog
from gui.progress_manager import ProgressManager, set_progress_manager
from timeline_ui.riff_browser_widget import RiffBrowserWidget
from riffs.riff_library import RiffLibrary


class MainWindow(QMainWindow, Ui_MainWindow):
    """Main application window with tab-based architecture

    Orchestrates tab components and handles application-level operations:
    - File operations (save/load configuration)
    - Workspace import/export
    - Cross-tab coordination
    - Toolbar and menu actions
    """

    def __init__(self):
        super().__init__()

        # Initialize configuration
        self.config = Configuration()

        # Set up UI from designer file
        self.setupUi(self)

        # Initialize paths
        self._initialize_paths()

        # Create and integrate tab components
        self._create_tabs()

        # Connect application-level signals
        self._connect_signals()

        # Set up status indicator timer
        self._setup_status_timer()

        # Initialize progress manager
        self.progress_manager = ProgressManager(self)
        set_progress_manager(self.progress_manager)

        # Initialize undo stack
        self._create_undo_stack()

        # With no menubar, actions living only in the overflow popup
        # would never fire their shortcuts; re-register them all on the
        # window (must run after every menu exists, incl. Edit/Render).
        from gui.widgets.topbar import register_menu_shortcuts
        register_menu_shortcuts(self, self.overflow_menu)

        # Initial statusbar hint (tab changes keep it current after this).
        self._update_status_hint(self.tabWidget.currentIndex())

    def _update_status_hint(self, index: int) -> None:
        """Show the current screen's contextual hint in the statusbar."""
        from gui.widgets.topbar import screen_hints
        hint = screen_hints().get(index)
        if hint and hasattr(self, "status_hint"):
            self.status_hint.setText(hint)

    def _setup_status_timer(self):
        """Set up timer for updating toolbar status indicators."""
        self.status_timer = QTimer()
        self.status_timer.timeout.connect(self._update_toolbar_status)
        self.status_timer.start(1000)  # Update every second
        # Initial update
        self._update_toolbar_status()

    def _update_toolbar_status(self):
        """Update ArtNet and TCP status indicators in the topbar.

        Drives the QSS dynamic-property selectors (`status="off"|"on"|"active"|"ready"`)
        rather than re-applying inline stylesheets, so the active theme stays
        in charge of the actual colors. Also refreshes the topbar's
        filename readout (config basename + dirty marker) on the same
        1 s tick.
        """
        if hasattr(self, 'topbar'):
            if getattr(self, 'config_path', None):
                name = os.path.basename(self.config_path)
                if self.windowTitle().endswith(" *"):
                    name += " *"
            else:
                # Reference screen 01: the filename slot reads
                # "no project loaded" until a project exists.
                name = "no project loaded"
            self.topbar.set_filename(name)
            # Keep the Home checklist live while the user works.
            if hasattr(self, 'home_screen') and self.home_screen.isVisible():
                self.home_screen.refresh_checklist(self.config)
        # ArtNet
        artnet_controller = getattr(self.shows_tab, 'artnet_controller', None)
        artnet_enabled = getattr(self.shows_tab, 'artnet_enabled', False)
        if artnet_controller and artnet_enabled:
            self.artnet_status_indicator.setText("ON")
            self._set_status(self.artnet_status_indicator, "on")
            self._set_status(self.artnet_toggle_btn, "on")
            self.artnet_status_indicator.setToolTip("ArtNet DMX Output: Enabled")
            self.artnet_toggle_btn.setToolTip("Click to disable ArtNet")
        else:
            self.artnet_status_indicator.setText("OFF")
            self._set_status(self.artnet_status_indicator, "off")
            self._set_status(self.artnet_toggle_btn, "off")
            self.artnet_status_indicator.setToolTip("ArtNet DMX Output: Disabled")
            self.artnet_toggle_btn.setToolTip("Click to enable ArtNet")

        # TCP visualizer server
        tcp_server = getattr(self.shows_tab, 'tcp_server', None)
        if tcp_server and tcp_server.is_running():
            client_count = tcp_server.get_client_count()
            if client_count > 0:
                self.tcp_status_indicator.setText(f"{client_count}")
                self._set_status(self.tcp_status_indicator, "active")
                self._set_status(self.tcp_toggle_btn, "active")
                self.tcp_status_indicator.setToolTip(
                    f"TCP Visualizer Server: {client_count} client(s) connected"
                )
            else:
                self.tcp_status_indicator.setText("ON")
                self._set_status(self.tcp_status_indicator, "ready")
                self._set_status(self.tcp_toggle_btn, "ready")
                self.tcp_status_indicator.setToolTip("TCP Visualizer Server: Running, no clients")
            self.tcp_toggle_btn.setToolTip("Click to stop Visualizer Server")
        else:
            self.tcp_status_indicator.setText("OFF")
            self._set_status(self.tcp_status_indicator, "off")
            self._set_status(self.tcp_toggle_btn, "off")
            self.tcp_status_indicator.setToolTip("TCP Visualizer Server: Not running")
            self.tcp_toggle_btn.setToolTip("Click to start Visualizer Server")

    def _set_status(self, widget, value):
        """Set the `status` dynamic property on a widget and re-polish so QSS
        selectors keyed off it (e.g. ``QLabel[status="on"]``) re-evaluate."""
        widget.setProperty("status", value)
        style = widget.style()
        if style:
            style.unpolish(widget)
            style.polish(widget)

    def _start_screensaver(self):
        """View > Screensaver (North Star 11a). Manual trigger for now;
        idle / LIVE-pause activation arrives with the Live milestones."""
        from gui.screens.screensaver import ScreensaverWindow
        self._screensaver = ScreensaverWindow()
        self._screensaver.dismissed.connect(
            lambda: setattr(self, "_screensaver", None))
        self._screensaver.activate()

    def _toggle_fullscreen(self):
        """F11 — switch between fullscreen and the previous (maximized) state."""
        if self.isFullScreen():
            self.showMaximized()
            self.actionToggleFullscreen.setChecked(False)
        else:
            self.showFullScreen()
            self.actionToggleFullscreen.setChecked(True)

    def _set_theme(self, name: str):
        """Apply and persist the selected theme (View > Theme).

        This is the ONLY place a theme choice is persisted - apply()
        itself deliberately doesn't save, so test runs and startup can
        never overwrite the user's saved theme."""
        from gui.theme_manager import ThemeManager
        manager = ThemeManager()
        manager.apply(QtWidgets.QApplication.instance(), name)
        manager.set_current(name)
        # Force the toolbar-status pills to re-evaluate their dynamic props
        # against the new theme, and re-rasterize the topbar line icons
        # in the new theme's color.
        self._update_toolbar_status()
        self.apply_shell_icons(name)

    def _toggle_artnet(self):
        """Toggle ArtNet output via shows tab."""
        if hasattr(self.shows_tab, 'toggle_artnet'):
            self.shows_tab.toggle_artnet()
            self._update_toolbar_status()

    def _toggle_tcp(self):
        """Toggle TCP server via shows tab."""
        if hasattr(self.shows_tab, 'toggle_tcp'):
            # Check if we're about to enable TCP (currently disabled)
            tcp_enabled = getattr(self.shows_tab, 'tcp_enabled', False)

            if not tcp_enabled:
                # We're enabling TCP - check if visualizer is running
                self.shows_tab.toggle_tcp()
                self._update_toolbar_status()

                # Check if visualizer is connected after a short delay
                # If no clients, offer to launch visualizer
                tcp_server = getattr(self.shows_tab, 'tcp_server', None)
                if tcp_server and tcp_server.is_running():
                    if tcp_server.get_client_count() == 0:
                        # No visualizer connected, ask to launch
                        reply = QMessageBox.question(
                            self,
                            "Launch Visualizer?",
                            "The TCP server is now running but no Visualizer is connected.\n\n"
                            "Would you like to launch the Visualizer?",
                            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                            QMessageBox.StandardButton.Yes
                        )
                        if reply == QMessageBox.StandardButton.Yes:
                            self._launch_visualizer()
            else:
                # We're disabling TCP
                self.shows_tab.toggle_tcp()
                self._update_toolbar_status()

    def _launch_visualizer(self):
        """Launch the 3D Visualizer application."""
        # Use stage_tab's launch functionality if available
        if hasattr(self.stage_tab, '_launch_visualizer'):
            self.stage_tab._launch_visualizer()
        else:
            # Fallback: launch directly
            import subprocess
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            visualizer_path = os.path.join(project_root, "visualizer", "main.py")

            if os.path.exists(visualizer_path):
                try:
                    subprocess.Popen(
                        [sys.executable, visualizer_path],
                        cwd=project_root
                    )
                    print("Visualizer launched")
                except Exception as e:
                    QMessageBox.critical(
                        self,
                        "Launch Error",
                        f"Failed to launch Visualizer:\n{str(e)}"
                    )

    def _initialize_paths(self):
        """Initialize project paths"""
        self.project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.setup_dir = os.path.join(self.project_root, "setup")
        self.config_path = None

    def _create_tabs(self):
        """Create and integrate tab components"""
        # Create tab instances with shared configuration
        self.config_tab = ConfigurationTab(self.config, self)
        self.fixtures_tab = FixturesTab(self.config, self)
        self.stage_tab = StageTab(self.config, self)
        self.structure_tab = StructureTab(self.config, self)
        self.shows_tab = ShowsTab(self.config, self)
        self.auto_tab = AutoTab(self.config, self)

        # Replace placeholder tabs with actual tab widgets
        # The tab widget structure is created in Ui_MainWindow
        # We need to replace the placeholder widgets

        # Configuration tab (tab_config)
        layout = self.tab_config.layout()
        if layout:
            # Clear existing widgets
            while layout.count():
                item = layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
            layout.deleteLater()

        # Set the config_tab as the layout/content
        new_layout = QtWidgets.QVBoxLayout(self.tab_config)
        new_layout.setContentsMargins(0, 0, 0, 0)
        new_layout.addWidget(self.config_tab)

        # Fixtures tab (tab)
        layout = self.tab.layout()
        if layout:
            while layout.count():
                item = layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
            layout.deleteLater()

        new_layout = QtWidgets.QVBoxLayout(self.tab)
        new_layout.setContentsMargins(0, 0, 0, 0)
        new_layout.addWidget(self.fixtures_tab)

        # Stage tab (tab_stage) - already has StageView, update it
        # Stage tab already has a layout from setupStageTab, we'll replace it entirely
        if self.tab_stage.layout():
            old_layout = self.tab_stage.layout()
            while old_layout.count():
                item = old_layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
            old_layout.deleteLater()

        new_layout = QtWidgets.QVBoxLayout(self.tab_stage)
        new_layout.setContentsMargins(0, 0, 0, 0)
        new_layout.addWidget(self.stage_tab)

        # Structure tab (tab_structure)
        layout = self.tab_structure.layout()
        if layout:
            while layout.count():
                item = layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
            layout.deleteLater()

        new_layout = QtWidgets.QVBoxLayout(self.tab_structure)
        new_layout.setContentsMargins(0, 0, 0, 0)
        new_layout.addWidget(self.structure_tab)

        # Shows tab (tab_2)
        layout = self.tab_2.layout()
        if layout:
            while layout.count():
                item = layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
            layout.deleteLater()

        new_layout = QtWidgets.QVBoxLayout(self.tab_2)
        new_layout.setContentsMargins(0, 0, 0, 0)
        new_layout.addWidget(self.shows_tab)

        # Auto tab (tab_auto)
        layout = self.tab_auto.layout()
        if layout:
            while layout.count():
                item = layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
            layout.deleteLater()

        new_layout = QtWidgets.QVBoxLayout(self.tab_auto)
        new_layout.setContentsMargins(0, 0, 0, 0)
        new_layout.addWidget(self.auto_tab)

        # Create Riff Browser dockable panel
        self._create_riff_browser()

    def _create_riff_browser(self):
        """Create the riff browser dockable panel."""
        # Initialize riff library
        self.riff_library = RiffLibrary()

        # Create riff browser widget
        self.riff_browser = RiffBrowserWidget(self.riff_library, self)

        # Add as dock widget on the right side
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.riff_browser)

        # Start hidden - will be shown when Shows tab is activated
        self.riff_browser.hide()

        # Track collapsed state for persistence across tab switches
        self._riff_browser_collapsed = False

    def _create_undo_stack(self):
        """Create the undo/redo stack and Edit menu."""
        # Create undo stack
        self.undo_stack = QUndoStack(self)

        # Create Edit menu if it doesn't exist
        if not hasattr(self, 'menuEdit'):
            self.menuEdit = QtWidgets.QMenu("Edit", parent=self)
            # Insert Edit menu after File menu (before Settings menu)
            self.overflow_menu.insertMenu(self.menuSettings.menuAction(), self.menuEdit)

        # Create undo action
        self.undo_action = self.undo_stack.createUndoAction(self, "Undo")
        self.undo_action.setShortcut(QKeySequence.StandardKey.Undo)
        self.undo_action.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
        self.menuEdit.addAction(self.undo_action)

        # Create redo action
        self.redo_action = self.undo_stack.createRedoAction(self, "Redo")
        self.redo_action.setShortcut(QKeySequence.StandardKey.Redo)
        self.redo_action.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
        self.menuEdit.addAction(self.redo_action)

        # Connect clean state changed for save indicator (optional)
        self.undo_stack.cleanChanged.connect(self._on_undo_clean_changed)

    def _on_undo_clean_changed(self, clean: bool):
        """Handle undo stack clean state change.

        Can be used to show unsaved changes indicator.
        """
        # Update window title to show unsaved state
        title = self.windowTitle()
        if clean:
            if title.endswith(" *"):
                self.setWindowTitle(title[:-2])
        else:
            if not title.endswith(" *"):
                self.setWindowTitle(title + " *")

    def get_undo_stack(self) -> QUndoStack:
        """Get the application's undo stack."""
        return self.undo_stack

    def _connect_signals(self):
        """Connect application-level signals"""
        # Toolbar actions
        self.saveAction.triggered.connect(self.save_configuration)
        self.loadAction.triggered.connect(self.load_configuration)
        self.importWorkspaceAction.triggered.connect(self.import_workspace)
        self.createWorkspaceAction.triggered.connect(self.create_workspace)

        # Status toggle button clicks
        self.artnet_toggle_btn.clicked.connect(self._toggle_artnet)
        self.tcp_toggle_btn.clicked.connect(self._toggle_tcp)

        # File menu actions
        self.actionSaveConfig.triggered.connect(self.save_configuration)
        self.actionSaveConfigAs.triggered.connect(self.save_configuration_as)
        self.actionLoadConfig.triggered.connect(self.load_configuration)
        self.actionImportShowStructure.triggered.connect(self.import_show_structure_file)
        self.actionExportShowStructure.triggered.connect(self.export_show_structure_file)
        self.actionImportFixtureList.triggered.connect(self.import_fixture_list_file)
        self.actionExportFixtureList.triggered.connect(self.export_fixture_list_file)
        self.actionImportShowsFromConfig.triggered.connect(self.import_shows_from_config_file)
        self.actionNewFromTemplate.triggered.connect(self.new_from_template)
        self.actionImportWorkspace.triggered.connect(self.import_workspace)
        self.actionCreateWorkspace.triggered.connect(self.create_workspace)
        self.actionExit.triggered.connect(self.close)

        # Tab change handler
        self.tabWidget.currentChanged.connect(self._on_tab_changed)

        # Settings menu actions
        self.actionAudioSettings.triggered.connect(self.open_audio_settings)

        # View menu actions
        self.actionToggleFullscreen.triggered.connect(self._toggle_fullscreen)
        self.actionScreensaver.triggered.connect(self._start_screensaver)
        self.actionThemeDark.triggered.connect(lambda: self._set_theme("dark"))
        self.actionThemeLight.triggered.connect(lambda: self._set_theme("light"))
        # Reflect the active theme in the menu's check state.
        from gui.theme_manager import ThemeManager
        active = ThemeManager().current() or "dark"
        if active == "light":
            self.actionThemeLight.setChecked(True)
        else:
            self.actionThemeDark.setChecked(True)

        # Render menu (insert before Help)
        self.menuRender = QtWidgets.QMenu("Render", parent=self)
        self.overflow_menu.insertMenu(self.menuHelp.menuAction(), self.menuRender)
        self.actionRenderToVideo = QAction("Render Show to Video...", self)
        self.menuRender.addAction(self.actionRenderToVideo)
        self.actionRenderToVideo.triggered.connect(self.render_to_video)

        # Ctrl+L focuses the embedded Auto tab (index 5) — the auto-DJ
        # audio-reactive lighting mode. Was originally a separate "Live
        # Mode" window opened from a "Live" menu before being folded in
        # as the sixth tab. Renamed from "Live" to "Auto" since the
        # engine is the auto-generation pipeline driven by live audio
        # rather than a generic "live mode".
        self.actionGotoAuto = QAction("Auto Mode", self)
        self.actionGotoAuto.setShortcut("Ctrl+L")
        self.actionGotoAuto.triggered.connect(
            lambda: self.tabWidget.setCurrentIndex(5)
        )
        self.addAction(self.actionGotoAuto)

        # Help menu actions
        self.actionOpenLogFolder.triggered.connect(self.open_log_folder)
        self.actionAbout.triggered.connect(self.show_about)

        # Home screen quick actions + recents + checklist
        self.home_screen.new_from_template_requested.connect(self.new_from_template)
        self.home_screen.open_requested.connect(self.load_configuration)
        self.home_screen.recent_requested.connect(self.open_recent_config)
        self.home_screen.go_to_screen.connect(self.tabWidget.setCurrentIndex)
        from utils.app_settings import recent_configs
        self.home_screen.refresh(recent_configs())
        self.home_screen.refresh_checklist(self.config)

    def _on_tab_changed(self, index):
        """Handle tab change - notify tabs of activation/deactivation."""
        try:

            # Map tab indices to tab widgets (check actual attribute names)
            tab_map = {}

            # Try to get the actual tab widgets
            if hasattr(self, 'config_tab'):
                tab_map[0] = self.config_tab
            if hasattr(self, 'fixtures_tab'):
                tab_map[1] = self.fixtures_tab
            if hasattr(self, 'stage_tab'):
                tab_map[2] = self.stage_tab
            if hasattr(self, 'structure_tab'):
                tab_map[3] = self.structure_tab
            if hasattr(self, 'shows_tab'):
                tab_map[4] = self.shows_tab
            if hasattr(self, 'auto_tab'):
                tab_map[5] = self.auto_tab

            # Call on_tab_deactivated on the previous tab
            if hasattr(self, '_current_tab_index') and self._current_tab_index in tab_map:
                prev_tab = tab_map[self._current_tab_index]
                if prev_tab and hasattr(prev_tab, 'on_tab_deactivated'):
                    prev_tab.on_tab_deactivated()

            # Store current tab index
            self._current_tab_index = index

            # Call on_tab_activated on the newly activated tab
            if index in tab_map:
                tab = tab_map[index]
                if tab and hasattr(tab, 'on_tab_activated'):
                    tab.on_tab_activated()

            # Show/hide riff browser based on tab (only visible in Shows tab = index 4)
            self._update_riff_browser_visibility(index)

            # Contextual statusbar hint for the new screen.
            self._update_status_hint(index)

        except Exception as e:
            print(f"ERROR in _on_tab_changed: {e}")
            import traceback
            traceback.print_exc()

    def _update_riff_browser_visibility(self, tab_index: int):
        """Show or hide the global riff-browser dock based on the current
        tab.

        The Shows tab now hosts an inline ``RiffBrowserPanel`` under the
        embedded visualizer (see ``shows_tab.setup_ui``), so the global
        dock would just be a duplicate when the user is on Shows. Keep
        the dock hidden in that case. No other tab uses the riff browser
        today, so the dock effectively stays hidden across the whole app
        — it sticks around only as a reusable home if a future tab wants
        a free-floating one.
        """
        if not hasattr(self, 'riff_browser'):
            return
        # Save the collapsed state if the dock was visible, then hide.
        if self.riff_browser.isVisible():
            self._riff_browser_collapsed = self.riff_browser.is_collapsed()
        self.riff_browser.hide()

    def on_groups_changed(self):
        """Coordinate updates when fixture groups change

        Called by FixturesTab when groups are modified.
        Propagates changes to dependent tabs (Stage, Structure, and Shows).
        """
        self.stage_tab.update_from_config()
        self.structure_tab.update_from_config()
        # Use lightweight update for shows tab - only update lane group combos
        # instead of recreating all lanes (major performance improvement)
        self.shows_tab.update_fixture_groups_only()
        # Auto tab's embedded visualizer otherwise wouldn't see new
        # fixtures until the user manually activates the tab — push the
        # current config now so its 3D preview stays in sync.
        self.on_visualizer_config_changed()

    def on_visualizer_config_changed(self):
        """Refresh every embedded 3D preview with the current config.

        Stage / Shows / Auto each own their own ``EmbeddedVisualizer``
        and historically each tab refreshed only its own on its own
        triggers — so changing stage dimensions in Stage tab left the
        Shows/Auto previews stale, and adding fixtures in Fixtures tab
        left Auto's preview stale, until the user manually activated
        the affected tab.

        This central push is called from any place that mutates the
        config in a way the previews care about: stage dims, fixture
        moves, fixture add/remove. ``EmbeddedVisualizer.set_config`` is
        idempotent and cheap (RenderEngine batches GL state internally),
        so calling it on every tab on every change is fine.
        """
        for tab_attr in ("stage_tab", "shows_tab", "auto_tab"):
            tab = getattr(self, tab_attr, None)
            if tab is None:
                continue
            vis = getattr(tab, "embedded_visualizer", None)
            if vis is None:
                continue
            try:
                vis.set_config(self.config)
            except Exception as e:
                # Don't let one tab's visualizer failure block the
                # others — log and keep going.
                print(f"{tab_attr} embedded visualizer refresh failed: {e}")

    def on_show_selected(self, show_name: str, source_tab: str):
        """Coordinate show selection across tabs.

        Called when a show is selected in either Structure or Shows tab.
        Syncs the selection to the other tab.

        Args:
            show_name: Name of the selected show
            source_tab: Which tab triggered the selection ('structure' or 'shows')
        """
        if source_tab == 'shows':
            # Update structure tab to match
            if self.structure_tab.show_combo.currentText() != show_name:
                self.structure_tab.show_combo.blockSignals(True)
                self.structure_tab.show_combo.setCurrentText(show_name)
                self.structure_tab.show_combo.blockSignals(False)
                self.structure_tab._load_show(show_name)
        elif source_tab == 'structure':
            # Update shows tab to match - refresh combo first so new shows appear
            self.shows_tab.show_combo.blockSignals(True)
            current = self.shows_tab.show_combo.currentText()
            self.shows_tab.show_combo.clear()
            self.shows_tab.show_combo.addItems(sorted(self.config.shows.keys()))
            self.shows_tab.show_combo.setCurrentText(show_name)
            self.shows_tab.show_combo.blockSignals(False)
            # Use _load_show directly, not _on_show_changed: the latter would
            # call parent().on_show_selected('shows') and bounce right back
            # to update the Structure tab again, infinite loop.
            self.shows_tab._load_show(show_name)

    def save_configuration(self):
        """Save configuration to YAML file"""
        try:
            # Save all tabs to configuration
            self.config_tab.save_to_config()
            self.fixtures_tab.save_to_config()
            self.stage_tab.save_to_config()
            self.structure_tab.save_to_config()
            self.shows_tab.save_to_config()

            # Prompt for file path if not set
            if not self.config_path:
                file_path, _ = QFileDialog.getSaveFileName(
                    self,
                    "Save Configuration",
                    "",
                    "YAML Files (*.yaml);;All Files (*)"
                )
                if not file_path:
                    return
                self.config_path = file_path

            # Save configuration
            self.config.save(self.config_path)
            self._record_recent_config(self.config_path)
            QMessageBox.information(
                self,
                "Success",
                f"Configuration saved to {self.config_path}"
            )
            print(f"Configuration saved to {self.config_path}")

        except Exception as e:
            QMessageBox.critical(
                self,
                "Error",
                f"Failed to save configuration: {str(e)}"
            )
            print(f"Error saving configuration: {e}")
            import traceback
            traceback.print_exc()

    def _record_recent_config(self, path: str) -> None:
        """Track a config for the Home screen recents and refresh it
        (including the FROM ZERO TO SHOW checklist states)."""
        from utils.app_settings import recent_configs, record_recent_config
        try:
            record_recent_config(path)
            if hasattr(self, "home_screen"):
                self.home_screen.refresh(recent_configs())
                self.home_screen.refresh_checklist(self.config)
        except Exception as e:
            print(f"recent configs: {e}")

    def open_recent_config(self, path: str):
        """Open a config picked from the Home screen recent list."""
        if not os.path.isfile(path):
            QMessageBox.warning(self, "File missing",
                                f"The file no longer exists:\n{path}")
            self._record_recent_config(self.config_path or "")
            return
        # Same deferred load flow as File -> Load Configuration.
        self._pending_config_path = path
        from PyQt6.QtWidgets import QApplication
        dialog = self.progress_manager.start_modal(
            "Loading Configuration", "Opening file...", maximum=8)
        for _ in range(5):
            QApplication.processEvents()
        if dialog:
            dialog.repaint()
            QApplication.processEvents()
        QTimer.singleShot(100, self._do_load_configuration)

    def save_configuration_as(self):
        """Save configuration to a new YAML file (always prompts for location)"""
        try:
            # Save all tabs to configuration
            self.config_tab.save_to_config()
            self.fixtures_tab.save_to_config()
            self.stage_tab.save_to_config()
            self.structure_tab.save_to_config()
            self.shows_tab.save_to_config()

            # Always prompt for file path
            default_dir = os.path.dirname(self.config_path) if self.config_path else ""
            file_path, _ = QFileDialog.getSaveFileName(
                self,
                "Save Configuration As",
                default_dir,
                "YAML Files (*.yaml);;All Files (*)"
            )
            if not file_path:
                return

            # Update the current config path to the new location
            self.config_path = file_path

            # Save configuration
            self.config.save(self.config_path)
            self._record_recent_config(self.config_path)
            QMessageBox.information(
                self,
                "Success",
                f"Configuration saved to {self.config_path}"
            )
            print(f"Configuration saved to {self.config_path}")

        except Exception as e:
            QMessageBox.critical(
                self,
                "Error",
                f"Failed to save configuration: {str(e)}"
            )
            print(f"Error saving configuration: {e}")
            import traceback
            traceback.print_exc()

    def new_from_template(self):
        """File -> New from Template: start a project from a starter rig.

        Copy-then-open, never open-in-place: the chosen template (rig
        only, or rig + demo show + audio) is copied to a user-picked
        location and THAT file becomes the project, so Ctrl+S can never
        overwrite a bundled template or write into the install dir.
        """
        from utils.templates import list_templates, instantiate_template

        templates = list_templates()
        if not templates:
            QMessageBox.warning(
                self, "No Templates",
                "No starter rigs found (demos/rigs/ is missing)."
            )
            return

        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("New Project from Template")
        dialog.resize(560, 380)
        layout = QtWidgets.QVBoxLayout(dialog)

        layout.addWidget(QtWidgets.QLabel("Choose a starter rig:"))
        template_list = QtWidgets.QListWidget()
        for template in templates:
            item = QtWidgets.QListWidgetItem(
                f"{template.name}  ({template.fixture_count} fixtures)\n"
                f"    {template.description}"
            )
            item.setData(Qt.ItemDataRole.UserRole, template)
            template_list.addItem(item)
        template_list.setCurrentRow(0)
        layout.addWidget(template_list)

        include_show_check = QtWidgets.QCheckBox(
            "Include the ready-to-play demo show + audio clip"
        )
        include_show_check.setChecked(True)
        layout.addWidget(include_show_check)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok |
            QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return
        current = template_list.currentItem()
        if current is None:
            return
        template = current.data(Qt.ItemDataRole.UserRole)

        dest_path, _ = QFileDialog.getSaveFileName(
            self,
            "Create Project From Template",
            os.path.join(os.path.expanduser("~"), f"{template.key}.yaml"),
            "YAML Files (*.yaml)"
        )
        if not dest_path:
            return
        if not os.path.splitext(dest_path)[1]:
            dest_path += ".yaml"

        try:
            new_path = instantiate_template(
                template, dest_path,
                include_show=include_show_check.isChecked(),
            )
        except Exception as e:
            QMessageBox.critical(
                self, "Template Failed",
                f"Could not create the project:\n{e}"
            )
            return

        # Open the copy through the normal deferred load flow (progress
        # modal + all-tab refresh), same as File -> Load Configuration.
        self._pending_config_path = new_path
        from PyQt6.QtWidgets import QApplication
        dialog = self.progress_manager.start_modal(
            "Loading Configuration",
            "Opening file...",
            maximum=8
        )
        for _ in range(5):
            QApplication.processEvents()
        if dialog:
            dialog.repaint()
            QApplication.processEvents()
        QTimer.singleShot(100, self._do_load_configuration)

    def load_configuration(self):
        """Load configuration from YAML file"""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Load Configuration",
            "",
            "YAML Files (*.yaml);;All Files (*)"
        )

        if not file_path:
            return

        # Store path for the delayed loader
        self._pending_config_path = file_path

        # Show progress dialog first
        from PyQt6.QtWidgets import QApplication
        from PyQt6.QtCore import QTimer

        dialog = self.progress_manager.start_modal(
            "Loading Configuration",
            "Opening file...",
            maximum=8  # Steps: open, parse, pre-cache, 5 tabs
        )

        # Force the dialog to actually render before starting blocking operations
        for _ in range(5):
            QApplication.processEvents()

        # Force repaint the dialog window
        if dialog:
            dialog.repaint()
            QApplication.processEvents()

        # Use a timer to delay the actual loading, giving the dialog time to fully render
        QTimer.singleShot(100, self._do_load_configuration)

    def _do_load_configuration(self):
        """Perform the actual configuration loading (called after dialog is visible)."""
        from PyQt6.QtWidgets import QApplication, QMessageBox

        try:
            file_path = self._pending_config_path

            # Step 1: Parse YAML
            self.progress_manager.update_modal(1, "Parsing configuration...")
            self.config = Configuration.load(file_path)
            self.config_path = file_path

            # Step 2: Pre-cache fixture definitions
            self.progress_manager.update_modal(2, "Loading fixture definitions...")
            self._preload_fixture_definitions()

            # Step 3-7: Update tabs with progress
            self.progress_manager.update_modal(3, "Updating configuration tab...")
            self.config_tab.config = self.config
            self.config_tab.update_from_config()

            self.progress_manager.update_modal(4, "Updating fixtures tab...")
            self.fixtures_tab.config = self.config
            self.fixtures_tab.schedule_update()

            self.progress_manager.update_modal(5, "Updating stage tab...")
            self.stage_tab.config = self.config
            self.stage_tab.update_from_config()

            self.progress_manager.update_modal(6, "Updating structure tab...")
            self.structure_tab.config = self.config
            self.structure_tab.update_from_config()

            self.progress_manager.update_modal(7, "Loading shows...")
            self.shows_tab.config = self.config
            self.shows_tab.mark_config_dirty()
            self.shows_tab.update_from_config()

            # Auto tab needs the same treatment — its self.config was
            # bound at construction time and stays pointing at the old
            # Configuration instance unless we explicitly rebind it
            # here. Without this the Auto tab keeps showing fixtures
            # from the previous session (or none at all), and its
            # embedded visualizer renders an empty stage even after a
            # config file is loaded.
            self.auto_tab.config = self.config
            self.auto_tab.update_from_config()

            # Push the freshly-loaded config to every embedded 3D
            # preview so all three (Stage / Shows / Auto) repaint with
            # the new fixture set without waiting for the user to
            # activate each tab.
            self.on_visualizer_config_changed()

            self.progress_manager.update_modal(8, "Done")
            self.progress_manager.finish_modal()

            print(f"Configuration loaded from {file_path}")

            # Home screen bookkeeping: remember the file and leave the
            # landing page for the tab pages.
            self._record_recent_config(file_path)
            if hasattr(self, "show_pages"):
                self.show_pages()

            # Legacy-CSV merge prompt. Old configs may have shows on disk in
            # the shows_directory hint that aren't in the YAML (the v1.0
            # cleanup stopped silently re-scanning them on load). Offer a
            # one-shot opt-in to merge them in. User still has to Save to
            # persist.
            self._offer_legacy_csv_merge()

        except Exception as e:
            self.progress_manager.finish_modal()
            print(f"Error loading configuration: {e}")
            import traceback
            traceback.print_exc()

    def _offer_legacy_csv_merge(self):
        """Scan config.shows_directory for *.csv shows not in config.shows.

        If any are found, prompt once. On accept, read each via
        ``utils.show_io.read_show`` and add to ``config.shows`` in memory.
        Skips silently if shows_directory is unset / missing / has no
        unrecognised CSVs.
        """
        shows_dir = getattr(self.config, 'shows_directory', None)
        if not shows_dir or not os.path.isdir(shows_dir):
            return
        try:
            csv_files = [f for f in os.listdir(shows_dir) if f.lower().endswith('.csv')]
        except OSError:
            return
        candidates = []
        for csv_name in csv_files:
            stem = os.path.splitext(csv_name)[0]
            if stem in self.config.shows:
                continue
            candidates.append((stem, os.path.join(shows_dir, csv_name)))
        if not candidates:
            return

        names_preview = ', '.join(stem for stem, _ in candidates[:5])
        more = f' (and {len(candidates) - 5} more)' if len(candidates) > 5 else ''
        reply = QMessageBox.question(
            self,
            "Legacy CSV Shows Found",
            f"Found {len(candidates)} show CSV file(s) in:\n{shows_dir}\n\n"
            f"that aren't in your config.yaml: {names_preview}{more}\n\n"
            "Import them into the config? (You will still need to Save to "
            "persist the result.)",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        from utils.show_io import read_show
        imported = 0
        for stem, path in candidates:
            try:
                show, _ = read_show(path)
                # Use the stem we derived from the filename in case the
                # file's internal name disagrees.
                show.name = stem
                self.config.shows[stem] = show
                imported += 1
            except Exception as e:
                print(f"Skipping {path}: {e}")
        if imported:
            self.structure_tab.update_from_config()
            self.shows_tab.update_from_config()
            QMessageBox.information(
                self, "Shows Imported",
                f"Imported {imported} legacy CSV show(s) into the config.\n"
                "Save the config to persist them."
            )

    def _preload_fixture_definitions(self):
        """Pre-load fixture definitions into cache for faster access."""
        try:
            from utils.fixture_utils import get_cached_fixture_definitions

            # Collect all fixture models from configuration
            models_in_config = set()
            for fixture in self.config.fixtures:
                models_in_config.add((fixture.manufacturer, fixture.model))
            for group in self.config.groups.values():
                for fixture in group.fixtures:
                    models_in_config.add((fixture.manufacturer, fixture.model))

            # Load into cache
            if models_in_config:
                get_cached_fixture_definitions(models_in_config)
                print(f"Pre-loaded {len(models_in_config)} fixture definition(s) into cache")
        except Exception as e:
            print(f"Warning: Could not pre-load fixture definitions: {e}")

    def import_workspace(self):
        """Import configuration from QLC+ workspace file"""
        try:
            file_path, _ = QFileDialog.getOpenFileName(
                self,
                "Import QLC+ Workspace",
                "",
                "QLC+ Workspace (*.qxw);;All Files (*)"
            )

            if not file_path:
                return

            # Show progress dialog
            self.progress_manager.start_modal(
                "Importing Workspace",
                "Parsing QLC+ workspace file...",
                maximum=7  # Steps: import, pre-cache, 5 tabs
            )

            # Import from workspace
            self.progress_manager.update_modal(1, "Importing fixtures and universes...")
            self.config = Configuration.from_workspace(file_path)

            # Pre-load fixture definitions into cache
            self.progress_manager.update_modal(2, "Loading fixture definitions...")
            self._preload_fixture_definitions()

            # Update all tabs — every tab's self.config was bound at
            # construction time, so a fresh Configuration object needs
            # to be propagated explicitly. Auto tab is on the same list
            # as the others; a missing rebind here was the bug behind
            # "Auto tab visualizer doesn't show fixtures after load".
            self.config_tab.config = self.config
            self.fixtures_tab.config = self.config
            self.stage_tab.config = self.config
            self.structure_tab.config = self.config
            self.shows_tab.config = self.config
            self.auto_tab.config = self.config

            # Refresh all tabs
            self.progress_manager.update_modal(3, "Updating Configuration tab...")
            self.config_tab.update_from_config()

            self.progress_manager.update_modal(4, "Updating Fixtures tab...")
            self.fixtures_tab.update_from_config()

            self.progress_manager.update_modal(5, "Updating Stage tab...")
            self.stage_tab.update_from_config()

            self.progress_manager.update_modal(6, "Updating Structure tab...")
            self.structure_tab.update_from_config()

            self.progress_manager.update_modal(7, "Updating Shows tab...")
            self.shows_tab.update_from_config()

            # Auto tab refresh + central visualizer push so all 3D
            # previews repaint with the imported fixture set.
            self.auto_tab.update_from_config()
            self.on_visualizer_config_changed()

            self.progress_manager.finish_modal()

            QMessageBox.information(
                self,
                "Success",
                f"Workspace imported from {file_path}"
            )
            print(f"Workspace imported from {file_path}")

        except Exception as e:
            self.progress_manager.finish_modal()
            QMessageBox.critical(
                self,
                "Error",
                f"Failed to import workspace: {str(e)}"
            )
            print(f"Error importing workspace: {e}")
            import traceback
            traceback.print_exc()

    def import_show_structure_file(self):
        """File -> Import Show Structure: read a .csv or .yaml into the config.

        CSV input: show name comes from the file basename, only ``parts`` are
        populated. YAML input: full show (parts + effects + timeline_data +
        triggers) reconstructed from a self-contained show file.

        If a show with the same name already exists, the user is asked to
        confirm overwrite. The imported show is selected in the Structure
        tab on success.
        """
        from utils.show_io import read_show
        default_dir = self.config.shows_directory or (
            os.path.dirname(self.config_path) if self.config_path else ""
        )
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Import Show Structure",
            default_dir,
            "Show files (*.csv *.yaml *.yml);;CSV (*.csv);;YAML (*.yaml *.yml)"
        )
        if not file_path:
            return
        try:
            show, fmt = read_show(file_path)
        except Exception as e:
            QMessageBox.critical(
                self, "Import Failed",
                f"Could not import {os.path.basename(file_path)}:\n{e}"
            )
            return

        if show.name in self.config.shows:
            reply = QMessageBox.question(
                self, "Overwrite Show?",
                f"A show named '{show.name}' already exists in the config.\n\n"
                "Overwrite it with the imported one?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        self.config.shows[show.name] = show
        # Refresh the Structure tab so the imported show shows up + selects.
        self.structure_tab.update_from_config()
        if hasattr(self.structure_tab, 'show_combo'):
            idx = self.structure_tab.show_combo.findText(show.name)
            if idx >= 0:
                self.structure_tab.show_combo.setCurrentIndex(idx)
        # Remember this directory for the next import/export dialog.
        self.config.shows_directory = os.path.dirname(file_path)

        QMessageBox.information(
            self, "Imported",
            f"Imported show '{show.name}' from {fmt.upper()}.\n"
            f"Save the config to persist it."
        )

    def export_show_structure_file(self):
        """File -> Export Show Structure: write the current show to .csv or .yaml.

        CSV writes the 6-column structure (parts only). YAML writes the full
        show including timeline_data, effects, and triggers. Format is picked
        by the extension of the chosen path.
        """
        from utils.show_io import write_show
        current_name = getattr(self.structure_tab, 'current_show_name', '')
        show = self.config.shows.get(current_name) if current_name else None
        if not show:
            QMessageBox.warning(
                self, "No Show Selected",
                "Open a show in the Structure tab before exporting."
            )
            return
        default_dir = self.config.shows_directory or (
            os.path.dirname(self.config_path) if self.config_path else ""
        )
        default_path = os.path.join(default_dir, f"{show.name}.csv") if default_dir else f"{show.name}.csv"
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Show Structure",
            default_path,
            "CSV (*.csv);;YAML (*.yaml)"
        )
        if not file_path:
            return
        # Auto-append extension if the user didn't type one (Qt's filter
        # selection alone doesn't guarantee it on every platform).
        if not os.path.splitext(file_path)[1]:
            file_path += ".csv"
        try:
            fmt = write_show(file_path, show)
        except Exception as e:
            QMessageBox.critical(
                self, "Export Failed",
                f"Could not export to {os.path.basename(file_path)}:\n{e}"
            )
            return
        self.config.shows_directory = os.path.dirname(file_path)
        QMessageBox.information(
            self, "Exported",
            f"Exported '{show.name}' to {fmt.upper()}:\n{file_path}"
        )

    def import_shows_from_config_file(self):
        """File -> Import Shows from Config: pull selected shows from another
        config.yaml into the current one without swapping the project.

        The picker lists every show in the source config with its part
        count, name conflicts, and any fixture groups this config doesn't
        have. Missing groups are reported, not fixed — those lanes stay
        dormant until re-pointed (retargeting is the v1.4 morphing work).
        Audio files are copied into this config's audiofiles/ bundle.
        """
        from utils.config_merge import list_import_candidates, merge_shows

        default_dir = os.path.dirname(self.config_path) if self.config_path else ""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Import Shows from Config",
            default_dir,
            "Config files (*.yaml *.yml)"
        )
        if not file_path:
            return
        if self.config_path and os.path.abspath(file_path) == os.path.abspath(self.config_path):
            QMessageBox.warning(
                self, "Same Config",
                "That is the currently open config — nothing to import."
            )
            return

        try:
            source = Configuration.load(file_path)
        except Exception as e:
            QMessageBox.critical(
                self, "Import Failed",
                f"Could not load {os.path.basename(file_path)}:\n{e}"
            )
            return
        if not source.shows:
            QMessageBox.warning(
                self, "No Shows",
                f"{os.path.basename(file_path)} contains no shows."
            )
            return

        candidates = list_import_candidates(source, self.config)

        # ── Picker dialog ────────────────────────────────────────────
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle(f"Import Shows from {os.path.basename(file_path)}")
        dialog.resize(520, 420)
        layout = QtWidgets.QVBoxLayout(dialog)

        layout.addWidget(QtWidgets.QLabel("Select the shows to import:"))
        show_list = QtWidgets.QListWidget()
        for candidate in candidates:
            text = f"{candidate.name}  —  {candidate.num_parts} part(s)"
            if candidate.audio_file:
                text += f", audio: {candidate.audio_file}"
            if candidate.name_conflict:
                text += "   [name exists]"
            if candidate.missing_groups:
                text += f"   [missing groups: {', '.join(candidate.missing_groups)}]"
            item = QtWidgets.QListWidgetItem(text)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            item.setData(Qt.ItemDataRole.UserRole, candidate.name)
            show_list.addItem(item)
        layout.addWidget(show_list)

        form = QtWidgets.QFormLayout()
        conflict_combo = QtWidgets.QComboBox()
        conflict_combo.addItem("Rename the imported show", "rename")
        conflict_combo.addItem("Overwrite the existing show", "overwrite")
        conflict_combo.addItem("Skip the imported show", "skip")
        form.addRow("If a show name exists:", conflict_combo)
        copy_audio_check = QtWidgets.QCheckBox("Copy audio files into this config's bundle")
        copy_audio_check.setChecked(True)
        form.addRow(copy_audio_check)
        layout.addLayout(form)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok |
            QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return

        selected = [
            show_list.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(show_list.count())
            if show_list.item(i).checkState() == Qt.CheckState.Checked
        ]
        if not selected:
            return

        results = merge_shows(
            self.config, source, selected,
            on_conflict=conflict_combo.currentData(),
            copy_audio=copy_audio_check.isChecked(),
        )

        # Refresh the Structure tab so the imported shows appear.
        self.structure_tab.update_from_config()

        lines = []
        for r in results:
            if r.action == 'skipped':
                lines.append(f"- {r.source_name}: skipped (name exists)")
                continue
            line = f"- {r.source_name}: {r.action}"
            if r.action == 'renamed':
                line += f" as '{r.final_name}'"
            if r.audio_action == 'copied':
                line += ", audio copied"
            elif r.audio_action == 'not-found':
                line += ", AUDIO FILE NOT FOUND"
            if r.missing_groups:
                line += f", missing groups: {', '.join(r.missing_groups)}"
            lines.append(line)
        imported = sum(1 for r in results if r.action != 'skipped')
        msg = f"Imported {imported} show(s) from {os.path.basename(file_path)}:\n\n"
        msg += "\n".join(lines)
        if any(r.missing_groups for r in results):
            msg += (
                "\n\nLanes targeting missing groups stay dormant until you "
                "re-point them at this config's groups."
            )
        msg += "\n\nSave the config to persist the imported shows."
        QMessageBox.information(self, "Imported", msg)

    def import_fixture_list_file(self):
        """File -> Import Fixture List: read a rig .csv or .json into the config.

        CSV input: flat spec-sheet rows; each fixture arrives with a single
        synthesized mode that library resolution upgrades to the real .qxf
        mode list where possible. JSON input: full-fidelity rig including
        group metadata and mode lists.

        If the config already has fixtures, the user picks Replace (swap the
        whole rig) or Add (append; name collisions get a numbered suffix).
        """
        from utils.fixture_io import (
            apply_fixture_list, read_fixture_list, resolve_modes_from_library,
        )
        default_dir = os.path.dirname(self.config_path) if self.config_path else ""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Import Fixture List",
            default_dir,
            "Fixture lists (*.csv *.json);;CSV (*.csv);;JSON (*.json)"
        )
        if not file_path:
            return
        try:
            fixtures, group_props, layers, fmt = read_fixture_list(file_path)
        except Exception as e:
            QMessageBox.critical(
                self, "Import Failed",
                f"Could not import {os.path.basename(file_path)}:\n{e}"
            )
            return
        if not fixtures:
            QMessageBox.warning(
                self, "Nothing to Import",
                f"{os.path.basename(file_path)} contains no fixtures."
            )
            return

        replace = False
        if self.config.fixtures:
            box = QMessageBox(self)
            box.setWindowTitle("Import Fixture List")
            box.setText(
                f"The config already has {len(self.config.fixtures)} fixture(s).\n\n"
                f"Replace the current rig with the {len(fixtures)} imported "
                f"fixture(s), or add them to it?"
            )
            replace_btn = box.addButton(
                "Replace", QMessageBox.ButtonRole.DestructiveRole)
            add_btn = box.addButton("Add", QMessageBox.ButtonRole.AcceptRole)
            box.addButton(QMessageBox.StandardButton.Cancel)
            box.exec()
            clicked = box.clickedButton()
            if clicked is replace_btn:
                replace = True
            elif clicked is not add_btn:
                return

        # Resolution also warms the shared definitions cache, so the
        # visualizer and capability detection see the imported models.
        warnings = resolve_modes_from_library(fixtures)
        apply_fixture_list(self.config, fixtures, group_props, layers, replace=replace)

        self.fixtures_tab.update_from_config(force=True)
        self.on_groups_changed()

        msg = f"Imported {len(fixtures)} fixture(s) from {fmt.upper()}."
        if warnings:
            msg += "\n\nWarnings:\n- " + "\n- ".join(warnings)
        msg += "\n\nSave the config to persist the imported rig."
        QMessageBox.information(self, "Imported", msg)

    def export_fixture_list_file(self):
        """File -> Export Fixture List: write the rig to .csv or .json.

        CSV writes the flat spec sheet (effective z/orientation). JSON
        writes the full-fidelity rig. Format is picked by the extension of
        the chosen path.
        """
        from utils.fixture_io import write_fixture_list
        if not self.config.fixtures:
            QMessageBox.warning(
                self, "No Fixtures",
                "Add fixtures in the Fixtures tab before exporting a fixture list."
            )
            return
        default_dir = os.path.dirname(self.config_path) if self.config_path else ""
        default_path = os.path.join(default_dir, "fixtures.csv") if default_dir else "fixtures.csv"
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Fixture List",
            default_path,
            "CSV (*.csv);;JSON (*.json)"
        )
        if not file_path:
            return
        if not os.path.splitext(file_path)[1]:
            file_path += ".csv"
        try:
            fmt = write_fixture_list(file_path, self.config)
        except Exception as e:
            QMessageBox.critical(
                self, "Export Failed",
                f"Could not export to {os.path.basename(file_path)}:\n{e}"
            )
            return
        QMessageBox.information(
            self, "Exported",
            f"Exported {len(self.config.fixtures)} fixture(s) to {fmt.upper()}:\n{file_path}"
        )

    def create_workspace(self):
        """Create QLC+ workspace file from configuration"""
        try:
            # Show workspace options dialog
            options_dialog = WorkspaceOptionsDialog(self, config=self.config)
            if options_dialog.exec() != options_dialog.DialogCode.Accepted:
                return  # User cancelled

            options_dialog.save_group_intensities()
            vc_options = options_dialog.get_options()

            # Show progress dialog with log area
            self.progress_manager.start_modal_with_log(
                "Creating Workspace",
                "Saving configuration...",
                maximum=4 if vc_options.get('generate_vc') else 3
            )

            # Save all tabs to configuration first
            self.progress_manager.update_modal(1, "Saving tab data...")
            self.config_tab.save_to_config()
            self.fixtures_tab.save_to_config()
            self.stage_tab.save_to_config()
            self.structure_tab.save_to_config()
            self.shows_tab.save_to_config()

            # Create workspace with log capture
            if vc_options.get('generate_vc'):
                self.progress_manager.update_modal(2, "Generating Virtual Console...")
                self.progress_manager.update_modal(3, "Generating QLC+ workspace XML...")
            else:
                self.progress_manager.update_modal(2, "Generating QLC+ workspace XML...")

            self.progress_manager.start_log_capture()
            try:
                create_qlc_workspace(self.config, vc_options)
            finally:
                self.progress_manager.stop_log_capture()

            self.progress_manager.update_modal(
                4 if vc_options.get('generate_vc') else 3,
                "Done!"
            )
            self.progress_manager.finish_modal()

            workspace_path = os.path.join(self.project_root, 'workspace.qxw')
            QMessageBox.information(
                self,
                "Success",
                f"Workspace created at {workspace_path}"
            )
            print(f"Workspace created at {workspace_path}")

        except Exception as e:
            self.progress_manager.stop_log_capture()
            self.progress_manager.finish_modal()
            QMessageBox.critical(
                self,
                "Error",
                f"Failed to create workspace: {str(e)}"
            )
            print(f"Error creating workspace: {e}")
            import traceback
            traceback.print_exc()

    def render_to_video(self):
        """Open the render-to-video dialog."""
        try:
            if not self.config.shows:
                QMessageBox.warning(self, "No Shows", "No shows available to render.")
                return

            # Load fixture definitions
            models_in_config = {(f.manufacturer, f.model)
                                for g in self.config.groups.values()
                                for f in g.fixtures}
            from utils.fixture_utils import load_fixture_definitions_from_qlc
            fixture_definitions = load_fixture_definitions_from_qlc(models_in_config)

            from gui.dialogs.render_dialog import RenderDialog
            dialog = RenderDialog(self.config, fixture_definitions, parent=self)
            dialog.exec()

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to open render dialog: {str(e)}")
            import traceback
            traceback.print_exc()

    def open_audio_settings(self):
        """Open audio settings dialog"""
        try:
            # Get audio engine and device manager from shows tab if available
            audio_engine = getattr(self.shows_tab, 'audio_engine', None)
            device_manager = getattr(self.shows_tab, 'device_manager', None)

            dialog = AudioSettingsDialog(
                device_manager=device_manager,
                audio_engine=audio_engine,
                parent=self
            )

            if dialog.exec():
                # Settings were applied
                settings = dialog.get_settings()
                if settings:
                    # Store settings for shows tab to use
                    self.audio_settings = settings

                    # If shows tab has audio components, update them
                    if hasattr(self.shows_tab, 'apply_audio_settings'):
                        self.shows_tab.apply_audio_settings(settings)

                    print(f"Audio settings applied: device={settings['device_index']}, "
                          f"rate={settings['sample_rate']}, buffer={settings['buffer_size']}")

        except Exception as e:
            QMessageBox.critical(
                self,
                "Error",
                f"Failed to open audio settings: {str(e)}"
            )
            print(f"Error opening audio settings: {e}")
            import traceback
            traceback.print_exc()

    def open_log_folder(self):
        """Open the application log directory in the system file browser."""
        from PyQt6.QtCore import QUrl
        from PyQt6.QtGui import QDesktopServices
        from utils.app_logging import log_dir
        directory = log_dir()
        try:
            os.makedirs(directory, exist_ok=True)
        except OSError:
            pass
        QDesktopServices.openUrl(QUrl.fromLocalFile(directory))

    def show_about(self):
        """Show about dialog"""
        from utils import app_identity
        QMessageBox.about(
            self,
            f"About {app_identity.APP_NAME}",
            f"{app_identity.APP_NAME}\n"
            f"{app_identity.SLOGAN_EN}\n\n"
            f"Version {app_identity.APP_VERSION} · {app_identity.APP_DOMAIN}\n\n"
            "Visual light show authoring:\n"
            "- Beat-synced timeline editing\n"
            "- Fixture management and grouping (GDTF and QLC+ formats)\n"
            "- Stage layout and printable stage plots\n"
            "- Automatic show generation from audio\n"
            "- Real-time 3D visualizer preview\n"
            "- Live ArtNet/DMX playback\n"
            "- QLC+ workspace export (interop)"
        )

    def closeEvent(self, event):
        """Handle application close"""
        # Clean up shows tab audio resources
        if hasattr(self.shows_tab, 'cleanup'):
            self.shows_tab.cleanup()

        # Tear down Auto Mode threads (audio input, analyser, DMX) and
        # persist its session state. Auto Mode is performance-oriented so
        # it stays running across tab switches; closing the app is the
        # only place that stops it.
        if hasattr(self, 'auto_tab') and hasattr(self.auto_tab, 'cleanup'):
            self.auto_tab.cleanup()

        event.accept()
