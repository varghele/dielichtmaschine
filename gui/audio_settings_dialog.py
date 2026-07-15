# gui/audio_settings_dialog.py
# Audio Settings Dialog for Die Lichtmaschine
# Allows users to select audio output device and configure audio parameters

from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                             QComboBox, QPushButton, QGroupBox, QSpinBox,
                             QCheckBox, QMessageBox)
from PyQt6.QtCore import Qt

# Try to import audio components
try:
    from audio.device_manager import DeviceManager, asio_status
    from audio.audio_engine import AudioEngine
    AUDIO_AVAILABLE = True
except ImportError:
    AUDIO_AVAILABLE = False
    DeviceManager = None
    AudioEngine = None
    asio_status = None


# Special host-API combo entries — mirror the AutoTab. ``CURATED``
# applies the standard mapper/telephony filter plus cross-API dedup;
# ``RAW`` disables all filtering for power users.
_API_CURATED = "Curated (recommended)"
_API_RAW = "All devices (raw)"


class AudioSettingsDialog(QDialog):
    """Dialog for configuring audio output settings."""

    def __init__(self, device_manager=None, audio_engine=None, parent=None):
        """Initialize audio settings dialog.

        Args:
            device_manager: DeviceManager instance (optional, will create if not provided)
            audio_engine: AudioEngine instance (optional)
            parent: Parent widget
        """
        super().__init__(parent)

        self.device_manager = device_manager
        self.audio_engine = audio_engine
        self._owns_device_manager = False

        # Create device manager if not provided
        if self.device_manager is None and AUDIO_AVAILABLE:
            self.device_manager = DeviceManager()
            self._owns_device_manager = True

        self.setWindowTitle("Audio Settings")
        self.setModal(True)
        self.setMinimumWidth(500)

        self.setup_ui()
        self.load_current_settings()

    def setup_ui(self):
        """Setup the dialog UI."""
        layout = QVBoxLayout(self)

        if not AUDIO_AVAILABLE:
            # Show error message if audio not available
            error_label = QLabel(
                "Audio support is not available.\n\n"
                "Please ensure the following packages are installed:\n"
                "- sounddevice\n"
                "- soundfile\n"
                "- librosa"
            )
            error_label.setStyleSheet("color: red; font-weight: bold;")
            error_label.setWordWrap(True)
            layout.addWidget(error_label)

            # Close button
            close_button = QPushButton("Close")
            close_button.clicked.connect(self.reject)
            layout.addWidget(close_button)
            return

        # Host API Selection Group
        api_group = QGroupBox("Audio Host API")
        api_layout = QVBoxLayout(api_group)

        api_select_layout = QHBoxLayout()
        api_label = QLabel("Host API:")
        self.api_combo = QComboBox()
        self.api_combo.setMinimumWidth(300)
        self.api_combo.currentIndexChanged.connect(self._on_host_api_changed)

        api_select_layout.addWidget(api_label)
        api_select_layout.addWidget(self.api_combo)
        api_select_layout.addStretch()

        api_layout.addLayout(api_select_layout)

        # ASIO-aware status label, populated by _refresh_asio_status().
        # Was a static "Select ASIO for low-latency on Windows" hint
        # which lied: ASIO only appears in the combo when a driver is
        # both registered and exposing a PortAudio host API.
        self._api_info = QLabel("")
        self._api_info.setStyleSheet("color: gray; font-style: italic;")
        self._api_info.setWordWrap(True)
        api_layout.addWidget(self._api_info)
        self._refresh_asio_status()

        layout.addWidget(api_group)

        # Device Selection Group
        device_group = QGroupBox("Audio Output Device")
        device_layout = QVBoxLayout(device_group)

        # Device dropdown
        device_select_layout = QHBoxLayout()
        device_label = QLabel("Output Device:")
        self.device_combo = QComboBox()
        self.device_combo.setMinimumWidth(300)

        device_select_layout.addWidget(device_label)
        device_select_layout.addWidget(self.device_combo)
        device_select_layout.addStretch()

        device_layout.addLayout(device_select_layout)

        # Refresh button
        refresh_button = QPushButton("Refresh Devices")
        refresh_button.clicked.connect(self.refresh_devices)
        device_layout.addWidget(refresh_button)

        layout.addWidget(device_group)

        # Audio Parameters Group
        params_group = QGroupBox("Audio Parameters")
        params_layout = QVBoxLayout(params_group)

        # Sample Rate
        sample_rate_layout = QHBoxLayout()
        sample_rate_label = QLabel("Sample Rate:")
        self.sample_rate_combo = QComboBox()
        self.sample_rate_combo.addItems(["44100", "48000", "96000"])
        self.sample_rate_combo.setCurrentText("44100")

        sample_rate_layout.addWidget(sample_rate_label)
        sample_rate_layout.addWidget(self.sample_rate_combo)
        sample_rate_layout.addStretch()

        params_layout.addLayout(sample_rate_layout)

        # Buffer Size
        buffer_size_layout = QHBoxLayout()
        buffer_size_label = QLabel("Buffer Size:")
        self.buffer_size_spinbox = QSpinBox()
        self.buffer_size_spinbox.setRange(64, 4096)
        self.buffer_size_spinbox.setSingleStep(64)
        self.buffer_size_spinbox.setValue(512)

        buffer_size_layout.addWidget(buffer_size_label)
        buffer_size_layout.addWidget(self.buffer_size_spinbox)
        buffer_size_layout.addStretch()

        params_layout.addLayout(buffer_size_layout)

        # Latency display
        self._latency_label = QLabel()
        self._latency_label.setStyleSheet("color: gray; font-style: italic;")
        params_layout.addWidget(self._latency_label)
        self._update_latency_display()
        self.sample_rate_combo.currentTextChanged.connect(lambda _: self._update_latency_display())
        self.buffer_size_spinbox.valueChanged.connect(lambda _: self._update_latency_display())

        # Info label
        info_label = QLabel("Note: Changing audio settings will restart the audio engine.")
        info_label.setWordWrap(True)
        info_label.setStyleSheet("color: gray; font-style: italic;")
        params_layout.addWidget(info_label)

        layout.addWidget(params_group)

        # Audio Input Group
        input_group = QGroupBox("Audio Input (Live)")
        input_layout = QVBoxLayout(input_group)

        self.enable_input_checkbox = QCheckBox("Enable Live Audio Input")
        self.enable_input_checkbox.setChecked(False)
        self.enable_input_checkbox.toggled.connect(self._on_input_toggled)
        input_layout.addWidget(self.enable_input_checkbox)

        input_device_layout = QHBoxLayout()
        input_device_label = QLabel("Input Device:")
        self.input_device_combo = QComboBox()
        self.input_device_combo.setMinimumWidth(300)
        self.input_device_combo.setEnabled(False)

        input_device_layout.addWidget(input_device_label)
        input_device_layout.addWidget(self.input_device_combo)
        input_device_layout.addStretch()
        input_layout.addLayout(input_device_layout)

        input_info = QLabel("Captures live audio for real-time reactive lighting. "
                            "Use a different device than output to avoid ASIO conflicts.")
        input_info.setStyleSheet("color: gray; font-style: italic;")
        input_info.setWordWrap(True)
        input_layout.addWidget(input_info)

        layout.addWidget(input_group)

        # Dialog buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        test_button = QPushButton("Test")
        test_button.clicked.connect(self.test_device)

        apply_button = QPushButton("Apply")
        apply_button.clicked.connect(self.apply_settings)

        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)

        button_layout.addWidget(test_button)
        button_layout.addWidget(apply_button)
        button_layout.addWidget(cancel_button)

        layout.addLayout(button_layout)

    def _on_input_toggled(self, enabled):
        """Handle enable/disable of live audio input."""
        self.input_device_combo.setEnabled(enabled)
        if enabled and self.input_device_combo.count() == 0:
            self._populate_input_device_combo()

    def _current_filter_kwargs(self):
        """Map the API combo selection to filter kwargs for
        ``enumerate_*`` calls.

        Three modes mirror the AutoTab combo: Curated (full filtering +
        cross-API dedup), per-API (same filtering, scoped to one API),
        and Raw (no filtering at all).
        """
        text = (self.api_combo.currentText()
                if self.api_combo.count() else _API_CURATED)
        if text == _API_CURATED:
            return {
                "host_api_filter": None,
                "include_mappers": False,
                "include_telephony": False,
                "dedup_physical": True,
            }
        if text == _API_RAW:
            return {
                "host_api_filter": None,
                "include_mappers": True,
                "include_telephony": True,
                "dedup_physical": False,
            }
        return {
            "host_api_filter": text,
            "include_mappers": False,
            "include_telephony": False,
            "dedup_physical": False,
        }

    def _populate_input_device_combo(self):
        """Populate input device combo based on current host API filter."""
        if not self.device_manager:
            return

        self.input_device_combo.clear()
        devices = self.device_manager.enumerate_input_devices(
            **self._current_filter_kwargs())

        if not devices:
            self.input_device_combo.addItem("No input devices found", None)
            return

        for device in devices:
            display_text = (f"{device.display_name or device.name} "
                            f"[{device.host_api}]")
            self.input_device_combo.addItem(display_text, device.index)

        # Select default input device
        default_input = self.device_manager.get_default_input_device()
        if default_input:
            for i in range(self.input_device_combo.count()):
                if self.input_device_combo.itemData(i) == default_input.index:
                    self.input_device_combo.setCurrentIndex(i)
                    break

    def _update_latency_display(self):
        """Update the estimated latency label."""
        if not hasattr(self, '_latency_label'):
            return
        try:
            sr = int(self.sample_rate_combo.currentText())
            bs = self.buffer_size_spinbox.value()
            latency_ms = (bs / sr) * 1000
            self._latency_label.setText(f"Estimated latency: {latency_ms:.1f} ms")
        except (ValueError, ZeroDivisionError):
            self._latency_label.setText("")

    def _on_host_api_changed(self, _index):
        """Handle host API selection change — re-filter both device lists."""
        self._populate_device_combo()
        if self.enable_input_checkbox.isChecked():
            self._populate_input_device_combo()

    def _populate_device_combo(self):
        """Populate output device combo based on current host API filter."""
        if not self.device_manager:
            return

        current_device_index = self.device_combo.currentData()

        self.device_combo.clear()
        devices = self.device_manager.enumerate_devices(
            **self._current_filter_kwargs())

        if not devices:
            self.device_combo.addItem("No devices found for this host API", None)
            return

        for device in devices:
            display_text = (f"{device.display_name or device.name} "
                            f"[{device.host_api}]")
            self.device_combo.addItem(display_text, device.index)

        # Restore selection if possible
        if current_device_index is not None:
            for i in range(self.device_combo.count()):
                if self.device_combo.itemData(i) == current_device_index:
                    self.device_combo.setCurrentIndex(i)
                    break

    def _refresh_asio_status(self):
        """Update the under-combo hint with the current ASIO state.

        Three flavours match :func:`audio.device_manager.asio_status`:

        - ``ok``: ASIO host API present in PortAudio. Friendly green-ish
          confirmation.
        - ``warn``: registry has ASIO drivers but PortAudio sees no ASIO
          host API. Typical when the user's interface is unplugged.
          Amber colour.
        - ``info``: no ASIO anywhere. Hint at ASIO4ALL for Windows users.
        """
        if not asio_status:
            return
        try:
            status = asio_status()
        except Exception:
            return
        level = status["level"]
        if level == "ok":
            color = "#2E7D32"  # green
        elif level == "warn":
            color = "#e67e22"  # amber
        else:
            color = "gray"
        self._api_info.setText(status["message"])
        self._api_info.setStyleSheet(
            f"color: {color}; font-style: italic;"
        )

    def load_current_settings(self):
        """Load current audio settings into the UI."""
        if not AUDIO_AVAILABLE or not self.device_manager:
            return

        try:
            # Populate host API combo. Order mirrors the AutoTab:
            # Curated first (default), then real host APIs sorted by
            # quality, then the raw escape hatch.
            self.api_combo.blockSignals(True)
            self.api_combo.clear()
            self.api_combo.addItem(_API_CURATED)
            for _, api_name in self.device_manager.get_available_host_apis():
                self.api_combo.addItem(api_name)
            self.api_combo.addItem(_API_RAW)
            self.api_combo.blockSignals(False)

            # Populate devices (curated by default).
            self._populate_device_combo()

            # Set current device
            default_device = self.device_manager.get_default_device()
            if default_device:
                for i in range(self.device_combo.count()):
                    if self.device_combo.itemData(i) == default_device.index:
                        self.device_combo.setCurrentIndex(i)
                        break

            # Set current sample rate and buffer size from engine if available
            if self.audio_engine:
                if hasattr(self.audio_engine, 'sample_rate'):
                    self.sample_rate_combo.setCurrentText(str(self.audio_engine.sample_rate))
                if hasattr(self.audio_engine, 'buffer_size'):
                    self.buffer_size_spinbox.setValue(self.audio_engine.buffer_size)

        except Exception as e:
            print(f"Error loading settings: {e}")

    def refresh_devices(self):
        """Refresh the list of available devices.

        Also re-probes ASIO status — plugging in an audio interface
        between dialog open and refresh can register a new ASIO host
        API or flip a registered-but-not-loaded driver to ready.
        """
        if not AUDIO_AVAILABLE or not self.device_manager:
            return

        try:
            # Re-build the API combo so newly-available host APIs (e.g.
            # ASIO after plugging in an interface) appear without
            # reopening the dialog. Preserve the current selection.
            prev_api = self.api_combo.currentText()
            self.api_combo.blockSignals(True)
            self.api_combo.clear()
            self.api_combo.addItem(_API_CURATED)
            for _, api_name in self.device_manager.get_available_host_apis():
                self.api_combo.addItem(api_name)
            self.api_combo.addItem(_API_RAW)
            idx = self.api_combo.findText(prev_api)
            self.api_combo.setCurrentIndex(idx if idx >= 0 else 0)
            self.api_combo.blockSignals(False)

            self._populate_device_combo()
            if self.enable_input_checkbox.isChecked():
                self._populate_input_device_combo()
            self._refresh_asio_status()

            device_count = self.device_combo.count()
            if device_count == 1 and self.device_combo.itemData(0) is None:
                device_count = 0
            QMessageBox.information(self, "Success",
                                    f"Found {device_count} audio devices")

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to refresh devices: {str(e)}")

    def test_device(self):
        """Test the selected audio device."""
        if not AUDIO_AVAILABLE or not self.device_manager:
            return

        device_index = self.device_combo.currentData()

        if device_index is None:
            QMessageBox.warning(self, "Warning", "Please select a device")
            return

        try:
            # Validate device
            if self.device_manager.validate_device(device_index):
                QMessageBox.information(self, "Success",
                                        "Audio device is valid and available")
            else:
                QMessageBox.warning(self, "Warning",
                                    "Selected device may not be available")

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Device test failed: {str(e)}")

    def apply_settings(self):
        """Apply the selected settings."""
        if not AUDIO_AVAILABLE:
            self.reject()
            return

        device_index = self.device_combo.currentData()
        sample_rate = int(self.sample_rate_combo.currentText())
        buffer_size = self.buffer_size_spinbox.value()

        if device_index is None:
            QMessageBox.warning(self, "Warning", "Please select a device")
            return

        # Store settings for retrieval
        self.selected_device_index = device_index
        self.selected_sample_rate = sample_rate
        self.selected_buffer_size = buffer_size

        # If we have an audio engine, apply directly
        if self.audio_engine:
            try:
                # Stop current playback if running
                if hasattr(self.audio_engine, 'is_playing') and self.audio_engine.is_playing():
                    self.audio_engine.stop_playback()

                # Cleanup old engine
                if hasattr(self.audio_engine, 'cleanup'):
                    self.audio_engine.cleanup()

                # Update engine parameters
                self.audio_engine.sample_rate = sample_rate
                self.audio_engine.buffer_size = buffer_size

                # Re-initialize with new device
                if self.audio_engine.initialize(device_index=device_index):
                    QMessageBox.information(self, "Success",
                                            "Audio settings applied successfully")
                    self.accept()
                else:
                    QMessageBox.critical(self, "Error",
                                         "Failed to initialize audio with selected device")

            except Exception as e:
                QMessageBox.critical(self, "Error",
                                     f"Failed to apply audio settings: {str(e)}")
        else:
            # No engine provided, just store settings and accept
            QMessageBox.information(self, "Success",
                                    "Audio settings saved. They will be applied when playback starts.")
            self.accept()

    def get_settings(self):
        """Get the selected settings.

        Returns:
            dict with device_index, sample_rate, buffer_size,
            live_input_enabled, input_device_index, or None if cancelled
        """
        if hasattr(self, 'selected_device_index'):
            settings = {
                'device_index': self.selected_device_index,
                'sample_rate': self.selected_sample_rate,
                'buffer_size': self.selected_buffer_size,
                'live_input_enabled': self.enable_input_checkbox.isChecked(),
                'input_device_index': self.input_device_combo.currentData()
                    if self.enable_input_checkbox.isChecked() else None,
            }
            return settings
        return None

    def closeEvent(self, event):
        """Handle dialog close."""
        # Clean up device manager if we created it
        if self._owns_device_manager and self.device_manager:
            self.device_manager.cleanup()
        super().closeEvent(event)
