# tests/unit/test_about_dialog.py
"""The branded About dialog (2026-07-21, replaced QMessageBox.about).

Identity (wordmark, slogan, version, domain) pulls from
utils.app_identity; the rating plate is app_identity.rating_plate -
the SAME facts the README banner renders (one copy, mapped to colours
per consumer). ABOUT_BODY is the user-editable paragraph (todo.md has
the user hand-writing the final copy before v1.5.0). House rule: no
em-dashes anywhere in the visible strings.
"""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture
def dialog(qapp):
    from gui.theme_manager import ThemeManager
    from gui.dialogs.about_dialog import AboutDialog
    ThemeManager().apply(qapp, "dark")
    dlg = AboutDialog(None)
    yield dlg
    dlg.deleteLater()


class TestIdentity:

    def test_wordmark_and_slogan(self, dialog):
        from utils import app_identity
        assert dialog.wordmark_label.text() == app_identity.APP_WORDMARK
        # MicroLabel uppercases; the slogan already is.
        assert dialog.slogan_label.text() == app_identity.SLOGAN_DE
        assert app_identity.APP_NAME in dialog.windowTitle()

    def test_version_stamps_from_identity(self, dialog):
        from utils import app_identity
        plate_text = " ".join(label.text()
                              for label in dialog.plate_labels)
        assert f"v{app_identity.APP_VERSION}" in plate_text

    def test_domain_is_a_real_link(self, dialog):
        from utils import app_identity
        assert f'href="https://{app_identity.APP_DOMAIN}"' \
            in dialog.link_label.text()
        assert dialog.link_label.openExternalLinks()

    def test_close_accepts(self, dialog):
        dialog.close_button.click()
        from PyQt6.QtWidgets import QDialog
        assert dialog.result() == QDialog.DialogCode.Accepted


class TestRatingPlate:

    def test_one_row_per_plate_line(self, dialog):
        from utils.app_identity import rating_plate
        assert len(dialog.plate_labels) == len(rating_plate())

    def test_every_fact_renders(self, dialog):
        from utils.app_identity import rating_plate
        plate_text = " ".join(label.text()
                              for label in dialog.plate_labels)
        for line in rating_plate():
            for text, _emphasis in line:
                assert text in plate_text, text

    def test_banner_script_maps_the_same_facts(self):
        """scripts/render_brand_assets.plate_lines is a colour mapping
        over rating_plate - the banner and the dialog can never drift."""
        from scripts.render_brand_assets import PLATE_COLOURS, plate_lines
        from utils.app_identity import rating_plate
        rendered = plate_lines("9.9.9")
        facts = rating_plate("9.9.9")
        assert [[t for t, _ in line] for line in rendered] == \
            [[t for t, _ in line] for line in facts]
        assert [[c for _, c in line] for line in rendered] == \
            [[PLATE_COLOURS[e] for _, e in line] for line in facts]


class TestHouseRules:

    def test_no_em_dashes_anywhere(self, dialog):
        from gui.dialogs.about_dialog import ABOUT_BODY
        from utils.app_identity import rating_plate
        strings = [ABOUT_BODY, dialog.windowTitle(),
                   dialog.body_label.text()]
        strings += [text for line in rating_plate()
                    for text, _ in line]
        for value in strings:
            assert "—" not in value and "–" not in value, value

    def test_show_about_opens_the_branded_dialog(self, qapp, monkeypatch):
        """gui.show_about routes to AboutDialog (not QMessageBox) -
        checked at the source level so no MainWindow build is needed."""
        import inspect
        from gui.gui import MainWindow
        source = inspect.getsource(MainWindow.show_about)
        assert "AboutDialog" in source
        assert "QMessageBox" not in source
