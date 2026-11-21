"""
Cross-tab embedded-visualizer synchronisation.

Stage / Shows / Auto each own their own ``EmbeddedVisualizer`` and used
to refresh only their own on their own triggers — so changing stage
dimensions in Stage tab left the Shows / Auto previews stale, and
adding fixtures via the Fixtures tab left Auto's preview stale, until
the user manually activated each affected tab.

These tests pin the central
:meth:`MainWindow.on_visualizer_config_changed` propagation so a
regression to the old per-tab-only refresh is caught immediately.
"""

from __future__ import annotations

import os
import types
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _make_fake_main_with_visualizers():
    """Build a fake MainWindow with three tabs, each carrying a mock
    EmbeddedVisualizer. We only test the dispatch logic — the real
    method just iterates tab attribute names and calls
    ``embedded_visualizer.set_config`` on each.
    """
    from gui.gui import MainWindow

    fake = types.SimpleNamespace(
        config=object(),  # opaque placeholder; mocks just record it
        stage_tab=types.SimpleNamespace(embedded_visualizer=MagicMock()),
        shows_tab=types.SimpleNamespace(embedded_visualizer=MagicMock()),
        auto_tab=types.SimpleNamespace(embedded_visualizer=MagicMock()),
    )
    # Bind the unbound method to our fake — avoids having to construct a
    # real QMainWindow + every tab during the test.
    MainWindow.on_visualizer_config_changed(fake)
    return fake


def test_central_push_hits_every_tab_visualizer():
    fake = _make_fake_main_with_visualizers()
    fake.stage_tab.embedded_visualizer.set_config.assert_called_once_with(fake.config)
    fake.shows_tab.embedded_visualizer.set_config.assert_called_once_with(fake.config)
    fake.auto_tab.embedded_visualizer.set_config.assert_called_once_with(fake.config)


def test_one_tab_failure_does_not_block_the_others():
    """If one tab's set_config raises, the central push must still
    deliver the config to the other tabs."""
    from gui.gui import MainWindow

    fake = types.SimpleNamespace(
        config=object(),
        stage_tab=types.SimpleNamespace(embedded_visualizer=MagicMock()),
        shows_tab=types.SimpleNamespace(embedded_visualizer=MagicMock()),
        auto_tab=types.SimpleNamespace(embedded_visualizer=MagicMock()),
    )
    fake.shows_tab.embedded_visualizer.set_config.side_effect = (
        RuntimeError("preview engine unhappy")
    )

    # Must not raise.
    MainWindow.on_visualizer_config_changed(fake)

    # Other two tabs still received the config.
    fake.stage_tab.embedded_visualizer.set_config.assert_called_once_with(fake.config)
    fake.auto_tab.embedded_visualizer.set_config.assert_called_once_with(fake.config)


def test_missing_tab_or_visualizer_is_skipped():
    """Tabs without an ``embedded_visualizer`` attribute (or no tab at
    all) shouldn't break the propagation — Structure tab in particular
    has no embedded preview."""
    from gui.gui import MainWindow

    fake = types.SimpleNamespace(
        config=object(),
        stage_tab=types.SimpleNamespace(embedded_visualizer=MagicMock()),
        # shows_tab missing entirely
        auto_tab=types.SimpleNamespace(),  # no embedded_visualizer attr
    )
    # Must not raise.
    MainWindow.on_visualizer_config_changed(fake)
    fake.stage_tab.embedded_visualizer.set_config.assert_called_once_with(fake.config)


def test_stage_dim_change_propagates_via_spinbox(qapp, sample_configuration):
    """Driving ``stage_width`` (spinbox valueChanged) should reach the
    central broadcast even when no MainWindow is wired — ``_update_stage``
    falls back to a local refresh in that case, but it must still happen.
    """
    from gui.theme_manager import ThemeManager
    from gui.tabs import StageTab

    ThemeManager().apply(qapp, "dark")
    tab = StageTab(sample_configuration, parent=None)
    try:
        # Replace the embedded visualizer with a mock so we can see what
        # set_config gets called with without spinning up a real GL ctx.
        tab.embedded_visualizer = MagicMock()

        starting = sample_configuration.stage_width
        new_width = int(starting) + 5
        tab.stage_width.setValue(new_width)
        qapp.processEvents()

        # config mutated to the new width…
        assert sample_configuration.stage_width == float(new_width)
        # …and the visualizer received the updated config.
        tab.embedded_visualizer.set_config.assert_called()
        assert (
            tab.embedded_visualizer.set_config.call_args[0][0]
            is sample_configuration
        )
    finally:
        tab.deleteLater()


def test_update_stage_button_is_gone(qapp, sample_configuration):
    """The 'Update Stage' button used to fire the same handler the
    spinboxes already drove. It's been removed; this test pins that so
    we don't accidentally re-add a redundant control."""
    from gui.theme_manager import ThemeManager
    from gui.tabs import StageTab

    ThemeManager().apply(qapp, "dark")
    tab = StageTab(sample_configuration, parent=None)
    try:
        assert not hasattr(tab, "update_stage_btn"), (
            "Update Stage button is back — the spinboxes' valueChanged "
            "already drives _update_stage, so the button is redundant."
        )
    finally:
        tab.deleteLater()


def test_load_flow_propagates_config_to_auto_tab(qapp, sample_configuration):
    """When the user loads a YAML config file, MainWindow swaps
    self.config to a new Configuration instance. Every tab's
    ``self.config`` was bound at construction time and stays pointing
    at the OLD instance unless rebound — which is what
    ``_do_load_configuration`` does for each tab via
    ``self.X_tab.config = self.config``.

    Live tab was missed in that ladder for a long while: the visualizer
    rendered an empty stage after a load even though the other tabs
    showed all fixtures. This test pins the rebind + the central
    visualizer push so the regression can't sneak back in.
    """
    from config.models import (Configuration, Fixture, FixtureGroup,
                               FixtureMode, Universe)
    from gui.theme_manager import ThemeManager
    from gui.tabs import AutoTab

    ThemeManager().apply(qapp, "dark")

    # Live tab built against an empty starting config (mirrors the
    # state right after MainWindow.__init__ before any file is loaded).
    initial = Configuration()
    tab = AutoTab(initial, parent=None)
    try:
        tab.embedded_visualizer = MagicMock()
        assert tab.config is initial

        # Now pretend the user loaded a YAML file: a new Configuration
        # appears with fixtures + groups + universes. The MainWindow
        # load flow does `self.auto_tab.config = self.config` followed
        # by `self.auto_tab.update_from_config()`.
        f = Fixture(
            universe=1, address=1, manufacturer="M", model="X",
            name="A1", group="Lights", current_mode="m",
            available_modes=[FixtureMode(name="m", channels=4)],
            type="PAR",
        )
        loaded = Configuration(
            fixtures=[f],
            groups={"Lights": FixtureGroup(name="Lights", fixtures=[f])},
            universes={1: Universe(id=1, name="U1", output={})},
        )
        tab.config = loaded
        tab.update_from_config()
        qapp.processEvents()

        # Live tab is now operating on the loaded config.
        assert tab.config is loaded
        # Submasters rebuilt for the freshly-loaded group.
        assert list(tab._submasters._sliders.keys()) == ["Lights"]
        # Visualizer was handed the new config (not the empty initial).
        tab.embedded_visualizer.set_config.assert_called()
        last_call = tab.embedded_visualizer.set_config.call_args[0][0]
        assert last_call is loaded
    finally:
        tab.cleanup()
        tab.deleteLater()


def test_on_groups_changed_pushes_to_visualizers():
    """``MainWindow.on_groups_changed`` historically only refreshed the
    Stage/Shows tabs' visualizers (via update_from_config and
    update_fixture_groups_only). Live tab was left out. Verify the
    central push is now invoked too so all three previews stay synced
    when fixtures are added/removed via the Fixtures tab."""
    from gui.gui import MainWindow

    update_from_config_calls = []
    update_fixture_groups_calls = []
    visualizer_calls = []

    fake = types.SimpleNamespace(
        config=object(),
        stage_tab=types.SimpleNamespace(
            update_from_config=lambda: update_from_config_calls.append("stage"),
            embedded_visualizer=MagicMock(),
        ),
        structure_tab=types.SimpleNamespace(
            update_from_config=lambda: update_from_config_calls.append("structure"),
        ),
        shows_tab=types.SimpleNamespace(
            update_fixture_groups_only=lambda: update_fixture_groups_calls.append("shows"),
            embedded_visualizer=MagicMock(),
        ),
        auto_tab=types.SimpleNamespace(embedded_visualizer=MagicMock()),
    )
    # on_groups_changed delegates to self.on_visualizer_config_changed —
    # bind it to the fake so the lookup resolves.
    fake.on_visualizer_config_changed = lambda: (
        MainWindow.on_visualizer_config_changed(fake)
    )

    MainWindow.on_groups_changed(fake)

    # Existing per-tab refresh still happens.
    assert update_from_config_calls == ["stage", "structure"]
    assert update_fixture_groups_calls == ["shows"]

    # Plus the central push hits every embedded visualizer — including
    # Live, which was the regression we're guarding against.
    fake.stage_tab.embedded_visualizer.set_config.assert_called_once_with(fake.config)
    fake.shows_tab.embedded_visualizer.set_config.assert_called_once_with(fake.config)
    fake.auto_tab.embedded_visualizer.set_config.assert_called_once_with(fake.config)
