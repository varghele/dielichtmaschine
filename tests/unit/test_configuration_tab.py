"""ConfigurationTab: the North Star 1d card list + inspector.

Supersedes the old table-cell tests: protocol-irrelevant fields are no
longer disabled table cells (the source of the historical "mysteriously
dead white cells" bug) - the inspector simply shows the page for the
selected output type, so wrong-protocol fields cannot be interacted
with at all. These tests pin the new structure and the unchanged data
contract (Universe.output edited in place, gui.py's
update_from_config/save_to_config entry points).
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _make_config(protocols=("ArtNet",)):
    from config.models import Configuration, Universe

    params_for = {
        "ArtNet": {"ip": "192.168.1.50", "subnet": "0", "universe": "0"},
        "E1.31": {"multicast": "true", "ip": "239.255.0.1",
                  "port": "5568", "universe": "1"},
        "DMX USB": {"device": ""},
    }
    cfg = Configuration()
    cfg.universes = {
        i + 1: Universe(
            id=i + 1, name=f"Universe {i + 1}",
            output={"plugin": p, "parameters": dict(params_for[p]),
                    "line": "0"},
        )
        for i, p in enumerate(protocols)
    }
    return cfg


def _make_tab(qapp, protocols=("ArtNet",), config=None):
    from gui.theme_manager import ThemeManager
    from gui.tabs.configuration_tab import ConfigurationTab

    ThemeManager().apply(qapp, "dark")
    cfg = config if config is not None else _make_config(protocols)
    with patch(
        "gui.tabs.configuration_tab.get_device_display_names",
        return_value=["No Device"],
    ):
        tab = ConfigurationTab(cfg, parent=None)
    return tab


class TestCardList:
    def test_one_card_per_universe_first_selected(self, qapp):
        tab = _make_tab(qapp, ("ArtNet", "E1.31"))
        try:
            assert sorted(tab._cards) == [1, 2]
            assert tab._selected_id == 1
            assert tab._cards[1].property("selected") == "true"
            assert tab._cards[2].property("selected") == "false"
        finally:
            tab.deleteLater()

    def test_card_shows_protocol_chip_and_destination(self, qapp):
        tab = _make_tab(qapp, ("ArtNet",))
        try:
            card = tab._cards[1]
            assert card.output_chip.text() == "ARTNET"
            assert "192.168.1.50" in card.destination_label.text()
            assert "0-based" in card.destination_label.text()
            assert card.status_label.text() == "READY"
        finally:
            tab.deleteLater()

    def test_click_selects_and_loads_inspector(self, qapp):
        tab = _make_tab(qapp, ("ArtNet", "E1.31"))
        try:
            tab._on_card_clicked(2)
            assert tab._selected_id == 2
            assert tab._cards[2].property("selected") == "true"
            assert tab.protocol_buttons["E1.31"].isChecked()
            assert tab.param_stack.currentIndex() == 1
        finally:
            tab.deleteLater()

    def test_channels_used_counts_current_mode_footprints(self, qapp):
        from config.models import Fixture, FixtureMode
        from gui.tabs.configuration_tab import channels_used

        cfg = _make_config(("ArtNet",))
        cfg.fixtures = [
            Fixture(universe=1, address=1, manufacturer="M", model="X",
                    name="A", group="G", current_mode="Std",
                    available_modes=[FixtureMode(name="Std", channels=10)],
                    type="PAR"),
            Fixture(universe=1, address=20, manufacturer="M", model="X",
                    name="B", group="G", current_mode="Big",
                    available_modes=[FixtureMode(name="Std", channels=10),
                                     FixtureMode(name="Big", channels=24)],
                    type="PAR"),
            Fixture(universe=2, address=1, manufacturer="M", model="X",
                    name="C", group="G", current_mode="Std",
                    available_modes=[FixtureMode(name="Std", channels=8)],
                    type="PAR"),
        ]
        assert channels_used(cfg, 1) == 34
        assert channels_used(cfg, 2) == 8

        tab = _make_tab(qapp, config=cfg)
        try:
            assert tab._cards[1].used_label.text() == "34/512"
        finally:
            tab.deleteLater()


class TestInspectorEditing:
    def test_protocol_switch_resets_params_to_defaults(self, qapp):
        tab = _make_tab(qapp, ("ArtNet",))
        try:
            tab._on_protocol_selected("E1.31")
            output = tab.config.universes[1].output
            assert output["plugin"] == "E1.31"
            assert output["parameters"]["multicast"] == "true"
            assert tab.param_stack.currentIndex() == 1
            assert tab._cards[1].output_chip.text() == "E1.31"
        finally:
            tab.deleteLater()

    def test_param_edit_writes_through_and_updates_card(self, qapp):
        tab = _make_tab(qapp, ("ArtNet",))
        try:
            tab._on_param_edited("ip", "10.0.0.7")
            assert tab.config.universes[1].output["parameters"]["ip"] == "10.0.0.7"
            assert "10.0.0.7" in tab._cards[1].destination_label.text()
        finally:
            tab.deleteLater()

    def test_e131_multicast_locks_ip_and_autocalculates(self, qapp):
        tab = _make_tab(qapp, ("E1.31",))
        try:
            assert not tab.e131_ip.isEnabled()  # multicast on
            tab._on_e131_universe_edited("258")
            params = tab.config.universes[1].output["parameters"]
            assert params["ip"] == "239.255.1.2"  # 258 = 1*256 + 2
            tab.e131_multicast.setChecked(False)
            assert tab.e131_ip.isEnabled()
            assert params["multicast"] == "false"
        finally:
            tab.deleteLater()

    def test_name_edit_updates_card(self, qapp):
        tab = _make_tab(qapp, ("ArtNet",))
        try:
            tab._on_name_edited("Main rig")
            assert tab.config.universes[1].name == "Main rig"
            assert tab._cards[1].name_label.text() == "Main rig"
        finally:
            tab.deleteLater()

    def test_usb_without_device_reads_unset(self, qapp):
        tab = _make_tab(qapp, ("DMX USB",))
        try:
            card = tab._cards[1]
            assert card.status_label.text() == "UNSET"
            assert "no device" in card.destination_label.text()
        finally:
            tab.deleteLater()


class TestAddRemove:
    def test_add_universe_appends_and_selects(self, qapp):
        tab = _make_tab(qapp, ("ArtNet",))
        try:
            tab._add_universe()
            assert sorted(tab.config.universes) == [1, 2]
            assert tab._selected_id == 2
            assert tab._cards[2].property("selected") == "true"
        finally:
            tab.deleteLater()

    def test_remove_selected_universe(self, qapp):
        tab = _make_tab(qapp, ("ArtNet", "E1.31"))
        try:
            tab._on_card_clicked(2)
            tab._remove_universe()
            assert sorted(tab.config.universes) == [1]
            assert 2 not in tab._cards
            assert tab._selected_id == 1
        finally:
            tab.deleteLater()

    def test_empty_config_disables_inspector(self, qapp):
        from config.models import Configuration
        cfg = Configuration()
        cfg.universes = {}
        tab = _make_tab(qapp, config=cfg)
        try:
            assert not tab.name_edit.isEnabled()
            assert not tab.remove_universe_btn.isEnabled()
        finally:
            tab.deleteLater()


class TestContract:
    def test_toolbar_width_constant_still_exported(self):
        """FixturesTab and StageTab import TOOLBAR_BTN_WIDTH from here."""
        from gui.tabs.configuration_tab import (
            TOOLBAR_BTN_SIZE, TOOLBAR_BTN_WIDTH,
        )
        assert TOOLBAR_BTN_WIDTH == TOOLBAR_BTN_SIZE == 40

    def test_update_from_config_rebuilds_after_external_change(self, qapp):
        from config.models import Universe
        tab = _make_tab(qapp, ("ArtNet",))
        try:
            tab.config.universes[9] = Universe(
                id=9, name="Late", output={
                    "plugin": "ArtNet", "line": "0",
                    "parameters": {"ip": "1.2.3.4", "subnet": "0",
                                   "universe": "3"}})
            tab.update_from_config()
            assert 9 in tab._cards
            assert tab._cards[9].name_label.text() == "Late"
        finally:
            tab.deleteLater()
