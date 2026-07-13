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
    fixture_yoke,
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
        assert fixture_yoke("NoSuch", "Fixture", "Mode") == (False, False)

    def test_result_is_cached(self):
        a = fixture_yoke("NoSuch", "Fixture", "Mode")
        b = fixture_yoke("NoSuch", "Fixture", "Mode")
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

        # The buffer now holds the real-yoke angles for the same solver
        # aim, within the two 16-bit quantisation hops (decode the
        # solver bytes, convert, re-encode): ~0.01 deg per hop.
        want_pan, want_tilt = solver_to_gdtf_axes(30.0, 60.0, flipped=True)
        got_pan = self._decode(buf, 0, 1, 540.0)
        got_tilt = self._decode(buf, 2, 3, 270.0)
        assert abs(got_pan - want_pan) < 0.03
        assert abs(got_tilt - want_tilt) < 0.03

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




class TestQxfSyntheticYoke:
    def test_qxf_only_mover_gets_the_standard_yoke(self, monkeypatch):
        """A .qxf definition (no GDTF tree) is brought to the GDTF
        standard: converted with the synthetic hanging-authored yoke,
        the branch verified on real hardware."""
        import utils.fixture_library as fl

        class _QxfDefn:
            gdtf = None
        monkeypatch.setattr(fl, "get_definition",
                            lambda m, mo: _QxfDefn())
        # Unique identity per run so the lru_cache cannot serve a stale
        # verdict from another test.
        assert fixture_yoke("QxfMfr-synth", "QxfModel-synth",
                            "8 Channel") == (True, True)


class TestExportAimDmx:
    """The .qxw export aims like native output: real ranges + the yoke
    conversion (it used to emit raw solver angles at hardcoded 540/270,
    which aims a real mover elsewhere)."""

    class _Fx:
        manufacturer = "ExpMfr-a"
        model = "ExpModel-a"
        current_mode = "M"
        x, y = 0.0, 0.0

    def test_converted_and_range_aware(self, monkeypatch):
        import utils.yoke as yoke
        monkeypatch.setattr(yoke, "_physical_ranges",
                            lambda m, mo: (540.0, 220.0))
        monkeypatch.setattr(yoke, "fixture_yoke", lambda *a: (True, True))
        from utils.orientation import preset_angles
        yaw, pitch, roll = preset_angles("hanging")
        # Hanging mover 5 m up, target straight below: solver says
        # tilt +90 (its convention); the REAL yoke value is tilt 0 =
        # DMX centre. The old export emitted the raw solver angle.
        pan_dmx, tilt_dmx = yoke.export_aim_dmx(
            self._Fx(), 5.0, (0.0, 0.0, 0.0), "hanging", yaw, pitch, roll)
        assert tilt_dmx == 127, "straight down = tilt centre on a real yoke"

    def test_unresolvable_fixture_keeps_solver_values(self, monkeypatch):
        import utils.yoke as yoke
        monkeypatch.setattr(yoke, "_physical_ranges",
                            lambda m, mo: (540.0, 270.0))
        monkeypatch.setattr(yoke, "fixture_yoke", lambda *a: (False, False))
        from utils.orientation import (calculate_pan_tilt, pan_tilt_to_dmx,
                                       preset_angles)
        yaw, pitch, roll = preset_angles("hanging")
        got = yoke.export_aim_dmx(
            self._Fx(), 5.0, (2.0, 0.0, 0.0), "hanging", yaw, pitch, roll)
        want = pan_tilt_to_dmx(*calculate_pan_tilt(
            0.0, 0.0, 5.0, 2.0, 0.0, 0.0, "hanging", yaw, pitch, roll,
            540.0, 270.0), 540.0, 270.0)
        assert got == want
