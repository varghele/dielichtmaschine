# timeline_ui/colour_block_dialog.py
# Dialog for editing colour sublane block parameters
# Simplified version with presets, hex picker, RGBW sliders, and optional color wheel

from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
                             QGroupBox, QSlider, QSpinBox, QLabel,
                             QDialogButtonBox, QWidget, QPushButton,
                             QComboBox, QFrame, QGridLayout, QLineEdit,
                             QScrollArea)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from config.models import ColourBlock
from gui.typography import mono_font

#: role combo sentinel labels (v1.5 palette roles)
LITERAL_LABEL = "Literal colour (no role)"
NEW_ROLE_LABEL = "New role..."


def _active_tokens() -> dict:
    """Token dict of the theme currently applied to the app.

    Same stylesheet sniff as gui/tabs/stage_tab.py: the light theme's
    window color only ever appears in the light stylesheet. The colour
    swatches below are *data* colors (the user's chosen colour), so only
    their neutral chrome (borders) is sourced from the theme.
    """
    from PyQt6.QtWidgets import QApplication
    from gui.theme_tokens import THEMES

    app = QApplication.instance()
    qss = app.styleSheet() if app is not None else ""
    light = THEMES.get("light")
    if light is not None and light["window"] in qss:
        return light
    return THEMES["dark"]


class ColorPreviewWidget(QFrame):
    """Widget showing color preview."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(60)
        self.setFrameShape(QFrame.Shape.Box)
        self._border = _active_tokens()["border"]
        self.setStyleSheet(
            f"background-color: #000000; border: 1px solid {self._border};")
        self._color = QColor(0, 0, 0)

    def set_color(self, color: QColor):
        """Update the preview color."""
        self._color = color
        self.setStyleSheet(
            f"background-color: {color.name()}; "
            f"border: 1px solid {self._border};")

    def color(self) -> QColor:
        return self._color


class ColorPresetButton(QPushButton):
    """Button for quick color selection.

    The fill is a *data* color (a standard light colour); only the
    neutral border comes from the active theme.
    """

    def __init__(self, name: str, color: QColor, parent=None):
        super().__init__(name, parent)
        self.color_value = color
        self.setFixedHeight(35)
        self.setMinimumWidth(70)
        tokens = _active_tokens()
        border = tokens["border"]
        accent = tokens["accent"]
        # Set button style with the color
        text_color = "#000000" if color.lightness() > 128 else "#ffffff"
        self.setStyleSheet(f"""
            QPushButton {{
                background-color: {color.name()};
                color: {text_color};
                border: 1px solid {border};
                border-radius: 0px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                border: 1px solid {accent};
            }}
            QPushButton:pressed {{
                border: 2px solid {accent};
            }}
        """)


class PaletteEditorDialog(QDialog):
    """Edit the song's colour palette (role -> RGB).

    Small role list with a swatch button per row (QColorDialog) plus
    add/remove. On accept it writes ``Song.palette`` and calls
    ``song.apply_palette()`` so every role-tagged block in the song
    re-resolves immediately - changing "primary" re-skins the whole
    song, which is the point of the indirection (v1.5 design doc 4.4).
    """

    def __init__(self, song, parent=None):
        super().__init__(parent)
        self.song = song
        self.setWindowTitle("Edit Palette")
        self.setMinimumWidth(380)
        self._rows = []   # (name_edit, swatch_btn, remove_btn, container)

        layout = QVBoxLayout(self)
        hint = QLabel(
            "Roles resolve to colours per song. Blocks tagged with a "
            "role re-resolve when the palette changes; literal blocks "
            "are never touched.")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self._rows_layout = QVBoxLayout()
        self._rows_layout.setSpacing(4)
        layout.addLayout(self._rows_layout)

        add_btn = QPushButton("Add Role")
        add_btn.clicked.connect(lambda: self.add_role("", (255, 255, 255)))
        layout.addWidget(add_btn)
        layout.addStretch()

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        for role, rgb in (song.palette or {}).items():
            self.add_role(role, tuple(rgb))

    # -- rows (plain methods so tests drive them without mouse events) --

    def add_role(self, name: str, rgb: tuple) -> int:
        """Append a role row; returns its index."""
        container = QWidget()
        row = QHBoxLayout(container)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)

        name_edit = QLineEdit(name)
        name_edit.setPlaceholderText("role name (e.g. primary)")
        row.addWidget(name_edit, 1)

        swatch = QPushButton()
        swatch.setFixedSize(48, 24)
        swatch.clicked.connect(lambda _=False, c=container:
                               self._pick_colour(c))
        row.addWidget(swatch)

        remove = QPushButton("Remove")
        remove.clicked.connect(lambda _=False, c=container:
                               self._remove_row(c))
        row.addWidget(remove)

        self._rows_layout.addWidget(container)
        self._rows.append((name_edit, swatch, remove, container))
        self._set_swatch(swatch, rgb)
        return len(self._rows) - 1

    def _set_swatch(self, swatch: QPushButton, rgb: tuple) -> None:
        swatch.rgb = (int(rgb[0]), int(rgb[1]), int(rgb[2]))
        border = _active_tokens()["border"]
        swatch.setStyleSheet(
            f"QPushButton {{ background-color: "
            f"rgb({swatch.rgb[0]}, {swatch.rgb[1]}, {swatch.rgb[2]}); "
            f"border: 1px solid {border}; border-radius: 0px; }}")

    def set_role_color(self, index: int, rgb: tuple) -> None:
        self._set_swatch(self._rows[index][1], rgb)

    def remove_role(self, index: int) -> None:
        self._remove_row(self._rows[index][3])

    def _remove_row(self, container) -> None:
        for i, (_, _, _, c) in enumerate(self._rows):
            if c is container:
                self._rows.pop(i)
                self._rows_layout.removeWidget(container)
                container.deleteLater()
                return

    def _pick_colour(self, container) -> None:
        from PyQt6.QtWidgets import QColorDialog
        for name_edit, swatch, _, c in self._rows:
            if c is container:
                current = QColor(*swatch.rgb)
                color = QColorDialog.getColor(initial=current, parent=self)
                if color.isValid():
                    self._set_swatch(
                        swatch, (color.red(), color.green(), color.blue()))
                return

    def palette(self) -> dict:
        """Role -> [r, g, b] from the current rows (blank names skipped)."""
        result = {}
        for name_edit, swatch, _, _ in self._rows:
            role = name_edit.text().strip()
            if role:
                result[role] = list(swatch.rgb)
        return result

    def accept(self):
        """Write the palette to the song and re-resolve tagged blocks."""
        self.song.palette = self.palette()
        self.song.apply_palette()
        super().accept()


class ColourBlockDialog(QDialog):
    """Dialog for editing colour sublane block parameters.

    Simplified UI with:
    - Quick preset buttons for standard colors
    - Hex color picker
    - RGBW sliders
    - Optional color wheel (if fixture supports it)
    """

    # Standard light color presets (name, R, G, B, W values)
    PRESET_COLORS = [
        ("Red", 255, 0, 0, 0),
        ("Green", 0, 255, 0, 0),
        ("Blue", 0, 0, 255, 0),
        ("White", 0, 0, 0, 255),  # Use W channel for white
        ("Amber", 255, 100, 0, 0),
        ("UV", 75, 0, 130, 0),
        ("Lime", 180, 255, 0, 0),
        ("Yellow", 255, 255, 0, 0),
        ("Cyan", 0, 255, 255, 0),
        ("Magenta", 255, 0, 255, 0),
        ("Orange", 255, 165, 0, 0),
        ("Pink", 255, 105, 180, 0),
    ]

    def __init__(self, block: ColourBlock, color_wheel_options: list = None,
                 parent=None, song=None):
        """Create the colour block dialog.

        Args:
            block: ColourBlock to edit
            color_wheel_options: Optional list of (name, dmx_value, hex_color) tuples
                                 from fixture definition. If provided, shows color wheel selector.
            parent: Parent widget
            song: Optional Song owning this block (v1.5 palette roles).
                  Provides the role list and enables EDIT PALETTE...;
                  without it, only literal + free-text roles work.
        """
        super().__init__(parent)
        self.block = block
        self.song = song
        self.color_wheel_options = color_wheel_options or []

        self.setWindowTitle("Edit Colour Block")
        self.setMinimumWidth(500)
        self.setMinimumHeight(650)

        self.setup_ui()
        self.load_current_values()
        self._update_preview_from_sliders()

    def setup_ui(self):
        main_layout = QVBoxLayout(self)

        # Create scroll area for the content
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll_widget = QWidget()
        layout = QVBoxLayout(scroll_widget)

        # Timing info (read-only display)
        timing_group = QGroupBox("Timing")
        timing_layout = QFormLayout()

        self.start_label = QLabel()
        self.end_label = QLabel()
        self.duration_label = QLabel()
        timing_layout.addRow("Start:", self.start_label)
        timing_layout.addRow("End:", self.end_label)
        timing_layout.addRow("Duration:", self.duration_label)

        timing_group.setLayout(timing_layout)
        layout.addWidget(timing_group)

        # Color preview and hex picker
        preview_group = QGroupBox("Color Preview")
        preview_layout = QVBoxLayout()

        self.color_preview = ColorPreviewWidget()
        preview_layout.addWidget(self.color_preview)

        # Hex picker row
        hex_layout = QHBoxLayout()
        self.pick_color_btn = QPushButton("Pick Color...")
        self.pick_color_btn.clicked.connect(self._open_color_picker)
        self.hex_label = QLabel("#000000")
        self.hex_label.setFont(mono_font(11))
        hex_layout.addWidget(self.pick_color_btn)
        hex_layout.addWidget(self.hex_label)
        hex_layout.addStretch()
        preview_layout.addLayout(hex_layout)

        preview_group.setLayout(preview_layout)
        layout.addWidget(preview_group)

        # Palette role (v1.5): the block can carry a role instead of
        # being a pure literal; Song.apply_palette() re-resolves tagged
        # blocks when the palette changes.
        role_group = QGroupBox("Palette Role")
        role_layout = QHBoxLayout()

        self.role_combo = QComboBox()
        self._rebuild_role_combo()
        self.role_combo.currentIndexChanged.connect(self._on_role_changed)
        role_layout.addWidget(self.role_combo, 1)

        self.new_role_edit = QLineEdit()
        self.new_role_edit.setPlaceholderText("new role name")
        self.new_role_edit.setVisible(False)
        role_layout.addWidget(self.new_role_edit, 1)

        self.edit_palette_btn = QPushButton("Edit Palette...")
        self.edit_palette_btn.clicked.connect(self._edit_palette)
        if self.song is None:
            self.edit_palette_btn.setEnabled(False)
            self.edit_palette_btn.setToolTip(
                "The song owning this block could not be resolved; "
                "roles can still be typed, the palette is edited from "
                "the song's timeline.")
        role_layout.addWidget(self.edit_palette_btn)

        role_group.setLayout(role_layout)
        layout.addWidget(role_group)

        # Quick preset buttons
        preset_group = QGroupBox("Quick Presets")
        preset_layout = QGridLayout()
        preset_layout.setSpacing(5)

        self.preset_buttons = []
        for i, (name, r, g, b, w) in enumerate(self.PRESET_COLORS):
            color = QColor(r, g, b)
            btn = ColorPresetButton(name, color)
            btn.clicked.connect(lambda checked, r=r, g=g, b=b, w=w: self._apply_preset(r, g, b, w))
            self.preset_buttons.append(btn)
            row = i // 4
            col = i % 4
            preset_layout.addWidget(btn, row, col)

        preset_group.setLayout(preset_layout)
        layout.addWidget(preset_group)

        # Color wheel (only if fixture has one)
        if self.color_wheel_options:
            wheel_group = QGroupBox("Color Wheel")
            wheel_layout = QFormLayout()

            self.wheel_combo = QComboBox()
            for name, dmx_value, hex_color in self.color_wheel_options:
                self.wheel_combo.addItem(name, (dmx_value, hex_color))

            self.wheel_combo.currentIndexChanged.connect(self._on_wheel_changed)
            wheel_layout.addRow("Position:", self.wheel_combo)

            wheel_group.setLayout(wheel_layout)
            layout.addWidget(wheel_group)

        # RGBW sliders
        rgbw_group = QGroupBox("RGBW Values")
        rgbw_layout = QFormLayout()

        # Create sliders for R, G, B, W. The sliders adopt the themed
        # look (accent handle); the channel is named by the row label.
        self.sliders = {}
        for channel, label in [("red", "Red"),
                               ("green", "Green"),
                               ("blue", "Blue"),
                               ("white", "White")]:
            row = QHBoxLayout()
            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setRange(0, 255)

            spinbox = QSpinBox()
            spinbox.setRange(0, 255)
            spinbox.setFixedWidth(60)

            slider.valueChanged.connect(spinbox.setValue)
            spinbox.valueChanged.connect(slider.setValue)
            slider.valueChanged.connect(self._update_preview_from_sliders)

            row.addWidget(slider, 1)
            row.addWidget(spinbox)

            self.sliders[channel] = (slider, spinbox)
            rgbw_layout.addRow(f"{label}:", row)

        rgbw_group.setLayout(rgbw_layout)
        layout.addWidget(rgbw_group)

        # Add stretch to push content to top
        layout.addStretch()

        # Set up scroll area
        scroll.setWidget(scroll_widget)
        main_layout.addWidget(scroll)

        # Dialog buttons (outside scroll area)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.ok_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.ok_button.setProperty("role", "primary")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        main_layout.addWidget(buttons)

    # -- palette role (v1.5) ------------------------------------------------

    def _rebuild_role_combo(self, keep: str = None):
        """Literal + one entry per Song.palette key + New role...
        The block's own role is always listed (a role can outlive its
        palette entry). itemData carries the raw role; the New role
        sentinel carries None."""
        current = keep if keep is not None else self.block.palette_role
        roles = list((self.song.palette or {}).keys()) if self.song else []
        if current and current not in roles:
            roles.append(current)
        self.role_combo.blockSignals(True)
        self.role_combo.clear()
        self.role_combo.addItem(LITERAL_LABEL, "")
        for role in roles:
            self.role_combo.addItem(role, role)
        self.role_combo.addItem(NEW_ROLE_LABEL, None)
        index = self.role_combo.findData(current) if current else 0
        self.role_combo.setCurrentIndex(max(0, index))
        self.role_combo.blockSignals(False)

    def _on_role_changed(self):
        self.new_role_edit.setVisible(
            self.role_combo.currentData() is None)

    def selected_role(self) -> str:
        """The role the dialog will write on accept ("" = literal)."""
        data = self.role_combo.currentData()
        if data is None:                       # New role... free text
            return self.new_role_edit.text().strip()
        return data

    def _edit_palette(self):
        """Open the song palette editor; on accept the song's palette
        is written and every role-tagged block re-resolved, so reload
        this block's (possibly rewritten) literals into the sliders."""
        if self.song is None:
            return
        dialog = PaletteEditorDialog(self.song, parent=self)
        if dialog.exec():
            self._rebuild_role_combo(keep=self.selected_role())
            self._on_role_changed()
            self.sliders["red"][0].setValue(int(self.block.red))
            self.sliders["green"][0].setValue(int(self.block.green))
            self.sliders["blue"][0].setValue(int(self.block.blue))

    def _apply_preset(self, r, g, b, w):
        """Apply a preset color to the sliders and update wheel position."""
        self.sliders["red"][0].setValue(r)
        self.sliders["green"][0].setValue(g)
        self.sliders["blue"][0].setValue(b)
        self.sliders["white"][0].setValue(w)

        # Also update wheel position to closest match (if wheel available)
        if self.color_wheel_options and hasattr(self, 'wheel_combo'):
            # For wheel matching, blend white into RGB (same as preview)
            # so that White preset (0,0,0,255) matches white on the wheel
            match_r, match_g, match_b = r, g, b
            if w > 0:
                factor = w / 255.0
                match_r = min(255, int(r + (255 - r) * factor))
                match_g = min(255, int(g + (255 - g) * factor))
                match_b = min(255, int(b + (255 - b) * factor))

            closest_index = self._find_closest_wheel_color(match_r, match_g, match_b)
            if closest_index >= 0:
                self.wheel_combo.blockSignals(True)
                self.wheel_combo.setCurrentIndex(closest_index)
                self.wheel_combo.blockSignals(False)

    def _find_closest_wheel_color(self, r: int, g: int, b: int) -> int:
        """Find the closest color wheel position to the given RGB values.

        Args:
            r, g, b: RGB values (0-255)

        Returns:
            Index of closest color in wheel_combo, or -1 if no wheel
        """
        if not self.color_wheel_options:
            return -1

        min_distance = float('inf')
        closest_index = 0

        for i, (name, dmx_value, hex_color) in enumerate(self.color_wheel_options):
            # Parse hex color to RGB
            if hex_color and hex_color.startswith('#'):
                try:
                    wheel_r = int(hex_color[1:3], 16)
                    wheel_g = int(hex_color[3:5], 16)
                    wheel_b = int(hex_color[5:7], 16)

                    # Calculate Euclidean distance
                    distance = ((r - wheel_r) ** 2 +
                               (g - wheel_g) ** 2 +
                               (b - wheel_b) ** 2) ** 0.5

                    if distance < min_distance:
                        min_distance = distance
                        closest_index = i
                except (ValueError, IndexError):
                    continue

        return closest_index

    def _on_wheel_changed(self, index):
        """Handle color wheel selection change."""
        if index >= 0 and self.color_wheel_options:
            dmx_value, hex_color = self.wheel_combo.currentData()
            if hex_color:
                # Update preview with wheel color
                color = QColor(hex_color)
                self.color_preview.set_color(color)
                self.hex_label.setText(hex_color.upper())
                # Also set RGB sliders to match
                self.sliders["red"][0].blockSignals(True)
                self.sliders["green"][0].blockSignals(True)
                self.sliders["blue"][0].blockSignals(True)
                self.sliders["red"][0].setValue(color.red())
                self.sliders["green"][0].setValue(color.green())
                self.sliders["blue"][0].setValue(color.blue())
                self.sliders["red"][0].blockSignals(False)
                self.sliders["green"][0].blockSignals(False)
                self.sliders["blue"][0].blockSignals(False)

    def _update_preview_from_sliders(self):
        """Update the color preview from current slider values."""
        r = self.sliders["red"][1].value()
        g = self.sliders["green"][1].value()
        b = self.sliders["blue"][1].value()
        w = self.sliders["white"][1].value()

        # Blend white into RGB for preview
        # If white is set, brighten the RGB values towards white
        if w > 0:
            factor = w / 255.0
            r = min(255, int(r + (255 - r) * factor))
            g = min(255, int(g + (255 - g) * factor))
            b = min(255, int(b + (255 - b) * factor))

        color = QColor(r, g, b)
        self.color_preview.set_color(color)
        self.hex_label.setText(color.name().upper())

    def _open_color_picker(self):
        """Open system color picker dialog."""
        from PyQt6.QtWidgets import QColorDialog

        current_color = self.color_preview.color()
        color = QColorDialog.getColor(initial=current_color, parent=self)

        if color.isValid():
            # Apply picked color to sliders
            self.sliders["red"][0].setValue(color.red())
            self.sliders["green"][0].setValue(color.green())
            self.sliders["blue"][0].setValue(color.blue())
            # Reset white when picking a color
            self.sliders["white"][0].setValue(0)

            # Also update wheel position to closest match (if wheel available)
            if self.color_wheel_options and hasattr(self, 'wheel_combo'):
                closest_index = self._find_closest_wheel_color(color.red(), color.green(), color.blue())
                if closest_index >= 0:
                    self.wheel_combo.blockSignals(True)
                    self.wheel_combo.setCurrentIndex(closest_index)
                    self.wheel_combo.blockSignals(False)

    def load_current_values(self):
        """Load current block values into the dialog."""
        # Timing
        self.start_label.setText(f"{self.block.start_time:.2f}s")
        self.end_label.setText(f"{self.block.end_time:.2f}s")
        duration = self.block.end_time - self.block.start_time
        self.duration_label.setText(f"{duration:.2f}s")

        # RGBW values
        self.sliders["red"][0].setValue(int(self.block.red))
        self.sliders["green"][0].setValue(int(self.block.green))
        self.sliders["blue"][0].setValue(int(self.block.blue))
        self.sliders["white"][0].setValue(int(self.block.white))

        # Color wheel (if available)
        if self.color_wheel_options and hasattr(self, 'wheel_combo'):
            # Try to find matching wheel position
            for i in range(self.wheel_combo.count()):
                dmx_value, _ = self.wheel_combo.itemData(i)
                if dmx_value == self.block.color_wheel_position:
                    self.wheel_combo.setCurrentIndex(i)
                    break

    def accept(self):
        """Save parameters to block and close."""
        # Save RGBW values
        self.block.red = float(self.sliders["red"][1].value())
        self.block.green = float(self.sliders["green"][1].value())
        self.block.blue = float(self.sliders["blue"][1].value())
        self.block.white = float(self.sliders["white"][1].value())

        # Palette role: intent metadata only - the literals above stand
        # until the next Song.apply_palette() (palette editor / morph).
        self.block.palette_role = self.selected_role()

        # Determine color mode
        if self.color_wheel_options and hasattr(self, 'wheel_combo'):
            dmx_value, _ = self.wheel_combo.currentData()
            self.block.color_wheel_position = dmx_value
            self.block.color_mode = "Wheel"
        else:
            self.block.color_mode = "RGB"

        super().accept()
