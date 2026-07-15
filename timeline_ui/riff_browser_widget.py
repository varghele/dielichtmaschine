# timeline_ui/riff_browser_widget.py
"""RiffBrowserWidget - Dockable panel for browsing and selecting riffs.

Styled to the Die Lichtmaschine North Star (docs/timeline-styling-review.md
item 3): brand surfaces and the Glutorange accent replace the old
Windows-blue / Material-gray inline colors. Ordinary chrome (the panel
container, search field, tree selection, icon buttons) goes through theme
QSS roles so the widget inherits the app-wide look; the only widget-local
styles left are token-derived surfaces that no single role covers (the
raised riff-item card with its accent hover) and the QPainter drag
preview, which reads brand colors from the active theme tokens.
"""

import json
from PyQt6.QtWidgets import (
    QDockWidget, QWidget, QVBoxLayout, QHBoxLayout,
    QLineEdit, QTreeWidget, QTreeWidgetItem, QPushButton,
    QLabel, QFrame, QSizePolicy, QStackedWidget, QApplication
)
from PyQt6.QtCore import Qt, pyqtSignal, QMimeData
from PyQt6.QtGui import QDrag, QPixmap, QPainter, QColor, QFont

from config.models import Riff, FixtureGroup
from riffs.riff_library import RiffLibrary

# Mime type for scene drags out of the library rail. Distinct from the
# riff mime ("application/x-qlc-riff") on purpose: timelines only accept
# riff drops, so a scene drag is inert until the cross-lane drop handler
# lands with the capability-mapping pass (docs/timeline-v3-plan.md,
# "Deferred": scenes dropping across multiple lanes).
SCENE_MIME_TYPE = "application/x-lm-scene"

# Empty-library marker, same copy as the Live tab's scene rail.
SCENES_EMPTY_TEXT = "No scenes yet · predefined looks arrive later"


def _active_tokens() -> dict:
    """The token dict of the theme currently applied to the app.

    The applied stylesheet is the only reliable record of the active
    theme, so sniff it the same way ``gui/tabs/stage_tab.py::_active_tokens``
    does: the light theme's window color is unique to light. Falls back
    to dark (the default before a theme is applied).
    """
    from gui.theme_tokens import THEMES

    app = QApplication.instance()
    qss = app.styleSheet() if app is not None else ""
    light = THEMES.get("light")
    if light is not None and light["window"] in qss:
        return light
    return THEMES["dark"]


class RiffItemWidget(QFrame):
    """Widget representing a single riff in the browser."""

    def __init__(self, riff: Riff, parent=None):
        super().__init__(parent)
        self.riff = riff
        self._setup_ui()
        self.setAcceptDrops(False)

    def _setup_ui(self):
        # A raised card that stands against the panel-colored tree, with an
        # accent hover. No single theme role covers "raised surface + accent
        # hover", so this stays widget-local, but every color is a brand
        # token (radius 0 per the brand).
        t = _active_tokens()
        self.setStyleSheet(f"""
            RiffItemWidget {{
                background-color: {t['raised']};
                border: 1px solid {t['border']};
                padding: 4px;
            }}
            RiffItemWidget:hover {{
                background-color: {t['accent_tint']};
                border-color: {t['accent']};
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(2)

        # Riff name - brand text color comes from the app-wide QWidget rule;
        # bold is set on the font so no widget-local color is needed.
        name_label = QLabel(self.riff.name.replace('_', ' ').title())
        name_font = name_label.font()
        name_font.setBold(True)
        name_label.setFont(name_font)
        layout.addWidget(name_label)

        # Info line: beats | fixture type
        info_parts = []
        beats = int(self.riff.length_beats)
        bars = beats // 4
        if bars > 0:
            info_parts.append(f"{bars} bar{'s' if bars > 1 else ''}")
        else:
            info_parts.append(f"{beats} beat{'s' if beats > 1 else ''}")

        if self.riff.fixture_types:
            info_parts.append(" | ".join(self.riff.fixture_types))
        else:
            info_parts.append("Universal")

        info_label = QLabel(" | ".join(info_parts))
        info_label.setProperty("role", "micro")
        layout.addWidget(info_label)

        # Tags line ('#punchy #chorus'), only when the riff has any -
        # searchable via the rail search (a '#tag' query matches tags
        # only), editable via the tree's right-click Edit Tags.
        if self.riff.tags:
            tags_label = QLabel(" ".join(f"#{t}" for t in self.riff.tags))
            tags_label.setProperty("role", "micro")
            tags_label.setStyleSheet(
                f"color: {t['accent']};")
            layout.addWidget(tags_label)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start_pos = event.pos()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            return
        if not hasattr(self, '_drag_start_pos'):
            return

        # Check if we've moved enough to start a drag
        if (event.pos() - self._drag_start_pos).manhattanLength() < 10:
            return

        # Start drag
        drag = QDrag(self)
        mime_data = QMimeData()

        # Serialize riff reference
        riff_data = {
            "path": f"{self.riff.category}/{self.riff.name}",
            "name": self.riff.name,
            "length_beats": self.riff.length_beats
        }
        mime_data.setData("application/x-qlc-riff", json.dumps(riff_data).encode())

        drag.setMimeData(mime_data)

        # Create drag pixmap
        pixmap = self._create_drag_pixmap()
        drag.setPixmap(pixmap)
        drag.setHotSpot(pixmap.rect().center())

        drag.exec(Qt.DropAction.CopyAction)

    def _create_drag_pixmap(self) -> QPixmap:
        """Create a simple pixmap for drag preview."""
        width = 120
        height = 30
        # Brand-colored preview: raised surface + primary text, read from
        # the active theme tokens (a QPainter can't reach QSS roles).
        t = _active_tokens()
        fill = QColor(t['raised'])
        fill.setAlpha(220)
        pixmap = QPixmap(width, height)
        pixmap.fill(fill)

        painter = QPainter(pixmap)
        painter.setPen(QColor(t['accent']))
        painter.drawRect(0, 0, width - 1, height - 1)
        painter.setPen(QColor(t['text']))
        painter.setFont(QFont("Arial", 9))

        # Draw riff name
        text = self.riff.name.replace('_', ' ')
        if len(text) > 15:
            text = text[:12] + "..."
        painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, text)

        painter.end()
        return pixmap


class SceneItemWidget(QFrame):
    """A scene row in the library rail: name, an optional colour swatch
    (the scene's display colour, painted as real pixels) and a small
    mono "N GROUPS" tag.

    Drag SOURCE only: the row starts a drag carrying SCENE_MIME_TYPE,
    but no timeline accepts it yet - cross-lane scene drops are deferred
    to the capability-mapping pass (docs/timeline-v3-plan.md).
    """

    def __init__(self, scene, parent=None):
        super().__init__(parent)
        self.scene = scene
        self._setup_ui()
        self.setAcceptDrops(False)

    def _setup_ui(self):
        # Same raised-card treatment as RiffItemWidget so riffs and
        # scenes read as one library.
        t = _active_tokens()
        self.setStyleSheet(f"""
            SceneItemWidget {{
                background-color: {t['raised']};
                border: 1px solid {t['border']};
                padding: 4px;
            }}
            SceneItemWidget:hover {{
                background-color: {t['accent_tint']};
                border-color: {t['accent']};
            }}
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(6)

        self.chip_label = None
        color = QColor(self.scene.color) if self.scene.color else QColor()
        if color.isValid():
            self.chip_label = QLabel()
            pixmap = QPixmap(12, 12)
            pixmap.fill(color)
            self.chip_label.setPixmap(pixmap)
            self.chip_label.setFixedSize(12, 12)
            self.chip_label.setToolTip(color.name().upper())
            layout.addWidget(self.chip_label)

        name_label = QLabel(self.scene.name)
        name_font = name_label.font()
        name_font.setBold(True)
        name_label.setFont(name_font)
        layout.addWidget(name_label)

        layout.addStretch()

        group_count = len(self.scene.groups)
        tag = f"{group_count} GROUP{'S' if group_count != 1 else ''}"
        self.tag_label = QLabel(tag)
        self.tag_label.setProperty("role", "micro")
        layout.addWidget(self.tag_label)

    def _build_mime_data(self) -> QMimeData:
        """The drag payload: a scene reference under SCENE_MIME_TYPE."""
        mime_data = QMimeData()
        payload = {
            "key": f"{self.scene.category}/{self.scene.name}",
            "name": self.scene.name,
            "groups": list(self.scene.groups),
        }
        mime_data.setData(SCENE_MIME_TYPE, json.dumps(payload).encode())
        return mime_data

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start_pos = event.pos()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            return
        if not hasattr(self, '_drag_start_pos'):
            return
        if (event.pos() - self._drag_start_pos).manhattanLength() < 10:
            return

        drag = QDrag(self)
        drag.setMimeData(self._build_mime_data())
        pixmap = self._create_drag_pixmap()
        drag.setPixmap(pixmap)
        drag.setHotSpot(pixmap.rect().center())
        drag.exec(Qt.DropAction.CopyAction)

    def _create_drag_pixmap(self) -> QPixmap:
        """Simple brand-colored drag preview (mirrors the riff one)."""
        width = 120
        height = 30
        t = _active_tokens()
        fill = QColor(t['raised'])
        fill.setAlpha(220)
        pixmap = QPixmap(width, height)
        pixmap.fill(fill)

        painter = QPainter(pixmap)
        painter.setPen(QColor(t['accent']))
        painter.drawRect(0, 0, width - 1, height - 1)
        painter.setPen(QColor(t['text']))
        painter.setFont(QFont("Arial", 9))
        text = self.scene.name
        if len(text) > 15:
            text = text[:12] + "..."
        painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, text)
        painter.end()
        return pixmap


class CollapsedRiffBar(QWidget):
    """Thin vertical bar shown when riff browser is collapsed."""

    expand_clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        self.setFixedWidth(28)
        # Panel surface + border via the inspector role (the same library
        # panel chrome the rest of the app uses).
        self.setProperty("role", "inspector")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 4, 2, 4)
        layout.setSpacing(4)

        # Expand chevron - flat pane-icon treatment (accent-tint hover).
        self.expand_btn = QPushButton("◀")
        self.expand_btn.setFixedSize(24, 24)
        self.expand_btn.setToolTip("Expand Riff Library")
        self.expand_btn.setProperty("role", "pane-icon")
        self.expand_btn.clicked.connect(self.expand_clicked.emit)
        layout.addWidget(self.expand_btn)

        # Vertical label - secondary micro caption.
        self.label = QLabel("R\ni\nf\nf\ns")
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label.setProperty("role", "micro")
        layout.addWidget(self.label)

        layout.addStretch()


class RiffBrowserPanel(QWidget):
    """Reusable browser panel — search bar + category tree + status line.

    The QDockWidget version (`RiffBrowserWidget`) wraps an instance of
    this panel; embedded uses (e.g. inline under the Shows-tab visualizer)
    instantiate it directly. All the riff-browsing logic lives here so
    both call sites stay in sync without code duplication.
    """

    riff_drag_started = pyqtSignal(object)  # Riff object

    def __init__(
        self,
        riff_library: RiffLibrary = None,
        parent=None,
        *,
        show_collapse_button: bool = False,
        on_collapse_clicked=None,
        scene_library=None,
    ):
        """
        Args:
            riff_library: Shared :class:`RiffLibrary` instance. The panel
                does not own the library — pass the same instance when
                building multiple views.
            show_collapse_button: When True, prepend a ▶ button in the
                header that calls ``on_collapse_clicked``. Used by the
                dock wrapper; embedded panels leave it off.
            on_collapse_clicked: Callable invoked when the collapse
                button is clicked. Required iff ``show_collapse_button``.
            scene_library: Optional :class:`scenes.scene_library.SceneLibrary`
                override for the SCENES section. When omitted the panel
                resolves the main window's shared ``scene_library``
                (falling back to an empty library), the same way the
                riff library is shared from MainWindow.
        """
        super().__init__(parent)
        self.riff_library = riff_library or RiffLibrary()
        self._scene_library = scene_library
        self._fixture_filter: FixtureGroup = None
        self._category_items: dict = {}
        self._show_collapse_button = show_collapse_button
        self._on_collapse_clicked = on_collapse_clicked
        self._setup_ui()
        self._populate_tree()

    def _resolve_scene_library(self):
        """The SceneLibrary to render the SCENES section from.

        Injected instance first, then the main window's shared
        ``scene_library`` attribute (gui.py owns it, same pattern the
        Live tab uses), then a safe empty fallback - SceneLibrary
        tolerates a missing scenes directory. Window resolution is
        re-done per populate so a library attached after construction
        is picked up on the next refresh.
        """
        if self._scene_library is not None:
            return self._scene_library
        window = self.window()
        lib = getattr(window, "scene_library", None) if window is not None \
            else None
        if lib is None:
            from scenes.scene_library import SceneLibrary
            lib = SceneLibrary()
        return lib

    def _setup_ui(self):
        """Set up the panel UI."""
        # Library-panel chrome (panel surface + border) from the shared
        # inspector role.
        self.setProperty("role", "inspector")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # Header with collapse and refresh buttons
        header_layout = QHBoxLayout()
        header_layout.setSpacing(4)

        if self._show_collapse_button and self._on_collapse_clicked is not None:
            # Flat collapse chevron (pane-icon role).
            self._collapse_btn = QPushButton("▶")
            self._collapse_btn.setFixedSize(24, 24)
            self._collapse_btn.setToolTip("Collapse Riff Library")
            self._collapse_btn.setProperty("role", "pane-icon")
            self._collapse_btn.clicked.connect(self._on_collapse_clicked)
            header_layout.addWidget(self._collapse_btn)

        # Search bar - app-wide QLineEdit styling (raised surface, brand
        # border, accent focus + accent selection) covers this fully.
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search riffs...")
        self.search_input.textChanged.connect(self._on_search_changed)
        header_layout.addWidget(self.search_input, 1)

        # Refresh button - bordered icon action (output-select role).
        refresh_btn = QPushButton("↻")
        refresh_btn.setFixedSize(28, 28)
        refresh_btn.setToolTip("Refresh riff library")
        refresh_btn.setProperty("role", "output-select")
        refresh_btn.clicked.connect(self._on_refresh)
        header_layout.addWidget(refresh_btn)

        layout.addLayout(header_layout)

        # Category tree - app-wide QTreeView styling gives the panel
        # surface, brand border and the accent selection color. No
        # QTreeWidget::item rule here on purpose (docs/qt-gotchas.md #1);
        # the accent selection comes from selection-background-color on the
        # QTreeView rule, not an ::item override.
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(16)
        self.tree.setAnimated(True)
        self.tree.setExpandsOnDoubleClick(True)
        self.tree.setDragEnabled(False)  # We handle drag manually
        # Right-click a riff row for Edit Tags (tags feed the search;
        # a '#tag' query matches tags only).
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(
            self._show_tree_context_menu)
        layout.addWidget(self.tree, 1)

        # Status label - secondary micro caption.
        self.status_label = QLabel()
        self.status_label.setProperty("role", "micro")
        layout.addWidget(self.status_label)

        self._update_status()

    def _populate_tree(self):
        """Populate the tree with categories and riffs."""
        self.tree.clear()
        self._category_items.clear()

        # Category icons/prefixes
        category_icons = {
            "builds": "📈",
            "fills": "⚡",
            "loops": "🔄",
            "drops": "💥",
            "movement": "↔️",
            "custom": "⭐"
        }

        for category in self.riff_library.get_categories():
            riffs = self.riff_library.get_riffs_in_category(category)

            # Filter by fixture compatibility if set
            if self._fixture_filter:
                riffs = [r for r in riffs
                         if r.is_compatible_with(self._fixture_filter)[0]]

            # Skip empty categories
            if not riffs:
                continue

            # Create category item
            icon = category_icons.get(category, "📁")
            category_item = QTreeWidgetItem([f"{icon} {category.title()} ({len(riffs)})"])
            category_item.setData(0, Qt.ItemDataRole.UserRole, {"type": "category", "name": category})
            self._category_items[category] = category_item
            self.tree.addTopLevelItem(category_item)

            # Add riff items
            for riff in riffs:
                riff_item = QTreeWidgetItem()
                riff_item.setData(0, Qt.ItemDataRole.UserRole, {"type": "riff", "riff": riff})

                # Create custom widget for riff
                widget = RiffItemWidget(riff)
                riff_item.setSizeHint(0, widget.sizeHint())

                category_item.addChild(riff_item)
                self.tree.setItemWidget(riff_item, 0, widget)

        # SCENES section after the riff categories (timeline v3 stage
        # T5: the mock's SZENEN category in the library rail).
        self._append_scenes_section()

        # Expand all categories by default
        self.tree.expandAll()

    def _append_scenes_section(self):
        """Append the SCENES category rendered from the shared
        SceneLibrary. Display + drag source only: rows drag with
        SCENE_MIME_TYPE but no timeline accepts them yet (cross-lane
        scene drop is deferred, docs/timeline-v3-plan.md). An empty
        library shows the Live tab's marker copy instead of vanishing.
        """
        library = self._resolve_scene_library()
        scenes = library.get_all_scenes() if library is not None else []

        # No icon prefix: the riff-category emojis lean on the system
        # emoji font, and every scene-ish candidate (🎬, ◆) renders as
        # tofu in the brand fonts - the plain label is the marker.
        section = QTreeWidgetItem([f"Scenes ({len(scenes)})"])
        section.setData(0, Qt.ItemDataRole.UserRole,
                        {"type": "scene_category", "name": "scenes"})
        self._scenes_item = section
        self.tree.addTopLevelItem(section)

        if not scenes:
            from PyQt6.QtCore import QSize
            empty_item = QTreeWidgetItem()
            empty_item.setData(0, Qt.ItemDataRole.UserRole,
                               {"type": "scene_empty"})
            section.addChild(empty_item)
            marker = QLabel(SCENES_EMPTY_TEXT)
            marker.setProperty("role", "micro")
            marker.setContentsMargins(6, 2, 6, 2)
            # The copy is longer than a narrow rail: wrap instead of
            # clipping, and size the row for the wrapped height at a
            # conservative width (the label re-wraps to whatever width
            # the tree actually gives it).
            marker.setWordWrap(True)
            hint_width = 200
            empty_item.setSizeHint(0, QSize(
                hint_width, marker.heightForWidth(hint_width) + 6))
            self.tree.setItemWidget(empty_item, 0, marker)
            return

        for scene in scenes:
            scene_item = QTreeWidgetItem()
            scene_item.setData(0, Qt.ItemDataRole.UserRole,
                               {"type": "scene", "scene": scene})
            widget = SceneItemWidget(scene)
            scene_item.setSizeHint(0, widget.sizeHint())
            section.addChild(scene_item)
            self.tree.setItemWidget(scene_item, 0, widget)

    def _on_search_changed(self, text: str):
        """Filter riffs based on search text."""
        search_lower = text.lower().strip()

        if not search_lower:
            # Show all
            self._populate_tree()
            return

        # Search and repopulate
        self.tree.clear()
        self._category_items.clear()

        results = self.riff_library.search(search_lower, self._fixture_filter)

        if not results:
            self.status_label.setText("No riffs found")
            return

        # Group results by category
        by_category = {}
        for riff in results:
            if riff.category not in by_category:
                by_category[riff.category] = []
            by_category[riff.category].append(riff)

        # Create tree items
        category_icons = {
            "builds": "📈",
            "fills": "⚡",
            "loops": "🔄",
            "drops": "💥",
            "movement": "↔️",
            "custom": "⭐"
        }

        for category, riffs in sorted(by_category.items()):
            icon = category_icons.get(category, "📁")
            category_item = QTreeWidgetItem([f"{icon} {category.title()} ({len(riffs)})"])
            self._category_items[category] = category_item
            self.tree.addTopLevelItem(category_item)

            for riff in riffs:
                riff_item = QTreeWidgetItem()
                riff_item.setData(0, Qt.ItemDataRole.UserRole, {"type": "riff", "riff": riff})

                widget = RiffItemWidget(riff)
                riff_item.setSizeHint(0, widget.sizeHint())

                category_item.addChild(riff_item)
                self.tree.setItemWidget(riff_item, 0, widget)

        self.tree.expandAll()
        self._update_status(f"Found {len(results)} riff(s)")

    def _on_refresh(self):
        """Reload riffs from disk."""
        self.riff_library.refresh()
        self._populate_tree()
        self._update_status()

    def _show_tree_context_menu(self, pos):
        """Right-click menu on the library tree: Edit Tags on riff rows."""
        from PyQt6.QtWidgets import QMenu

        item = self.tree.itemAt(pos)
        data = (item.data(0, Qt.ItemDataRole.UserRole) or {}) if item \
            else {}
        if data.get("type") != "riff":
            return
        riff = data["riff"]
        menu = QMenu(self)
        menu.addAction("Edit Tags...", lambda: self._edit_riff_tags(riff))
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def _edit_riff_tags(self, riff):
        """Comma-separated tag editor. Tags render on the riff card and
        feed the search (a '#tag' query matches tags only); the riff is
        saved back to its library file."""
        from PyQt6.QtWidgets import QInputDialog

        text, ok = QInputDialog.getText(
            self, "Edit Tags",
            f"Tags for '{riff.name}' (comma-separated):",
            text=", ".join(riff.tags))
        if not ok:
            return
        from riffs.riff_library import parse_tags
        riff.tags = parse_tags(text)
        try:
            self.riff_library.save_riff(riff)
        except Exception as e:
            print(f"riff tags: save failed: {e}")
        # Rebuild so the card shows the new tags; keep an active search
        # consistent with them.
        query = self.search_input.text().strip()
        if query:
            self._on_search_changed(query)
        else:
            self._populate_tree()

    def _update_status(self, message: str = None):
        """Update status label."""
        if message:
            self.status_label.setText(message)
        else:
            count = len(self.riff_library)
            self.status_label.setText(f"{count} riff{'s' if count != 1 else ''} available")

    def set_fixture_filter(self, fixture_group: FixtureGroup):
        """Filter to show only compatible riffs.

        Args:
            fixture_group: Group to filter by, or None to show all
        """
        self._fixture_filter = fixture_group
        self._populate_tree()

        if fixture_group:
            self._update_status(f"Showing riffs for: {fixture_group.name}")
        else:
            self._update_status()

    def clear_fixture_filter(self):
        """Clear fixture filter and show all riffs."""
        self.set_fixture_filter(None)

    def get_riff_library(self) -> RiffLibrary:
        """Get the riff library instance."""
        return self.riff_library


class RiffBrowserWidget(QDockWidget):
    """Dockable wrapper around :class:`RiffBrowserPanel`.

    The dock supports a collapsed-to-thin-bar mode used to claw back
    horizontal space when the user wants the timeline full-width. The
    actual riff-browsing UI lives inside the panel so the Shows tab can
    embed the same panel inline (under the visualizer) without having to
    fight the dock plumbing.
    """

    riff_drag_started = pyqtSignal(object)

    def __init__(self, riff_library: RiffLibrary = None, parent=None):
        super().__init__("Riff Library", parent)
        self.riff_library = riff_library or RiffLibrary()
        self._is_collapsed = False

        self.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea |
            Qt.DockWidgetArea.RightDockWidgetArea
        )

        # Stacked widget toggles between full panel and a thin bar.
        self._stacked = QStackedWidget()
        self.setWidget(self._stacked)

        self._panel = RiffBrowserPanel(
            self.riff_library, self,
            show_collapse_button=True,
            on_collapse_clicked=self.collapse,
        )
        self._panel.riff_drag_started.connect(self.riff_drag_started.emit)
        self._stacked.addWidget(self._panel)

        self._collapsed_bar = CollapsedRiffBar()
        self._collapsed_bar.expand_clicked.connect(self.expand)
        self._stacked.addWidget(self._collapsed_bar)

        self._stacked.setCurrentIndex(0)
        self._update_size_for_state()

    # ── Collapse / expand (dock-only chrome) ──────────────────────────

    def _update_size_for_state(self):
        if self._is_collapsed:
            self.setMinimumWidth(28)
            self.setMaximumWidth(28)
        else:
            self.setMinimumWidth(200)
            self.setMaximumWidth(16777215)

    def collapse(self):
        if self._is_collapsed:
            return
        self._is_collapsed = True
        self._stacked.setCurrentIndex(1)
        self._update_size_for_state()
        self.setTitleBarWidget(QWidget())

    def expand(self):
        if not self._is_collapsed:
            return
        self._is_collapsed = False
        self._stacked.setCurrentIndex(0)
        self._update_size_for_state()
        self.setTitleBarWidget(None)

    def is_collapsed(self) -> bool:
        return self._is_collapsed

    def set_collapsed(self, collapsed: bool):
        if collapsed:
            self.collapse()
        else:
            self.expand()

    # ── Pass-through to the panel for back-compat ─────────────────────

    def set_fixture_filter(self, fixture_group: FixtureGroup):
        self._panel.set_fixture_filter(fixture_group)

    def clear_fixture_filter(self):
        self._panel.clear_fixture_filter()

    def get_riff_library(self) -> RiffLibrary:
        return self._panel.get_riff_library()
