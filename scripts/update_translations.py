"""Refresh and (where possible) compile the UI translation catalogs.

Usage: python scripts/update_translations.py

1. Runs pylupdate6 (ships with PyQt6) over the GUI sources to merge
   new translatable strings into translations/*.ts (source of truth,
   committed to git).
2. Compiles each .ts to the .qm the app actually loads, if a Qt
   Linguist lrelease is on PATH (plain ``lrelease``, ``lrelease6`` or
   ``pyside6-lrelease``; ``pip install pyside6`` is the easiest way to
   get one). Without it the .ts edits still land, only the compile
   step is skipped - the app then keeps showing English.
"""

import glob
import os
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRANSLATIONS = os.path.join(ROOT, "translations")

# Every UI package is scanned whole (pylupdate6 reads a directory
# recursively), so a newly wrapped module never needs listing here.
# tests/unit/test_translations_catalog.py fails when a translate() call
# has no German entry in the .ts, which is the reminder to re-run this.
SOURCES = [
    os.path.join(ROOT, "gui"),
    os.path.join(ROOT, "timeline_ui"),
    os.path.join(ROOT, "visualizer"),
]


def normalise_catalog(ts_path: str) -> None:
    """Rewrite a refreshed .ts in the committed layout.

    pylupdate6 writes location paths relative to the .ts with the host's
    separator and its own indentation; the catalog was first generated
    on Windows (``..\\gui``, two-space XML indent). Normalising both
    keeps a refresh diff down to the messages that really changed,
    whichever OS ran it.
    """
    tree = ET.parse(ts_path)
    root = tree.getroot()
    for loc in root.iter("location"):
        name = loc.get("filename")
        if name:
            loc.set("filename", name.replace("/", "\\"))
    ET.indent(root, space="  ")
    body = ET.tostring(root, encoding="unicode")
    with open(ts_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write('<?xml version="1.0" encoding="utf-8"?>\n<!DOCTYPE TS>\n')
        fh.write(body)
        fh.write("\n")


def main() -> int:
    ts_files = sorted(glob.glob(os.path.join(TRANSLATIONS, "*.ts")))
    if not ts_files:
        print("no .ts files found")
        return 1

    # No --no-obsolete: vanished strings stay in the .ts marked obsolete
    # instead of being deleted, so translations are never destroyed by a
    # partial scan.
    pylupdate = shutil.which("pylupdate6")
    if pylupdate:
        cmd = [pylupdate, *SOURCES, "--ts", *ts_files]
        print("running:", " ".join(os.path.basename(c) for c in cmd[:1]),
              "...")
        subprocess.run(cmd, check=True)
        for ts in ts_files:
            normalise_catalog(ts)
    else:
        print("pylupdate6 not found (pip install PyQt6); skipping merge")

    lrelease = (shutil.which("lrelease") or shutil.which("lrelease6")
                or shutil.which("pyside6-lrelease"))
    if not lrelease:
        print("lrelease not found; .qm files NOT compiled. "
              "Install one via 'pip install pyside6' (pyside6-lrelease) "
              "or the Qt tools, then re-run.")
        return 0
    for ts in ts_files:
        qm = os.path.splitext(ts)[0] + ".qm"
        subprocess.run([lrelease, ts, "-qm", qm], check=True)
        print("compiled", os.path.basename(qm))
    return 0


if __name__ == "__main__":
    sys.exit(main())
