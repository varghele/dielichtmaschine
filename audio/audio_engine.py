"""
Audio playback engine for Die Lichtmaschine using sounddevice.
Manages audio stream and provides sample-accurate playback.
Supports ASIO (Windows) and JACK (Linux) for low-latency operation.
"""

import sounddevice as sd
import numpy as np
import threading
import queue
from typing import Optional, Callable
from .audio_mixer import AudioMixer


class AudioCommand:
    """Commands for audio engine"""
    START = "start"
    STOP = "stop"
    PAUSE = "pause"
    SEEK = "seek"


class AudioEngine:
    """Core audio playback engine using sounddevice"""

    def __init__(self, sample_rate: int = 44100, buffer_size: int = 512):
        self.sample_rate = sample_rate
        self.buffer_size = buffer_size

        self._sd_stream: Optional[sd.OutputStream] = None
        self.mixer: Optional[AudioMixer] = None

        # Playback state
        self._current_frame = 0
        self._is_playing = False
        self._is_initialized = False

        # Thread safety
        self._lock = threading.Lock()
        self._command_queue = queue.Queue()

        # Seeking
        self._seek_pending = False
        self._seek_target_frame = 0

        # Position callback
        self._position_callback: Optional[Callable[[float], None]] = None

    def initialize(self, device_index: Optional[int] = None) -> bool:
        """
        Initialize sounddevice and create audio output stream.

        Args:
            device_index: Audio device to use (None = default)

        Returns:
            True if initialization successful
        """
        try:
            if self._is_initialized:
                return True

            self._sd_stream = sd.OutputStream(
                samplerate=self.sample_rate,
                blocksize=self.buffer_size,
                device=device_index,
                channels=2,
                dtype='float32',
                callback=self._audio_callback,
            )

            self._is_initialized = True
            return True

        except Exception as e:
            print(f"Failed to initialize audio engine: {e}")
            self.cleanup()
            return False

    def cleanup(self):
        """Cleanup audio resources"""
        self.stop_playback()

        if self._sd_stream:
            try:
                if self._sd_stream.active:
                    self._sd_stream.abort()
                self._sd_stream.close()
            except Exception:
                pass
            self._sd_stream = None

        self._is_initialized = False

    def set_mixer(self, mixer: AudioMixer):
        """Set the audio mixer to use"""
        with self._lock:
            self.mixer = mixer

    def set_position_callback(self, callback: Callable[[float], None]):
        """Set callback for position updates"""
        self._position_callback = callback

    def start_playback(self, start_position: float = 0.0) -> bool:
        """
        Start audio playback.

        Args:
            start_position: Starting position in seconds

        Returns:
            True if playback started
        """
        if not self._is_initialized:
            return False

        with self._lock:
            # Clear any pending seek from previous stop operation
            self._seek_pending = False

            # Seek to start position
            start_frame = int(start_position * self.sample_rate)
            self._current_frame = start_frame

            if self.mixer:
                self.mixer.seek_all_lanes(start_position)

            self._is_playing = True

        # Start the stream if not already running
        if not self._sd_stream.active:
            self._sd_stream.start()

        return True

    def stop_playback(self):
        """Stop playback and reset to beginning"""
        with self._lock:
            self._is_playing = False
            self._current_frame = 0

            if self.mixer:
                self.mixer.reset_all_lanes()

        if self._sd_stream and self._sd_stream.active:
            self._sd_stream.abort()

    def pause_playback(self):
        """Pause playback at current position"""
        with self._lock:
            self._is_playing = False

        if self._sd_stream and self._sd_stream.active:
            self._sd_stream.abort()

    def seek(self, time_seconds: float):
        """
        Seek to specific time position.

        Args:
            time_seconds: Target position in seconds
        """
        with self._lock:
            self._seek_target_frame = int(time_seconds * self.sample_rate)
            self._seek_pending = True

    def get_current_position(self) -> float:
        """Get current playback position in seconds"""
        with self._lock:
            return self._current_frame / self.sample_rate

    def is_playing(self) -> bool:
        """Check if currently playing"""
        with self._lock:
            return self._is_playing

    def _audio_callback(self, outdata, frames, time, status):
        """
        sounddevice callback - called from audio thread.

        Args:
            outdata: Output buffer to fill (numpy array, shape (frames, channels))
            frames: Number of frames to produce
            time: Timing info
            status: Callback status flags
        """
        if status:
            if status.output_underflow:
                pass  # Common during init, suppress
            else:
                print(f"Audio callback status: {status}")

        # Handle seek
        with self._lock:
            if self._seek_pending:
                self._execute_seek()
                self._seek_pending = False

            if not self._is_playing or not self.mixer:
                outdata[:] = 0
                return

        # Mix audio from all lanes
        try:
            mixed_audio = self.mixer.mix_frames(frames)

            with self._lock:
                self._current_frame += frames

            # Write mixed audio to output buffer
            outdata[:] = mixed_audio

            # Periodically report position (every ~100ms)
            if self._position_callback and self._current_frame % 4410 == 0:
                try:
                    position = self._current_frame / self.sample_rate
                    self._position_callback(position)
                except Exception:
                    pass  # Don't let callback errors crash audio thread

        except Exception as e:
            print(f"Error in audio callback: {e}")
            outdata[:] = 0

    def _execute_seek(self):
        """Execute pending seek operation (called from audio callback)"""
        try:
            self._current_frame = self._seek_target_frame

            if self.mixer:
                seek_time = self._current_frame / self.sample_rate
                self.mixer.seek_all_lanes(seek_time)

        except Exception as e:
            print(f"Error executing seek: {e}")
