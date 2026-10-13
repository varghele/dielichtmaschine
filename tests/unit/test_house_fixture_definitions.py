# tests/unit/test_house_fixture_definitions.py
"""The hand-authored house-rig fixture definitions (2026-07-16, built
for the Stellwerk 'hinten' venue rider from the official manufacturer
manuals - not from GDTF Share, so they are committable and portable).

Pins each definition's identity, the exact mode the venue uses, its
channel count, and the aim-critical facts (the HydraBeam head's Focus
ranges and per-head channel layout: a 56ch bar patches as 4 heads at
base/base+14/base+28/base+42)."""

import pytest

from utils.fixture_library import get_definition


#: (manufacturer, model, mode name, channel count)
HOUSE_DEFINITIONS = [
    ("Expolite", "TourLED 42CM", "Ar1.S", 5),
    ("Litecraft", "LED StudioPAR 25x3W", "DMX-3CH", 3),
    ("Cameo", "HydraBeam 4000 RGBW Head", "Head (56Ch bar)", 14),
    ("Cameo", "Q-Spot 15 RGBW", "9CH", 9),
    ("Cameo", "ROOT PAR 6", "D12CH", 12),
    ("Cameo", "ROOT PAR 4", "D10CH", 10),
]


class TestHouseDefinitions:

    @pytest.mark.parametrize(
        "manufacturer,model,mode,channels", HOUSE_DEFINITIONS,
        ids=[m for _, m, _, _ in HOUSE_DEFINITIONS])
    def test_mode_resolves_with_expected_channel_count(
            self, manufacturer, model, mode, channels):
        defn = get_definition(manufacturer, model)
        assert defn is not None, f"{manufacturer} {model} not in library"
        modes = {m.name: len(m.channels) for m in defn.modes}
        assert modes.get(mode) == channels, modes

    def test_hydrabeam_head_focus_ranges(self):
        """The manual's PAN 540 / TILT 270 must reach the solver (the
        real ranges drive both native aiming and export)."""
        defn = get_definition("Cameo", "HydraBeam 4000 RGBW Head")
        assert defn.pan_max == 540
        assert defn.tilt_max == 270

    def test_hydrabeam_head_channel_layout(self):
        """Manual 56ch table, one head: pan/fine, tilt/fine, speed,
        dimmer, strobe, macro, auto, sound, R, G, B, W."""
        defn = get_definition("Cameo", "HydraBeam 4000 RGBW Head")
        mode = next(m for m in defn.modes if m.name == "Head (56Ch bar)")
        names = [c.name for c in mode.channels]
        assert names == [
            "Pan", "Pan Fine", "Tilt", "Tilt Fine", "Head Speed",
            "Dimmer", "Strobe", "Colour Macro", "Auto / Sound / Reset",
            "Sound Sensitivity", "Red", "Green", "Blue", "White"]

    def test_capability_detection_matches_hardware(self):
        """The morph gating story: heads are movers, PARs are not, the
        3ch StudioPAR has colour but no dimmer channel."""
        from config.models import Configuration, Fixture, FixtureGroup, \
            FixtureMode, Universe
        from utils.morph.checker import group_capabilities

        def fx(mfr, model, mode, ch):
            return Fixture(universe=1, address=1, manufacturer=mfr,
                           model=model, current_mode=mode,
                           available_modes=[FixtureMode(name=mode,
                                                        channels=ch)],
                           name=model, group=model)

        groups = {}
        for mfr, model, mode, ch in HOUSE_DEFINITIONS:
            f = fx(mfr, model, mode, ch)
            groups[model] = FixtureGroup(model, [f])
        cfg = Configuration(
            fixtures=[g.fixtures[0] for g in groups.values()],
            groups=groups,
            universes={1: Universe(id=1, name="U1", output={})})
        cfg.songs = {}
        caps = group_capabilities(cfg)
        assert "movement" in caps["HydraBeam 4000 RGBW Head"]
        assert "movement" not in caps["TourLED 42CM"]
        assert "movement" not in caps["ROOT PAR 6"]
        assert caps["LED StudioPAR 25x3W"] == {"colour"}
