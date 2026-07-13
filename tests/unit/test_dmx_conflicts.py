"""DMX address lint (utils/dmx_conflicts.py).

Overlap is defined on the inclusive address range of each fixture's
current mode, per universe. The lint is what the Fixtures tab renders
as per-row conflict warnings, so these tests pin the exact pairing and
overlap-range semantics.
"""

from config.models import Fixture, FixtureMode
from utils.dmx_conflicts import (
    DMX_MAX_ADDRESS,
    fixture_address_range,
    fixture_channel_count,
    lint_dmx_addresses,
)


def make_fixture(name, universe, address, channels=10, mode_name="Standard",
                 current_mode=None, extra_modes=()):
    modes = [FixtureMode(name=mode_name, channels=channels)]
    modes.extend(FixtureMode(name=n, channels=c) for n, c in extra_modes)
    return Fixture(
        universe=universe,
        address=address,
        manufacturer="TestMfr",
        model="TestModel",
        name=name,
        group="",
        current_mode=current_mode or mode_name,
        available_modes=modes,
    )


class TestChannelCount:

    def test_current_mode_wins(self):
        f = make_fixture("A", 1, 1, channels=10,
                         extra_modes=[("Extended", 24)], current_mode="Extended")
        assert fixture_channel_count(f) == 24

    def test_drifted_mode_falls_back_to_first(self):
        f = make_fixture("A", 1, 1, channels=10, current_mode="NoSuchMode")
        assert fixture_channel_count(f) == 10

    def test_no_modes_falls_back_to_one(self):
        f = make_fixture("A", 1, 1)
        f.available_modes = []
        assert fixture_channel_count(f) == 1

    def test_address_range_is_inclusive(self):
        f = make_fixture("A", 1, 10, channels=6)
        assert fixture_address_range(f) == (10, 15)


class TestOverlapDetection:

    def test_no_fixtures_is_clean(self):
        assert lint_dmx_addresses([]).is_clean

    def test_adjacent_fixtures_do_not_conflict(self):
        fixtures = [
            make_fixture("A", 1, 1, channels=10),    # 1-10
            make_fixture("B", 1, 11, channels=10),   # 11-20
        ]
        assert lint_dmx_addresses(fixtures).is_clean

    def test_single_channel_overlap(self):
        fixtures = [
            make_fixture("A", 1, 1, channels=10),    # 1-10
            make_fixture("B", 1, 10, channels=10),   # 10-19
        ]
        lint = lint_dmx_addresses(fixtures)
        assert len(lint.conflicts) == 1
        c = lint.conflicts[0]
        assert (c.index_a, c.index_b) == (0, 1)
        assert (c.overlap_start, c.overlap_end) == (10, 10)
        assert c.universe == 1

    def test_same_address_different_universe_is_clean(self):
        fixtures = [
            make_fixture("A", 1, 1, channels=10),
            make_fixture("B", 2, 1, channels=10),
        ]
        assert lint_dmx_addresses(fixtures).is_clean

    def test_contained_range_reports_full_containment(self):
        fixtures = [
            make_fixture("A", 1, 1, channels=100),   # 1-100
            make_fixture("B", 1, 20, channels=5),    # 20-24
        ]
        lint = lint_dmx_addresses(fixtures)
        assert len(lint.conflicts) == 1
        c = lint.conflicts[0]
        assert (c.overlap_start, c.overlap_end) == (20, 24)

    def test_three_way_pileup_reports_each_pair_once(self):
        fixtures = [
            make_fixture("A", 1, 1, channels=10),    # 1-10
            make_fixture("B", 1, 5, channels=10),    # 5-14
            make_fixture("C", 1, 8, channels=10),    # 8-17
        ]
        lint = lint_dmx_addresses(fixtures)
        pairs = {(c.index_a, c.index_b) for c in lint.conflicts}
        assert pairs == {(0, 1), (0, 2), (1, 2)}
        assert len(lint.conflicts) == 3

    def test_conflict_uses_current_mode_channels(self):
        # In 10ch mode A ends at 10 and B starts at 11: clean.
        # In its 24ch mode A ends at 24: conflict.
        fixtures = [
            make_fixture("A", 1, 1, channels=10,
                         extra_modes=[("Extended", 24)], current_mode="Extended"),
            make_fixture("B", 1, 11, channels=10),
        ]
        lint = lint_dmx_addresses(fixtures)
        assert len(lint.conflicts) == 1

    def test_by_fixture_maps_both_sides(self):
        fixtures = [
            make_fixture("A", 1, 1, channels=10),
            make_fixture("B", 1, 5, channels=10),
            make_fixture("C", 2, 1, channels=10),
        ]
        by_fixture = lint_dmx_addresses(fixtures).by_fixture()
        assert set(by_fixture.keys()) == {0, 1}
        assert len(by_fixture[0]) == 1
        assert len(by_fixture[1]) == 1


class TestOverflow:

    def test_footprint_past_512_is_flagged(self):
        f = make_fixture("A", 1, 510, channels=10)   # 510-519
        lint = lint_dmx_addresses([f])
        assert len(lint.overflows) == 1
        o = lint.overflows[0]
        assert o.index == 0
        assert o.end_address == 519
        assert not lint.is_clean

    def test_footprint_ending_exactly_at_512_is_clean(self):
        f = make_fixture("A", 1, DMX_MAX_ADDRESS - 9, channels=10)  # 503-512
        assert lint_dmx_addresses([f]).is_clean

    def test_overflow_appears_in_by_fixture(self):
        f = make_fixture("A", 1, 510, channels=10)
        by_fixture = lint_dmx_addresses([f]).by_fixture()
        assert 0 in by_fixture


class TestUntangleAddresses:
    """Untangle: move ONLY the offenders, each to the nearest free
    range; the lower-addressed member of a pair stays put."""

    def test_clean_patch_is_untouched(self):
        fixtures = [make_fixture("A", 1, 1), make_fixture("B", 1, 11)]
        from utils.dmx_conflicts import untangle_addresses
        assert untangle_addresses(fixtures) == ({}, [])

    def test_second_of_a_pair_moves_to_nearest_free(self):
        # A 1-10, B 5-14 overlap; C 21-30 is clean and pins its range.
        fixtures = [make_fixture("A", 1, 1), make_fixture("B", 1, 5),
                    make_fixture("C", 1, 21)]
        from utils.dmx_conflicts import untangle_addresses
        moves, unresolved = untangle_addresses(fixtures)
        assert unresolved == []
        assert 0 not in moves, "lower-addressed member stays put"
        assert 2 not in moves, "clean fixture stays put"
        # Nearest free 10-wide slot for B (current 5): 11-20 (delta 6).
        assert moves[1] == 11

    def test_result_is_lint_clean(self):
        fixtures = [make_fixture("A", 1, 1), make_fixture("B", 1, 5),
                    make_fixture("C", 1, 8), make_fixture("D", 1, 30)]
        from utils.dmx_conflicts import untangle_addresses
        moves, unresolved = untangle_addresses(fixtures)
        assert unresolved == []
        for i, address in moves.items():
            fixtures[i].address = address
        assert lint_dmx_addresses(fixtures).is_clean

    def test_overflow_is_pulled_back_into_range(self):
        fixtures = [make_fixture("A", 1, 510)]   # runs past 512
        from utils.dmx_conflicts import untangle_addresses
        moves, unresolved = untangle_addresses(fixtures)
        assert unresolved == []
        assert moves[0] == 503                  # nearest fit: 503-512

    def test_universes_are_independent(self):
        fixtures = [make_fixture("A", 1, 1), make_fixture("B", 2, 1)]
        from utils.dmx_conflicts import untangle_addresses
        assert untangle_addresses(fixtures) == ({}, [])

    def test_unplaceable_fixture_is_reported_not_moved(self):
        # 52 ten-channel fixtures fill 1-520 > 512: the universe is
        # genuinely full, the last flagged one cannot fit anywhere.
        fixtures = [make_fixture(f"F{i}", 1, 1 + i * 10) for i in range(51)]
        fixtures.append(make_fixture("Extra", 1, 5))   # overlaps F0/F1
        from utils.dmx_conflicts import untangle_addresses
        moves, unresolved = untangle_addresses(fixtures)
        assert unresolved == [51]
        assert 51 not in moves
        assert fixtures[51].address == 5


class TestCompactAddresses:
    """Compact: gap-free repack per universe, order preserved."""

    def test_gaps_close_and_order_holds(self):
        fixtures = [make_fixture("A", 1, 41), make_fixture("B", 1, 101),
                    make_fixture("C", 1, 1)]
        from utils.dmx_conflicts import compact_addresses
        moves, unresolved = compact_addresses(fixtures)
        assert unresolved == []
        # Order by current address: C(1) A(41) B(101) -> 1, 11, 21.
        assert moves == {0: 11, 1: 21}          # C already at 1
        for i, address in moves.items():
            fixtures[i].address = address
        assert [f.address for f in fixtures] == [11, 21, 1]
        assert lint_dmx_addresses(fixtures).is_clean

    def test_universes_pack_independently(self):
        fixtures = [make_fixture("A", 1, 50), make_fixture("B", 2, 50)]
        from utils.dmx_conflicts import compact_addresses
        moves, _ = compact_addresses(fixtures)
        assert moves == {0: 1, 1: 1}

    def test_already_compact_is_a_no_op(self):
        fixtures = [make_fixture("A", 1, 1), make_fixture("B", 1, 11)]
        from utils.dmx_conflicts import compact_addresses
        assert compact_addresses(fixtures) == ({}, [])

    def test_overfull_universe_reports_the_rest(self):
        fixtures = [make_fixture(f"F{i}", 1, 1 + i * 10, channels=200)
                    for i in range(3)]
        from utils.dmx_conflicts import compact_addresses
        moves, unresolved = compact_addresses(fixtures)
        # 200+200 fit (1, 201); the third would end at 600 -> reported.
        assert moves == {1: 201}                 # F0 already at 1
        assert unresolved == [2]
