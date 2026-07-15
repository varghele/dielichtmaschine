# gui/dialogs/autogen_dialog.py
# Configuration dialog for automatic show generation.
#
# Rebuilt against docs/design/screens/
# 10-autogen-dialog.html: a 44px display-caps header, a 420px left
# column (AUDIO / STRUCTURE / SONG KEY / COLOUR PALETTE, mono captions
# over raised readout tiles, then the accent GENERATE call to action and
# a hint line) and a right pane that carries the generation parameters
# above the "GENERATION INSPECTOR . LAST RUN" table.
#
# Two controls of the reference board have no backing in autogen/ and
# are deliberately absent (see tests/unit/test_autogen_dialog.py):
# INTENSITY CEILING (no such field on AutogenConfig, and the generator
# never clamps intensity) and the "Overwrite existing blocks" toggle
# (replace-vs-append is asked after generation by the calling tab, not
# configured here). The reference's "SEED 4211 . RERUN" readout is gone
# for the same reason: generation draws from the unseeded global RNG.
#
# Public contract kept intact: AutogenDialog(parent) exec()s modally and
# exposes result_config / result_key_signature / result_palette after
# accept(); AutogenWorker keeps its constructor and its
# finished/error/progress signals.

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QWidget,
    QDoubleSpinBox, QSpinBox, QLabel, QComboBox, QPushButton, QCheckBox,
    QColorDialog, QButtonGroup, QSizePolicy,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor, QFont

from autogen.matcher import AutogenConfig
from autogen.color_generator import SongPalette, get_preset_names, get_preset_palette
from gui.typography import DisplayLabel, MicroLabel, mono_font
from gui.widgets.chip import Chip

#: Width of the reference board's left configuration column.
LEFT_COLUMN_WIDTH = 420

#: Inspector table column widths (reference grid: 120 / 110 / 1fr / 170).
INSPECTOR_SECTION_WIDTH = 120
INSPECTOR_ENVELOPE_WIDTH = 110
INSPECTOR_WHY_WIDTH = 200

#: Palette source modes (segmented chip row of the COLOUR PALETTE block).
MODE_AUDIO = "audio"
MODE_PRESET = "preset"
MODE_CUSTOM = "custom"

AUTO_KEY = "(Auto-detect)"

KEY_SIGNATURES = [
    AUTO_KEY, "C major", "C minor",
    "D major", "D minor", "E major", "E minor",
    "F major", "F minor", "G major", "G minor",
    "A major", "A minor", "B major", "B minor",
    "Db major", "Eb major", "Eb minor",
    "Gb major", "Ab major", "Ab minor", "Bb major", "Bb minor",
]


def _active_tokens() -> dict:
    """Token dict of the theme currently applied to the app.

    Same stylesheet sniff as gui/tabs/structure_tab.py: the light
    theme's window color only ever appears in the light stylesheet.
    """
    from PyQt6.QtWidgets import QApplication
    from gui.theme_tokens import THEMES

    app = QApplication.instance()
    qss = app.styleSheet() if app is not None else ""
    light = THEMES.get("light")
    if light is not None and light["window"] in qss:
        return light
    return THEMES["dark"]


class AutogenWorker(QThread):
    """Background worker for show generation."""
    finished = pyqtSignal(list, object)  # (lanes, GenerationReport)
    error = pyqtSignal(str)
    progress = pyqtSignal(str)

    def __init__(self, audio_path, song_structure, config, autogen_config,
                 key_signature, song_palette):
        super().__init__()
        self.audio_path = audio_path
        self.song_structure = song_structure
        self.config = config
        self.autogen_config = autogen_config
        self.key_signature = key_signature
        self.song_palette = song_palette

    def run(self):
        try:
            from autogen.generator import generate_show
            self.progress.emit("Analyzing audio...")
            lanes, report = generate_show(
                self.audio_path,
                self.song_structure,
                self.config,
                self.autogen_config,
                self.key_signature,
                self.song_palette,
            )
            self.progress.emit("Done!")
            self.finished.emit(lanes, report)
        except Exception as e:
            self.error.emit(str(e))


# ──────────────────────────────────────────────
# Report -> inspector row text (real report fields only)
# ──────────────────────────────────────────────

def _active_groups(section):
    """The section's group reports that actually got light (weight > 0)."""
    return [(name, gr) for name, gr in section.group_reports.items()
            if gr.weight > 0]


def section_envelope(section) -> str:
    """The reference's ENVELOPE column: the dominant groove envelope
    category across the section's active groups (rudiments/rudiment.py
    EnvelopeCategory values), or STATIC when nothing plays.

    Ties go to the first group in report order, so the readout does not
    depend on set iteration (i.e. on PYTHONHASHSEED).
    """
    counts = {}
    order = {}
    for index, (_, gr) in enumerate(_active_groups(section)):
        if not gr.groove_category:
            continue
        counts[gr.groove_category] = counts.get(gr.groove_category, 0) + 1
        order.setdefault(gr.groove_category, index)
    if not counts:
        return "STATIC"
    dominant = max(counts, key=lambda c: (counts[c], -order[c]))
    return str(dominant).upper()


def section_picks(section, max_groups: int = 3) -> str:
    """The reference's PICKS (PER GROUP) column: 'GROUP rudiment' per
    active group, truncated with a count when there are more."""
    active = _active_groups(section)
    if not active:
        return "no groups active"
    shown = active[:max_groups]
    text = " · ".join(f"{name.upper()} {gr.groove_rudiment}"
                      for name, gr in shown)
    extra = len(active) - len(shown)
    if extra:
        text += f" · +{extra} more"
    return text


def section_why(section) -> str:
    """The reference's WHY column, built only from recorded audio
    features (autogen/report.py SectionReport)."""
    vocals = "vocals" if section.vocal_presence >= 0.5 else "no vocals"
    return (f"energy {section.relative_energy:.2f}, "
            f"flux {section.spectral_flux:.2f}, {vocals}")


def peak_section_index(report) -> int:
    """Index of the loudest section (highest relative energy) - the row
    the reference board highlights. -1 when the report has no sections."""
    if report is None or not getattr(report, "sections", None):
        return -1
    energies = [s.relative_energy for s in report.sections]
    return energies.index(max(energies))


# ──────────────────────────────────────────────
# Small building blocks
# ──────────────────────────────────────────────

def _caption(text: str) -> MicroLabel:
    """The board's 10px tracked mono block caption."""
    label = MicroLabel(text, point_size=7, tracking_em=0.12)
    label.setProperty("role", "stat-caption")
    return label


class _ReadoutTile(QWidget):
    """Raised bordered readout strip (reference: the AUDIO and STRUCTURE
    rows). Chrome is the theme's stat-tile role."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setProperty("role", "stat-tile")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.row = QHBoxLayout(self)
        self.row.setContentsMargins(12, 10, 12, 10)
        self.row.setSpacing(8)


class _ColorButton(QPushButton):
    """Square swatch that opens a color picker on click.

    The fill is a *data* color (the user's palette), so it stays
    widget-local; the theme owns no swatch role.
    """

    def __init__(self, initial_color=(128, 128, 128), parent=None):
        super().__init__(parent)
        self.color = initial_color
        self.setFixedSize(30, 30)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._update_style()
        self.clicked.connect(self._pick_color)

    def _update_style(self):
        r, g, b = self.color
        border = _active_tokens()["border"]
        self.setStyleSheet(
            f"background-color: rgb({r},{g},{b}); "
            f"border: 1px solid {border}; border-radius: 0px;"
        )

    def _pick_color(self):
        r, g, b = self.color
        color = QColorDialog.getColor(QColor(r, g, b), self, "Pick Color")
        if color.isValid():
            self.color = (color.red(), color.green(), color.blue())
            self._update_style()


class _ElidedLabel(QLabel):
    """QLabel that elides its text instead of clipping it when the layout
    hands it less width than the string needs (the PICKS column of the
    inspector grows with the number of active groups).

    The elision happens on ``resizeEvent`` and is written back through
    ``QLabel.setText``, so the label keeps being painted by the QSS
    engine (a custom ``paintEvent`` would have to hardcode the text
    color - docs/qt-gotchas.md #5).
    """

    def __init__(self, text: str = "", parent=None):
        super().__init__(parent)
        self._full_text = ""
        self.setMinimumWidth(0)
        self.setText(text)

    def setText(self, text: str) -> None:  # noqa: N802 (Qt API)
        self._full_text = text
        self.setToolTip(text)
        self._apply_elide()

    def full_text(self) -> str:
        return self._full_text

    def _apply_elide(self) -> None:
        from PyQt6.QtGui import QFontMetrics
        width = self.width()
        text = self._full_text
        if width > 0:
            text = QFontMetrics(self.font()).elidedText(
                self._full_text, Qt.TextElideMode.ElideRight, width)
        QLabel.setText(self, text)

    def resizeEvent(self, event):  # noqa: N802 (Qt API)
        super().resizeEvent(event)
        self._apply_elide()


class _ParamField(QWidget):
    """Mono caption over a spin box (the right pane's parameter grid)."""

    def __init__(self, caption: str, editor: QWidget, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.caption_label = _caption(caption)
        layout.addWidget(self.caption_label)
        layout.addWidget(editor)


class _InspectorRow(QWidget):
    """One section row of the LAST RUN table: SECTION / ENVELOPE /
    PICKS (PER GROUP) / WHY.

    Chrome reuses the theme's ``#GroupRow`` role: a bottom hairline per
    row, raised background when ``selected`` - which is exactly how the
    reference paints its highlighted (peak-energy) row.
    """

    def __init__(self, section, highlight: bool = False, parent=None):
        super().__init__(parent)
        self.setObjectName("GroupRow")
        self.setProperty("selected", "true" if highlight else "false")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        row = QHBoxLayout(self)
        row.setContentsMargins(14, 10, 14, 10)
        row.setSpacing(10)

        self.name_label = DisplayLabel(section.name or "SECTION",
                                       point_size=11)
        self.name_label.setFixedWidth(INSPECTOR_SECTION_WIDTH)
        row.addWidget(self.name_label)

        self.envelope_label = QLabel(section_envelope(section))
        self.envelope_label.setFont(mono_font(8))
        self.envelope_label.setProperty("role", "micro")
        self.envelope_label.setFixedWidth(INSPECTOR_ENVELOPE_WIDTH)
        row.addWidget(self.envelope_label)

        self.picks_label = _ElidedLabel(section_picks(section))
        self.picks_label.setFont(mono_font(8))
        self.picks_label.setSizePolicy(QSizePolicy.Policy.Expanding,
                                       QSizePolicy.Policy.Preferred)
        row.addWidget(self.picks_label, 1)

        if highlight:
            self.peak_chip = Chip("peak", variant="accent", point_size=7)
            row.addWidget(self.peak_chip)

        self.why_label = QLabel(section_why(section))
        self.why_label.setProperty("role", "stat-caption")
        self.why_label.setWordWrap(True)
        self.why_label.setFixedWidth(INSPECTOR_WHY_WIDTH)
        row.addWidget(self.why_label)


class AutogenDialog(QDialog):
    """Configuration dialog for automatic show generation.

    ``audio_path`` / ``show`` / ``report`` default to whatever the
    calling tab already holds (both callers pass themselves as parent);
    they exist so tests and future callers can supply the context
    explicitly. Nothing is displayed that the caller does not have.
    """

    def __init__(self, parent=None, *, audio_path=None, show=None,
                 report=None):
        super().__init__(parent)
        self.setWindowTitle("Autogenerate Song")
        self.setMinimumSize(1180, 680)

        self._audio_path = audio_path if audio_path is not None \
            else self._parent_audio_path(parent)
        self._show = show if show is not None else self._parent_show(parent)
        self._report = report if report is not None \
            else self._parent_report(parent)

        self.result_config = None
        self.result_key_signature = None
        self.result_palette = None
        self._setup_ui()
        self._set_palette_mode(MODE_AUDIO)

    # -- caller context (read-only, never mutates the parent) ----------

    @staticmethod
    def _parent_audio_path(parent):
        try:
            return parent.audio_lane.get_audio_file_path() or None
        except Exception:
            return None

    @staticmethod
    def _parent_show(parent):
        try:
            show = getattr(parent, "current_show", None)
            if show is not None:
                return show
            return parent.config.songs.get(parent.current_song_name)
        except Exception:
            return None

    @staticmethod
    def _parent_report(parent):
        for attr in ("_generation_report", "_autogen_report"):
            report = getattr(parent, attr, None)
            if report is not None:
                return report
        return None

    # -- construction --------------------------------------------------

    def _setup_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        outer.addWidget(self._build_header())

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        body.addWidget(self._build_left_column())
        body.addWidget(self._build_right_pane(), 1)
        outer.addLayout(body, 1)

    def _build_header(self) -> QWidget:
        header = QWidget()
        header.setObjectName("AutogenHeader")
        # section-caption gives the reference's hairline under the bar.
        header.setProperty("role", "section-caption")
        header.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        header.setFixedHeight(44)
        row = QHBoxLayout(header)
        row.setContentsMargins(18, 0, 18, 0)

        title = "Autogenerate song"
        if self._show is not None and getattr(self._show, "name", ""):
            title = f"Autogenerate song · {self._show.name}"
        self.title_label = DisplayLabel(title, point_size=12,
                                        weight=QFont.Weight.Bold,
                                        tracking_em=0.08)
        row.addWidget(self.title_label)
        row.addStretch()
        return header

    # -- left column ---------------------------------------------------

    def _build_left_column(self) -> QWidget:
        column = QWidget()
        column.setObjectName("AutogenConfigColumn")
        # The inspector role paints the panel surface + the 1px divider
        # the reference draws between the two columns.
        column.setProperty("role", "inspector")
        column.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        column.setFixedWidth(LEFT_COLUMN_WIDTH)
        layout = QVBoxLayout(column)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        layout.addWidget(_caption("Audio"))
        layout.addWidget(self._build_audio_tile())

        layout.addWidget(_caption("Structure"))
        layout.addWidget(self._build_structure_tile())

        layout.addWidget(_caption("Song key"))
        self.key_combo = QComboBox()
        self.key_combo.addItems(KEY_SIGNATURES)
        layout.addWidget(self.key_combo)

        layout.addWidget(_caption("Colour palette"))
        layout.addWidget(self._build_palette_block())

        layout.addStretch(1)

        self.generate_btn = QPushButton("GENERATE")
        self.generate_btn.setObjectName("AutogenGenerateButton")
        self.generate_btn.setProperty("role", "cta-accent")
        self.generate_btn.setFixedHeight(44)
        self.generate_btn.setDefault(True)
        self.generate_btn.clicked.connect(self._on_accepted)
        layout.addWidget(self.generate_btn)

        self.cancel_btn = QPushButton("CANCEL")
        self.cancel_btn.setObjectName("AutogenCancelButton")
        self.cancel_btn.setProperty("role", "cta-outline")
        self.cancel_btn.clicked.connect(self.reject)
        layout.addWidget(self.cancel_btn)

        self.footer_hint = QLabel(
            "Output is ordinary timeline blocks · edit anything afterwards.")
        self.footer_hint.setObjectName("AutogenFooterHint")
        self.footer_hint.setProperty("role", "stat-caption")
        self.footer_hint.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.footer_hint.setWordWrap(True)
        layout.addWidget(self.footer_hint)
        return column

    def _build_audio_tile(self) -> QWidget:
        tile = _ReadoutTile()
        import os

        self.audio_label = QLabel(
            os.path.basename(self._audio_path) if self._audio_path
            else "no audio file loaded")
        self.audio_label.setObjectName("AutogenAudioName")
        self.audio_label.setFont(mono_font(9))
        tile.row.addWidget(self.audio_label)
        tile.row.addStretch()

        if self._audio_path:
            self.audio_chip = Chip("loaded", variant="accent", point_size=7)
        else:
            self.audio_chip = Chip("missing", variant="warning", point_size=7)
        tile.row.addWidget(self.audio_chip)
        return tile

    def _build_structure_tile(self) -> QWidget:
        tile = _ReadoutTile()
        self.structure_label = QLabel(self._structure_summary())
        self.structure_label.setObjectName("AutogenStructureSummary")
        tile.row.addWidget(self.structure_label)
        tile.row.addStretch()
        return tile

    def _structure_summary(self) -> str:
        parts = list(getattr(self._show, "parts", []) or []) \
            if self._show is not None else []
        if not parts:
            return "no song parts defined"
        bars = sum(int(getattr(p, "num_bars", 0) or 0) for p in parts)
        part_word = "part" if len(parts) == 1 else "parts"
        bar_word = "bar" if bars == 1 else "bars"
        return (f"From song · Structure · {len(parts)} {part_word}, "
                f"{bars} {bar_word}")

    def _build_palette_block(self) -> QWidget:
        block = QWidget()
        layout = QVBoxLayout(block)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # Segmented source row (reference: FROM AUDIO / PRESET...).
        segments = QWidget()
        segments.setObjectName("AutogenPaletteModes")
        seg_row = QHBoxLayout(segments)
        seg_row.setContentsMargins(0, 0, 0, 0)
        seg_row.setSpacing(6)
        self.palette_mode_group = QButtonGroup(self)
        self.palette_mode_group.setExclusive(True)
        self._mode_buttons = {}
        for mode, text in ((MODE_AUDIO, "FROM AUDIO"),
                           (MODE_PRESET, "PRESET"),
                           (MODE_CUSTOM, "CUSTOM")):
            btn = QPushButton(text)
            btn.setCheckable(True)
            btn.setProperty("role", "mode-chip")
            btn.setFont(mono_font(8, tracking_em=0.08))
            btn.clicked.connect(lambda _checked, m=mode:
                                self._set_palette_mode(m))
            self.palette_mode_group.addButton(btn)
            seg_row.addWidget(btn, 1)
            self._mode_buttons[mode] = btn
        layout.addWidget(segments)

        self.color_preset_combo = QComboBox()
        self.color_preset_combo.setProperty("role", "accent-field")
        self.color_preset_combo.addItems(get_preset_names())
        self.color_preset_combo.currentTextChanged.connect(
            self._on_color_preset_changed)
        layout.addWidget(self.color_preset_combo)

        # FROM AUDIO has no swatches to show: the palette only exists
        # after the worker analyzed the file. Say so rather than paint
        # colors the generator will not use.
        self.palette_hint = QLabel(
            "Colours are derived from the audio analysis.")
        self.palette_hint.setObjectName("AutogenPaletteHint")
        self.palette_hint.setProperty("role", "hint-box")
        self.palette_hint.setWordWrap(True)
        layout.addWidget(self.palette_hint)

        # Swatch row: primary / secondary / tertiary (+ white).
        swatches = QWidget()
        self._swatch_row = swatches
        swatch_row = QHBoxLayout(swatches)
        swatch_row.setContentsMargins(0, 0, 0, 0)
        swatch_row.setSpacing(5)
        self.color_btn_1 = _ColorButton((255, 0, 0))
        self.color_btn_2 = _ColorButton((0, 0, 255))
        self.color_btn_3 = _ColorButton((128, 128, 128))
        for btn in (self.color_btn_1, self.color_btn_2, self.color_btn_3):
            swatch_row.addWidget(btn)
        self.white_swatch = QLabel()
        self.white_swatch.setFixedSize(30, 30)
        self.white_swatch.setStyleSheet(
            f"background-color: #FFFFFF; "
            f"border: 1px solid {_active_tokens()['border']};")
        swatch_row.addWidget(self.white_swatch)
        swatch_row.addStretch()
        layout.addWidget(swatches)

        # How many palette colors (SongPalette carries up to three).
        count_row = QWidget()
        self._count_row = count_row
        count_layout = QHBoxLayout(count_row)
        count_layout.setContentsMargins(0, 0, 0, 0)
        count_layout.setSpacing(6)
        count_layout.addWidget(_caption("Colours"))
        self.num_colors_group = QButtonGroup(self)
        self.num_colors_group.setExclusive(True)
        self._count_buttons = []
        for count in (1, 2, 3):
            btn = QPushButton(str(count))
            btn.setCheckable(True)
            btn.setProperty("role", "segment")
            btn.setProperty("divider", "true" if count > 1 else "false")
            btn.setFont(mono_font(8))
            btn.clicked.connect(lambda _checked, c=count:
                                self._on_num_colors_changed(c - 1))
            self.num_colors_group.addButton(btn)
            count_layout.addWidget(btn)
            self._count_buttons.append(btn)
        self._count_buttons[1].setChecked(True)  # default: 2 colors
        count_layout.addStretch()
        layout.addWidget(count_row)

        self.include_white_check = QCheckBox("Include white")
        self.include_white_check.setChecked(True)
        self.include_white_check.toggled.connect(
            self.white_swatch.setVisible)
        layout.addWidget(self.include_white_check)
        return block

    # -- right pane ------------------------------------------------------

    def _build_right_pane(self) -> QWidget:
        pane = QWidget()
        pane.setObjectName("AutogenInspectorPane")
        layout = QVBoxLayout(pane)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        layout.addWidget(self._section_caption("Generation parameters"))
        layout.addWidget(self._build_params_grid())
        layout.addSpacing(4)

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        self.inspector_caption = MicroLabel(
            "Generation inspector · last run", point_size=7, tracking_em=0.12)
        self.inspector_caption.setProperty("role", "stat-caption")
        head.addWidget(self.inspector_caption)
        head.addStretch()
        sections = getattr(self._report, "sections", None) or []
        self.inspector_status = MicroLabel(
            f"{len(sections)} sections" if sections else "no run yet",
            point_size=7, tracking_em=0.1)
        head.addWidget(self.inspector_status)
        layout.addLayout(head)

        layout.addWidget(self._build_inspector_table())
        layout.addStretch(1)

        self.inspector_hint = QLabel(
            "Rows describe the previous run in this session. "
            "Generating again replaces them.")
        self.inspector_hint.setObjectName("AutogenInspectorHint")
        self.inspector_hint.setProperty("role", "stat-caption")
        layout.addWidget(self.inspector_hint)
        return pane

    def _section_caption(self, text: str) -> QWidget:
        strip = QWidget()
        strip.setProperty("role", "section-caption")
        strip.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        row = QHBoxLayout(strip)
        row.setContentsMargins(0, 7, 0, 7)
        row.addWidget(_caption(text))
        row.addStretch()
        return strip

    def _build_params_grid(self) -> QWidget:
        grid_host = QWidget()
        grid = QGridLayout(grid_host)
        grid.setContentsMargins(0, 6, 0, 0)
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(12)

        self.phrase_length_spin = QSpinBox()
        self.phrase_length_spin.setRange(2, 8)
        self.phrase_length_spin.setValue(4)
        self.phrase_length_spin.setSuffix(" bars")

        self.groove_fill_spin = self._ratio_spin(0.5, 0.9, 0.75)
        self.groove_fill_spin.setToolTip(
            "Proportion of a phrase spent on groove (the rest is fill)")
        self.fidelity_spin = self._ratio_spin(0.0, 1.0, 0.6)
        self.coherence_spin = self._ratio_spin(0.0, 1.0, 0.4)
        self.tolerance_spin = self._ratio_spin(0.05, 0.5, 0.2)
        self.gobo_threshold_spin = self._ratio_spin(0.0, 1.0, 0.7)
        self.prism_threshold_spin = self._ratio_spin(0.0, 1.0, 0.8)

        fields = [
            ("Phrase length", self.phrase_length_spin),
            ("Groove / fill ratio", self.groove_fill_spin),
            ("Fidelity weight", self.fidelity_spin),
            ("Coherence weight", self.coherence_spin),
            ("Tolerance band", self.tolerance_spin),
            ("Gobo threshold", self.gobo_threshold_spin),
            ("Prism threshold", self.prism_threshold_spin),
        ]
        for index, (caption, editor) in enumerate(fields):
            grid.addWidget(_ParamField(caption, editor), index // 4,
                           index % 4)
        for column in range(4):
            grid.setColumnStretch(column, 1)
        return grid_host

    @staticmethod
    def _ratio_spin(minimum, maximum, value) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(minimum, maximum)
        spin.setSingleStep(0.05)
        spin.setValue(value)
        return spin

    def _build_inspector_table(self) -> QWidget:
        table = QWidget()
        table.setObjectName("AutogenInspectorTable")
        table.setProperty("role", "inspector")
        table.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout = QVBoxLayout(table)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QWidget()
        header.setObjectName("GroupRow")  # bottom hairline under the head
        header.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        header_row = QHBoxLayout(header)
        header_row.setContentsMargins(14, 8, 14, 8)
        header_row.setSpacing(10)
        for text, width in (("Section", INSPECTOR_SECTION_WIDTH),
                            ("Envelope", INSPECTOR_ENVELOPE_WIDTH),
                            ("Picks (per group)", None),
                            ("Why", INSPECTOR_WHY_WIDTH)):
            label = _caption(text)
            if width is not None:
                label.setFixedWidth(width)
            header_row.addWidget(label, 0 if width is not None else 1)
        layout.addWidget(header)

        self.inspector_rows = []
        sections = getattr(self._report, "sections", None) or []
        if not sections:
            empty = QLabel(
                "No generation run yet. Choose the palette and parameters, "
                "then GENERATE - every decision shows up here.")
            empty.setObjectName("AutogenInspectorEmpty")
            empty.setProperty("role", "hint-box")
            empty.setWordWrap(True)
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            wrapper = QVBoxLayout()
            wrapper.setContentsMargins(14, 14, 14, 14)
            wrapper.addWidget(empty)
            layout.addLayout(wrapper)
        else:
            peak = peak_section_index(self._report)
            for index, section in enumerate(sections):
                row = _InspectorRow(section, highlight=(index == peak))
                self.inspector_rows.append(row)
                layout.addWidget(row)
        return table

    # -- palette state ---------------------------------------------------

    def palette_mode(self) -> str:
        for mode, btn in self._mode_buttons.items():
            if btn.isChecked():
                return mode
        return MODE_AUDIO

    def _set_palette_mode(self, mode: str) -> None:
        self._mode_buttons[mode].setChecked(True)
        self.color_preset_combo.setVisible(mode == MODE_PRESET)
        self.palette_hint.setVisible(mode == MODE_AUDIO)
        self._swatch_row.setVisible(mode != MODE_AUDIO)
        self._count_row.setVisible(mode != MODE_AUDIO)
        self.include_white_check.setVisible(mode != MODE_AUDIO)
        self._set_custom_visible(mode == MODE_CUSTOM)
        if mode == MODE_PRESET:
            self._on_color_preset_changed(self.color_preset_combo.currentText())

    def _set_custom_visible(self, editable: bool) -> None:
        """Custom mode is the only one where the swatches are editable and
        the count segments apply; a preset previews its own colors."""
        for btn in (self.color_btn_1, self.color_btn_2, self.color_btn_3):
            btn.setEnabled(editable)
            btn.setToolTip("" if editable else
                           "Colours come from the selected preset")
        for btn in self._count_buttons:
            btn.setEnabled(editable)
        self.include_white_check.setEnabled(editable)
        if editable:
            self._on_num_colors_changed(self.num_colors() - 1)
        self.white_swatch.setVisible(self.include_white_check.isChecked())

    def num_colors(self) -> int:
        for index, btn in enumerate(self._count_buttons):
            if btn.isChecked():
                return index + 1
        return 1

    def _on_color_preset_changed(self, text) -> None:
        """Preview the preset's colors in the swatch row."""
        preset = get_preset_palette(text)
        if not preset:
            return
        self.color_btn_1.color = preset.primary
        self.color_btn_1._update_style()
        self.color_btn_2.setVisible(preset.secondary is not None)
        if preset.secondary:
            self.color_btn_2.color = preset.secondary
            self.color_btn_2._update_style()
        self.color_btn_3.setVisible(preset.tertiary is not None)
        if preset.tertiary:
            self.color_btn_3.color = preset.tertiary
            self.color_btn_3._update_style()
        self.include_white_check.setChecked(preset.include_white)

    def _on_num_colors_changed(self, index) -> None:
        """Show as many swatches as the palette carries colors."""
        num = index + 1
        if 1 <= num <= 3:
            self._count_buttons[num - 1].setChecked(True)
        self.color_btn_2.setVisible(num >= 2)
        self.color_btn_3.setVisible(num >= 3)

    def _build_palette(self):
        """Build the SongPalette the worker receives (None = auto)."""
        mode = self.palette_mode()
        if mode == MODE_AUDIO:
            return None
        if mode == MODE_PRESET:
            preset = get_preset_palette(self.color_preset_combo.currentText())
            if preset:
                return preset
            return None

        num = self.num_colors()
        return SongPalette(
            primary=self.color_btn_1.color,
            secondary=self.color_btn_2.color if num >= 2 else None,
            tertiary=self.color_btn_3.color if num >= 3 else None,
            include_white=self.include_white_check.isChecked(),
        )

    # -- accept ------------------------------------------------------------

    def _on_accepted(self):
        """Build config and accept."""
        self.result_config = AutogenConfig(
            groove_fill_ratio=self.groove_fill_spin.value(),
            phrase_length_bars=self.phrase_length_spin.value(),
            fidelity_weight=self.fidelity_spin.value(),
            coherence_weight=self.coherence_spin.value(),
            tolerance_band_width=self.tolerance_spin.value(),
            spectral_richness_gobo_threshold=self.gobo_threshold_spin.value(),
            spectral_richness_prism_threshold=self.prism_threshold_spin.value(),
        )

        key_text = self.key_combo.currentText()
        self.result_key_signature = None if key_text == AUTO_KEY else key_text
        self.result_palette = self._build_palette()

        self.accept()
