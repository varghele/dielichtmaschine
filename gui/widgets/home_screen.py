"""Home screen (North Star card 1a).

The landing page: rotor glyph, wordmark hero, slogan, quick actions,
and the recent-configurations list. Self-contained: emits signals, the
MainWindow wires them to its existing handlers. Hosted in the shell's
QStackedWidget above the tab pages (Ui_MainWindow), so it never touches
tab indices.
"""

import os

from PyQt6.QtCore import QCoreApplication, Qt, pyqtSignal
from PyQt6.QtGui import QFont, QPixmap
from PyQt6.QtWidgets import (
    QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from gui.typography import DisplayLabel, MicroLabel, display_font, mono_font
from utils.app_identity import APP_WORDMARK, SLOGAN_DE, SLOGAN_EN, app_icon_path


class RecentConfigButton(QPushButton):
    """One recent entry: filename prominent, full path as tooltip."""

    def __init__(self, path: str, parent=None):
        super().__init__(os.path.basename(path), parent)
        self.path = path
        self.setProperty("role", "recent-config")
        self.setToolTip(path)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFont(mono_font(9))


class HomeScreen(QWidget):
    """Hero + quick actions + recent list."""

    new_from_template_requested = pyqtSignal()
    open_requested = pyqtSignal()
    recent_requested = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("HomeScreen")
        # Needed so the QSS #HomeScreen background (window + grid tile)
        # paints on a plain QWidget.
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        outer = QVBoxLayout(self)
        outer.addStretch(3)

        # Hero: glyph, wordmark, slogan
        glyph = QLabel()
        glyph.setObjectName("HomeGlyph")
        pixmap = QPixmap(app_icon_path())
        if not pixmap.isNull():
            glyph.setPixmap(pixmap.scaled(
                112, 112, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation))
        glyph.setAlignment(Qt.AlignmentFlag.AlignCenter)
        outer.addWidget(glyph)
        outer.addSpacing(16)

        wordmark = QLabel(APP_WORDMARK)
        wordmark.setObjectName("HomeWordmark")
        wordmark.setFont(display_font(40, QFont.Weight.ExtraBold,
                                      tracking_em=0.08))
        wordmark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        outer.addWidget(wordmark)

        slogan = MicroLabel(f"{SLOGAN_EN} · {SLOGAN_DE}", point_size=10,
                            tracking_em=0.2)
        slogan.setObjectName("HomeSlogan")
        slogan.setAlignment(Qt.AlignmentFlag.AlignCenter)
        outer.addWidget(slogan)
        outer.addSpacing(28)

        # Quick actions
        actions = QHBoxLayout()
        actions.addStretch(1)
        self.template_btn = QPushButton(QCoreApplication.translate(
            "Shell", "New from Template"))
        self.template_btn.setProperty("role", "primary")
        self.template_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.template_btn.clicked.connect(self.new_from_template_requested)
        actions.addWidget(self.template_btn)

        self.open_btn = QPushButton(QCoreApplication.translate(
            "Shell", "Open Configuration"))
        self.open_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.open_btn.clicked.connect(self.open_requested)
        actions.addWidget(self.open_btn)
        actions.addStretch(1)
        outer.addLayout(actions)
        outer.addSpacing(32)

        # Recent configurations
        self.recent_title = DisplayLabel(
            QCoreApplication.translate("Shell", "Recent"),
            point_size=12, weight=QFont.Weight.Bold, tracking_em=0.1)
        self.recent_title.setObjectName("HomeRecentTitle")
        self.recent_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        outer.addWidget(self.recent_title)
        outer.addSpacing(6)

        self._recent_box = QVBoxLayout()
        self._recent_box.setSpacing(2)
        recent_row = QHBoxLayout()
        recent_row.addStretch(1)
        recent_row.addLayout(self._recent_box)
        recent_row.addStretch(1)
        outer.addLayout(recent_row)
        self._recent_buttons = []

        outer.addStretch(4)
        self.refresh([])

    def refresh(self, recent_paths) -> None:
        """Rebuild the recent list (most recent first)."""
        for button in self._recent_buttons:
            self._recent_box.removeWidget(button)
            button.hide()
            button.setParent(None)
            button.deleteLater()
        self._recent_buttons = []

        visible = bool(recent_paths)
        self.recent_title.setVisible(visible)
        for path in list(recent_paths)[:8]:
            button = RecentConfigButton(path)
            button.clicked.connect(
                lambda _=False, p=path: self.recent_requested.emit(p))
            self._recent_box.addWidget(button)
            self._recent_buttons.append(button)

    def recent_paths(self):
        return [b.path for b in self._recent_buttons]
