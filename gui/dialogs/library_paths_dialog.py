# gui/dialogs/library_paths_dialog.py
"""Settings > Fixture Libraries: the user's own definition directories.

Two paths (ROADMAP v1.2 "Configurable fixture library paths"): a GDTF
directory and a .qxf directory, persisted via utils/app_settings.py and
folded into utils/fixture_library.fixture_search_dirs() with priority
user GDTF > project gdtf_fixtures/ > bundled custom_fixtures/ > user
QXF > platform QLC+ dirs. Saving invalidates the definition cache (the
app_settings setters do), so the next fixture-browser open or config
load rescans; accepted directories are created if missing - the
defaults live in the per-user app-data dir, which is exactly where the
future GDTF Share downloads land.
"""

import os

from PyQt6 import QtWidgets

from utils.app_settings import (
    app_settings, default_user_gdtf_dir, default_user_qxf_dir,
    set_user_gdtf_dir, set_user_qxf_dir, user_gdtf_dir, user_qxf_dir,
)


class LibraryPathsDialog(QtWidgets.QDialog):
    """Modal editor for the two user fixture-library directories."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Fixture Libraries")
        self.setModal(True)
        self.setMinimumWidth(560)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(12)

        intro = QtWidgets.QLabel(
            "Your own fixture definitions. Files in these directories are "
            "found by the fixture browser and win over the shipped "
            "definitions of the same fixture (GDTF wins over .qxf either "
            "way). Leave a field empty to use the per-user default.")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        form = QtWidgets.QFormLayout()
        form.setSpacing(8)
        self.gdtf_edit = self._path_row(
            form, "GDTF directory", user_gdtf_dir(),
            default_user_gdtf_dir())
        self.qxf_edit = self._path_row(
            form, "QXF directory", user_qxf_dir(),
            default_user_qxf_dir())
        layout.addLayout(form)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _path_row(self, form, label: str, current: str,
                  default: str) -> QtWidgets.QLineEdit:
        """One form row: line edit (default as placeholder; the stored
        value only fills the edit when it differs from the default) +
        a browse button."""
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(6)
        edit = QtWidgets.QLineEdit()
        edit.setPlaceholderText(default)
        if os.path.normpath(current) != os.path.normpath(default):
            edit.setText(current)
        browse = QtWidgets.QPushButton("Browse...")
        browse.clicked.connect(lambda: self._browse_into(edit))
        row.addWidget(edit, 1)
        row.addWidget(browse)
        form.addRow(label, row)
        return edit

    def _browse_into(self, edit: QtWidgets.QLineEdit) -> None:
        start = edit.text() or edit.placeholderText()
        chosen = QtWidgets.QFileDialog.getExistingDirectory(
            self, "Choose directory", start)
        if chosen:
            edit.setText(chosen)

    # -- persistence ------------------------------------------------------

    def effective_paths(self) -> tuple:
        """(gdtf_dir, qxf_dir) as the dialog would persist them - the
        typed text, or '' meaning "use the default"."""
        return (self.gdtf_edit.text().strip(),
                self.qxf_edit.text().strip())

    def accept(self) -> None:
        gdtf, qxf = self.effective_paths()
        # Create whatever will be in effect so a freshly-pointed
        # directory is immediately usable (and the app-data default
        # exists once the user has visited this dialog).
        for path in (gdtf or default_user_gdtf_dir(),
                     qxf or default_user_qxf_dir()):
            try:
                os.makedirs(path, exist_ok=True)
            except OSError as exc:
                QtWidgets.QMessageBox.warning(
                    self, "Fixture Libraries",
                    f"Cannot create {path}:\n{exc}")
                return  # keep the dialog open for a correction
        set_user_gdtf_dir(gdtf)
        set_user_qxf_dir(qxf)
        app_settings().sync()
        super().accept()
