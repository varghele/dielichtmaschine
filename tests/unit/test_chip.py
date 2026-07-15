"""Chip widget: variants, caps, QSS hooks, fixtures-tab usage."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class TestChip:
    def test_defaults(self, qapp):
        from gui.widgets.chip import Chip
        chip = Chip("dmx ok")
        assert chip.text() == "DMX OK"
        assert chip.property("role") == "chip-label"
        assert chip.property("variant") == "neutral"

    @pytest.mark.parametrize("variant", ["neutral", "warning", "error",
                                         "accent"])
    def test_variants(self, qapp, variant):
        from gui.widgets.chip import Chip
        assert Chip("x", variant=variant).property("variant") == variant

    def test_unknown_variant_falls_back_to_neutral(self, qapp):
        from gui.widgets.chip import Chip
        assert Chip("x", variant="sparkly").property("variant") == "neutral"

    def test_template_styles_every_variant(self):
        from gui.theme_tokens import render_theme
        qss = render_theme("dark")
        assert 'QLabel[role="chip-label"]' in qss
        for variant in ("warning", "error", "accent"):
            assert f'[variant="{variant}"]' in qss


class TestFixturesTabConflictChip:
    def test_conflict_label_is_a_warning_chip(self, qapp,
                                              sample_configuration):
        from gui.tabs.fixtures_tab import FixturesTab
        from gui.widgets.chip import Chip
        tab = FixturesTab(sample_configuration, parent=None)
        try:
            assert isinstance(tab.conflict_label, Chip)
            assert tab.conflict_label.property("variant") == "warning"
        finally:
            tab.deleteLater()
