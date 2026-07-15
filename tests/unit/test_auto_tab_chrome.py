"""Auto tab chrome, rebuilt to the reference screen
docs/design/screens/07-auto.html.

Covers the parts of the anatomy that carry behaviour:

- the GROUPS · MODE rows (group-color left border, AUTO / CURATED /
  LOCKED chips writing through the backing GroupRiffConstraintPanel, the
  120x8 intensity bar writing through the backing GroupSubmasterPanel),
- ENERGY SENSITIVITY and PLANE BIAS driving the existing engine settings,
- the BPM readout + TAP / SET... / BPM AUTO chips,
- the RMS / CONTRAST / VOCALS meter columns and their stopped state,
- the colour-override row (swatches, RELEASE) round-tripping the
  HSVColorWheel,
- the UI-side engine log (bounded, accent for riff changes),
- the 3D-preview header (pop-out + collapse chevron).

Font families are never asserted (polish-order race); QSS is checked
through gui.theme_tokens.render_theme instead.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(autouse=True)
def _no_settings_persistence(monkeypatch):
    """Isolate from ``~/.qlcautoshow/auto_mode_settings.json`` in both
    directions (a stale file changes defaults; tests must not persist)."""
    from auto.settings import AutoModeSettings
    monkeypatch.setattr("auto.settings.load", lambda: AutoModeSettings())
    monkeypatch.setattr("auto.settings.save", lambda _settings: None)


def _make_config():
    from config.models import (Configuration, Fixture, FixtureGroup,
                               FixtureMode, Universe)

    def fixture(name, group, address, ftype="PAR"):
        return Fixture(
            universe=1, address=address, manufacturer="TestMfr",
            model="TestModel", name=name, group=group, current_mode="m",
            available_modes=[FixtureMode(name="m", channels=4)], type=ftype)

    pars = [fixture("PAR 1", "Front Pars", 1), fixture("PAR 2", "Front Pars", 5)]
    wash = [fixture("WASH 1", "Rear Wash", 9, "WASH")]
    movers = [fixture("MH 1", "Movers", 17, "MH")]
    return Configuration(
        fixtures=pars + wash + movers,
        groups={
            "Front Pars": FixtureGroup("Front Pars", pars, color="#D9A441"),
            "Rear Wash": FixtureGroup("Rear Wash", wash, color="#4ECBD4"),
            "Movers": FixtureGroup("Movers", movers, color="#C95FD0"),
        },
        universes={1: Universe(id=1, name="U1", output={})},
    )


@pytest.fixture
def auto_tab(qapp):
    from PyQt6.QtWidgets import QApplication
    from gui.theme_manager import ThemeManager
    from gui.tabs.auto_tab import AutoTab

    ThemeManager().apply(qapp, "dark")
    tab = AutoTab(_make_config(), parent=None)
    try:
        yield tab
    finally:
        tab.cleanup()
        tab.deleteLater()
        QApplication.processEvents()


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

class TestHelpers:
    def test_riff_display_text(self):
        from gui.tabs.auto_tab import riff_display_text
        assert riff_display_text("pulse", False) == "pulse"
        assert riff_display_text("pulse", True) == "pulse (locked)"
        assert riff_display_text(None, True) == "-"
        assert riff_display_text("pulse", False, "▸") == "▸ pulse"

    def test_constraint_mode(self):
        from gui.tabs.auto_tab import constraint_mode
        assert constraint_mode(None) == "AUTO"
        assert constraint_mode(set()) == "AUTO"
        assert constraint_mode({"pulse"}) == "LOCKED"
        assert constraint_mode({"pulse", "chase"}) == "CURATED"

    def test_metric_words(self):
        from gui.tabs.auto_tab import contrast_word, vocal_word
        assert contrast_word(0.6) == "RICH"
        assert contrast_word(0.2) == "FLAT"
        assert vocal_word(0.97) == "PRESENT"
        assert vocal_word(0.1) == "ABSENT"


# ---------------------------------------------------------------------------
# Left panel: GROUPS · MODE
# ---------------------------------------------------------------------------

class TestGroupRows:
    def test_one_row_per_group_with_color_border(self, auto_tab):
        from gui.tabs.auto_tab import INTENSITY_BAR_SIZE
        assert list(auto_tab._group_rows) == ["Front Pars", "Rear Wash",
                                              "Movers"]
        row = auto_tab._group_rows["Front Pars"]
        assert "#d9a441" in row.styleSheet().lower()
        assert "border-left: 3px solid" in row.styleSheet()
        assert row.name_label.text() == "FRONT PARS"
        assert row.name_label.width() == 150 or row.name_label.minimumWidth() == 150
        assert sorted(row.mode_buttons) == ["AUTO", "CURATED", "LOCKED"]
        assert (row.intensity_bar.width(),
                row.intensity_bar.height()) == INTENSITY_BAR_SIZE
        assert row.percent_label.text() == "100%"

    def test_rows_rebuild_when_groups_change(self, qapp):
        from PyQt6.QtWidgets import QApplication
        from config.models import Configuration
        from gui.tabs.auto_tab import AutoTab

        tab = AutoTab(Configuration(), parent=None)
        try:
            assert tab._group_rows == {}
            tab.config = _make_config()
            tab.update_from_config()
            QApplication.processEvents()
            assert len(tab._group_rows) == 3
            # Backing panels follow.
            assert list(tab._submasters._sliders) == list(tab._group_rows)
        finally:
            tab.cleanup()
            tab.deleteLater()

    def test_auto_chip_clears_constraint_and_fills_accent(self, auto_tab):
        """Chip fills are theme-owned (QPushButton[role="mode-chip"]);
        the tab only drives the checked state + the locked variant.
        Asserting widget styleSheet() would pin the wrong contract."""
        from gui.theme_tokens import THEMES, render_theme

        panel = auto_tab._riff_constraints
        panel.set_constraint("Movers", {"pulse"})
        auto_tab._refresh_group_rows()
        row = auto_tab._group_rows["Movers"]

        # LOCKED is the active chip and carries the locked variant.
        locked = row.mode_buttons["LOCKED"]
        assert locked.isChecked()
        assert locked.property("state") == "locked"
        qss = render_theme("dark")
        locked_rule = qss.split(
            'QPushButton[role="mode-chip"][state="locked"]:checked {',
            1)[1].split("}", 1)[0]
        assert THEMES["dark"]["text"] in locked_rule  # warm-white fill

        row.mode_buttons["AUTO"].click()
        assert "Movers" not in panel.get_constraints()
        assert row.mode_buttons["AUTO"].isChecked()
        assert not row.mode_buttons["LOCKED"].isChecked()
        checked_rule = qss.split(
            'QPushButton[role="mode-chip"]:checked,', 1)[1].split("}", 1)[0]
        assert THEMES["dark"]["accent"] in checked_rule

    def test_lock_sets_constraint_and_labels_the_riff(self, auto_tab):
        auto_tab._lock_group_to("Rear Wash", "pulse")
        assert auto_tab._riff_constraints.get_constraints()["Rear Wash"] == {"pulse"}
        row = auto_tab._group_rows["Rear Wash"]
        assert "LOCKED" in row.riff_label.text()
        assert "PULSE" in row.riff_label.text()

    def test_constraint_change_reaches_the_engine(self, auto_tab):
        from unittest.mock import MagicMock
        auto_tab._engine = MagicMock()
        auto_tab._lock_group_to("Movers", "chase")
        auto_tab._engine.set_group_constraints.assert_called_with(
            "Movers", {"chase"})

    def test_intensity_bar_drives_submaster_and_engine(self, auto_tab):
        from unittest.mock import MagicMock
        auto_tab._engine = MagicMock()
        row = auto_tab._group_rows["Front Pars"]
        row.intensity_bar.set_fraction(0.6)
        auto_tab._on_intensity_bar("Front Pars", 0.6)
        assert auto_tab._submasters.get_values()["Front Pars"] == 60
        assert row.percent_label.text() == "60%"
        auto_tab._engine.set_group_submaster.assert_called_with("Front Pars", 0.6)

    def test_engine_riffs_land_on_the_rows(self, auto_tab):
        auto_tab._apply_active_riffs({"Front Pars": "pulse"})
        assert "PULSE" in auto_tab._group_rows["Front Pars"].riff_label.text()


class TestEnergyAndPlaneBias:
    def test_energy_slider_writes_fader_and_engine(self, auto_tab):
        from unittest.mock import MagicMock
        auto_tab._engine = MagicMock()
        auto_tab._energy_slider.set_value(0.4)
        auto_tab._on_energy_slider_moved(0.4)
        assert auto_tab._energy_fader.value() == pytest.approx(0.4, abs=0.01)
        auto_tab._engine.set_energy_sensitivity.assert_called_with(0.4)
        # And it round-trips through the settings dataclass.
        auto_tab._save_settings()
        assert auto_tab._settings.energy_sensitivity == 40

    def test_plane_chips_select_front_mid_back(self, auto_tab):
        from unittest.mock import MagicMock
        from gui.tabs.auto_tab import PLANE_NONE
        auto_tab._engine = MagicMock()

        auto_tab._plane_chips["Back"].click()
        assert auto_tab._plane_combo.currentText() == "Back"
        assert auto_tab._engine.set_target_plane.call_args.args[0].name == "Back"

        # MID is the no-plane case: the engine has no mid plane.
        auto_tab._plane_chips[PLANE_NONE].click()
        assert auto_tab._plane_combo.currentText() == PLANE_NONE
        assert auto_tab._engine.set_target_plane.call_args.args[0] is None

    def test_plane_chip_highlight_follows_the_combo(self, auto_tab):
        """The accent fill is theme-owned (bias-chip:checked); the tab
        drives which chip is checked."""
        from gui.theme_tokens import THEMES, render_theme

        auto_tab._plane_combo.setCurrentText("Front")
        assert auto_tab._plane_chips["Front"].isChecked()
        assert not auto_tab._plane_chips["Back"].isChecked()

        # A plane the chips don't cover lights none of them.
        auto_tab._plane_combo.setCurrentText("Ceiling")
        assert not any(chip.isChecked()
                       for chip in auto_tab._plane_chips.values())

        rule = render_theme("dark").split(
            'QPushButton[role="bias-chip"]:checked {', 1)[1].split("}", 1)[0]
        assert THEMES["dark"]["accent"] in rule


# ---------------------------------------------------------------------------
# Centre: BPM, meters, actions, colour override
# ---------------------------------------------------------------------------

class TestBpmRow:
    def test_readout_has_one_decimal_and_follows_the_spinbox(self, auto_tab):
        auto_tab._bpm_spinbox.setValue(128)
        assert auto_tab._bpm_display.text() == "128.0"

    def test_tap_updates_spinbox_display_and_log(self, auto_tab):
        from unittest.mock import MagicMock
        auto_tab._tap_bpm.tap = MagicMock(return_value=124.6)
        auto_tab._tap_btn.click()
        assert auto_tab._bpm_spinbox.value() == 125
        assert auto_tab._bpm_display.text() == "124.6"
        assert any("Tap tempo" in msg
                   for _s, msg, _a in auto_tab.engine_log_entries())

    def test_set_chip_opens_manual_entry(self, auto_tab, monkeypatch):
        monkeypatch.setattr(
            "gui.tabs.auto_tab.QInputDialog.getInt",
            staticmethod(lambda *a, **k: (96, True)))
        auto_tab._bpm_set_btn.click()
        assert auto_tab._bpm_spinbox.value() == 96
        assert auto_tab._bpm_display.text() == "96.0"

    def test_bpm_auto_chip_disables_manual_controls(self, auto_tab):
        auto_tab._auto_bpm_checkbox.setChecked(True)
        assert not auto_tab._tap_btn.isEnabled()
        assert not auto_tab._bpm_spinbox.isEnabled()
        assert not auto_tab._bpm_set_btn.isEnabled()
        auto_tab._auto_bpm_checkbox.setChecked(False)
        assert auto_tab._tap_btn.isEnabled()

    def test_chip_roles(self, auto_tab):
        assert auto_tab._tap_btn.property("role") == "primary"
        assert auto_tab._auto_bpm_checkbox.property("role") == "output-select"
        assert auto_tab._bpm_set_btn.property("role") == "output-select"


class TestMeterColumns:
    def test_stopped_shows_dashes_and_empty_bars(self, auto_tab):
        for key in ("rms", "contrast", "vocal"):
            assert auto_tab._meter_values[key].text() == "-"
            assert auto_tab._meter_bars[key].fraction() is None

    def test_bar_geometry_matches_the_reference(self, auto_tab):
        from gui.tabs.auto_tab import METER_BAR_SIZE
        for bar in auto_tab._meter_bars.values():
            assert (bar.width(), bar.height()) == METER_BAR_SIZE

    def test_live_frame_fills_the_meters(self, auto_tab):
        from audio.realtime_spectral import LiveFeatureFrame
        auto_tab._latest_frame = LiveFeatureFrame(
            timestamp=0.0, flux=0.5, transient=0.4, richness=0.6,
            vocal=0.88, centroid=0.3, rms=0.74, contrast=0.60)
        auto_tab._update_ui()
        assert auto_tab._meter_values["rms"].text() == "0.74"
        assert auto_tab._meter_values["contrast"].text() == "0.60 RICH"
        assert auto_tab._meter_values["vocal"].text() == "PRESENT"
        assert auto_tab._meter_bars["rms"].fraction() == pytest.approx(0.74)

        auto_tab._clear_meters()
        assert auto_tab._meter_values["rms"].text() == "-"


class TestActionRow:
    def test_fill_and_engine_toggle(self, auto_tab):
        assert auto_tab._fill_btn.property("role") == "cta-accent"
        assert auto_tab._fill_btn.text() == "FILL NOW"
        # Stopped: START visible, STOP hidden + disabled.
        assert auto_tab._start_btn.isEnabled()
        assert not auto_tab._stop_btn.isEnabled()
        assert auto_tab._stop_btn.isHidden()
        assert auto_tab._start_btn.text() == "START ENGINE"
        assert auto_tab._stop_btn.text() == "STOP ENGINE"

    def test_fill_now_calls_the_engine_and_logs(self, auto_tab):
        from unittest.mock import MagicMock
        auto_tab._engine = MagicMock()
        auto_tab._fill_btn.click()
        auto_tab._engine.force_fill.assert_called_once()
        assert auto_tab.engine_log_entries()[-1][1] == "Fill bar"


class TestColourOverride:
    def test_swatch_activates_override_and_marks_selection(self, auto_tab):
        from unittest.mock import MagicMock
        from gui.tabs.auto_tab import COLOR_PRESETS, SWATCH_SIZE
        auto_tab._engine = MagicMock()
        for swatch in auto_tab._swatches:
            assert (swatch.width(), swatch.height()) == (SWATCH_SIZE,
                                                         SWATCH_SIZE)
        auto_tab._on_swatch_clicked(COLOR_PRESETS[1])
        assert auto_tab._color_wheel.is_override_active()
        assert auto_tab._engine.set_color_override.call_args.args[0] is not None
        selected = [s.color() for s in auto_tab._swatches if s.is_selected()]
        assert selected == [COLOR_PRESETS[1]]

    def test_release_clears_the_override(self, auto_tab):
        from unittest.mock import MagicMock
        from gui.tabs.auto_tab import COLOR_PRESETS
        auto_tab._on_swatch_clicked(COLOR_PRESETS[0])
        auto_tab._engine = MagicMock()
        auto_tab._release_color_btn.click()
        assert not auto_tab._color_wheel.is_override_active()
        auto_tab._engine.set_color_override.assert_called_with(None)
        assert not any(s.is_selected() for s in auto_tab._swatches)

    def test_wheel_button_opens_the_hsv_wheel(self, auto_tab):
        assert auto_tab._color_wheel_dialog is None
        auto_tab._open_color_wheel()
        try:
            assert auto_tab._color_wheel_dialog is not None
            assert auto_tab._color_wheel.parent() is not None
        finally:
            auto_tab._color_wheel_dialog.close()


# ---------------------------------------------------------------------------
# Right panel: preview header, engine log, readouts
# ---------------------------------------------------------------------------

class TestPreviewHeader:
    def test_chevron_is_icon_only_and_toggles_the_preview(self, qapp, auto_tab):
        auto_tab.resize(1400, 800)
        auto_tab.show()
        for _ in range(3):
            qapp.processEvents()
        try:
            assert auto_tab._pane_toggle_btn.text() == ""
            assert not auto_tab._pane_toggle_btn.icon().isNull()
            assert auto_tab._right_splitter.sizes()[0] > 0

            auto_tab._pane_toggle_btn.setChecked(False)
            assert auto_tab._right_splitter.sizes()[0] == 0
            auto_tab._pane_toggle_btn.setChecked(True)
            assert auto_tab._right_splitter.sizes()[0] > 0
        finally:
            auto_tab.hide()

    def test_pop_out_button_delegates_to_the_launcher(self, auto_tab,
                                                      monkeypatch):
        calls = []
        monkeypatch.setattr(auto_tab, "_launch_visualizer",
                            lambda: calls.append(1))
        auto_tab._pop_out_btn.clicked.disconnect()
        auto_tab._pop_out_btn.clicked.connect(auto_tab._launch_visualizer)
        auto_tab._pop_out_btn.click()
        assert calls == [1]


class TestEngineLog:
    def test_bounded_and_newest_last(self, auto_tab):
        from gui.tabs.auto_tab import ENGINE_LOG_CAPACITY
        for i in range(ENGINE_LOG_CAPACITY + 10):
            auto_tab._log_event(f"event {i}")
        entries = auto_tab.engine_log_entries()
        assert len(entries) == ENGINE_LOG_CAPACITY
        assert entries[-1][1] == f"event {ENGINE_LOG_CAPACITY + 9}"

    def test_riff_changes_are_accented(self, auto_tab):
        auto_tab._apply_active_riffs({"Movers": "pulse"})
        auto_tab._apply_active_riffs({"Movers": "chase"})
        stamp, message, accent = auto_tab.engine_log_entries()[-1]
        assert message == "Movers: pulse -> chase"
        assert accent is True
        assert len(stamp.split(":")) == 3

    def test_same_riff_is_not_logged_twice(self, auto_tab):
        auto_tab._apply_active_riffs({"Movers": "pulse"})
        before = len(auto_tab.engine_log_entries())
        auto_tab._apply_active_riffs({"Movers": "pulse"})
        assert len(auto_tab.engine_log_entries()) == before

    def test_colour_override_events_are_logged(self, auto_tab):
        from gui.tabs.auto_tab import COLOR_PRESETS
        auto_tab._on_swatch_clicked(COLOR_PRESETS[0])
        assert "Colour override" in auto_tab.engine_log_entries()[-1][1]
        auto_tab._on_release_color()
        assert auto_tab.engine_log_entries()[-1][1] == "Colour override released"


class TestReadouts:
    def test_window_row_shows_the_engine_analysis_window(self, auto_tab):
        from auto.engine import _WINDOW_SECONDS
        assert auto_tab._window_value.text() == f"{float(_WINDOW_SECONDS):.1f} s"

    def test_input_row_names_device_and_channels(self, auto_tab):
        text = auto_tab._input_value.text()
        assert " CH" in text
        assert "·" in text

    def test_no_latency_row(self, auto_tab):
        # audio/ exposes no input latency; the reference row is omitted.
        assert not hasattr(auto_tab, "_latency_value")


class TestSetupDisclosure:
    def test_setup_area_hidden_by_default_and_keeps_the_plumbing(self, auto_tab):
        assert not auto_tab._setup_toggle_btn.isChecked()
        assert auto_tab._setup_area.isHidden()
        for name in ("_ip_input", "_universe_table", "_mirror_checkbox",
                     "_input_api_combo", "_input_device_combo",
                     "_refresh_devices_btn", "_asio_hint_label",
                     "_plane_combo", "_speed_slider", "_bpm_spinbox"):
            assert getattr(auto_tab, name, None) is not None, name
        auto_tab._setup_toggle_btn.setChecked(True)
        assert not auto_tab._setup_area.isHidden()


# ---------------------------------------------------------------------------
# Theme contract (never assert font().family() - polish-order race)
# ---------------------------------------------------------------------------

class TestThemeContract:
    @pytest.mark.parametrize("theme", ["dark", "light"])
    def test_roles_the_tab_relies_on_exist(self, theme):
        from gui.theme_tokens import render_theme
        qss = render_theme(theme)
        for rule in ('QPushButton[role="primary"]',
                     'QPushButton[role="output-select"]',
                     'QWidget[role="inspector"]',
                     'QLabel[role="micro"]',
                     '#GroupRow',
                     'QLabel#AutoStatusPhase[phase="stopped"]',
                     'QLabel#AutoBpmDisplay'):
            assert rule in qss, rule
