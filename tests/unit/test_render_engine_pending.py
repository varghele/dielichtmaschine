"""
Pending-state buffering in :class:`visualizer.renderer.engine.RenderEngine`.

``QOpenGLWidget.initializeGL`` only fires the first time the widget is
shown — so an embedded visualizer hosted on an inactive tab silently
dropped fixture / grid / DMX updates pushed at config-load time. The
engine now buffers them and flushes them in ``initializeGL``.

Since v1.5.5 the buffer is the engine's LAST state and is never cleared:
every ``initializeGL`` replays it, so a context Qt destroys and recreates
(widget reparented) comes back with its fixtures, grid, plane and DMX
instead of an empty stage.

This test pins the buffer-and-flush contract directly so it cannot
regress without breaking the test, regardless of which tab happens to
be visible at config-load time.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture
def engine(qapp):
    """A bare RenderEngine that has NOT had initializeGL fire yet — i.e.
    stage_renderer / fixture_manager are still ``None``. We never show
    the widget, so Qt won't call initializeGL on us."""
    from visualizer.renderer.engine import RenderEngine

    e = RenderEngine(parent=None)
    try:
        # Stop the 60 FPS render timer so it doesn't fire `update()` and
        # tickle GL initialisation underneath us mid-test.
        e.render_timer.stop()
        # Sanity: pre-init state should match what initializeGL guards.
        assert e.stage_renderer is None
        assert e.fixture_manager is None
        yield e
    finally:
        e.deleteLater()


def test_update_fixtures_before_init_is_buffered(engine):
    payload = [{"id": "f1", "x": 0, "y": 0, "z": 0}]
    engine.update_fixtures(payload)
    assert engine._last_fixtures is payload


def test_set_grid_size_before_init_is_buffered(engine):
    engine.set_grid_size(0.5)
    assert engine._last_grid_size == 0.5


def test_update_dmx_before_init_is_buffered_per_universe(engine):
    engine.update_dmx(0, b"\x01" * 512)
    engine.update_dmx(1, b"\x02" * 512)
    # Later push for universe 0 wins (we only need the latest frame).
    engine.update_dmx(0, b"\x03" * 512)
    assert set(engine._last_dmx.keys()) == {0, 1}
    assert engine._last_dmx[0] == b"\x03" * 512
    assert engine._last_dmx[1] == b"\x02" * 512


def test_flush_pushes_buffered_state_to_renderers(engine):
    payload = [{"id": "f1"}]
    engine.update_fixtures(payload)
    engine.set_grid_size(0.25)
    engine.update_dmx(0, b"\x10" * 512)
    engine.update_dmx(1, b"\x20" * 512)

    # Simulate initializeGL having created the renderers without
    # actually creating a GL context — we only care about the flush.
    engine.stage_renderer = MagicMock()
    engine.fixture_manager = MagicMock()

    engine._replay_state()

    engine.stage_renderer.set_grid_size.assert_called_once_with(0.25)
    engine.fixture_manager.update_fixtures.assert_called_once_with(payload)
    # Both universes flushed with their latest buffered frame.
    dmx_calls = engine.fixture_manager.update_dmx.call_args_list
    sent = {c.args[0]: c.args[1] for c in dmx_calls}
    assert sent == {0: b"\x10" * 512, 1: b"\x20" * 512}

    # Kept, not cleared: a recreated context replays the same state.
    assert engine._last_grid_size == 0.25
    assert engine._last_fixtures is payload
    assert set(engine._last_dmx) == {0, 1}


def test_flush_with_no_last_state_is_a_noop(engine):
    """Engines that received no updates before init shouldn't bother
    the renderers with empty calls during initializeGL."""
    engine.stage_renderer = MagicMock()
    engine.fixture_manager = MagicMock()

    engine._replay_state()

    engine.stage_renderer.set_grid_size.assert_not_called()
    engine.fixture_manager.update_fixtures.assert_not_called()
    engine.fixture_manager.update_dmx.assert_not_called()


def test_post_init_calls_go_straight_through_and_are_remembered(engine):
    """Once renderers exist, setters go straight through, and the last
    value is remembered for a context recreation."""
    engine.stage_renderer = MagicMock()
    engine.fixture_manager = MagicMock()
    # The setters call makeCurrent / doneCurrent on the widget; stub
    # them out so we don't trip over a missing GL context.
    engine.makeCurrent = MagicMock()
    engine.doneCurrent = MagicMock()

    engine.update_fixtures([{"id": "f"}])
    engine.set_grid_size(0.5)
    engine.update_dmx(0, b"\x00" * 512)

    assert engine._last_fixtures == [{"id": "f"}]
    assert engine._last_grid_size == 0.5
    assert engine._last_dmx == {0: b"\x00" * 512}
    engine.fixture_manager.update_fixtures.assert_called_once()
    engine.stage_renderer.set_grid_size.assert_called_once_with(0.5)
    engine.fixture_manager.update_dmx.assert_called_once()


def test_recreated_context_replays_the_last_state(engine, monkeypatch):
    """docs/v1.5.5-hardening-plan.md handover #3: after Qt destroys the
    context (aboutToBeDestroyed -> _release_gl) and recreates it,
    initializeGL built empty renderers and the stage came back without
    fixtures. Renderer classes and moderngl are mocked: no GL needed."""
    import visualizer.renderer.engine as engine_mod

    built = {}

    def factory(name):
        def make(*args, **kwargs):
            mock = MagicMock(name=name)
            built.setdefault(name, []).append(mock)
            return mock
        return make

    for name in ("StageRenderer", "StagePlaneHighlight", "CoordinateGizmo",
                 "FixtureManager", "HDRPipeline"):
        monkeypatch.setattr(engine_mod, name, factory(name))
    monkeypatch.setattr(engine_mod.moderngl, "create_context",
                        lambda **kw: MagicMock(name="ctx"))
    engine.makeCurrent = MagicMock()
    engine.doneCurrent = MagicMock()
    engine.defaultFramebufferObject = MagicMock(return_value=0)
    engine._hook_context_teardown = MagicMock()

    engine.initializeGL()
    payload = [{"id": "f1"}]
    engine.update_fixtures(payload)
    engine.set_grid_size(0.5)
    engine.set_highlighted_plane("Floor", rig_height=4.0)
    engine.update_dmx(0, b"\x07" * 512)

    engine._release_gl()
    assert engine.fixture_manager is None
    engine.initializeGL()

    fixtures = built["FixtureManager"][-1]
    assert len(built["FixtureManager"]) == 2
    fixtures.update_fixtures.assert_called_once_with(payload)
    fixtures.update_dmx.assert_called_once_with(0, b"\x07" * 512)
    built["StageRenderer"][-1].set_grid_size.assert_called_once_with(0.5)
    planes = built["StagePlaneHighlight"][-1]
    planes.set_rig_height.assert_called_once_with(4.0)
    planes.set_highlight.assert_called_once_with("Floor")
