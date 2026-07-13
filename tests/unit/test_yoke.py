# tests/unit/test_yoke.py
"""Output-boundary yoke conversion (utils/yoke.py).

The solver and a real moving head use different yokes; the wire needs
the real one while everything internal stays solver-convention. These
pin the decode/convert/encode and the GDTF-chain gating; the arbiter
routing (hardware converted, mirror not) is in test_output_arbiter.py,
and the end-to-end aim is in test_gdtf_draw_plan.py::TestAimedBeamHitsTheSpot.
"""

import math

from utils.yoke import (
    apply_yoke_to_universe,
    gdtf_chain_yoke,
    solver_to_gdtf_axes,
)


class _StubMap:
    """Minimal FixtureChannelMap stand-in: fixture at address 1, pan
    coarse/fine at 0/1, tilt coarse/fine at 2/3, in universe 1."""
    universe = 1
    pan_channels = [0]
    pan_fine_channels = [1]
    tilt_channels = [2]
    tilt_fine_channels = [3]
    pan_range = 540.0
    tilt_range = 270.0

    def get_absolute_address(self, offset):
        return (1, offset)


class TestGdtfChainYoke:
    def test_unknown_fixture_does_not_use_the_chain(self):
        assert gdtf_chain_yoke("NoSuch", "Fixture", "Mode") == (False, False)

    def test_result_is_cached(self):
        a = gdtf_chain_yoke("NoSuch", "Fixture", "Mode")
        b = gdtf_chain_yoke("NoSuch", "Fixture", "Mode")
        assert a == b == (False, False)


class TestApplyYokeToUniverse:
    def _decode(self, buf, coarse, fine, rng):
        return ((buf[coarse] * 256 + buf[fine]) / 65535.0 - 0.5) * rng

    def test_converts_pan_tilt_matching_the_pure_function(self):
        buf = bytearray(512)
        # Solver pan 30, tilt 60 encoded 16-bit into the buffer.
        from utils.orientation import pan_tilt_to_dmx16
        pc, pf, tc, tf = pan_tilt_to_dmx16(30.0, 60.0, 540.0, 270.0)
        buf[0], buf[1], buf[2], buf[3] = pc, pf, tc, tf

        apply_yoke_to_universe(buf, _StubMap(), flipped=True)

        # The buffer now holds the real-yoke angles for the same solver aim.
        want_pan, want_tilt = solver_to_gdtf_axes(30.0, 60.0, flipped=True)
        got_pan = self._decode(buf, 0, 1, 540.0)
        got_tilt = self._decode(buf, 2, 3, 270.0)
        assert got_pan == round_trip(want_pan, 540.0)
        assert got_tilt == round_trip(want_tilt, 270.0)

    def test_no_pan_tilt_is_a_noop(self):
        class NoMove(_StubMap):
            pan_channels = []
            tilt_channels = []
        buf = bytearray(512)
        buf[7] = 200
        apply_yoke_to_universe(buf, NoMove(), flipped=True)
        assert buf[7] == 200 and not any(buf[i] for i in range(4))

    def test_fine_bytes_are_written(self):
        # A converted angle that is not a whole coarse step must populate
        # the fine byte (16-bit precision preserved through the convert).
        buf = bytearray(512)
        from utils.orientation import pan_tilt_to_dmx16
        pc, pf, tc, tf = pan_tilt_to_dmx16(17.3, 42.7, 540.0, 270.0)
        buf[0], buf[1], buf[2], buf[3] = pc, pf, tc, tf
        apply_yoke_to_universe(buf, _StubMap(), flipped=True)
        assert buf[1] != 0 or buf[3] != 0


def round_trip(deg, rng):
    """The degrees that survive a 16-bit encode/decode at this range -
    what apply_yoke_to_universe stores and _decode reads back."""
    half = rng / 2
    norm = max(-1.0, min(1.0, deg / half))
    val16 = round((norm + 1.0) / 2.0 * 65535)
    return (val16 / 65535.0 - 0.5) * rng
