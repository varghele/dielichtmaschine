# tests/unit/test_timeline_undo.py
"""Timeline undo/redo (v1.3): the QUndoCommand layer.

The commands mutate the RUNTIME lane objects in place (preserving
LightBlock identity, which every block widget's ``.block`` reference
depends on). Commands for edits that already happened (live drags, the
add/paste paths) are pushed already-applied: QUndoStack.push() calls
redo() immediately, and re-applying a move would shift the sublane
blocks a second time - the exact bug the ``already_applied`` flag (and
AddBlockCommand's presence guard) prevents.

Stubs stand in for the Qt widgets: the commands only touch
``lane_widget.lane.light_blocks``, ``lane_widget.light_block_widgets``
and ``create_light_block_widget`` - all duck-typed here.
"""

import pytest

from PyQt6.QtGui import QUndoStack

from config.models import DimmerBlock, LightBlock
from timeline_ui.undo_commands import (
    AddBlockCommand,
    AddLaneCommand,
    MoveBlockCommand,
    RemoveLaneCommand,
    ResizeBlockCommand,
)


class _StubBlockWidget:
    def __init__(self, block):
        self.block = block
        self.deleted = False

    def update_position(self):
        pass

    def deleteLater(self):
        self.deleted = True


class _StubLane:
    def __init__(self):
        self.light_blocks = []


class _StubLaneWidget:
    def __init__(self):
        self.lane = _StubLane()
        self.light_block_widgets = []

    def create_light_block_widget(self, block):
        self.light_block_widgets.append(_StubBlockWidget(block))


def _block(start=4.0, end=8.0, with_sublane=True):
    block = LightBlock(start_time=start, end_time=end, effect_name="")
    if with_sublane:
        block.dimmer_blocks.append(
            DimmerBlock(start_time=start, end_time=end, intensity=255.0))
    return block


class TestMoveAlreadyApplied:
    def test_push_does_not_double_shift_sublanes(self, qapp):
        lane_widget = _StubLaneWidget()
        block = _block(4.0, 8.0)
        lane_widget.lane.light_blocks.append(block)
        lane_widget.create_light_block_widget(block)

        # The live drag already moved everything +2 s.
        block.start_time, block.end_time = 6.0, 10.0
        block.dimmer_blocks[0].start_time = 6.0
        block.dimmer_blocks[0].end_time = 10.0

        stack = QUndoStack(qapp)
        stack.push(MoveBlockCommand(lane_widget, block, 4.0, 8.0, 6.0, 10.0,
                                    already_applied=True))
        # Push-time redo must be a no-op: still exactly +2, not +4.
        assert block.dimmer_blocks[0].start_time == pytest.approx(6.0)

        stack.undo()
        assert (block.start_time, block.end_time) == (4.0, 8.0)
        assert block.dimmer_blocks[0].start_time == pytest.approx(4.0)
        assert block.dimmer_blocks[0].end_time == pytest.approx(8.0)

        stack.redo()
        assert (block.start_time, block.end_time) == (6.0, 10.0)
        assert block.dimmer_blocks[0].start_time == pytest.approx(6.0)

    def test_resize_survives_the_push_time_redo(self, qapp):
        lane_widget = _StubLaneWidget()
        block = _block(4.0, 8.0)
        lane_widget.lane.light_blocks.append(block)
        lane_widget.create_light_block_widget(block)
        block.end_time = 12.0     # live resize already applied

        stack = QUndoStack(qapp)
        stack.push(ResizeBlockCommand(lane_widget, block, 4.0, 8.0,
                                      4.0, 12.0))
        assert block.end_time == 12.0      # absolute re-set, no harm
        stack.undo()
        assert block.end_time == 8.0
        stack.redo()
        assert block.end_time == 12.0


class TestAddBlockAlreadyApplied:
    def test_round_trip_preserves_identity(self, qapp):
        lane_widget = _StubLaneWidget()
        block = _block()
        lane_widget.lane.light_blocks.append(block)   # already applied
        lane_widget.create_light_block_widget(block)

        stack = QUndoStack(qapp)
        stack.push(AddBlockCommand(lane_widget, block))
        # Push-time redo: guarded no-op (no duplicate block or widget).
        assert lane_widget.lane.light_blocks == [block]
        assert len(lane_widget.light_block_widgets) == 1

        stack.undo()
        assert lane_widget.lane.light_blocks == []
        assert lane_widget.light_block_widgets == []

        stack.redo()
        assert lane_widget.lane.light_blocks == [block]  # SAME object
        assert lane_widget.light_block_widgets[0].block is block


class _StubShowsTab:
    def __init__(self):
        self.lane_widgets = []

    def _add_lane_widget(self, lane):
        widget = _StubLaneWidget()
        widget.lane = lane
        self.lane_widgets.append(widget)

    def _remove_lane_widget(self, widget):
        self.lane_widgets.remove(widget)


class TestLaneCommands:
    def test_add_lane_round_trip(self, qapp):
        tab = _StubShowsTab()
        lane = _StubLane()
        tab._add_lane_widget(lane)        # the action already happened

        stack = QUndoStack(qapp)
        stack.push(AddLaneCommand(tab, lane))
        assert len(tab.lane_widgets) == 1  # push-time redo is a no-op

        stack.undo()
        assert tab.lane_widgets == []
        stack.redo()
        assert len(tab.lane_widgets) == 1
        assert tab.lane_widgets[0].lane is lane   # SAME lane object

    def test_remove_lane_round_trip(self, qapp):
        tab = _StubShowsTab()
        lane = _StubLane()
        lane.light_blocks.append(_block())
        tab._add_lane_widget(lane)
        widget = tab.lane_widgets[0]

        stack = QUndoStack(qapp)
        stack.push(RemoveLaneCommand(tab, widget))  # redo removes NOW
        assert tab.lane_widgets == []

        stack.undo()
        assert len(tab.lane_widgets) == 1
        restored = tab.lane_widgets[0].lane
        assert restored is lane, "the same runtime lane returns"
        assert restored.light_blocks, "with its blocks intact"


class TestEnvelopeDragPush:
    """LightBlockWidget._push_envelope_drag_undo, exercised unbound on
    a duck-typed stand-in (the method only reads drag flags and the
    block, and finds the stack via lane_widget)."""

    class _Stub:
        def __init__(self, stack, block):
            self.drag_start_time = 4.0
            self.drag_start_duration = 4.0
            self.dragging = True
            self.shift_drag_copying = False
            self.resizing_left = False
            self.resizing_right = False
            self.block = block
            # The drag finalize flips morphed provenance to hand_edited
            # (morph design doc 5.3); borrow the real hook so the stub
            # stays complete.
            from timeline_ui.light_block_widget import LightBlockWidget
            self._flip_morph_provenance = (
                LightBlockWidget._flip_morph_provenance.__get__(self))

            class _Lane:
                # A real LightLaneWidget carries light_block_widgets;
                # the Move/Resize commands iterate it on undo (an
                # exception inside a QUndoCommand called from C++ aborts
                # the process, so the stub must be complete).
                light_block_widgets = []

                def __init__(self, s):
                    self._s = s

                def _get_undo_stack(self):
                    return self._s
            self.lane_widget = _Lane(stack)

            class _Sig:
                def __init__(self):
                    self.count = 0

                def emit(self):
                    self.count += 1
            self.block_edited = _Sig()

    def _push(self, stub):
        from timeline_ui.light_block_widget import LightBlockWidget
        LightBlockWidget._push_envelope_drag_undo(stub)

    def test_completed_move_pushes_one_command(self, qapp):
        stack = QUndoStack(qapp)
        block = _block(6.0, 10.0)     # already moved from 4-8
        stub = self._Stub(stack, block)
        self._push(stub)
        assert stack.count() == 1
        assert stub.block_edited.count == 1
        stack.undo()
        assert (block.start_time, block.end_time) == (4.0, 8.0)

    def test_click_without_movement_pushes_nothing(self, qapp):
        stack = QUndoStack(qapp)
        block = _block(4.0, 8.0)      # unchanged from drag start
        stub = self._Stub(stack, block)
        self._push(stub)
        assert stack.count() == 0
        assert stub.block_edited.count == 0

    def test_resize_pushes_resize_command(self, qapp):
        stack = QUndoStack(qapp)
        block = _block(4.0, 12.0)     # end dragged from 8 to 12
        stub = self._Stub(stack, block)
        stub.dragging = False
        stub.resizing_right = True
        self._push(stub)
        assert stack.count() == 1
        stack.undo()
        assert block.end_time == 8.0

    def test_shift_copy_drag_pushes_nothing(self, qapp):
        # The copy routes through paste (its own command); the original
        # block was restored to its start position.
        stack = QUndoStack(qapp)
        block = _block(4.0, 8.0)
        stub = self._Stub(stack, block)
        stub.shift_drag_copying = True
        self._push(stub)
        assert stack.count() == 0
