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
- PLACE MARK: the Stage tab's toggle arms StageView's click mode and a
  left click drops a MARK there - placement only, touching no show
  data. Reworked 2026-08-09: it used to also assign the target to the
  Shows tab's selected movement blocks, which duplicated both the MARKS
  "+" button and the movement block dialog's mark picker, and forced a
  cross-tab selection carry. One job per surface now.

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


class TestStageTabPlaceMark:
    """PLACE MARK drops a mark on the plan and touches NOTHING else
    (user call 2026-08-09).

    It used to also assign the clicked target to whatever movement
    blocks were selected in the Shows tab, which duplicated both the
    MARKS "+" button (creating) and the movement block dialog
    (assigning), and forced a cross-tab selection carry. One job per
    surface now: the Stage tab places marks, the dialog picks which
    mark a block uses, the Live POSITION pool aims real movers at one.
    """

    @pytest.fixture
    def stage_tab(self, qapp):
        from gui.tabs.stage_tab import StageTab
        tab = StageTab(_mover_config(), parent=None)
        yield tab
        tab.deleteLater()

    def test_button_arms_the_view(self, stage_tab):
        assert stage_tab.aim_btn.isCheckable()
        assert stage_tab.stage_view.aim_mode is False
        stage_tab.aim_btn.setChecked(True)
        assert stage_tab.stage_view.aim_mode is True
        stage_tab.aim_btn.setChecked(False)
        assert stage_tab.stage_view.aim_mode is False

    def test_click_places_a_mark_at_the_point(self, stage_tab):
        before = set(stage_tab.config.spots)
        stage_tab._on_aim_clicked(2.0, -1.5, False)
        created = set(stage_tab.config.spots) - before
        assert len(created) == 1
        spot = stage_tab.config.spots[created.pop()]
        assert (spot.x, spot.y, spot.z) == (2.0, -1.5, 0.0)

    def test_click_writes_no_show_data(self, stage_tab):
        """The whole point of the 2026-08-09 simplification."""
        block = _block(target_spot_name="Mark")
        stage_tab._on_aim_clicked(2.0, -1.5, False)
        assert block.target_spot_name == "Mark"
        assert block.target_point is None

    def test_needs_no_timeline_selection(self, stage_tab):
        """It is a rig-setup tool: nothing has to be selected anywhere."""
        stage_tab._on_aim_clicked(1.0, 1.0, False)   # must not raise
        assert stage_tab.config.spots

    def test_clicking_an_existing_mark_selects_it(self, stage_tab):
        from gui.tabs.stage_tab import MARK_SNAP_M
        before = set(stage_tab.config.spots)
        existing = stage_tab.config.spots["Mark"]
        stage_tab._on_aim_clicked(existing.x + MARK_SNAP_M / 2,
                                  existing.y, False)
        assert set(stage_tab.config.spots) == before, "no duplicate mark"

    def test_selecting_an_existing_mark_never_moves_it(self, stage_tab):
        from gui.tabs.stage_tab import MARK_SNAP_M
        existing = stage_tab.config.spots["Mark"]
        before = (existing.x, existing.y, existing.z)
        stage_tab._on_aim_clicked(existing.x + MARK_SNAP_M / 2,
                                  existing.y, False)
        moved = stage_tab.config.spots["Mark"]
        assert (moved.x, moved.y, moved.z) == before

    def test_two_distant_clicks_make_two_marks(self, stage_tab):
        before = len(stage_tab.config.spots)
        stage_tab._on_aim_clicked(4.0, 4.0, False)
        stage_tab._on_aim_clicked(-4.0, -4.0, False)
        assert len(stage_tab.config.spots) == before + 2

    def test_a_placed_mark_is_selected_for_renaming(self, stage_tab):
        stage_tab._on_aim_clicked(3.0, 3.0, False)
        current = stage_tab.marks_list.currentItem()
        assert current is not None
        assert current.text() in stage_tab.config.spots

    def test_placing_disarms_the_mode(self, stage_tab):
        """Reported 2026-08-09: a sticky placement mode dropped a mark
        on every following click, including ones meant to select a
        fixture. One mark per arm."""
        stage_tab.aim_btn.setChecked(True)
        stage_tab._on_aim_clicked(3.0, 3.0, False)
        assert stage_tab.aim_btn.isChecked() is False
        assert stage_tab.stage_view.aim_mode is False

    def test_shift_click_stays_armed_for_a_row_of_marks(self, stage_tab):
        stage_tab.aim_btn.setChecked(True)
        before = len(stage_tab.config.spots)
        stage_tab._on_aim_clicked(3.0, 3.0, True)
        assert stage_tab.aim_btn.isChecked() is True
        stage_tab._on_aim_clicked(-3.0, 3.0, True)
        assert len(stage_tab.config.spots) == before + 2

    def test_selecting_an_existing_mark_stays_armed(self, stage_tab):
        """Nothing was placed, so the arm has not been spent."""
        from gui.tabs.stage_tab import MARK_SNAP_M
        existing = stage_tab.config.spots["Mark"]
        stage_tab.aim_btn.setChecked(True)
        stage_tab._on_aim_clicked(existing.x + MARK_SNAP_M / 2,
                                  existing.y, False)
        assert stage_tab.aim_btn.isChecked() is True


class TestPlaceMarkSnapsToGrid:
    """A mark placed off-grid next to snapped rig geometry is wrong, so
    the click honours the Stage tab's Snap to grid setting."""

    @pytest.fixture
    def view(self, qapp):
        from gui.StageView import StageView
        view = StageView()
        view.set_config(_mover_config())
        yield view
        view.deleteLater()

    def _click_at(self, view, x_m, y_m):
        from PyQt6.QtCore import QPointF, Qt
        received = []
        view.aim_clicked.connect(lambda x, y, k: received.append((x, y)))
        view.set_aim_mode(True)
        x_px, y_px = view.meters_to_pixels(x_m, y_m)
        view.mousePressEvent(_mouse_press(
            view, view.mapFromScene(QPointF(x_px, y_px)),
            Qt.KeyboardModifier.NoModifier))
        return received[0]

    def test_snapped_click_lands_on_the_grid(self, view):
        view.set_snap_to_grid(True)
        view.grid_size_m = 0.5
        x, y = self._click_at(view, 1.18, -0.87)
        assert x == pytest.approx(1.0, abs=0.01)
        assert y == pytest.approx(-1.0, abs=0.01)

    def test_unsnapped_click_keeps_the_exact_point(self, view):
        view.set_snap_to_grid(False)
        x, y = self._click_at(view, 1.18, -0.87)
        assert x == pytest.approx(1.18, abs=0.05)
        assert y == pytest.approx(-0.87, abs=0.05)


class TestDeleteMarksOnThePlan:
    """Reported 2026-08-09: Delete did not remove marks.

    The only Delete binding was a WidgetShortcut on the MARKS list, so
    it fired only while that list held keyboard focus - selecting a mark
    on the plan (where you placed it, and where you are looking) and
    pressing Delete did nothing."""

    @pytest.fixture
    def stage_tab(self, qapp):
        from gui.tabs.stage_tab import StageTab
        tab = StageTab(_mover_config(), parent=None)
        yield tab
        tab.deleteLater()

    def _press(self, view, key):
        from PyQt6.QtCore import QEvent, Qt
        from PyQt6.QtGui import QKeyEvent
        view.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, key,
                                     Qt.KeyboardModifier.NoModifier))

    def test_delete_removes_the_mark_selected_on_the_plan(self, stage_tab):
        from PyQt6.QtCore import Qt
        view = stage_tab.stage_view
        view.spots["Mark"].setSelected(True)
        self._press(view, Qt.Key.Key_Delete)
        assert "Mark" not in stage_tab.config.spots
        assert "Mark" not in view.spots

    def test_backspace_works_too(self, stage_tab):
        from PyQt6.QtCore import Qt
        view = stage_tab.stage_view
        view.spots["Mark"].setSelected(True)
        self._press(view, Qt.Key.Key_Backspace)
        assert "Mark" not in stage_tab.config.spots

    def test_a_freshly_placed_mark_can_be_deleted_immediately(self,
                                                              stage_tab):
        """The 'oops, wrong spot' flow: place, then Delete."""
        from PyQt6.QtCore import Qt
        before = set(stage_tab.config.spots)
        stage_tab._on_aim_clicked(3.5, 2.5, False)
        placed = (set(stage_tab.config.spots) - before).pop()
        self._press(stage_tab.stage_view, Qt.Key.Key_Delete)
        assert placed not in stage_tab.config.spots

    def test_delete_leaves_fixtures_alone(self, stage_tab):
        """No undo on this tab - Delete must not reach the rig."""
        from PyQt6.QtCore import Qt
        view = stage_tab.stage_view
        before = len(stage_tab.config.fixtures)
        for item in view.scene.items():
            if hasattr(item, "fixture"):
                item.setSelected(True)
        self._press(view, Qt.Key.Key_Delete)
        assert len(stage_tab.config.fixtures) == before

    def test_the_marks_list_follows(self, stage_tab):
        from PyQt6.QtCore import Qt
        view = stage_tab.stage_view
        view.spots["Mark"].setSelected(True)
        self._press(view, Qt.Key.Key_Delete)
        names = {stage_tab.marks_list.item(i).text()
                 for i in range(stage_tab.marks_list.count())}
        assert "Mark" not in names
