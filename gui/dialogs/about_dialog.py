# gui/dialogs/about_dialog.py
"""The branded About dialog (Help > About).

Replaces the generic QMessageBox.about (2026-07-21): the rotor glyph
and wordmark up top, the slogan, a short body text, the machine's
RATING PLATE (the same verifiable facts as the README banner, from
utils.app_identity.rating_plate - one copy), and the domain as a real
link. Identity fields (name, version, domain, slogan) all pull from
utils.app_identity, so a release bump changes the dialog without
touching this file.

ABOUT_BODY is deliberately a plain module constant: the v1.5 release
list (todo.md) has the user hand-writing the final copy - edit the
constant, nothing else. House rules apply: no em-dashes, separator
is " · ".
"""

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QPixmap
from PyQt6.QtWidgets import (QDialog, QFrame, QHBoxLayout, QLabel,
                             QPushButton, QVBoxLayout)

from gui.fonts import FONT_MONO
from gui.typography import DisplayLabel, MicroLabel, mono_font
from utils import app_identity

#: The human paragraph. USER-AUTHORED copy pending (todo.md, v1.5
#: release list) - this placeholder describes the tool factually until
#: the real text lands.
ABOUT_BODY = (
    "Standalone light show authoring for bands and small stages: "
    "beat-synced timelines, GDTF and QLC+ fixtures, printable stage "
    "plots, automatic show generation, a real-time 3D preview and "
    "native ArtNet playback."
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
