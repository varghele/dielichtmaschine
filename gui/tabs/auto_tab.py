"""AutoTab - the audio-reactive engine screen, rebuilt to the reference
docs/design/screens/07-auto.html.

Anatomy (left to right):

- a 420px GROUPS · MODE panel: one row per fixture group with a 3px left
  border in the group color, display-caps group name, a segmented
  AUTO / CURATED / LOCKED chip selector, the currently selected riff
  (mono, dim), a 120x8 intensity bar in the group color and the mono
  percentage. Because the reference row is authored at 660px and we run
  at 420px, the riff / bar / percentage wrap onto a second line.
  Underneath: ENERGY SENSITIVITY (accent bar slider) and PLANE BIAS
  (FRONT / MID / BACK chips).
- the engine stage in the centre, on the engineering-grid background: a
  mono state caption, the huge BPM readout, the BPM AUTO / TAP / SET
  chip row, the RMS ENERGY / CONTRAST / VOCALS meter columns, the
  FILL NOW + STOP/START action row and the colour-override row.
- a 400px right column: the 3D PREVIEW · LIVE DMX header (pop-out +
  collapse chevron), the embedded visualizer, the ENGINE LOG, the mono
  key/value block (Input, Window) and a collapsed SETUP disclosure that
  holds the plumbing the reference screen does not draw: ArtNet target /
  universe mapping / mirror, audio host-API + device selection, the full
  movement-target plane list, the movement speed cap and the manual BPM
  spinbox.

Backing model vs. presentation: ``_riff_constraints``
(GroupRiffConstraintPanel) and ``_submasters`` (GroupSubmasterPanel)
stay alive as *hidden* backing widgets - they own the riff checklists,
the per-group constraint state and the submaster values, and they still
emit ``constraints_changed`` / ``submaster_changed`` into the engine.
The visible rows are a view onto them, so every existing signal path and
the settings round-trip are untouched.

Two behavioural deltas worth knowing:

- **Lazy fixture-definition load.** ``on_tab_activated`` parses the QXF
  files on the first activation rather than blocking app startup.
- **UI timer pauses when the tab isn't visible.** ``on_tab_deactivated``
  stops the 20 Hz UI tick to save cycles. The engine itself keeps
  running - Auto Mode is performance-oriented and shouldn't auto-stop
  when the user peeks at another tab.

Cleanup runs from ``MainWindow.closeEvent`` via :meth:`cleanup`.
"""

import math
from collections import deque
from datetime import datetime
from typing import Dict, Optional

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QLabel, QPushButton, QSpinBox, QCheckBox, QSlider,
    QLineEdit, QComboBox, QGroupBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QFrame, QScrollArea, QMenu, QInputDialog, QDialog,
    QApplication, QSizePolicy,
)
from PyQt6.QtCore import Qt, QTimer, QEvent, QPointF, pyqtSignal
from PyQt6.QtGui import (
    QColor, QConicalGradient, QFont, QPainter,
)
from utils import user_warnings

from config.models import Configuration
from audio.device_manager import DeviceManager
from audio.live_input import (GAIN_MAX, GAIN_MIN, LiveAudioInput,
                              compute_auto_gain, gain_to_slider,
                              level_to_fraction, slider_to_gain)
from audio.realtime_spectral import RealtimeSpectralAnalyzer, LiveFeatureFrame
from audio.live_feature_bridge import LiveFeatureBridge
from gui.fonts import FONT_MONO
from gui.icons import shell_icon
from gui.typography import DisplayLabel, MicroLabel, display_font, mono_font
from gui.widgets.embedded_visualizer import EmbeddedVisualizer
from auto.engine import AutoShowEngine
from auto.dmx_output import AutoDMXController
from auto.bpm_detector import TapBPM, AutoBPMDetector
from auto.widgets.color_wheel import HSVColorWheel
from auto.widgets.group_submasters import GroupSubmasterPanel
from auto.widgets.energy_fader import EnergySensitivityFader
from auto.widgets.riff_palette import GroupRiffConstraintPanel
from auto.widgets.metrics_tracker import AutoMetricsTracker
from auto import settings as auto_settings
from autogen.spatial import compute_stage_planes

from .base_tab import BaseTab

# Reference geometry.
LEFT_PANEL_WIDTH = 420
RIGHT_PANEL_WIDTH = 400
METER_BAR_SIZE = (110, 10)
INTENSITY_BAR_SIZE = (120, 8)
COLOR_WHEEL_BUTTON_SIZE = 34
SWATCH_SIZE = 26
PANE_HEADER_HEIGHT = 30

# Data colors. Group fallbacks mirror the Fixtures screen palette; the
# vocals meter takes the reference's cyan (a data color, not a token).
GROUP_PALETTE = (
    "#D9A441", "#4ECBD4", "#C95FD0", "#6F9E4C",
    "#5F86C9", "#C96A5F", "#9A7FD0", "#8D9299",
)
VOCAL_COLOR = "#4ECBD4"
# The raw input level meter (what the mic delivers, post-gain): amber,
# first in the meter row - signal-chain order, input feeds analysis.
INPUT_LEVEL_COLOR = "#D9A441"


def _level_db_label(peak: float) -> str:
    """Peak amplitude -> meter readout ("-38 dB"); "-" below the
    meter floor (-60 dBFS) or at silence."""
    if peak < 1e-3:
        return "-"
    db = 20.0 * math.log10(min(1.0, peak))
    return f"{db:.0f} dB"


def _gain_db_label(gain: float) -> str:
    """Linear gain -> signed dB readout ("+6.0 dB" / "-12.0 dB")."""
    db = 20.0 * math.log10(gain)
    return f"{db:+.1f} dB" if abs(db) >= 0.05 else "0.0 dB"

# Colour-override presets (reference swatches).
COLOR_PRESETS = ("#FF2850", "#C95FD0", "#4ECBD4")

# Sentinel entry of the movement-plane combo.
PLANE_NONE = "None (manual)"

# PLANE BIAS chips -> movement-target plane. "MID" is the no-plane
# (manual) case: the engine has Front/Back/Left/Right/Floor/Ceiling
# planes but no mid plane, so MID releases the plane target instead of
# inventing an engine parameter. The full plane list stays reachable
# through the SETUP disclosure's Movement Target combo.
PLANE_BIAS_CHIPS = (("Front", "Front"), ("Mid", PLANE_NONE), ("Back", "Back"))

# How many engine-log entries we keep / show.
ENGINE_LOG_CAPACITY = 50
ENGINE_LOG_VISIBLE = 8


def _active_tokens() -> dict:
    """The token dict of the theme currently applied to the app.

    Sniffs the applied stylesheet (ThemeManager.apply doesn't persist);
    the light theme's window color is unique to light. Falls back to
    dark. Same trick as gui/tabs/fixtures_tab.py.
    """
    from gui.theme_tokens import THEMES

    app = QApplication.instance()
    qss = app.styleSheet() if app is not None else ""
    light = THEMES.get("light")
    if light is not None and light["window"] in qss:
        return light
    return THEMES["dark"]


def _mono_supports(char: str) -> bool:
    """Does the mono family actually carry ``char``?

    The reference prefixes riff names with a small triangle. Barlow and
    the offscreen fallback font don't have it, so we only use the glyph
    when the loaded IBM Plex Mono can draw it.
    """
    from PyQt6.QtGui import QFontMetrics
    try:
        return QFontMetrics(QFont(FONT_MONO, 10)).inFont(char)
    except Exception:
        return False


def riff_display_text(riff_name: Optional[str], locked: bool,
                      prefix: str = "") -> str:
    """The riff line of a group row.

    Empty riff renders as a dash; locked groups get a " (locked)" suffix
    (no padlock glyph - Barlow has none).
    """
    body = riff_name or "-"
    if locked and riff_name:
        body = f"{body} (locked)"
    return f"{prefix} {body}".strip() if prefix else body


def constraint_mode(allowed) -> str:
    """AUTO / CURATED / LOCKED for a group's allowed-riff set."""
    if not allowed:
        return "AUTO"
    if len(allowed) == 1:
        return "LOCKED"
    return "CURATED"


def contrast_word(value: float) -> str:
    """The reference's qualitative contrast word."""
    return "RICH" if value >= 0.5 else "FLAT"


def vocal_word(value: float) -> str:
    return "PRESENT" if value >= 0.5 else "ABSENT"


# ---------------------------------------------------------------------------
# Small painted primitives (data colors -> widget-local painting)
# ---------------------------------------------------------------------------

class _Bar(QWidget):
    """A flat two-tone bar: track + fill. Fill color is a data color."""

    def __init__(self, width: int, height: int, fill: str, parent=None):
        super().__init__(parent)
        self.setFixedSize(width, height)
        self._fill = QColor(fill)
        self._fraction: Optional[float] = None

    def set_fill_color(self, color: str) -> None:
        self._fill = QColor(color)
        self.update()

    def fraction(self) -> Optional[float]:
        return self._fraction

    def set_fraction(self, fraction: Optional[float]) -> None:
        if fraction is not None:
            fraction = max(0.0, min(1.0, float(fraction)))
        self._fraction = fraction
        self.update()

    def paintEvent(self, event):
        tokens = _active_tokens()
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(tokens["border"]))
        if self._fraction:
            filled = int(round(self.width() * self._fraction))
            if filled > 0:
                painter.fillRect(0, 0, filled, self.height(), self._fill)
        painter.end()


class _IntensityBar(_Bar):
    """The per-group 120x8 submaster bar. Click / drag sets the value."""

    value_changed = pyqtSignal(float)

    def __init__(self, fill: str, parent=None):
        super().__init__(*INTENSITY_BAR_SIZE, fill, parent)
        self.setCursor(Qt.CursorShape.SizeHorCursor)
        self._fraction = 1.0

    def _set_from_x(self, x: float) -> None:
        fraction = max(0.0, min(1.0, x / max(1, self.width())))
        if fraction != self._fraction:
            self.set_fraction(fraction)
            self.value_changed.emit(fraction)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._set_from_x(event.position().x())

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton:
            self._set_from_x(event.position().x())


class _BarSlider(QWidget):
    """The reference's slider: accent-filled progress bar with a handle."""

    value_changed = pyqtSignal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(16)
        self.setMinimumWidth(80)
        self.setCursor(Qt.CursorShape.SizeHorCursor)
        self._value = 0.7

    def value(self) -> float:
        return self._value

    def set_value(self, value: float) -> None:
        self._value = max(0.0, min(1.0, float(value)))
        self.update()

    def _set_from_x(self, x: float) -> None:
        value = max(0.0, min(1.0, x / max(1, self.width())))
        if value != self._value:
            self._value = value
            self.update()
            self.value_changed.emit(value)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._set_from_x(event.position().x())

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton:
            self._set_from_x(event.position().x())

    def paintEvent(self, event):
        tokens = _active_tokens()
        painter = QPainter(self)
        track_top = (self.height() - 8) // 2
        painter.fillRect(0, track_top, self.width(), 8,
                         QColor(tokens["border"]))
        filled = int(round(self.width() * self._value))
        if filled > 0:
            painter.fillRect(0, track_top, filled, 8, QColor(tokens["accent"]))
        handle_x = min(self.width() - 4, max(0, filled - 2))
        painter.fillRect(handle_x, 0, 4, self.height(), QColor(tokens["text"]))
        painter.end()


class _ColorWheelButton(QWidget):
    """34px conic-gradient disc that opens the HSV colour wheel."""

    clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(COLOR_WHEEL_BUTTON_SIZE, COLOR_WHEEL_BUTTON_SIZE)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Colour override: pick a hue")

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()

    def paintEvent(self, event):
        tokens = _active_tokens()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        centre = QPointF(self.width() / 2.0, self.height() / 2.0)
        gradient = QConicalGradient(centre, 0.0)
        for stop, color in ((0.0, "#FF4040"), (0.15, "#F0562E"),
                            (0.35, "#40FF70"), (0.55, "#40C8FF"),
                            (0.75, "#8040FF"), (0.9, "#FF40C0"),
                            (1.0, "#FF4040")):
            gradient.setColorAt(stop, QColor(color))
        painter.setBrush(gradient)
        painter.setPen(QColor(tokens["border"]))
        painter.drawEllipse(2, 2, self.width() - 4, self.height() - 4)
        painter.end()


class _Swatch(QWidget):
    """26px colour-preset square; selected gets a 2px text-colored border."""

    clicked = pyqtSignal(str)

    def __init__(self, color: str, parent=None):
        super().__init__(parent)
        self.setFixedSize(SWATCH_SIZE, SWATCH_SIZE)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._color = color
        self._selected = False
        self.setToolTip(f"Colour override {color}")

    def color(self) -> str:
        return self._color

    def is_selected(self) -> bool:
        return self._selected

    def set_selected(self, selected: bool) -> None:
        self._selected = bool(selected)
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._color)

    def paintEvent(self, event):
        tokens = _active_tokens()
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(self._color))
        if self._selected:
            painter.setPen(QColor(tokens["text"]))
            painter.drawRect(0, 0, self.width() - 1, self.height() - 1)
            painter.drawRect(1, 1, self.width() - 3, self.height() - 3)
        else:
            painter.setPen(QColor(tokens["border"]))
            painter.drawRect(0, 0, self.width() - 1, self.height() - 1)
        painter.end()


class _EngineLogView(QWidget):
    """Mono log list: dim timestamp + message, accent for riff changes.

    Purely UI-side. Fed by :meth:`AutoTab._log_event` from the events the
    tab already observes; ``auto/engine.py`` is untouched.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(3)
        self._layout.addStretch(1)

    def render_entries(self, entries) -> None:
        tokens = _active_tokens()
        while self._layout.count() > 1:
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        for stamp, message, accent in entries:
            row = QWidget(self)
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(8)
            time_label = QLabel(stamp, row)
            time_label.setFont(mono_font(8))
            time_label.setStyleSheet(
                f"color: {tokens['text_disabled']};"
                f" font-family: '{FONT_MONO}';")
            row_layout.addWidget(time_label)
            text_label = QLabel(message, row)
            text_label.setFont(mono_font(8))
            color = tokens["accent_line"] if accent else tokens["text_secondary"]
            text_label.setStyleSheet(
                f"color: {color}; font-family: '{FONT_MONO}';")
            row_layout.addWidget(text_label, 1)
            self._layout.insertWidget(self._layout.count() - 1, row)


class _GroupRow(QWidget):
    """One GROUPS · MODE row: colour border, name, mode chips, riff, bar."""

    mode_clicked = pyqtSignal(str, str)      # group, "AUTO"|"CURATED"|"LOCKED"
    intensity_changed = pyqtSignal(str, float)

    def __init__(self, group_name: str, color: str, prefix: str, parent=None):
        super().__init__(parent)
        self.group_name = group_name
        self.setObjectName("GroupRow")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"#GroupRow {{ border-left: 3px solid {color}; }}")
        self._prefix = prefix

        outer = QVBoxLayout(self)
        outer.setContentsMargins(13, 10, 16, 10)
        outer.setSpacing(8)

        top = QHBoxLayout()
        top.setSpacing(14)
        self.name_label = DisplayLabel(group_name, point_size=14,
                                       weight=QFont.Weight.Bold,
                                       tracking_em=0.05)
        self.name_label.setFixedWidth(150)
        top.addWidget(self.name_label)

        self.mode_buttons: Dict[str, QPushButton] = {}
        chip_row = QHBoxLayout()
        chip_row.setSpacing(0)
        for mode in ("AUTO", "CURATED", "LOCKED"):
            button = QPushButton(mode, self)
            # Theme-owned chrome: QPushButton[role="mode-chip"], filled
            # with the accent when checked (warm text fill for LOCKED
            # via the [state="locked"] variant).
            button.setProperty("role", "mode-chip")
            button.setProperty("state", mode.lower())
            button.setCheckable(True)
            button.setAutoExclusive(False)  # set_mode drives the state
            button.setFont(mono_font(9, QFont.Weight.DemiBold))
            button.setFixedHeight(28)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(
                lambda _checked=False, m=mode: self.mode_clicked.emit(
                    self.group_name, m))
            chip_row.addWidget(button)
            self.mode_buttons[mode] = button
        top.addLayout(chip_row)
        top.addStretch()
        outer.addLayout(top)

        bottom = QHBoxLayout()
        bottom.setSpacing(10)
        self.riff_label = MicroLabel("-", point_size=8, tracking_em=0.0)
        bottom.addWidget(self.riff_label, 1)
        self.intensity_bar = _IntensityBar(color, self)
        self.intensity_bar.value_changed.connect(
            lambda value: self.intensity_changed.emit(self.group_name, value))
        bottom.addWidget(self.intensity_bar)
        self.percent_label = MicroLabel("100%", point_size=8, tracking_em=0.0)
        self.percent_label.setFixedWidth(38)
        self.percent_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        bottom.addWidget(self.percent_label)
        outer.addLayout(bottom)

    # -- state -> visuals ------------------------------------------------
    def set_mode(self, mode: str) -> None:
        """Check the active chip; the theme paints the fill (accent, or
        warm text color for LOCKED)."""
        for name, button in self.mode_buttons.items():
            button.setChecked(name == mode)
            style = button.style()
            if style:
                style.unpolish(button)
                style.polish(button)

    def set_riff(self, riff_name: Optional[str], locked: bool) -> None:
        self.riff_label.setText(
            riff_display_text(riff_name, locked, self._prefix))

    def set_intensity(self, fraction: float) -> None:
        self.intensity_bar.set_fraction(fraction)
        self.percent_label.setText(f"{int(round(fraction * 100))}%")


class AutoTab(BaseTab):
    """Real-time audio-reactive lighting embedded as a tab."""

    def __init__(self, config: Configuration, parent=None):
        # All the non-UI state must be set before super().__init__ - that
        # call invokes setup_ui() which references several of these.
        self.fixture_definitions: dict = {}
        self._fixtures_loaded = False

        self._settings = auto_settings.load()

        self._device_manager = DeviceManager()
        self._live_input = None
        self._analyzer = None
        self._bridge = None
        self._engine = None
        self._dmx_controller = None
        self._tap_bpm = TapBPM()
        self._auto_bpm = AutoBPMDetector()
        self._is_running = False

        # Input level meter + gain (2026-07-21). Capture ownership is a
        # strict two-state machine: idle-owned XOR engine-owned, never
        # both. _idle_input monitors the mic while the engine is
        # stopped; the engine's _live_input takes over on START.
        self._idle_input = None
        self._input_gain = min(GAIN_MAX, max(
            GAIN_MIN, float(getattr(self._settings, "input_gain", 1.0))))
        # 2 s of 20 Hz raw-peak polls: the AUTO gain measurement window.
        self._recent_raw_peaks = deque(maxlen=40)
        # Hold-and-decay display peak against 20 Hz flicker.
        self._displayed_input_peak = 0.0

        # 20 Hz UI tick - paused when the tab isn't visible (see
        # on_tab_deactivated) so it doesn't burn cycles in the background.
        self._ui_timer = QTimer()
        self._ui_timer.setInterval(50)
        self._ui_timer.timeout.connect(self._update_ui)

        # Latest feature frame for meters; replaced on each analyzer tick.
        self._latest_frame: LiveFeatureFrame = None

        # Cached riffs payload - set from the engine callback (which may
        # arrive on a worker thread); applied on the next UI tick.
        self._pending_riff_update = None

        # Bounded UI-side engine log: (timestamp, message, accent).
        self._engine_log = deque(maxlen=ENGINE_LOG_CAPACITY)
        # Last riff seen per group, so we only log actual changes.
        self._last_logged_riffs: Dict[str, str] = {}
        self._last_logged_bpm: Optional[int] = None

        self._group_rows: Dict[str, _GroupRow] = {}
        self._group_colors: Dict[str, str] = {}
        self._riff_prefix = "▸" if _mono_supports("▸") else ""

        super().__init__(config, parent)

        # Device list depends on the audio host being initialised; build
        # it after the UI exists so the combos are ready to receive
        # items. Order matters: the API combo must be populated before
        # the device combo can be filtered through it.
        self._populate_input_apis()
        self._populate_devices()
        self._refresh_asio_hint()
        self._refresh_input_readout()

    # -- BaseTab overrides -------------------------------------------------

    def setup_ui(self):
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        main_layout.addWidget(self._build_groups_panel())
        main_layout.addWidget(self._build_center_panel(), 1)
        main_layout.addWidget(self._build_right_panel())

        # Now that the visible shell exists, build the hidden backing
        # panels + the visible group rows for the first time.
        self._current_groups_fingerprint = None
        self._rebuild_group_panels()
        self._apply_chrome_icons()
        self._sync_plane_chips()
        self._refresh_color_row()
        self._refresh_static_readouts()

    # -- Left panel: GROUPS · MODE ----------------------------------------

    def _build_groups_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("AutoGroupsPanel")
        panel.setProperty("role", "inspector")
        panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        panel.setFixedWidth(LEFT_PANEL_WIDTH)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QWidget()
        header_row = QHBoxLayout(header)
        header_row.setContentsMargins(16, 10, 16, 10)
        header_row.addWidget(MicroLabel("Groups · Mode", point_size=8,
                                        tracking_em=0.12))
        header_row.addStretch()
        header_row.addWidget(MicroLabel("Submaster", point_size=8,
                                        tracking_em=0.12))
        layout.addWidget(header)

        rows_scroll = QScrollArea()
        rows_scroll.setWidgetResizable(True)
        rows_scroll.setFrameShape(QFrame.Shape.NoFrame)
        rows_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._groups_container = QWidget()
        self._groups_layout = QVBoxLayout(self._groups_container)
        self._groups_layout.setContentsMargins(0, 0, 0, 0)
        self._groups_layout.setSpacing(0)
        self._groups_layout.addStretch(1)
        rows_scroll.setWidget(self._groups_container)
        layout.addWidget(rows_scroll, 1)

        # Bottom controls: ENERGY SENSITIVITY + PLANE BIAS.
        footer = QWidget()
        footer_row = QHBoxLayout(footer)
        footer_row.setContentsMargins(16, 12, 16, 14)
        footer_row.setSpacing(12)

        energy_col = QVBoxLayout()
        energy_col.setSpacing(6)
        energy_col.addWidget(MicroLabel("Energy sensitivity", point_size=7,
                                        tracking_em=0.1))
        # The fader widget stays as the backing store (value(), settings
        # round-trip); the visible control is the reference's bar slider.
        self._energy_fader = EnergySensitivityFader(self)
        self._energy_fader.set_value(self._settings.energy_sensitivity / 100.0)
        self._energy_fader.sensitivity_changed.connect(
            self._on_energy_sensitivity_changed)
        self._energy_fader.hide()
        self._energy_slider = _BarSlider()
        self._energy_slider.set_value(self._energy_fader.value())
        self._energy_slider.value_changed.connect(self._on_energy_slider_moved)
        energy_col.addWidget(self._energy_slider)
        footer_row.addLayout(energy_col, 1)

        plane_col = QVBoxLayout()
        plane_col.setSpacing(6)
        plane_col.addWidget(MicroLabel("Plane bias · front · mid · back",
                                       point_size=7, tracking_em=0.06))
        chips = QHBoxLayout()
        chips.setSpacing(4)
        self._plane_chips: Dict[str, QPushButton] = {}
        for label, plane_name in PLANE_BIAS_CHIPS:
            chip = QPushButton(label.upper())
            chip.setFont(mono_font(8, QFont.Weight.DemiBold))
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            chip.setFixedHeight(24)
            chip.clicked.connect(
                lambda _checked=False, p=plane_name: self._on_plane_chip(p))
            chips.addWidget(chip, 1)
            self._plane_chips[plane_name] = chip
        plane_col.addLayout(chips)
        footer_row.addLayout(plane_col, 1)

        layout.addWidget(footer)
        return panel

    # -- Center panel: the engine stage ------------------------------------

    def _build_center_panel(self) -> QWidget:
        tokens = _active_tokens()
        panel = QWidget()
        panel.setObjectName("AutoEngineStage")
        panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        # Engineering-grid motif, theme-owned: QWidget[role="grid-surface"].
        panel.setProperty("role", "grid-surface")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(28)
        layout.addStretch(1)

        # -- state caption + BPM readout + BPM chips -----------------------
        head = QVBoxLayout()
        head.setSpacing(2)
        self._status_phase = MicroLabel("Engine stopped", point_size=8,
                                        tracking_em=0.16)
        self._status_phase.setObjectName("AutoStatusPhase")
        self._status_phase.setProperty("phase", "stopped")
        self._status_phase.setAlignment(Qt.AlignmentFlag.AlignCenter)
        head.addWidget(self._status_phase)

        self._bpm_display = QLabel(f"{float(self._settings.bpm):.1f}")
        self._bpm_display.setObjectName("AutoBpmDisplay")
        self._bpm_display.setFont(mono_font(60, QFont.Weight.DemiBold))
        # Family pinned locally: the app-wide QWidget font-family rule
        # beats setFont (see docs/qt-gotchas.md and CLAUDE.md).
        self._bpm_display.setStyleSheet(
            f"QLabel#AutoBpmDisplay {{ font-family: '{FONT_MONO}'; }}")
        self._bpm_display.setAlignment(Qt.AlignmentFlag.AlignCenter)
        head.addWidget(self._bpm_display)

        chips = QHBoxLayout()
        chips.setSpacing(8)
        chips.addStretch()
        # Kept as the checkable control the feature-frame handler reads.
        self._auto_bpm_checkbox = QPushButton("BPM AUTO")
        self._auto_bpm_checkbox.setCheckable(True)
        self._auto_bpm_checkbox.setProperty("role", "output-select")
        self._auto_bpm_checkbox.setFont(mono_font(8, QFont.Weight.Medium))
        self._auto_bpm_checkbox.toggled.connect(self._on_auto_bpm_toggled)
        chips.addWidget(self._auto_bpm_checkbox)

        self._tap_btn = QPushButton("TAP")
        self._tap_btn.setProperty("role", "primary")
        self._tap_btn.setFont(mono_font(8, QFont.Weight.DemiBold))
        self._tap_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._tap_btn.clicked.connect(self._on_tap_bpm)
        chips.addWidget(self._tap_btn)

        self._bpm_set_btn = QPushButton("SET...")
        self._bpm_set_btn.setProperty("role", "output-select")
        self._bpm_set_btn.setFont(mono_font(8, QFont.Weight.Medium))
        self._bpm_set_btn.setToolTip("Enter a BPM manually")
        self._bpm_set_btn.clicked.connect(self._on_set_bpm)
        chips.addWidget(self._bpm_set_btn)
        chips.addStretch()
        head.addLayout(chips)
        layout.addLayout(head)

        # Manual BPM value lives in the spinbox (settings round-trip, engine
        # push). It is shown in the SETUP disclosure on the right.
        self._bpm_spinbox = QSpinBox()
        self._bpm_spinbox.setRange(30, 300)
        self._bpm_spinbox.setValue(self._settings.bpm)
        self._bpm_spinbox.setSuffix(" BPM")
        self._bpm_spinbox.valueChanged.connect(self._on_bpm_spinbox_changed)

        # -- meter columns --------------------------------------------------
        meters = QHBoxLayout()
        meters.setSpacing(32)
        meters.addStretch()
        self._meter_bars: Dict[str, _Bar] = {}
        self._meter_values: Dict[str, QLabel] = {}
        # The INPUT stage rides its own centered row above the analysis
        # meters (signal-chain order) - a fourth meter column would push
        # the centre panel past the 720p width budget.
        layout.addLayout(self._build_input_row())
        for key, caption, color in (
            ("rms", "RMS energy", tokens["accent"]),
            ("contrast", "Contrast", tokens["text_secondary"]),
            ("vocal", "Vocals", VOCAL_COLOR),
        ):
            column = QVBoxLayout()
            column.setSpacing(5)
            caption_label = MicroLabel(caption, point_size=7, tracking_em=0.1)
            caption_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            column.addWidget(caption_label)
            bar = _Bar(*METER_BAR_SIZE, color)
            column.addWidget(bar, alignment=Qt.AlignmentFlag.AlignHCenter)
            value = MicroLabel("-", point_size=8, tracking_em=0.0)
            value.setAlignment(Qt.AlignmentFlag.AlignCenter)
            column.addWidget(value)
            meters.addLayout(column)
            self._meter_bars[key] = bar
            self._meter_values[key] = value
        meters.addStretch()
        layout.addLayout(meters)

        # Scrolling feature chart: still fed on every tick (it is the
        # tuning instrument), but the reference screen has no room for it.
        self._metrics_tracker = AutoMetricsTracker(panel)
        self._metrics_tracker.hide()

        # -- action row ------------------------------------------------------
        actions = QHBoxLayout()
        actions.setSpacing(14)
        actions.addStretch()
        self._fill_btn = QPushButton("FILL NOW")
        self._fill_btn.setProperty("role", "cta-accent")
        self._fill_btn.setFont(display_font(20, QFont.Weight.ExtraBold,
                                            tracking_em=0.1))
        self._fill_btn.setFixedHeight(66)
        self._fill_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._fill_btn.setStyleSheet(
            'QPushButton[role="primary"] { padding: 20px 44px; }')
        self._fill_btn.clicked.connect(self._on_fill_now)
        actions.addWidget(self._fill_btn)

        # Both buttons exist (gui/tests drive them by name); only the one
        # matching the engine state is visible, per the reference's single
        # toggling button.
        self._start_btn = QPushButton("START ENGINE")
        self._stop_btn = QPushButton("STOP ENGINE")
        for button in (self._start_btn, self._stop_btn):
            button.setFont(display_font(15, QFont.Weight.Bold,
                                        tracking_em=0.08))
            button.setFixedHeight(66)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setStyleSheet("QPushButton { padding: 20px 30px; }")
            actions.addWidget(button)
        self._start_btn.clicked.connect(self._on_start)
        self._stop_btn.clicked.connect(self._on_stop)
        self._stop_btn.setEnabled(False)
        self._stop_btn.hide()
        actions.addStretch()
        layout.addLayout(actions)

        # -- colour override row ----------------------------------------------
        colors = QHBoxLayout()
        colors.setSpacing(12)
        colors.addStretch()
        colors.addWidget(MicroLabel("Colour override", point_size=8,
                                    tracking_em=0.1))

        # The wheel widget itself lives in a popup dialog; the tab keeps
        # the reference's 34px disc as the affordance.
        self._color_wheel = HSVColorWheel(panel)
        self._color_wheel.hide()
        self._color_wheel.set_state(
            self._settings.color_override_active,
            self._settings.color_override_hue,
            self._settings.color_override_saturation,
        )
        self._color_wheel.color_changed.connect(self._on_color_changed)
        self._color_wheel_dialog = None

        self._color_wheel_btn = _ColorWheelButton()
        self._color_wheel_btn.clicked.connect(self._open_color_wheel)
        colors.addWidget(self._color_wheel_btn)

        self._swatches = []
        for preset in COLOR_PRESETS:
            swatch = _Swatch(preset)
            swatch.clicked.connect(self._on_swatch_clicked)
            colors.addWidget(swatch)
            self._swatches.append(swatch)

        self._release_color_btn = QPushButton("RELEASE")
        self._release_color_btn.setProperty("role", "output-select")
        self._release_color_btn.setFont(mono_font(8, QFont.Weight.Medium))
        self._release_color_btn.setToolTip("Clear the colour override")
        self._release_color_btn.clicked.connect(self._on_release_color)
        colors.addWidget(self._release_color_btn)
        colors.addStretch()
        layout.addLayout(colors)

        layout.addStretch(1)
        return panel

    def _build_input_row(self) -> QHBoxLayout:
        """The INPUT stage strip: level meter, GAIN slider (log-mapped,
        centre = 0 dB), signed dB readout and the momentary AUTO button
        (measures the last 2 s of raw peaks and sets the gain once -
        TAP's interaction shape, not an AGC). Registered under the
        "input" meter key so the shared stopped/clear paths cover it."""
        row = QHBoxLayout()
        row.setSpacing(16)
        row.addStretch()

        meter_column = QVBoxLayout()
        meter_column.setSpacing(5)
        caption = MicroLabel("Input level", point_size=7, tracking_em=0.1)
        caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        meter_column.addWidget(caption)
        bar = _Bar(*METER_BAR_SIZE, INPUT_LEVEL_COLOR)
        meter_column.addWidget(bar, alignment=Qt.AlignmentFlag.AlignHCenter)
        value = MicroLabel("-", point_size=8, tracking_em=0.0)
        value.setAlignment(Qt.AlignmentFlag.AlignCenter)
        meter_column.addWidget(value)
        row.addLayout(meter_column)
        self._meter_bars["input"] = bar
        self._meter_values["input"] = value

        gain_column = QVBoxLayout()
        gain_column.setSpacing(5)
        gain_caption = MicroLabel("Gain", point_size=7, tracking_em=0.1)
        gain_caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        gain_column.addWidget(gain_caption)
        self._gain_control = self._make_gain_control()
        self._gain_control.set_value(gain_to_slider(self._input_gain))
        self._gain_control.value_changed.connect(self._on_gain_changed)
        gain_column.addWidget(self._gain_control,
                              alignment=Qt.AlignmentFlag.AlignHCenter)
        self._gain_value = MicroLabel(_gain_db_label(self._input_gain),
                                      point_size=8, tracking_em=0.0)
        self._gain_value.setAlignment(Qt.AlignmentFlag.AlignCenter)
        gain_column.addWidget(self._gain_value)
        row.addLayout(gain_column)

        self._gain_auto_btn = QPushButton("AUTO")
        self._gain_auto_btn.setProperty("role", "primary")
        self._gain_auto_btn.setFont(mono_font(8, QFont.Weight.DemiBold))
        self._gain_auto_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._gain_auto_btn.setToolTip(
            "Set the gain from the level of the last two seconds")
        self._gain_auto_btn.clicked.connect(self._on_auto_gain)
        row.addWidget(self._gain_auto_btn,
                      alignment=Qt.AlignmentFlag.AlignVCenter)

        row.addStretch()
        return row

    def _make_gain_control(self):
        """Factory for the gain control widget. Everything else talks
        only to value()/set_value()/value_changed, so a rotary knob can
        replace the bar slider by changing this one method."""
        control = _BarSlider()
        control.setFixedWidth(METER_BAR_SIZE[0])
        control.setToolTip("Input gain · -20 dB to +20 dB · centre is "
                           "0 dB · applied before analysis")
        return control

    # -- Right panel: preview, log, readouts, setup -------------------------

    def _build_right_panel(self) -> QWidget:
        from gui.tabs.configuration_tab import TOOLBAR_BTN_WIDTH

        panel = QWidget()
        panel.setObjectName("AutoPreviewPanel")
        panel.setProperty("role", "inspector")
        panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        panel.setFixedWidth(RIGHT_PANEL_WIDTH)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QWidget()
        header.setFixedHeight(PANE_HEADER_HEIGHT)
        header_row = QHBoxLayout(header)
        header_row.setContentsMargins(14, 0, 6, 0)
        header_row.setSpacing(12)
        header_row.addWidget(MicroLabel("3D preview · live DMX", point_size=8,
                                        tracking_em=0.12))
        header_row.addStretch()
        self._pop_out_btn = QPushButton("POP-OUT")
        self._pop_out_btn.setFlat(True)
        self._pop_out_btn.setFont(mono_font(8))
        self._pop_out_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._pop_out_btn.setToolTip("Open the standalone visualizer")
        self._pop_out_btn.setProperty("role", "pane-icon")
        self._pop_out_btn.clicked.connect(self._launch_visualizer)
        header_row.addWidget(self._pop_out_btn)
        self._pane_toggle_btn = QPushButton()
        self._pane_toggle_btn.setCheckable(True)
        self._pane_toggle_btn.setChecked(True)
        self._pane_toggle_btn.setFixedWidth(TOOLBAR_BTN_WIDTH)
        self._pane_toggle_btn.setProperty("density", "compact")
        # Flat: the reference draws a bare chevron, and the base
        # QPushButton:checked rule would otherwise paint an accent border
        # around a control that is "on" in its resting state.
        # Theme-owned: QPushButton[role="pane-icon"].
        self._pane_toggle_btn.setProperty("role", "pane-icon")
        self._pane_toggle_btn.setToolTip("Collapse or restore the 3D preview")
        self._pane_toggle_btn.toggled.connect(self._on_pane_toggle)
        header_row.addWidget(self._pane_toggle_btn)
        layout.addWidget(header)

        # Vertical splitter: visualizer on top, everything else below.
        self._right_splitter = QSplitter(Qt.Orientation.Vertical)
        self.embedded_visualizer = EmbeddedVisualizer(self)
        self.embedded_visualizer.set_pop_out_callback(self._launch_visualizer)
        self.embedded_visualizer.set_config(self.config)
        self.embedded_visualizer.set_preview_mode("build")
        # The 3D pane header carries POP-OUT (reference 07); don't offer
        # the same action twice.
        self.embedded_visualizer.set_inner_pop_out_visible(False)
        self._right_splitter.addWidget(self.embedded_visualizer)

        lower = QWidget()
        lower_layout = QVBoxLayout(lower)
        lower_layout.setContentsMargins(16, 12, 16, 12)
        lower_layout.setSpacing(8)

        lower_layout.addWidget(MicroLabel("Engine log", point_size=8,
                                          tracking_em=0.12))
        self._engine_log_view = _EngineLogView()
        lower_layout.addWidget(self._engine_log_view)
        lower_layout.addStretch(1)

        # Key/value readouts. No Latency row: nothing in audio/ exposes an
        # input latency (see the report).
        self._input_value = self._add_readout_row(lower_layout, "Input")
        self._window_value = self._add_readout_row(lower_layout, "Window")

        # SETUP disclosure - the plumbing the reference screen omits.
        self._setup_toggle_btn = QPushButton("SETUP")
        self._setup_toggle_btn.setCheckable(True)
        self._setup_toggle_btn.setProperty("role", "output-select")
        self._setup_toggle_btn.setFont(mono_font(8, QFont.Weight.Medium))
        # Height floor: when the disclosure opens into a pane without
        # room, the layout crushes height-flexible children - the
        # button squeezed to a 14px unlabelled bar. Must be a WIDGET
        # stylesheet rule: the theme's output-select role declares
        # min-height: 0, and QSS geometry beats setMinimumHeight (same
        # cascade trap as the app-wide font-family rule vs setFont).
        # Content-box: 11px content + 2x6px padding + 2x1px border =
        # the button's natural 25px resting height.
        self._setup_toggle_btn.setStyleSheet("min-height: 11px;")
        self._setup_toggle_btn.setToolTip(
            "Show ArtNet, audio input and movement settings")
        self._setup_toggle_btn.toggled.connect(self._on_setup_toggled)
        lower_layout.addWidget(self._setup_toggle_btn)

        self._setup_area = self._build_setup_area()
        self._setup_area.hide()
        lower_layout.addWidget(self._setup_area)
        self._lower_panel = lower
        self._pre_setup_splitter_sizes = None

        self._right_splitter.addWidget(lower)
        self._right_splitter.setStretchFactor(0, 0)
        self._right_splitter.setStretchFactor(1, 1)
        self._right_splitter.setCollapsible(0, True)
        self._right_splitter.setCollapsible(1, False)
        self._right_splitter_default_sizes = [250, 600]
        self._restore_right_splitter_state()
        self._right_splitter.splitterMoved.connect(
            self._save_right_splitter_state)
        layout.addWidget(self._right_splitter, 1)
        return panel

    def _add_readout_row(self, layout, key: str) -> QLabel:
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 2, 0, 2)
        key_label = QLabel(key)
        key_label.setFont(mono_font(8))
        key_label.setStyleSheet(f"font-family: '{FONT_MONO}';")
        row_layout.addWidget(key_label)
        row_layout.addStretch()
        value_label = QLabel("-")
        value_label.setFont(mono_font(8))
        value_label.setStyleSheet(f"font-family: '{FONT_MONO}';")
        row_layout.addWidget(value_label)
        layout.addWidget(row)
        return value_label

    def _build_setup_area(self) -> QWidget:
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.Shape.NoFrame)
        area.setMinimumHeight(260)
        inner = QWidget()
        right_layout = QVBoxLayout(inner)
        right_layout.setContentsMargins(0, 8, 0, 0)
        right_layout.setSpacing(8)

        artnet_group = QGroupBox("ArtNet Output")
        artnet_layout = QVBoxLayout(artnet_group)

        ip_row = QHBoxLayout()
        ip_row.addWidget(QLabel("Target IP:"))
        self._ip_input = QLineEdit(self._settings.target_ip)
        self._ip_input.setPlaceholderText("192.168.1.151")
        self._ip_input.editingFinished.connect(self._on_ip_changed)
        ip_row.addWidget(self._ip_input)
        artnet_layout.addLayout(ip_row)

        artnet_layout.addWidget(QLabel("Universe Mapping:"))
        self._universe_table = QTableWidget(0, 2)
        # Short labels - the column is narrow; two-letter labels and a
        # stretch resize mode let the columns split the available width.
        self._universe_table.setHorizontalHeaderLabels(["Config", "ArtNet"])
        h_header = self._universe_table.horizontalHeader()
        h_header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._universe_table.verticalHeader().setVisible(False)
        self._universe_table.setFixedHeight(120)
        self._populate_universe_table()
        # Propagate ArtNet-uid edits to the running controller so mid-show
        # remappings actually take effect on the wire.
        self._universe_table.itemChanged.connect(
            self._on_universe_mapping_edited)
        artnet_layout.addWidget(self._universe_table)

        self._mirror_checkbox = QCheckBox("Mirror to visualiser broadcast")
        self._mirror_checkbox.setChecked(self._settings.mirror_to_visualizer)
        self._mirror_checkbox.toggled.connect(self._on_mirror_toggled)
        artnet_layout.addWidget(self._mirror_checkbox)
        right_layout.addWidget(artnet_group)

        input_group = QGroupBox("Audio Input")
        input_layout = QVBoxLayout(input_group)

        api_row = QHBoxLayout()
        api_row.setContentsMargins(0, 0, 0, 0)
        api_label = QLabel("Host API:")
        api_label.setFixedWidth(60)
        self._input_api_combo = QComboBox()
        api_row.addWidget(api_label)
        api_row.addWidget(self._input_api_combo, 1)
        input_layout.addLayout(api_row)

        dev_row = QHBoxLayout()
        dev_row.setContentsMargins(0, 0, 0, 0)
        dev_label = QLabel("Device:")
        dev_label.setFixedWidth(60)
        self._input_device_combo = QComboBox()
        dev_row.addWidget(dev_label)
        dev_row.addWidget(self._input_device_combo, 1)
        input_layout.addLayout(dev_row)

        refresh_row = QHBoxLayout()
        refresh_row.setContentsMargins(0, 0, 0, 0)
        self._refresh_devices_btn = QPushButton("Refresh devices")
        self._refresh_devices_btn.setProperty("density", "compact")
        self._refresh_devices_btn.clicked.connect(self._on_refresh_devices)
        refresh_row.addWidget(self._refresh_devices_btn)
        refresh_row.addStretch()
        input_layout.addLayout(refresh_row)

        self._asio_hint_label = QLabel("")
        self._asio_hint_label.setWordWrap(True)
        self._asio_hint_label.setVisible(False)
        input_layout.addWidget(self._asio_hint_label)
        right_layout.addWidget(input_group)

        # Wire after both combos exist so the api handler can reach the
        # device combo. _populate_devices rebuilds both consistently.
        self._input_api_combo.currentTextChanged.connect(
            self._on_input_api_changed)
        self._input_device_combo.currentIndexChanged.connect(
            self._on_input_device_changed)

        plane_group = QGroupBox("Movement Target")
        plane_layout = QVBoxLayout(plane_group)
        self._plane_combo = QComboBox()
        self._stage_planes: dict = {}
        self._populate_plane_combo()
        self._plane_combo.currentTextChanged.connect(
            self._on_target_plane_changed)
        plane_layout.addWidget(self._plane_combo)

        speed_row = QHBoxLayout()
        speed_label = QLabel("Max Speed:")
        speed_label.setFixedWidth(70)
        self._speed_slider = QSlider(Qt.Orientation.Horizontal)
        self._speed_slider.setRange(0, 360)
        self._speed_slider.setValue(self._settings.max_movement_speed)
        self._speed_value_label = QLabel(
            "OFF" if self._settings.max_movement_speed == 0
            else f"{self._settings.max_movement_speed}°/s"
        )
        self._speed_value_label.setFixedWidth(46)
        self._speed_value_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._speed_slider.valueChanged.connect(self._on_speed_changed)
        speed_row.addWidget(speed_label)
        speed_row.addWidget(self._speed_slider)
        speed_row.addWidget(self._speed_value_label)
        plane_layout.addLayout(speed_row)
        right_layout.addWidget(plane_group)

        bpm_group = QGroupBox("BPM")
        bpm_layout = QHBoxLayout(bpm_group)
        bpm_layout.addWidget(self._bpm_spinbox)
        bpm_layout.addStretch()
        right_layout.addWidget(bpm_group)

        # The riff-constraint + submaster panels are the backing model of
        # the left column's rows. Parented here (hidden) so Qt owns them.
        self._riff_constraints = None
        self._submasters = None

        right_layout.addStretch()
        area.setWidget(inner)
        area.setSizePolicy(QSizePolicy.Policy.Preferred,
                           QSizePolicy.Policy.Expanding)
        return area

    # -- Group-keyed panels (rebuild on config change) ---------------------

    def _rebuild_group_panels(self) -> None:
        """Rebuild the backing constraint/submaster panels and the visible
        group rows from the current ``config.groups``.

        Called from ``setup_ui`` (initial fill) and ``update_from_config``
        (when the user loads a config file after construction). Skips the
        rebuild if the group set hasn't changed.

        Captures the existing widgets' state first so live edits to
        submasters / constraints survive when the user later adds a group
        (which forces a rebuild) - ``self._settings`` is only snapshotted
        on tab deactivation, so reading from it here would re-introduce
        stale on-disk values from before the live moves.
        """
        group_names = list(self.config.groups.keys())
        fingerprint = frozenset(group_names)
        if fingerprint == self._current_groups_fingerprint:
            return
        self._current_groups_fingerprint = fingerprint

        current_constraints: Dict[str, set] = {}
        if self._riff_constraints is not None:
            current_constraints = dict(self._riff_constraints.get_constraints())
        current_submasters: Dict[str, int] = {}
        if self._submasters is not None:
            current_submasters = dict(self._submasters.get_values())

        # -- backing riff-constraint panel (hidden) -------------------------
        new_constraints = GroupRiffConstraintPanel(group_names, self)
        new_constraints.hide()
        for g in group_names:
            if g in current_constraints:
                new_constraints.set_constraint(g, set(current_constraints[g]))
            elif g in self._settings.group_constraints:
                new_constraints.set_constraint(
                    g, set(self._settings.group_constraints[g]))
        new_constraints.constraints_changed.connect(self._on_constraints_changed)
        if self._riff_constraints is not None:
            try:
                self._riff_constraints.constraints_changed.disconnect(
                    self._on_constraints_changed)
            except (TypeError, RuntimeError):
                pass
            self._riff_constraints.setParent(None)
            self._riff_constraints.deleteLater()
        self._riff_constraints = new_constraints

        # -- backing submaster panel (hidden) -------------------------------
        new_submasters = GroupSubmasterPanel(group_names, self)
        new_submasters.hide()
        for g in group_names:
            if g in current_submasters:
                new_submasters.set_value(g, current_submasters[g] / 100.0)
            elif g in self._settings.group_submasters:
                new_submasters.set_value(
                    g, self._settings.group_submasters[g] / 100.0)
        new_submasters.submaster_changed.connect(self._on_submaster_changed)
        if self._submasters is not None:
            try:
                self._submasters.submaster_changed.disconnect(
                    self._on_submaster_changed)
            except (TypeError, RuntimeError):
                pass
            self._submasters.setParent(None)
            self._submasters.deleteLater()
        self._submasters = new_submasters

        self._rebuild_group_rows(group_names)

    def _group_color(self, index: int, group_name: str) -> str:
        group = self.config.groups.get(group_name)
        saved = getattr(group, "color", None) if group is not None else None
        if saved and saved != "#808080" and QColor(saved).isValid():
            return QColor(saved).name()
        return GROUP_PALETTE[index % len(GROUP_PALETTE)]

    def _rebuild_group_rows(self, group_names) -> None:
        while self._groups_layout.count() > 1:
            item = self._groups_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._group_rows = {}
        self._group_colors = {}

        submaster_values = self._submasters.get_values()
        for index, name in enumerate(group_names):
            color = self._group_color(index, name)
            self._group_colors[name] = color
            row = _GroupRow(name, color, self._riff_prefix)
            row.mode_clicked.connect(self._on_mode_chip)
            row.intensity_changed.connect(self._on_intensity_bar)
            row.set_intensity(submaster_values.get(name, 100) / 100.0)
            self._groups_layout.insertWidget(
                self._groups_layout.count() - 1, row)
            self._group_rows[name] = row
        self._refresh_group_rows()

    def _refresh_group_rows(self) -> None:
        """Push mode + riff text from the backing constraint panel."""
        if getattr(self, "_riff_constraints", None) is None:
            return
        constraints = self._riff_constraints.get_constraints()
        for name, row in self._group_rows.items():
            allowed = constraints.get(name)
            mode = constraint_mode(allowed)
            row.set_mode(mode)
            if mode == "LOCKED":
                row.set_riff(next(iter(allowed)), True)
            else:
                row.set_riff(self._last_logged_riffs.get(name), False)

    # -- Group-row interactions --------------------------------------------

    def _on_mode_chip(self, group_name: str, mode: str) -> None:
        """AUTO clears the constraint; CURATED / LOCKED open a picker.

        Both write through ``GroupRiffConstraintPanel.set_constraint``,
        which emits ``constraints_changed`` -> the engine.
        """
        panel = self._riff_constraints
        if panel is None:
            return
        if mode == "AUTO":
            panel.set_constraint(group_name, None)
            self._refresh_group_rows()
            self._log_event(f"{group_name}: mode AUTO")
            return
        row = self._group_rows.get(group_name)
        anchor = row.mode_buttons[mode] if row else self
        if mode == "CURATED":
            menu = panel._menus.get(group_name)
            if menu is not None:
                menu.exec(anchor.mapToGlobal(anchor.rect().bottomLeft()))
                self._refresh_group_rows()
                self._log_event(f"{group_name}: mode CURATED")
            return
        # LOCKED: pick exactly one riff.
        menu = QMenu(self)
        for riff in panel._rudiment_names:
            action = menu.addAction(riff)
            action.triggered.connect(
                lambda _checked=False, g=group_name, r=riff:
                self._lock_group_to(g, r))
        menu.exec(anchor.mapToGlobal(anchor.rect().bottomLeft()))

    def _lock_group_to(self, group_name: str, riff: str) -> None:
        self._riff_constraints.set_constraint(group_name, {riff})
        self._refresh_group_rows()
        self._log_event(f"{group_name}: locked to {riff}")

    def _on_intensity_bar(self, group_name: str, fraction: float) -> None:
        row = self._group_rows.get(group_name)
        if row is not None:
            row.percent_label.setText(f"{int(round(fraction * 100))}%")
        if self._submasters is not None:
            # set_value is silent; push to the engine ourselves so the
            # signal contract (submaster_changed -> engine) is unchanged.
            self._submasters.set_value(group_name, fraction)
        self._on_submaster_changed(group_name, fraction)

    # -- Energy / plane bias ------------------------------------------------

    def _on_energy_slider_moved(self, value: float) -> None:
        self._energy_fader.set_value(value)  # silent; keeps the backing store
        self._on_energy_sensitivity_changed(value)

    def _on_plane_chip(self, plane_name: str) -> None:
        index = self._plane_combo.findText(plane_name)
        if index >= 0:
            self._plane_combo.setCurrentIndex(index)  # fires the engine push
        self._sync_plane_chips()

    def _sync_plane_chips(self) -> None:
        """Reflect the movement-target combo on the PLANE BIAS chips.

        No chip lights up when the combo names a plane the chips don't
        cover (Floor / Ceiling / Left / Right, reachable via SETUP).
        """
        current = self._plane_combo.currentText()
        for plane_name, chip in self._plane_chips.items():
            # Theme-owned: QPushButton[role="bias-chip"]:checked.
            chip.setCheckable(True)
            chip.setProperty("role", "bias-chip")
            chip.setChecked(plane_name == current)
            style = chip.style()
            if style:
                style.unpolish(chip)
                style.polish(chip)

    # -- Colour override ----------------------------------------------------

    def _open_color_wheel(self) -> None:
        """Show the HSV wheel in a popup. The wheel widget itself is the
        long-lived control (settings + engine); the dialog just hosts it."""
        if self._color_wheel_dialog is None:
            dialog = QDialog(self)
            dialog.setWindowTitle("Colour override")
            layout = QVBoxLayout(dialog)
            layout.setContentsMargins(8, 8, 8, 8)
            layout.addWidget(self._color_wheel)
            self._color_wheel_dialog = dialog
        self._color_wheel.show()
        self._color_wheel_dialog.show()
        self._color_wheel_dialog.raise_()

    def _on_swatch_clicked(self, color: str) -> None:
        rgb = QColor(color)
        hue = max(0.0, rgb.hueF()) * 360.0
        self._color_wheel.set_state(True, hue, rgb.saturationF())
        self._refresh_color_row()

    def _on_release_color(self) -> None:
        hue, sat = self._color_wheel.get_hue_saturation()
        self._color_wheel.set_state(False, hue, sat)
        self._refresh_color_row()

    def _refresh_color_row(self) -> None:
        # Match on hue/saturation, not RGB: the wheel pins value to 1.0,
        # so a preset's RGB never survives the round trip.
        active = self._color_wheel.is_override_active()
        hue, sat = self._color_wheel.get_hue_saturation()
        for swatch in self._swatches:
            color = QColor(swatch.color())
            selected = (
                active
                and abs(max(0.0, color.hueF()) * 360.0 - hue) < 1.0
                and abs(color.saturationF() - sat) < 0.01
            )
            swatch.set_selected(selected)
        self._release_color_btn.setEnabled(active)

    # -- Embedded visualizer plumbing --------------------------------------

    def _apply_chrome_icons(self) -> None:
        expanded = self._pane_toggle_btn.isChecked()
        self._pane_toggle_btn.setIcon(
            shell_icon("chevron-right" if expanded else "chevron-left"))

    def changeEvent(self, event):
        # Theme switches restyle the whole app via app.setStyleSheet, which
        # lands here as a StyleChange - re-ink the themed icon + the
        # widget-local (token-derived) chip fills.
        if event.type() == QEvent.Type.StyleChange:
            if hasattr(self, "_pane_toggle_btn"):
                self._apply_chrome_icons()
            if hasattr(self, "_plane_chips") and hasattr(self, "_plane_combo"):
                self._sync_plane_chips()
            if getattr(self, "_riff_constraints", None) is not None:
                self._refresh_group_rows()
        super().changeEvent(event)

    def _on_pane_toggle(self, visible: bool) -> None:
        """Collapse or restore the 3D preview inside the right splitter."""
        self._apply_chrome_icons()
        sizes = self._right_splitter.sizes()
        if visible:
            saved = getattr(self, "_saved_preview_sizes", None)
            if not saved or len(saved) != 2 or saved[0] <= 0:
                saved = list(self._right_splitter_default_sizes)
            self._right_splitter.setSizes(saved)
        else:
            if len(sizes) == 2 and sizes[0] > 0:
                self._saved_preview_sizes = sizes
            self._right_splitter.setSizes([0, max(1, sum(sizes))])
        self._save_right_splitter_state()

    def _on_setup_toggled(self, checked: bool) -> None:
        """Show/hide the SETUP disclosure AND make the splitter room.

        The disclosure demands its scroll area's minimum height inside
        whatever pane height the splitter happens to hold - with the 3D
        preview pane large, opening it crushed the log to nothing and
        the toggle button itself to a flat unlabelled bar. Opening now
        grows the lower pane to the content's minimum (taking from the
        collapsible preview pane); closing restores the split the user
        had. Programmatic setSizes does not emit splitterMoved, so the
        temporary growth never overwrites the saved splitter state.
        """
        splitter = self._right_splitter
        if checked:
            self._pre_setup_splitter_sizes = splitter.sizes()
            self._setup_area.setVisible(True)
            sizes = splitter.sizes()
            total = sum(sizes)
            if total > 0:
                needed = self._lower_panel.minimumSizeHint().height()
                lower = max(sizes[1], min(needed, total))
                splitter.setSizes([total - lower, lower])
        else:
            self._setup_area.setVisible(False)
            previous = self._pre_setup_splitter_sizes
            self._pre_setup_splitter_sizes = None
            if previous and sum(previous) > 0:
                splitter.setSizes(previous)

    def _launch_visualizer(self):
        """Pop-out callback. Delegates to the Stage tab's standalone
        launcher so QLC+ interop / TCP / ArtNet stays the same."""
        main_window = self.window()
        stage_tab = getattr(main_window, "stage_tab", None) if main_window else None
        launcher = getattr(stage_tab, "_launch_visualizer", None) if stage_tab else None
        if callable(launcher):
            launcher()
            return
        import os
        import subprocess
        import sys
        project_root = os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        )
        visualizer_path = os.path.join(project_root, "visualizer", "main.py")
        if os.path.exists(visualizer_path):
            subprocess.Popen([sys.executable, visualizer_path], cwd=project_root)

    def _restore_right_splitter_state(self) -> None:
        from utils.app_settings import app_settings
        settings = app_settings()
        state = settings.value("auto/right_splitter")
        if state is not None:
            try:
                self._right_splitter.restoreState(state)
                return
            except Exception:
                pass
        self._right_splitter.setSizes(self._right_splitter_default_sizes)

    def _save_right_splitter_state(self, *_args) -> None:
        from utils.app_settings import app_settings
        settings = app_settings()
        settings.setValue("auto/right_splitter",
                          self._right_splitter.saveState())

    # -- Engine log ---------------------------------------------------------

    def _log_event(self, message: str, accent: bool = False) -> None:
        """Append to the bounded UI-side engine log and re-render."""
        stamp = datetime.now().strftime("%H:%M:%S")
        self._engine_log.append((stamp, message, accent))
        entries = list(self._engine_log)[-ENGINE_LOG_VISIBLE:]
        self._engine_log_view.render_entries(reversed(entries))

    def engine_log_entries(self):
        """The log, newest last. Exposed for tests."""
        return list(self._engine_log)

    # -- Tab lifecycle ------------------------------------------------------

    def on_tab_activated(self):
        self.update_from_config()
        self._populate_input_apis()
        self._populate_devices()
        self._refresh_asio_hint()
        self._refresh_input_readout()
        # Unconditional (was: only while running): the input level
        # meter monitors the mic while the engine is stopped, riding
        # the same 20 Hz tick.
        self._ui_timer.start()
        if not self._is_running:
            self._start_idle_capture()

    def on_tab_deactivated(self):
        self._ui_timer.stop()
        # Release the input device to other applications while the tab
        # is out of sight (the engine's own capture is untouched).
        self._stop_idle_capture()
        try:
            self._save_settings()
        except Exception as e:
            user_warnings.warn(f"Auto Mode settings could not be saved: {e}", category="config-load", once_key="auto-settings-save")

    # -- Idle input monitoring (meter while the engine is stopped) ---------

    def _start_idle_capture(self) -> None:
        """Open the selected input device for level monitoring only.

        SILENT on failure (no device, open refused, device held by
        another app): the meter shows "-" and a retry happens naturally
        on re-activation, refresh or a device-combo change. Never a
        modal - this runs on tab switches.
        """
        if self._is_running or self._idle_input is not None:
            return
        if self._input_device_combo.currentIndex() < 0:
            return
        idle = LiveAudioInput(sample_rate=44100, channels=1,
                              buffer_size=512)
        idle.set_gain(self._input_gain)
        device_index = self._input_device_combo.currentData()
        if not idle.initialize(device_index=device_index) \
                or not idle.start():
            idle.cleanup()
            return
        self._idle_input = idle
        self._recent_raw_peaks.clear()

    def _stop_idle_capture(self) -> None:
        if self._idle_input is not None:
            self._idle_input.cleanup()
            self._idle_input = None

    def _resume_idle_monitoring(self) -> None:
        """Back to idle metering after the engine stopped or failed to
        start (_cleanup stopped the UI timer and owns no capture)."""
        self._start_idle_capture()
        if self.isVisible():
            self._ui_timer.start()

    def _monitored_input(self):
        """Whichever capture currently feeds the input level meter."""
        return self._live_input if self._is_running else self._idle_input

    def update_from_config(self):
        # Refresh QXF fixture definitions for the current config on every
        # call: the one-shot ``_fixtures_loaded`` flag only primed the
        # cache once, and a YAML loaded *after* the first activation would
        # otherwise leave ``fixture_definitions`` empty forever - START
        # then built zero FixtureChannelMaps and DMX went nowhere.
        self._load_fixture_definitions()
        self._fixtures_loaded = True

        if hasattr(self, "_plane_combo"):
            self._populate_plane_combo()
            self._sync_plane_chips()
        if hasattr(self, "_universe_table"):
            self._populate_universe_table()
        if hasattr(self, "_groups_layout"):
            self._rebuild_group_panels()
        if hasattr(self, "embedded_visualizer") and self.embedded_visualizer:
            self.embedded_visualizer.set_config(self.config)
        if hasattr(self, "_window_value"):
            self._refresh_static_readouts()
        if self._engine is not None:
            try:
                self._engine.refresh_from_config(self.config)
            except Exception as e:
                print(f"AutoTab: engine refresh_from_config failed: {e}")

    # -- Lazy fixture definitions -------------------------------------------

    def _load_fixture_definitions(self):
        """Refresh QXF definitions for every (manufacturer, model) the
        current config references. Idempotent and cheap thanks to
        ``get_cached_fixture_definitions``."""
        try:
            models_in_config = {(f.manufacturer, f.model)
                                for g in self.config.groups.values()
                                for f in g.fixtures}
            from utils.fixture_utils import get_cached_fixture_definitions
            self.fixture_definitions = dict(
                get_cached_fixture_definitions(models_in_config)
            )
        except Exception as e:
            user_warnings.warn(f"Auto Mode could not load fixture definitions: {e}", category="fixture-library")
            self.fixture_definitions = {}

    # -- Population helpers -------------------------------------------------

    _API_CURATED = "Curated (recommended)"
    _API_RAW = "All devices (raw)"

    def _populate_input_apis(self):
        prev = (self._input_api_combo.currentText()
                if self._input_api_combo.count() else None)
        self._input_api_combo.blockSignals(True)
        try:
            self._input_api_combo.clear()
            self._input_api_combo.addItem(self._API_CURATED)
            for _, api_name in self._device_manager.get_available_host_apis():
                self._input_api_combo.addItem(api_name)
            self._input_api_combo.addItem(self._API_RAW)

            target = prev or self._settings.input_host_api or self._API_CURATED
            idx = self._input_api_combo.findText(target)
            if idx < 0:
                idx = 0
            self._input_api_combo.setCurrentIndex(idx)
        finally:
            self._input_api_combo.blockSignals(False)

    def _current_api_filter_kwargs(self):
        """Translate the API combo selection into filter args for
        ``enumerate_input_devices``: Curated filters + dedups, a specific
        host API filters within that API, Raw is the debugging escape."""
        text = self._input_api_combo.currentText()
        if text == self._API_CURATED:
            return {
                "host_api_filter": None,
                "include_mappers": False,
                "include_telephony": False,
                "dedup_physical": True,
            }
        if text == self._API_RAW:
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

    def _populate_devices(self):
        """Rebuild the device combo according to the current API filter.

        Restoration priority: live selection, persisted name, system
        default.
        """
        prev_index = self._input_device_combo.currentData()
        kwargs = self._current_api_filter_kwargs()
        devices = self._device_manager.enumerate_input_devices(**kwargs)

        self._input_device_combo.blockSignals(True)
        try:
            self._input_device_combo.clear()
            for device in devices:
                label = f"{device.display_name or device.name}  [{device.host_api}]"
                self._input_device_combo.addItem(label, device.index)

            chosen = -1
            if prev_index is not None:
                for i in range(self._input_device_combo.count()):
                    if self._input_device_combo.itemData(i) == prev_index:
                        chosen = i
                        break

            saved_name = self._settings.input_device_name
            if chosen < 0 and saved_name:
                for i, device in enumerate(devices):
                    if device.name == saved_name or device.display_name == saved_name:
                        chosen = i
                        break

            if chosen < 0:
                default = self._device_manager.get_default_input_device()
                if default is not None:
                    for i in range(self._input_device_combo.count()):
                        if self._input_device_combo.itemData(i) == default.index:
                            chosen = i
                            break

            if chosen >= 0:
                self._input_device_combo.setCurrentIndex(chosen)
        finally:
            self._input_device_combo.blockSignals(False)

    def _refresh_asio_hint(self):
        """Update the ASIO status label below the device combo (warn/info
        only - the ``ok`` message would just add noise)."""
        from audio.device_manager import asio_status
        tokens = _active_tokens()
        status = asio_status()
        level = status["level"]
        if level == "ok":
            self._asio_hint_label.setVisible(False)
            return
        color = tokens["warning"] if level == "warn" else tokens["text_secondary"]
        self._asio_hint_label.setStyleSheet(f"color: {color};")
        self._asio_hint_label.setText(status["message"])
        self._asio_hint_label.setVisible(True)

    def _device_label(self) -> str:
        idx = self._input_device_combo.currentIndex()
        if idx < 0:
            return "No device"
        label = self._input_device_combo.itemText(idx)
        parts = label.rsplit(" [", 1)
        return (parts[0].rstrip()
                if len(parts) == 2 and parts[1].endswith("]") else label)

    def _refresh_input_readout(self) -> None:
        channels = self._live_input.channels if self._live_input else 1
        self._input_value.setText(f"{self._device_label()} · {channels} CH")

    def _refresh_static_readouts(self) -> None:
        # Engine analysis window (its sliding feature window).
        from auto.engine import _WINDOW_SECONDS
        self._window_value.setText(f"{float(_WINDOW_SECONDS):.1f} s")

    def _on_input_api_changed(self, _text: str):
        self._populate_devices()
        self._refresh_input_readout()
        self._rebind_idle_capture()

    def _on_input_device_changed(self, _index: int):
        self._refresh_input_readout()
        self._rebind_idle_capture()

    def _on_refresh_devices(self):
        self._populate_input_apis()
        self._populate_devices()
        self._refresh_asio_hint()
        self._refresh_input_readout()
        self._rebind_idle_capture()

    def _rebind_idle_capture(self) -> None:
        """Device selection changed while the engine is stopped: follow
        it. Also the retry path - picking a device after a failed or
        deviceless idle open starts monitoring. Visibility-gated so the
        combo populations during tab activation (which fire these
        signals before _start_idle_capture runs) and background config
        refreshes never open a device on a hidden tab."""
        if self._is_running or not self.isVisible():
            return
        self._stop_idle_capture()
        self._start_idle_capture()

    def _populate_plane_combo(self):
        planes = compute_stage_planes(self.config)
        self._stage_planes = {p.name: p for p in planes}

        # Block signals while we tear down and rebuild - clear() fires
        # ``currentTextChanged("")`` and each addItem fires it again.
        self._plane_combo.blockSignals(True)
        try:
            self._plane_combo.clear()
            self._plane_combo.addItem(PLANE_NONE)
            for plane in planes:
                self._plane_combo.addItem(plane.name)

            saved = self._settings.target_plane_name
            idx = self._plane_combo.findText(saved) if saved else -1
            if idx < 0:
                idx = self._plane_combo.findText("Front")
            if idx >= 0:
                self._plane_combo.setCurrentIndex(idx)
        finally:
            self._plane_combo.blockSignals(False)

    def _populate_universe_table(self):
        universes = list(self.config.universes.keys())
        saved = self._settings.universe_mapping
        self._universe_table.blockSignals(True)
        try:
            self._universe_table.setRowCount(len(universes))
            for row, uid in enumerate(universes):
                uid_int = int(uid)
                config_item = QTableWidgetItem(str(uid_int))
                config_item.setFlags(config_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                artnet_uid = saved.get(uid_int, uid_int - 1)
                artnet_item = QTableWidgetItem(str(artnet_uid))
                self._universe_table.setItem(row, 0, config_item)
                self._universe_table.setItem(row, 1, artnet_item)
        finally:
            self._universe_table.blockSignals(False)

    def _get_universe_mapping(self) -> dict:
        """The universe-mapping table, or ``None`` when a cell is
        unparsable (callers then keep the controller's mapping instead of
        silently killing DMX to the affected universes)."""
        mapping = {}
        for row in range(self._universe_table.rowCount()):
            config_item = self._universe_table.item(row, 0)
            artnet_item = self._universe_table.item(row, 1)
            if not (config_item and artnet_item):
                return None
            try:
                mapping[int(config_item.text())] = int(artnet_item.text())
            except ValueError:
                return None
        return mapping

    def _on_universe_mapping_edited(self, _item) -> None:
        if self._dmx_controller is None:
            return
        mapping = self._get_universe_mapping()
        if mapping is None:
            self.show_error(
                "Invalid universe mapping",
                "ArtNet universe must be an integer. The previous mapping "
                "has been kept until you fix the bad row.",
            )
            return
        self._dmx_controller.set_universe_mapping(mapping)

    # -- Start / Stop -------------------------------------------------------

    def _on_start(self):
        if self._is_running:
            return

        if not self._fixtures_loaded:
            self._load_fixture_definitions()
            self._fixtures_loaded = True

        # Precondition gates - surfaced as errors rather than silent no-ops.
        if not self.config.groups:
            self.show_error(
                "No fixture groups",
                "Auto mode needs at least one fixture group. Add fixtures "
                "in the Fixtures tab and assign them to groups before starting.",
            )
            return
        if not self.config.universes:
            self.show_error(
                "No universes configured",
                "Auto mode has nothing to send DMX to. Configure at least "
                "one universe in the Configuration tab before starting.",
            )
            return
        if not self.fixture_definitions:
            self.show_error(
                "No fixture definitions",
                "QLC+ fixture definitions could not be loaded for the "
                "configured fixtures. Check that the QXF files for each "
                "fixture's manufacturer/model are reachable.",
            )
            return
        if self._input_device_combo.currentIndex() < 0:
            self.show_error(
                "No audio input device",
                "Select an input device in the SETUP panel before starting "
                "Auto mode.",
            )
            return

        # Hand the device from idle monitoring to the engine BEFORE the
        # engine opens it (ASIO/WASAPI-exclusive drivers refuse a second
        # open). Every failure path below resumes idle monitoring.
        self._stop_idle_capture()

        try:
            device_index = self._input_device_combo.currentData()

            self._live_input = LiveAudioInput(
                sample_rate=44100, channels=1, buffer_size=512
            )
            self._live_input.set_gain(self._input_gain)
            if not self._live_input.initialize(device_index=device_index):
                self.show_error(
                    "Audio input failed",
                    "Could not initialise the selected audio input device. "
                    "Try a different device or check that no other process "
                    "is holding the input exclusively.",
                )
                self._cleanup()
                self._resume_idle_monitoring()
                return

            # The stream may have fallen back to the device's native
            # rate (Invalid-sample-rate devices): analyze at the rate
            # the stream ACTUALLY runs at.
            self._analyzer = RealtimeSpectralAnalyzer(
                sample_rate=self._live_input.sample_rate)
            self._bridge = LiveFeatureBridge(self._analyzer)
            self._bridge.feature_updated.connect(self._on_feature_frame)

            # The detector converts flux-lag counts to BPM, so its rate must
            # match the arrival rate of the values it buffers.
            self._auto_bpm = AutoBPMDetector(
                analysis_rate_hz=self._analyzer.beat_frame_rate_hz
            )

            self._engine = AutoShowEngine(self.config, self.fixture_definitions)
            self._engine.set_bpm(self._bpm_spinbox.value())
            self._engine.set_energy_sensitivity(self._energy_fader.value())
            self._engine.set_on_riffs_updated(self._on_riffs_updated_from_engine)
            plane_text = self._plane_combo.currentText()
            plane = (self._stage_planes.get(plane_text)
                     if plane_text != PLANE_NONE else None)
            self._engine.set_target_plane(plane)

            # Push the current UI state for sticky per-group controls; the
            # engine starts with its own defaults and would otherwise ignore
            # a 50% submaster until the user touched it.
            if self._submasters is not None:
                for g, v in self._submasters.get_values().items():
                    self._engine.set_group_submaster(g, v / 100.0)
            if self._riff_constraints is not None:
                for g, allowed in self._riff_constraints.get_constraints().items():
                    self._engine.set_group_constraints(g, allowed)
            if self._color_wheel.is_override_active():
                r, g, b = self._color_wheel.get_color()
                self._engine.set_color_override((r, g, b))

            target_ip = self._ip_input.text().strip() or "192.168.1.151"

            def _feed_embedded(universe: int, dmx_bytes: bytes) -> None:
                vis = getattr(self, "embedded_visualizer", None)
                if vis is not None:
                    vis.feed_dmx(universe, dmx_bytes)

            # Use the app-wide shared arbiter when hosted in the main
            # window (exclusive playback slot: timeline XOR auto);
            # standalone (tests) the controller builds a private one.
            window = self.window()
            shared_arbiter = window.output_arbiter() \
                if hasattr(window, "output_arbiter") else None

            self._dmx_controller = AutoDMXController(
                self.config, self.fixture_definitions, target_ip=target_ip,
                local_dmx_callback=_feed_embedded,
                arbiter=shared_arbiter,
            )
            # Only override the controller's default mapping if the universe
            # table actually has rows - an empty user mapping used to wipe
            # the controller's default and silence every universe.
            user_mapping = self._get_universe_mapping()
            if user_mapping:
                self._dmx_controller.set_universe_mapping(user_mapping)
            self._dmx_controller.set_mirror_to_visualizer(
                self._mirror_checkbox.isChecked())
            self._dmx_controller.set_engine(self._engine)
            self._dmx_controller.dmx_manager.set_stage_planes(self._stage_planes)
            # set_engine wires engine._dmx_manager - only now can the speed
            # cap take effect.
            self._engine.set_max_movement_speed(float(self._speed_slider.value()))

            if not self._live_input.start():
                self.show_error(
                    "Audio capture failed",
                    "Initialised the audio input but the stream refused to "
                    "start. Check that the device isn't in use by another "
                    "application and try again.",
                )
                self._cleanup()
                self._resume_idle_monitoring()
                return
            self._bridge.start(self._live_input.ring_buffer)
            if not self._dmx_controller.start():
                self.show_error(
                    "DMX output refused",
                    "The Show tab's timeline is playing and holds the "
                    "DMX output. Stop timeline playback before "
                    "starting Auto mode.",
                )
                self._cleanup()
                self._resume_idle_monitoring()
                return

            self._is_running = True
            self._ui_timer.start()

            self._start_btn.setEnabled(False)
            self._start_btn.hide()
            self._stop_btn.setEnabled(True)
            self._stop_btn.show()
            self._set_phase("running")
            self._status_phase.setText("Engine running")
            self._refresh_input_readout()
            self._log_event("Engine start", accent=True)

            # Flip the preview to "live" so feed_dmx frames drive it.
            if self.embedded_visualizer is not None:
                self.embedded_visualizer.set_preview_mode("live")

            print("Auto Mode started")

        except Exception as e:
            import traceback
            traceback.print_exc()
            self._cleanup()
            self._resume_idle_monitoring()
            self.show_error(
                "Auto mode failed to start",
                f"An unexpected error occurred while starting:\n\n{e}\n\n"
                "See the console for full traceback.",
            )

    def _on_stop(self):
        if not self._is_running:
            return

        self._cleanup()
        self._resume_idle_monitoring()

        self._start_btn.setEnabled(True)
        self._start_btn.show()
        self._stop_btn.setEnabled(False)
        self._stop_btn.hide()
        self._set_phase("stopped")
        self._status_phase.setText("Engine stopped")
        self._clear_meters()
        self._last_logged_riffs = {}
        self._last_logged_bpm = None
        self._log_event("Engine stop", accent=True)
        self._refresh_group_rows()

        # Drop the embedded preview back to build mode so every fixture is
        # visibly lit again instead of frozen on the last live frame.
        if self.embedded_visualizer is not None:
            self.embedded_visualizer.set_preview_mode("build")

        print("Auto Mode stopped")

    def _clear_meters(self) -> None:
        for key, bar in self._meter_bars.items():
            bar.set_fraction(None)
            self._meter_values[key].setText("-")

    def _cleanup(self):
        """Tear down audio + engine + DMX threads. Idempotent."""
        self._is_running = False
        self._ui_timer.stop()
        self._stop_idle_capture()
        # The timer keeps running after a STOP (idle metering), so a
        # stale frame would repaint the last RMS/contrast/vocal values
        # forever.
        self._latest_frame = None

        if self._dmx_controller:
            self._dmx_controller.stop()
            self._dmx_controller = None

        if self._bridge:
            self._bridge.stop()
            self._bridge = None

        if self._analyzer:
            self._analyzer.stop()
            self._analyzer = None

        if self._live_input:
            self._live_input.cleanup()
            self._live_input = None

        self._engine = None

    def cleanup(self):
        """Called from MainWindow.closeEvent on app shutdown."""
        try:
            self._save_settings()
        except Exception as e:
            user_warnings.warn(f"Auto Mode settings could not be saved: {e}", category="config-load", once_key="auto-settings-save")
        self._cleanup()
        try:
            self._device_manager.cleanup()
        except Exception:
            pass
        if hasattr(self, "embedded_visualizer") and self.embedded_visualizer:
            try:
                self.embedded_visualizer.cleanup()
            except Exception:
                pass

    # -- Engine event handlers ----------------------------------------------

    def _on_feature_frame(self, frame: LiveFeatureFrame):
        """Receive feature frame from analyzer (Qt signal, main thread)."""
        self._latest_frame = frame
        if self._engine:
            self._engine.on_feature_frame(frame)
        if self._auto_bpm_checkbox.isChecked():
            self._auto_bpm.on_feature(frame)

    def _on_tap_bpm(self):
        bpm = self._tap_bpm.tap()
        if bpm is not None:
            self._bpm_spinbox.blockSignals(True)
            self._bpm_spinbox.setValue(int(round(bpm)))
            self._bpm_spinbox.blockSignals(False)
            self._bpm_display.setText(f"{bpm:.1f}")
            if self._engine:
                self._engine.set_bpm(bpm)
            self._log_event(f"Tap tempo {bpm:.1f} BPM")

    def _on_set_bpm(self):
        """The reference's SET... chip: manual BPM entry into the spinbox
        (which is the engine's write path)."""
        value, ok = QInputDialog.getInt(
            self, "Set BPM", "BPM:", self._bpm_spinbox.value(), 30, 300)
        if ok:
            self._bpm_spinbox.setValue(value)
            self._log_event(f"BPM set to {value}")

    def _on_auto_bpm_toggled(self, checked):
        if checked:
            self._auto_bpm.reset()
        # Auto BPM rewrites the spinbox on every UI tick, so disable the
        # manual controls to make the conflict visible.
        if hasattr(self, "_bpm_spinbox"):
            self._bpm_spinbox.setEnabled(not checked)
        if hasattr(self, "_tap_btn"):
            self._tap_btn.setEnabled(not checked)
        if hasattr(self, "_bpm_set_btn"):
            self._bpm_set_btn.setEnabled(not checked)
        self._log_event(f"BPM auto {'on' if checked else 'off'}")

    def _on_bpm_spinbox_changed(self, value):
        # Keep the readout in sync even when the engine isn't running.
        if hasattr(self, "_bpm_display"):
            self._bpm_display.setText(f"{float(value):.1f}")
        if self._engine:
            self._engine.set_bpm(float(value))

    def _on_fill_now(self):
        if self._engine:
            self._engine.force_fill()
        self._log_event("Fill bar", accent=True)

    def _on_color_changed(self, r, g, b):
        if self._engine:
            if r < 0:
                self._engine.set_color_override(None)
            else:
                self._engine.set_color_override((r, g, b))
        if hasattr(self, "_swatches"):
            self._refresh_color_row()
            if r < 0:
                self._log_event("Colour override released")
            else:
                self._log_event(f"Colour override {QColor(r, g, b).name()}")

    def _on_energy_sensitivity_changed(self, value: float):
        if self._engine:
            self._engine.set_energy_sensitivity(value)

    def _on_ip_changed(self):
        if self._dmx_controller:
            self._dmx_controller.set_target_ip(
                self._ip_input.text().strip() or "192.168.1.151"
            )

    def _on_mirror_toggled(self, checked: bool):
        if self._dmx_controller:
            self._dmx_controller.set_mirror_to_visualizer(checked)

    def _on_speed_changed(self, value):
        if value == 0:
            self._speed_value_label.setText("OFF")
        else:
            self._speed_value_label.setText(f"{value}°/s")
        if self._engine:
            self._engine.set_max_movement_speed(float(value))

    def _on_target_plane_changed(self, text):
        # ``QComboBox.clear()`` synchronously fires ``currentTextChanged("")``
        # before _populate_plane_combo refills it - treat that as a no-op.
        if not text:
            return
        if self._engine:
            plane = (self._stage_planes.get(text)
                     if text != PLANE_NONE else None)
            self._engine.set_target_plane(plane)
        if hasattr(self, "_plane_chips"):
            self._sync_plane_chips()

    def _on_submaster_changed(self, group_name, value):
        if self._engine:
            self._engine.set_group_submaster(group_name, value)

    def _on_constraints_changed(self, group_name, allowed):
        if self._engine:
            self._engine.set_group_constraints(group_name, allowed)

    def _on_riffs_updated_from_engine(self, per_group_rudiments):
        # Engine may invoke this from the DMX worker thread - defer the
        # widget update to the next UI tick instead of touching widgets
        # off-thread.
        self._pending_riff_update = per_group_rudiments

    # -- UI tick (20 Hz) -----------------------------------------------------

    def _update_ui(self):
        self._update_input_meter()
        frame = self._latest_frame
        if frame:
            self._meter_bars['rms'].set_fraction(frame.rms)
            self._meter_bars['contrast'].set_fraction(frame.contrast)
            self._meter_bars['vocal'].set_fraction(frame.vocal)
            self._meter_values['rms'].setText(f"{frame.rms:.2f}")
            self._meter_values['contrast'].setText(
                f"{frame.contrast:.2f} {contrast_word(frame.contrast)}")
            self._meter_values['vocal'].setText(vocal_word(frame.vocal))
            self._metrics_tracker.append_frame(frame)

        if self._engine and self._is_running:
            total = self._engine.cycle_bars
            bar = self._engine.current_bar + 1
            is_fill = self._engine.is_fill
            state = "Engine fill" if is_fill else "Engine running"
            self._status_phase.setText(f"{state} · bar {bar}/{total}")
            self._set_phase("fill" if is_fill else "groove")
            self._bpm_display.setText(f"{self._engine.bpm:.1f}")

        # Capture-and-clear atomically so a worker-thread write that races
        # with this read isn't silently dropped.
        pending = self._pending_riff_update
        if pending:
            self._pending_riff_update = None
            active = {g: r[0] for g, r in pending.items()}
            if self._riff_constraints is not None:
                self._riff_constraints.update_active_riffs(active)
            self._apply_active_riffs(active)

        if self._auto_bpm_checkbox.isChecked() and self._is_running:
            auto_bpm = self._auto_bpm.get_bpm()
            if auto_bpm is not None:
                self._bpm_spinbox.blockSignals(True)
                self._bpm_spinbox.setValue(int(round(auto_bpm)))
                self._bpm_spinbox.blockSignals(False)
                if self._engine:
                    self._engine.set_bpm(auto_bpm)
                locked = int(round(auto_bpm))
                if locked != self._last_logged_bpm:
                    self._last_logged_bpm = locked
                    self._log_event(f"BPM lock {auto_bpm:.1f}")

    def _update_input_meter(self) -> None:
        """Paint the INPUT LEVEL meter from whichever capture is live.

        Reads the capture callback's pre-gain block peak (NOT the ring
        buffer - the analyzer's destructive reads starve read_latest
        while the engine runs, and NOT frame.rms - that is EMA-
        normalized, i.e. already auto-gained). Shown post-gain, so
        moving the GAIN control visibly moves the meter and the bar
        answers "what does the analysis hear".
        """
        source = self._monitored_input()
        if source is not None and source.is_active():
            raw_peak = source.raw_peak()
            self._recent_raw_peaks.append(raw_peak)
            shown = raw_peak * self._input_gain
            # Hold-and-decay against 20 Hz single-block flicker.
            self._displayed_input_peak = max(
                shown, self._displayed_input_peak * 0.85)
            self._meter_bars["input"].set_fraction(
                level_to_fraction(self._displayed_input_peak))
            self._meter_values["input"].setText(
                _level_db_label(self._displayed_input_peak))
        else:
            if source is not None and source is self._idle_input:
                # Device died mid-idle: release it; retry happens on
                # refresh, re-activation or a device change.
                self._stop_idle_capture()
            self._recent_raw_peaks.clear()
            self._displayed_input_peak = 0.0
            self._meter_bars["input"].set_fraction(None)
            self._meter_values["input"].setText("-")

    def _on_gain_changed(self, slider_value: float) -> None:
        """Manual gain drag: push to whichever capture exists (silent,
        like the energy slider - no log per pixel of drag)."""
        self._input_gain = slider_to_gain(slider_value)
        for source in (self._idle_input, self._live_input):
            if source is not None:
                source.set_gain(self._input_gain)
        self._gain_value.setText(_gain_db_label(self._input_gain))

    def _on_auto_gain(self) -> None:
        """Momentary measure-and-set: aim the loudest raw peak of the
        last 2 s at the -12 dBFS target. Refuses on silence."""
        peak = max(self._recent_raw_peaks, default=0.0)
        gain = compute_auto_gain(peak)
        if gain is None:
            self._log_event("Auto gain skipped · no signal")
            return
        self._input_gain = gain
        self._gain_control.set_value(gain_to_slider(gain))
        for source in (self._idle_input, self._live_input):
            if source is not None:
                source.set_gain(gain)
        self._gain_value.setText(_gain_db_label(gain))
        self._log_event(f"Auto gain {_gain_db_label(gain)}", accent=True)

    def _apply_active_riffs(self, active: Dict[str, str]) -> None:
        """Push engine-selected riffs into the rows and log the changes."""
        constraints = (self._riff_constraints.get_constraints()
                       if self._riff_constraints is not None else {})
        for group_name, riff in active.items():
            previous = self._last_logged_riffs.get(group_name)
            self._last_logged_riffs[group_name] = riff
            row = self._group_rows.get(group_name)
            if row is not None:
                allowed = constraints.get(group_name)
                row.set_riff(riff, constraint_mode(allowed) == "LOCKED")
            if previous and previous != riff:
                self._log_event(f"{group_name}: {previous} -> {riff}",
                                accent=True)
            elif previous is None:
                self._log_event(f"{group_name}: {riff}", accent=True)

    # -- Phase property + theme ---------------------------------------------

    def _set_phase(self, phase: str):
        """Set the ``phase`` dynamic property + re-polish so the theme's
        ``QLabel#AutoStatusPhase[phase="..."]`` rule re-evaluates."""
        if self._status_phase.property("phase") == phase:
            return
        self._status_phase.setProperty("phase", phase)
        style = self._status_phase.style()
        if style is not None:
            style.unpolish(self._status_phase)
            style.polish(self._status_phase)

    # -- Settings persistence -----------------------------------------------

    def _save_settings(self):
        hue, sat = self._color_wheel.get_hue_saturation()
        override_active = self._color_wheel.is_override_active()

        if self._riff_constraints is not None:
            constraints = {
                g: sorted(allowed)
                for g, allowed in self._riff_constraints.get_constraints().items()
            }
        else:
            constraints = self._settings.group_constraints
        if self._submasters is not None:
            submasters = self._submasters.get_values()
        else:
            submasters = self._settings.group_submasters

        device_name = None
        if self._input_device_combo.currentIndex() >= 0:
            device_name = self._device_label()

        # Save the raw combo text - including the PLANE_NONE sentinel - so
        # the user's choice round-trips cleanly.
        target_plane = self._plane_combo.currentText()

        # A malformed universe row makes ``_get_universe_mapping`` return
        # None; preserve the last known-good mapping instead of persisting
        # an empty dict that would wipe the user's setup on next launch.
        universe_mapping = self._get_universe_mapping()
        if universe_mapping is None:
            universe_mapping = self._settings.universe_mapping

        input_host_api = (self._input_api_combo.currentText()
                          if hasattr(self, "_input_api_combo")
                          and self._input_api_combo.count()
                          else self._settings.input_host_api)

        self._settings = auto_settings.AutoModeSettings(
            target_ip=self._ip_input.text().strip() or "192.168.1.151",
            universe_mapping=universe_mapping,
            mirror_to_visualizer=self._mirror_checkbox.isChecked(),
            input_device_name=device_name,
            input_host_api=input_host_api,
            bpm=self._bpm_spinbox.value(),
            energy_sensitivity=int(round(self._energy_fader.value() * 100)),
            input_gain=self._input_gain,
            target_plane_name=target_plane,
            max_movement_speed=self._speed_slider.value(),
            color_override_active=override_active,
            color_override_hue=hue,
            color_override_saturation=sat,
            group_constraints=constraints,
            group_submasters=submasters,
        )
        auto_settings.save(self._settings)
