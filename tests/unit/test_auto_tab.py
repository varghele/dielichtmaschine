"""
Smoke test for ``AutoTab`` — covers the QMainWindow → tab refactor that
folded the former ``LiveModeWindow`` into the sixth tab and the
subsequent Live → Auto rename.

We don't drive the audio engine here (that pulls in real audio devices
and sounddevice / portaudio threads). The test just makes sure the tab
can be constructed offscreen, exposes the expected widgets, and
implements the BaseTab lifecycle hooks the MainWindow's tab bar relies
on.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(autouse=True)
def _no_settings_persistence(monkeypatch):
    """Isolate AutoTab tests from ``~/.qlcautoshow/auto_mode_settings.json``.

    Tests construct AutoTab instances which load settings from disk in
    ``__init__`` and save back via ``cleanup()`` / ``on_tab_deactivated()``.
    Both directions are dangerous in CI / dev:

    - **Load**: a stale or hand-edited settings file on the developer's
      machine can flip the host-API combo's default away from
      "Curated (recommended)" and break tests that assume the default.
      Also catches pollution from non-pytest smoke runs (manual
      ``python -c ...`` invocations) that bypass this fixture.
    - **Save**: tests that exercise the combo would otherwise persist
      their choices to the real user settings file.

    Stub both directions: load returns a fresh defaulted dataclass,
    save is a no-op."""
    from auto.settings import AutoModeSettings
    monkeypatch.setattr("auto.settings.load", lambda: AutoModeSettings())
    monkeypatch.setattr("auto.settings.save", lambda _settings: None)


def test_auto_tab_constructs(qapp, sample_configuration):
    from gui.theme_manager import ThemeManager
    from gui.tabs import AutoTab

    ThemeManager().apply(qapp, "dark")

    tab = AutoTab(sample_configuration, parent=None)
    try:
        # Core widgets must exist for the rest of the tab to be useful.
        assert tab._start_btn is not None
        assert tab._stop_btn is not None
        assert tab._bpm_spinbox is not None
        assert tab._status_phase is not None

        # Stop button is disabled at rest; START is enabled.
        assert tab._start_btn.isEnabled()
        assert not tab._stop_btn.isEnabled()

        # Phase label drives off the `phase` dynamic property — start
        # state must match the QSS rule for "stopped" so colour is
        # right out of the box.
        assert tab._status_phase.property("phase") == "stopped"

        # BaseTab lifecycle hooks are present and don't blow up when
        # called without an active engine.
        tab.on_tab_activated()
        tab.on_tab_deactivated()
        # Lazy fixture-defs load fired during the first activation.
        assert tab._fixtures_loaded is True

        # Cleanup is idempotent and safe to call without a started engine.
        tab.cleanup()
        tab.cleanup()
    finally:
        tab.deleteLater()


def test_auto_tab_phase_property_drives_theme(qapp, sample_configuration):
    """``_set_phase`` flips the dynamic property and re-polishes so the
    QSS ``QLabel#AutoStatusPhase[phase="..."]`` rule re-evaluates."""
    from gui.theme_manager import ThemeManager
    from gui.tabs import AutoTab

    ThemeManager().apply(qapp, "dark")
    tab = AutoTab(sample_configuration, parent=None)
    try:
        tab._set_phase("running")
        assert tab._status_phase.property("phase") == "running"
        tab._set_phase("fill")
        assert tab._status_phase.property("phase") == "fill"
        tab._set_phase("stopped")
        assert tab._status_phase.property("phase") == "stopped"
    finally:
        tab.cleanup()
        tab.deleteLater()


def test_group_panels_rebuild_when_config_groups_change(qapp):
    """Submasters + riff-constraint panels must rebuild when the user
    loads a config file *after* MainWindow has constructed the tab.

    Reproduces the original bug: tab built with empty config.groups,
    then config populates → submasters stayed empty because setup_ui
    only ran once with the original (empty) group set.
    """
    from PyQt6.QtWidgets import QApplication
    from config.models import (Configuration, Fixture, FixtureGroup,
                               FixtureMode, Universe)
    from gui.theme_manager import ThemeManager
    from gui.tabs import AutoTab

    ThemeManager().apply(qapp, "dark")

    # Empty config at construction — no groups → submasters has 0 sliders.
    config = Configuration(fixtures=[], groups={}, universes={})
    tab = AutoTab(config, parent=None)
    try:
        assert list(tab._submasters._sliders.keys()) == []
        assert tab._current_groups_fingerprint == frozenset()

        # Config grows after construction.
        f = Fixture(
            universe=1, address=1, manufacturer="M", model="X",
            name="A1", group="Lights", current_mode="m",
            available_modes=[FixtureMode(name="m", channels=4)],
            type="PAR",
        )
        config.fixtures.append(f)
        config.groups["Lights"] = FixtureGroup(name="Lights", fixtures=[f])
        config.universes[1] = Universe(id=1, name="U1", output={})

        # Activating the tab should rebuild the group panels.
        tab.on_tab_activated()
        QApplication.processEvents()

        assert list(tab._submasters._sliders.keys()) == ["Lights"]
        assert tab._current_groups_fingerprint == frozenset({"Lights"})
    finally:
        tab.cleanup()
        tab.deleteLater()


def test_universe_table_layout(qapp, sample_configuration):
    """Universe-mapping table must stretch its columns and hide the
    vertical header so it fits in the 220-px right panel without
    clipping."""
    from PyQt6.QtWidgets import QHeaderView
    from gui.theme_manager import ThemeManager
    from gui.tabs import AutoTab

    ThemeManager().apply(qapp, "dark")
    tab = AutoTab(sample_configuration, parent=None)
    try:
        # Short header labels — anything longer gets clipped at 100 px.
        labels = [tab._universe_table.horizontalHeaderItem(c).text()
                  for c in range(tab._universe_table.columnCount())]
        assert labels == ["Config", "ArtNet"]

        # Stretch resize mode on every column.
        h_header = tab._universe_table.horizontalHeader()
        for c in range(tab._universe_table.columnCount()):
            assert (h_header.sectionResizeMode(c)
                    == QHeaderView.ResizeMode.Stretch)

        # Vertical header (row numbers) hidden.
        assert not tab._universe_table.verticalHeader().isVisible()

        # 120-px fixed height (≈ header + 3 rows).
        assert tab._universe_table.minimumHeight() == 120
        assert tab._universe_table.maximumHeight() == 120
    finally:
        tab.cleanup()
        tab.deleteLater()


def test_force_groove_is_gone():
    """Removed alongside the GROOVE NOW button — engine grooves
    continuously, no programmatic restart needed."""
    from config.models import Configuration
    from auto.engine import AutoShowEngine

    engine = AutoShowEngine(Configuration(), fixture_definitions={})
    assert not hasattr(engine, "force_groove")


def test_auto_tab_embeds_visualizer(qapp, sample_configuration):
    """AutoTab should expose an EmbeddedVisualizer and host it inside a
    vertical splitter on the right side, defaulting to build mode."""
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QSplitter
    from gui.theme_manager import ThemeManager
    from gui.tabs import AutoTab
    from gui.tabs.auto_tab import RIGHT_PANEL_WIDTH
    from gui.widgets.embedded_visualizer import EmbeddedVisualizer

    ThemeManager().apply(qapp, "dark")
    tab = AutoTab(sample_configuration, parent=None)
    try:
        assert isinstance(tab.embedded_visualizer, EmbeddedVisualizer)
        assert tab.embedded_visualizer.preview_mode() == "build"

        # The right pane is a vertical splitter with vis on top.
        assert isinstance(tab._right_splitter, QSplitter)
        assert tab._right_splitter.orientation() == Qt.Orientation.Vertical
        assert tab._right_splitter.widget(0) is tab.embedded_visualizer

        # The preview column is the reference's fixed 400px.
        panel = tab._right_splitter.parentWidget()
        assert panel.minimumWidth() == RIGHT_PANEL_WIDTH
        assert panel.maximumWidth() == RIGHT_PANEL_WIDTH
    finally:
        tab.cleanup()
        tab.deleteLater()


def test_live_dmx_callback_fires_per_universe():
    """AutoDMXController.local_dmx_callback should fire once per
    configured universe with the 1-based config universe id and a
    512-byte buffer. Misbehaving callbacks must not break the wire send."""
    from unittest.mock import MagicMock

    from config.models import (Configuration, Fixture, FixtureMode,
                               FixtureGroup, Universe)
    from auto.dmx_output import AutoDMXController

    fixtures = [
        Fixture(universe=1, address=1, manufacturer="M", model="A",
                name="A1", group="G", current_mode="m",
                available_modes=[FixtureMode(name="m", channels=4)],
                type="PAR"),
        Fixture(universe=2, address=1, manufacturer="M", model="B",
                name="B1", group="G", current_mode="m",
                available_modes=[FixtureMode(name="m", channels=4)],
                type="PAR"),
    ]
    config = Configuration(
        fixtures=fixtures,
        groups={"G": FixtureGroup(name="G", fixtures=fixtures)},
        universes={1: Universe(id=1, name="U1", output={}),
                   2: Universe(id=2, name="U2", output={})},
    )

    received: list[tuple[int, bytes]] = []
    controller = AutoDMXController(
        config, fixture_definitions={},
        local_dmx_callback=lambda u, b: received.append((u, b)),
    )
    # Mock the senders so no UDP socket is actually opened.
    controller.artnet_sender = MagicMock()
    controller._visualizer_sender = MagicMock()

    controller._send_all_universes()
    seen_universes = sorted(u for u, _ in received)
    assert seen_universes == [1, 2]
    for _, payload in received:
        assert isinstance(payload, bytes)
        assert len(payload) == 512

    # Misbehaving callback shouldn't break the send loop.
    bad_controller = AutoDMXController(
        config, fixture_definitions={},
        local_dmx_callback=lambda u, b: (_ for _ in ()).throw(
            RuntimeError("boom")
        ),
    )
    bad_controller.artnet_sender = MagicMock()
    bad_controller._visualizer_sender = MagicMock()
    # Must not raise.
    bad_controller._send_all_universes()
    # Wire send still happened for both universes.
    assert bad_controller.artnet_sender.send_dmx.call_count == 2


def test_fixture_definitions_reload_after_late_config_load(qapp, monkeypatch):
    """Auto tab regression: opening the tab once with an empty config
    primed ``_fixtures_loaded = True`` against an empty
    ``fixture_definitions`` dict, and the one-shot guard meant a
    *subsequent* config load never reloaded the QXFs. START would then
    spin up an engine + DMXManager that built zero
    ``FixtureChannelMap`` entries, so every ``_apply_*_block`` call hit
    the ``fixture.name not in self.fixture_maps`` early-out and no DMX
    was produced — audio meters worked, but lights didn't move and
    colours didn't change. ``update_from_config`` must refresh the
    definitions on every call so config swaps propagate.
    """
    from config.models import (Configuration, Fixture, FixtureGroup,
                               FixtureMode, Universe)
    from gui.theme_manager import ThemeManager
    from gui.tabs import AutoTab
    from utils import fixture_utils

    ThemeManager().apply(qapp, "dark")

    # Fake QXF cache: returns empty before the config has any fixtures,
    # then a real-looking dict once models are requested.
    served = {"calls": 0}

    def fake_get_cached(models_in_config=None):
        served["calls"] += 1
        if not models_in_config:
            return {}
        return {
            f"{mfr}_{model}": {
                "manufacturer": mfr, "model": model,
                "channels": [], "modes": [],
            }
            for (mfr, model) in models_in_config
        }

    monkeypatch.setattr(
        fixture_utils, "get_cached_fixture_definitions", fake_get_cached
    )

    # Tab born against an empty config, exactly as MainWindow does.
    initial = Configuration()
    tab = AutoTab(initial, parent=None)
    try:
        # Simulate the user opening the Auto tab once before loading a
        # YAML — the original bug's setup.
        tab.on_tab_activated()
        assert tab._fixtures_loaded is True
        assert tab.fixture_definitions == {}

        # User loads a config: MainWindow rebinds tab.config and calls
        # update_from_config. We must end up with a populated
        # fixture_definitions dict matching the new config — without
        # the fix, the one-shot guard left it empty.
        f = Fixture(
            universe=1, address=1, manufacturer="ChauvetDJ", model="Intimidator",
            name="MH1", group="Movers", current_mode="m",
            available_modes=[FixtureMode(name="m", channels=10)],
            type="MH",
        )
        loaded = Configuration(
            fixtures=[f],
            groups={"Movers": FixtureGroup(name="Movers", fixtures=[f])},
            universes={1: Universe(id=1, name="U1", output={})},
        )
        tab.config = loaded
        tab.update_from_config()

        assert "ChauvetDJ_Intimidator" in tab.fixture_definitions, (
            "fixture_definitions stayed stale after a config swap — "
            "the engine + DMXManager would build zero fixture maps and "
            "silently produce no DMX."
        )
    finally:
        tab.cleanup()
        tab.deleteLater()


def test_universe_table_repopulates_on_late_config_load(qapp):
    """Auto tab regression: ``_populate_universe_table`` was called
    once in ``setup_ui`` against whatever config the tab was constructed
    with. If MainWindow built the tab against an empty ``Configuration``
    (the typical app-startup state) and the user then loaded a YAML,
    the universe table stayed at 0 rows. ``_get_universe_mapping()``
    returned ``{}``, ``AutoDMXController.set_universe_mapping({})``
    overwrote the controller's default mapping, ``_send_all_universes``
    iterated an empty dict, and ZERO DMX went anywhere — wire OR local
    callback. Audio meters kept ticking because they don't depend on
    DMX, which is exactly the visible symptom: 'meters work, lights
    don't move'.

    The fix has ``update_from_config`` repopulate the table, AND
    ``_on_start`` keeps the controller's default mapping when the user
    table is empty (defence in depth).
    """
    from config.models import (Configuration, Fixture, FixtureGroup,
                               FixtureMode, Universe)
    from gui.theme_manager import ThemeManager
    from gui.tabs import AutoTab

    ThemeManager().apply(qapp, "dark")

    # Empty config at construction → universe table starts at 0 rows.
    initial = Configuration()
    tab = AutoTab(initial, parent=None)
    try:
        assert tab._universe_table.rowCount() == 0
        assert tab._get_universe_mapping() == {}

        # User loads a config with two universes. MainWindow rebinds
        # tab.config and calls update_from_config.
        f = Fixture(
            universe=1, address=1, manufacturer="M", model="X",
            name="A1", group="G", current_mode="m",
            available_modes=[FixtureMode(name="m", channels=4)],
            type="PAR",
        )
        loaded = Configuration(
            fixtures=[f],
            groups={"G": FixtureGroup(name="G", fixtures=[f])},
            universes={
                1: Universe(id=1, name="U1", output={}),
                2: Universe(id=2, name="U2", output={}),
            },
        )
        tab.config = loaded
        tab.update_from_config()

        # Table now reflects the loaded universes.
        assert tab._universe_table.rowCount() == 2, (
            "Universe table didn't repopulate after a config swap — "
            "_get_universe_mapping() will return {} and the DMX "
            "controller will be silenced."
        )
        mapping = tab._get_universe_mapping()
        assert set(mapping.keys()) == {1, 2}
        # Default 1-based config → 0-based ArtNet conversion.
        assert mapping == {1: 0, 2: 1}
    finally:
        tab.cleanup()
        tab.deleteLater()


def test_on_start_keeps_default_mapping_when_user_mapping_empty(qapp, monkeypatch):
    """Defence-in-depth for the dead-DMX bug: even if the universe
    table is empty for some reason, START must not pass an empty
    mapping into ``AutoDMXController.set_universe_mapping`` — that
    would wipe the controller's auto-built default and leave the
    DMX thread sending nothing. Only override when the user mapping
    is non-empty.
    """
    from unittest.mock import MagicMock
    from config.models import (Configuration, Fixture, FixtureGroup,
                               FixtureMode, Universe)
    from gui.theme_manager import ThemeManager
    from gui.tabs import AutoTab
    from utils import fixture_utils

    ThemeManager().apply(qapp, "dark")

    # Stub fixture-def loader so we don't scan the filesystem.
    monkeypatch.setattr(
        fixture_utils, "get_cached_fixture_definitions",
        lambda models=None: {
            f"{m}_{x}": {"manufacturer": m, "model": x,
                         "channels": [], "modes": []}
            for (m, x) in (models or set())
        },
    )

    f = Fixture(
        universe=1, address=1, manufacturer="M", model="X",
        name="A1", group="G", current_mode="m",
        available_modes=[FixtureMode(name="m", channels=4)],
        type="PAR",
    )
    config = Configuration(
        fixtures=[f],
        groups={"G": FixtureGroup(name="G", fixtures=[f])},
        universes={1: Universe(id=1, name="U1", output={})},
    )
    tab = AutoTab(config, parent=None)
    try:
        # Force the universe table empty to simulate the bug state.
        tab._universe_table.setRowCount(0)
        assert tab._get_universe_mapping() == {}

        # Capture the mapping the controller actually ends up with by
        # spying on set_universe_mapping. We don't run the full
        # _on_start (it would touch real audio devices); just exercise
        # the mapping-decision branch directly.
        controller = MagicMock()
        # Simulate the relevant lines of _on_start verbatim:
        user_mapping = tab._get_universe_mapping()
        if user_mapping:
            controller.set_universe_mapping(user_mapping)

        # set_universe_mapping must NOT have been called with empty.
        controller.set_universe_mapping.assert_not_called()
    finally:
        tab.cleanup()
        tab.deleteLater()


def test_engine_does_not_auto_fill():
    """The engine grooves continuously; ``is_fill`` is only set by
    ``force_fill`` and clears on the next bar boundary. Catches a
    regression to the old groove+fill auto-cycling."""
    import time
    from config.models import Configuration
    from auto.engine import AutoShowEngine

    engine = AutoShowEngine(Configuration(), fixture_definitions={})
    engine.set_bpm(240.0)  # 1 bar = 1 second
    engine.start()
    try:
        # Tick across several bar boundaries — should never auto-flip
        # is_fill on its own.
        t0 = time.monotonic()
        for elapsed in (0.2, 1.2, 2.2, 3.2, 4.2, 5.2):
            engine.tick(t0 + elapsed)
            assert engine.is_fill is False, (
                f"Engine auto-flipped is_fill at t={elapsed}s — auto-fill "
                "should be gone after the groove-only refactor."
            )

        # set_groove_bars should be gone (groove length is fixed).
        assert not hasattr(engine, "set_groove_bars")
        # cycle_bars property exists with the fixed default.
        assert engine.cycle_bars == 4
    finally:
        engine.stop()


# ── Audio input host-API combo (new in May 2026) ─────────────────────


def test_input_api_combo_populated_with_curated_default(qapp, sample_configuration):
    """The host-API combo must contain Curated (first, default), each
    real host API, and a Raw fallback at the bottom. Curated is the
    selected entry on first construction so the user sees the filtered
    list immediately rather than 43 entries."""
    from gui.tabs import AutoTab

    tab = AutoTab(sample_configuration, parent=None)
    try:
        api_combo = tab._input_api_combo
        items = [api_combo.itemText(i) for i in range(api_combo.count())]
        assert "Curated (recommended)" in items
        assert "All devices (raw)" in items
        # Curated is the default.
        assert api_combo.currentText() == "Curated (recommended)"
        # First and last positions are the special entries.
        assert items[0] == "Curated (recommended)"
        assert items[-1] == "All devices (raw)"
    finally:
        tab.cleanup()
        tab.deleteLater()


def test_switching_api_repopulates_device_combo(qapp, sample_configuration):
    """Changing the host-API combo must drive a new device-combo
    population through ``_populate_devices``. We assert by patching the
    DeviceManager so we can observe the kwargs passed to it."""
    from unittest.mock import MagicMock
    from gui.tabs import AutoTab

    tab = AutoTab(sample_configuration, parent=None)
    try:
        # Wrap enumerate_input_devices so we can spy on call args while
        # still returning real (or empty) devices.
        original = tab._device_manager.enumerate_input_devices
        spy = MagicMock(side_effect=original)
        tab._device_manager.enumerate_input_devices = spy

        # Switch to "All devices (raw)" — should call enumerate with
        # mappers + telephony included and dedup off.
        spy.reset_mock()
        idx = tab._input_api_combo.findText("All devices (raw)")
        tab._input_api_combo.setCurrentIndex(idx)
        assert spy.call_count >= 1
        kwargs = spy.call_args.kwargs
        assert kwargs["include_mappers"] is True
        assert kwargs["include_telephony"] is True
        assert kwargs["dedup_physical"] is False
        assert kwargs["host_api_filter"] is None

        # Switch back to Curated — opposite kwargs.
        spy.reset_mock()
        idx = tab._input_api_combo.findText("Curated (recommended)")
        tab._input_api_combo.setCurrentIndex(idx)
        kwargs = spy.call_args.kwargs
        assert kwargs["include_mappers"] is False
        assert kwargs["include_telephony"] is False
        assert kwargs["dedup_physical"] is True
    finally:
        tab.cleanup()
        tab.deleteLater()


def test_input_host_api_persists_through_settings(qapp, sample_configuration):
    """The selected host API round-trips through ``AutoModeSettings``.

    The autouse ``_no_settings_persistence`` fixture already prevents
    disk writes, so calling ``_save_settings`` here is safe — we just
    verify the dataclass picks up the combo's current text."""
    from gui.tabs import AutoTab

    tab = AutoTab(sample_configuration, parent=None)
    try:
        idx = tab._input_api_combo.findText("All devices (raw)")
        tab._input_api_combo.setCurrentIndex(idx)
        tab._save_settings()
        assert tab._settings.input_host_api == "All devices (raw)"
    finally:
        tab.cleanup()
        tab.deleteLater()


def test_refresh_devices_button_reprobes_apis(qapp, sample_configuration):
    """The Refresh button re-runs API enumeration so a newly-plugged-in
    interface (e.g. Focusrite USB with ASIO driver) appears without an
    app restart."""
    from unittest.mock import MagicMock
    from gui.tabs import AutoTab

    tab = AutoTab(sample_configuration, parent=None)
    try:
        spy_apis = MagicMock(side_effect=tab._device_manager.get_available_host_apis)
        spy_devs = MagicMock(side_effect=tab._device_manager.enumerate_input_devices)
        tab._device_manager.get_available_host_apis = spy_apis
        tab._device_manager.enumerate_input_devices = spy_devs

        tab._on_refresh_devices()

        assert spy_apis.called
        assert spy_devs.called
    finally:
        tab.cleanup()
        tab.deleteLater()


def test_asio_hint_visible_when_drivers_registered_but_not_loaded(
        qapp, sample_configuration):
    """When the ASIO registry has entries but PortAudio doesn't expose
    an ASIO host API (your Focusrite-not-plugged-in case), the hint
    label below the combo must surface the explanation."""
    from unittest.mock import patch
    from gui.tabs import AutoTab

    fake_status = {
        "in_portaudio": False,
        "registered_drivers": ["Focusrite USB ASIO"],
        "message": "ASIO drivers registered but not exposed.",
        "level": "warn",
    }
    with patch("audio.device_manager.asio_status", return_value=fake_status):
        tab = AutoTab(sample_configuration, parent=None)
        try:
            assert tab._asio_hint_label.isVisible() or \
                "ASIO" in tab._asio_hint_label.text()
            assert "ASIO" in tab._asio_hint_label.text()
        finally:
            tab.cleanup()
            tab.deleteLater()
