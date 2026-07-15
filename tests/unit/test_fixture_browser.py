"""Fixture browser dialog (gui/dialogs/fixture_browser_dialog.py) and the
multi-add flow in FixturesTab.

Contract:
- parse_qxf_summary extracts manufacturer/model/type/modes from a .qxf.
- The dialog filters on search text, shows a lazy details pane for the
  selected entry (modes + channel counts), tags bundled definitions,
  disables OK until something is selected, and returns (path, quantity).
- FixturesTab._add_fixtures_from_qxf adds N copies with unique names at
  consecutive free addresses — verified conflict-free with the DMX lint.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PAR_QXF = os.path.join(PROJECT_ROOT, "custom_fixtures",
                       "Stairville-Retro-Flat-Par-18x12W-RGBW-.qxf")
SPOT_QXF = os.path.join(PROJECT_ROOT, "custom_fixtures",
                        "Varytec-Hero-Spot-60.qxf")


def entries():
    return [
        {"manufacturer": "Stairville", "model": "Retro Flat Par",
         "path": PAR_QXF, "source": "bundled"},
        {"manufacturer": "Varytec", "model": "Hero Spot 60",
         "path": SPOT_QXF, "source": "library"},
    ]


class TestParseSummary:

    def test_reads_real_qxf(self):
        from gui.dialogs.fixture_browser_dialog import parse_qxf_summary
        summary = parse_qxf_summary(PAR_QXF)
        assert summary["manufacturer"] == "Stairville"
        assert summary["model"] == "Retro Flat Par 18x12W RGBW "
        assert ("8 Channel", 8) in summary["modes"]
        assert summary["type"]  # classified to something non-empty

    def test_invalid_file_raises(self, tmp_path):
        from gui.dialogs.fixture_browser_dialog import parse_qxf_summary
        bad = tmp_path / "broken.qxf"
        bad.write_text("this is not xml <")
        with pytest.raises(Exception):
            parse_qxf_summary(str(bad))


class TestBrowserDialog:

    @pytest.fixture
    def dialog(self, qapp):
        from gui.dialogs.fixture_browser_dialog import FixtureBrowserDialog
        dialog = FixtureBrowserDialog(entries(), parent=None)
        yield dialog
        dialog.deleteLater()

    def test_lists_sorted_with_bundled_tag(self, dialog):
        texts = [dialog.list_widget.item(i).text()
                 for i in range(dialog.list_widget.count())]
        assert len(texts) == 2
        assert texts[0].startswith("Stairville")
        assert "[bundled]" in texts[0]
        assert "[bundled]" not in texts[1]

    def test_search_filters(self, dialog):
        dialog.search_box.setText("hero")
        hidden = [dialog.list_widget.item(i).isHidden()
                  for i in range(dialog.list_widget.count())]
        assert hidden == [True, False]
        dialog.search_box.setText("")
        assert not any(dialog.list_widget.item(i).isHidden()
                       for i in range(dialog.list_widget.count()))

    def test_ok_disabled_until_selection(self, dialog):
        assert not dialog._ok_button.isEnabled()
        dialog.list_widget.setCurrentRow(0)
        assert dialog._ok_button.isEnabled()

    def test_details_pane_shows_modes(self, dialog):
        dialog.list_widget.setCurrentRow(0)
        text = dialog.details.toPlainText()
        assert "Stairville" in text
        assert "8 Channel" in text
        assert "8 ch" in text

    def test_selection_returns_path_and_quantity(self, dialog):
        dialog.list_widget.setCurrentRow(1)
        dialog.quantity_spin.setValue(6)
        assert dialog.selection() == (SPOT_QXF, 6)

    def test_no_selection_returns_none(self, dialog):
        assert dialog.selection() is None

    def test_unreadable_qxf_disables_ok(self, qapp, tmp_path):
        from gui.dialogs.fixture_browser_dialog import FixtureBrowserDialog
        bad = tmp_path / "broken.qxf"
        bad.write_text("not xml <")
        dialog = FixtureBrowserDialog(
            [{"manufacturer": "X", "model": "Broken",
              "path": str(bad), "source": "library"}],
            parent=None,
        )
        try:
            dialog.list_widget.setCurrentRow(0)
            assert not dialog._ok_button.isEnabled()
            assert "Could not read" in dialog.details.toPlainText()
        finally:
            dialog.deleteLater()


class TestMultiAdd:

    def test_adds_n_conflict_free_copies_with_unique_names(
            self, qapp, sample_configuration):
        from gui.tabs.fixtures_tab import FixturesTab
        from utils.dmx_conflicts import lint_dmx_addresses

        tab = FixturesTab(sample_configuration, parent=None)
        try:
            before = len(sample_configuration.fixtures)
            tab._add_fixtures_from_qxf(PAR_QXF, quantity=4)

            fixtures = sample_configuration.fixtures
            assert len(fixtures) == before + 4

            added = fixtures[before:]
            names = [f.name for f in added]
            assert len(set(names)) == 4  # all unique
            assert all(f.model == "Retro Flat Par 18x12W RGBW " for f in added)
            assert all(f.available_modes for f in added)

            # Consecutively patched, and the whole config lints clean.
            assert lint_dmx_addresses(fixtures).is_clean
        finally:
            tab.deleteLater()
