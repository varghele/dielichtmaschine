# tests/unit/test_render_engine_stage_size.py
"""RenderEngine.set_stage_size's redundant-call contract (2026-07-21):
set_config is documented "call me liberally" - three embedded engines
receive it on construction, every config rebind and song load - so an
UNCHANGED size must return without touching camera or renderers (the
old path re-applied everything and printed two lines per call, six-plus
times at startup). Safe because initializeGL re-applies the current
size to everything it creates. GL never initializes here: the engine
widget is constructed but never shown, so stage_renderer stays None
and the camera stub observes exactly what the guard lets through."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class _CameraSpy:
    def __init__(self):
        self.calls = []

    def set_stage_size(self, width, height):
        self.calls.append((width, height))

    def __getattr__(self, name):        # any other camera use is inert
        return lambda *a, **k: None


@pytest.fixture
def engine(qapp):
    from visualizer.renderer.engine import RenderEngine
    widget = RenderEngine()
    widget.camera = _CameraSpy()
    yield widget
    widget.deleteLater()


class TestStageSizeGuard:

    def test_changed_size_applies(self, engine):
        engine.set_stage_size(14.0, 28.0)
        assert (engine.stage_width, engine.stage_height) == (14.0, 28.0)
        assert engine.camera.calls == [(14.0, 28.0)]

    def test_unchanged_size_is_a_silent_no_op(self, engine):
        engine.set_stage_size(14.0, 28.0)
        engine.camera.calls.clear()
        engine.set_stage_size(14.0, 28.0)      # the redundant rebind call
        engine.set_stage_size(14.0, 28.0)
        assert engine.camera.calls == []

    def test_second_change_applies_again(self, engine):
        engine.set_stage_size(14.0, 28.0)
        engine.set_stage_size(10.0, 6.0)
        assert engine.camera.calls == [(14.0, 28.0), (10.0, 6.0)]
        assert (engine.stage_width, engine.stage_height) == (10.0, 6.0)
