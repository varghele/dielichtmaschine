# gui/dialogs/workspace_options_dialog.py
# Dialog for configuring QLC+ workspace export options

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QCheckBox, QGroupBox,
    QDialogButtonBox, QLabel, QSpinBox, QGridLayout, QComboBox
)

# QLC+ target versions for the cosmetic <Creator><Version> stamp.
# The workspace XML schema is identical across these (verified: stock
# Sample.qxw and engine/src/doc.cpp are byte-identical between QLC+_4.14.4
# and QLC+_5.2.1), so this only changes the version field on import to
# silence QLC+'s built-in version-mismatch banner. See ROADMAP v1.0.
QLC_TARGET_VERSIONS = [
    ("QLC+ 4.x (latest stable, 4.14.4)", "4.14.4"),
    ("QLC+ 5.x (latest stable, 5.2.1)", "5.2.1"),
]
DEFAULT_QLC_TARGET_VERSION = "4.14.4"


class WorkspaceOptionsDialog(QDialog):
    """Dialog for configuring Virtual Console generation options when exporting workspace."""

    def __init__(self, parent=None, config=None):
        super().__init__(parent)
        self.setWindowTitle("Workspace Export Options")
        self.setMinimumWidth(400)
        self._config = config
        self._group_spinboxes = {}  # group_name -> QSpinBox
        self._setup_ui()

    def _setup_ui(self):
        """Set up the dialog UI."""
        layout = QVBoxLayout(self)
        layout.setSpacing(15)

        # Description
        desc_label = QLabel(
            "Configure what to include in the exported QLC+ workspace.\n"
            "The Virtual Console provides live control of your fixtures."
        )
        desc_label.setWordWrap(True)
        desc_label.setStyleSheet("color: #888; margin-bottom: 10px;")
        layout.addWidget(desc_label)

        # Virtual Console group
        vc_group = QGroupBox("Virtual Console")
        vc_layout = QVBoxLayout(vc_group)

        # Main toggle
        self.generate_vc_checkbox = QCheckBox("Generate Virtual Console controls")
        self.generate_vc_checkbox.setChecked(True)
        self.generate_vc_checkbox.setToolTip(
            "Creates sliders, XY pads, and buttons for each fixture group\n"
            "based on their capabilities (dimmer, color, movement, special)"
        )
        self.generate_vc_checkbox.toggled.connect(self._on_vc_toggled)
        vc_layout.addWidget(self.generate_vc_checkbox)

        # Sub-options container
        self.sub_options_widget = QGroupBox()
        self.sub_options_widget.setFlat(True)
        self.sub_options_widget.setStyleSheet("QGroupBox { border: none; margin-left: 20px; }")
        sub_layout = QVBoxLayout(self.sub_options_widget)
        sub_layout.setContentsMargins(20, 5, 0, 5)

        # Group controls
        self.group_controls_checkbox = QCheckBox("Fixture group controls (sliders, XY pads)")
        self.group_controls_checkbox.setChecked(True)
        self.group_controls_checkbox.setToolTip(
            "Creates control widgets for each fixture group:\n"
            "- Master dimmer slider\n"
            "- RGB/Color sliders (if group has color capability)\n"
            "- XY Pad for pan/tilt (if group has movement capability)\n"
            "- Focus/Zoom sliders (if group has special capability)"
        )
        sub_layout.addWidget(self.group_controls_checkbox)

        # Scene presets
        self.scene_presets_checkbox = QCheckBox("Color and intensity preset scenes")
        self.scene_presets_checkbox.setChecked(True)
        self.scene_presets_checkbox.setToolTip(
            "Creates preset scenes for each fixture group:\n"
            "- Colors: Red, Green, Blue, White, Amber, Blackout\n"
            "- Intensities: 25%, 50%, 75%, 100%"
        )
        sub_layout.addWidget(self.scene_presets_checkbox)

        # Movement presets
        self.movement_presets_checkbox = QCheckBox("Movement preset patterns (for moving heads)")
        self.movement_presets_checkbox.setChecked(True)
        self.movement_presets_checkbox.setToolTip(
            "Creates movement EFX functions for moving head groups:\n"
            "- Center position\n"
            "- Circle pattern\n"
            "- Sweep pattern"
        )
        sub_layout.addWidget(self.movement_presets_checkbox)

        # Show buttons
        self.show_buttons_checkbox = QCheckBox("Show trigger buttons (in SoloFrame)")
        self.show_buttons_checkbox.setChecked(True)
        self.show_buttons_checkbox.setToolTip(
            "Creates a SoloFrame with buttons to trigger each show.\n"
            "Only one show can play at a time (solo/exclusive mode)."
        )
        sub_layout.addWidget(self.show_buttons_checkbox)

        # Speed dial
        self.speed_dial_checkbox = QCheckBox("Tap BPM SpeedDial")
        self.speed_dial_checkbox.setChecked(True)
        self.speed_dial_checkbox.setToolTip(
            "Creates a SpeedDial widget for tap tempo BPM control."
        )
        sub_layout.addWidget(self.speed_dial_checkbox)

        # Master presets
        self.master_presets_checkbox = QCheckBox("Master presets (scenes/chasers for all fixtures)")
        self.master_presets_checkbox.setChecked(True)
        self.master_presets_checkbox.setToolTip(
            "Creates master preset functions that control all fixtures:\n"
            "- Scenes: All Warm White, Red Wash, Blue Wash, Purple Wash, Rainbow\n"
            "- Chasers: Party (16 beats), Pulse (4 beats), Sparkle (1 beat)\n"
            "- Movement: Sweep All (8 beats), Circle All (8 beats)\n"
            "All synced to Tap BPM SpeedDial."
        )
        sub_layout.addWidget(self.master_presets_checkbox)

        vc_layout.addWidget(self.sub_options_widget)
        layout.addWidget(vc_group)

        # Export overrides group — per-group intensity scaling
        overrides_group = QGroupBox("Export Intensity per Group")
        overrides_layout = QVBoxLayout(overrides_group)

        overrides_desc = QLabel(
            "Set the max DMX intensity (0-255) for each fixture group.\n"
            "All dimmer values are scaled proportionally to balance brightness."
        )
        overrides_desc.setWordWrap(True)
        overrides_desc.setStyleSheet("color: #888; margin-bottom: 5px;")
        overrides_layout.addWidget(overrides_desc)

        if self._config and self._config.groups:
            grid = QGridLayout()
            grid.setColumnStretch(1, 1)
            for row, (group_name, group) in enumerate(self._config.groups.items()):
                label = QLabel(group_name)
                spinbox = QSpinBox()
                spinbox.setRange(0, 255)
                spinbox.setValue(group.export_intensity)
                spinbox.setToolTip(
                    f"Max export intensity for {group_name}.\n"
                    "255 = no scaling, lower values dim this group proportionally."
                )
                grid.addWidget(label, row, 0)
                grid.addWidget(spinbox, row, 1)
                self._group_spinboxes[group_name] = spinbox
            overrides_layout.addLayout(grid)
        else:
            no_groups_label = QLabel("No fixture groups configured.")
            no_groups_label.setStyleSheet("color: #666; font-style: italic;")
            overrides_layout.addWidget(no_groups_label)

        layout.addWidget(overrides_group)

        # QLC+ target version (cosmetic stamp; schema is identical 4.x/5.x)
        version_group = QGroupBox("QLC+ Target Version")
        version_layout = QVBoxLayout(version_group)
        version_desc = QLabel(
            "Target QLC+ version stamped into the workspace file. The XML\n"
            "schema is identical across 4.x and 5.x, so this only affects the\n"
            "version banner QLC+ shows on import."
        )
        version_desc.setWordWrap(True)
        version_desc.setStyleSheet("color: #888; margin-bottom: 5px;")
        version_layout.addWidget(version_desc)

        self.qlc_version_combo = QComboBox()
        for label, value in QLC_TARGET_VERSIONS:
            self.qlc_version_combo.addItem(label, userData=value)
        # Default to latest stable 4.x.
        default_idx = next(
            (i for i, (_, v) in enumerate(QLC_TARGET_VERSIONS)
             if v == DEFAULT_QLC_TARGET_VERSION),
            0,
        )
        self.qlc_version_combo.setCurrentIndex(default_idx)
        version_layout.addWidget(self.qlc_version_combo)
        layout.addWidget(version_group)

        # Dark mode option
        appearance_group = QGroupBox("Appearance")
        appearance_layout = QVBoxLayout(appearance_group)

        self.dark_mode_checkbox = QCheckBox("Dark mode (black background)")
        self.dark_mode_checkbox.setChecked(True)
        self.dark_mode_checkbox.setToolTip(
            "Sets the Virtual Console background to black.\n"
            "Recommended for live performance to reduce distraction."
        )
        appearance_layout.addWidget(self.dark_mode_checkbox)

        layout.addWidget(appearance_group)

        # Spacer
        layout.addStretch()

        # Dialog buttons
        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def _on_vc_toggled(self, checked: bool):
        """Enable/disable sub-options when main VC checkbox is toggled."""
        self.sub_options_widget.setEnabled(checked)
        self.dark_mode_checkbox.setEnabled(checked)

    def save_group_intensities(self):
        """Write spinbox values back to config for persistence."""
        if self._config:
            for group_name, spinbox in self._group_spinboxes.items():
                if group_name in self._config.groups:
                    self._config.groups[group_name].export_intensity = spinbox.value()

    def get_options(self) -> dict:
        """Get the selected export options.

        Returns:
            Dict with keys:
                - generate_vc: bool - Master toggle for VC generation
                - group_controls: bool - Include fixture group controls
                - scene_presets: bool - Include color/intensity scenes
                - movement_presets: bool - Include movement EFX patterns
                - show_buttons: bool - Include show trigger buttons
                - speed_dial: bool - Include tap BPM SpeedDial
                - master_presets: bool - Include master presets for all fixtures
                - dark_mode: bool - Use dark/black background
                - group_intensities: dict[str, int] - Per-group max intensity (0-255)
                - qlc_target_version: str - Version string stamped into
                  <Creator><Version> (cosmetic; e.g. "4.14.4" or "5.2.1")
        """
        group_intensities = {
            name: spinbox.value()
            for name, spinbox in self._group_spinboxes.items()
        }
        return {
            'generate_vc': self.generate_vc_checkbox.isChecked(),
            'group_controls': self.group_controls_checkbox.isChecked(),
            'scene_presets': self.scene_presets_checkbox.isChecked(),
            'movement_presets': self.movement_presets_checkbox.isChecked(),
            'show_buttons': self.show_buttons_checkbox.isChecked(),
            'speed_dial': self.speed_dial_checkbox.isChecked(),
            'master_presets': self.master_presets_checkbox.isChecked(),
            'dark_mode': self.dark_mode_checkbox.isChecked(),
            'group_intensities': group_intensities,
            'qlc_target_version': self.qlc_version_combo.currentData() or DEFAULT_QLC_TARGET_VERSION,
        }
