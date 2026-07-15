"""Byte-identical export check for refactors of the fixture/export pipeline.

Exports every demo rig to .qxw with the full-featured VC options and writes
one SHA-256 line per rig. Run it before and after a refactor and diff the
two files; identical hashes prove the export pipeline's output is unchanged.

Determinism requirements (the script enforces what it can):
- PYTHONHASHSEED must be pinned in the environment (set iteration order
  leaks into fixture-definition load order): PYTHONHASHSEED=0 python ...
- The global RNG is re-seeded per rig here because one export path
  (preset_scenes_to_xml's bright-fixture sampling) draws from it unseeded.

Usage:
    PYTHONHASHSEED=0 python scripts/export_hash_check.py before.txt
    ... apply refactor ...
    PYTHONHASHSEED=0 python scripts/export_hash_check.py after.txt
    diff before.txt after.txt

Used as the Phase 0 acceptance gate of docs/gdtf-integration-plan.md.
"""
import hashlib
import os
import random
import sys

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, REPO_ROOT)

from config.models import Configuration                    # noqa: E402
from utils.create_workspace import create_qlc_workspace    # noqa: E402

RIGS = ["club_band", "band_midsize", "festival_mainstage", "dj_edm", "theatre_static"]
VC_OPTIONS = {
    "generate_vc": True,
    "group_controls": True,
    "scene_presets": True,
    "movement_presets": True,
    "show_buttons": True,
    "speed_dial": True,
    "master_presets": True,
    "dark_mode": False,
}
WORKSPACE_OUT = os.path.join(REPO_ROOT, "workspace.qxw")


def main(out_path):
    if os.environ.get("PYTHONHASHSEED") is None:
        print("WARNING: PYTHONHASHSEED is not set; hashes will not be "
              "comparable across runs. Re-run with PYTHONHASHSEED=0.")
    lines = []
    for rig in RIGS:
        config = Configuration.load(
            os.path.join(REPO_ROOT, "demos", "rigs", f"{rig}.yaml"))
        try:
            random.seed(0)
            create_qlc_workspace(config, VC_OPTIONS)
            with open(WORKSPACE_OUT, "rb") as f:
                digest = hashlib.sha256(f.read()).hexdigest()
        finally:
            if os.path.exists(WORKSPACE_OUT):
                os.remove(WORKSPACE_OUT)
        lines.append(f"{rig}  {digest}")
        print(lines[-1])
    with open(out_path, "w") as f:
        f.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    main(sys.argv[1])
