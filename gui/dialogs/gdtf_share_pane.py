# gui/dialogs/gdtf_share_pane.py
"""GDTF Share browse/download pane (Phase 4 of the GDTF plan).

Hosted as the GDTF SHARE tab of the fixture browser: log in with the
user's own Share account, search the catalog, download revisions into
the user GDTF directory (utils/app_settings.user_gdtf_dir), where the
library scan picks them up immediately. Network work runs on a worker
thread so the dialog never freezes on the catalog fetch (getList takes
tens of seconds cold). Offline: an existing cached catalog is browsable
without logging in; only downloads need the session.

Credentials: username persists in QSettings, the password only in the
OS credential store (keyring) when REMEMBER is checked - see
utils/gdtf_share. The ShareAccountForm rows are reused by the Settings
account dialog (gui/dialogs/gdtf_share_account_dialog.py).
"""

from PyQt6 import QtCore, QtWidgets

from utils import gdtf_share
from utils.gdtf_share import GDTFShareClient, GDTFShareError


class _ShareWorker(QtCore.QThread):
    """Run one blocking client call off the GUI thread."""
    ok = QtCore.pyqtSignal(object)
    fail = QtCore.pyqtSignal(str)

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self._fn = fn

    def run(self):
        try:
            self.ok.emit(self._fn())
        except GDTFShareError as exc:
            self.fail.emit(str(exc))
        except Exception as exc:  # network stacks throw broadly
            self.fail.emit(f"GDTF Share error: {exc}")


class ShareAccountForm(QtWidgets.QWidget):
    """Username / password / remember rows, prefilled from the stored
    account. persist() writes them back per the remember checkbox."""

    def __init__(self, parent=None):
        super().__init__(parent)
        form = QtWidgets.QFormLayout(self)
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(8)

        self.user_edit = QtWidgets.QLineEdit()
        self.user_edit.setPlaceholderText("GDTF Share username")
        self.password_edit = QtWidgets.QLineEdit()
        self.password_edit.setEchoMode(
            QtWidgets.QLineEdit.EchoMode.Password)
        self.remember_check = QtWidgets.QCheckBox(
            "Remember password (OS credential store)")
        if not gdtf_share.keyring_available():
            self.remember_check.setEnabled(False)
            self.remember_check.setToolTip(
                "No OS credential store available (keyring). The password "
                "is kept for this session only - it is never written to "
                "disk in plaintext.")
        form.addRow("Username", self.user_edit)
        form.addRow("Password", self.password_edit)
        form.addRow("", self.remember_check)

        user = gdtf_share.stored_username()
        if user:
            self.user_edit.setText(user)
            password = gdtf_share.stored_password(user)
            if password:
                self.password_edit.setText(password)
                self.remember_check.setChecked(True)

    def credentials(self) -> tuple:
        return (self.user_edit.text().strip(), self.password_edit.text())

    def persist(self) -> None:
        """Store the username; store or clear the password per REMEMBER.
        Called after a successful login so bad credentials are never
        remembered."""
        user, password = self.credentials()
        gdtf_share.store_username(user)
        if self.remember_check.isChecked():
            gdtf_share.save_password(user, password)
        else:
            gdtf_share.clear_password(user)


class GDTFSharePane(QtWidgets.QWidget):
    """CONNECT, search, results table, DOWNLOAD."""

    #: file paths written into the user GDTF dir by the last download
    fixtures_downloaded = QtCore.pyqtSignal(list)

    RESULT_LIMIT = 100

    def __init__(self, client: GDTFShareClient = None, parent=None):
        super().__init__(parent)
        self._client = client or GDTFShareClient()
        self._worker = None
        self._results = []

        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(10)

        self.account = ShareAccountForm()
        layout.addWidget(self.account)

        connect_row = QtWidgets.QHBoxLayout()
        self.connect_btn = QtWidgets.QPushButton("CONNECT")
        self.connect_btn.clicked.connect(self._connect)
        connect_row.addWidget(self.connect_btn)
        self.account_status = QtWidgets.QLabel("Not connected.")
        connect_row.addWidget(self.account_status, 1)
        layout.addLayout(connect_row)

        self.search_box = QtWidgets.QLineEdit()
        self.search_box.setPlaceholderText(
            "Search GDTF Share... (manufacturer or fixture)")
        self.search_box.setEnabled(False)
        self.search_box.textChanged.connect(self._refresh_results)
        layout.addWidget(self.search_box)

        self.table = QtWidgets.QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["Manufacturer", "Fixture", "Uploader", "Rating", "Modes"])
        self.table.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(
            QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setStretchLastSection(True)
        header.setSectionResizeMode(
            QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        self.table.itemSelectionChanged.connect(self._update_download_state)
        layout.addWidget(self.table, 1)

        bottom = QtWidgets.QHBoxLayout()
        self.download_btn = QtWidgets.QPushButton("DOWNLOAD")
        self.download_btn.setEnabled(False)
        self.download_btn.clicked.connect(self._download)
        bottom.addWidget(self.download_btn)
        self.status_label = QtWidgets.QLabel("")
        bottom.addWidget(self.status_label, 1)
        layout.addLayout(bottom)

        # Offline grace: an existing cached catalog is browsable before
        # (or without) a login; downloads still require the session.
        if self._client.load_cached_catalog() is not None:
            self.search_box.setEnabled(True)
            self.account_status.setText(
                "Not connected · showing the cached catalog.")
            self._refresh_results()

    # -- async plumbing ---------------------------------------------------

    def _submit(self, fn, on_ok, on_fail) -> None:
        """One worker at a time; buttons are disabled while it runs."""
        if self._worker is not None and self._worker.isRunning():
            return
        worker = _ShareWorker(fn, parent=self)
        worker.ok.connect(on_ok)
        worker.fail.connect(on_fail)
        worker.finished.connect(self._on_worker_finished)
        self._worker = worker
        self.connect_btn.setEnabled(False)
        self.download_btn.setEnabled(False)
        worker.start()

    def _on_worker_finished(self):
        self.connect_btn.setEnabled(True)
        self._update_download_state()

    # -- connect ----------------------------------------------------------

    def _connect(self):
        user, password = self.account.credentials()
        client = self._client
        self.account_status.setText("Connecting...")

        def work():
            client.login(user, password)
            return client.catalog()

        self._submit(work, self._on_connected, self._on_connect_failed)

    def _on_connected(self, catalog):
        self.account.persist()
        self.account_status.setText(
            f"Connected · catalog: {len(catalog)} revisions.")
        self.search_box.setEnabled(True)
        self._refresh_results()

    def _on_connect_failed(self, message: str):
        self.account_status.setText(message)

    # -- search -----------------------------------------------------------

    def _refresh_results(self):
        if self._client.load_cached_catalog() is None:
            return
        term = self.search_box.text().strip()
        self._results = self._client.search(term, limit=self.RESULT_LIMIT)
        self.table.setRowCount(len(self._results))
        for row, entry in enumerate(self._results):
            modes = ", ".join(
                f"{m.get('name')} ({m.get('dmxfootprint')}ch)"
                for m in (entry.get("modes") or [])[:4])
            if len(entry.get("modes") or []) > 4:
                modes += ", ..."
            values = (entry.get("manufacturer") or "",
                      entry.get("fixture") or "",
                      entry.get("uploader") or "",
                      str(entry.get("rating") or ""),
                      modes)
            for col, value in enumerate(values):
                self.table.setItem(
                    row, col, QtWidgets.QTableWidgetItem(value))
        self._update_download_state()

    def _selected_entries(self) -> list:
        rows = sorted({index.row() for index
                       in self.table.selectionModel().selectedRows()})
        return [self._results[row] for row in rows
                if row < len(self._results)]

    def _update_download_state(self):
        busy = self._worker is not None and self._worker.isRunning()
        self.download_btn.setEnabled(
            not busy and self._client.logged_in
            and bool(self._selected_entries()))

    # -- download ---------------------------------------------------------

    def _download(self):
        entries = self._selected_entries()
        if not entries:
            return
        from utils.app_settings import user_gdtf_dir
        dest_dir = user_gdtf_dir()
        client = self._client
        self.status_label.setText(
            f"Downloading {len(entries)} file(s)...")

        def work():
            return [client.download(entry, dest_dir) for entry in entries]

        self._submit(work, self._on_downloaded, self._on_download_failed)

    def _on_downloaded(self, paths: list):
        from utils.fixture_library import clear_library_cache
        clear_library_cache()
        from utils.app_settings import user_gdtf_dir
        self.status_label.setText(
            f"Saved {len(paths)} file(s) to {user_gdtf_dir()}")
        self.fixtures_downloaded.emit(paths)

    def _on_download_failed(self, message: str):
        self.status_label.setText(message)
