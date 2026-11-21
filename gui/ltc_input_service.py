"""Qt boundary of the LTC input (docs/ltc-plan.md phase 2).

``audio/ltc_input.py`` ``LTCInputCore`` owns the device, the reader
thread, the decoder and the chase, and is Qt-free; this subclass only
turns its two display hooks into signals for the shell (MainWindow
owns the one instance, the Live tab's SYNC chip displays it). Split out
of audio/ in v1.5.6 so the core packages import without PyQt6.

Signal emits happen exactly where the hooks are called, under the
core's emit lock, so the thread-safety guarantees of the core (no stale
state emitted after ``stop()``, atomic last-emitted check) carry over
unchanged.
"""

import time
from typing import Callable, Optional

from PyQt6.QtCore import QObject, pyqtSignal

from audio.live_input import LiveAudioInput
from audio.ltc_input import LTCInputCore


class LTCInputService(LTCInputCore, QObject):
    """LTCInputCore plus the display signals."""

    state_changed = pyqtSignal(str)   # ChaseState.value
    timecode = pyqtSignal(str)        # last label, throttled for display

    def __init__(self, sample_rate: int = 44100, device_hint: str = "",
                 clock: Callable[[], float] = time.monotonic,
                 audio_input_factory: Optional[Callable[..., LiveAudioInput]] = None,
                 poll_interval: float = 0.05,
                 display_interval: float = 0.25,
                 parent: Optional[QObject] = None):
        # QObject first, explicitly: the core's initialiser does not
        # chain to super(), so neither base runs twice.
        QObject.__init__(self, parent)
        LTCInputCore.__init__(
            self, sample_rate=sample_rate, device_hint=device_hint,
            clock=clock, audio_input_factory=audio_input_factory,
            poll_interval=poll_interval,
            display_interval=display_interval)

    def _signal_state(self, state: str) -> None:
        self.state_changed.emit(state)

    def _signal_timecode(self, label: str) -> None:
        self.timecode.emit(label)
