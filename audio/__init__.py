# audio/__init__.py
# Audio subsystem for Die Lichtmaschine
# Provides audio playback, mixing, live input, real-time analysis, and waveform visualization

from .device_manager import DeviceManager, AudioDevice
from .audio_file import AudioFile, AudioMetadata
from .audio_engine import AudioEngine
from .audio_mixer import AudioMixer, AudioLaneState
from .playback_synchronizer import PlaybackSynchronizer
from .waveform_analyzer import WaveformAnalyzer, WaveformData, WaveformPeaks
from .audio_waveform_widget import AudioWaveformWidget, AudioLoaderThread
from .ring_buffer import AudioRingBuffer
from .live_input import LiveAudioInput
from .realtime_spectral import RealtimeSpectralAnalyzer, LiveFeatureFrame
from .live_feature_bridge import LiveFeatureBridge

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
