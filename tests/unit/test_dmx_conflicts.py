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
