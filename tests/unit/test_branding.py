"""Brand foundation: identity constants, brand assets, shipped fonts.

The rebrand (docs/rebranding-plan.md) hinges on utils/app_identity.py
being the single source of truth and on the assets/fonts actually being
present and loadable, so packaging can't silently ship without them.
"""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from utils import app_identity


class TestIdentityConstants:
    def test_product_name(self):
        assert app_identity.APP_NAME == "Die Lichtmaschine"
        assert app_identity.APP_WORDMARK == "DIE LICHTMASCHINE"

    def test_settings_identity_is_space_free(self):
        assert " " not in app_identity.SETTINGS_ORG
        assert " " not in app_identity.SETTINGS_APP

    def test_legacy_identity_kept_for_migration(self):
        assert app_identity.LEGACY_SETTINGS_ORG == "QLCShowCreator"
        assert app_identity.LEGACY_SETTINGS_APP == "QLCShowCreator"

    def test_version_string_carries_name_and_version(self):
        s = app_identity.version_string()
        assert app_identity.APP_NAME in s
        assert app_identity.APP_VERSION in s

    def test_no_em_dashes_in_identity_strings(self):
        for name in dir(app_identity):
            value = getattr(app_identity, name)
            if isinstance(value, str):
                assert "—" not in value and "–" not in value, name


class TestBrandAssets:
    def test_icon_pngs_present_in_all_sizes(self):
        for size in (16, 32, 48, 64, 128, 256, 512):
            path = os.path.join(app_identity.brand_dir(), f"icon-{size}.png")
            assert os.path.isfile(path), path

    def test_app_icon_path_exists(self):
        assert os.path.isfile(app_identity.app_icon_path())

    def test_windows_ico_has_all_frames(self):
        from PIL import Image
        path = app_identity.app_ico_path()
        assert os.path.isfile(path)
        ico = Image.open(path)
        assert ico.info.get("sizes") == {
            (16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)}

    def test_icon_loads_as_qicon(self, qapp):
        from PyQt6.QtGui import QIcon
        icon = QIcon(app_identity.app_icon_path())
        assert not icon.isNull()


class TestBrandFonts:
    def test_expected_ttf_files_shipped_with_licenses(self):
        from gui.fonts import fonts_dir
        names = set(os.listdir(fonts_dir()))
        expected = {
            "Barlow-Regular.ttf", "Barlow-Medium.ttf", "Barlow-SemiBold.ttf",
            "BarlowCondensed-SemiBold.ttf", "BarlowCondensed-Bold.ttf",
            "BarlowCondensed-ExtraBold.ttf",
            "IBMPlexMono-Regular.ttf", "IBMPlexMono-Medium.ttf",
            "IBMPlexMono-SemiBold.ttf",
            "OFL-Barlow.txt", "OFL-BarlowCondensed.txt", "OFL-IBMPlexMono.txt",
        }
        missing = expected - names
        assert not missing, f"missing shipped font files: {sorted(missing)}"

    def test_register_brand_fonts_reports_all_families(self, qapp):
        from gui import fonts
        families = fonts.register_brand_fonts()
        if not families:
            pytest.skip("platform font database rejected application fonts "
                        "(offscreen QPA without font support)")
        joined = " ".join(families)
        for family in (fonts.FONT_UI, fonts.FONT_DISPLAY, fonts.FONT_MONO):
            assert family in joined, (family, families)

    def test_register_is_idempotent(self, qapp):
        from gui.fonts import register_brand_fonts
        first = register_brand_fonts()
        second = register_brand_fonts()
        assert sorted(first) == sorted(second)


@pytest.fixture
def ini_settings(tmp_path, monkeypatch):
    """Redirect QSettings to INI files under tmp_path so tests never
    touch the real registry/config dir. Yields the tmp path."""
    from PyQt6.QtCore import QSettings
    from utils import app_settings as mod
    monkeypatch.setattr(mod, "_settings_format", QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat,
                      QSettings.Scope.UserScope, str(tmp_path))
    yield tmp_path


class TestSettingsMigration:
    def _legacy(self):
        from utils import app_settings as mod
        return mod._make(app_identity.LEGACY_SETTINGS_ORG,
                         app_identity.LEGACY_SETTINGS_APP)

    def test_copies_legacy_keys_once(self, ini_settings):
        from utils.app_settings import app_settings, migrate_legacy_settings
        legacy = self._legacy()
        legacy.setValue("ui/theme", "light")
        legacy.setValue("stage/main_splitter", b"state")
        legacy.sync()

        assert migrate_legacy_settings() == 2
        assert app_settings().value("ui/theme") == "light"
        # Second run is a no-op even if the legacy store changes.
        legacy.setValue("ui/theme", "dark")
        legacy.sync()
        assert migrate_legacy_settings() == 0
        assert app_settings().value("ui/theme") == "light"

    def test_existing_new_keys_never_clobbered(self, ini_settings):
        from utils.app_settings import app_settings, migrate_legacy_settings
        legacy = self._legacy()
        legacy.setValue("ui/theme", "light")
        legacy.sync()
        app_settings().setValue("ui/theme", "dark")

        migrate_legacy_settings()
        assert app_settings().value("ui/theme") == "dark"

    def test_empty_legacy_store_is_fine(self, ini_settings):
        from utils.app_settings import migrate_legacy_settings
        assert migrate_legacy_settings() == 0

    def test_theme_manager_uses_new_store(self, ini_settings, qapp):
        from gui.theme_manager import ThemeManager
        from utils.app_settings import app_settings
        tm = ThemeManager()
        tm.set_current("light")
        assert app_settings().value("ui/theme") == "light"
        assert tm.current() == "light"


class TestIdentitySwitchover:
    def test_main_window_title_is_product_name(self, qapp):
        from PyQt6.QtWidgets import QMainWindow
        from gui.Ui_MainWindow import Ui_MainWindow
        window = QMainWindow()
        try:
            ui = Ui_MainWindow()
            ui.setupUi(window)
            assert window.windowTitle() == app_identity.APP_NAME
            assert "QLC" not in window.windowTitle()
        finally:
            window.deleteLater()

    def test_no_stray_legacy_qsettings_constructions(self):
        """No code outside the settings module may build the legacy
        QSettings identity; everything goes through app_settings()."""
        import subprocess
        result = subprocess.run(
            ["git", "grep", "-l", 'QSettings("QLCShowCreator"', "--",
             "*.py", ":!utils/app_settings.py", ":!tests/"],
            capture_output=True, text=True,
            cwd=os.path.dirname(os.path.dirname(os.path.dirname(
                os.path.abspath(__file__)))),
        )
        assert result.stdout.strip() == "", result.stdout

    def test_version_flag_prints_brand(self):
        import subprocess
        import sys as _sys
        root = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))))
        env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
        result = subprocess.run(
            [_sys.executable, "main.py", "--version"],
            capture_output=True, text=True, cwd=root, env=env, timeout=120,
        )
        assert result.returncode == 0, result.stderr
        assert app_identity.version_string() in result.stdout
