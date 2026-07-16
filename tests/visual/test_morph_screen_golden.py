# tests/visual/test_morph_screen_golden.py
"""Golden screenshot for the morph screen's PATCH page (v1.5b, rework
2026-07-16 after the dialog era shipped elided chips and clipped group
names).

Pins the layout the rework fixed: group names LEADING their target
rows, capability chips wide enough for their full text, edge chips in
a wrapping flow inside the row frame, the visible LOCK button, the
arrow-glyph lane expanders, and the step rail with PATCH active.

The screen is grabbed inside a themed QMainWindow (a bare top-level
QWidget composites no styled background) after flushing DeferredDelete
- _rebuild_rows retires row generations via deleteLater and a grab
without a running event loop ghost-stacks them. Regenerate with
QLC_REGEN_GOLDENS=1 and review the PNG.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from tests.visual.harness import compare_to_golden


def _fixture(name, group="G"):
    from config.models import Fixture, FixtureMode
    return Fixture(universe=1, address=1, manufacturer="M", model="X",
                   current_mode="Std",
                   available_modes=[FixtureMode(name="Std", channels=1)],
                   name=name, group=group)


def _group(name, fixtures, caps, role=""):
    from config.models import FixtureGroup, FixtureGroupCapabilities
    group = FixtureGroup(name, fixtures, lighting_role=role)
    group.capabilities = FixtureGroupCapabilities(
        has_dimmer="dimmer" in caps, has_colour="colour" in caps,
        has_movement="movement" in caps, has_special="special" in caps)
    return group


def _config(groups, songs=None):
    from config.models import Configuration, Universe
    fixtures = [f for g in groups for f in g.fixtures]
    cfg = Configuration(fixtures=fixtures,
                        groups={g.name: g for g in groups},
                        universes={1: Universe(id=1, name="U1", output={})})
    cfg.songs = songs or {}
    return cfg


def _song():
    from config.models import (ColourBlock, DimmerBlock, LightBlock,
                               LightLane, MovementBlock, ShowPart, Song,
                               TimelineData)
    pars = LightLane(
        name="Pars", fixture_targets=["PARS"],
        light_blocks=[LightBlock(
            start_time=0.0, end_time=16.0, effect_name="x",
            dimmer_blocks=[DimmerBlock(0.0, 16.0, intensity=200.0)],
            colour_blocks=[ColourBlock(0.0, 16.0, red=255.0)])])
    movers = LightLane(
        name="Movers", fixture_targets=["MOVERS"],
        light_blocks=[LightBlock(
            start_time=0.0, end_time=8.0, effect_name="x",
            dimmer_blocks=[DimmerBlock(0.0, 8.0, intensity=180.0)],
            movement_blocks=[MovementBlock(0.0, 8.0,
                                           effect_type="circle")])])
    return Song(name="S",
                parts=[ShowPart(name="All", color="#fff", signature="4/4",
                                bpm=120.0, num_bars=8,
                                transition="instant")],
                timeline_data=TimelineData(lanes=[pars, movers])), pars


def _flush(qapp):
    from PyQt6 import QtCore
    for _ in range(3):
        QtCore.QCoreApplication.sendPostedEvents(
            None, QtCore.QEvent.Type.DeferredDelete.value)
        qapp.processEvents()


@pytest.fixture
def morph_window(qapp):
    from PyQt6 import QtWidgets
    from gui.theme_manager import ThemeManager
    from gui.screens.morph_screen import MorphScreen

    ThemeManager().apply(qapp, "dark")
    song, pars = _song()
    source = _config(
        [_group("PARS", [_fixture("p1")], {"dimmer", "colour"},
                role="backbone"),
         _group("MOVERS", [_fixture("m1", group="MOVERS")],
                {"dimmer", "movement"}, role="movement")],
        songs={"S": song})
    target = _config(
        [_group("WASH", [_fixture("w1", group="WASH"),
                         _fixture("w2", group="WASH")],
                {"dimmer", "colour"}, role="backbone"),
         _group("SPOT", [_fixture("s1", group="SPOT")],
                {"dimmer", "movement"}, role="movement"),
         _group("STROBE", [_fixture("b1", group="STROBE")],
                {"dimmer"})])

    screen = MorphScreen(source, source_path="master.lms")
    screen.set_target_config(target, "venue.lms")
    window = QtWidgets.QMainWindow()
    window.setCentralWidget(screen)
    window.resize(1280, 800)
    window.show()
    _flush(qapp)
    try:
        yield window, screen
    finally:
        window.hide()
        window.deleteLater()
        _flush(qapp)


def test_morph_screen_patchbay_golden(qapp, morph_window):
    window, screen = morph_window
    screen._go_next()                       # TARGET -> PATCH
    screen.patchbay.auto_suggest()
    # One lane expanded + one pending wire: the golden pins the sublane
    # rows, the arrow glyphs, the checked chip and the gated (disabled)
    # target chips in a single grab.
    first = screen.patchbay._lanes[0].lane_id
    screen.patchbay.set_expanded(first, True)
    screen.patchbay._chip_clicked(first, "dimmer")
    _flush(qapp)
    assert (window.width(), window.height()) == (1280, 800), (
        "grab size drifted - golden invalid"
    )
    compare_to_golden(window.grab().toImage(),
                      "morph_screen_patchbay_dark")
