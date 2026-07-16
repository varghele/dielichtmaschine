# tests/unit/test_preflight_dialog.py
"""gui/dialogs/preflight_dialog.py - the venue pre-flight screen
(design doc 7.2-7.5, v1.5b phase 5): generate/resume against the
persisted checklist, CORRECT auto-advance with the drive state
following, the INCORRECT fix-and-re-test loop (orientation dialog for
aim items, guidance for patch/colour items), CAPTURE writing
Fixture.calibration in the CONFIG and never into show blocks, the
completion stamps the export guard reads, and the create_workspace /
CLI guard hooks. Offscreen; the GL orientation dialog is stubbed."""

import os

import pytest

from config.models import (ColourBlock, Configuration, DimmerBlock,
                           Fixture, FixtureGroup, FixtureMode, LightBlock,
                           LightLane, MovementBlock, ShowPart, Song, Spot,
                           TimelineData, Universe)
from utils.morph.plan import config_hash
from utils.morph.preflight import (PreflightChecklist,
                                   derive_plan_from_config,
                                   plan_fingerprint)


def _fixture(name, address=1):
    return Fixture(universe=1, address=address, manufacturer="TestMfr",
                   model="TestModel", name=name, group="MOVERS",
                   current_mode="Standard",
                   available_modes=[FixtureMode(name="Standard",
                                                channels=10)],
                   type="MH")


def _config():
    """A standalone rig whose own lanes drive the derived plan: one
    mover group with dimmer + colour + movement streams and one spot.
    Expected items: flash, spot_verify, focus_capture, colour_sanity,
    scrub."""
    fixtures = [_fixture("m1", 1), _fixture("m2", 11)]
    lane = LightLane(name="Movers", fixture_targets=["MOVERS"],
                     light_blocks=[LightBlock(
                         0.0, 16.0, "x",
                         dimmer_blocks=[DimmerBlock(0.0, 16.0,
                                                    intensity=200.0)],
                         colour_blocks=[ColourBlock(0.0, 16.0, red=255.0)],
                         movement_blocks=[MovementBlock(
                             0.0, 16.0, target_spot_name="Centre")])])
    song = Song(name="S",
                parts=[ShowPart(name="All", color="#fff", signature="4/4",
                                bpm=120.0, num_bars=8,
                                transition="instant")],
                timeline_data=TimelineData(lanes=[lane]))
    config = Configuration(
        fixtures=fixtures,
        groups={"MOVERS": FixtureGroup(name="MOVERS", fixtures=fixtures)},
        universes={1: Universe(id=1, name="U1", output={})})
    config.spots = {"Centre": Spot(name="Centre", x=0.0, y=0.0, z=1.0)}
    config.songs = {"S": song}
    return config


def _dialog(config, config_path, regen=None, **kwargs):
    """A dialog whose stale-checklist prompt is answered without a
    modal; regen=None asserts the prompt is never reached."""
    from gui.dialogs.preflight_dialog import PreflightDialog

    class _Dlg(PreflightDialog):
        def _ask_regenerate(self):
            assert regen is not None, "unexpected regenerate prompt"
            return regen

    return _Dlg(config, config_path=config_path, **kwargs)


EXPECTED_KINDS = ["flash", "spot_verify", "focus_capture",
                  "colour_sanity", "scrub"]


class TestGenerateAndResume:
    def test_generates_in_design_order_and_stamps_hashes(self, qapp,
                                                         tmp_path):
        config = _config()
        path = str(tmp_path / "venue.lms")
        dialog = _dialog(config, path)
        assert [i.kind for i in dialog.checklist.items] == EXPECTED_KINDS
        assert not dialog.resumed
        assert dialog.checklist.plan_hash == plan_fingerprint(
            derive_plan_from_config(config))
        assert dialog.checklist.target_hash == config_hash(config)
        # Nothing saved yet - only completions write.
        assert not os.path.exists(dialog.checklist_path)
        dialog.done(0)

    def test_resumes_when_hashes_match(self, qapp, tmp_path):
        config = _config()
        path = str(tmp_path / "venue.lms")
        first = _dialog(config, path)
        first.mark_correct()                  # completes + saves
        first.done(0)
        second = _dialog(config, path)
        assert second.resumed
        assert second.checklist.items[0].done
        # The first pending item is pre-selected.
        assert second.current_item().kind == "spot_verify"
        second.done(0)

    def test_stale_checklist_offers_regenerate(self, qapp, tmp_path):
        config = _config()
        path = str(tmp_path / "venue.lms")
        first = _dialog(config, path)
        first.mark_correct()
        first.done(0)
        config.fixtures[0].x = 5.0            # the rig changed
        fresh = _dialog(config, path, regen=True)
        assert not fresh.resumed
        assert not any(i.done for i in fresh.checklist.items)
        fresh.done(0)
        kept = _dialog(config, path, regen=False)
        assert kept.resumed
        assert kept.checklist.items[0].done
        kept.done(0)

    def test_corrupt_checklist_regenerates_silently(self, qapp,
                                                    tmp_path):
        config = _config()
        path = str(tmp_path / "venue.lms")
        checklist_path = PreflightChecklist.default_path(path)
        with open(checklist_path, "w", encoding="utf-8") as f:
            f.write("{ not valid yaml: [")
        dialog = _dialog(config, path)
        assert [i.kind for i in dialog.checklist.items] == EXPECTED_KINDS
        dialog.done(0)


class TestCorrectFlow:
    def test_correct_marks_done_saves_and_advances(self, qapp, tmp_path):
        config = _config()
        dialog = _dialog(config, str(tmp_path / "venue.lms"))
        first = dialog.current_item()
        assert first.kind == "flash"
        dialog.drive_btn.setChecked(True)
        assert dialog.layer.drive_state == first.drive_state
        dialog.mark_correct()
        assert first.done and first.result == "ok" and first.completed_at
        assert os.path.exists(dialog.checklist_path)
        # Auto-advance: the next pending item is active and, since
        # DRIVE was on, its state is armed.
        second = dialog.current_item()
        assert second.kind == "spot_verify"
        assert dialog.drive_btn.isChecked()
        assert dialog.layer.drive_state == second.drive_state
        dialog.done(0)

    def test_switching_items_releases_the_drive_state(self, qapp,
                                                      tmp_path):
        config = _config()
        dialog = _dialog(config, str(tmp_path / "venue.lms"))
        dialog.drive_btn.setChecked(True)
        assert dialog.layer.armed
        dialog.select_item(3)
        assert not dialog.drive_btn.isChecked()
        assert not dialog.layer.armed
        dialog.done(0)

    def test_scrub_item_is_not_drivable(self, qapp, tmp_path):
        config = _config()
        dialog = _dialog(config, str(tmp_path / "venue.lms"))
        dialog.select_item(EXPECTED_KINDS.index("scrub"))
        assert not dialog.drive_btn.isEnabled()
        dialog.done(0)


class _StubOrientationDialog:
    """Stands in for the GL-backed OrientationDialog."""

    def __init__(self, values, accepted=True):
        self._values = values
        self._accepted = accepted
        self.adapters = None

    def exec(self):
        from PyQt6 import QtWidgets
        return QtWidgets.QDialog.DialogCode.Accepted if self._accepted \
            else QtWidgets.QDialog.DialogCode.Rejected

    def get_orientation_values(self):
        return self._values


class TestIncorrectFlow:
    def test_aim_item_opens_orientation_and_rearms_the_same_item(
            self, qapp, tmp_path):
        config = _config()
        dialog = _dialog(config, str(tmp_path / "venue.lms"))
        index = EXPECTED_KINDS.index("spot_verify")
        dialog.select_item(index)
        item = dialog.current_item()
        dialog.drive_btn.setChecked(True)
        values = {"mounting": "standing", "yaw": 10.0, "pitch": -90.0,
                  "roll": 0.0, "z_height": 1.2, "apply_to_group": False,
                  "invert_pan": True, "invert_tilt": False}
        stub = _StubOrientationDialog(values)
        opened = []
        dialog._make_orientation_dialog = \
            lambda adapters: opened.append(adapters) or stub
        dialog.mark_incorrect()
        assert len(opened) == 1
        assert [a.fixture_name for a in opened[0]] == ["m1", "m2"]
        # The fix landed in the CONFIG fixtures (7.1: geometry = truth).
        for fixture in config.fixtures:
            assert fixture.mounting == "standing"
            assert fixture.yaw == 10.0
            assert fixture.z == 1.2
            assert fixture.orientation_uses_group_default is False
            # The panel's per-fixture DMX invert flags ride along.
            assert fixture.invert_pan is True
            assert fixture.invert_tilt is False
        # The SAME item is still pending and re-armed for the re-test.
        assert not item.done
        assert dialog.current_item() is item
        assert dialog.drive_btn.isChecked()
        assert dialog.layer.drive_state == item.drive_state
        dialog.done(0)

    def test_rejected_orientation_changes_nothing(self, qapp, tmp_path):
        config = _config()
        dialog = _dialog(config, str(tmp_path / "venue.lms"))
        dialog.select_item(EXPECTED_KINDS.index("spot_verify"))
        stub = _StubOrientationDialog({}, accepted=False)
        dialog._make_orientation_dialog = lambda adapters: stub
        before = config_hash(config)
        dialog.mark_incorrect()
        assert config_hash(config) == before
        dialog.done(0)

    def test_incorrect_reopens_a_done_item(self, qapp, tmp_path):
        config = _config()
        dialog = _dialog(config, str(tmp_path / "venue.lms"))
        item = dialog.current_item()             # flash
        dialog.mark_correct()
        assert item.done
        guided = []
        dialog._show_guidance = guided.append
        dialog.select_item(0)
        dialog.mark_incorrect()
        assert not item.done and item.result == ""
        assert guided == [item]
        dialog.done(0)

    def test_patch_and_colour_items_get_guidance(self, qapp, tmp_path):
        config = _config()
        dialog = _dialog(config, str(tmp_path / "venue.lms"))
        guided = []
        dialog._show_guidance = guided.append
        for kind in ("flash", "colour_sanity"):
            dialog.select_item(EXPECTED_KINDS.index(kind))
            dialog.mark_incorrect()
        assert [i.kind for i in guided] == ["flash", "colour_sanity"]
        dialog.done(0)


class TestCapture:
    def test_capture_writes_calibration_and_never_show_blocks(
            self, qapp, tmp_path):
        config = _config()
        dialog = _dialog(config, str(tmp_path / "venue.lms"))
        index = EXPECTED_KINDS.index("focus_capture")
        dialog.select_item(index)
        item = dialog.current_item()
        dialog.drive_btn.setChecked(True)
        dialog.focus_slider.setValue(132)
        dialog.zoom_slider.setValue(90)
        block = config.songs["S"].timeline_data.lanes[0].light_blocks[0]
        dialog.capture()
        for fixture in config.fixtures:
            assert fixture.calibration == {"focus": 132, "zoom": 90}
        # The capture rule (7.1): show blocks stay untouched.
        assert not hasattr(block.movement_blocks[0], "focus")
        assert block.dimmer_blocks[0].intensity == 200.0
        assert item.done and item.result == "fixed" and item.completed_at
        dialog.done(0)

    def test_capture_only_applies_to_capture_items(self, qapp, tmp_path):
        config = _config()
        dialog = _dialog(config, str(tmp_path / "venue.lms"))
        dialog.capture()                          # current item is flash
        assert not dialog.checklist.items[0].done
        assert config.fixtures[0].calibration == {}
        dialog.done(0)


class TestCompletion:
    def _complete_all(self, dialog):
        while dialog.checklist.pending():
            item = dialog.current_item()
            if item.kind == "focus_capture":
                dialog.capture()
            else:
                dialog.mark_correct()

    def test_last_item_stamps_completion_and_config_hash(self, qapp,
                                                         tmp_path):
        config = _config()
        dialog = _dialog(config, str(tmp_path / "venue.lms"))
        self._complete_all(dialog)
        assert dialog.checklist.complete
        assert dialog.checklist.completed_at
        # The hash is of the config AS COMPLETED - captures included.
        assert dialog.checklist.completed_target_hash == \
            config_hash(config)
        saved = PreflightChecklist.load(dialog.checklist_path)
        assert saved.completed_at == dialog.checklist.completed_at
        assert saved.completed_target_hash == \
            dialog.checklist.completed_target_hash
        dialog.done(0)

    def test_completed_checklist_clears_the_export_guard(self, qapp,
                                                         tmp_path):
        from utils.morph.preflight import export_guard_message
        config = _config()
        dialog = _dialog(config, str(tmp_path / "venue.lms"))
        checklist_path = dialog.checklist_path
        dialog.mark_correct()                     # incomplete
        assert "INCOMPLETE" in export_guard_message(
            checklist_path, config_hash(config))
        self._complete_all(dialog)
        assert export_guard_message(
            checklist_path, config_hash(config)) is None
        # A calibration edit after completion makes it stale again.
        config.fixtures[0].calibration["focus"] = 7
        assert "changed AFTER" in export_guard_message(
            checklist_path, config_hash(config))
        dialog.done(0)


class TestExportGuardHooks:
    """The gui.gui.create_workspace hook (unbound-method-on-stub, the
    established MainWindow test pattern) and the headless CLI print."""

    def _stub(self, config, config_path):
        import types
        return types.SimpleNamespace(config=config,
                                     config_path=config_path)

    def test_no_checklist_means_no_warning(self, qapp, tmp_path):
        from gui.gui import MainWindow
        config = _config()
        stub = self._stub(config, str(tmp_path / "venue.lms"))
        assert MainWindow._preflight_export_warning(stub) is None

    def test_incomplete_checklist_warns(self, qapp, tmp_path):
        from gui.gui import MainWindow
        config = _config()
        path = str(tmp_path / "venue.lms")
        dialog = _dialog(config, path)
        dialog.mark_correct()                     # saves, incomplete
        dialog.done(0)
        message = MainWindow._preflight_export_warning(
            self._stub(config, path))
        assert message and "INCOMPLETE" in message

    def test_unsaved_config_never_warns(self, qapp):
        from gui.gui import MainWindow
        assert MainWindow._preflight_export_warning(
            self._stub(_config(), "")) is None

    def test_corrupt_checklist_never_breaks_the_export(self, qapp,
                                                       tmp_path):
        from gui.gui import MainWindow
        path = str(tmp_path / "venue.lms")
        checklist_path = PreflightChecklist.default_path(path)
        with open(checklist_path, "w", encoding="utf-8") as f:
            f.write("{ not valid yaml: [")
        assert MainWindow._preflight_export_warning(
            self._stub(_config(), path)) is None


class TestWizardHandoff:
    def test_commit_page_enables_the_preflight_button(
            self, qapp, tmp_path):
        """The wizard's Run Pre-Flight Now... unlocks with the commit
        (nothing to verify on the venue rig before it)."""
        from gui.dialogs.morph_wizard import MorphWizard
        source = _config()
        target = _config()
        target.songs = {}
        wizard = MorphWizard(source, source_path="master.lms")
        wizard.set_target_config(target, str(tmp_path / "venue.lms"))
        assert not wizard.preflight_btn.isEnabled()
        lane = source.songs["S"].timeline_data.lanes[0]
        wizard.patchbay.add_edge(lane.lane_id, "dimmer", "MOVERS")
        assert wizard.commit() is True
        assert wizard.preflight_btn.isEnabled()
