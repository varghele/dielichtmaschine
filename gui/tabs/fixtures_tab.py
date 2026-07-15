# gui/tabs/fixtures_tab.py
"""Setup > Fixtures, rebuilt to the reference screen
docs/design/screens/02-setup-fixtures.html.

Anatomy (left to right, top to bottom):

- a slim 38px action strip: DMX-conflict warning chip left (hidden when
  clean), accent "+ ADD FIXTURE" CTA right. No tab title - the shell
  subnav already names the screen.
- a 280px GROUPS panel: one row per group with a 3px left border in the
  group color, caps group name, "N FIX" mono count, a secondary role
  line, plus a dashed hint box at the bottom. Clicking a row selects
  that group's fixtures in the table.
- the display-styled patch table: # / FIXTURE / TYPE / MODE / UNI /
  ADDRESS / GROUP. Plain read-only items, group-tinted rows (low-alpha
  background brushes - allowed because the theme has no
  QTableView::item rule, see docs/qt-gotchas.md #1), red UNI/ADDRESS
  cells on DMX conflicts. GROUP shows the fixture's FULL membership
  (" · "-joined, primary first, elided with the full list in the
  tooltip) in the PRIMARY group's color; single-group rows tint in the
  primary group's colour, multi-group rows get diagonal candy stripes
  cycling through every membership's tint (primary band first).
  Membership add/remove/make-primary happens in the table's
  right-click Assign menu.
- a 380px inspector: display-caps fixture name + mono provenance,
  CAPABILITIES chip row, CHANNEL MAP mono list (both derived from the
  fixture-definition cache), the editors (name / universe / address /
  mode / primary group / role), position readout, and a Duplicate /
  Remove footer.
- a mono status strip: "N FIXTURES · M GROUPS" and per-universe usage
  ("U1 92/512 · U2 58/512").

All editing happens in the inspector; the table is a pure display of
config.fixtures (row index == config index, no sorting). Inspector
editors write straight into the config, then refresh the affected table
row(s), the DMX lint, the groups panel and the status strip.
"""

import math

from PyQt6 import QtWidgets, QtCore, QtGui
from PyQt6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLineEdit,
)
from PyQt6.QtGui import QFont
from PyQt6.QtCore import Qt
from config.models import Configuration, Fixture, FixtureMode, FixtureGroup
from utils.fixture_utils import get_cached_fixture_definitions
from utils.dmx_conflicts import (
    AddressConflict,
    DMX_MAX_ADDRESS,
    fixture_channel_count,
    lint_dmx_addresses,
)
from .base_tab import BaseTab
from utils import user_warnings

# Table columns, reference order.
COL_NUM, COL_FIXTURE, COL_TYPE, COL_MODE, COL_UNI, COL_ADDRESS, COL_GROUP = \
    range(7)
TABLE_HEADERS = ("#", "FIXTURE", "TYPE", "MODE", "UNI", "ADDRESS", "GROUP")

# Row tint: the group color at the reference's rgba(...,0.17).
GROUP_TINT_ALPHA = 43

# Candy stripes for multi-group rows: the row background cycles through
# EVERY membership's tint colour (primary group first) as repeating
# diagonal bands - the same visual family as the Live tab's diagonal
# split swatches, here as an N-colour pattern. STRIPE_WIDTH is the
# horizontal run of one band; STRIPE_ANGLE_DEG the slant off VERTICAL
# (a little off, deliberately not 45). The tile height is derived so
# the skew across the tile is exactly one horizontal period, making the
# texture wrap seamlessly in both directions (the rounding nudges the
# true angle a fraction of a degree).
STRIPE_WIDTH = 11
STRIPE_ANGLE_DEG = 18.0

# Colour tuple -> QPixmap; one tile per membership colour combination.
_STRIPE_TILE_CACHE = {}

# Warning treatment for Universe / Address cells of conflicting fixtures.
# A fixed red (not theme-derived) so it reads as "error" on both themes
# and can't collide with the group tints.
CONFLICT_BG = "#d9534f"
CONFLICT_FG = "#ffffff"

# Readable words for the legacy fixture-type strings.
TYPE_LABELS = {
    "PAR": "PAR",
    "MH": "MOVING HEAD",
    "WASH": "WASH",
    "BAR": "LED BAR",
    "PIXELBAR": "PIXEL BAR",
    "SUNSTRIP": "SUNSTRIP",
}

# Group data colors, reference-flavoured (amber / cyan / magenta /
# green / blue / terracotta / violet / gray). Saturated mid-tones so
# they read as foreground text on the dark theme and as a tint at
# GROUP_TINT_ALPHA on both themes.
GROUP_PALETTE = (
    "#D9A441", "#4ECBD4", "#C95FD0", "#6F9E4C",
    "#5F86C9", "#C96A5F", "#9A7FD0", "#8D9299",
)

LIGHTING_ROLES = ("", "wash", "key", "texture", "accent")


# ---------------------------------------------------------------------------
# Pure helpers (unit-tested in tests/unit/test_fixture_capabilities_chips.py)
# ---------------------------------------------------------------------------

def type_label(raw_type: str) -> str:
    """A readable type word for a legacy fixture-type string."""
    token = (raw_type or "").strip().upper()
    if not token:
        return "PAR"
    return TYPE_LABELS.get(token, token)


def format_address_range(address: int, channels: int) -> str:
    """Zero-padded inclusive DMX range, e.g. (1, 8) -> '001-008'."""
    end = address + max(int(channels), 1) - 1
    return f"{address:03d}-{end:03d}"


def group_role_line(group) -> str:
    """The secondary line of a groups-panel row.

    "Role: accent · MH x2" - lighting role when set, then a summary of
    member types. Empty string when there is nothing to say.
    """
    parts = []
    role = (getattr(group, "lighting_role", "") or "").strip()
    if role:
        parts.append(f"Role: {role}")
    counts = {}
    for fixture in getattr(group, "fixtures", None) or []:
        token = (getattr(fixture, "type", "") or "PAR").strip().upper() or "PAR"
        counts[token] = counts.get(token, 0) + 1
    if counts:
        parts.append(" · ".join(f"{t} x{n}" for t, n in counts.items()))
    return " · ".join(parts)


def _channel_blob(channel: dict) -> str:
    """Lower-cased name+preset haystack for capability matching."""
    return f"{channel.get('name') or ''} {channel.get('preset') or ''}".lower()


def mode_channel_dicts(definition: dict, mode_name: str,
                       channel_count=None):
    """The ordered channel dicts of a mode from a legacy definition dict
    (the get_cached_fixture_definitions shape).

    Resolution: exact mode-name match, then a channel-count match (mode
    names drift between config and definition), else None. Channel refs
    that don't resolve to a global <Channel> keep their name with no
    preset/capabilities.
    """
    if not definition:
        return None
    modes = definition.get("modes") or []
    mode = next((m for m in modes if m.get("name") == mode_name), None)
    if mode is None and channel_count is not None:
        mode = next(
            (m for m in modes if len(m.get("channels") or []) == channel_count),
            None)
    if mode is None:
        return None
    by_name = {ch.get("name"): ch for ch in definition.get("channels") or []}
    out = []
    refs = sorted(mode.get("channels") or [],
                  key=lambda r: r.get("number", 0))
    for ref in refs:
        name = ref.get("name") or ""
        channel = by_name.get(name)
        if channel is None:
            channel = {"name": name, "preset": None, "capabilities": []}
        out.append(channel)
    return out


def derive_capability_chips(channels) -> list:
    """Capability chip texts for a mode's channel dicts.

    Rules (all case-insensitive over channel name + preset):
    - PAN/TILT when both a pan and a tilt channel exist
    - RGBW / RGB when red+green+blue (+white) components exist,
      else CMY when cyan+magenta+yellow exist
    - DIMMER on any 'dimmer' channel
    - GOBO on a gobo wheel channel (not a rotation channel); "xN" when
      N wheel capabilities carry 'gobo' in their name (slot count on
      the cheap)
    - PRISM / ZOOM / FOCUS on the matching term
    - STROBE on 'strobe' or 'shutter'
    """
    blobs = [(_channel_blob(ch), ch) for ch in channels or []]

    def present(term):
        return any(term in blob for blob, _ in blobs)

    chips = []
    if present("pan") and present("tilt"):
        chips.append("PAN/TILT")
    if present("red") and present("green") and present("blue"):
        chips.append("RGBW" if present("white") else "RGB")
    elif present("cyan") and present("magenta") and present("yellow"):
        chips.append("CMY")
    if present("dimmer"):
        chips.append("DIMMER")

    gobo_wheel = False
    slots = 0
    for blob, channel in blobs:
        if "gobo" in blob and "rot" not in blob:
            gobo_wheel = True
            for cap in channel.get("capabilities") or []:
                cap_name = (cap.get("name") or "").lower()
                if "gobo" in cap_name:
                    slots += 1
    if gobo_wheel:
        chips.append(f"GOBO x{slots}" if slots else "GOBO")

    if present("prism"):
        chips.append("PRISM")
    if present("strobe") or present("shutter"):
        chips.append("STROBE")
    if present("zoom"):
        chips.append("ZOOM")
    if present("focus"):
        chips.append("FOCUS")
    return chips


def channel_map_rows(channels) -> list:
    """(label, qualifier) rows for the CHANNEL MAP list.

    Label is 'NN CHANNELNAME'; qualifier is 'fine' when the channel
    name/preset says so, else empty.
    """
    rows = []
    for i, channel in enumerate(channels or [], start=1):
        name = (channel.get("name") or f"CH {i}").upper()
        qualifier = "fine" if "fine" in _channel_blob(channel) else ""
        rows.append((f"{i:02d} {name}", qualifier))
    return rows


def group_column_text(fixture) -> str:
    """The GROUP cell text: the fixture's FULL membership joined with
    " · " (same language as the timeline lane subtitle), primary group
    first (list order). The view elides it to the column width; the
    full list lives in the tooltip (group_column_tooltip)."""
    return " · ".join(g.upper() for g in fixture.groups if g)


def group_column_tooltip(fixture) -> str:
    """The un-elided membership list for the GROUP cell tooltip.

    Verbatim group names; the first is flagged as primary once the
    fixture is in more than one group."""
    names = [g for g in fixture.groups if g]
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    return " · ".join([f"{names[0]} (primary)"] + names[1:])


def group_tint_color(group_color: QtGui.QColor,
                     base_color: QtGui.QColor) -> QtGui.QColor:
    """The group color at GROUP_TINT_ALPHA pre-blended over the table
    base, as an OPAQUE color.

    Opaque on purpose: QTableView paints PE_PanelItemViewRow (the
    selection fill) *before* the item delegate runs, so a translucent
    item brush lets the accent selection color bleed through on
    selected rows even though GroupRowDelegate strips State_Selected.
    An opaque brush covers it, exactly like the pre-rebuild tints did.
    """
    alpha = GROUP_TINT_ALPHA / 255.0
    return QtGui.QColor(
        round(group_color.red() * alpha + base_color.red() * (1 - alpha)),
        round(group_color.green() * alpha + base_color.green() * (1 - alpha)),
        round(group_color.blue() * alpha + base_color.blue() * (1 - alpha)),
    )


def group_stripe_pixmap(color_names) -> QtGui.QPixmap:
    """A seamless candy-stripe texture tile for a multi-group row.

    ``color_names`` is an ordered iterable of OPAQUE '#rrggbb' strings,
    each a group colour already pre-blended over the table base via
    :func:`group_tint_color` (primary group first) - so every band has
    exactly the contrast the solid single-group tint has, and text
    stays as readable. Bands repeat left to right in membership order,
    STRIPE_WIDTH px wide, boundaries slanted STRIPE_ANGLE_DEG off
    vertical with a band's bottom edge to the RIGHT of its top edge.

    Pixels are computed per scanline (no antialiasing), so the tile is
    fully deterministic; the cache returns the SAME QPixmap object for
    the same colour tuple, keeping goldens stable and letting every row
    of a membership combination share one texture.
    """
    key = tuple(color_names)
    cached = _STRIPE_TILE_CACHE.get(key)
    if cached is not None:
        return cached
    colors = [QtGui.QColor(name).rgb() for name in key]
    period = STRIPE_WIDTH * len(colors)
    height = max(1, round(period / math.tan(math.radians(STRIPE_ANGLE_DEG))))
    image = QtGui.QImage(period, height, QtGui.QImage.Format.Format_RGB32)
    for y in range(height):
        # Bands shift right by exactly one period across the tile
        # height, so scanline ``height`` would equal scanline 0 and
        # vertical tiling is seamless.
        shift = (y * period) // height
        for x in range(period):
            image.setPixel(
                x, y, colors[((x - shift) % period) // STRIPE_WIDTH])
    pixmap = QtGui.QPixmap.fromImage(image)
    _STRIPE_TILE_CACHE[key] = pixmap
    return pixmap


def _active_tokens() -> dict:
    """The token dict of the theme currently applied to the app.

    The applied stylesheet is the only reliable record of the active
    theme (ThemeManager.apply deliberately doesn't persist), so sniff
    it: the light theme's window color is unique to light. Falls back
    to dark.
    """
    from PyQt6.QtWidgets import QApplication
    from gui.theme_tokens import THEMES

    app = QApplication.instance()
    qss = app.styleSheet() if app is not None else ""
    light = THEMES.get("light")
    if light is not None and light["window"] in qss:
        return light
    return THEMES["dark"]


class _FlowLayout(QtWidgets.QLayout):
    """Minimal left-to-right wrapping layout for the capability chips."""

    def __init__(self, parent=None, hspacing: int = 6, vspacing: int = 6):
        super().__init__(parent)
        self._items = []
        self._h = hspacing
        self._v = vspacing
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index):
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self):
        return QtCore.Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do_layout(QtCore.QRect(0, 0, width, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QtCore.QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        size += QtCore.QSize(margins.left() + margins.right(),
                             margins.top() + margins.bottom())
        return size

    def _do_layout(self, rect, test_only: bool) -> int:
        x, y, line_height = rect.x(), rect.y(), 0
        for item in self._items:
            hint = item.sizeHint()
            if x + hint.width() > rect.right() + 1 and line_height > 0:
                x = rect.x()
                y += line_height + self._v
                line_height = 0
            if not test_only:
                item.setGeometry(QtCore.QRect(QtCore.QPoint(x, y), hint))
            x += hint.width() + self._h
            line_height = max(line_height, hint.height())
        return y + line_height - rect.y()


class _GroupRow(QtWidgets.QWidget):
    """One clickable row of the GROUPS panel."""

    clicked = QtCore.pyqtSignal(str)
    context_requested = QtCore.pyqtSignal(str, QtCore.QPoint)

    def __init__(self, group_name: str, parent=None):
        super().__init__(parent)
        self._group_name = group_name
        self.setObjectName("GroupRow")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._group_name)
        super().mousePressEvent(event)

    def contextMenuEvent(self, event):
        # Handle (and accept) the right-click here so it does not also bubble
        # up to the groups panel's own "Add group" context menu.
        self.context_requested.emit(self._group_name, event.globalPos())
        event.accept()


class FixturesTab(BaseTab):
    """Fixture inventory and group management tab.

    Handles fixture CRUD, QLC+/GDTF fixture browsing, group management,
    and the group-tinted patch table. The table is read-only display;
    the inspector is the single write path into the config.
    """

    def __init__(self, config: Configuration, parent=None):
        # Color management state (before super().__init__ builds the UI).
        self.group_colors = {}
        self.color_index = 0
        self.predefined_colors = [QtGui.QColor(c) for c in GROUP_PALETTE]
        self.existing_groups = set()
        # Groups created via the panel's "+" that no fixture references
        # yet; _update_groups preserves them instead of dropping them.
        self._manual_groups = set()
        # Groups-panel selection (independent of the table selection).
        self._selected_group = None
        # (manufacturer, model) -> legacy definition dict or None.
        self._definition_memo = {}
        self._tokens = None

        # Track fixture state to avoid unnecessary rebuilds
        self._last_fixture_fingerprint = None
        # Lazy loading flag - update when tab becomes visible
        self._pending_update = False
        # Reentrancy and rebuild guards
        self._is_activating = False
        self._is_rebuilding = False

        super().__init__(config, parent)

    # ------------------------------------------------------------------
    # Tab lifecycle
    # ------------------------------------------------------------------
    def showEvent(self, event):
        """Handle tab becoming visible - trigger pending update if needed."""
        super().showEvent(event)
        if self._pending_update:
            self._pending_update = False
            # Use QTimer to defer update slightly, avoiding Qt stack issues
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(50, self._deferred_update)

    def _deferred_update(self):
        """Deferred update callback - only run if tab is still visible."""
        if self.isVisible() and not self._is_rebuilding:
            self.update_from_config(force=True)

    def schedule_update(self):
        """Schedule an update for when the tab becomes visible."""
        self._pending_update = True
        # If already visible, update now
        if self.isVisible():
            self._pending_update = False
            self.update_from_config(force=True)

    def on_tab_activated(self):
        """Called when tab becomes visible. Only reload if pending update."""
        if self._is_activating:
            return
        try:
            self._is_activating = True
            if self._pending_update:
                self._pending_update = False
                self.update_from_config(force=True)
            else:
                self.update_from_config()
        finally:
            self._is_activating = False

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def setup_ui(self):
        """Build the reference screen: action strip, groups panel,
        display table, inspector, status strip."""
        from gui.typography import MicroLabel, display_font
        from gui.widgets.chip import Chip

        self._tokens = _active_tokens()

        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # -- Action strip (38px): conflict chip left, accent CTA right --
        strip = QtWidgets.QWidget()
        strip.setFixedHeight(38)
        strip_row = QtWidgets.QHBoxLayout(strip)
        strip_row.setContentsMargins(16, 0, 16, 0)
        strip_row.setSpacing(12)

        self.conflict_label = Chip("", variant="warning")
        self.conflict_label.hide()
        strip_row.addWidget(self.conflict_label)
        strip_row.addStretch()

        # Accent primary CTA (reference: "+ IMPORT .QXF" in the subnav
        # row); opens the fixture browser dialog. The display family is
        # pinned by the theme's QPushButton[role="cta-accent"] rule.
        self.add_btn = QtWidgets.QPushButton("+ ADD FIXTURE")
        self.add_btn.setProperty("role", "cta-accent")
        self.add_btn.setFont(display_font(11, QFont.Weight.Bold,
                                          tracking_em=0.08))
        self.add_btn.setToolTip("Add Fixture")
        self.add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        # Pin the width from the button's own font metrics (plus the
        # theme's 28px padding + border and some slack) so the
        # glyph-clipping sweep can diff renders at stable geometry:
        # auto-width buttons re-layout when the harness blanks their
        # text, which breaks the with/without-text diff.
        metrics = QtGui.QFontMetrics(self.add_btn.font())
        self.add_btn.setFixedWidth(
            metrics.horizontalAdvance(self.add_btn.text()) + 44)
        strip_row.addWidget(self.add_btn)

        main_layout.addWidget(strip)

        # -- Body: groups panel | table column | inspector ---------------
        body = QtWidgets.QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        body.addWidget(self._build_groups_panel())
        body.addLayout(self._build_table_column(), 1)
        body.addWidget(self._build_inspector())
        main_layout.addLayout(body, 1)

        # -- Status strip: counts + per-universe usage --------------------
        status = QtWidgets.QWidget()
        status.setFixedHeight(26)
        status_row = QtWidgets.QHBoxLayout(status)
        status_row.setContentsMargins(16, 0, 16, 0)
        status_row.setSpacing(24)
        self.summary_label = MicroLabel("", point_size=8, tracking_em=0.1)
        status_row.addWidget(self.summary_label)
        self.universe_usage_label = MicroLabel("", point_size=8,
                                               tracking_em=0.1)
        status_row.addWidget(self.universe_usage_label)
        status_row.addStretch()
        main_layout.addWidget(status)

        # Load initial data
        self.update_from_config()

    def _build_groups_panel(self) -> QtWidgets.QWidget:
        """The 280px GROUPS panel (reference left column)."""
        from gui.typography import MicroLabel
        from gui.tabs.configuration_tab import TOOLBAR_BTN_WIDTH

        panel = QtWidgets.QWidget()
        panel.setObjectName("GroupsPanel")
        panel.setProperty("role", "inspector")
        panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        panel.setFixedWidth(280)
        # Right-click empty space in the panel to add a group.
        panel.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        panel.customContextMenuRequested.connect(
            lambda pos: self._show_groups_panel_menu(panel, pos))
        layout = QtWidgets.QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QtWidgets.QWidget()
        header_row = QtWidgets.QHBoxLayout(header)
        header_row.setContentsMargins(16, 8, 8, 8)
        header_row.setSpacing(8)
        header_row.addWidget(MicroLabel("Groups", point_size=8,
                                        tracking_em=0.12))
        header_row.addStretch()
        self.group_add_btn = QtWidgets.QPushButton("+")
        self.group_add_btn.setFixedWidth(TOOLBAR_BTN_WIDTH)
        self.group_add_btn.setToolTip("Add Group")
        header_row.addWidget(self.group_add_btn)
        layout.addWidget(header)

        self._groups_container = QtWidgets.QWidget()
        self._groups_layout = QtWidgets.QVBoxLayout(self._groups_container)
        self._groups_layout.setContentsMargins(0, 0, 0, 0)
        self._groups_layout.setSpacing(0)
        layout.addWidget(self._groups_container)
        layout.addStretch(1)

        # Dashed hint box (reference bottom of the groups column).
        # Widget-local styling: the dashed-border label has no theme
        # role yet (see NEEDED-QSS in the report); colors come from the
        # active theme's tokens.
        self.groups_hint = QtWidgets.QLabel(
            "Groups are the unit the timeline, Autogen and Live Controls "
            "address. Keep them role-based.")
        self.groups_hint.setObjectName("GroupsHint")
        self.groups_hint.setWordWrap(True)
        hint_font = self.groups_hint.font()
        hint_font.setPointSize(8)
        self.groups_hint.setFont(hint_font)
        self._style_groups_hint()
        hint_wrap = QtWidgets.QVBoxLayout()
        hint_wrap.setContentsMargins(16, 16, 16, 16)
        hint_wrap.addWidget(self.groups_hint)
        layout.addLayout(hint_wrap)
        return panel

    def _style_groups_hint(self):
        # Theme-owned: QLabel[role="hint-box"] in the QSS template.
        self.groups_hint.setProperty("role", "hint-box")

    def _build_table_column(self) -> QtWidgets.QVBoxLayout:
        """The group-tinted patch table."""
        from gui.widgets.row_outline_table import RowOutlineTableWidget

        column = QtWidgets.QVBoxLayout()
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)

        # RowOutlineTableWidget paints a continuous selection outline
        # around the row; GroupRowDelegate (below) strips the opaque
        # selection fill so the group tint stays visible.
        self.table = RowOutlineTableWidget()
        self._setup_table()
        column.addWidget(self.table, 1)
        return column

    def _setup_table(self):
        """Initialize table structure and properties."""
        from gui.typography import mono_font
        from gui.widgets.modern_table import apply_modern_table_style
        from gui.widgets.group_row_delegate import GroupRowDelegate

        self.table.setColumnCount(len(TABLE_HEADERS))
        self.table.setHorizontalHeaderLabels(list(TABLE_HEADERS))
        self.table.horizontalHeader().setFont(mono_font(8, tracking_em=0.1))
        self.table.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Expanding,
        )

        # Modern table behaviour (no grid, no vertical header, row
        # selection); then widen to multi-row selection so a groups-panel
        # click can select every fixture of the group.
        apply_modern_table_style(self.table)
        self.table.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection)
        # Uniform row background (reference look): every row carries an
        # explicit opaque background brush from _apply_row_visuals, so
        # alternating colors would never show anyway.
        self.table.setAlternatingRowColors(False)

        # Single-line cells: without this, a long GROUP membership list
        # word-wraps into the fixed row height instead of right-eliding
        # (QTableView wraps by default and only elides what still
        # overflows a line). Every column is single-line content, so
        # ElideRight + tooltip is the contract.
        self.table.setWordWrap(False)

        # Display-only: all editing happens in the inspector.
        self.table.setEditTriggers(
            QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)

        # Keep row index == config.fixtures index (patch-list order).
        self.table.setSortingEnabled(False)

        self._group_row_delegate = GroupRowDelegate(self.table)
        self.table.setItemDelegate(self._group_row_delegate)

        # Right-click a row for Duplicate / Remove (connected in
        # connect_signals). The row outline is the only selection chrome;
        # GroupRowDelegate strips the dotted focus rect.
        self.table.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu)

        header = self.table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(
            QtWidgets.QHeaderView.ResizeMode.Interactive)
        # Reference grid: 44px / 1.6fr / 1fr / 0.7fr / 0.6fr / 0.8fr / 1fr.
        self.table.setColumnWidth(COL_NUM, 44)
        self.table.setColumnWidth(COL_TYPE, 130)
        self.table.setColumnWidth(COL_MODE, 80)
        self.table.setColumnWidth(COL_UNI, 56)
        self.table.setColumnWidth(COL_ADDRESS, 100)
        self.table.setColumnWidth(COL_GROUP, 150)
        header.setSectionResizeMode(
            COL_FIXTURE, QtWidgets.QHeaderView.ResizeMode.Stretch)

    def _build_inspector(self) -> QtWidgets.QWidget:
        """The right-hand inspector (reference detail column).

        Sections in reference order: header (display-caps name + mono
        provenance), CAPABILITIES chips, CHANNEL MAP list, the editors,
        position readout, Duplicate / Remove footer. Editors write
        directly into the config.
        """
        from gui.typography import DisplayLabel, MicroLabel, mono_font

        panel = QtWidgets.QWidget()
        panel.setObjectName("FixtureInspector")
        panel.setProperty("role", "inspector")
        panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        panel.setFixedWidth(380)
        layout = QtWidgets.QVBoxLayout(panel)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)

        # Header: "MHX-50 MOVING HEAD · L" / "mhx-50.qxf · QLC+ LIBRARY".
        self.inspector_title = DisplayLabel("No fixture", point_size=13,
                                            weight=QFont.Weight.Bold)
        self.inspector_title.setWordWrap(True)
        layout.addWidget(self.inspector_title)

        self.inspector_source = MicroLabel("", point_size=8,
                                           tracking_em=0.1)
        self.inspector_source.setWordWrap(True)
        layout.addWidget(self.inspector_source)

        layout.addSpacing(6)

        # CAPABILITIES chip row (from the fixture definition cache).
        layout.addWidget(MicroLabel("Capabilities", point_size=8,
                                    tracking_em=0.12))
        self._caps_container = QtWidgets.QWidget()
        self._caps_flow = _FlowLayout(self._caps_container)
        layout.addWidget(self._caps_container)
        self.caps_placeholder = MicroLabel("No definition found",
                                           point_size=8, tracking_em=0.1)
        self.caps_placeholder.hide()
        layout.addWidget(self.caps_placeholder)

        layout.addSpacing(6)

        # CHANNEL MAP · MODE <N> CH (scrollable for big fixtures).
        self.channel_map_header = MicroLabel("Channel map", point_size=8,
                                             tracking_em=0.12)
        layout.addWidget(self.channel_map_header)
        self.channel_map_area = QtWidgets.QScrollArea()
        self.channel_map_area.setWidgetResizable(True)
        self.channel_map_area.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        map_inner = QtWidgets.QWidget()
        self._map_layout = QtWidgets.QVBoxLayout(map_inner)
        self._map_layout.setContentsMargins(0, 0, 0, 0)
        self._map_layout.setSpacing(2)
        self._map_layout.addStretch(1)
        self.channel_map_area.setWidget(map_inner)
        # The map area is the one vertically compressible section: it
        # absorbs shortfall (scrolls) so the editors below keep their
        # natural heights on short windows.
        self.channel_map_area.setMinimumHeight(48)
        layout.addWidget(self.channel_map_area, 1)

        layout.addSpacing(4)

        # Editors: the single write path into the config.
        layout.addWidget(MicroLabel("Name", point_size=8, tracking_em=0.1))
        self.insp_name = QtWidgets.QLineEdit()
        self.insp_name.textEdited.connect(self._on_inspector_name)
        layout.addWidget(self.insp_name)

        patch_row = QtWidgets.QHBoxLayout()
        patch_row.setSpacing(8)
        uni_col = QtWidgets.QVBoxLayout()
        uni_col.setSpacing(4)
        uni_col.addWidget(MicroLabel("Universe", point_size=8,
                                     tracking_em=0.1))
        self.insp_universe = QtWidgets.QSpinBox()
        self.insp_universe.setRange(0, 16)
        self.insp_universe.valueChanged.connect(self._on_inspector_universe)
        uni_col.addWidget(self.insp_universe)
        patch_row.addLayout(uni_col)
        addr_col = QtWidgets.QVBoxLayout()
        addr_col.setSpacing(4)
        addr_col.addWidget(MicroLabel("Address", point_size=8,
                                      tracking_em=0.1))
        self.insp_address = QtWidgets.QSpinBox()
        self.insp_address.setRange(1, 512)
        self.insp_address.valueChanged.connect(self._on_inspector_address)
        addr_col.addWidget(self.insp_address)
        patch_row.addLayout(addr_col)
        layout.addLayout(patch_row)

        layout.addWidget(MicroLabel("Mode", point_size=8, tracking_em=0.1))
        self.insp_mode = QtWidgets.QComboBox()
        self.insp_mode.currentIndexChanged.connect(self._on_inspector_mode)
        layout.addWidget(self.insp_mode)

        group_role_row = QtWidgets.QHBoxLayout()
        group_role_row.setSpacing(8)
        group_col = QtWidgets.QVBoxLayout()
        group_col.setSpacing(4)
        # Edits the PRIMARY group slot only (labelled so): secondary
        # memberships are untouched; membership add/remove lives in the
        # table's right-click menu.
        group_col.addWidget(MicroLabel("Primary group", point_size=8,
                                       tracking_em=0.1))
        self.insp_group = QtWidgets.QComboBox()
        self.insp_group.currentTextChanged.connect(self._on_inspector_group)
        group_col.addWidget(self.insp_group)
        group_role_row.addLayout(group_col, 1)
        role_col = QtWidgets.QVBoxLayout()
        role_col.setSpacing(4)
        role_col.addWidget(MicroLabel("Role", point_size=8,
                                      tracking_em=0.1))
        self.insp_role = QtWidgets.QComboBox()
        self.insp_role.addItems(list(LIGHTING_ROLES))
        self.insp_role.currentTextChanged.connect(self._on_inspector_role)
        role_col.addWidget(self.insp_role)
        group_role_row.addLayout(role_col, 1)
        layout.addLayout(group_role_row)

        layout.addSpacing(4)
        layout.addWidget(MicroLabel("Position", point_size=8,
                                    tracking_em=0.1))
        self.insp_position = QtWidgets.QLabel("")
        self.insp_position.setFont(mono_font(9))
        layout.addWidget(self.insp_position)

        # Footer action row: Duplicate / Remove (previously the title
        # row's icon buttons).
        footer = QtWidgets.QHBoxLayout()
        footer.setSpacing(8)
        self.duplicate_btn = QtWidgets.QPushButton("Duplicate")
        self.duplicate_btn.setToolTip("Duplicate Fixture")
        footer.addWidget(self.duplicate_btn, 1)
        self.remove_btn = QtWidgets.QPushButton("Remove")
        self.remove_btn.setProperty("role", "destructive")
        self.remove_btn.setToolTip("Remove Fixture")
        footer.addWidget(self.remove_btn, 1)
        layout.addLayout(footer)

        self._inspector_editors = (self.insp_name, self.insp_universe,
                                   self.insp_address, self.insp_mode,
                                   self.insp_group, self.insp_role)
        # Editors must not collapse when the panel runs out of height
        # (the channel-map scroll area is the compressible section).
        for editor in self._inspector_editors:
            editor.setMinimumHeight(26)
        return panel

    def connect_signals(self):
        """Connect widget signals to handlers."""
        self.add_btn.clicked.connect(self._add_fixture)
        self.remove_btn.clicked.connect(self._remove_fixture)
        self.duplicate_btn.clicked.connect(self._duplicate_fixture)
        self.group_add_btn.clicked.connect(self._add_group)
        self.table.itemSelectionChanged.connect(self._refresh_inspector)
        self.table.customContextMenuRequested.connect(
            self._show_table_context_menu)

    # ------------------------------------------------------------------
    # Config sync
    # ------------------------------------------------------------------
    def _get_fixture_fingerprint(self) -> str:
        """Fingerprint of fixtures and groups for change detection."""
        parts = []
        for f in self.config.fixtures:
            parts.append(f"{f.name}:{f.universe}:{f.address}:"
                         f"{f.manufacturer}:{f.model}:{f.current_mode}:"
                         f"{','.join(f.groups)}")
        parts.append("groups:" + ",".join(
            f"{name}:{group.color}:{group.lighting_role}"
            for name, group in sorted(self.config.groups.items())))
        return "|".join(parts)

    def _sync_fingerprint(self):
        self._last_fixture_fingerprint = self._get_fixture_fingerprint()

    def _notify_main_window(self):
        main_window = self.window()
        if main_window and hasattr(main_window, 'on_groups_changed'):
            main_window.on_groups_changed()

    def update_from_config(self, force: bool = False):
        """Refresh the tab from the configuration.

        Args:
            force: If True, rebuild even if no changes detected
        """
        if self._is_rebuilding:
            return
        current_fingerprint = self._get_fixture_fingerprint()
        if not force and current_fingerprint == self._last_fixture_fingerprint:
            return  # No changes, skip expensive rebuild
        self._is_rebuilding = True
        try:
            self._update_from_config_inner(current_fingerprint)
        finally:
            self._is_rebuilding = False

    def _update_from_config_inner(self, current_fingerprint):
        """Inner implementation of update_from_config."""
        self._last_fixture_fingerprint = current_fingerprint
        self._tokens = _active_tokens()
        self._style_groups_hint()
        self.existing_groups = set(self.config.groups.keys())

        self.table.blockSignals(True)
        self.table.setRowCount(0)
        self.table.setRowCount(len(self.config.fixtures))
        for row, fixture in enumerate(self.config.fixtures):
            self._populate_row(row, fixture)
        self.table.blockSignals(False)

        self._refresh_all_row_visuals()
        self._update_conflict_indicators()

        if self._selected_group not in self.config.groups:
            self._selected_group = None
        self._refresh_groups_panel()

        # Keep a row selected so the inspector always shows something.
        if self.table.rowCount() and not self.table.selectedItems():
            self.table.selectRow(0)
        self._refresh_inspector()
        self._update_status_strip()

    def save_to_config(self, item=None):
        """Sync derived config state (groups, universes).

        The inspector already wrote fixture fields directly; this keeps
        the group table and the auto-created universes in step and is
        what MainWindow calls before saving/exporting.
        """
        if self._is_rebuilding:
            return
        self._update_groups()
        self.config.ensure_universes_for_fixtures()
        self._sync_fingerprint()
        self._update_conflict_indicators()
        self._update_status_strip()

    # ------------------------------------------------------------------
    # Table population + visuals
    # ------------------------------------------------------------------
    def _populate_row(self, row: int, fixture: Fixture):
        """Create the 7 read-only display items of one table row."""
        from gui.typography import mono_font

        mono = mono_font(8)
        channels = fixture_channel_count(fixture)

        def make(col, text, font=None):
            item = QtWidgets.QTableWidgetItem(text)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            if font is not None:
                item.setFont(font)
            self.table.setItem(row, col, item)
            return item

        name_font = self.table.font()
        name_font.setWeight(QFont.Weight.Medium)
        group_font = self.table.font()
        group_font.setWeight(QFont.Weight.DemiBold)

        make(COL_NUM, f"{row + 1:02d}", mono)
        make(COL_FIXTURE, fixture.name, name_font)
        make(COL_TYPE, type_label(fixture.type))
        make(COL_MODE, f"{channels} CH", mono)
        make(COL_UNI, f"U{fixture.universe}", mono)
        make(COL_ADDRESS, format_address_range(fixture.address, channels),
             mono)
        # Full membership, primary first; the view elides to the column
        # width, the tooltip carries the whole list.
        group_item = make(COL_GROUP, group_column_text(fixture), group_font)
        group_item.setToolTip(group_column_tooltip(fixture))

    def _refresh_all_row_visuals(self):
        for row in range(min(self.table.rowCount(),
                             len(self.config.fixtures))):
            self._apply_row_visuals(row)

    def _apply_row_visuals(self, row: int):
        """Group tint + per-column foregrounds for one row (reference:
        rgba(group, 0.17) row background, dim mono #, bright fixture
        name, secondary data cells, group name in the group color).

        Single-group rows get the solid primary-group tint; multi-group
        rows get diagonal candy stripes cycling through EVERY
        membership's tint (primary band first, group_stripe_pixmap)."""
        if row >= len(self.config.fixtures):
            return
        fixture = self.config.fixtures[row]
        tokens = self._tokens or _active_tokens()

        base = QtGui.QColor(tokens["panel"])
        member_colors = [QtGui.QColor(self._ensure_group_color(name))
                         for name in fixture.groups if name]
        group_color = member_colors[0] if member_colors else None
        if len(member_colors) > 1:
            # Candy stripes: every band is one membership's colour
            # pre-blended exactly like the solid tint, so contrast (and
            # the opaque-covers-selection story) is unchanged.
            background = QtGui.QBrush(group_stripe_pixmap(
                tuple(group_tint_color(c, base).name()
                      for c in member_colors)))
        elif group_color is not None:
            background = QtGui.QBrush(group_tint_color(group_color, base))
        else:
            # Opaque panel color, not a default brush: see
            # group_tint_color for why translucency/no-brush lets the
            # selection fill bleed through.
            background = QtGui.QBrush(base)

        foreground_by_col = {
            COL_NUM: tokens["text_disabled"],
            COL_FIXTURE: tokens["text"],
            COL_TYPE: tokens["text_secondary"],
            COL_MODE: tokens["text_secondary"],
            COL_UNI: tokens["text_secondary"],
            COL_ADDRESS: tokens["text_secondary"],
            COL_GROUP: (group_color.name() if group_color is not None
                        else tokens["text_disabled"]),
        }
        for col in range(self.table.columnCount()):
            table_item = self.table.item(row, col)
            if table_item is None:
                continue
            table_item.setBackground(background)
            table_item.setForeground(
                QtGui.QBrush(QtGui.QColor(foreground_by_col[col])))
            if col in (COL_UNI, COL_ADDRESS):
                table_item.setToolTip("")

    def _ensure_group_color(self, group_name: str) -> str:
        """The group's data color as '#rrggbb', assigning one if new.

        Saved config colors win (unless the '#808080' default); new
        groups take the next unused palette color. The chosen color is
        written back to the config group so every tab agrees.
        """
        color = self.group_colors.get(group_name)
        if color is None:
            group = self.config.groups.get(group_name)
            saved = getattr(group, "color", None) if group else None
            if saved and saved != "#808080" and QtGui.QColor(saved).isValid():
                color = QtGui.QColor(saved)
            else:
                used = {c.name() for c in self.group_colors.values()}
                for _ in range(len(self.predefined_colors)):
                    candidate = self.predefined_colors[
                        self.color_index % len(self.predefined_colors)]
                    self.color_index += 1
                    if candidate.name() not in used:
                        color = candidate
                        break
                else:
                    color = self.predefined_colors[
                        self.color_index % len(self.predefined_colors)]
                    self.color_index += 1
            self.group_colors[group_name] = color
        group = self.config.groups.get(group_name)
        if group is not None:
            group.color = color.name()
        return color.name()

    # ------------------------------------------------------------------
    # DMX conflict indicators
    # ------------------------------------------------------------------
    def _describe_dmx_finding(self, row, finding, fixtures) -> str:
        if isinstance(finding, AddressConflict):
            other_idx = finding.index_b if finding.index_a == row else finding.index_a
            other = fixtures[other_idx]
            return (
                f"Overlaps '{other.name}' on universe {finding.universe}, "
                f"channels {finding.overlap_start}-{finding.overlap_end}"
            )
        return (
            f"Runs past the end of universe {finding.universe} "
            f"(ends at channel {finding.end_address}, max {DMX_MAX_ADDRESS})"
        )

    def _update_conflict_indicators(self):
        """Flag DMX overlaps/overflow on the UNI + ADDRESS cells.

        Conflicting cells get the fixed red background + white text and
        a tooltip naming the clash; clean rows get their group visuals
        restored. The warning chip in the action strip carries the
        issue count.
        """
        fixtures = self.config.fixtures
        lint = lint_dmx_addresses(fixtures)
        findings_by_fixture = lint.by_fixture()

        conflict_bg = QtGui.QBrush(QtGui.QColor(CONFLICT_BG))
        conflict_fg = QtGui.QBrush(QtGui.QColor(CONFLICT_FG))
        for row in range(min(self.table.rowCount(), len(fixtures))):
            findings = findings_by_fixture.get(row)
            if findings:
                tooltip = "\n".join(
                    self._describe_dmx_finding(row, f, fixtures)
                    for f in findings)
                for col in (COL_UNI, COL_ADDRESS):
                    table_item = self.table.item(row, col)
                    if table_item is not None:
                        table_item.setBackground(conflict_bg)
                        table_item.setForeground(conflict_fg)
                        table_item.setToolTip(tooltip)
            else:
                # Restores group tint/foregrounds and clears tooltips.
                self._apply_row_visuals(row)

        issue_count = len(lint.conflicts) + len(lint.overflows)
        if issue_count:
            noun = "issue" if issue_count == 1 else "issues"
            # No warning glyph: the chip's warning variant carries the
            # signal, and the character is missing from Barlow.
            self.conflict_label.setText(f"{issue_count} DMX addressing {noun}")
            self.conflict_label.show()
        else:
            self.conflict_label.hide()

    # ------------------------------------------------------------------
    # Groups panel
    # ------------------------------------------------------------------
    def _refresh_groups_panel(self):
        """Rebuild the group rows from config.groups."""
        while self._groups_layout.count():
            entry = self._groups_layout.takeAt(0)
            widget = entry.widget()
            if widget is not None:
                widget.deleteLater()
        for name, group in self.config.groups.items():
            self._groups_layout.addWidget(self._make_group_row(name, group))

    def _make_group_row(self, name: str, group: FixtureGroup) -> QtWidgets.QWidget:
        from gui.typography import MicroLabel
        from gui.fonts import FONT_UI

        tokens = self._tokens or _active_tokens()
        color = self._ensure_group_color(name)
        selected = (name == self._selected_group)

        row = _GroupRow(name)
        # Only the DATA color is widget-local; hairline + selected
        # background come from the theme's #GroupRow rules.
        row.setStyleSheet(
            f"#GroupRow {{ border-left: 3px solid {color}; }}")
        row.setProperty("selected", "true" if selected else "false")

        layout = QtWidgets.QVBoxLayout(row)
        layout.setContentsMargins(13, 10, 16, 10)
        layout.setSpacing(3)

        top = QtWidgets.QHBoxLayout()
        top.setSpacing(8)
        name_label = QtWidgets.QLabel(name.upper())
        name_font = QFont(FONT_UI, 10)
        name_font.setWeight(QFont.Weight.DemiBold)
        name_label.setFont(name_font)
        top.addWidget(name_label)
        top.addStretch()
        count = len(getattr(group, "fixtures", None) or [])
        top.addWidget(MicroLabel(f"{count} FIX", point_size=8,
                                 tracking_em=0.08))
        layout.addLayout(top)

        role_text = group_role_line(group)
        if role_text:
            role_label = QtWidgets.QLabel(role_text)
            role_label.setProperty("role", "card-readout")
            role_font = QFont(FONT_UI, 8)
            role_label.setFont(role_font)
            layout.addWidget(role_label)

        row.clicked.connect(self._on_group_row_clicked)
        row.context_requested.connect(self._show_group_context_menu)
        return row

    def _on_group_row_clicked(self, name: str):
        """Highlight the group row and select its fixtures in the table."""
        self._selected_group = name
        self._refresh_groups_panel()

        model = self.table.model()
        selection_model = self.table.selectionModel()
        if model is None or selection_model is None:
            return
        selection = QtCore.QItemSelection()
        last_col = self.table.columnCount() - 1
        for row, fixture in enumerate(self.config.fixtures):
            # Membership check spans the whole groups list, so clicking a
            # group row selects secondary members too.
            if name in fixture.groups and row < self.table.rowCount():
                selection.select(model.index(row, 0),
                                 model.index(row, last_col))
        selection_model.select(
            selection,
            QtCore.QItemSelectionModel.SelectionFlag.ClearAndSelect)

    def _add_group(self):
        """The groups panel '+' flow: name + lighting role dialog."""
        dialog = QDialog(self)
        dialog.setWindowTitle("Add New Group")
        layout = QFormLayout()
        new_group_input = QLineEdit()
        layout.addRow("Group Name:", new_group_input)

        role_combo = QComboBox()
        role_combo.addItems(list(LIGHTING_ROLES))
        layout.addRow("Lighting Role:", role_combo)

        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel
        )
        button_box.accepted.connect(dialog.accept)
        button_box.rejected.connect(dialog.reject)
        layout.addWidget(button_box)
        dialog.setLayout(layout)

        if dialog.exec() == QDialog.DialogCode.Accepted:
            name = new_group_input.text().strip()
            if name:
                self._create_group(name, role_combo.currentText())

    def _create_group(self, name: str, role: str = ""):
        """Create (or re-role) a group; empty groups persist until used."""
        if name not in self.config.groups:
            self.config.groups[name] = FixtureGroup(
                name, [], lighting_role=role)
            self._manual_groups.add(name)
            self._ensure_group_color(name)
        elif role:
            self.config.groups[name].lighting_role = role
        self._selected_group = name
        self._refresh_groups_panel()
        self._refresh_inspector()
        self._update_status_strip()
        self._sync_fingerprint()
        self._notify_main_window()

    def _update_groups(self):
        """Rebuild groups from fixtures, preserving colors, orientation
        defaults and lighting roles. Panel-created empty groups survive
        until a fixture joins them."""
        existing_props = {
            name: {
                'color': getattr(group, 'color', '#808080'),
                'default_mounting': getattr(group, 'default_mounting', 'hanging'),
                'default_yaw': getattr(group, 'default_yaw', 0.0),
                'default_pitch': getattr(group, 'default_pitch', 0.0),
                'default_roll': getattr(group, 'default_roll', 0.0),
                'default_z_height': getattr(group, 'default_z_height', 3.0),
                'lighting_role': getattr(group, 'lighting_role', ''),
            }
            for name, group in self.config.groups.items()
        }

        def build_group(name):
            props = existing_props.get(name, {})
            return FixtureGroup(
                name,
                [],
                color=props.get('color', '#808080'),
                default_mounting=props.get('default_mounting', 'hanging'),
                default_yaw=props.get('default_yaw', 0.0),
                default_pitch=props.get('default_pitch', 0.0),
                default_roll=props.get('default_roll', 0.0),
                default_z_height=props.get('default_z_height', 3.0),
                lighting_role=props.get('lighting_role', ''),
            )

        self.config.groups = {}
        for fixture in self.config.fixtures:
            # Full membership: a fixture appears in EVERY group it lists
            # (multi-group plan stage 1), not just its primary one.
            for group_name in fixture.groups:
                if group_name not in self.config.groups:
                    self.config.groups[group_name] = build_group(group_name)
                self.config.groups[group_name].fixtures.append(fixture)

        for name in list(self._manual_groups):
            if name in self.config.groups:
                if self.config.groups[name].fixtures:
                    self._manual_groups.discard(name)
            else:
                self.config.groups[name] = build_group(name)

        self.existing_groups = set(self.config.groups.keys())

    # ------------------------------------------------------------------
    # Inspector
    # ------------------------------------------------------------------
    def _selected_fixture_row(self) -> int:
        """The config.fixtures index of the first selected row, or -1."""
        model = self.table.selectionModel()
        rows = model.selectedRows() if model else []
        if rows:
            row = min(index.row() for index in rows)
        else:
            items = self.table.selectedItems()
            if not items:
                return -1
            row = min(item.row() for item in items)
        if 0 <= row < len(self.config.fixtures):
            return row
        return -1

    def _selected_fixture_rows(self) -> list:
        """Every selected row's config.fixtures index, ascending."""
        model = self.table.selectionModel()
        rows = ({index.row() for index in model.selectedRows()}
                if model else {item.row() for item in self.table.selectedItems()})
        return sorted(r for r in rows if 0 <= r < len(self.config.fixtures))

    def _refresh_inspector(self):
        """Load the selected fixture into the inspector.

        Signals stay blocked during population; widgets the user is
        typing into (focus) are skipped so a refresh never fights the
        caret or a half-typed value.
        """
        row = self._selected_fixture_row()
        fixture = self.config.fixtures[row] if row >= 0 else None

        enabled = fixture is not None
        for editor in self._inspector_editors:
            editor.setEnabled(enabled)
        self.duplicate_btn.setEnabled(enabled)
        self.remove_btn.setEnabled(enabled)

        if fixture is None:
            self.inspector_title.setText("No fixture")
            self.inspector_source.setText("")
            self.insp_position.setText("")
            for editor in self._inspector_editors:
                editor.blockSignals(True)
            self.insp_name.setText("")
            self.insp_mode.clear()
            self.insp_group.clear()
            self.insp_role.setCurrentIndex(0)
            for editor in self._inspector_editors:
                editor.blockSignals(False)
            self._refresh_capabilities_and_map(None)
            return

        self.inspector_title.setText(fixture.name or fixture.model)
        source = "GDTF" if fixture.definition_source == "gdtf" else "QXF"
        self.inspector_source.setText(
            f"{fixture.manufacturer} · {fixture.model} · {source}")

        if not self.insp_name.hasFocus():
            self.insp_name.blockSignals(True)
            self.insp_name.setText(fixture.name)
            self.insp_name.blockSignals(False)

        for spin, value in ((self.insp_universe, fixture.universe),
                            (self.insp_address, fixture.address)):
            if not spin.hasFocus():
                spin.blockSignals(True)
                spin.setValue(value)
                spin.blockSignals(False)

        if not self.insp_mode.hasFocus():
            self.insp_mode.blockSignals(True)
            self.insp_mode.clear()
            if fixture.available_modes:
                for mode in fixture.available_modes:
                    self.insp_mode.addItem(f"{mode.name} ({mode.channels}ch)")
                index = next(
                    (i for i, mode in enumerate(fixture.available_modes)
                     if mode.name == fixture.current_mode), 0)
                self.insp_mode.setCurrentIndex(index)
            else:
                self.insp_mode.addItem(fixture.current_mode)
            self.insp_mode.blockSignals(False)

        if not self.insp_group.hasFocus():
            self.insp_group.blockSignals(True)
            self.insp_group.clear()
            self.insp_group.addItem("")
            for group in sorted(self.config.groups.keys()):
                self.insp_group.addItem(group)
            self.insp_group.setCurrentText(fixture.group)
            self.insp_group.blockSignals(False)

        if not self.insp_role.hasFocus():
            group = self.config.groups.get(fixture.group)
            role = getattr(group, "lighting_role", "") if group else ""
            self.insp_role.blockSignals(True)
            index = self.insp_role.findText(role or "")
            self.insp_role.setCurrentIndex(index if index >= 0 else 0)
            self.insp_role.blockSignals(False)
            self.insp_role.setEnabled(bool(fixture.group))

        group = self.config.groups.get(fixture.group)
        z = fixture.get_effective_z(group)
        self.insp_position.setText(
            f"X {fixture.x:.2f}   Y {fixture.y:.2f}   Z {z:.2f} m")

        self._refresh_capabilities_and_map(fixture)

    # -- capabilities + channel map ------------------------------------
    def _resolve_definition(self, fixture):
        """The legacy definition dict for (manufacturer, model), or None
        (synthetic test fixtures, unknown models). Memoised per tab."""
        key = (fixture.manufacturer, fixture.model)
        if key in self._definition_memo:
            return self._definition_memo[key]
        definitions = get_cached_fixture_definitions({key})
        result = None
        for cache_key in (f"{key[0]}_{key[1]}",
                          f"{key[0]}_{key[1].replace(' ', '_')}"):
            if definitions.get(cache_key):
                result = definitions[cache_key]
                break
        self._definition_memo[key] = result
        return result

    def _clear_layout_widgets(self, layout, keep_stretch: bool = False):
        index = layout.count() - 1
        while index >= 0:
            entry = layout.itemAt(index)
            if keep_stretch and entry.widget() is None:
                index -= 1
                continue
            entry = layout.takeAt(index)
            widget = entry.widget()
            if widget is not None:
                widget.deleteLater()
            index -= 1

    def _refresh_capabilities_and_map(self, fixture):
        """Rebuild the CAPABILITIES chips + CHANNEL MAP list from the
        fixture definition cache for the fixture's current mode."""
        from gui.typography import MicroLabel
        from gui.widgets.chip import Chip

        self._clear_layout_widgets(self._caps_flow)
        self._clear_layout_widgets(self._map_layout, keep_stretch=True)

        if fixture is None:
            self.channel_map_header.setText("Channel map")
            self.caps_placeholder.hide()
            return

        channels_count = fixture_channel_count(fixture)
        self.channel_map_header.setText(
            f"Channel map · mode {channels_count} CH")

        definition = self._resolve_definition(fixture)
        mode_channels = mode_channel_dicts(definition, fixture.current_mode,
                                           channels_count)
        if not mode_channels:
            self.caps_placeholder.show()
            return
        self.caps_placeholder.hide()

        for chip_text in derive_capability_chips(mode_channels):
            self._caps_flow.addWidget(Chip(chip_text, variant="neutral"))

        insert_at = self._map_layout.count() - 1  # before the stretch
        for label_text, qualifier in channel_map_rows(mode_channels):
            row_widget = QtWidgets.QWidget()
            row_layout = QtWidgets.QHBoxLayout(row_widget)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(8)
            row_layout.addWidget(MicroLabel(label_text, point_size=8,
                                            tracking_em=0.0))
            row_layout.addStretch()
            if qualifier:
                row_layout.addWidget(MicroLabel(qualifier, point_size=8,
                                                tracking_em=0.0))
            self._map_layout.insertWidget(insert_at, row_widget)
            insert_at += 1

    # -- inspector edit handlers (direct config writes) ------------------
    def _on_inspector_name(self, text: str):
        row = self._selected_fixture_row()
        if row < 0 or self._is_rebuilding:
            return
        fixture = self.config.fixtures[row]
        fixture.name = text
        item = self.table.item(row, COL_FIXTURE)
        if item is not None:
            item.setText(text)
        self.inspector_title.setText(text or fixture.model)
        self._sync_fingerprint()

    def _on_inspector_universe(self, value: int):
        row = self._selected_fixture_row()
        if row < 0 or self._is_rebuilding:
            return
        fixture = self.config.fixtures[row]
        if fixture.universe == value:
            return
        fixture.universe = value
        self.config.ensure_universes_for_fixtures()
        item = self.table.item(row, COL_UNI)
        if item is not None:
            item.setText(f"U{value}")
        self._update_conflict_indicators()
        self._update_status_strip()
        self._sync_fingerprint()
        self._notify_main_window()

    def _on_inspector_address(self, value: int):
        row = self._selected_fixture_row()
        if row < 0 or self._is_rebuilding:
            return
        fixture = self.config.fixtures[row]
        if fixture.address == value:
            return
        fixture.address = value
        item = self.table.item(row, COL_ADDRESS)
        if item is not None:
            item.setText(format_address_range(
                value, fixture_channel_count(fixture)))
        self._update_conflict_indicators()
        self._sync_fingerprint()

    def _on_inspector_mode(self, index: int):
        row = self._selected_fixture_row()
        if row < 0 or self._is_rebuilding or index < 0:
            return
        fixture = self.config.fixtures[row]
        if not (0 <= index < len(fixture.available_modes)):
            return
        mode = fixture.available_modes[index]
        if fixture.current_mode == mode.name:
            return
        fixture.current_mode = mode.name
        mode_item = self.table.item(row, COL_MODE)
        if mode_item is not None:
            mode_item.setText(f"{mode.channels} CH")
        address_item = self.table.item(row, COL_ADDRESS)
        if address_item is not None:
            address_item.setText(
                format_address_range(fixture.address, mode.channels))
        self._update_conflict_indicators()
        self._refresh_capabilities_and_map(fixture)
        self._update_status_strip()
        self._sync_fingerprint()
        self._notify_main_window()

    def _on_inspector_group(self, text: str):
        """The inspector's "Primary group" combo: edits groups[0] ONLY.

        Secondary memberships survive (never `fixture.group = text` -
        the compat setter would REPLACE the whole list). Picking a group
        the fixture is already a secondary member of promotes it to
        primary (the old primary membership is what the edit replaces);
        picking "" drops the primary membership and promotes the next
        group, matching the old clear behavior for single-group
        fixtures. Membership add/remove lives in the table context menu.
        """
        row = self._selected_fixture_row()
        if row < 0 or self._is_rebuilding:
            return
        fixture = self.config.fixtures[row]
        if fixture.group == text:
            return
        rest = [g for g in fixture.groups[1:] if g != text]
        fixture.groups = ([text] + rest) if text else rest
        self._update_groups()
        item = self.table.item(row, COL_GROUP)
        if item is not None:
            item.setText(group_column_text(fixture))
            item.setToolTip(group_column_tooltip(fixture))
        self._refresh_all_row_visuals()
        self._update_conflict_indicators()
        if self._selected_group not in self.config.groups:
            self._selected_group = None
        self._refresh_groups_panel()
        self._update_status_strip()
        # Role editor follows the (possibly new) group.
        group = self.config.groups.get(fixture.group)
        role = getattr(group, "lighting_role", "") if group else ""
        self.insp_role.blockSignals(True)
        index = self.insp_role.findText(role or "")
        self.insp_role.setCurrentIndex(index if index >= 0 else 0)
        self.insp_role.blockSignals(False)
        self.insp_role.setEnabled(bool(fixture.group))
        self._sync_fingerprint()
        self._notify_main_window()

    def _on_inspector_role(self, text: str):
        row = self._selected_fixture_row()
        if row < 0 or self._is_rebuilding:
            return
        fixture = self.config.fixtures[row]
        group = self.config.groups.get(fixture.group)
        if group is None or group.lighting_role == text:
            return
        group.lighting_role = text
        self._refresh_groups_panel()
        self._sync_fingerprint()

    # ------------------------------------------------------------------
    # Status strip
    # ------------------------------------------------------------------
    def _update_status_strip(self):
        """Counts + per-universe usage (reference bottom strip)."""
        from gui.tabs.configuration_tab import channels_used

        n_fixtures = len(self.config.fixtures)
        n_groups = len(self.config.groups)
        fixture_noun = "fixture" if n_fixtures == 1 else "fixtures"
        group_noun = "group" if n_groups == 1 else "groups"
        self.summary_label.setText(
            f"{n_fixtures} {fixture_noun} · {n_groups} {group_noun}")

        universe_ids = sorted(
            {f.universe for f in self.config.fixtures}
            | set((self.config.universes or {}).keys()))
        self.universe_usage_label.setText(" · ".join(
            f"U{uid} {channels_used(self.config, uid)}/512"
            for uid in universe_ids))

    # ------------------------------------------------------------------
    # Fixture CRUD
    # ------------------------------------------------------------------
    def _scan_fixture_files(self) -> list:
        """Every .qxf reachable in the bundled + platform QLC+ fixture
        directories, as dicts the browser dialog consumes. The bundled
        custom_fixtures/ come first and are tagged 'bundled'."""
        from utils.fixture_library import all_fixture_files
        return all_fixture_files()

    # ------------------------------------------------------------------
    # Table context menu (Duplicate / Remove)
    # ------------------------------------------------------------------
    def _build_table_context_menu(self, has_row: bool = True) -> QtWidgets.QMenu:
        """The patch-table right-click menu.

        "Add fixture..." is always offered (so a right-click on empty space
        adds one); Duplicate / Remove / Assign to group are added when a row
        is under the cursor. Split out from :meth:`_show_table_context_menu`
        so the wiring is testable without popping the (blocking) menu.
        """
        menu = QtWidgets.QMenu(self.table)
        add_action = menu.addAction("Add fixture...")
        add_action.triggered.connect(self._add_fixture)

        # Addressing actions are table-wide, so they ride along whether
        # or not a row is under the cursor. Untangle only lights up
        # when the lint actually flags something.
        menu.addSeparator()
        untangle_action = menu.addAction("Untangle addresses")
        untangle_action.setToolTip(
            "Move only the conflicting fixtures to the nearest free "
            "addresses; everything else stays put.")
        untangle_action.setEnabled(
            not lint_dmx_addresses(self.config.fixtures).is_clean)
        untangle_action.triggered.connect(self._untangle_addresses)
        compact_action = menu.addAction("Compact addresses")
        compact_action.setToolTip(
            "Repack each universe to consecutive addresses with no "
            "gaps, keeping the current order.")
        compact_action.setEnabled(bool(self.config.fixtures))
        compact_action.triggered.connect(self._compact_addresses)

        if not has_row:
            return menu
        menu.addSeparator()

        duplicate_action = menu.addAction("Duplicate")
        duplicate_action.triggered.connect(self._duplicate_fixture)
        remove_action = menu.addAction("Remove")
        remove_action.triggered.connect(self._remove_fixture)

        # Assign to group: MEMBERSHIP editing over every selected row.
        # Entries are checkable and reflect the selection's membership
        # (checked = every selected fixture has the group). Clicking an
        # unchecked group ADDS the membership to the fixtures missing it
        # (append - existing memberships are never touched); clicking a
        # checked one REMOVES that membership from the whole selection.
        rows = self._selected_fixture_rows()
        selected = [self.config.fixtures[r] for r in rows]
        assign_menu = menu.addMenu("Assign to group")
        if len(rows) > 1:
            assign_menu.setTitle(f"Assign {len(rows)} to group")
        for name in self.config.groups:
            act = assign_menu.addAction(name)
            act.setCheckable(True)
            act.setChecked(bool(selected)
                           and all(name in f.groups for f in selected))
            act.triggered.connect(
                lambda _checked, g=name: self._assign_selected_to_group(g))
        if self.config.groups:
            assign_menu.addSeparator()
        new_group_action = assign_menu.addAction("New group...")
        new_group_action.triggered.connect(self._assign_selected_to_new_group)
        # Ungroup clears the selection's whole membership list.
        assign_menu.addSeparator()
        clear_action = assign_menu.addAction("Ungroup")
        clear_action.triggered.connect(
            lambda: self._assign_selected_to_group(""))

        # Make primary: reorder a single fixture's membership so the
        # picked group becomes groups[0] ("first group wins" for data
        # color, orientation defaults, role and export intensity). Only
        # meaningful for one multi-group fixture.
        if len(selected) == 1 and len(selected[0].groups) > 1:
            assign_menu.addSeparator()
            primary_menu = assign_menu.addMenu("Make primary")
            for name in selected[0].groups:
                act = primary_menu.addAction(name)
                act.setCheckable(True)
                act.setChecked(name == selected[0].groups[0])
                act.triggered.connect(
                    lambda _checked, g=name: self._make_selected_primary(g))
        return menu

    def _untangle_addresses(self):
        """Resolve DMX overlaps by moving only the offenders (pure
        logic in utils/dmx_conflicts.untangle_addresses)."""
        from utils.dmx_conflicts import untangle_addresses
        self._apply_address_moves(*untangle_addresses(self.config.fixtures))

    def _compact_addresses(self):
        """Repack each universe to consecutive gap-free addresses."""
        from utils.dmx_conflicts import compact_addresses
        self._apply_address_moves(*compact_addresses(self.config.fixtures))

    def _apply_address_moves(self, moves: dict, unresolved: list):
        """Write bulk address changes into the config and refresh the
        table + lint; fixtures that could not be placed are named."""
        for index, address in moves.items():
            if 0 <= index < len(self.config.fixtures):
                self.config.fixtures[index].address = address
        if moves:
            self.update_from_config(force=True)
        if unresolved:
            names = ", ".join(
                self.config.fixtures[i].name for i in unresolved
                if 0 <= i < len(self.config.fixtures))
            QtWidgets.QMessageBox.warning(
                self, "Addresses",
                "No free address range fits these fixtures in their "
                f"universe; they were left unchanged:\n{names}")

    def _assign_selected_to_group(self, group_name: str):
        """Toggle ``group_name`` membership on every selected fixture.

        Membership editing, not replacement: when at least one selected
        fixture lacks the group, it is APPENDED to those fixtures'
        `groups` (their existing memberships stay untouched - a fixture
        already in another group keeps it and gains this one as a
        secondary). When every selected fixture already has the group,
        the click removes that membership instead (the menu entry shows
        checked in that state). "" is Ungroup: clears the whole
        membership list. Always mutate `fixture.groups`; the compat
        `fixture.group` setter would replace the list.
        """
        rows = self._selected_fixture_rows()
        if not rows:
            return
        fixtures = [self.config.fixtures[r] for r in rows]
        if not group_name:
            for fixture in fixtures:
                fixture.groups = []
        elif all(group_name in f.groups for f in fixtures):
            for fixture in fixtures:
                fixture.groups[:] = [g for g in fixture.groups
                                     if g != group_name]
        else:
            for fixture in fixtures:
                if group_name not in fixture.groups:
                    fixture.groups.append(group_name)
        self._after_group_assignment(group_name)

    def _make_selected_primary(self, group_name: str):
        """Move ``group_name`` to groups[0] of the selected fixture
        (first group wins: data color, orientation defaults, role and
        export intensity follow the primary group)."""
        row = self._selected_fixture_row()
        if row < 0:
            return
        fixture = self.config.fixtures[row]
        if group_name not in fixture.groups:
            return
        fixture.groups[:] = ([group_name]
                             + [g for g in fixture.groups if g != group_name])
        self._after_group_assignment(group_name)

    def _assign_selected_to_new_group(self):
        """Prompt for a new group name, create it, and assign the selection."""
        rows = self._selected_fixture_rows()
        if not rows:
            return
        name, ok = QtWidgets.QInputDialog.getText(
            self, "New Group", "Group name:")
        name = name.strip() if ok else ""
        if not name:
            return
        self._create_group(name)
        self._assign_selected_to_group(name)

    def _after_group_assignment(self, group_name: str):
        """Shared refresh after fixtures change group (mirrors the inspector
        group-change path but for a multi-row assignment)."""
        # Sync the GROUP column text from the model: the assignment changed
        # several fixtures' membership, and _refresh_all_row_visuals only
        # recolors cells - it does not rewrite their text (that is why the
        # group name looked stale after a multi-select assign). Text is the
        # FULL membership list, not just the primary group.
        for row in range(min(self.table.rowCount(),
                             len(self.config.fixtures))):
            item = self.table.item(row, COL_GROUP)
            if item is not None:
                fixture = self.config.fixtures[row]
                item.setText(group_column_text(fixture))
                item.setToolTip(group_column_tooltip(fixture))
        self._update_groups()
        self._refresh_all_row_visuals()
        self._update_conflict_indicators()
        if group_name and group_name in self.config.groups:
            self._selected_group = group_name
        elif self._selected_group not in self.config.groups:
            self._selected_group = None
        self._refresh_groups_panel()
        self._refresh_inspector()
        self._update_status_strip()
        self._sync_fingerprint()
        self._notify_main_window()

    def _duplicate_group(self, name: str):
        """Duplicate a group's settings (lighting role) into a new, empty
        group. Membership is deliberately not copied; the copy is ready
        to receive its own fixtures (add them via the table's Assign
        menu - fixtures can belong to several groups)."""
        source = self.config.groups.get(name)
        if source is None:
            return
        new_name = self._unique_group_name(f"{name} copy")
        self._create_group(new_name, getattr(source, "lighting_role", ""))

    def _delete_group(self, name: str):
        """Delete a group: remove that MEMBERSHIP from every fixture that
        lists it (the fixtures themselves survive, keeping their other
        memberships; the next listed group becomes primary where this
        was groups[0]), then drop the group itself."""
        for fixture in self.config.fixtures:
            if name in fixture.groups:
                fixture.groups[:] = [g for g in fixture.groups if g != name]
        self._manual_groups.discard(name)
        self.config.groups.pop(name, None)
        self.group_colors.pop(name, None)
        if self._selected_group == name:
            self._selected_group = None
        self._after_group_assignment("")

    def _unique_group_name(self, base: str) -> str:
        if base not in self.config.groups:
            return base
        i = 2
        while f"{base} {i}" in self.config.groups:
            i += 1
        return f"{base} {i}"

    def _show_group_context_menu(self, name: str, global_pos):
        menu = QtWidgets.QMenu(self)
        add_action = menu.addAction("Add group...")
        add_action.triggered.connect(self._add_group)
        duplicate_action = menu.addAction("Duplicate group")
        duplicate_action.triggered.connect(
            lambda: self._duplicate_group(name))
        delete_action = menu.addAction("Delete group")
        delete_action.triggered.connect(
            lambda: self._delete_group(name))
        menu.exec(global_pos)

    def _show_groups_panel_menu(self, panel, pos):
        """Right-click on empty groups-panel space: offer Add group."""
        menu = QtWidgets.QMenu(self)
        add_action = menu.addAction("Add group...")
        add_action.triggered.connect(self._add_group)
        menu.exec(panel.mapToGlobal(pos))

    def _show_table_context_menu(self, pos: QtCore.QPoint):
        """Right-click on the patch table.

        On a row: select it (if not already) and offer Add / Duplicate /
        Remove / Assign. On empty space: offer just Add fixture.
        """
        index = self.table.indexAt(pos)
        has_row = index.isValid()
        if has_row:
            row = index.row()
            selection_model = self.table.selectionModel()
            selected_rows = ({i.row() for i in selection_model.selectedRows()}
                             if selection_model is not None else set())
            if row not in selected_rows:
                self.table.selectRow(row)
        menu = self._build_table_context_menu(has_row=has_row)
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def _add_fixture(self):
        """Open the fixture browser and add the picked fixture(s)."""
        from gui.dialogs.fixture_browser_dialog import FixtureBrowserDialog
        from gui.dialogs.gdtf_share_pane import GDTFSharePane
        try:
            fixture_files = self._scan_fixture_files()
            if not fixture_files:
                raise Exception("No fixture files found in QLC+ directories")

            dialog = FixtureBrowserDialog(
                fixture_files, parent=self,
                rescan=self._scan_fixture_files,
                share_pane=GDTFSharePane())
            if dialog.exec() == QDialog.DialogCode.Accepted:
                selected = dialog.selection()
                if selected:
                    path, quantity = selected
                    self._add_fixtures_from_qxf(path, quantity)

        except Exception as e:
            user_warnings.warn(f"Adding the fixture failed: {e}", category="fixture-library")
            import traceback
            traceback.print_exc()

    def _find_next_available_address(self, channel_count: int) -> tuple:
        """Find the next available DMX address that can fit the given channel count.

        Returns:
            tuple: (universe, address) for the next available slot
        """
        # Build a map of used addresses per universe
        used_addresses = {}  # universe -> list of (start, end) tuples

        for fixture in self.config.fixtures:
            universe = fixture.universe
            if universe not in used_addresses:
                used_addresses[universe] = []

            start = fixture.address
            end = fixture.address + fixture_channel_count(fixture) - 1
            used_addresses[universe].append((start, end))

        # Try to find space in existing universes first
        for universe in range(1, 17):
            if universe not in used_addresses:
                # Empty universe, use address 1
                return (universe, 1)

            # Sort ranges by start address
            ranges = sorted(used_addresses[universe], key=lambda x: x[0])

            # Check if there's space at the beginning
            if ranges[0][0] > channel_count:
                return (universe, 1)

            # Check for gaps between fixtures
            for i in range(len(ranges) - 1):
                gap_start = ranges[i][1] + 1
                gap_end = ranges[i + 1][0] - 1
                if gap_end - gap_start + 1 >= channel_count:
                    return (universe, gap_start)

            # Check if there's space after the last fixture
            last_end = ranges[-1][1]
            if last_end + channel_count <= 512:
                return (universe, last_end + 1)

        # Fallback to universe 1, address 1 if all universes are somehow full
        return (1, 1)

    def _unique_fixture_name(self, base_name: str) -> str:
        """base_name, or 'base_name (2)', 'base_name (3)', ... if taken."""
        existing = {f.name for f in self.config.fixtures}
        if base_name not in existing:
            return base_name
        n = 2
        while f"{base_name} ({n})" in existing:
            n += 1
        return f"{base_name} ({n})"

    def _add_fixtures_from_qxf(self, fixture_path: str, quantity: int = 1):
        """Parse a .qxf and add ``quantity`` fixtures to the config.

        Each copy is patched at the next free (universe, address) slot -
        the free-slot search re-runs after every append, so multi-adds
        come out at consecutive non-overlapping addresses.
        """
        from utils.fixture_library import parse_fixture_file
        defn = parse_fixture_file(fixture_path)

        manufacturer = defn.manufacturer
        model = defn.model
        fixture_type = defn.legacy_type

        mode_data = [
            {'name': mode.name, 'channels': len(mode.channels)}
            for mode in defn.modes
        ]
        first_mode_channels = mode_data[0]['channels'] if mode_data else 1

        for _ in range(quantity):
            universe, address = self._find_next_available_address(first_mode_channels)
            new_fixture = Fixture(
                universe=universe,
                address=address,
                manufacturer=manufacturer,
                model=model,
                name=self._unique_fixture_name(model),
                group="",
                current_mode=mode_data[0]['name'],
                available_modes=[
                    FixtureMode(name=mode['name'], channels=mode['channels'])
                    for mode in mode_data
                ],
                type=fixture_type,
                x=0.0,
                y=0.0,
                z=0.0,
                definition_source=defn.source,
                gdtf_fixture_type_id=defn.gdtf_fixture_type_id,
            )
            self.config.fixtures.append(new_fixture)

        # Check if this fixture model is already cached
        from utils.fixture_utils import _fixture_definitions_cache
        fixture_key = f"{manufacturer}_{model}"
        alt_key = f"{manufacturer}_{model.replace(' ', '_')}"
        needs_caching = fixture_key not in _fixture_definitions_cache and alt_key not in _fixture_definitions_cache

        if needs_caching:
            # Show loading dialog with animated progress bar
            # Run the slow operation in a thread so animation keeps moving
            loading_dialog = QtWidgets.QDialog(self)
            loading_dialog.setWindowTitle("Loading Fixture")
            loading_dialog.setWindowModality(QtCore.Qt.WindowModality.WindowModal)
            loading_dialog.setFixedSize(320, 100)
            loading_dialog.setWindowFlags(
                loading_dialog.windowFlags() & ~QtCore.Qt.WindowType.WindowCloseButtonHint
            )

            layout = QtWidgets.QVBoxLayout(loading_dialog)
            layout.setContentsMargins(20, 15, 20, 15)

            label = QtWidgets.QLabel(f"Loading {manufacturer} {model}...")
            label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(label)

            # Indeterminate progress bar (animated)
            progress_bar = QtWidgets.QProgressBar()
            progress_bar.setMinimum(0)
            progress_bar.setMaximum(0)  # This makes it indeterminate/animated
            progress_bar.setTextVisible(False)
            layout.addWidget(progress_bar)

            loading_dialog.show()
            QtWidgets.QApplication.processEvents()

            # Run caching in a background thread
            from PyQt6.QtCore import QThread, pyqtSignal

            class CacheWorker(QThread):
                finished = pyqtSignal()

                def __init__(self, mfr, mdl):
                    super().__init__()
                    self.mfr = mfr
                    self.mdl = mdl

                def run(self):
                    get_cached_fixture_definitions({(self.mfr, self.mdl)})
                    self.finished.emit()

            worker = CacheWorker(manufacturer, model)
            worker.finished.connect(loading_dialog.accept)
            # A loading dialog is a progress indicator, not a question, so
            # never QDialog.exec() - the test suite's modal guard bans it
            # (docs/qt-gotchas.md #7) and a modal loop adds nothing here.
            # A plain QEventLoop waits for the worker while the shown
            # dialog keeps animating; the WindowModal flag still blocks
            # input to the tab underneath.
            wait_loop = QtCore.QEventLoop()
            worker.finished.connect(wait_loop.quit)
            worker.start()
            wait_loop.exec()
            worker.wait()  # Ensure thread is fully done
        else:
            # Already cached, no need for loading dialog
            get_cached_fixture_definitions({(manufacturer, model)})

        # A fresh parse may now resolve models that missed earlier.
        self._definition_memo.pop((manufacturer, model), None)

        # Refresh table
        self.update_from_config()

        # Notify main window of changes
        self._notify_main_window()

        print(f"Added {quantity}x fixture: {manufacturer} {model}")

    def _remove_fixture(self):
        """Remove the selected fixture from the configuration."""
        row = self._selected_fixture_row()
        if row < 0:
            return
        self.config.fixtures.pop(row)
        self._update_groups()
        self.update_from_config(force=True)
        self._notify_main_window()

    def _find_next_free_address(self, universe: int, channel_count: int, exclude_fixture=None) -> tuple:
        """Find the next free DMX address in a universe.

        Args:
            universe: The universe to search in
            channel_count: Number of channels needed
            exclude_fixture: Optional fixture to exclude from conflict check

        Returns:
            Tuple of (universe, address) for the next free slot
        """
        max_address = 512

        # Collect all used address ranges in this universe
        used_ranges = []
        for fixture in self.config.fixtures:
            if fixture is exclude_fixture:
                continue
            if fixture.universe == universe:
                fixture_channels = fixture_channel_count(fixture)
                used_ranges.append((fixture.address, fixture.address + fixture_channels - 1))

        # Sort by start address
        used_ranges.sort(key=lambda x: x[0])

        # Find first gap that fits
        current_address = 1
        for start, end in used_ranges:
            if current_address + channel_count - 1 < start:
                # Found a gap before this fixture
                return (universe, current_address)
            # Move past this fixture
            current_address = max(current_address, end + 1)

        # Check if there's room at the end
        if current_address + channel_count - 1 <= max_address:
            return (universe, current_address)

        # No room in this universe, try next universe
        return self._find_next_free_address(universe + 1, channel_count, exclude_fixture)

    def _generate_unique_copy_name(self, base_name: str) -> str:
        """Generate a unique copy name for a fixture.

        Args:
            base_name: The original fixture name (e.g., "M1")

        Returns:
            A unique name like "M1 (Copy)", "M1 (Copy 2)", "M1 (Copy 3)", etc.
        """
        existing_names = {f.name for f in self.config.fixtures}

        # Try simple "(Copy)" first
        candidate = f"{base_name} (Copy)"
        if candidate not in existing_names:
            return candidate

        # Try numbered copies
        copy_num = 2
        while True:
            candidate = f"{base_name} (Copy {copy_num})"
            if candidate not in existing_names:
                return candidate
            copy_num += 1

    def _duplicate_fixture(self):
        """Duplicate the selected fixture at the next available address."""
        row = self._selected_fixture_row()
        if row < 0:
            QtWidgets.QMessageBox.warning(
                self,
                "No Selection",
                "Please select a fixture to duplicate.",
                QtWidgets.QMessageBox.StandardButton.Ok
            )
            return

        # Get original fixture
        original_fixture = self.config.fixtures[row]

        # Get channel count
        channel_count = fixture_channel_count(original_fixture)

        # Find next free address (starting from same universe)
        new_universe, new_address = self._find_next_free_address(
            original_fixture.universe, channel_count
        )

        # Generate unique copy name
        new_name = self._generate_unique_copy_name(original_fixture.name)

        # Create duplicate
        new_fixture = Fixture(
            universe=new_universe,
            address=new_address,
            manufacturer=original_fixture.manufacturer,
            model=original_fixture.model,
            name=new_name,
            # Full membership, not the compat `group=` keyword (which
            # would keep only the primary group). Copy the list so the
            # twins don't share one mutable membership.
            groups=list(original_fixture.groups),
            current_mode=original_fixture.current_mode,
            available_modes=[
                FixtureMode(name=mode.name, channels=mode.channels)
                for mode in original_fixture.available_modes
            ],
            type=original_fixture.type,
            x=original_fixture.x,
            y=original_fixture.y,
            z=original_fixture.z,
            # Copy orientation settings
            mounting=original_fixture.mounting,
            yaw=original_fixture.yaw,
            pitch=original_fixture.pitch,
            roll=original_fixture.roll,
            orientation_uses_group_default=original_fixture.orientation_uses_group_default,
            z_uses_group_default=original_fixture.z_uses_group_default,
            definition_source=original_fixture.definition_source,
            gdtf_fixture_type_id=original_fixture.gdtf_fixture_type_id,
        )

        # Add to configuration
        self.config.fixtures.append(new_fixture)

        # Add to every group it is a member of (derived lists).
        for group_name in new_fixture.groups:
            if group_name in self.config.groups:
                self.config.groups[group_name].fixtures.append(new_fixture)

        # Refresh table
        self.update_from_config(force=True)

        # Notify main window of changes
        self._notify_main_window()

        print(f"Duplicated fixture: {original_fixture.manufacturer} {original_fixture.model}")
