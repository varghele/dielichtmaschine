"""UI translation loading (i18n scaffolding, shell pass S3).

English is the source language and the default. A different language
is opted into via the ``ui/language`` setting (e.g. ``de``); the
corresponding compiled catalog ``translations/lichtmaschine_<lang>.qm``
is then installed on the QApplication. The editable catalogs are the
``.ts`` files next to it (source of truth, committed); compile them
with Qt Linguist's lrelease - see scripts/update_translations.py.

There is deliberately no language-switcher UI yet; set the value by
hand or leave it unset for English.
"""

import os

from PyQt6.QtCore import QTranslator

from utils.paths import get_project_root

CATALOG_PREFIX = "lichtmaschine_"


def translations_dir() -> str:
    return os.path.join(get_project_root(), "translations")


def catalog_path(language: str) -> str:
    return os.path.join(translations_dir(), f"{CATALOG_PREFIX}{language}.qm")


def install_translator(app) -> bool:
    """Install the user's chosen UI language on the application.

    Returns True when a translator was installed. English (or an unset
    setting, or a missing/uncompiled catalog) leaves the app untouched
    and returns False - the UI then shows the English source strings.
    """
    from utils.app_settings import app_settings

    language = app_settings().value("ui/language", type=str)
    if not language or language == "en":
        return False

    path = catalog_path(language)
    translator = QTranslator(app)
    if not translator.load(path):
        print(f"i18n: no compiled catalog for '{language}' at {path}; "
              f"falling back to English")
        return False
    app.installTranslator(translator)
    return True
