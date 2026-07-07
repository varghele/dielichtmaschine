"""Generate the engineering-grid background tiles.

North Star motif: a fine engineering grid, rgba(141,146,153) at
0.04-0.07 alpha, 24-48px cells (design_handoff_lichtmaschine_app/
README.md, "Grid/Schema-Motive"). One 48px tile per theme with a 1px
line on the top and left edge; QSS repeats it across the main window
background.

Usage: python scripts/generate_grid_tiles.py  (re-run + commit when the
motif values change; the PNGs in resources/themes/ are checked in so
the build has no Pillow dependency.)
"""

import os

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "resources", "themes")

CELL = 48
STEEL = (141, 146, 153)
TILES = {
    "grid-dark.png": 13,    # ~0.05 alpha on #141416
    "grid-light.png": 18,   # ~0.07 alpha on #ECE9E2 (needs a bit more)
}


def main() -> None:
    for name, alpha in TILES.items():
        tile = Image.new("RGBA", (CELL, CELL), (0, 0, 0, 0))
        line = (*STEEL, alpha)
        for i in range(CELL):
            tile.putpixel((i, 0), line)
            tile.putpixel((0, i), line)
        path = os.path.join(OUT_DIR, name)
        tile.save(path)
        print("wrote", path)


if __name__ == "__main__":
    main()
