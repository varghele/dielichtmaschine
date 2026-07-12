from PyQt6 import QtCore, QtWidgets, QtGui
from PyQt6.QtWidgets import QToolButton
from PyQt6.QtGui import QAction, QFont
from gui.StageView import StageView
from utils.app_identity import APP_NAME, SETTINGS_APP


class Ui_MainWindow(object):
    def setupUi(self, MainWindow):
        MainWindow.setObjectName(SETTINGS_APP)
        # Fallback geometry only — main.py uses showMaximized so this only
        # applies if the window is later un-maximized by the user.
        MainWindow.resize(1600, 1000)
        MainWindow.setWindowTitle(APP_NAME)

        # Create central widget
        self.centralwidget = QtWidgets.QWidget(parent=MainWindow)
        self.centralwidget.setObjectName("centralwidget")

        # The Save/Load/Import/Create actions live on the shell topbar.
        # Icons are brand line-SVGs applied theme-aware in
        # apply_shell_icons (re-run on theme switch); the QAction objects
        # keep their names so gui.py's existing connections keep working.
        self.saveAction = QAction("Save Configuration", MainWindow)
        self.loadAction = QAction("Load Configuration", MainWindow)
        self.importWorkspaceAction = QAction("Import Workspace", MainWindow)
        self.createWorkspaceAction = QAction("Create Workspace", MainWindow)

        # ArtNet / TCP-Visualizer status widgets. Per-theme styling lives
        # in the QSS template; here we only set role/status dynamic
        # properties that the stylesheet targets. gui.py's
        # _update_toolbar_status drives text + status props; the widgets
        # are packed into topbar StatusChips in setupStatusAndMenu.
        self.artnet_status_indicator = QtWidgets.QLabel("OFF")
        self.artnet_status_indicator.setProperty("status", "off")
        self.artnet_status_indicator.setToolTip(
            "DMX output status (native ArtNet)")
        # The toggle is a small square that fills with the status color
        # (QSS [status=...] rules); no glyph, so no font dependency.
        self.artnet_toggle_btn = QtWidgets.QPushButton("")
        self.artnet_toggle_btn.setFixedSize(14, 14)
        self.artnet_toggle_btn.setProperty("role", "status-pill")
        self.artnet_toggle_btn.setProperty("status", "off")
        self.artnet_toggle_btn.setToolTip("Click to toggle DMX output")
        self.artnet_toggle_btn.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)

        self.tcp_status_indicator = QtWidgets.QLabel("OFF")
        self.tcp_status_indicator.setProperty("status", "off")
        self.tcp_status_indicator.setToolTip("Visualizer feed status")
        # A labelled ACTION button, not an anonymous status square:
        # OPEN launches the standalone visualizer and starts its TCP
        # feed in one click, STOP ends the feed. Text is driven by
        # gui.py's _update_toolbar_status; width from the text (a
        # fixed narrow width would clip the glyphs, CLAUDE.md).
        self.tcp_toggle_btn = QtWidgets.QPushButton("OPEN")
        self.tcp_toggle_btn.setProperty("role", "output-select")
        # compact density: the default 6px vertical padding clips the
        # label inside the 26px chip row (CLAUDE.md glyph-clip rule).
        self.tcp_toggle_btn.setProperty("density", "compact")
        self.tcp_toggle_btn.setProperty("status", "off")
        from gui.typography import mono_font
        self.tcp_toggle_btn.setFont(mono_font(8, QFont.Weight.DemiBold))
        self.tcp_toggle_btn.setFixedHeight(20)
        self.tcp_toggle_btn.setToolTip(
            "Launch the standalone visualizer and start its feed")
        self.tcp_toggle_btn.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)

        # Main layout: [topbar][subnav][tab pages]; the topbar + subnav
        # rows are inserted by setupStatusAndMenu once actions exist.
        self.central_layout = QtWidgets.QVBoxLayout(self.centralwidget)
        self.central_layout.setContentsMargins(0, 0, 0, 0)
        self.central_layout.setSpacing(0)
        self.tabWidget = QtWidgets.QTabWidget(parent=self.centralwidget)

        # Configuration/Universes tab (UI created by ConfigurationTab)
        self.tab_config = QtWidgets.QWidget()

        # Fixtures Tab (UI created by FixturesTab)
        self.tab = QtWidgets.QWidget()

        # Stage Tab (UI created by StageTab)
        self.tab_stage = QtWidgets.QWidget()

        # Shows Tab (UI created by ShowsTab)
        self.tab_2 = QtWidgets.QWidget()

        # Structure Tab (UI created by StructureTab)
        self.tab_structure = QtWidgets.QWidget()

        # Auto Tab (UI created by AutoTab) — real-time audio-reactive
        # auto-generation pipeline. Was originally a separate QMainWindow
        # opened from a "Live" menu (Ctrl+L) before being folded in as the
        # sixth tab. Renamed from "Live" to "Auto" so a future Live tab
        # (operator runtime view) can claim that name.
        self.tab_auto = QtWidgets.QWidget()

        # Live Tab (UI created by LiveTab) - the touch-palette busking
        # surface (North Star screen 09, layout 3b). The "Live" name was
        # freed when the old Live tab became Auto.
        self.tab_live = QtWidgets.QWidget()

        # Add tabs to widget
        self.tabWidget.addTab(self.tab_config, "Configuration")
        self.tabWidget.addTab(self.tab, "Fixtures")
        self.tabWidget.addTab(self.tab_stage, "Stage")
        self.tabWidget.addTab(self.tab_structure, "Structure")
        self.tabWidget.addTab(self.tab_2, "Shows")
        self.tabWidget.addTab(self.tab_auto, "Auto(Experimental)")
        self.tabWidget.addTab(self.tab_live, "Live")

        # The shell topbar + subnav are the visible navigation; the tab
        # bar itself is hidden and the QTabWidget stays as the page host
        # (indices unchanged, so Ctrl+L and _on_tab_changed keep working).
        # A QStackedWidget hosts [Home | tab pages] so the Home screen
        # (North Star 1a) never disturbs tab indices.
        self.tabWidget.tabBar().setVisible(False)
        from gui.widgets.home_screen import HomeScreen
        self.home_screen = HomeScreen(parent=self.centralwidget)
        self.page_stack = QtWidgets.QStackedWidget(parent=self.centralwidget)
        self.page_stack.addWidget(self.home_screen)
        self.page_stack.addWidget(self.tabWidget)
        self.page_stack.setCurrentWidget(self.home_screen)
        self.central_layout.addWidget(self.page_stack)
        MainWindow.setCentralWidget(self.centralwidget)

        # Setup status bar and menu
        self.setupStatusAndMenu(MainWindow)

        self.tabWidget.setCurrentIndex(0)
        QtCore.QMetaObject.connectSlotsByName(MainWindow)

    def retranslateUi(self, MainWindow):
        _translate = QtCore.QCoreApplication.translate
        MainWindow.setWindowTitle(_translate("MainWindow", APP_NAME))
        # Tab titles
        self.tabWidget.setTabText(self.tabWidget.indexOf(self.tab_config), _translate("MainWindow", "Configuration"))
        self.tabWidget.setTabText(self.tabWidget.indexOf(self.tab), _translate("MainWindow", "Fixtures"))
        self.tabWidget.setTabText(self.tabWidget.indexOf(self.tab_stage), _translate("MainWindow", "Stage"))
        self.tabWidget.setTabText(self.tabWidget.indexOf(self.tab_structure), _translate("MainWindow", "Structure"))
        self.tabWidget.setTabText(self.tabWidget.indexOf(self.tab_2), _translate("MainWindow", "Shows"))
        self.tabWidget.setTabText(self.tabWidget.indexOf(self.tab_auto), _translate("MainWindow", "Auto(Experimental)"))
        self.tabWidget.setTabText(self.tabWidget.indexOf(self.tab_live), _translate("MainWindow", "Live"))
        # Toolbar actions
        self.saveAction.setText(_translate("MainWindow", "Save Configuration"))
        self.loadAction.setText(_translate("MainWindow", "Load Configuration"))

    def setupStatusAndMenu(self, MainWindow):
        # 26px mono status strip: contextual hint left, version right.
        # showMessage() still works for transient messages (saves etc.).
        from gui.typography import MicroLabel
        from utils.app_identity import APP_VERSION

        self.statusbar = QtWidgets.QStatusBar(parent=MainWindow)
        self.statusbar.setFixedHeight(26)
        self.statusbar.setSizeGripEnabled(False)
        self.status_hint = MicroLabel(
            QtCore.QCoreApplication.translate("Shell", "Ready"),
            point_size=8, tracking_em=0.1)
        self.status_hint.setObjectName("StatusHint")
        self.statusbar.addWidget(self.status_hint)
        from utils.app_identity import APP_DOMAIN
        version_label = MicroLabel(f"v{APP_VERSION} · {APP_DOMAIN}",
                                   point_size=8, tracking_em=0.1)
        version_label.setObjectName("StatusVersion")
        self.statusbar.addPermanentWidget(version_label)
        MainWindow.setStatusBar(self.statusbar)

        # File menu
        self.menuFile = QtWidgets.QMenu("File", parent=MainWindow)
        self.actionNewFromTemplate = QAction("New from Template...", MainWindow)
        self.actionNewFromTemplate.setShortcut("Ctrl+N")
        self.actionSaveConfig = QAction("Save Configuration", MainWindow)
        self.actionSaveConfig.setShortcut("Ctrl+S")
        self.actionSaveConfigAs = QAction("Save Configuration As...", MainWindow)
        self.actionSaveConfigAs.setShortcut("Ctrl+Shift+S")
        self.actionLoadConfig = QAction("Load Configuration", MainWindow)
        self.actionLoadConfig.setShortcut("Ctrl+O")
        self.actionImportShowStructure = QAction("Import Show Structure...", MainWindow)
        self.actionExportShowStructure = QAction("Export Show Structure...", MainWindow)
        self.actionImportFixtureList = QAction("Import Fixture List...", MainWindow)
        self.actionExportFixtureList = QAction("Export Fixture List...", MainWindow)
        self.actionImportShowsFromConfig = QAction("Import Shows from Config...", MainWindow)
        self.actionImportLegacyCsv = QAction("Import Legacy CSV Songs...", MainWindow)
        self.actionImportWorkspace = QAction("Import QLC+ Workspace...", MainWindow)
        self.actionCreateWorkspace = QAction("Create QLC+ Workspace", MainWindow)
        self.actionExit = QAction("Exit", MainWindow)
        self.actionExit.setShortcut("Ctrl+Q")

        self.menuFile.addAction(self.actionNewFromTemplate)
        self.menuFile.addSeparator()
        self.menuFile.addAction(self.actionSaveConfig)
        self.menuFile.addAction(self.actionSaveConfigAs)
        self.menuFile.addAction(self.actionLoadConfig)
        self.menuFile.addSeparator()
        self.menuFile.addAction(self.actionImportShowStructure)
        self.menuFile.addAction(self.actionExportShowStructure)
        self.menuFile.addAction(self.actionImportShowsFromConfig)
        self.menuFile.addAction(self.actionImportLegacyCsv)
        self.menuFile.addSeparator()
        self.menuFile.addAction(self.actionImportFixtureList)
        self.menuFile.addAction(self.actionExportFixtureList)
        self.menuFile.addSeparator()
        self.menuFile.addAction(self.actionImportWorkspace)
        self.menuFile.addAction(self.actionCreateWorkspace)
        self.menuFile.addSeparator()
        self.menuFile.addAction(self.actionExit)

        # View menu — fullscreen toggle + theme picker.
        self.menuView = QtWidgets.QMenu("View", parent=MainWindow)
        self.actionToggleFullscreen = QAction("Toggle Fullscreen", MainWindow)
        self.actionToggleFullscreen.setShortcut("F11")
        self.actionToggleFullscreen.setCheckable(True)
        self.menuView.addAction(self.actionToggleFullscreen)
        self.actionScreensaver = QAction("Screensaver", MainWindow)
        # F7 opens the pause screen. Free key (F11 is fullscreen; F and L
        # are widget-scoped in the Stage tab). register_menu_shortcuts
        # re-adds it to the window so it fires without a menubar.
        self.actionScreensaver.setShortcut("F7")
        self.menuView.addAction(self.actionScreensaver)
        self.menuView.addSeparator()

        self.menuTheme = QtWidgets.QMenu("Theme", parent=self.menuView)
        self.themeActionGroup = QtGui.QActionGroup(MainWindow)
        self.themeActionGroup.setExclusive(True)
        self.actionThemeDark = QAction("Dark", MainWindow)
        self.actionThemeDark.setCheckable(True)
        self.actionThemeLight = QAction("Light", MainWindow)
        self.actionThemeLight.setCheckable(True)
        self.themeActionGroup.addAction(self.actionThemeDark)
        self.themeActionGroup.addAction(self.actionThemeLight)
        self.menuTheme.addAction(self.actionThemeDark)
        self.menuTheme.addAction(self.actionThemeLight)
        self.menuView.addMenu(self.menuTheme)

        # Settings menu
        self.menuSettings = QtWidgets.QMenu("Settings", parent=MainWindow)
        self.actionAudioSettings = QAction("Audio Settings...", MainWindow)
        self.actionAudioSettings.setShortcut("Ctrl+,")
        self.menuSettings.addAction(self.actionAudioSettings)
        # User fixture-library directories (GDTF + .qxf), folded into
        # the definition search path (gui/dialogs/library_paths_dialog.py).
        self.actionLibraryPaths = QAction("Fixture Libraries...", MainWindow)
        self.menuSettings.addAction(self.actionLibraryPaths)
        # Hidden deep setting: toggle the canvas sub-lane purpose labels in
        # the Show Timeline. Checkable, persisted to the
        # "timeline/show_sublane_labels" QSettings key (default on).
        self.actionShowSublaneLabels = QAction(
            "Show timeline sub-lane labels", MainWindow)
        self.actionShowSublaneLabels.setCheckable(True)
        self.menuSettings.addAction(self.actionShowSublaneLabels)

        # Help menu
        self.menuHelp = QtWidgets.QMenu("Help", parent=MainWindow)
        self.actionOpenLogFolder = QAction("Open Log Folder", MainWindow)
        self.menuHelp.addAction(self.actionOpenLogFolder)
        self.actionAbout = QAction("About", MainWindow)
        self.menuHelp.addAction(self.actionAbout)

        # No QMenuBar (North Star shell): the menus live in one overflow
        # QMenu behind the topbar's ☰ button. gui.py inserts the Edit and
        # Render menus into this container (before Settings / Help), and
        # re-registers every shortcut on the window afterwards
        # (register_menu_shortcuts) since popup-only actions don't fire
        # their shortcuts app-wide.
        self.overflow_menu = QtWidgets.QMenu(MainWindow)
        self.overflow_menu.addMenu(self.menuFile)
        self.overflow_menu.addMenu(self.menuView)
        self.overflow_menu.addMenu(self.menuSettings)
        self.overflow_menu.addMenu(self.menuHelp)

        # ── Shell topbar + subnav ────────────────────────────────────
        from gui.widgets.topbar import (
            ShellNav, StatusChip, SubNav, TopBar, TopBarIconButton,
            default_sections,
        )

        sections = default_sections()
        self.topbar = TopBar(sections, parent=self.centralwidget)
        self.subnav = SubNav(parent=self.centralwidget)

        # Right side of the topbar: icon shortcuts, overflow menu,
        # filename, status chips.
        for action in (self.saveAction, self.loadAction,
                       self.importWorkspaceAction, self.createWorkspaceAction):
            btn = TopBarIconButton()
            btn.setDefaultAction(action)
            self.topbar.right_layout.addWidget(btn)

        self.overflow_btn = TopBarIconButton()
        self.overflow_btn.setToolTip(
            QtCore.QCoreApplication.translate("Shell", "Menu"))
        self.overflow_btn.setMenu(self.overflow_menu)
        self.overflow_btn.setPopupMode(
            QToolButton.ToolButtonPopupMode.InstantPopup)
        self.topbar.right_layout.addWidget(self.overflow_btn)

        self.topbar.right_layout.addSpacing(8)
        self.topbar.right_layout.addWidget(self.topbar.filename_label)
        self.topbar.right_layout.addSpacing(8)

        # OUTPUT = the master DMX switch (native ArtNet); VISUALIZER
        # pairs the feed status with an explicit OPEN/STOP action.
        self.artnet_chip = StatusChip(
            "Output", self.artnet_status_indicator, self.artnet_toggle_btn)
        self.tcp_chip = StatusChip(
            "Visualizer", self.tcp_status_indicator, self.tcp_toggle_btn)
        self.topbar.right_layout.addWidget(self.artnet_chip)
        self.topbar.right_layout.addWidget(self.tcp_chip)

        self.central_layout.insertWidget(0, self.topbar)
        self.central_layout.insertWidget(1, self.subnav)
        self.shell_nav = ShellNav(sections, self.topbar, self.subnav,
                                  self.tabWidget)
        self.apply_shell_icons()

        # Home <-> tabs switching. Any navigation shows the tab pages;
        # the brand block returns Home. On Home no section is active and
        # the subnav row hides.
        self.topbar.home_selected.connect(self.show_home)
        self.topbar.section_selected.connect(lambda _key: self.show_pages())
        self.subnav.screen_selected.connect(lambda _i: self.show_pages())
        # External navigation (e.g. Ctrl+L jumping to Auto) must leave
        # Home too.
        self.tabWidget.currentChanged.connect(lambda _i: self.show_pages())
        self.show_home()

    def show_home(self) -> None:
        """Show the Home landing page (no active section)."""
        self.page_stack.setCurrentWidget(self.home_screen)
        self.topbar.set_active_section(None)
        self.subnav.setVisible(False)

    def show_pages(self) -> None:
        """Show the tab pages and restore the shell nav state."""
        self.page_stack.setCurrentWidget(self.tabWidget)
        self.subnav.setVisible(True)
        self.shell_nav.sync_to_tab(self.tabWidget.currentIndex())

    def apply_shell_icons(self, theme: str = None) -> None:
        """(Re)apply the brand line icons in the active theme's color.

        Called once at setup and again after every theme switch - the
        icons are rasterized pixmaps, so unlike QSS they don't recolor
        on repolish.
        """
        from gui.icons import shell_icon
        for action, name in (
            (self.saveAction, "save"),
            (self.loadAction, "open"),
            (self.importWorkspaceAction, "import"),
            (self.createWorkspaceAction, "export"),
        ):
            action.setIcon(shell_icon(name, theme))
        self.overflow_btn.setIcon(shell_icon("menu", theme))