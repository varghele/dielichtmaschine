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
