# tests/unit/test_export_movement_yoke.py
"""Per-step yoke conversion for exported movement PATTERNS (the last
v1.5a yoke sliver, closed 2026-07-13 overnight).

Before: the .qxw export converted only the CENTRE of a spot-targeted
movement block to the real yoke and added the shape offsets in solver
DMX space on top - a mixed frame that traces the wrong figure on a
real head. Now the whole step is computed in solver space (like the
native renderer) and converted per step (utils/yoke.convert_solver_dmx),
so QLC+ playback moves like native output - whose wire conversion
(apply_yoke_to_universe) is the oracle here.

Identity guarantee: fixtures without a resolvable definition (and
therefore no known yoke) export unchanged, which keeps mover-less rigs
byte-identical (scripts/export_hash_check.py).
"""

import math

import pytest

from config.models import (
    Configuration, Fixture, FixtureGroup, FixtureMode, Spot, Universe,
)
from utils.yoke import (
    apply_yoke_to_universe,
    convert_solver_dmx,
    export_aim_dmx,
    export_solver_aim_dmx,
    fixture_yoke,
    solver_to_gdtf_axes,
)


def _fixture(manufacturer, model="StepMover", name="MH1"):
    return Fixture(
        universe=1, address=1, manufacturer=manufacturer, model=model,
        name=name, group="Movers", current_mode="Standard",
        available_modes=[FixtureMode(name="Standard", channels=10)],
        type="MH", x=-1.0, y=0.0, z=4.0,
    )


class _QxfDefn:
    """A resolvable .qxf-only definition: synthetic standard yoke
    (convert=True, flipped=True), default 540/270 physical ranges."""
    gdtf = None
    pan_max = 0.0
    tilt_max = 0.0


@pytest.fixture
def qxf_mover(monkeypatch):
    """A fixture whose identity resolves to a .qxf-only definition.
    Unique manufacturer per test session run to dodge the lru_caches
    in fixture_yoke/_physical_ranges."""
    import utils.fixture_library as fl
    manufacturer = "YokeTestMfr_qxf"
    real = fl.get_definition

    def fake(mfr, model):
        if mfr == manufacturer:
            return _QxfDefn()
        return real(mfr, model)

    monkeypatch.setattr(fl, "get_definition", fake)
    fixture_yoke.cache_clear()
    yield _fixture(manufacturer)
    fixture_yoke.cache_clear()


class TestConvertSolverDmx:
    def test_identity_without_a_definition(self):
        fixture = _fixture("NoSuchMfr_identity")
        assert convert_solver_dmx(fixture, 200, 40) == (200, 40)
        # Fractional and out-of-range inputs clamp to sane bytes.
        assert convert_solver_dmx(fixture, 300.7, -5) == (255, 0)

    def test_converts_like_the_pure_function(self, qxf_mover):
        # Solver pan 30 deg / tilt 60 deg encoded 8-bit, converted,
        # decoded: must match solver_to_gdtf_axes within the 8-bit
        # quantisation (540/255 ~ 2.1 deg per pan step).
        from utils.orientation import pan_tilt_to_dmx
        pan_dmx, tilt_dmx = pan_tilt_to_dmx(30.0, 60.0, 540.0, 270.0)
        got_pan, got_tilt = convert_solver_dmx(qxf_mover, pan_dmx,
                                               tilt_dmx)
        want_pan_deg, want_tilt_deg = solver_to_gdtf_axes(
            30.0, 60.0, flipped=True)
        got_pan_deg = (got_pan - 127.0) / 127.0 * 270.0
        got_tilt_deg = (got_tilt - 127.0) / 127.0 * 135.0
        assert abs(got_pan_deg - want_pan_deg) < 2.5
        assert abs(got_tilt_deg - want_tilt_deg) < 1.5

    def test_matches_the_wire_conversion(self, qxf_mover):
        """Export step == arbiter hardware pass for the same solver
        pair (within one coarse step of 16-bit vs 8-bit rounding)."""
        class _Map:
            universe = 1
            pan_channels = [0]
            pan_fine_channels = [1]
            tilt_channels = [2]
            tilt_fine_channels = [3]
            pan_range = 540.0
            tilt_range = 270.0

            def get_absolute_address(self, offset):
                return (1, offset)

        from utils.orientation import pan_tilt_to_dmx16
        for solver_pan_deg, solver_tilt_deg in (
                (0.0, 0.0), (30.0, 60.0), (-100.0, 20.0), (200.0, -40.0)):
            buf = bytearray(512)
            pc, pf, tc, tf = pan_tilt_to_dmx16(
                solver_pan_deg, solver_tilt_deg, 540.0, 270.0)
            buf[0], buf[1], buf[2], buf[3] = pc, pf, tc, tf
            apply_yoke_to_universe(buf, _Map(), flipped=True)

            export_pan, export_tilt = convert_solver_dmx(
                qxf_mover, pc, tc)   # the 8-bit coarse pair
            assert abs(export_pan - buf[0]) <= 1, solver_pan_deg
            assert abs(export_tilt - buf[2]) <= 1, solver_tilt_deg


def _spot_config(fixture):
    config = Configuration(
        fixtures=[fixture],
        groups={"Movers": FixtureGroup(name="Movers",
                                       fixtures=[fixture])},
        universes={1: Universe(id=1, name="U1", output={})},
    )
    config.spots = {"Mark": Spot(name="Mark", x=1.0, y=-2.0, z=0.0)}
    return config


def _movement_block(effect_type, **overrides):
    from config.models import MovementBlock
    params = dict(start_time=0.0, end_time=8.0, effect_type=effect_type,
                  target_spot_name="Mark", pan_amplitude=30.0,
                  tilt_amplitude=20.0)
    params.update(overrides)
    return MovementBlock(**params)


class TestSampledMovementSteps:
    """unified_sequence.sample_movement_at_time: the export's live
    movement path."""

    def _sample(self, config, fixture, block, time_s):
        from utils.to_xml.unified_sequence import sample_movement_at_time
        return sample_movement_at_time(
            time_s, [block], fixture_idx=0, total_fixtures=1,
            step_idx=0, total_steps=1, bpm=120.0, signature="4/4",
            config=config, fixture=fixture)

    def test_static_spot_step_matches_the_one_shot_aim(self, qxf_mover):
        config = _spot_config(qxf_mover)
        block = _movement_block("static")
        got = self._sample(config, qxf_mover, block, 0.0)
        group = config.groups["Movers"]
        mounting, yaw, pitch, roll = \
            qxf_mover.get_effective_orientation(group)
        want = export_aim_dmx(
            qxf_mover, qxf_mover.get_effective_z(group),
            (1.0, -2.0, 0.0), mounting, yaw, pitch, roll)
        assert abs(got[0] - want[0]) <= 1
        assert abs(got[1] - want[1]) <= 1

    def test_pattern_steps_convert_the_whole_step(self, qxf_mover):
        """A circle step must equal convert(solver_centre + offset),
        NOT convert(centre) + offset - the exact v1.5a bug."""
        config = _spot_config(qxf_mover)
        block = _movement_block("circle")
        group = config.groups["Movers"]
        mounting, yaw, pitch, roll = \
            qxf_mover.get_effective_orientation(group)
        centre = export_solver_aim_dmx(
            qxf_mover, qxf_mover.get_effective_z(group),
            (1.0, -2.0, 0.0), mounting, yaw, pitch, roll)

        from effects.timing import movement_total_cycles
        total_cycles = movement_total_cycles(8.0, 2.0, 1.0)
        for time_s in (0.0, 1.0, 3.0, 5.5):
            progress = time_s / 8.0
            t = 2 * math.pi * total_cycles * progress
            solver_pan = max(0.0, min(255.0,
                                      centre[0] + 30.0 * math.cos(t)))
            solver_tilt = max(0.0, min(255.0,
                                       centre[1] + 20.0 * math.sin(t)))
            want = convert_solver_dmx(qxf_mover, solver_pan, solver_tilt)
            got = self._sample(config, qxf_mover, block, time_s)
            assert got == want, time_s

        # And the old mixed-space frame is NOT what we emit: over the
        # cycle the converted-centre-plus-solver-offset trace diverges
        # from the converted-step trace (individual phases can
        # coincide within a byte; the figure as a whole must not).
        converted_centre = convert_solver_dmx(qxf_mover, *centre)
        diverged = False
        for time_s in (0.5, 1.0, 2.0, 2.5, 3.5, 5.0, 6.5, 7.5):
            t = 2 * math.pi * total_cycles * (time_s / 8.0)
            mixed = (int(max(0.0, min(255.0,
                                      converted_centre[0]
                                      + 30.0 * math.cos(t)))),
                     int(max(0.0, min(255.0,
                                      converted_centre[1]
                                      + 20.0 * math.sin(t)))))
            if self._sample(config, qxf_mover, block, time_s) != mixed:
                diverged = True
                break
        assert diverged, "per-step conversion must reshape the figure"

    def test_unknown_definition_exports_solver_values_unchanged(self):
        """No resolvable definition = no known yoke = identity: the
        pre-existing solver-space export survives byte for byte (the
        mover-less byte-identity guarantee)."""
        fixture = _fixture("NoSuchMfr_sequence")
        config = _spot_config(fixture)
        block = _movement_block("circle", target_spot_name=None,
                                pan=127.0, tilt=127.0)
        got = self._sample(config, fixture, block, 1.0)
        from effects.timing import movement_total_cycles
        total_cycles = movement_total_cycles(8.0, 2.0, 1.0)
        t = 2 * math.pi * total_cycles * (1.0 / 8.0)
        want = (int(127.0 + 30.0 * math.cos(t)),
                int(127.0 + 20.0 * math.sin(t)))
        assert got == want
