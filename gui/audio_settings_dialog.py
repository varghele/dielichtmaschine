# gui/audio_settings_dialog.py
"""Settings > Audio Settings: where song playback comes out.

Song audio (Shows and Structure tabs) plays through the app's one pygame
player (audio/simple_audio_player.py). This dialog picks its SDL output
device, sample rate and buffer size, persists them (utils/app_settings
``audio_output_settings``) and re-opens a running player in place.
Live audio INPUT is chosen on the Auto tab, not here.
"""

from PyQt6 import QtWidgets

from audio import simple_audio_player as song_audio
from utils.app_settings import (
    AUDIO_SAMPLE_RATES,
    audio_output_settings,
    set_audio_output_settings,
)

#: Buffer sizes offered (SDL wants powers of two).
BUFFER_SIZES = (256, 512, 1024, 2048, 4096, 8192)

SYSTEM_DEFAULT_LABEL = "System default"


class AudioSettingsDialog(QtWidgets.QDialog):
    """Modal editor for the song-playback output device and format."""

    def __init__(self, parent=None, device_lister=None):
        """``device_lister`` returns the SDL output device names
        (default :func:`audio.simple_audio_player.list_output_devices`);
        tests pass a fake."""
        super().__init__(parent)
        self._list_devices = device_lister or song_audio.list_output_devices
        self.setWindowTitle("Audio Settings")
        self.setModal(True)
        self.setMinimumWidth(500)

        stored = audio_output_settings()

        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(12)

        intro = QtWidgets.QLabel(
            "Where song audio plays in the Shows and Structure tabs. "
            "Changes apply immediately, also during playback. Live "
            "audio input is chosen on the Auto tab.")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        form = QtWidgets.QFormLayout()
        form.setSpacing(8)

        device_row = QtWidgets.QHBoxLayout()
        device_row.setSpacing(6)
        self.device_combo = QtWidgets.QComboBox()
        self.device_combo.setMinimumWidth(300)
        refresh = QtWidgets.QPushButton("Refresh")
        refresh.clicked.connect(self.refresh_devices)
        device_row.addWidget(self.device_combo, 1)
        device_row.addWidget(refresh)
        form.addRow("Output device", device_row)

        self.sample_rate_combo = QtWidgets.QComboBox()
        for rate in AUDIO_SAMPLE_RATES:
            self.sample_rate_combo.addItem(f"{rate} Hz", rate)
        self.sample_rate_combo.setCurrentIndex(
            max(0, self.sample_rate_combo.findData(stored["sample_rate"])))
        form.addRow("Sample rate", self.sample_rate_combo)

        self.buffer_combo = QtWidgets.QComboBox()
        sizes = list(BUFFER_SIZES)
        if stored["buffer_size"] not in sizes:
            sizes = sorted(sizes + [stored["buffer_size"]])
        for size in sizes:
            self.buffer_combo.addItem(f"{size} samples", size)
        self.buffer_combo.setCurrentIndex(
            max(0, self.buffer_combo.findData(stored["buffer_size"])))
        form.addRow("Buffer size", self.buffer_combo)

        self.latency_label = QtWidgets.QLabel()
        form.addRow("Latency", self.latency_label)
        layout.addLayout(form)

        self.sample_rate_combo.currentIndexChanged.connect(
            self._update_latency)
        self.buffer_combo.currentIndexChanged.connect(self._update_latency)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._populate_devices(stored["output_device"])
        self._update_latency()

    # -- devices ----------------------------------------------------------

    def _populate_devices(self, selected: str) -> None:
        """System default first, then every SDL output device. A stored
        device that is not connected right now stays listed (marked) so
        opening the dialog never silently forgets the choice."""
        self.device_combo.clear()
        self.device_combo.addItem(SYSTEM_DEFAULT_LABEL, "")
        names = self._list_devices()
        for name in names:
            self.device_combo.addItem(name, name)
        if selected and selected not in names:
            self.device_combo.addItem(f"{selected} (not connected)",
                                      selected)
        self.device_combo.setCurrentIndex(
            max(0, self.device_combo.findData(selected)))

    def refresh_devices(self) -> None:
        self._populate_devices(self.device_combo.currentData() or "")

    def _update_latency(self, *_args) -> None:
        rate = self.sample_rate_combo.currentData()
        size = self.buffer_combo.currentData()
        if rate and size:
            self.latency_label.setText(f"about {size / rate * 1000:.0f} ms")

    # -- persistence ------------------------------------------------------

    def selected_settings(self) -> dict:
        """The settings as the dialog would persist them."""
        return {
            "output_device": self.device_combo.currentData() or "",
            "sample_rate": int(self.sample_rate_combo.currentData()),
            "buffer_size": int(self.buffer_combo.currentData()),
        }

    def accept(self) -> None:
        s = self.selected_settings()
        set_audio_output_settings(s["output_device"], s["sample_rate"],
                                  s["buffer_size"])
        if not song_audio.apply_output_settings(
                s["sample_rate"], s["buffer_size"], s["output_device"]):
            QtWidgets.QMessageBox.warning(
                self, "Audio Settings",
                "The audio output could not be opened with these "
                "settings. Song playback continues without sound until "
                "a working device is chosen.")
        super().accept()
