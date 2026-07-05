"""
FixturesTab — toolbar button visuals.

The +/-/duplicate toolbar buttons originally rendered blank (default
``QPushButton { padding: 6px 14px; }`` ate every pixel of glyph room
on a 31×31 fixed-size button). The first fix used
``density="compact"`` to tighten the padding, which made the glyphs
visible but left the icon buttons reading as a different widget
class from default text buttons in ConfigurationTab's toolbar.

Final contract: NO compact density, fixed width matching
``TOOLBAR_BTN_WIDTH`` (currently 40), height free so the theme's
natural ~36 px wins. Both tabs share the constant so future tweaks
only happen in one place.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_toolbar_buttons_match_default_button_styling(qapp, sample_configuration):
    from gui.theme_manager import ThemeManager
    from gui.tabs.configuration_tab import TOOLBAR_BTN_WIDTH
    from gui.tabs.fixtures_tab import FixturesTab

    ThemeManager().apply(qapp, "dark")
    tab = FixturesTab(sample_configuration, parent=None)
    try:
        # No compact-density: rely on the default
        # ``QPushButton { padding: 6px 14px; }`` rule so the icon
        # buttons render with the same proportions as text buttons.
        assert tab.add_btn.property("density") in (None, "")
        assert tab.remove_btn.property("density") in (None, "")
        assert tab.duplicate_btn.property("density") in (None, "")

        # Sanity: button glyphs are what we think they are.
        assert tab.add_btn.text() == "+"
        assert tab.remove_btn.text() == "-"
        assert tab.duplicate_btn.text() == "⎘"

        # All three icon buttons match the shared icon-button width.
        for btn in (tab.add_btn, tab.remove_btn, tab.duplicate_btn):
            assert btn.minimumWidth() == TOOLBAR_BTN_WIDTH
            assert btn.maximumWidth() == TOOLBAR_BTN_WIDTH
    finally:
        tab.deleteLater()


# ---------------------------------------------------------------------------
# DMX address conflict indicators
#
# Contract: fixtures whose (universe, address range) footprints overlap get
# the warning stylesheet + a tooltip naming the other fixture on their
# Universe/Address cell widgets, and the summary label shows the issue
# count. Resolving the conflict via the Address spinbox clears all of it
# (save_to_config re-lints; no full table rebuild involved).
# ---------------------------------------------------------------------------

def _overlapping_config(sample_configuration):
    """Add a second fixture overlapping the first (both 1-10 on universe 0)."""
    from config.models import Fixture, FixtureMode

    clash = Fixture(
        universe=0,
        address=5,
        manufacturer="TestMfr",
        model="TestModel",
        name="Test Fixture 2",
        group="TestGroup",
        current_mode="Standard",
        available_modes=[FixtureMode(name="Standard", channels=10)],
    )
    sample_configuration.fixtures.append(clash)
    sample_configuration.groups["TestGroup"].fixtures.append(clash)
    return sample_configuration


def test_conflicting_fixtures_are_flagged(qapp, sample_configuration):
    from gui.tabs.fixtures_tab import CONFLICT_CELL_QSS, FixturesTab

    config = _overlapping_config(sample_configuration)
    tab = FixturesTab(config, parent=None)
    try:
        assert tab.conflict_label.isVisibleTo(tab)
        assert "1 DMX addressing issue" in tab.conflict_label.text()

        for row, other_name in ((0, "Test Fixture 2"), (1, "Test Fixture 1")):
            for col in (0, 1):
                widget = tab.table.cellWidget(row, col)
                assert widget.styleSheet() == CONFLICT_CELL_QSS
                assert other_name in widget.toolTip()
                assert "channels 5-10" in widget.toolTip()
    finally:
        tab.deleteLater()


def test_resolving_conflict_clears_flags(qapp, sample_configuration):
    from gui.tabs.fixtures_tab import CONFLICT_CELL_QSS, FixturesTab

    config = _overlapping_config(sample_configuration)
    tab = FixturesTab(config, parent=None)
    try:
        # Move the second fixture clear of the first (1-10 -> 11-20).
        tab.table.cellWidget(1, 1).setValue(11)

        assert not tab.conflict_label.isVisibleTo(tab)
        for row in (0, 1):
            for col in (0, 1):
                widget = tab.table.cellWidget(row, col)
                assert widget.styleSheet() != CONFLICT_CELL_QSS
                assert widget.toolTip() == ""
    finally:
        tab.deleteLater()


def test_overflow_past_universe_end_is_flagged(qapp, sample_configuration):
    from gui.tabs.fixtures_tab import CONFLICT_CELL_QSS, FixturesTab

    tab = FixturesTab(sample_configuration, parent=None)
    try:
        # 10-channel fixture at 510 runs to 519, past the 512 limit.
        tab.table.cellWidget(0, 1).setValue(510)

        assert tab.conflict_label.isVisibleTo(tab)
        widget = tab.table.cellWidget(0, 1)
        assert widget.styleSheet() == CONFLICT_CELL_QSS
        assert "ends at channel 519" in widget.toolTip()
    finally:
        tab.deleteLater()
