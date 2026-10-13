"""Envelope edge drags trim or stretch the sublane blocks
(utils/envelope_edit.py, decision 2026-10-13).

The envelope is derived from the sublane blocks and playback reads only
the sublane times, so the old edge resize (it wrote the deprecated
LightBlock.duration, and only moved the start on the left) never changed
the show. A plain drag now trims like a DAW clip; an Alt-drag stretches
around the opposite edge.
"""

import pytest

from config.models import ColourBlock, DimmerBlock, LightBlock, MovementBlock
from utils import envelope_edit
from utils.envelope_edit import MIN_DURATION, EnvelopeState


def _block():
    """Dimmer 0-4 and 4-8, colour 2-8, movement 6-8: envelope 0-8."""
    block = LightBlock(start_time=0.0, end_time=8.0, effect_name="t",
                       dimmer_blocks=[DimmerBlock(start_time=0.0, end_time=4.0),
                                      DimmerBlock(start_time=4.0, end_time=8.0)],
                       colour_blocks=[ColourBlock(start_time=2.0, end_time=8.0)],
                       movement_blocks=[MovementBlock(start_time=6.0,
                                                      end_time=8.0)])
    return block, EnvelopeState.capture(block)


def _spans(blocks):
    return [(b.start_time, b.end_time) for b in blocks]


class TestTrim:
    def test_right_edge_cuts_crossing_and_drops_outside(self):
        block, state = _block()
        envelope_edit.apply(block, state, "right", 5.0, stretch=False)
        assert _spans(block.dimmer_blocks) == [(0.0, 4.0), (4.0, 5.0)]
        assert _spans(block.colour_blocks) == [(2.0, 5.0)]
        assert block.movement_blocks == []
        assert (block.start_time, block.end_time) == (0.0, 5.0)

    def test_left_edge(self):
        block, state = _block()
        envelope_edit.apply(block, state, "left", 3.0, stretch=False)
        assert _spans(block.dimmer_blocks) == [(3.0, 4.0), (4.0, 8.0)]
        assert _spans(block.colour_blocks) == [(3.0, 8.0)]
        assert (block.start_time, block.end_time) == (3.0, 8.0)

    def test_cannot_extend_past_the_content(self):
        block, state = _block()
        assert envelope_edit.apply(block, state, "right", 12.0,
                                   stretch=False) == 8.0
        assert envelope_edit.apply(block, state, "left", -3.0,
                                   stretch=False) == 0.0
        assert _spans(block.dimmer_blocks) == [(0.0, 4.0), (4.0, 8.0)]

    def test_never_shorter_than_the_minimum(self):
        block, state = _block()
        envelope_edit.apply(block, state, "right", -5.0, stretch=False)
        assert block.end_time - block.start_time == pytest.approx(MIN_DURATION)

    def test_every_step_starts_from_the_snapshot(self):
        """Dragging in and back out restores what the drag cut."""
        block, state = _block()
        envelope_edit.apply(block, state, "right", 3.0, stretch=False)
        envelope_edit.apply(block, state, "right", 8.0, stretch=False)
        assert _spans(block.dimmer_blocks) == [(0.0, 4.0), (4.0, 8.0)]
        assert _spans(block.movement_blocks) == [(6.0, 8.0)]

    def test_same_objects_survive(self):
        block, state = _block()
        first = block.dimmer_blocks[0]
        envelope_edit.apply(block, state, "right", 5.0, stretch=False)
        assert block.dimmer_blocks[0] is first


class TestStretch:
    def test_right_edge_scales_around_the_left(self):
        block, state = _block()
        envelope_edit.apply(block, state, "right", 16.0, stretch=True)
        assert _spans(block.dimmer_blocks) == [(0.0, 8.0), (8.0, 16.0)]
        assert _spans(block.colour_blocks) == [(4.0, 16.0)]
        assert _spans(block.movement_blocks) == [(12.0, 16.0)]
        assert (block.start_time, block.end_time) == (0.0, 16.0)

    def test_left_edge_scales_around_the_right(self):
        block, state = _block()
        envelope_edit.apply(block, state, "left", 4.0, stretch=True)
        assert _spans(block.dimmer_blocks) == [(4.0, 6.0), (6.0, 8.0)]
        assert _spans(block.colour_blocks) == [(5.0, 8.0)]

    def test_any_beat_ratio(self):
        """Not just x2 / x1/2: 8 s -> 6 s is a 3/4 squeeze."""
        block, state = _block()
        envelope_edit.apply(block, state, "right", 6.0, stretch=True)
        assert _spans(block.dimmer_blocks) == [(0.0, 3.0), (3.0, 6.0)]

    def test_never_shorter_than_the_minimum_or_before_zero(self):
        block, state = _block()
        envelope_edit.apply(block, state, "right", -1.0, stretch=True)
        assert block.end_time - block.start_time == pytest.approx(MIN_DURATION)
        block, state = _block()
        envelope_edit.apply(block, state, "left", -4.0, stretch=True)
        assert block.start_time == 0.0

    def test_switching_mode_mid_drag(self):
        block, state = _block()
        envelope_edit.apply(block, state, "right", 4.0, stretch=False)
        envelope_edit.apply(block, state, "right", 4.0, stretch=True)
        assert _spans(block.dimmer_blocks) == [(0.0, 2.0), (2.0, 4.0)]
        assert _spans(block.movement_blocks) == [(3.0, 4.0)]


class TestEnvelopeState:
    def test_restore_brings_back_lists_and_times(self):
        block, state = _block()
        envelope_edit.apply(block, state, "right", 1.0, stretch=False)
        state.restore(block)
        assert _spans(block.dimmer_blocks) == [(0.0, 4.0), (4.0, 8.0)]
        assert len(block.movement_blocks) == 1
        assert (block.start_time, block.end_time) == (0.0, 8.0)

    def test_empty_block_moves_its_edge(self):
        block = LightBlock(start_time=2.0, end_time=6.0, effect_name="t")
        state = EnvelopeState.capture(block)
        envelope_edit.apply(block, state, "right", 4.0, stretch=False)
        assert (block.start_time, block.end_time) == (2.0, 4.0)
