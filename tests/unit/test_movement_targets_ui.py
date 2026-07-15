# tests/unit/test_movement_targets_ui.py
"""UI surfaces of the v1.5a focus-geometry authoring pass
(docs/focus-morphing-plan.md phase 1):

- Tools > Convert Movement to World Targets... lives in the shell's
  overflow menu (there is NO QMenuBar) and the confirmation flow never
  mutates the config before CONVERT
  (gui/dialogs/movement_migration_dialog.py).
- The movement block editor's target combo offers MANUAL / the stored
  world POINT (read-only display) / every named spot / every stage
  plane, mirroring the resolution priority plane > spot > point >
  manual (timeline_ui/movement_block_dialog.py).
- Click-to-aim: the Stage tab's AIM toggle arms StageView's aim mode,
  a left click reports the stage coordinate, and the tab writes it into
  the Shows tab's selected movement blocks (Shift keeps the current
  target height).
- ShowsTab.selected_movement_blocks: explicit movement sublane
  selection wins over the envelope multi-selection.

All offscreen; dialogs are driven through accept()/injected exec (the
suite blocks real QDialog.exec, qt-gotchas #7)."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from config.models import (Configuration, Fixture, FixtureGroup,
                           FixtureMode, LightBlock, LightLane,
                           MovementBlock, Song, Spot, TimelineData)


# ---------------------------------------------------------------------------
# Shared builders
# ---------------------------------------------------------------------------

def _mover_config():
    fixture = Fixture(
        universe=1, address=1, manufacturer="NoSuchMfr_targets_ui",
        model="StepMover", name="MH1", group="Movers",
        current_mode="Standard",
        available_modes=[FixtureMode(name="Standard", channels=10)],
        type="MH", x=0.0, y=0.0, z=4.0,
        mounting="hanging", yaw=0.0, pitch=90.0, roll=0.0,
        orientation_uses_group_default=False, z_uses_group_default=False)
    config = Configuration(
        fixtures=[fixture],
        groups={"Movers": FixtureGroup(name="Movers", fixtures=[fixture])},
        stage_width=10.0, stage_height=6.0)
    config.spots = {"Mark": Spot(name="Mark", x=1.0, y=-2.0, z=0.0)}
    return config


def _add_movement_song(config, block):
    lane = LightLane(name="Movers", fixture_targets=["Movers"])
    lane.light_blocks.append(LightBlock(
        start_time=block.start_time, end_time=block.end_time,
        effect_name="", movement_blocks=[block]))
    config.songs["Song A"] = Song(
        name="Song A", timeline_data=TimelineData(lanes=[lane]))
    return config


def _block(**overrides):
    params = dict(start_time=0.0, end_time=8.0, effect_type="static")
    params.update(overrides)
    return MovementBlock(**params)


# ---------------------------------------------------------------------------
# Tools menu (shell)
# ---------------------------------------------------------------------------

class TestToolsMenu:
    @pytest.fixture
    def shell(self, qapp):
        from PyQt6.QtWidgets import QMainWindow
        from gui.Ui_MainWindow import Ui_MainWindow
        window = QMainWindow()
        ui = Ui_MainWindow()
        ui.setupUi(window)
        yield window, ui
        window.deleteLater()

    def test_tools_menu_sits_in_the_overflow(self, shell):
        _, ui = shell
        submenus = [a.menu() for a in ui.overflow_menu.actions()
                    if a.menu() is not None]
        assert ui.menuTools in submenus
        # Between View and Settings, matching the shell's menu order.
        assert submenus.index(ui.menuTools) \
            == submenus.index(ui.menuView) + 1

    def test_convert_action_lives_in_tools(self, shell):
        _, ui = shell
        assert ui.actionConvertMovementTargets in ui.menuTools.actions()
        assert ui.actionConvertMovementTargets.text() == \
            "Convert Movement to World Targets..."

    def test_shortcut_registration_survives_the_new_menu(self, shell):
        from gui.widgets.topbar import register_menu_shortcuts
        window, ui = shell
        assert register_menu_shortcuts(window, ui.overflow_menu) >= 7


# ---------------------------------------------------------------------------
# Confirmation flow
# ---------------------------------------------------------------------------

class TestMigrationConfirmationFlow:
    def _config(self):
        return _add_movement_song(_mover_config(),
                                  _block(pan=127.0, tilt=127.0))

    def test_cancel_changes_nothing(self, qapp):
        from PyQt6.QtWidgets import QDialog
        from gui.dialogs.movement_migration_dialog import (
            run_movement_migration,
        )
        config = self._config()
        block = (config.songs["Song A"].timeline_data
                 .lanes[0].light_blocks[0].movement_blocks[0])
        result = run_movement_migration(
            config, execute=lambda d: QDialog.DialogCode.Rejected)
        assert result is None
        assert block.target_point is None

    def test_confirm_applies_the_plan(self, qapp):
        from PyQt6.QtWidgets import QDialog
        from gui.dialogs.movement_migration_dialog import (
            run_movement_migration,
        )
        config = self._config()
        block = (config.songs["Song A"].timeline_data
                 .lanes[0].light_blocks[0].movement_blocks[0])
        result = run_movement_migration(
            config, execute=lambda d: QDialog.DialogCode.Accepted)
        assert result == 1
        assert block.target_point is not None
        # pan/tilt stay as authored fallback
        assert (block.pan, block.tilt) == (127.0, 127.0)

    def test_dialog_lists_the_full_report_before_apply(self, qapp):
        from gui.dialogs.movement_migration_dialog import (
            MovementMigrationDialog,
        )
        from utils.movement_migration import plan_migration
        config = self._config()
        entries = plan_migration(config)
        dialog = MovementMigrationDialog(entries)
        try:
            assert dialog.report_table.rowCount() == 1
            assert dialog.report_table.item(0, 0).text() == "Song A"
            assert dialog.report_table.item(0, 1).text() == "Movers"
            assert dialog.report_table.item(0, 2).text() == "0.0-8.0s"
            assert "->" in dialog.report_table.item(0, 3).text()
            assert dialog.ok_button.isEnabled()
            assert dialog.ok_button.text() == "CONVERT"
        finally:
            dialog.deleteLater()

    def test_convert_disabled_when_nothing_converts(self, qapp):
        from gui.dialogs.movement_migration_dialog import (
            MovementMigrationDialog,
        )
        dialog = MovementMigrationDialog([])
        try:
            assert not dialog.ok_button.isEnabled()
        finally:
            dialog.deleteLater()


# ---------------------------------------------------------------------------
# Movement block editor: target combo
# ---------------------------------------------------------------------------

class TestTargetCombo:
    def _dialog(self, block, config=None):
        from timeline_ui.movement_block_dialog import MovementBlockDialog
        return MovementBlockDialog(
            block, config=config if config is not None
            else _mover_config())

    def _kinds(self, dialog):
        return [dialog.target_combo.itemData(i)
                for i in range(dialog.target_combo.count())]

    def _select(self, dialog, wanted):
        for i in range(dialog.target_combo.count()):
            if dialog.target_combo.itemData(i) == wanted:
                dialog.target_combo.setCurrentIndex(i)
                return
        raise AssertionError(f"{wanted} not offered")

    def test_combo_offers_manual_spots_and_planes(self, qapp):
        dialog = self._dialog(_block())
        kinds = self._kinds(dialog)
        assert kinds[0] == ("manual", None)
        assert ("spot", "Mark") in kinds
        for plane in ("Floor", "Ceiling", "Front", "Back", "Left",
                      "Right"):
            assert ("plane", plane) in kinds
        # no stored point -> no POINT entry
        assert ("point", None) not in kinds
        dialog.deleteLater()

    def test_point_entry_displays_the_stored_coordinate(self, qapp):
        dialog = self._dialog(_block(target_point=[1.5, -2.0, 0.25]))
        kinds = self._kinds(dialog)
        assert ("point", None) in kinds
        index = kinds.index(("point", None))
        assert dialog.target_combo.itemText(index) == \
            "POINT (1.50, -2.00, 0.25) m"
        # and it is preselected (highest-priority target on the block)
        assert dialog.target_combo.currentData() == ("point", None)
        dialog.deleteLater()

    def test_priority_mirrors_resolution_order(self, qapp):
        dialog = self._dialog(_block(target_plane_name="Floor",
                                     target_spot_name="Mark",
                                     target_point=[0.0, 0.0, 0.0]))
        assert dialog.target_combo.currentData() == ("plane", "Floor")
        dialog.deleteLater()
        dialog = self._dialog(_block(target_spot_name="Mark",
                                     target_point=[0.0, 0.0, 0.0]))
        assert dialog.target_combo.currentData() == ("spot", "Mark")
        dialog.deleteLater()

    def test_selecting_a_spot_writes_it_and_clears_the_point(self, qapp):
        block = _block(target_point=[1.0, 1.0, 0.0])
        dialog = self._dialog(block)
        self._select(dialog, ("spot", "Mark"))
        dialog.accept()
        assert block.target_spot_name == "Mark"
        assert block.target_plane_name is None
        assert block.target_point is None

    def test_selecting_a_plane_writes_it_and_clears_the_rest(self, qapp):
        block = _block(target_spot_name="Mark")
        dialog = self._dialog(block)
        self._select(dialog, ("plane", "Floor"))
        dialog.accept()
        assert block.target_plane_name == "Floor"
        assert block.target_spot_name is None
        assert block.target_point is None

    def test_selecting_manual_clears_every_target(self, qapp):
        block = _block(target_spot_name="Mark",
                       target_point=[1.0, 1.0, 0.0])
        dialog = self._dialog(block)
        self._select(dialog, ("manual", None))
        dialog.accept()
        assert block.target_spot_name is None
        assert block.target_plane_name is None
        assert block.target_point is None

    def test_keeping_the_point_selection_keeps_the_point(self, qapp):
        block = _block(target_point=[1.0, -2.0, 0.5])
        dialog = self._dialog(block)
        dialog.accept()  # POINT preselected, untouched
        assert block.target_point == [1.0, -2.0, 0.5]
        assert block.target_spot_name is None


# ---------------------------------------------------------------------------
# Click-to-aim: StageView mode + StageTab wiring
# ---------------------------------------------------------------------------

def _mouse_press(view, view_point, modifiers):
    from PyQt6.QtCore import QEvent, QPointF, Qt
    from PyQt6.QtGui import QMouseEvent
    return QMouseEvent(
        QEvent.Type.MouseButtonPress, QPointF(view_point),
        view.mapToGlobal(QPointF(view_point)),
        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, modifiers)


class TestStageViewAimMode:
    @pytest.fixture
    def view(self, qapp):
        from gui.StageView import StageView
        view = StageView()
        view.set_config(_mover_config())
        yield view
        view.deleteLater()

    def test_aim_click_reports_the_stage_coordinate(self, view):
        from PyQt6.QtCore import Qt
        received = []
        view.aim_clicked.connect(
            lambda x, y, keep: received.append((x, y, keep)))
        view.set_aim_mode(True)

        x_px, y_px = view.meters_to_pixels(2.0, -1.5)
        from PyQt6.QtCore import QPointF
        view_point = view.mapFromScene(QPointF(x_px, y_px))
        view.mousePressEvent(_mouse_press(
            view, view_point, Qt.KeyboardModifier.NoModifier))

        assert len(received) == 1
        x, y, keep = received[0]
        assert x == pytest.approx(2.0, abs=0.05)
        assert y == pytest.approx(-1.5, abs=0.05)
        assert keep is False
        # the click was consumed - no rubber band started
        assert not view._is_rubber_band_selecting

    def test_shift_click_sets_the_keep_z_flag(self, view):
        from PyQt6.QtCore import QPointF, Qt
        received = []
        view.aim_clicked.connect(
            lambda x, y, keep: received.append(keep))
        view.set_aim_mode(True)
        x_px, y_px = view.meters_to_pixels(0.0, 0.0)
        view.mousePressEvent(_mouse_press(
            view, view.mapFromScene(QPointF(x_px, y_px)),
            Qt.KeyboardModifier.ShiftModifier))
        assert received == [True]

    def test_clicks_pass_through_when_mode_is_off(self, view):
        from PyQt6.QtCore import QPointF, Qt
        received = []
        view.aim_clicked.connect(
            lambda x, y, keep: received.append((x, y)))
        x_px, y_px = view.meters_to_pixels(0.0, 0.0)
        view.mousePressEvent(_mouse_press(
            view, view.mapFromScene(QPointF(x_px, y_px)),
            Qt.KeyboardModifier.NoModifier))
        assert received == []


class TestStageTabClickToAim:
    @pytest.fixture
    def stage_tab(self, qapp):
        from gui.tabs.stage_tab import StageTab
        tab = StageTab(_mover_config(), parent=None)
        yield tab
        tab.deleteLater()

    def test_aim_button_arms_the_view(self, stage_tab):
        assert stage_tab.aim_btn.isCheckable()
        assert stage_tab.stage_view.aim_mode is False
        stage_tab.aim_btn.setChecked(True)
        assert stage_tab.stage_view.aim_mode is True
        stage_tab.aim_btn.setChecked(False)
        assert stage_tab.stage_view.aim_mode is False

    def test_click_writes_the_selected_blocks_target_point(self, stage_tab):
        blocks = [_block(target_spot_name="Mark"),
                  _block(target_plane_name="Floor")]
        stage_tab.aim_blocks_provider = lambda: blocks
        stage_tab._on_aim_clicked(2.0, -1.5, False)
        for block in blocks:
            assert block.target_point == [2.0, -1.5, 0.0]
            # the click's point must actually win: spot/plane cleared
            assert block.target_spot_name is None
            assert block.target_plane_name is None
            assert block.modified is True

    def test_shift_click_keeps_the_current_height(self, stage_tab):
        block = _block(target_point=[0.0, 0.0, 1.5])
        stage_tab.aim_blocks_provider = lambda: [block]
        stage_tab._on_aim_clicked(3.0, 1.0, True)
        assert block.target_point == [3.0, 1.0, 1.5]
        # without a stored point, Shift falls back to the floor
        fresh = _block()
        stage_tab.aim_blocks_provider = lambda: [fresh]
        stage_tab._on_aim_clicked(3.0, 1.0, True)
        assert fresh.target_point == [3.0, 1.0, 0.0]

    def test_no_selection_is_a_no_op(self, stage_tab):
        stage_tab.aim_blocks_provider = lambda: []
        stage_tab._on_aim_clicked(1.0, 1.0, False)  # must not raise

    def test_default_provider_asks_the_shows_tab(self, stage_tab):
        """Without the test hook, the tab resolves the Shows tab via its
        MainWindow parent; parentless (as here) it degrades to no-op."""
        assert stage_tab._aim_movement_blocks() == []


# ---------------------------------------------------------------------------
# ShowsTab selection tiers
# ---------------------------------------------------------------------------

def _stub_heavy_widgets(monkeypatch):
    """Replace the GL visualizer + riff panel with inert widgets (same
    trick as tests/unit/test_shows_tab_chrome.py)."""
    from PyQt6.QtWidgets import QWidget

    class StubVisualizer(QWidget):
        def __init__(self, parent=None):
            super().__init__(parent)

        def set_pop_out_callback(self, callback):
            pass

        def set_inner_pop_out_visible(self, visible):
            pass

        def set_config(self, config):
            pass

        def set_preview_mode(self, mode):
            pass

        def feed_dmx(self, universe, dmx_bytes):
            pass

        def cleanup(self):
            pass

    class StubRiffPanel(QWidget):
        def __init__(self, library=None, parent=None):
            super().__init__(parent)

    monkeypatch.setattr("gui.tabs.shows_tab.EmbeddedVisualizer",
                        StubVisualizer)
    monkeypatch.setattr("gui.tabs.shows_tab.RiffBrowserPanel",
                        StubRiffPanel)
    monkeypatch.setattr(
        "gui.tabs.shows_tab.ShowsTab._get_shared_riff_library",
        lambda self: None)


class TestShowsTabSelection:
    @pytest.fixture
    def shows_tab(self, qapp, monkeypatch, sample_configuration):
        from PyQt6.QtCore import QEvent
        from PyQt6.QtWidgets import QApplication
        from gui.theme_manager import ThemeManager

        _stub_heavy_widgets(monkeypatch)
        ThemeManager().apply(qapp, "dark")
        from gui.tabs.shows_tab import ShowsTab
        tab = ShowsTab(sample_configuration, parent=None)
        tab.artnet_enabled = False
        tab.tcp_enabled = False
        try:
            yield tab
        finally:
            tab.cleanup()
            tab.deleteLater()
            QApplication.sendPostedEvents(
                None, QEvent.Type.DeferredDelete.value)
            QApplication.processEvents()

    def _lane_with_movement(self, shows_tab, blocks):
        from timeline.light_lane import LightLane
        lane = LightLane("Movers")
        lane.fixture_targets = ["TestGroup"]
        envelope = LightBlock(start_time=0.0, end_time=8.0,
                              effect_name="", movement_blocks=list(blocks))
        lane.light_blocks = [envelope]
        shows_tab._add_lane_widget(lane)
        return shows_tab.lane_widgets[-1]

    def test_empty_selection_returns_nothing(self, shows_tab):
        self._lane_with_movement(shows_tab, [_block()])
        assert shows_tab.selected_movement_blocks() == []

    def test_envelope_selection_returns_its_movement_blocks(self, shows_tab):
        first, second = _block(), _block(start_time=4.0, end_time=8.0)
        lane_widget = self._lane_with_movement(shows_tab, [first, second])
        widget = lane_widget.get_all_block_widgets()[0]
        shows_tab.selection_manager.select(widget)
        assert shows_tab.selected_movement_blocks() == [first, second]

    def test_explicit_sublane_selection_wins(self, shows_tab):
        first, second = _block(), _block(start_time=4.0, end_time=8.0)
        lane_widget = self._lane_with_movement(shows_tab, [first, second])
        widget = lane_widget.get_all_block_widgets()[0]
        shows_tab.selection_manager.select(widget)
        widget.selected_sublane_type = "movement"
        widget.selected_sublane_block = second
        assert shows_tab.selected_movement_blocks() == [second]

    def test_non_movement_sublane_selection_does_not_count(self, shows_tab):
        block = _block()
        lane_widget = self._lane_with_movement(shows_tab, [block])
        widget = lane_widget.get_all_block_widgets()[0]
        widget.selected_sublane_type = "dimmer"
        widget.selected_sublane_block = object()
        assert shows_tab.selected_movement_blocks() == []

    def test_refresh_movement_targets_is_safe(self, shows_tab):
        self._lane_with_movement(shows_tab, [_block()])
        shows_tab.refresh_movement_targets()  # must not raise
