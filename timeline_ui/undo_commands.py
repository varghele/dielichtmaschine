# timeline_ui/undo_commands.py
"""Undo/redo commands for timeline operations."""

from PyQt6.QtGui import QUndoCommand
from config.models import LightBlock
from typing import List, TYPE_CHECKING

if TYPE_CHECKING:
    from timeline_ui.light_lane_widget import LightLaneWidget


class InsertRiffCommand(QUndoCommand):
    """Command to insert a riff as a LightBlock, removing overlapping blocks."""

    def __init__(self, lane_widget: 'LightLaneWidget', new_block: LightBlock,
                 removed_blocks: List[LightBlock], description: str = None):
        """Create insert riff command.

        Args:
            lane_widget: The LightLaneWidget where the riff is inserted
            new_block: The new LightBlock created from the riff
            removed_blocks: List of blocks that were removed due to overlap
            description: Optional description for undo stack
        """
        super().__init__(description or f"Insert Riff")
        self.lane_widget = lane_widget
        self.new_block = new_block
        self.removed_blocks = removed_blocks
        self._new_block_widget = None

    def redo(self):
        """Insert the riff block and remove overlapping blocks."""
        # Remove overlapping blocks (if any still exist from previous redo)
        for block in self.removed_blocks:
            if block in self.lane_widget.lane.light_blocks:
                # Find and remove widget
                widget = self._find_widget_for_block(block)
                if widget:
                    self.lane_widget.light_block_widgets.remove(widget)
                    widget.deleteLater()
                self.lane_widget.lane.light_blocks.remove(block)

        # Add the new block
        if self.new_block not in self.lane_widget.lane.light_blocks:
            self.lane_widget.lane.light_blocks.append(self.new_block)
            self.lane_widget.create_light_block_widget(self.new_block)
            # Store reference to the widget for undo
            self._new_block_widget = self._find_widget_for_block(self.new_block)

    def undo(self):
        """Remove the riff block and restore overlapping blocks."""
        # Remove the new block
        if self.new_block in self.lane_widget.lane.light_blocks:
            widget = self._find_widget_for_block(self.new_block)
            if widget:
                self.lane_widget.light_block_widgets.remove(widget)
                widget.deleteLater()
            self.lane_widget.lane.light_blocks.remove(self.new_block)

        # Restore the removed blocks
        for block in self.removed_blocks:
            if block not in self.lane_widget.lane.light_blocks:
                self.lane_widget.lane.light_blocks.append(block)
                self.lane_widget.create_light_block_widget(block)

    def _find_widget_for_block(self, block: LightBlock):
        """Find the widget for a given block."""
        for widget in self.lane_widget.light_block_widgets:
            if widget.block is block:
                return widget
        return None


class DeleteBlockCommand(QUndoCommand):
    """Command to delete a LightBlock."""

    def __init__(self, lane_widget: 'LightLaneWidget', block: LightBlock,
                 description: str = None):
        """Create delete block command.

        Args:
            lane_widget: The LightLaneWidget containing the block
            block: The block to delete
            description: Optional description for undo stack
        """
        super().__init__(description or "Delete Block")
        self.lane_widget = lane_widget
        self.block = block

    def redo(self):
        """Delete the block."""
        if self.block in self.lane_widget.lane.light_blocks:
            # Find and remove widget
            widget = self._find_widget_for_block(self.block)
            if widget:
                self.lane_widget.light_block_widgets.remove(widget)
                widget.deleteLater()
            self.lane_widget.lane.light_blocks.remove(self.block)

    def undo(self):
        """Restore the block."""
        if self.block not in self.lane_widget.lane.light_blocks:
            self.lane_widget.lane.light_blocks.append(self.block)
            self.lane_widget.create_light_block_widget(self.block)

    def _find_widget_for_block(self, block: LightBlock):
        """Find the widget for a given block."""
        for widget in self.lane_widget.light_block_widgets:
            if widget.block is block:
                return widget
        return None


class MoveBlockCommand(QUndoCommand):
    """Command to move a LightBlock to a new position.

    Pass ``already_applied=True`` when the move has ALREADY happened
    (the live drag mutated the block per pixel and the command is
    pushed on mouse release): QUndoStack.push() calls redo()
    immediately, and re-applying would shift the sublane blocks a
    second time.
    """

    def __init__(self, lane_widget: 'LightLaneWidget', block: LightBlock,
                 old_start: float, old_end: float,
                 new_start: float, new_end: float,
                 description: str = None, already_applied: bool = False):
        """Create move block command.

        Args:
            lane_widget: The LightLaneWidget containing the block
            block: The block being moved
            old_start: Original start time
            old_end: Original end time
            new_start: New start time
            new_end: New end time
            description: Optional description
            already_applied: The first redo() is a no-op (see class doc)
        """
        super().__init__(description or "Move Block")
        self.lane_widget = lane_widget
        self.block = block
        self.old_start = old_start
        self.old_end = old_end
        self.new_start = new_start
        self.new_end = new_end
        self._skip_first_redo = already_applied

    def redo(self):
        """Apply the move."""
        if self._skip_first_redo:
            self._skip_first_redo = False
            return
        self.block.start_time = self.new_start
        self.block.end_time = self.new_end
        self._update_sublane_times(self.old_start, self.new_start)
        self._update_block_widget()

    def undo(self):
        """Revert the move."""
        self.block.start_time = self.old_start
        self.block.end_time = self.old_end
        self._update_sublane_times(self.new_start, self.old_start)
        self._update_block_widget()

    def _update_sublane_times(self, old_start: float, new_start: float):
        """Update sublane block times based on offset."""
        offset = new_start - old_start

        for sub_block in self.block.dimmer_blocks:
            sub_block.start_time += offset
            sub_block.end_time += offset

        for sub_block in self.block.colour_blocks:
            sub_block.start_time += offset
            sub_block.end_time += offset

        for sub_block in self.block.movement_blocks:
            sub_block.start_time += offset
            sub_block.end_time += offset

        for sub_block in self.block.special_blocks:
            sub_block.start_time += offset
            sub_block.end_time += offset

    def _update_block_widget(self):
        """Update the block widget's position."""
        for widget in self.lane_widget.light_block_widgets:
            if widget.block is self.block:
                widget.update_position()
                break


class ResizeBlockCommand(QUndoCommand):
    """Command to resize a LightBlock."""

    def __init__(self, lane_widget: 'LightLaneWidget', block: LightBlock,
                 old_start: float, old_end: float,
                 new_start: float, new_end: float,
                 description: str = None):
        """Create resize block command.

        Args:
            lane_widget: The LightLaneWidget containing the block
            block: The block being resized
            old_start: Original start time
            old_end: Original end time
            new_start: New start time
            new_end: New end time
            description: Optional description
        """
        super().__init__(description or "Resize Block")
        self.lane_widget = lane_widget
        self.block = block
        self.old_start = old_start
        self.old_end = old_end
        self.new_start = new_start
        self.new_end = new_end

    def redo(self):
        """Apply the resize."""
        self.block.start_time = self.new_start
        self.block.end_time = self.new_end
        self._update_block_widget()

    def undo(self):
        """Revert the resize."""
        self.block.start_time = self.old_start
        self.block.end_time = self.old_end
        self._update_block_widget()

    def _update_block_widget(self):
        """Update the block widget's size."""
        for widget in self.lane_widget.light_block_widgets:
            if widget.block is self.block:
                widget.update_position()
                break


class AddLaneCommand(QUndoCommand):
    """Command for adding a whole lane to the Shows tab timeline.

    Built AFTER the lane was created and its widget added (the first
    redo is a no-op); undo/redo then remove/re-add the SAME runtime
    lane object through the tab's helpers, so block identities (and
    every block widget's ``.block`` reference) survive round trips.
    """

    def __init__(self, shows_tab, lane, description: str = None):
        super().__init__(description or "Add Lane")
        self.shows_tab = shows_tab
        self.lane = lane
        self._skip_first_redo = True

    def redo(self):
        if self._skip_first_redo:
            self._skip_first_redo = False
            return
        self.shows_tab._add_lane_widget(self.lane)

    def undo(self):
        for widget in list(self.shows_tab.lane_widgets):
            if widget.lane is self.lane:
                self.shows_tab._remove_lane_widget(widget)
                break


class RemoveLaneCommand(QUndoCommand):
    """Command for removing a lane.

    Undo re-adds the SAME runtime lane object (its widget is rebuilt
    from lane.light_blocks by the LightLaneWidget constructor, so every
    block survives). The restored lane appears at the BOTTOM of the
    timeline - the grid only appends rows; index-preserving restore is
    a future nicety.
    """

    def __init__(self, shows_tab, lane_widget, description: str = None):
        super().__init__(description or "Remove Lane")
        self.shows_tab = shows_tab
        self.lane = lane_widget.lane

    def redo(self):
        for widget in list(self.shows_tab.lane_widgets):
            if widget.lane is self.lane:
                self.shows_tab._remove_lane_widget(widget)
                break

    def undo(self):
        self.shows_tab._add_lane_widget(self.lane)


class AddBlockCommand(QUndoCommand):
    """Command to add a new LightBlock."""

    def __init__(self, lane_widget: 'LightLaneWidget', block: LightBlock,
                 description: str = None):
        """Create add block command.

        Args:
            lane_widget: The LightLaneWidget where the block is added
            block: The new block
            description: Optional description
        """
        super().__init__(description or "Add Block")
        self.lane_widget = lane_widget
        self.block = block

    def redo(self):
        """Add the block."""
        if self.block not in self.lane_widget.lane.light_blocks:
            self.lane_widget.lane.light_blocks.append(self.block)
            self.lane_widget.create_light_block_widget(self.block)

    def undo(self):
        """Remove the block."""
        if self.block in self.lane_widget.lane.light_blocks:
            widget = self._find_widget_for_block(self.block)
            if widget:
                self.lane_widget.light_block_widgets.remove(widget)
                widget.deleteLater()
            self.lane_widget.lane.light_blocks.remove(self.block)

    def _find_widget_for_block(self, block: LightBlock):
        """Find the widget for a given block."""
        for widget in self.lane_widget.light_block_widgets:
            if widget.block is block:
                return widget
        return None
