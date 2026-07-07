"""Golden for static stage elements on the 2D plan (5a first step)."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from config.models import Configuration, StageElement
from tests.visual.harness import compare_to_golden


def test_stage_elements_golden(qapp):
    """Elements render as steel line symbols at real footprint: riser
    with label, rotated truss, wedge pair - under the grid + AUDIENCE
    chrome of the plan."""
    from gui.theme_manager import ThemeManager
    from gui.StageView import StageView

    ThemeManager().apply(qapp, "dark")
    config = Configuration(stage_width=8.0, stage_height=6.0)
    config.stage_elements = [
        StageElement(kind="drum-riser", x=0.0, y=1.5, width=2.0, depth=2.0,
                     label="Drums"),
        StageElement(kind="truss-straight", x=0.0, y=-2.0, rotation=0.0,
                     width=3.0, depth=0.3),
        StageElement(kind="wedge", x=-2.0, y=-0.5, width=0.6, depth=0.5,
                     rotation=180.0),
        StageElement(kind="wedge", x=2.0, y=-0.5, width=0.6, depth=0.5,
                     rotation=180.0),
    ]
    view = StageView()
    view.set_config(config)
    try:
        view.setFixedSize(720, 560)
        view.fit_to_stage()
        compare_to_golden(view.grab().toImage(), "stage_elements_dark")
    finally:
        view.deleteLater()
