# tests/unit/test_library_paths.py
"""Configurable fixture library paths (ROADMAP v1.2): the user GDTF /
QXF directory settings (utils/app_settings.py), their fold into
fixture_search_dirs() with the documented priority, the definition
cache invalidation on change, and the Settings dialog
(gui/dialogs/library_paths_dialog.py). Settings are hermetic via the
session conftest (IniFormat in a tmp dir)."""

import os
import shutil

import pytest

from utils import app_settings as aps
from utils import fixture_library as fl

CUSTOM_FIXTURES = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))), "custom_fixtures")


@pytest.fixture(autouse=True)
def _clean_library_settings():
    """Each test starts and ends with no user dirs configured."""
    aps.set_user_gdtf_dir("")
    aps.set_user_qxf_dir("")
    yield
    aps.set_user_gdtf_dir("")
    aps.set_user_qxf_dir("")


class TestSettings:
    def test_defaults_live_in_the_user_data_dir(self):
        from utils.app_identity import user_data_dir
        assert aps.user_gdtf_dir() == os.path.join(
            user_data_dir(), "fixtures", "gdtf")
        assert aps.user_qxf_dir() == os.path.join(
            user_data_dir(), "fixtures", "qxf")

    def test_round_trip(self, tmp_path):
        aps.set_user_gdtf_dir(str(tmp_path / "g"))
        aps.set_user_qxf_dir(str(tmp_path / "q"))
        assert aps.user_gdtf_dir() == str(tmp_path / "g")
        assert aps.user_qxf_dir() == str(tmp_path / "q")

    def test_empty_resets_to_default(self, tmp_path):
        aps.set_user_gdtf_dir(str(tmp_path))
        aps.set_user_gdtf_dir("")
        assert aps.user_gdtf_dir() == aps.default_user_gdtf_dir()

    def test_setting_a_dir_invalidates_the_definition_cache(self, tmp_path):
        fl._definition_cache[("Sentinel", "Model")] = None
        aps.set_user_qxf_dir(str(tmp_path))
        assert ("Sentinel", "Model") not in fl._definition_cache


class TestSearchDirs:
    """The REAL fixture_search_dirs (the session conftest wraps the
    module attribute to keep other tests hermetic; the unwrapped
    function is parked as _real_fixture_search_dirs)."""

    def _dirs(self):
        return fl._real_fixture_search_dirs()

    def test_priority_user_gdtf_first_user_qxf_after_bundled(
            self, tmp_path):
        gdtf_dir = tmp_path / "gdtf"
        qxf_dir = tmp_path / "qxf"
        gdtf_dir.mkdir()
        qxf_dir.mkdir()
        aps.set_user_gdtf_dir(str(gdtf_dir))
        aps.set_user_qxf_dir(str(qxf_dir))

        dirs = self._dirs()
        sources = [source for _path, source in dirs]
        assert sources[0] == "user-gdtf"
        assert dirs[0][0] == str(gdtf_dir)
        bundled = sources.index("bundled")
        user_qxf = sources.index("user-qxf")
        assert bundled < user_qxf
        # Everything after the user QXF dir is platform QLC+ dirs.
        assert set(sources[user_qxf + 1:]) <= {"library"}

    def test_missing_user_dirs_are_skipped(self, tmp_path):
        aps.set_user_gdtf_dir(str(tmp_path / "nope"))
        aps.set_user_qxf_dir(str(tmp_path / "nada"))
        sources = [source for _path, source in self._dirs()]
        assert "user-gdtf" not in sources
        assert "user-qxf" not in sources

    def test_unset_settings_fall_back_to_defaults_silently(self):
        # The app-data defaults usually do not exist; the scan must not
        # invent them, just skip.
        for path, source in self._dirs():
            if source in ("user-gdtf", "user-qxf"):
                assert os.path.isdir(path)

    def test_definition_found_in_a_user_qxf_dir(self, tmp_path,
                                                monkeypatch):
        user_dir = tmp_path / "myfixtures"
        user_dir.mkdir()
        shutil.copyfile(
            os.path.join(CUSTOM_FIXTURES, "Martin-MAC-Aura.qxf"),
            user_dir / "Martin-MAC-Aura.qxf")
        monkeypatch.setattr(
            fl, "fixture_search_dirs",
            lambda: [(str(user_dir), "user-qxf")])
        fl.clear_library_cache()
        try:
            defn = fl.get_definition("Martin", "MAC Aura")
            assert defn is not None
            assert defn.path == str(user_dir / "Martin-MAC-Aura.qxf")
        finally:
            fl.clear_library_cache()


class TestDialog:
    def _dialog(self, qapp, monkeypatch, tmp_path):
        from gui.dialogs import library_paths_dialog as mod
        # Keep the dialog's create-on-accept off the real app-data dir.
        g_default = str(tmp_path / "default_gdtf")
        q_default = str(tmp_path / "default_qxf")
        for target in (mod, aps):
            monkeypatch.setattr(target, "default_user_gdtf_dir",
                                lambda: g_default)
            monkeypatch.setattr(target, "default_user_qxf_dir",
                                lambda: q_default)
        return mod.LibraryPathsDialog(), g_default, q_default

    def test_defaults_show_as_placeholders(self, qapp, monkeypatch,
                                           tmp_path):
        dialog, g_default, q_default = self._dialog(
            qapp, monkeypatch, tmp_path)
        assert dialog.gdtf_edit.text() == ""
        assert dialog.gdtf_edit.placeholderText() == g_default
        assert dialog.qxf_edit.placeholderText() == q_default

    def test_accept_persists_creates_and_invalidates(self, qapp,
                                                     monkeypatch,
                                                     tmp_path):
        dialog, _g, _q = self._dialog(qapp, monkeypatch, tmp_path)
        gdtf_dir = str(tmp_path / "gdtf_new")
        qxf_dir = str(tmp_path / "qxf_new")
        dialog.gdtf_edit.setText(gdtf_dir)
        dialog.qxf_edit.setText(qxf_dir)
        fl._definition_cache[("Sentinel", "Model")] = None
        dialog.accept()
        assert aps.user_gdtf_dir() == gdtf_dir
        assert aps.user_qxf_dir() == qxf_dir
        assert os.path.isdir(gdtf_dir) and os.path.isdir(qxf_dir)
        assert ("Sentinel", "Model") not in fl._definition_cache

    def test_accept_with_empty_fields_keeps_the_defaults(self, qapp,
                                                         monkeypatch,
                                                         tmp_path):
        dialog, g_default, q_default = self._dialog(
            qapp, monkeypatch, tmp_path)
        dialog.accept()
        # '' persisted = "use the default"; the defaults were created.
        assert aps.app_settings().value(
            "library/user_gdtf_dir", "", type=str) == ""
        assert os.path.isdir(g_default) and os.path.isdir(q_default)

    def test_reject_persists_nothing(self, qapp, monkeypatch, tmp_path):
        dialog, _g, _q = self._dialog(qapp, monkeypatch, tmp_path)
        dialog.gdtf_edit.setText(str(tmp_path / "never"))
        dialog.reject()
        assert aps.user_gdtf_dir() == aps.default_user_gdtf_dir()

    def test_stored_value_equal_to_default_shows_as_placeholder(
            self, qapp, monkeypatch, tmp_path):
        from gui.dialogs import library_paths_dialog as mod
        g_default = str(tmp_path / "default_gdtf")
        q_default = str(tmp_path / "default_qxf")
        for target in (mod, aps):
            monkeypatch.setattr(target, "default_user_gdtf_dir",
                                lambda: g_default)
            monkeypatch.setattr(target, "default_user_qxf_dir",
                                lambda: q_default)
        aps.set_user_gdtf_dir(g_default)
        dialog = mod.LibraryPathsDialog()
        assert dialog.gdtf_edit.text() == ""