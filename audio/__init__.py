# audio/__init__.py
# Audio subsystem for Die Lichtmaschine
# Provides song playback (pygame, simple_audio_player), live input,
# real-time analysis and waveform analysis.
# The package is Qt-free: the waveform widget lives in timeline_ui/, the
# Qt signal bridges (LiveFeatureBridge, LTCInputService) in gui/
# (tests/unit/test_core_imports_without_qt.py).
#
# The package exports resolve LAZILY (PEP 562 module __getattr__): every
# ``from audio import X`` keeps working, but importing a submodule such
# as ``audio.spectral_analysis`` (autogen, the headless morph CLI) no
# longer drags in the device layer through this file.

import importlib

#: Public name -> submodule that defines it.
_EXPORTS = {
    'DeviceManager': '.device_manager',
    'AudioDevice': '.device_manager',
    'AudioFile': '.audio_file',
    'AudioMetadata': '.audio_file',
    'WaveformAnalyzer': '.waveform_analyzer',
    'WaveformData': '.waveform_analyzer',
    'WaveformPeaks': '.waveform_analyzer',
    'AudioRingBuffer': '.ring_buffer',
    'LiveAudioInput': '.live_input',
    'RealtimeSpectralAnalyzer': '.realtime_spectral',
    'LiveFeatureFrame': '.realtime_spectral',
}

__all__ = [
    'DeviceManager', 'AudioDevice',
    'AudioFile', 'AudioMetadata',
    'WaveformAnalyzer', 'WaveformData', 'WaveformPeaks',
    'AudioRingBuffer',
    'LiveAudioInput',
    'RealtimeSpectralAnalyzer', 'LiveFeatureFrame',
]


def __getattr__(name):
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(importlib.import_module(module_name, __name__), name)
    globals()[name] = value
    return value


def __dir__():
    return sorted(set(globals()) | set(__all__))
