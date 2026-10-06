# tests/unit/test_render_dialog_lifetime.py
"""Render-to-video worker lifetime (v1.5.5 G8).

Before the fix: RenderWorker was created without a parent and its
outcome signal was called ``finished``, shadowing QThread.finished.
Closing the dialog mid-render let Python destroy a running QThread
(a fatal abort), a renderer that raised never reported back (the
dialog sat in its rendering state), a cancel issued before the
renderer existed was lost, and Cancel only stopped the current show:
the queue carried on with the next one.

The renderer is faked: a thread that blocks until cancelled (or until
the test releases it) stands in for OfflineRenderer, so no GL and no
ffmpeg are involved.
"""

import os
import threading

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QThread

from config.models import Configuration, ShowPart, Song, TimelineData


class BlockingRenderer:
    """OfflineRenderer stand-in: render() blocks until cancel() or
    release()."""
    instances = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.cancelled = False
        self._event = threading.Event()
        BlockingRenderer.instances.append(self)

    def cancel(self):
        self.cancelled = True
        self._event.set()

    def release(self):
        self._event.set()

    def render(self):
        self._event.wait(10)
        return not self.cancelled


class RaisingRenderer:
    def __init__(self, **kwargs):
        pass

    def cancel(self):
        pass

    def render(self):
        raise RuntimeError("ffmpeg missing")


def _config(*names):
    config = Configuration()
    for name in names:
        config.songs[name] = Song(
            name=name,
            parts=[ShowPart(name="Intro", color="#FF0000", signature="4/4",
                            bpm=120.0, num_bars=4, transition="instant")],
            effects=[], timeline_data=TimelineData())
    return config


@pytest.fixture
def blocking(monkeypatch):
    import utils.render.offline_renderer as offline
    BlockingRenderer.instances = []
    monkeypatch.setattr(offline, "OfflineRenderer", BlockingRenderer)
    yield BlockingRenderer
    for renderer in BlockingRenderer.instances:
        renderer.release()


@pytest.fixture
def dialog(qapp, blocking, tmp_path):
    from gui.dialogs.render_dialog import RenderDialog
    dlg = RenderDialog(_config("One", "Two"), {})
    dlg._output_dir_edit.setText(str(tmp_path))
    dlg._set_all_checked(True)
    yield dlg
    # done() cancels (even before the renderer exists) and waits, so
    # the dialog never takes a running thread down with it.
    dlg.done(0)
    dlg.deleteLater()


def _wait_for(predicate, qapp, timeout_s=5.0):
    import time
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        qapp.processEvents()
        if predicate():
            return True
        time.sleep(0.005)
    return False


def test_worker_is_owned_by_the_dialog(dialog, qapp):
    dialog._start_render()
    assert dialog._worker.parent() is dialog


def test_closing_mid_render_cancels_and_waits_for_the_thread(dialog, qapp):
    dialog._start_render()
    worker = dialog._worker
    assert _wait_for(lambda: BlockingRenderer.instances, qapp)
    assert worker.isRunning()
    dialog.reject()                      # Close / Escape / close box
    assert BlockingRenderer.instances[0].cancelled
    assert not worker.isRunning()


def test_cancel_stops_the_whole_queue(dialog, qapp):
    dialog._start_render()
    assert _wait_for(lambda: BlockingRenderer.instances, qapp)
    dialog._cancel_render()
    assert _wait_for(lambda: dialog._render_btn.isEnabled(), qapp)
    qapp.processEvents()
    # the second show never started
    assert len(BlockingRenderer.instances) == 1
    assert "cancelled" in dialog._log.toPlainText().lower()


def test_render_button_waits_for_the_cancelled_worker(dialog, qapp,
                                                     monkeypatch):
    # A renderer that winds down slowly: cancel() is noted, but render()
    # only returns once the test releases it.
    monkeypatch.setattr(BlockingRenderer, "cancel",
                        lambda self: setattr(self, "cancelled", True))
    dialog._start_render()
    assert _wait_for(lambda: BlockingRenderer.instances, qapp)
    dialog._cancel_render()
    qapp.processEvents()
    # still winding down: Render must not start a second one on top
    assert dialog._worker.isRunning()
    assert not dialog._render_btn.isEnabled()
    BlockingRenderer.instances[0].release()
    assert _wait_for(lambda: dialog._render_btn.isEnabled(), qapp)
    assert len(BlockingRenderer.instances) == 1


def test_cancel_before_the_renderer_exists_is_not_lost(qapp, blocking):
    from gui.dialogs.render_dialog import RenderWorker
    show = _config("One").songs["One"]
    worker = RenderWorker(Configuration(), show, {}, "front", "x.mp4")
    worker.cancel()
    results = []
    worker.render_done.connect(lambda name, ok: results.append((name, ok)))
    worker.run()                         # synchronously, no thread
    assert BlockingRenderer.instances[0].cancelled
    assert results == [("One", False)]


def test_a_raising_renderer_still_reports_back(qapp, monkeypatch):
    import utils.render.offline_renderer as offline
    from gui.dialogs.render_dialog import RenderWorker
    monkeypatch.setattr(offline, "OfflineRenderer", RaisingRenderer)
    show = _config("One").songs["One"]
    worker = RenderWorker(Configuration(), show, {}, "front", "x.mp4")
    results, messages = [], []
    worker.render_done.connect(lambda name, ok: results.append((name, ok)))
    worker.progress.connect(lambda c, t, msg: messages.append(msg))
    worker.run()
    assert results == [("One", False)]
    assert any("ffmpeg missing" in msg for msg in messages)


def test_outcome_signal_does_not_shadow_qthread_finished(qapp):
    from gui.dialogs.render_dialog import RenderWorker
    assert RenderWorker.finished is QThread.finished
