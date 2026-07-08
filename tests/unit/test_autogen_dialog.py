"""AutogenDialog: public contract, reference anatomy, honest omissions.

The dialog was rebuilt against
design_handoff_lichtmaschine_app/screens/10-autogen-dialog.html. These
tests pin three things:

1. the contract both callers rely on (``AutogenDialog(parent)`` ->
   ``exec()`` -> ``result_config`` / ``result_key_signature`` /
   ``result_palette``, plus AutogenWorker's signals);
2. the anatomy: role properties for every themed element, the four
   inspector columns, the accent GENERATE call to action;
3. the omissions: the reference's INTENSITY CEILING slider, its
   "Overwrite existing blocks" toggle and its "SEED . RERUN" readout
   have no backing in autogen/ and must not be faked.
"""

from __future__ import annotations

import os
from dataclasses import fields

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QDialog

from autogen.color_generator import SongPalette, get_preset_names
from autogen.matcher import AutogenConfig
from autogen.report import GenerationReport, GroupSectionReport, SectionReport
from config.models import Configuration, FixtureGroup, Show, ShowPart, TimelineData
from gui.dialogs.autogen_dialog import (
    AUTO_KEY, LEFT_COLUMN_WIDTH, MODE_AUDIO, MODE_CUSTOM, MODE_PRESET,
    AutogenDialog, AutogenWorker, peak_section_index, section_envelope,
    section_picks, section_why,
)


# ──────────────────────────────────────────────
# Fixtures: a realistic Configuration + a realistic report
# ──────────────────────────────────────────────

def make_config() -> Configuration:
    config = Configuration()
    config.groups["Pars"] = FixtureGroup("Pars", [])
    config.groups["Wash"] = FixtureGroup("Wash", [])
    config.groups["Movers"] = FixtureGroup("Movers", [])
    config.shows["Neon Ruinen"] = Show(
        name="Neon Ruinen",
        parts=[
            ShowPart("Intro", "#8D9299", "4/4", 120.0, 8, "gradual"),
            ShowPart("Verse 1", "#4ECBD4", "4/4", 126.0, 16, "gradual"),
            ShowPart("Chorus 1", "#F0562E", "4/4", 128.0, 8, "instant"),
            ShowPart("Drop", "#C95FD0", "4/4", 128.0, 8, "gradual"),
            ShowPart("Outro", "#8D9299", "4/4", 120.0, 8, "instant"),
        ],
        effects=[],
        timeline_data=TimelineData(),
    )
    return config


def _group(role, groove, category, weight=1.0):
    return GroupSectionReport(weight=weight, role=role, groove_rudiment=groove,
                              groove_category=category)


def make_report() -> GenerationReport:
    """Five sections with realistic recorded features; CHORUS 1 peaks."""
    def section(name, energy, flux, vocal, groups):
        report = SectionReport(name=name, relative_energy=energy,
                               spectral_flux=flux, vocal_presence=vocal)
        report.group_reports = groups
        return report

    return GenerationReport(
        group_names=["Pars", "Wash", "Movers"],
        sections=[
            section("Intro", 0.18, 0.12, 0.0, {
                "Pars": _group("full", "single_stroke", "flat"),
                "Wash": _group("groove", "static", "flat"),
                "Movers": _group("fill", "static", "flat", weight=0.0),
            }),
            section("Verse 1", 0.45, 0.33, 0.8, {
                "Pars": _group("groove", "paradiddle", "oscillating"),
                "Wash": _group("full", "single_stroke_four", "rolling"),
            }),
            section("Chorus 1", 0.91, 0.72, 0.9, {
                "Pars": _group("full", "flam_accent", "spike"),
                "Wash": _group("groove", "five_stroke_roll", "rolling"),
                "Movers": _group("fill", "drag", "ramp"),
            }),
            section("Drop", 0.80, 0.95, 0.1, {
                "Pars": _group("full", "buzz_roll", "stochastic"),
                "Wash": _group("full", "buzz_roll", "stochastic"),
                "Movers": _group("full", "single_stroke", "spike"),
            }),
            section("Outro", 0.10, 0.08, 0.0, {
                "Pars": _group("groove", "static", "flat"),
            }),
        ],
    )


@pytest.fixture
def dialog(qapp):
    from gui.theme_manager import ThemeManager
    ThemeManager().apply(qapp, "dark")
    config = make_config()
    dlg = AutogenDialog(None, audio_path="/songs/neon_ruinen.wav",
                        show=config.shows["Neon Ruinen"], report=make_report())
    yield dlg
    dlg.deleteLater()


@pytest.fixture
def empty_dialog(qapp):
    from gui.theme_manager import ThemeManager
    ThemeManager().apply(qapp, "dark")
    dlg = AutogenDialog(None)
    yield dlg
    dlg.deleteLater()


# ──────────────────────────────────────────────
# Public contract (grep: gui/tabs/shows_tab.py:1141,
# gui/tabs/structure_tab.py:1332 construct with a bare parent)
# ──────────────────────────────────────────────

def test_constructs_with_only_a_parent(qapp):
    dlg = AutogenDialog(None)
    assert isinstance(dlg, QDialog)
    assert dlg.result_config is None
    assert dlg.result_key_signature is None
    assert dlg.result_palette is None
    dlg.deleteLater()


def test_generate_button_accepts_and_fills_the_results(dialog):
    accepted = []
    dialog.accepted.connect(lambda: accepted.append(True))
    dialog.phrase_length_spin.setValue(8)
    dialog.groove_fill_spin.setValue(0.6)
    dialog.fidelity_spin.setValue(0.55)
    dialog.coherence_spin.setValue(0.45)
    dialog.tolerance_spin.setValue(0.25)
    dialog.gobo_threshold_spin.setValue(0.65)
    dialog.prism_threshold_spin.setValue(0.85)
    dialog.key_combo.setCurrentText("D minor")

    dialog.generate_btn.click()

    assert accepted == [True]
    assert dialog.result() == QDialog.DialogCode.Accepted
    config = dialog.result_config
    assert isinstance(config, AutogenConfig)
    assert config.phrase_length_bars == 8
    assert config.groove_fill_ratio == pytest.approx(0.6)
    assert config.fidelity_weight == pytest.approx(0.55)
    assert config.coherence_weight == pytest.approx(0.45)
    assert config.tolerance_band_width == pytest.approx(0.25)
    assert config.spectral_richness_gobo_threshold == pytest.approx(0.65)
    assert config.spectral_richness_prism_threshold == pytest.approx(0.85)
    assert dialog.result_key_signature == "D minor"


def test_auto_key_maps_to_none(dialog):
    dialog.key_combo.setCurrentText(AUTO_KEY)
    dialog.generate_btn.click()
    assert dialog.result_key_signature is None


def test_cancel_rejects_without_building_a_config(dialog):
    dialog.cancel_btn.click()
    assert dialog.result() == QDialog.DialogCode.Rejected
    assert dialog.result_config is None


def test_worker_signature_and_signals():
    worker = AutogenWorker("a.wav", object(), Configuration(),
                           AutogenConfig(), None, None)
    assert worker.audio_path == "a.wav"
    for signal in ("finished", "error", "progress"):
        assert hasattr(worker, signal)


# ──────────────────────────────────────────────
# Palette: modes map onto the real SongPalette model
# ──────────────────────────────────────────────

def test_default_palette_mode_is_from_audio_and_yields_none(dialog):
    assert dialog.palette_mode() == MODE_AUDIO
    dialog.generate_btn.click()
    assert dialog.result_palette is None


def test_preset_mode_returns_the_named_preset(dialog):
    dialog._set_palette_mode(MODE_PRESET)
    assert dialog.color_preset_combo.isVisibleTo(dialog)
    dialog.color_preset_combo.setCurrentText("Ocean")
    dialog.generate_btn.click()
    palette = dialog.result_palette
    assert isinstance(palette, SongPalette)
    assert palette.primary == (0, 100, 255)


def test_preset_combo_lists_exactly_the_registered_presets(dialog):
    items = [dialog.color_preset_combo.itemText(i)
             for i in range(dialog.color_preset_combo.count())]
    assert items == get_preset_names()


def test_custom_mode_builds_a_palette_from_the_swatches(dialog):
    dialog._set_palette_mode(MODE_CUSTOM)
    dialog.color_btn_1.color = (10, 20, 30)
    dialog.color_btn_2.color = (40, 50, 60)
    dialog.color_btn_3.color = (70, 80, 90)
    dialog._on_num_colors_changed(2)  # three colors
    dialog.include_white_check.setChecked(False)
    dialog.generate_btn.click()
    palette = dialog.result_palette
    assert palette.primary == (10, 20, 30)
    assert palette.secondary == (40, 50, 60)
    assert palette.tertiary == (70, 80, 90)
    assert palette.include_white is False
    assert palette.num_colors == 3


def test_custom_mode_one_colour_drops_secondary_and_tertiary(dialog):
    dialog._set_palette_mode(MODE_CUSTOM)
    dialog._on_num_colors_changed(0)
    assert dialog.num_colors() == 1
    assert not dialog.color_btn_2.isVisibleTo(dialog)
    dialog.generate_btn.click()
    assert dialog.result_palette.secondary is None
    assert dialog.result_palette.tertiary is None


def test_from_audio_mode_hides_the_swatches_instead_of_faking_them(dialog):
    """The audio palette only exists after analysis, so the dialog must
    not paint colors the generator will not use."""
    dialog._set_palette_mode(MODE_AUDIO)
    assert not dialog._swatch_row.isVisibleTo(dialog)
    assert not dialog._count_row.isVisibleTo(dialog)
    assert dialog.palette_hint.isVisibleTo(dialog)
    assert dialog.palette_hint.property("role") == "hint-box"


def test_swatches_are_read_only_outside_custom_mode(dialog):
    dialog._set_palette_mode(MODE_PRESET)
    assert dialog._swatch_row.isVisibleTo(dialog)
    assert not dialog.color_btn_1.isEnabled()
    assert not dialog.palette_hint.isVisibleTo(dialog)
    dialog._set_palette_mode(MODE_CUSTOM)
    assert dialog.color_btn_1.isEnabled()


# ──────────────────────────────────────────────
# Caller context: audio / structure readouts show real data only
# ──────────────────────────────────────────────

def test_audio_readout_uses_the_supplied_path(dialog):
    assert dialog.audio_label.text() == "neon_ruinen.wav"
    assert dialog.audio_chip.property("variant") == "accent"


def test_audio_readout_warns_when_no_audio_is_known(empty_dialog):
    assert "no audio" in empty_dialog.audio_label.text()
    assert empty_dialog.audio_chip.property("variant") == "warning"


def test_structure_readout_counts_real_parts_and_bars(dialog):
    # 8 + 16 + 8 + 8 + 8 = 48 bars, matching the reference copy.
    assert dialog.structure_label.text() == \
        "From show · Structure · 5 parts, 48 bars"


def test_structure_readout_without_a_show(empty_dialog):
    assert empty_dialog.structure_label.text() == "no song parts defined"


def test_context_is_read_off_the_parent_when_not_passed(qapp):
    """Both callers pass themselves as parent (shows_tab.py:1141,
    structure_tab.py:1332); the dialog reads their state, never writes."""
    class FakeAudioLane:
        def get_audio_file_path(self):
            return "song.wav"

    class FakeTab:
        audio_lane = FakeAudioLane()
        current_show = make_config().shows["Neon Ruinen"]
        _generation_report = make_report()

    tab = FakeTab()
    dlg = AutogenDialog(None, audio_path=tab.audio_lane.get_audio_file_path(),
                        show=tab.current_show, report=tab._generation_report)
    assert dlg.audio_label.text() == "song.wav"
    assert len(dlg.inspector_rows) == 5
    dlg.deleteLater()

    assert AutogenDialog._parent_audio_path(tab) == "song.wav"
    assert AutogenDialog._parent_show(tab) is tab.current_show
    assert AutogenDialog._parent_report(tab) is tab._generation_report
    assert AutogenDialog._parent_audio_path(object()) is None
    assert AutogenDialog._parent_show(object()) is None
    assert AutogenDialog._parent_report(object()) is None


# ──────────────────────────────────────────────
# Inspector: every cell comes from a recorded report field
# ──────────────────────────────────────────────

def test_inspector_renders_one_row_per_section(dialog):
    assert len(dialog.inspector_rows) == 5
    names = [row.name_label.text() for row in dialog.inspector_rows]
    assert names == ["INTRO", "VERSE 1", "CHORUS 1", "DROP", "OUTRO"]


def test_inspector_envelope_is_the_dominant_groove_category():
    report = make_report()
    assert section_envelope(report.sections[0]) == "FLAT"
    assert section_envelope(report.sections[3]) == "STOCHASTIC"
    # Ties resolve to the first group in report order (no set iteration,
    # so the readout is stable under any PYTHONHASHSEED).
    assert section_envelope(report.sections[1]) == "OSCILLATING"
    assert section_envelope(report.sections[2]) == "SPIKE"
    # Groups with weight 0 contribute nothing.
    empty = SectionReport(name="Silence")
    assert section_envelope(empty) == "STATIC"


def test_inspector_picks_list_the_active_groups():
    report = make_report()
    assert section_picks(report.sections[1]) == \
        "PARS paradiddle · WASH single_stroke_four"
    assert section_picks(report.sections[2], max_groups=2) == \
        "PARS flam_accent · WASH five_stroke_roll · +1 more"
    assert section_picks(SectionReport()) == "no groups active"


def test_inspector_why_quotes_recorded_audio_features():
    report = make_report()
    assert section_why(report.sections[0]) == \
        "energy 0.18, flux 0.12, no vocals"
    assert section_why(report.sections[2]) == \
        "energy 0.91, flux 0.72, vocals"


def test_picks_column_elides_rather_than_clipping(dialog, qapp):
    from PyQt6.QtGui import QFontMetrics
    row = dialog.inspector_rows[2]
    label = row.picks_label
    assert label.full_text() == \
        "PARS flam_accent · WASH five_stroke_roll · MOVERS drag"
    # A hidden widget only gets its QResizeEvent on show, so re-run the
    # elide explicitly at the narrow width the layout would hand it.
    label.resize(80, 20)
    label.setText(label.full_text())
    assert label.text() != label.full_text()
    assert QFontMetrics(label.font()).horizontalAdvance(label.text()) <= 80
    assert label.toolTip() == label.full_text()


def test_peak_row_is_the_highest_relative_energy_section(dialog):
    report = make_report()
    assert peak_section_index(report) == 2  # Chorus 1
    assert peak_section_index(GenerationReport()) == -1
    assert peak_section_index(None) == -1

    selected = [row.property("selected") for row in dialog.inspector_rows]
    assert selected == ["false", "false", "true", "false", "false"]
    assert dialog.inspector_rows[2].peak_chip.property("variant") == "accent"


def test_inspector_shows_an_empty_state_without_a_report(empty_dialog):
    assert empty_dialog.inspector_rows == []
    assert empty_dialog.inspector_status.text() == "NO RUN YET"
    empty = empty_dialog.findChild(object, "AutogenInspectorEmpty")
    assert empty is not None
    assert empty.property("role") == "hint-box"


def test_inspector_status_counts_sections(dialog):
    assert dialog.inspector_status.text() == "5 SECTIONS"


# ──────────────────────────────────────────────
# Anatomy: role properties, not stylesheets
# ──────────────────────────────────────────────

def test_generate_is_the_accent_primary_and_cancel_the_outline(dialog):
    assert dialog.generate_btn.property("role") == "primary"
    assert dialog.generate_btn.isDefault()
    assert dialog.cancel_btn.property("role") == "cta-outline"


def test_accent_primary_rule_paints_the_brand_orange():
    from gui.theme_tokens import render_theme
    qss = render_theme("dark")
    assert 'QPushButton[role="primary"]' in qss
    assert "#F0562E" in qss


def test_left_column_matches_the_reference_width(dialog):
    assert LEFT_COLUMN_WIDTH == 420
    column = dialog.findChild(object, "AutogenConfigColumn")
    assert column.width() == 420 or column.minimumWidth() == 420
    assert column.property("role") == "inspector"


def test_themed_elements_carry_roles_not_inline_stylesheets(dialog):
    assert dialog.findChild(object, "AutogenHeader").property("role") == \
        "section-caption"
    assert dialog.findChild(object, "AutogenInspectorTable").property("role") \
        == "inspector"
    assert dialog.title_label.property("role") == "display"
    assert dialog.inspector_caption.property("role") == "stat-caption"
    assert dialog.footer_hint.property("role") == "stat-caption"
    for mode in (MODE_AUDIO, MODE_PRESET, MODE_CUSTOM):
        assert dialog._mode_buttons[mode].property("role") == "mode-chip"
    for btn in dialog._count_buttons:
        assert btn.property("role") == "segment"
    assert dialog.color_preset_combo.property("role") == "accent-field"


def test_inspector_rows_use_the_group_row_chrome(dialog):
    for row in dialog.inspector_rows:
        assert row.objectName() == "GroupRow"
    # ...and that role really draws a hairline + raised selected state.
    from gui.theme_tokens import render_theme
    qss = render_theme("dark")
    assert "#GroupRow {" in qss
    assert '#GroupRow[selected="true"]' in qss


def test_no_banned_symbols_in_visible_text(dialog):
    from PyQt6.QtWidgets import QAbstractButton, QLabel
    banned = "▾⚙✓⧉＋×—–✕↻"
    texts = [w.text() for w in dialog.findChildren(QLabel)]
    texts += [w.text() for w in dialog.findChildren(QAbstractButton)]
    texts.append(dialog.windowTitle())
    for text in texts:
        for ch in banned:
            assert ch not in text, f"banned symbol {ch!r} in {text!r}"


# ──────────────────────────────────────────────
# Omissions: the reference shows controls autogen/ cannot honor
# ──────────────────────────────────────────────

def test_autogen_config_has_no_intensity_ceiling_or_overwrite_field():
    """Proof that the reference's INTENSITY CEILING slider and its
    "Overwrite existing blocks" toggle have nothing to bind to."""
    names = {f.name for f in fields(AutogenConfig)}
    assert "intensity_ceiling" not in names
    assert not any("ceiling" in n for n in names)
    assert not any("overwrite" in n for n in names)
    assert not any("seed" in n for n in names)


def test_dialog_omits_the_unbacked_reference_controls(dialog):
    from PyQt6.QtWidgets import QAbstractButton, QLabel, QSlider
    assert dialog.findChildren(QSlider) == []  # no intensity ceiling
    texts = [w.text().lower() for w in dialog.findChildren(QLabel)]
    texts += [w.text().lower() for w in dialog.findChildren(QAbstractButton)]
    blob = " ".join(texts)
    for phantom in ("overwrite", "ceiling", "seed", "rerun"):
        assert phantom not in blob


def test_generation_report_carries_no_seed():
    """The 'SEED 4211 . RERUN' readout of the reference cannot be
    reproduced: generation samples the unseeded global RNG."""
    names = {f.name for f in fields(GenerationReport)}
    assert "seed" not in names
