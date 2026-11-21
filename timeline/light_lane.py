# timeline/light_lane.py
# Runtime light lane class for timeline playback

from typing import List, Optional
from config.models import LightBlock


class LightLane:
    """Runtime light lane for timeline editing and playback.

    This class wraps the data model LightLane from config.models
    and provides additional runtime functionality.
    """

    def __init__(self, name: str, fixture_targets: List[str] = None):
        """Create a new light lane.

        Args:
            name: Display name for the lane
            fixture_targets: List of fixture target strings (group names or "group:index")
        """
        self.name = name
        self.fixture_targets = fixture_targets or []
        self.muted = False
        self.solo = False
        self.light_blocks: List[LightBlock] = []

    @property
    def fixture_group(self) -> str:
        """Backward compatibility: returns first target or empty string."""
        return self.fixture_targets[0] if self.fixture_targets else ""

    @fixture_group.setter
    def fixture_group(self, value: str):
        """Backward compatibility: sets single target."""
        self.fixture_targets = [value] if value else []

    def add_light_block(self, start_time: float, duration: float,
                        effect_name: str = "") -> LightBlock:
        """Add a new light block to this lane (legacy method).

        Args:
            start_time: Start time in seconds
            duration: Duration in seconds
            effect_name: Effect name (e.g., "bars.static")

        Returns:
            The created LightBlock
        """
        block = LightBlock(
            start_time=start_time,
            end_time=start_time + duration,
            effect_name=effect_name,
        )
        self.light_blocks.append(block)
        return block

    def add_light_block_with_sublanes(self, start_time: float, end_time: float,
                                      effect_name: str = "",
                                      dimmer_block=None, colour_block=None,
                                      movement_block=None, special_block=None,
                                      dimmer_blocks=None, colour_blocks=None,
                                      movement_blocks=None, special_blocks=None) -> LightBlock:
        """Add a new light block with sublane blocks.

        Args:
            start_time: Envelope start time in seconds
            end_time: Envelope end time in seconds
            effect_name: Effect name (e.g., "bars.static")
            dimmer_block: Optional single DimmerBlock (legacy, converted to list)
            colour_block: Optional single ColourBlock (legacy, converted to list)
            movement_block: Optional single MovementBlock (legacy, converted to list)
            special_block: Optional single SpecialBlock (legacy, converted to list)
            dimmer_blocks: Optional list of DimmerBlocks (new format)
            colour_blocks: Optional list of ColourBlocks (new format)
            movement_blocks: Optional list of MovementBlocks (new format)
            special_blocks: Optional list of SpecialBlocks (new format)

        Returns:
            The created LightBlock
        """
        # Handle both legacy single-block args and new list args
        final_dimmer_blocks = dimmer_blocks or ([] if dimmer_block is None else [dimmer_block])
        final_colour_blocks = colour_blocks or ([] if colour_block is None else [colour_block])
        final_movement_blocks = movement_blocks or ([] if movement_block is None else [movement_block])
        final_special_blocks = special_blocks or ([] if special_block is None else [special_block])

        block = LightBlock(
            start_time=start_time,
            end_time=end_time,
            effect_name=effect_name,
            modified=False,
            dimmer_blocks=final_dimmer_blocks,
            colour_blocks=final_colour_blocks,
            movement_blocks=final_movement_blocks,
            special_blocks=final_special_blocks
        )
        self.light_blocks.append(block)
        return block

    def remove_light_block(self, block: LightBlock):
        """Remove a light block from this lane.

        Args:
            block: The block to remove
        """
        if block in self.light_blocks:
            self.light_blocks.remove(block)

    def get_block_at_time(self, time: float) -> Optional[LightBlock]:
        """Get the block at a specific time.

        Args:
            time: Time position in seconds

        Returns:
            LightBlock at that time, or None
        """
        for block in self.light_blocks:
            if block.start_time <= time < block.end_time:
                return block
        return None

    def get_blocks_in_range(self, start_time: float, end_time: float) -> List[LightBlock]:
        """Get all blocks that overlap with a time range.

        Args:
            start_time: Start of range in seconds
            end_time: End of range in seconds

        Returns:
            List of overlapping blocks
        """
        blocks = []
        for block in self.light_blocks:
            # Check if block overlaps with range
            if block.start_time < end_time and block.end_time > start_time:
                blocks.append(block)
        return blocks

    def to_data_model(self):
        """Convert to config.models.LightLane for serialization.

        Returns:
            LightLane data model instance
        """
        from config.models import LightLane as LightLaneModel
        lane_model = LightLaneModel(
            name=self.name,
            fixture_targets=self.fixture_targets.copy(),
            muted=self.muted,
            solo=self.solo,
            light_blocks=self.light_blocks.copy()
        )
        return lane_model

    @classmethod
    def from_data_model(cls, lane_model) -> 'LightLane':
        """Create from config.models.LightLane.

        Args:
            lane_model: LightLane data model instance

        Returns:
            New LightLane instance
        """
        # Handle both new fixture_targets and old fixture_group
        targets = getattr(lane_model, 'fixture_targets', None)
        if targets is None:
            old_group = getattr(lane_model, 'fixture_group', '')
            targets = [old_group] if old_group else []

        lane = cls(
            name=lane_model.name,
            fixture_targets=targets
        )
        lane.muted = lane_model.muted
        lane.solo = lane_model.solo
        lane.light_blocks = lane_model.light_blocks.copy()
        return lane
