"""Golden screenshot for the Autogenerate dialog (reference screen 10).

Pins the rebuilt anatomy: the 44px display-caps header strip, the 420px
left configuration column (mono block captions over raised AUDIO and
STRUCTURE readout tiles, the SONG KEY combo, the COLOUR PALETTE chip row
with its swatches and colour-count segments), the accent GENERATE call
to action with the outlined CANCEL under it and the mono hint line; on
the right the GENERATION PARAMETERS grid of the seven real AutogenConfig
knobs and the "GENERATION INSPECTOR . LAST RUN" table whose five rows
(SECTION / ENVELOPE / PICKS (PER GROUP) / WHY) come from a realistic
GenerationReport, CHORUS 1 raised as the peak-energy row with its accent
PEAK chip.

Regenerate after intended changes with

    QLC_REGEN_GOLDENS=1 pytest tests/visual/test_autogen_dialog_golden.py

Goldens live under goldens/<platform>/ because the offscreen QPA has no
font database on Windows (fallback boxes); layout, geometry and colors
are what this pins, not glyph shapes.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from tests.unit.test_autogen_dialog import make_config, make_report
from tests.visual.harness import compare_to_golden


def test_autogen_dialog_golden(qapp):
    """Autogenerate dialog (reference screen 10) at the board's 1400px."""
    from gui.theme_manager import ThemeManager
    from gui.dialogs.autogen_dialog import AutogenDialog

    ThemeManager().apply(qapp, "dark")
    config = make_config()
    dialog = AutogenDialog(
        None,
        audio_path="/shows/audiofiles/neon_ruinen.wav",
        show=config.shows["Neon Ruinen"],
        report=make_report(),
    )
    try:
        dialog.setFixedSize(1400, 720)
        compare_to_golden(dialog.grab().toImage(), "autogen_dialog_dark")
    finally:
        dialog.deleteLater()
