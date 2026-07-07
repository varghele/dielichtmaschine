"""Chip: the North Star bordered micro-label.

Chips are the design system's small status/tag element: 1px border,
tracked mono caps, no fill unless accented (mockup examples: capability
tags, OVERLAP: XFADE, output status). Variants map to QSS rules on
``QLabel[role="chip-label"][variant=...]`` in the theme template:

- neutral: border + secondary text
- warning: warning color text + border (e.g. DMX addressing issues)
- error: destructive color
- accent: filled Glutorange with on-accent text
"""

from gui.typography import MicroLabel

VARIANTS = ("neutral", "warning", "error", "accent")


class Chip(MicroLabel):
    def __init__(self, text: str = "", variant: str = "neutral",
                 point_size: int = 8, parent=None):
        super().__init__(text, point_size=point_size, tracking_em=0.12,
                         parent=parent)
        self.setProperty("role", "chip-label")
        self.set_variant(variant)

    def set_variant(self, variant: str) -> None:
        if variant not in VARIANTS:
            variant = "neutral"
        self.setProperty("variant", variant)
        # Re-polish so the QSS [variant=...] selector re-evaluates when
        # the variant changes on a live widget.
        style = self.style()
        if style:
            style.unpolish(self)
            style.polish(self)
