from PyQt6.QtWidgets import QGraphicsItem, QGraphicsEllipseItem, QGraphicsView
from PyQt6.QtCore import Qt, QRectF, QPointF
from PyQt6.QtGui import QPen, QBrush, QColor, QPainter, QFontMetrics, QFont
from math import sin, cos, radians, atan2, sqrt

from utils.fixture_capabilities import chassis_from_legacy_type
from gui.widgets.fixture_icons import (
    ACCENT_LAMPS,
    ACCENT_PIXELS,
    paint_fixture_icon,
)


def projected_bar_angle_2d(yaw: float, pitch: float, roll: float) -> float:
    """2D top-down rotation (degrees) of a bar fixture's length axis.

    Projects the fixture's local X-axis through the full yaw/pitch/roll
    orientation onto the floor plane. Shared by the Stage tab's
    FixtureItem and the stage-plot exporter so both draw bars at the
    same apparent angle. Returns ``yaw + 90`` when the length axis is
    near-vertical (no meaningful floor projection).

    Coordinate systems:
    - 3D World: X = stage right, Y = up (height), Z = toward audience (depth)
    - 2D Stage view (top-down): X = stage right, Y = toward audience (maps to 3D Z)
    """
    yaw_rad = radians(yaw)
    pitch_rad = radians(pitch)
    roll_rad = radians(roll)

    # Where does the local X unit vector (the bar's length) end up in
    # world space after Yaw (Y) -> Pitch (X) -> Roll (Z)?
    x1, y1, z1 = cos(yaw_rad), 0.0, -sin(yaw_rad)

    x2 = x1
    y2 = y1 * cos(pitch_rad) - z1 * sin(pitch_rad)
    z2 = y1 * sin(pitch_rad) + z1 * cos(pitch_rad)

    x3 = x2 * cos(roll_rad) - y2 * sin(roll_rad)
    z3 = z2  # Z unchanged by roll around Z

    # Project onto the floor plane. Near-vertical bars have no useful
    # projection; show them rotated 90° from yaw like FixtureItem did.
    proj_length = sqrt(x3 * x3 + z3 * z3)
    if proj_length < 0.01:
        return yaw + 90

    # atan2(z, x) measures from +X toward +Z; positive Z (toward the
    # audience) is negative screen-Y, hence the negation.
    return atan2(-z3, x3) * 180.0 / 3.14159265359


class FixtureItem(QGraphicsItem):
    # Class-level toggle for orientation-axis overlay (controlled by
    # stage_tab.py's "Show orientation axes" checkbox). When True every
    # FixtureItem draws its XYZ axes on top of the fixture symbol.
    show_orientation_axes = False

    def __init__(self, fixture_name, fixture_type, channel_color, parent=None):
        super().__init__(parent)
        self.fixture_name = fixture_name
        self.fixture_type = fixture_type
        self.channel_color = channel_color
        self.rotation_angle = 0  # Yaw rotation
        self.z_height = 0

        # Orientation fields (new)
        self.mounting = "hanging"  # "hanging", "standing", "wall_left", "wall_right", "wall_back", "wall_front"
        self.pitch = 0.0
        self.roll = 0.0
        self.orientation_uses_group_default = True
        self.z_uses_group_default = True  # Whether to use group's default_z_height
        self.layer = ""  # Stage layer assignment ("" = none)
        self.docked_to = ""  # element_id of the truss this hangs on
        # Active-layer editing: fixtures NOT on the active layer ghost to
        # a faint, locked reference (see StageView.set_active_layer).
        self.ghosted = False

        # Enable dragging and mouse interaction
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.setAcceptHoverEvents(True)

        # Size of the fixture symbol
        self.size = 30

        # Text height
        self.text_height = 25  # Height reserved for text

    def boundingRect(self):
        # Include the main fixture symbol plus text area (wider for long names)
        text_width = max(self.size * 3, 100)  # At least 100px wide for text

        # For bar-type fixtures, account for the rotated extent
        if self.fixture_type in ("BAR", "PIXELBAR", "SUNSTRIP"):
            rotation_2d = self._get_2d_rotation_angle()
            # Bar symbol dimensions: width = size*2; the vertical extent
            # covers the SVG bar body plus its beam tick (tick top sits
            # 0.583*size above center) and the selection ring.
            bar_half_width = self.size  # half of bar_width
            bar_half_height = self.size * 0.62
            # Calculate the extent after rotation
            angle_rad = radians(rotation_2d)
            horizontal_extent = abs(bar_half_width * cos(angle_rad)) + abs(bar_half_height * sin(angle_rad))
            vertical_extent = abs(bar_half_width * sin(angle_rad)) + abs(bar_half_height * cos(angle_rad))
            # Use max of text width and fixture horizontal extent
            total_width = max(text_width, horizontal_extent * 2)
            total_height = vertical_extent + self.text_height + 3  # +3 for padding
            return QRectF(-total_width / 2, -vertical_extent, total_width, total_height + vertical_extent)

        return QRectF(-text_width / 2, -self.size / 2, text_width, self.size + self.text_height)

    def set_ghosted(self, ghosted: bool):
        """Ghost = barely visible + locked. Applied while another stage
        layer is active for editing: the fixture stays on the plot as a
        spatial reference but can't be selected, dragged, or wheel-edited."""
        if ghosted == self.ghosted:
            return
        self.ghosted = ghosted
        self.setOpacity(0.18 if ghosted else 1.0)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, not ghosted)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, not ghosted)
        if ghosted:
            self.setSelected(False)
        self.update()

    def mouseMoveEvent(self, event):
        """Handle mouse movement for dragging fixtures"""
        if self.ghosted:
            # Belt and braces on top of the cleared ItemIsMovable flag —
            # this override moves the item itself, so it must not run.
            event.ignore()
            return
        if Qt.MouseButton.LeftButton & event.buttons():
            # Get the view
            view = self.scene().views()[0]

            # Get the new position
            new_pos = event.scenePos()

            # If view has snapping enabled, snap to grid during movement
            if hasattr(view, 'snap_enabled') and view.snap_enabled:
                # Calculate the snapped position
                snapped_pos = view.snap_to_grid_position(new_pos)
                self.setPos(snapped_pos)
            else:
                self.setPos(new_pos)

            # Update the configuration through the view
            if hasattr(view, 'save_positions_to_config'):
                view.save_positions_to_config()

            event.accept()
            return

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        """Drop = dock/undock check against truss elements (the view
        owns the rules; see StageView.handle_fixture_drop)."""
        super().mouseReleaseEvent(event)
        if self.ghosted:
            return
        scene = self.scene()
        if scene is not None:
            views = scene.views()
            if views and hasattr(views[0], 'handle_fixture_drop'):
                views[0].handle_fixture_drop(self)

    def paint(self, painter, option, widget):
        painter.save()  # Save the current painter state

        # Apply rotation transformation
        painter.translate(0, 0)  # Translate to center point
        # For bar-type fixtures, calculate 2D rotation from full 3D orientation
        # This correctly projects the fixture's length onto the top-down view
        if self.fixture_type in ("BAR", "PIXELBAR", "SUNSTRIP"):
            rotation_2d = self._get_2d_rotation_angle()
            painter.rotate(rotation_2d)
        else:
            painter.rotate(self.rotation_angle + 90)  # Add 90 degrees to make 0 point downwards

        # Set smaller font size
        font = painter.font()
        font.setPointSize(8)
        painter.setFont(font)

        # Set up pens and brushes based on selection state
        if self.isSelected():
            painter.setPen(QPen(Qt.GlobalColor.blue, 3))
            selected_color = QColor(self.channel_color)
            selected_color.setAlpha(160)
            painter.setBrush(QBrush(selected_color))
        else:
            painter.setPen(QPen(Qt.GlobalColor.black, 2))
            painter.setBrush(QBrush(QColor(self.channel_color)))

        # Draw the fixture icon. Mapped types render their North Star
        # stage-plot symbol (line art in the group color); unknown types
        # fall back to the chassis-keyed primitives, where the legacy
        # fixture_type string still drives the accent.
        chassis = chassis_from_legacy_type(self.fixture_type)
        if self.fixture_type == "PIXELBAR":
            accent = ACCENT_PIXELS
        elif self.fixture_type == "SUNSTRIP":
            accent = ACCENT_LAMPS
        else:
            accent = None
        used_symbol = paint_fixture_icon(
            painter, chassis, self.size, accent=accent,
            fixture_type=self.fixture_type,
        )
        if used_symbol and self.isSelected():
            # The line symbols have no filled body for the blue selection
            # pen to outline (the legacy primitives got that for free), so
            # draw an explicit selection ring around the symbol box.
            painter.setBrush(Qt.BrushStyle.NoBrush)
            if self.fixture_type in ("BAR", "PIXELBAR", "SUNSTRIP"):
                ring = QRectF(-self.size - 2, -self.size * 0.62 - 2,
                              2 * self.size + 4, 2 * self.size * 0.62 + 4)
            else:
                ring = QRectF(-self.size / 2 - 2, -self.size / 2 - 2,
                              self.size + 4, self.size + 4)
            painter.drawRect(ring)

        # Draw mounting indicator (colored dot/ring in center)
        self._draw_mounting_indicator(painter)

        # Reset transformation for rotation handle and text
        painter.restore()  # Restore the original painter state
        painter.save()

        # Draw orientation axes if enabled (single class-level toggle
        # — see show_orientation_axes for the rationale behind not
        # gating on selection).
        if FixtureItem.show_orientation_axes:
            self._draw_orientation_axes(painter)

        painter.restore()

        # Draw text (not rotated) - name and Z-height separately
        text_width = max(self.size * 3, 100)

        # Calculate the vertical offset for text based on fixture type and rotation
        # For bar-type fixtures, account for the rotated extent
        if self.fixture_type in ("BAR", "PIXELBAR", "SUNSTRIP"):
            rotation_2d = self._get_2d_rotation_angle()
            # Must match boundingRect's bar extents (symbol body + beam
            # tick + selection ring) so labels clear the artwork.
            bar_half_width = self.size  # half of bar_width
            bar_half_height = self.size * 0.62
            # Calculate the maximum vertical extent after rotation
            angle_rad = radians(rotation_2d)
            # The vertical extent is the max of the rotated corners
            vertical_extent = abs(bar_half_width * sin(angle_rad)) + abs(bar_half_height * cos(angle_rad))
            text_y_offset = vertical_extent + 3  # 3px padding
        else:
            text_y_offset = self.size / 2

        # Draw fixture name (regular font). Text colour comes from
        # the parent StageView's ``fixtureTextColor`` qproperty, which
        # the active QSS theme drives via
        # ``StageView { qproperty-fixtureTextColor: #...; }`` —
        # hardcoding black left the labels invisible on the dark-mode
        # stage fill.
        text_color = self._theme_text_color()

        # North Star stage plan labels: small mono name, and the Z/layer
        # readout one step quieter (secondary label color, not bold - the
        # old bold Z line dominated the whole plot).
        from gui.typography import mono_font
        painter.setFont(mono_font(7))
        painter.setPen(QPen(text_color))

        name_rect = QRectF(-text_width / 2, text_y_offset, text_width, 12)
        painter.drawText(name_rect, Qt.AlignmentFlag.AlignCenter, self.fixture_name)

        painter.setFont(mono_font(6))
        painter.setPen(QPen(self._theme_label_color()))

        z_rect = QRectF(-text_width / 2, text_y_offset + 11, text_width, 12)
        z_label = f"Z {self.z_height:.1f}m"
        if self.layer:
            z_label += f" · {self.layer}"
        painter.drawText(z_rect, Qt.AlignmentFlag.AlignCenter, z_label)

    def wheelEvent(self, event):
        """Handle mouse wheel events for changing z-height (Shift+scroll)."""
        if self.ghosted:
            event.ignore()
            return
        modifiers = event.modifiers()

        # Only handle Z-height adjustment with Shift modifier
        # Rotation is now handled via the Orientation Dialog
        if modifiers & Qt.KeyboardModifier.ShiftModifier:
            if hasattr(event, 'angleDelta'):
                delta = event.angleDelta().y()
            else:
                delta = event.delta()

            delta = delta / 120.0

            z_step = 0.1
            if delta > 0:
                self.z_height = max(0, self.z_height + z_step)
            else:
                self.z_height = max(0, self.z_height - z_step)

            # Mark that user has set a custom Z value (don't use group default anymore)
            self.z_uses_group_default = False

            self.update()

            # Auto-save to config after z-height change
            view = self.scene().views()[0]
            if hasattr(view, 'save_positions_to_config'):
                view.save_positions_to_config()

            event.accept()
        else:
            # Pass to parent for default handling
            event.ignore()

    def _draw_mounting_indicator(self, painter):
        """Draw mounting indicator based on mounting type.

        - Blue dot/ring: Beam points down (hanging)
        - Orange dot/ring: Beam points up (standing)
        - Colored bar on edge: Wall mount (positioned on the wall side)
        """
        indicator_size = 8

        # Determine color based on mounting
        if self.mounting == "hanging":
            color = QColor(60, 120, 255)  # Blue for hanging (beam down)
        elif self.mounting == "standing":
            color = QColor(255, 140, 0)  # Orange for standing (beam up)
        elif self.mounting in ("wall_left", "wall_right", "wall_back", "wall_front"):
            color = QColor(100, 180, 100)  # Green for wall mounts
        else:
            color = QColor(128, 128, 128)  # Gray for unknown

        # Check if this is a custom orientation (non-preset values)
        is_custom = self._is_custom_orientation()

        if self.mounting in ("wall_left", "wall_right", "wall_back", "wall_front"):
            # Draw a bar on the wall side
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(color))

            bar_width = 4
            bar_length = self.size * 0.6

            if self.mounting == "wall_back":
                # Bar at the back (top in 2D view after rotation compensation)
                painter.drawRect(QRectF(-bar_length/2, -self.size/2 - bar_width, bar_length, bar_width))
            elif self.mounting == "wall_front":
                # Bar at the front (bottom in 2D view)
                painter.drawRect(QRectF(-bar_length/2, self.size/2, bar_length, bar_width))
            elif self.mounting == "wall_left":
                # Bar on the left
                painter.drawRect(QRectF(-self.size/2 - bar_width, -bar_length/2, bar_width, bar_length))
            elif self.mounting == "wall_right":
                # Bar on the right
                painter.drawRect(QRectF(self.size/2, -bar_length/2, bar_width, bar_length))
        else:
            # Draw a dot/ring in the center for hanging/standing
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(color))

            if is_custom:
                # Draw ring (hollow) for custom orientation
                painter.setPen(QPen(color, 2))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawEllipse(QRectF(-indicator_size/2, -indicator_size/2, indicator_size, indicator_size))
            else:
                # Draw filled dot for preset orientation
                painter.drawEllipse(QRectF(-indicator_size/2, -indicator_size/2, indicator_size, indicator_size))

    def _is_custom_orientation(self) -> bool:
        """Check if this fixture has a custom (non-preset) orientation.

        Returns True if pitch or roll are non-zero, indicating user customization.
        """
        return abs(self.pitch) > 0.1 or abs(self.roll) > 0.1

    def _get_2d_rotation_angle(self) -> float:
        """2D rotation for the top-down view — see projected_bar_angle_2d."""
        return projected_bar_angle_2d(self.rotation_angle, self.pitch, self.roll)

    def _theme_text_color(self):
        """Return the theme-driven label colour from the parent
        StageView's ``fixtureTextColor`` qproperty.

        Falls back to black if the item isn't yet attached to a scene
        (e.g. during early construction or in unit tests). The active
        QSS theme writes this property via the ``StageView { ... }``
        rule, so adding a new theme is just a matter of adding the
        right ``qproperty-fixtureTextColor`` line.
        """
        scene = self.scene()
        if scene is not None:
            views = scene.views()
            if views:
                view = views[0]
                color = getattr(view, "fixtureTextColor", None)
                if color is not None and color.isValid():
                    return color
        return QColor(0, 0, 0)

    def _theme_label_color(self):
        """The quieter secondary label colour (StageView's
        ``stageLabelColor`` qproperty), for the Z/layer readout."""
        scene = self.scene()
        if scene is not None:
            views = scene.views()
            if views:
                view = views[0]
                color = getattr(view, "stageLabelColor", None)
                if color is not None and color.isValid():
                    return color
        return QColor(120, 120, 120)

    def _draw_orientation_axes(self, painter):
        """Draw orientation coordinate axes for the fixture.

        Shows the fixture's local coordinate system in 2D:
        - X axis (red): Solid arrow in viewing plane
        - Y axis (green): Solid arrow in viewing plane
        - Z axis (blue): Circle indicator (⊙ for out of page, ⊗ for into page)
        """
        axis_length = self.size * 0.6
        arrow_size = 4

        # Since we're in a 2D top-down view after yaw rotation has been applied:
        # - X axis points to the right (red)
        # - Y axis points up in the view (green)
        # - Z axis points out of/into the page (blue)

        # Draw X axis (red) - pointing right
        painter.setPen(QPen(QColor(255, 80, 80), 2))
        painter.drawLine(QPointF(0, 0), QPointF(axis_length, 0))
        # Arrow head
        painter.drawLine(QPointF(axis_length, 0), QPointF(axis_length - arrow_size, -arrow_size/2))
        painter.drawLine(QPointF(axis_length, 0), QPointF(axis_length - arrow_size, arrow_size/2))

        # Draw Y axis (green) - pointing up (which is negative Y in Qt coordinates)
        painter.setPen(QPen(QColor(80, 200, 80), 2))
        painter.drawLine(QPointF(0, 0), QPointF(0, -axis_length))
        # Arrow head
        painter.drawLine(QPointF(0, -axis_length), QPointF(-arrow_size/2, -axis_length + arrow_size))
        painter.drawLine(QPointF(0, -axis_length), QPointF(arrow_size/2, -axis_length + arrow_size))

        # Draw Z axis indicator (blue circle with dot or X)
        z_indicator_size = 8
        z_offset = axis_length * 0.4  # Position slightly offset from center

        painter.setPen(QPen(QColor(80, 80, 255), 2))

        # Determine Z direction based on mounting
        if self.mounting == "hanging":
            # Beam points down: Z into page (⊗)
            painter.drawEllipse(QRectF(z_offset - z_indicator_size/2, z_offset - z_indicator_size/2,
                                       z_indicator_size, z_indicator_size))
            # Draw X inside
            cross_size = z_indicator_size * 0.3
            painter.drawLine(QPointF(z_offset - cross_size, z_offset - cross_size),
                           QPointF(z_offset + cross_size, z_offset + cross_size))
            painter.drawLine(QPointF(z_offset - cross_size, z_offset + cross_size),
                           QPointF(z_offset + cross_size, z_offset - cross_size))
        else:
            # Beam points up or horizontal: Z out of page (⊙)
            painter.drawEllipse(QRectF(z_offset - z_indicator_size/2, z_offset - z_indicator_size/2,
                                       z_indicator_size, z_indicator_size))
            # Draw dot inside
            painter.setBrush(QBrush(QColor(80, 80, 255)))
            painter.drawEllipse(QRectF(z_offset - 2, z_offset - 2, 4, 4))


class SpotItem(QGraphicsItem):
    def __init__(self, name: str, parent=None):
        super().__init__(parent)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.setAcceptHoverEvents(True)
        self.size = 20  # Size of the X
        self.name = name
        self.z_height = 0.0  # Z height in meters (for 3D targeting)
        self.last_pos = self.pos()  # Store last position for snapping

    def boundingRect(self):
        text_width = max(len(self.name) * 8, 60)  # Approximate width of text
        return QRectF(-self.size/2 - 2, -self.size/2 - 2,
                     max(self.size + 4, text_width), self.size + 35)  # Extra space for Z-height

    def mouseMoveEvent(self, event):
        view = self.scene().views()[0]  # Get the main view
        if view.snap_enabled:
            # Get current position in scene coordinates
            new_pos = event.scenePos()

            # Use view's snap_to_grid_position for center-based snapping
            snapped_pos = view.snap_to_grid_position(new_pos)
            self.setPos(snapped_pos)
        else:
            super().mouseMoveEvent(event)

        # Store new position
        self.last_pos = self.pos()

        # Auto-save to config after move
        if hasattr(view, 'save_positions_to_config'):
            view.save_positions_to_config()

    def wheelEvent(self, event):
        """Handle mouse wheel events for changing z-height (Shift+scroll)."""
        modifiers = event.modifiers()

        if modifiers & Qt.KeyboardModifier.ShiftModifier:
            if hasattr(event, 'angleDelta'):
                delta = event.angleDelta().y()
            else:
                delta = event.delta()

            delta = delta / 120.0
            z_step = 0.1

            if delta > 0:
                self.z_height = self.z_height + z_step
            else:
                self.z_height = self.z_height - z_step

            self.update()

            # Auto-save to config after z-height change
            view = self.scene().views()[0]
            if hasattr(view, 'save_positions_to_config'):
                view.save_positions_to_config()

            event.accept()
        else:
            event.ignore()

    def paint(self, painter, option, widget):
        if self.isSelected():
            painter.setPen(QPen(Qt.GlobalColor.blue, 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(QRectF(-self.size/2 - 2, -self.size/2 - 2,
                                     self.size + 4, self.size + 4))
            painter.setPen(QPen(Qt.GlobalColor.blue, 5))
        else:
            painter.setPen(QPen(Qt.GlobalColor.black, 5))

        # Draw X
        painter.drawLine(QPointF(-self.size/2, -self.size/2),
                        QPointF(self.size/2, self.size/2))
        painter.drawLine(QPointF(-self.size/2, self.size/2),
                        QPointF(self.size/2, -self.size/2))

        # Draw name below the X
        painter.setPen(QPen(Qt.GlobalColor.black, 1))
        painter.setFont(QFont("Arial", 10))
        painter.drawText(QPointF(-self.size/2, self.size + 5), self.name)

        # Draw Z-height below the name
        font = painter.font()
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(QPointF(-self.size/2, self.size + 18), f"Z: {self.z_height:.1f}m")



class StageElementItem(QGraphicsItem):
    """A static stage element (riser, wedge, amp, truss shape, ...) on
    the plan (StageElement model, utils/stage_element_catalog.py).

    Renders the stageplot SVG symbol stretched to the element's real
    footprint, draggable with grid snap, rotatable via context menu,
    ghosted by the active-layer mode exactly like fixtures. Draws under
    fixtures (zValue -1). Holds a direct reference to its StageElement
    model; the view writes positions back on drag.
    """

    _renderers = {}  # kind -> QSvgRenderer (shared per session)

    def __init__(self, element, pixels_per_meter, parent=None):
        super().__init__(parent)
        self.element = element
        self.ppm = pixels_per_meter
        self.ghosted = False
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.setZValue(-1)  # under fixtures

    @classmethod
    def _renderer(cls, kind):
        if kind not in cls._renderers:
            from PyQt6.QtSvg import QSvgRenderer
            from utils.stage_element_catalog import symbol_path
            cls._renderers[kind] = QSvgRenderer(symbol_path(kind))
        return cls._renderers[kind]

    def _body_rect(self):
        w = self.element.width * self.ppm
        d = self.element.depth * self.ppm
        return QRectF(-w / 2, -d / 2, w, d)

    def boundingRect(self):
        rect = self._body_rect()
        # Rotation happens inside paint(); bound by the rotated extent
        # plus the label strip and selection ring.
        angle = radians(self.element.rotation)
        half_w = abs(rect.width() / 2 * cos(angle)) + abs(rect.height() / 2 * sin(angle))
        half_h = abs(rect.width() / 2 * sin(angle)) + abs(rect.height() / 2 * cos(angle))
        label_h = 14 if self.element.label else 0
        return QRectF(-half_w - 4, -half_h - 4,
                      2 * half_w + 8, 2 * half_h + 8 + label_h)

    def set_ghosted(self, ghosted: bool):
        if ghosted == self.ghosted:
            return
        self.ghosted = ghosted
        self.setOpacity(0.18 if ghosted else 1.0)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, not ghosted)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, not ghosted)
        if ghosted:
            self.setSelected(False)
        self.update()

    def paint(self, painter, option, widget):
        painter.save()
        painter.rotate(self.element.rotation)
        renderer = self._renderer(self.element.kind)
        if renderer.isValid():
            renderer.render(painter, self._body_rect())
        else:
            painter.setPen(QPen(QColor("#8D9299"), 1, Qt.PenStyle.DashLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(self._body_rect())
        painter.restore()

        if self.isSelected():
            painter.setPen(QPen(Qt.GlobalColor.blue, 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            body = self.boundingRect()
            painter.drawRect(body.adjusted(2, 2, -2,
                                           -(14 if self.element.label else 0) - 2))

        if self.element.label:
            from gui.typography import mono_font
            painter.setFont(mono_font(6))
            view_color = self._label_color()
            painter.setPen(QPen(view_color))
            body = self.boundingRect()
            painter.drawText(
                QRectF(body.left(), body.bottom() - 13, body.width(), 12),
                Qt.AlignmentFlag.AlignCenter, self.element.label)

    def _label_color(self):
        scene = self.scene()
        if scene is not None:
            views = scene.views()
            if views:
                color = getattr(views[0], "stageLabelColor", None)
                if color is not None and color.isValid():
                    return color
        return QColor(120, 120, 120)

    def mouseMoveEvent(self, event):
        if self.ghosted:
            event.ignore()
            return
        if Qt.MouseButton.LeftButton & event.buttons():
            view = self.scene().views()[0]
            new_pos = event.scenePos()
            if getattr(view, "snap_enabled", False):
                new_pos = view.snap_to_grid_position(new_pos)
            old_pos = self.pos()
            self.setPos(new_pos)
            # A truss carries its docked fixtures (truss = its own
            # layer; the fixtures hang on it).
            delta = self.pos() - old_pos
            if not delta.isNull() and hasattr(view, "move_docked_fixtures"):
                view.move_docked_fixtures(self.element, delta)
            if hasattr(view, "save_positions_to_config"):
                view.save_positions_to_config()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def set_size(self, width_m: float, depth_m: float) -> None:
        """Resize the element's footprint in metres (length x depth for a
        straight truss). Bounds change, so callers must be inside a
        prepareGeometryChange or call it via the context-menu path."""
        self.element.width = max(0.1, float(width_m))
        self.element.depth = max(0.1, float(depth_m))

    def _edit_size(self) -> bool:
        """Prompt for the footprint. Straight trusses ask only for length
        (their depth is the truss profile); everything else asks for both.
        Returns False when the user cancels."""
        from PyQt6.QtWidgets import QInputDialog
        from utils.stage_element_catalog import is_truss

        straight = self.element.kind == "truss-straight"
        length, ok = QInputDialog.getDouble(
            None,
            "Truss Length" if is_truss(self.element.kind) else "Element Size",
            "Length (m):" if straight else "Width (m):",
            self.element.width, 0.1, 100.0, 2)
        if not ok:
            return False
        depth = self.element.depth
        if not straight:
            depth, ok = QInputDialog.getDouble(
                None, "Element Size", "Depth (m):",
                self.element.depth, 0.1, 100.0, 2)
            if not ok:
                return False
        self.set_size(length, depth)
        return True

    def contextMenuEvent(self, event):
        if self.ghosted:
            event.ignore()
            return
        from PyQt6.QtWidgets import QMenu, QInputDialog
        from utils.stage_element_catalog import is_truss
        view = self.scene().views()[0]
        menu = QMenu()
        rotate_left = menu.addAction("Rotate -45°")
        rotate_right = menu.addAction("Rotate +45°")
        rename = menu.addAction("Set Label...")
        size_action = menu.addAction(
            "Truss Length..." if is_truss(self.element.kind)
            else "Element Size...")
        height_action = None
        if is_truss(self.element.kind):
            height_action = menu.addAction("Truss Height...")
        layer_menu = menu.addMenu("Assign to Layer")
        layer_actions = {}
        clear_action = layer_menu.addAction("(none)")
        config = getattr(view, "config", None)
        for layer in getattr(config, "stage_layers", []) or []:
            layer_actions[layer_menu.addAction(layer.name)] = layer.name
        menu.addSeparator()
        remove = menu.addAction("Remove Element")

        chosen = menu.exec(event.screenPos())
        if chosen is rotate_left:
            self.element.rotation = (self.element.rotation - 45) % 360
        elif chosen is rotate_right:
            self.element.rotation = (self.element.rotation + 45) % 360
        elif chosen is size_action:
            if not self._edit_size():
                event.accept()
                return
        elif height_action is not None and chosen is height_action:
            config = getattr(view, "config", None)
            layer = (config.get_stage_layer(self.element.layer)
                     if config and self.element.layer else None)
            current = layer.z_height if layer is not None else 4.0
            value, ok = QInputDialog.getDouble(
                None, "Truss Height",
                "Hang height (m) - moves every fixture on this truss's layer:",
                current, 0.0, 30.0, 1)
            if ok and hasattr(view, "set_truss_height"):
                view.set_truss_height(self.element, value)
            event.accept()
            return
        elif chosen is rename:
            text, ok = QInputDialog.getText(None, "Element Label",
                                            "Label:", text=self.element.label)
            if ok:
                self.element.label = text
        elif chosen is clear_action:
            self.element.layer = ""
        elif chosen in layer_actions:
            self.element.layer = layer_actions[chosen]
        elif chosen is remove:
            if hasattr(view, "remove_stage_element"):
                view.remove_stage_element(self)
            event.accept()
            return
        else:
            event.accept()
            return
        self.prepareGeometryChange()
        self.update()
        if hasattr(view, "save_positions_to_config"):
            view.save_positions_to_config()
        if hasattr(view, "apply_layer_visibility"):
            view.apply_layer_visibility()
        event.accept()
