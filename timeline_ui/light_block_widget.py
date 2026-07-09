# timeline_ui/light_block_widget.py
# Visual widget for light effect blocks on timeline
# Adapted from midimaker_and_show_structure/ui/midi_block_widget.py

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel
from PyQt6.QtCore import Qt, pyqtSignal, QPoint, QRect
from PyQt6.QtGui import QPainter, QColor, QPen, QBrush, QMouseEvent
from config.models import LightBlock

# Glutorange, the brand accent (gui/theme_tokens.py); selection marks in
# this custom-painted widget follow the theme's selection color. Same
# value in both themes, so a constant is fine here.
ACCENT = QColor(240, 86, 46)


def active_tokens() -> dict:
    """Token dict of the theme currently applied to the app.

    Custom painters cannot reach QSS roles, so they read the brand
    tokens directly. Same stylesheet sniff the tabs use (see
    gui/dialogs/autogen_dialog._active_tokens): the light theme's
    window color only ever appears in the light stylesheet.
    """
    from PyQt6.QtWidgets import QApplication
    from gui.theme_tokens import THEMES

    app = QApplication.instance()
    qss = app.styleSheet() if app is not None else ""
    light = THEMES.get("light")
    if light is not None and light["window"] in qss:
        return light
    return THEMES["dark"]


def token_qcolor(key: str, alpha: int = 255) -> QColor:
    """Brand token as a QColor, optionally with an alpha override.

    Only the solid ``#rrggbb`` tokens are used here; the ``rgba(...)``
    string tokens (e.g. accent_tint) are not QColor-parseable, so we
    pass the base accent through with an explicit alpha instead.
    """
    tok = active_tokens()
    color = QColor(tok.get(key, "#000000"))
    if alpha != 255:
        color.setAlpha(alpha)
    return color


def _tinted(base: QColor, alpha: int) -> QColor:
    """A copy of ``base`` at the given alpha (for low-alpha row tints)."""
    color = QColor(base)
    color.setAlpha(alpha)
    return color


class LightBlockWidget(QWidget):
    """Visual representation of a light effect block on the timeline.

    Supports dragging to move, edge dragging to resize, and double-click to edit.
    """

    remove_requested = pyqtSignal(object)  # Emits self when delete requested
    position_changed = pyqtSignal(object, float)  # Emits (self, new_start_time)
    duration_changed = pyqtSignal(object, float)  # Emits (self, new_duration)
    block_edited = pyqtSignal()  # Emitted when block content is edited (for auto-save)

    RESIZE_HANDLE_WIDTH = 8  # Pixels for resize handle area
    HEADER_HEIGHT = 24  # Pixels reserved for header/handle area (drag entire effect)
    # Minimum duration for a sublane block created by drag — anything shorter
    # is treated as an accidental mouse slip and rejected.
    MIN_SUBLANE_BLOCK_DURATION = 0.05  # seconds
    # Hit-test buffer (in pixels) so very narrow sublane blocks remain clickable.
    SUBLANE_HIT_BUFFER = 3

    def __init__(self, block: LightBlock, timeline_widget, lane_widget, parent=None):
        """Create a light block widget.

        Args:
            block: LightBlock data model
            timeline_widget: Parent TimelineWidget for coordinate conversion
            lane_widget: Parent LightLaneWidget for capability/sublane info
            parent: Parent widget (defaults to timeline_widget)
        """
        super().__init__(parent or timeline_widget)
        self.block = block
        self.timeline_widget = timeline_widget
        self.lane_widget = lane_widget

        self.dragging = False
        self.resizing_left = False
        self.resizing_right = False
        self.drag_start_pos = None
        self.drag_start_time = None
        self.drag_start_duration = None
        self.snap_to_grid = True
        self.shift_drag_copying = False  # True when shift+drag to copy

        # Sublane interaction state
        self.clicked_sublane_type = None  # Which sublane type was clicked (if any)
        self.selected_sublane_type = None  # Which sublane type is currently selected (for highlighting)
        self.selected_sublane_block = None  # Which specific sublane block is selected
        self.resizing_sublane = None  # Block being resized (block reference)
        self.resizing_sublane_edge = None  # 'left' or 'right'
        self.dragging_sublane = None  # Block being dragged (block reference)
        self.drag_start_sublane_start = None  # Start time of sublane being resized/dragged
        self.drag_start_sublane_end = None  # End time of sublane being resized/dragged

        # Drag-to-create state
        self.creating_sublane = None  # Which sublane type is being created
        self.create_start_time = None  # Start time for new block being created
        self.create_end_time = None  # End time for new block being created (updated during drag)

        # Overlap feedback state
        self.overlap_detected = False  # True when current drag/resize would create overlap

        # Intensity handle state (for dimmer blocks)
        self.dragging_intensity_handle = None  # Which dimmer block's intensity handle is being dragged
        self.drag_start_intensity = None  # Initial intensity value when drag started

        # Multi-selection state
        self._is_multi_selected = False

        # Right-button marquee selection of sublane blocks within this effect.
        # Pending = right-button down but drag hasn't crossed threshold yet.
        # Active = drawing the marquee. On release with active marquee, the
        # native contextMenuEvent is suppressed once via _suppress_next_context_menu.
        self._sublane_marquee_pending = False
        self._sublane_marquee_active = False
        self._sublane_marquee_start = QPoint()
        self._sublane_marquee_current = QPoint()
        self._suppress_next_context_menu = False
        self.MARQUEE_DRAG_THRESHOLD = 6  # pixels

        self.setMinimumHeight(30)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMouseTracking(True)  # Enable mouse tracking for cursor updates on hover

        self.setup_ui()
        self.update_position()

    def setup_ui(self):
        """Set up the block's visual appearance."""
        # No UI widgets needed - we'll draw everything in paintEvent
        pass

    def _get_display_name(self) -> str:
        """Get display name for the block."""
        # Use custom name if set, otherwise default to "base"
        if self.block.name:
            name = self.block.name
        else:
            name = "base"

        # Add asterisk if modified
        if self.block.modified:
            name += " *"

        return name

    def _format_parameters(self) -> str:
        """Format block parameters for display."""
        params = self.block.parameters
        parts = []
        if params.get('speed') and params['speed'] != '1':
            parts.append(f"×{params['speed']}")
        if params.get('intensity'):
            parts.append(f"I:{params['intensity']}")
        return " ".join(parts) if parts else ""

    def update_display(self):
        """Update the display after block data changes."""
        self.update()  # Trigger repaint

    @property
    def is_multi_selected(self) -> bool:
        """Check if this block is part of a multi-selection."""
        return self._is_multi_selected

    def set_multi_selected(self, selected: bool) -> None:
        """Set multi-selection state.

        Args:
            selected: True to mark as multi-selected
        """
        if self._is_multi_selected != selected:
            self._is_multi_selected = selected
            self.update()  # Trigger repaint for visual update

    def get_block_time_bounds(self) -> tuple:
        """Get the time bounds of this block.

        Returns:
            Tuple of (start_time, end_time)
        """
        return (self.block.start_time, self.block.end_time)

    def update_position(self):
        """Update widget position and size based on block envelope data."""
        # Calculate position based on envelope start/end times
        x = int(self.timeline_widget.time_to_pixel(self.block.start_time))
        duration = self.block.end_time - self.block.start_time
        width = int(self.timeline_widget.time_to_pixel(duration))
        width = max(20, width)  # Minimum width

        # Height: fill entire timeline height (spans all sublanes)
        height = self.timeline_widget.height()

        # Position at top of timeline (y=0)
        self.setGeometry(x, 0, width, height)

    def set_snap_to_grid(self, snap: bool):
        """Enable/disable snap to grid."""
        self.snap_to_grid = snap

    def pixel_to_time(self, pixel_x):
        """Convert pixel X position (relative to envelope) to absolute time."""
        envelope_start_pixel = self.timeline_widget.time_to_pixel(self.block.start_time)
        absolute_pixel = envelope_start_pixel + pixel_x
        return self.timeline_widget.pixel_to_time(absolute_pixel)

    def paintEvent(self, event):
        """Draw the effect envelope and sublane blocks."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Draw effect envelope (subtle background)
        self._draw_envelope(painter)

        # Draw individual sublane blocks
        self._draw_sublane_blocks(painter)

        # Draw resize handles on envelope
        self._draw_resize_handles(painter)

        # Draw preview of block being created
        if self.creating_sublane and self.create_start_time is not None and self.create_end_time is not None:
            self._draw_create_preview(painter)

        # Draw effect name label LAST (on top of everything)
        self._draw_effect_label(painter)

        # Draw riff indicator if this block came from a riff
        if self.block.riff_source:
            self._draw_riff_indicator(painter)

        # Draw the sublane marquee rectangle on top of everything else.
        if self._sublane_marquee_active:
            rect = self._compute_sublane_marquee_rect()
            marquee_fill = QColor(ACCENT)
            marquee_fill.setAlpha(40)
            marquee_pen = QColor(ACCENT)
            marquee_pen.setAlpha(200)
            painter.setBrush(QBrush(marquee_fill))
            painter.setPen(QPen(marquee_pen, 2))
            painter.drawRect(rect)

    def _has_group_color(self) -> bool:
        """True when the lane resolves to a group data color."""
        if hasattr(self.lane_widget, "group_color"):
            return bool(self.lane_widget.group_color())
        return False

    def _group_base_color(self) -> QColor:
        """Base color for this block's fills and hairlines.

        The lane's group data color when resolvable (North Star: blocks
        read in their group's color), else a faint brand neutral so the
        block still reads on the dark surface without inventing a
        Material color.
        """
        if hasattr(self.lane_widget, "group_color"):
            group = self.lane_widget.group_color()
            if group:
                return QColor(group)
        return token_qcolor("text_secondary")

    def sublane_fill_color(self, sublane_type: str, sublane_block=None) -> QColor:
        """Base (pre-alpha) fill color for a sublane row.

        Colour rows use the block's own RGBW data color (the real
        content); every other row is a tint of the lane's group color.
        Exposed so tests can assert fills derive from the group color
        rather than a fixed Material palette.
        """
        if sublane_type == "colour" and sublane_block is not None:
            return self._get_colour_block_color(sublane_block)
        return self._group_base_color()

    def _draw_envelope(self, painter):
        """Draw the effect envelope: group-color frame + tint fill.

        North Star block anatomy: the effect container is framed in its
        lane's group color with a ~0.18-alpha tint of the same color as
        fill. Lanes without a resolvable group keep the old neutral
        gray. Selection stays distinct: a solid accent border.
        """
        base = self._group_base_color()
        group = self._has_group_color()

        fill = QColor(base)
        fill.setAlpha(46 if group else 60)  # ~0.18 group tint / faint neutral
        painter.setBrush(QBrush(fill))

        if self._is_multi_selected:
            # Multi-selection highlight - solid accent border
            pen = QPen(ACCENT, 3, Qt.PenStyle.SolidLine)
        else:
            # Envelope outline - dashed group-color line (dashes keep
            # the envelope visually distinct from its sub-blocks)
            border_color = QColor(base)
            border_color.setAlpha(200)
            pen = QPen(border_color, 2, Qt.PenStyle.DashLine)
            pen.setDashPattern([4, 3])  # Custom dash pattern: 4px dash, 3px gap

        painter.setPen(pen)

        # Hard corners (datasheet aesthetic, radius 0)
        painter.drawRect(self.rect().adjusted(1, 1, -1, -1))

    def _draw_effect_label(self, painter):
        """Draw effect name label on top of everything."""
        from PyQt6.QtGui import QFont
        from PyQt6.QtCore import QRect

        # Set font
        font = QFont()
        font.setPointSize(9)
        font.setBold(True)
        painter.setFont(font)

        # Get text
        text = self._get_display_name()

        # Calculate text size
        metrics = painter.fontMetrics()
        text_width = metrics.horizontalAdvance(text)
        text_height = metrics.height()

        # Position at top-left with padding
        x_pos = 6
        y_pos = 6
        padding = 4

        # Draw semi-transparent panel background behind text (brand
        # surface + border tokens, not Material grays)
        bg_rect = QRect(x_pos - padding, y_pos - padding,
                       text_width + 2 * padding, text_height + 2 * padding)
        painter.setBrush(QBrush(token_qcolor("panel", 200)))
        painter.setPen(QPen(token_qcolor("border"), 1))
        painter.drawRect(bg_rect)

        # Draw text in warm white (#F4F1EA), never pure white
        painter.setPen(QPen(token_qcolor("text")))
        painter.drawText(x_pos, y_pos + text_height - 3, text)

    def _draw_riff_indicator(self, painter):
        """Draw indicator badge showing this block came from a riff."""
        from PyQt6.QtGui import QFont
        from PyQt6.QtCore import QRect

        # Choose indicator text and color based on modification state.
        # Modified reads in the brand accent; unmodified stays a quiet
        # neutral chip (brand tokens, no Material tan/green).
        if self.block.modified:
            indicator_text = "R*"
            bg_color = token_qcolor("accent", 220)
            border_color = token_qcolor("accent_line")
            text_color = token_qcolor("on_accent")
        else:
            indicator_text = "R"
            bg_color = token_qcolor("raised", 220)
            border_color = token_qcolor("border")
            text_color = token_qcolor("text_secondary")

        # Set font
        font = QFont()
        font.setPointSize(7)
        font.setBold(True)
        painter.setFont(font)

        # Calculate text size
        metrics = painter.fontMetrics()
        text_width = metrics.horizontalAdvance(indicator_text)
        text_height = metrics.height()

        # Position in top-right corner (below the effect label if present)
        padding = 3
        x_pos = self.width() - text_width - padding * 2 - 4
        y_pos = 6  # Same y as effect label

        # Draw badge background
        bg_rect = QRect(x_pos - padding, y_pos - padding,
                       text_width + 2 * padding, text_height + 2 * padding)
        painter.setBrush(QBrush(bg_color))
        painter.setPen(QPen(border_color, 1))
        painter.drawRect(bg_rect)

        # Draw text
        painter.setPen(QPen(text_color))
        painter.drawText(x_pos, y_pos + text_height - 3, indicator_text)

    def _draw_sublane_blocks(self, painter):
        """Draw individual sublane blocks within the envelope.

        North Star: every row tints in the lane's group data color;
        colour rows keep the block's own RGBW color (the real content)
        as a left-to-right gradient. No Material per-type palette.
        """
        sublane_height = self.lane_widget.sublane_height

        # Group data color (or brand neutral) drives the non-colour rows
        # and every hairline border.
        group_base = self._group_base_color()
        hairline = _tinted(group_base, 180)

        # Get capabilities
        caps = self.lane_widget.capabilities if hasattr(self.lane_widget, 'capabilities') and self.lane_widget.capabilities else None
        has_dimmer = caps.has_dimmer if caps else True
        has_colour = caps.has_colour if caps else False
        has_movement = caps.has_movement if caps else False
        has_special = caps.has_special if caps else False

        # Draw dimmer blocks if lane has dimmer or colour capability
        if has_dimmer or has_colour:
            for dimmer_block in self.block.dimmer_blocks:
                self._draw_sublane_block(
                    painter,
                    dimmer_block,
                    "dimmer",
                    _tinted(group_base, 60),
                    sublane_height,
                    border_color=hairline,
                )

        # Draw colour blocks if lane has colour capability
        if has_colour:
            for colour_block in self.block.colour_blocks:
                color = self._get_colour_block_color(colour_block)
                self._draw_sublane_block(
                    painter,
                    colour_block,
                    "colour",
                    color,
                    sublane_height,
                    border_color=hairline,
                )

        # Draw movement blocks if lane has movement capability
        if has_movement:
            for movement_block in self.block.movement_blocks:
                self._draw_sublane_block(
                    painter,
                    movement_block,
                    "movement",
                    _tinted(group_base, 60),
                    sublane_height,
                    border_color=hairline,
                )

        # Draw special blocks if lane has special capability
        if has_special:
            for special_block in self.block.special_blocks:
                self._draw_sublane_block(
                    painter,
                    special_block,
                    "special",
                    _tinted(group_base, 60),
                    sublane_height,
                    border_color=hairline,
                )

    def _draw_sublane_block(self, painter, sublane_block, sublane_type, color,
                            sublane_height, border_color=None):
        """Draw a single sublane block."""
        # Get sublane row index
        sublane_index = self.lane_widget.get_sublane_index(sublane_type)

        # Calculate y position for this sublane
        y_offset = sublane_index * sublane_height

        # Calculate x position and width based on block times relative to envelope
        block_start_pixel = self.timeline_widget.time_to_pixel(sublane_block.start_time)
        block_end_pixel = self.timeline_widget.time_to_pixel(sublane_block.end_time)
        envelope_start_pixel = self.timeline_widget.time_to_pixel(self.block.start_time)

        x_offset = block_start_pixel - envelope_start_pixel
        width = block_end_pixel - block_start_pixel

        # Draw the sublane block. Colour rows carry the real content
        # color, so they render as a left-to-right gradient (North Star
        # color-block sheen); other rows are a flat group-color tint.
        if sublane_type == "colour":
            from PyQt6.QtGui import QLinearGradient
            gradient = QLinearGradient(int(x_offset), 0,
                                       int(x_offset + width), 0)
            left = QColor(color)
            left.setAlpha(210)
            right = QColor(color.darker(140))
            right.setAlpha(210)
            gradient.setColorAt(0.0, left)
            gradient.setColorAt(1.0, right)
            painter.setBrush(QBrush(gradient))
        else:
            painter.setBrush(QBrush(color))

        # Thicker accent border if this specific block is selected;
        # otherwise a group-color hairline (never Material darkening).
        is_selected = (sublane_block is self.selected_sublane_block)
        if is_selected:
            painter.setPen(QPen(ACCENT, 3))  # Accent border when selected
        else:
            hairline = border_color if border_color is not None else color.darker(130)
            painter.setPen(QPen(hairline, 1))

        # Draw with some margin from edges; hard corners (radius 0)
        margin = 2
        painter.drawRect(
            int(x_offset + margin),
            int(y_offset + margin),
            int(width - 2 * margin),
            int(sublane_height - 2 * margin),
        )

        # Draw grid and intensity handle for dimmer blocks
        if sublane_type == "dimmer":
            self._draw_dimmer_block_grid(painter, sublane_block, x_offset, y_offset, width, sublane_height, margin)
            self._draw_intensity_handle(painter, sublane_block, x_offset, y_offset, width, sublane_height, margin)

            # Draw RGB icon if controlling RGB instead of dimmer
            has_dimmer = self.lane_widget.capabilities.has_dimmer if hasattr(self.lane_widget, 'capabilities') and self.lane_widget.capabilities else True
            has_colour = self.lane_widget.capabilities.has_colour if hasattr(self.lane_widget, 'capabilities') and self.lane_widget.capabilities else False
            if not has_dimmer and has_colour and width >= 40:
                self._draw_rgb_icon(painter, x_offset, y_offset, width, sublane_height, margin)

        # Draw grid for movement blocks (similar to dimmer blocks)
        if sublane_type == "movement":
            self._draw_movement_block_grid(painter, sublane_block, x_offset, y_offset, width, sublane_height, margin)

        # Draw text label if block is wide enough
        self._draw_sublane_block_label(painter, sublane_block, sublane_type, x_offset, y_offset, width, sublane_height, margin)

        # Draw resize handles if this specific block is selected.
        if is_selected:
            handle_color = token_qcolor("accent", 180)
            painter.setBrush(QBrush(handle_color))
            painter.setPen(Qt.PenStyle.NoPen)

            # Left handle
            painter.drawRect(int(x_offset + margin), int(y_offset + margin),
                           4, int(sublane_height - 2 * margin))
            # Right handle
            painter.drawRect(int(x_offset + width - margin - 4), int(y_offset + margin),
                           4, int(sublane_height - 2 * margin))

    def _draw_sublane_block_label(self, painter, sublane_block, sublane_type, x_offset, y_offset, width, sublane_height, margin):
        """Draw text label on sublane block if wide enough."""
        from PyQt6.QtGui import QFont
        from PyQt6.QtCore import QRect

        # Minimum width to show label (in pixels)
        MIN_WIDTH_FOR_LABEL = 60

        if width < MIN_WIDTH_FOR_LABEL:
            return  # Block too narrow, skip label

        # For dimmer blocks, use effect type as the primary label
        if sublane_type == "dimmer":
            effect_type = getattr(sublane_block, 'effect_type', 'static')
            # Format effect type nicely (e.g., "ping_pong_smooth" -> "Ping Pong")
            label_text = effect_type.replace('_', ' ').title()
            # Shorten some common names
            label_text = label_text.replace('Ping Pong Smooth', 'Ping Pong')
            label_text = label_text.replace('Random Strobe', 'Random')
            label_text = label_text.replace('Waterfall Down', 'Waterfall ↓')
            label_text = label_text.replace('Waterfall Up', 'Waterfall ↑')

            # Add intensity if wide enough
            if width >= 100:
                intensity = int(sublane_block.intensity)
                full_text = f"{label_text} ({intensity})"
            else:
                full_text = label_text
        else:
            # Sublane type labels for other types
            sublane_labels = {
                "colour": "Colour",
                "movement": "Movement",
                "special": "Special"
            }

            # Get label text
            label_text = sublane_labels.get(sublane_type, sublane_type.capitalize())

            # Get additional info if block is wide enough
            info_text = ""
            if width >= 100:  # Wide enough for additional info
                info_text = self._get_sublane_block_info(sublane_block, sublane_type)

            # Combine label and info
            if info_text:
                full_text = f"{label_text}: {info_text}"
            else:
                full_text = label_text

        # Set font
        font = QFont()
        font.setPointSize(7)
        font.setBold(True)
        painter.setFont(font)

        # Calculate text size
        metrics = painter.fontMetrics()
        text_width = metrics.horizontalAdvance(full_text)
        text_height = metrics.height()

        # Check if text fits within block width
        if text_width + 10 > width - 2 * margin:
            # Text too wide, try just the label without info
            full_text = label_text
            text_width = metrics.horizontalAdvance(full_text)
            if text_width + 10 > width - 2 * margin:
                return  # Even just label doesn't fit, skip

        # Calculate centered position
        text_x = int(x_offset + (width - text_width) / 2)
        text_y = int(y_offset + (sublane_height + text_height) / 2 - 2)

        # Draw text in warm white (#F4F1EA); reads on the group tint and
        # on the colour gradient without pure white
        painter.setPen(QPen(token_qcolor("text")))
        painter.drawText(text_x, text_y, full_text)

    def _draw_rgb_icon(self, painter, x_offset, y_offset, width, sublane_height, margin):
        """Draw small RGB icon in corner of dimmer block to indicate RGB control mode."""
        from PyQt6.QtGui import QFont
        from PyQt6.QtCore import QRect

        # Draw "RGB" text in top-right corner
        font = QFont()
        font.setPointSize(6)
        font.setBold(True)
        painter.setFont(font)

        icon_text = "RGB"
        metrics = painter.fontMetrics()
        text_width = metrics.horizontalAdvance(icon_text)
        text_height = metrics.height()

        # Position in top-right corner with padding
        icon_x = int(x_offset + width - text_width - 6)
        icon_y = int(y_offset + margin + text_height)

        # Draw semi-transparent background (brand surface + text tokens)
        bg_rect = QRect(icon_x - 2, icon_y - text_height, text_width + 4, text_height + 2)
        painter.setBrush(QBrush(token_qcolor("window", 150)))
        painter.setPen(QPen(token_qcolor("text", 200), 1))
        painter.drawRect(bg_rect)

        # Draw text
        painter.setPen(QPen(token_qcolor("text")))
        painter.drawText(icon_x, icon_y, icon_text)

    def _draw_intensity_handle(self, painter, sublane_block, x_offset, y_offset, width, sublane_height, margin):
        """Draw intensity handle and darkened area above it for dimmer blocks."""
        try:
            # Get intensity (0-255)
            intensity = getattr(sublane_block, 'intensity', 255.0)

            # Calculate handle Y position (top=255, bottom=0)
            # Invert: higher intensity = higher position (toward top)
            usable_height = sublane_height - 2 * margin
            intensity_ratio = intensity / 255.0
            handle_y_offset = y_offset + margin + (usable_height * (1.0 - intensity_ratio))

            # Draw darkened overlay above the handle
            if intensity < 255:
                dark_overlay = token_qcolor("window", 120)
                painter.setBrush(QBrush(dark_overlay))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawRect(
                    int(x_offset + margin),
                    int(y_offset + margin),
                    int(width - 2 * margin),
                    int(handle_y_offset - (y_offset + margin))
                )

            # Draw intensity handle line
            handle_pen = QPen(token_qcolor("text", 220), 2)
            painter.setPen(handle_pen)
            painter.drawLine(
                int(x_offset + margin),
                int(handle_y_offset),
                int(x_offset + width - margin),
                int(handle_y_offset)
            )

            # Draw intensity label if dragging this handle
            if hasattr(self, 'dragging_intensity_handle') and self.dragging_intensity_handle is sublane_block:
                from PyQt6.QtGui import QFont
                from PyQt6.QtCore import QRect

                # Draw intensity value label
                font = QFont()
                font.setPointSize(8)
                font.setBold(True)
                painter.setFont(font)

                intensity_text = f"{int(intensity)}"
                metrics = painter.fontMetrics()
                text_width = metrics.horizontalAdvance(intensity_text)
                text_height = metrics.height()

                # Position label near the handle
                label_x = int(x_offset + width / 2 - text_width / 2)
                label_y = int(handle_y_offset - 5)

                # Draw background (brand surface + text tokens)
                bg_rect = QRect(label_x - 3, label_y - text_height, text_width + 6, text_height + 3)
                painter.setBrush(QBrush(token_qcolor("panel", 210)))
                painter.setPen(QPen(token_qcolor("text"), 1))
                painter.drawRect(bg_rect)

                # Draw text
                painter.setPen(QPen(token_qcolor("text")))
                painter.drawText(label_x, label_y, intensity_text)

        except Exception as e:
            # Silently fail if handle cannot be drawn
            pass

    def _draw_dimmer_block_grid(self, painter, sublane_block, x_offset, y_offset, width, sublane_height, margin):
        """Draw beat grid lines inside dimmer block based on speed setting."""
        try:
            # Get speed setting
            effect_speed = getattr(sublane_block, 'effect_speed', '1')

            # Convert speed to multiplier
            if '/' in effect_speed:
                num, denom = map(int, effect_speed.split('/'))
                speed_multiplier = num / denom
            else:
                speed_multiplier = float(effect_speed)

            # Get BPM at block start time
            if hasattr(self.timeline_widget, 'song_structure') and self.timeline_widget.song_structure:
                part_at_block = self.timeline_widget.song_structure.get_part_at_time(sublane_block.start_time)
                if part_at_block:
                    bpm = part_at_block.bpm
                    # Parse time signature
                    numerator, denominator = map(int, part_at_block.signature.split('/'))
                    beats_per_bar = (numerator * 4) / denominator
                else:
                    bpm = 120
                    beats_per_bar = 4.0
            else:
                bpm = 120
                beats_per_bar = 4.0

            # Calculate time per step (in seconds)
            seconds_per_beat = 60.0 / bpm
            seconds_per_step = seconds_per_beat / speed_multiplier

            # Calculate block duration
            block_duration = sublane_block.end_time - sublane_block.start_time

            # Calculate number of steps
            num_steps = int(block_duration / seconds_per_step)

            # Draw beat grid lines (faint brand neutral, readable on the
            # group-color tint over the dark surface)
            grid_pen = QPen(token_qcolor("text_disabled", 150), 1, Qt.PenStyle.DotLine)
            painter.setPen(grid_pen)

            for step in range(1, num_steps):  # Skip first (start) and last (end)
                step_time = sublane_block.start_time + (step * seconds_per_step)
                step_pixel = self.timeline_widget.time_to_pixel(step_time)
                envelope_start_pixel = self.timeline_widget.time_to_pixel(self.block.start_time)

                x = step_pixel - envelope_start_pixel

                # Draw vertical line
                painter.drawLine(
                    int(x),
                    int(y_offset + margin),
                    int(x),
                    int(y_offset + sublane_height - margin)
                )
        except Exception as e:
            # Silently fail if grid cannot be drawn
            pass

    def _draw_movement_block_grid(self, painter, sublane_block, x_offset, y_offset, width, sublane_height, margin):
        """Draw beat grid lines inside movement block based on speed setting."""
        try:
            # Get speed setting (movement blocks now have effect_speed like dimmer blocks)
            effect_speed = getattr(sublane_block, 'effect_speed', '1')

            # Convert speed to multiplier
            if '/' in effect_speed:
                num, denom = map(int, effect_speed.split('/'))
                speed_multiplier = num / denom
            else:
                speed_multiplier = float(effect_speed)

            # Get BPM at block start time
            if hasattr(self.timeline_widget, 'song_structure') and self.timeline_widget.song_structure:
                part_at_block = self.timeline_widget.song_structure.get_part_at_time(sublane_block.start_time)
                if part_at_block:
                    bpm = part_at_block.bpm
                    # Parse time signature
                    numerator, denominator = map(int, part_at_block.signature.split('/'))
                    beats_per_bar = (numerator * 4) / denominator
                else:
                    bpm = 120
                    beats_per_bar = 4.0
            else:
                bpm = 120
                beats_per_bar = 4.0

            # Calculate time per step (in seconds)
            seconds_per_beat = 60.0 / bpm
            seconds_per_step = seconds_per_beat / speed_multiplier

            # Calculate block duration
            block_duration = sublane_block.end_time - sublane_block.start_time

            # Calculate number of steps
            num_steps = int(block_duration / seconds_per_step)

            # Draw beat grid lines (faint brand neutral, matches dimmer)
            grid_pen = QPen(token_qcolor("text_disabled", 150), 1, Qt.PenStyle.DotLine)
            painter.setPen(grid_pen)

            for step in range(1, num_steps):  # Skip first (start) and last (end)
                step_time = sublane_block.start_time + (step * seconds_per_step)
                step_pixel = self.timeline_widget.time_to_pixel(step_time)
                envelope_start_pixel = self.timeline_widget.time_to_pixel(self.block.start_time)

                x = step_pixel - envelope_start_pixel

                # Draw vertical line
                painter.drawLine(
                    int(x),
                    int(y_offset + margin),
                    int(x),
                    int(y_offset + sublane_height - margin)
                )
        except Exception as e:
            # Silently fail if grid cannot be drawn
            pass

    def _get_sublane_block_info(self, sublane_block, sublane_type):
        """Get short info text about sublane block content."""
        try:
            if sublane_type == "dimmer":
                # Show effect type and intensity
                intensity = int(sublane_block.intensity)
                effect_type = getattr(sublane_block, 'effect_type', 'static')
                # Capitalize first letter of effect type
                effect_display = effect_type.capitalize()
                return f"{effect_display} ({intensity})"
            elif sublane_type == "colour":
                # Show actual color name or hex value
                r = int(getattr(sublane_block, 'red', 0))
                g = int(getattr(sublane_block, 'green', 0))
                b = int(getattr(sublane_block, 'blue', 0))
                w = int(getattr(sublane_block, 'white', 0))

                # Check for common color names
                color_name = self._get_color_name(r, g, b, w)
                if color_name:
                    return color_name

                # Fall back to hex code
                return f"#{r:02X}{g:02X}{b:02X}"
            elif sublane_type == "movement":
                # Show effect type (and pan/tilt for static)
                effect_type = getattr(sublane_block, 'effect_type', 'static')
                effect_display = effect_type.replace('_', ' ').title()
                if effect_type == "static" and hasattr(sublane_block, 'pan') and hasattr(sublane_block, 'tilt'):
                    pan = int(sublane_block.pan)
                    tilt = int(sublane_block.tilt)
                    return f"P{pan}/T{tilt}"
                return effect_display
            elif sublane_type == "special":
                # Show if any special effects are active
                active_effects = []
                if hasattr(sublane_block, 'gobo') and sublane_block.gobo:
                    active_effects.append("Gobo")
                if hasattr(sublane_block, 'prism') and sublane_block.prism:
                    active_effects.append("Prism")
                if active_effects:
                    return active_effects[0]  # Show first effect
                return "FX"
        except Exception:
            pass
        return ""

    def _get_color_name(self, r: int, g: int, b: int, w: int) -> str:
        """Get a human-readable color name for common colors.

        Args:
            r, g, b: RGB values (0-255)
            w: White value (0-255)

        Returns:
            Color name string, or empty string if no match
        """
        # Tolerance for color matching
        tolerance = 30

        def close_to(val, target):
            return abs(val - target) <= tolerance

        # Check for white (either via W channel or RGB)
        if w > 200 and r < tolerance and g < tolerance and b < tolerance:
            return "White"
        if close_to(r, 255) and close_to(g, 255) and close_to(b, 255):
            return "White"

        # Check for black/off
        if r < tolerance and g < tolerance and b < tolerance and w < tolerance:
            return "Off"

        # Check for primary colors
        if close_to(r, 255) and g < tolerance and b < tolerance:
            return "Red"
        if r < tolerance and close_to(g, 255) and b < tolerance:
            return "Green"
        if r < tolerance and g < tolerance and close_to(b, 255):
            return "Blue"

        # Check for secondary colors
        if close_to(r, 255) and close_to(g, 255) and b < tolerance:
            return "Yellow"
        if close_to(r, 255) and g < tolerance and close_to(b, 255):
            return "Magenta"
        if r < tolerance and close_to(g, 255) and close_to(b, 255):
            return "Cyan"

        # Check for other common colors
        if close_to(r, 255) and close_to(g, 165) and b < tolerance:
            return "Orange"
        if close_to(r, 255) and close_to(g, 100) and b < tolerance:
            return "Amber"
        if close_to(r, 128) and g < tolerance and close_to(b, 128):
            return "Purple"
        if close_to(r, 255) and close_to(g, 105) and close_to(b, 180):
            return "Pink"
        if close_to(r, 180) and close_to(g, 255) and b < tolerance:
            return "Lime"

        # No match found
        return ""

    def _draw_resize_handles(self, painter):
        """Draw resize handles on the envelope edges."""
        handle_color = token_qcolor("text", 100)
        painter.setBrush(QBrush(handle_color))
        painter.setPen(Qt.PenStyle.NoPen)

        # Left handle
        painter.drawRect(0, 0, 3, self.height())
        # Right handle
        painter.drawRect(self.width() - 3, 0, 3, self.height())

    def _draw_create_preview(self, painter):
        """Draw preview of block being created."""
        sublane_height = self.lane_widget.sublane_height

        # Get sublane row index
        sublane_index = self.lane_widget.get_sublane_index(self.creating_sublane)
        y_offset = sublane_index * sublane_height

        # Calculate x position and width
        start_pixel = self.timeline_widget.time_to_pixel(self.create_start_time)
        end_pixel = self.timeline_widget.time_to_pixel(self.create_end_time)
        envelope_start_pixel = self.timeline_widget.time_to_pixel(self.block.start_time)

        x_offset = start_pixel - envelope_start_pixel
        width = end_pixel - start_pixel

        # Preview tint from the group data color; the destructive token
        # flags an invalid (overlapping) placement.
        if self.overlap_detected:
            color = token_qcolor("destructive", 150)  # overlap warning
            border_color = token_qcolor("destructive", 220)
        else:
            color = _tinted(self._group_base_color(), 120)
            border_color = token_qcolor("text", 150)

        # Draw preview block
        painter.setBrush(QBrush(color))
        painter.setPen(QPen(border_color, 2, Qt.PenStyle.DashLine))

        margin = 2
        painter.drawRect(
            int(x_offset + margin),
            int(y_offset + margin),
            int(width - 2 * margin),
            int(sublane_height - 2 * margin),
        )

    def _get_colour_block_color(self, colour_block):
        """Get display color for colour block based on its RGBW values.

        Args:
            colour_block: The ColourBlock instance to get color from

        Returns:
            QColor for display
        """
        if not colour_block:
            return self._group_base_color()  # No content: read in group color

        r = int(colour_block.red)
        g = int(colour_block.green)
        b = int(colour_block.blue)
        w = int(getattr(colour_block, 'white', 0))

        # Blend white channel into RGB for display (same as preview logic)
        if w > 0:
            factor = w / 255.0
            r = min(255, int(r + (255 - r) * factor))
            g = min(255, int(g + (255 - g) * factor))
            b = min(255, int(b + (255 - b) * factor))

        # Use blended RGB values if any color is present
        if r > 0 or g > 0 or b > 0:
            return QColor(r, g, b)

        # No color set: read in the group data color, not an arbitrary hue
        return self._group_base_color()

    def _get_sublane_row_at_y(self, y_pos):
        """Detect which sublane row a Y position is in.

        Args:
            y_pos: Y coordinate relative to widget

        Returns:
            Sublane type string ("dimmer", "colour", "movement", "special") or None
        """
        sublane_height = self.lane_widget.sublane_height

        # Check each sublane row based on capabilities
        sublane_types = []
        # Show dimmer sublane if has dimmer OR colour (dimmer controls RGB for no-dimmer fixtures)
        if self.lane_widget.capabilities.has_dimmer or self.lane_widget.capabilities.has_colour:
            sublane_types.append("dimmer")
        if self.lane_widget.capabilities.has_colour:
            sublane_types.append("colour")
        if self.lane_widget.capabilities.has_movement:
            sublane_types.append("movement")
        if self.lane_widget.capabilities.has_special:
            sublane_types.append("special")

        for i, sublane_type in enumerate(sublane_types):
            y_min = i * sublane_height
            y_max = (i + 1) * sublane_height
            if y_min <= y_pos < y_max:
                return sublane_type

        return None

    def _get_sublane_block_at_pos(self, pos):
        """Detect which sublane block (if any) contains the given position.

        Args:
            pos: QPoint position relative to widget

        Returns:
            Tuple of (sublane_type, sublane_block) or (None, None)
        """
        sublane_height = self.lane_widget.sublane_height

        # Build list of sublane types based on fixture capabilities
        # This must match the rendering logic exactly
        sublane_block_lists = []
        caps = self.lane_widget.capabilities

        # Show dimmer sublane if has dimmer OR colour (dimmer controls RGB for no-dimmer fixtures)
        if caps.has_dimmer or caps.has_colour:
            sublane_block_lists.append(("dimmer", self.block.dimmer_blocks))
        if caps.has_colour:
            sublane_block_lists.append(("colour", self.block.colour_blocks))
        if caps.has_movement:
            sublane_block_lists.append(("movement", self.block.movement_blocks))
        if caps.has_special:
            sublane_block_lists.append(("special", self.block.special_blocks))

        for sublane_type, sublane_blocks in sublane_block_lists:
            # Get sublane row index
            sublane_index = self.lane_widget.get_sublane_index(sublane_type)

            # Calculate y bounds for this sublane row
            y_min = sublane_index * sublane_height
            y_max = (sublane_index + 1) * sublane_height

            # Check if Y position is in this sublane row
            if not (y_min <= pos.y() <= y_max):
                continue

            # Two-pass hit test: first try strict bounds (cheaper, preferred when
            # multiple narrow blocks sit close together), then fall back to a
            # buffered test so tiny blocks below the buffer width remain clickable.
            strict_match = None
            buffered_match = None
            for sublane_block in sublane_blocks:
                # Calculate x bounds relative to envelope
                block_start_pixel = self.timeline_widget.time_to_pixel(sublane_block.start_time)
                block_end_pixel = self.timeline_widget.time_to_pixel(sublane_block.end_time)
                envelope_start_pixel = self.timeline_widget.time_to_pixel(self.block.start_time)

                x_min = block_start_pixel - envelope_start_pixel
                x_max = block_end_pixel - envelope_start_pixel

                if x_min <= pos.x() <= x_max:
                    strict_match = (sublane_type, sublane_block)
                    break

                if (x_min - self.SUBLANE_HIT_BUFFER) <= pos.x() <= (x_max + self.SUBLANE_HIT_BUFFER):
                    if buffered_match is None:
                        buffered_match = (sublane_type, sublane_block)

            if strict_match is not None:
                return strict_match
            if buffered_match is not None:
                return buffered_match

        return (None, None)

    def _is_on_intensity_handle(self, pos, sublane_type, sublane_block):
        """Check if position is on the intensity handle of a dimmer block.

        Args:
            pos: QPoint position relative to widget
            sublane_type: Type of sublane
            sublane_block: The sublane block object

        Returns:
            True if on intensity handle, False otherwise
        """
        if sublane_type != "dimmer":
            return False

        try:
            sublane_height = self.lane_widget.sublane_height
            margin = 2

            # Get sublane row index
            sublane_index = self.lane_widget.get_sublane_index(sublane_type)
            y_offset = sublane_index * sublane_height

            # Calculate handle Y position
            intensity = getattr(sublane_block, 'intensity', 255.0)
            usable_height = sublane_height - 2 * margin
            intensity_ratio = intensity / 255.0
            handle_y_offset = y_offset + margin + (usable_height * (1.0 - intensity_ratio))

            # Check if Y position is near the handle (within 8 pixels)
            handle_tolerance = 8
            if abs(pos.y() - handle_y_offset) <= handle_tolerance:
                # Also check X position is within block bounds
                block_start_pixel = self.timeline_widget.time_to_pixel(sublane_block.start_time)
                block_end_pixel = self.timeline_widget.time_to_pixel(sublane_block.end_time)
                envelope_start_pixel = self.timeline_widget.time_to_pixel(self.block.start_time)

                x_min = block_start_pixel - envelope_start_pixel
                x_max = block_end_pixel - envelope_start_pixel

                if x_min <= pos.x() <= x_max:
                    return True

        except Exception:
            pass

        return False

    def _is_on_sublane_block_edge(self, pos, sublane_type, sublane_block):
        """Check if position is on the left or right edge of a sublane block.

        Args:
            pos: QPoint position relative to widget
            sublane_type: Type of sublane ("dimmer", "colour", etc.)
            sublane_block: The sublane block object

        Returns:
            'left', 'right', or None
        """
        # Calculate x bounds relative to envelope
        block_start_pixel = self.timeline_widget.time_to_pixel(sublane_block.start_time)
        block_end_pixel = self.timeline_widget.time_to_pixel(sublane_block.end_time)
        envelope_start_pixel = self.timeline_widget.time_to_pixel(self.block.start_time)

        x_min = block_start_pixel - envelope_start_pixel
        x_max = block_end_pixel - envelope_start_pixel

        # Check edges (8 pixel handle width)
        if abs(pos.x() - x_min) <= self.RESIZE_HANDLE_WIDTH:
            return 'left'
        elif abs(pos.x() - x_max) <= self.RESIZE_HANDLE_WIDTH:
            return 'right'

        return None

    def _get_block_color(self) -> QColor:
        """Get color for block based on effect or parameters.

        Falls back to the lane's group data color (or a brand neutral)
        rather than a Material per-effect palette.
        """
        # Use color from parameters if set
        if self.block.parameters.get('color'):
            return QColor(self.block.parameters['color'])
        return self._group_base_color()

    def mousePressEvent(self, event: QMouseEvent):
        """Handle mouse press for dragging/resizing envelope or sublane blocks."""
        if event.button() == Qt.MouseButton.RightButton:
            # Track press position. If the user drags, mouseMoveEvent activates
            # a marquee for sublane blocks. A plain right-click (no drag) falls
            # through to the existing contextMenuEvent.
            self._sublane_marquee_pending = True
            self._sublane_marquee_start = event.pos()
            self._sublane_marquee_current = event.pos()
            return

        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.pos()

            # Check if Shift is held for copy operation
            shift_held = event.modifiers() & Qt.KeyboardModifier.ShiftModifier

            # FIRST: Check for intensity handle click (takes priority over header zone)
            # This allows adjusting dimmer intensity even when the handle is in the header area
            sublane_type, sublane_block = self._get_sublane_block_at_pos(pos)
            if sublane_block is not None and self._is_on_intensity_handle(pos, sublane_type, sublane_block):
                # Clicking on intensity handle - start intensity drag
                self.selected_sublane_type = sublane_type
                self.selected_sublane_block = sublane_block
                self.dragging_intensity_handle = sublane_block
                self.drag_start_pos = event.globalPosition().toPoint()
                self.update()
                return

            # Check if clicking in header zone (top area) - drags entire envelope
            if pos.y() < self.HEADER_HEIGHT:
                # Deselect any sublane block
                self.selected_sublane_type = None
                self.selected_sublane_block = None
                self.update()

                # Header zone always moves entire effect (no resize from here)
                self.dragging = True
                if shift_held:
                    self.shift_drag_copying = True

                self.drag_start_pos = event.globalPosition().toPoint()
                self.drag_start_time = self.block.start_time
                self.drag_start_duration = self.block.end_time - self.block.start_time
                return

            # Below header: handle sublane block interactions
            # (sublane_type and sublane_block already retrieved above)

            if sublane_block is not None:
                # Clicked on a sublane block - select it.
                self.clicked_sublane_type = sublane_type
                self.selected_sublane_type = sublane_type
                self.selected_sublane_block = sublane_block  # Store block reference
                self.update()  # Trigger repaint to show selection

                # Store initial sublane times for resizing
                self.drag_start_sublane_start = sublane_block.start_time
                self.drag_start_sublane_end = sublane_block.end_time

                # Check if clicking on edge for resizing
                # (intensity handle is already checked at the top of this function)
                if self._is_on_sublane_block_edge(pos, sublane_type, sublane_block):
                    # Start resizing sublane block.
                    self.resizing_sublane = sublane_block
                    edge = self._is_on_sublane_block_edge(pos, sublane_type, sublane_block)
                    self.resizing_sublane_edge = edge
                else:
                    # Clicked on sublane block body - enable dragging.
                    self.dragging_sublane = sublane_block

            else:
                # Clicked on envelope background - deselect any sublane
                self.selected_sublane_type = None
                self.selected_sublane_block = None
                self.update()  # Trigger repaint

                # Check if clicking within a sublane row (for drag-to-create)
                sublane_row = self._get_sublane_row_at_y(pos.y())

                if sublane_row:
                    # Clicking in a sublane row - start drag-to-create
                    self.creating_sublane = sublane_row
                    # Convert click position to time
                    click_time = self.pixel_to_time(pos.x())
                    if self.snap_to_grid:
                        click_time = self.timeline_widget.find_nearest_beat_time(click_time)
                    self.create_start_time = click_time
                    self.create_end_time = click_time  # Will be updated in mouseMoveEvent
                else:
                    # Not in a sublane row - check envelope resize handles
                    x = pos.x()

                    if x <= self.RESIZE_HANDLE_WIDTH:
                        self.resizing_left = True
                    elif x >= self.width() - self.RESIZE_HANDLE_WIDTH:
                        self.resizing_right = True
                    else:
                        self.dragging = True
                        # Check if shift is held for copy operation
                        if shift_held:
                            self.shift_drag_copying = True

            self.drag_start_pos = event.globalPosition().toPoint()
            self.drag_start_time = self.block.start_time
            self.drag_start_duration = self.block.end_time - self.block.start_time

    def mouseMoveEvent(self, event: QMouseEvent):
        """Handle mouse move for dragging/resizing."""
        # Right-button drag: start or continue the sublane marquee.
        if (self._sublane_marquee_pending or self._sublane_marquee_active) and \
                (event.buttons() & Qt.MouseButton.RightButton):
            pos = event.pos()
            if self._sublane_marquee_pending:
                if (pos - self._sublane_marquee_start).manhattanLength() >= self.MARQUEE_DRAG_THRESHOLD:
                    self._sublane_marquee_pending = False
                    self._sublane_marquee_active = True
            if self._sublane_marquee_active:
                self._sublane_marquee_current = pos
                self.update()
            return

        if not (self.dragging or self.resizing_left or self.resizing_right or self.resizing_sublane or self.dragging_sublane or self.creating_sublane or self.dragging_intensity_handle):
            # Update cursor based on position
            pos = event.pos()

            # FIRST: Check for intensity handle (takes priority over header zone)
            sublane_type, sublane_block = self._get_sublane_block_at_pos(pos)
            if sublane_block and self._is_on_intensity_handle(pos, sublane_type, sublane_block):
                # On intensity handle - show vertical resize cursor
                self.setCursor(Qt.CursorShape.SizeVerCursor)
                return

            # Check if hovering over header zone (drag handle for entire effect)
            if pos.y() < self.HEADER_HEIGHT:
                # Show move cursor in header zone (unless on intensity handle, checked above)
                self.setCursor(Qt.CursorShape.SizeAllCursor)
                return

            # Check if hovering over a sublane block
            if sublane_block:
                # Check if hovering over edge
                edge = self._is_on_sublane_block_edge(pos, sublane_type, sublane_block)
                if edge:
                    # On sublane edge - show resize cursor
                    self.setCursor(Qt.CursorShape.SizeHorCursor)
                    return

            # Check envelope edges
            x = pos.x()
            if x <= self.RESIZE_HANDLE_WIDTH or x >= self.width() - self.RESIZE_HANDLE_WIDTH:
                self.setCursor(Qt.CursorShape.SizeHorCursor)
            else:
                self.setCursor(Qt.CursorShape.PointingHandCursor)
            return

        current_pos = event.globalPosition().toPoint()
        delta_pixels = current_pos.x() - self.drag_start_pos.x()
        delta_time = delta_pixels / self.timeline_widget.pixels_per_second

        if self.dragging:
            # Move the block
            new_time = max(0.0, self.drag_start_time + delta_time)

            if self.snap_to_grid:
                new_time = self.timeline_widget.find_nearest_beat_time(new_time)

            # Calculate actual delta to apply to sublane blocks
            actual_delta = new_time - self.block.start_time

            # Move entire effect (envelope + all sublane blocks) by the same delta
            if actual_delta != 0:
                # Move envelope
                self.block.end_time += actual_delta

                # Move all sublane blocks
                for sublane_block in self.block.dimmer_blocks:
                    sublane_block.start_time += actual_delta
                    sublane_block.end_time += actual_delta
                for sublane_block in self.block.colour_blocks:
                    sublane_block.start_time += actual_delta
                    sublane_block.end_time += actual_delta
                for sublane_block in self.block.movement_blocks:
                    sublane_block.start_time += actual_delta
                    sublane_block.end_time += actual_delta
                for sublane_block in self.block.special_blocks:
                    sublane_block.start_time += actual_delta
                    sublane_block.end_time += actual_delta

            self.block.start_time = new_time
            self.update_position()
            self.position_changed.emit(self, new_time)

        elif self.resizing_left:
            # Resize from left edge (changes start time and duration)
            new_start = self.drag_start_time + delta_time
            new_duration = self.drag_start_duration - delta_time

            if self.snap_to_grid:
                new_start = self.timeline_widget.find_nearest_beat_time(new_start)
                new_duration = (self.drag_start_time + self.drag_start_duration) - new_start

            if new_start >= 0 and new_duration >= 0.1:
                self.block.start_time = new_start
                self.block.duration = new_duration
                self.update_position()
                self.position_changed.emit(self, new_start)
                self.duration_changed.emit(self, new_duration)

        elif self.resizing_right:
            # Resize from right edge (changes duration only)
            new_duration = self.drag_start_duration + delta_time

            if self.snap_to_grid:
                new_end = self.block.start_time + new_duration
                new_end = self.timeline_widget.find_nearest_beat_time(new_end)
                new_duration = new_end - self.block.start_time

            if new_duration >= 0.1:
                self.block.duration = new_duration
                self.update_position()
                self.duration_changed.emit(self, new_duration)

        elif self.resizing_sublane:
            # Resize sublane block.
            sublane_block = self.resizing_sublane

            if self.resizing_sublane_edge == 'left':
                # Resize from left edge (changes start time)
                new_start = self.drag_start_sublane_start + delta_time

                if self.snap_to_grid:
                    new_start = self.timeline_widget.find_nearest_beat_time(new_start)

                # Don't allow shrinking below minimum duration
                if new_start >= 0 and (self.drag_start_sublane_end - new_start) >= 0.1:
                    sublane_block.start_time = new_start
                    # Update envelope bounds
                    self.block.update_envelope_bounds()
                    self.block.modified = True
                    self.update_position()
                    self.update()  # Redraw

            elif self.resizing_sublane_edge == 'right':
                # Resize from right edge (changes end time)
                new_end = self.drag_start_sublane_end + delta_time

                if self.snap_to_grid:
                    new_end = self.timeline_widget.find_nearest_beat_time(new_end)

                # Don't allow shrinking below minimum duration
                if (new_end - self.drag_start_sublane_start) >= 0.1:
                    sublane_block.end_time = new_end
                    # Update envelope bounds
                    self.block.update_envelope_bounds()
                    self.block.modified = True
                    self.update_position()
                    self.update()  # Redraw

        elif self.dragging_sublane:
            # Drag sublane block.
            sublane_block = self.dragging_sublane

            # Calculate new start time
            new_start = self.drag_start_sublane_start + delta_time

            if self.snap_to_grid:
                new_start = self.timeline_widget.find_nearest_beat_time(new_start)

            # Calculate duration and new end time
            duration = self.drag_start_sublane_end - self.drag_start_sublane_start
            new_end = new_start + duration

            # Don't allow negative start time
            if new_start >= 0:
                sublane_block.start_time = new_start
                sublane_block.end_time = new_end
                # Update envelope bounds
                self.block.update_envelope_bounds()
                self.block.modified = True
                self.update_position()
                self.update()  # Redraw

        elif self.creating_sublane:
            # Update end time for block being created
            pos = event.pos()
            current_time = self.pixel_to_time(pos.x())

            if self.snap_to_grid:
                current_time = self.timeline_widget.find_nearest_beat_time(current_time)

            self.create_end_time = max(current_time, self.create_start_time + 0.1)  # Minimum duration

            # Check for overlap in Movement/Special sublanes
            if self.creating_sublane in ["movement", "special"]:
                self.overlap_detected = self._check_overlap(
                    self.creating_sublane,
                    self.create_start_time,
                    self.create_end_time
                )
            else:
                self.overlap_detected = False

            self.update()  # Redraw to show preview

        elif self.dragging_intensity_handle:
            # Drag intensity handle vertically
            pos = event.pos()

            # Get sublane info
            sublane_type = "dimmer"  # Intensity handle only for dimmer blocks
            sublane_height = self.lane_widget.sublane_height
            margin = 2

            # Get sublane row index
            sublane_index = self.lane_widget.get_sublane_index(sublane_type)
            y_offset = sublane_index * sublane_height

            # Calculate new intensity from Y position
            usable_height = sublane_height - 2 * margin
            # Y position relative to sublane top
            y_in_sublane = pos.y() - (y_offset + margin)

            # Clamp to usable height
            y_in_sublane = max(0, min(y_in_sublane, usable_height))

            # Convert to intensity (inverted: top=255, bottom=0)
            intensity_ratio = 1.0 - (y_in_sublane / usable_height)
            new_intensity = intensity_ratio * 255.0

            # Clamp intensity
            new_intensity = max(0.0, min(255.0, new_intensity))

            # Update intensity
            self.dragging_intensity_handle.intensity = new_intensity

            # Mark block as modified
            self.block.modified = True

            # Redraw to update handle position and label
            self.update()

    def _get_sublane_blocks_by_type(self, sublane_type):
        """Get list of sublane block objects by type.

        Returns:
            List of blocks for the given sublane type, or empty list if not found.
        """
        if sublane_type == "dimmer":
            return self.block.dimmer_blocks
        elif sublane_type == "colour":
            return self.block.colour_blocks
        elif sublane_type == "movement":
            return self.block.movement_blocks
        elif sublane_type == "special":
            return self.block.special_blocks
        return []

    def _check_overlap(self, sublane_type, start_time, end_time, exclude_block=None):
        """Check if a time range would overlap with existing blocks in a sublane.

        Args:
            sublane_type: Type of sublane to check
            start_time: Proposed start time
            end_time: Proposed end time
            exclude_block: Block to exclude from overlap check (when resizing/moving existing block)

        Returns:
            True if overlap detected, False otherwise
        """
        # Get the list of blocks for this sublane type
        if sublane_type == "dimmer":
            blocks = self.block.dimmer_blocks
        elif sublane_type == "colour":
            blocks = self.block.colour_blocks
        elif sublane_type == "movement":
            blocks = self.block.movement_blocks
        elif sublane_type == "special":
            blocks = self.block.special_blocks
        else:
            return False

        # Check for overlaps with existing blocks
        for existing_block in blocks:
            if existing_block is exclude_block:
                continue  # Skip the block we're currently editing

            # Two ranges overlap if: start1 < end2 AND start2 < end1
            if start_time < existing_block.end_time and existing_block.start_time < end_time:
                return True  # Overlap detected

        return False

    def _create_sublane_block(self, sublane_type, start_time, end_time):
        """Create a new sublane block of the specified type.

        Args:
            sublane_type: Type of sublane ("dimmer", "colour", "movement", "special")
            start_time: Start time for the block
            end_time: End time for the block
        """
        from config.models import DimmerBlock, ColourBlock, MovementBlock, SpecialBlock

        # Reject mouse-slip-tiny blocks that would be near-impossible to grab afterward.
        if (end_time - start_time) < self.MIN_SUBLANE_BLOCK_DURATION:
            return

        # Check for overlaps in Movement/Special sublanes (prevent conflicts)
        if sublane_type in ["movement", "special"]:
            if self._check_overlap(sublane_type, start_time, end_time):
                print(f"Warning: Cannot create {sublane_type} block - overlaps with existing block")
                return  # Abort creation

        # Create the appropriate sublane block and append to its list.
        if sublane_type == "dimmer":
            new_block = DimmerBlock(
                start_time=start_time,
                end_time=end_time,
                intensity=255.0
            )
            self.block.dimmer_blocks.append(new_block)
        elif sublane_type == "colour":
            new_block = ColourBlock(
                start_time=start_time,
                end_time=end_time,
                color_mode="RGB",
                red=255.0,
                green=255.0,
                blue=255.0
            )
            self.block.colour_blocks.append(new_block)
        elif sublane_type == "movement":
            new_block = MovementBlock(
                start_time=start_time,
                end_time=end_time,
                pan=127.5,
                tilt=127.5
            )
            self.block.movement_blocks.append(new_block)
        elif sublane_type == "special":
            new_block = SpecialBlock(
                start_time=start_time,
                end_time=end_time
            )
            self.block.special_blocks.append(new_block)

        # Update envelope bounds and mark as modified
        self.block.update_envelope_bounds()
        self.block.modified = True
        self.update_position()
        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent):
        """Handle mouse release to stop dragging/resizing."""
        if event.button() == Qt.MouseButton.RightButton:
            if self._sublane_marquee_active:
                # Drag-marquee was active. Find sublane blocks inside the rect
                # and offer a bulk-delete menu. Suppress the native context menu
                # that would otherwise fire on right-button release.
                rect = self._compute_sublane_marquee_rect()
                hits = self._sublane_blocks_in_rect(rect)
                self._sublane_marquee_active = False
                self._suppress_next_context_menu = True
                self.update()  # Clear the marquee rendering
                self._show_sublane_marquee_menu(event.globalPosition().toPoint(), hits)
                return
            # No drag — clear pending state and let contextMenuEvent fire.
            self._sublane_marquee_pending = False
            return

        if event.button() == Qt.MouseButton.LeftButton:
            # Handle shift+drag copy completion
            if self.shift_drag_copying and self.dragging:
                # Create a copy of the effect at the new position
                new_start_time = self.block.start_time  # Current position after drag
                # Reset original block to its starting position
                self.block.start_time = self.drag_start_time
                self.block.end_time = self.drag_start_time + self.drag_start_duration
                # Update sublane blocks back to original times
                self._restore_sublane_times()
                self.update_position()

                # Create copy at new position via lane widget
                if hasattr(self.lane_widget, 'paste_effect_at_time'):
                    from .effect_clipboard import copy_effect, paste_effect
                    copy_effect(self.block)
                    self.lane_widget.paste_effect_at_time(new_start_time)

                self.shift_drag_copying = False

            # Handle drag-to-create completion
            if self.creating_sublane and self.create_start_time is not None and self.create_end_time is not None:
                # Only create if no overlap (overlap_detected flag is set during mouseMoveEvent)
                if not self.overlap_detected:
                    # Create the new sublane block
                    self._create_sublane_block(self.creating_sublane, self.create_start_time, self.create_end_time)
                # Clear creation state
                self.creating_sublane = None
                self.create_start_time = None
                self.create_end_time = None
                self.overlap_detected = False
                self.update()

            self.dragging = False
            self.resizing_left = False
            self.resizing_right = False
            self.drag_start_pos = None

            # Clear sublane interaction state
            self.clicked_sublane_type = None
            self.resizing_sublane = None
            self.resizing_sublane_edge = None
            self.dragging_sublane = None
            self.dragging_intensity_handle = None
            # Note: We keep self.selected_sublane_block so the selection persists after release

    def mouseDoubleClickEvent(self, event: QMouseEvent):
        """Handle double-click to open effect editor or sublane block editor."""
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position().toPoint()
            sublane_type, sublane_block = self._get_sublane_block_at_pos(pos)

            if sublane_block is not None:
                # Double-clicked on a sublane block - open sublane-specific dialog
                self.open_sublane_dialog(sublane_type, sublane_block)
            else:
                # Double-clicked on envelope - open rename dialog
                self.set_block_name()

    def contextMenuEvent(self, event):
        """Handle right-click context menu."""
        # Suppressed once after a marquee release — the marquee shows its own menu.
        if self._suppress_next_context_menu:
            self._suppress_next_context_menu = False
            return

        from PyQt6.QtWidgets import QMenu
        menu = QMenu(self)

        # Check if right-clicked on a sublane block
        pos = self.mapFromGlobal(event.globalPos())
        sublane_type, sublane_block = self._get_sublane_block_at_pos(pos)

        if sublane_block is not None:
            # Sublane block context menu
            sublane_labels = {
                "dimmer": "Dimmer",
                "colour": "Colour",
                "movement": "Movement",
                "special": "Special"
            }
            label = sublane_labels.get(sublane_type, sublane_type.capitalize())

            edit_sublane_action = menu.addAction(f"Edit {label} Block...")
            edit_sublane_action.triggered.connect(
                lambda: self.open_sublane_dialog(sublane_type, sublane_block)
            )

            delete_sublane_action = menu.addAction(f"Delete {label} Block")
            delete_sublane_action.triggered.connect(
                lambda: self._delete_sublane_block(sublane_type, sublane_block)
            )

            menu.addSeparator()

        set_name_action = menu.addAction("Set Name...")
        set_name_action.triggered.connect(self.set_block_name)

        menu.addSeparator()

        # Dynamic copy label based on selection count
        copy_label = "Copy Effect"
        if self._is_multi_selected:
            shows_tab = self._get_shows_tab()
            if shows_tab and hasattr(shows_tab, 'selection_manager'):
                count = shows_tab.selection_manager.get_selection_count()
                if count > 1:
                    copy_label = f"Copy {count} Effects"

        copy_action = menu.addAction(copy_label)
        copy_action.triggered.connect(self.copy_effect)

        menu.addSeparator()

        save_riff_action = menu.addAction("Save as Riff...")
        save_riff_action.triggered.connect(self.save_as_riff)

        menu.addSeparator()

        # Dynamic delete label based on selection count
        delete_label = "Delete Entire Effect"
        if self._is_multi_selected:
            shows_tab = self._get_shows_tab()
            if shows_tab and hasattr(shows_tab, 'selection_manager'):
                count = shows_tab.selection_manager.get_selection_count()
                if count > 1:
                    delete_label = f"Delete {count} Effects"

        delete_action = menu.addAction(delete_label)
        delete_action.triggered.connect(self._delete_effect_or_selection)

        menu.exec(event.globalPos())

    def save_as_riff(self):
        """Save this light block as a reusable riff."""
        from .save_riff_dialog import SaveRiffDialog

        # Get riff library from main window
        main_window = self.window()
        riff_library = getattr(main_window, 'riff_library', None)

        if not riff_library:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(
                self, "Error",
                "Riff library not available. Cannot save riff."
            )
            return

        # Get BPM at block start for beat conversion
        timeline_widget = self.parent()
        song_structure = getattr(timeline_widget, 'song_structure', None)
        if song_structure and hasattr(song_structure, 'get_bpm_at_time'):
            bpm = song_structure.get_bpm_at_time(self.block.start_time)
        else:
            bpm = getattr(timeline_widget, 'bpm', 120.0)

        # Show save dialog
        dialog = SaveRiffDialog(self.block, bpm, riff_library, parent=self)
        dialog.exec()

    def set_block_name(self):
        """Set or change the custom name for this effect block."""
        from PyQt6.QtWidgets import QInputDialog

        # Get current name (or empty string if None)
        current_name = self.block.name if self.block.name else ""

        # Show input dialog
        name, ok = QInputDialog.getText(
            self,
            "Set Effect Name",
            "Enter name for this effect block:",
            text=current_name
        )

        if ok:
            # Set name (or None if empty)
            self.block.name = name if name.strip() else None
            self.update_display()
            self.block_edited.emit()  # Trigger auto-save

    def open_sublane_dialog(self, sublane_type: str, sublane_block):
        """Open the appropriate dialog for a sublane block.

        Args:
            sublane_type: Type of sublane ("dimmer", "colour", "movement", "special")
            sublane_block: The sublane block to edit
        """
        dialog = None

        if sublane_type == "dimmer":
            from .dimmer_block_dialog import DimmerBlockDialog
            dialog = DimmerBlockDialog(sublane_block, parent=self)
        elif sublane_type == "colour":
            from .colour_block_dialog import ColourBlockDialog
            # Get color wheel options from fixture if available
            color_wheel_options = self._get_color_wheel_options()
            dialog = ColourBlockDialog(sublane_block, color_wheel_options=color_wheel_options, parent=self)
        elif sublane_type == "movement":
            from .movement_block_dialog import MovementBlockDialog
            # Pass config for spot selection
            config = self.lane_widget.config if self.lane_widget else None
            dialog = MovementBlockDialog(sublane_block, parent=self, config=config)
        elif sublane_type == "special":
            from .special_block_dialog import SpecialBlockDialog
            dialog = SpecialBlockDialog(sublane_block, parent=self)

        if dialog and dialog.exec():
            # Mark effect as modified since sublane was changed
            self.block.modified = True
            self.update_display()
            self.block_edited.emit()  # Trigger auto-save

    def _get_color_wheel_options(self):
        """Get color wheel options from fixture group if available.

        Returns:
            List of (name, dmx_value, hex_color) tuples, or empty list
        """
        try:
            # Check if we have access to config through lane_widget
            if not self.lane_widget or not self.lane_widget.config:
                return []

            # Get fixture group
            group_name = self.lane_widget.lane.fixture_group
            if group_name not in self.lane_widget.config.groups:
                return []

            group = self.lane_widget.config.groups[group_name]

            # Get color wheel options from fixtures
            from utils.fixture_utils import get_color_wheel_options
            return get_color_wheel_options(group.fixtures)

        except Exception:
            # If anything goes wrong, just return empty list
            return []

    def _delete_sublane_block(self, sublane_type: str, sublane_block):
        """Delete a specific sublane block.

        Args:
            sublane_type: Type of sublane
            sublane_block: The block to delete
        """
        block_list = None
        if sublane_type == "dimmer":
            block_list = self.block.dimmer_blocks
        elif sublane_type == "colour":
            block_list = self.block.colour_blocks
        elif sublane_type == "movement":
            block_list = self.block.movement_blocks
        elif sublane_type == "special":
            block_list = self.block.special_blocks

        if block_list and sublane_block in block_list:
            block_list.remove(sublane_block)
            # Clear selection if deleted block was selected
            if self.selected_sublane_block == sublane_block:
                self.selected_sublane_block = None
                self.selected_sublane_type = None
            self.block.modified = True
            self.update_display()

    # ── Right-click sublane marquee helpers ───────────────────────────────

    def _compute_sublane_marquee_rect(self) -> QRect:
        """Return the marquee rectangle in widget-local coordinates, normalised."""
        x1 = min(self._sublane_marquee_start.x(), self._sublane_marquee_current.x())
        y1 = min(self._sublane_marquee_start.y(), self._sublane_marquee_current.y())
        x2 = max(self._sublane_marquee_start.x(), self._sublane_marquee_current.x())
        y2 = max(self._sublane_marquee_start.y(), self._sublane_marquee_current.y())
        return QRect(x1, y1, x2 - x1, y2 - y1)

    def _sublane_blocks_in_rect(self, rect: QRect):
        """Find all sublane blocks whose bounding box intersects the rect.

        Returns:
            List of (sublane_type, sublane_block) tuples.
        """
        sublane_height = self.lane_widget.sublane_height
        caps = self.lane_widget.capabilities

        sublane_lists = []
        if caps.has_dimmer or caps.has_colour:
            sublane_lists.append(("dimmer", self.block.dimmer_blocks))
        if caps.has_colour:
            sublane_lists.append(("colour", self.block.colour_blocks))
        if caps.has_movement:
            sublane_lists.append(("movement", self.block.movement_blocks))
        if caps.has_special:
            sublane_lists.append(("special", self.block.special_blocks))

        envelope_start_pixel = self.timeline_widget.time_to_pixel(self.block.start_time)
        results = []

        for sublane_type, sublane_blocks in sublane_lists:
            sublane_index = self.lane_widget.get_sublane_index(sublane_type)
            row_top = sublane_index * sublane_height
            row_bottom = row_top + sublane_height
            # Vertical overlap with marquee rect.
            if rect.bottom() < row_top or rect.top() > row_bottom:
                continue

            for sb in sublane_blocks:
                start_px = self.timeline_widget.time_to_pixel(sb.start_time) - envelope_start_pixel
                end_px = self.timeline_widget.time_to_pixel(sb.end_time) - envelope_start_pixel
                # Horizontal overlap with marquee rect.
                if end_px < rect.left() or start_px > rect.right():
                    continue
                results.append((sublane_type, sb))

        return results

    def _show_sublane_marquee_menu(self, global_pos: QPoint, hits):
        """Show the bulk-action menu after a sublane marquee finalises."""
        from PyQt6.QtWidgets import QMenu

        menu = QMenu(self)
        count = len(hits)
        if count == 0:
            empty = menu.addAction("No blocks in selection")
            empty.setEnabled(False)
        else:
            label = "Delete Block" if count == 1 else f"Delete {count} Blocks"
            delete = menu.addAction(label)
            delete.triggered.connect(lambda: self._bulk_delete_sublane_blocks(hits))
            menu.addSeparator()
            cancel = menu.addAction("Cancel")
            cancel.triggered.connect(lambda: None)
        menu.exec(global_pos)

    def _bulk_delete_sublane_blocks(self, hits):
        """Delete every (sublane_type, sublane_block) in the list."""
        for sublane_type, sb in hits:
            self._delete_sublane_block(sublane_type, sb)
        # Update envelope bounds in case deletions shrank the effect.
        self.block.update_envelope_bounds()
        self.update_position()
        self.update()
        self.block_edited.emit()

    def _restore_sublane_times(self):
        """Restore all sublane block times to match the original envelope position.

        Used when cancelling a shift+drag copy to reset the visual dragging.
        """
        # Calculate the time offset that was applied during dragging
        current_duration = self.block.end_time - self.block.start_time
        original_duration = self.drag_start_duration

        # The blocks were dragged with the envelope, so we need to restore them
        # to match the original start time
        time_delta = self.drag_start_time - self.block.start_time

        # Since we already reset self.block.start_time and end_time,
        # we need to adjust all sublane blocks to match
        for dimmer_block in self.block.dimmer_blocks:
            dimmer_block.start_time += time_delta
            dimmer_block.end_time += time_delta

        for colour_block in self.block.colour_blocks:
            colour_block.start_time += time_delta
            colour_block.end_time += time_delta

        for movement_block in self.block.movement_blocks:
            movement_block.start_time += time_delta
            movement_block.end_time += time_delta

        for special_block in self.block.special_blocks:
            special_block.start_time += time_delta
            special_block.end_time += time_delta

    def copy_effect(self):
        """Copy this effect (or all selected effects) to the clipboard."""
        from .effect_clipboard import copy_effect, copy_multiple_effects

        # Check if this block is part of a multi-selection
        if self._is_multi_selected:
            # Try to get selection manager from parent chain
            shows_tab = self._get_shows_tab()
            if shows_tab and hasattr(shows_tab, 'selection_manager'):
                selected_blocks = shows_tab.selection_manager.get_selected_blocks()
                if len(selected_blocks) > 1:
                    copy_multiple_effects(selected_blocks)
                    return

        # Fall back to single block copy
        copy_effect(self.block)

    def _get_shows_tab(self):
        """Get the ShowsTab parent widget if available."""
        if self.lane_widget:
            # Walk up the parent chain to find ShowsTab (has selection_manager)
            widget = self.lane_widget.parent()
            while widget is not None:
                if hasattr(widget, 'selection_manager'):
                    return widget
                widget = widget.parent()
        return None

    def _delete_effect_or_selection(self):
        """Delete this effect or all selected effects."""
        # Check if this block is part of a multi-selection
        if self._is_multi_selected:
            shows_tab = self._get_shows_tab()
            if shows_tab and hasattr(shows_tab, '_delete_selected_blocks'):
                shows_tab._delete_selected_blocks()
                return

        # Fall back to single block delete
        self.remove_requested.emit(self)

    def wheelEvent(self, event):
        """Handle mouse wheel for speed adjustment (Ctrl+wheel) on dimmer and movement blocks."""
        from PyQt6.QtCore import Qt

        # Check if Ctrl is pressed and a dimmer or movement block is selected
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            if self.selected_sublane_type in ["dimmer", "movement"] and self.selected_sublane_block:
                # Speed options in order
                speed_options = ["1/16", "1/8", "1/4", "1/2", "1", "2", "4", "8", "16"]

                # Get current speed
                current_speed = getattr(self.selected_sublane_block, 'effect_speed', '1')

                # Find current index
                try:
                    current_index = speed_options.index(current_speed)
                except ValueError:
                    current_index = 2  # Default to "1"

                # Determine direction (up = faster, down = slower)
                delta = event.angleDelta().y()
                if delta > 0:
                    # Scroll up - increase speed
                    new_index = min(current_index + 1, len(speed_options) - 1)
                else:
                    # Scroll down - decrease speed
                    new_index = max(current_index - 1, 0)

                # Update speed
                self.selected_sublane_block.effect_speed = speed_options[new_index]

                # Mark block as modified
                self.block.modified = True

                # Repaint to update grid
                self.update()

                # Accept event to prevent propagation
                event.accept()
                return

        # If not handled, pass to parent
        super().wheelEvent(event)

    def keyPressEvent(self, event):
        """Handle key press for deletion."""
        if event.key() == Qt.Key.Key_Delete or event.key() == Qt.Key.Key_Backspace:
            self.remove_requested.emit(self)
        else:
            super().keyPressEvent(event)
