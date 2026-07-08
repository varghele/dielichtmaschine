"""Golden screenshot for the Auto tab (reference screen 07).

Pins the rebuilt anatomy: the 420px GROUPS · MODE panel (group-color
left borders, AUTO / CURATED / LOCKED chip selectors, riff line,
group-colored intensity bars, ENERGY SENSITIVITY + PLANE BIAS footer),
the engine stage on the engineering grid (state caption, huge BPM
readout, BPM AUTO / TAP / SET chips, RMS / CONTRAST / VOCALS meter
columns, FILL NOW + START ENGINE, colour-override row) and the 400px
preview column (3D PREVIEW header, ENGINE LOG, Input / Window readouts,
collapsed SETUP disclosure).

The engine is STOPPED, so the render is deterministic: dashes in the
meters, a static BPM, an empty log. The reference screen shows a running
engine.

Regenerate after intended changes:

    QLC_REGEN_GOLDENS=1 pytest tests/visual/test_auto_golden.py

Goldens live under goldens/<platform>/ because the offscreen QPA has no
font database on Windows; layout, geometry and colors are what this
pins, not glyph shapes.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from config.models import (
    Configuration, Fixture, FixtureGroup, FixtureMode, Universe,
)
from tests.visual.harness import compare_to_golden


def _stub_visualizer(monkeypatch):
    """Replace the embedded GL preview with an inert widget.

    Constructing AutoTab headlessly otherwise brings up a real
    QOpenGLWidget whose contents are machine-dependent. Same trick as
    tests/unit/test_shows_tab_chrome.py.
    """
    from PyQt6.QtWidgets import QWidget

    class StubVisualizer(QWidget):
        def set_pop_out_callback(self, callback):
            pass

        def set_config(self, config):
            pass

        def set_preview_mode(self, mode):
            pass

        def preview_mode(self):
            return "build"

        def feed_dmx(self, universe, dmx_bytes):
            pass

        def cleanup(self):
            pass

    monkeypatch.setattr("gui.tabs.auto_tab.EmbeddedVisualizer", StubVisualizer)


def _make_fixture(name, group, address, ftype="PAR", channels=8):
    return Fixture(
        universe=1, address=address, manufacturer="TestMfr",
        model="TestModel", name=name, group=group, current_mode="Standard",
        available_modes=[FixtureMode(name="Standard", channels=channels)],
        type=ftype)


@pytest.fixture
def scene_config():
    """Reference-flavoured rig: five colored groups."""
    rows = (
        ("Front Pars", "#D9A441", "PAR", 3),
        ("Rear Wash", "#4ECBD4", "WASH", 2),
        ("Movers", "#C95FD0", "MH", 2),
        ("Pixel Bar", "#6F9E4C", "PIXELBAR", 1),
        ("Sunstrip", "#8D9299", "SUNSTRIP", 1),
    )
    fixtures = []
    groups = {}
    address = 1
    for name, color, ftype, count in rows:
        members = []
        for i in range(count):
            fixture = _make_fixture(f"{name} {i + 1}", name, address, ftype)
            address += 10
            members.append(fixture)
        fixtures.extend(members)
        groups[name] = FixtureGroup(name, members, color=color)
    return Configuration(
        fixtures=fixtures, groups=groups,
        universes={1: Universe(id=1, name="Universe 1", output={})},
        stage_width=8.0, stage_height=6.0,
    )


def test_auto_tab_golden(qapp, monkeypatch, scene_config):
    """Auto tab (reference screen 07), engine stopped."""
    from auto.settings import AutoModeSettings
    from gui.theme_manager import ThemeManager

    # Deterministic settings: never read/write the user's JSON.
    monkeypatch.setattr("auto.settings.load", lambda: AutoModeSettings())
    monkeypatch.setattr("auto.settings.save", lambda _settings: None)
    _stub_visualizer(monkeypatch)
    ThemeManager().apply(qapp, "dark")

    from gui.tabs.auto_tab import AutoTab

    tab = None
    try:
        tab = AutoTab(scene_config, parent=None)
        # Deterministic per-group state matching the reference rows.
        tab._riff_constraints.set_constraint("Rear Wash",
                                             {"pulse", "chase", "static"})
        locked_riff = sorted(tab._riff_constraints._rudiment_names)[0]
        tab._riff_constraints.set_constraint("Movers", {locked_riff})
        tab._refresh_group_rows()
        for group, value in (("Front Pars", 0.8), ("Rear Wash", 1.0),
                             ("Movers", 0.6), ("Pixel Bar", 0.9),
                             ("Sunstrip", 0.7)):
            tab._group_rows[group].set_intensity(value)
        tab._energy_slider.set_value(0.65)
        tab._plane_combo.setCurrentText("Front")
        # Pin the preview/log split: _restore_right_splitter_state reads
        # the user's QSettings, which would make the render machine-local.
        tab._right_splitter.setSizes([250, 600])
        # ...and the Input readout names the machine's real audio device.
        tab._input_value.setText("Focusrite 2i2 · 1 CH")
        tab.setFixedSize(1600, 900)
        compare_to_golden(tab.grab().toImage(), "auto_tab_dark")
    finally:
        if tab is not None:
            tab.cleanup()
            tab.deleteLater()
