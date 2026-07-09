"""LiveTab (North Star screen 09, layout 3b) - the busking palette shell.

A UI shell over an in-memory ``LiveState`` with no DMX/ArtNet output.
These tests pin the state contract and the tile/swatch/fader/control
wiring across the three 3b regions (SELECT + FADE rows, the three-pool
centre grid with a fully-built COLOUR pool and marked POSITION/INTENSITY
placeholders, the right column of playbacks/strobe/kills, and the
submaster bank whose first column is the GRAND master + DBO), plus that
the tab refreshes when the config's groups change. Round 2 adds the dual
queue: the running-playbacks stack (mirroring the single staged
effect/scene, PAUSE/RESUME + KILL per row, a pinned show row in SHOW
mode) and the NEXT UP list (QUEUE latch arms touch-to-enqueue, GO fires
the head) - all state-only, no output engine. They assert role
properties and LiveState, never widget.styleSheet() or font().family()
(per the brand-role convention).
"""

from __future__ import annotations

import os
from unittest.mock import Mock

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from config.models import (
    Configuration, Fixture, FixtureGroup, FixtureMode, Universe,
)


def _fixture(name, group, address, ftype="PAR"):
    return Fixture(
        universe=1, address=address, manufacturer="TestMfr",
        model="TestModel", name=name, group=group, current_mode="Standard",
        available_modes=[FixtureMode(name="Standard", channels=8)],
        type=ftype)


def _config(rows):
    """rows: iterable of (group_name, color, fixture_count)."""
    fixtures = []
    groups = {}
    address = 1
    for name, color, count in rows:
        members = []
        for i in range(count):
            members.append(_fixture(f"{name} {i + 1}", name, address))
            address += 10
        fixtures.extend(members)
        groups[name] = FixtureGroup(name, members, color=color)
    return Configuration(
        fixtures=fixtures, groups=groups,
        universes={1: Universe(id=1, name="Universe 1", output={})},
        stage_width=8.0, stage_height=6.0,
    )


@pytest.fixture
def three_group_config():
    return _config((
        ("Front Pars", "#D9A441", 4),
        ("Rear Wash", "#4ECBD4", 2),
        ("Movers", "#C95FD0", 6),
    ))


@pytest.fixture
def live_tab(qapp, three_group_config):
    from gui.theme_manager import ThemeManager
    from gui.tabs.live_tab import LiveTab

    ThemeManager().apply(qapp, "dark")
    tab = LiveTab(three_group_config, parent=None)
    yield tab
    tab.deleteLater()


class TestSelectTiles:
    def test_one_tile_per_group(self, live_tab, three_group_config):
        assert set(live_tab._select_tiles) == set(three_group_config.groups)

    def test_tile_shows_fixture_count(self, live_tab):
        assert "4" in live_tab._select_tiles["Front Pars"].count_label.text()
        assert "6" in live_tab._select_tiles["Movers"].count_label.text()

    def test_clicking_tile_toggles_selection(self, live_tab):
        tile = live_tab._select_tiles["Movers"]
        tile.clicked.emit("Movers")
        assert "Movers" in live_tab.state.selected
        assert tile.is_selected()
        tile.clicked.emit("Movers")
        assert "Movers" not in live_tab.state.selected
        assert not tile.is_selected()

    def test_multi_select(self, live_tab):
        live_tab._select_tiles["Front Pars"].clicked.emit("Front Pars")
        live_tab._select_tiles["Rear Wash"].clicked.emit("Rear Wash")
        assert live_tab.state.selected == {"Front Pars", "Rear Wash"}

    def test_clear_selection_button(self, live_tab):
        live_tab.state.toggle_group("Front Pars")
        live_tab._clear_sel_btn.click()
        assert live_tab.state.selected == set()

    def test_all_button_selects_every_group(self, live_tab,
                                            three_group_config):
        live_tab._all_btn.click()
        assert live_tab.state.selected == set(three_group_config.groups)

    def test_oddeven_is_placeholder(self, live_tab):
        # Fixture-level odd/even needs the fixture programmer; it is a
        # marked (disabled) placeholder this pass.
        assert live_tab._oddeven_btn.isEnabled() is False


class TestColourPool:
    def test_all_swatches_present(self, live_tab):
        from gui.tabs.live_tab import COLOUR_SWATCHES
        assert set(live_tab._colour_swatches) == {c[0] for c in COLOUR_SWATCHES}

    def test_swatches_are_square(self, live_tab):
        from gui.tabs.live_tab import SWATCH_SIZE
        for swatch in live_tab._colour_swatches.values():
            # Fixed square cell so the pool reads as a grid of squares.
            assert swatch.width() == swatch.height() == SWATCH_SIZE

    def test_touch_applies_colour_to_selection(self, live_tab):
        live_tab.state.toggle_group("Front Pars")
        live_tab.state.toggle_group("Movers")
        live_tab._colour_swatches["red"].clicked.emit("red")
        assert live_tab.state.colours["Front Pars"] == "red"
        assert live_tab.state.colours["Movers"] == "red"
        assert live_tab.state.staged_colour == "red"

    def test_active_swatch_outlined(self, live_tab):
        live_tab.state.toggle_group("Front Pars")
        live_tab._colour_swatches["cyan"].clicked.emit("cyan")
        assert live_tab._colour_swatches["cyan"].is_active()
        assert not live_tab._colour_swatches["red"].is_active()

    def test_mutual_exclusion_newest_wins(self, live_tab):
        live_tab.state.toggle_group("Movers")
        live_tab._colour_swatches["red"].clicked.emit("red")
        live_tab._colour_swatches["cyan"].clicked.emit("cyan")
        # A group holds at most one colour; the newest touch wins.
        assert live_tab.state.colours["Movers"] == "cyan"
        assert live_tab.state.active_colour_ids() == {"cyan"}
        assert live_tab._colour_swatches["cyan"].is_active()
        assert not live_tab._colour_swatches["red"].is_active()

    def test_touch_with_no_selection_records_nothing(self, live_tab):
        live_tab._colour_swatches["amber"].clicked.emit("amber")
        assert live_tab.state.colours == {}
        # Still staged so a future selection/apply can commit it.
        assert live_tab.state.staged_colour == "amber"

    def test_programmer_bar_names_groups_and_colour(self, live_tab):
        live_tab.state.toggle_group("Front Pars")
        live_tab.state.toggle_group("Movers")
        live_tab._colour_swatches["red"].clicked.emit("red")
        text = live_tab._programmer_label.text()
        assert "FRONT PARS" in text
        assert "MOVERS" in text
        assert "RED" in text

    def test_colour_placeholders_marked(self, live_tab):
        assert set(live_tab._colour_placeholders) == {
            "song_palette", "picker", "rec"}
        for cell in live_tab._colour_placeholders.values():
            assert cell.isEnabled() is False


class TestPools:
    def test_three_pools_exist(self, live_tab):
        assert live_tab._colour_pool is not None
        assert live_tab._position_pool is not None
        assert live_tab._intensity_pool is not None

    def test_position_cells_are_disabled_placeholders(self, live_tab):
        assert live_tab._position_cells
        for cell in live_tab._position_cells:
            assert cell.isEnabled() is False
            assert cell.property("placeholder") is True

    def test_intensity_cells_are_disabled_placeholders(self, live_tab):
        assert live_tab._intensity_cells
        for cell in live_tab._intensity_cells:
            assert cell.isEnabled() is False
            assert cell.property("placeholder") is True

    def test_intensity_gates_cell_fx(self, live_tab):
        # At least one intensity cell is gated "NEEDS CELLS".
        subs = [c.sub_label.text() for c in live_tab._intensity_cells
                if c.sub_label is not None]
        assert any("NEEDS CELLS" in text for text in subs)


class TestFade:
    def test_fade_chip_feeds_state(self, live_tab):
        for btn, key, _seconds in live_tab._fade_buttons:
            if key == "4s":
                btn.click()
        assert live_tab.state.fade_key == "4s"
        assert live_tab.state.fade_seconds == 4.0

    def test_default_fade_is_two_seconds(self, live_tab):
        assert live_tab.state.fade_seconds == 2.0
        checked = [k for btn, k, _s in live_tab._fade_buttons if btn.isChecked()]
        assert checked == ["2s"]

    def test_bar_fade_selects_chip_without_seconds(self, live_tab):
        for btn, key, _seconds in live_tab._fade_buttons:
            if key == "1bar":
                btn.click()
        assert live_tab.state.fade_key == "1bar"
        # Bar fades keep the last numeric seconds (no clock yet).
        assert live_tab.state.fade_seconds == 2.0


class TestSubmastersAndMasters:
    def test_submaster_per_group_updates_level(self, live_tab):
        live_tab._submaster_faders["Movers"].value_changed.emit(30)
        assert live_tab.state.submasters["Movers"] == 30

    def test_grandmaster_updates(self, live_tab):
        live_tab._grand_fader.value_changed.emit(60)
        assert live_tab.state.grandmaster == 60

    def test_grand_master_is_first_bank_column(self, live_tab):
        # The GRAND master is the first column of the submaster bank, and
        # its (accent) vertical fader drives the grandmaster.
        first = live_tab._bank_layout.itemAt(0).widget()
        assert first is live_tab._grand_column
        assert live_tab._grand_fader.parentWidget() is live_tab._grand_column
        live_tab._grand_fader.value_changed.emit(42)
        assert live_tab.state.grandmaster == 42

    def test_dbo_lives_in_master_column(self, live_tab):
        # DBO sits under the GRAND fader in the first bank column.
        assert live_tab._dbo_btn.parentWidget() is live_tab._grand_column
        live_tab._dbo_btn.setChecked(True)
        assert live_tab.state.dbo is True
        live_tab._dbo_btn.setChecked(False)
        assert live_tab.state.dbo is False

    def test_submaster_columns_have_bounded_width(self, live_tab):
        from gui.tabs.live_tab import SUBMASTER_COLUMN_WIDTH
        # Few groups must not stretch each fader column to a comical width.
        column = live_tab._submaster_faders["Movers"].parentWidget()
        assert column.maximumWidth() == SUBMASTER_COLUMN_WIDTH
        assert live_tab._grand_column.maximumWidth() == SUBMASTER_COLUMN_WIDTH

    def test_group_level_is_grand_times_submaster(self, live_tab):
        live_tab.state.set_grandmaster(80)
        live_tab.state.set_submaster("Movers", 50)
        assert live_tab.state.group_level("Movers") == pytest.approx(0.4)

    def test_group_level_zero_under_dbo(self, live_tab):
        live_tab.state.set_submaster("Movers", 100)
        live_tab.state.set_dbo(True)
        assert live_tab.state.group_level("Movers") == 0.0

    def test_group_level_zero_under_blackout(self, live_tab):
        live_tab.state.set_blackout(True)
        assert live_tab.state.group_level("Movers") == 0.0

    def test_group_level_full_under_flash(self, live_tab):
        live_tab.state.set_grandmaster(10)
        live_tab.state.set_submaster("Movers", 10)
        live_tab.state.set_flash("Movers", True)
        assert live_tab.state.group_level("Movers") == 1.0

    def test_flash_overrides_blackout_but_dbo_overrides_flash(self, live_tab):
        live_tab.state.set_flash("Movers", True)
        live_tab.state.set_blackout(True)
        assert live_tab.state.group_level("Movers") == 1.0
        live_tab.state.set_dbo(True)
        assert live_tab.state.group_level("Movers") == 0.0

    def test_flash_button_is_momentary(self, live_tab):
        btn = live_tab._flash_buttons["Front Pars"]
        btn.pressed.emit()
        assert "Front Pars" in live_tab.state.flash
        btn.released.emit()
        assert "Front Pars" not in live_tab.state.flash


class TestRightColumnActions:
    def test_hold_look_latches(self, live_tab):
        live_tab._hold_look_btn.setChecked(True)
        assert live_tab.state.held_look is True

    def test_strobe_kill_forces_off(self, live_tab):
        live_tab.state.set_strobe_on(True)
        live_tab._strobe_kill_btn.click()
        assert live_tab.state.strobe_on is False

    def test_strobe_toggle_and_rate_feed_state(self, live_tab):
        live_tab._strobe_btn.setChecked(True)
        assert live_tab.state.strobe_on is True
        live_tab._strobe_slider.value_changed.emit(75)
        assert live_tab.state.strobe_rate == 75

    def test_release_all_clears_programmer(self, live_tab):
        live_tab.state.toggle_group("Front Pars")
        live_tab._colour_swatches["red"].clicked.emit("red")
        assert live_tab.state.colours  # applied
        live_tab._release_all_btn.click()
        assert live_tab.state.colours == {}
        assert live_tab.state.staged_colour is None
        assert live_tab.state.selected == set()
        assert "EMPTY" in live_tab._programmer_label.text()

    def test_release_all_clears_running_and_staged_playbacks(self, live_tab):
        live_tab.state.set_effect("custom/Riff A")
        live_tab.state.set_scene("looks/Warm Wash")
        live_tab.state.enqueue("effect", "custom/Riff B", "Riff B")
        live_tab._release_all_btn.click()
        assert live_tab.state.effect is None
        assert live_tab.state.scene is None
        assert live_tab.state.running == []
        # The preloaded queue is deliberately kept (it is not output).
        assert len(live_tab.state.next_up) == 1


class TestTempoCluster:
    def test_tap_sets_bpm_and_readout(self, live_tab):
        # Deterministic: patch the estimator so a tap yields a fixed BPM
        # (never rely on real tap timing).
        live_tab._tap_bpm.tap = Mock(return_value=140.0)
        live_tab._tap_btn.click()
        live_tab._tap_bpm.tap.assert_called_once()
        assert live_tab.state.bpm == 140.0
        assert "140.0 BPM" in live_tab._bpm_display.text()

    def test_tap_without_enough_taps_leaves_bpm(self, live_tab):
        # tap() returns None until it has 3 taps; the reference must hold.
        before = live_tab.state.bpm
        live_tab._tap_bpm.tap = Mock(return_value=None)
        live_tab._tap_btn.click()
        assert live_tab.state.bpm == before

    def test_reset_clears_tap_history_and_keeps_bpm(self, live_tab):
        live_tab.state.set_bpm(150.0)
        live_tab._tap_bpm.reset = Mock()
        live_tab._tap_reset_btn.click()
        live_tab._tap_bpm.reset.assert_called_once()
        # RESET only clears tap history; the stored reference is kept.
        assert live_tab.state.bpm == 150.0

    def test_set_bpm_clamps_to_range(self, live_tab):
        live_tab.state.set_bpm(9999)
        assert live_tab.state.bpm == 300.0
        live_tab.state.set_bpm(1)
        assert live_tab.state.bpm == 30.0

    def test_tempo_controls_use_output_select_role(self, live_tab):
        assert live_tab._tap_btn.property("role") == "output-select"
        assert live_tab._tap_reset_btn.property("role") == "output-select"


class TestModeToggle:
    def test_defaults_to_live(self, live_tab):
        assert live_tab.state.mode == "live"
        assert live_tab._live_mode_btn.isChecked()
        assert not live_tab._show_mode_btn.isChecked()

    def test_show_button_sets_show_mode(self, live_tab):
        live_tab._show_mode_btn.click()
        assert live_tab.state.mode == "show"
        assert live_tab._show_mode_btn.isChecked()
        assert not live_tab._live_mode_btn.isChecked()

    def test_live_button_returns_to_live_mode(self, live_tab):
        live_tab.state.set_mode("show")
        live_tab._live_mode_btn.click()
        assert live_tab.state.mode == "live"
        assert live_tab._live_mode_btn.isChecked()

    def test_live_mode_active_playbacks_text(self, live_tab):
        live_tab.state.set_mode("live")
        assert live_tab._active_playbacks_label.text() == "NOTHING ELSE RUNNING"
        assert not live_tab._active_playbacks_label.isHidden()
        assert live_tab._pinned_show_label is None

    def test_show_mode_pins_a_show_row(self, live_tab):
        live_tab.state.set_mode("show")
        # The single hint gives way to a pinned, non-killable show row
        # naming the show that would run (no shows configured -> "SHOW").
        assert live_tab._active_playbacks_label.isHidden()
        assert live_tab._pinned_show_label is not None
        assert live_tab._pinned_show_label.text() == "SHOW"
        # Honestly marked: there is no output engine yet.
        marker = live_tab._pinned_show_marker.text()
        assert "SHOW MODE" in marker
        assert "NO ENGINE YET" in marker
        # Pinned = not killable: no KILL button belongs to the show row.
        assert live_tab._kill_buttons == []

    def test_show_mode_pinned_row_names_first_show(self, live_tab):
        live_tab.config.shows = {"Opening Night": object(),
                                 "Encore": object()}
        live_tab.state.set_mode("show")
        assert live_tab._pinned_show_label.text() == "OPENING NIGHT"

    def test_mode_controls_use_output_select_role(self, live_tab):
        assert live_tab._show_mode_btn.property("role") == "output-select"
        assert live_tab._live_mode_btn.property("role") == "output-select"


class TestStateSignal:
    def test_state_changed_emits_on_interactions(self, live_tab):
        hits = []
        live_tab.state.state_changed.connect(lambda: hits.append(1))
        live_tab.state.toggle_group("Movers")
        live_tab.state.stage_colour("red")
        live_tab.state.set_grandmaster(30)
        live_tab.state.set_submaster("Movers", 40)
        live_tab.state.set_flash("Movers", True)
        live_tab.state.set_dbo(True)
        live_tab.state.set_fade("0.5s", 0.5)
        live_tab.state.set_strobe_on(True)
        live_tab.state.set_strobe_rate(20)
        live_tab.state.release_all()
        assert len(hits) == 10

    def test_state_changed_emits_on_tempo_and_mode(self, live_tab):
        hits = []
        live_tab.state.state_changed.connect(lambda: hits.append(1))
        live_tab.state.set_bpm(128)
        live_tab.state.set_mode("show")
        assert len(hits) == 2


class TestUpdateFromConfig:
    def test_refreshes_tiles_when_groups_change(self, live_tab):
        new_config = _config((
            ("Spots", "#5F86C9", 3),
            ("Blinders", "#C96A5F", 2),
        ))
        live_tab.config = new_config
        live_tab.update_from_config()
        assert set(live_tab._select_tiles) == {"Spots", "Blinders"}
        assert set(live_tab._submaster_faders) == {"Spots", "Blinders"}

    def test_seeds_submasters_for_new_groups(self, live_tab):
        new_config = _config((("Spots", "#5F86C9", 1),))
        live_tab.config = new_config
        live_tab.update_from_config()
        assert live_tab.state.submasters == {"Spots": 100}

    def test_stale_state_pruned_on_group_change(self, live_tab):
        live_tab.state.toggle_group("Movers")
        live_tab.state.stage_colour("red")
        live_tab.state.set_submaster("Movers", 40)
        new_config = _config((("Spots", "#5F86C9", 1),))
        live_tab.config = new_config
        live_tab.update_from_config()
        assert "Movers" not in live_tab.state.selected
        assert "Movers" not in live_tab.state.colours
        assert "Movers" not in live_tab.state.submasters

    def test_bpm_and_mode_survive_group_change(self, live_tab):
        live_tab.state.set_bpm(133)
        live_tab.state.set_mode("show")
        new_config = _config((("Spots", "#5F86C9", 1),))
        live_tab.config = new_config
        live_tab.update_from_config()
        assert live_tab.state.bpm == 133.0
        assert live_tab.state.mode == "show"


def _riff_library(tmp_path, riffs):
    """An empty RiffLibrary (no disk scan) populated with the given
    (category, name) riffs directly in .riffs."""
    from riffs.riff_library import RiffLibrary
    from config.models import Riff
    lib = RiffLibrary(riffs_directory=str(tmp_path))
    lib.riffs = {}
    lib.by_category = {}
    for category, name in riffs:
        lib.riffs[f"{category}/{name}"] = Riff(name=name, category=category)
    return lib


def _scene_library(tmp_path, scenes):
    """A SceneLibrary populated with the given Scene objects via add_scene."""
    from scenes.scene_library import SceneLibrary
    from config.models import Scene
    lib = SceneLibrary(scenes_directory=str(tmp_path))
    for name, category, color in scenes:
        lib.add_scene(Scene(name=name, category=category, color=color),
                      category=category)
    return lib


class TestEffectsPool:
    def test_cells_created_per_riff(self, live_tab, tmp_path):
        lib = _riff_library(tmp_path, [("custom", "Riff A"),
                                       ("loops", "Riff B")])
        live_tab.set_effect_library(lib)
        assert set(live_tab._effect_cells) == {"custom/Riff A", "loops/Riff B"}

    def test_click_stages_effect(self, live_tab, tmp_path):
        lib = _riff_library(tmp_path, [("custom", "Riff A")])
        live_tab.set_effect_library(lib)
        live_tab.state.toggle_group("Movers")
        cell = live_tab._effect_cells["custom/Riff A"]
        cell.clicked.emit("custom/Riff A")
        assert live_tab.state.effect == "custom/Riff A"
        assert cell.is_active()

    def test_click_same_cell_toggles_off(self, live_tab, tmp_path):
        lib = _riff_library(tmp_path, [("custom", "Riff A")])
        live_tab.set_effect_library(lib)
        cell = live_tab._effect_cells["custom/Riff A"]
        cell.clicked.emit("custom/Riff A")
        assert live_tab.state.effect == "custom/Riff A"
        cell.clicked.emit("custom/Riff A")
        assert live_tab.state.effect is None
        assert not cell.is_active()

    def test_pool_disabled_without_selection_enabled_with(self, live_tab,
                                                          tmp_path):
        lib = _riff_library(tmp_path, [("custom", "Riff A")])
        live_tab.set_effect_library(lib)
        # Selection empty -> effects are selection-scoped -> pool greyed.
        assert live_tab._effects_pool.isEnabled() is False
        live_tab.state.toggle_group("Movers")
        assert live_tab._effects_pool.isEnabled() is True
        live_tab.state.clear_selection()
        assert live_tab._effects_pool.isEnabled() is False

    def test_empty_library_shows_marked_empty_state(self, live_tab, tmp_path):
        live_tab.set_effect_library(_riff_library(tmp_path, []))
        assert live_tab._effect_cells == {}
        item = live_tab._effects_grid.itemAtPosition(0, 0)
        assert item is not None
        # MicroLabel renders caps; match case-insensitively.
        assert "no effects yet" in item.widget().text().lower()

    def test_cells_carry_card_role(self, live_tab, tmp_path):
        live_tab.set_effect_library(_riff_library(tmp_path,
                                                  [("custom", "Riff A")]))
        cell = live_tab._effect_cells["custom/Riff A"]
        assert cell.property("role") == "card"

    def test_set_effect_emits_state_changed(self, live_tab):
        hits = []
        live_tab.state.state_changed.connect(lambda: hits.append(1))
        live_tab.state.set_effect("custom/Riff A")
        live_tab.state.set_effect("custom/Riff A")  # toggle off
        assert len(hits) == 2
        assert live_tab.state.effect is None

    def test_programmer_bar_shows_effect(self, live_tab, tmp_path):
        live_tab.set_effect_library(_riff_library(tmp_path,
                                                  [("custom", "Riff A")]))
        live_tab.state.toggle_group("Movers")
        live_tab.state.set_effect("custom/Riff A")
        assert "FX: RIFF A" in live_tab._programmer_label.text()


class TestScenesPool:
    def test_cells_created_per_scene(self, live_tab, tmp_path):
        lib = _scene_library(tmp_path, [
            ("Warm Wash", "looks", "#F0562E"),
            ("Cold Snap", "looks", ""),
        ])
        live_tab.set_scene_library(lib)
        assert set(live_tab._scene_cells) == {"looks/Warm Wash",
                                              "looks/Cold Snap"}

    def test_click_stages_scene(self, live_tab, tmp_path):
        live_tab.set_scene_library(_scene_library(
            tmp_path, [("Warm Wash", "looks", "#F0562E")]))
        cell = live_tab._scene_cells["looks/Warm Wash"]
        cell.clicked.emit("looks/Warm Wash")
        assert live_tab.state.scene == "looks/Warm Wash"
        assert cell.is_active()

    def test_click_same_cell_toggles_off(self, live_tab, tmp_path):
        live_tab.set_scene_library(_scene_library(
            tmp_path, [("Warm Wash", "looks", "")]))
        cell = live_tab._scene_cells["looks/Warm Wash"]
        cell.clicked.emit("looks/Warm Wash")
        assert live_tab.state.scene == "looks/Warm Wash"
        cell.clicked.emit("looks/Warm Wash")
        assert live_tab.state.scene is None

    def test_pool_always_enabled_regardless_of_selection(self, live_tab,
                                                         tmp_path):
        live_tab.set_scene_library(_scene_library(
            tmp_path, [("Warm Wash", "looks", "")]))
        # No selection: scenes are whole-rig, so the pool stays enabled.
        assert live_tab.state.selected == set()
        assert live_tab._scenes_pool.isEnabled() is True
        live_tab.state.toggle_group("Movers")
        assert live_tab._scenes_pool.isEnabled() is True

    def test_empty_library_shows_marked_empty_state(self, live_tab, tmp_path):
        live_tab.set_scene_library(_scene_library(tmp_path, []))
        assert live_tab._scene_cells == {}
        item = live_tab._scenes_grid.itemAtPosition(0, 0)
        assert item is not None
        # MicroLabel renders caps; match case-insensitively.
        assert "no scenes yet" in item.widget().text().lower()

    def test_cells_carry_card_role(self, live_tab, tmp_path):
        live_tab.set_scene_library(_scene_library(
            tmp_path, [("Warm Wash", "looks", "#F0562E")]))
        cell = live_tab._scene_cells["looks/Warm Wash"]
        assert cell.property("role") == "card"

    def test_set_scene_emits_state_changed(self, live_tab):
        hits = []
        live_tab.state.state_changed.connect(lambda: hits.append(1))
        live_tab.state.set_scene("looks/Warm Wash")
        live_tab.state.set_scene("looks/Warm Wash")  # toggle off
        assert len(hits) == 2
        assert live_tab.state.scene is None

    def test_programmer_bar_shows_scene(self, live_tab, tmp_path):
        live_tab.set_scene_library(_scene_library(
            tmp_path, [("Warm Wash", "looks", "")]))
        live_tab.state.set_scene("looks/Warm Wash")
        assert "SCENE: WARM WASH" in live_tab._programmer_label.text()


class TestLibraryStatePreserved:
    def test_effect_and_scene_survive_group_change(self, live_tab):
        live_tab.state.set_effect("custom/Riff A")
        live_tab.state.set_scene("looks/Warm Wash")
        new_config = _config((("Spots", "#5F86C9", 1),))
        live_tab.config = new_config
        live_tab.update_from_config()
        assert live_tab.state.effect == "custom/Riff A"
        assert live_tab.state.scene == "looks/Warm Wash"

    def test_running_and_next_up_survive_group_change(self, live_tab):
        live_tab.state.set_effect("custom/Riff A")
        live_tab.state.enqueue("scene", "looks/Warm Wash", "Warm Wash")
        new_config = _config((("Spots", "#5F86C9", 1),))
        live_tab.config = new_config
        live_tab.update_from_config()
        assert [r["key"] for r in live_tab.state.running] == ["custom/Riff A"]
        assert [r["key"] for r in live_tab.state.next_up] == \
            ["looks/Warm Wash"]


class TestRunningStack:
    def test_set_effect_creates_running_record(self, live_tab):
        live_tab.state.set_effect("custom/Riff A")
        assert live_tab.state.running == [{
            "kind": "effect", "key": "custom/Riff A",
            "label": "Riff A", "paused": False}]

    def test_toggle_off_removes_record(self, live_tab):
        live_tab.state.set_effect("custom/Riff A")
        live_tab.state.set_effect("custom/Riff A")
        assert live_tab.state.running == []

    def test_replacing_effect_swaps_record(self, live_tab):
        live_tab.state.set_effect("custom/Riff A")
        live_tab.state.set_effect("loops/Riff B")
        # At most one kind=="effect" record; the newest key wins.
        assert [r["key"] for r in live_tab.state.running] == ["loops/Riff B"]

    def test_scene_record_parallel_to_effect(self, live_tab):
        live_tab.state.set_scene("looks/Warm Wash")
        assert live_tab.state.running == [{
            "kind": "scene", "key": "looks/Warm Wash",
            "label": "Warm Wash", "paused": False}]
        live_tab.state.set_scene("looks/Cold Snap")
        assert [r["key"] for r in live_tab.state.running] == \
            ["looks/Cold Snap"]
        live_tab.state.set_scene("looks/Cold Snap")
        assert live_tab.state.running == []

    def test_at_most_one_record_per_kind(self, live_tab):
        live_tab.state.set_effect("custom/Riff A")
        live_tab.state.set_scene("looks/Warm Wash")
        live_tab.state.set_effect("loops/Riff B")
        live_tab.state.set_scene("looks/Cold Snap")
        kinds = [r["kind"] for r in live_tab.state.running]
        assert sorted(kinds) == ["effect", "scene"]

    def test_running_records_render_rows_with_buttons(self, live_tab):
        live_tab.state.set_effect("custom/Riff A")
        live_tab.state.set_scene("looks/Warm Wash")
        assert len(live_tab._pause_buttons) == 2
        assert len(live_tab._kill_buttons) == 2
        assert live_tab._active_playbacks_label.isHidden()
        for btn in live_tab._kill_buttons:
            assert btn.property("role") == "destructive"

    def test_kill_removes_record_and_clears_effect(self, live_tab):
        live_tab.state.set_effect("custom/Riff A")
        live_tab._kill_buttons[0].click()
        assert live_tab.state.running == []
        assert live_tab.state.effect is None

    def test_kill_scene_record_clears_scene(self, live_tab):
        live_tab.state.set_effect("custom/Riff A")
        live_tab.state.set_scene("looks/Warm Wash")
        # Kill the scene row (index 1); the effect keeps running.
        live_tab.state.kill_playback(1)
        assert live_tab.state.scene is None
        assert live_tab.state.effect == "custom/Riff A"
        assert [r["kind"] for r in live_tab.state.running] == ["effect"]

    def test_toggle_pause_flips_flag_and_row_shows_resume(self, live_tab):
        live_tab.state.set_effect("custom/Riff A")
        assert live_tab._pause_buttons[0].text() == "PAUSE"
        live_tab._pause_buttons[0].click()
        assert live_tab.state.running[0]["paused"] is True
        assert live_tab._pause_buttons[0].text() == "RESUME"
        live_tab._pause_buttons[0].click()
        assert live_tab.state.running[0]["paused"] is False
        assert live_tab._pause_buttons[0].text() == "PAUSE"


class TestQueue:
    def test_enqueue_appends_and_allows_repeats(self, live_tab):
        live_tab.state.enqueue("effect", "custom/Riff A", "Riff A")
        live_tab.state.enqueue("effect", "custom/Riff A", "Riff A")
        live_tab.state.enqueue("scene", "looks/Warm Wash", "Warm Wash")
        assert [r["key"] for r in live_tab.state.next_up] == [
            "custom/Riff A", "custom/Riff A", "looks/Warm Wash"]
        # Enqueueing never touches the live staged state.
        assert live_tab.state.effect is None
        assert live_tab.state.scene is None

    def test_fire_next_pops_head_and_applies_effect(self, live_tab):
        live_tab.state.enqueue("effect", "custom/Riff A", "Riff A")
        live_tab.state.enqueue("scene", "looks/Warm Wash", "Warm Wash")
        live_tab.state.fire_next()
        assert live_tab.state.effect == "custom/Riff A"
        assert [r["key"] for r in live_tab.state.running] == ["custom/Riff A"]
        assert [r["key"] for r in live_tab.state.next_up] == \
            ["looks/Warm Wash"]
        live_tab.state.fire_next()
        assert live_tab.state.scene == "looks/Warm Wash"
        assert live_tab.state.next_up == []

    def test_fire_next_never_toggles_a_running_key_off(self, live_tab):
        live_tab.state.set_effect("custom/Riff A")
        live_tab.state.enqueue("effect", "custom/Riff A", "Riff A")
        live_tab.state.fire_next()
        # GO applies; firing the already-running key keeps it running.
        assert live_tab.state.effect == "custom/Riff A"
        assert [r["key"] for r in live_tab.state.running] == ["custom/Riff A"]
        assert live_tab.state.next_up == []

    def test_fire_next_on_empty_queue_is_a_noop(self, live_tab):
        hits = []
        live_tab.state.state_changed.connect(lambda: hits.append(1))
        live_tab.state.fire_next()
        assert hits == []
        assert live_tab.state.effect is None

    def test_remove_queued_drops_by_index(self, live_tab):
        live_tab.state.enqueue("effect", "custom/Riff A", "Riff A")
        live_tab.state.enqueue("scene", "looks/Warm Wash", "Warm Wash")
        live_tab.state.remove_queued(0)
        assert [r["key"] for r in live_tab.state.next_up] == \
            ["looks/Warm Wash"]

    def test_queued_row_remove_button(self, live_tab):
        live_tab.state.enqueue("effect", "custom/Riff A", "Riff A")
        assert len(live_tab._queue_remove_buttons) == 1
        live_tab._queue_remove_buttons[0].click()
        assert live_tab.state.next_up == []

    def test_go_disabled_when_empty_enabled_when_not(self, live_tab):
        assert live_tab._go_btn.isEnabled() is False
        assert not live_tab._queue_empty_hint.isHidden()
        live_tab.state.enqueue("effect", "custom/Riff A", "Riff A")
        assert live_tab._go_btn.isEnabled() is True
        assert live_tab._queue_empty_hint.isHidden()

    def test_go_button_fires_next(self, live_tab):
        live_tab.state.enqueue("effect", "custom/Riff A", "Riff A")
        live_tab._go_btn.click()
        assert live_tab.state.effect == "custom/Riff A"
        assert live_tab.state.next_up == []
        assert live_tab._go_btn.isEnabled() is False

    def test_go_uses_cta_accent_role(self, live_tab):
        assert live_tab._go_btn.property("role") == "cta-accent"
        assert live_tab._queue_latch_btn.property("role") == "output-select"

    def test_latched_touch_enqueues_effect_without_firing(self, live_tab,
                                                          tmp_path):
        live_tab.set_effect_library(_riff_library(tmp_path,
                                                  [("custom", "Riff A")]))
        live_tab.state.toggle_group("Movers")
        live_tab._queue_latch_btn.setChecked(True)
        cell = live_tab._effect_cells["custom/Riff A"]
        cell.clicked.emit("custom/Riff A")
        assert live_tab.state.next_up == [{
            "kind": "effect", "key": "custom/Riff A", "label": "Riff A"}]
        # The cell did NOT fire live: no staged effect, cell not active.
        assert live_tab.state.effect is None
        assert not cell.is_active()

    def test_latched_touch_enqueues_scene(self, live_tab, tmp_path):
        live_tab.set_scene_library(_scene_library(
            tmp_path, [("Warm Wash", "looks", "")]))
        live_tab._queue_latch_btn.setChecked(True)
        live_tab._scene_cells["looks/Warm Wash"].clicked.emit(
            "looks/Warm Wash")
        assert live_tab.state.next_up == [{
            "kind": "scene", "key": "looks/Warm Wash",
            "label": "Warm Wash"}]
        assert live_tab.state.scene is None

    def test_unlatched_touch_fires_live(self, live_tab, tmp_path):
        live_tab.set_effect_library(_riff_library(tmp_path,
                                                  [("custom", "Riff A")]))
        live_tab.state.toggle_group("Movers")
        assert live_tab._queue_latch_btn.isChecked() is False
        live_tab._effect_cells["custom/Riff A"].clicked.emit("custom/Riff A")
        assert live_tab.state.effect == "custom/Riff A"
        assert live_tab.state.next_up == []

    def test_state_changed_emitted_by_queue_mutators(self, live_tab):
        hits = []
        live_tab.state.state_changed.connect(lambda: hits.append(1))
        live_tab.state.enqueue("effect", "custom/Riff A", "Riff A")
        live_tab.state.fire_next()
        live_tab.state.toggle_pause(0)
        live_tab.state.kill_playback(0)
        live_tab.state.enqueue("scene", "looks/Warm Wash", "Warm Wash")
        live_tab.state.remove_queued(0)
        assert len(hits) == 6


class TestRoles:
    def test_actions_use_theme_roles(self, live_tab):
        assert live_tab._dbo_btn.property("role") == "destructive"
        assert live_tab._strobe_btn.property("role") == "output-select"
        assert live_tab._release_all_btn.property("role") == "cta-outline"
        assert live_tab._active_playbacks_label.property("role") == "hint-box"

    def test_theme_defines_used_roles(self):
        from gui.theme_tokens import render_theme
        qss = render_theme("dark")
        assert 'QPushButton[role="destructive"]' in qss
        assert 'QPushButton[role="output-select"]' in qss
        assert 'QPushButton[role="cta-outline"]' in qss
        assert 'QLabel[role="hint-box"]' in qss
