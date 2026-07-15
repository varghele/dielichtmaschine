# gui/dialogs/morph_wizard.py
"""File > Morph to Venue: the wizard around the morph patchbay
(v1.5b phase 4, frame per docs/design/screens/11-morph-wizard.html).

Four steps over the tested engine in utils/morph - the dialog holds no
compile logic of its own:

1. TARGET - pick the venue config (.lms / legacy .yaml). The source is
   the currently open project, passed in. LOAD PLAN... adopts an
   existing *.morphplan.yaml (the re-morph workflow); a hash mismatch
   against either config shows a non-blocking warning banner.
2. PATCHBAY - wire the plan (gui/dialogs/morph_patchbay.py).
3. REVIEW - the completeness checker per song x target group x
   capability (gap rows highlighted as blocking warnings), the morph
   report from a DRY-RUN compile into a deep copy of the target, and
   the destroyed-hand-edits manifest when re-morphing.
4. COMMIT - applies for real (apply_morph force flow: the manifest is
   shown and explicitly confirmed), then offers "Save target as..."
   and "Save plan as...".

Isolation contract: the real target config object is mutated ONLY by
the commit button. Review compiles into a deep copy; Cancel anywhere
changes nothing. Saving stamps plan.source_hash / target_hash via
utils/morph/plan.config_hash so a changed rig invalidates visibly.
"""

from __future__ import annotations

import copy
import datetime
import os

from PyQt6 import QtWidgets
from PyQt6.QtCore import Qt

from utils import app_identity
from utils.morph.checker import group_capabilities
from utils.morph.compile import (apply_morph, compile_setlist,
                                 pending_destruction)
from utils.morph.plan import MorphPlan, PlanError, config_hash

from gui.dialogs.morph_patchbay import SUBLANE_LABELS, MorphPatchbay

PLAN_FILTER = "Morph plans (*.morphplan.yaml);;All files (*)"

PAGE_TARGET, PAGE_PATCHBAY, PAGE_REVIEW, PAGE_COMMIT = range(4)


def _config_summary(config, path: str = "") -> str:
    songs = len(getattr(config, "songs", {}) or {})
    parts = [f"{len(config.fixtures)} fixtures",
             f"{len(config.groups)} groups"]
    if songs:
        parts.append(f"{songs} song(s)")
    if path:
        parts.insert(0, os.path.basename(path))
    return " · ".join(parts)


class MorphWizard(QtWidgets.QDialog):
    """Modal morph flow. ``source_config`` is the open project (read
    only); the target config is loaded here and mutated only on
    commit - the caller decides nothing, the save buttons write to
    disk."""

    def __init__(self, source_config, source_path: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Morph to Venue")
        self.setModal(True)
        self.setMinimumSize(980, 640)

        self.source_config = source_config
        self.source_path = source_path
        self.target_config = None
        self.target_path = ""
        self.plan = MorphPlan(name="morph")
        self.patchbay: MorphPatchbay | None = None
        self.committed = False
        self._dry_result = None
        self._source_hash = None       # config_hash cache (modal dialog)
        self._target_hash = None

        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(10)

        # Non-blocking plan-vs-config warning (design: warn, never block).
        self.banner = QtWidgets.QLabel("")
        self.banner.setWordWrap(True)
        self.banner.setStyleSheet(
            "QLabel { color: #ff9800; border: 1px solid #ff9800;"
            " padding: 6px 10px; }")
        self.banner.setVisible(False)
        layout.addWidget(self.banner)

        self._stack = QtWidgets.QStackedWidget()
        self._stack.addWidget(self._build_target_page())
        self._stack.addWidget(self._build_patchbay_page())
        self._stack.addWidget(self._build_review_page())
        self._stack.addWidget(self._build_commit_page())
        layout.addWidget(self._stack, 1)

        row = QtWidgets.QHBoxLayout()
        self.back_btn = QtWidgets.QPushButton("Back")
        self.back_btn.clicked.connect(self._go_back)
        row.addWidget(self.back_btn)
        row.addStretch(1)
        self.cancel_btn = QtWidgets.QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.reject)
        row.addWidget(self.cancel_btn)
        self.next_btn = QtWidgets.QPushButton("Next")
        self.next_btn.setDefault(True)
        self.next_btn.clicked.connect(self._go_next)
        row.addWidget(self.next_btn)
        layout.addLayout(row)

        self._sync_buttons()

    # ── page 1: target ────────────────────────────────────────────────────

    def _build_target_page(self) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(page)
        layout.setSpacing(8)

        intro = QtWidgets.QLabel(
            "Morph the open show onto another rig. Pick the venue "
            "config; the patchbay wires each source lane stream onto "
            "the target groups. Nothing is written until you commit "
            "and save.")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        cards = QtWidgets.QHBoxLayout()
        source_box = QtWidgets.QGroupBox("Source · the open project")
        source_layout = QtWidgets.QVBoxLayout(source_box)
        self.source_label = QtWidgets.QLabel(
            _config_summary(self.source_config, self.source_path))
        self.source_label.setWordWrap(True)
        source_layout.addWidget(self.source_label)
        cards.addWidget(source_box, 1)

        target_box = QtWidgets.QGroupBox("Target · the venue rig")
        target_layout = QtWidgets.QVBoxLayout(target_box)
        pick_row = QtWidgets.QHBoxLayout()
        self.target_edit = QtWidgets.QLineEdit()
        self.target_edit.setReadOnly(True)
        self.target_edit.setPlaceholderText("Choose a project file...")
        browse = QtWidgets.QPushButton("Browse...")
        browse.clicked.connect(self._browse_target)
        pick_row.addWidget(self.target_edit, 1)
        pick_row.addWidget(browse)
        target_layout.addLayout(pick_row)
        self.target_label = QtWidgets.QLabel("No target loaded.")
        self.target_label.setWordWrap(True)
        target_layout.addWidget(self.target_label)
        cards.addWidget(target_box, 1)
        layout.addLayout(cards)

        plan_row = QtWidgets.QHBoxLayout()
        load_plan = QtWidgets.QPushButton("Load Plan...")
        load_plan.setToolTip(
            "Adopt an existing *.morphplan.yaml - the re-morph workflow")
        load_plan.clicked.connect(self._browse_plan)
        plan_row.addWidget(load_plan)
        self.plan_label = QtWidgets.QLabel("Plan: new (empty)")
        plan_row.addWidget(self.plan_label, 1)
        layout.addLayout(plan_row)
        layout.addStretch(1)
        return page

    def _browse_target(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Choose Target Rig", "",
            app_identity.project_open_filter())
        if not path:
            return
        from config.models import Configuration
        try:
            config = Configuration.load(path)
        except Exception as exc:
            QtWidgets.QMessageBox.warning(
                self, "Morph to Venue",
                f"Could not load {os.path.basename(path)}:\n{exc}")
            return
        self.set_target_config(config, path)

    def set_target_config(self, config, path: str = "") -> None:
        """Adopt the venue config (Browse and tests both land here)."""
        self.target_config = config
        self.target_path = path
        # Hash the target NOW: this pins the rig the plan is authored
        # against. Computed after commit it would hash the morphed
        # songs into the identity and every saved plan would read as
        # "rig changed" on its first re-morph.
        self._target_hash = config_hash(config)
        self.target_edit.setText(path)
        self.target_label.setText(_config_summary(config, path))
        # A fresh target invalidates any previous patchbay wiring UI;
        # the plan survives (its edges re-validate against the new rig).
        self.patchbay = MorphPatchbay(self.source_config, config,
                                      self.plan)
        holder = self._patchbay_holder.layout()
        while holder.count():
            item = holder.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        holder.addWidget(self.patchbay)
        self._update_banner()
        self._sync_buttons()

    def _browse_plan(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Load Morph Plan", "", PLAN_FILTER)
        if not path:
            return
        try:
            self.load_plan_file(path)
        except PlanError as exc:
            QtWidgets.QMessageBox.warning(self, "Morph to Venue", str(exc))

    def load_plan_file(self, path: str) -> None:
        """Adopt an existing plan file; hash mismatches warn, never
        block."""
        plan = MorphPlan.load(path)
        self.set_plan(plan)
        self.plan_label.setText(
            f"Plan: {os.path.basename(path)} ({len(plan.edges)} edge(s))")

    def set_plan(self, plan: MorphPlan) -> None:
        """ONE plan object is shared by wizard and patchbay - both
        mutate it, commit and save read it."""
        self.plan = plan
        if self.patchbay is not None:
            self.patchbay.load_plan(plan)
        self._update_banner()

    def _hash_of_source(self) -> str:
        if self._source_hash is None:
            self._source_hash = config_hash(self.source_config)
        return self._source_hash

    def _hash_of_target(self) -> str:
        if self._target_hash is None:
            self._target_hash = config_hash(self.target_config)
        return self._target_hash

    def _update_banner(self) -> None:
        stale = []
        if self.plan.source_hash and \
                self.plan.source_hash != self._hash_of_source():
            stale.append("source")
        if self.target_config is not None and self.plan.target_hash and \
                self.plan.target_hash != self._hash_of_target():
            stale.append("target")
        if stale:
            self.banner.setText(
                "The " + " and ".join(stale) + " rig changed since this "
                "plan was authored - review the wiring before committing.")
        self.banner.setVisible(bool(stale))

    # ── page 2: patchbay ──────────────────────────────────────────────────

    def _build_patchbay_page(self) -> QtWidgets.QWidget:
        self._patchbay_holder = QtWidgets.QWidget()
        QtWidgets.QVBoxLayout(self._patchbay_holder)
        return self._patchbay_holder

    # ── page 3: review ────────────────────────────────────────────────────

    def _build_review_page(self) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(page)
        layout.setSpacing(8)

        self.review_summary = QtWidgets.QLabel("")
        self.review_summary.setWordWrap(True)
        layout.addWidget(self.review_summary)

        layout.addWidget(QtWidgets.QLabel(
            "Coverage per song, target group and capability "
            "(0% on a capability the group has = blocking warning):"))
        self.coverage_table = QtWidgets.QTableWidget()
        self.coverage_table.setEditTriggers(
            QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.coverage_table.verticalHeader().setVisible(False)
        layout.addWidget(self.coverage_table, 2)

        self.destroyed_label = QtWidgets.QLabel("")
        self.destroyed_label.setWordWrap(True)
        self.destroyed_label.setStyleSheet("QLabel { color: #e5484d; }")
        self.destroyed_label.setVisible(False)
        layout.addWidget(self.destroyed_label)

        layout.addWidget(QtWidgets.QLabel("Morph report (dry run):"))
        self.report_view = QtWidgets.QPlainTextEdit()
        self.report_view.setReadOnly(True)
        layout.addWidget(self.report_view, 3)
        return page

    def _enter_review(self) -> None:
        """Dry-run compile into a DEEP COPY - the real target config is
        untouched until commit."""
        target_copy = copy.deepcopy(self.target_config)
        self._dry_result = compile_setlist(
            self.source_config, self.plan, target_copy)
        report = self._dry_result.report

        result = self.patchbay.checker()
        caps = group_capabilities(self.target_config)
        gaps = {(g.song, g.target_group, g.sublane)
                for g in result.gaps(caps)}

        headers = ["Song", "Target group", "Capability", "Coverage",
                   "Edges"]
        self.coverage_table.clear()
        self.coverage_table.setColumnCount(len(headers))
        self.coverage_table.setHorizontalHeaderLabels(headers)
        self.coverage_table.setRowCount(len(result.coverage))
        for r, row in enumerate(result.coverage):
            is_gap = (row.song, row.target_group, row.sublane) in gaps
            values = [row.song, row.target_group,
                      SUBLANE_LABELS[row.sublane],
                      f"{row.percent}%" + (" GAP" if is_gap else ""),
                      str(row.routed_edges)]
            for c, value in enumerate(values):
                item = QtWidgets.QTableWidgetItem(value)
                if is_gap:
                    item.setForeground(Qt.GlobalColor.red)
                self.coverage_table.setItem(r, c, item)
        self.coverage_table.resizeColumnsToContents()

        errors = len(report.of_kind("error"))
        pieces = [f"{len(self._dry_result.songs)} song(s) compiled",
                  f"{len(self.plan.edges)} edge(s)",
                  f"{len(gaps)} capability gap(s)"]
        if errors:
            pieces.append(f"{errors} error(s) - commit stays disabled")
        if result.unrouted_sources:
            pieces.append(f"{len(result.unrouted_sources)} unrouted "
                          f"source stream(s) (deliberate drops)")
        self.review_summary.setText(" · ".join(pieces) + ".")

        manifest = pending_destruction(self._dry_result,
                                       self.target_config, self.plan)
        if manifest:
            self.destroyed_label.setText(
                "Re-morph will destroy these hand-edited blocks:\n"
                + "\n".join(manifest))
        self.destroyed_label.setVisible(bool(manifest))

        self.report_view.setPlainText(report.to_markdown())

    # ── page 4: commit ────────────────────────────────────────────────────

    def _build_commit_page(self) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(page)
        layout.setSpacing(8)

        self.commit_summary = QtWidgets.QLabel("")
        self.commit_summary.setWordWrap(True)
        layout.addWidget(self.commit_summary)

        self.commit_btn = QtWidgets.QPushButton("Commit Morph")
        self.commit_btn.clicked.connect(self.commit)
        layout.addWidget(self.commit_btn)

        self.commit_status = QtWidgets.QLabel("")
        self.commit_status.setWordWrap(True)
        layout.addWidget(self.commit_status)

        save_row = QtWidgets.QHBoxLayout()
        self.save_target_btn = QtWidgets.QPushButton("Save Target As...")
        self.save_target_btn.setEnabled(False)
        self.save_target_btn.clicked.connect(self._save_target_as)
        save_row.addWidget(self.save_target_btn)
        self.save_plan_btn = QtWidgets.QPushButton("Save Plan As...")
        self.save_plan_btn.clicked.connect(self._save_plan_as)
        save_row.addWidget(self.save_plan_btn)
        save_row.addStretch(1)
        layout.addLayout(save_row)
        layout.addStretch(1)
        return page

    def _enter_commit(self) -> None:
        target = os.path.basename(self.target_path) or "the target config"
        count = len(self._dry_result.songs) if self._dry_result else 0
        self.commit_summary.setText(
            f"Commit writes {count} morphed song(s) into {target}. "
            f"The plan can be saved either way; the target only changes "
            f"on disk via Save Target As.")
        self.commit_btn.setEnabled(not self.committed and count > 0)

    def _confirm_destruction(self, manifest) -> bool:
        """The apply_morph force gate: show the manifest, ask. Split out
        so tests can drive commit() without a modal dialog."""
        text = ("Re-morphing replaces the target songs and will destroy "
                "these hand-edited blocks:\n\n" + "\n".join(manifest)
                + "\n\nReplace anyway?")
        answer = QtWidgets.QMessageBox.question(
            self, "Destroy hand edits?", text,
            QtWidgets.QMessageBox.StandardButton.Yes
            | QtWidgets.QMessageBox.StandardButton.No)
        return answer == QtWidgets.QMessageBox.StandardButton.Yes

    def commit(self) -> bool:
        """Compile against the REAL target config and apply. The force
        flow: a non-empty destroyed-hand-edits manifest must be
        explicitly confirmed first."""
        if self.committed or self.target_config is None:
            return False
        result = compile_setlist(self.source_config, self.plan,
                                 self.target_config,
                                 stamp=self._lineage_stamp())
        if result.report.has_errors:
            errors = "\n".join(
                e.format() for e in result.report.of_kind("error"))
            QtWidgets.QMessageBox.warning(
                self, "Morph to Venue",
                "The compile reported errors; nothing was applied:\n\n"
                + errors)
            return False
        manifest = pending_destruction(result, self.target_config,
                                       self.plan)
        if manifest and not self._confirm_destruction(manifest):
            return False
        apply_morph(result, self.target_config, self.plan, force=True)
        self.committed = True
        self.commit_btn.setEnabled(False)
        self.save_target_btn.setEnabled(True)
        self.commit_status.setText(
            f"Morph applied: {len(result.songs)} song(s) written. "
            f"Save the target and the plan to keep them.")
        self._sync_buttons()
        return True

    def _lineage_stamp(self) -> dict:
        from utils.app_identity import APP_VERSION
        return {"app_version": APP_VERSION,
                "timestamp": datetime.datetime.now().isoformat(
                    timespec="seconds"),
                "source_path": self.source_path,
                "target_path": self.target_path}

    def _save_target_as(self) -> None:
        start = self.target_path or ""
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Save Morphed Target As", start,
            app_identity.project_save_filter())
        if not path:
            return
        self.target_config.save(app_identity.ensure_project_ext(path))

    def _save_plan_as(self) -> None:
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Save Morph Plan As", "", PLAN_FILTER)
        if not path:
            return
        if not path.endswith(".morphplan.yaml"):
            path += ".morphplan.yaml"
        self.save_plan_to(path)

    def save_plan_to(self, path: str) -> None:
        """Stamp identity hashes + date, then persist (design doc 5.1)."""
        self.plan.source_hash = self._hash_of_source()
        if self.target_config is not None:
            # The committed target contains the morphed songs; the plan
            # pins the rig it was AUTHORED against - the hash cached by
            # set_target_config at load time, before any commit.
            self.plan.target_hash = self._hash_of_target()
        if not self.plan.created:
            self.plan.created = datetime.date.today().isoformat()
        self.plan.save(path)

    # ── navigation ────────────────────────────────────────────────────────

    def _go_next(self) -> None:
        index = self._stack.currentIndex()
        if index == PAGE_TARGET:
            self._stack.setCurrentIndex(PAGE_PATCHBAY)
        elif index == PAGE_PATCHBAY:
            self._enter_review()
            self._stack.setCurrentIndex(PAGE_REVIEW)
        elif index == PAGE_REVIEW:
            self._enter_commit()
            self._stack.setCurrentIndex(PAGE_COMMIT)
        else:
            self.accept()
        self._sync_buttons()

    def _go_back(self) -> None:
        index = self._stack.currentIndex()
        if index > 0:
            self._stack.setCurrentIndex(index - 1)
        self._sync_buttons()

    def _sync_buttons(self) -> None:
        index = self._stack.currentIndex()
        self.back_btn.setEnabled(index > 0 and not self.committed)
        if index == PAGE_COMMIT:
            self.next_btn.setText("Close" if self.committed else "Done")
            self.next_btn.setEnabled(True)
        else:
            self.next_btn.setText("Next")
            self.next_btn.setEnabled(self.target_config is not None)
        # After a commit the target object is already morphed; Cancel
        # would imply it is not. (Nothing hits disk without the save
        # buttons either way.)
        self.cancel_btn.setVisible(not self.committed)
