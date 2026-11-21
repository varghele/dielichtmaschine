"""
Tests for :func:`autogen.spatial.classify_fixture_groups` zone classification.

The Stage tab and 3D visualiser use a **centered Y** coordinate system::

    y < 0   downstage (closer to audience)
    y == 0  centre line
    y > 0   upstage (back of stage)

Valid Y range is ``[-stage_height/2, +stage_height/2]``.

Earlier versions of ``classify_fixture_groups`` assumed Y ranged
``[0, stage_height]`` and used thresholds at ``D * 0.33`` / ``D * 0.66``.
Net effect on real centred-Y configs:

- A fixture at ``y=0`` (centre line) was classified "front"
- A fixture at ``y=+2`` on a 10 m stage was classified "front"
- A fixture at ``y=+4`` was classified "mid"
- Only fixtures at ``y > +6.6`` (i.e. off-stage past the back edge) got "back"

This file pins the corrected behaviour: thirds split at ``±D/6`` in
centred coordinates so each Y zone really covers a third of the stage.
"""

from __future__ import annotations

from autogen.spatial import classify_fixture_groups
from config.models import Configuration, Fixture, FixtureGroup, FixtureMode


def _make_fixture(name: str, y: float, z: float = 0.0) -> Fixture:
    """Minimal fixture stub with just enough state for the classifier."""
    return Fixture(
        universe=1,
        address=1,
        manufacturer="Test",
        model="Stub",
        name=name,
        group="G",
        current_mode="1",
        available_modes=[FixtureMode(name="1", channels=1)],
        type="PAR",
        x=0.0, y=y, z=z,
        mounting="standing",
        yaw=0.0, pitch=0.0, roll=0.0,
        orientation_uses_group_default=False,
        z_uses_group_default=False,
    )


def _make_config(groups: dict[str, list[Fixture]], stage_height: float = 10.0) -> Configuration:
    cfg = Configuration(stage_height=stage_height, stage_width=10.0)
    for gname, fixtures in groups.items():
        cfg.fixtures.extend(fixtures)
        cfg.groups[gname] = FixtureGroup(name=gname, fixtures=fixtures)
    return cfg


# ── Boundary cases on a 10 m-deep stage (thresholds at ±5/3 ≈ ±1.67) ─


def test_downstage_fixture_classifies_as_front():
    """A fixture at y=-3 on a 10 m stage sits in the downstage third."""
    cfg = _make_config({"DS": [_make_fixture("ds1", y=-3.0)]})
    result = classify_fixture_groups(cfg)
    assert result["DS"].zone == "front"


def test_centre_fixture_classifies_as_mid():
    """y=0 is the centre line. Pre-fix it was "front" because 0 < D*0.33."""
    cfg = _make_config({"CTR": [_make_fixture("c1", y=0.0)]})
    result = classify_fixture_groups(cfg)
    assert result["CTR"].zone == "mid"


def test_upstage_fixture_classifies_as_back():
    """A fixture at y=+3 on a 10 m stage sits in the upstage third."""
    cfg = _make_config({"US": [_make_fixture("us1", y=3.0)]})
    result = classify_fixture_groups(cfg)
    assert result["US"].zone == "back"


def test_just_inside_centre_third_classifies_as_mid():
    """y just inside the middle-third boundary stays "mid"."""
    # threshold = stage_height / 6 ≈ 1.666… for D=10
    cfg = _make_config({
        "MID_NEAR_FRONT": [_make_fixture("a", y=-1.5)],
        "MID_NEAR_BACK": [_make_fixture("b", y=1.5)],
    }, stage_height=10.0)
    result = classify_fixture_groups(cfg)
    assert result["MID_NEAR_FRONT"].zone == "mid"
    assert result["MID_NEAR_BACK"].zone == "mid"


def test_just_outside_centre_third_flips_zone():
    """y just past the threshold flips out of "mid"."""
    cfg = _make_config({
        "FRONT_EDGE": [_make_fixture("a", y=-2.0)],
        "BACK_EDGE": [_make_fixture("b", y=2.0)],
    }, stage_height=10.0)
    result = classify_fixture_groups(cfg)
    assert result["FRONT_EDGE"].zone == "front"
    assert result["BACK_EDGE"].zone == "back"


def test_overhead_overrides_y_zone():
    """High z trumps the Y classification — anything sitting more than
    half the assumed ceiling above the floor counts as overhead."""
    cfg = _make_config({"OH": [_make_fixture("oh", y=-3.0, z=3.0)]})
    result = classify_fixture_groups(cfg)
    # y=-3 alone would say "front", but z=3 > 4*0.5 = 2 wins.
    assert result["OH"].zone == "overhead"


def test_demo_config_layout_classifies_correctly():
    """Sanity check against the exact two-row layout shipped in the legacy
    ``conf_demo_all_fixtures.yaml`` (moved to local-only ``archive/`` in v1.0):
    downstage row at y=-3, upstage row at y=+3 on a 10 m stage. Pre-fix both
    rows came out "front" because both ``-3 < D*0.33 = 3.3`` and ``3 < D*0.33``."""
    cfg = _make_config({
        "DOWNSTAGE": [_make_fixture("d", y=-3.0)],
        "UPSTAGE":   [_make_fixture("u", y=3.0)],
    }, stage_height=10.0)
    result = classify_fixture_groups(cfg)
    assert result["DOWNSTAGE"].zone == "front"
    assert result["UPSTAGE"].zone == "back"


def test_empty_group_is_skipped():
    """Groups with no fixtures should not appear in the result."""
    cfg = Configuration(stage_height=10.0)
    cfg.groups["EMPTY"] = FixtureGroup(name="EMPTY", fixtures=[])
    cfg.groups["FILLED"] = FixtureGroup(name="FILLED",
                                        fixtures=[_make_fixture("a", y=0.0)])
    cfg.fixtures = [cfg.groups["FILLED"].fixtures[0]]
    result = classify_fixture_groups(cfg)
    assert "EMPTY" not in result
    assert "FILLED" in result


def test_zero_stage_depth_falls_through_to_mid():
    """A degenerate stage with stage_height=0 must not divide by zero
    and must produce a deterministic fallback ("mid" — the catch-all)."""
    cfg = _make_config({"X": [_make_fixture("a", y=0.0)]}, stage_height=0.0)
    result = classify_fixture_groups(cfg)
    assert result["X"].zone == "mid"
