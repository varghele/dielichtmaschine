"""Tests for group activation roles in auto-generation."""

from autogen.spatial import (
    ActivationRole, GroupClassification,
    compute_richness_weights, assign_group_roles,
)
from autogen.generator import _generate_section_blocks
from autogen.matcher import AutogenConfig
from config.models import LightLane, ShowPart


# ── Helpers ──────────────────────────────────────────────


def _make_classifications(with_mh=True):
    """Create a typical set of group classifications."""
    groups = {
        "Front Wash": GroupClassification("Front Wash", "front", has_moving_heads=False),
        "Bars": GroupClassification("Bars", "mid", has_moving_heads=False),
        "Moving Heads": GroupClassification("Moving Heads", "back", has_moving_heads=True),
    }
    if not with_mh:
        del groups["Moving Heads"]
    return groups


def _make_lane():
    return LightLane(
        name="Test", fixture_targets=["Test"], muted=False, solo=False, light_blocks=[]
    )


def _make_part(num_bars=8, bpm=120.0):
    return ShowPart(
        name="Test Section", color="#FFFFFF", signature="4/4",
        bpm=bpm, num_bars=num_bars, transition="instant",
        start_time=0.0, duration=num_bars * (60.0 / bpm) * 4,
    )


# ── Weight Tests (compute_richness_weights) ──────────────


class TestWeights:

    def test_high_energy_all_active(self):
        groups = _make_classifications()
        result = compute_richness_weights(groups, 0.8, 0.8, relative_energy=0.8)
        for name, weight in result.items():
            assert weight > 0.0

    def test_very_quiet_single_active(self):
        groups = _make_classifications()
        result = compute_richness_weights(groups, 0.1, 0.1, relative_energy=0.1)
        active = [n for n, w in result.items() if w > 0.0]
        assert len(active) == 1

    def test_low_energy_limited_active(self):
        groups = _make_classifications()
        result = compute_richness_weights(groups, 0.3, 0.3, relative_energy=0.25)
        active = [n for n, w in result.items() if w > 0.0]
        assert 1 <= len(active) <= 2

    def test_empty_groups(self):
        result = compute_richness_weights({}, 0.5, 0.5, 0.5)
        assert result == {}


# ── Role Assignment Tests (assign_group_roles) ───────────


class TestRoleAssignment:

    def test_high_energy_all_full(self):
        """At high energy, all groups should be FULL regardless of rudiment."""
        rudiments = {
            "A": ("stroke", "cascade"),     # spike category
            "B": ("static", "pulse"),       # flat category
            "C": ("sparkle", "stroke"),     # stochastic category
        }
        roles = assign_group_roles(rudiments, relative_energy=0.8)
        for role in roles.values():
            assert role == ActivationRole.FULL

    def test_medium_energy_spike_becomes_fill(self):
        """At medium energy, spike-category groove → FILL_ONLY."""
        rudiments = {
            "Wash": ("pulse", "stroke"),      # oscillating → FULL
            "MH": ("stroke", "cascade"),      # spike → FILL_ONLY
        }
        roles = assign_group_roles(rudiments, relative_energy=0.5)
        assert roles["Wash"] == ActivationRole.FULL
        assert roles["MH"] == ActivationRole.FILL_ONLY

    def test_medium_energy_stochastic_becomes_fill(self):
        """At medium energy, stochastic-category groove → FILL_ONLY."""
        rudiments = {
            "Bars": ("wave", "sparkle"),       # rolling → FULL
            "FX": ("random_stroke", "stroke"), # stochastic → FILL_ONLY
        }
        roles = assign_group_roles(rudiments, relative_energy=0.5)
        assert roles["Bars"] == ActivationRole.FULL
        assert roles["FX"] == ActivationRole.FILL_ONLY

    def test_medium_energy_oscillating_stays_full(self):
        """Oscillating-category grooves stay FULL at medium energy."""
        rudiments = {
            "A": ("pulse", "stroke"),       # oscillating
            "B": ("throb", "cascade"),      # oscillating
        }
        roles = assign_group_roles(rudiments, relative_energy=0.5)
        assert roles["A"] == ActivationRole.FULL
        assert roles["B"] == ActivationRole.FULL

    def test_low_energy_groove_character_becomes_groove_only(self):
        """At low energy, groove-character rudiments → GROOVE_ONLY."""
        rudiments = {
            "Wash": ("static", "stroke"),  # flat → GROOVE_ONLY
            "MH": ("stroke", "cascade"),   # spike → FILL_ONLY
        }
        roles = assign_group_roles(rudiments, relative_energy=0.2)
        assert roles["Wash"] == ActivationRole.GROOVE_ONLY
        assert roles["MH"] == ActivationRole.FILL_ONLY

    def test_safety_at_least_one_groove_carrier(self):
        """If all groups are fill-character, promote one to carry groove."""
        rudiments = {
            "A": ("stroke", "cascade"),      # spike
            "B": ("random_stroke", "stroke"),  # stochastic
        }
        roles = assign_group_roles(rudiments, relative_energy=0.5)
        has_groove = any(r != ActivationRole.FILL_ONLY for r in roles.values())
        assert has_groove

    def test_empty_rudiments(self):
        roles = assign_group_roles({}, relative_energy=0.5)
        assert roles == {}

    def test_roles_vary_by_rudiment_not_fixture_type(self):
        """Same group gets different role depending on its assigned rudiment."""
        # MH with a sustaining groove → FULL
        roles_a = assign_group_roles(
            {"Wash": ("pulse", "stroke"), "MH": ("wave", "stroke")},
            relative_energy=0.5,
        )
        assert roles_a["MH"] == ActivationRole.FULL

        # MH with a punchy groove → FILL_ONLY (Wash carries groove)
        roles_b = assign_group_roles(
            {"Wash": ("pulse", "stroke"), "MH": ("stroke", "cascade")},
            relative_energy=0.5,
        )
        assert roles_b["MH"] == ActivationRole.FILL_ONLY


# ── Block Generation Role Tests ──────────────────────────


class TestBlockGenerationRoles:

    def _count_blocks(self, role, num_bars=8, phrase_bars=4, ratio=0.75):
        lane = _make_lane()
        part = _make_part(num_bars=num_bars)
        config = AutogenConfig(phrase_length_bars=phrase_bars, groove_fill_ratio=ratio)
        _generate_section_blocks(
            lane=lane, part=part,
            groove_name="pulse", fill_name="stroke",
            movement_strategy=None,
            color_assignment=None,
            gobo_prism={},
            weight=1.0, config=config,
            color_index=0, effect_speed="1",
            role=role,
        )
        return len(lane.light_blocks)

    def test_full_role_generates_groove_and_fill(self):
        # 8 bars / 4-bar phrases = 2 phrases, each with groove + fill = 4 blocks
        count = self._count_blocks(ActivationRole.FULL)
        assert count == 4  # 2 groove + 2 fill

    def test_groove_only_skips_fills(self):
        # 2 phrases, groove only = 2 blocks
        count = self._count_blocks(ActivationRole.GROOVE_ONLY)
        assert count == 2

    def test_fill_only_skips_grooves(self):
        # 2 phrases, fill only = 2 blocks
        count = self._count_blocks(ActivationRole.FILL_ONLY)
        assert count == 2

    def test_fill_only_no_remainder_blocks(self):
        # 9 bars / 4-bar phrases = 2 full phrases + 1 remainder bar
        full_count = self._count_blocks(ActivationRole.FULL, num_bars=9)
        fill_count = self._count_blocks(ActivationRole.FILL_ONLY, num_bars=9)
        assert full_count == 5  # 2 groove + 2 fill + 1 remainder
        assert fill_count == 2  # 2 fill only

    def test_groove_only_gets_remainder(self):
        # 9 bars: 2 groove + 1 remainder = 3
        count = self._count_blocks(ActivationRole.GROOVE_ONLY, num_bars=9)
        assert count == 3

    def test_short_section_fill_only_produces_nothing(self):
        # Section shorter than phrase: fill_bars=0, so fill-only has nothing
        count = self._count_blocks(ActivationRole.FILL_ONLY, num_bars=2, phrase_bars=4)
        assert count == 0

    def test_fill_only_block_names_are_fill(self):
        lane = _make_lane()
        part = _make_part(num_bars=8)
        config = AutogenConfig(phrase_length_bars=4, groove_fill_ratio=0.75)
        _generate_section_blocks(
            lane=lane, part=part,
            groove_name="pulse", fill_name="stroke",
            movement_strategy=None,
            color_assignment=None,
            gobo_prism={},
            weight=1.0, config=config,
            color_index=0, effect_speed="1",
            role=ActivationRole.FILL_ONLY,
        )
        for block in lane.light_blocks:
            assert "stroke" in block.effect_name
