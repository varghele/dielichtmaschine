# tests/unit/test_fixture_caches.py
"""Fixture-definition cache invalidation and mode-aware group analysis
(v1.5.5 hardening, group G5).

Four modules memoize data derived from fixture definitions: the library
itself (utils/fixture_library), the legacy dict cache
(utils/fixture_utils), the capabilities cache
(utils/fixture_capabilities), the yoke + physical-range lookups
(utils/yoke) and the visualizer protocol parse (utils/tcp/protocol).
A library rescan (user library dir changed, GDTF Share download, GDTF
autopull) used to clear only the first, so the derived caches kept
serving the stale (or "not found") answer until restart.
invalidate_fixture_caches() is the one entry point that clears them all.

The group-analysis half pins that detect_fixture_group_capabilities and
get_color_wheel_options read the channels of the fixture's CURRENT MODE,
the same set FixtureChannelMap drives, instead of every channel the
definition declares.
"""

import os
from types import SimpleNamespace

import pytest

from utils import fixture_library as fl

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
CUSTOM_FIXTURES = os.path.join(REPO_ROOT, "custom_fixtures")

MH = ("Varytec", "Hero Spot 60")
PAR = ("Stairville", "Retro Flat Par 18x12W RGBW ")  # trailing space: verbatim


def _fx(identity, mode):
    return SimpleNamespace(manufacturer=identity[0], model=identity[1],
                           current_mode=mode)


@pytest.fixture()
def library(monkeypatch):
    """A switchable search path: starts EMPTY (nothing resolves), and
    ``library.publish()`` makes custom_fixtures/ reachable, standing in
    for a definition that lands on disk mid-session (Share download,
    autopull, a new user library dir)."""
    state = {"dirs": []}
    monkeypatch.setattr(fl, "fixture_search_dirs", lambda: list(state["dirs"]))
    fl.invalidate_fixture_caches()

    def publish():
        state["dirs"] = [(CUSTOM_FIXTURES, "bundled")]

    yield SimpleNamespace(publish=publish)
    fl.invalidate_fixture_caches()


@pytest.fixture()
def bundled_only(monkeypatch):
    monkeypatch.setattr(
        fl, "fixture_search_dirs", lambda: [(CUSTOM_FIXTURES, "bundled")])
    fl.invalidate_fixture_caches()
    yield
    fl.invalidate_fixture_caches()


# ---------------------------------------------------------------------------
# invalidate_fixture_caches clears every derived cache
# ---------------------------------------------------------------------------

class TestInvalidateFixtureCaches:
    def test_capabilities_recover_after_a_definition_lands(self, library):
        from utils.fixture_capabilities import (
            Chassis, get_capabilities_for_fixture)
        fixture = _fx(MH, "14 Channel")
        assert get_capabilities_for_fixture(fixture).chassis == Chassis.OTHER

        library.publish()
        fl.invalidate_fixture_caches()

        assert get_capabilities_for_fixture(fixture).chassis != Chassis.OTHER

    def test_legacy_dict_cache_is_cleared(self, bundled_only):
        from utils import fixture_utils
        fixture_utils.get_cached_fixture_definitions({MH})
        held = fixture_utils._fixture_definitions_cache
        assert held

        fl.invalidate_fixture_caches()

        assert not fixture_utils._fixture_definitions_cache
        # Rebound, not cleared in place: a holder taken before the clear
        # (ShowsArtNetController via DMXManager, RenderWorker) rebuilds its
        # fixture maps from it later and must not find it emptied.
        assert held

    def test_physical_ranges_recover_after_a_definition_lands(self, library):
        from utils.yoke import physical_ranges
        assert physical_ranges(*MH) == (540.0, 270.0)  # unresolved default

        library.publish()
        fl.invalidate_fixture_caches()

        defn = fl.get_definition(*MH)
        assert physical_ranges(*MH) == (defn.pan_max or 540.0,
                                        defn.tilt_max or 270.0)
        assert physical_ranges(*MH) != (540.0, 270.0)

    def test_visualizer_protocol_parse_recovers(self, library):
        from utils.tcp.protocol import _parse_qxf_for_visualizer
        before = _parse_qxf_for_visualizer(MH[0], MH[1], "14 Channel")
        assert before["channel_mapping"] == {}

        library.publish()
        fl.invalidate_fixture_caches()

        after = _parse_qxf_for_visualizer(MH[0], MH[1], "14 Channel")
        assert after["channel_mapping"], "real definition parsed after rescan"

    def test_clear_fixture_definitions_cache_is_the_full_invalidation(
            self, library):
        from utils import fixture_utils
        from utils.fixture_capabilities import (
            Chassis, get_capabilities_for_fixture)
        fixture = _fx(MH, "14 Channel")
        assert get_capabilities_for_fixture(fixture).chassis == Chassis.OTHER

        library.publish()
        fixture_utils.clear_fixture_definitions_cache()

        assert get_capabilities_for_fixture(fixture).chassis != Chassis.OTHER


# ---------------------------------------------------------------------------
# get_capabilities_for_fixture never memoizes its safe default
# (v1.5.5 handover: it cached the "not found" default, so only the full
# invalidation could heal it)
# ---------------------------------------------------------------------------

class TestCapabilitiesFailureCaching:
    def test_unresolved_definition_is_not_cached(self, library):
        from utils.fixture_capabilities import (
            Chassis, get_capabilities_for_fixture)
        fixture = _fx(MH, "14 Channel")
        assert get_capabilities_for_fixture(fixture).chassis == Chassis.OTHER

        # Only the LIBRARY cache drops: capabilities must pick the
        # definition up on their own, like the yoke below.
        library.publish()
        fl.clear_library_cache()

        assert get_capabilities_for_fixture(fixture).chassis == Chassis.MOVING_YOKE

    def test_resolved_result_is_cached(self, bundled_only, monkeypatch):
        from utils import fixture_capabilities as fc
        fixture = _fx(MH, "14 Channel")
        first = fc.get_capabilities_for_fixture(fixture)
        calls = []
        monkeypatch.setattr(fc, "_find_and_parse_qxf",
                            lambda *a: calls.append(a))
        assert fc.get_capabilities_for_fixture(fixture) is first
        assert calls == [], "a resolved fixture is a pure cache hit"


# ---------------------------------------------------------------------------
# fixture_yoke never memoizes an unresolved definition
# ---------------------------------------------------------------------------

class TestFixtureYokeFailureCaching:
    def test_unresolved_definition_is_not_cached(self, library):
        from utils.yoke import fixture_yoke
        assert fixture_yoke(MH[0], MH[1], "14 Channel") == (False, False)

        # Only the LIBRARY cache drops (the pre-G5 rescan paths did just
        # this): the yoke must pick the definition up on its own.
        library.publish()
        fl.clear_library_cache()

        assert fixture_yoke(MH[0], MH[1], "14 Channel") == (True, True)

    def test_resolved_result_is_cached(self, bundled_only, monkeypatch):
        from utils import yoke
        assert yoke.fixture_yoke(MH[0], MH[1], "14 Channel") == (True, True)
        calls = []
        real = fl.get_definition
        monkeypatch.setattr(fl, "get_definition",
                            lambda *a: calls.append(a) or real(*a))
        assert yoke.fixture_yoke(MH[0], MH[1], "14 Channel") == (True, True)
        assert calls == [], "a resolved yoke is a pure cache hit"

    def test_invalidation_drops_resolved_entries(self, bundled_only,
                                                 monkeypatch):
        from utils import yoke
        assert yoke.fixture_yoke(MH[0], MH[1], "14 Channel") == (True, True)
        fl.invalidate_fixture_caches()
        monkeypatch.setattr(fl, "fixture_search_dirs", lambda: [])
        fl.clear_library_cache()
        assert yoke.fixture_yoke(MH[0], MH[1], "14 Channel") == (False, False)

    def test_cache_clear_alias_still_works(self, bundled_only):
        # tests and tools call fixture_yoke.cache_clear() (lru_cache API).
        from utils.yoke import fixture_yoke
        fixture_yoke(MH[0], MH[1], "14 Channel")
        fixture_yoke.cache_clear()


# ---------------------------------------------------------------------------
# Rescan paths route through invalidate_fixture_caches
# ---------------------------------------------------------------------------

class TestRescanPathsInvalidate:
    @pytest.fixture()
    def calls(self, monkeypatch):
        seen = []
        monkeypatch.setattr(fl, "invalidate_fixture_caches",
                            lambda: seen.append(True))
        return seen

    def test_library_dir_change(self, calls):
        from utils import app_settings as aps
        aps.set_user_qxf_dir("")
        assert calls == [True]

    def test_share_download(self, qapp, calls):
        from gui.dialogs.gdtf_share_pane import GDTFSharePane
        pane = SimpleNamespace(
            status_label=SimpleNamespace(setText=lambda _t: None),
            fixtures_downloaded=SimpleNamespace(emit=lambda _p: None))
        GDTFSharePane._on_downloaded(pane, ["/x/a.gdtf"])
        assert calls == [True]

    def test_gdtf_autopull(self, qapp, calls):
        from gui.gui import MainWindow
        window = SimpleNamespace(
            statusbar=SimpleNamespace(showMessage=lambda *_a: None))
        MainWindow._on_gdtf_autopull_done(window, ["/x/Mfr@Model.gdtf"])
        assert calls == [True]


# ---------------------------------------------------------------------------
# Group analysis reads the fixture's current mode
# ---------------------------------------------------------------------------

class TestModeAwareGroupCapabilities:
    def test_mover_in_8_channel_mode_has_no_colour(self, bundled_only):
        from utils.fixture_utils import detect_fixture_group_capabilities
        caps = detect_fixture_group_capabilities([_fx(MH, "8 Channel")])
        assert caps.has_movement and caps.has_dimmer
        assert not caps.has_colour, "8 Channel mode exposes no colour channel"
        # No gobo / prism in this mode, but Focus (BeamFocusNearFar) is a
        # special-sublane parameter that FixtureChannelMap does drive.
        assert caps.has_special

    def test_special_comes_from_mode_channels_only(self):
        from utils.fixture_utils import detect_fixture_group_capabilities
        defs = {"M_X": {
            "channels": [
                {"name": "Pan", "preset": "PositionPan"},
                {"name": "Gobo", "preset": None, "group": "Gobo"},
            ],
            "modes": [
                {"name": "Basic", "channels": [{"number": 0, "name": "Pan"}]},
                {"name": "Full", "channels": [{"number": 0, "name": "Pan"},
                                              {"number": 1, "name": "Gobo"}]},
            ],
        }}
        basic = SimpleNamespace(manufacturer="M", model="X",
                                current_mode="Basic")
        full = SimpleNamespace(manufacturer="M", model="X",
                               current_mode="Full")
        assert not detect_fixture_group_capabilities([basic], defs).has_special
        assert detect_fixture_group_capabilities([full], defs).has_special

    def test_mover_in_14_channel_mode_keeps_colour_and_special(
            self, bundled_only):
        from utils.fixture_utils import detect_fixture_group_capabilities
        caps = detect_fixture_group_capabilities([_fx(MH, "14 Channel")])
        assert caps.has_movement and caps.has_dimmer
        assert caps.has_colour and caps.has_special

    def test_unknown_mode_falls_back_to_every_channel(self, bundled_only):
        # A mode name the definition does not carry (hand-edited YAML,
        # pre-reconciliation config) keeps the historical whole-definition
        # analysis rather than reporting an empty group.
        from utils.fixture_utils import detect_fixture_group_capabilities
        caps = detect_fixture_group_capabilities([_fx(MH, "No Such Mode")])
        assert caps.has_movement and caps.has_colour and caps.has_special

    def test_definition_without_modes_falls_back(self):
        from utils.fixture_utils import detect_fixture_group_capabilities
        defs = {"M_X": {"channels": [{"name": "Red", "preset": "IntensityRed"}]}}
        fixture = SimpleNamespace(manufacturer="M", model="X",
                                  current_mode="Any")
        assert detect_fixture_group_capabilities([fixture], defs).has_colour

    def test_mixed_modes_union_per_fixture(self, bundled_only):
        from utils.fixture_utils import detect_fixture_group_capabilities
        caps = detect_fixture_group_capabilities(
            [_fx(MH, "8 Channel"), _fx(MH, "14 Channel")])
        assert caps.has_colour and caps.has_special


class TestModeAwareColourWheel:
    def test_par_in_6_channel_mode_offers_no_wheel(self, bundled_only):
        from utils.fixture_utils import get_color_wheel_options
        assert get_color_wheel_options([_fx(PAR, "6 Channel")]) == []

    def test_par_in_8_channel_mode_offers_its_colour_selection(
            self, bundled_only):
        from utils.fixture_utils import get_color_wheel_options
        assert get_color_wheel_options([_fx(PAR, "8 Channel")])

    def test_mover_wheel_follows_the_mode(self, bundled_only):
        from utils.fixture_utils import get_color_wheel_options
        assert get_color_wheel_options([_fx(MH, "8 Channel")]) == []
        assert get_color_wheel_options([_fx(MH, "14 Channel")])


class TestColourDialogWheelMode:
    """The colour editor stores color_mode from the wheel options it is
    given. Since G5 a wheel-less patched mode yields no options, so the
    block stays RGB; the dialog half of docs/bug-reports.md entry 2
    (a fixture WITH a wheel records 'Wheel' even after an RGB-only edit)
    is still open and pinned as a strict xfail."""

    def _dialog(self, block, fixtures):
        from timeline_ui.colour_block_dialog import ColourBlockDialog
        from utils.fixture_utils import get_color_wheel_options
        return ColourBlockDialog(block, get_color_wheel_options(fixtures))

    def test_wheel_less_mode_records_rgb(self, qapp, bundled_only):
        from config.models import ColourBlock
        block = ColourBlock(start_time=0, end_time=4)
        dlg = self._dialog(block, [_fx(PAR, "6 Channel")])
        dlg.sliders["red"][1].setValue(255)
        dlg.accept()
        assert block.color_mode == "RGB"

    @pytest.mark.xfail(
        strict=True,
        reason="BUG (docs/bug-reports.md #2): ColourBlockDialog.accept() "
               "sets color_mode='Wheel' whenever wheel options exist, even "
               "when only the RGB sliders were touched.")
    def test_rgb_only_edit_on_a_wheel_mode_records_rgb(self, qapp,
                                                       bundled_only):
        from config.models import ColourBlock
        block = ColourBlock(start_time=0, end_time=4)
        dlg = self._dialog(block, [_fx(PAR, "8 Channel")])
        dlg.sliders["red"][1].setValue(255)
        dlg.accept()
        assert block.color_mode == "RGB"
