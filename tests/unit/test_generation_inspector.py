"""Smoke tests for the Generation Inspector window (v1.5.5 hardening, G10).

``gui/dialogs/generation_inspector.py`` (the autogen decision dashboard
the Shows tab opens next to playback) had no test. These build it from
recorded-style reports, paint every panel at several playhead
positions, and drive the clicks a user makes. Paint-time exceptions in
PyQt only print, so the tests route ``sys.excepthook`` into a list and
assert it stays empty.

Two bugs pinned here:

- Moving into a section where the selected group has no decision (or no
  group has one) left the PREVIOUS section's match-score bars on screen
  under the new section; clicking such a group did the same. The score
  panel now falls back to its empty state.
- Section, group and rudiment names went into the rich-text info panel
  unescaped, so "Front & Back" or "<Wash>" lost characters or broke the
  table markup.
"""

from __future__ import annotations

import os
import sys

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import QWidget

from autogen.report import (
    GenerationReport,
    GroupSectionReport,
    MatchScoreEntry,
    SectionReport,
)
from gui.dialogs.generation_inspector import FluxPlot3DWidget, GenerationInspector


def _group(rudiment="chase", weight=1.0, scores=True):
    return GroupSectionReport(
        weight=weight, role="full", groove_rudiment=rudiment,
        groove_category="rolling",
        match_scores=[
            MatchScoreEntry(rudiment, 0.8, 0.5, 0.4, 0.3, 0.2),
            MatchScoreEntry("wave", 0.5, 0.3, 0.2, 0.1, 0.1),
        ] if scores else [],
    )


def _section(name, start, end, groups, colors=((255, 0, 0),)):
    sec = SectionReport(
        name=name, start_time=start, end_time=end, relative_energy=0.6,
        spectral_flux=0.4, spectral_centroid=1200.0 + start,
        color_rgb=list(colors),
    )
    sec.group_reports = groups
    return sec


def _full_report() -> GenerationReport:
    n = 60
    rng = np.random.RandomState(0)
    return GenerationReport(
        group_names=["Pars", "Wash"],
        song_palette_rgb=[(255, 0, 0), (0, 0, 255)],
        sections=[
            _section("Intro", 0.0, 10.0, {"Pars": _group("static")}),
            _section("Verse", 10.0, 20.0,
                     {"Pars": _group("chase"), "Wash": _group("wave")}),
            _section("Break", 20.0, 30.0, {}),
        ],
        frame_times=list(np.linspace(0.0, 30.0, n)),
        frame_flux=list(rng.uniform(0, 1, n)),
        frame_transient=list(rng.uniform(0, 1, n)),
        frame_richness=list(rng.uniform(0, 1, n)),
        frame_vocal=list(rng.uniform(0, 1, n)),
        frame_centroid=list(rng.uniform(500, 3000, n)),
        mel_spectrogram_db=rng.uniform(-80.0, 0.0, (32, 90)),
        mel_frequencies=np.linspace(20.0, 8000.0, 32),
        mel_times=np.linspace(0.0, 30.0, 90),
    )


@pytest.fixture
def paint_errors(monkeypatch):
    """Collect exceptions raised inside Qt virtuals (paintEvent etc.)."""
    errors = []
    monkeypatch.setattr(sys, "excepthook",
                        lambda *exc: errors.append(exc[1]))
    return errors


@pytest.fixture
def make_inspector(qapp):
    made = []

    def build(report):
        w = GenerationInspector(report, audio_path="")
        w.resize(1000, 760)
        w.show()
        qapp.processEvents()
        made.append(w)
        return w

    yield build
    for w in made:
        w.close()


def _paint_all(widget):
    widget.grab()
    for child in widget.findChildren(QWidget):
        if child.isVisible():
            child.grab()


def _click(widget, x, y):
    pos = QPointF(x, y)
    for kind in (QMouseEvent.Type.MouseButtonPress,
                 QMouseEvent.Type.MouseButtonRelease):
        event = QMouseEvent(kind, pos, widget.mapToGlobal(pos),
                            Qt.MouseButton.LeftButton,
                            Qt.MouseButton.LeftButton,
                            Qt.KeyboardModifier.NoModifier)
        if kind == QMouseEvent.Type.MouseButtonPress:
            widget.mousePressEvent(event)
        else:
            widget.mouseReleaseEvent(event)


class TestPaintsEveryReportShape:
    @pytest.mark.parametrize("report", [
        GenerationReport(),
        _full_report(),
        # section-level fallback (no frame data, no spectrogram)
        GenerationReport(group_names=["Pars"],
                         sections=[_section("Only", 0.0, 5.0, {"Pars": _group()})]),
        # zero-length song
        GenerationReport(group_names=["Pars"],
                         sections=[_section("Zero", 0.0, 0.0, {})]),
        # a section names a group the report does not list
        GenerationReport(group_names=[],
                         sections=[_section("X", 0.0, 5.0, {"Ghost": _group()})]),
    ], ids=["empty", "full", "sections-only", "zero-length", "ghost-group"])
    def test_paints_across_the_whole_timeline(self, make_inspector,
                                              paint_errors, report):
        w = make_inspector(report)
        _paint_all(w)
        for t in (-1.0, 0.0, 4.9, 10.0, 19.99, 29.9, 30.0, 500.0):
            w.update_position(t)
            _paint_all(w)
        w.resize(240, 200)   # cramped: plot areas collapse to <= 0
        _paint_all(w)
        assert paint_errors == []

    def test_sections_drive_info_and_activation(self, make_inspector):
        report = _full_report()
        w = make_inspector(report)
        w.update_position(12.0)
        assert w._current_section_idx == 1
        assert w.activation_widget.current_section_idx == 1
        assert "Verse" in w.info_label.text()
        assert w.color_widget._current_colors == report.sections[1].color_rgb
        w.update_position(25.0)
        assert w._current_section_idx == 2


class TestInteraction:
    def test_legend_click_toggles_a_feature(self, make_inspector):
        w = make_inspector(_full_report())
        audio = w.audio_widget
        audio.grab()   # paint fills the legend hit rects
        rect = audio._legend_rects["flux"]
        _click(audio, rect.center().x(), rect.center().y())
        assert audio._visible["flux"] is False
        _click(audio, rect.center().x(), rect.center().y())
        assert audio._visible["flux"] is True

    def test_activation_click_selects_group_and_shows_its_scores(self, make_inspector):
        w = make_inspector(_full_report())
        w.update_position(12.0)
        grid = w.activation_widget
        # second row = "Wash"
        row_h = (grid.height() - 16 - 4) / 2
        _click(grid, 120, 16 + row_h * 1.5)
        assert w._selected_group == "Wash"
        assert w.scores_widget._group_name == "Wash"
        assert w.scores_widget._selected_rudiment == "wave"
        assert len(w.scores_widget._scores) == 2

    def test_flux_plot_orbit_and_zoom(self, qapp, paint_errors):
        plot = FluxPlot3DWidget()
        plot.resize(400, 300)
        report = _full_report()
        plot.set_data(report.frame_times, report.frame_flux,
                      report.frame_transient, report.sections)
        plot.grab()
        _click(plot, 100, 100)
        plot.update_cursor(15.0)
        plot.grab()
        assert plot._projected and not plot._needs_reproject
        plot.set_data([], [], [], [])
        plot.grab()
        assert paint_errors == []


class TestScorePanelNeverGoesStale:
    def test_section_without_decisions_clears_previous_scores(self, make_inspector):
        w = make_inspector(_full_report())
        w.update_position(12.0)            # Verse: Pars has scores
        assert w.scores_widget._scores
        w.update_position(25.0)            # Break: no group decisions
        assert w.scores_widget._scores == []

    def test_selected_group_missing_from_section_clears_scores(self, make_inspector):
        w = make_inspector(_full_report())
        w.update_position(12.0)
        w._on_group_selected("Wash")
        assert w.scores_widget._group_name == "Wash"
        w.update_position(5.0)             # Intro: only Pars decided
        # Falls back to the first active group, with ITS scores.
        assert w.scores_widget._group_name == "Pars"
        assert w.scores_widget._selected_rudiment == "static"
        w._on_group_selected("Wash")       # click a group absent here
        assert w.scores_widget._scores == []
        assert w.scores_widget._group_name == "Wash"


class TestInfoPanelEscapesNames:
    def test_markup_in_names_is_shown_literally(self, make_inspector):
        report = GenerationReport(
            group_names=["Front & Back", "<Wash>"],
            sections=[_section("Verse <1>", 0.0, 10.0, {
                "Front & Back": _group("chase"),
                "<Wash>": _group("wave"),
            })],
        )
        w = make_inspector(report)
        w.update_position(1.0)
        text = w.info_label.text()
        assert "Verse &lt;1&gt;" in text
        assert "Front &amp; B" in text
        assert "&lt;Wash&gt;" in text
        assert "<Wash>" not in text

    def test_none_fields_render_instead_of_crashing(self, make_inspector):
        # Before escaping, an f-string printed a None rudiment as "None";
        # html.escape(None) would raise inside update_position instead.
        gr = _group("chase")
        gr.fill_rudiment = None
        report = GenerationReport(
            group_names=["Pars"],
            sections=[_section("Verse", 0.0, 10.0, {"Pars": gr})],
        )
        report.sections[0].movement_shape = None
        w = make_inspector(report)
        w.update_position(1.0)
        assert "None" in w.info_label.text()
