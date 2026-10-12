# tests/unit/test_export_live_parity.py
"""Export / live effect parity (v1.5.5 hardening, group G4).

The .qxw exporter (utils/to_xml/unified_sequence.py) used to carry its
own copy of every dimmer and movement effect next to the effects/
registries the native renderer puts on the wire, and the copies had
drifted: fade, cascade, fill and throb exported as a static look, linear_sweep
and fan exported as a parked head, pulse ignored its per-fixture phase
spread, the polygon shapes and bounce ignored the movement phase
offset, sparkle and the pixel-bar waterfall seeded their randomness
from list positions instead of the fixture name (so the exported
twinkle differed from what the rig showed, and two groups' bars could
twinkle in lockstep), and a dangling spot name skipped the target point
the native renderer falls through to.

The oracle is the native path itself: DMXManager._apply_dimmer_block /
_apply_colour_block / _apply_movement_block, sampled at the same
instant as the exporter. Values must match exactly.

Intentional differences, NOT covered here:
- Step quantisation: QLC+ plays the export as a chaser of fixed-length
  steps (calculate_unified_step_grid), so between two steps the export
  holds a value the native renderer keeps animating. Parity is checked
  at the sample instants only.
- Time signature: the exporter scales movement cycles to the song's
  bar length (signature-aware), the native renderer assumes 4/4. The
  tests run in 4/4.
- Export intensity overrides (group_max_intensity) scale the export
  only; the tests run at the default 255.
- Sparkle on a NON-segmented fixture with several dimmer channels:
  native draws one random value per dimmer channel, the export writes
  the first one to every dimmer channel (identical for the usual single
  dimmer channel, which is what the tests use).
- Native pan/tilt speed limiting (set_max_pan_tilt_speed) has no
  export equivalent; it is off by default.
"""

import pytest

from config.models import (
    ColourBlock, Configuration, DimmerBlock, Fixture, FixtureGroup,
    FixtureMode, MovementBlock, Spot, Universe,
)
from effects import DIMMER_REGISTRY, MOVEMENT_REGISTRY
from utils.artnet.dmx_manager import DMXManager
from utils.to_xml.unified_sequence import (
    build_unified_step, sample_dimmer_at_time, sample_movement_at_time,
)

DEF_KEY = "TestMfr_TestModel"
BAR_KEY = "TestMfr_ParityBar"
STRIP_KEY = "TestMfr_ParityStrip"
BAR_SEGMENTS = 4

# Sample instants: off-grid values so no effect sits on a cycle seam.
TIMES = [0.0, 0.13, 0.37, 0.61, 0.9, 1.27, 1.55, 2.04, 2.71, 3.33,
         4.18, 5.02, 5.77, 6.49, 7.31, 7.96]


def _mover(idx, manufacturer="TestMfr", model="TestModel",
           ftype="MH", channels=10):
    return Fixture(
        universe=1, address=1 + idx * 20, manufacturer=manufacturer,
        model=model, name=f"FX{idx}", group="Lane",
        current_mode="Standard",
        available_modes=[FixtureMode(name="Standard", channels=channels)],
        type=ftype, x=float(idx), y=0.0, z=4.0,
    )


def _config(fixtures):
    return Configuration(
        fixtures=list(fixtures),
        groups={"Lane": FixtureGroup(name="Lane", fixtures=list(fixtures))},
        universes={1: Universe(id=1, name="U1", output={})},
    )


def _bar_def():
    """A pixel bar: master dimmer + four RGB segments. The colour
    channels carry no group, so neither side mistakes them for a
    dimmer or a colour wheel."""
    channels = [{"name": "Dimmer", "preset": "IntensityMasterDimmer",
                 "group": "Intensity", "capabilities": []}]
    mode = [{"number": 0, "name": "Dimmer"}]
    for seg in range(BAR_SEGMENTS):
        for colour in ("Red", "Green", "Blue"):
            name = f"{colour} {seg + 1}"
            channels.append({"name": name, "preset": f"Intensity{colour}",
                             "group": "", "capabilities": []})
            mode.append({"number": len(mode), "name": name})
    return {"manufacturer": "TestMfr", "model": "ParityBar",
            "channels": channels,
            "modes": [{"name": "Standard", "channels": mode}]}


def _parse_step(step):
    """Step text -> {fixture_id: {channel: value}} (absent = 0)."""
    out = {}
    text = step.text or ""
    tokens = text.split(":") if text else []
    for i in range(0, len(tokens) - 1, 2):
        pairs = tokens[i + 1].split(",") if tokens[i + 1] else []
        chans = out.setdefault(int(tokens[i]), {})
        for j in range(0, len(pairs) - 1, 2):
            chans.setdefault(int(pairs[j]), int(pairs[j + 1]))
    return out


# ── dimmer: non-segmented fixtures ───────────────────────────────────

N_FIXTURES = 5

DIMMER_CASES = [
    dict(effect_type=name) for name in sorted(DIMMER_REGISTRY)
] + [
    # Non-segmented waterfall cascades across the fixtures on both
    # sides (decision 2026-10-12; native used to render it static).
    dict(effect_type="waterfall", direction="up"),
    dict(effect_type="waterfall", effect_speed="2"),
    dict(effect_type="pulse", phase_offset_per_fixture=True),
    dict(effect_type="fade", direction="out"),
    dict(effect_type="cascade", build_fraction=0.4),
    dict(effect_type="chase", chase_scope="global"),
    dict(effect_type="stroke", effect_speed="2"),
    dict(effect_type="sparkle", effect_speed="1/2"),
    dict(effect_type="random_stroke", effect_speed="1/4"),
]


def _case_id(case):
    return "-".join(f"{v}" for v in case.values())


def _single_dimmer_def(mock_fixture_def):
    """The shared mock with its dimmer in no channel group, like real
    definitions: preset IntensityMasterDimmer AND group Intensity would
    list channel 0 twice in the native map (a mock-only artefact that
    makes the native side write the dimmer twice)."""
    import copy
    definition = copy.deepcopy(mock_fixture_def)
    for channel in definition["channels"]:
        if channel["name"] == "Dimmer":
            channel["group"] = ""
    return definition


@pytest.fixture
def dimmer_lane(mock_fixture_def):
    fixtures = [_mover(i) for i in range(N_FIXTURES)]
    config = _config(fixtures)
    defs = {DEF_KEY: _single_dimmer_def(mock_fixture_def)}
    manager = DMXManager(config, defs)
    id_map = {(f.universe, f.address): i for i, f in enumerate(fixtures)}
    return fixtures, manager, defs, id_map


def _dimmer_block(**kw):
    params = dict(start_time=0.0, end_time=8.0, intensity=200.0)
    params.update(kw)
    return DimmerBlock(**params)


def _native_dimmer(manager, fixture, block, time_s, idx, total):
    fmap = manager.fixture_maps[fixture.name]
    manager.clear_all_dmx()
    manager._apply_dimmer_block(fmap, block, time_s, idx, total)
    universe, channel = fmap.get_absolute_address(fmap.dimmer_channels[0])
    return manager.dmx_state[universe][channel]


@pytest.mark.parametrize("case", DIMMER_CASES, ids=_case_id)
def test_exported_dimmer_matches_native(dimmer_lane, case):
    fixtures, manager, defs, id_map = dimmer_lane
    block = _dimmer_block(**case)
    mismatches = []
    for time_s in TIMES:
        step = build_unified_step(
            0, time_s, 50, fixtures, id_map, defs, [block], [], [], [],
            1, all_lane_fixtures=fixtures, bpm=120.0)
        exported = _parse_step(step)
        for idx, fixture in enumerate(fixtures):
            native = _native_dimmer(manager, fixture, block, time_s,
                                    idx, len(fixtures))
            got = exported.get(id_map[(fixture.universe, fixture.address)],
                               {}).get(0, 0)
            if got != native:
                mismatches.append((time_s, idx, got, native))
    assert not mismatches, f"(t, fixture, export, native): {mismatches[:6]}"


def test_sampler_seeds_sparkle_from_the_fixture_name():
    """The randomness is keyed to the fixture, not to where the
    fixture happens to sit in a list."""
    block = _dimmer_block(effect_type="sparkle", intensity=255.0)
    a = [sample_dimmer_at_time(t, [block], 0, 4, 0, 1, fixture_name="FX9")
         for t in TIMES]
    b = [sample_dimmer_at_time(t, [block], 3, 4, 0, 1, fixture_name="FX9")
         for t in TIMES]
    c = [sample_dimmer_at_time(t, [block], 0, 4, 0, 1, fixture_name="FX8")
         for t in TIMES]
    assert a == b
    assert a != c


def test_unknown_effect_exports_static_like_native(dimmer_lane):
    fixtures, manager, defs, id_map = dimmer_lane
    block = _dimmer_block(effect_type="no_such_effect")
    assert sample_dimmer_at_time(1.0, [block], 0, 5, 0, 1) == 200
    assert _native_dimmer(manager, fixtures[0], block, 1.0, 0, 5) == 200


class TestNonSegmentedWaterfall:
    """Decision 2026-10-12: a waterfall on fixtures without segments
    sweeps across the lane's fixtures, natively AND in the export (the
    parity cases above compare them value for value). Native used to
    render it static while the export cascaded with a pseudo-random
    phase per fixture."""

    def test_native_cascades_across_fixtures(self, dimmer_lane):
        fixtures, manager, _, _ = dimmer_lane
        block = _dimmer_block(effect_type="waterfall")
        levels = [_native_dimmer(manager, fixture, block, 0.0, idx,
                                 len(fixtures))
                  for idx, fixture in enumerate(fixtures)]
        # direction "down" starts on the last fixture at full level.
        assert levels[-1] == 200
        assert len(set(levels)) == len(levels)


# ── dimmer: segmented pixel bars (sparkle + waterfall) ───────────────

@pytest.fixture
def bar_lane():
    fixtures = [_mover(i, model="ParityBar", ftype="PIXELBAR",
                       channels=1 + 3 * BAR_SEGMENTS) for i in range(3)]
    config = _config(fixtures)
    defs = {BAR_KEY: _bar_def()}
    manager = DMXManager(config, defs)
    id_map = {(f.universe, f.address): 10 + i
              for i, f in enumerate(fixtures)}
    return fixtures, manager, defs, id_map


# Every dimmer effect runs per segment on bars and sunstrips, natively
# and in the export (decision 2026-10-12; the export used to do this for
# sparkle and waterfall on RGB bars only).
SEGMENT_CASES = [
    dict(effect_type=name) for name in sorted(DIMMER_REGISTRY)
] + [
    dict(effect_type="sparkle", effect_speed="2"),
    dict(effect_type="waterfall", direction="up", effect_speed="1/2"),
    dict(effect_type="chase", chase_scope="global"),
    dict(effect_type="fade", direction="out"),
    dict(effect_type="pulse", phase_offset_per_fixture=True),
]


@pytest.mark.parametrize("case", SEGMENT_CASES, ids=_case_id)
def test_exported_pixel_bar_matches_native(bar_lane, case):
    fixtures, manager, defs, id_map = bar_lane
    block = _dimmer_block(**case)
    colour = ColourBlock(start_time=0.0, end_time=8.0, red=200.0,
                         green=120.0, blue=60.0, white=0.0)
    n_channels = 1 + 3 * BAR_SEGMENTS
    mismatches = []
    for time_s in TIMES:
        step = build_unified_step(
            0, time_s, 50, fixtures, id_map, defs, [block], [colour],
            [], [], 1, all_lane_fixtures=fixtures, bpm=120.0)
        exported = _parse_step(step)
        for idx, fixture in enumerate(fixtures):
            fmap = manager.fixture_maps[fixture.name]
            manager.clear_all_dmx()
            manager._apply_dimmer_block(fmap, block, time_s, idx,
                                        len(fixtures))
            manager._apply_colour_block(fmap, colour, time_s)
            got = exported.get(id_map[(fixture.universe, fixture.address)],
                               {})
            for ch in range(n_channels):
                universe, channel = fmap.get_absolute_address(ch)
                native = manager.dmx_state[universe][channel]
                if got.get(ch, 0) != native:
                    mismatches.append((time_s, idx, ch, got.get(ch, 0),
                                       native))
    assert not mismatches, \
        f"(t, fixture, channel, export, native): {mismatches[:6]}"


def _strip_def():
    """A sunstrip: dimmer-only segments, one IntensityDimmer channel per
    cell and nothing else (no group, so no channel is listed twice)."""
    channels = [{"name": f"Dimmer {seg + 1}", "preset": "IntensityDimmer",
                 "group": "", "capabilities": []}
                for seg in range(STRIP_SEGMENTS)]
    mode = [{"number": i, "name": c["name"]} for i, c in enumerate(channels)]
    return {"manufacturer": "TestMfr", "model": "ParityStrip",
            "channels": channels,
            "modes": [{"name": "Standard", "channels": mode}]}


STRIP_SEGMENTS = 6


@pytest.fixture
def strip_lane():
    fixtures = [_mover(i, model="ParityStrip", ftype="SUNSTRIP",
                       channels=STRIP_SEGMENTS) for i in range(3)]
    config = _config(fixtures)
    defs = {STRIP_KEY: _strip_def()}
    manager = DMXManager(config, defs)
    id_map = {(f.universe, f.address): 20 + i
              for i, f in enumerate(fixtures)}
    return fixtures, manager, defs, id_map


@pytest.mark.parametrize("case", SEGMENT_CASES, ids=_case_id)
def test_exported_sunstrip_matches_native(strip_lane, case):
    fixtures, manager, defs, id_map = strip_lane
    block = _dimmer_block(**case)
    mismatches = []
    for time_s in TIMES:
        step = build_unified_step(
            0, time_s, 50, fixtures, id_map, defs, [block], [], [], [],
            1, all_lane_fixtures=fixtures, bpm=120.0)
        exported = _parse_step(step)
        for idx, fixture in enumerate(fixtures):
            fmap = manager.fixture_maps[fixture.name]
            manager.clear_all_dmx()
            manager._apply_dimmer_block(fmap, block, time_s, idx,
                                        len(fixtures))
            got = exported.get(id_map[(fixture.universe, fixture.address)],
                               {})
            for ch in range(STRIP_SEGMENTS):
                universe, channel = fmap.get_absolute_address(ch)
                native = manager.dmx_state[universe][channel]
                if got.get(ch, 0) != native:
                    mismatches.append((time_s, idx, ch, got.get(ch, 0),
                                       native))
    assert not mismatches, \
        f"(t, fixture, channel, export, native): {mismatches[:6]}"


def test_sunstrip_effect_differs_along_the_strip(strip_lane):
    """The export really animates the cells, not one value per strip."""
    fixtures, manager, defs, id_map = strip_lane
    block = _dimmer_block(effect_type="chase")
    step = build_unified_step(
        0, 0.37, 50, fixtures, id_map, defs, [block], [], [], [],
        1, all_lane_fixtures=fixtures, bpm=120.0)
    cells = _parse_step(step)[20]
    assert len({cells.get(ch, 0) for ch in range(STRIP_SEGMENTS)}) > 1


# ── movement ─────────────────────────────────────────────────────────

MOVEMENT_CASES = [
    dict(effect_type=name) for name in sorted(MOVEMENT_REGISTRY)
] + [
    dict(effect_type=name, phase_offset_enabled=True,
         phase_offset_degrees=90.0)
    for name in sorted(MOVEMENT_REGISTRY)
] + [
    dict(effect_type="lissajous", lissajous_ratio="3:2"),
    dict(effect_type="circle", effect_speed="4"),
    dict(effect_type="square", effect_speed="2", phase_offset_enabled=True,
         phase_offset_degrees=45.0),
]


@pytest.fixture
def mover_lane(mock_fixture_def):
    fixtures = [_mover(i) for i in range(3)]
    manager = DMXManager(_config(fixtures), {DEF_KEY: mock_fixture_def})
    return fixtures, manager


def _movement_block(**kw):
    params = dict(start_time=0.0, end_time=8.0, pan=120.0, tilt=110.0,
                  pan_amplitude=40.0, tilt_amplitude=30.0)
    params.update(kw)
    return MovementBlock(**params)


@pytest.mark.parametrize("case", MOVEMENT_CASES, ids=_case_id)
def test_exported_movement_matches_native(mover_lane, case):
    fixtures, manager = mover_lane
    block = _movement_block(**case)
    mismatches = []
    for time_s in TIMES:
        for idx, fixture in enumerate(fixtures):
            fmap = manager.fixture_maps[fixture.name]
            manager.clear_all_dmx()
            manager._apply_movement_block(fmap, block, time_s, idx,
                                          len(fixtures))
            pan_u, pan_ch = fmap.get_absolute_address(fmap.pan_channels[0])
            tilt_u, tilt_ch = fmap.get_absolute_address(
                fmap.tilt_channels[0])
            native = (manager.dmx_state[pan_u][pan_ch],
                      manager.dmx_state[tilt_u][tilt_ch])
            # fixture=None: solver-space values, no yoke conversion
            # (the native state above is solver space too).
            exported = sample_movement_at_time(
                time_s, [block], idx, len(fixtures), 0, 1, bpm=120.0,
                signature="4/4")
            if tuple(exported) != tuple(native):
                mismatches.append((time_s, idx, exported, native))
    assert not mismatches, f"(t, fixture, export, native): {mismatches[:6]}"


class TestDanglingSpotFallsThroughToPoint:
    """A spot name this config does not know (a morphed show carrying
    rig A's spot names) continues to target_point in the export too,
    like the native renderer since 2026-07-16."""

    def _setup(self):
        fixture = Fixture(
            universe=1, address=1, manufacturer="NoSuchMfr_parity",
            model="StepMover", name="MH1", group="Lane",
            current_mode="Standard",
            available_modes=[FixtureMode(name="Standard", channels=10)],
            type="MH", x=-1.0, y=0.0, z=4.0)
        config = _config([fixture])
        config.spots = {"Mark": Spot(name="Mark", x=1.0, y=-2.0, z=0.0)}
        return fixture, config

    def _sample(self, config, fixture, block):
        return sample_movement_at_time(
            0.0, [block], 0, 1, 0, 1, bpm=120.0, signature="4/4",
            config=config, fixture=fixture)

    def test_dangling_spot_uses_the_point(self):
        fixture, config = self._setup()
        point = [1.0, -2.0, 0.0]
        via_point = self._sample(config, fixture,
                                 _movement_block(effect_type="static",
                                                 target_point=point))
        dangling = self._sample(config, fixture, _movement_block(
            effect_type="static", target_spot_name="NoSuchSpot",
            target_point=point, pan=10.0, tilt=10.0))
        manual = self._sample(config, fixture, _movement_block(
            effect_type="static", pan=10.0, tilt=10.0))
        assert dangling == via_point
        assert dangling != manual

    def test_dangling_spot_without_point_stays_manual(self):
        fixture, config = self._setup()
        dangling = self._sample(config, fixture, _movement_block(
            effect_type="static", target_spot_name="NoSuchSpot",
            pan=10.0, tilt=10.0))
        manual = self._sample(config, fixture, _movement_block(
            effect_type="static", pan=10.0, tilt=10.0))
        assert dangling == manual


# ── step grid resolution for the newly exported effects ──────────────

@pytest.mark.parametrize("effect, max_step_ms", [
    ("throb", 500 / 8),      # per-beat decay: 8 steps per beat
    ("fade", 2000 / 16),     # ramps: 16 steps per bar
    ("cascade", 2000 / 16),
])
def test_step_grid_resolves_the_effect(effect, max_step_ms):
    """Sampled once per beat, throb sits on its attack peak every step
    (a static look again) and the fade/cascade ramps become stairs."""
    from utils.to_xml.unified_sequence import calculate_unified_step_grid
    block = _dimmer_block(effect_type=effect)
    _, step_ms = calculate_unified_step_grid([block], [], [], [], 120.0)
    assert step_ms <= max_step_ms


def test_single_fixture_wave_matches_native(dimmer_lane):
    """A one-fixture wave used to run an export-only breathing curve
    that ran in the opposite phase to native."""
    fixtures, manager, defs, id_map = dimmer_lane
    block = _dimmer_block(effect_type="wave")
    for time_s in TIMES:
        exported = sample_dimmer_at_time(time_s, [block], 0, 1, 0, 1,
                                         fixture_name=fixtures[0].name)
        native = _native_dimmer(manager, fixtures[0], block, time_s, 0, 1)
        assert exported == native, time_s
