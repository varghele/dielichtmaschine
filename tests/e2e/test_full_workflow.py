"""End-to-end user workflow: universe -> fixtures -> stage -> structure ->
timeline -> playback, driven through the real MainWindow.

Every step clicks the widget a user would click and then asserts on the
Configuration model. The last test walks the whole path in one go and adds a
save/load round-trip, proving the authored project survives serialization.

Four regressions this file exists to pin (all fixed, all previously invisible
to the suite):

1. Structure "+ New" silently did nothing behind a dead
   ``_ensure_shows_directory()`` gate.  -> ``TestStep4Structure``
2. A straight truss had no way to set its length.  -> ``TestStep3Stage``
   (``test_truss_length_action_exists_and_resizes``)
3. Right-click "Set Orientation..." only rebound an inline panel that is
   unreachable in the inline inspector; it now also opens the modal
   ``OrientationDialog``.  -> ``TestStep3Stage``
   (``test_set_orientation_context_action_opens_modal_and_writes_back``)
4. The Shows/Timeline tab must genuinely author and play back a show.
   -> ``TestStep5Timeline`` + ``TestStep6Playback``
"""

from __future__ import annotations

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import (QComboBox, QDialog, QDoubleSpinBox, QLineEdit,
                             QTreeWidget)

from tests.e2e.conftest import (MH_MFR, MH_MODE_8CH, MH_MODEL, MH_QXF, PAR_MFR,
                                PAR_MODE_6CH, PAR_MODEL, PAR_QXF, TAB_CONFIG,
                                TAB_FIXTURES, TAB_SHOWS, TAB_STAGE,
                                TAB_STRUCTURE, goto_tab, project_path)

pytestmark = pytest.mark.e2e

TARGET_IP = "10.0.0.42"
SHOW_NAME = "E2E Show"
WASH_GROUP = "Wash"
MOVER_GROUP = "Movers"
WASH_LAYER = "Front Wash"

# Addresses we patch the fixtures to, so their channel footprints never
# overlap once the modes below are selected.
PAR1_ADDR, PAR2_ADDR, MH_ADDR = 1, 11, 21

# 0-based offsets inside the 512-byte universe array, derived from the
# bundled .qxf modes (see conftest for the channel order).
PAR_DIMMER, PAR_RED, PAR_GREEN, PAR_BLUE, PAR_WHITE, PAR_STROBE = range(6)
MH_PAN, MH_TILT, _MH_SPEED, MH_DIMMER, MH_SHUTTER = range(5)


# ===========================================================================
# Step drivers. Each one performs the real user actions for one workflow
# step and returns nothing; assertions live in the tests that call them.
# ===========================================================================
def step1_create_artnet_universe(window):
    """Setup > Universes: add a universe, make it ArtNet, set the target IP."""
    goto_tab(window, TAB_CONFIG)
    tab = window.config_tab

    tab.add_universe_btn.click()

    # `_add_universe` selects the universe it just created, which is what the
    # inspector edits below operate on.
    tab.protocol_buttons["ArtNet"].click()

    assert tab.artnet_ip.isEnabled(), "broadcast checkbox must not be latched on"
    tab.artnet_ip.clear()  # clear() does not emit textEdited...
    QTest.keyClicks(tab.artnet_ip, TARGET_IP)  # ...keyClicks does, per char.


def step2_patch_fixtures(window, dialogs):
    """Setup > Fixtures: add 2 PARs + 1 moving head via the browser dialog,
    create two groups, then patch mode / address / group in the inspector."""
    goto_tab(window, TAB_FIXTURES)
    tab = window.fixtures_tab

    def browse(qxf_rel, quantity):
        wanted = project_path(qxf_rel)

        def handler(dialog):
            # Drive the dialog's real filter + selection, not its internals.
            # Handlers run inside a Qt slot, so report problems via
            # dialogs.fail() rather than raising (see conftest).
            dialog.search_box.setText(_stem(wanted))
            row = _row_for_path(dialog, wanted)
            if row is None:
                dialogs.fail(f"{wanted} not offered by the fixture browser")
                return QDialog.DialogCode.Rejected
            dialog.list_widget.setCurrentRow(row)
            dialog.quantity_spin.setValue(quantity)
            if not dialog._ok_button.isEnabled():
                dialogs.fail("browser OK button must enable once a row is current")
                return QDialog.DialogCode.Rejected
            return QDialog.DialogCode.Accepted

        dialogs.on("FixtureBrowserDialog", handler)
        tab.add_btn.click()

    browse(PAR_QXF, 2)
    browse(MH_QXF, 1)

    for group, role in ((WASH_GROUP, "wash"), (MOVER_GROUP, "key")):
        dialogs.on("Add New Group", _group_dialog_handler(group, role))
        tab.group_add_btn.click()

    # Table row index == config.fixtures index (sorting is disabled).
    _patch_row(tab, 0, PAR_MODE_6CH, PAR1_ADDR, WASH_GROUP)
    _patch_row(tab, 1, PAR_MODE_6CH, PAR2_ADDR, WASH_GROUP)
    _patch_row(tab, 2, MH_MODE_8CH, MH_ADDR, MOVER_GROUP)


def step3_place_on_stage(window, dialogs, inputs, menus):
    """Setup > Stage: layer, positions, truss (length + height), docking,
    orientation via the right-click modal."""
    goto_tab(window, TAB_STAGE)
    tab = window.stage_tab
    view = tab.stage_view
    view.resize(900, 700)  # give the view a viewport so hit-testing resolves

    # --- a stage layer, through the real "+ LAYER" chip and its dialog ----
    dialogs.on("Add Stage Layer", _layer_dialog_handler(WASH_LAYER, 2.5))
    tab.add_layer_chip.click()

    # --- a stage element and a straight truss from the palette -----------
    # Both land at stage centre; drag the riser clear so the truss is the
    # topmost item at its own centre (the context menus below hit-test).
    tab.element_buttons["drum-riser"].click()
    riser_item = view.stage_element_items[-1]
    tab.element_buttons["truss-straight"].click()
    truss_item = view.stage_element_items[-1]
    riser_item.setPos(*view.meters_to_pixels(-3.5, 2.0))

    # --- positions -------------------------------------------------------
    # The only production path that moves a fixture is FixtureItem's
    # mouseMoveEvent -> setPos -> view.save_positions_to_config(). Offscreen
    # Qt does not deliver synthetic drags to QGraphicsItems, so we do the
    # setPos + save the drag would have done.
    _place(view, _par_names(window)[0], -2.0, -1.0)
    _place(view, _par_names(window)[1], 2.0, -1.0)
    _place(view, _mh_name(window), 3.0, -2.5)
    view.save_positions_to_config()

    # --- assign PAR 1 to the layer via the right-click submenu ------------
    par1_item = view.fixtures[_par_names(window)[0]]
    menus.choose(f"{WASH_LAYER} (2.5 m)")
    _right_click(view, par1_item)

    # --- truss length, through the item's real context menu --------------
    menus.choose("Truss Length...")
    inputs.answer("Truss Length", 6.0)
    _item_context_menu(view, truss_item)

    # --- truss height ----------------------------------------------------
    menus.choose("Truss Height...")
    inputs.answer("Truss Height", 5.0)
    _item_context_menu(view, truss_item)

    # --- dock the moving head onto the truss -----------------------------
    mh_item = view.fixtures[_mh_name(window)]
    mh_item.setPos(truss_item.pos())
    view.handle_fixture_drop(mh_item)  # what FixtureItem.mouseReleaseEvent calls

    # --- orientation via right-click "Set Orientation..." -----------------
    dialogs.on("OrientationDialog", _orientation_dialog_handler("standing", 2.5))
    menus.choose("Set Orientation...")
    _right_click(view, par1_item)


def step4_create_show_structure(window, inputs):
    """Show > Structure: create a show, edit part 1, add part 2."""
    goto_tab(window, TAB_STRUCTURE)
    tab = window.structure_tab

    inputs.answer("Create New Show", SHOW_NAME)
    tab.new_show_btn.click()

    tab._cards[0].clicked.emit(0)  # select part 1 the way PartCard does

    tab.part_name_edit.clear()
    QTest.keyClicks(tab.part_name_edit, "Verse")  # textEdited, per char
    tab.bpm_spin.setValue(128.0)
    tab.bars_spin.setValue(4)
    # set_signature() is the load path and blocks signals; the user edits the
    # numerator spinbox, which is what emits TimeSignatureWidget.valueChanged.
    tab.signature_widget.numerator.setValue(3)
    tab.transition_combo.setCurrentText("gradual")

    tab.add_part_tile.click()


def step5_build_timeline(window, dialogs):
    """Show > Timeline: add a lane targeting the Wash group, add an effect
    block (dimmer + colour sub-blocks), recolour it red, save."""
    goto_tab(window, TAB_SHOWS)
    tab = window.shows_tab

    tab.add_lane_btn.click()
    lane_widget = tab.lane_widgets[0]

    dialogs.on("TargetSelectionDialog", _target_dialog_handler(dialogs, WASH_GROUP))
    lane_widget.edit_targets_btn.click()

    lane_widget.timeline_widget.playhead_position = 0.0
    lane_widget.add_block_button.click()

    block_widget = lane_widget.light_block_widgets[0]
    colour_block = block_widget.block.colour_blocks[0]
    dialogs.on("ColourBlockDialog", _colour_dialog_handler(255, 0, 0))
    # The same call the block widget's double-click / context menu makes.
    block_widget.open_sublane_dialog("colour", colour_block)

    tab.save_btn.click()


def step6_build_playback_controller(window, monkeypatch):
    """Mirror ShowsTab._init_artnet_controller with a socket-free sender."""
    import utils.artnet.shows_artnet_controller as sac
    from utils.fixture_utils import load_fixture_definitions_from_qlc

    sent = []

    class StubSender:
        MAX_SEND_RATE_HZ = 44

        def __init__(self, target_ip="255.255.255.255", target_port=6454):
            self.target_ip = target_ip

        def send_dmx(self, universe, dmx_data, force=False):
            sent.append((universe, bytes(dmx_data)))
            return True

        def set_target_ip(self, ip): self.target_ip = ip
        def close(self): pass

    monkeypatch.setattr(sac, "ArtNetSender", StubSender)

    tab = window.shows_tab
    config = window.config
    config.ensure_universes_for_fixtures()
    models = {(f.manufacturer, f.model) for f in config.fixtures}
    fixture_defs = load_fixture_definitions_from_qlc(models)

    fed = []
    controller = sac.ShowsArtNetController(
        config=config,
        fixture_definitions=fixture_defs,
        song_structure=tab.song_structure,
        target_ip="255.255.255.255",
        local_dmx_callback=lambda u, data: fed.append((u, bytes(data))),
    )
    controller.set_light_lanes([w.lane for w in tab.lane_widgets])
    controller.enable_output()
    assert controller._position_callback is None, \
        "no position callback: the test pins current_time itself"
    return controller, sent, fed


def render_at(controller, t):
    """Run exactly one frame of the real DMX loop body at time ``t``."""
    controller.current_time = t
    controller._update_and_send_dmx()
    return controller.dmx_manager.get_dmx_data(1)


# ===========================================================================
# Helpers
# ===========================================================================
def _stem(path):
    import os
    return os.path.splitext(os.path.basename(path))[0]


def _row_for_path(dialog, path):
    for i in range(dialog.list_widget.count()):
        item = dialog.list_widget.item(i)
        if item.data(Qt.ItemDataRole.UserRole) == path and not item.isHidden():
            return i
    return None


def _group_dialog_handler(name, role):
    def handler(dialog):
        # The ad-hoc QDialog keeps its widgets as locals; reach them by type.
        dialog.findChild(QLineEdit).setText(name)
        dialog.findChild(QComboBox).setCurrentText(role)
        return QDialog.DialogCode.Accepted
    return handler


def _layer_dialog_handler(name, z_height):
    def handler(dialog):
        dialog.findChild(QLineEdit).setText(name)
        dialog.findChild(QDoubleSpinBox).setValue(z_height)
        return QDialog.DialogCode.Accepted
    return handler


def _orientation_dialog_handler(preset, z_height):
    def handler(dialog):
        dialog.panel.preset_buttons[preset].click()
        dialog.panel.z_spin.setValue(z_height)
        return QDialog.DialogCode.Accepted
    return handler


def _target_dialog_handler(dialogs, group_name):
    def handler(dialog):
        tree = dialog.findChild(QTreeWidget)
        for i in range(tree.topLevelItemCount()):
            item = tree.topLevelItem(i)
            if item.data(0, Qt.ItemDataRole.UserRole)["name"] == group_name:
                item.setCheckState(0, Qt.CheckState.Checked)
                return QDialog.DialogCode.Accepted
        dialogs.fail(f"group {group_name!r} not offered by the target dialog")
        return QDialog.DialogCode.Rejected
    return handler


def _colour_dialog_handler(red, green, blue):
    def handler(dialog):
        for name, value in (("red", red), ("green", green), ("blue", blue)):
            dialog.sliders[name][1].setValue(value)  # [1] is the spinbox accept() reads
        dialog.accept()  # the dialog's own write-back into the ColourBlock
        return QDialog.DialogCode.Accepted
    return handler


def _patch_row(tab, row, mode, address, group):
    tab.table.selectRow(row)
    # The mode combo labels items "<name> (<n>ch)"; its handler takes the index.
    index = next(i for i in range(tab.insp_mode.count())
                 if tab.insp_mode.itemText(i).startswith(f"{mode} ("))
    tab.insp_mode.setCurrentIndex(index)
    tab.insp_address.setValue(address)
    tab.insp_group.setCurrentText(group)


def _place(view, fixture_name, x_m, y_m):
    item = view.fixtures[fixture_name]
    item.setPos(*view.meters_to_pixels(x_m, y_m))


def _viewport_pos(view, item):
    pos = view.mapFromScene(item.sceneBoundingRect().center())
    assert view.itemAt(pos) is item, f"{item} is not on top at {pos}"
    return pos


def _right_click(view, item):
    """Right-press on the view: StageView.mousePressEvent opens the fixture
    context menu (QMenu.exec is patched to pick an action)."""
    QTest.mouseClick(view.viewport(), Qt.MouseButton.RightButton,
                     Qt.KeyboardModifier.NoModifier, _viewport_pos(view, item))


def _item_context_menu(view, item):
    """Deliver a real QContextMenuEvent so QGraphicsView routes it to the
    item under the cursor, which is how StageElementItem.contextMenuEvent
    fires in the app. QGraphicsSceneContextMenuEvent cannot be built directly
    in PyQt6, so we go in through the viewport as Windows does."""
    from PyQt6.QtGui import QContextMenuEvent
    from PyQt6.QtWidgets import QApplication
    pos = _viewport_pos(view, item)
    event = QContextMenuEvent(QContextMenuEvent.Reason.Mouse, pos,
                              view.viewport().mapToGlobal(pos))
    QApplication.sendEvent(view.viewport(), event)


def _par_names(window):
    return [f.name for f in window.config.fixtures if f.model == PAR_MODEL]


def _mh_name(window):
    return next(f.name for f in window.config.fixtures if f.model == MH_MODEL)


def _fixture(window, name):
    return next(f for f in window.config.fixtures if f.name == name)


# ===========================================================================
# Step 1: universes
# ===========================================================================
class TestStep1Universe:
    def test_add_universe_sets_artnet_and_target_ip(self, main_window):
        step1_create_artnet_universe(main_window)

        universes = main_window.config.universes
        assert list(universes) == [1]
        output = universes[1].output
        assert output["plugin"] == "ArtNet"
        assert output["parameters"]["ip"] == TARGET_IP

        from gui.tabs.configuration_tab import is_ready
        assert is_ready(universes[1]), "an ArtNet universe with an IP is 'ready'"

    def test_switching_protocol_resets_parameters(self, main_window):
        """Documents a real trap: `_on_protocol_selected` clears the params
        dict, so a target IP set before the protocol switch is lost."""
        step1_create_artnet_universe(main_window)
        tab = main_window.config_tab

        tab.protocol_buttons["E1.31"].click()
        assert main_window.config.universes[1].output["plugin"] == "E1.31"
        assert main_window.config.universes[1].output["parameters"]["ip"] != TARGET_IP


# ===========================================================================
# Step 2: fixtures
# ===========================================================================
class TestStep2Fixtures:
    def test_browser_dialog_patches_two_types_into_groups(self, main_window, dialogs):
        step1_create_artnet_universe(main_window)
        step2_patch_fixtures(main_window, dialogs)

        config = main_window.config
        assert len(config.fixtures) == 3

        pars = [f for f in config.fixtures if f.model == PAR_MODEL]
        assert len(pars) == 2
        assert all(f.manufacturer == PAR_MFR for f in pars)
        assert all(f.current_mode == PAR_MODE_6CH for f in pars)
        assert all(f.group == WASH_GROUP for f in pars)
        assert [f.address for f in pars] == [PAR1_ADDR, PAR2_ADDR]
        assert all(f.universe == 1 for f in pars)

        mh = _fixture(main_window, _mh_name(main_window))
        assert (mh.manufacturer, mh.model) == (MH_MFR, MH_MODEL)
        assert mh.current_mode == MH_MODE_8CH
        assert mh.group == MOVER_GROUP
        assert mh.address == MH_ADDR
        assert mh.type == "MH"

        assert set(config.groups) == {WASH_GROUP, MOVER_GROUP}
        assert len(config.groups[WASH_GROUP].fixtures) == 2
        assert len(config.groups[MOVER_GROUP].fixtures) == 1
        assert config.groups[WASH_GROUP].lighting_role == "wash"

    def test_group_capabilities_reflect_the_patched_modes(self, main_window, dialogs):
        step1_create_artnet_universe(main_window)
        step2_patch_fixtures(main_window, dialogs)

        from utils.target_resolver import detect_targets_capabilities
        wash = detect_targets_capabilities([WASH_GROUP], main_window.config)
        assert wash.has_dimmer and wash.has_colour
        assert not wash.has_movement

        movers = detect_targets_capabilities([MOVER_GROUP], main_window.config)
        assert movers.has_movement and movers.has_dimmer

    @pytest.mark.xfail(
        strict=True,
        reason="BUG: utils/fixture_utils.py:114 detect_fixture_group_capabilities "
               "walks fixture_def['channels'] (every channel the .qxf declares) "
               "instead of the channels of fixture.current_mode. The Hero Spot 60 "
               "in '8 Channel' mode has no Color/Gobo/Prism channel, yet the group "
               "reports has_colour/has_special, so the timeline offers colour and "
               "special sublanes whose DMX goes nowhere - FixtureChannelMap "
               "(utils/artnet/dmx_manager.py:44) does respect current_mode.")
    def test_capabilities_must_respect_the_patched_mode(self, main_window, dialogs):
        step1_create_artnet_universe(main_window)
        step2_patch_fixtures(main_window, dialogs)

        from utils.target_resolver import detect_targets_capabilities
        movers = detect_targets_capabilities([MOVER_GROUP], main_window.config)
        assert not movers.has_colour, "8 Channel mode exposes no colour channel"
        assert not movers.has_special, "8 Channel mode exposes no gobo/prism channel"


# ===========================================================================
# Step 3: stage
# ===========================================================================
class TestStep3Stage:
    def test_positions_layer_and_element_land_in_the_config(
            self, main_window, dialogs, inputs, menus):
        step1_create_artnet_universe(main_window)
        step2_patch_fixtures(main_window, dialogs)
        step3_place_on_stage(main_window, dialogs, inputs, menus)

        config = main_window.config

        layers = {layer.name: layer for layer in config.stage_layers}
        assert WASH_LAYER in layers
        assert layers[WASH_LAYER].z_height == 2.5
        # Placing a truss auto-creates its own layer.
        assert "Truss 1" in layers

        par1 = _fixture(main_window, _par_names(main_window)[0])
        assert par1.x == pytest.approx(-2.0, abs=0.01)
        assert par1.y == pytest.approx(-1.0, abs=0.01)
        assert par1.layer == WASH_LAYER
        assert par1.z == pytest.approx(2.5)
        assert par1.z_uses_group_default is False

        kinds = [element.kind for element in config.stage_elements]
        assert kinds == ["drum-riser", "truss-straight"]

    def test_truss_length_action_exists_and_resizes(
            self, main_window, dialogs, inputs, menus):
        """Regression: the straight truss had no length control at all.
        MenuDriver raises if 'Truss Length...' is missing from the menu."""
        step1_create_artnet_universe(main_window)
        step2_patch_fixtures(main_window, dialogs)
        step3_place_on_stage(main_window, dialogs, inputs, menus)

        truss = next(e for e in main_window.config.stage_elements
                     if e.kind == "truss-straight")
        assert truss.width == 6.0, "truss length must come from the context menu"
        assert truss.depth == 0.3, "a straight truss keeps its catalog profile"
        assert ("Truss Length", "getDouble") in inputs.asked

    def test_truss_height_moves_its_layer_and_docked_fixtures(
            self, main_window, dialogs, inputs, menus):
        step1_create_artnet_universe(main_window)
        step2_patch_fixtures(main_window, dialogs)
        step3_place_on_stage(main_window, dialogs, inputs, menus)

        config = main_window.config
        truss_layer = config.get_stage_layer("Truss 1")
        assert truss_layer.z_height == 5.0

        mh = _fixture(main_window, _mh_name(main_window))
        truss = next(e for e in config.stage_elements if e.kind == "truss-straight")
        assert mh.docked_to == truss.element_id
        assert mh.layer == "Truss 1"
        assert mh.z == pytest.approx(5.0)

    def test_set_orientation_context_action_opens_modal_and_writes_back(
            self, main_window, dialogs, inputs, menus):
        """Regression: 'Set Orientation...' used to only rebind an inline
        panel that is unreachable in the inline inspector, so nothing was
        written. The dialogs driver raises if the modal never opens, and the
        mounting assertion fails if it opens but never writes back."""
        step1_create_artnet_universe(main_window)
        step2_patch_fixtures(main_window, dialogs)
        step3_place_on_stage(main_window, dialogs, inputs, menus)

        assert "OrientationDialog" in dialogs.seen, \
            "right-click Set Orientation... must open the modal dialog"

        par1 = _fixture(main_window, _par_names(main_window)[0])
        assert par1.mounting == "standing"
        assert par1.pitch == pytest.approx(-90.0)  # PRESET_VALUES['standing']
        assert par1.yaw == pytest.approx(0.0)
        assert par1.z == pytest.approx(2.5)
        assert par1.orientation_uses_group_default is False

    def test_undocking_clears_the_truss_layer(
            self, main_window, dialogs, inputs, menus):
        step1_create_artnet_universe(main_window)
        step2_patch_fixtures(main_window, dialogs)
        step3_place_on_stage(main_window, dialogs, inputs, menus)

        view = main_window.stage_tab.stage_view
        mh_item = view.fixtures[_mh_name(main_window)]
        mh_item.setPos(*view.meters_to_pixels(4.5, 2.5))  # far from the truss
        view.handle_fixture_drop(mh_item)

        mh = _fixture(main_window, _mh_name(main_window))
        assert mh.docked_to == ""
        assert mh.layer == ""


# ===========================================================================
# Step 4: show structure
# ===========================================================================
class TestStep4Structure:
    def test_new_show_button_actually_creates_the_show(self, main_window, inputs):
        """Regression: '+ New' returned silently behind a dead
        `_ensure_shows_directory()` gate, so config.shows stayed empty."""
        goto_tab(main_window, TAB_STRUCTURE)
        assert main_window.config.shows == {}

        inputs.answer("Create New Show", SHOW_NAME)
        main_window.structure_tab.new_show_btn.click()

        assert SHOW_NAME in main_window.config.shows, \
            "'+ New' must create the show even with no shows_directory set"
        show = main_window.config.shows[SHOW_NAME]
        assert [p.name for p in show.parts] == ["Intro"]
        assert main_window.structure_tab.show_combo.currentText() == SHOW_NAME

    def test_part_edits_and_new_part_land_in_the_model(self, main_window, inputs):
        step4_create_show_structure(main_window, inputs)

        parts = main_window.config.shows[SHOW_NAME].parts
        assert len(parts) == 2

        first = parts[0]
        assert first.name == "Verse"
        assert first.bpm == pytest.approx(128.0)
        assert first.num_bars == 4
        assert first.signature == "3/4"
        assert first.transition == "gradual"

        assert parts[1].name == "Part 2"
        assert parts[1].bpm == pytest.approx(120.0)

    def test_show_structure_drives_the_song_structure(self, main_window, inputs):
        step4_create_show_structure(main_window, inputs)
        goto_tab(main_window, TAB_SHOWS)

        song_structure = main_window.shows_tab.song_structure
        assert song_structure is not None
        # Part 1: 4 bars of 3/4 at 128 BPM = 12 beats = 5.625 s.
        assert song_structure.get_bpm_at_time(1.0) == pytest.approx(128.0)
        assert song_structure.get_bpm_at_time(8.0) == pytest.approx(120.0)


# ===========================================================================
# Step 5: timeline
# ===========================================================================
class TestStep5Timeline:
    def test_lane_block_and_sub_blocks_are_authored_and_saved(
            self, main_window, dialogs, inputs):
        step1_create_artnet_universe(main_window)
        step2_patch_fixtures(main_window, dialogs)
        step4_create_show_structure(main_window, inputs)
        step5_build_timeline(main_window, dialogs)

        tab = main_window.shows_tab
        assert len(tab.lane_widgets) == 1
        lane = tab.lane_widgets[0].lane
        assert lane.fixture_targets == [WASH_GROUP]
        assert len(lane.light_blocks) == 1

        block = lane.light_blocks[0]
        assert (block.start_time, block.end_time) == (0.0, 4.0)
        assert len(block.dimmer_blocks) == 1
        assert len(block.colour_blocks) == 1
        # The Wash group has no movement channels, so no movement sub-block.
        assert block.movement_blocks == []

        dimmer = block.dimmer_blocks[0]
        assert dimmer.intensity == pytest.approx(255.0)
        assert dimmer.effect_type == "static"

        colour = block.colour_blocks[0]
        assert (colour.red, colour.green, colour.blue) == (255.0, 0.0, 0.0)

        # save_btn -> save_to_config() writes the runtime lanes into the model.
        saved = main_window.config.shows[SHOW_NAME].timeline_data.lanes
        assert len(saved) == 1
        assert saved[0].fixture_targets == [WASH_GROUP]
        assert len(saved[0].light_blocks[0].colour_blocks) == 1

    @pytest.mark.xfail(
        strict=True,
        reason="BUG: an RGB-slider-only edit on a 6-channel PAR is recorded as "
               "color_mode='Wheel'. Two causes: utils/fixture_utils.py:197 "
               "get_color_wheel_options walks fixture_def['channels'] instead of "
               "the current_mode's channels, so a colour wheel is offered for a "
               "mode that has none; and timeline_ui/colour_block_dialog.py:418 "
               "accept() sets color_mode='Wheel' whenever wheel options exist, "
               "even when the user never touched the wheel combo. Harmless today "
               "(FixtureChannelMap finds no wheel channel in 6 Channel mode) but "
               "the block silently flips to the wheel colour if the fixture is "
               "later re-patched to 8 Channel mode.")
    def test_rgb_only_colour_edit_stays_in_rgb_mode(self, main_window, dialogs, inputs):
        step1_create_artnet_universe(main_window)
        step2_patch_fixtures(main_window, dialogs)
        step4_create_show_structure(main_window, inputs)
        step5_build_timeline(main_window, dialogs)

        colour = main_window.shows_tab.lane_widgets[0].lane.light_blocks[0].colour_blocks[0]
        assert colour.color_mode == "RGB"

    def test_adding_a_lane_without_a_show_is_warned_about(
            self, main_window, message_boxes):
        """A QMessageBox here is the correct behaviour: no show, no lane. The
        autouse modal guard records it, so we can assert it fired and that no
        lane was created."""
        goto_tab(main_window, TAB_SHOWS)
        message_boxes.expect("No Show Selected")

        main_window.shows_tab.add_lane_btn.click()

        assert main_window.shows_tab.lane_widgets == []
        assert [box[0] for box in message_boxes.shown] == ["warning"]


# ===========================================================================
# Step 6: playback -> real DMX
# ===========================================================================
class TestStep6Playback:
    @pytest.fixture
    def authored(self, main_window, dialogs, inputs, monkeypatch):
        step1_create_artnet_universe(main_window)
        step2_patch_fixtures(main_window, dialogs)
        step4_create_show_structure(main_window, inputs)
        step5_build_timeline(main_window, dialogs)
        controller, sent, fed = step6_build_playback_controller(main_window, monkeypatch)
        try:
            yield main_window, controller, sent, fed
        finally:
            controller.cleanup()

    def test_dmx_is_non_zero_inside_the_block(self, authored):
        window, controller, _sent, _fed = authored

        dmx = render_at(controller, 1.0)
        assert len(dmx) == 512

        for base in (PAR1_ADDR - 1, PAR2_ADDR - 1):
            assert dmx[base + PAR_DIMMER] == 255, "dimmer must be at full"
            assert dmx[base + PAR_RED] == 255, "colour block is pure red"
            assert dmx[base + PAR_GREEN] == 0
            assert dmx[base + PAR_BLUE] == 0
            assert dmx[base + PAR_WHITE] == 0
            # The PAR's shutter uses the ShutterStrobeSlowFast preset, which
            # DMXManager.strobe_channels does not list, so safe-idle leaves it
            # at 0 - which is "no strobe" for this preset. Pinned so a change
            # to that preset list has to be a deliberate one.
            assert dmx[base + PAR_STROBE] == 0

        # The moving head is in a different group; the lane never targets it.
        mh_base = MH_ADDR - 1
        assert dmx[mh_base + MH_DIMMER] == 0
        assert dmx[mh_base + MH_PAN] == 127, "safe idle centres pan/tilt"
        assert dmx[mh_base + MH_TILT] == 127
        assert dmx[mh_base + MH_SHUTTER] == 255, "safe idle opens the shutter"

    def test_dmx_is_zero_outside_the_block(self, authored):
        window, controller, _sent, _fed = authored

        render_at(controller, 1.0)  # inside
        dmx = render_at(controller, 6.0)  # the block ends at 4.0 s

        for base in (PAR1_ADDR - 1, PAR2_ADDR - 1):
            assert dmx[base + PAR_DIMMER] == 0
            assert dmx[base + PAR_RED] == 0
            assert dmx[base + PAR_GREEN] == 0
            assert dmx[base + PAR_BLUE] == 0

    def test_block_boundaries_are_half_open(self, authored):
        window, controller, _sent, _fed = authored
        base = PAR1_ADDR - 1

        assert render_at(controller, 0.0)[base + PAR_DIMMER] == 255
        assert render_at(controller, 3.999)[base + PAR_DIMMER] == 255
        assert render_at(controller, 4.0)[base + PAR_DIMMER] == 0

    def test_frames_reach_the_sender_and_the_visualizer_callback(self, authored):
        window, controller, sent, fed = authored

        render_at(controller, 1.0)

        # Universe 1 internally, 0-based on the wire.
        assert sent and sent[-1][0] == 0
        assert len(sent[-1][1]) == 512
        assert fed and fed[-1][0] == 1
        assert fed[-1][1][PAR1_ADDR - 1 + PAR_RED] == 255

    def test_muting_the_lane_silences_it(self, authored):
        window, controller, _sent, _fed = authored
        base = PAR1_ADDR - 1

        assert render_at(controller, 1.0)[base + PAR_DIMMER] == 255

        window.shows_tab.lane_widgets[0].mute_button.click()
        controller.active_block_ids.clear()
        controller.dmx_manager.clear_active_blocks()

        assert render_at(controller, 1.0)[base + PAR_DIMMER] == 0


# ===========================================================================
# The whole path, once, plus a save/load round-trip
# ===========================================================================
class TestFullWorkflow:
    def test_author_play_and_round_trip(
            self, main_window, dialogs, inputs, menus, monkeypatch, tmp_path):
        window = main_window

        step1_create_artnet_universe(window)
        step2_patch_fixtures(window, dialogs)
        step3_place_on_stage(window, dialogs, inputs, menus)
        step4_create_show_structure(window, inputs)
        step5_build_timeline(window, dialogs)
        controller, _sent, _fed = step6_build_playback_controller(window, monkeypatch)

        try:
            base = PAR1_ADDR - 1
            inside = render_at(controller, 1.0)
            assert inside[base + PAR_DIMMER] == 255
            assert inside[base + PAR_RED] == 255
            outside = render_at(controller, 6.0)
            assert outside[base + PAR_DIMMER] == 0
            assert outside[base + PAR_RED] == 0
        finally:
            controller.cleanup()

        # --- save / load round-trip --------------------------------------
        path = str(tmp_path / "e2e_project.yaml")
        window.config.save(path)

        from config.models import Configuration
        loaded = Configuration.load(path)

        # universes
        assert loaded.universes[1].output["plugin"] == "ArtNet"
        assert loaded.universes[1].output["parameters"]["ip"] == TARGET_IP

        # fixtures
        assert len(loaded.fixtures) == 3
        pars = sorted((f for f in loaded.fixtures if f.model == PAR_MODEL),
                      key=lambda f: f.address)
        assert [f.address for f in pars] == [PAR1_ADDR, PAR2_ADDR]
        assert all(f.current_mode == PAR_MODE_6CH for f in pars)
        assert all(f.group == WASH_GROUP for f in pars)
        assert pars[0].x == pytest.approx(-2.0, abs=0.01)
        assert pars[0].layer == WASH_LAYER
        assert pars[0].mounting == "standing"
        assert pars[0].pitch == pytest.approx(-90.0)

        mh = next(f for f in loaded.fixtures if f.model == MH_MODEL)
        assert mh.current_mode == MH_MODE_8CH
        assert mh.layer == "Truss 1"
        assert mh.z == pytest.approx(5.0)

        # groups
        assert set(loaded.groups) == {WASH_GROUP, MOVER_GROUP}
        assert loaded.groups[WASH_GROUP].lighting_role == "wash"
        assert len(loaded.groups[WASH_GROUP].fixtures) == 2

        # stage layers + elements
        assert {layer.name for layer in loaded.stage_layers} == {WASH_LAYER, "Truss 1"}
        assert loaded.get_stage_layer("Truss 1").z_height == 5.0
        truss = next(e for e in loaded.stage_elements if e.kind == "truss-straight")
        assert truss.width == 6.0
        assert truss.element_id == next(
            e for e in window.config.stage_elements
            if e.kind == "truss-straight").element_id
        assert mh.docked_to == truss.element_id
        assert any(e.kind == "drum-riser" for e in loaded.stage_elements)

        # show structure
        show = loaded.shows[SHOW_NAME]
        assert [p.name for p in show.parts] == ["Verse", "Part 2"]
        assert show.parts[0].bpm == pytest.approx(128.0)
        assert show.parts[0].signature == "3/4"
        assert show.parts[0].num_bars == 4
        assert show.parts[0].transition == "gradual"

        # timeline
        lanes = show.timeline_data.lanes
        assert len(lanes) == 1
        assert lanes[0].fixture_targets == [WASH_GROUP]
        block = lanes[0].light_blocks[0]
        assert (block.start_time, block.end_time) == (0.0, 4.0)
        assert block.dimmer_blocks[0].intensity == pytest.approx(255.0)
        colour = block.colour_blocks[0]
        assert (colour.red, colour.green, colour.blue) == (255.0, 0.0, 0.0)

    def test_reloaded_project_still_plays_back(
            self, main_window, dialogs, inputs, menus, monkeypatch, tmp_path):
        """The round-trip is only meaningful if the reloaded project drives
        the same DMX. Rebuild the engine from the loaded config alone."""
        window = main_window
        step1_create_artnet_universe(window)
        step2_patch_fixtures(window, dialogs)
        step4_create_show_structure(window, inputs)
        step5_build_timeline(window, dialogs)

        path = str(tmp_path / "replay.yaml")
        window.config.save(path)

        from config.models import Configuration
        loaded = Configuration.load(path)

        import utils.artnet.shows_artnet_controller as sac
        from utils.fixture_utils import load_fixture_definitions_from_qlc

        class StubSender:
            def __init__(self, *a, **k): self.target_ip = ""
            def send_dmx(self, *a, **k): return True
            def set_target_ip(self, ip): pass
            def close(self): pass

        monkeypatch.setattr(sac, "ArtNetSender", StubSender)

        models = {(f.manufacturer, f.model) for f in loaded.fixtures}
        controller = sac.ShowsArtNetController(
            config=loaded,
            fixture_definitions=load_fixture_definitions_from_qlc(models),
            song_structure=None,
        )
        controller.set_light_lanes(loaded.shows[SHOW_NAME].timeline_data.lanes)
        controller.enable_output()
        try:
            base = PAR1_ADDR - 1
            dmx = render_at(controller, 1.0)
            assert dmx[base + PAR_DIMMER] == 255
            assert dmx[base + PAR_RED] == 255
            assert dmx[base + PAR_GREEN] == 0
            assert render_at(controller, 6.0)[base + PAR_DIMMER] == 0
        finally:
            controller.cleanup()
