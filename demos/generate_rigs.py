#!/usr/bin/env python3
"""Deterministic generator for the bundled demo lighting rigs.

Each rig is a standard, recognisable stage archetype (club band, mid-size
band, festival mainstage, DJ/EDM, static theatre) emitted as a
``Configuration`` YAML. The rigs reference **only** the fixtures bundled in
``custom_fixtures/``, so they load and render on any machine regardless of
which QLC+ version (or none) the user has installed — the stock QLC+
"Generic" manufacturer folder has no movers/beams/strobes, so it can't
express these layouts.

The generator reads the real modes and channel counts straight out of the
``.qxf`` files (via the project's own ``determine_fixture_type``), so the
``available_modes`` and DMX addressing are always correct, even if a fixture
definition is later edited.

Coordinate convention (matches the Stage tab / 3D visualiser):

    X  left -> right across the stage width,   range [-W/2, +W/2]
    Y  depth, CENTRED: y < 0 downstage (front, near audience),
                       y > 0 upstage (back);    range [-D/2, +D/2]
    Z  height in metres (z above ~2 reads as overhead)

Run:
    python -m demos.generate_rigs       # from the project root
    python demos/generate_rigs.py
Output:
    demos/rigs/<name>.lms
"""

from __future__ import annotations

import os
import sys
import xml.etree.ElementTree as ET

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from config.models import (  # noqa: E402
    Configuration, Fixture, FixtureGroup, FixtureMode, Universe,
)
from utils.fixture_utils import determine_fixture_type  # noqa: E402

CUSTOM_FIXTURES = os.path.join(PROJECT_ROOT, "custom_fixtures")
OUT_DIR = os.path.join(PROJECT_ROOT, "demos", "rigs")
QLC_NS = {"": "http://www.qlcplus.org/FixtureDefinition"}

# Short id -> (manufacturer, model-name prefix, preferred mode name).
# The model is matched by prefix so we never trip over quirks like the
# trailing space in "Retro Flat Par 18x12W RGBW ".
CATALOG = {
    "PAR":    ("Stairville", "Retro Flat Par",          "8 Channel"),
    "WASH":   ("Stairville", "Wild Wash Pro",           "6 Channel"),
    "SPOT":   ("Varytec",    "Hero Spot 60",            "14 Channel"),
    "MWASH":  ("Martin",     "MAC Aura",                "Standard"),
    "BLADE":  ("Ayrton",     "MagicBlade R",            "St (20ch)"),
    "GBAR":   ("Varytec",    "Giga Bar 5 LED RGBW",     "8 Channels"),
    "LBAR":   ("Varghele",   "LED BAR",                 "40 Channels Mode"),
    "SUN":    ("Showtec",    "Sunstrip Active",         "10 Channels Mode"),
    "MATRIX": ("Stairville", "LED Matrix Blinder 5x5",  "26-Channel"),
}


def scan_custom_fixtures() -> dict:
    """Parse every .qxf in custom_fixtures/ into {(manufacturer, model): def}."""
    defs = {}
    for fn in sorted(os.listdir(CUSTOM_FIXTURES)):
        if not fn.endswith(".qxf"):
            continue
        root = ET.parse(os.path.join(CUSTOM_FIXTURES, fn)).getroot()
        manufacturer = root.find(".//Manufacturer", QLC_NS).text
        model = root.find(".//Model", QLC_NS).text
        modes = [
            {"name": m.get("Name"), "channels": len(m.findall("Channel", QLC_NS))}
            for m in root.findall(".//Mode", QLC_NS)
        ]
        defs[(manufacturer, model)] = {
            "type": determine_fixture_type(root),
            "modes": modes,
        }
    return defs


def resolve(defs: dict, cat_id: str):
    """Resolve a catalogue id to (key, definition, chosen_mode)."""
    manufacturer, model_prefix, preferred = CATALOG[cat_id]
    key = next(
        ((man, mod) for (man, mod) in defs
         if man == manufacturer and mod.strip().startswith(model_prefix)),
        None,
    )
    if key is None:
        raise KeyError(f"{manufacturer} / {model_prefix}* not found in custom_fixtures/")
    fdef = defs[key]
    mode = next((m for m in fdef["modes"] if m["name"] == preferred), None)
    if mode is None:  # fall back to a name that starts the same, else the first mode
        mode = next((m for m in fdef["modes"] if m["name"].startswith(preferred)), None)
    if mode is None:
        mode = fdef["modes"][0]
    return key, fdef, mode


class Patcher:
    """Sequential DMX address allocator that rolls to the next universe at 512."""

    def __init__(self, start_universe: int = 1):
        self.universe = start_universe
        self.addr = 1
        self.used = set()

    def place(self, channels: int):
        if self.addr + channels - 1 > 512:
            self.universe += 1
            self.addr = 1
        u, a = self.universe, self.addr
        self.addr += channels
        self.used.add(u)
        return u, a


def spread(n: int, width: float, margin: float = 0.6) -> list:
    """n x-positions evenly spaced across the stage width, centred on 0."""
    if n <= 1:
        return [0.0]
    half = max(0.0, width / 2 - margin)
    return [round(-half + 2 * half * i / (n - 1), 2) for i in range(n)]


def build_rig(name: str, width: float, depth: float, groups: list) -> Configuration:
    """Assemble a Configuration from a list of group specs.

    Each group spec is a dict:
        name, cat, role, color, mounting, layout
        row  layout: n, y, z
        tower layout: x, y, z_list  (vertical boom: same x, stepped z)
    """
    defs = scan_custom_fixtures()
    patcher = Patcher()
    cfg = Configuration(stage_width=width, stage_height=depth, grid_size=0.5)

    for spec in groups:
        key, fdef, mode = resolve(defs, spec["cat"])
        channels = mode["channels"]
        available = [FixtureMode(name=m["name"], channels=m["channels"]) for m in fdef["modes"]]

        if spec["layout"] == "row":
            positions = [(x, spec["y"], spec["z"]) for x in spread(spec["n"], width)]
        elif spec["layout"] == "tower":
            positions = [(spec["x"], spec["y"], z) for z in spec["z_list"]]
        else:
            raise ValueError(f"unknown layout {spec['layout']!r}")

        fixtures = []
        for i, (x, y, z) in enumerate(positions):
            u, a = patcher.place(channels)
            fixtures.append(Fixture(
                universe=u, address=a,
                manufacturer=key[0], model=key[1],
                name=f"{spec['name']} {i + 1}",
                group=spec["name"],
                current_mode=mode["name"],
                available_modes=available,
                type=fdef["type"],
                x=round(x, 2), y=round(y, 2), z=round(z, 2),
                mounting=spec["mounting"],
                orientation_uses_group_default=True,  # take the group's mounting/angles
                z_uses_group_default=False,           # but keep each fixture's own height
            ))

        cfg.fixtures.extend(fixtures)
        cfg.groups[spec["name"]] = FixtureGroup(
            name=spec["name"],
            fixtures=fixtures,
            color=spec["color"],
            default_mounting=spec["mounting"],
            default_z_height=round(positions[0][2], 2),
            lighting_role=spec["role"],
        )

    for uid in sorted(patcher.used):
        cfg.universes[uid] = Universe(
            id=uid, name=f"Universe {uid}",
            output={
                "plugin": "E1.31", "line": "0",
                "parameters": {
                    "ip": f"192.168.1.{uid}", "port": "6454",
                    "subnet": "0", "universe": str(uid),
                },
            },
        )

    return cfg


# Distinct per-group tints so the fixtures-table row colouring reads clearly.
C_PAR, C_PAR2 = "#4477cc", "#5588dd"
C_WASH = "#cc7744"
C_SPOT = "#44cc77"
C_MWASH = "#cc44aa"
C_BLADE, C_BLADE2 = "#3366bb", "#5599ee"
C_BAR = "#44cccc"
C_BLIND = "#ccaa33"
C_FX = "#cc4444"


RIGS = {
    # ── 1. Club / pub band: smallest viable rig (fast-path test) ──────────
    "club_band": dict(width=8.0, depth=6.0, groups=[
        {"name": "Front PARs", "cat": "PAR",  "role": "backbone", "color": C_PAR,
         "mounting": "hanging",  "layout": "row", "n": 4, "y": -2.0, "z": 2.6},
        {"name": "Back Wash",  "cat": "WASH", "role": "ambient",  "color": C_WASH,
         "mounting": "hanging",  "layout": "row", "n": 2, "y": 2.0,  "z": 2.6},
        {"name": "Movers",     "cat": "SPOT", "role": "movement", "color": C_SPOT,
         "mounting": "hanging",  "layout": "row", "n": 2, "y": 0.0,  "z": 2.8},
        {"name": "Blinder",    "cat": "SUN",  "role": "effect",   "color": C_BLIND,
         "mounting": "standing", "layout": "row", "n": 1, "y": -2.5, "z": 0.5},
    ]),

    # ── 2. Mid-size band: every lighting_role + all four sublane types ────
    "band_midsize": dict(width=10.0, depth=8.0, groups=[
        {"name": "Front PARs",  "cat": "PAR",   "role": "backbone", "color": C_PAR,
         "mounting": "hanging",  "layout": "row", "n": 4, "y": -3.0, "z": 3.0},
        {"name": "Back PARs",   "cat": "PAR",   "role": "backbone", "color": C_PAR2,
         "mounting": "hanging",  "layout": "row", "n": 4, "y": 3.0,  "z": 3.0},
        {"name": "Spots",       "cat": "SPOT",  "role": "movement", "color": C_SPOT,
         "mounting": "hanging",  "layout": "row", "n": 4, "y": 0.0,  "z": 3.4},
        {"name": "Moving Wash", "cat": "MWASH", "role": "accent",   "color": C_MWASH,
         "mounting": "hanging",  "layout": "row", "n": 2, "y": 3.2,  "z": 3.4},
        {"name": "LED Bars",    "cat": "GBAR",  "role": "accent",   "color": C_BAR,
         "mounting": "standing", "layout": "row", "n": 4, "y": 3.6,  "z": 0.2},
        {"name": "Blinders",    "cat": "SUN",   "role": "effect",   "color": C_BLIND,
         "mounting": "hanging",  "layout": "row", "n": 2, "y": 3.5,  "z": 2.2},
        {"name": "Matrix",      "cat": "MATRIX","role": "effect",   "color": C_FX,
         "mounting": "hanging",  "layout": "row", "n": 1, "y": 0.0,  "z": 4.0},
    ]),

    # ── 3. Festival mainstage: the rows-of-movers look; scale stressor ────
    "festival_mainstage": dict(width=16.0, depth=12.0, groups=[
        {"name": "Front Wash Truss", "cat": "MWASH", "role": "movement", "color": C_MWASH,
         "mounting": "hanging", "layout": "row", "n": 8,  "y": -4.0, "z": 7.0},
        {"name": "Mid Spot Truss",   "cat": "SPOT",  "role": "movement", "color": C_SPOT,
         "mounting": "hanging", "layout": "row", "n": 8,  "y": -1.0, "z": 7.5},
        {"name": "Back Beam Truss",  "cat": "BLADE", "role": "movement", "color": C_BLADE,
         "mounting": "hanging", "layout": "row", "n": 12, "y": 3.0,  "z": 7.0},
        {"name": "Floor Beams",      "cat": "BLADE", "role": "movement", "color": C_BLADE2,
         "mounting": "standing", "layout": "row", "n": 8, "y": 4.5,  "z": 0.3},
        {"name": "Blinders",         "cat": "SUN",   "role": "effect",   "color": C_BLIND,
         "mounting": "hanging", "layout": "row", "n": 8,  "y": 4.0,  "z": 5.0},
        {"name": "Matrix Panels",    "cat": "MATRIX","role": "effect",   "color": C_FX,
         "mounting": "hanging", "layout": "row", "n": 4,  "y": 4.5,  "z": 4.0},
        {"name": "Front Pixel Bars", "cat": "LBAR",  "role": "accent",   "color": C_BAR,
         "mounting": "standing", "layout": "row", "n": 4, "y": -5.0, "z": 0.2},
        {"name": "Side Tower L",     "cat": "SPOT",  "role": "movement", "color": C_SPOT,
         "mounting": "wall_left",  "layout": "tower", "x": -7.5, "y": 0.0, "z_list": [2.0, 4.0, 6.0, 8.0]},
        {"name": "Side Tower R",     "cat": "SPOT",  "role": "movement", "color": C_SPOT,
         "mounting": "wall_right", "layout": "tower", "x": 7.5,  "y": 0.0, "z_list": [2.0, 4.0, 6.0, 8.0]},
    ]),

    # ── 4. DJ / EDM: movement-centric, matrix/beam/strobe heavy ───────────
    "dj_edm": dict(width=10.0, depth=8.0, groups=[
        {"name": "Beam Array",  "cat": "BLADE", "role": "movement", "color": C_BLADE,
         "mounting": "hanging",  "layout": "row", "n": 8, "y": 0.0,  "z": 4.0},
        {"name": "Moving Wash", "cat": "MWASH", "role": "movement", "color": C_MWASH,
         "mounting": "hanging",  "layout": "row", "n": 4, "y": 3.0,  "z": 4.0},
        {"name": "Pixel Bars",  "cat": "LBAR",  "role": "accent",   "color": C_BAR,
         "mounting": "standing", "layout": "row", "n": 4, "y": -3.5, "z": 0.2},
        {"name": "Matrix",      "cat": "MATRIX","role": "effect",   "color": C_FX,
         "mounting": "hanging",  "layout": "row", "n": 2, "y": 3.5,  "z": 3.0},
        {"name": "Strobes",     "cat": "SUN",   "role": "effect",   "color": C_BLIND,
         "mounting": "hanging",  "layout": "row", "n": 2, "y": -3.5, "z": 2.5},
    ]),

    # ── 5. Theatre / static: zero movement (no-movement export path) ──────
    "theatre_static": dict(width=12.0, depth=8.0, groups=[
        {"name": "Front Wash",   "cat": "PAR",  "role": "backbone", "color": C_PAR,
         "mounting": "hanging",  "layout": "row", "n": 6, "y": -3.0, "z": 4.0},
        {"name": "Back Cyc Wash","cat": "WASH", "role": "ambient",  "color": C_WASH,
         "mounting": "hanging",  "layout": "row", "n": 6, "y": 3.0,  "z": 3.5},
        {"name": "Side Boom L",  "cat": "PAR",  "role": "accent",   "color": C_SPOT,
         "mounting": "wall_left",  "layout": "tower", "x": -5.5, "y": 0.0, "z_list": [1.5, 3.5]},
        {"name": "Side Boom R",  "cat": "PAR",  "role": "accent",   "color": C_SPOT,
         "mounting": "wall_right", "layout": "tower", "x": 5.5,  "y": 0.0, "z_list": [1.5, 3.5]},
    ]),
}


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    for name, spec in RIGS.items():
        cfg = build_rig(name, spec["width"], spec["depth"], spec["groups"])
        out = os.path.join(OUT_DIR, f"{name}.lms")
        cfg.save(out)
        n_fix = len(cfg.fixtures)
        n_grp = len(cfg.groups)
        n_uni = len(cfg.universes)
        print(f"  {name:22s} {n_fix:3d} fixtures  {n_grp} groups  "
              f"{n_uni} universe(s)  -> {os.path.relpath(out, PROJECT_ROOT)}")


if __name__ == "__main__":
    print("Generating demo rigs from custom_fixtures/ ...")
    main()
