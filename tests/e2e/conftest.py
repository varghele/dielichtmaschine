"""End-to-end harness: drives the real MainWindow through the whole
authoring flow (universe -> fixtures -> stage -> structure -> timeline ->
playback) and asserts on the configuration model, never on pixels.

Design rules for everything under tests/e2e:

* The REAL widgets and the REAL signal wiring run. We click real buttons
  and let the real handlers mutate the real ``Configuration``.
* Only these things are stubbed, each for a reason that has nothing to do
  with the behaviour under test:
    - OpenGL surfaces (``EmbeddedVisualizer``, ``OrientationPreviewWidget``)
      cannot create a GL context under ``QT_QPA_PLATFORM=offscreen``.
    - ``RiffBrowserPanel``, whose construction pulls in the riff library.
    - ``ArtNetSender``, which opens a broadcast UDP socket in ``__init__``.
    - Hardware/OS probes: USB serial enumeration, MIDI profile discovery,
      the auto-tab settings file, and the standalone-visualizer subprocess.

* NO MODAL CAN EVER BLOCK. ``QDialog.exec``, ``QMenu.exec`` and the
  ``QInputDialog`` / ``QMessageBox`` / ``QFileDialog`` static helpers are all
  replaced by guards. A guard either runs the handler the test registered, or
  - if the test did not plan for that modal - records a violation and returns
  the "user pressed Cancel" answer. ``modals`` then fails the test at
  teardown. Guards must never raise: PyQt6 calls ``qFatal()`` when a Python
  exception escapes a slot invoked from C++ (``button.click()`` does exactly
  that), which aborts the interpreter instead of failing the test.

The dialog guard deliberately keeps the real dialog objects: a registered
handler receives the constructed dialog and pokes its real widgets, so the
dialog's own accept()/write-back logic still runs.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


# ---------------------------------------------------------------------------
# Fixture definitions used by the whole suite. The PAR's model name carries a
# trailing space in the bundled .qxf - keep it verbatim (see CLAUDE.md).
# ---------------------------------------------------------------------------
PAR_QXF = "custom_fixtures/Stairville-Retro-Flat-Par-18x12W-RGBW-.qxf"
PAR_MFR = "Stairville"
PAR_MODEL = "Retro Flat Par 18x12W RGBW "
PAR_MODE_6CH = "6 Channel"  # Dimmer, R, G, B, W, Strobe

MH_QXF = "custom_fixtures/Varytec-Hero-Spot-60.qxf"
MH_MFR = "Varytec"
MH_MODEL = "Hero Spot 60"
MH_MODE_8CH = "8 Channel"  # Pan, Tilt, Speed, Dimmer, Shutter, Focus, ...


def project_path(rel: str) -> str:
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(root, *rel.split("/"))


# ---------------------------------------------------------------------------
# Modal guards
# ---------------------------------------------------------------------------
class DialogDriver:
    """Registry of per-dialog handlers for the patched ``QDialog.exec``.

    Register by class name (preferred, stable) or by window title (for the
    ad-hoc ``QDialog`` instances that app code builds inline and whose widgets
    are local variables, reachable only via ``findChildren``).
    """

    def __init__(self, violations):
        self._handlers = {}
        self._violations = violations
        self.seen = []

    def on(self, key: str, handler):
        """handler(dialog) -> int (a QDialog.DialogCode value)."""
        self._handlers[key] = handler

    def fail(self, message: str):
        """Record a failure from inside a handler.

        Handlers run inside Qt slots; a raised exception there is a qFatal(),
        not a test failure. Record and let `modals` fail at teardown.
        """
        self._violations.append(message)

    def _exec(self, dialog):
        from PyQt6.QtWidgets import QDialog
        for key in (type(dialog).__name__, dialog.windowTitle()):
            if key in self._handlers:
                self.seen.append(key)
                return int(self._handlers[key](dialog))
        self._violations.append(
            f"Unhandled modal dialog: class={type(dialog).__name__!r} "
            f"title={dialog.windowTitle()!r}"
        )
        return int(QDialog.DialogCode.Rejected)


class MenuDriver:
    """Registry for the patched ``QMenu.exec``: pick one action by text."""

    def __init__(self, violations):
        self._choice = None
        self._violations = violations
        self.last_action_texts = []

    def choose(self, action_text: str):
        self._choice = action_text

    @staticmethod
    def _walk(menu):
        """Every leaf action in the menu, descending into submenus."""
        for action in menu.actions():
            submenu = action.menu()
            if submenu is not None:
                yield from MenuDriver._walk(submenu)
            elif not action.isSeparator():
                yield action

    def _exec(self, menu):
        actions = list(self._walk(menu))
        self.last_action_texts = [a.text() for a in actions]
        if self._choice is None:
            self._violations.append(
                f"Unhandled context menu offering {self.last_action_texts}")
            return None
        for action in actions:
            if action.text() == self._choice:
                self._choice = None
                return action
        self._violations.append(
            f"Menu action {self._choice!r} not found; menu offers "
            f"{self.last_action_texts}")
        self._choice = None
        return None


class InputDriver:
    """Registry for the ``QInputDialog`` static helpers, keyed by title."""

    def __init__(self, violations):
        self._answers = {}
        self._violations = violations
        self.asked = []

    def answer(self, title: str, value, ok: bool = True):
        self._answers[title] = (value, ok)

    def _respond(self, title, kind, default):
        self.asked.append((title, kind))
        if title not in self._answers:
            self._violations.append(f"Unhandled QInputDialog.{kind} {title!r}")
            return (default, False)  # as if the user pressed Cancel
        return self._answers[title]


class MessageBoxDriver:
    """Records QMessageBox statics.

    An unexpected message box in the middle of the happy path means the app
    refused to do what the user asked (exactly the shape of the '+ New show
    silently did nothing' bug), so it fails the test unless declared.
    """

    def __init__(self, violations):
        self._violations = violations
        self.shown = []
        self._expected = []

    def expect(self, title_fragment: str):
        self._expected.append(title_fragment)

    def _record(self, kind, title, text):
        self.shown.append((kind, title, text))
        for fragment in self._expected:
            if fragment in title or fragment in text:
                self._expected.remove(fragment)
                return
        self._violations.append(f"Unexpected QMessageBox.{kind}: {title!r} {text!r}")

    def _unmet(self):
        return list(self._expected)


class ModalGuard:
    def __init__(self):
        self.violations = []
        self.dialogs = DialogDriver(self.violations)
        self.menus = MenuDriver(self.violations)
        self.inputs = InputDriver(self.violations)
        self.messages = MessageBoxDriver(self.violations)


@pytest.fixture(autouse=True)
def modals(monkeypatch):
    """Install the modal guards. Autouse: no e2e test may open a real modal."""
    from PyQt6.QtWidgets import (QDialog, QFileDialog, QInputDialog, QMenu,
                                 QMessageBox)

    guard = ModalGuard()

    monkeypatch.setattr(QDialog, "exec", lambda self: guard.dialogs._exec(self))
    monkeypatch.setattr(QMenu, "exec", lambda self, *a, **k: guard.menus._exec(self))

    def _input(kind, default):
        def helper(parent, title, label, *a, **k):
            return guard.inputs._respond(title, kind, default)
        return staticmethod(helper)

    monkeypatch.setattr(QInputDialog, "getText", _input("getText", ""))
    monkeypatch.setattr(QInputDialog, "getDouble", _input("getDouble", 0.0))
    monkeypatch.setattr(QInputDialog, "getInt", _input("getInt", 0))
    monkeypatch.setattr(QInputDialog, "getItem", _input("getItem", ""))

    def _message(kind, answer):
        def helper(parent, title, text, *a, **k):
            guard.messages._record(kind, title, text)
            return answer
        return staticmethod(helper)

    for kind in ("warning", "critical", "information"):
        monkeypatch.setattr(QMessageBox, kind,
                            _message(kind, QMessageBox.StandardButton.Ok))
    monkeypatch.setattr(QMessageBox, "question",
                        _message("question", QMessageBox.StandardButton.No))
    monkeypatch.setattr(QMessageBox, "about",
                        staticmethod(lambda *a, **k: None))

    def no_file_dialog(kind, empty):
        def helper(*a, **k):
            guard.violations.append(f"Unexpected QFileDialog.{kind}")
            return empty  # as if the user cancelled
        return staticmethod(helper)

    for name in ("getOpenFileName", "getSaveFileName", "getOpenFileNames"):
        monkeypatch.setattr(QFileDialog, name, no_file_dialog(name, ("", "")))
    monkeypatch.setattr(QFileDialog, "getExistingDirectory",
                        no_file_dialog("getExistingDirectory", ""))

    yield guard

    assert not guard.violations, "modal-guard violations:\n  " + \
        "\n  ".join(guard.violations)
    assert not guard.messages._unmet(), \
        f"expected message boxes never appeared: {guard.messages._unmet()}"


@pytest.fixture
def dialogs(modals):
    return modals.dialogs


@pytest.fixture
def menus(modals):
    return modals.menus


@pytest.fixture
def inputs(modals):
    return modals.inputs


@pytest.fixture
def message_boxes(modals):
    return modals.messages


# ---------------------------------------------------------------------------
# Headless stand-ins for the GL surfaces and the riff panel
# ---------------------------------------------------------------------------
def _install_headless_stubs(monkeypatch):
    from PyQt6.QtCore import pyqtSignal
    from PyQt6.QtWidgets import QWidget

    class StubVisualizer(QWidget):
        """EmbeddedVisualizer owns a QOpenGLWidget (RenderEngine) and a
        500 ms FPS timer; neither survives the offscreen platform."""

        def __init__(self, parent=None):
            super().__init__(parent)
            self.config = None
            self.preview_mode = None
            self.fed = []

        def set_pop_out_callback(self, callback): pass
        def set_inner_pop_out_visible(self, visible): pass
        def set_config(self, config): self.config = config
        def set_preview_mode(self, mode): self.preview_mode = mode
        def set_highlighted_plane(self, *a, **k): pass
        def feed_dmx(self, universe, dmx): self.fed.append((universe, bytes(dmx)))
        def refresh_from_config(self, *a, **k): pass
        def cleanup(self): pass

    class StubOrientationPreview(QWidget):
        """OrientationPreviewWidget is a QOpenGLWidget + moderngl context."""

        orientation_changed = pyqtSignal(float, float, float)

        def __init__(self, parent=None):
            super().__init__(parent)
            self.mounting = "hanging"
            self.yaw = self.pitch = self.roll = 0.0

        def set_fixture_type(self, fixture_type, segment_count=8): pass

        def set_orientation(self, mounting, yaw, pitch, roll):
            self.mounting, self.yaw, self.pitch, self.roll = mounting, yaw, pitch, roll

        def cleanup(self): pass

    class StubRiffPanel(QWidget):
        def __init__(self, library=None, parent=None):
            super().__init__(parent)

    for module in ("gui.tabs.shows_tab", "gui.tabs.stage_tab", "gui.tabs.auto_tab"):
        monkeypatch.setattr(f"{module}.EmbeddedVisualizer", StubVisualizer)

    monkeypatch.setattr(
        "gui.dialogs.orientation_dialog.OrientationPreviewWidget",
        StubOrientationPreview)
    monkeypatch.setattr("gui.tabs.shows_tab.RiffBrowserPanel", StubRiffPanel)
    monkeypatch.setattr("gui.tabs.shows_tab.ShowsTab._get_shared_riff_library",
                        lambda self: None)

    # Enumerates USB serial ports.
    monkeypatch.setattr("gui.tabs.configuration_tab.get_device_display_names",
                        lambda: ["No Device"])
    # Scans the MIDI profile directory.
    monkeypatch.setattr("utils.midi_utils.discover_midi_profiles", lambda: [])
    # The auto tab persists its own settings file.
    from auto.settings import AutoModeSettings
    monkeypatch.setattr("auto.settings.load", lambda: AutoModeSettings())
    monkeypatch.setattr("auto.settings.save", lambda _s: None)

    # The auto tab idle-monitors the input level on tab activation
    # (2026-07-21): a real LiveAudioInput would open the developer's
    # actual microphone during e2e tab switches and the 720p golden
    # grabs. The stub refuses to initialize, so the meter renders its
    # deterministic empty state.
    from audio.live_input import GAIN_MAX, GAIN_MIN

    class StubLiveInput:
        def __init__(self, *a, **k):
            self._gain = 1.0

        def initialize(self, device_index=None): return False
        def start(self): return False
        def stop(self): pass
        def cleanup(self): pass
        def is_active(self): return False
        def raw_peak(self): return 0.0
        def gain(self): return self._gain

        def set_gain(self, gain):
            self._gain = float(min(GAIN_MAX, max(GAIN_MIN, gain)))

        @property
        def ring_buffer(self): return None

    monkeypatch.setattr("gui.tabs.auto_tab.LiveAudioInput", StubLiveInput)


def _warm_fixture_cache():
    """Pre-populate utils.fixture_utils._fixture_definitions_cache.

    ``FixturesTab._add_fixtures_from_qxf`` pops a modal loading dialog and
    spawns a QThread when a model is not yet cached. Warming the cache takes
    that branch out; it does not touch the code path under test.
    """
    from utils.fixture_utils import get_cached_fixture_definitions
    get_cached_fixture_definitions({(PAR_MFR, PAR_MODEL), (MH_MFR, MH_MODEL)})


@pytest.fixture(scope="session", autouse=True)
def _e2e_theme(qapp):
    from gui.theme_manager import ThemeManager
    ThemeManager().apply(qapp, "dark")


@pytest.fixture
def main_window(qapp, monkeypatch):
    """The real MainWindow, headless. Yields the window; cleans up hard.

    MainWindow.__init__ takes no config, so tests mutate ``window.config``
    through the tabs exactly as a user would.
    """
    from PyQt6.QtCore import QEvent
    from PyQt6.QtWidgets import QApplication

    _install_headless_stubs(monkeypatch)
    _warm_fixture_cache()

    from gui.gui import MainWindow
    window = MainWindow()

    # 1 Hz toolbar-status tick; nothing under test depends on it.
    window.status_timer.stop()
    # Never open sockets or the TCP server from the shows tab.
    window.shows_tab.artnet_enabled = False
    window.shows_tab.tcp_enabled = False
    # Never launch the standalone visualizer subprocess.
    monkeypatch.setattr(window, "_launch_visualizer", lambda *a, **k: None,
                        raising=False)

    # The tab bar is hidden and page_stack starts on the home screen.
    window.page_stack.setCurrentWidget(window.tabWidget)

    try:
        yield window
    finally:
        for tab in (window.shows_tab, window.stage_tab, window.auto_tab):
            try:
                tab.cleanup()
            except Exception:
                pass
        window.deleteLater()
        # DeferredDelete is not flushed by processEvents() at this nesting
        # level; without this, torn-down tabs accumulate and the next
        # ThemeManager.apply() repolishes half-dead widgets (native crash).
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
        QApplication.processEvents()


# Tab indices, from MainWindow._on_tab_changed / Ui_MainWindow.addTab order.
TAB_CONFIG, TAB_FIXTURES, TAB_STAGE, TAB_STRUCTURE, TAB_SHOWS, TAB_AUTO = range(6)


def goto_tab(window, index):
    """Switch tabs the way the user does, so on_tab_deactivated /
    on_tab_activated (i.e. save_to_config / update_from_config) both run."""
    from PyQt6.QtWidgets import QApplication
    window.tabWidget.setCurrentIndex(index)
    QApplication.processEvents()
