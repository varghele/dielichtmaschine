"""
Synchronization bridge between Qt PlaybackEngine and sounddevice AudioEngine.
Ensures sample-accurate audio playback synchronized with UI timeline.
"""

from PyQt6.QtCore import QObject, pyqtSignal
from typing import List
from .audio_engine import AudioEngine
from .audio_mixer import AudioMixer
from .audio_file import AudioFile


class PlaybackSynchronizer(QObject):
    """Bridges Qt timer-based playback and PyAudio continuous audio stream"""

    # Signal emitted when audio position updates
    position_updated = pyqtSignal(float)

    def __init__(self, audio_engine: AudioEngine, audio_mixer: AudioMixer):
        super().__init__()

        self.audio_engine = audio_engine
        self.audio_mixer = audio_mixer

        # Connect audio engine to mixer
        self.audio_engine.set_mixer(self.audio_mixer)

        # Set position callback from audio engine
        self.audio_engine.set_position_callback(self._on_audio_position_update)

        # No drift compensation: the Shows and Structure tabs read the
        # playhead from the audio engine (get_accurate_position) on every
        # UI tick, so the audio clock is the only clock. The old 500 ms
        # "drift" check compared the audio position with its own reading
        # half a second earlier, fired on every tick and fed a signal
        # nothing listened to; removed 2026-10-12. A real audio vs
        # wall-clock drift monitor belongs to the v1.8 conductor clock.

        # Playback state
        self._is_playing = False

    def on_play_requested(self, position: float) -> bool:
        """Handle play request from PlaybackEngine.

        Returns:
            True if audio playback started successfully, False otherwise.
        """
        try:
            if not self.audio_engine.start_playback(position):
                print(f"Audio engine failed to start playback at position {position}")
                return False
            self._is_playing = True
            return True

        except Exception as e:
            print(f"Error starting audio playback: {e}")
            return False

    def on_pause_requested(self):
        """Handle pause request from PlaybackEngine"""
        try:
            self.audio_engine.pause_playback()
            self._is_playing = False

        except Exception as e:
            print(f"Error pausing audio playback: {e}")

    def on_stop_requested(self):
        """Handle stop request from PlaybackEngine"""
        try:
            self.audio_engine.stop_playback()
            self._is_playing = False

        except Exception as e:
            print(f"Error stopping audio playback: {e}")

    def on_seek_requested(self, position: float):
        """Handle seek request from PlaybackEngine"""
        try:
            self.audio_engine.seek(position)

        except Exception as e:
            print(f"Error seeking audio: {e}")

    def update_lanes(self, audio_lanes: List):
        """
        Update audio lanes in the mixer

        Args:
            audio_lanes: List of AudioLane objects from the project
        """
        try:
            # Clear existing lanes
            self.audio_mixer.clear_all_lanes()

            # Add new lanes
            for lane in audio_lanes:
                if lane.audio_file_path:
                    # Load audio file
                    audio_file = AudioFile(target_sample_rate=self.audio_engine.sample_rate)

                    if audio_file.load(lane.audio_file_path):
                        # Add to mixer
                        self.audio_mixer.add_lane(
                            id(lane),  # Use lane object id as unique identifier
                            audio_file,
                            lane.volume
                        )

                        # Apply mute/solo states
                        self.audio_mixer.set_mute_state(id(lane), lane.muted)
                        self.audio_mixer.set_solo_state(id(lane), lane.solo)

        except Exception as e:
            print(f"Error updating audio lanes: {e}")

    def update_lane_volume(self, lane_id: int, volume: float):
        """Update volume for a specific lane"""
        try:
            self.audio_mixer.update_lane_volume(lane_id, volume)
        except Exception as e:
            print(f"Error updating lane volume: {e}")

    def update_lane_mute(self, lane_id: int, muted: bool):
        """Update mute state for a specific lane"""
        try:
            self.audio_mixer.set_mute_state(lane_id, muted)
        except Exception as e:
            print(f"Error updating lane mute: {e}")

    def update_lane_solo(self, lane_id: int, solo: bool):
        """Update solo state for a specific lane"""
        try:
            self.audio_mixer.set_solo_state(lane_id, solo)
        except Exception as e:
            print(f"Error updating lane solo: {e}")

    def get_accurate_position(self) -> float:
        """Get sample-accurate position from audio engine"""
        return self.audio_engine.get_current_position()

    def _on_audio_position_update(self, position: float):
        """
        Called from audio thread when position updates

        This emits a Qt signal to safely update the UI thread
        """
        self.position_updated.emit(position)
