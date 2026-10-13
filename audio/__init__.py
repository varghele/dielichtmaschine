# audio/__init__.py
# Audio subsystem for Die Lichtmaschine
# Provides audio playback, mixing, live input, real-time analysis, and waveform visualization
#
# The package exports resolve LAZILY (PEP 562 module __getattr__): every
# ``from audio import X`` keeps working, but importing a submodule such
# as ``audio.spectral_analysis`` (autogen, the headless morph CLI) no
# longer drags in QtWidgets, the device layer and the waveform widget
# through this file.

import importlib

#: Public name -> submodule that defines it.
_EXPORTS = {
    'DeviceManager': '.device_manager',
    'AudioDevice': '.device_manager',
    'AudioFile': '.audio_file',
    'AudioMetadata': '.audio_file',
    'AudioEngine': '.audio_engine',
    'AudioMixer': '.audio_mixer',
    'AudioLaneState': '.audio_mixer',
    'PlaybackSynchronizer': '.playback_synchronizer',
    'WaveformAnalyzer': '.waveform_analyzer',
    'WaveformData': '.waveform_analyzer',
    'WaveformPeaks': '.waveform_analyzer',
    'AudioWaveformWidget': '.audio_waveform_widget',
    'AudioLoaderThread': '.audio_waveform_widget',
    'AudioRingBuffer': '.ring_buffer',
    'LiveAudioInput': '.live_input',
    'RealtimeSpectralAnalyzer': '.realtime_spectral',
    'LiveFeatureFrame': '.realtime_spectral',
    'LiveFeatureBridge': '.live_feature_bridge',
}

__all__ = [
    'DeviceManager', 'AudioDevice',
    'AudioFile', 'AudioMetadata',
    'AudioEngine',
    'AudioMixer', 'AudioLaneState',
    'PlaybackSynchronizer',
    'WaveformAnalyzer', 'WaveformData', 'WaveformPeaks',
    'AudioWaveformWidget', 'AudioLoaderThread',
    'AudioRingBuffer',
    'LiveAudioInput',
    'RealtimeSpectralAnalyzer', 'LiveFeatureFrame',
    'LiveFeatureBridge',
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
