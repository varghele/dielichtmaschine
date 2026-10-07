"""Smoke tests for the rudiment registry and block converter (v1.5.5, G10).

``rudiments/`` feeds both autogen and the Auto engine, but was only
exercised indirectly. These pin the registry's internal consistency
(every rudiment maps onto an effect the DMX side can actually render,
envelopes are normalised, parameter defaults are legal) and the
converter's mapping onto Dimmer/Movement blocks.
"""

from __future__ import annotations

import pytest

from config.models import DimmerBlock, MovementBlock
from effects import DIMMER_REGISTRY, MOVEMENT_REGISTRY
from effects.timing import parse_speed
from rudiments import (
    INTENSITY_RUDIMENTS,
    MOVEMENT_RUDIMENTS,
    CycleMode,
    RudimentType,
    get_intensity_rudiments,
    get_movement_rudiments,
    get_rudiment,
    rudiment_to_dimmer_block,
    rudiment_to_movement_block,
)

ALL = [(n, r) for n, r in INTENSITY_RUDIMENTS.items()] + \
      [(n, r) for n, r in MOVEMENT_RUDIMENTS.items()]
IDS = [f"{r.rudiment_type.value}:{n}" for n, r in ALL]


class TestRegistryConsistency:
    def test_tables_are_populated_on_import(self):
        assert len(INTENSITY_RUDIMENTS) >= 10
        assert len(MOVEMENT_RUDIMENTS) >= 8
        assert get_intensity_rudiments() is INTENSITY_RUDIMENTS
        assert get_movement_rudiments() is MOVEMENT_RUDIMENTS

    def test_registries_cover_each_other_exactly(self):
        # A rudiment without an effect renders nothing; an effect without
        # a rudiment is unreachable from autogen / Auto.
        assert set(INTENSITY_RUDIMENTS) == set(DIMMER_REGISTRY)
        assert set(MOVEMENT_RUDIMENTS) == set(MOVEMENT_REGISTRY)

    @pytest.mark.parametrize("name,rudiment", ALL, ids=IDS)
    def test_rudiment_is_well_formed(self, name, rudiment):
        table = (DIMMER_REGISTRY if rudiment.rudiment_type is RudimentType.INTENSITY
                 else MOVEMENT_REGISTRY)
        assert rudiment.name == name
        assert rudiment.effect_function in table
        env = rudiment.envelope
        assert len(env.samples) == env.resolution
        assert all(0.0 <= s <= 1.0 for s in env.samples)
        assert isinstance(env.cycle_mode, CycleMode)
        assert rudiment.average_flux == pytest.approx(
            sum(env.samples) / len(env.samples))
        assert rudiment.description

    @pytest.mark.parametrize("name,rudiment", ALL, ids=IDS)
    def test_parameter_defaults_are_legal(self, name, rudiment):
        names = [p.name for p in rudiment.parameters]
        assert len(names) == len(set(names))
        for p in rudiment.parameters:
            if p.min_value is not None and p.max_value is not None:
                assert p.min_value <= p.default <= p.max_value, p.name
            if p.param_type == "enum":
                assert p.default in p.enum_values, p.name

    def test_envelopes_are_deterministic(self):
        # The stochastic envelope is hash-derived, never RNG-derived, so
        # autogen's envelope matching is stable across runs.
        import random
        import rudiments.registry as reg
        random.seed(1)
        first = reg._stochastic()
        random.seed(2)
        assert reg._stochastic() == first
        assert INTENSITY_RUDIMENTS["sparkle"].envelope.samples == first

    def test_lookup(self):
        assert get_rudiment("chase").rudiment_type is RudimentType.INTENSITY
        assert get_rudiment("circle").rudiment_type is RudimentType.MOVEMENT
        assert get_rudiment("no_such_rudiment") is None
        # "static" exists in both tables; the shared lookup prefers the
        # intensity one (pinned, so a change here is deliberate).
        assert get_rudiment("static") is INTENSITY_RUDIMENTS["static"]


class TestDimmerConversion:
    @pytest.mark.parametrize("name", sorted(INTENSITY_RUDIMENTS))
    def test_every_intensity_rudiment_converts(self, name):
        block = rudiment_to_dimmer_block(name, {}, 1.0, 5.0)
        assert isinstance(block, DimmerBlock)
        assert (block.start_time, block.end_time) == (1.0, 5.0)
        assert block.effect_type == name
        assert block.effect_type in DIMMER_REGISTRY
        assert 0.0 <= block.intensity <= 255.0
        assert parse_speed(block.effect_speed) > 0

    def test_params_override_defaults(self):
        block = rudiment_to_dimmer_block(
            "waterfall", {"intensity": 0.5, "speed": "2", "direction": "up"},
            0.0, 4.0)
        assert block.intensity == pytest.approx(127.5)
        assert parse_speed(block.effect_speed) == 2.0
        assert block.direction == "up"

    def test_rudiment_specific_fields(self):
        assert rudiment_to_dimmer_block("chase", {"chase_scope": "global"},
                                        0, 1).chase_scope == "global"
        assert rudiment_to_dimmer_block("cascade", {}, 0, 1).build_fraction == \
            pytest.approx(0.7)
        assert rudiment_to_dimmer_block("pulse", {"phase_offset_per_fixture": True},
                                        0, 1).phase_offset_per_fixture is True

    def test_float_speed_from_auto_engine_parses(self):
        # auto/engine.py passes speed=1.0 (a float): the block carries
        # "1.0", which the DMX side must read as 1x.
        block = rudiment_to_dimmer_block("pulse", {"speed": 1.0}, 0, 1)
        assert parse_speed(block.effect_speed) == 1.0

    def test_unknown_rudiment_raises(self):
        with pytest.raises(ValueError):
            rudiment_to_dimmer_block("nope", {}, 0, 1)


class TestMovementConversion:
    @pytest.mark.parametrize("name", sorted(MOVEMENT_RUDIMENTS))
    def test_every_movement_rudiment_converts(self, name):
        block = rudiment_to_movement_block(name, {}, 2.0, 6.0)
        assert isinstance(block, MovementBlock)
        assert (block.start_time, block.end_time) == (2.0, 6.0)
        assert block.effect_type == name
        assert block.effect_type in MOVEMENT_REGISTRY
        assert parse_speed(block.effect_speed) > 0

    def test_amplitude_drives_both_axes_and_targets_pass_through(self):
        block = rudiment_to_movement_block(
            "lissajous", {"amplitude": 80.0, "freq_ratio": "3:2"}, 0, 8,
            target_spot_name="Spot A", target_plane_name="Back Wall")
        assert block.pan_amplitude == block.tilt_amplitude == 80.0
        assert block.lissajous_ratio == "3:2"
        assert block.target_spot_name == "Spot A"
        assert block.target_plane_name == "Back Wall"

    def test_static_is_centred(self):
        block = rudiment_to_movement_block("static", {}, 0, 1)
        assert (block.pan, block.tilt) == (127.5, 127.5)
        block = rudiment_to_movement_block("static", {"pan": 10.0, "tilt": 200.0}, 0, 1)
        assert (block.pan, block.tilt) == (10.0, 200.0)

    def test_unknown_rudiment_raises(self):
        with pytest.raises(ValueError):
            rudiment_to_movement_block("nope", {}, 0, 1)
