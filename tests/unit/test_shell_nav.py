"""Shell chrome: topbar/subnav navigation, overflow menu, shortcuts.

The shell replaces the menubar + visible tab bar (shell pass S2, see
docs/shell-pass-plan.md). These tests pin the contract: nav drives the
existing QTabWidget indices, external index changes sync the chrome,
every menu survives into the overflow popup, and every shortcut still
fires without a menubar.
"""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtGui import QAction, QKeySequence
from PyQt6.QtWidgets import QMainWindow, QMenu, QMenuBar


@pytest.fixture
def shell_window(qapp):
    """A QMainWindow with the Ui shell set up (tab pages stay empty
    placeholders - the heavy tabs are only built by MainWindow)."""
    from gui.Ui_MainWindow import Ui_MainWindow
    window = QMainWindow()
    ui = Ui_MainWindow()
    ui.setupUi(window)
    yield window, ui
    window.deleteLater()


class TestShellNav:
    def test_no_menubar_and_hidden_tabbar(self, shell_window):
        window, ui = shell_window
        assert window.findChild(QMenuBar) is None
        assert not ui.tabWidget.tabBar().isVisibleTo(window)

    def test_initial_state_is_home_then_setup_universes(self, shell_window):
        """Startup lands on Home (no active section); entering the
        pages restores SETUP > UNIVERSES."""
        _, ui = shell_window
        assert ui.topbar.active_section() is None  # Home
        ui.show_pages()
        assert ui.tabWidget.currentIndex() == 0
        assert ui.topbar.active_section() == "setup"
        assert ui.subnav.tab_indices() == [0, 1, 2]

    def test_nav_button_switches_section(self, shell_window):
        _, ui = shell_window
        ui.topbar._buttons["show"].click()
        assert ui.tabWidget.currentIndex() == 3  # Structure
        assert ui.subnav.tab_indices() == [3, 4]
        # LIVE's first screen is the Live surface (tab 6), with Auto
        # (tab 5) as its sibling screen.
        ui.topbar._buttons["live"].click()
        assert ui.tabWidget.currentIndex() == 6
        assert ui.subnav.tab_indices() == [5, 6]

    def test_subnav_switches_screen_within_section(self, shell_window):
        _, ui = shell_window
        ui.subnav._buttons[2].click()  # Stage
        assert ui.tabWidget.currentIndex() == 2
        assert ui.topbar.active_section() == "setup"

    def test_section_remembers_last_screen(self, shell_window):
        _, ui = shell_window
        ui.subnav._buttons[1].click()          # Setup > Fixtures
        ui.topbar._buttons["show"].click()     # away
        ui.topbar._buttons["setup"].click()    # back
        assert ui.tabWidget.currentIndex() == 1

    def test_external_index_change_syncs_chrome(self, shell_window):
        """Ctrl+L path: setCurrentIndex from outside the shell."""
        _, ui = shell_window
        ui.tabWidget.setCurrentIndex(5)  # Auto lives under LIVE now
        assert ui.topbar.active_section() == "live"
        assert ui.subnav.tab_indices() == [5, 6]
        ui.tabWidget.setCurrentIndex(4)
        assert ui.topbar.active_section() == "show"

    def test_live_section_remembers_auto_screen(self, shell_window):
        """LIVE and AUTO are sibling screens of one section: leaving
        from Auto and clicking LIVE again returns to Auto."""
        _, ui = shell_window
        ui.topbar._buttons["live"].click()
        ui.subnav._buttons[5].click()          # Live > Auto
        ui.topbar._buttons["show"].click()     # away
        ui.topbar._buttons["live"].click()     # back
        assert ui.tabWidget.currentIndex() == 5
        assert ui.topbar.active_section() == "live"

    def test_status_widgets_keep_their_contract(self, shell_window):
        """gui.py's _update_toolbar_status drives these by attribute
        name and dynamic property; the move into chips must not break
        that."""
        _, ui = shell_window
        for name in ("artnet_status_indicator", "artnet_toggle_btn",
                     "tcp_status_indicator", "tcp_toggle_btn"):
            widget = getattr(ui, name)
            assert widget.property("status") == "off"
        assert ui.artnet_chip.isVisibleTo(ui.topbar) or True  # exists
        assert ui.tcp_chip is not None

    def test_filename_label_updates(self, shell_window):
        _, ui = shell_window
        ui.topbar.set_filename("myshow.yaml *")
        assert ui.topbar.filename_label.text() == "MYSHOW.YAML *"


class TestOverflowMenu:
    def test_all_menus_present_in_order(self, shell_window):
        _, ui = shell_window
        titles = [a.menu().title() for a in ui.overflow_menu.actions()
                  if a.menu() is not None]
        assert titles == ["File", "View", "Tools", "Settings", "Help"]

    def test_gui_py_insertion_points_exist(self, shell_window):
        """gui.py inserts Edit before Settings and Render before Help."""
        _, ui = shell_window
        actions = ui.overflow_menu.actions()
        assert ui.menuSettings.menuAction() in actions
        assert ui.menuHelp.menuAction() in actions

    def test_import_legacy_csv_action_in_file_menu(self, shell_window):
        """The Structure tab's SHOW DIRECTORY chip became this explicit
        import action (the only interactive use of the directory hint
        was merging pre-v1.0 CSV songs)."""
        _, ui = shell_window
        assert ui.actionImportLegacyCsv.text() == "Import Legacy CSV Songs..."
        assert ui.actionImportLegacyCsv in ui.menuFile.actions()


class TestScreenHints:
    def test_every_screen_has_a_hint(self, qapp):
        from gui.widgets.topbar import default_sections, screen_hints
        hints = screen_hints()
        all_indices = [i for s in default_sections() for i in s.tab_indices()]
        for index in all_indices:
            assert hints.get(index), f"no hint for tab index {index}"

    def test_hints_use_the_brand_separator(self, qapp):
        from gui.widgets.topbar import screen_hints
        for hint in screen_hints().values():
            assert "—" not in hint and "–" not in hint
            if "·" in hint:
                assert " · " in hint  # spaced separator, per the handoff


class TestShortcutRegistration:
    def test_register_menu_shortcuts_recurses_and_counts(self, qapp):
        from gui.widgets.topbar import register_menu_shortcuts
        window = QMainWindow()
        try:
            root = QMenu(window)
            sub = root.addMenu("Sub")
            plain = QAction("no shortcut", window)
            sub.addAction(plain)
            hot = QAction("hot", window)
            hot.setShortcut(QKeySequence("Ctrl+T"))
            sub.addAction(hot)
            top_hot = QAction("top", window)
            top_hot.setShortcut(QKeySequence("Ctrl+U"))
            root.addAction(top_hot)

            count = register_menu_shortcuts(window, root)
            assert count == 2
            assert hot in window.actions()
            assert top_hot in window.actions()
            assert plain not in window.actions()
        finally:
            window.deleteLater()

    def test_shell_shortcuts_registered_on_ui(self, shell_window):
        """Every shortcut-carrying action in the overflow tree can be
        registered on the window (what MainWindow.__init__ does)."""
        window, ui = shell_window
        from gui.widgets.topbar import register_menu_shortcuts
        count = register_menu_shortcuts(window, ui.overflow_menu)
        # File menu alone carries Ctrl+N/S/Shift+S/O/Q; View has F11;
        # Settings has Ctrl+, - at least 7 in the Ui-built tree.
        assert count >= 7
        shortcuts = [a.shortcut().toString() for a in window.actions()]
        assert "Ctrl+S" in shortcuts
        assert "F11" in shortcuts
        # F7 opens the pause screen / screensaver.
        assert "F7" in shortcuts

    def test_screensaver_action_has_the_f7_shortcut(self, shell_window):
        _, ui = shell_window
        assert ui.actionScreensaver.shortcut().toString() == "F7"
