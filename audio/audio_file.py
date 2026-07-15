"""
Audio file loading and management for Die Lichtmaschine.
Supports WAV, MP3, FLAC, and OGG formats.
"""

import numpy as np
import soundfile as sf
from dataclasses import dataclass
from typing import Optional, Tuple
import os


@dataclass
class AudioMetadata:
    """Audio file metadata"""
    duration: float  # in seconds
    sample_rate: int
    channels: int
    frames: int
    format_name: str

    def __str__(self):
        return (f"{self.duration:.2f}s @ {self.sample_rate}Hz, "
                f"{self.channels} channel(s), {self.format_name}")


class AudioFile:
    """Represents a loaded audio file with playback capabilities"""

    def __init__(self, target_sample_rate: int = 44100):
        self.file_path: Optional[str] = None
        self.audio_data: Optional[np.ndarray] = None
        self.sample_rate: int = 0
        self.channels: int = 0
        self.frames: int = 0
        self.duration: float = 0.0
        self.target_sample_rate = target_sample_rate
        self.current_frame = 0
        self._is_loaded = False

    def load(self, file_path: str) -> bool:
        """Load audio file from disk"""
        if not os.path.exists(file_path):
            print(f"Audio file not found: {file_path}")
            return False

        try:
            # Load audio using soundfile
            # This handles WAV, FLAC, OGG natively
            audio_data, sample_rate = sf.read(file_path, dtype='float32')

            # Handle mono vs stereo
            if audio_data.ndim == 1:
                # Mono to stereo
                audio_data = np.stack([audio_data, audio_data], axis=1)
                channels = 2
            else:
                channels = audio_data.shape[1]
                # If more than 2 channels, downmix to stereo
                if channels > 2:
                    audio_data = self._downmix_to_stereo(audio_data)
                    channels = 2

            self.file_path = file_path
            self.audio_data = audio_data
            self.sample_rate = sample_rate
            self.channels = channels
            self.frames = len(audio_data)
            self.duration = self.frames / self.sample_rate
            self.current_frame = 0
            self._is_loaded = True

            # Resample if needed
            if self.sample_rate != self.target_sample_rate:
                self._resample(self.target_sample_rate)

            return True

        except Exception as e:
            # Try fallback for MP3 using audioread + librosa
            try:
                return self._load_with_librosa(file_path)
            except Exception as e2:
                print(f"Error loading audio file {file_path}: {e}, {e2}")
                return False

    def _load_with_librosa(self, file_path: str) -> bool:
        """Fallback loader using librosa for MP3 support"""
        try:
            import librosa

            # Load with librosa (handles MP3)
            audio_data, sample_rate = librosa.load(
                file_path,
                sr=self.target_sample_rate,
                mono=False
            )

            # Ensure stereo
            if audio_data.ndim == 1:
                audio_data = np.stack([audio_data, audio_data], axis=0)

            # librosa returns (channels, samples), transpose to (samples, channels)
            audio_data = audio_data.T

            self.file_path = file_path
            self.audio_data = audio_data.astype(np.float32)
            self.sample_rate = self.target_sample_rate
            self.channels = 2
            self.frames = len(audio_data)
            self.duration = self.frames / self.sample_rate
            self.current_frame = 0
            self._is_loaded = True

            return True
        except ImportError:
            print("librosa not installed, cannot load MP3 files")
            return False
        except Exception as e:
            print(f"Error loading audio with librosa: {e}")
            return False

    def _downmix_to_stereo(self, audio_data: np.ndarray) -> np.ndarray:
        """Downmix multi-channel audio to stereo"""
        if audio_data.shape[1] == 2:
            return audio_data

        # Simple downmix: average all channels
        left = audio_data[:, 0]
        right = audio_data[:, 1] if audio_data.shape[1] > 1 else audio_data[:, 0]

        # Add contribution from other channels
        if audio_data.shape[1] > 2:
            for i in range(2, audio_data.shape[1]):
                left += audio_data[:, i]
                right += audio_data[:, i]
            left /= (audio_data.shape[1] - 1)
            right /= (audio_data.shape[1] - 1)

        return np.stack([left, right], axis=1)

    def _resample(self, target_rate: int):
        """Resample audio to target sample rate"""
        if self.sample_rate == target_rate:
            return

        try:
            import librosa

            # Resample each channel
            resampled_channels = []
            for ch in range(self.channels):
                channel_data = self.audio_data[:, ch]
                resampled = librosa.resample(
                    channel_data,
                    orig_sr=self.sample_rate,
                    target_sr=target_rate
                )
                resampled_channels.append(resampled)

            self.audio_data = np.stack(resampled_channels, axis=1).astype(np.float32)
            self.sample_rate = target_rate
            self.frames = len(self.audio_data)
            self.duration = self.frames / self.sample_rate

        except ImportError:
            print("librosa not installed, cannot resample audio")
        except Exception as e:
            print(f"Error resampling audio: {e}")

    def get_metadata(self) -> Optional[AudioMetadata]:
        """Get audio file metadata"""
        if not self._is_loaded:
            return None

        format_name = os.path.splitext(self.file_path)[1][1:].upper()

        return AudioMetadata(
            duration=self.duration,
            sample_rate=self.sample_rate,
            channels=self.channels,
            frames=self.frames,
            format_name=format_name
        )

    def read_frames(self, frame_count: int, start_frame: Optional[int] = None) -> np.ndarray:
        """
        Read frames from audio file

        Args:
            frame_count: Number of frames to read
            start_frame: Starting frame position (None = current position)

        Returns:
            Numpy array of shape (frame_count, 2) with stereo audio data
        """
        if not self._is_loaded or self.audio_data is None:
            return np.zeros((frame_count, 2), dtype=np.float32)

        if start_frame is not None:
            self.current_frame = start_frame

        # Calculate available frames
        available = self.frames - self.current_frame

        if available <= 0:
            # Past end of file, return silence
            return np.zeros((frame_count, 2), dtype=np.float32)

        # Read what's available
        frames_to_read = min(frame_count, available)
        end_frame = self.current_frame + frames_to_read

        audio_chunk = self.audio_data[self.current_frame:end_frame]

        # Advance position
        self.current_frame = end_frame

        # Pad with silence if needed
        if frames_to_read < frame_count:
            padding = np.zeros((frame_count - frames_to_read, 2), dtype=np.float32)
            audio_chunk = np.vstack([audio_chunk, padding])

        return audio_chunk

    def seek(self, frame_number: int) -> bool:
        """Seek to specific frame position"""
        if not self._is_loaded:
            return False

        self.current_frame = max(0, min(frame_number, self.frames))
        return True

    def seek_time(self, time_seconds: float) -> bool:
        """Seek to specific time position"""
        if not self._is_loaded:
            return False

        frame = int(time_seconds * self.sample_rate)
        return self.seek(frame)

    def get_current_time(self) -> float:
        """Get current playback time in seconds"""
        if not self._is_loaded:
            return 0.0
        return self.current_frame / self.sample_rate

    def reset(self):
        """Reset to beginning of file"""
        self.current_frame = 0

    def is_loaded(self) -> bool:
        """Check if audio file is loaded"""
        return self._is_loaded

    def unload(self):
        """Unload audio data from memory"""
        self.audio_data = None
        self._is_loaded = False
        self.current_frame = 0
