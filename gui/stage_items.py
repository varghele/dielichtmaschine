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
            # Bar dimensions: width = size*2, height = size/3
            bar_half_width = self.size  # half of bar_width
            bar_half_height = self.size / 6  # half of bar_height
            # Calculate the extent after rotation
            angle_rad = radians(rotation_2d)
            horizontal_extent = abs(bar_half_width * cos(angle_rad)) + abs(bar_half_height * sin(angle_rad))
            vertical_extent = abs(bar_half_width * sin(angle_rad)) + abs(bar_half_height * cos(angle_rad))
            # Use max of text width and fixture horizontal extent
            total_width = max(text_width, horizontal_extent * 2)
            total_height = vertical_extent + self.text_height + 3  # +3 for padding
            return QRectF(-total_width / 2, -vertical_extent, total_width, total_height + vertical_extent)

        return QRectF(-text_width / 2, -self.size / 2, text_width, self.size + self.text_height)

    def mouseMoveEvent(self, event):
        """Handle mouse movement for dragging fixtures"""
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

        # Draw the chassis-keyed icon. PIXELBAR / SUNSTRIP are both
        # Chassis.BAR; the legacy fixture_type string still drives the
        # accent so visual fidelity is preserved.
        chassis = chassis_from_legacy_type(self.fixture_type)
        if self.fixture_type == "PIXELBAR":
            accent = ACCENT_PIXELS
        elif self.fixture_type == "SUNSTRIP":
            accent = ACCENT_LAMPS
        else:
            accent = None
        paint_fixture_icon(painter, chassis, self.size, accent=accent)

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
            # Bar dimensions: width = size*2, height = size/3
            bar_half_width = self.size  # half of bar_width
            bar_half_height = self.size / 6  # half of bar_height
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

        font = painter.font()
        font.setPointSize(8)
        font.setBold(False)
        painter.setFont(font)
        painter.setPen(QPen(text_color))

        name_rect = QRectF(-text_width / 2, text_y_offset, text_width, 12)
        painter.drawText(name_rect, Qt.AlignmentFlag.AlignCenter, self.fixture_name)

        # Draw Z-height (bold font)
        font.setBold(True)
        painter.setFont(font)

        z_rect = QRectF(-text_width / 2, text_y_offset + 11, text_width, 12)
        z_label = f"Z: {self.z_height:.1f}m"
        if self.layer:
            z_label += f"  [{self.layer}]"
        painter.drawText(z_rect, Qt.AlignmentFlag.AlignCenter, z_label)

    def wheelEvent(self, event):
        """Handle mouse wheel events for changing z-height (Shift+scroll)."""
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
        """Calculate the 2D rotation angle for top-down view based on full 3D orientation.

        For bar-type fixtures (BAR, SUNSTRIP), this computes where the fixture's
        local X-axis (its length) projects onto the floor plane (XZ in 3D world).

        Coordinate systems:
        - 3D World: X = stage right, Y = up (height), Z = toward audience (depth)
        - 2D Stage view (top-down): X = stage right, Y = toward audience (maps to 3D Z)

        Returns:
            Rotation angle in degrees for the 2D painter rotation.
        """
        # Get orientation angles in radians
        yaw_rad = radians(self.rotation_angle)  # rotation_angle stores yaw
        pitch_rad = radians(self.pitch)
        roll_rad = radians(self.roll)

        # Start with local X-axis unit vector (1, 0, 0)
        # This represents the "length" direction of the fixture

        # Apply rotations in order: Yaw (Y) -> Pitch (X) -> Roll (Z)
        # We compute where local X ends up in world space

        # After Yaw rotation around Y-axis:
        # x' = x*cos(yaw) + z*sin(yaw)
        # y' = y
        # z' = -x*sin(yaw) + z*cos(yaw)
        # For (1, 0, 0): (cos(yaw), 0, -sin(yaw))
        x1 = cos(yaw_rad)
        y1 = 0.0
        z1 = -sin(yaw_rad)

        # After Pitch rotation around X-axis:
        # x'' = x'
        # y'' = y'*cos(pitch) - z'*sin(pitch)
        # z'' = y'*sin(pitch) + z'*cos(pitch)
        x2 = x1
        y2 = y1 * cos(pitch_rad) - z1 * sin(pitch_rad)
        z2 = y1 * sin(pitch_rad) + z1 * cos(pitch_rad)

        # After Roll rotation around Z-axis:
        # x''' = x''*cos(roll) - y''*sin(roll)
        # y''' = x''*sin(roll) + y''*cos(roll)
        # z''' = z''
        x3 = x2 * cos(roll_rad) - y2 * sin(roll_rad)
        y3 = x2 * sin(roll_rad) + y2 * cos(roll_rad)
        z3 = z2  # Z is unchanged by roll around Z

        # Project onto floor plane (XZ in 3D world = XY in 2D stage view)
        # x3 = world X (stage left/right)
        # z3 = world Z (stage depth, becomes Y in 2D view)

        # Handle near-zero projection (fixture's length pointing straight up/down)
        proj_length = sqrt(x3 * x3 + z3 * z3)
        if proj_length < 0.01:
            # Fixture's length is nearly vertical (pointing up or down)
            # Show as vertical in 2D (rotated 90° from yaw)
            return self.rotation_angle + 90

        # Calculate angle in degrees
        # atan2(z, x) gives angle from positive X-axis toward positive Z
        # In 2D stage view: positive Z (toward audience) is negative Y on screen
        # So we negate z3 to match screen coordinates
        angle = atan2(-z3, x3) * 180.0 / 3.14159265359

        return angle

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

