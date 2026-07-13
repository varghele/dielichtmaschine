# utils/dmx_conflicts.py
"""DMX address lint: overlapping fixture footprints and universe overflow.

Pure functions over the Fixture dataclass (duck-typed to avoid the
config.models -> utils import cycle). The Fixtures tab renders the
result as per-row warnings; the checks themselves stay UI-free so
they can also guard exports or a future headless CLI.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Tuple

DMX_MAX_ADDRESS = 512


def fixture_channel_count(fixture) -> int:
    """Channel count of the fixture's current mode.

    Falls back to the first available mode when current_mode has
    drifted out of sync with available_modes (same convention as the
    Fixtures tab's channel column), and to 1 when no modes exist.
    """
    for mode in fixture.available_modes:
        if mode.name == fixture.current_mode:
            return mode.channels
    if fixture.available_modes:
        return fixture.available_modes[0].channels
    return 1


def fixture_address_range(fixture) -> Tuple[int, int]:
    """Inclusive (start, end) DMX address range the fixture occupies."""
    start = fixture.address
    return start, start + fixture_channel_count(fixture) - 1


@dataclass(frozen=True)
class AddressConflict:
    """Two fixtures overlapping on the same universe."""
    universe: int
    index_a: int            # indices into the fixtures list passed to lint
    index_b: int
    overlap_start: int      # inclusive DMX address range shared by both
    overlap_end: int


@dataclass(frozen=True)
class AddressOverflow:
    """A fixture whose footprint runs past DMX address 512."""
    universe: int
    index: int
    end_address: int


@dataclass
class DmxLint:
    conflicts: List[AddressConflict] = field(default_factory=list)
    overflows: List[AddressOverflow] = field(default_factory=list)

    @property
    def is_clean(self) -> bool:
        return not self.conflicts and not self.overflows

    def by_fixture(self) -> Dict[int, List]:
        """Map fixture index -> the findings involving it (both kinds)."""
        result: Dict[int, List] = {}
        for c in self.conflicts:
            result.setdefault(c.index_a, []).append(c)
            result.setdefault(c.index_b, []).append(c)
        for o in self.overflows:
            result.setdefault(o.index, []).append(o)
        return result


def lint_dmx_addresses(fixtures) -> DmxLint:
    """Check a fixture list for address overlaps and universe overflow.

    Overlap is pairwise per universe on the inclusive address range of
    each fixture's current mode. Every overlapping pair is reported
    once, with index_a < index_b.
    """
    lint = DmxLint()

    ranges = []  # (index, universe, start, end)
    for i, fixture in enumerate(fixtures):
        start, end = fixture_address_range(fixture)
        ranges.append((i, fixture.universe, start, end))
        if end > DMX_MAX_ADDRESS:
            lint.overflows.append(
                AddressOverflow(universe=fixture.universe, index=i, end_address=end)
            )

    by_universe: Dict[int, List[Tuple[int, int, int]]] = {}
    for i, universe, start, end in ranges:
        by_universe.setdefault(universe, []).append((start, end, i))

    for universe, entries in by_universe.items():
        entries.sort()
        for pos, (start, end, i) in enumerate(entries):
            for other_start, other_end, j in entries[pos + 1:]:
                if other_start > end:
                    break  # sorted by start: no later entry can overlap either
                lint.conflicts.append(
                    AddressConflict(
                        universe=universe,
                        index_a=min(i, j),
                        index_b=max(i, j),
                        overlap_start=other_start,
                        overlap_end=min(end, other_end),
                    )
                )

    return lint


# ---------------------------------------------------------------------------
# Auto-repair: Untangle (fix overlaps in place) and Compact (remove gaps)
# ---------------------------------------------------------------------------

def _occupied_overlaps(occupied: List[Tuple[int, int]], start: int,
                       end: int) -> bool:
    return any(not (end < s or start > e) for s, e in occupied)


def untangle_addresses(fixtures) -> Tuple[Dict[int, int], List[int]]:
    """Resolve address overlaps/overflow by moving ONLY the offenders.

    Clean fixtures stay exactly where they are. Flagged fixtures are
    visited per universe in (address, name) order; each keeps its
    current address if that is free by now (so the lower-addressed
    member of an overlapping pair stays put), else it moves to the
    free slot NEAREST its current address (ties break toward the lower
    address). A fixture whose footprint fits nowhere is left unchanged
    and reported.

    Returns ``(moves, unresolved)``: ``moves`` maps fixture index ->
    new address (only actual changes), ``unresolved`` lists indices
    that could not be placed.
    """
    lint = lint_dmx_addresses(fixtures)
    flagged = set(lint.by_fixture())
    moves: Dict[int, int] = {}
    unresolved: List[int] = []

    by_universe: Dict[int, List[int]] = {}
    for i, fixture in enumerate(fixtures):
        by_universe.setdefault(fixture.universe, []).append(i)

    for universe, indices in sorted(by_universe.items()):
        occupied: List[Tuple[int, int]] = []
        # Clean fixtures are pinned first.
        for i in indices:
            if i not in flagged:
                occupied.append(fixture_address_range(fixtures[i]))

        ordered = sorted((i for i in indices if i in flagged),
                         key=lambda i: (fixtures[i].address,
                                        getattr(fixtures[i], "name", "")))

        # Pass 1: every flagged fixture that can KEEP its current
        # address (free against the pinned and already-kept ranges)
        # does, in address order - so incumbents whose ranges work stay
        # put and only the actual intruders relocate. Keeping runs
        # BEFORE any relocation so a mover can never grab an address an
        # incumbent was about to keep.
        to_relocate: List[int] = []
        for i in ordered:
            start, end = fixture_address_range(fixtures[i])
            if end <= DMX_MAX_ADDRESS and \
                    not _occupied_overlaps(occupied, start, end):
                occupied.append((start, end))
            else:
                to_relocate.append(i)

        # Pass 2: relocate the rest, each to the nearest free slot.
        for i in to_relocate:
            footprint = fixture_channel_count(fixtures[i])
            current = fixtures[i].address
            candidates = [
                s for s in range(1, DMX_MAX_ADDRESS - footprint + 2)
                if not _occupied_overlaps(occupied, s, s + footprint - 1)
            ]
            if not candidates:
                unresolved.append(i)
                continue
            best = min(candidates, key=lambda s: (abs(s - current), s))
            moves[i] = best
            occupied.append((best, best + footprint - 1))

    return moves, unresolved


def compact_addresses(fixtures) -> Tuple[Dict[int, int], List[int]]:
    """Repack every universe to consecutive addresses with no gaps.

    Fixtures keep their relative (address, name) order and get packed
    from address 1 up. Fixtures whose footprint no longer fits inside
    the universe are left unchanged and reported.

    Returns ``(moves, unresolved)`` like :func:`untangle_addresses`.
    """
    moves: Dict[int, int] = {}
    unresolved: List[int] = []

    by_universe: Dict[int, List[int]] = {}
    for i, fixture in enumerate(fixtures):
        by_universe.setdefault(fixture.universe, []).append(i)

    for universe, indices in sorted(by_universe.items()):
        next_address = 1
        for i in sorted(indices, key=lambda i: (fixtures[i].address,
                                                getattr(fixtures[i],
                                                        "name", ""))):
            footprint = fixture_channel_count(fixtures[i])
            if next_address + footprint - 1 > DMX_MAX_ADDRESS:
                unresolved.append(i)
                continue
            if fixtures[i].address != next_address:
                moves[i] = next_address
            next_address += footprint

    return moves, unresolved
