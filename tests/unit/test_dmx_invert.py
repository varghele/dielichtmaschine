# tests/unit/test_dmx_invert.py
"""Per-fixture DMX direction inversion (the last v1.5a yoke sliver) and
the range-aware-export pin. Inversion applies at the WIRE
(arbiter hardware pass) and EXPORT (convert_solver_dmx, export_aim_dmx)
boundaries only - with or without a resolvable yoke chain - and never
touches solver/visualizer math. Plus a regression pin that the export
aims at the definition's real Focus ranges (closed by the 2026-07-13/14
yoke work; the roadmap note claiming 540/270 was stale)."""

import pytest

from config.models import Configuration, Fixture, FixtureGroup, FixtureMode, Universe
from utils.yoke import (apply_yoke_to_universe, convert_solver_dmx,
                        export_aim_dmx, fixture_yoke)


def _fixture(manufacturer="NoSuchMfr_invert", **kw):
    return Fixture(universe=1, address=1, manufacturer=manufacturer,
                   model="StepMover", name="MH1", group="Movers",
                   current_mode="Standard",
                   available_modes=[FixtureMode(name="Standard",
                                                channels=10)],
                   type="MH", x=-1.0, y=0.0, z=4.0, **kw)


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


class TestConvertSolverDmxInversion:
    def test_invert_without_a_yoke_chain(self):
        plain = _fixture()
        inverted = _fixture(invert_pan=True, invert_tilt=True)
        assert convert_solver_dmx(plain, 200, 40) == (200, 40)
        assert convert_solver_dmx(inverted, 200, 40) == (55, 215)

    def test_single_axis_inversion(self):
        fixture = _fixture(invert_pan=True)
        assert convert_solver_dmx(fixture, 200, 40) == (55, 40)


class TestExportAimInversion:
    def test_inverted_aim_mirrors_the_bytes(self):
        plain = _fixture()
        inverted = _fixture(invert_pan=True, invert_tilt=True)
        args = (0.0, (1.0, -2.0, 0.0), "hanging", 0.0, 90.0, 0.0)
        p0, t0 = export_aim_dmx(plain, *args)
        p1, t1 = export_aim_dmx(inverted, *args)
        assert (p1, t1) == (255 - p0, 255 - t0)


class TestWireInversion:
    def test_invert_only_pass_without_conversion(self):
        buf = bytearray(512)
        buf[0], buf[1], buf[2], buf[3] = 100, 200, 30, 40
        apply_yoke_to_universe(buf, _Map(), flipped=False, convert=False,
                               invert_pan=True, invert_tilt=False)
        # pan 16-bit 100*256+200=25800 -> 65535-25800=39735 -> 155/55
        assert (buf[0], buf[1]) == (155, 55)
        assert (buf[2], buf[3]) == (30, 40)  # tilt untouched

    def test_arbiter_processes_invert_only_fixtures(self):
        from utils.artnet.arbiter import OutputArbiter
        fixture = _fixture(invert_pan=True)
        fmap = _Map()
        fmap.fixture = fixture
        fmap.mode_name = "Standard"
        merged = {1: bytearray(512)}
        merged[1][0] = 100
        arbiter = OutputArbiter.__new__(OutputArbiter)  # no loop needed
        out = arbiter._hardware_frame(merged, {"MH1": fmap})
        assert out[1][0] == 155  # (100*256) inverted -> coarse 155
        # mirror/solver frame untouched
        assert merged[1][0] == 100

    def test_no_chain_no_invert_is_a_no_op_fast_path(self):
        from utils.artnet.arbiter import OutputArbiter
        fixture = _fixture()
        fmap = _Map()
        fmap.fixture = fixture
        fmap.mode_name = "Standard"
        merged = {1: bytearray(512)}
        arbiter = OutputArbiter.__new__(OutputArbiter)
        assert arbiter._hardware_frame(merged, {"MH1": fmap}) is merged


class TestPersistence:
    def test_yaml_round_trip(self, tmp_path):
        fixture = _fixture(invert_pan=True)
        cfg = Configuration(
            fixtures=[fixture],
            groups={"Movers": FixtureGroup("Movers", [fixture])},
            universes={1: Universe(id=1, name="U", output={})})
        path = tmp_path / "rig.yaml"
        cfg.save(str(path))
        loaded = Configuration.load(str(path))
        assert loaded.fixtures[0].invert_pan is True
        assert loaded.fixtures[0].invert_tilt is False


class TestOrientationPanelUI:
    def test_values_carry_the_flags_and_apply_writes_them(self, qapp):
        from gui.dialogs.orientation_dialog import OrientationPanel

        fixture = _fixture(invert_tilt=True)
        cfg = Configuration(
            fixtures=[fixture],
            groups={"Movers": FixtureGroup("Movers", [fixture])},
            universes={1: Universe(id=1, name="U", output={})})

        class _Item:
            fixture_name = "MH1"
            mounting = "hanging"
            rotation_angle = 0.0
            pitch = 0.0
            roll = 0.0
            z_height = 4.0

        panel = OrientationPanel([_Item()], cfg)
        try:
            # initialized from the config fixture
            assert panel.invert_tilt_checkbox.isChecked()
            assert not panel.invert_pan_checkbox.isChecked()
            panel.invert_pan_checkbox.setChecked(True)
            values = panel.get_orientation_values()
            assert values["invert_pan"] and values["invert_tilt"]
        finally:
            panel.cleanup()


class TestRangeAwareExportPin:
    def test_export_aim_reacts_to_definition_ranges(self, monkeypatch):
        """Regression pin: the export aims at the definition's REAL
        Focus ranges (the old roadmap claim of hardcoded 540/270 was
        closed by the 2026-07-13/14 yoke work)."""
        import utils.fixture_library as fl
        from utils.yoke import _physical_ranges, fixture_yoke

        class _Narrow:
            gdtf = None
            pan_max = 360.0
            tilt_max = 180.0

        real = fl.get_definition

        def fake(mfr, model):
            if mfr == "NarrowMfr_ranges":
                return _Narrow()
            return real(mfr, model)

        monkeypatch.setattr(fl, "get_definition", fake)
        _physical_ranges.cache_clear()
        fixture_yoke.cache_clear()
        try:
            narrow = _fixture(manufacturer="NarrowMfr_ranges")
            wide = _fixture()   # unresolvable -> 540/270 fallback
            args = (0.0, (1.5, -2.0, 0.0), "hanging", 0.0, 90.0, 0.0)
            assert export_aim_dmx(narrow, *args) != \
                export_aim_dmx(wide, *args)
        finally:
            _physical_ranges.cache_clear()
            fixture_yoke.cache_clear()
