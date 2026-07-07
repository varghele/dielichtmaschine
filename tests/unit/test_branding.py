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
