"""LiveTab (North Star screen 09, layout 3b) - the busking palette shell.

First pass: a UI shell over an in-memory ``LiveState`` with no DMX/ArtNet
output. These tests pin the state contract and the tile/cell/control
wiring, plus that the tab refreshes its SELECT tiles when the config's
groups change. They assert role properties and LiveState, never
widget.styleSheet() or font().family() (per the brand-role convention).
"""

from __future__ import annotations

import os

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
        # Front Pars has 4 fixtures, Movers 6.
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


class TestPaletteCells:
    def test_cells_present(self, live_tab):
        from gui.tabs.live_tab import PALETTE_CELLS
        assert set(live_tab._palette_cells) == {k for k, _ in PALETTE_CELLS}

    def test_touch_records_palette_for_selection(self, live_tab):
        live_tab.state.toggle_group("Front Pars")
        live_tab.state.toggle_group("Movers")
        live_tab._palette_cells["strobe"].clicked.emit("strobe")
        assert live_tab.state.group_palettes["Front Pars"] == "strobe"
        assert live_tab.state.group_palettes["Movers"] == "strobe"
        assert live_tab.state.staged_palette == "strobe"

    def test_touched_cell_highlights(self, live_tab):
        live_tab.state.toggle_group("Front Pars")
        live_tab._palette_cells["circle"].clicked.emit("circle")
        assert live_tab._palette_cells["circle"].is_active()
        assert not live_tab._palette_cells["static"].is_active()

    def test_touch_with_no_selection_records_nothing(self, live_tab):
        live_tab._palette_cells["static"].clicked.emit("static")
        assert live_tab.state.group_palettes == {}
        # Still staged, so APPLY can commit it once a group is selected.
        assert live_tab.state.staged_palette == "static"

    def test_apply_to_selection_commits_staged(self, live_tab):
        live_tab._palette_cells["sparkle"].clicked.emit("sparkle")
        live_tab.state.toggle_group("Rear Wash")   # select after staging
        live_tab._apply_btn.click()
        assert live_tab.state.group_palettes["Rear Wash"] == "sparkle"


class TestMasterAndBlackout:
    def test_master_fader_updates_level(self, live_tab):
        live_tab._master_fader.value_changed.emit(40)
        assert live_tab.state.master == 40
        assert live_tab._master_value.text() == "40"

    def test_blackout_zeroes_master_and_sets_flag(self, live_tab):
        live_tab.state.set_master(80)
        live_tab._blackout_btn.setChecked(True)
        assert live_tab.state.blackout is True
        assert live_tab.state.master == 0

    def test_releasing_blackout_restores_master(self, live_tab):
        live_tab.state.set_master(70)
        live_tab._blackout_btn.setChecked(True)
        live_tab._blackout_btn.setChecked(False)
        assert live_tab.state.blackout is False
        assert live_tab.state.master == 70

    def test_moving_master_off_zero_releases_blackout(self, live_tab):
        live_tab._blackout_btn.setChecked(True)
        live_tab.state.set_master(55)
        assert live_tab.state.blackout is False
        assert live_tab.state.master == 55


class TestStrobeAndFade:
    def test_strobe_toggle_feeds_state(self, live_tab):
        live_tab._strobe_btn.setChecked(True)
        assert live_tab.state.strobe_on is True

    def test_strobe_rate_feeds_state(self, live_tab):
        live_tab._strobe_slider.value_changed.emit(75)
        assert live_tab.state.strobe_rate == 75

    def test_fade_control_feeds_state(self, live_tab):
        # Click the "4 s" fade button.
        for btn, seconds in live_tab._fade_buttons:
            if abs(seconds - 4.0) < 1e-6:
                btn.click()
        assert live_tab.state.fade_seconds == 4.0

    def test_default_fade_is_two_seconds(self, live_tab):
        assert live_tab.state.fade_seconds == 2.0
        # ...and the matching chip is checked after the initial sync.
        checked = [s for btn, s in live_tab._fade_buttons if btn.isChecked()]
        assert checked == [2.0]


class TestStateSignal:
    def test_state_changed_emits_on_interactions(self, live_tab):
        hits = []
        live_tab.state.state_changed.connect(lambda: hits.append(1))
        live_tab.state.toggle_group("Movers")
        live_tab.state.stage_palette("static")
        live_tab.state.set_master(30)
        live_tab.state.set_blackout(True)
        live_tab.state.set_fade_seconds(0.5)
        live_tab.state.set_strobe_on(True)
        live_tab.state.set_strobe_rate(20)
        assert len(hits) == 7


class TestUpdateFromConfig:
    def test_refreshes_tiles_when_groups_change(self, live_tab):
        new_config = _config((
            ("Spots", "#5F86C9", 3),
            ("Blinders", "#C96A5F", 2),
        ))
        live_tab.config = new_config
        live_tab.update_from_config()
        assert set(live_tab._select_tiles) == {"Spots", "Blinders"}

    def test_stale_selection_pruned_on_group_change(self, live_tab):
        live_tab.state.toggle_group("Movers")
        new_config = _config((("Spots", "#5F86C9", 1),))
        live_tab.config = new_config
        live_tab.update_from_config()
        assert "Movers" not in live_tab.state.selected


class TestRoles:
    def test_panels_and_actions_use_theme_roles(self, live_tab):
        # Assert role properties (not stylesheets) per the brand convention.
        assert live_tab._apply_btn.property("role") == "cta-accent"
        assert live_tab._blackout_btn.property("role") == "destructive"
        assert live_tab._strobe_btn.property("role") == "output-select"

    def test_destructive_role_rule_exists_in_theme(self):
        from gui.theme_tokens import render_theme
        qss = render_theme("dark")
        assert 'QPushButton[role="destructive"]' in qss
        assert 'QPushButton[role="cta-accent"]' in qss
