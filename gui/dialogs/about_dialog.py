# gui/dialogs/about_dialog.py
"""The branded About dialog (Help > About).

Replaces the generic QMessageBox.about (2026-07-21): the rotor glyph
and wordmark up top, the slogan, a short body text, the machine's
RATING PLATE (the same verifiable facts as the README banner, from
utils.app_identity.rating_plate - one copy), and the domain as a real
link. Identity fields (name, version, domain, slogan) all pull from
utils.app_identity, so a release bump changes the dialog without
touching this file.

ABOUT_BODY is a plain module constant carrying the author's copy
(hand-written 2026-07-23) - edit the constant, nothing else, then
regenerate the golden (test_about_dialog_golden.py). House rules
apply: no em-dashes, separator is " · ".
"""

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QPixmap
from PyQt6.QtWidgets import (QDialog, QFrame, QHBoxLayout, QLabel,
                             QPushButton, QVBoxLayout)

from gui.fonts import FONT_MONO
from gui.typography import DisplayLabel, MicroLabel, mono_font
from utils import app_identity

#: The human paragraph - the author's own words (2026-07-23). Each
#: line is a separate string literal, so keep a trailing space on
#: every line but the last, or sentences run together at the joins.
ABOUT_BODY = (
    "Hello and welcome, you have found the Lichtmaschine! Step right up! "
    "If you read this: first of all, thank you very much for checking out "
    "the code, it means a lot to me. "
    "Now, this little program is meant to take care of the light-show needs "
    "of your band, be you big or be you small. "
    "With it you can pre-program light shows the way you would arrange sound "
    "in a DAW, and run them live via LTC, MTC (WIP) or MIDI (WIP). "
    "If you want to see how it works, you can run the automatic generation, "
    "or busk along with the Live tab. "
    "Check out the visualizer too, so you get immediate 3D renderings of "
    "your show! We work with the GDTF lighting standard, but also support "
    "import and export from QLC+, "
    "another marvelous free lighting program (seriously, check them out, "
    "they might fit your needs even better). "
    "I'll keep working on this to support MIDI controllers, custom effect "
    "creation and much more, so check in regularly. "
    "And last but not least: this is free, but non-commercial. If you want "
    "to do a good deed, spend your money on an animal shelter, "
    "or on literally any other worthwhile online project (might I recommend "
    "Wikipedia?), because I already earn a comfortable living. "
    "Take code from this project if you like, but please do not "
    "commercialise it. That would be so not radical of you. "
    "Otherwise, have fun, good luck with your project, and if you wish for a "
    "feature or encounter a bug, let me know on the repo! "
    "Cheers! -V"
)


def _active_tokens() -> dict:
    """The token dict of the applied theme (same sniff as the tabs:
    the applied stylesheet is the only record of the active theme)."""
    from PyQt6.QtWidgets import QApplication
    from gui.theme_tokens import THEMES

    app = QApplication.instance()
    qss = app.styleSheet() if app is not None else ""
    light = THEMES.get("light")
    if light is not None and light["window"] in qss:
        return light
    return THEMES["dark"]


class AboutDialog(QDialog):
    """Modal About card: brand block, body, rating plate, links."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"About {app_identity.APP_NAME}")
        self.setObjectName("AboutDialog")
        self.setFixedWidth(520)

        tokens = _active_tokens()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 20)
        layout.setSpacing(14)

        # Brand block: rotor glyph + wordmark, slogan underneath.
        brand_row = QHBoxLayout()
        brand_row.setSpacing(14)
        glyph = QLabel()
        glyph.setObjectName("AboutGlyph")
        pixmap = QPixmap(app_identity.app_icon_path())
        if not pixmap.isNull():
            glyph.setPixmap(pixmap.scaled(
                44, 44, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation))
        brand_row.addWidget(glyph)

        name_column = QVBoxLayout()
        name_column.setSpacing(2)
        self.wordmark_label = DisplayLabel(
            app_identity.APP_WORDMARK, point_size=21,
            weight=QFont.Weight.ExtraBold, tracking_em=0.08)
        name_column.addWidget(self.wordmark_label)
        self.slogan_label = MicroLabel(app_identity.SLOGAN_DE,
                                       point_size=8, tracking_em=0.18)
        self.slogan_label.setStyleSheet(
            f"color: {tokens['accent']}; background: transparent;")
        name_column.addWidget(self.slogan_label)
        brand_row.addLayout(name_column)
        brand_row.addStretch(1)
        layout.addLayout(brand_row)

        # Body copy (ABOUT_BODY - the user-editable part).
        self.body_label = QLabel(ABOUT_BODY)
        self.body_label.setWordWrap(True)
        self.body_label.setMinimumWidth(1)
        layout.addWidget(self.body_label)

        # Rating plate: the banner's facts, emphasis mapped onto the
        # theme (shipped = full text colour, outstanding/label dimmed).
        plate = QFrame()
        plate.setObjectName("AboutPlate")
        plate.setStyleSheet(
            f"#AboutPlate {{ background-color: {tokens['panel']};"
            f" border: 1px solid {tokens['border']}; }}")
        plate_layout = QVBoxLayout(plate)
        plate_layout.setContentsMargins(14, 10, 14, 10)
        plate_layout.setSpacing(4)
        emphasis_colours = {"shipped": tokens["text"],
                            "outstanding": tokens["text_disabled"],
                            "label": tokens["text_secondary"]}
        self.plate_labels = []
        for line in app_identity.rating_plate():
            rich = "".join(
                f'<span style="color: {emphasis_colours[emphasis]};">'
                f"{text}</span>" for text, emphasis in line)
            row = QLabel(rich)
            row.setFont(mono_font(8, QFont.Weight.Medium,
                                  tracking_em=0.08))
            row.setTextFormat(Qt.TextFormat.RichText)
            # The app-wide QWidget font-family rule beats setFont
            # (qt-gotchas): pin the mono family for the plate rows.
            row.setStyleSheet(f"font-family: '{FONT_MONO}';"
                              " background: transparent;")
            plate_layout.addWidget(row)
            self.plate_labels.append(row)
        layout.addWidget(plate)

        # Footer: domain link left, CLOSE right.
        footer = QHBoxLayout()
        self.link_label = QLabel(
            f'<a style="color: {tokens["accent"]};" '
            f'href="https://{app_identity.APP_DOMAIN}">'
            f"{app_identity.APP_DOMAIN}</a>")
        self.link_label.setTextFormat(Qt.TextFormat.RichText)
        self.link_label.setOpenExternalLinks(True)
        self.link_label.setFont(mono_font(8))
        self.link_label.setStyleSheet(
            f"font-family: '{FONT_MONO}'; background: transparent;")
        footer.addWidget(self.link_label)
        footer.addStretch(1)
        self.close_button = QPushButton("CLOSE")
        self.close_button.setProperty("role", "output-select")
        self.close_button.setFont(mono_font(8, QFont.Weight.Medium))
        self.close_button.setDefault(True)
        self.close_button.clicked.connect(self.accept)
        footer.addWidget(self.close_button)
        layout.addLayout(footer)
