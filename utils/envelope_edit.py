"""Trim and stretch a light block by dragging its envelope edge.

A LightBlock's envelope is DERIVED: it spans its sublane blocks
(``LightBlock.update_envelope_bounds``), and playback and export read
only the sublane times. So dragging an envelope edge has to act on the
sublane blocks (decision 2026-10-13):

- **trim** (plain drag): the dragged edge cuts the sublane blocks that
  cross it and drops the ones left wholly outside, like trimming a clip
  in a DAW. There is nothing hidden to reveal, so the edge cannot be
  dragged out past the content.
- **stretch** (Alt-drag): every sublane time scales around the opposite
  edge, so a 4-bar build dragged to 8 bars lasts 8 bars. Effect speeds
  are beat-relative and stay on the grid; fades and cascades run over
  their block's span and stretch with it.

Every drag step is computed from the snapshot taken at mouse press, so
switching between trim and stretch mid-drag just changes the result.
Qt-free; the caller holds utils.timeline_edit_lock around ``apply``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple

SUBLANE_LISTS = ("dimmer_blocks", "colour_blocks", "movement_blocks",
                 "special_blocks")

# Shortest block the edge drag will produce, in seconds (the old
# envelope resize used the same floor).
MIN_DURATION = 0.1

_EPS = 1e-9


@dataclass
class EnvelopeState:
    """A light block's envelope plus every sublane block's interval and
    list membership. Restoring it brings back the SAME block objects
    (deleted ones included), so playback identity survives undo."""
    start: float
    end: float
    sublanes: Dict[str, List[Tuple[object, float, float]]]

    @classmethod
    def capture(cls, block) -> "EnvelopeState":
        return cls(
            start=block.start_time, end=block.end_time,
            sublanes={name: [(sub, sub.start_time, sub.end_time)
                             for sub in getattr(block, name)]
                      for name in SUBLANE_LISTS})

    def restore(self, block) -> None:
        for name, entries in self.sublanes.items():
            for sub, start, end in entries:
                sub.start_time = start
                sub.end_time = end
            setattr(block, name, [sub for sub, _, _ in entries])
        block.start_time = self.start
        block.end_time = self.end

    def content_bounds(self) -> Tuple[float, float]:
        """(earliest start, latest end) over the sublane blocks; the
        envelope when there are none."""
        entries = [e for es in self.sublanes.values() for e in es]
        if not entries:
            return self.start, self.end
        return (min(s for _, s, _ in entries), max(e for _, _, e in entries))


def clamp_edge(state: EnvelopeState, edge: str, new_time: float,
               stretch: bool) -> float:
    """The dragged edge's time after the mode's limits: never closer
    than MIN_DURATION to the other edge, never below 0, and for a trim
    never past the content."""
    lo, hi = state.content_bounds()
    if edge == "left":
        if not stretch:
            new_time = max(new_time, lo)
        return max(0.0, min(new_time, hi - MIN_DURATION))
    if not stretch:
        new_time = min(new_time, hi)
    return max(new_time, lo + MIN_DURATION)


def apply(block, state: EnvelopeState, edge: str, new_time: float,
          stretch: bool) -> float:
    """Set ``block`` to ``state`` trimmed or stretched so its ``edge``
    ("left"/"right") sits at ``new_time`` (clamped, see clamp_edge).
    Returns the clamped edge time."""
    new_time = clamp_edge(state, edge, new_time, stretch)
    lo, hi = state.content_bounds()
    state.restore(block)

    if stretch and hi - lo > _EPS:
        anchor = hi if edge == "left" else lo
        moved = lo if edge == "left" else hi
        scale = (new_time - anchor) / (moved - anchor)
        for name in SUBLANE_LISTS:
            for sub in getattr(block, name):
                start = anchor + (sub.start_time - anchor) * scale
                end = anchor + (sub.end_time - anchor) * scale
                sub.start_time, sub.end_time = min(start, end), max(start, end)
    else:
        win_lo, win_hi = (new_time, hi) if edge == "left" else (lo, new_time)
        for name in SUBLANE_LISTS:
            kept = []
            for sub in getattr(block, name):
                if sub.end_time <= win_lo + _EPS or sub.start_time >= win_hi - _EPS:
                    continue                    # wholly outside: dropped
                sub.start_time = max(sub.start_time, win_lo)
                sub.end_time = min(sub.end_time, win_hi)
                kept.append(sub)
            setattr(block, name, kept)

    if any(getattr(block, name) for name in SUBLANE_LISTS):
        block.update_envelope_bounds()
    elif edge == "left":
        block.start_time = new_time         # an empty block: move the edge
    else:
        block.end_time = new_time
    return new_time
