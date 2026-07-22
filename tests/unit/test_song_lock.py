# tests/unit/test_song_lock.py
"""The per-song lock (v1.5, 2026-07-22): Song.locked is an EDITOR
fence. When set, timeline and structure edits refuse everywhere
(handler guards + disabled chrome), while playback, export, morphing,
the setlist and the lane mute/solo toggles stay untouched, and every
read-only path (selection, copy) keeps working.

Serialization coverage lives in test_compact_serializer.TestSongLock;
this file covers the behavioral fence: the ShowsTab chip + guards, the
lane/block widget guards, the StructureTab chip + disabled inspector,
the movement-migration skip and the morph-output-unlocked invariant.
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from tests.unit.test_shows_tab_chrome import _add_show, _stub_heavy_widgets


@pytest.fixture
def shows_tab(qapp, monkeypatch, sample_configuration):
    from PyQt6.QtCore import QEvent
    from PyQt6.QtWidgets import QApplication
    from gui.theme_manager import ThemeManager

    _stub_heavy_widgets(monkeypatch)
    ThemeManager().apply(qapp, "dark")
    _add_show(sample_configuration)

    from gui.tabs.shows_tab import ShowsTab
    tab = ShowsTab(sample_configuration, parent=None)
    tab.artnet_enabled = False
    tab.tcp_enabled = False
    tab._load_show("Demo Show")
    try:
        yield tab
    finally:
        tab.cleanup()
        tab.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
        QApplication.processEvents()


def _lock_current(tab, locked=True):
    tab.config.songs[tab.current_song_name].locked = locked
    tab._refresh_lock_ui()


class TestShowsTabLock:

    def test_locked_disables_edit_chrome_and_tags_the_footer(self,
                                                            shows_tab):
        _lock_current(shows_tab)
        assert not shows_tab.add_lane_btn.isEnabled()
        assert not shows_tab.autogen_btn.isEnabled()
        assert "LOCKED" in shows_tab.status_line.text()
        _lock_current(shows_tab, False)
        assert shows_tab.add_lane_btn.isEnabled()
        assert shows_tab.autogen_btn.isEnabled()
        assert "LOCKED" not in shows_tab.status_line.text()

    def test_add_lane_refuses(self, shows_tab):
        _lock_current(shows_tab)
        before = len(shows_tab.lane_widgets)
        shows_tab._add_new_lane()
        assert len(shows_tab.lane_widgets) == before

    def test_lane_remove_refuses(self, shows_tab):
        shows_tab._add_new_lane()
        _lock_current(shows_tab)
        before = len(shows_tab.lane_widgets)
        shows_tab._on_lane_remove_requested(shows_tab.lane_widgets[0])
        assert len(shows_tab.lane_widgets) == before

    def test_lane_widgets_grey_out(self, shows_tab):
        shows_tab._add_new_lane()
        lane_widget = shows_tab.lane_widgets[0]
        _lock_current(shows_tab)
        assert lane_widget.name_edit.isReadOnly()
        assert not lane_widget.targets_chip.isEnabled()
        assert not lane_widget.add_block_button.isEnabled()
        _lock_current(shows_tab, False)
        assert not lane_widget.name_edit.isReadOnly()
        assert lane_widget.targets_chip.isEnabled()

    def test_lane_level_guards_refuse(self, shows_tab):
        shows_tab._add_new_lane()
        lane_widget = shows_tab.lane_widgets[0]
        _lock_current(shows_tab)
        lane_widget.add_light_block()
        assert lane_widget.lane.light_blocks == []
        lane_widget.on_name_changed("New Name")
        assert lane_widget.lane.name != "New Name"
        lane_widget.on_riff_dropped("loops/whatever", 0.0)
        assert lane_widget.lane.light_blocks == []

    def test_mute_solo_stay_live(self, shows_tab):
        """The lock fences CONTENT, not output controls."""
        shows_tab._add_new_lane()
        lane_widget = shows_tab.lane_widgets[0]
        _lock_current(shows_tab)
        lane_widget.on_mute_toggled(True)
        assert lane_widget.lane.muted is True
        lane_widget.on_solo_toggled(True)
        assert lane_widget.lane.solo is True

    def test_unlocked_paths_still_work(self, shows_tab):
        """Regression half: the guards must not fire when unlocked."""
        shows_tab._add_new_lane()
        assert len(shows_tab.lane_widgets) == 1
        lane_widget = shows_tab.lane_widgets[0]
        lane_widget.add_light_block()
        assert len(lane_widget.lane.light_blocks) == 1


class TestBlockWidgetLock:

    @pytest.fixture
    def locked_block_widget(self, shows_tab):
        """A block on a lane whose song is locked, resolved data-driven
        (the block object is shared with the model, so _find_owning_song
        sees the lock without any tab plumbing)."""
        shows_tab._add_new_lane()
        lane_widget = shows_tab.lane_widgets[0]
        lane_widget.add_light_block()
        shows_tab.save_to_config()
        song = shows_tab.config.songs["Demo Show"]
        song.locked = True
        widget = lane_widget.light_block_widgets[0]
        assert widget._locked() is True     # the data-driven resolution
        return widget

    def test_press_selects_but_never_picks_up_a_drag(self,
                                                     locked_block_widget):
        from PyQt6.QtCore import QPointF, Qt
        from PyQt6.QtGui import QMouseEvent
        widget = locked_block_widget
        event = QMouseEvent(
            QMouseEvent.Type.MouseButtonPress, QPointF(5.0, 5.0),
            QPointF(5.0, 5.0), Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        widget.mousePressEvent(event)
        assert not widget.dragging
        assert not widget.resizing_left and not widget.resizing_right
        assert widget.creating_sublane is None
        assert widget.dragging_sublane is None
        assert widget.resizing_sublane is None
        assert widget.dragging_intensity_handle is None

    def test_mutating_sinks_refuse(self, locked_block_widget):
        widget = locked_block_widget
        block = widget.block
        dimmer_count = len(block.dimmer_blocks)
        widget._create_sublane_block("dimmer", 0.0, 1.0)
        assert len(block.dimmer_blocks) == dimmer_count
        if block.dimmer_blocks:
            widget._delete_sublane_block("dimmer", block.dimmer_blocks[0])
            assert len(block.dimmer_blocks) == dimmer_count
        widget.set_block_name()          # would open a dialog if unfenced
        widget.open_sublane_dialog("dimmer", None)  # ditto

    def test_delete_key_refuses(self, locked_block_widget):
        from PyQt6.QtCore import Qt
        from PyQt6.QtGui import QKeyEvent
        widget = locked_block_widget
        fired = []
        widget.remove_requested.connect(lambda w: fired.append(w))
        event = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Delete,
                          Qt.KeyboardModifier.NoModifier)
        widget.keyPressEvent(event)
        assert fired == []

    def test_copy_still_works(self, locked_block_widget):
        from timeline_ui.effect_clipboard import has_clipboard_data
        locked_block_widget.copy_effect()
        assert has_clipboard_data()


class TestStructureTabLock:

    @pytest.fixture
    def tab(self, qapp):
        from tests.unit.test_structure_tab import make_config
        from gui.tabs.structure_tab import StructureTab
        with patch("utils.midi_utils.discover_midi_profiles",
                   return_value=[]):
            tab = StructureTab(make_config(), parent=None)
        tab.update_from_config()
        yield tab
        tab.cleanup()
        tab.deleteLater()

    def _lock(self, tab, locked=True):
        tab.current_show.locked = locked
        tab.refresh_lock_ui()

    def test_chip_state_and_toggle(self, tab):
        assert tab.lock_song_btn.isCheckable()
        assert not tab.lock_song_btn.isChecked()
        tab.lock_song_btn.setChecked(True)   # toggled -> _on_lock_toggled
        assert tab.current_show.locked is True
        tab.lock_song_btn.setChecked(False)
        assert tab.current_show.locked is False

    def test_locked_disables_the_chrome(self, tab):
        self._lock(tab)
        assert not tab.rename_show_btn.isEnabled()
        assert not tab.delete_show_btn.isEnabled()
        assert not tab.add_part_tile.isEnabled()
        assert not tab.autogen_btn.isEnabled()
        assert not tab.load_audio_btn.isEnabled()
        tab._select_part(0) if hasattr(tab, "_select_part") else None
        assert not tab.bpm_spin.isEnabled()
        assert not tab.delete_part_btn.isEnabled()
        self._lock(tab, False)
        assert tab.rename_show_btn.isEnabled()
        assert tab.add_part_tile.isEnabled()

    def test_part_mutations_refuse(self, tab):
        self._lock(tab)
        parts_before = list(tab.current_show.parts)
        tab._add_new_part()
        tab._delete_part()
        tab._move_part(1)
        tab._reorder_part(0, 1)
        tab._on_bpm_changed(199.0)
        tab._set_transition_out(0, "gradual")
        assert tab.current_show.parts == parts_before
        assert tab.current_show.parts[0].bpm == 120.0
        assert tab.current_show.parts[0].transition == "instant"

    def test_unlocked_part_edit_still_works(self, tab):
        tab._selected_index = 0
        tab._on_bpm_changed(150.0)
        assert tab.current_show.parts[0].bpm == 150.0

    def test_cross_tab_push(self, tab):
        calls = []

        class FakeShowsTab:
            def mark_config_dirty(self):
                calls.append("dirty")

            def _refresh_lock_ui(self):
                calls.append("refresh")

            def _on_autogenerate(self):
                pass

        with patch.object(type(tab), "_shows_tab_delegate",
                          lambda self: FakeShowsTab()):
            tab.lock_song_btn.setChecked(True)
        assert "dirty" in calls and "refresh" in calls


class TestMigrationSkipsLocked:

    def test_locked_songs_report_skipped(self):
        from tests.unit.test_structure_tab import make_config
        from config.models import LightBlock, LightLane, MovementBlock, \
            TimelineData
        from utils.movement_migration import apply_migration, plan_migration

        config = make_config()
        block = LightBlock(start_time=0.0, end_time=4.0,
                           effect_name="bars.static")
        block.movement_blocks.append(MovementBlock(
            start_time=0.0, end_time=4.0, pan=127.5, tilt=127.5))
        lane = LightLane(name="Movers", fixture_targets=["Movers"],
                         light_blocks=[block])
        config.songs["Demo"].timeline_data = TimelineData(lanes=[lane])
        config.songs["Demo"].locked = True

        entries = plan_migration(config)
        assert entries, "the movement block must appear in the report"
        assert all(e.status == "skipped" and e.reason == "song is locked"
                   for e in entries)
        applied = apply_migration(config, entries)
        assert applied == 0
        assert block.movement_blocks[0].target_point is None


class TestMorphOutputUnlocked:

    def test_song_constructor_allow_list_stays_lock_free(self):
        """Morph output is fresh work: the compile's explicit Song
        constructor must not carry the source lock. Source-level pin -
        cheaper than a full compile and fails on exactly the mistake."""
        import inspect
        from utils.morph import compile as morph_compile
        source = inspect.getsource(morph_compile)
        assert "locked=" not in source
