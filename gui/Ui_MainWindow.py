from PyQt6 import QtCore, QtWidgets, QtGui
from PyQt6.QtWidgets import QToolButton
from PyQt6.QtGui import QAction, QFont
from gui.StageView import StageView


class Ui_MainWindow(object):
    def setupUi(self, MainWindow):
        MainWindow.setObjectName("QLCShowCreator")
        # Fallback geometry only — main.py uses showMaximized so this only
        # applies if the window is later un-maximized by the user.
        MainWindow.resize(1600, 1000)
        MainWindow.setWindowTitle("QLC+ Show Creator")

        # Create central widget
        self.centralwidget = QtWidgets.QWidget(parent=MainWindow)
        self.centralwidget.setObjectName("centralwidget")

        # The Save/Load/Import/Create actions used to live on a separate
        # QToolBar row. They now sit on the menubar's right corner together
        # with the ArtNet/Visualizer status pills, freeing a vertical line
        # of UI. The QAction objects stay around so gui.py's existing
        # connections keep working — only the visual host changed.
        style_obj = QtWidgets.QApplication.style()
        self.saveAction = QAction(
            style_obj.standardIcon(QtWidgets.QStyle.StandardPixmap.SP_DialogSaveButton),
            "Save Configuration", MainWindow)
        self.loadAction = QAction(
            style_obj.standardIcon(QtWidgets.QStyle.StandardPixmap.SP_DialogOpenButton),
            "Load Configuration", MainWindow)
        self.importWorkspaceAction = QAction(
            style_obj.standardIcon(QtWidgets.QStyle.StandardPixmap.SP_FileDialogDetailedView),
            "Import Workspace", MainWindow)
        self.createWorkspaceAction = QAction(
            style_obj.standardIcon(QtWidgets.QStyle.StandardPixmap.SP_MediaSeekForward),
            "Create Workspace", MainWindow)

        # Status indicators container — shared by ArtNet and TCP/Visualizer
        # state widgets. Will be packed into the menubar corner below.
        status_container = QtWidgets.QWidget()
        status_layout = QtWidgets.QHBoxLayout(status_container)
        status_layout.setContentsMargins(0, 0, 10, 0)
        status_layout.setSpacing(15)

        # ArtNet status indicator with toggle button. Per-theme styling lives
        # in resources/themes/*.qss; here we only set role/status dynamic
        # properties that the stylesheets target.
        artnet_layout = QtWidgets.QHBoxLayout()
        artnet_layout.setSpacing(4)
        artnet_label = QtWidgets.QLabel("ArtNet:")
        artnet_label.setProperty("role", "status-label")
        self.artnet_status_indicator = QtWidgets.QLabel("OFF")
        self.artnet_status_indicator.setProperty("status", "off")
        self.artnet_status_indicator.setToolTip("ArtNet DMX Output Status")
        self.artnet_toggle_btn = QtWidgets.QPushButton("●")
        self.artnet_toggle_btn.setFixedSize(24, 24)
        self.artnet_toggle_btn.setProperty("role", "status-pill")
        self.artnet_toggle_btn.setProperty("status", "off")
        self.artnet_toggle_btn.setToolTip("Click to toggle ArtNet")
        self.artnet_toggle_btn.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        artnet_layout.addWidget(artnet_label)
        artnet_layout.addWidget(self.artnet_status_indicator)
        artnet_layout.addWidget(self.artnet_toggle_btn)
        status_layout.addLayout(artnet_layout)

        # TCP/Visualizer status indicator with toggle button. Same dynamic-
        # property pattern as the ArtNet pill; theme files do the colors.
        tcp_layout = QtWidgets.QHBoxLayout()
        tcp_layout.setSpacing(4)
        tcp_label = QtWidgets.QLabel("Visualizer:")
        tcp_label.setProperty("role", "status-label")
        self.tcp_status_indicator = QtWidgets.QLabel("OFF")
        self.tcp_status_indicator.setProperty("status", "off")
        self.tcp_status_indicator.setToolTip("TCP Visualizer Server Status")
        self.tcp_toggle_btn = QtWidgets.QPushButton("●")
        self.tcp_toggle_btn.setFixedSize(24, 24)
        self.tcp_toggle_btn.setProperty("role", "status-pill")
        self.tcp_toggle_btn.setProperty("status", "off")
        self.tcp_toggle_btn.setToolTip("Click to toggle Visualizer Server")
        self.tcp_toggle_btn.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        tcp_layout.addWidget(tcp_label)
        tcp_layout.addWidget(self.tcp_status_indicator)
        tcp_layout.addWidget(self.tcp_toggle_btn)
        status_layout.addLayout(tcp_layout)

        # Hold the assembled status container; the corner widget is wired
        # up after the menubar exists (in setupStatusAndMenu).
        self._status_container = status_container

        # Main layout
        self.horizontalLayout = QtWidgets.QHBoxLayout(self.centralwidget)
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

        # Add tabs to widget
        self.tabWidget.addTab(self.tab_config, "Configuration")
        self.tabWidget.addTab(self.tab, "Fixtures")
        self.tabWidget.addTab(self.tab_stage, "Stage")
        self.tabWidget.addTab(self.tab_structure, "Structure")
        self.tabWidget.addTab(self.tab_2, "Shows")
        self.tabWidget.addTab(self.tab_auto, "Auto(Experimental)")

        self.horizontalLayout.addWidget(self.tabWidget)
        MainWindow.setCentralWidget(self.centralwidget)

        # Setup status bar and menu
        self.setupStatusAndMenu(MainWindow)

        self.tabWidget.setCurrentIndex(0)
        QtCore.QMetaObject.connectSlotsByName(MainWindow)

    def retranslateUi(self, MainWindow):
        _translate = QtCore.QCoreApplication.translate
        MainWindow.setWindowTitle(_translate("MainWindow", "QLC+ Show Creator"))
        # Tab titles
        self.tabWidget.setTabText(self.tabWidget.indexOf(self.tab_config), _translate("MainWindow", "Configuration"))
        self.tabWidget.setTabText(self.tabWidget.indexOf(self.tab), _translate("MainWindow", "Fixtures"))
        self.tabWidget.setTabText(self.tabWidget.indexOf(self.tab_stage), _translate("MainWindow", "Stage"))
        self.tabWidget.setTabText(self.tabWidget.indexOf(self.tab_structure), _translate("MainWindow", "Structure"))
        self.tabWidget.setTabText(self.tabWidget.indexOf(self.tab_2), _translate("MainWindow", "Shows"))
        self.tabWidget.setTabText(self.tabWidget.indexOf(self.tab_auto), _translate("MainWindow", "Auto(Experimental)"))
        # Toolbar actions
        self.saveAction.setText(_translate("MainWindow", "Save Configuration"))
        self.loadAction.setText(_translate("MainWindow", "Load Configuration"))

    def setupStatusAndMenu(self, MainWindow):
        self.statusbar = QtWidgets.QStatusBar(parent=MainWindow)
        MainWindow.setStatusBar(self.statusbar)

        self.menubar = QtWidgets.QMenuBar(parent=MainWindow)
        self.menubar.setGeometry(QtCore.QRect(0, 0, 1200, 22))

        # File menu
        self.menuFile = QtWidgets.QMenu("File", parent=self.menubar)
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
        self.actionImportWorkspace = QAction("Import QLC+ Workspace...", MainWindow)
        self.actionCreateWorkspace = QAction("Create QLC+ Workspace", MainWindow)
        self.actionExit = QAction("Exit", MainWindow)
        self.actionExit.setShortcut("Ctrl+Q")

        self.menuFile.addAction(self.actionSaveConfig)
        self.menuFile.addAction(self.actionSaveConfigAs)
        self.menuFile.addAction(self.actionLoadConfig)
        self.menuFile.addSeparator()
        self.menuFile.addAction(self.actionImportShowStructure)
        self.menuFile.addAction(self.actionExportShowStructure)
        self.menuFile.addAction(self.actionImportShowsFromConfig)
        self.menuFile.addSeparator()
        self.menuFile.addAction(self.actionImportFixtureList)
        self.menuFile.addAction(self.actionExportFixtureList)
        self.menuFile.addSeparator()
        self.menuFile.addAction(self.actionImportWorkspace)
        self.menuFile.addAction(self.actionCreateWorkspace)
        self.menuFile.addSeparator()
        self.menuFile.addAction(self.actionExit)

        # View menu — fullscreen toggle + theme picker.
        self.menuView = QtWidgets.QMenu("View", parent=self.menubar)
        self.actionToggleFullscreen = QAction("Toggle Fullscreen", MainWindow)
        self.actionToggleFullscreen.setShortcut("F11")
        self.actionToggleFullscreen.setCheckable(True)
        self.menuView.addAction(self.actionToggleFullscreen)
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
        self.menuSettings = QtWidgets.QMenu("Settings", parent=self.menubar)
        self.actionAudioSettings = QAction("Audio Settings...", MainWindow)
        self.actionAudioSettings.setShortcut("Ctrl+,")
        self.menuSettings.addAction(self.actionAudioSettings)

        # Help menu
        self.menuHelp = QtWidgets.QMenu("Help", parent=self.menubar)
        self.actionAbout = QAction("About", MainWindow)
        self.menuHelp.addAction(self.actionAbout)

        # Add menus to menubar
        MainWindow.setMenuBar(self.menubar)
        self.menubar.addAction(self.menuFile.menuAction())
        self.menubar.addAction(self.menuView.menuAction())
        self.menubar.addAction(self.menuSettings.menuAction())
        self.menubar.addAction(self.menuHelp.menuAction())

        # Right corner of the menubar: the four icon shortcuts plus the
        # ArtNet/Visualizer status pills (assembled earlier in setupUi).
        # Replaces the old standalone QToolBar, freeing one full row of
        # vertical space.
        corner = QtWidgets.QWidget()
        corner_layout = QtWidgets.QHBoxLayout(corner)
        corner_layout.setContentsMargins(0, 0, 6, 0)
        corner_layout.setSpacing(2)

        for action in (self.saveAction, self.loadAction,
                       self.importWorkspaceAction, self.createWorkspaceAction):
            btn = QToolButton()
            btn.setDefaultAction(action)
            btn.setToolButtonStyle(QtCore.Qt.ToolButtonStyle.ToolButtonIconOnly)
            btn.setAutoRaise(True)
            corner_layout.addWidget(btn)

        # Vertical separator between the icons and the status pills.
        sep = QtWidgets.QFrame()
        sep.setFrameShape(QtWidgets.QFrame.Shape.VLine)
        sep.setFrameShadow(QtWidgets.QFrame.Shadow.Sunken)
        corner_layout.addWidget(sep)

        if hasattr(self, "_status_container") and self._status_container is not None:
            corner_layout.addWidget(self._status_container)

        self.menubar.setCornerWidget(corner, QtCore.Qt.Corner.TopRightCorner)