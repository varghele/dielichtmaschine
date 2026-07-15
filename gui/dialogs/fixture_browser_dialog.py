# gui/dialogs/fixture_browser_dialog.py
"""Search-and-patch browser over the QLC+ fixture library.

Replaces the ad-hoc list dialog that lived inside FixturesTab._add_fixture.
Upgrades for onboarding:

- Details pane: selecting an entry lazily parses its .qxf and shows the
  fixture type plus every mode with its channel count, so users can pick
  the right definition without opening QLC+.
- Source tag: entries from the bundled ``custom_fixtures/`` are marked,
  since those are guaranteed to exist on every machine.
- Quantity: add N copies in one go; the caller patches them at
  consecutive free addresses.
- GDTF SHARE tab (Phase 4): when the caller passes a ``share_pane``
  (gui/dialogs/gdtf_share_pane.GDTFSharePane), the library view and the
  Share browser sit in two tabs; a Share download triggers ``rescan``
  and the fresh files appear in the library list immediately.

The dialog is given the fixture file list (it does no directory
scanning) so tests can feed it a known set and FixturesTab keeps owning
the platform-specific search paths.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple

from PyQt6 import QtCore, QtGui, QtWidgets

from utils.fixture_library import parse_fixture_file


def parse_qxf_summary(path: str) -> Dict:
    """Parse one .qxf into the details the browser shows.

    Returns {'manufacturer', 'model', 'type', 'modes': [(name, channels)]}.
    Raises on unreadable/invalid files; the dialog turns that into an
    inline error message instead of a crash.
    """
    return parse_fixture_file(path).summary()


class FixtureBrowserDialog(QtWidgets.QDialog):
    """Modal fixture picker; read the result via :meth:`selection`."""

    def __init__(self, fixture_files: List[dict], parent=None,
                 rescan=None, share_pane=None):
        """fixture_files: [{'manufacturer', 'model', 'path', 'source'}]
        where source is 'bundled' (custom_fixtures/) or 'library'.
        rescan: zero-arg callable returning a fresh fixture_files list,
        called after a GDTF Share download. share_pane: an optional
        GDTFSharePane shown as a second tab."""
        super().__init__(parent)
        self.setWindowTitle("Add Fixture")
        self.setModal(True)
        self.resize(760, 560)
        self._summary_cache: Dict[str, Dict] = {}
        self._rescan = rescan
        self.share_pane = share_pane

        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(10)

        library_page = QtWidgets.QWidget()
        library_layout = QtWidgets.QVBoxLayout(library_page)
        library_layout.setContentsMargins(0, 0, 0, 0)
        library_layout.setSpacing(10)

        self.search_box = QtWidgets.QLineEdit()
        self.search_box.setPlaceholderText(
            "Search fixtures... (manufacturer or model)")
        font = QtGui.QFont()
        font.setPointSize(12)
        self.search_box.setFont(font)
        self.search_box.setMinimumHeight(36)
        library_layout.addWidget(self.search_box)

        split = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)

        self.list_widget = QtWidgets.QListWidget()
        self.list_widget.setFont(font)
        self.list_widget.setSpacing(2)
        self.set_fixture_files(fixture_files)
        split.addWidget(self.list_widget)

        self.details = QtWidgets.QTextBrowser()
        self.details.setOpenExternalLinks(False)
        self.details.setPlaceholderText("Select a fixture to see its modes.")
        split.addWidget(self.details)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        library_layout.addWidget(split, stretch=1)

        if share_pane is not None:
            self.tabs = QtWidgets.QTabWidget()
            self.tabs.addTab(library_page, "LIBRARY")
            self.tabs.addTab(share_pane, "GDTF SHARE")
            layout.addWidget(self.tabs, stretch=1)
            share_pane.fixtures_downloaded.connect(
                self._on_share_downloaded)
        else:
            layout.addWidget(library_page, stretch=1)

        bottom = QtWidgets.QHBoxLayout()
        bottom.addWidget(QtWidgets.QLabel("Quantity:"))
        self.quantity_spin = QtWidgets.QSpinBox()
        self.quantity_spin.setRange(1, 64)
        self.quantity_spin.setToolTip(
            "Add this many copies, patched at consecutive free addresses.")
        bottom.addWidget(self.quantity_spin)
        bottom.addStretch()

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok |
            QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        self._ok_button = buttons.button(
            QtWidgets.QDialogButtonBox.StandardButton.Ok)
        self._ok_button.setEnabled(False)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        bottom.addWidget(buttons)
        layout.addLayout(bottom)

        self.search_box.textChanged.connect(self._filter)
        self.list_widget.currentItemChanged.connect(self._update_details)
        self.list_widget.itemDoubleClicked.connect(lambda _item: self.accept())
        self.search_box.setFocus()

    # ── Behavior ──────────────────────────────────────────────────────

    def set_fixture_files(self, fixture_files: List[dict]) -> None:
        """(Re)populate the library list, sorted, with source tags."""
        self.list_widget.clear()
        fixture_files = sorted(
            fixture_files,
            key=lambda f: (f['manufacturer'].lower(), f['model'].lower()),
        )
        for entry in fixture_files:
            label = f"{entry['manufacturer']} · {entry['model']}"
            source = entry.get('source')
            if source == 'bundled':
                label += "   [bundled]"
            elif source in ('gdtf', 'user-gdtf'):
                label += "   [GDTF]"
            elif source == 'user-qxf':
                label += "   [user]"
            item = QtWidgets.QListWidgetItem(label)
            item.setData(QtCore.Qt.ItemDataRole.UserRole, entry['path'])
            self.list_widget.addItem(item)

    def _on_share_downloaded(self, _paths: list) -> None:
        """A Share download landed in the user GDTF dir: rescan so the
        new definitions are patchable without reopening the dialog."""
        if self._rescan is None:
            return
        try:
            self.set_fixture_files(self._rescan())
        except Exception:
            # The files are on disk; the next open picks them up.
            logging.getLogger(__name__).warning(
                "Library rescan after a GDTF Share download failed",
                exc_info=True)
        if self.search_box.text():
            self._filter()

    def _filter(self):
        needle = self.search_box.text().lower()
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            item.setHidden(needle not in item.text().lower())

    def _summary_for(self, path: str) -> Optional[Dict]:
        if path not in self._summary_cache:
            try:
                self._summary_cache[path] = parse_qxf_summary(path)
            except Exception as e:
                self._summary_cache[path] = {'error': str(e)}
        summary = self._summary_cache[path]
        return None if 'error' in summary else summary

    def _update_details(self, current, _previous=None):
        self._ok_button.setEnabled(current is not None)
        if current is None:
            self.details.clear()
            return
        path = current.data(QtCore.Qt.ItemDataRole.UserRole)
        summary = self._summary_for(path)
        if summary is None:
            self.details.setHtml(
                f"<p><b>Could not read this fixture definition.</b></p>"
                f"<p>{self._summary_cache[path]['error']}</p>"
            )
            self._ok_button.setEnabled(False)
            return
        mode_rows = "".join(
            f"<tr><td>{name}</td><td align='right'>{channels} ch</td></tr>"
            for name, channels in summary['modes']
        ) or "<tr><td colspan='2'>(no modes)</td></tr>"
        self.details.setHtml(
            f"<h3>{summary['manufacturer']} {summary['model']}</h3>"
            f"<p>Type: <b>{summary['type']}</b></p>"
            f"<p><b>Modes</b></p>"
            f"<table width='100%' cellpadding='2'>{mode_rows}</table>"
        )

    def selection(self) -> Optional[Tuple[str, int]]:
        """(qxf_path, quantity) of the accepted pick, or None."""
        item = self.list_widget.currentItem()
        if item is None:
            return None
        return (item.data(QtCore.Qt.ItemDataRole.UserRole),
                self.quantity_spin.value())
