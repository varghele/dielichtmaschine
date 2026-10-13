# tests/unit/test_morph_patchbay.py
"""The morph patchbay widget (v1.5b phase 4, mockup 6d): capability
gated docking, lane-level patches (dashed fan-out), edge mode /
transform / priority operations, the lock round-trip into
plan.protected_target_lanes, auto-suggest (role first, capability
overlap second, add-only), the live checker strip data, and the
editor's hand-edit provenance hook. All through the widget's plain
model methods - no mouse events, offscreen platform."""

import pytest

from config.models import (ColourBlock, Configuration, DimmerBlock, Fixture,
                           FixtureGroup, FixtureGroupCapabilities,
                           FixtureMode, LightBlock, LightLane, MovementBlock,
                           ShowPart, Song, TimelineData, Universe)
from utils.morph.plan import MorphPlan


def _fixture(name, x=0.0, group="G"):
    return Fixture(universe=1, address=1, manufacturer="M", model="X",
                   current_mode="Std",
                   available_modes=[FixtureMode(name="Std", channels=1)],
                   name=name, group=group, x=x)


def _group(name, fixtures, caps, role=""):
    group = FixtureGroup(name, fixtures, lighting_role=role)
    group.capabilities = FixtureGroupCapabilities(
        has_dimmer="dimmer" in caps, has_colour="colour" in caps,
        has_movement="movement" in caps, has_special="special" in caps)
    return group


def _config(groups, songs=None):
    fixtures = [f for g in groups for f in g.fixtures]
    cfg = Configuration(fixtures=fixtures,
                        groups={g.name: g for g in groups},
                        universes={1: Universe(id=1, name="U1", output={})})
    cfg.songs = songs or {}
    return cfg


def _song(name="S", lanes=None):
    return Song(name=name,
                parts=[ShowPart(name="All", color="#fff", signature="4/4",
                                bpm=120.0, num_bars=8,
                                transition="instant")],
                timeline_data=TimelineData(lanes=lanes or []))


def _lane(name, targets, dimmer=(), colour=(), movement=()):
    return LightLane(name=name, fixture_targets=list(targets),
                     light_blocks=[LightBlock(
                         start_time=0.0, end_time=16.0, effect_name="x",
                         dimmer_blocks=list(dimmer),
                         colour_blocks=list(colour),
                         movement_blocks=list(movement))])


@pytest.fixture
def rigs():
    """Source: a PARS lane (dimmer + colour) and a MOVERS lane
    (dimmer + movement). Target: WASH (dimmer+colour, backbone role),
    SPOT (dimmer+movement, movement role), STROBE (dimmer only)."""
    pars = _lane("Pars", ["PARS"],
                 dimmer=[DimmerBlock(0.0, 16.0, intensity=200.0)],
                 colour=[ColourBlock(0.0, 16.0, red=255.0)])
    movers = _lane("Movers", ["MOVERS"],
                   dimmer=[DimmerBlock(0.0, 8.0, intensity=180.0)],
                   movement=[MovementBlock(0.0, 8.0,
                                           effect_type="circle")])
    source = _config(
        [_group("PARS", [_fixture("p1")], {"dimmer", "colour"},
                role="backbone"),
         _group("MOVERS", [_fixture("m1", group="MOVERS")],
                {"dimmer", "movement"}, role="movement")],
        songs={"S": _song(lanes=[pars, movers])})
    target = _config(
        [_group("WASH", [_fixture("w1", group="WASH"),
                         _fixture("w2", x=1.0, group="WASH")],
                {"dimmer", "colour"}, role="backbone"),
         _group("SPOT", [_fixture("s1", group="SPOT")],
                {"dimmer", "movement"}, role="movement"),
         _group("STROBE", [_fixture("b1", group="STROBE")],
                {"dimmer"})])
    return source, target, pars, movers


@pytest.fixture
def patchbay(qapp, rigs):
    from gui.dialogs.morph_patchbay import MorphPatchbay
    source, target, _pars, _movers = rigs
    return MorphPatchbay(source, target)


class TestCapabilityGating:
    def test_matching_capability_docks(self, patchbay, rigs):
        _s, _t, pars, _m = rigs
        edge = patchbay.add_edge(pars.fixture_targets[0], "colour", "WASH")
        assert edge is not None
        assert edge.mode == "copy"
        assert patchbay.plan.edges == [edge]

    def test_missing_target_capability_is_refused(self, patchbay, rigs):
        _s, _t, pars, _m = rigs
        assert patchbay.add_edge(pars.fixture_targets[0], "colour", "STROBE") is None
        assert patchbay.plan.edges == []

    def test_empty_source_stream_is_refused(self, patchbay, rigs):
        # The PARS lane carries no special blocks; BEAM cannot wire.
        _s, _t, pars, _m = rigs
        assert patchbay.add_edge(pars.fixture_targets[0], "special", "WASH") is None

    def test_duplicate_edge_is_refused(self, patchbay, rigs):
        _s, _t, pars, _m = rigs
        assert patchbay.add_edge(pars.fixture_targets[0], "dimmer", "WASH")
        assert patchbay.add_edge(pars.fixture_targets[0], "dimmer", "WASH") is None
        assert len(patchbay.plan.edges) == 1

    def test_empty_movement_wires_as_regenerate(self, patchbay, rigs):
        # PARS has no movement -> the ghost POSITION chip's contract.
        _s, _t, pars, movers = rigs
        ghost = patchbay.add_edge(pars.fixture_targets[0], "movement", "SPOT")
        assert ghost.mode == "regenerate"
        assert ghost.regenerate_strategy == "manual"
        real = patchbay.add_edge(movers.fixture_targets[0], "movement", "SPOT")
        assert real.mode == "copy"


class TestLanePatch:
    def test_fans_out_to_shared_capabilities_only(self, patchbay, rigs):
        _s, _t, pars, _m = rigs
        added = patchbay.add_group_patch(pars.fixture_targets[0], "WASH")
        assert sorted(e.sublane for e in added) == ["colour", "dimmer"]
        assert patchbay.is_group_patch(pars.fixture_targets[0], "WASH")

    def test_single_stream_patch_is_not_marked(self, patchbay, rigs):
        _s, _t, pars, _m = rigs
        added = patchbay.add_group_patch(pars.fixture_targets[0], "STROBE")
        assert [e.sublane for e in added] == ["dimmer"]
        assert not patchbay.is_group_patch(pars.fixture_targets[0], "STROBE")

    def test_marker_clears_with_the_last_edge(self, patchbay, rigs):
        _s, _t, pars, _m = rigs
        added = patchbay.add_group_patch(pars.fixture_targets[0], "WASH")
        for edge in added:
            patchbay.remove_edge(edge.edge_id)
        assert not patchbay.is_group_patch(pars.fixture_targets[0], "WASH")
        assert patchbay.plan.edges == []

    def test_loaded_plan_derives_the_marker(self, qapp, rigs):
        from gui.dialogs.morph_patchbay import MorphPatchbay
        source, target, pars, _m = rigs
        first = MorphPatchbay(source, target)
        first.add_group_patch(pars.fixture_targets[0], "WASH")
        second = MorphPatchbay(source, target, plan=first.plan)
        assert second.is_group_patch(pars.fixture_targets[0], "WASH")


class TestEdgeOperations:
    def test_transform_flips_mode_and_replaces_same_kind(self, patchbay,
                                                         rigs):
        _s, _t, pars, _m = rigs
        edge = patchbay.add_edge(pars.fixture_targets[0], "dimmer", "WASH")
        patchbay.set_transform(edge.edge_id, "intensity_scale", factor=0.5)
        assert edge.mode == "copy_transform"
        patchbay.set_transform(edge.edge_id, "intensity_scale", factor=0.8)
        assert edge.transforms == [
            {"type": "intensity_scale", "factor": 0.8}]

    def test_transform_vocabulary_is_enforced(self, patchbay, rigs):
        _s, _t, pars, _m = rigs
        edge = patchbay.add_edge(pars.fixture_targets[0], "dimmer", "WASH")
        with pytest.raises(ValueError):
            patchbay.set_transform(edge.edge_id, "warp")
        with pytest.raises(ValueError):
            patchbay.set_transform(edge.edge_id, "intensity_scale")

    def test_clearing_the_last_transform_restores_copy(self, patchbay,
                                                       rigs):
        _s, _t, pars, _m = rigs
        edge = patchbay.add_edge(pars.fixture_targets[0], "dimmer", "WASH")
        patchbay.set_transform(edge.edge_id, "mirror")
        patchbay.clear_transform(edge.edge_id, "mirror")
        assert edge.transforms == []
        assert edge.mode == "copy"

    def test_priority_bumps_and_floors_at_zero(self, patchbay, rigs):
        _s, _t, pars, _m = rigs
        edge = patchbay.add_edge(pars.fixture_targets[0], "dimmer", "WASH")
        patchbay.bump_priority(edge.edge_id, +1)
        patchbay.bump_priority(edge.edge_id, +1)
        assert edge.priority == 2
        for _ in range(5):
            patchbay.bump_priority(edge.edge_id, -1)
        assert edge.priority == 0

    def test_regenerate_mode_with_strategy(self, patchbay, rigs):
        _s, _t, _pars, movers = rigs
        edge = patchbay.add_edge(movers.fixture_targets[0], "movement", "SPOT")
        patchbay.set_edge_mode(edge.edge_id, "regenerate",
                               "derive_from_intensity")
        assert edge.mode == "regenerate"
        assert edge.regenerate_strategy == "derive_from_intensity"


class TestLock:
    def test_round_trips_protected_target_lanes(self, patchbay):
        patchbay.set_lock("WASH", True)
        assert patchbay.plan.protected_target_lanes == ["WASH"]
        assert patchbay.is_locked("WASH")
        patchbay.set_lock("SPOT", True)
        assert patchbay.plan.protected_target_lanes == ["SPOT", "WASH"]
        patchbay.set_lock("WASH", False)
        assert patchbay.plan.protected_target_lanes == ["SPOT"]
        assert not patchbay.is_locked("WASH")


class TestAutoSuggest:
    def test_prefers_matching_role_then_overlap(self, patchbay, rigs):
        _s, _t, pars, movers = rigs
        added = patchbay.auto_suggest()
        wires = {(e.source_group, e.sublane, e.target_group)
                 for e in added}
        # Keyed by GROUP SELECTOR now, not the lane's display name.
        assert wires == {("PARS", "dimmer", "WASH"),
                         ("PARS", "colour", "WASH"),
                         ("MOVERS", "dimmer", "SPOT"),
                         ("MOVERS", "movement", "SPOT")}

    def test_only_valid_edges(self, patchbay):
        from utils.morph.checker import group_capabilities
        caps = group_capabilities(patchbay.target_config)
        for edge in patchbay.auto_suggest():
            assert edge.sublane in caps[edge.target_group]
            assert patchbay.source_content(
                edge.source_group).get(edge.sublane)

    def test_adds_only_and_never_repeats(self, patchbay, rigs):
        _s, _t, pars, _m = rigs
        manual = patchbay.add_edge(pars.fixture_targets[0], "dimmer", "STROBE")
        first = patchbay.auto_suggest()
        assert manual in patchbay.plan.edges       # untouched
        assert patchbay.auto_suggest() == []       # nothing new
        assert len(patchbay.plan.edges) == 1 + len(first)


class TestCheckerStrip:
    def test_gap_on_an_unrouted_capability(self, patchbay, rigs):
        _s, _t, _pars, movers = rigs
        patchbay.add_edge(movers.fixture_targets[0], "dimmer", "SPOT")
        summary = {(g, s): (p, gap)
                   for g, s, p, gap in patchbay.coverage_summary()}
        assert summary[("SPOT", "dimmer")] == (50, False)  # 8s of 16s
        assert summary[("SPOT", "movement")] == (0, True)  # the gap

    def test_full_coverage_is_not_a_gap(self, patchbay, rigs):
        _s, _t, pars, _m = rigs
        patchbay.add_group_patch(pars.fixture_targets[0], "WASH")
        summary = {(g, s): (p, gap)
                   for g, s, p, gap in patchbay.coverage_summary()}
        assert summary[("WASH", "dimmer")] == (100, False)
        assert summary[("WASH", "colour")] == (100, False)


class TestHandEditHook:
    """Design doc 5.3: the editor flips morphed provenance on touch."""

    def _stub(self, block):
        from timeline_ui.light_block_widget import LightBlockWidget

        class WidgetStub:
            _flip_morph_provenance = \
                LightBlockWidget._flip_morph_provenance
            _mark_hand_edit = LightBlockWidget._mark_hand_edit

        stub = WidgetStub()
        stub.block = block
        return stub

    def test_morphed_block_flips_to_hand_edited(self, qapp):
        block = LightBlock(start_time=0.0, end_time=4.0, effect_name="x",
                           provenance="morphed:abc123")
        stub = self._stub(block)
        stub._mark_hand_edit()
        assert block.provenance == "hand_edited"
        assert block.modified is True

    def test_authored_block_is_never_tagged(self, qapp):
        block = LightBlock(start_time=0.0, end_time=4.0, effect_name="x")
        stub = self._stub(block)
        stub._mark_hand_edit()
        assert block.provenance == ""
        assert block.modified is True

    def test_envelope_drag_flip_leaves_modified_alone(self, qapp):
        block = LightBlock(start_time=0.0, end_time=4.0, effect_name="x",
                           provenance="morphed:abc123")
        stub = self._stub(block)
        stub._flip_morph_provenance()
        assert block.provenance == "hand_edited"
        assert block.modified is False

    def test_every_edit_path_routes_through_the_hook(self):
        """No editor path may set block.modified directly: the single
        allowed assignment lives inside _mark_hand_edit itself."""
        import inspect
        import timeline_ui.light_block_widget as module
        source = inspect.getsource(module)
        assert source.count("self.block.modified = True") == 1


class TestDragAndDropWiring:
    """The drag path (mockup 6d: ZIEHEN QUELLE -> ZIEL). Drops route
    through wire_drop_allowed/handle_wire_drop - the same gate as
    click-click - so these drive the plain methods plus one real
    QDragEnterEvent/QDropEvent pass through the target chip."""

    def test_mime_round_trip(self, qapp):
        from gui.dialogs.morph_patchbay import (decode_wire_mime,
                                                encode_wire_mime)
        assert decode_wire_mime(encode_wire_mime("L1", "dimmer")) == \
            ("L1", "dimmer")
        assert decode_wire_mime(encode_wire_mime("L1", None)) == \
            ("L1", None)
        from PyQt6 import QtCore
        assert decode_wire_mime(QtCore.QMimeData()) is None

    def test_stream_drop_on_matching_chip_docks(self, patchbay, rigs):
        _s, _t, pars, _m = rigs
        assert patchbay.wire_drop_allowed(
            pars.fixture_targets[0], "colour", "WASH", "colour")
        assert patchbay.handle_wire_drop(
            pars.fixture_targets[0], "colour", "WASH", "colour")
        assert [e.sublane for e in patchbay.plan.edges] == ["colour"]

    def test_stream_drop_on_wrong_chip_is_refused(self, patchbay, rigs):
        _s, _t, pars, _m = rigs
        assert not patchbay.wire_drop_allowed(
            pars.fixture_targets[0], "colour", "WASH", "dimmer")
        assert not patchbay.handle_wire_drop(
            pars.fixture_targets[0], "colour", "WASH", "dimmer")
        assert patchbay.plan.edges == []

    def test_stream_drop_on_the_row_docks_its_capability(self, patchbay,
                                                         rigs):
        _s, _t, pars, _m = rigs
        assert patchbay.handle_wire_drop(pars.fixture_targets[0], "colour", "WASH")
        assert [e.sublane for e in patchbay.plan.edges] == ["colour"]

    def test_incompatible_stream_drop_on_row_is_refused(self, patchbay,
                                                        rigs):
        _s, _t, pars, _m = rigs
        assert not patchbay.handle_wire_drop(
            pars.fixture_targets[0], "colour", "STROBE")
        assert patchbay.plan.edges == []

    def test_lane_drop_fans_out_as_lane_patch(self, patchbay, rigs):
        _s, _t, pars, _m = rigs
        assert patchbay.handle_wire_drop(pars.fixture_targets[0], None, "WASH")
        assert sorted(e.sublane for e in patchbay.plan.edges) == \
            ["colour", "dimmer"]
        assert patchbay.is_group_patch(pars.fixture_targets[0], "WASH")

    def test_lane_drop_on_chip_the_lane_lacks_is_refused(self, patchbay,
                                                         rigs):
        # PARS carries no movement: a lane drag may not dock via the
        # POSITION chip even though SPOT renders it.
        _s, _t, pars, _m = rigs
        assert not patchbay.wire_drop_allowed(
            pars.fixture_targets[0], None, "SPOT", "movement")

    def test_unknown_lane_never_docks(self, patchbay):
        assert not patchbay.wire_drop_allowed(
            "no-such-lane", "dimmer", "WASH", None)

    def _target_chip(self, patchbay, group, sublane):
        from PyQt6 import QtWidgets
        for chip in patchbay._board.findChildren(QtWidgets.QToolButton):
            if chip.property("target_key") == (group, sublane):
                return chip
        raise AssertionError(f"no target chip {group}/{sublane}")

    def test_drop_events_dock_through_the_chip(self, patchbay, rigs):
        from PyQt6 import QtCore, QtGui
        from gui.dialogs.morph_patchbay import encode_wire_mime
        _s, _t, pars, _m = rigs
        chip = self._target_chip(patchbay, "WASH", "colour")
        mime = encode_wire_mime(pars.fixture_targets[0], "colour")
        enter = QtGui.QDragEnterEvent(
            QtCore.QPoint(2, 2), QtCore.Qt.DropAction.CopyAction, mime,
            QtCore.Qt.MouseButton.LeftButton,
            QtCore.Qt.KeyboardModifier.NoModifier)
        chip.dragEnterEvent(enter)
        assert enter.isAccepted()
        drop = QtGui.QDropEvent(
            QtCore.QPointF(2.0, 2.0), QtCore.Qt.DropAction.CopyAction,
            mime, QtCore.Qt.MouseButton.LeftButton,
            QtCore.Qt.KeyboardModifier.NoModifier)
        chip.dropEvent(drop)
        assert drop.isAccepted()
        assert [e.sublane for e in patchbay.plan.edges] == ["colour"]

    def test_incompatible_drag_enter_is_ignored(self, patchbay, rigs):
        from PyQt6 import QtCore, QtGui
        from gui.dialogs.morph_patchbay import encode_wire_mime
        _s, _t, pars, _m = rigs
        chip = self._target_chip(patchbay, "WASH", "dimmer")
        # Keep the mime alive for the handler: QDragEnterEvent does NOT
        # take ownership, an inline temporary is freed under the event.
        mime = encode_wire_mime(pars.fixture_targets[0], "colour")
        enter = QtGui.QDragEnterEvent(
            QtCore.QPoint(2, 2), QtCore.Qt.DropAction.CopyAction, mime,
            QtCore.Qt.MouseButton.LeftButton,
            QtCore.Qt.KeyboardModifier.NoModifier)
        enter.ignore()
        chip.dragEnterEvent(enter)
        assert not enter.isAccepted()

    def test_drag_gates_targets_like_a_pending_click(self, patchbay,
                                                     rigs):
        _s, _t, pars, _m = rigs
        patchbay.begin_wire_drag((pars.fixture_targets[0], "colour"))
        assert "Drop on" in patchbay.hint_label.text()
        assert self._target_chip(patchbay, "WASH", "colour").isEnabled()
        assert not self._target_chip(patchbay, "WASH", "dimmer").isEnabled()
        assert not self._target_chip(patchbay, "SPOT", "movement"
                                     ).isEnabled()
        patchbay.end_wire_drag()
        assert self._target_chip(patchbay, "WASH", "dimmer").isEnabled()
        assert patchbay.HINT_IDLE in patchbay.hint_label.text()


class TestCableInFlight:
    """The cable that follows the cursor while a wire is being pulled
    (2026-08-08). Painting reads pending_curve(); tests drive
    set_drag_position() directly, the same way handle_wire_drop stands in
    for a real drop - a QDrag runs its own event loop and cannot be
    synthesized meaningfully offscreen."""

    def test_no_cable_when_nothing_is_pending(self, patchbay):
        assert patchbay.pending_curve() is None

    def test_no_cable_until_the_cursor_has_a_position(self, patchbay, rigs):
        _s, _t, pars, _m = rigs
        patchbay.begin_wire_drag((pars.fixture_targets[0], "dimmer"))
        patchbay.set_drag_position(None)
        assert patchbay.pending_curve() is None

    def test_cable_runs_from_the_source_anchor_to_the_cursor(self, patchbay,
                                                             rigs):
        from PyQt6.QtCore import QPoint
        _s, _t, pars, _m = rigs
        selector = pars.fixture_targets[0]
        patchbay.set_expanded(selector, True)
        patchbay.begin_wire_drag((selector, "dimmer"))
        patchbay.set_drag_position(QPoint(640, 400))

        curve = patchbay.pending_curve()
        assert curve is not None
        x1, y1, x2, y2, colour = curve
        assert (x2, y2) == (640.0, 400.0), "free end follows the cursor"
        # Fixed end is the anchor row's right-middle, in board coords.
        # Asserted against the anchor itself rather than a magnitude:
        # nothing is laid out offscreen, so real geometry is meaningless.
        from PyQt6.QtCore import QPoint
        anchor = patchbay._source_anchors[(selector, "dimmer")]
        want = anchor.mapTo(patchbay._board,
                            QPoint(anchor.width(), anchor.height() // 2))
        assert (x1, y1) == (float(want.x()), float(want.y()))
        assert colour == patchbay._sources_by_selector[selector].colour

    def test_cable_clears_when_the_drag_ends(self, patchbay, rigs):
        from PyQt6.QtCore import QPoint
        _s, _t, pars, _m = rigs
        # Collapsed row, so the wireable key is the whole-GROUP one.
        patchbay.begin_wire_drag((pars.fixture_targets[0], None))
        patchbay.set_drag_position(QPoint(100, 100))
        assert patchbay.pending_curve() is not None
        patchbay.end_wire_drag()
        assert patchbay.pending_curve() is None

    def test_drag_tracking_timer_stops_with_the_drag(self, patchbay, rigs):
        """A polling timer left running would burn a wakeup every 16 ms
        for the rest of the session."""
        _s, _t, pars, _m = rigs
        patchbay.begin_wire_drag((pars.fixture_targets[0], "dimmer"))
        assert patchbay._drag_timer is not None
        assert patchbay._drag_timer.isActive()
        patchbay.end_wire_drag()
        assert not patchbay._drag_timer.isActive()

    def test_target_relays_its_position_in_board_coordinates(self, patchbay,
                                                             rigs):
        """report_drag_position takes the widget's OWN coordinates and
        maps them - a target reporting raw local coords would put the
        cable in the wrong place."""
        from PyQt6.QtCore import QPoint
        _s, _t, pars, _m = rigs
        selector = pars.fixture_targets[0]
        patchbay.begin_wire_drag((selector, None))
        target = patchbay._target_anchors["WASH"]
        patchbay.report_drag_position(target, QPoint(3, 5))
        expected = target.mapTo(patchbay._board, QPoint(3, 5))
        curve = patchbay.pending_curve()
        assert (curve[2], curve[3]) == (float(expected.x()),
                                        float(expected.y()))


def _unpatch_buttons(patchbay):
    """Every visible × button, by the edge it removes.

    Flushes first: rebuilding rows retires the old ones with
    deleteLater(), and without a running event loop they would still be
    found as children - the app itself has a loop, so this is what the
    user actually sees (see tests/conftest.flush_deferred_deletes)."""
    from PyQt6.QtWidgets import QToolButton
    from tests.conftest import flush_deferred_deletes
    flush_deferred_deletes()
    found = {}
    for button in patchbay._board.findChildren(QToolButton):
        edge_id = button.property("unpatch_edge_id")
        if edge_id:
            found[edge_id] = button
    return found


class TestUnpatch:
    """Removal was reachable only through a right-click menu on the edge
    chip, so users concluded there was no way to un-patch at all
    (reported 2026-08-08 during the desktop checks). Every edge now
    carries a visible ×."""

    def test_every_edge_gets_an_unpatch_button(self, patchbay, rigs):
        _s, _t, pars, _m = rigs
        one = patchbay.add_edge(pars.fixture_targets[0], "dimmer", "WASH")
        two = patchbay.add_edge(pars.fixture_targets[0], "colour", "WASH")
        buttons = _unpatch_buttons(patchbay)
        assert set(buttons) == {one.edge_id, two.edge_id}

    def test_clicking_it_removes_that_edge_only(self, patchbay, rigs):
        _s, _t, pars, _m = rigs
        one = patchbay.add_edge(pars.fixture_targets[0], "dimmer", "WASH")
        two = patchbay.add_edge(pars.fixture_targets[0], "colour", "WASH")
        _unpatch_buttons(patchbay)[one.edge_id].click()
        assert [e.edge_id for e in patchbay.plan.edges] == [two.edge_id]

    def test_the_button_disappears_with_its_edge(self, patchbay, rigs):
        _s, _t, pars, _m = rigs
        edge = patchbay.add_edge(pars.fixture_targets[0], "dimmer", "WASH")
        _unpatch_buttons(patchbay)[edge.edge_id].click()
        assert _unpatch_buttons(patchbay) == {}

    def test_removal_emits_changed_so_the_screen_resyncs(self, patchbay,
                                                         rigs):
        _s, _t, pars, _m = rigs
        edge = patchbay.add_edge(pars.fixture_targets[0], "dimmer", "WASH")
        seen = []
        patchbay.changed.connect(lambda: seen.append(1))
        _unpatch_buttons(patchbay)[edge.edge_id].click()
        assert seen


def _edge_holders(patchbay):
    """Edge chip containers by edge id."""
    from gui.dialogs.morph_patchbay import _EdgeChipHolder
    from tests.conftest import flush_deferred_deletes
    flush_deferred_deletes()
    return {h.edge_id: h
            for h in patchbay._board.findChildren(_EdgeChipHolder)}


class TestUnpatchByKeyboard:
    """Delete / Backspace on a focused edge, so removal does not depend
    on landing the mouse on an 18px ×."""

    def _press(self, widget, key):
        from PyQt6.QtCore import QEvent, Qt
        from PyQt6.QtGui import QKeyEvent
        widget.keyPressEvent(
            QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier))

    def test_delete_removes_the_focused_edge(self, patchbay, rigs):
        from PyQt6.QtCore import Qt
        _s, _t, pars, _m = rigs
        edge = patchbay.add_edge(pars.fixture_targets[0], "dimmer", "WASH")
        self._press(_edge_holders(patchbay)[edge.edge_id], Qt.Key.Key_Delete)
        assert patchbay.plan.edges == []

    def test_backspace_removes_it_too(self, patchbay, rigs):
        from PyQt6.QtCore import Qt
        _s, _t, pars, _m = rigs
        edge = patchbay.add_edge(pars.fixture_targets[0], "dimmer", "WASH")
        self._press(_edge_holders(patchbay)[edge.edge_id],
                    Qt.Key.Key_Backspace)
        assert patchbay.plan.edges == []

    def test_other_keys_are_left_alone(self, patchbay, rigs):
        from PyQt6.QtCore import Qt
        _s, _t, pars, _m = rigs
        edge = patchbay.add_edge(pars.fixture_targets[0], "dimmer", "WASH")
        self._press(_edge_holders(patchbay)[edge.edge_id], Qt.Key.Key_A)
        assert [e.edge_id for e in patchbay.plan.edges] == [edge.edge_id]

    def test_holders_are_focusable(self, patchbay, rigs):
        from PyQt6.QtCore import Qt
        _s, _t, pars, _m = rigs
        edge = patchbay.add_edge(pars.fixture_targets[0], "dimmer", "WASH")
        holder = _edge_holders(patchbay)[edge.edge_id]
        assert holder.focusPolicy() == Qt.FocusPolicy.StrongFocus


class TestWireSelection:
    """Click the wire itself to select, Delete to unpatch - the gesture
    a patchbay implies. Hit-testing shares curve_path() with the
    painter, so clicks land on the line that is actually drawn."""

    def _wire_point(self, patchbay, edge_id, t=0.5):
        """A point ON the given wire, in canvas coordinates."""
        width = float(patchbay._canvas.width())
        for y1, y2, _c, _d, eid in patchbay.edge_curves():
            if eid == edge_id:
                return patchbay.curve_path(y1, y2, width).pointAtPercent(t)
        raise AssertionError(f"no curve for {edge_id}")

    def test_clicking_a_wire_selects_it(self, patchbay, rigs):
        _s, _t, pars, _m = rigs
        edge = patchbay.add_edge(pars.fixture_targets[0], "dimmer", "WASH")
        point = self._wire_point(patchbay, edge.edge_id)
        assert patchbay.edge_at(point.toPoint()) == edge.edge_id

    def test_empty_canvas_hits_nothing(self, patchbay, rigs):
        from PyQt6.QtCore import QPoint
        _s, _t, pars, _m = rigs
        patchbay.add_edge(pars.fixture_targets[0], "dimmer", "WASH")
        # Far below every row.
        assert patchbay.edge_at(QPoint(10, 5000)) is None

    def test_selection_then_delete_removes_that_wire(self, patchbay, rigs):
        _s, _t, pars, _m = rigs
        one = patchbay.add_edge(pars.fixture_targets[0], "dimmer", "WASH")
        two = patchbay.add_edge(pars.fixture_targets[0], "colour", "WASH")
        patchbay.select_edge(one.edge_id)
        assert patchbay.remove_selected_edge()
        assert [e.edge_id for e in patchbay.plan.edges] == [two.edge_id]

    def test_delete_with_nothing_selected_is_a_no_op(self, patchbay, rigs):
        _s, _t, pars, _m = rigs
        patchbay.add_edge(pars.fixture_targets[0], "dimmer", "WASH")
        assert not patchbay.remove_selected_edge()
        assert len(patchbay.plan.edges) == 1

    def test_selecting_an_unknown_edge_is_ignored(self, patchbay, rigs):
        _s, _t, pars, _m = rigs
        edge = patchbay.add_edge(pars.fixture_targets[0], "dimmer", "WASH")
        patchbay.select_edge(edge.edge_id)
        patchbay.select_edge("nope")
        assert patchbay.selected_edge_id == edge.edge_id

    def test_removing_by_other_means_clears_the_selection(self, patchbay,
                                                          rigs):
        """Otherwise Delete would fire at an edge that is already gone."""
        _s, _t, pars, _m = rigs
        edge = patchbay.add_edge(pars.fixture_targets[0], "dimmer", "WASH")
        patchbay.select_edge(edge.edge_id)
        patchbay.remove_edge(edge.edge_id)          # the × path
        assert patchbay.selected_edge_id is None

    def test_canvas_click_routes_through_to_selection(self, patchbay, rigs):
        from PyQt6.QtCore import QPointF, Qt
        from PyQt6.QtGui import QMouseEvent
        from PyQt6.QtCore import QEvent
        _s, _t, pars, _m = rigs
        edge = patchbay.add_edge(pars.fixture_targets[0], "dimmer", "WASH")
        point = self._wire_point(patchbay, edge.edge_id)
        patchbay._canvas.mousePressEvent(QMouseEvent(
            QEvent.Type.MouseButtonPress, QPointF(point),
            Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier))
        assert patchbay.selected_edge_id == edge.edge_id


class TestUnpatchByDragging:
    """Pull the patch off its row and it comes out - the physical
    gesture. QDrag.exec runs a platform loop that cannot be synthesized
    offscreen, so the outcome lives in finish_unpatch_drag()."""

    def test_pulled_clear_removes_the_edge(self, patchbay, rigs):
        _s, _t, pars, _m = rigs
        edge = patchbay.add_edge(pars.fixture_targets[0], "dimmer", "WASH")
        assert patchbay.finish_unpatch_drag(edge.edge_id, pulled_out=True)
        assert patchbay.plan.edges == []

    def test_dropped_on_something_keeps_it(self, patchbay, rigs):
        """A drag that landed somewhere meaningful is not an unplug."""
        _s, _t, pars, _m = rigs
        edge = patchbay.add_edge(pars.fixture_targets[0], "dimmer", "WASH")
        assert not patchbay.finish_unpatch_drag(edge.edge_id,
                                                pulled_out=False)
        assert [e.edge_id for e in patchbay.plan.edges] == [edge.edge_id]

    def test_unpatch_mime_is_distinct_from_the_wire_mime(self):
        from gui.dialogs.morph_patchbay import UNPATCH_MIME, WIRE_MIME
        assert UNPATCH_MIME != WIRE_MIME

    def test_targets_ignore_an_unpatch_drag(self, patchbay, rigs):
        """If a target chip accepted it, the drag would end in
        AcceptAction and the cable would never come out."""
        from PyQt6.QtCore import QMimeData, QPointF, Qt
        from PyQt6.QtGui import QDragMoveEvent
        from gui.dialogs.morph_patchbay import UNPATCH_MIME
        _s, _t, pars, _m = rigs
        patchbay.add_edge(pars.fixture_targets[0], "dimmer", "WASH")
        mime = QMimeData()
        mime.setData(UNPATCH_MIME, b"whatever")
        target = patchbay._target_anchors["WASH"]
        event = QDragMoveEvent(QPointF(1.0, 1.0).toPoint(),
                               Qt.DropAction.MoveAction, mime,
                               Qt.MouseButton.LeftButton,
                               Qt.KeyboardModifier.NoModifier)
        event.accept()
        row = target.parent()
        if hasattr(row, "dragMoveEvent"):
            row.dragMoveEvent(event)
            assert not event.isAccepted()


class TestUnpatchEverything:
    """Bulk removal at three scopes: the whole plan, one target row, one
    source group. clear_edges() is pure model; the confirmation lives at
    the UI entry points (QMessageBox is blocked in the suite)."""

    def _wire_a_few(self, patchbay, rigs):
        _s, _t, pars, movers = rigs
        p, m = pars.fixture_targets[0], movers.fixture_targets[0]
        return {
            "pars_wash_dim": patchbay.add_edge(p, "dimmer", "WASH"),
            "pars_wash_col": patchbay.add_edge(p, "colour", "WASH"),
            "pars_strobe": patchbay.add_edge(p, "dimmer", "STROBE"),
            "movers_spot": patchbay.add_edge(m, "movement", "SPOT"),
        }

    def test_clearing_the_whole_plan(self, patchbay, rigs):
        self._wire_a_few(patchbay, rigs)
        assert patchbay.clear_edges() == 4
        assert patchbay.plan.edges == []

    def test_clearing_one_target_row_leaves_the_others(self, patchbay, rigs):
        edges = self._wire_a_few(patchbay, rigs)
        assert patchbay.clear_edges(target_group="WASH") == 2
        assert {e.edge_id for e in patchbay.plan.edges} == {
            edges["pars_strobe"].edge_id, edges["movers_spot"].edge_id}

    def test_clearing_one_source_leaves_the_others(self, patchbay, rigs):
        edges = self._wire_a_few(patchbay, rigs)
        _s, _t, pars, _m = rigs
        removed = patchbay.clear_edges(source_group=pars.fixture_targets[0])
        assert removed == 3
        assert [e.edge_id for e in patchbay.plan.edges] == [
            edges["movers_spot"].edge_id]

    def test_clearing_an_empty_scope_removes_nothing(self, patchbay, rigs):
        self._wire_a_few(patchbay, rigs)
        assert patchbay.clear_edges(target_group="SPOT",
                                    source_group="PARS") == 0
        assert len(patchbay.plan.edges) == 4

    def test_group_patch_markers_go_with_their_edges(self, patchbay, rigs):
        _s, _t, pars, _m = rigs
        selector = pars.fixture_targets[0]
        patchbay.add_group_patch(selector, "WASH")
        assert patchbay.is_group_patch(selector, "WASH")
        patchbay.clear_edges()
        assert not patchbay.is_group_patch(selector, "WASH")

    def test_a_stale_selection_does_not_survive(self, patchbay, rigs):
        edges = self._wire_a_few(patchbay, rigs)
        patchbay.select_edge(edges["pars_wash_dim"].edge_id)
        patchbay.clear_edges()
        assert patchbay.selected_edge_id is None

    def test_clearing_emits_changed_once(self, patchbay, rigs):
        self._wire_a_few(patchbay, rigs)
        seen = []
        patchbay.changed.connect(lambda: seen.append(1))
        patchbay.clear_edges()
        assert len(seen) == 1, "one rebuild for the whole bulk removal"

    def test_confirm_asks_before_a_bulk_removal(self, patchbay, rigs,
                                                monkeypatch):
        from PyQt6.QtWidgets import QMessageBox
        self._wire_a_few(patchbay, rigs)
        asked = []
        monkeypatch.setattr(
            QMessageBox, "question",
            staticmethod(lambda *a, **k: (asked.append(a),
                                          QMessageBox.StandardButton.No)[1]))
        assert patchbay.confirm_and_clear(what="this plan") == 0
        assert asked, "a bulk removal must ask first - there is no undo"
        assert len(patchbay.plan.edges) == 4, "declining keeps everything"

    def test_confirm_yes_clears(self, patchbay, rigs, monkeypatch):
        from PyQt6.QtWidgets import QMessageBox
        self._wire_a_few(patchbay, rigs)
        monkeypatch.setattr(
            QMessageBox, "question",
            staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))
        assert patchbay.confirm_and_clear(what="this plan") == 4
        assert patchbay.plan.edges == []

    def test_single_edge_does_not_nag(self, patchbay, rigs):
        """One wire is not a bulk removal; asking every time trains the
        user to click through the dialog."""
        _s, _t, pars, _m = rigs
        patchbay.add_edge(pars.fixture_targets[0], "dimmer", "WASH")
        # QMessageBox.question is blocked by the suite guard, so this
        # passing at all proves no dialog was raised.
        assert patchbay.confirm_and_clear(target_group="WASH") == 1
        assert patchbay.plan.edges == []

    def test_target_row_grows_an_unpatch_control_only_when_patched(
            self, patchbay, rigs):
        from PyQt6.QtWidgets import QToolButton
        from tests.conftest import flush_deferred_deletes

        def controls():
            flush_deferred_deletes()
            return {b.property("unpatch_target_group")
                    for b in patchbay._board.findChildren(QToolButton)
                    if b.property("unpatch_target_group")}

        assert controls() == set()
        _s, _t, pars, _m = rigs
        patchbay.add_edge(pars.fixture_targets[0], "dimmer", "WASH")
        assert controls() == {"WASH"}


class TestUndoRedo:
    """The patchbay has its OWN undo stack (2026-08-08). Ctrl+Z here
    means "put that patch back", never "undo a timeline edit" - the app
    stack is a different document.

    Undo is snapshot-based rather than a command class per mutation:
    the plan is small and there are nine ways to mutate it, so nine
    inverse operations would drift out of sync with them."""

    def test_nothing_to_undo_on_a_fresh_patchbay(self, patchbay):
        assert not patchbay.can_undo()
        assert not patchbay.can_redo()

    def test_add_then_undo_then_redo(self, patchbay, rigs):
        _s, _t, pars, _m = rigs
        edge = patchbay.add_edge(pars.fixture_targets[0], "dimmer", "WASH")
        assert patchbay.can_undo()

        patchbay.undo()
        assert patchbay.plan.edges == []
        assert patchbay.can_redo()

        patchbay.redo()
        assert [e.edge_id for e in patchbay.plan.edges] == [edge.edge_id]

    def test_unpatch_is_undoable(self, patchbay, rigs):
        """The reason this exists: × is one click and there was no way
        back."""
        _s, _t, pars, _m = rigs
        edge = patchbay.add_edge(pars.fixture_targets[0], "dimmer", "WASH")
        patchbay.remove_edge(edge.edge_id)
        assert patchbay.plan.edges == []
        patchbay.undo()
        assert [e.edge_id for e in patchbay.plan.edges] == [edge.edge_id]

    def test_group_patch_undoes_as_one_step(self, patchbay, rigs):
        """A fan-out that took one drop must take one Ctrl+Z, not four."""
        _s, _t, pars, _m = rigs
        added = patchbay.add_group_patch(pars.fixture_targets[0], "WASH")
        assert len(added) == 2
        patchbay.undo()
        assert patchbay.plan.edges == []
        assert not patchbay.can_undo(), "one step, not one per edge"

    def test_auto_suggest_undoes_as_one_step(self, patchbay):
        added = patchbay.auto_suggest()
        assert len(added) > 1
        patchbay.undo()
        assert patchbay.plan.edges == []
        assert not patchbay.can_undo()

    def test_bulk_unpatch_undoes_as_one_step(self, patchbay, rigs):
        _s, _t, pars, _m = rigs
        patchbay.auto_suggest()
        before = len(patchbay.plan.edges)
        patchbay.clear_edges()
        assert patchbay.plan.edges == []
        patchbay.undo()
        assert len(patchbay.plan.edges) == before

    def test_group_patch_marker_comes_back_with_the_edges(self, patchbay,
                                                          rigs):
        _s, _t, pars, _m = rigs
        selector = pars.fixture_targets[0]
        patchbay.add_group_patch(selector, "WASH")
        patchbay.clear_edges()
        patchbay.undo()
        assert patchbay.is_group_patch(selector, "WASH"), \
            "the dashed fan-out marker is part of the state, not a cache"

    def test_lock_is_undoable(self, patchbay):
        patchbay.set_lock("WASH", True)
        assert patchbay.plan.protected_target_lanes == ["WASH"]
        patchbay.undo()
        assert patchbay.plan.protected_target_lanes == []

    def test_transform_is_undoable(self, patchbay, rigs):
        _s, _t, pars, _m = rigs
        edge = patchbay.add_edge(pars.fixture_targets[0], "dimmer", "WASH")
        patchbay.set_transform(edge.edge_id, "intensity_scale", factor=0.5)
        assert patchbay.edge(edge.edge_id).mode == "copy_transform"
        patchbay.undo()
        assert patchbay.edge(edge.edge_id).mode == "copy"
        assert patchbay.edge(edge.edge_id).transforms == []

    def test_a_no_op_edit_pushes_nothing(self, patchbay, rigs):
        """A refused dock must not leave an empty step on the stack, or
        the first Ctrl+Z would appear to do nothing."""
        _s, _t, pars, _m = rigs
        patchbay.add_edge(pars.fixture_targets[0], "colour", "STROBE")
        assert not patchbay.can_undo()

    def test_undo_keeps_the_shared_plan_object(self, patchbay, rigs):
        """The morph screen holds the SAME MorphPlan instance; rebinding
        it would leave the screen editing an orphan."""
        _s, _t, pars, _m = rigs
        plan = patchbay.plan
        patchbay.add_edge(pars.fixture_targets[0], "dimmer", "WASH")
        patchbay.undo()
        assert patchbay.plan is plan

    def test_redo_is_dropped_by_a_new_edit(self, patchbay, rigs):
        _s, _t, pars, movers = rigs
        patchbay.add_edge(pars.fixture_targets[0], "dimmer", "WASH")
        patchbay.undo()
        patchbay.add_edge(movers.fixture_targets[0], "movement", "SPOT")
        assert not patchbay.can_redo()

    def test_buttons_track_the_stack(self, patchbay, rigs):
        _s, _t, pars, _m = rigs
        assert not patchbay.undo_btn.isEnabled()
        patchbay.add_edge(pars.fixture_targets[0], "dimmer", "WASH")
        assert patchbay.undo_btn.isEnabled()
        assert not patchbay.redo_btn.isEnabled()
        patchbay.undo()
        assert patchbay.redo_btn.isEnabled()

    def test_stack_signal_does_not_outlive_the_widget(self, qapp, rigs):
        """indexChanged was connected to a lambda, which has no receiver
        for PyQt to track - it fired after teardown into the deleted
        QUndoStack and took a native access violation."""
        from gui.dialogs.morph_patchbay import MorphPatchbay
        from tests.conftest import flush_deferred_deletes
        import gc
        source, target, pars, _m = rigs
        bay = MorphPatchbay(source, target)
        bay.add_edge(pars.fixture_targets[0], "dimmer", "WASH")
        bay.deleteLater()
        del bay
        flush_deferred_deletes()
        gc.collect()          # crashed here before the fix
