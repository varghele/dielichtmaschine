# timeline_ui/save_riff_dialog.py
"""Dialog for saving a LightBlock as a Riff."""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLineEdit, QComboBox, QTextEdit, QPushButton,
    QLabel, QMessageBox, QDialogButtonBox
)
from PyQt6.QtCore import Qt

from config.models import (
    LightBlock, Riff, RiffDimmerBlock, RiffColourBlock,
    RiffMovementBlock, RiffSpecialBlock
)
from riffs.riff_library import RiffLibrary


class SaveRiffDialog(QDialog):
    """Dialog for saving a LightBlock as a reusable Riff."""

    def __init__(self, block: LightBlock, bpm: float, riff_library: RiffLibrary,
                 parent=None):
        """Create the save riff dialog.

        Args:
            block: LightBlock to save as riff
            bpm: BPM to use for time-to-beat conversion
            riff_library: RiffLibrary to save the riff to
            parent: Parent widget
        """
        super().__init__(parent)
        self.block = block
        self.bpm = bpm
        self.riff_library = riff_library

        self.setWindowTitle("Save as Riff")
        self.setMinimumWidth(400)
        self.setModal(True)

        self._setup_ui()

    def _setup_ui(self):
        """Create the dialog UI."""
        layout = QVBoxLayout(self)

        # Form layout for inputs
        form = QFormLayout()

        # Riff name
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Enter riff name...")
        form.addRow("Name:", self.name_edit)

        # Category selection
        self.category_combo = QComboBox()
        self.category_combo.setEditable(True)
        categories = self.riff_library.get_categories()
        if not categories:
            categories = ["custom", "builds", "fills", "loops", "drops", "movement"]
        self.category_combo.addItems(categories)
        self.category_combo.setCurrentText("custom")
        form.addRow("Category:", self.category_combo)

        # Description
        self.description_edit = QTextEdit()
        self.description_edit.setPlaceholderText("Optional description...")
        self.description_edit.setMaximumHeight(80)
        form.addRow("Description:", self.description_edit)

        # Tags (comma-separated)
        self.tags_edit = QLineEdit()
        self.tags_edit.setPlaceholderText("tag1, tag2, tag3...")
        form.addRow("Tags:", self.tags_edit)

        layout.addLayout(form)

        # Info label
        duration = self.block.end_time - self.block.start_time
        beats = duration * self.bpm / 60.0
        info_text = f"Duration: {duration:.2f}s ({beats:.1f} beats at {self.bpm:.0f} BPM)"
        info_label = QLabel(info_text)
        info_label.setProperty("role", "stat-caption")
        layout.addWidget(info_label)

        # Button box
        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save |
            QDialogButtonBox.StandardButton.Cancel
        )
        self.save_button = button_box.button(QDialogButtonBox.StandardButton.Save)
        self.save_button.setProperty("role", "primary")
        button_box.accepted.connect(self.save_riff)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def save_riff(self):
        """Convert the block to a riff and save it."""
        name = self.name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Error", "Please enter a riff name.")
            return

        category = self.category_combo.currentText().strip()
        if not category:
            category = "custom"

        description = self.description_edit.toPlainText().strip()

        # Parse tags
        tags_text = self.tags_edit.text().strip()
        tags = [t.strip() for t in tags_text.split(",") if t.strip()] if tags_text else []

        # Convert LightBlock to Riff
        riff = self._convert_block_to_riff(name, category, description, tags)

        # Save to library
        try:
            filepath = self.riff_library.save_riff(riff, category)
            QMessageBox.information(
                self, "Success",
                f"Riff saved to:\n{filepath}"
            )
            self.accept()
        except Exception as e:
            QMessageBox.critical(
                self, "Error",
                f"Failed to save riff:\n{str(e)}"
            )

    def _convert_block_to_riff(self, name: str, category: str,
                                description: str, tags: list) -> Riff:
        """Convert a LightBlock to a Riff.

        Times are converted to beats relative to the block start.

        Args:
            name: Riff name
            category: Category
            description: Description
            tags: List of tags

        Returns:
            Riff object
        """
        block_start = self.block.start_time
        block_duration = self.block.end_time - self.block.start_time
        seconds_per_beat = 60.0 / self.bpm

        def time_to_beat(time: float) -> float:
            """Convert absolute time to beat offset from block start."""
            offset_seconds = time - block_start
            return offset_seconds / seconds_per_beat

        # Convert dimmer blocks
        dimmer_blocks = []
        for db in self.block.dimmer_blocks:
            dimmer_blocks.append(RiffDimmerBlock(
                start_beat=time_to_beat(db.start_time),
                end_beat=time_to_beat(db.end_time),
                intensity=db.intensity,
                strobe_speed=db.strobe_speed,
                iris=db.iris,
                effect_type=db.effect_type,
                effect_speed=db.effect_speed
            ))

        # Convert colour blocks
        colour_blocks = []
        for cb in self.block.colour_blocks:
            colour_blocks.append(RiffColourBlock(
                start_beat=time_to_beat(cb.start_time),
                end_beat=time_to_beat(cb.end_time),
                color_mode=cb.color_mode,
                red=cb.red,
                green=cb.green,
                blue=cb.blue,
                white=cb.white,
                amber=cb.amber,
                cyan=cb.cyan,
                magenta=cb.magenta,
                yellow=cb.yellow,
                uv=cb.uv,
                lime=cb.lime,
                hue=cb.hue,
                saturation=cb.saturation,
                value=cb.value,
                color_wheel_position=cb.color_wheel_position
            ))

        # Convert movement blocks
        movement_blocks = []
        for mb in self.block.movement_blocks:
            movement_blocks.append(RiffMovementBlock(
                start_beat=time_to_beat(mb.start_time),
                end_beat=time_to_beat(mb.end_time),
                pan=mb.pan,
                tilt=mb.tilt,
                pan_fine=mb.pan_fine,
                tilt_fine=mb.tilt_fine,
                speed=mb.speed,
                interpolate_from_previous=mb.interpolate_from_previous,
                effect_type=mb.effect_type,
                effect_speed=mb.effect_speed,
                pan_min=mb.pan_min,
                pan_max=mb.pan_max,
                tilt_min=mb.tilt_min,
                tilt_max=mb.tilt_max,
                pan_amplitude=mb.pan_amplitude,
                tilt_amplitude=mb.tilt_amplitude,
                lissajous_ratio=mb.lissajous_ratio,
                phase_offset_enabled=mb.phase_offset_enabled,
                phase_offset_degrees=mb.phase_offset_degrees
            ))

        # Convert special blocks
        special_blocks = []
        for sb in self.block.special_blocks:
            special_blocks.append(RiffSpecialBlock(
                start_beat=time_to_beat(sb.start_time),
                end_beat=time_to_beat(sb.end_time),
                gobo_index=sb.gobo_index,
                gobo_rotation=sb.gobo_rotation,
                focus=sb.focus,
                zoom=sb.zoom,
                prism_enabled=sb.prism_enabled,
                prism_rotation=sb.prism_rotation
            ))

        # Calculate length in beats
        length_beats = block_duration / seconds_per_beat

        return Riff(
            name=name,
            category=category,
            description=description,
            length_beats=length_beats,
            signature="4/4",  # Default signature
            fixture_types=[],  # Universal by default
            dimmer_blocks=dimmer_blocks,
            colour_blocks=colour_blocks,
            movement_blocks=movement_blocks,
            special_blocks=special_blocks,
            tags=tags,
            author="user",
            version="1.0"
        )
