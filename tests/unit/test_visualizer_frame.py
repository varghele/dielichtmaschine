# tests/unit/test_visualizer_frame.py
"""The standalone visualizer's window frame wears the brand
(visualizer/main.py): rotor glyph + wordmark header with chip actions
instead of the stock QToolBar, mono statusbar with token-driven state
colors and the brand separator, no hardcoded hex.

The GL engine, ArtNet listener and TCP client are stubbed - these
tests pin the FRAME (the scene is renderer territory, tested
elsewhere), and must not bind sockets or need a GL context.
"""

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import pyqtSignal, QObject
from PyQt6.QtWidgets import QWidget


class _StubEngine(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.dmx_calls = []   # (universe, bytes) pushed by the window

    def set_stage_size(self, w, h):
        pass

    def set_grid_size(self, g):
        pass

    def get_fps(self):
        return 60.0

    def update_dmx(self, universe, data):
        self.dmx_calls.append((universe, bytes(data)))

    def update_fixtures(self, fixtures):
        pass

    def reset_camera(self):
        pass

    def cleanup(self):
        pass


class _StubTCPClient(QObject):
    connected = pyqtSignal()
    disconnected = pyqtSignal()
    connection_error = pyqtSignal(str)
    stage_received = pyqtSignal(float, float, float)
    fixtures_received = pyqtSignal(list)
    groups_received = pyqtSignal(list)
    update_received = pyqtSignal(dict)
    host = "127.0.0.1"
    port = 9000

    def connect_to_host(self):
        pass

    def connect(self):  # noqa: A003 - mirrors the real client API
        pass

    def disconnect(self):
        pass


class _StubListener(QObject):
    dmx_received = pyqtSignal(int, bytes)
    receiving_started = pyqtSignal()
    receiving_stopped = pyqtSignal()
    error_occurred = pyqtSignal(str)

    def start(self):
        pass

    def stop(self):
        pass


@pytest.fixture
def window(qapp, monkeypatch):
    import visualizer.main as vis_main

    monkeypatch.setattr(vis_main, "RenderEngine", _StubEngine)
    monkeypatch.setattr(vis_main, "VisualizerTCPClient", _StubTCPClient)
    monkeypatch.setattr(vis_main, "ArtNetListener", _StubListener)

    from gui.theme_manager import ThemeManager
    ThemeManager().apply(qapp, "dark")

    win = vis_main.VisualizerWindow()
    yield win
    win.status_timer.stop()
    win.deleteLater()


class TestVisualizerFrame:
    def test_title_carries_the_brand(self, window):
        from utils.app_identity import APP_NAME
        assert window.windowTitle() == f"{APP_NAME} · Visualizer"

    def test_header_is_the_themed_topbar(self, window):
        header = window.centralWidget().layout().itemAt(0).widget()
        assert header.objectName() == "TopBar"
        assert header.height() == 48 or header.maximumHeight() == 48

    def test_header_actions_are_chips(self, window):
        for btn, text in ((window.connect_btn, "CONNECT"),
                          (window.reset_view_btn, "RESET VIEW"),
                          (window.help_btn, "HELP")):
            assert btn.property("role") == "output-select"
            assert btn.text() == text

    def test_connect_button_swaps_with_the_indicator(self, window):
        window._update_tcp_indicator(True)
        assert window.connect_btn.text() == "DISCONNECT"
        assert "TCP CONNECTED" == window.tcp_status_label.text()
        window._update_tcp_indicator(False)
        assert window.connect_btn.text() == "CONNECT"
        assert "TCP OFFLINE" == window.tcp_status_label.text()

    def test_status_colors_come_from_the_tokens(self, window):
        # Never hardcoded hex: the label styles carry the theme's own
        # token values for both states.
        tokens = window._tokens
        window._update_artnet_indicator(True)
        assert tokens["success"] in window.artnet_status_label.styleSheet()
        window._update_artnet_indicator(False)
        assert tokens["text_disabled"] in \
            window.artnet_status_label.styleSheet()

    def test_statusbar_reads_mono_caps(self, window):
        assert window.artnet_status_label.text() == "ARTNET NO DATA"
        assert window.stage_info_label.text().startswith("STAGE ")
        assert window.fixture_count_label.text() == "FIXTURES 0"

    def test_stage_info_updates(self, window):
        window.set_stage_dimensions(8.0, 6.0, 0.5)
        assert window.stage_info_label.text() == "STAGE 8.0 x 6.0 m"


# One 6-channel RGB par at U1@10 and one mover-ish fixture at U2@1;
# channel_mapping keys as strings, like after the JSON round-trip.
_RIG = [
    {"name": "P1", "universe": 1, "address": 10,
     "channel_mapping": {"0": "dimmer", "1": "red", "2": "green",
                         "3": "blue", "4": "shutter", "5": "gobo"}},
    {"name": "M1", "universe": 2, "address": 1,
     "channel_mapping": {"0": "pan", "2": "tilt", "5": "dimmer"}},
]


class TestBuildLookToggle:
    """The BUILD chip: synthetic full-on rig look for checking
    orientation / beam direction without live DMX."""

    def test_chip_exists_and_is_a_toggle(self, window):
        assert window.build_btn.text() == "BUILD"
        assert window.build_btn.isCheckable()
        assert window.build_btn.property("role") == "output-select"
        assert not window.build_mode

    def test_toggle_on_pushes_the_synthetic_look(self, window):
        window.set_fixtures(list(_RIG))
        window.render_engine.dmx_calls.clear()
        window.build_btn.setChecked(True)
        assert window.build_mode
        pushed = dict(window.render_engine.dmx_calls)
        # U1: par at address 10 -> base index 9.
        assert pushed[1][9] == 255       # dimmer
        assert pushed[1][10] == 255      # red
        assert pushed[1][13] == 255      # shutter open
        assert pushed[1][14] == 0        # gobo stays off
        # U2: mover at address 1 -> pan/tilt centred, dimmer up.
        assert pushed[2][0] == 128       # pan
        assert pushed[2][2] == 128       # tilt
        assert pushed[2][5] == 255       # dimmer

    def test_live_dmx_is_ignored_while_on(self, window):
        window.set_fixtures(list(_RIG))
        window.build_btn.setChecked(True)
        window.render_engine.dmx_calls.clear()
        window._on_dmx_received(0, bytes(512))   # ArtNet path
        window.update_dmx(1, bytes(512))         # public path
        assert window.render_engine.dmx_calls == []

    def test_toggle_off_clears_to_reality(self, window):
        window.set_fixtures(list(_RIG))
        window.build_btn.setChecked(True)
        window.render_engine.dmx_calls.clear()
        window.build_btn.setChecked(False)
        assert not window.build_mode
        # The universes the look filled are zeroed, not frozen lit.
        pushed = dict(window.render_engine.dmx_calls)
        assert pushed[1] == bytes(512)
        assert pushed[2] == bytes(512)
        # ...and live DMX flows again.
        window.render_engine.dmx_calls.clear()
        window._on_dmx_received(0, bytes([7] * 512))
        assert window.render_engine.dmx_calls == [(1, bytes([7] * 512))]

    def test_rig_update_while_on_refreshes_the_look(self, window):
        window.set_fixtures(list(_RIG))
        window.build_btn.setChecked(True)
        window.render_engine.dmx_calls.clear()
        window.set_fixtures(list(_RIG))          # re-sent rig
        pushed = dict(window.render_engine.dmx_calls)
        assert pushed and pushed[1][9] == 255
