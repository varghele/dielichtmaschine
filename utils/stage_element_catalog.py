"""Catalog of placeable stage elements (North Star stageplot set).

Every entry maps a StageElement.kind onto its SVG symbol in
resources/stageplot/<kind>.svg plus a display label, a real-world
default footprint in meters, and a palette category. The GUI palette,
the stage-plan canvas, and the printable plot all consume this one
table, so adding an element is one line (plus the SVG, which the
handoff already ships for all of these).

Trusses are listed as STATIC shapes: placing one draws it on the plan
but fixtures do not dock to it yet (that needs the truss data model,
tracked in ROADMAP/plan docs).
"""

from dataclasses import dataclass
import os

from utils.paths import get_project_root

CATEGORY_STAGE = "Stage elements"
CATEGORY_TRUSS = "Trusses (static)"


@dataclass(frozen=True)
class ElementSpec:
    kind: str
    label: str
    width: float    # default footprint, meters
    depth: float
    category: str


_SPECS = [
    # Stage elements
    ElementSpec("drum-riser", "Drum riser", 2.0, 2.0, CATEGORY_STAGE),
    ElementSpec("riser", "Riser", 2.0, 1.0, CATEGORY_STAGE),
    ElementSpec("wedge", "Wedge monitor", 0.6, 0.5, CATEGORY_STAGE),
    ElementSpec("amp", "Amp", 0.7, 0.5, CATEGORY_STAGE),
    ElementSpec("cab-4x12", "4x12 cab", 0.8, 0.4, CATEGORY_STAGE),
    ElementSpec("mic-stand", "Mic stand", 0.4, 0.4, CATEGORY_STAGE),
    ElementSpec("mic-boom", "Mic boom", 0.6, 0.6, CATEGORY_STAGE),
    ElementSpec("keys", "Keys", 1.4, 0.5, CATEGORY_STAGE),
    ElementSpec("di-box", "DI box", 0.3, 0.3, CATEGORY_STAGE),
    ElementSpec("distro", "Power distro", 0.6, 0.6, CATEGORY_STAGE),
    ElementSpec("foh", "FOH desk", 2.0, 1.0, CATEGORY_STAGE),
    ElementSpec("backdrop", "Backdrop", 6.0, 0.3, CATEGORY_STAGE),
    ElementSpec("stairs", "Stairs", 1.0, 0.8, CATEGORY_STAGE),
    ElementSpec("hazer", "Hazer", 0.5, 0.4, CATEGORY_STAGE),
    # Truss shapes (static placement only, no docking yet)
    ElementSpec("truss-straight", "Truss straight", 3.0, 0.3, CATEGORY_TRUSS),
    ElementSpec("truss-tower", "Truss tower", 0.5, 0.5, CATEGORY_TRUSS),
    ElementSpec("truss-corner", "Truss corner", 1.0, 1.0, CATEGORY_TRUSS),
    ElementSpec("truss-circle", "Truss circle", 3.0, 3.0, CATEGORY_TRUSS),
]

CATALOG = {spec.kind: spec for spec in _SPECS}
CATEGORIES = (CATEGORY_STAGE, CATEGORY_TRUSS)


def specs_for_category(category: str):
    return [spec for spec in _SPECS if spec.category == category]


def symbol_path(kind: str) -> str:
    return os.path.join(get_project_root(), "resources", "stageplot",
                        f"{kind}.svg")


def make_element(kind: str, x: float = 0.0, y: float = 0.0):
    """A StageElement with the catalog's default footprint."""
    from config.models import StageElement
    spec = CATALOG[kind]
    return StageElement(kind=kind, x=x, y=y, width=spec.width,
                        depth=spec.depth)
