# gui/dialogs/gdtf_share_account_dialog.py
"""Settings > GDTF Share Account: the user's own Share credentials.

The account the fixture browser's GDTF SHARE tab logs in with. The
username persists in QSettings; the password goes to the OS credential
store (keyring) only while REMEMBER is checked - unchecked, it is used
for this session and never written anywhere (utils/gdtf_share owns the
rules). TEST LOGIN exercises the real API on a worker thread.
"""

from PyQt6 import QtWidgets

from gui.dialogs.gdtf_share_pane import ShareAccountForm, _ShareWorker
from utils.gdtf_share import GDTFShareClient


class GDTFShareAccountDialog(QtWidgets.QDialog):
    """Modal editor for the GDTF Share account."""

    def __init__(self, client: GDTFShareClient = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("GDTF Share Account")
        self.setModal(True)
        self.setMinimumWidth(480)
        self._client = client or GDTFShareClient()
        self._worker = None

        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(12)

        intro = QtWidgets.QLabel(
            "Your own gdtf-share.com account, used by the fixture "
            "browser's GDTF SHARE tab. Downloads land in your GDTF "
            "directory (Settings > Fixture Libraries) and are fetched "
            "per user - the Share terms do not allow bundling them.")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self.account = ShareAccountForm()
        layout.addWidget(self.account)

        test_row = QtWidgets.QHBoxLayout()
        self.test_btn = QtWidgets.QPushButton("TEST LOGIN")
        self.test_btn.clicked.connect(self._test_login)
        test_row.addWidget(self.test_btn)
        self.status_label = QtWidgets.QLabel("")
        test_row.addWidget(self.status_label, 1)
        layout.addLayout(test_row)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _test_login(self):
        user, password = self.account.credentials()
        client = self._client
        self.status_label.setText("Connecting...")
        self.test_btn.setEnabled(False)
        worker = _ShareWorker(
            lambda: client.login(user, password), parent=self)
        worker.ok.connect(
            lambda _res: self.status_label.setText("Login OK."))
        worker.fail.connect(self.status_label.setText)
        worker.finished.connect(lambda: self.test_btn.setEnabled(True))
        self._worker = worker
        worker.start()

    def accept(self) -> None:
        self.account.persist()
        super().accept()
