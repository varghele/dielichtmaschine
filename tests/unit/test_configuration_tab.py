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


class TestContextMenu:
    """Right-click add / remove universes (card menu + empty-space menu)."""

    def test_remove_by_id_targets_that_universe_not_the_selection(self, qapp):
        tab = _make_tab(qapp, ("ArtNet", "E1.31"))
        try:
            tab._on_card_clicked(1)          # #1 selected
            tab._remove_universe_by_id(2)     # remove the OTHER one
            assert sorted(tab.config.universes) == [1]
            assert tab._selected_id == 1      # selection untouched
        finally:
            tab.deleteLater()

    def test_remove_by_id_ignores_missing_or_none(self, qapp):
        tab = _make_tab(qapp, ("ArtNet",))
        try:
            tab._remove_universe_by_id(99)
            tab._remove_universe_by_id(None)
            assert sorted(tab.config.universes) == [1]
        finally:
            tab.deleteLater()

    def test_card_menu_selects_and_offers_add_and_remove(self, qapp, monkeypatch):
        from PyQt6 import QtWidgets
        from PyQt6.QtCore import QPoint

        tab = _make_tab(qapp, ("ArtNet", "E1.31"))
        try:
            captured = {}
            monkeypatch.setattr(
                QtWidgets.QMenu, "exec",
                lambda menu, *a, **k: captured.setdefault(
                    "texts", [act.text() for act in menu.actions()]))
            tab._show_card_context_menu(2, QPoint(0, 0))
            assert tab._selected_id == 2      # right-click selected the card
            assert captured["texts"] == ["Add Universe", "Remove Universe"]
        finally:
            tab.deleteLater()

    def test_empty_space_menu_offers_add_only(self, qapp, monkeypatch):
        from PyQt6 import QtWidgets
        from PyQt6.QtCore import QPoint

        tab = _make_tab(qapp, ("ArtNet",))
        try:
            captured = {}
            monkeypatch.setattr(
                QtWidgets.QMenu, "exec",
                lambda menu, *a, **k: captured.setdefault(
                    "texts", [act.text() for act in menu.actions()]))
            tab._show_list_context_menu(QPoint(5, 5))
            assert captured["texts"] == ["Add Universe"]
        finally:
            tab.deleteLater()

    def test_triggering_menu_remove_deletes_that_universe(self, qapp, monkeypatch):
        from PyQt6 import QtWidgets
        from PyQt6.QtCore import QPoint

        tab = _make_tab(qapp, ("ArtNet", "E1.31"))
        try:
            def fake_exec(menu, *a, **k):
                for act in menu.actions():
                    if act.text() == "Remove Universe":
                        act.trigger()
            monkeypatch.setattr(QtWidgets.QMenu, "exec", fake_exec)
            tab._exec_universe_menu(QPoint(0, 0), 2)
            assert sorted(tab.config.universes) == [1]
        finally:
            tab.deleteLater()

    def test_triggering_menu_add_appends_a_universe(self, qapp, monkeypatch):
        from PyQt6 import QtWidgets
        from PyQt6.QtCore import QPoint

        tab = _make_tab(qapp, ("ArtNet",))
        try:
            def fake_exec(menu, *a, **k):
                for act in menu.actions():
                    if act.text() == "Add Universe":
                        act.trigger()
            monkeypatch.setattr(QtWidgets.QMenu, "exec", fake_exec)
            tab._exec_universe_menu(QPoint(0, 0), None)
            assert sorted(tab.config.universes) == [1, 2]
        finally:
            tab.deleteLater()

    def test_card_emits_context_requested_on_right_click(self, qapp,
                                                         monkeypatch):
        from PyQt6 import QtGui, QtWidgets
        from PyQt6.QtCore import QPoint

        tab = _make_tab(qapp, ("ArtNet",))
        try:
            # The tab's own handler on this signal opens a QMenu, and
            # QMenu.exec is a MODAL event loop: unstubbed it blocks the
            # whole test run forever (froze two full-suite runs on
            # 2026-07-14 - see docs/qt-gotchas.md). Stub it and use the
            # capture to prove the menu wiring fired.
            menus = []
            monkeypatch.setattr(
                QtWidgets.QMenu, "exec",
                lambda self, *a, **k: menus.append(self))
            received = []
            tab._cards[1].context_requested.connect(
                lambda uid, pos: received.append(uid))
            event = QtGui.QContextMenuEvent(
                QtGui.QContextMenuEvent.Reason.Mouse, QPoint(2, 2))
            tab._cards[1].contextMenuEvent(event)
            assert received == [1]
            assert len(menus) == 1
        finally:
            tab.deleteLater()


def _patch_fixture(universe, address=1):
    from config.models import Fixture, FixtureMode
    return Fixture(universe=universe, address=address, manufacturer="M",
                   model="X", name=f"F{universe}", group="G",
                   current_mode="Std",
                   available_modes=[FixtureMode(name="Std", channels=8)],
                   type="PAR")


class TestRemoveConfirmation:
    """Deleting a universe with fixtures still patched to it asks first."""

    def test_helper_lists_fixtures_on_that_universe(self, qapp):
        from gui.tabs.configuration_tab import fixtures_on_universe
        cfg = _make_config(("ArtNet", "E1.31"))
        cfg.fixtures = [_patch_fixture(1), _patch_fixture(1, 20),
                        _patch_fixture(2)]
        assert len(fixtures_on_universe(cfg, 1)) == 2
        assert len(fixtures_on_universe(cfg, 2)) == 1
        assert fixtures_on_universe(cfg, 9) == []

    def test_empty_universe_removed_without_prompt(self, qapp, monkeypatch):
        from PyQt6 import QtWidgets
        tab = _make_tab(qapp, ("ArtNet", "E1.31"))
        try:
            def boom(*a, **k):
                raise AssertionError("should not prompt for an empty universe")
            monkeypatch.setattr(QtWidgets.QMessageBox, "question", boom)
            tab._remove_universe_by_id(2)
            assert sorted(tab.config.universes) == [1]
        finally:
            tab.deleteLater()

    def test_patched_universe_prompts_and_cancel_keeps_it(self, qapp, monkeypatch):
        from PyQt6 import QtWidgets
        tab = _make_tab(qapp, ("ArtNet", "E1.31"))
        try:
            tab.config.fixtures = [_patch_fixture(2)]
            asked = {}
            def no(parent, title, text, *a, **k):
                asked["text"] = text
                return QtWidgets.QMessageBox.StandardButton.No
            monkeypatch.setattr(QtWidgets.QMessageBox, "question",
                                staticmethod(no))
            tab._remove_universe_by_id(2)
            assert sorted(tab.config.universes) == [1, 2]  # kept
            assert "patched" in asked["text"]
        finally:
            tab.deleteLater()

    def test_patched_universe_prompts_and_confirm_removes_it(self, qapp, monkeypatch):
        from PyQt6 import QtWidgets
        tab = _make_tab(qapp, ("ArtNet", "E1.31"))
        try:
            tab.config.fixtures = [_patch_fixture(2), _patch_fixture(2, 20)]
            monkeypatch.setattr(
                QtWidgets.QMessageBox, "question",
                staticmethod(lambda *a, **k:
                             QtWidgets.QMessageBox.StandardButton.Yes))
            tab._remove_universe_by_id(2)
            assert sorted(tab.config.universes) == [1]  # removed
        finally:
            tab.deleteLater()

    def test_remove_button_also_confirms(self, qapp, monkeypatch):
        from PyQt6 import QtWidgets
        tab = _make_tab(qapp, ("ArtNet", "E1.31"))
        try:
            tab._on_card_clicked(2)
            tab.config.fixtures = [_patch_fixture(2)]
            calls = []
            monkeypatch.setattr(
                QtWidgets.QMessageBox, "question",
                staticmethod(lambda *a, **k: calls.append(1) or
                             QtWidgets.QMessageBox.StandardButton.No))
            tab._remove_universe()  # the inspector button path
            assert calls == [1]                    # it prompted
            assert sorted(tab.config.universes) == [1, 2]  # cancelled
        finally:
            tab.deleteLater()


class TestReferenceChrome:
    """Deltas closed in the screen-03 diff pass."""

    def test_no_tab_title(self, qapp):
        """The shell subnav names the screen (reference has no title)."""
        tab = _make_tab(qapp, ("ArtNet",))
        try:
            assert not hasattr(tab, "config_label")
        finally:
            tab.deleteLater()

    def test_inspector_title_is_uni_and_name(self, qapp):
        tab = _make_tab(qapp, ("ArtNet",))
        try:
            assert tab.inspector_title.text() == "U1 · UNIVERSE 1"
            tab._on_name_edited("Main rig")
            assert tab.inspector_title.text() == "U1 · MAIN RIG"
        finally:
            tab.deleteLater()

    def test_rate_readout_comes_from_the_sender_constant(self, qapp):
        """Rate is a fixed property of the ArtNet sender, not a setting."""
        from utils.artnet.sender import ArtNetSender
        tab = _make_tab(qapp, ("ArtNet",))
        try:
            assert tab.artnet_rate.text() == \
                f"{ArtNetSender.MAX_SEND_RATE_HZ} Hz"
        finally:
            tab.deleteLater()

    def test_broadcast_toggle_drives_the_ip(self, qapp):
        """'Broadcast' is the 255.255.255.255 convention, not a field."""
        from gui.tabs.configuration_tab import BROADCAST_IP
        tab = _make_tab(qapp, ("ArtNet",))
        try:
            params = tab.config.universes[1].output["parameters"]
            assert not tab.artnet_broadcast.isChecked()

            tab.artnet_broadcast.setChecked(True)
            assert params["ip"] == BROADCAST_IP
            assert not tab.artnet_ip.isEnabled()

            tab.artnet_broadcast.setChecked(False)
            assert params["ip"] == "192.168.1.50"  # restored unicast
            assert tab.artnet_ip.isEnabled()
        finally:
            tab.deleteLater()

    def test_typing_the_broadcast_ip_checks_the_toggle(self, qapp):
        from gui.tabs.configuration_tab import BROADCAST_IP
        tab = _make_tab(qapp, ("ArtNet",))
        try:
            tab.artnet_ip.setText(BROADCAST_IP)
            tab._sync_broadcast_checkbox()
            assert tab.artnet_broadcast.isChecked()
        finally:
            tab.deleteLater()

    def test_numbering_hint_is_artnet_only(self, qapp):
        tab = _make_tab(qapp, ("ArtNet",))
        try:
            assert tab.numbering_hint.isVisibleTo(tab)
            assert tab.numbering_hint.property("role") == "hint-info"
            tab._on_protocol_selected("E1.31")
            assert not tab.numbering_hint.isVisibleTo(tab)
        finally:
            tab.deleteLater()

    def test_hint_info_role_uses_the_info_colour(self):
        from gui.theme_tokens import THEMES, render_theme
        rule = render_theme("dark").split(
            'QLabel[role="hint-info"] {', 1)[1].split("}", 1)[0]
        assert THEMES["dark"]["info"] in rule

    def test_status_strip_counts_configured_universes(self, qapp):
        tab = _make_tab(qapp, ("ArtNet", "DMX USB"))
        try:
            # ArtNet has an ip; the USB universe has no device yet.
            assert tab.status_line.text() == "2 UNIVERSES · 1 CONFIGURED"
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
