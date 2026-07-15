"""i18n scaffolding: catalog integrity and the translator loader."""

import os
import xml.etree.ElementTree as ET

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from utils.translations import catalog_path, install_translator, translations_dir


class TestGermanCatalog:
    def _root(self):
        path = os.path.join(translations_dir(), "lichtmaschine_de.ts")
        assert os.path.isfile(path)
        return ET.parse(path).getroot()

    def test_parses_with_shell_context(self):
        root = self._root()
        contexts = [c.findtext("name") for c in root.findall("context")]
        assert "Shell" in contexts

    def test_covers_the_shell_vocabulary(self):
        root = self._root()
        shell = next(c for c in root.findall("context")
                     if c.findtext("name") == "Shell")
        sources = {m.findtext("source") for m in shell.findall("message")}
        expected = {"Setup", "Show", "Auto", "Universes", "Fixtures",
                    "Stage", "Structure", "Timeline", "Ready", "Menu"}
        missing = expected - sources
        assert not missing, f"catalog lacks shell strings: {sorted(missing)}"

    def test_every_message_has_a_translation(self):
        root = self._root()
        for message in root.iter("message"):
            source = message.findtext("source")
            translation = message.find("translation")
            assert translation is not None and (translation.text or ""), source


class TestInstallTranslator:
    @pytest.fixture
    def ini_settings(self, tmp_path, monkeypatch):
        from PyQt6.QtCore import QSettings
        from utils import app_settings as mod
        monkeypatch.setattr(mod, "_settings_format",
                            QSettings.Format.IniFormat)
        QSettings.setPath(QSettings.Format.IniFormat,
                          QSettings.Scope.UserScope, str(tmp_path))
        yield

    def test_unset_language_installs_nothing(self, qapp, ini_settings):
        assert install_translator(qapp) is False

    def test_english_installs_nothing(self, qapp, ini_settings):
        from utils.app_settings import app_settings
        app_settings().setValue("ui/language", "en")
        assert install_translator(qapp) is False

    def test_missing_catalog_degrades_gracefully(self, qapp, ini_settings):
        from utils.app_settings import app_settings
        app_settings().setValue("ui/language", "xx")
        assert install_translator(qapp) is False
        assert not os.path.exists(catalog_path("xx"))
