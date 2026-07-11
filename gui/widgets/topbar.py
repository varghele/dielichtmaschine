"""North Star shell chrome: the 48px topbar and the section subnav.

Anatomy (design_handoff_lichtmaschine_app/README.md, "App-Struktur"):
left the rotor glyph + DIE LICHTMASCHINE wordmark, then the section
tabs (SETUP · SHOW · LIVE), on the right 30x30 icon buttons, the
config filename in mono, and the output status chips. Below it a
subnav row lists the active section's screens (LIVE hosts the Live
busking surface and the Auto tab as sibling screens).

The shell drives the existing (tab-bar-hidden) QTabWidget by index and
syncs back on ``currentChanged``, so external navigation such as the
Ctrl+L jump to Auto keeps working. The section/screen model is data
(``SECTIONS``); adding LIVE later is one entry.

Strings go through ``QCoreApplication.translate("Shell", ...)`` (i18n
scaffolding); the caps rendering is done by the widgets, so
translations keep natural casing.
"""

from PyQt6.QtCore import QCoreApplication, Qt, pyqtSignal
from PyQt6.QtGui import QFont, QPixmap
from PyQt6.QtWidgets import (
    QHBoxLayout, QLabel, QPushButton, QSizePolicy, QToolButton, QWidget,
)

from gui.typography import MicroLabel, display_font
from utils.app_identity import APP_WORDMARK, app_icon_path


class Section:
    """One topbar section with its subnav screens."""

    def __init__(self, key, label, screens):
        self.key = key
        self.label = label
        # screens: list of (screen_key, screen_label, tab_index)
        self.screens = screens

    def tab_indices(self):
        return [index for _, _, index in self.screens]


def default_sections():
    """The current app mapped onto the North Star sections.

    Labels are translated lazily (call this after QApplication and any
    translators are installed). Tab indices match the QTabWidget pages
    built in Ui_MainWindow.setupUi. The translate() calls use string
    literals on purpose: pylupdate6 only extracts literals, a wrapper
    function would hide them from the catalog.
    """
    return [
        Section("setup", QCoreApplication.translate("Shell", "Setup"), [
            ("universes",
             QCoreApplication.translate("Shell", "Universes"), 0),
            ("fixtures",
             QCoreApplication.translate("Shell", "Fixtures"), 1),
            ("stage", QCoreApplication.translate("Shell", "Stage"), 2),
        ]),
        Section("show", QCoreApplication.translate("Shell", "Show"), [
            ("structure",
             QCoreApplication.translate("Shell", "Structure"), 3),
            ("timeline",
             QCoreApplication.translate("Shell", "Timeline"), 4),
        ]),
        # LIVE hosts the busking surface and the Auto pilot as sibling
        # screens (like SETUP/SHOW). Screen order is display order; the
        # tab indices need not be ascending.
        Section("live", QCoreApplication.translate("Shell", "Live"), [
            ("live", QCoreApplication.translate("Shell", "Live"), 6),
            ("auto", QCoreApplication.translate("Shell", "Auto"), 5),
        ]),
    ]


class NavButton(QPushButton):
    """Topbar section tab: condensed caps, accent underline when active
    (underline drawn by the QSS rule for QPushButton[role="nav"])."""

    def __init__(self, label: str, parent=None):
        super().__init__((label or "").upper(), parent)
        self.setProperty("role", "nav")
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFont(display_font(13, QFont.Weight.Bold, tracking_em=0.08))
        self.setFixedHeight(48)


class SubNavButton(QPushButton):
    """Subnav screen tab under the topbar."""

    def __init__(self, label: str, parent=None):
        super().__init__((label or "").upper(), parent)
        self.setProperty("role", "subnav")
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFont(display_font(11, QFont.Weight.DemiBold, tracking_em=0.08))
        self.setFixedHeight(30)


class TopBarIconButton(QToolButton):
    """30x30 bordered icon button on the topbar's right side."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setProperty("role", "topbar-icon")
        self.setFixedSize(30, 30)
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.setCursor(Qt.CursorShape.PointingHandCursor)


class StatusChip(QWidget):
    """Bordered chip hosting a status label pair + toggle dot button.

    The indicator/toggle widgets keep the dynamic ``status`` property
    protocol from the old menubar pills, so gui.py's
    ``_update_toolbar_status`` keeps styling them without changes.
    """

    def __init__(self, caption: str, indicator: QLabel,
                 toggle_btn: QPushButton, parent=None):
        super().__init__(parent)
        self.setProperty("role", "chip")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 0, 4, 0)
        layout.setSpacing(6)
        self.caption = MicroLabel(caption, point_size=8, tracking_em=0.15)
        layout.addWidget(self.caption)
        layout.addWidget(indicator)
        layout.addWidget(toggle_btn)
        self.setFixedHeight(26)


class _BrandBlock(QWidget):
    """Clickable glyph + wordmark; click returns to the Home screen."""

    clicked = pyqtSignal()

    def mousePressEvent(self, event):  # noqa: N802 (Qt API)
        self.clicked.emit()
        event.accept()


class TopBar(QWidget):
    """The 48px shell topbar. Emits ``section_selected(key)`` for nav
    clicks and ``home_selected`` when the brand block is clicked."""

    section_selected = pyqtSignal(str)
    home_selected = pyqtSignal()

    def __init__(self, sections, parent=None):
        super().__init__(parent)
        self.setObjectName("TopBar")
        self.setFixedHeight(48)
        self._sections = list(sections)
        self._buttons = {}

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 8, 0)
        layout.setSpacing(8)

        # Brand block: rotor glyph + wordmark, clickable -> Home
        brand = _BrandBlock()
        brand.setCursor(Qt.CursorShape.PointingHandCursor)
        brand.setToolTip(QCoreApplication.translate("Shell", "Home"))
        brand.clicked.connect(self.home_selected)
        brand_layout = QHBoxLayout(brand)
        brand_layout.setContentsMargins(0, 0, 0, 0)
        brand_layout.setSpacing(8)

        glyph = QLabel()
        glyph.setObjectName("TopBarGlyph")
        pixmap = QPixmap(app_icon_path())
        if not pixmap.isNull():
            glyph.setPixmap(pixmap.scaled(
                22, 22, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation))
        brand_layout.addWidget(glyph)

        wordmark = QLabel(APP_WORDMARK)
        wordmark.setObjectName("TopBarWordmark")
        wordmark.setFont(display_font(15, QFont.Weight.ExtraBold,
                                      tracking_em=0.08))
        brand_layout.addWidget(wordmark)
        layout.addWidget(brand)

        layout.addSpacing(16)

        for section in self._sections:
            button = NavButton(section.label)
            button.clicked.connect(
                lambda _=False, key=section.key: self._on_nav_clicked(key))
            layout.addWidget(button)
            self._buttons[section.key] = button

        layout.addStretch(1)

        # Right side: filled by install_shell (icon buttons, filename,
        # chips) - kept as a sub-layout so the order is stable.
        self.right_layout = QHBoxLayout()
        self.right_layout.setContentsMargins(0, 0, 0, 0)
        self.right_layout.setSpacing(6)
        layout.addLayout(self.right_layout)

        self.filename_label = MicroLabel("", point_size=8, tracking_em=0.1)
        self.filename_label.setObjectName("TopBarFilename")

    # ------------------------------------------------------------------
    def _on_nav_clicked(self, key: str) -> None:
        self.set_active_section(key)
        self.section_selected.emit(key)

    def set_active_section(self, key: str) -> None:
        for section_key, button in self._buttons.items():
            button.setChecked(section_key == key)

    def active_section(self):
        for key, button in self._buttons.items():
            if button.isChecked():
                return key
        return None

    def set_filename(self, text: str) -> None:
        self.filename_label.setText(text or "")


class SubNav(QWidget):
    """Screen tabs for the active section. Emits
    ``screen_selected(tab_index)``."""

    screen_selected = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SubNav")
        self.setFixedHeight(30)
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(12, 0, 12, 0)
        self._layout.setSpacing(2)
        self._layout.addStretch(1)
        self._buttons = {}  # tab_index -> SubNavButton

    def show_section(self, section: Section) -> None:
        """Rebuild the row for a section's screens."""
        for button in self._buttons.values():
            self._layout.removeWidget(button)
            # hide + unparent immediately: deleteLater() is deferred to
            # the event loop, and until it runs the stale buttons would
            # still paint on top of the new row.
            button.hide()
            button.setParent(None)
            button.deleteLater()
        self._buttons = {}
        insert_at = 0
        for _, label, tab_index in section.screens:
            button = SubNavButton(label)
            button.clicked.connect(
                lambda _=False, index=tab_index:
                self.screen_selected.emit(index))
            self._layout.insertWidget(insert_at, button)
            self._buttons[tab_index] = button
            insert_at += 1

    def set_active_tab(self, tab_index: int) -> None:
        for index, button in self._buttons.items():
            button.setChecked(index == tab_index)

    def tab_indices(self):
        return sorted(self._buttons)


class ShellNav:
    """Coordinates topbar, subnav, and the page-hosting QTabWidget.

    Remembers the last visited screen per section so switching back to
    a section restores where you were. Pure logic + signal wiring;
    fully testable offscreen.
    """

    def __init__(self, sections, topbar: TopBar, subnav: SubNav,
                 tab_widget) -> None:
        self.sections = {s.key: s for s in sections}
        self.topbar = topbar
        self.subnav = subnav
        self.tab_widget = tab_widget
        self._last_screen = {
            s.key: s.screens[0][2] for s in sections}
        self._index_to_section = {}
        for section in sections:
            for index in section.tab_indices():
                self._index_to_section[index] = section.key

        topbar.section_selected.connect(self._on_section_selected)
        subnav.screen_selected.connect(self._on_screen_selected)
        tab_widget.currentChanged.connect(self._on_tab_changed)

        self.sync_to_tab(tab_widget.currentIndex())

    # -- user actions ---------------------------------------------------
    def _on_section_selected(self, key: str) -> None:
        self.tab_widget.setCurrentIndex(self._last_screen[key])

    def _on_screen_selected(self, tab_index: int) -> None:
        self.tab_widget.setCurrentIndex(tab_index)

    def section_for_tab(self, index: int):
        """The section key ("setup"/"show"/"live") hosting a tab index,
        or None. The shell uses this to wire per-section behaviour
        (e.g. the output arbiter's idle-floor policy)."""
        return self._index_to_section.get(index)

    # -- keep chrome in sync with the tab widget (any source) -----------
    def _on_tab_changed(self, index: int) -> None:
        self.sync_to_tab(index)

    def sync_to_tab(self, index: int) -> None:
        key = self._index_to_section.get(index)
        if key is None:
            return
        self._last_screen[key] = index
        section = self.sections[key]
        self.topbar.set_active_section(key)
        # subnav.tab_indices() is sorted; the section's screens are in
        # display order (LIVE lists tab 6 before 5), so sort both sides
        # or the row would be torn down and rebuilt on every tab change.
        if self.subnav.tab_indices() != sorted(section.tab_indices()):
            self.subnav.show_section(section)
        self.subnav.set_active_tab(index)


def screen_hints():
    """Per-tab-index statusbar hints (mockup: contextual hint plus
    shortcut in the 26px mono strip). Only verified shortcuts are
    named. Literal translate() calls for pylupdate6 extraction."""
    return {
        0: QCoreApplication.translate(
            "Shell", "Add a universe and pick its output · Ctrl+S save · Ctrl+O open"),
        1: QCoreApplication.translate(
            "Shell", "Red cells mark DMX address conflicts · Ctrl+N new from template"),
        2: QCoreApplication.translate(
            "Shell", "L cycles the active layer · hold Space to pan"),
        3: QCoreApplication.translate(
            "Shell", "Define parts, BPM and bars per song"),
        4: QCoreApplication.translate(
            "Shell", "Drop riffs onto lanes · Ctrl+Z undo · Auto-Generate builds a song from audio"),
        5: QCoreApplication.translate(
            "Shell", "Pick an audio input and press Start · Ctrl+L jumps here"),
        6: QCoreApplication.translate(
            "Shell", "Select groups, then touch a palette to busk the rig live"),
    }


def register_menu_shortcuts(window, menu) -> int:
    """Re-register every shortcut-carrying action of a popup menu tree
    on the window, so shortcuts fire without a menubar. Returns how
    many actions were registered."""
    count = 0
    for action in menu.actions():
        submenu = action.menu()
        if submenu is not None:
            count += register_menu_shortcuts(window, submenu)
        elif not action.shortcut().isEmpty():
            window.addAction(action)
            count += 1
    return count
