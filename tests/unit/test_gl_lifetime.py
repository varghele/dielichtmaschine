"""GL widget lifetime: render timers, context-current teardown, per-frame
allocations (v1.5.5 hardening, group G9).

Four bugs pinned here:

- ``RenderEngine`` released its moderngl objects without making its own
  context current, so the GL deletes landed in whatever context happened
  to be current (another embedded engine's, or none), and the release
  only ran from ``closeEvent``, which an embedded child widget never
  receives. Teardown now runs with ``makeCurrent()`` and is hooked to
  the Qt context's ``aboutToBeDestroyed``, the pattern the Qt docs
  prescribe for QOpenGLWidget.
- The 60 fps render timers (three embedded engines plus the orientation
  preview) were unparented and ticked from construction on, also while
  their tab was hidden. They are parented now and only run while the
  widget is shown.
- The orientation preview built and freed a VBO pair plus a VAO for the
  beam indicator on every frame; it now builds it once.
- ``EmbeddedVisualizer.cleanup`` stopped only its FPS poll and left the
  engine's GL resources to a teardown path that did not exist, and the
  Stage tab (third engine plus the orientation preview) had no shutdown
  cleanup at all; MainWindow.closeEvent now calls it.

The offscreen test platform has no usable libGL for moderngl, so the GL
objects are mocks and the assertions are structural: the call order
around ``makeCurrent``, the signal hook on the real Qt context, the
timer's parent and activity. Rendered pixels are unchanged by design.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtGui import QHideEvent, QShowEvent
from PyQt6.QtWidgets import QApplication


def _send_show(widget):
    QApplication.sendEvent(widget, QShowEvent())


def _send_hide(widget):
    QApplication.sendEvent(widget, QHideEvent())


def _record_release_order(widget, attrs):
    """Swap ``widget``'s GL objects for mocks that log into one list,
    together with makeCurrent / doneCurrent, and return the list."""
    order = []
    widget.makeCurrent = lambda: order.append("makeCurrent")
    widget.doneCurrent = lambda: order.append("doneCurrent")
    mocks = {}
    for attr in attrs:
        mock = MagicMock(name=attr)
        mock.release.side_effect = lambda a=attr: order.append(a)
        setattr(widget, attr, mock)
        mocks[attr] = mock
    return order, mocks


# ── RenderEngine ──────────────────────────────────────────────────────

ENGINE_GL_ATTRS = (
    "fixture_manager", "stage_renderer", "stage_planes",
    "gizmo_renderer", "hdr", "ctx",
)


@pytest.fixture
def engine(qapp):
    from visualizer.renderer.engine import RenderEngine

    e = RenderEngine(parent=None)
    yield e
    e.render_timer.stop()
    e.deleteLater()


def test_engine_render_timer_is_parented(engine):
    """An unparented QTimer outlives the widget and keeps a Python
    reference cycle to its update slot."""
    assert engine.render_timer.parent() is engine


def test_engine_render_timer_idles_until_shown(engine):
    """Construction alone must not start a 60 fps tick: the embedded
    engines are built at startup on tabs nobody is looking at."""
    assert not engine.render_timer.isActive()
    _send_show(engine)
    assert engine.render_timer.isActive()


def test_engine_render_timer_stops_while_hidden(engine):
    """Switching away from the hosting tab hides the engine; the timer
    must stop and resume on the next show."""
    _send_show(engine)
    _send_hide(engine)
    assert not engine.render_timer.isActive()
    _send_show(engine)
    assert engine.render_timer.isActive()


def test_engine_cleanup_releases_with_context_current(engine):
    order, _ = _record_release_order(engine, ENGINE_GL_ATTRS)
    engine.cleanup()
    assert order[0] == "makeCurrent"
    assert order[-1] == "doneCurrent"
    # The moderngl context goes last, after every object it owns.
    assert order[-2] == "ctx"
    assert set(order[1:-1]) == set(ENGINE_GL_ATTRS)
    for attr in ENGINE_GL_ATTRS:
        assert getattr(engine, attr) is None
    assert not engine.render_timer.isActive()


def test_engine_cleanup_is_idempotent_and_skips_untouched_contexts(engine):
    """Never-initialised engines (every hidden tab in the unit suite)
    have nothing to release and must not poke the GL context at all."""
    order = []
    engine.makeCurrent = lambda: order.append("makeCurrent")
    engine.doneCurrent = lambda: order.append("doneCurrent")
    engine.cleanup()
    engine.cleanup()
    assert order == []


def test_engine_teardown_without_a_current_context_only_drops_refs(engine):
    """aboutToBeDestroyed can arrive from the QOpenGLWidget destructor,
    after the Python wrapper lost its C++ object: makeCurrent raises
    there. Releasing anyway would issue GL deletes with no context (or a
    foreign one) current; the dying context frees its objects itself."""
    order, mocks = _record_release_order(engine, ENGINE_GL_ATTRS)

    def gone():
        raise RuntimeError("wrapped C/C++ object has been deleted")

    engine.makeCurrent = gone
    engine.cleanup()
    assert order == []
    for attr, mock in mocks.items():
        assert not mock.release.called, f"{attr} released with no context"
        assert getattr(engine, attr) is None


def test_engine_releases_gl_when_qt_context_is_destroyed(qapp):
    """initializeGL hooks the Qt context's aboutToBeDestroyed (before
    touching moderngl, so the hook exists even where moderngl fails).
    The signal is emitted by hand: in Qt 6 the context's destruction
    order depends on the platform and the top-level window, and this
    headless platform cannot complete a real teardown. What is pinned is
    that the real Qt context reaches the release, context current."""
    from visualizer.renderer.engine import RenderEngine

    e = RenderEngine(parent=None)
    try:
        e.resize(64, 48)
        e.show()
        for _ in range(5):
            qapp.processEvents()
        e.render_timer.stop()
        context = e.context()
        if context is None or not e.isValid():
            # Windows offscreen hands back a context wrapper but never
            # initialises the widget, so initializeGL (and the hook) never ran.
            pytest.skip("platform created no usable Qt OpenGL context")
        order, mocks = _record_release_order(e, ENGINE_GL_ATTRS)
        context.aboutToBeDestroyed.emit()
        for attr, mock in mocks.items():
            assert mock.release.called, f"{attr} not released on context teardown"
            assert getattr(e, attr) is None
        assert order[0] == "makeCurrent"
        assert order[-1] == "doneCurrent"
    finally:
        e.hide()
        e.deleteLater()


# ── EmbeddedVisualizer ────────────────────────────────────────────────

def test_embedded_visualizer_cleanup_tears_down_the_engine(qapp):
    from gui.widgets.embedded_visualizer import EmbeddedVisualizer

    v = EmbeddedVisualizer(parent=None)
    try:
        real_engine = v._engine
        real_engine.render_timer.stop()
        v._engine = MagicMock()
        v.cleanup()
        v._engine.cleanup.assert_called_once()
        assert not v._fps_timer.isActive()
    finally:
        v._engine = real_engine
        v.deleteLater()


# ── OrientationPreviewWidget ──────────────────────────────────────────

@pytest.fixture
def preview(qapp):
    from gui.dialogs.orientation_dialog import OrientationPreviewWidget

    w = OrientationPreviewWidget(parent=None)
    yield w
    w.render_timer.stop()
    w.deleteLater()


def test_preview_render_timer_is_parented_and_idle_until_shown(preview):
    assert preview.render_timer.parent() is preview
    assert not preview.render_timer.isActive()
    _send_show(preview)
    assert preview.render_timer.isActive()
    _send_hide(preview)
    assert not preview.render_timer.isActive()


def test_preview_beam_indicator_allocates_nothing_per_frame(preview):
    """The beam line used to cost two buffers and a VAO per frame (30 per
    second while the Stage tab's inline preview was up)."""
    import moderngl

    ctx = MagicMock(name="ctx")
    preview.ctx = ctx
    preview.floor_program = MagicMock(name="floor_program")
    preview._create_axes_geometry()
    built_buffers = ctx.buffer.call_count
    built_vaos = ctx.vertex_array.call_count
    assert preview.beam_vao is not None

    for _ in range(3):
        preview._render_beam_indicator(MagicMock(), MagicMock())

    assert ctx.buffer.call_count == built_buffers
    assert ctx.vertex_array.call_count == built_vaos
    assert preview.beam_vao.render.call_count == 3
    preview.beam_vao.render.assert_called_with(moderngl.LINES)
    assert ctx.line_width == 3.0
    preview.ctx = None


def test_preview_beam_geometry_matches_the_old_per_frame_line(preview):
    """Same two vertices and colours as the per-frame version, so the
    rendered pixels cannot move."""
    import numpy as np

    ctx = MagicMock(name="ctx")
    preview.ctx = ctx
    preview.floor_program = MagicMock(name="floor_program")
    preview._create_axes_geometry()
    payloads = [np.asarray(c.args[0]) for c in ctx.buffer.call_args_list]
    beam_verts = np.array([[0, 0, 0], [0, 0, 1]], dtype="f4").flatten()
    beam_cols = np.array([[1, 1, 0], [1, 1, 0]], dtype="f4").flatten()
    assert any(p.shape == beam_verts.shape and np.array_equal(p, beam_verts)
               for p in payloads)
    assert any(p.shape == beam_cols.shape and np.array_equal(p, beam_cols)
               for p in payloads)
    preview.ctx = None


def test_preview_cleanup_releases_with_context_current(preview):
    attrs = ("beam_vao", "beam_vbo", "beam_cbo", "fixture_vao", "ctx")
    order, _ = _record_release_order(preview, attrs)
    preview.cleanup()
    assert order[0] == "makeCurrent"
    assert order[-1] == "doneCurrent"
    assert order[-2] == "ctx"
    assert set(order[1:-1]) == set(attrs)
    assert preview.ctx is None
    assert preview.beam_vao is None
    assert not preview.render_timer.isActive()


def test_preview_teardown_without_a_current_context_only_drops_refs(preview):
    attrs = ("beam_vao", "beam_vbo", "beam_cbo", "fixture_vao", "ctx")
    order, mocks = _record_release_order(preview, attrs)

    def gone():
        raise RuntimeError("wrapped C/C++ object has been deleted")

    preview.makeCurrent = gone
    preview.cleanup()
    assert order == []
    for attr, mock in mocks.items():
        assert not mock.release.called, f"{attr} released with no context"
        assert getattr(preview, attr) is None


def test_preview_fixture_type_change_builds_in_its_own_context(preview):
    """set_fixture_type runs outside paintGL (Stage tab selection), so
    the new geometry must be built with the preview's context current,
    not in whichever context (the 3D preview's, say) is current."""
    order = []
    preview.makeCurrent = lambda: order.append("makeCurrent")
    preview.doneCurrent = lambda: order.append("doneCurrent")
    preview._update_fixture_geometry = lambda: order.append("build")
    preview.ctx = MagicMock(name="ctx")
    new_type = "PAR" if preview.fixture_type != "PAR" else "WASH"
    preview.set_fixture_type(new_type)
    assert order == ["makeCurrent", "build", "doneCurrent"]
    preview.ctx = None


def test_preview_releases_gl_when_qt_context_is_destroyed(qapp):
    """Same aboutToBeDestroyed hook as RenderEngine (emitted by hand for
    the reason given there)."""
    from gui.dialogs.orientation_dialog import OrientationPreviewWidget

    w = OrientationPreviewWidget(parent=None)
    try:
        w.resize(64, 48)
        w.show()
        for _ in range(5):
            qapp.processEvents()
        w.render_timer.stop()
        context = w.context()
        if context is None or not w.isValid():
            pytest.skip("platform created no usable Qt OpenGL context")
        order, mocks = _record_release_order(w, ("beam_vao", "ctx"))
        context.aboutToBeDestroyed.emit()
        assert all(m.release.called for m in mocks.values())
        assert order[0] == "makeCurrent"
        assert w.ctx is None
    finally:
        w.hide()
        w.deleteLater()


# ── Shutdown wiring ───────────────────────────────────────────────────

def test_stage_tab_cleanup_releases_both_gl_surfaces(qapp, sample_configuration):
    """The Stage tab owns the third embedded engine and the inline
    orientation preview; before G9 it had no cleanup at all, so neither
    was released on shutdown."""
    from gui.tabs.stage_tab import StageTab

    tab = StageTab(sample_configuration, parent=None)
    try:
        real = (tab.embedded_visualizer, tab.orientation_panel)
        tab.embedded_visualizer = MagicMock()
        tab.orientation_panel = MagicMock()
        tab.cleanup()
        tab.embedded_visualizer.cleanup.assert_called_once()
        tab.orientation_panel.cleanup.assert_called_once()
    finally:
        tab.embedded_visualizer, tab.orientation_panel = real
        tab.cleanup()
        tab.deleteLater()


def test_main_window_close_cleans_up_the_stage_tab():
    from types import SimpleNamespace
    from gui.gui import MainWindow

    fake = SimpleNamespace(
        shows_tab=MagicMock(), structure_tab=None, auto_tab=MagicMock(),
        stage_tab=MagicMock(), _output_arbiter=None, _autosave_worker=None,
    )
    fake.shows_tab._autogen_worker = None
    event = MagicMock()
    MainWindow.closeEvent(fake, event)
    fake.stage_tab.cleanup.assert_called_once()
    event.accept.assert_called_once()


# ── Orientation preview: fixture-type geometry (v1.5.5 handover) ──────
#
# Releasing a moderngl VAO does not free the buffers it reads. The
# preview released only its eight body VAOs on a fixture-type change, so
# every change leaked all the vertex/normal buffers plus the per-type
# coordinate-axis VAOs, once per Stage tab selection of another type.

FIXTURE_TYPES = ("MH", "PAR", "WASH", "BAR", "SUNSTRIP", "MH")


def _counting_ctx():
    """A mock moderngl context whose buffers and VAOs log releases."""
    created, released = [], []

    def make(kind):
        def factory(*_args, **_kwargs):
            obj = MagicMock(name=kind)
            if kind == "buffer":
                del obj.render  # VAOs render, buffers do not
            obj.release.side_effect = lambda o=obj: released.append(o)
            created.append(obj)
            return obj
        return factory

    ctx = MagicMock(name="ctx")
    ctx.buffer.side_effect = make("buffer")
    ctx.vertex_array.side_effect = make("vao")
    return ctx, created, released


def test_preview_type_change_releases_buffers_and_vaos(preview):
    preview.makeCurrent = lambda: None
    preview.doneCurrent = lambda: None
    ctx, created, released = _counting_ctx()
    preview.ctx = ctx
    preview.fixture_program = MagicMock(name="program")
    preview.set_fixture_type("MH")
    for fixture_type in FIXTURE_TYPES[1:]:
        before = list(created)
        preview.set_fixture_type(fixture_type)
        leaked = [o for o in before if o not in released]
        assert leaked == [], f"{len(leaked)} objects leaked switching to {fixture_type}"
    assert any(not hasattr(o, "render") for o in released), "no buffer was released"
    preview.ctx = None


def test_preview_type_change_releases_vaos_before_their_buffers(preview):
    preview.makeCurrent = lambda: None
    preview.doneCurrent = lambda: None
    ctx, created, released = _counting_ctx()
    preview.ctx = ctx
    preview.fixture_program = MagicMock(name="program")
    preview.set_fixture_type("PAR")
    preview.set_fixture_type("BAR")
    kinds = [hasattr(o, "render") for o in released]
    assert kinds == sorted(kinds, reverse=True)
    preview.ctx = None


def test_preview_type_change_with_a_real_context(preview):
    """Same check on real moderngl objects where a standalone context is
    available: after each change every object of the previous type is
    really deleted (moderngl swaps in an InvalidObject), and the
    renderable attributes point at live objects only."""
    moderngl = pytest.importorskip("moderngl")
    try:
        ctx = moderngl.create_standalone_context()
    except Exception as e:  # no libGL / no driver
        pytest.skip(f"no standalone GL context: {e}")
    try:
        preview.makeCurrent = lambda: None
        preview.doneCurrent = lambda: None
        preview.ctx = ctx
        preview._create_fixture_geometry()
        for fixture_type in FIXTURE_TYPES:
            if fixture_type == preview.fixture_type:
                continue  # no change, nothing to release
            before = list(preview._fixture_gl)
            assert before
            preview.set_fixture_type(fixture_type)
            for obj in before:
                assert type(obj.mglo).__name__ == "InvalidObject"
            for attr in preview._FIXTURE_VAO_ATTRS:
                vao = getattr(preview, attr)
                if vao is not None:
                    assert type(vao.mglo).__name__ != "InvalidObject", attr
        preview._release_fixture_vaos()
    finally:
        preview.ctx = None
        ctx.release()
