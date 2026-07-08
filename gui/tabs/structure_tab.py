# gui/tabs/structure_tab.py
"""Show > Structure, rebuilt to the reference screen
design_handoff_lichtmaschine_app/screens/05-show-structure.html.

Anatomy (top to bottom):

- a slim 38px action strip: no tab title (the shell subnav names the
  screen); the mono audio readout ("neon_ruinen.wav . 03:42 ANALYZED",
  the status word in green) and a bordered display-caps
  "AUTOGENERATE SHOW..." button on the right.
- the main column (28px padding, 28px gaps): the show-management row,
  the "PARTS" caption over the horizontal strip of 190px part cards
  (3px top bar + tint in the part color, transition chips between the
  cards, a dashed 44x44 add tile at the end), then the
  "MASTER GRID . N BARS . mm:ss" caption over the master timeline grid
  and the mono snap-hint row.
- a 400px inspector: the part name in display caps *in the part color*,
  a 2x2 grid of bordered stat tiles (BPM / TIME SIG / BARS / DURATION),
  the editors (name, BPM, time signature, bars, color, reorder), the
  TRANSITION OUT combo, the AUDIO ANALYSIS read-out rows, and a
  destructive Delete Part footer.
- transport + Pause Show rows (features with no home in the reference
  screen; kept reachable directly above the status strip).
- a mono status strip: "N PARTS . N BARS . mm:ss".

The part cards are display-only; every edit goes through the inspector,
writes straight into the ShowPart model, and refreshes the cards, the
stat tiles, the grid caption, the timelines and the status strip.
"""

import os
import csv
from PyQt6.QtWidgets import (QVBoxLayout, QHBoxLayout, QWidget, QLabel,
                             QPushButton, QComboBox, QScrollArea, QFrame,
                             QLineEdit, QSpinBox, QDoubleSpinBox, QColorDialog,
                             QMessageBox, QSplitter, QInputDialog, QSlider,
                             QGridLayout,
                             QSizePolicy, QMenu, QFileDialog, QProgressDialog,
                             QGroupBox, QCheckBox)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QRectF, QPointF
from PyQt6.QtGui import (QPainter, QColor, QPen, QBrush, QFont, QAction,
                         QFontMetrics)
import shutil
from config.models import Configuration, Show, ShowPart, TimelineData, MidiInputDevice, PauseShowConfig
from gui.typography import DisplayLabel, MicroLabel, display_font, mono_font
from gui.widgets.chip import Chip
from timeline.song_structure import SongStructure
from timeline_ui import AudioLaneWidget, MasterTimelineContainer, TimelineGrid
from .base_tab import BaseTab


def _active_tokens() -> dict:
    """The token dict of the theme currently applied to the app.

    The applied stylesheet is the only reliable record of the active
    theme (ThemeManager.apply deliberately doesn't persist), so sniff
    it: the light theme's window color is unique to light. Falls back
    to dark. Same trick as gui/tabs/fixtures_tab.py.
    """
    from PyQt6.QtWidgets import QApplication
    from gui.theme_tokens import THEMES

    app = QApplication.instance()
    qss = app.styleSheet() if app is not None else ""
    light = THEMES.get("light")
    if light is not None and light["window"] in qss:
        return light
    return THEMES["dark"]


def format_clock(seconds: float) -> str:
    """Seconds as mm:ss (the reference's '03:42' readouts)."""
    total = max(0, int(seconds))
    return f"{total // 60:02d}:{total % 60:02d}"


def energy_words(relative_energy: float) -> str:
    """'0.82 HIGH' - the reference's Energy read-out."""
    band = ("HIGH" if relative_energy >= 0.66
            else "MID" if relative_energy >= 0.33 else "LOW")
    return f"{relative_energy:.2f} {band}"


def contrast_words(spectral_contrast: float) -> str:
    """'0.64 RICH' - the reference's Contrast read-out."""
    band = "RICH" if spectral_contrast >= 0.5 else "FLAT"
    return f"{spectral_contrast:.2f} {band}"


def vocal_words(vocal_presence: float) -> str:
    """'PRESENT' / 'ABSENT' - the reference's Vocals read-out."""
    return "PRESENT" if vocal_presence >= 0.5 else "ABSENT"


class StatTile(QFrame):
    """A bordered read-out tile of the inspector's 2x2 grid: mono micro
    caption over a big mono value (reference: BPM / TIME SIG / BARS /
    DURATION).

    Chrome is theme-owned: ``QWidget[role="stat-tile"]`` plus the
    stat-caption / stat-value label roles in the QSS template.
    """

    def __init__(self, caption: str, parent=None):
        super().__init__(parent)
        self.setObjectName("StatTile")
        self.setProperty("role", "stat-tile")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(2)

        self.caption_label = MicroLabel(caption, point_size=7,
                                        tracking_em=0.1)
        self.caption_label.setProperty("role", "stat-caption")
        layout.addWidget(self.caption_label)

        self.value_label = QLabel("-")
        self.value_label.setObjectName("StatTileValue")
        self.value_label.setProperty("role", "stat-value")
        self.value_label.setFont(mono_font(16))
        layout.addWidget(self.value_label)

    def apply_tokens(self, tokens: dict) -> None:
        """Kept for callers that re-apply on theme switch; chrome now
        comes from the QSS template, so this only repolishes."""
        style = self.style()
        if style:
            style.unpolish(self)
            style.polish(self)

    def set_value(self, text: str) -> None:
        self.value_label.setText(text)


class AnalysisRow(QWidget):
    """One mono row of the inspector's AUDIO ANALYSIS block: label left,
    value right. The value is a dim "-" until a generation report with
    per-section audio features exists."""

    PLACEHOLDER = "-"
    PLACEHOLDER_TOOLTIP = "Available after Autogenerate analysis"

    def __init__(self, caption: str, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 5, 0, 5)
        layout.setSpacing(8)

        self.name_label = QLabel(caption)
        self.name_label.setFont(mono_font(9))
        self.name_label.setProperty("role", "micro")
        layout.addWidget(self.name_label)
        layout.addStretch()

        self.value_label = QLabel(self.PLACEHOLDER)
        self.value_label.setObjectName("AnalysisValue")
        self.value_label.setFont(mono_font(9))
        layout.addWidget(self.value_label)

        self._tokens = _active_tokens()
        self.set_value(None)

    def apply_tokens(self, tokens: dict) -> None:
        self._tokens = tokens
        self.set_value(self._value)

    def set_value(self, text) -> None:
        """``None`` renders the dim placeholder with the explanatory
        tooltip; a string renders in the theme's primary text color."""
        self._value = text
        tokens = self._tokens
        if text is None:
            self.value_label.setText(self.PLACEHOLDER)
            self.value_label.setToolTip(self.PLACEHOLDER_TOOLTIP)
            self.setToolTip(self.PLACEHOLDER_TOOLTIP)
            color = tokens["text_disabled"]
        else:
            self.value_label.setText(text)
            self.value_label.setToolTip("")
            self.setToolTip("")
            color = tokens["text"]
        self.value_label.setStyleSheet(
            f"color: {color}; background: transparent;")


class TimeSignatureWidget(QWidget):
    """Custom widget for editing time signature with two spinboxes."""

    valueChanged = pyqtSignal(str)  # Emits signature as "4/4" string

    def __init__(self, signature: str = "4/4", parent=None):
        super().__init__(parent)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 0, 4, 0)
        layout.setSpacing(2)

        # Parse initial signature
        try:
            num, denom = map(int, signature.split('/'))
        except (ValueError, AttributeError):
            num, denom = 4, 4

        # Numerator spinbox
        self.numerator = QSpinBox()
        self.numerator.setRange(1, 99)
        self.numerator.setValue(num)
        self.numerator.setMaximumWidth(50)
        self.numerator.valueChanged.connect(self._on_value_changed)
        layout.addWidget(self.numerator)

        # Separator
        separator = QLabel("/")
        separator.setStyleSheet("color: white;")
        layout.addWidget(separator)

        # Denominator spinbox
        self.denominator = QSpinBox()
        self.denominator.setRange(1, 99)
        self.denominator.setValue(denom)
        self.denominator.setMaximumWidth(50)
        self.denominator.valueChanged.connect(self._on_value_changed)
        layout.addWidget(self.denominator)

        layout.addStretch()

    def _on_value_changed(self):
        """Emit valueChanged signal when either spinbox changes."""
        self.valueChanged.emit(self.get_signature())

    def get_signature(self) -> str:
        """Get current signature as string (e.g., '4/4')."""
        return f"{self.numerator.value()}/{self.denominator.value()}"

    def set_signature(self, signature: str):
        """Set signature from string (e.g., '4/4')."""
        try:
            num, denom = map(int, signature.split('/'))
            self.numerator.blockSignals(True)
            self.denominator.blockSignals(True)
            self.numerator.setValue(num)
            self.denominator.setValue(denom)
            self.numerator.blockSignals(False)
            self.denominator.blockSignals(False)
        except (ValueError, AttributeError):
            pass


class ColorButton(QPushButton):
    """Button that opens color picker and displays current color."""

    colorChanged = pyqtSignal(str)  # Emits color as hex string

    def __init__(self, color: str = "#FFFFFF", parent=None):
        super().__init__(parent)
        self.current_color = QColor(color)
        self.setMinimumHeight(25)
        self.clicked.connect(self._pick_color)
        self._update_style()

    def _pick_color(self):
        """Open color picker dialog."""
        # Temporarily clear stylesheet to avoid affecting dialog
        original_stylesheet = self.styleSheet()
        self.setStyleSheet("")

        color = QColorDialog.getColor(self.current_color, self, "Select Color")

        # Restore stylesheet
        self.setStyleSheet(original_stylesheet)

        if color.isValid():
            self.current_color = color
            self._update_style()
            self.colorChanged.emit(color.name())

    def _update_style(self):
        """Update button background to show current color and display hex value."""
        # Calculate contrasting text color (black or white)
        # Use luminance formula to determine if color is light or dark
        r = self.current_color.red()
        g = self.current_color.green()
        b = self.current_color.blue()
        luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255
        text_color = "#000000" if luminance > 0.5 else "#FFFFFF"

        self.setText(self.current_color.name().upper())
        self.setStyleSheet(f"""
            QPushButton {{
                background-color: {self.current_color.name()};
                color: {text_color};
                border: 1px solid #666;
                border-radius: 3px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                border: 2px solid #999;
            }}
        """)

    def get_color(self) -> str:
        """Get current color as hex string."""
        return self.current_color.name()

    def set_color(self, color: str):
        """Set color from hex string."""
        self.current_color = QColor(color)
        self._update_style()


class PartCard(QWidget):
    """One song part as a reference card: 190px wide, 14px/16px padding,
    a 3px top bar and a low-alpha tint in the part's data color, the
    name in condensed caps, then the mono "8 BARS . 4/4" line and a
    "<bpm> BPM" line whose number is bright and whose unit is secondary.

    Display-only; editing happens in the part inspector. Emits
    ``clicked(index)`` on press.
    """

    clicked = pyqtSignal(int)

    CARD_WIDTH = 190

    def __init__(self, index: int, parent=None):
        super().__init__(parent)
        self.index = index
        self.setObjectName("PartCard")
        # Theme chrome: 1px border from role="card", accent border when
        # selected="true" (same convention as the Universes row cards).
        self.setProperty("role", "card")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedWidth(self.CARD_WIDTH)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 12)
        layout.setSpacing(0)

        self.name_label = DisplayLabel("", point_size=15,
                                       weight=QFont.Weight.Bold,
                                       tracking_em=0.06)
        self.name_label.setObjectName("PartCardName")
        layout.addWidget(self.name_label)

        layout.addSpacing(8)

        self.meta_label = QLabel("")
        self.meta_label.setObjectName("PartCardMeta")
        self.meta_label.setFont(mono_font(9))
        layout.addWidget(self.meta_label)

        # "<value> BPM": value in $text$, unit in $text_secondary$ (the
        # reference splits the line into two colors).
        bpm_row = QHBoxLayout()
        bpm_row.setContentsMargins(0, 4, 0, 0)
        bpm_row.setSpacing(5)
        self.bpm_label = QLabel("")
        self.bpm_label.setObjectName("PartCardBpm")
        self.bpm_label.setFont(mono_font(9))
        bpm_row.addWidget(self.bpm_label)
        self.bpm_unit_label = QLabel("BPM")
        self.bpm_unit_label.setObjectName("PartCardBpmUnit")
        self.bpm_unit_label.setFont(mono_font(9))
        bpm_row.addWidget(self.bpm_unit_label)
        bpm_row.addStretch()
        layout.addLayout(bpm_row)

        layout.addStretch(1)

    def update_data(self, part: ShowPart, selected: bool,
                    playing: bool = False, tokens: dict = None) -> None:
        self.name_label.setText(part.name)
        self.meta_label.setText(f"{part.num_bars} BARS · {part.signature}")
        self.bpm_label.setText(f"{part.bpm:.1f}")
        self._apply_part_style(part.color, selected, playing,
                               tokens or _active_tokens())

    def _apply_part_style(self, color: str, selected: bool,
                          playing: bool, tokens: dict) -> None:
        """Part colors are data colors, so tint + 3px top bar are a
        widget-local stylesheet (the sanctioned pattern, see
        light_lane_widget._apply_group_border). The 1px chrome border and
        the accent selected border stay with the theme's role="card"
        rules; only background and border-top are overridden here."""
        tint = QColor(color)
        if not tint.isValid():
            tint = QColor(tokens["text_secondary"])
        # Reference alphas: 0.12 idle, 0.14 selected. The playing tint is
        # ours (no playhead in a static mockup).
        alpha = "24%" if playing else ("14%" if selected else "12%")
        rgb = f"{tint.red()}, {tint.green()}, {tint.blue()}"
        rules = [
            f"QWidget#PartCard {{"
            f" background-color: rgba({rgb}, {alpha});"
            f" border-top: 3px solid {tint.name()}; }}",
            "QLabel#PartCardMeta, QLabel#PartCardBpmUnit"
            f" {{ color: {tokens['text_secondary']};"
            " background: transparent; }",
            f"QLabel#PartCardBpm {{ color: {tokens['text']};"
            " background: transparent; }",
        ]
        # Selection reads as accent everywhere in the design system: the
        # theme paints the 1px accent border via [selected="true"], the
        # title follows it.
        title_color = tokens["accent_line"] if selected else tokens["text"]
        rules.append(f"QLabel#PartCardName {{ color: {title_color};"
                     " background: transparent; }")
        self.setStyleSheet("\n".join(rules))
        self.setProperty("selected", "true" if selected else "false")
        style = self.style()
        if style:
            style.unpolish(self)
            style.polish(self)

    def mousePressEvent(self, event):
        self.clicked.emit(self.index)
        event.accept()


class StructureTab(BaseTab):
    """Tab for editing show structure (reference screen 05).

    Features:
    - Song parts as colored cards (3px top bar + tint in the part color)
      with transition chips between them and a dashed add tile
    - Master grid (master timeline + audio waveform) below the strip
    - Part inspector on the right: stat tiles, all editing (name, BPM,
      signature, bars, transition, color, reorder, delete) and the
      AUDIO ANALYSIS read-outs
    - Action-strip audio readout + "AUTOGENERATE SHOW..." entry point
    - CSV import/export, MIDI triggers, Pause Show, audio playback
    """

    #: Emitted with the current show name when the action strip's
    #: AUTOGENERATE button is pressed. A shell that wants to own the
    #: flow (e.g. so generated lanes land in the Timeline tab's lane
    #: widgets) can connect this; when nothing is connected and no
    #: sibling Shows tab is reachable, the tab runs the same
    #: AutogenDialog flow itself and writes the lanes into the show.
    autogenerate_requested = pyqtSignal(str)

    def __init__(self, config: Configuration, parent=None):
        self.current_show_name = ""
        self.current_show = None

        # Parts strip / inspector state (set before setup_ui runs)
        self._selected_index = -1
        self._playing_index = -1
        self._cards = []
        self._chips = []

        # Generation report from this tab's own autogen run (the sibling
        # Shows tab's report is used when we have none of our own).
        self._autogen_report = None

        # Playback state
        self.is_playing = False
        self.playhead_position = 0.0

        # Audio components (lazy init)
        self.audio_engine = None
        self.audio_mixer = None
        self.playback_sync = None
        self.device_manager = None

        # Playback timer
        self.playback_timer = QTimer()
        self.playback_timer.setInterval(16)  # ~60 FPS
        self.playback_timer.timeout.connect(self._update_playback)

        # Flag to prevent recursive activation
        self._is_activating = False

        # Active theme tokens; refreshed on every update_from_config so a
        # theme switch re-colors the data-colored bits.
        self._tokens = None

        super().__init__(config, parent)

    def setup_ui(self):
        """Build the reference screen: action strip, main column (show
        row, parts strip, master grid + hint), 400px part inspector,
        transport + Pause Show rows, mono status strip."""
        self._tokens = _active_tokens()

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        main_layout.addWidget(self._create_action_strip())

        # Keep reference to song structure for duration calculations
        self.song_structure = None

        # Build order matters: the parts strip refreshes the inspector,
        # the grid caption and the status strip while it populates, so
        # all three must exist before _create_parts_strip runs.
        inspector = self._build_inspector()
        self.grid_caption = MicroLabel("Master grid", point_size=8,
                                       tracking_em=0.12)
        status_strip = self._create_status_strip()

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        left_host = QWidget()
        left_column = QVBoxLayout(left_host)
        left_column.setContentsMargins(28, 28, 28, 28)
        left_column.setSpacing(28)

        # Show management + trigger assignment (no home in the reference
        # screen, which only shows one song; kept as a compact row).
        left_column.addLayout(self._create_show_row())

        # Parts strip: micro caption + horizontal card row.
        parts_section = QVBoxLayout()
        parts_section.setSpacing(12)
        self.parts_caption = MicroLabel("Parts · Select to edit",
                                        point_size=8, tracking_em=0.12)
        parts_section.addWidget(self.parts_caption)
        parts_section.addWidget(self._create_parts_strip())
        left_column.addLayout(parts_section)

        # Master grid: micro caption + shared master/audio grid.
        # Master + audio share a single horizontal scrollbar inside
        # TimelineGrid. Lane references stay so signal/method dispatch works.
        grid_section = QVBoxLayout()
        grid_section.setSpacing(12)
        grid_section.addWidget(self.grid_caption)
        self.master_timeline = MasterTimelineContainer()
        self.audio_lane = AudioLaneWidget()
        self.timeline_grid = TimelineGrid()
        self.timeline_grid.set_master(self.master_timeline)
        self.timeline_grid.set_audio_lane(self.audio_lane)
        self.timeline_grid.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed
        )
        # Structure tab only ever has master + audio rows - no light lanes -
        # so vertical scrolling inside the grid makes no sense here. Force
        # the scrollbar off; otherwise small height-budget squeezes (e.g.
        # the master row height bump in v1.0) leave room for Qt to decide
        # the content is one pixel too tall and pop the scrollbar in.
        self.timeline_grid.stripes_scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        # Cap the grid height so the sections below still get space.
        # 200 / 240 fits the current 76-px master + 100-px audio + horizontal
        # scrollbar + frame margins comfortably on both Windows and Linux Qt
        # builds, with belt-and-braces headroom in case row metrics shift.
        self.timeline_grid.setMinimumHeight(200)
        self.timeline_grid.setMaximumHeight(240)
        grid_section.addWidget(self.timeline_grid)
        grid_section.addLayout(self._create_grid_hint_row())
        left_column.addLayout(grid_section)
        left_column.addStretch(1)

        body.addWidget(left_host, 1)
        body.addWidget(inspector)
        main_layout.addLayout(body, 1)

        # Transport + Pause Show: no home in the reference screen, kept
        # reachable in a footer block above the status strip.
        footer = QWidget()
        footer_column = QVBoxLayout(footer)
        footer_column.setContentsMargins(28, 0, 28, 10)
        footer_column.setSpacing(8)
        footer_column.addWidget(self._create_pause_show_section())
        footer_column.addLayout(self._create_playback_controls())
        main_layout.addWidget(footer)

        main_layout.addWidget(status_strip)

    def _create_action_strip(self) -> QWidget:
        """38px strip: mono audio readout + AUTOGENERATE SHOW button.

        No tab title - the shell subnav already names the screen.
        """
        strip = QWidget()
        strip.setObjectName("StructureActionStrip")
        strip.setFixedHeight(38)
        row = QHBoxLayout(strip)
        row.setContentsMargins(16, 0, 16, 0)
        row.setSpacing(10)
        row.addStretch()

        # "neon_ruinen.wav · 03:42 · " + green "ANALYZED". Two labels
        # because a QLabel cannot carry two colors without rich text.
        self.audio_readout = QLabel("no audio loaded")
        self.audio_readout.setObjectName("AudioReadout")
        self.audio_readout.setFont(mono_font(8))
        row.addWidget(self.audio_readout)

        self.audio_status = QLabel("ANALYZED")
        self.audio_status.setObjectName("AudioReadoutStatus")
        self.audio_status.setFont(mono_font(8))
        self.audio_status.hide()
        row.addWidget(self.audio_status)

        # Bordered display-caps CTA (the reference's outlined button:
        # transparent fill, 1px $border$, Barlow Condensed caps).
        self.autogen_btn = QPushButton("AUTOGENERATE SHOW...")
        self.autogen_btn.setObjectName("AutogenButton")
        self._autogen_font = display_font(11, QFont.Weight.DemiBold,
                                          tracking_em=0.08)
        self.autogen_btn.setFont(self._autogen_font)
        self.autogen_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.autogen_btn.setToolTip(
            "Analyze the audio and generate a light show for this song")
        # Pin the width from the display font's own metrics (theme's
        # 14px horizontal padding + border + slack) so the glyph never
        # clips inside the content rect and the geometry stays stable
        # for pixel diffs.
        metrics = QFontMetrics(self._autogen_font)
        self.autogen_btn.setFixedWidth(
            metrics.horizontalAdvance(self.autogen_btn.text()) + 40)
        row.addSpacing(6)
        row.addWidget(self.autogen_btn)

        self._style_action_strip()
        return strip

    def _style_action_strip(self):
        """The audio readout's dim/green states (data-ish states, kept
        widget-local). The CTA's chrome is theme-owned via
        ``QPushButton[role="cta-outline"]``.
        """
        tokens = self._tokens or _active_tokens()
        has_audio = self.audio_readout.text() != "no audio loaded"
        color = tokens["text_secondary"] if has_audio else tokens["text_disabled"]
        self.audio_readout.setStyleSheet(
            f"color: {color}; background: transparent;")
        self.audio_status.setStyleSheet(
            f"color: {tokens['success']}; background: transparent;")
        self.autogen_btn.setProperty("role", "cta-outline")
        style = self.autogen_btn.style()
        if style:
            style.unpolish(self.autogen_btn)
            style.polish(self.autogen_btn)

    def _create_grid_hint_row(self) -> QHBoxLayout:
        """The mono line under the master grid: snap resolutions, a
        separator dot, and what the grid governs."""
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)
        row.addWidget(MicroLabel("Snap: bar · 1/2 beat · 1/4 beat",
                                 point_size=8, tracking_em=0.12))
        dot = QLabel("·")
        dot.setFont(mono_font(8))
        dot.setProperty("role", "micro")
        row.addWidget(dot)
        # Plain QLabel (not MicroLabel): sentence case must survive, and
        # role="micro" still hands it the secondary color from the theme.
        self.grid_hint = QLabel(
            "Every downstream feature snaps to this grid: timeline "
            "blocks, riffs, autogen phrases.")
        self.grid_hint.setObjectName("GridHint")
        self.grid_hint.setFont(mono_font(8))
        self.grid_hint.setProperty("role", "micro")
        row.addWidget(self.grid_hint)
        row.addStretch()
        return row

    def _create_status_strip(self) -> QWidget:
        """26px mono footer: "N PARTS · N BARS · mm:ss"."""
        strip = QWidget()
        strip.setObjectName("StructureStatusStrip")
        strip.setFixedHeight(26)
        row = QHBoxLayout(strip)
        row.setContentsMargins(16, 0, 16, 0)
        row.setSpacing(24)
        self.status_summary = MicroLabel("0 parts", point_size=8,
                                         tracking_em=0.1)
        row.addWidget(self.status_summary)
        row.addStretch()
        return strip

    PARTS_STRIP_HEIGHT = 128

    def _create_parts_strip(self) -> QWidget:
        """Horizontal strip of part cards with transition chips between
        them and a dashed add tile at the end (card 1e anatomy)."""
        self.parts_host = QWidget()
        self.parts_host.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu)
        self.parts_host.customContextMenuRequested.connect(
            self._show_context_menu)
        self.parts_row = QHBoxLayout(self.parts_host)
        self.parts_row.setContentsMargins(0, 0, 0, 0)
        self.parts_row.setSpacing(0)

        # Persistent add tile (re-attached on every strip rebuild).
        # Dashed chrome comes from the theme's role="add-tile".
        self.add_part_tile = QPushButton("+")
        self.add_part_tile.setObjectName("AddPartTile")
        self.add_part_tile.setProperty("role", "add-tile")
        self.add_part_tile.setFixedSize(44, 44)
        self.add_part_tile.setCursor(Qt.CursorShape.PointingHandCursor)
        self.add_part_tile.setToolTip("Add Part")

        self.parts_scroll = QScrollArea()
        self.parts_scroll.setWidgetResizable(True)
        self.parts_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.parts_scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.parts_scroll.setWidget(self.parts_host)
        self.parts_scroll.setFixedHeight(self.PARTS_STRIP_HEIGHT)

        self._rebuild_parts_strip()
        return self.parts_scroll

    INSPECTOR_WIDTH = 400

    def _build_inspector(self) -> QWidget:
        """The 400px part inspector (reference detail column).

        Reference order: part name in display caps *in the part color*,
        the 2x2 stat-tile grid, then (ours) the editors that used to be
        table cell widgets, the TRANSITION OUT combo, the AUDIO ANALYSIS
        rows and the destructive Delete Part footer.
        """
        panel = QWidget()
        panel.setObjectName("PartInspector")
        panel.setProperty("role", "inspector")
        panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        panel.setFixedWidth(self.INSPECTOR_WIDTH)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(10)

        self.inspector_title = DisplayLabel("No part selected",
                                            point_size=13,
                                            weight=QFont.Weight.Bold,
                                            tracking_em=0.05)
        self.inspector_title.setObjectName("PartInspectorTitle")
        layout.addWidget(self.inspector_title)

        # 2x2 read-out tiles (BPM / TIME SIG / BARS / DURATION).
        tiles = QGridLayout()
        tiles.setHorizontalSpacing(10)
        tiles.setVerticalSpacing(10)
        self.stat_bpm = StatTile("BPM")
        self.stat_signature = StatTile("Time sig")
        self.stat_bars = StatTile("Bars")
        self.stat_duration = StatTile("Duration")
        tiles.addWidget(self.stat_bpm, 0, 0)
        tiles.addWidget(self.stat_signature, 0, 1)
        tiles.addWidget(self.stat_bars, 1, 0)
        tiles.addWidget(self.stat_duration, 1, 1)
        self._stat_tiles = (self.stat_bpm, self.stat_signature,
                            self.stat_bars, self.stat_duration)
        layout.addLayout(tiles)

        # Editors: the write path. The tiles above are pure read-outs and
        # refresh from these.
        layout.addWidget(MicroLabel("Name", point_size=8, tracking_em=0.1))
        self.part_name_edit = QLineEdit()
        layout.addWidget(self.part_name_edit)

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(4)
        grid.addWidget(MicroLabel("BPM", point_size=8, tracking_em=0.1),
                       0, 0)
        grid.addWidget(MicroLabel("Time sig", point_size=8,
                                  tracking_em=0.1), 0, 1)
        self.bpm_spin = QDoubleSpinBox()
        self.bpm_spin.setRange(1.0, 999.0)
        self.bpm_spin.setDecimals(1)
        self.bpm_spin.setSingleStep(1.0)  # Scroll/arrow increment by 1 BPM
        grid.addWidget(self.bpm_spin, 1, 0)
        self.signature_widget = TimeSignatureWidget("4/4")
        grid.addWidget(self.signature_widget, 1, 1)
        grid.addWidget(MicroLabel("Bars", point_size=8, tracking_em=0.1),
                       2, 0)
        grid.addWidget(MicroLabel("Color", point_size=8,
                                  tracking_em=0.1), 2, 1)
        self.bars_spin = QSpinBox()
        self.bars_spin.setRange(1, 9999)
        grid.addWidget(self.bars_spin, 3, 0)
        self.part_color_btn = ColorButton("#4CAF50")
        grid.addWidget(self.part_color_btn, 3, 1)
        layout.addLayout(grid)

        move_row = QHBoxLayout()
        move_row.setSpacing(6)
        self.move_left_btn = QPushButton("< Move")
        self.move_left_btn.setToolTip("Move part earlier")
        move_row.addWidget(self.move_left_btn)
        self.move_right_btn = QPushButton("Move >")
        self.move_right_btn.setToolTip("Move part later")
        move_row.addWidget(self.move_right_btn)
        layout.addLayout(move_row)

        layout.addWidget(MicroLabel("Transition out", point_size=8,
                                    tracking_em=0.1))
        self.transition_combo = QComboBox()
        self.transition_combo.addItems(["instant", "gradual"])
        layout.addWidget(self.transition_combo)

        layout.addSpacing(4)
        layout.addWidget(MicroLabel("Audio analysis", point_size=8,
                                    tracking_em=0.1))
        self.analysis_energy = AnalysisRow("Energy")
        self.analysis_vocals = AnalysisRow("Vocals")
        self.analysis_contrast = AnalysisRow("Contrast")
        self._analysis_rows = (self.analysis_energy, self.analysis_vocals,
                               self.analysis_contrast)
        for analysis_row in self._analysis_rows:
            layout.addWidget(analysis_row)

        layout.addStretch(1)

        self.delete_part_btn = QPushButton("- Delete Part")
        self.delete_part_btn.setProperty("role", "destructive")
        layout.addWidget(self.delete_part_btn)

        return panel

    def _create_show_row(self):
        """Compact show-management row: selector, new/rename/delete, the
        shows-directory hint button, and the MIDI trigger assignment."""
        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(0, 0, 0, 0)
        toolbar.setSpacing(8)

        toolbar.addWidget(MicroLabel("Show", point_size=8, tracking_em=0.12))

        self.show_combo = QComboBox()
        self.show_combo.setMinimumWidth(200)
        toolbar.addWidget(self.show_combo)

        # New show button
        self.new_show_btn = QPushButton("+ New")
        self.new_show_btn.setProperty("role", "success")
        toolbar.addWidget(self.new_show_btn)

        # Rename show button (default neutral styling — non-destructive secondary action)
        self.rename_show_btn = QPushButton("Rename")
        toolbar.addWidget(self.rename_show_btn)

        # Delete show button
        self.delete_show_btn = QPushButton("Delete Show")
        self.delete_show_btn.setProperty("role", "destructive")
        toolbar.addWidget(self.delete_show_btn)

        toolbar.addSpacing(16)

        # Trigger assignment
        toolbar.addWidget(MicroLabel("Trigger", point_size=8,
                                     tracking_em=0.12))

        self.trigger_device_combo = QComboBox()
        self.trigger_device_combo.setMinimumWidth(160)
        self.trigger_device_combo.addItem("No Trigger")
        self.trigger_device_combo.addItem("None")  # Generic MIDI (no profile)
        # Populate with discovered MIDI profiles
        self._midi_profiles = []
        try:
            from utils.midi_utils import discover_midi_profiles
            self._midi_profiles = discover_midi_profiles()
            for profile in self._midi_profiles:
                self.trigger_device_combo.addItem(profile['name'])
        except Exception:
            pass
        toolbar.addWidget(self.trigger_device_combo)

        toolbar.addWidget(MicroLabel("Ch", point_size=8, tracking_em=0.12))

        self.trigger_channel_spin = QSpinBox()
        self.trigger_channel_spin.setRange(1, 512)
        self.trigger_channel_spin.setValue(1)
        self.trigger_channel_spin.setEnabled(False)
        self.trigger_channel_spin.setFixedWidth(70)
        toolbar.addWidget(self.trigger_channel_spin)

        toolbar.addSpacing(16)

        # Set directory button (primary action for the show toolbar)
        self.set_directory_btn = QPushButton("Set Show Directory")
        self.set_directory_btn.setProperty("role", "primary")
        toolbar.addWidget(self.set_directory_btn)

        toolbar.addStretch()

        return toolbar

    def _create_pause_show_section(self):
        """Create the Pause Show configuration section. Box styling comes
        from the active theme's QGroupBox rules."""
        group_box = QGroupBox("Pause Show")

        layout = QHBoxLayout()
        layout.setSpacing(10)

        # Enable checkbox
        self.pause_enable_cb = QCheckBox("Enable")
        layout.addWidget(self.pause_enable_cb)

        layout.addSpacing(10)

        # Color picker
        color_label = QLabel("Color:")
        layout.addWidget(color_label)

        self.pause_color_btn = ColorButton("#0000FF")
        self.pause_color_btn.setFixedWidth(80)
        self.pause_color_btn.setEnabled(False)
        layout.addWidget(self.pause_color_btn)

        layout.addSpacing(10)

        # MIDI trigger device
        trigger_label = QLabel("Trigger:")
        layout.addWidget(trigger_label)

        self.pause_trigger_device_combo = QComboBox()
        self.pause_trigger_device_combo.setMinimumWidth(160)
        self.pause_trigger_device_combo.addItem("No Trigger")
        self.pause_trigger_device_combo.addItem("None")  # Generic MIDI
        for profile in self._midi_profiles:
            self.pause_trigger_device_combo.addItem(profile['name'])
        self.pause_trigger_device_combo.setEnabled(False)
        layout.addWidget(self.pause_trigger_device_combo)

        # MIDI channel
        ch_label = QLabel("Ch:")
        layout.addWidget(ch_label)

        self.pause_trigger_channel_spin = QSpinBox()
        self.pause_trigger_channel_spin.setRange(1, 512)
        self.pause_trigger_channel_spin.setValue(1)
        self.pause_trigger_channel_spin.setEnabled(False)
        self.pause_trigger_channel_spin.setFixedWidth(70)
        layout.addWidget(self.pause_trigger_channel_spin)

        layout.addStretch()

        group_box.setLayout(layout)

        # Connect signals
        self.pause_enable_cb.toggled.connect(self._on_pause_enable_changed)
        self.pause_color_btn.colorChanged.connect(self._on_pause_color_changed)
        self.pause_trigger_device_combo.currentTextChanged.connect(self._on_pause_trigger_device_changed)
        self.pause_trigger_channel_spin.valueChanged.connect(self._on_pause_trigger_channel_changed)

        return group_box

    def _on_pause_enable_changed(self, enabled):
        """Handle pause show enable/disable toggle."""
        self.config.pause_show.enabled = enabled
        self.pause_color_btn.setEnabled(enabled)
        self.pause_trigger_device_combo.setEnabled(enabled)
        has_device = enabled and self.pause_trigger_device_combo.currentText() not in ("No Trigger", "")
        self.pause_trigger_channel_spin.setEnabled(has_device)
        self._auto_save()

    def _on_pause_color_changed(self, color):
        """Handle pause show color change."""
        self.config.pause_show.color = color
        self._auto_save()

    def _on_pause_trigger_device_changed(self, device_name):
        """Handle pause show trigger device change."""
        if device_name == "No Trigger" or not device_name:
            self.config.pause_show.trigger_device = ""
            self.config.pause_show.trigger_channel = -1
            self.pause_trigger_channel_spin.setEnabled(False)
            self.pause_trigger_channel_spin.setValue(1)
        else:
            self.config.pause_show.trigger_device = device_name
            self.pause_trigger_channel_spin.setEnabled(True)
            if self.config.pause_show.trigger_channel < 0:
                self.config.pause_show.trigger_channel = 1
            self._ensure_midi_device(device_name)
        self._auto_save()

    def _on_pause_trigger_channel_changed(self, channel):
        """Handle pause show trigger channel change."""
        self.config.pause_show.trigger_channel = channel
        self._auto_save()

    def _update_pause_show_widgets(self):
        """Update pause show widgets from config."""
        self.pause_enable_cb.blockSignals(True)
        self.pause_color_btn.blockSignals(True)
        self.pause_trigger_device_combo.blockSignals(True)
        self.pause_trigger_channel_spin.blockSignals(True)

        ps = self.config.pause_show
        self.pause_enable_cb.setChecked(ps.enabled)
        self.pause_color_btn.set_color(ps.color)
        self.pause_color_btn.setEnabled(ps.enabled)
        self.pause_trigger_device_combo.setEnabled(ps.enabled)

        if ps.trigger_device:
            idx = self.pause_trigger_device_combo.findText(ps.trigger_device)
            if idx >= 0:
                self.pause_trigger_device_combo.setCurrentIndex(idx)
            else:
                self.pause_trigger_device_combo.addItem(ps.trigger_device)
                self.pause_trigger_device_combo.setCurrentText(ps.trigger_device)
            self.pause_trigger_channel_spin.setEnabled(ps.enabled)
            self.pause_trigger_channel_spin.setValue(max(1, ps.trigger_channel))
        else:
            self.pause_trigger_device_combo.setCurrentIndex(0)
            self.pause_trigger_channel_spin.setEnabled(False)
            self.pause_trigger_channel_spin.setValue(1)

        self.pause_enable_cb.blockSignals(False)
        self.pause_color_btn.blockSignals(False)
        self.pause_trigger_device_combo.blockSignals(False)
        self.pause_trigger_channel_spin.blockSignals(False)

    def _create_playback_controls(self):
        """Create bottom playback control bar."""
        controls = QHBoxLayout()
        controls.setSpacing(10)

        # Playback buttons (transport — colors from active theme via role props).
        self.play_btn = QPushButton("Play")
        self.play_btn.setFixedWidth(70)
        self.play_btn.setProperty("role", "success")
        controls.addWidget(self.play_btn)

        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setFixedWidth(70)
        self.stop_btn.setProperty("role", "destructive")
        controls.addWidget(self.stop_btn)

        controls.addSpacing(20)

        # Time display — styled by `#TimeReadout` rule in the active theme.
        self.time_label = QLabel("00:00.00")
        self.time_label.setObjectName("TimeReadout")
        self.time_label.setFixedWidth(100)
        controls.addWidget(self.time_label)

        controls.addSpacing(10)

        # Position slider
        self.position_slider = QSlider(Qt.Orientation.Horizontal)
        self.position_slider.setRange(0, 1000)
        self.position_slider.setValue(0)
        controls.addWidget(self.position_slider, 1)

        # Total time display
        self.total_time_label = QLabel("/ 00:00")
        self.total_time_label.setObjectName("TimeReadoutSecondary")
        controls.addWidget(self.total_time_label)

        return controls

    def connect_signals(self):
        """Connect widget signals."""
        # Show selection
        self.show_combo.currentTextChanged.connect(self._on_show_changed)

        # Toolbar buttons
        self.new_show_btn.clicked.connect(self._create_new_show)
        self.rename_show_btn.clicked.connect(self._rename_show)
        self.delete_show_btn.clicked.connect(self._delete_show)
        self.set_directory_btn.clicked.connect(self._set_show_directory)
        self.trigger_device_combo.currentTextChanged.connect(self._on_trigger_device_changed)
        self.trigger_channel_spin.valueChanged.connect(self._on_trigger_channel_changed)

        # Action strip
        self.autogen_btn.clicked.connect(self._on_autogenerate)

        # Parts strip buttons
        self.add_part_tile.clicked.connect(self._add_new_part)
        self.delete_part_btn.clicked.connect(self._delete_part)

        # Part inspector editors (act on the selected part)
        self.part_name_edit.textEdited.connect(self._on_part_name_edited)
        self.bpm_spin.valueChanged.connect(self._on_bpm_changed)
        self.signature_widget.valueChanged.connect(self._on_signature_changed)
        self.bars_spin.valueChanged.connect(self._on_bars_changed)
        self.transition_combo.currentTextChanged.connect(
            self._on_transition_changed)
        self.part_color_btn.colorChanged.connect(self._on_color_changed)
        self.move_left_btn.clicked.connect(lambda: self._move_part(-1))
        self.move_right_btn.clicked.connect(lambda: self._move_part(1))

        # Playback controls
        self.play_btn.clicked.connect(self._toggle_playback)
        self.stop_btn.clicked.connect(self._stop_playback)
        self.position_slider.sliderPressed.connect(self._on_position_slider_pressed)
        self.position_slider.sliderReleased.connect(self._on_position_slider_released)
        self.position_slider.valueChanged.connect(self._on_position_slider_changed)

        # TimelineGrid is the single source of truth for playhead/zoom/audio.
        self.timeline_grid.playhead_moved.connect(self._on_playhead_moved)
        self.timeline_grid.zoom_changed.connect(self._sync_zoom)
        self.timeline_grid.audio_file_changed.connect(self._on_audio_file_loaded)

    def _sync_zoom(self, zoom_factor: float):
        """Apply zoom to every stripe via the grid."""
        self.timeline_grid.set_zoom_factor(zoom_factor)

    def _on_playhead_moved(self, position: float):
        """Handle playhead position change from timeline click."""
        self.playhead_position = position

        # Update master timeline playhead
        self.master_timeline.set_playhead_position(position)

        # Update audio lane playhead
        self.audio_lane.set_playhead_position(position)

    def _recalculate_structure(self):
        """Recalculate timing for all parts."""
        if not self.current_show or not self.current_show.parts:
            self.song_structure = None
            return

        self.song_structure = SongStructure()
        self.song_structure.load_from_show_parts(self.current_show.parts)

    def _rebuild_parts_strip(self):
        """Rebuild card + chip widgets from the current show's parts.

        The chip after card N shows part N's transition (the mockup's
        "TRANSITION OUT" semantic); the last part's transition only
        appears in the inspector."""
        # Recalculate durations first (cards show them via the inspector)
        self._recalculate_structure()

        # Detach the persistent add tile, clear everything else.
        while self.parts_row.count():
            item = self.parts_row.takeAt(0)
            widget = item.widget()
            if widget is self.add_part_tile:
                continue
            if widget:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
        self._cards = []
        self._chips = []

        parts = self.current_show.parts if self.current_show else []
        if self._selected_index >= len(parts):
            self._selected_index = len(parts) - 1

        for i in range(len(parts)):
            if i > 0:
                chip = Chip("", variant="neutral", point_size=8)
                self._chips.append(chip)
                self.parts_row.addSpacing(6)
                self.parts_row.addWidget(
                    chip, 0, Qt.AlignmentFlag.AlignVCenter)
                self.parts_row.addSpacing(6)
            card = PartCard(i)
            card.clicked.connect(self._select_part)
            self._cards.append(card)
            self.parts_row.addWidget(card)

        self.parts_row.addSpacing(14)
        self.parts_row.addWidget(self.add_part_tile, 0,
                                 Qt.AlignmentFlag.AlignVCenter)
        self.add_part_tile.show()
        self.parts_row.addStretch(1)

        self._refresh_cards()
        self._refresh_inspector()

    def _refresh_cards(self):
        """Push part data into the existing cards and chips."""
        parts = self.current_show.parts if self.current_show else []
        tokens = self._tokens or _active_tokens()
        for i, card in enumerate(self._cards):
            if i < len(parts):
                card.update_data(parts[i], i == self._selected_index,
                                 i == self._playing_index, tokens)
        for i, chip in enumerate(self._chips):
            if i < len(parts):
                # The chip after card N carries part N's transition out.
                # Literal model value, no invented crossfade lengths.
                chip.setText(parts[i].transition)
        self._update_grid_caption()
        self._update_status_strip()

    def _total_bars_and_duration(self):
        parts = self.current_show.parts if self.current_show else []
        total_bars = sum(p.num_bars for p in parts)
        total = (self.song_structure.get_total_duration()
                 if self.song_structure else 0.0)
        return len(parts), total_bars, total

    def _update_grid_caption(self):
        count, total_bars, total = self._total_bars_and_duration()
        if not count:
            self.grid_caption.setText("Master grid")
            return
        self.grid_caption.setText(
            f"Master grid · {total_bars} bars · {format_clock(total)}")

    def _update_status_strip(self):
        count, total_bars, total = self._total_bars_and_duration()
        noun = "part" if count == 1 else "parts"
        self.status_summary.setText(
            f"{count} {noun} · {total_bars} bars · {format_clock(total)}")

    # ------------------------------------------------------------------
    # Action strip: audio readout + autogenerate
    # ------------------------------------------------------------------
    def _generation_report(self):
        """The most recent autogen GenerationReport, if a sibling Shows
        tab holds one. Read-only lookup - nothing is stored on the model,
        so the AUDIO ANALYSIS rows fall back to their placeholder."""
        if getattr(self, "_autogen_report", None) is not None:
            return self._autogen_report
        window = self.window()
        shows_tab = getattr(window, "shows_tab", None) if window else None
        return getattr(shows_tab, "_generation_report", None)

    def _section_report(self, part: ShowPart):
        """The SectionReport for a part (matched by name, then by index)."""
        report = self._generation_report()
        sections = getattr(report, "sections", None) or []
        if not sections:
            return None
        target = (part.name or "").strip().lower()
        for section in sections:
            if (getattr(section, "name", "") or "").strip().lower() == target:
                return section
        index = self._selected_index
        if 0 <= index < len(sections):
            return sections[index]
        return None

    def _update_audio_readout(self):
        """Mono "<file>.wav · mm:ss" plus the green ANALYZED word once an
        autogen analysis has run for this session."""
        path = ""
        if self.current_show and self.current_show.timeline_data:
            path = self.current_show.timeline_data.audio_file_path or ""

        if not path:
            self.audio_readout.setText("no audio loaded")
            self.audio_status.hide()
            self._style_action_strip()
            return

        duration = 0.0
        audio_file = self.audio_lane.get_audio_file()
        if audio_file is not None:
            duration = float(getattr(audio_file, "duration", 0.0) or 0.0)
        if duration <= 0.0 and self.song_structure:
            duration = self.song_structure.get_total_duration()

        self.audio_readout.setText(
            f"{os.path.basename(path)} · {format_clock(duration)} ·")
        self.audio_status.setVisible(self._generation_report() is not None)
        self._style_action_strip()

    def _shows_tab_delegate(self):
        """A sibling Shows/Timeline tab that owns the autogen flow (it is
        where generated lanes become lane widgets)."""
        window = self.window()
        shows_tab = getattr(window, "shows_tab", None) if window else None
        if shows_tab is not None and hasattr(shows_tab, "_on_autogenerate"):
            return shows_tab
        return None

    def _on_autogenerate(self):
        """Run the same AutogenDialog flow the Timeline tab exposes.

        Preference order: hand off to the sibling Shows tab (its lane
        widgets consume the result), else let a connected shell handle
        ``autogenerate_requested``, else run the dialog + worker here and
        write the lanes into the show's timeline data.
        """
        if not self.current_show:
            QMessageBox.warning(self, "No Show Selected",
                                "Please select a show first.")
            return

        delegate = self._shows_tab_delegate()
        if delegate is not None:
            delegate._on_autogenerate()
            self._update_audio_readout()
            return

        if self.receivers(self.autogenerate_requested) > 0:
            self.autogenerate_requested.emit(self.current_show_name)
            return

        self._open_autogen_dialog()

    def _autogen_audio_path(self):
        """Absolute path of the current show's audio file, or None."""
        path = self.audio_lane.get_audio_file_path()
        if not path:
            return None
        if not os.path.isabs(path):
            bundle_dir = self.config.audio_bundle_dir()
            if not bundle_dir:
                return None
            path = os.path.join(bundle_dir, path)
        return path if os.path.exists(path) else None

    def _open_autogen_dialog(self):
        """Self-contained autogen path: same dialog + worker as the
        Timeline tab, result written into ``show.timeline_data.lanes``
        (the Timeline tab picks them up on its next refresh)."""
        from PyQt6.QtWidgets import QDialog
        from gui.dialogs.autogen_dialog import AutogenDialog, AutogenWorker

        show = self.current_show
        if not show.parts:
            QMessageBox.warning(self, "No Song Structure",
                                "Add song parts before generating a show.")
            return
        if not self.config.groups:
            QMessageBox.warning(self, "No Fixture Groups",
                                "Define fixture groups in the Fixtures tab "
                                "first.")
            return
        audio_path = self._autogen_audio_path()
        if not audio_path:
            QMessageBox.warning(self, "No Audio File",
                                "Load an audio file for this show first.")
            return

        dialog = AutogenDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        self._recalculate_structure()
        song_structure = self.song_structure or SongStructure()

        self.autogen_btn.setEnabled(False)
        self.autogen_btn.setText("GENERATING...")
        self._autogen_worker = AutogenWorker(
            audio_path, song_structure, self.config, dialog.result_config,
            dialog.result_key_signature, dialog.result_palette,
        )
        self._autogen_worker.finished.connect(self._on_autogen_finished)
        self._autogen_worker.error.connect(self._on_autogen_error)
        self._autogen_worker.start()

    def _reset_autogen_button(self):
        self.autogen_btn.setEnabled(True)
        self.autogen_btn.setText("AUTOGENERATE SHOW...")

    def _on_autogen_finished(self, lanes, report=None):
        """Store generated lanes on the show (the Timeline tab renders
        them) and keep the report for the AUDIO ANALYSIS rows."""
        from config.models import LightLane

        self._reset_autogen_button()
        self._autogen_report = report
        if not lanes:
            QMessageBox.information(self, "Auto-Generate",
                                    "No lanes were generated. Check fixture "
                                    "groups and song structure.")
            return
        if self.current_show.timeline_data is None:
            self.current_show.timeline_data = TimelineData()
        new_lanes = []
        for lane_data in lanes:
            lane = LightLane(lane_data.name)
            lane.fixture_targets = lane_data.fixture_targets
            lane.light_blocks = lane_data.light_blocks
            new_lanes.append(lane)
        self.current_show.timeline_data.lanes = new_lanes
        self._auto_save()
        self._refresh_inspector()
        self._update_audio_readout()
        QMessageBox.information(
            self, "Auto-Generate",
            f"Generated {len(new_lanes)} lanes. Open the Timeline tab to "
            "review them.")

    def _on_autogen_error(self, error_msg):
        self._reset_autogen_button()
        QMessageBox.critical(self, "Auto-Generate Error",
                             f"Generation failed:\n{error_msg}")

    def _selected_part(self):
        parts = self.current_show.parts if self.current_show else []
        if 0 <= self._selected_index < len(parts):
            return parts[self._selected_index]
        return None

    def _select_part(self, index: int):
        """Select a part card and load it into the inspector."""
        parts = self.current_show.parts if self.current_show else []
        self._selected_index = index if 0 <= index < len(parts) else -1
        self._refresh_cards()
        self._refresh_inspector()

    def _update_stat_tiles(self, part):
        """Push the selected part's read-outs into the 2x2 tile grid."""
        if part is None:
            for tile in self._stat_tiles:
                tile.set_value("-")
            return
        self.stat_bpm.set_value(f"{part.bpm:.1f}")
        self.stat_signature.set_value(part.signature)
        self.stat_bars.set_value(str(part.num_bars))
        self.stat_duration.set_value(f"{part.duration:.1f} s")

    def _update_analysis_rows(self, part):
        """AUDIO ANALYSIS rows from the autogen section report when one
        exists; otherwise the dim placeholder with its tooltip (the model
        carries no per-part audio features)."""
        section = self._section_report(part) if part is not None else None
        if section is None:
            for analysis_row in self._analysis_rows:
                analysis_row.set_value(None)
            return
        self.analysis_energy.set_value(
            energy_words(getattr(section, "relative_energy", 0.0)))
        self.analysis_vocals.set_value(
            vocal_words(getattr(section, "vocal_presence", 0.0)))
        self.analysis_contrast.set_value(
            contrast_words(getattr(section, "spectral_contrast", 0.0)))

    def _refresh_inspector(self):
        """Load the selected part into the inspector editors."""
        part = self._selected_part()
        editors = (self.part_name_edit, self.bpm_spin, self.signature_widget,
                   self.bars_spin, self.transition_combo, self.part_color_btn,
                   self.move_left_btn, self.move_right_btn,
                   self.delete_part_btn)
        for widget in editors:
            widget.setEnabled(part is not None)

        self._update_stat_tiles(part)
        self._update_analysis_rows(part)

        if part is None:
            self.inspector_title.setStyleSheet("")
            self.inspector_title.setText("No part selected")
            self.part_name_edit.setText("")
            return

        self.inspector_title.setText(part.name)
        # Part color is a data color: title tinted widget-locally.
        title_color = QColor(part.color)
        if title_color.isValid():
            self.inspector_title.setStyleSheet(
                f"color: {title_color.name()}; background: transparent;")
        else:
            self.inspector_title.setStyleSheet("")

        for widget in (self.bpm_spin, self.bars_spin, self.transition_combo):
            widget.blockSignals(True)
        self.part_name_edit.setText(part.name)  # textEdited: user-only
        self.bpm_spin.setValue(part.bpm)
        self.signature_widget.set_signature(part.signature)  # blocks itself
        self.bars_spin.setValue(part.num_bars)
        self.transition_combo.setCurrentText(part.transition)
        self.part_color_btn.set_color(part.color)  # emits only on pick
        for widget in (self.bpm_spin, self.bars_spin, self.transition_combo):
            widget.blockSignals(False)

        parts = self.current_show.parts
        self.move_left_btn.setEnabled(self._selected_index > 0)
        self.move_right_btn.setEnabled(
            self._selected_index < len(parts) - 1)

    def _add_new_part(self):
        """Add a new part to the current show."""
        if not self.current_show:
            QMessageBox.warning(self, "No Show", "Please create or select a show first.")
            return

        # Create new part with default values
        new_part = ShowPart(
            name=f"Part {len(self.current_show.parts) + 1}",
            color="#4CAF50",
            signature="4/4",
            bpm=120.0,
            num_bars=8,
            transition="instant"
        )

        # Add to show
        self.current_show.parts.append(new_part)

        # Select the new part, rebuild the strip, update timelines
        self._selected_index = len(self.current_show.parts) - 1
        self._rebuild_parts_strip()
        self._update_timelines()

        # Auto-save
        self._auto_save()

    def _refresh_selected_card(self):
        """Update the selected part's card (and chips) after an edit."""
        self._refresh_cards()

    def _on_part_name_edited(self, text: str):
        """Handle name edit from the inspector."""
        part = self._selected_part()
        if part is None:
            return
        part.name = text
        self.inspector_title.setText(part.name)
        self._recalculate_structure()
        self._refresh_selected_card()
        self._update_timelines()
        self._auto_save()

    def _on_bpm_changed(self, value: float):
        """Handle BPM spinbox change."""
        part = self._selected_part()
        if part is None:
            return
        part.bpm = value

        # Recalculate durations and update display
        self._recalculate_structure()
        self._refresh_selected_card()
        self._update_stat_tiles(part)
        self._update_timelines()
        self._auto_save()

    def _on_signature_changed(self, signature: str):
        """Handle time signature widget change."""
        part = self._selected_part()
        if part is None:
            return
        part.signature = signature

        # Recalculate durations and update display
        self._recalculate_structure()
        self._refresh_selected_card()
        self._update_stat_tiles(part)
        self._update_timelines()
        self._auto_save()

    def _on_bars_changed(self, value: int):
        """Handle bars spinbox change."""
        part = self._selected_part()
        if part is None:
            return
        part.num_bars = value

        # Recalculate durations and update display
        self._recalculate_structure()
        self._refresh_selected_card()
        self._update_stat_tiles(part)
        self._update_timelines()
        self._auto_save()

    def _on_transition_changed(self, transition: str):
        """Handle transition combobox change."""
        part = self._selected_part()
        if part is None:
            return
        part.transition = transition
        self._refresh_selected_card()  # chip between cards shows it
        self._auto_save()

    def _on_color_changed(self, color: str):
        """Handle color button change."""
        part = self._selected_part()
        if part is None:
            return
        part.color = color

        # Update card tint / top bar, inspector title and timelines
        self._refresh_selected_card()
        self._refresh_inspector()
        self._update_timelines()
        self._auto_save()

    def _move_part(self, delta: int):
        """Reorder: swap the selected part with its neighbor."""
        parts = self.current_show.parts if self.current_show else []
        source = self._selected_index
        target = source + delta
        if not (0 <= source < len(parts) and 0 <= target < len(parts)):
            return
        parts[source], parts[target] = parts[target], parts[source]
        self._selected_index = target
        self._rebuild_parts_strip()
        self._update_timelines()
        self._auto_save()

    def _update_timelines(self):
        """Update timeline widgets with current song structure."""
        if self.song_structure:
            self.audio_lane.set_song_structure(self.song_structure)
            self.master_timeline.timeline_widget.set_song_structure(self.song_structure)

    def _update_playing_highlight(self):
        """Emphasize the card whose part contains the playhead."""
        if not self.song_structure or not self.current_show:
            return

        playing = -1
        for i, part in enumerate(self.current_show.parts):
            if part.start_time <= self.playhead_position < part.start_time + part.duration:
                playing = i
                break

        if playing != self._playing_index:
            self._playing_index = playing
            self._refresh_cards()

    def _apply_tokens(self):
        """Re-read the active theme's tokens and push them into the
        widget-local (data-colored) chrome."""
        self._tokens = _active_tokens()
        for tile in self._stat_tiles:
            tile.apply_tokens(self._tokens)
        for analysis_row in self._analysis_rows:
            analysis_row.apply_tokens(self._tokens)
        self._style_action_strip()

    def update_from_config(self):
        """Refresh from configuration."""
        self._apply_tokens()

        # Update show combo
        current = self.show_combo.currentText()
        self.show_combo.blockSignals(True)
        self.show_combo.clear()
        self.show_combo.addItems(sorted(self.config.shows.keys()))

        if current and current in self.config.shows:
            self.show_combo.setCurrentText(current)
        elif self.config.shows:
            self.show_combo.setCurrentIndex(0)

        self.show_combo.blockSignals(False)

        # Load the current show
        self._load_show(self.show_combo.currentText())

        # Update pause show widgets
        self._update_pause_show_widgets()

    def _on_show_changed(self, show_name):
        """Handle show selection change."""
        self._load_show(show_name)

        # Update trigger widgets for the new show
        self._update_trigger_widgets()

        # Notify parent to sync with other tabs
        if self.parent() and hasattr(self.parent(), 'on_show_selected'):
            self.parent().on_show_selected(show_name, 'structure')

    def _update_trigger_widgets(self):
        """Update trigger device combo and channel spinbox for the current show."""
        self.trigger_device_combo.blockSignals(True)
        self.trigger_channel_spin.blockSignals(True)

        if self.current_show and self.current_show.trigger_device:
            # Find the device in the combo
            idx = self.trigger_device_combo.findText(self.current_show.trigger_device)
            if idx >= 0:
                self.trigger_device_combo.setCurrentIndex(idx)
            else:
                # Device not in list — add it
                self.trigger_device_combo.addItem(self.current_show.trigger_device)
                self.trigger_device_combo.setCurrentText(self.current_show.trigger_device)
            self.trigger_channel_spin.setEnabled(True)
            self.trigger_channel_spin.setValue(max(1, self.current_show.trigger_channel))
        else:
            self.trigger_device_combo.setCurrentIndex(0)  # "No Trigger"
            self.trigger_channel_spin.setEnabled(False)
            self.trigger_channel_spin.setValue(1)

        self.trigger_device_combo.blockSignals(False)
        self.trigger_channel_spin.blockSignals(False)

    def _on_trigger_device_changed(self, device_name):
        """Handle trigger device selection change."""
        if not self.current_show:
            return

        if device_name == "No Trigger" or not device_name:
            self.current_show.trigger_device = ""
            self.current_show.trigger_channel = -1
            self.trigger_channel_spin.setEnabled(False)
            self.trigger_channel_spin.setValue(1)
        else:
            self.current_show.trigger_device = device_name
            self.trigger_channel_spin.setEnabled(True)
            if self.current_show.trigger_channel < 0:
                self.current_show.trigger_channel = 1

            # Auto-create MIDI input device in config if not already present
            self._ensure_midi_device(device_name)

        self._auto_save()

    def _on_trigger_channel_changed(self, channel):
        """Handle trigger channel change."""
        if not self.current_show:
            return
        self.current_show.trigger_channel = channel
        self._auto_save()

    def _ensure_midi_device(self, profile_name):
        """Ensure a MidiInputDevice exists in config for the given profile name."""
        from utils.midi_utils import ensure_midi_device_in_config
        ensure_midi_device_in_config(self.config, profile_name, self._midi_profiles)

    def _create_new_show(self):
        """Create a new show with a dialog.

        No shows-directory gate: since v1.0 the config YAML is the single
        source of truth for shows and ``shows_directory`` is only a
        last-used import/export hint. The old gate silently returned when
        that hint was unset (the normal case), so "+ New" did nothing.
        """
        name, ok = QInputDialog.getText(
            self,
            "Create New Show",
            "Enter show name:",
            text="New Show"
        )

        if ok and name:
            # Check if name already exists
            if name in self.config.shows:
                QMessageBox.warning(
                    self,
                    "Name Exists",
                    f"A show named '{name}' already exists. Please choose a different name.",
                    QMessageBox.StandardButton.Ok
                )
                return

            # Create new show with default part
            new_show = Show(
                name=name,
                parts=[
                    ShowPart(
                        name="Intro",
                        color="#4CAF50",
                        signature="4/4",
                        bpm=120.0,
                        num_bars=8,
                        transition="instant"
                    )
                ],
                effects=[],
                timeline_data=TimelineData()
            )

            # Add to config
            self.config.shows[name] = new_show

            # Update combo and select new show
            self.show_combo.blockSignals(True)
            self.show_combo.addItem(name)
            self.show_combo.setCurrentText(name)
            self.show_combo.blockSignals(False)

            # Load the new show
            self._load_show(name)

            # Auto-save the new show to CSV
            self._save_to_csv()

            # Notify parent to sync with other tabs
            if self.parent() and hasattr(self.parent(), 'on_show_selected'):
                self.parent().on_show_selected(name, 'structure')

    def _rename_show(self):
        """Rename the current show."""
        if not self.current_show_name:
            QMessageBox.warning(self, "No Show Selected", "Please select a show to rename.")
            return

        old_name = self.current_show_name

        # Get new name from user
        new_name, ok = QInputDialog.getText(
            self,
            "Rename Show",
            "Enter new show name:",
            text=old_name
        )

        if ok and new_name and new_name != old_name:
            # Check if new name already exists
            if new_name in self.config.shows:
                QMessageBox.warning(
                    self,
                    "Name Exists",
                    f"A show named '{new_name}' already exists. Please choose a different name."
                )
                return

            # Rename in config
            self.config.shows[new_name] = self.config.shows.pop(old_name)
            self.config.shows[new_name].name = new_name

            # Rename CSV file
            try:
                project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
                shows_dir = os.path.join(project_root, "shows")
                old_csv = os.path.join(shows_dir, f"{old_name}.csv")
                new_csv = os.path.join(shows_dir, f"{new_name}.csv")

                if os.path.exists(old_csv):
                    os.rename(old_csv, new_csv)
            except Exception as e:
                print(f"Failed to rename CSV file: {e}")

            # Update current show name
            self.current_show_name = new_name

            # Update dropdown
            self.show_combo.blockSignals(True)
            self.show_combo.clear()
            self.show_combo.addItems(sorted(self.config.shows.keys()))
            self.show_combo.setCurrentText(new_name)
            self.show_combo.blockSignals(False)

            # Notify parent to sync
            if self.parent() and hasattr(self.parent(), 'on_show_selected'):
                self.parent().on_show_selected(new_name, 'structure')

            QMessageBox.information(self, "Success", f"Show renamed from '{old_name}' to '{new_name}'.")

    def _set_show_directory(self):
        """Manually set/change the shows directory."""
        # Ask user to choose directory
        current_dir = self.config.shows_directory if self.config.shows_directory else os.path.expanduser("~")

        custom_dir = QFileDialog.getExistingDirectory(
            self,
            "Select Shows Directory",
            current_dir,
            QFileDialog.Option.ShowDirsOnly
        )

        if custom_dir:
            self.config.shows_directory = custom_dir
            # shows_directory is just a hint now; we no longer auto-create
            # an audiofiles/ subdir here or auto-scan for CSVs. Audio files
            # live next to the config (config_dir/audiofiles/), and CSVs
            # are imported explicitly via File -> Import Show Structure.
            QMessageBox.information(
                self,
                "Directory Set",
                f"Shows directory hint set to:\n{custom_dir}\n\n"
                "Used as the default location for File -> Import / Export "
                "Show Structure dialogs."
            )

    def _ensure_shows_directory(self) -> bool:
        """Silent check: returns True iff shows_directory hint is set and exists.

        Used to be a prompt-and-auto-create-on-first-use path that also
        triggered CSV scanning. v1.0 demoted ``shows_directory`` to a hint
        (last-used import/export location) so this function no longer
        prompts or creates. Callers that need a directory for an explicit
        user action (Set Shows Directory button, Export Show Structure
        dialog) use a QFileDialog at the call site instead.
        """
        return bool(
            self.config.shows_directory
            and os.path.exists(self.config.shows_directory)
        )

    def _delete_show(self):
        """Delete the current show (from config and disk)."""
        if not self.current_show_name:
            QMessageBox.warning(self, "No Show Selected", "Please select a show to delete.")
            return

        reply = QMessageBox.question(
            self,
            "Confirm Delete",
            f"Are you sure you want to delete show '{self.current_show_name}'?\n\n"
            f"This will delete:\n"
            f"- The show configuration\n"
            f"- The CSV file\n"
            f"- Associated audio files\n\n"
            f"This action cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        show = self.config.shows.get(self.current_show_name)

        # Delete bundled audio file if it exists. CSVs on disk are now
        # user-managed (exported via File -> Export Show Structure), so
        # delete-show only touches the in-memory config and the audio bundle.
        if show and show.timeline_data and show.timeline_data.audio_file_path:
            audio_filename = os.path.basename(show.timeline_data.audio_file_path)
            bundle_dir = self.config.audio_bundle_dir()
            if bundle_dir:
                audio_path = os.path.join(bundle_dir, audio_filename)
                if os.path.exists(audio_path):
                    try:
                        os.remove(audio_path)
                    except Exception as e:
                        print(f"Failed to delete audio file: {e}")

        # Delete from config
        del self.config.shows[self.current_show_name]

        # Clear UI
        self.current_show_name = ""
        self.current_show = None

        # Refresh dropdown
        self.show_combo.blockSignals(True)
        self.show_combo.clear()
        self.show_combo.addItems(sorted(self.config.shows.keys()))
        if self.config.shows:
            self.show_combo.setCurrentIndex(0)
        self.show_combo.blockSignals(False)

        # Load first show if available
        if self.show_combo.currentText():
            self._load_show(self.show_combo.currentText())
        else:
            self._clear_timeline()

        QMessageBox.information(self, "Success", "Show deleted successfully.")

    def _auto_load_shows(self):
        """Automatically load all shows from the configured directory."""
        if not self.config.shows_directory or not os.path.exists(self.config.shows_directory):
            print(f"DEBUG: Cannot auto-load - no valid directory (directory={self.config.shows_directory})")
            return

        print(f"DEBUG: Auto-loading shows from {self.config.shows_directory}")
        try:
            self._import_all_shows_from_csv()
            print(f"DEBUG: Import completed, shows: {list(self.config.shows.keys())}")
        except Exception as e:
            print(f"Failed to auto-load shows: {e}")
            import traceback
            traceback.print_exc()

    def _clear_timeline(self):
        """Clear the timeline and the parts strip."""
        self._selected_index = -1
        self._rebuild_parts_strip()
        self.audio_lane.set_song_structure(None)
        self.master_timeline.timeline_widget.set_song_structure(None)

    def _load_show(self, show_name):
        """Load a show for editing."""
        if not show_name or show_name not in self.config.shows:
            self.current_show_name = ""
            self.current_show = None
            self._selected_index = -1
            self._rebuild_parts_strip()
            self.audio_lane.set_song_structure(None)
            self.master_timeline.timeline_widget.set_song_structure(None)
            self._update_audio_readout()
            return

        self.current_show_name = show_name
        self.current_show = self.config.shows[show_name]

        # Rebuild the parts strip; select the first part so the
        # inspector opens on something useful.
        self._selected_index = 0 if self.current_show.parts else -1
        self._playing_index = -1
        self._rebuild_parts_strip()

        # Set song structure on both audio lane and master timeline
        if self.song_structure:
            self.audio_lane.set_song_structure(self.song_structure)
            self.master_timeline.timeline_widget.set_song_structure(self.song_structure)

        # Load audio if available, or clear if not
        if self.current_show.timeline_data and self.current_show.timeline_data.audio_file_path:
            audio_filename = self.current_show.timeline_data.audio_file_path

            if os.path.isabs(audio_filename):
                # Legacy: absolute path written before audio_bundle_dir landed.
                if os.path.exists(audio_filename):
                    self.audio_lane.load_audio_file(audio_filename)
                else:
                    print(f"Audio file not found: {audio_filename}")
                    self.audio_lane.clear_audio()
            else:
                # New format: filename only. Resolve via Configuration's
                # audio_bundle_dir (tries <config_dir>/audiofiles/ first,
                # falls back to <shows_directory>/audiofiles/ for legacy).
                bundle_dir = self.config.audio_bundle_dir()
                audio_path = (
                    os.path.join(bundle_dir, audio_filename) if bundle_dir else None
                )
                if audio_path and os.path.exists(audio_path):
                    self.audio_lane.load_audio_file(audio_path)
                else:
                    print(f"Audio file not found for '{audio_filename}' "
                          f"(bundle dir: {bundle_dir})")
                    self.audio_lane.clear_audio()
        else:
            # No audio for this show, clear it
            self.audio_lane.clear_audio()

        self._update_audio_readout()

    def _load_all_shows(self):
        """Load all shows from CSV files in the shows directory."""
        try:
            # Import all shows
            self._import_all_shows_from_csv()

            # Update dropdown
            self.update_from_config()

            # Show success message
            show_count = len(self.config.shows)
            QMessageBox.information(
                self,
                "Success",
                f"Loaded {show_count} show(s) from CSV files."
            )

            # Load first show if available
            if self.show_combo.count() > 0:
                self._load_show(self.show_combo.currentText())

        except Exception as e:
            QMessageBox.critical(
                self,
                "Error",
                f"Failed to load shows:\n{str(e)}"
            )

    def _delete_part(self):
        """Delete the selected part."""
        if self._selected_part() is None:
            QMessageBox.warning(self, "No Selection", "Please select a part to delete.")
            return

        reply = QMessageBox.question(
            self,
            "Confirm Delete",
            "Are you sure you want to delete this part?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            # Delete from show parts
            del self.current_show.parts[self._selected_index]

            # Rebuild the strip (clamps the selection) and update timelines
            self._rebuild_parts_strip()
            self._update_timelines()

            self._auto_save()

    def _show_context_menu(self, position):
        """Show context menu for the parts strip right-click."""
        menu = QMenu(self)

        # Add Part action
        add_action = QAction("Add Part", self)
        add_action.triggered.connect(self._add_new_part)
        menu.addAction(add_action)

        # Delete Part action (only if a part is selected)
        if self._selected_part() is not None:
            delete_action = QAction("Delete Selected Part", self)
            delete_action.triggered.connect(self._delete_part)
            menu.addAction(delete_action)

        # Show menu at cursor position
        menu.exec(self.parts_host.mapToGlobal(position))

    def _import_from_csv(self):
        """Import show structure from CSV file."""
        if not self.current_show_name:
            QMessageBox.warning(self, "No Show Selected", "Please select a show first.")
            return

        # Use the existing import functionality
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        csv_path = os.path.join(project_root, "shows", f"{self.current_show_name}.csv")

        if not os.path.exists(csv_path):
            QMessageBox.warning(
                self,
                "CSV Not Found",
                f"No CSV file found for show '{self.current_show_name}' at:\n{csv_path}"
            )
            return

        try:
            # Clear existing parts
            self.current_show.parts.clear()

            # Read CSV
            with open(csv_path, 'r') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    part = ShowPart(
                        name=row['showpart'],
                        color=row['color'],
                        signature=row['signature'],
                        bpm=float(row['bpm']),
                        num_bars=int(row['num_bars']),
                        transition=row['transition']
                    )
                    self.current_show.parts.append(part)

            # Reload display
            self._selected_index = 0 if self.current_show.parts else -1
            self._rebuild_parts_strip()

            # Update timelines
            self._update_timelines()

            QMessageBox.information(self, "Success", f"Imported {len(self.current_show.parts)} parts from CSV.")

        except Exception as e:
            QMessageBox.critical(self, "Import Error", f"Failed to import CSV:\n{str(e)}")

    def _auto_save(self):
        """Hook called after in-memory edits. No-op today.

        Edits already mutate self.config.shows in place, so nothing needs to
        happen here for the YAML round-trip. The user persists via
        ``File -> Save Configuration``. Previously this also wrote a CSV per
        show on every edit, which created the parallel-filesystem problem
        v1.0 set out to fix (config.yaml + shows/*.csv kept independently).
        The autosave-to-yaml feature in v1.2 will land in this slot.
        """
        return

    def _save_to_csv(self):
        """Save current show structure to CSV file."""
        if not self.current_show or not self.current_show.parts:
            return

        # Ensure shows directory is configured
        if not self._ensure_shows_directory():
            return

        self._save_show_to_csv(self.current_show_name, self.current_show)

    def _import_all_shows_from_csv(self):
        """Import all show structures from CSV files in the shows directory."""
        # Use configured shows directory
        if not self.config.shows_directory:
            return

        shows_dir = self.config.shows_directory

        # Check if shows directory exists
        if not os.path.exists(shows_dir):
            print(f"Shows directory not found: {shows_dir}")
            return

        # Scan for all show structure CSV files
        csv_files = [f for f in os.listdir(shows_dir) if f.endswith('.csv')]

        if not csv_files:
            print(f"No CSV files found in {shows_dir}")
            return

        imported_count = 0

        for file in csv_files:
            try:
                show_name = os.path.splitext(file)[0]  # Remove .csv extension
                structure_file = os.path.join(shows_dir, file)

                # Check if show already exists in configuration
                if show_name in self.config.shows:
                    show = self.config.shows[show_name]
                    # Clear existing parts to reload from CSV
                    show.parts.clear()
                else:
                    # Create new Show object with timeline data
                    show = Show(
                        name=show_name,
                        parts=[],
                        effects=[],
                        timeline_data=TimelineData()
                    )
                    self.config.shows[show_name] = show

                # Read CSV and create show parts
                with open(structure_file, 'r') as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        # Create ShowPart from CSV row
                        show_part = ShowPart(
                            name=row['showpart'],
                            color=row['color'],
                            signature=row['signature'],
                            bpm=float(row['bpm']),
                            num_bars=int(row['num_bars']),
                            transition=row['transition']
                        )
                        # Add part to show
                        show.parts.append(show_part)

                imported_count += 1
                print(f"Imported show: {show_name}")

            except Exception as e:
                print(f"Failed to import {file}: {e}")

        print(f"Successfully imported {imported_count} show(s) from {shows_dir}")

    def _on_audio_file_loaded(self, file_path: str):
        """Handle audio file loaded - copy to <config_dir>/audiofiles/."""
        if not file_path or not self.current_show:
            return

        # Resolve the bundle dir next to the config (creates it if needed).
        # If the config has never been saved (no _loaded_from), we can't
        # bundle - warn and keep the absolute path so playback still works.
        audiofiles_dir = self.config.audio_bundle_dir(create=True)
        if not audiofiles_dir:
            QMessageBox.warning(
                self,
                "Audio Not Bundled",
                "The config has not been saved yet, so the audio file path "
                "will be stored as an absolute path.\n\n"
                "Save the config to bundle audio under "
                "<config_dir>/audiofiles/ on the next audio load."
            )
            if self.current_show.timeline_data is None:
                self.current_show.timeline_data = TimelineData()
            self.current_show.timeline_data.audio_file_path = os.path.abspath(file_path)
            self._auto_save()
            return

        try:
            filename = os.path.basename(file_path)
            dest_path = os.path.join(audiofiles_dir, filename)

            # Copy file if it's not already in audiofiles directory
            if os.path.abspath(file_path) != os.path.abspath(dest_path):
                shutil.copy2(file_path, dest_path)
                print(f"Copied audio file to: {dest_path}")

            # Store just the filename in timeline_data
            if self.current_show.timeline_data is None:
                self.current_show.timeline_data = TimelineData()
            self.current_show.timeline_data.audio_file_path = filename

            self._auto_save()

        except Exception as e:
            QMessageBox.warning(
                self,
                "Audio Copy Error",
                f"Failed to copy audio file to bundle directory:\n{str(e)}"
            )

        # Update time display
        if self.song_structure:
            total_duration = self.song_structure.get_total_duration()
            self.total_time_label.setText(f"/ {self._format_time(total_duration)}")

        self._update_audio_readout()

    def _toggle_playback(self):
        """Toggle play/pause."""
        if self.is_playing:
            self._pause_playback()
        else:
            self._start_playback()

    def _start_playback(self):
        """Start playback."""
        if not self.song_structure:
            return

        self.is_playing = True
        self.play_btn.setText("Pause")

        # Initialize audio if available
        try:
            from audio.audio_file import AudioFile
            from audio.audio_engine import AudioEngine
            from audio.audio_mixer import AudioMixer
            from audio.playback_synchronizer import PlaybackSynchronizer
            from audio.device_manager import DeviceManager

            if self.audio_lane.get_audio_file():
                self._init_audio_engine()
                if self.playback_sync:
                    self.playback_sync.on_play_requested(self.playhead_position)
        except ImportError:
            pass  # Audio not available

        self.playback_timer.start()

    def _pause_playback(self):
        """Pause playback."""
        self.is_playing = False
        self.play_btn.setText("Play")
        self.playback_timer.stop()

        if self.playback_sync:
            self.playback_sync.on_pause_requested()

    def _stop_playback(self):
        """Stop playback and reset position."""
        self.is_playing = False
        self.play_btn.setText("Play")
        self.playback_timer.stop()

        if self.playback_sync:
            self.playback_sync.on_stop_requested()

        self.playhead_position = 0.0
        self.time_label.setText("00:00.00")
        self.position_slider.setValue(0)

    def _update_playback(self):
        """Called by timer during playback to update position."""
        if not self.is_playing or not self.song_structure:
            return

        # Get position from audio if available, otherwise use timer
        if self.playback_sync:
            position = self.playback_sync.get_accurate_position()
        else:
            # Fallback: increment by timer interval
            position = self.playhead_position + 0.016  # 16ms

        total = self.song_structure.get_total_duration()
        if position >= total:
            self._stop_playback()
            return

        self.playhead_position = position
        self.time_label.setText(self._format_time(position))

        # Update position slider
        if total > 0:
            slider_pos = int((position / total) * 1000)
            self.position_slider.blockSignals(True)
            self.position_slider.setValue(slider_pos)
            self.position_slider.blockSignals(False)

        # Update playhead on all timelines
        self.master_timeline.set_playhead_position(position)
        self.audio_lane.set_playhead_position(position)

        # Update the playing-part card highlight
        self._update_playing_highlight()

    def _on_position_slider_pressed(self):
        """Handle position slider press - pause updates during drag."""
        self._slider_dragging = True

    def _on_position_slider_released(self):
        """Handle position slider release - seek to position."""
        self._slider_dragging = False
        if self.song_structure:
            total = self.song_structure.get_total_duration()
            position = (self.position_slider.value() / 1000.0) * total
            self.playhead_position = position
            if self.playback_sync:
                self.playback_sync.on_seek_requested(position)

    def _on_position_slider_changed(self, value: int):
        """Handle position slider value change during drag."""
        if hasattr(self, '_slider_dragging') and self._slider_dragging:
            if self.song_structure:
                total = self.song_structure.get_total_duration()
                position = (value / 1000.0) * total
                self.time_label.setText(self._format_time(position))

    def _format_time(self, seconds: float) -> str:
        """Format time as MM:SS.ss"""
        minutes = int(seconds // 60)
        secs = seconds % 60
        return f"{minutes:02d}:{secs:05.2f}"

    def _init_audio_engine(self):
        """Initialize audio engine on first use."""
        try:
            from audio.audio_file import AudioFile
            from audio.audio_engine import AudioEngine
            from audio.audio_mixer import AudioMixer
            from audio.playback_synchronizer import PlaybackSynchronizer
            from audio.device_manager import DeviceManager

            if self.audio_engine is None:
                self.device_manager = DeviceManager()
                self.audio_engine = AudioEngine()
                self.audio_mixer = AudioMixer()

                # Apply stored audio settings if available from parent
                device_index = None
                if hasattr(self.parent(), 'audio_settings') and self.parent().audio_settings:
                    device_index = self.parent().audio_settings.get('device_index')
                    sample_rate = self.parent().audio_settings.get('sample_rate', 44100)
                    buffer_size = self.parent().audio_settings.get('buffer_size', 1024)
                    self.audio_engine.sample_rate = sample_rate
                    self.audio_engine.buffer_size = buffer_size

                # Initialize audio engine with device
                if not self.audio_engine.initialize(device_index=device_index):
                    raise Exception("Audio device initialization failed")

                self.playback_sync = PlaybackSynchronizer(
                    self.audio_engine, self.audio_mixer
                )

                # Load audio file into mixer
                audio_file = self.audio_lane.get_audio_file()
                if audio_file:
                    self.audio_mixer.add_lane("audio", audio_file, 1.0)

                # Connect volume/mute if available
                if hasattr(self.audio_lane, 'volume_slider'):
                    self.audio_lane.volume_slider.valueChanged.connect(
                        lambda v: self.audio_mixer.update_lane_volume("audio", v / 100.0) if self.audio_mixer else None
                    )
                if hasattr(self.audio_lane, 'mute_button'):
                    self.audio_lane.mute_button.toggled.connect(
                        lambda m: self.audio_mixer.set_mute_state("audio", m) if self.audio_mixer else None
                    )

        except Exception as e:
            print(f"Failed to initialize audio engine: {e}")
            self.audio_engine = None
            self.playback_sync = None

    def save_to_config(self):
        """Flush UI state into the in-memory Configuration. No-op today.

        Other tabs use this hook to copy widget state back to the config
        object before File -> Save / Export. The structure tab's edits
        already mutate self.config.shows in place as the user edits, so
        nothing extra is needed here. Previously this method wrote a CSV
        per show to disk - that behaviour moved to the explicit
        File -> Export Show Structure action in v1.0.
        """
        return

    def _save_show_to_csv(self, show_name: str, show: Show):
        """Save a specific show structure to CSV file.

        Args:
            show_name: Name of the show
            show: Show object containing parts
        """
        if not show.parts:
            return

        csv_path = os.path.join(self.config.shows_directory, f"{show_name}.csv")

        try:
            with open(csv_path, 'w', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=['showpart', 'signature', 'bpm', 'num_bars', 'transition', 'color'])
                writer.writeheader()

                for part in show.parts:
                    writer.writerow({
                        'showpart': part.name,
                        'signature': part.signature,
                        'bpm': part.bpm,
                        'num_bars': part.num_bars,
                        'transition': part.transition,
                        'color': part.color
                    })
        except Exception as e:
            print(f"Failed to save CSV for {show_name}: {e}")

    def on_tab_activated(self):
        """Called when tab becomes visible.

        v1.0 made config.yaml the single source of truth, so this hook just
        refreshes the UI from the in-memory config. Previously it prompted
        for a shows_directory on first activation and silently scanned that
        directory for CSV files; both behaviours moved out (shows_directory
        is now a hint set via the "Set Shows Directory" button, and CSV
        import is explicit via File -> Import Show Structure).
        """
        if self._is_activating:
            return
        try:
            self._is_activating = True
            self.update_from_config()
        finally:
            self._is_activating = False

    def on_tab_deactivated(self):
        """Called when leaving tab."""
        self._pause_playback()  # Pause when leaving tab

    def cleanup(self):
        """Clean up audio resources."""
        self._stop_playback()

        if self.audio_engine:
            try:
                self.audio_engine.shutdown()
            except Exception:
                pass
            self.audio_engine = None
            self.audio_mixer = None
            self.playback_sync = None
