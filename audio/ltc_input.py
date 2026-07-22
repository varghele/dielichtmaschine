"""LTC input service (docs/ltc-plan.md phase 2).

Owns the audio capture for the timecode chase: a LiveAudioInput fills
its ring buffer from the device, a reader thread drains it through the
LTC decoder into the chase, and a thin Qt boundary emits display
signals. Pure logic stays in utils/timecode; this module is the only
place where the chase meets a device, a thread and Qt.

Ownership (phase 3): one instance lives on MainWindow, like the output
arbiter - the SHELL owns arm/disarm policy, tabs only display.

Design rules:
- Construction NEVER opens a stream; ``start()`` does, and a failing
  device open degrades to the no-signal state with a logged warning,
  never an exception into the caller.
- ``start()``/``stop()`` are idempotent.
- Everything timing-sensitive takes injectable pieces (clock, audio
  input factory) and ``drain_once(now)`` runs one reader iteration
  synchronously, so tests push samples into the ring buffer and step
  the service deterministically - no real device, no thread races.

Arrival mapping: each decoded frame carries its absolute sample
position; a drain anchors that to the CURRENT monotonic clock
(``arrival = now - samples_still_pending / rate``), so the audio
clock's slow drift against the monotonic clock can never accumulate -
only drain jitter remains, which the chase's fit window absorbs.
"""

import logging
import threading
import time
from typing import Callable, List, Optional, Tuple

from PyQt6.QtCore import QObject, pyqtSignal

from utils.timecode import ChaseState, LTCDecoder, TimecodeChase
from .live_input import LiveAudioInput

logger = logging.getLogger(__name__)

NO_SIGNAL = ChaseState.NO_SIGNAL.value


def resolve_input_device(hint: str) -> Optional[int]:
    """Map a stored device hint (Setlist.sync_device) to a PortAudio
    device index. Empty hint or no match -> None (system default)."""
    if not hint:
        return None
    try:
        from .device_manager import DeviceManager
        devices = DeviceManager().enumerate_input_devices()
    except Exception as exc:
        logger.warning("LTC device enumeration failed: %s", exc)
        return None
    for dev in devices:
        if hint in (dev.name, dev.display_name):
            return dev.index
    low = hint.lower()
    for dev in devices:
        if low in (dev.display_name or dev.name).lower():
            return dev.index
    logger.warning("LTC input device %r not found; using default", hint)
    return None


class LTCInputService(QObject):
    """Audio device -> ring buffer -> LTCDecoder -> TimecodeChase."""

    state_changed = pyqtSignal(str)   # ChaseState.value
    timecode = pyqtSignal(str)        # last label, throttled for display

    def __init__(self, sample_rate: int = 44100, device_hint: str = "",
                 clock: Callable[[], float] = time.monotonic,
                 audio_input_factory: Optional[Callable[..., LiveAudioInput]] = None,
                 poll_interval: float = 0.05,
                 display_interval: float = 0.25,
                 parent: Optional[QObject] = None):
        super().__init__(parent)
        self.sample_rate = sample_rate
        self.device_hint = device_hint
        self.poll_interval = poll_interval
        self.display_interval = display_interval
        self._clock = clock
        self._make_input = audio_input_factory or LiveAudioInput

        self._audio: Optional[LiveAudioInput] = None
        self._decoder: Optional[LTCDecoder] = None
        self._chase: Optional[TimecodeChase] = None
        self._samples_fed = 0
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._last_state_emitted = NO_SIGNAL
        self._last_display_emit = float("-inf")

    # -- lifecycle -----------------------------------------------------

    @property
    def is_running(self) -> bool:
        return self._running

    def start(self, run_reader: bool = True) -> bool:
        """Open the input and begin decoding. False (plus a warning and
        the no-signal state) when the device cannot be opened."""
        if self._running:
            return True
        device_index = resolve_input_device(self.device_hint)
        audio = self._make_input(sample_rate=self.sample_rate, channels=1)
        try:
            ok = audio.initialize(device_index) and audio.start()
        except Exception as exc:
            logger.warning("LTC input failed to open: %s", exc)
            ok = False
        if not ok:
            logger.warning(
                "LTC input unavailable (device hint %r); chase stays "
                "in no-signal", self.device_hint)
            try:
                audio.cleanup()
            except Exception:
                pass
            self._emit_state(NO_SIGNAL, force=True)
            return False

        with self._lock:
            self._audio = audio
            # The stream may have fallen back to the device's native
            # rate (Invalid-sample-rate devices, 2026-07-22): decode
            # at the rate the stream ACTUALLY runs at.
            self._active_rate = int(getattr(audio, "sample_rate",
                                            self.sample_rate))
            self._decoder = LTCDecoder(sample_rate=self._active_rate)
            self._chase = None
            self._samples_fed = 0
        self._running = True
        self._emit_state(NO_SIGNAL, force=True)
        if run_reader:
            self._thread = threading.Thread(
                target=self._reader_loop, name="ltc-input", daemon=True)
            self._thread.start()
        return True

    def stop(self) -> None:
        """Stop capture and forget the chase. Idempotent."""
        self._running = False
        thread, self._thread = self._thread, None
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)
        with self._lock:
            audio, self._audio = self._audio, None
            self._decoder = None
            self._chase = None
        if audio is not None:
            try:
                audio.cleanup()
            except Exception:
                pass
        self._emit_state(NO_SIGNAL)

    # -- chase access (any thread) ----------------------------------------

    def state(self, now: Optional[float] = None) -> str:
        with self._lock:
            if self._chase is None:
                return NO_SIGNAL
            return self._chase.state(self._now(now)).value

    def position(self, now: Optional[float] = None) -> Optional[float]:
        """Seconds on the incoming timecode timeline, or None."""
        with self._lock:
            if self._chase is None:
                return None
            return self._chase.position(self._now(now))

    def consume_jump(self) -> bool:
        with self._lock:
            return self._chase.consume_jump() if self._chase else False

    def last_label(self) -> str:
        with self._lock:
            if self._chase is None or self._chase.last_timecode is None:
                return ""
            return str(self._chase.last_timecode)

    def detected_rate(self):
        with self._lock:
            return self._decoder.rate_guess if self._decoder else None

    # -- the reader ----------------------------------------------------------

    def drain_once(self, now: Optional[float] = None) -> None:
        """One reader iteration: consume the ring buffer, decode, feed
        the chase, emit display signals. The thread calls this in a
        loop; tests call it directly."""
        now = self._now(now)
        with self._lock:
            audio, decoder = self._audio, self._decoder
            if audio is None or decoder is None:
                return
            pending = audio.ring_buffer.available()
            frames: List[Tuple] = []
            if pending > 0:
                chunk = audio.ring_buffer.read_consume(pending)
                samples = chunk[:, 0] if chunk.ndim == 2 else chunk
                decoded = decoder.feed(samples)
                self._samples_fed += samples.shape[0]
                if self._chase is None and decoded:
                    rate = decoder.rate_guess
                    if rate is not None:
                        self._chase = TimecodeChase(rate)
                if self._chase is not None:
                    rate = getattr(self, "_active_rate",
                                   self.sample_rate)
                    for frame in decoded:
                        lag = (self._samples_fed - frame.end_sample) \
                            / rate
                        self._chase.feed(frame, now - lag)
            chase = self._chase
            state = chase.state(now).value if chase else NO_SIGNAL
            label = ""
            if chase is not None and chase.last_timecode is not None:
                label = str(chase.last_timecode)

        self._emit_state(state)
        if label and now - self._last_display_emit >= self.display_interval:
            self._last_display_emit = now
            self.timecode.emit(label)

    def _reader_loop(self) -> None:
        while self._running:
            try:
                self.drain_once()
            except Exception:
                logger.exception("LTC reader iteration failed")
            time.sleep(self.poll_interval)

    # -- helpers ---------------------------------------------------------

    def _now(self, now: Optional[float]) -> float:
        return self._clock() if now is None else now

    def _emit_state(self, state: str, force: bool = False) -> None:
        if force or state != self._last_state_emitted:
            self._last_state_emitted = state
            self.state_changed.emit(state)
