"""utils/position_presets.py - the computed position presets the Live
tab's POSITION pool lists above the spike marks.

Pure-function tests, no Qt: preset identity/order, the point targets
(CENTRE, AUDIENCE, one per matching placed stage element with the
element's layer height folded in), the per-fixture pattern targets
(CROSS, FAN OUT, FLOOR, CEILING), and the element_preset_ids helper LiveState
prunes against. Coordinate frame is config/stage space: X centered,
Y depth centered with negative = front/audience, Z height, meters.
"""

import pytest

from config.models import (
    Configuration, Fixture, FixtureMode, StageElement, StageLayer,
)
from utils.position_presets import (
    ELEMENT_PRESET_PREFIX, KIND_PATTERN, KIND_POINT, MARK_PREFIX,
    PATTERN_TAG, PRESET_PREFIX, compute_presets, element_preset_ids,
    mark_id, mark_name,
)


def _fixture(x=0.0, y=0.0, z=0.0):
    return Fixture(universe=1, address=1, manufacturer="M", model="F",
                   name="fx", group="G", current_mode="Standard",
                   available_modes=[FixtureMode(name="Standard",
                                                channels=8)],
                   x=x, y=y, z=z)


def _config(**kwargs):
    kwargs.setdefault("stage_width", 8.0)
    kwargs.setdefault("stage_height", 6.0)   # stage DEPTH (compat name)
    return Configuration(**kwargs)


def _element(kind, x=0.0, y=0.0, layer="", element_id="el1"):
    return StageElement(kind=kind, x=x, y=y, layer=layer,
                        element_id=element_id)


def _by_id(config):
    return {p.preset_id: p for p in compute_presets(config)}


class TestIds:
    def test_mark_id_roundtrip(self):
        assert mark_id("DS Centre") == "mark:DS Centre"
        assert mark_name(mark_id("DS Centre")) == "DS Centre"
        assert mark_id("x").startswith(MARK_PREFIX)

    def test_element_prefix_nests_inside_preset_prefix(self):
        # LiveState's prune checks ELEMENT first, then the broader
        # PRESET namespace - the nesting is deliberate.
        assert ELEMENT_PRESET_PREFIX.startswith(PRESET_PREFIX)


class TestGeometryPresets:
    def test_deterministic_order_and_identity(self):
        presets = compute_presets(_config())
        assert [p.preset_id for p in presets] == [
            "preset:centre", "preset:audience", "preset:cross",
            "preset:fanout", "preset:floor", "preset:ceiling"]
        assert [p.label for p in presets] == [
            "Centre", "Audience", "Cross", "Fan Out", "Floor", "Ceiling"]
        assert [p.kind for p in presets] == [
            KIND_POINT, KIND_POINT, KIND_PATTERN, KIND_PATTERN,
            KIND_PATTERN, KIND_PATTERN]

    def test_centre_is_centre_stage_at_focus_height(self):
        preset = _by_id(_config())["preset:centre"]
        assert preset.target_for(_fixture(x=3.0, y=2.0)) == (0.0, 0.0, 1.5)
        assert preset.tag == "0.0 · 0.0"

    def test_audience_sits_past_the_downstage_edge(self):
        # Depth 6 m: front edge at y = -3, plus the 3 m throw -> -6,
        # head height 2 m.
        preset = _by_id(_config(stage_height=6.0))["preset:audience"]
        assert preset.target_for(_fixture()) == (0.0, -6.0, 2.0)
        assert preset.tag == "0.0 · -6.0"

    def test_audience_follows_the_stage_depth(self):
        preset = _by_id(_config(stage_height=10.0))["preset:audience"]
        assert preset.target_for(_fixture()) == (0.0, -8.0, 2.0)

    def test_cross_mirrors_x_and_clamps_y_downstage(self):
        preset = _by_id(_config())["preset:cross"]
        # Mirrored across the centreline, upstage y clamped to 0, floor
        # zone height.
        assert preset.target_for(_fixture(x=2.0, y=1.5)) == (-2.0, 0.0, 0.5)
        assert preset.target_for(_fixture(x=-3.0, y=-1.0)) == (3.0, -1.0, 0.5)
        assert preset.tag == PATTERN_TAG

    def test_cross_near_centre_still_crosses(self):
        # Mirroring 0.1 m to -0.1 m reads as straight down, not a
        # cross - near-centre fixtures throw a fixed 1.5 m to the other
        # side, sign(0) = +1 counting as stage right.
        preset = _by_id(_config())["preset:cross"]
        assert preset.target_for(_fixture(x=0.1)) == (-1.5, 0.0, 0.5)
        assert preset.target_for(_fixture(x=-0.2)) == (1.5, 0.0, 0.5)
        assert preset.target_for(_fixture(x=0.0)) == (-1.5, 0.0, 0.5)

    def test_fan_out_throws_past_the_stage_edge(self):
        # Width 8 m: half width 4 plus the 2 m throw -> +-6, raised to
        # 4 m, own depth kept. sign(0) = +1.
        preset = _by_id(_config(stage_width=8.0))["preset:fanout"]
        assert preset.target_for(_fixture(x=1.0, y=2.0)) == (6.0, 2.0, 4.0)
        assert preset.target_for(_fixture(x=-0.5, y=-1.0)) == (-6.0, -1.0, 4.0)
        assert preset.target_for(_fixture(x=0.0)) == (6.0, 0.0, 4.0)

    def test_ceiling_is_straight_up_from_the_fixture(self):
        preset = _by_id(_config())["preset:ceiling"]
        assert preset.target_for(_fixture(x=1.0, y=-2.0, z=3.5)) == \
            (1.0, -2.0, 13.5)

    def test_floor_is_straight_down_to_the_deck(self):
        # The natural rest for a hanging mover: same x/y, z=0.
        preset = _by_id(_config())["preset:floor"]
        assert preset.target_for(_fixture(x=1.0, y=-2.0, z=3.5)) == \
            (1.0, -2.0, 0.0)


class TestElementPresets:
    def test_matching_elements_get_presets_in_config_order(self):
        cfg = _config(stage_elements=[
            _element("drum-riser", x=0.0, y=1.5, element_id="a"),
            _element("wedge", element_id="b"),          # no preset
            _element("keys", x=-2.0, y=0.5, element_id="c"),
            _element("foh", element_id="d"),
            _element("mic-stand", x=0.0, y=-2.0, element_id="e"),
            _element("truss-straight", element_id="f"),  # no preset
        ])
        presets = compute_presets(cfg)[6:]
        assert [p.preset_id for p in presets] == [
            "preset:element:a", "preset:element:c",
            "preset:element:d", "preset:element:e"]
        assert [p.label for p in presets] == ["Drums", "Keys", "FOH", "Mic"]
        assert all(p.kind == KIND_POINT for p in presets)

    def test_target_is_element_centre_at_focus_raise(self):
        cfg = _config(stage_elements=[
            _element("drum-riser", x=1.0, y=1.5, element_id="a")])
        preset = _by_id(cfg)["preset:element:a"]
        assert preset.target_for(_fixture()) == (1.0, 1.5, 1.2)
        assert preset.tag == "1.0 · 1.5"

    def test_layer_height_folds_into_the_target(self):
        cfg = _config(
            stage_layers=[StageLayer(name="Riser deck", z_height=0.6)],
            stage_elements=[_element("drum-riser", x=0.0, y=1.5,
                                     layer="Riser deck", element_id="a")])
        assert _by_id(cfg)["preset:element:a"].point == \
            pytest.approx((0.0, 1.5, 1.8))

    def test_missing_layer_falls_back_to_the_deck(self):
        cfg = _config(stage_elements=[
            _element("drum-riser", layer="Gone", element_id="a")])
        assert _by_id(cfg)["preset:element:a"].point[2] == 1.2

    def test_duplicate_kinds_get_numbered_labels(self):
        cfg = _config(stage_elements=[
            _element("drum-riser", element_id="a"),
            _element("drum-riser", element_id="b")])
        labels = [p.label for p in compute_presets(cfg)[6:]]
        assert labels == ["Drums", "Drums 2"]

    def test_element_without_id_gets_a_stable_fallback(self):
        cfg = _config(stage_elements=[
            _element("drum-riser", element_id=""),
            _element("keys", element_id="")])
        ids = [p.preset_id for p in compute_presets(cfg)[6:]]
        assert ids == ["preset:element:idx0", "preset:element:idx1"]
        # ...and the prune helper derives the identical ids.
        assert element_preset_ids(cfg) == ids

    def test_element_preset_ids_matches_compute_presets(self):
        cfg = _config(stage_elements=[
            _element("drum-riser", element_id="a"),
            _element("wedge", element_id="b"),
            _element("foh", element_id="c")])
        assert element_preset_ids(cfg) == [
            "preset:element:a", "preset:element:c"]
        assert element_preset_ids(_config()) == []
