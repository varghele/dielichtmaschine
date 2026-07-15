from math import cos, radians, sin

from PyQt6 import QtWidgets, QtGui, QtCore
from PyQt6.QtCore import pyqtProperty
from PyQt6.QtGui import QColor
from gui.stage_items import FixtureItem, SpotItem
from config.models import Spot


# Fallback colours used only when QSS hasn't supplied a value yet (e.g.
# the very first paint before the theme is applied). The active theme
# overrides these via `qproperty-stageOutlineColor` and friends in the
# theme stylesheets — see ``resources/themes/{dark,light}.qss``.
_FALLBACK_OUTLINE = QColor(0, 0, 0)
_FALLBACK_FILL = QColor(240, 240, 240)
_FALLBACK_GRID = QColor(200, 200, 200)
_FALLBACK_LABEL = QColor(60, 60, 60)
_FALLBACK_FIXTURE_TEXT = QColor(0, 0, 0)


# Drag-and-drop contract between the Stage tab's element palette and the
# 2D plan: the payload is the catalog kind, UTF-8 encoded. Kept here
# because the drop target owns the format; the palette imports it.
ELEMENT_MIME_TYPE = "application/x-lichtmaschine-element"


def element_mime_data(kind: str) -> QtCore.QMimeData:
    """The QMimeData a palette tile drags: one catalog kind."""
    mime = QtCore.QMimeData()
    mime.setData(ELEMENT_MIME_TYPE, QtCore.QByteArray(kind.encode("utf-8")))
    return mime


def element_kind_from_mime(mime) -> str:
    """The catalog kind carried by a drag, or '' when it carries none."""
    if mime is None or not mime.hasFormat(ELEMENT_MIME_TYPE):
        return ""
    return bytes(mime.data(ELEMENT_MIME_TYPE)).decode("utf-8", "replace")


class StageView(QtWidgets.QGraphicsView):
    # Signal emitted when fixture positions/rotations/heights change
    fixtures_changed = QtCore.pyqtSignal()

    # Signal emitted when user requests to set orientation for selected fixtures
    set_orientation_requested = QtCore.pyqtSignal(list)  # List of FixtureItem

    # Emitted with the freshly placed StageElement after a palette click
    # or a palette drop (the tab refreshes its layer UI on it: placing a
    # truss creates a stage layer).
    stage_element_added = QtCore.pyqtSignal(object)

    # Emitted whenever the set of stage marks (spots) changes - added,
    # removed or renamed - so the Marks list in the tab can refresh.
    spots_changed = QtCore.pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        # Theme-driven colours — populated by Qt's stylesheet engine
        # via ``qproperty-stageOutlineColor`` (etc.) rules in the
        # active QSS theme. Initialised here to neutral defaults so a
        # paint that races the first stylesheet apply still works.
        self._stage_outline_color = QColor(_FALLBACK_OUTLINE)
        self._stage_fill_color = QColor(_FALLBACK_FILL)
        self._stage_grid_color = QColor(_FALLBACK_GRID)
        self._stage_label_color = QColor(_FALLBACK_LABEL)
        self._fixture_text_color = QColor(_FALLBACK_FIXTURE_TEXT)

        self.config = None  # Store configuration
        self.scene = QtWidgets.QGraphicsScene(self)
        self.setScene(self.scene)
        self.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)

        # Enable drag and drop
        self.setAcceptDrops(True)

        # Globally track if snapping is enabled
        self.snap_enabled = True  # Enabled by default

        # Rectangle selection state
        self._rubber_band = None
        self._rubber_band_origin = None
        self._is_rubber_band_selecting = False

        # Stage properties (in meters)
        self.stage_width_m = 10.0  # Default 10m
        self.stage_depth_m = 6.0  # Default 6m
        self.pixels_per_meter = 50  # Scale factor
        self.padding = 40  # Padding in pixels for dimension labels

        # Grid properties
        self.grid_visible = True
        self.grid_size_m = 0.5  # Default 0.5m grid

        # Zoom + pan state. Zoom is tracked as the cumulative scale
        # factor applied on top of the fit-to-stage baseline (1.0 ==
        # exactly fitted; 2.0 == 2x zoomed in). Pan happens when the
        # user holds Space and left-drags.
        self._zoom = 1.0
        self._min_zoom = 0.2
        self._max_zoom = 12.0
        self._space_held = False
        self._panning = False
        self._pan_anchor = None  # last mouse position during a pan drag

        # Scrollbars stay off — large stages would otherwise show bars
        # even when fitted, and AsNeeded was unreliable under some
        # platforms (range stayed at [0,0] after scale). Panning works
        # via direct QGraphicsView.translate() on the transform, so
        # scrollbar state doesn't matter.
        self.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setViewportUpdateMode(
            QtWidgets.QGraphicsView.ViewportUpdateMode.FullViewportUpdate
        )
        # AnchorUnderMouse keeps the point under the cursor stationary
        # while zooming — the natural feel for a CAD-style view.
        self.setTransformationAnchor(
            QtWidgets.QGraphicsView.ViewportAnchor.AnchorUnderMouse
        )
        self.setResizeAnchor(
            QtWidgets.QGraphicsView.ViewportAnchor.AnchorViewCenter
        )
        # StrongFocus so the view receives keyPressEvent for Space; the
        # widget grabs focus on first click. Without this, Space+drag
        # only works after the user has tabbed to the view.
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)

        # Active-layer editing mode: when set to a layer name, only that
        # layer's fixtures are interactive; everything else ghosts to a
        # faint, locked reference. None = normal editing. UI state, not
        # persisted to the config.
        self.active_layer = None

        # List to store fixture items
        self.fixtures = {}
        self.spots = {}  # name: SpotItem
        self.spot_counter = 1  # Counter for generating unique spot names
        self.stage_element_items = []  # StageElementItem per config.stage_elements entry

        # Initial update
        self.updateStage()

    # ── Theme-driven colour properties ────────────────────────────────
    # Each ``pyqtProperty(QColor, ...)`` is settable from QSS via
    # ``qproperty-<name>`` so the theme files own these values. The
    # setter triggers a viewport repaint and a fixture repaint so the
    # plot updates immediately when the theme is swapped at runtime.

    def _get_stage_outline_color(self):
        return self._stage_outline_color

    def _set_stage_outline_color(self, color):
        self._stage_outline_color = QColor(color)
        self._on_theme_color_changed()

    stageOutlineColor = pyqtProperty(QColor, _get_stage_outline_color, _set_stage_outline_color)

    def _get_stage_fill_color(self):
        return self._stage_fill_color

    def _set_stage_fill_color(self, color):
        self._stage_fill_color = QColor(color)
        self._on_theme_color_changed()

    stageFillColor = pyqtProperty(QColor, _get_stage_fill_color, _set_stage_fill_color)

    def _get_stage_grid_color(self):
        return self._stage_grid_color

    def _set_stage_grid_color(self, color):
        self._stage_grid_color = QColor(color)
        self._on_theme_color_changed()

    stageGridColor = pyqtProperty(QColor, _get_stage_grid_color, _set_stage_grid_color)

    def _get_stage_label_color(self):
        return self._stage_label_color

    def _set_stage_label_color(self, color):
        self._stage_label_color = QColor(color)
        self._on_theme_color_changed()

    stageLabelColor = pyqtProperty(QColor, _get_stage_label_color, _set_stage_label_color)

    def _get_fixture_text_color(self):
        return self._fixture_text_color

    def _set_fixture_text_color(self, color):
        self._fixture_text_color = QColor(color)
        self._on_theme_color_changed()

    fixtureTextColor = pyqtProperty(QColor, _get_fixture_text_color, _set_fixture_text_color)

    def _on_theme_color_changed(self):
        """Repaint the chrome and every item when QSS pushes a new
        colour. Called from each colour-property setter."""
        self.viewport().update()
        for item in self.scene.items():
            item.update()

    def set_config(self, config):
        """Update the configuration and refresh the view"""
        if config is not self.config:
            # A different project: the active-layer editing mode belongs
            # to the previous config's layer set.
            self.active_layer = None
        self.config = config
        self.update_from_config()

    def meters_to_pixels(self, x_m, y_m):
        """Convert center-based meter coordinates to pixel coordinates

        Args:
            x_m: X position in meters (0 = center, negative = left, positive = right)
            y_m: Y position in meters (0 = center, negative = front, positive = back)

        Returns:
            Tuple of (x_px, y_px) pixel coordinates

        The audience/front (negative Y) renders at the BOTTOM of the
        plan: screen Y grows downward, so negative y_m must map to a
        LARGER y_px. The X mapping is unchanged.
        """
        # Center of stage in pixels
        center_x_px = self.padding + (self.stage_width_m / 2) * self.pixels_per_meter
        center_y_px = self.padding + (self.stage_depth_m / 2) * self.pixels_per_meter

        x_px = center_x_px + x_m * self.pixels_per_meter
        y_px = center_y_px - y_m * self.pixels_per_meter

        return x_px, y_px

    def pixels_to_meters(self, x_px, y_px):
        """Convert pixel coordinates to center-based meter coordinates

        Args:
            x_px: X position in pixels
            y_px: Y position in pixels

        Returns:
            Tuple of (x_m, y_m) meter coordinates (0,0 = center)
        """
        # Center of stage in pixels
        center_x_px = self.padding + (self.stage_width_m / 2) * self.pixels_per_meter
        center_y_px = self.padding + (self.stage_depth_m / 2) * self.pixels_per_meter

        # Inverse of meters_to_pixels: the Y axis is flipped so that a
        # LOW screen y (bottom = audience/front) maps to a negative y_m.
        x_m = (x_px - center_x_px) / self.pixels_per_meter
        y_m = -(y_px - center_y_px) / self.pixels_per_meter

        return x_m, y_m

    def update_from_config(self):
        """Update all fixtures from current configuration"""
        if not self.config:
            return

        # Clear and update fixtures
        for fixture in self.fixtures.values():
            self.scene.removeItem(fixture)
        self.fixtures.clear()

        # Clear and update spots
        for spot in self.spots.values():
            self.scene.removeItem(spot)
        self.spots.clear()

        # Clear and update static stage elements
        for item in self.stage_element_items:
            self.scene.removeItem(item)
        self.stage_element_items = []

        # Reset spot counter
        self.spot_counter = 1

        # Stage elements draw under fixtures (zValue -1 in the item)
        from gui.stage_items import StageElementItem
        for element in getattr(self.config, 'stage_elements', []) or []:
            item = StageElementItem(element, self.pixels_per_meter)
            x_px, y_px = self.meters_to_pixels(element.x, element.y)
            item.setPos(x_px, y_px)
            self.scene.addItem(item)
            self.stage_element_items.append(item)

        # Update fixtures
        if hasattr(self.config, 'fixtures'):
            for fixture in self.config.fixtures:
                group_color = '#808080'
                group = None
                if fixture.group and hasattr(self.config, 'groups'):
                    group = self.config.groups.get(fixture.group)
                    if group:
                        group_color = group.color

                fixture_item = FixtureItem(
                    fixture_name=fixture.name,
                    fixture_type=fixture.type,
                    channel_color=group_color
                )

                # Set position directly from fixture properties (center-based coordinates)
                x_px, y_px = self.meters_to_pixels(fixture.x, fixture.y)
                fixture_item.setPos(x_px, y_px)

                # Get effective values (respecting group defaults if flags are set)
                mounting, yaw, pitch, roll = fixture.get_effective_orientation(group)
                effective_z = fixture.get_effective_z(group)

                # Set z-height and yaw rotation using effective values
                fixture_item.z_height = effective_z
                fixture_item.rotation_angle = yaw  # Use yaw for 2D rotation

                # Set orientation fields using effective values
                fixture_item.mounting = mounting
                fixture_item.pitch = pitch
                fixture_item.roll = roll
                fixture_item.orientation_uses_group_default = fixture.orientation_uses_group_default
                fixture_item.z_uses_group_default = fixture.z_uses_group_default

                # Store additional properties
                fixture_item.universe = fixture.universe
                fixture_item.address = fixture.address
                fixture_item.manufacturer = fixture.manufacturer
                fixture_item.model = fixture.model
                fixture_item.group = fixture.group
                fixture_item.current_mode = fixture.current_mode
                fixture_item.available_modes = fixture.available_modes
                fixture_item.layer = fixture.layer
                fixture_item.docked_to = getattr(fixture, 'docked_to', "")

                self.scene.addItem(fixture_item)
                self.fixtures[fixture.name] = fixture_item

        self.apply_layer_visibility()

        # Update spots
        if hasattr(self.config, 'spots'):
            for spot_name, spot_data in self.config.spots.items():
                spot_item = SpotItem(name=spot_name)
                x_px, y_px = self.meters_to_pixels(spot_data.x, spot_data.y)
                spot_item.setPos(x_px, y_px)
                # Load z_height from config (default to 0.0 for backwards compatibility)
                spot_item.z_height = getattr(spot_data, 'z', 0.0)

                self.scene.addItem(spot_item)
                self.spots[spot_name] = spot_item

                # Update spot counter
                try:
                    spot_number = int(spot_name.replace('Spot', ''))
                    self.spot_counter = max(self.spot_counter, spot_number + 1)
                except ValueError:
                    pass

    def save_positions_to_config(self):
        """Save current fixture positions and spot positions back to configuration"""
        # Save fixture positions
        for fixture_name, fixture_item in self.fixtures.items():
            # Find the corresponding fixture in config
            config_fixture = next((f for f in self.config.fixtures if f.name == fixture_name), None)
            if config_fixture:
                # Convert position from pixels to center-based meters
                pos = fixture_item.pos()
                x_m, y_m = self.pixels_to_meters(pos.x(), pos.y())

                # Update fixture properties directly
                config_fixture.x = x_m
                config_fixture.y = y_m
                config_fixture.z = fixture_item.z_height
                config_fixture.yaw = fixture_item.rotation_angle  # Use yaw for 2D rotation

                # Save orientation fields
                config_fixture.mounting = fixture_item.mounting
                config_fixture.pitch = fixture_item.pitch
                config_fixture.roll = fixture_item.roll
                config_fixture.orientation_uses_group_default = fixture_item.orientation_uses_group_default
                config_fixture.z_uses_group_default = fixture_item.z_uses_group_default
                config_fixture.layer = fixture_item.layer
                config_fixture.docked_to = getattr(fixture_item, 'docked_to', "")

        # Save spot positions
        for spot_name, spot_item in self.spots.items():
            if spot_name in self.config.spots:
                pos = spot_item.pos()
                x_m, y_m = self.pixels_to_meters(pos.x(), pos.y())
                self.config.spots[spot_name].x = x_m
                self.config.spots[spot_name].y = y_m
                self.config.spots[spot_name].z = spot_item.z_height

        # Save stage element positions (items hold their model directly;
        # rotation/label/layer are written by the item's own actions)
        for item in self.stage_element_items:
            pos = item.pos()
            x_m, y_m = self.pixels_to_meters(pos.x(), pos.y())
            item.element.x = x_m
            item.element.y = y_m

        # Emit signal to notify listeners (e.g., for TCP visualizer updates)
        self.fixtures_changed.emit()

    def set_active_layer(self, name):
        """Enter/leave active-layer editing mode (None leaves).

        While a layer is active, its fixtures stay fully interactive and
        every other fixture (other layers AND unassigned) ghosts: faint,
        unselectable, undraggable — visible enough to place the active
        layer's fixtures relative to them, locked so they can't be moved
        by accident.
        """
        if name and (not self.config or self.config.get_stage_layer(name) is None):
            name = None
        self.active_layer = name
        self.apply_layer_visibility()

    def apply_layer_visibility(self):
        """Show/hide fixture items according to their stage layer's
        visible flag, and apply active-layer ghosting. Invisible
        QGraphicsItems are excluded from itemAt / rubber-band hits, so
        hidden layers can't be selected or dragged by accident."""
        if not self.config:
            return
        active = self.active_layer
        if active and self.config.get_stage_layer(active) is None:
            # Layer was deleted underneath us.
            active = self.active_layer = None
        for fixture_item in self.fixtures.values():
            config_fixture = next(
                (f for f in self.config.fixtures if f.name == fixture_item.fixture_name),
                None
            )
            if config_fixture is not None:
                fixture_item.setVisible(self.config.is_fixture_visible(config_fixture))
                fixture_item.set_ghosted(
                    active is not None and config_fixture.layer != active
                )

        # Stage elements follow the same layer rules as fixtures:
        # hidden layer -> hidden, active-layer mode -> non-members ghost.
        for item in self.stage_element_items:
            layer = (self.config.get_stage_layer(item.element.layer)
                     if item.element.layer else None)
            visible = layer.visible if layer is not None else True
            item.setVisible(visible)
            item.set_ghosted(
                active is not None and item.element.layer != active
            )

    def add_stage_element(self, kind):
        """Place a catalog element at stage center; returns the model.

        Palette click-to-place. Everything happens in
        :meth:`add_stage_element_at` so the drag-and-drop path and this
        one cannot drift apart.
        """
        return self.add_stage_element_at(kind, 0.0, 0.0)

    def add_stage_element_at(self, kind, x_m=0.0, y_m=0.0):
        """Place a catalog element at (x_m, y_m); returns the model.

        Trusses are their own layer: placing one auto-creates a
        StageLayer (unique "Truss N" name, default hang height 4 m)
        that the truss defines; docked fixtures join that layer and
        its z_height is the hang height.

        Any other element joins the layer currently being edited (if
        any), so a placed element is never born ghosted.
        """
        from config.models import StageLayer
        from gui.stage_items import StageElementItem
        from utils.stage_element_catalog import is_truss, make_element
        element = make_element(kind, x=float(x_m), y=float(y_m))
        if not hasattr(self.config, 'stage_elements') or self.config.stage_elements is None:
            self.config.stage_elements = []

        if is_truss(kind):
            n = 1
            while self.config.get_stage_layer(f"Truss {n}") is not None:
                n += 1
            layer = StageLayer(name=f"Truss {n}", z_height=4.0)
            self.config.stage_layers.append(layer)
            element.layer = layer.name
            element.label = layer.name
        elif self.active_layer:
            element.layer = self.active_layer

        self.config.stage_elements.append(element)
        item = StageElementItem(element, self.pixels_per_meter)
        x_px, y_px = self.meters_to_pixels(element.x, element.y)
        item.setPos(x_px, y_px)
        self.scene.addItem(item)
        self.stage_element_items.append(item)
        self.apply_layer_visibility()
        self.stage_element_added.emit(element)
        self.fixtures_changed.emit()
        return element

    # ── Palette drag-and-drop ─────────────────────────────────────────

    def _dropped_element_kind(self, event) -> str:
        """The catalog kind of a palette drag, '' when it is some other
        drag (fixture drags, file drops) - those fall through to the
        QGraphicsView default so nothing existing breaks."""
        from utils.stage_element_catalog import CATALOG
        kind = element_kind_from_mime(event.mimeData())
        return kind if kind in CATALOG else ""

    def dragEnterEvent(self, event):
        if self.config is not None and self._dropped_element_kind(event):
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if self.config is not None and self._dropped_element_kind(event):
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event):
        """Drop a palette tile: create the element under the cursor."""
        kind = self._dropped_element_kind(event) if self.config is not None else ""
        if not kind:
            super().dropEvent(event)
            return
        scene_pos = self.mapToScene(event.position().toPoint())
        scene_pos = self.snap_to_grid_position(scene_pos)
        x_m, y_m = self.pixels_to_meters(scene_pos.x(), scene_pos.y())
        self.add_stage_element_at(kind, x_m, y_m)
        event.acceptProposedAction()

    def remove_stage_element(self, item):
        """Remove an element item and its model from the config.

        Removing a truss undocks its fixtures (they keep their layer,
        position and Z); the truss's layer itself stays - remove it via
        the layers panel if unwanted."""
        element = item.element
        if element.element_id:
            for fixture in getattr(self.config, 'fixtures', []) or []:
                if fixture.docked_to == element.element_id:
                    fixture.docked_to = ""
            for fixture_item in self.fixtures.values():
                if getattr(fixture_item, 'docked_to', "") == element.element_id:
                    fixture_item.docked_to = ""
        if item in self.stage_element_items:
            self.stage_element_items.remove(item)
        try:
            self.config.stage_elements.remove(element)
        except (AttributeError, ValueError):
            pass
        self.scene.removeItem(item)
        self.fixtures_changed.emit()

    # ── Truss docking ─────────────────────────────────────────────────

    def get_stage_element(self, element_id):
        return next(
            (e for e in (getattr(self.config, 'stage_elements', []) or [])
             if e.element_id == element_id), None)

    def _truss_item_at(self, scene_pos):
        """The truss element item whose (rotated, padded) footprint
        contains the scene position, or None."""
        from utils.stage_element_catalog import is_truss
        pad_px = 0.3 * self.pixels_per_meter
        for item in self.stage_element_items:
            element = item.element
            if not is_truss(element.kind) or not element.element_id:
                continue
            local = item.mapFromScene(scene_pos)
            # mapFromScene does NOT undo the paint-time rotation (the
            # item rotates in paint(), not via setRotation) - rotate
            # the local point into the truss frame ourselves.
            angle = radians(-element.rotation)
            lx = local.x() * cos(angle) - local.y() * sin(angle)
            ly = local.x() * sin(angle) + local.y() * cos(angle)
            half_w = element.width * self.pixels_per_meter / 2 + pad_px
            half_d = element.depth * self.pixels_per_meter / 2 + pad_px
            if abs(lx) <= half_w and abs(ly) <= half_d:
                return item
        return None

    def handle_fixture_drop(self, fixture_item):
        """Dock/undock on drop: released over a truss -> dock to it
        (join its layer, snap Z to the hang height, snap onto the truss
        axis for straight trusses); released elsewhere while docked ->
        undock (clear docking AND the truss's layer; position and Z
        stay). Manually assigned non-truss layers are never touched.
        """
        from utils.stage_element_catalog import is_truss  # noqa: F401 (doc)
        truss_item = self._truss_item_at(fixture_item.pos())
        was_docked = getattr(fixture_item, 'docked_to', "")

        if truss_item is not None:
            element = truss_item.element
            layer = self.config.get_stage_layer(element.layer)
            fixture_item.docked_to = element.element_id
            if layer is not None:
                fixture_item.layer = layer.name
                fixture_item.z_height = layer.z_height
                fixture_item.z_uses_group_default = False
            if element.kind == "truss-straight":
                fixture_item.setPos(self._project_onto_truss(
                    truss_item, fixture_item.pos()))
        elif was_docked:
            fixture_item.docked_to = ""
            truss = self.get_stage_element(was_docked)
            # Only clear the layer if it is still the truss's own layer
            # (the user may have reassigned manually since docking).
            if truss is not None and fixture_item.layer == truss.layer:
                fixture_item.layer = ""

        self.save_positions_to_config()
        self.apply_layer_visibility()

    def _project_onto_truss(self, truss_item, scene_pos):
        """Scene position snapped onto a straight truss's length axis,
        clamped to its span."""
        element = truss_item.element
        local = truss_item.mapFromScene(scene_pos)
        angle = radians(-element.rotation)
        lx = local.x() * cos(angle) - local.y() * sin(angle)
        half_w = element.width * self.pixels_per_meter / 2
        lx = max(-half_w, min(half_w, lx))
        ly = 0.0  # on the axis
        back = radians(element.rotation)
        x = lx * cos(back) - ly * sin(back)
        y = lx * sin(back) + ly * cos(back)
        return truss_item.mapToScene(QtCore.QPointF(x, y))

    def move_docked_fixtures(self, element, delta):
        """Carry docked fixtures along with their truss (delta in
        scene px). Called live from the truss item's drag."""
        if not element.element_id:
            return
        for fixture_item in self.fixtures.values():
            if getattr(fixture_item, 'docked_to', "") == element.element_id:
                fixture_item.setPos(fixture_item.pos() + delta)

    def set_truss_height(self, element, z_m):
        """Change a truss's hang height: updates its layer and snaps
        every fixture on that layer (docked or manually assigned)."""
        layer = self.config.get_stage_layer(element.layer)
        if layer is None:
            return
        layer.z_height = z_m
        for fixture in getattr(self.config, 'fixtures', []) or []:
            if fixture.layer == layer.name:
                fixture.z = z_m
                fixture.z_uses_group_default = False
        for fixture_item in self.fixtures.values():
            if getattr(fixture_item, 'layer', "") == layer.name:
                fixture_item.z_height = z_m
                fixture_item.z_uses_group_default = False
                fixture_item.update()
        self.save_positions_to_config()
        self.fixtures_changed.emit()

    def assign_selected_to_layer(self, layer_name):
        """Assign the selected fixtures to a stage layer ('' clears).

        A layer is a Z-plane: assignment snaps the fixture's Z to the
        layer's height (as an explicit per-fixture value). Clearing the
        assignment leaves Z untouched.
        """
        layer = self.config.get_stage_layer(layer_name) if (self.config and layer_name) else None
        for fixture_item in self.get_selected_fixtures():
            fixture_item.layer = layer_name if layer is not None else ""
            if layer is not None:
                fixture_item.z_height = layer.z_height
                fixture_item.z_uses_group_default = False
            fixture_item.update()
        self.save_positions_to_config()
        self.apply_layer_visibility()

    def set_snap_to_grid(self, enabled):
        """Enable or disable snap to grid"""
        self.snap_enabled = enabled
        if enabled:
            self.snap_all_fixtures_to_grid()

    def snap_to_grid_position(self, pos):
        """Convert a position to the nearest grid point if snapping is enabled"""
        if not self.snap_enabled:
            return pos

        # Convert position to center-based meters
        x_m, y_m = self.pixels_to_meters(pos.x(), pos.y())

        # Snap to nearest grid point
        x_m = round(x_m / self.grid_size_m) * self.grid_size_m
        y_m = round(y_m / self.grid_size_m) * self.grid_size_m

        # Convert back to pixels
        x_px, y_px = self.meters_to_pixels(x_m, y_m)
        return QtCore.QPointF(x_px, y_px)

    def snap_all_fixtures_to_grid(self):
        """Snap all existing fixtures to the grid"""
        if not self.snap_enabled:
            return

        for fixture in self.fixtures.values():
            current_pos = fixture.pos()
            snapped_pos = self.snap_to_grid_position(current_pos)
            fixture.setPos(snapped_pos)

        self.save_positions_to_config()

    def add_spot(self, x_m=0.0, y_m=0.0, z_m=0.0):
        """Add a new spot to the stage

        Args:
            x_m: X position in meters (0 = center)
            y_m: Y position in meters (0 = center)
            z_m: Z height in meters (default 0.0)
        """
        spot_name = f"Spot{self.spot_counter}"
        spot = SpotItem(name=spot_name)
        spot.z_height = z_m

        # Convert center-based meters to pixels
        x_px, y_px = self.meters_to_pixels(x_m, y_m)
        spot.setPos(x_px, y_px)

        self.scene.addItem(spot)
        self.spots[spot_name] = spot
        self.spot_counter += 1

        # Add to configuration with center-based coordinates
        if self.config:
            self.config.spots[spot_name] = Spot(
                name=spot_name,
                x=x_m,
                y=y_m,
                z=z_m
            )
        self.spots_changed.emit()
        return spot

    def remove_spot(self, name: str) -> bool:
        """Remove a single mark by name (scene, model and config)."""
        spot = self.spots.pop(name, None)
        if spot is None:
            return False
        self.scene.removeItem(spot)
        if self.config and name in getattr(self.config, "spots", {}):
            del self.config.spots[name]
        self.spots_changed.emit()
        return True

    def rename_spot(self, old_name: str, new_name: str) -> bool:
        """Rename a mark. Returns False on empty/duplicate/unknown name."""
        new_name = (new_name or "").strip()
        if not new_name or old_name not in self.spots:
            return False
        if new_name == old_name:
            return True
        if new_name in self.spots:
            return False  # would collide with another mark
        spot = self.spots.pop(old_name)
        spot.prepareGeometryChange()  # boundingRect depends on the label
        spot.name = new_name
        self.spots[new_name] = spot
        spot.update()
        if self.config and old_name in getattr(self.config, "spots", {}):
            # Rebuild in place so the renamed mark keeps its position in the
            # list instead of jumping to the bottom.
            self.config.spots[old_name].name = new_name
            self.config.spots = {
                (new_name if key == old_name else key): value
                for key, value in self.config.spots.items()
            }
        self.spots_changed.emit()
        return True

    def remove_selected_items(self):
        """Remove selected items from the stage"""
        removed_spot = False
        for item in self.scene.selectedItems():
            if isinstance(item, FixtureItem):
                self.scene.removeItem(item)
                if item.fixture_name in self.fixtures:
                    del self.fixtures[item.fixture_name]
            elif isinstance(item, SpotItem):
                self.scene.removeItem(item)
                if item.name in self.spots:
                    del self.spots[item.name]
                    if self.config:
                        del self.config.spots[item.name]
                    removed_spot = True

                    # Update spot counter if necessary
                    try:
                        removed_number = int(item.name.replace('Spot', ''))
                        if removed_number == self.spot_counter - 1:
                            # If we removed the last spot, decrease the counter
                            self.spot_counter = removed_number
                    except ValueError:
                        pass  # If the name doesn't follow the SpotX format, ignore
        if removed_spot:
            self.spots_changed.emit()

    def updateStage(self, width_m=None, depth_m=None):
        """Update stage dimensions"""
        if width_m is not None:
            self.stage_width_m = width_m
        if depth_m is not None:
            self.stage_depth_m = depth_m

        # Convert to pixels
        width_px = self.stage_width_m * self.pixels_per_meter
        depth_px = self.stage_depth_m * self.pixels_per_meter

        # Calculate total size including padding
        total_width = width_px + (2 * self.padding)
        total_depth = depth_px + (2 * self.padding)

        # Update scene rect with padding
        self.scene.setSceneRect(0, 0, total_width, total_depth)

        # Re-fit so a dimension change always lands on a clean baseline.
        # User-applied zoom resets when the stage is resized — same
        # behaviour as the historical ``fitInView`` call.
        self.fit_to_stage()

    def fit_to_stage(self):
        """Reset zoom + pan so the full stage fits in the viewport.

        Public so the Stage tab's ``Fit View`` button and ``F`` shortcut
        can call it directly. Also used by ``updateStage`` whenever the
        scene rect changes.
        """
        self.resetTransform()
        self._zoom = 1.0
        self.fitInView(
            self.scene.sceneRect(),
            QtCore.Qt.AspectRatioMode.KeepAspectRatio,
        )
        self.viewport().update()

    def updateGrid(self, visible=None, size_m=None):
        """Update grid properties"""
        if visible is not None:
            self.grid_visible = visible
        if size_m is not None:
            self.grid_size_m = size_m
        self.viewport().update()

    def drawBackground(self, painter, rect):
        """Draw stage and grid with dimension labels.

        Colours come from QSS via the ``stageOutlineColor`` /
        ``stageFillColor`` / ``stageGridColor`` qproperties — see the
        ``StageView { ... }`` block in each theme stylesheet. Centre
        axes (red/blue) below stay hardcoded; they're "data" colours,
        not theme chrome.
        """
        super().drawBackground(painter, rect)

        # Convert stage dimensions to pixels and ensure they're integers
        width_px = int(self.stage_width_m * self.pixels_per_meter)
        depth_px = int(self.stage_depth_m * self.pixels_per_meter)

        # Calculate center position in pixels
        center_x_px = self.padding + width_px / 2
        center_y_px = self.padding + depth_px / 2

        # Draw stage outline with padding
        painter.setPen(QtGui.QPen(self._stage_outline_color, 2))
        painter.setBrush(QtGui.QBrush(self._stage_fill_color))
        painter.drawRect(
            self.padding,
            self.padding,
            width_px,
            depth_px
        )

        # Draw grid if enabled
        if self.grid_visible:
            grid_size_px = int(self.grid_size_m * self.pixels_per_meter)

            # Draw regular grid lines (theme-aware secondary tone)
            painter.setPen(QtGui.QPen(self._stage_grid_color, 1))

            # Draw vertical grid lines
            for x in range(self.padding, width_px + self.padding + 1, grid_size_px):
                painter.drawLine(x, self.padding, x, depth_px + self.padding)

            # Draw horizontal grid lines
            for y in range(self.padding, depth_px + self.padding + 1, grid_size_px):
                painter.drawLine(self.padding, y, width_px + self.padding, y)

            # Centre axes. Hues still match the 3D visualizer's X=red /
            # Y=blue so the two views stay cross-readable, but per the
            # North Star stage plan (card 5a) they are quiet 1px dashed
            # marks instead of the old loud 2px lines.
            x_axis = QtGui.QColor(255, 80, 80)
            x_axis.setAlpha(90)
            pen = QtGui.QPen(x_axis, 1, QtCore.Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.drawLine(self.padding, int(center_y_px), width_px + self.padding, int(center_y_px))

            y_axis = QtGui.QColor(80, 80, 255)
            y_axis.setAlpha(90)
            pen = QtGui.QPen(y_axis, 1, QtCore.Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.drawLine(int(center_x_px), self.padding, int(center_x_px), depth_px + self.padding)

        # AUDIENCE marker at the front edge, drawn along the BOTTOM band
        # of the plan (negative Y = front now maps to the bottom).
        try:
            from gui.typography import mono_font as _mono_font
            painter.setFont(_mono_font(8, tracking_em=0.2))
        except Exception:
            pass
        painter.setPen(QtGui.QPen(self._stage_label_color, 1))
        painter.drawText(
            QtCore.QRect(self.padding, depth_px + self.padding + 4,
                         width_px, self.padding - 4),
            QtCore.Qt.AlignmentFlag.AlignHCenter |
            QtCore.Qt.AlignmentFlag.AlignBottom,
            "A U D I E N C E")

        # Draw dimension labels
        self._draw_dimension_labels(painter, width_px, depth_px, center_x_px, center_y_px)

    def _draw_dimension_labels(self, painter, width_px, depth_px, center_x_px, center_y_px):
        """Draw dimension labels at the edges of the stage"""
        # Mono readout font per the design system (was hardcoded Arial).
        from gui.typography import mono_font
        painter.setFont(mono_font(7))
        painter.setPen(QtGui.QPen(self._stage_label_color, 1))

        # Calculate label interval (use 1m intervals, or 0.5m for small stages)
        label_interval_m = 1.0
        if self.stage_width_m <= 4 or self.stage_depth_m <= 4:
            label_interval_m = 0.5

        label_interval_px = int(label_interval_m * self.pixels_per_meter)

        # Draw X-axis labels (TOP edge) - from center outward. The plan
        # was flipped so the audience sits at the bottom; the X meter
        # numbers move up into the top padding band (where AUDIENCE used
        # to sit) and the AUDIENCE marker owns the bottom band.
        half_width_m = self.stage_width_m / 2
        x_label_y = self.padding - 20  # inside the top padding band

        # Draw labels from center to the right
        x_m = 0.0
        while x_m <= half_width_m + 0.01:  # Small epsilon for floating point
            x_px = center_x_px + x_m * self.pixels_per_meter
            if x_px <= self.padding + width_px + 1:
                label = f"{x_m:.1f}" if x_m != int(x_m) else f"{int(x_m)}"
                # Draw at top
                painter.drawText(
                    int(x_px) - 15,
                    x_label_y,
                    30, 15,
                    QtCore.Qt.AlignmentFlag.AlignCenter,
                    label
                )
            x_m += label_interval_m

        # Draw labels from center to the left (negative values)
        x_m = -label_interval_m
        while x_m >= -half_width_m - 0.01:
            x_px = center_x_px + x_m * self.pixels_per_meter
            if x_px >= self.padding - 1:
                label = f"{x_m:.1f}" if x_m != int(x_m) else f"{int(x_m)}"
                # Draw at top
                painter.drawText(
                    int(x_px) - 15,
                    x_label_y,
                    30, 15,
                    QtCore.Qt.AlignmentFlag.AlignCenter,
                    label
                )
            x_m -= label_interval_m

        # Draw Y-axis labels (left edge) - from center outward
        half_depth_m = self.stage_depth_m / 2

        # Draw labels from center to the top (positive Y = back). The Y
        # axis is flipped, so positive Y now maps toward the top edge.
        y_m = 0.0
        while y_m <= half_depth_m + 0.01:
            y_px = center_y_px - y_m * self.pixels_per_meter
            if y_px >= self.padding - 1:
                label = f"{y_m:.1f}" if y_m != int(y_m) else f"{int(y_m)}"
                # Draw at left
                painter.drawText(
                    2,
                    int(y_px) - 8,
                    self.padding - 4, 16,
                    QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter,
                    label
                )
            y_m += label_interval_m

        # Draw labels from center to the bottom (negative Y = front /
        # audience). The Y axis is flipped, so negative Y maps downward.
        y_m = -label_interval_m
        while y_m >= -half_depth_m - 0.01:
            y_px = center_y_px - y_m * self.pixels_per_meter
            if y_px <= self.padding + depth_px + 1:
                label = f"{y_m:.1f}" if y_m != int(y_m) else f"{int(y_m)}"
                # Draw at left
                painter.drawText(
                    2,
                    int(y_px) - 8,
                    self.padding - 4, 16,
                    QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter,
                    label
                )
            y_m -= label_interval_m

    def resizeEvent(self, event):
        """Handle window resize"""
        super().resizeEvent(event)
        self.updateStage()

    def changeEvent(self, event):
        """Repaint when the active QSS theme changes.

        ``ThemeManager.apply`` re-polishes every widget after swapping
        the stylesheet, which fires ``QEvent.StyleChange`` here. The
        ``qproperty-*`` setters already nudge the viewport when QSS
        pushes new colours, but theme switches that don't actually
        change a colour (e.g. flipping back to the same theme) still
        benefit from a defensive repaint — and it costs nothing.
        """
        super().changeEvent(event)
        if event.type() == QtCore.QEvent.Type.StyleChange:
            self._on_theme_color_changed()

    def mousePressEvent(self, event):
        """Handle mouse press for rubber band selection and context menu."""
        # Space + left-drag pans the view. Intercepted before any of the
        # rubber-band / item-selection / context-menu branches so the
        # pan gesture wins cleanly even when the press lands on a
        # fixture (otherwise Space+drag on a hanging MH would start a
        # fixture-drag instead of a pan).
        if (event.button() == QtCore.Qt.MouseButton.LeftButton
                and self._space_held):
            self._panning = True
            self._pan_anchor = event.pos()
            self.viewport().setCursor(QtCore.Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return

        # Check if clicking on empty space (not on an item)
        item_at_pos = self.itemAt(event.pos())

        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            if item_at_pos is None:
                # Start rubber band selection on empty space
                self._rubber_band_origin = event.pos()
                if self._rubber_band is None:
                    self._rubber_band = QtWidgets.QRubberBand(
                        QtWidgets.QRubberBand.Shape.Rectangle, self
                    )
                self._rubber_band.setGeometry(QtCore.QRect(self._rubber_band_origin, QtCore.QSize()))
                self._rubber_band.show()
                self._is_rubber_band_selecting = True

                # Clear selection if not holding Ctrl
                if not (event.modifiers() & QtCore.Qt.KeyboardModifier.ControlModifier):
                    self.scene.clearSelection()
            else:
                # Clicking on an item - let default behavior handle it
                # But handle Ctrl+click for toggle selection
                if event.modifiers() & QtCore.Qt.KeyboardModifier.ControlModifier:
                    if isinstance(item_at_pos, (FixtureItem, SpotItem)):
                        item_at_pos.setSelected(not item_at_pos.isSelected())
                        event.accept()
                        return

        elif event.button() == QtCore.Qt.MouseButton.RightButton:
            # Show context menu
            self._show_context_menu(event.pos())
            event.accept()
            return

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        """Handle mouse move for rubber band selection or panning."""
        if self._panning:
            # Translate the view's transform directly. ``delta`` is in
            # widget pixels; QGraphicsView.translate expects scene
            # units, so divide by the current scale (m11 == m22 since
            # we only do uniform zoom).
            #
            # AnchorUnderMouse (set in __init__ for cursor-anchored
            # zooming) also fires on translate() and tries to keep the
            # point under the cursor fixed in the viewport — the exact
            # opposite of what a pan should do. Without swapping to
            # NoAnchor for the translate, the resulting pan speed
            # scales with zoom level (slower when zoomed out, way too
            # fast when zoomed in) because the anchor compensation
            # adds back a scale-dependent offset on top of our shift.
            delta = event.pos() - self._pan_anchor
            self._pan_anchor = event.pos()
            scale = self.transform().m11()
            if scale != 0:
                prev_anchor = self.transformationAnchor()
                self.setTransformationAnchor(
                    QtWidgets.QGraphicsView.ViewportAnchor.NoAnchor
                )
                self.translate(delta.x() / scale, delta.y() / scale)
                self.setTransformationAnchor(prev_anchor)
            event.accept()
            return
        if self._is_rubber_band_selecting and self._rubber_band is not None:
            self._rubber_band.setGeometry(
                QtCore.QRect(self._rubber_band_origin, event.pos()).normalized()
            )
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        """Handle mouse release to complete rubber band selection or pan."""
        if self._panning and event.button() == QtCore.Qt.MouseButton.LeftButton:
            self._panning = False
            self._pan_anchor = None
            # Back to OpenHand if Space is still held, else default cursor.
            if self._space_held:
                self.viewport().setCursor(QtCore.Qt.CursorShape.OpenHandCursor)
            else:
                self.viewport().unsetCursor()
            event.accept()
            return
        if event.button() == QtCore.Qt.MouseButton.LeftButton and self._is_rubber_band_selecting:
            if self._rubber_band is not None:
                # Get the selection rectangle in scene coordinates
                rubber_rect = self._rubber_band.geometry()
                scene_rect = self.mapToScene(rubber_rect).boundingRect()

                # Select all items within the rectangle
                items_in_rect = self.scene.items(scene_rect)
                for item in items_in_rect:
                    if isinstance(item, (FixtureItem, SpotItem)):
                        item.setSelected(True)

                self._rubber_band.hide()
            self._is_rubber_band_selecting = False
            self._rubber_band_origin = None
        else:
            super().mouseReleaseEvent(event)

    def _show_context_menu(self, pos):
        """Show context menu for selected fixtures."""
        # Get selected fixture items
        selected_fixtures = [
            item for item in self.scene.selectedItems()
            if isinstance(item, FixtureItem)
        ]

        if not selected_fixtures:
            # Check if right-clicking on a fixture that's not selected
            item_at_pos = self.itemAt(pos)
            if isinstance(item_at_pos, FixtureItem):
                # Select this fixture
                self.scene.clearSelection()
                item_at_pos.setSelected(True)
                selected_fixtures = [item_at_pos]

        if not selected_fixtures:
            return  # No fixtures to show menu for

        # Create context menu
        menu = QtWidgets.QMenu(self)

        # Set Orientation action
        orientation_action = menu.addAction("Set Orientation...")
        orientation_action.setEnabled(len(selected_fixtures) > 0)

        # Assign to Layer submenu — only offered once layers exist.
        layer_actions = {}
        clear_layer_action = None
        if self.config and self.config.stage_layers:
            layer_menu = menu.addMenu("Assign to Layer")
            for layer in self.config.stage_layers:
                action = layer_menu.addAction(f"{layer.name} ({layer.z_height:g} m)")
                layer_actions[action] = layer.name
            layer_menu.addSeparator()
            clear_layer_action = layer_menu.addAction("None")

        menu.addSeparator()

        # Select All action
        select_all_action = menu.addAction("Select All Fixtures")

        # Deselect All action
        deselect_action = menu.addAction("Deselect All")

        # Execute menu
        action = menu.exec(self.mapToGlobal(pos))

        if action == orientation_action:
            # Emit signal to open orientation dialog
            self.set_orientation_requested.emit(selected_fixtures)
        elif action in layer_actions:
            self.assign_selected_to_layer(layer_actions[action])
        elif clear_layer_action is not None and action == clear_layer_action:
            self.assign_selected_to_layer("")
        elif action == select_all_action:
            for fixture_item in self.fixtures.values():
                fixture_item.setSelected(True)
        elif action == deselect_action:
            self.scene.clearSelection()

    def wheelEvent(self, event):
        """Handle wheel for: Shift+wheel ⇒ multi-select Z-height, plain
        wheel ⇒ zoom around the cursor.

        Single-fixture Z-height adjustment is still handled inside the
        individual ``FixtureItem`` (the ``super().wheelEvent`` path); only
        plain wheel on empty stage area / multi-select-without-Shift
        flows through to zoom.
        """
        # Check if we have multiple fixtures selected
        selected_fixtures = [
            item for item in self.scene.selectedItems()
            if isinstance(item, FixtureItem)
        ]

        # If Shift is held and we have selected fixtures, adjust Z-height for all
        if (event.modifiers() & QtCore.Qt.KeyboardModifier.ShiftModifier) and len(selected_fixtures) > 1:
            delta = event.angleDelta().y() / 120.0
            z_step = 0.1

            for fixture_item in selected_fixtures:
                if delta > 0:
                    fixture_item.z_height = max(0, fixture_item.z_height + z_step)
                else:
                    fixture_item.z_height = max(0, fixture_item.z_height - z_step)
                # Mark that user has set a custom Z value
                fixture_item.z_uses_group_default = False
                fixture_item.update()

            # Save changes
            self.save_positions_to_config()
            event.accept()
            return

        # If the wheel happened over a single fixture, let the item's
        # own wheelEvent (which adjusts that fixture's Z) win. Otherwise
        # treat the wheel as a zoom request — that covers the empty-
        # stage case (most common) and the multi-select-without-Shift
        # case (no item-level handler).
        item_at_pos = self.itemAt(event.position().toPoint())
        if (isinstance(item_at_pos, FixtureItem)
                and not item_at_pos.ghosted
                and len(selected_fixtures) <= 1):
            super().wheelEvent(event)
            return

        # Zoom around cursor. AnchorUnderMouse (set in __init__) keeps
        # the point under the pointer fixed in screen space.
        delta = event.angleDelta().y()
        if delta == 0:
            return
        factor = 1.15 if delta > 0 else (1.0 / 1.15)
        new_zoom = self._zoom * factor
        new_zoom = max(self._min_zoom, min(self._max_zoom, new_zoom))
        # Compute the actual factor we'll apply after clamping so
        # repeated wheel events at the limit don't drift the transform
        # away from the recorded zoom level.
        applied = new_zoom / self._zoom
        if applied != 1.0:
            self.scale(applied, applied)
            self._zoom = new_zoom
        event.accept()

    # ── Zoom / pan input ──────────────────────────────────────────────

    def keyPressEvent(self, event):
        """Track Space-held state to enable click-drag panning.

        Auto-repeat events are ignored so holding Space doesn't spam
        cursor changes. Other keys (including the global ``F`` shortcut
        for fit-view, which is owned by StageTab) fall through to the
        default handler.
        """
        if event.key() == QtCore.Qt.Key.Key_Space and not event.isAutoRepeat():
            self._space_held = True
            # OpenHand = "you can grab"; ClosedHand only shows during the
            # actual drag (set in mousePressEvent).
            if not self._panning:
                self.viewport().setCursor(QtCore.Qt.CursorShape.OpenHandCursor)
            event.accept()
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if event.key() == QtCore.Qt.Key.Key_Space and not event.isAutoRepeat():
            self._space_held = False
            if not self._panning:
                self.viewport().unsetCursor()
            event.accept()
            return
        super().keyReleaseEvent(event)

    def focusOutEvent(self, event):
        """Drop Space-held state when focus leaves the view — otherwise
        Alt-Tabbing away while holding Space leaves us in panning-armed
        mode with no key release ever arriving."""
        if self._space_held:
            self._space_held = False
            if not self._panning:
                self.viewport().unsetCursor()
        super().focusOutEvent(event)

    def get_selected_fixtures(self):
        """Get list of currently selected FixtureItem objects."""
        return [
            item for item in self.scene.selectedItems()
            if isinstance(item, FixtureItem)
        ]

    def select_group_fixtures(self, group_name):
        """Select every selectable fixture of a group (clears first).

        Ghosted (off-active-layer) and hidden items are skipped: they
        carry no ItemIsSelectable flag, so selecting them would be a
        no-op that silently reports the wrong selection count.
        """
        self.scene.clearSelection()
        selected = []
        for fixture_item in self.fixtures.values():
            if getattr(fixture_item, 'group', "") != group_name:
                continue
            if not fixture_item.isVisible() or fixture_item.ghosted:
                continue
            fixture_item.setSelected(True)
            selected.append(fixture_item)
        return selected

