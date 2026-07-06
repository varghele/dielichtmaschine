"""Spike-gate coverage diff: demo-rig .qxf definitions vs GDTF equivalents.

For every fixture the demo rigs use, parse both the bundled .qxf and the
Share-downloaded .gdtf (gdtf_fixtures/, not committed) through the same
canonical pipeline and compare what capability detection sees. Output is
a markdown table; findings live in docs/gdtf-coverage-note.md.

Run: python scripts/gdtf_coverage_diff.py
"""
import glob
import os
import sys

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, REPO_ROOT)

from utils.fixture_capabilities import detect_capabilities   # noqa: E402
from utils.fixture_library import parse_fixture_file         # noqa: E402

# (qxf filename, gdtf filename prefix or None, note)
PAIRS = [
    ("Martin-MAC-Aura.qxf", "Martin Professional@MAC Aura@", "exact"),
    ("Ayrton-MagicBlade-R.qxf", "Ayrton@MagicBlade R@", "exact"),
    ("Showtec-Sunstrip-Active.qxf", "Showtec@Sunstrip Active MKII@", "successor (MKII)"),
    ("Stairville-LED-Matrix-Blinder-5x5.qxf", "StairVille@LED Matrix Blinder 5x5@", "exact"),
    ("Varytec-Hero-Spot-60.qxf", "Varytec@Hero Spot 60@", "exact"),
    ("Varytec-Giga-Bar-5-LED-RGBW.qxf", "Varytec@Giga Bar 5@", "exact"),
    ("Stairville-Wild-Wash-Pro-648-RGB-LED.qxf", "StairVille@Wild Wash 132 RGB@", "different model (648 vs 132)"),
    ("Stairville-Retro-Flat-Par-18x12W-RGBW-.qxf", None, "no GDTF on Share"),
    ("Varghele-LED-BAR.qxf", None, "own fixture, .qxf only"),
]


def _caps_summary(defn, mode_name):
    caps = detect_capabilities(defn.root, mode_name)
    wheel = len(caps.color_wheel.entries) if caps.color_wheel else 0
    gobo = len(caps.gobo_wheel.entries) if caps.gobo_wheel else 0
    emitter = type(caps.emitter).__name__
    cells = getattr(caps.emitter, 'width', 1) * getattr(caps.emitter, 'height', 1)
    return {
        'chassis': caps.chassis.name,
        'move': (f"{caps.movement.pan_max_deg:.0f}/{caps.movement.tilt_max_deg:.0f}"
                 if caps.movement else "-"),
        'color': caps.color_mixing.mode.name if caps.color_mixing else "-",
        'wheel': wheel, 'gobo': gobo,
        'strobe': caps.strobe_channel is not None,
        'zoom': caps.zoom_channel is not None,
        'emitter': f"{emitter}({cells})" if emitter == 'CellArray' else emitter,
        'dims': "x".join(f"{v:.2f}" for v in caps.body_dims_m),
        'lumens': int(caps.lumens_estimate),
        'beam': f"{caps.beam.min_deg:.0f}-{caps.beam.max_deg:.0f}" if caps.beam else "-",
    }


def _richest_mode(defn):
    return max(defn.modes, key=lambda m: len(m.channels))


def main():
    print("| fixture | src | mode(ch) | chassis | pan/tilt | color | wheel | gobo "
          "| strobe | zoom | emitter | dims m | lumens | beam deg | models |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for qxf_name, gdtf_prefix, note in PAIRS:
        rows = []
        qxf = parse_fixture_file(os.path.join(REPO_ROOT, "custom_fixtures", qxf_name))
        rows.append((qxf, "qxf", "-"))
        if gdtf_prefix:
            hits = glob.glob(os.path.join(REPO_ROOT, "gdtf_fixtures", glob.escape(gdtf_prefix) + "*.gdtf"))
            if hits:
                gd = parse_fixture_file(hits[0])
                glbs = sum(1 for m in gd.gdtf.models.values() if m.glb_path())
                meshes = sum(1 for m in gd.gdtf.models.values() if m.archive_paths)
                rows.append((gd, "gdtf", f"{meshes} ({glbs} glb)"))
        label = f"{qxf.model.strip()} [{note}]"
        for defn, src, models in rows:
            mode = _richest_mode(defn)
            s = _caps_summary(defn, mode.name)
            print(f"| {label if src == 'qxf' else ''} | {src} "
                  f"| {mode.name}({len(mode.channels)}) | {s['chassis']} | {s['move']} "
                  f"| {s['color']} | {s['wheel']} | {s['gobo']} | {s['strobe']} | {s['zoom']} "
                  f"| {s['emitter']} | {s['dims']} | {s['lumens']} | {s['beam']} | {models} |")


if __name__ == "__main__":
    main()
