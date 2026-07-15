"""
Real-time audio mixing for multiple lanes in Die Lichtmaschine.
Handles volume, mute, and solo processing.
"""

import numpy as np
import threading
from typing import Dict, Optional
from .audio_file import AudioFile


class AudioLaneState:
    """State information for an audio lane"""

    def __init__(self, lane_id: int, audio_file: AudioFile, volume: float = 1.0):
        self.lane_id = lane_id
        self.audio_file = audio_file
        self.volume = volume
        self.muted = False
        self.solo = False
        self.enabled = True


class AudioMixer:
    """Real-time audio mixer for multiple lanes"""

    def __init__(self):
        self._lanes: Dict[int, AudioLaneState] = {}
        self._lock = threading.Lock()
        self._has_solo_lanes = False

    def add_lane(self, lane_id: int, audio_file: AudioFile, volume: float = 1.0):
        """
        Add an audio lane to the mixer

        Args:
            lane_id: Unique identifier for the lane
            audio_file: Loaded AudioFile object
            volume: Initial volume (0.0-1.0)
        """
        with self._lock:
            lane_state = AudioLaneState(lane_id, audio_file, volume)
            self._lanes[lane_id] = lane_state

    def remove_lane(self, lane_id: int):
        """Remove an audio lane from the mixer"""
        with self._lock:
            if lane_id in self._lanes:
                del self._lanes[lane_id]
                self._update_solo_state()

    def clear_all_lanes(self):
        """Remove all lanes from the mixer"""
        with self._lock:
            self._lanes.clear()
            self._has_solo_lanes = False

    def update_lane_volume(self, lane_id: int, volume: float):
        """
        Update volume for a lane

        Args:
            lane_id: Lane identifier
            volume: Volume level (0.0-1.0)
        """
        with self._lock:
            if lane_id in self._lanes:
                self._lanes[lane_id].volume = max(0.0, min(1.0, volume))

    def set_mute_state(self, lane_id: int, muted: bool):
        """Set mute state for a lane"""
        with self._lock:
            if lane_id in self._lanes:
                self._lanes[lane_id].muted = muted

    def set_solo_state(self, lane_id: int, solo: bool):
        """Set solo state for a lane"""
        with self._lock:
            if lane_id in self._lanes:
                self._lanes[lane_id].solo = solo
                self._update_solo_state()

    def set_enabled_state(self, lane_id: int, enabled: bool):
        """Enable or disable a lane"""
        with self._lock:
            if lane_id in self._lanes:
                self._lanes[lane_id].enabled = enabled

    def _update_solo_state(self):
        """Update internal solo state flag"""
        self._has_solo_lanes = any(lane.solo for lane in self._lanes.values())

    def mix_frames(self, frame_count: int) -> np.ndarray:
        """
        Mix audio frames from all active lanes

        Args:
            frame_count: Number of frames to mix

        Returns:
            Mixed audio as numpy array of shape (frame_count, 2)
        """
        # Create output buffer (stereo)
        output = np.zeros((frame_count, 2), dtype=np.float32)

        with self._lock:
            if not self._lanes:
                return output

            # Check if any lanes should play
            has_audio = False

            for lane_state in self._lanes.values():
                # Skip if disabled or not loaded
                if not lane_state.enabled or not lane_state.audio_file.is_loaded():
                    continue

                # Skip if muted
                if lane_state.muted:
                    # Still need to advance the audio file position
                    lane_state.audio_file.read_frames(frame_count)
                    continue

                # Handle solo logic
                if self._has_solo_lanes and not lane_state.solo:
                    # Still need to advance the audio file position
                    lane_state.audio_file.read_frames(frame_count)
                    continue

                # Read frames from this lane
                try:
                    frames = lane_state.audio_file.read_frames(frame_count)

                    # Apply volume
                    if lane_state.volume != 1.0:
                        frames = frames * lane_state.volume

                    # Mix into output
                    output += frames
                    has_audio = True

                except Exception as e:
                    print(f"Error reading frames from lane {lane_state.lane_id}: {e}")
                    continue

        # Prevent clipping by limiting output range
        if has_audio:
            output = np.clip(output, -1.0, 1.0)

        return output

    def seek_all_lanes(self, time_seconds: float):
        """Seek all lanes to specific time position"""
        with self._lock:
            for lane_state in self._lanes.values():
                if lane_state.audio_file.is_loaded():
                    lane_state.audio_file.seek_time(time_seconds)

    def reset_all_lanes(self):
        """Reset all lanes to beginning"""
        with self._lock:
            for lane_state in self._lanes.values():
                if lane_state.audio_file.is_loaded():
                    lane_state.audio_file.reset()

    def get_lane_count(self) -> int:
        """Get number of lanes in mixer"""
        with self._lock:
            return len(self._lanes)

    def has_lanes(self) -> bool:
        """Check if mixer has any lanes"""
        with self._lock:
            return len(self._lanes) > 0

    def get_current_time(self) -> float:
        """
        Get current playback time (from first lane)
        Used for position tracking
        """
        with self._lock:
            if not self._lanes:
                return 0.0

            # Get time from first available lane
            for lane_state in self._lanes.values():
                if lane_state.audio_file.is_loaded():
                    return lane_state.audio_file.get_current_time()

            return 0.0
