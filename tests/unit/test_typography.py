"""Typography helpers: brand families, tracking, forced caps."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtGui import QFont


class TestFonts:
    def test_display_font_family_and_tracking(self, qapp):
        from gui.fonts import FONT_DISPLAY
        from gui.typography import display_font
        font = display_font(15, QFont.Weight.ExtraBold, tracking_em=0.08)
        assert font.family() == FONT_DISPLAY
        assert font.weight() == QFont.Weight.ExtraBold
        assert font.letterSpacingType() == QFont.SpacingType.PercentageSpacing
        assert font.letterSpacing() == pytest.approx(108.0)

    def test_mono_font_defaults_untracked(self, qapp):
        from gui.fonts import FONT_MONO
        from gui.typography import mono_font
        font = mono_font(10)
        assert font.family() == FONT_MONO
        assert font.letterSpacing() == 0.0  # untouched -> no tracking

    def test_micro_tracking(self, qapp):
        from gui.typography import mono_font
        font = mono_font(8, tracking_em=0.2)
        assert font.letterSpacing() == pytest.approx(120.0)


class TestCapsLabels:
    def test_display_label_uppercases(self, qapp):
        from gui.typography import DisplayLabel
        label = DisplayLabel("Die Lichtmaschine")
        assert label.text() == "DIE LICHTMASCHINE"

    def test_uppercase_survives_later_settext(self, qapp):
        from gui.typography import MicroLabel
        label = MicroLabel("initial")
        label.setText("Bühne frei")  # e.g. a translated string
        assert label.text() == "BÜHNE FREI"

    def test_role_properties_for_qss(self, qapp):
        from gui.typography import DisplayLabel, MicroLabel
        assert DisplayLabel("x").property("role") == "display"
        assert MicroLabel("x").property("role") == "micro"

    def test_empty_and_none_are_safe(self, qapp):
        from gui.typography import DisplayLabel
        label = DisplayLabel()
        label.setText(None)
        assert label.text() == ""
