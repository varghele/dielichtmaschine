# gui/dialogs/render_dialog.py
# Dialog for rendering shows to video files

import os
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                              QComboBox, QPushButton, QFileDialog, QLineEdit,
                              QCheckBox, QGroupBox, QScrollArea, QWidget,
                              QProgressBar, QTextEdit, QApplication)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont

from config.models import Configuration, Song
from utils.render.camera_presets import CAMERA_PRESETS


class RenderWorker(QThread):
    """Background thread for rendering a show to video."""
    progress = pyqtSignal(int, int, str)  # current, total, message
    finished = pyqtSignal(str, bool)  # show_name, success

    def __init__(self, config, show, fixture_definitions, camera_preset,
                 output_path, parent=None):
        super().__init__(parent)
        self.config = config
        self.show = show
        self.fixture_definitions = fixture_definitions
        self.camera_preset = camera_preset
        self.output_path = output_path
        self._renderer = None

    def run(self):
        from utils.render.offline_renderer import OfflineRenderer
        self._renderer = OfflineRenderer(
            config=self.config,
            show=self.show,
            fixture_definitions=self.fixture_definitions,
            camera_preset_name=self.camera_preset,
            output_path=self.output_path,
            progress_callback=lambda cur, tot, msg: self.progress.emit(cur, tot, msg),
        )
        success = self._renderer.render()
        self.finished.emit(self.show.name, success)

    def cancel(self):
        if self._renderer:
            self._renderer.cancel()


class RenderDialog(QDialog):
    """Dialog for selecting shows and rendering to video."""

    def __init__(self, config: Configuration, fixture_definitions: dict, parent=None):
        super().__init__(parent)
        self.config = config
        self.fixture_definitions = fixture_definitions
        self._worker = None
        self._render_queue = []
        self._current_render_idx = 0

        self.setWindowTitle("Render Show to Video")
        self.setMinimumWidth(550)
        self.setMinimumHeight(500)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # Show selection
        show_group = QGroupBox("Shows to Render")
        show_layout = QVBoxLayout(show_group)

        # Select all / none buttons
        btn_row = QHBoxLayout()
        select_all_btn = QPushButton("Select All")
        select_all_btn.clicked.connect(lambda: self._set_all_checked(True))
        select_none_btn = QPushButton("Select None")
        select_none_btn.clicked.connect(lambda: self._set_all_checked(False))
        btn_row.addWidget(select_all_btn)
        btn_row.addWidget(select_none_btn)
        btn_row.addStretch()
        show_layout.addLayout(btn_row)

        # Scrollable show checkboxes
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMaximumHeight(200)
        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)
        scroll_layout.setSpacing(4)

        self._show_checkboxes = {}
        for show_name in sorted(self.config.songs.keys()):
            show = self.config.songs[show_name]
            # Only include shows with timeline data and parts
            if show.parts:
                cb = QCheckBox(show_name)
                cb.setChecked(False)
                scroll_layout.addWidget(cb)
                self._show_checkboxes[show_name] = cb

        scroll_layout.addStretch()
        scroll.setWidget(scroll_widget)
        show_layout.addWidget(scroll)
        layout.addWidget(show_group)

        # Camera preset
        cam_row = QHBoxLayout()
        cam_row.addWidget(QLabel("Camera:"))
        self._camera_combo = QComboBox()
        for name, preset in CAMERA_PRESETS.items():
            self._camera_combo.addItem(f"{name} - {preset['description']}", name)
        self._camera_combo.setCurrentIndex(0)
        cam_row.addWidget(self._camera_combo, stretch=1)
        layout.addLayout(cam_row)

        # Output directory
        dir_row = QHBoxLayout()
        dir_row.addWidget(QLabel("Output:"))
        self._output_dir_edit = QLineEdit()
        self._output_dir_edit.setPlaceholderText("Select output directory...")
        # Default to shows directory
        if self.config.shows_directory:
            default_dir = os.path.join(self.config.shows_directory, "renders")
            self._output_dir_edit.setText(default_dir)
        dir_row.addWidget(self._output_dir_edit, stretch=1)
        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self._browse_output)
        dir_row.addWidget(browse_btn)
        layout.addLayout(dir_row)

        # Render / Cancel buttons
        self._render_btn = QPushButton("Render")
        self._render_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50; color: white; font-weight: bold;
                border: none; border-radius: 4px; padding: 8px 20px; font-size: 14px;
            }
            QPushButton:hover { background-color: #66BB6A; }
            QPushButton:disabled { background-color: #555; }
        """)
        self._render_btn.clicked.connect(self._start_render)

        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.setStyleSheet("""
            QPushButton {
                background-color: #f44336; color: white; font-weight: bold;
                border: none; border-radius: 4px; padding: 8px 20px; font-size: 14px;
            }
            QPushButton:hover { background-color: #EF5350; }
        """)
        self._cancel_btn.clicked.connect(self._cancel_render)
        self._cancel_btn.setVisible(False)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        btn_layout.addWidget(self._render_btn)
        btn_layout.addWidget(self._cancel_btn)
        layout.addLayout(btn_layout)

        # Progress section
        self._progress_label = QLabel("")
        layout.addWidget(self._progress_label)

        self._progress_bar = QProgressBar()
        self._progress_bar.setVisible(False)
        layout.addWidget(self._progress_bar)

        # Log area
        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setFont(QFont("Consolas", 9))
        self._log.setMaximumHeight(150)
        self._log.setVisible(False)
        layout.addWidget(self._log)

        # Styling
        self.setStyleSheet("""
            QDialog { background-color: #3d3d3d; }
            QLabel { color: white; }
            QGroupBox { color: white; font-weight: bold; border: 1px solid #555; border-radius: 4px; margin-top: 10px; padding-top: 15px; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 3px; }
            QCheckBox { color: white; }
            QComboBox, QLineEdit { background-color: #2d2d2d; color: white; border: 1px solid #555; border-radius: 3px; padding: 4px; }
            QScrollArea { border: none; background-color: #2d2d2d; }
            QScrollArea > QWidget > QWidget { background-color: #2d2d2d; }
            QProgressBar { border: 1px solid #555; border-radius: 3px; background-color: #2d2d2d; text-align: center; color: white; }
            QProgressBar::chunk { background-color: #4CAF50; border-radius: 2px; }
            QTextEdit { background-color: #1e1e1e; color: #cccccc; border: 1px solid #555; border-radius: 3px; }
        """)

    def _set_all_checked(self, checked: bool):
        for cb in self._show_checkboxes.values():
            cb.setChecked(checked)

    def _browse_output(self):
        directory = QFileDialog.getExistingDirectory(self, "Select Output Directory")
        if directory:
            self._output_dir_edit.setText(directory)

    def _get_selected_shows(self) -> list:
        return [name for name, cb in self._show_checkboxes.items() if cb.isChecked()]

    def _start_render(self):
        selected = self._get_selected_shows()
        if not selected:
            return

        output_dir = self._output_dir_edit.text().strip()
        if not output_dir:
            return

        os.makedirs(output_dir, exist_ok=True)

        camera_preset = self._camera_combo.currentData()

        # Build render queue
        self._render_queue = []
        for show_name in selected:
            show = self.config.songs[show_name]
            output_path = os.path.join(output_dir, f"{show_name}.mp4")
            self._render_queue.append((show, output_path))

        self._current_render_idx = 0

        # UI state
        self._render_btn.setEnabled(False)
        self._cancel_btn.setVisible(True)
        self._progress_bar.setVisible(True)
        self._log.setVisible(True)
        self._log.clear()

        self._log.append(f"Rendering {len(self._render_queue)} show(s)...")

        # Start first render
        self._render_next(camera_preset)

    def _render_next(self, camera_preset: str):
        if self._current_render_idx >= len(self._render_queue):
            # All done
            self._log.append("\nAll renders complete!")
            self._render_btn.setEnabled(True)
            self._cancel_btn.setVisible(False)
            self._progress_label.setText("Done!")
            return

        show, output_path = self._render_queue[self._current_render_idx]
        total = len(self._render_queue)
        self._progress_label.setText(
            f"Rendering {self._current_render_idx + 1}/{total}: {show.name}"
        )
        self._log.append(f"\n--- {show.name} ---")

        self._worker = RenderWorker(
            self.config, show, self.fixture_definitions,
            camera_preset, output_path
        )
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(
            lambda name, success: self._on_render_finished(name, success, camera_preset)
        )
        self._worker.start()

    def _on_progress(self, current: int, total: int, message: str):
        if total > 0:
            self._progress_bar.setMaximum(total)
            self._progress_bar.setValue(current)
        self._log.append(message)
        # Auto-scroll
        scrollbar = self._log.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def _on_render_finished(self, show_name: str, success: bool, camera_preset: str):
        if success:
            self._log.append(f"{show_name}: Render complete!")
        else:
            self._log.append(f"{show_name}: Render FAILED")

        self._current_render_idx += 1
        self._render_next(camera_preset)

    def _cancel_render(self):
        if self._worker:
            self._worker.cancel()
            self._log.append("Cancelling...")
            self._render_btn.setEnabled(True)
            self._cancel_btn.setVisible(False)
