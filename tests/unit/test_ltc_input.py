"""LTC input service (audio/ltc_input.py, docs/ltc-plan.md phase 2).

No real audio device anywhere: a fake input exposes a real ring
buffer, generated LTC audio is pushed into it, and the service is
stepped with drain_once() under a fake clock - the whole
device -> decoder -> chase -> signals path runs deterministically.
"""

import numpy as np
import pytest

from audio.ltc_input import LTCInputService, resolve_input_device
from audio.ring_buffer import AudioRingBuffer
from utils.timecode import FPS_25, Timecode, generate_ltc

SR = 44100
CHUNK = 2205          # 50 ms of samples
DT = 0.05


class FakeAudioInput:
    def __init__(self, sample_rate=SR, channels=1, fail=False):
        self.sample_rate = sample_rate
        self.ring_buffer = AudioRingBuffer(
            max_seconds=30.0, sample_rate=sample_rate, channels=channels)
        self.fail = fail
        self.device_index = "unset"
        self.active = False
        self.cleaned = 0

    def initialize(self, device_index=None):
        self.device_index = device_index
        return not self.fail

    def start(self):
        self.active = True
        return True

    def stop(self):
        self.active = False

    def cleanup(self):
        self.cleaned += 1
        self.active = False

    def is_active(self):
        return self.active


class FakeClock:
    def __init__(self, t=100.0):
        self.t = t

    def __call__(self):
        return self.t


def make_service(fail=False, **kwargs):
    created = []
    clock = FakeClock()

    def factory(sample_rate=SR, channels=1):
        fake = FakeAudioInput(sample_rate, channels, fail=fail)
        created.append(fake)
        return fake

    service = LTCInputService(sample_rate=SR, clock=clock,
                              audio_input_factory=factory, **kwargs)
    return service, created, clock


def push_and_drain(service, fake, clock, audio):
    for i in range(0, len(audio), CHUNK):
        fake.ring_buffer.write(np.asarray(audio[i:i + CHUNK]).reshape(-1, 1))
        clock.t += DT
        service.drain_once()


class TestEndToEnd:

    def test_lock_position_label_and_rate(self, qapp):
        service, created, clock = make_service()
        assert service.start(run_reader=False)
        start = Timecode.parse("00:05:00:00", FPS_25)
        push_and_drain(service, created[0], clock,
                       generate_ltc(start, 3.0))
        assert service.state() == "locked"
        truth = start.to_seconds() + 3.0
        assert service.position() == pytest.approx(truth, abs=0.05)
        assert service.last_label().startswith("00:05:0")
        assert service.detected_rate() == FPS_25
        service.stop()

    def test_state_signal_walks_lock_freewheel_no_signal(self, qapp):
        service, created, clock = make_service()
        states = []
        service.state_changed.connect(states.append)
        service.start(run_reader=False)
        assert states == ["no_signal"]
        push_and_drain(service, created[0], clock,
                       generate_ltc(Timecode.parse("00:05:00:00", FPS_25),
                                    2.0))
        assert states[-1] == "locked"
        clock.t += 1.0                      # signal stops
        service.drain_once()
        assert states[-1] == "freewheel"
        clock.t += 2.5                      # freewheel expires
        service.drain_once()
        assert states[-1] == "no_signal"
        service.stop()

    def test_timecode_signal_is_throttled_for_display(self, qapp):
        service, created, clock = make_service()
        labels = []
        service.timecode.connect(labels.append)
        service.start(run_reader=False)
        push_and_drain(service, created[0], clock,
                       generate_ltc(Timecode.parse("00:00:00:00", FPS_25),
                                    2.0))
        # 2 s of audio at a 0.25 s display throttle: a handful, not 100.
        assert 4 <= len(labels) <= 9
        service.stop()


class TestLifecycle:

    def test_start_is_idempotent(self, qapp):
        service, created, clock = make_service()
        assert service.start(run_reader=False)
        assert service.start(run_reader=False)
        assert len(created) == 1            # no second stream opened
        service.stop()

    def test_stop_is_idempotent_and_resets_the_chase(self, qapp):
        service, created, clock = make_service()
        service.start(run_reader=False)
        push_and_drain(service, created[0], clock,
                       generate_ltc(Timecode.parse("00:05:00:00", FPS_25),
                                    1.0))
        assert service.state() == "locked"
        service.stop()
        service.stop()
        assert created[0].cleaned >= 1
        assert service.state() == "no_signal"
        assert service.position() is None
        # A fresh start opens a fresh stream and starts cold.
        assert service.start(run_reader=False)
        assert len(created) == 2
        assert service.state() == "no_signal"
        service.stop()

    def test_failing_device_degrades_without_raising(self, qapp):
        service, created, clock = make_service(fail=True)
        states = []
        service.state_changed.connect(states.append)
        assert service.start(run_reader=False) is False
        assert service.is_running is False
        assert states == ["no_signal"]
        assert service.position() is None
        assert created[0].cleaned >= 1      # nothing left half-open


class TestDeviceResolution:

    def _devices(self):
        from audio.device_manager import AudioDevice
        return [
            AudioDevice(index=3, name="Line In (High Definition Audio)",
                        max_output_channels=0, max_input_channels=2,
                        default_sample_rate=44100.0,
                        host_api="Windows WASAPI", host_api_index=1,
                        display_name="Line In"),
            AudioDevice(index=7, name="USB Interface Input",
                        max_output_channels=0, max_input_channels=8,
                        default_sample_rate=48000.0, host_api="ASIO",
                        host_api_index=2, display_name="USB Interface"),
        ]

    @pytest.fixture(autouse=True)
    def _patched(self, monkeypatch):
        from audio.device_manager import DeviceManager
        devices = self._devices()
        monkeypatch.setattr(DeviceManager, "enumerate_input_devices",
                            lambda self, **kw: devices)

    def test_empty_hint_is_default_device(self):
        assert resolve_input_device("") is None

    def test_exact_raw_name_wins(self):
        assert resolve_input_device(
            "Line In (High Definition Audio)") == 3

    def test_display_name_matches(self):
        assert resolve_input_device("USB Interface") == 7

    def test_loose_case_insensitive_substring(self):
        assert resolve_input_device("line in") == 3

    def test_unknown_hint_falls_back_to_default(self):
        assert resolve_input_device("Firewire Thing") is None
