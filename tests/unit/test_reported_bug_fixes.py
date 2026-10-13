"""Regressions for bugs reported from real use (2026-07-08).

These are exactly the failures a visual/golden suite cannot see: the
widget renders perfectly and does nothing. The end-to-end harness in
tests/e2e covers the same paths as a user workflow; these pin the
individual root causes.
"""

import os
from unittest.mock import patch

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from config.models import (
    Configuration, Fixture, FixtureGroup, FixtureMode, Universe,
)


def _mover(name="MH 1"):
    return Fixture(universe=1, address=1, manufacturer="M", model="X",
                   name=name, group="G", current_mode="Std",
                   available_modes=[FixtureMode(name="Std", channels=8)],
                   type="MH")


class TestNewShowButton:
    """'+ New' silently did nothing: it was gated on shows_directory,
    which v1.0 demoted to an optional import/export hint."""

    def test_creates_a_show_without_a_shows_directory(self, qapp):
        from gui.tabs.structure_tab import StructureTab

        config = Configuration()
        assert config.shows_directory is None  # the normal state
        tab = StructureTab(config, parent=None)
        try:
            with patch("gui.tabs.structure_tab.QInputDialog.getText",
                       return_value=("My Show", True)):
                tab._create_new_show()
            assert "My Show" in config.songs
            assert config.songs["My Show"].parts, "needs a default part"
        finally:
            tab.deleteLater()

    def test_cancelling_the_dialog_creates_nothing(self, qapp):
        from gui.tabs.structure_tab import StructureTab

        config = Configuration()
        tab = StructureTab(config, parent=None)
        try:
            with patch("gui.tabs.structure_tab.QInputDialog.getText",
                       return_value=("", False)):
                tab._create_new_show()
            assert config.songs == {}
        finally:
            tab.deleteLater()


class TestTrussLength:
    """A straight truss had no way to set its length: the context menu
    offered rotate / label / height / layer / remove and nothing else."""

    @pytest.fixture
    def view(self, qapp):
        from gui.StageView import StageView
        stage_view = StageView()
        stage_view.set_config(Configuration())
        yield stage_view
        stage_view.deleteLater()

    def test_set_size_changes_the_footprint(self, view):
        truss = view.add_stage_element("truss-straight")
        item = view.stage_element_items[0]
        assert truss.width == 3.0

        item.set_size(8.0, truss.depth)
        assert view.config.stage_elements[0].width == 8.0

    def test_set_size_clamps_to_a_positive_footprint(self, view):
        view.add_stage_element("truss-straight")
        item = view.stage_element_items[0]
        item.set_size(0.0, -5.0)
        assert item.element.width >= 0.1
        assert item.element.depth >= 0.1

    def test_length_survives_the_yaml_round_trip(self, view, tmp_path):
        view.add_stage_element("truss-straight")
        view.stage_element_items[0].set_size(8.0, 0.3)
        path = str(tmp_path / "rig.yaml")
        view.config.save(path)
        loaded = Configuration.load(path)
        assert loaded.stage_elements[0].width == 8.0

    def test_straight_truss_prompts_for_length_only(self, view):
        """Depth is the truss profile; only length is asked for."""
        from PyQt6.QtWidgets import QInputDialog
        view.add_stage_element("truss-straight")
        item = view.stage_element_items[0]
        with patch.object(QInputDialog, "getDouble",
                          return_value=(9.0, True)) as prompt:
            assert item._edit_size() is True
        assert prompt.call_count == 1          # length only
        assert item.element.width == 9.0

    def test_non_truss_prompts_for_width_and_depth(self, view):
        from PyQt6.QtWidgets import QInputDialog
        view.add_stage_element("drum-riser")
        item = view.stage_element_items[0]
        with patch.object(QInputDialog, "getDouble",
                          side_effect=[(3.0, True), (2.5, True)]) as prompt:
            assert item._edit_size() is True
        assert prompt.call_count == 2
        assert (item.element.width, item.element.depth) == (3.0, 2.5)

    def test_cancelling_leaves_the_size_alone(self, view):
        from PyQt6.QtWidgets import QInputDialog
        view.add_stage_element("truss-straight")
        item = view.stage_element_items[0]
        with patch.object(QInputDialog, "getDouble", return_value=(0.0, False)):
            assert item._edit_size() is False
        assert item.element.width == 3.0


class TestOrientationReachable:
    """The inline orientation panel sits in the right inspector column,
    so right-click 'Set Orientation...' has to open the modal too or the
    user cannot set fixture rotation at all."""

    @pytest.fixture
    def tab(self, qapp):
        from gui.tabs.stage_tab import StageTab
        fixture = _mover()
        config = Configuration(
            fixtures=[fixture],
            groups={"G": FixtureGroup("G", [fixture], color="#cc6666")},
            universes={1: Universe(id=1, name="U1", output={})})
        stage_tab = StageTab(config, parent=None)
        stage_tab.update_from_config()
        yield stage_tab
        stage_tab.deleteLater()

    def test_right_click_opens_the_modal_dialog(self, tab):
        import gui.tabs.stage_tab as stage_tab_module

        opened = []

        class FakeDialog:
            def __init__(self, fixture_items, config, parent):
                opened.append(fixture_items)

            def exec(self):
                return 0  # Rejected: nothing applied

            def get_orientation_values(self):
                raise AssertionError("not accepted")

        item = tab.stage_view.fixtures["MH 1"]
        with patch.object(stage_tab_module, "OrientationDialog", FakeDialog):
            tab._on_set_orientation_requested([item])
        assert opened and opened[0] == [item]

    def test_accepted_dialog_writes_the_rotation_through(self, tab):
        import gui.tabs.stage_tab as stage_tab_module
        from PyQt6.QtWidgets import QDialog

        class FakeDialog:
            def __init__(self, *args):
                pass

            def exec(self):
                return QDialog.DialogCode.Accepted

            def get_orientation_values(self):
                return {"mounting": "standing", "yaw": 90.0, "pitch": 10.0,
                        "roll": 0.0, "z_height": 2.5, "apply_to_group": False}

        item = tab.stage_view.fixtures["MH 1"]
        with patch.object(stage_tab_module, "OrientationDialog", FakeDialog):
            tab._on_set_orientation_requested([item])

        fixture = tab.config.fixtures[0]
        assert fixture.yaw == 90.0
        assert fixture.pitch == 10.0
        assert fixture.mounting == "standing"

    def test_stage_view_still_emits_the_request(self, tab):
        """The right-click menu path stays connected to the handler.

        The emit runs the tab's real handler, which now opens a modal
        dialog: without patching it out, exec() blocks the test process
        forever (offscreen QPA still runs the event loop).
        """
        import gui.tabs.stage_tab as stage_tab_module

        opened = []

        class FakeDialog:
            def __init__(self, fixture_items, config, parent):
                opened.append(fixture_items)

            def exec(self):
                return 0

        item = tab.stage_view.fixtures["MH 1"]
        with patch.object(stage_tab_module, "OrientationDialog", FakeDialog):
            tab.stage_view.set_orientation_requested.emit([item])
        assert opened == [[item]], "the menu signal no longer reaches the tab"


class TestShowsDirectoryHeal:
    """A hand-copied project carries the other machine's absolute
    shows_directory verbatim; makedirs on it walked into a
    PermissionError on the Stellwerk kit (2026-07-17). Load heals a
    non-existent stored directory to the config's own directory; an
    existing one is deliberate and stays."""

    def _save(self, tmp_path, shows_directory):
        cfg = Configuration(fixtures=[], groups={}, universes={})
        cfg.shows_directory = shows_directory
        path = str(tmp_path / "proj" / "show.lms")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        cfg.save(path)
        return path

    def test_foreign_path_heals_to_the_config_dir(self, tmp_path):
        foreign = str(tmp_path / "no" / "such" / "machine" / "kit")
        path = self._save(tmp_path, foreign)
        loaded = Configuration.load(path)
        assert loaded.shows_directory == os.path.dirname(
            os.path.abspath(path))
        assert not os.path.exists(foreign), "healing must not mkdir"

    def test_existing_directory_is_kept(self, tmp_path):
        elsewhere = tmp_path / "legacy_shows"
        elsewhere.mkdir()
        path = self._save(tmp_path, str(elsewhere))
        loaded = Configuration.load(path)
        assert loaded.shows_directory == str(elsewhere)

    def test_unset_stays_unset(self, tmp_path):
        path = self._save(tmp_path, None)
        loaded = Configuration.load(path)
        assert not loaded.shows_directory
