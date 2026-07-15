"""Home screen, built against the design reference
docs/design/screens/01-home-startfenster.html.

Anatomy: two centered columns on the engineering grid.
Left (460px): horizontal brand lockup (64px rotor glyph beside the
52px condensed-caps wordmark), a 3px x 80px accent rule with the
slogan, NEW PROJECT / OPEN... CTAs, and the recent-files rows
(filename left, relative age right). Right (560px): the FROM ZERO TO
SHOW checklist card - five steps whose done-state is computed from the
live Configuration; the current step is highlighted with the accent
left border and its screen tag; clicking a step jumps to that screen.

Self-contained: emits signals, MainWindow wires them.
"""

import os
import time

from PyQt6.QtCore import QCoreApplication, Qt, pyqtSignal
from PyQt6.QtGui import QFont, QPixmap
from PyQt6.QtWidgets import (
    QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from gui.typography import MicroLabel, display_font, mono_font
from utils.app_identity import APP_WORDMARK, SLOGAN_EN, app_icon_path


# NOTE: all user-visible strings below use LITERAL
# QCoreApplication.translate("Shell", "...") calls - pylupdate6 cannot
# extract literals hidden behind wrapper functions (documented gotcha).

def relative_age(path: str, now: float = None) -> str:
    """'today' / 'yesterday' / 'N days ago' from the file's mtime."""
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return ""
    now = time.time() if now is None else now
    days = max(0, int((now - mtime) / 86400.0))
    if days == 0:
        return QCoreApplication.translate("Shell", "today")
    if days == 1:
        return QCoreApplication.translate("Shell", "yesterday")
    return f"{days} " + QCoreApplication.translate("Shell", "days ago")


# ── Checklist model ────────────────────────────────────────────────────
# (title, description, screen tag, tab index, done-predicate)

def _has_universes(config):
    return bool(getattr(config, "universes", None))


def _has_fixtures(config):
    return bool(getattr(config, "fixtures", None))


def _has_placed_fixtures(config):
    return any((f.x, f.y) != (0.0, 0.0)
               for f in getattr(config, "fixtures", []) or []) or \
        bool(getattr(config, "stage_elements", None))


def _has_structure(config):
    songs = getattr(config, "songs", {}) or {}
    return any(getattr(s, "parts", None) for s in songs.values())


def _has_timeline_content(config):
    songs = (getattr(config, "songs", {}) or {}).values()
    for show in songs:
        timeline = getattr(show, "timeline_data", None)
        for lane in getattr(timeline, "light_lanes", []) or []:
            if getattr(lane, "light_blocks", None):
                return True
    return False


def checklist_steps():
    return [
        (QCoreApplication.translate("Shell", "Add a universe, pick DMX output"),
         QCoreApplication.translate("Shell", "E1.31, ArtNet or USB DMX - where the light goes."),
         "SETUP · UNIVERSES", 0, _has_universes),
        (QCoreApplication.translate("Shell", "Import fixtures, group them by role"),
         QCoreApplication.translate("Shell", "GDTF or QLC+ definitions, grouped the way you busk."),
         "SETUP · FIXTURES", 1, _has_fixtures),
        (QCoreApplication.translate("Shell", "Place fixtures on the stage plot"),
         QCoreApplication.translate("Shell", "Drag into position - the 3D pane shows what you're placing."),
         "SETUP · STAGE", 2, _has_placed_fixtures),
        (QCoreApplication.translate("Shell", "Define the song structure"),
         QCoreApplication.translate("Shell", "Parts, BPM, time signature - the grid everything snaps to."),
         "SHOW · STRUCTURE", 3, _has_structure),
        (QCoreApplication.translate("Shell", "Build the show - or let the machine generate one"),
         QCoreApplication.translate("Shell", "Paint blocks on the timeline, drop riffs, or run Autogenerate."),
         "SHOW · TIMELINE", 4, _has_timeline_content),
    ]


class ChecklistRow(QWidget):
    """One FROM ZERO TO SHOW step. States: done / current / upcoming."""

    clicked = pyqtSignal(int)  # tab index

    def __init__(self, number, title, description, tag, tab_index,
                 parent=None):
        super().__init__(parent)
        self.tab_index = tab_index
        self.setObjectName("ChecklistRow")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(20, 12, 20, 12)
        layout.setSpacing(14)

        self.marker = QLabel(f"{number:02d}")
        self.marker.setObjectName("ChecklistMarker")
        self.marker.setFont(mono_font(9))
        self.marker.setFixedWidth(20)
        layout.addWidget(self.marker)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("ChecklistStepTitle")
        title_font = self.title_label.font()
        title_font.setBold(True)
        self.title_label.setFont(title_font)
        text_col.addWidget(self.title_label)
        self.description_label = QLabel(description)
        self.description_label.setObjectName("ChecklistDescription")
        text_col.addWidget(self.description_label)
        layout.addLayout(text_col, 1)

        self.tag_label = QLabel(tag)
        self.tag_label.setObjectName("ChecklistTag")
        self.tag_label.setFont(mono_font(8, tracking_em=0.08))
        layout.addWidget(self.tag_label)

        self._number = number
        self.set_state("upcoming")

    def set_state(self, state: str) -> None:
        """done | current | upcoming - drives QSS + the marker/tag.

        The done strikethrough comes from the theme QSS
        (text-decoration on #ChecklistStepTitle), NOT QFont.strikeOut:
        the repolish below re-applies the stylesheet font, which wiped
        a code-set strikeout depending on theme state.
        """
        self.setProperty("state", state)
        if state == "done":
            self.marker.setText("✓")  # check, exists in Plex Mono
            self.description_label.setVisible(False)
        else:
            self.marker.setText(f"{self._number:02d}")
            self.description_label.setVisible(True)
        style = self.style()
        if style:
            style.unpolish(self)
            style.polish(self)
            for child in (self.marker, self.title_label,
                          self.description_label, self.tag_label):
                style.unpolish(child)
                style.polish(child)

    def mousePressEvent(self, event):
        self.clicked.emit(self.tab_index)
        event.accept()


class RecentRow(QWidget):
    """One recent-config row: filename left, relative age right."""

    clicked = pyqtSignal(str)

    def __init__(self, path: str, parent=None):
        super().__init__(parent)
        self.path = path
        self.setObjectName("RecentRow")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(path)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 9, 12, 9)
        self.name_label = QLabel(os.path.basename(path))
        layout.addWidget(self.name_label)
        layout.addStretch(1)
        self.age_label = QLabel(relative_age(path))
        self.age_label.setFont(mono_font(9))
        self.age_label.setObjectName("RecentAge")
        layout.addWidget(self.age_label)

    def mousePressEvent(self, event):
        self.clicked.emit(self.path)
        event.accept()


class HomeScreen(QWidget):
    """Reference-faithful Home: hero column + checklist card."""

    new_from_template_requested = pyqtSignal()
    open_requested = pyqtSignal()
    recent_requested = pyqtSignal(str)
    go_to_screen = pyqtSignal(int)  # tab index from the checklist

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("HomeScreen")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._config = None

        outer = QHBoxLayout(self)
        outer.addStretch(1)

        # ── Left column: brand lockup, slogan, CTAs, recents ──────────
        left = QVBoxLayout()
        left.setSpacing(20)
        left_host = QWidget()
        # Minimum per the reference column; the wordmark's natural width
        # may push it wider (QLabel clips at fixed widths where the
        # reference CSS just overflows).
        left_host.setMinimumWidth(460)
        left_host.setMaximumWidth(560)
        left_host.setLayout(left)

        # Row 1: the ringed rotor glyph vertically centered on the
        # wordmark (reference: 64px glyph, align-items center).
        lockup = QHBoxLayout()
        lockup.setSpacing(18)
        glyph = QLabel()
        glyph.setObjectName("HomeGlyph")
        from PyQt6.QtGui import QIcon
        from utils.app_identity import brand_glyph_ring_path
        glyph.setPixmap(QIcon(brand_glyph_ring_path()).pixmap(64, 64))
        glyph.setFixedSize(64, 64)
        lockup.addWidget(glyph, 0, Qt.AlignmentFlag.AlignVCenter)

        # Two-line hero wordmark (explicit break instead of QLabel word
        # wrap so the size hint is exact and nothing clips). Family +
        # 800 weight are pinned by the #HomeWordmark QSS rule - the
        # app-wide font-family rule otherwise races setFont and thinned
        # the hero.
        wordmark = QLabel(APP_WORDMARK.replace(" ", "\n", 1))
        wordmark.setObjectName("HomeWordmark")
        wordmark.setFont(display_font(38, QFont.Weight.ExtraBold,
                                      tracking_em=0.03))
        lockup.addWidget(wordmark, 1, Qt.AlignmentFlag.AlignVCenter)
        left.addLayout(lockup)

        # Row 2: accent rule + slogan, indented to the text column
        # (starts where the wordmark starts, like the reference).
        slogan_row = QHBoxLayout()
        slogan_row.setSpacing(12)
        slogan_row.addSpacing(64 + 18)
        rule = QWidget()
        rule.setObjectName("HomeAccentRule")
        rule.setFixedSize(80, 3)
        slogan_row.addWidget(rule)
        slogan = MicroLabel(SLOGAN_EN, point_size=9, tracking_em=0.14)
        slogan.setObjectName("HomeSlogan")
        slogan_row.addWidget(slogan)
        slogan_row.addStretch(1)
        left.addLayout(slogan_row)

        ctas = QHBoxLayout()
        ctas.setSpacing(12)
        self.template_btn = QPushButton(
            QCoreApplication.translate("Shell", "New Project").upper())
        self.template_btn.setProperty("role", "cta-accent")
        self.template_btn.setFont(display_font(13, QFont.Weight.Bold,
                                               tracking_em=0.08))
        self.template_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.template_btn.clicked.connect(self.new_from_template_requested)
        ctas.addWidget(self.template_btn)

        self.open_btn = QPushButton(
            QCoreApplication.translate("Shell", "Open...").upper())
        self.open_btn.setProperty("role", "cta-outline")
        self.open_btn.setFont(display_font(13, QFont.Weight.DemiBold,
                                           tracking_em=0.08))
        self.open_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.open_btn.clicked.connect(self.open_requested)
        ctas.addWidget(self.open_btn)
        ctas.addStretch(1)
        left.addLayout(ctas)

        self.recent_title = MicroLabel(
            QCoreApplication.translate("Shell", "Recent"),
            point_size=8, tracking_em=0.12)
        self.recent_title.setObjectName("HomeRecentTitle")
        left.addWidget(self.recent_title)

        self._recent_box = QVBoxLayout()
        self._recent_box.setSpacing(-1)  # collapse adjacent row borders
        left.addLayout(self._recent_box)
        self._recent_rows = []

        # Center both columns as one unit (reference: align-items:center).
        left_wrap = QVBoxLayout()
        left_wrap.addStretch(1)
        left_wrap.addWidget(left_host)
        left_wrap.addStretch(1)
        outer.addLayout(left_wrap)
        outer.addSpacing(80)

        # ── Right column: FROM ZERO TO SHOW checklist ─────────────────
        self.checklist_card = QWidget()
        self.checklist_card.setObjectName("ChecklistCard")
        self.checklist_card.setProperty("role", "card")
        self.checklist_card.setAttribute(
            Qt.WidgetAttribute.WA_StyledBackground, True)
        self.checklist_card.setFixedWidth(560)
        card = QVBoxLayout(self.checklist_card)
        card.setContentsMargins(0, 0, 0, 0)
        card.setSpacing(0)

        header = QWidget()
        header.setObjectName("ChecklistHeader")
        header.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        header_row = QHBoxLayout(header)
        header_row.setContentsMargins(20, 14, 20, 14)
        header_title = QLabel(QCoreApplication.translate(
            "Shell", "From zero to show").upper())
        header_title.setFont(display_font(14, QFont.Weight.Bold,
                                          tracking_em=0.08))
        header_title.setObjectName("ChecklistTitle")
        header_row.addWidget(header_title)
        header_row.addStretch(1)
        self.progress_label = QLabel("")
        self.progress_label.setFont(mono_font(8))
        self.progress_label.setObjectName("ChecklistProgress")
        header_row.addWidget(self.progress_label)
        card.addWidget(header)

        self.checklist_rows = []
        for number, (title, description, tag, tab_index, _predicate) in \
                enumerate(checklist_steps(), start=1):
            row = ChecklistRow(number, title, description, tag, tab_index)
            row.clicked.connect(self.go_to_screen)
            card.addWidget(row)
            self.checklist_rows.append(row)

        column_wrap = QVBoxLayout()
        column_wrap.addStretch(1)
        column_wrap.addWidget(self.checklist_card)
        column_wrap.addStretch(1)
        outer.addLayout(column_wrap)
        outer.addStretch(1)

        self.refresh([])
        self.refresh_checklist(None)

    # ── Data refresh ──────────────────────────────────────────────────
    def refresh(self, recent_paths) -> None:
        for row in self._recent_rows:
            self._recent_box.removeWidget(row)
            row.hide()
            row.setParent(None)
            row.deleteLater()
        self._recent_rows = []
        visible = bool(recent_paths)
        self.recent_title.setVisible(visible)
        for path in list(recent_paths)[:5]:
            row = RecentRow(path)
            row.clicked.connect(self.recent_requested)
            self._recent_box.addWidget(row)
            self._recent_rows.append(row)

    def refresh_checklist(self, config) -> None:
        """Recompute step states from the configuration (None = fresh)."""
        self._config = config
        done_flags = []
        for (_t, _d, _tag, _i, predicate) in checklist_steps():
            try:
                done_flags.append(bool(config is not None
                                       and predicate(config)))
            except Exception:
                done_flags.append(False)
        current = next((i for i, done in enumerate(done_flags) if not done),
                       None)
        for i, row in enumerate(self.checklist_rows):
            if done_flags[i]:
                row.set_state("done")
            elif i == current:
                row.set_state("current")
            else:
                row.set_state("upcoming")
        self.progress_label.setText(
            f"{sum(done_flags)} / {len(done_flags)} "
            + QCoreApplication.translate("Shell", "done").upper())

    def recent_paths(self):
        return [row.path for row in self._recent_rows]
