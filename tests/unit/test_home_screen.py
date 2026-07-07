"""Home screen (North Star 1a): recents tracking, signals, shell hosting."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture
def ini_settings(tmp_path, monkeypatch):
    from PyQt6.QtCore import QSettings
    from utils import app_settings as mod
    monkeypatch.setattr(mod, "_settings_format", QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat,
                      QSettings.Scope.UserScope, str(tmp_path))
    yield tmp_path


class TestRecentConfigs:
    def test_most_recent_first_and_deduplicated(self, ini_settings, tmp_path):
        from utils.app_settings import recent_configs, record_recent_config
        a = tmp_path / "a.yaml"
        b = tmp_path / "b.yaml"
        a.write_text("x")
        b.write_text("x")
        record_recent_config(str(a))
        record_recent_config(str(b))
        record_recent_config(str(a))  # a again -> moves to front, no dupe
        assert recent_configs() == [str(a), str(b)]

    def test_missing_files_filtered_on_read(self, ini_settings, tmp_path):
        from utils.app_settings import recent_configs, record_recent_config
        gone = tmp_path / "gone.yaml"
        gone.write_text("x")
        record_recent_config(str(gone))
        gone.unlink()
        assert recent_configs() == []

    def test_capped_at_eight(self, ini_settings, tmp_path):
        from utils.app_settings import recent_configs, record_recent_config
        for i in range(12):
            p = tmp_path / f"c{i}.yaml"
            p.write_text("x")
            record_recent_config(str(p))
        assert len(recent_configs()) == 8
        assert recent_configs()[0].endswith("c11.yaml")

    def test_empty_path_ignored(self, ini_settings):
        from utils.app_settings import recent_configs, record_recent_config
        record_recent_config("")
        assert recent_configs() == []


class TestHomeScreenWidget:
    def test_quick_actions_emit(self, qapp):
        from gui.widgets.home_screen import HomeScreen
        home = HomeScreen()
        try:
            fired = []
            home.new_from_template_requested.connect(
                lambda: fired.append("template"))
            home.open_requested.connect(lambda: fired.append("open"))
            home.template_btn.click()
            home.open_btn.click()
            assert fired == ["template", "open"]
        finally:
            home.deleteLater()

    def test_recent_list_populates_and_emits(self, qapp, tmp_path):
        from gui.widgets.home_screen import HomeScreen
        home = HomeScreen()
        try:
            paths = [str(tmp_path / "one.yaml"), str(tmp_path / "two.yaml")]
            home.refresh(paths)
            assert home.recent_paths() == paths
            picked = []
            home.recent_requested.connect(picked.append)
            home._recent_buttons[1].click()
            assert picked == [paths[1]]
            # Refresh replaces, never accumulates
            home.refresh([paths[0]])
            assert home.recent_paths() == [paths[0]]
        finally:
            home.deleteLater()

    def test_empty_recents_hide_the_title(self, qapp):
        from gui.widgets.home_screen import HomeScreen
        home = HomeScreen()
        try:
            home.refresh([])
            assert not home.recent_title.isVisibleTo(home)
        finally:
            home.deleteLater()


class TestShellHosting:
    @pytest.fixture
    def shell_window(self, qapp):
        from PyQt6.QtWidgets import QMainWindow
        from gui.Ui_MainWindow import Ui_MainWindow
        window = QMainWindow()
        ui = Ui_MainWindow()
        ui.setupUi(window)
        yield window, ui
        window.deleteLater()

    def test_starts_on_home_with_hidden_subnav(self, shell_window):
        _, ui = shell_window
        assert ui.page_stack.currentWidget() is ui.home_screen
        assert not ui.subnav.isVisibleTo(ui.centralwidget)
        assert ui.topbar.active_section() is None

    def test_nav_click_leaves_home(self, shell_window):
        _, ui = shell_window
        ui.topbar._buttons["show"].click()
        assert ui.page_stack.currentWidget() is ui.tabWidget
        assert ui.tabWidget.currentIndex() == 3

    def test_external_tab_change_leaves_home(self, shell_window):
        """Ctrl+L path while sitting on Home."""
        _, ui = shell_window
        ui.tabWidget.setCurrentIndex(5)
        assert ui.page_stack.currentWidget() is ui.tabWidget

    def test_brand_click_returns_home(self, shell_window):
        _, ui = shell_window
        ui.topbar._buttons["setup"].click()
        assert ui.page_stack.currentWidget() is ui.tabWidget
        ui.topbar.home_selected.emit()
        assert ui.page_stack.currentWidget() is ui.home_screen
        assert ui.topbar.active_section() is None
