# gui/dialogs/preflight_dialog.py
"""The venue pre-flight screen (design doc docs/design-show-morphing.md
7.2-7.5, v1.5b phase 5) - the operator clicks through the generated
checklist while the app drives the rig into testable states.

Opened from Tools > Venue Pre-Flight... (the current config, checklist
derived from its own lane routing) and from the morph wizard's commit
page (config B with the real morph plan). The checklist persists next
to the config (*.preflight.yaml) and resumes when the plan and config
hashes still match; a mismatch offers regeneration.

One item is active at a time. DRIVE arms the rig-driving layer
(utils/artnet/preflight_layer.py) on the shared arbiter's exclusive
playback slot; CORRECT marks done and auto-advances; INCORRECT opens
the remediation for the item kind (orientation dialog for aim items, a
guidance box pointing at the fixing tab for patch/colour items) and
re-arms the SAME item - the fix-and-re-test loop is mandatory (7.2).
CAPTURE items hold the aim while focus/zoom sliders trim live; the
captured values land in each fixture's ``Fixture.calibration`` in the
CONFIG, never in show blocks (the 7.1 capture rule). When the last
item completes, the checklist stamps ``completed_at`` and the config
content hash, which the export guard (7.5) reads.
"""

from __future__ import annotations

import datetime
import os

from PyQt6 import QtWidgets
from PyQt6.QtCore import Qt

from utils.morph.plan import config_hash
from utils.morph.preflight import (PreflightChecklist, derive_plan_from_config,
                                   generate_checklist, plan_fingerprint)
from utils.artnet.preflight_layer import (PreflightRigLayer, RGB_STEP_LABELS,
                                          SPECIAL_STEP_COUNT)

#: item kinds whose INCORRECT branch opens the orientation dialog for
#: the group's fixtures (aim/orientation problems); everything else
#: verify-shaped gets a guidance box naming the tab that fixes it.
ORIENTATION_KINDS = ("spot_verify",)

GUIDANCE = {
    "flash": ("A silent fixture is a patch or address error. Fix the "
              "fixture's universe/address (and DMX mode) in the Setup "
              "section's fixture list, then re-test this item."),
    "colour_sanity": ("Swapped colours mean wrong channel order - "
                      "usually a different DMX mode than the rig list "
                      "claimed. Fix the fixture's mode in the Setup "
                      "section, then re-test this item."),
    "special_verify": ("Mismatched gobo/prism states usually mean a "
                       "different fixture mode or definition. Check the "
                       "fixture's mode in the Setup section, then "
                       "re-test this item."),
    "scrub": ("Fix the offending looks on the Shows timeline (or the "
              "geometry in the Stage tab), then re-run the scrub."),
}


def _now_iso() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


class _OrientationTarget:
    """Adapter presenting a config Fixture to the OrientationPanel,
    which expects the StageView's FixtureItem attribute names."""

    def __init__(self, fixture, group=None):
        mounting, yaw, pitch, roll = \
            fixture.get_effective_orientation(group)
        self.fixture = fixture
        self.fixture_name = fixture.name
        self.fixture_type = fixture.type
        self.manufacturer = fixture.manufacturer
        self.model = fixture.model
        self.mounting = mounting
        self.rotation_angle = yaw
        self.pitch = pitch
        self.roll = roll
        self.z_height = fixture.get_effective_z(group)


class PreflightDialog(QtWidgets.QDialog):
    """Modal checklist runner over the tested model in
    utils/morph/preflight.py.

    ``arbiter_provider`` is a zero-arg callable returning the shared
    OutputArbiter (MainWindow.output_arbiter); None means the dialog
    runs data-only (tests, no-output sessions). ``plan`` and
    ``source_config`` come from the morph wizard; omitted, the plan is
    derived from the config's own lanes (the Tools menu path).
    """

    def __init__(self, config, config_path: str = "", plan=None,
                 source_config=None, arbiter_provider=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Venue Pre-Flight")
        self.setModal(True)
        self.setMinimumSize(720, 480)

        self.config = config
        self.config_path = config_path or ""
        self.plan = plan if plan is not None \
            else derive_plan_from_config(config)
        self.source_config = source_config \
            if source_config is not None else config
        self._arbiter_provider = arbiter_provider

        self._plan_hash = plan_fingerprint(self.plan)
        self._target_hash = config_hash(config)
        self.checklist_path = PreflightChecklist.default_path(
            self.config_path) if self.config_path else ""
        self.resumed = False
        self.checklist = self._load_or_generate()

        # The rig-driving layer: the config's own channel maps (the
        # playback slot is not map-forwarded by the arbiter). A config
        # whose definitions cannot be found drives nothing - the
        # checklist still runs data-only.
        try:
            from utils.artnet.dmx_manager import DMXManager
            maps = DMXManager.build_fixture_maps(config)
        except Exception:
            maps = {}
        self.layer = PreflightRigLayer(
            config_provider=lambda: self.config, fixture_maps=maps)

        self._build_ui()
        self._refresh_list()
        self._select_first_pending()

    # ── checklist load/generate ──────────────────────────────────────────

    def _generate(self) -> PreflightChecklist:
        checklist = generate_checklist(self.source_config, self.plan,
                                       self.config)
        checklist.plan_hash = self._plan_hash
        checklist.target_hash = self._target_hash
        return checklist

    def _load_or_generate(self) -> PreflightChecklist:
        """Resume the saved checklist when plan and config hashes still
        match; a mismatch offers regeneration (design doc 7.4: venue
        setup gets interrupted, the checklist resumes)."""
        if not self.checklist_path \
                or not os.path.exists(self.checklist_path):
            return self._generate()
        try:
            existing = PreflightChecklist.load(self.checklist_path)
        except Exception:
            return self._generate()
        if not existing.items:
            return self._generate()
        if existing.plan_hash == self._plan_hash \
                and existing.target_hash == self._target_hash:
            self.resumed = True
            return existing
        if self._ask_regenerate():
            return self._generate()
        self.resumed = True
        return existing

    def _ask_regenerate(self) -> bool:
        """The stale-checklist prompt; split out so tests decide
        without a modal. True = throw the old one away."""
        answer = QtWidgets.QMessageBox.question(
            self, "Venue Pre-Flight",
            "A saved checklist exists for this config, but the plan or "
            "the config changed since it was written.\n\nRegenerate the "
            "checklist (recommended), or resume the old one anyway?",
            QtWidgets.QMessageBox.StandardButton.Yes
            | QtWidgets.QMessageBox.StandardButton.No)
        return answer == QtWidgets.QMessageBox.StandardButton.Yes

    # ── UI ────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(8)

        self.progress_label = QtWidgets.QLabel("")
        layout.addWidget(self.progress_label)

        body = QtWidgets.QHBoxLayout()
        self.item_list = QtWidgets.QListWidget()
        self.item_list.currentRowChanged.connect(self._on_row_changed)
        body.addWidget(self.item_list, 1)

        detail = QtWidgets.QVBoxLayout()
        self.title_label = QtWidgets.QLabel("")
        self.title_label.setWordWrap(True)
        detail.addWidget(self.title_label)
        self.instruction_label = QtWidgets.QLabel("")
        self.instruction_label.setWordWrap(True)
        self.instruction_label.setAlignment(Qt.AlignmentFlag.AlignTop)
        detail.addWidget(self.instruction_label, 1)

        # DRIVE row.
        drive_row = QtWidgets.QHBoxLayout()
        self.drive_btn = QtWidgets.QPushButton("DRIVE")
        self.drive_btn.setCheckable(True)
        self.drive_btn.setToolTip(
            "Drive the rig into this item's test state (exclusive with "
            "timeline/Auto playback)")
        self.drive_btn.toggled.connect(self._on_drive_toggled)
        drive_row.addWidget(self.drive_btn)
        self.step_btn = QtWidgets.QPushButton("NEXT STEP")
        self.step_btn.clicked.connect(self._on_next_step)
        drive_row.addWidget(self.step_btn)
        self.step_label = QtWidgets.QLabel("")
        drive_row.addWidget(self.step_label)
        drive_row.addStretch(1)
        detail.addLayout(drive_row)

        # CAPTURE row (focus_capture items only).
        capture_row = QtWidgets.QHBoxLayout()
        capture_row.addWidget(QtWidgets.QLabel("Focus"))
        self.focus_slider = QtWidgets.QSlider(Qt.Orientation.Horizontal)
        self.focus_slider.setRange(0, 255)
        self.focus_slider.valueChanged.connect(self._on_capture_levels)
        capture_row.addWidget(self.focus_slider, 1)
        capture_row.addWidget(QtWidgets.QLabel("Zoom"))
        self.zoom_slider = QtWidgets.QSlider(Qt.Orientation.Horizontal)
        self.zoom_slider.setRange(0, 255)
        self.zoom_slider.valueChanged.connect(self._on_capture_levels)
        capture_row.addWidget(self.zoom_slider, 1)
        self.capture_btn = QtWidgets.QPushButton("CAPTURE")
        self.capture_btn.setToolTip(
            "Store the trimmed focus/zoom into the fixtures' "
            "calibration (the config, never the show)")
        self.capture_btn.clicked.connect(self.capture)
        capture_row.addWidget(self.capture_btn)
        self._capture_widgets = [
            capture_row.itemAt(i).widget()
            for i in range(capture_row.count())
            if capture_row.itemAt(i).widget() is not None]
        detail.addLayout(capture_row)

        # Verdict row.
        verdict_row = QtWidgets.QHBoxLayout()
        self.correct_btn = QtWidgets.QPushButton("CORRECT")
        self.correct_btn.clicked.connect(self.mark_correct)
        verdict_row.addWidget(self.correct_btn)
        self.incorrect_btn = QtWidgets.QPushButton("INCORRECT")
        self.incorrect_btn.clicked.connect(self.mark_incorrect)
        verdict_row.addWidget(self.incorrect_btn)
        verdict_row.addStretch(1)
        detail.addLayout(verdict_row)

        body.addLayout(detail, 2)
        layout.addLayout(body, 1)

        bottom = QtWidgets.QHBoxLayout()
        self.status_label = QtWidgets.QLabel("")
        bottom.addWidget(self.status_label, 1)
        close_btn = QtWidgets.QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        bottom.addWidget(close_btn)
        layout.addLayout(bottom)

    # ── list/selection ────────────────────────────────────────────────────

    def _refresh_list(self) -> None:
        current = self.item_list.currentRow()
        self.item_list.blockSignals(True)
        self.item_list.clear()
        for index, item in enumerate(self.checklist.items):
            marker = "[DONE]" if item.done else "[    ]"
            self.item_list.addItem(f"{marker} {index + 1:02d} · "
                                   f"{item.title}")
        if 0 <= current < self.item_list.count():
            # Same row, no state change: keep the drive state armed
            # (signals stay blocked; callers resync the detail pane).
            self.item_list.setCurrentRow(current)
        self.item_list.blockSignals(False)
        done = sum(1 for i in self.checklist.items if i.done)
        total = len(self.checklist.items)
        pieces = [f"{done} / {total} items done"]
        if self.resumed:
            pieces.append("resumed")
        if self.checklist.completed_at:
            pieces.append(f"completed {self.checklist.completed_at}")
        self.progress_label.setText(" · ".join(pieces))

    def _select_first_pending(self) -> None:
        pending = self.checklist.pending()
        if pending:
            index = self.checklist.items.index(pending[0])
        else:
            index = 0 if self.checklist.items else -1
        if index >= 0:
            self.item_list.setCurrentRow(index)
        self._sync_detail()

    def current_item(self):
        row = self.item_list.currentRow()
        if 0 <= row < len(self.checklist.items):
            return self.checklist.items[row]
        return None

    def select_item(self, index: int) -> None:
        self.item_list.setCurrentRow(index)

    def _on_row_changed(self, _row: int) -> None:
        # Switching items releases the previous drive state - one item
        # active at a time.
        if self.drive_btn.isChecked():
            self.drive_btn.setChecked(False)
        self._sync_detail()

    def _sync_detail(self) -> None:
        item = self.current_item()
        if item is None:
            for widget in (self.drive_btn, self.step_btn,
                           self.correct_btn, self.incorrect_btn):
                widget.setEnabled(False)
            for widget in self._capture_widgets:
                widget.setVisible(False)
            self.title_label.setText("No items.")
            self.instruction_label.setText("")
            return
        self.title_label.setText(f"<b>{item.title}</b>")
        self.instruction_label.setText(item.instruction)
        drivable = item.kind != "scrub"
        self.drive_btn.setEnabled(drivable)
        self.step_btn.setVisible(item.kind in ("colour_sanity",
                                               "special_verify"))
        self.step_btn.setEnabled(drivable)
        self.step_label.setVisible(self.step_btn.isVisible())
        self._sync_step_label()
        is_capture = item.kind == "focus_capture"
        for widget in self._capture_widgets:
            widget.setVisible(is_capture)
        self.correct_btn.setVisible(not is_capture)
        self.correct_btn.setEnabled(True)
        self.incorrect_btn.setEnabled(True)
        if is_capture:
            calibration = self._group_calibration(item.group)
            self.focus_slider.setValue(
                int(calibration.get("focus", 128)))
            self.zoom_slider.setValue(int(calibration.get("zoom", 128)))

    def _group_calibration(self, group_name: str) -> dict:
        group = (getattr(self.config, "groups", {}) or {}).get(group_name)
        for fixture in (getattr(group, "fixtures", None) or []):
            if fixture.calibration:
                return fixture.calibration
        return {}

    def _sync_step_label(self) -> None:
        item = self.current_item()
        if item is None:
            return
        if item.kind == "colour_sanity":
            self.step_label.setText(RGB_STEP_LABELS[self.layer.rgb_step])
        elif item.kind == "special_verify":
            self.step_label.setText(
                f"Gobo step {self.layer.special_step + 1} / "
                f"{SPECIAL_STEP_COUNT}")

    # ── driving ───────────────────────────────────────────────────────────

    def _on_drive_toggled(self, on: bool) -> None:
        if not on:
            self.layer.disarm()
            self.status_label.setText("")
            return
        item = self.current_item()
        if item is None or item.kind == "scrub":
            self.drive_btn.setChecked(False)
            return
        if self._arbiter_provider is not None:
            try:
                arbiter = self._arbiter_provider()
            except Exception:
                arbiter = None
            if arbiter is not None and not self.layer.attach(arbiter):
                self.status_label.setText(
                    "Output is busy: stop timeline/Auto playback first.")
                self.drive_btn.setChecked(False)
                return
        self._arm_current()

    def _arm_current(self) -> None:
        item = self.current_item()
        if item is None:
            return
        self.layer.arm(item.drive_state)
        if item.kind == "focus_capture":
            self._on_capture_levels()
        self._sync_step_label()

    def _on_next_step(self) -> None:
        item = self.current_item()
        if item is None:
            return
        if item.kind == "colour_sanity":
            self.layer.set_rgb_step(self.layer.rgb_step + 1)
        elif item.kind == "special_verify":
            self.layer.set_special_step(self.layer.special_step + 1)
        self._sync_step_label()

    def _on_capture_levels(self, _value: int = 0) -> None:
        item = self.current_item()
        if item is not None and item.kind == "focus_capture" \
                and self.layer.armed:
            self.layer.set_capture_levels(self.focus_slider.value(),
                                          self.zoom_slider.value())

    # ── verdicts ──────────────────────────────────────────────────────────

    def mark_correct(self) -> None:
        item = self.current_item()
        if item is None:
            return
        self.checklist.mark_done(item.item_id, result="ok",
                                 stamp=_now_iso())
        self._after_completion()

    def mark_incorrect(self) -> None:
        """The remediation branch: fix, then re-test the SAME item
        (design doc 7.2 - a checklist that cannot be re-run after a
        fix is a list of regrets)."""
        item = self.current_item()
        if item is None:
            return
        if item.done:
            self.checklist.reopen(item.item_id)
            self._save()
        if item.kind in ORIENTATION_KINDS:
            self._open_orientation_remediation(item)
        else:
            self._show_guidance(item)
        self._refresh_list()
        # Re-arm the same item so the re-test drives the fixed state.
        if self.drive_btn.isChecked():
            self._arm_current()

    def capture(self) -> None:
        """CAPTURE: the 7.1 rule in code - slider values land in each
        group fixture's Fixture.calibration in the CONFIG, never in
        show blocks."""
        item = self.current_item()
        if item is None or item.kind != "focus_capture":
            return
        focus = self.focus_slider.value()
        zoom = self.zoom_slider.value()
        group = (getattr(self.config, "groups", {}) or {}).get(item.group)
        for fixture in (getattr(group, "fixtures", None) or []):
            fixture.calibration.update({"focus": focus, "zoom": zoom})
        self.checklist.mark_done(item.item_id, result="fixed",
                                 stamp=_now_iso())
        self._after_completion()

    def _after_completion(self) -> None:
        if self.checklist.complete and not self.checklist.completed_at:
            self.checklist.completed_at = _now_iso()
            # Hash the config AS COMPLETED (captures included): a later
            # calibration edit makes the completion stale (7.5).
            self.checklist.completed_target_hash = config_hash(self.config)
        self._save()
        self._refresh_list()
        self._advance()

    def _advance(self) -> None:
        pending = self.checklist.pending()
        if not pending:
            self.drive_btn.setChecked(False)
            self.status_label.setText(
                "Checklist complete · "
                f"{self.checklist.completed_at}")
            self._sync_detail()
            return
        index = self.checklist.items.index(pending[0])
        was_driving = self.drive_btn.isChecked()
        self.item_list.setCurrentRow(index)   # releases the drive state
        if was_driving:
            self.drive_btn.setChecked(True)   # re-arms the new item

    # ── remediation ───────────────────────────────────────────────────────

    def _make_orientation_dialog(self, adapters):
        """Split out so tests stub the GL-backed dialog."""
        from gui.dialogs.orientation_dialog import OrientationDialog
        return OrientationDialog(adapters, self.config, self)

    def _open_orientation_remediation(self, item) -> None:
        group = (getattr(self.config, "groups", {}) or {}).get(item.group)
        fixtures = list(getattr(group, "fixtures", None) or [])
        if not fixtures:
            self._show_guidance(item)
            return
        adapters = [_OrientationTarget(f, group) for f in fixtures]
        dialog = self._make_orientation_dialog(adapters)
        if dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            self.apply_orientation_values(item.group,
                                          dialog.get_orientation_values())
        cleanup = getattr(dialog, "panel", None)
        if cleanup is not None and hasattr(cleanup, "cleanup"):
            cleanup.cleanup()

    def apply_orientation_values(self, group_name: str,
                                 values: dict) -> None:
        """Write the orientation dialog's result into the CONFIG
        fixtures (geometry is config truth, design doc 7.1)."""
        group = (getattr(self.config, "groups", {}) or {}).get(group_name)
        for fixture in (getattr(group, "fixtures", None) or []):
            fixture.mounting = values["mounting"]
            fixture.yaw = values["yaw"]
            fixture.pitch = values["pitch"]
            fixture.roll = values["roll"]
            fixture.z = values["z_height"]
            fixture.orientation_uses_group_default = False
            fixture.z_uses_group_default = False
            # The panel also carries the per-fixture DMX invert flags
            # (v1.5a): a head running opposite to every calculated aim
            # is exactly what an aim check catches on site.
            if "invert_pan" in values:
                fixture.invert_pan = bool(values["invert_pan"])
            if "invert_tilt" in values:
                fixture.invert_tilt = bool(values["invert_tilt"])
        if values.get("apply_to_group") and group is not None:
            group.default_mounting = values["mounting"]
            group.default_yaw = values["yaw"]
            group.default_pitch = values["pitch"]
            group.default_roll = values["roll"]
            group.default_z_height = values["z_height"]

    def _show_guidance(self, item) -> None:
        QtWidgets.QMessageBox.information(
            self, "Venue Pre-Flight",
            GUIDANCE.get(item.kind,
                         "Fix the underlying issue, then re-test."))

    # ── persistence / teardown ────────────────────────────────────────────

    def _save(self) -> None:
        if not self.checklist_path:
            return
        try:
            self.checklist.save(self.checklist_path)
        except OSError:
            self.status_label.setText(
                f"Could not save {self.checklist_path}")

    def done(self, result: int) -> None:
        self.layer.detach()
        super().done(result)
