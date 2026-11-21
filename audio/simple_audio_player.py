"""Song playback through pygame.mixer.

The one audio OUTPUT path of the app: the Shows and Structure tabs play
their song's audio through :func:`shared_player`. pygame's mixer (and
``pygame.mixer.music``) is a process-wide singleton, so there is exactly
one player; a tab takes it over with :meth:`SimpleAudioPlayer.claim`
before playing and only drives it while it is the owner, so one tab
never pauses, seeks or re-volumes the other tab's song.

Live audio INPUT (Auto mode, LTC) is separate and stays on sounddevice
(``audio/live_input.py``, ``audio/ltc_input.py``).
"""

import logging
import os
import threading
import time
from typing import Callable, List, Optional

logger = logging.getLogger(__name__)

try:
    import pygame
    PYGAME_AVAILABLE = True
except ImportError:
    PYGAME_AVAILABLE = False
    logger.warning("pygame not available - install with: pip install pygame")

DEFAULT_FREQUENCY = 44100
DEFAULT_BUFFER_SIZE = 2048


def list_output_devices() -> List[str]:
    """SDL playback device names, in SDL's order ([] when unavailable).

    The names are what :meth:`SimpleAudioPlayer.initialize` accepts as
    ``devicename``. SDL needs its audio subsystem up to enumerate, so the
    mixer is opened briefly when nothing has opened it yet."""
    if not PYGAME_AVAILABLE:
        return []
    try:
        from pygame._sdl2 import audio as sdl_audio
    except ImportError:
        return []
    opened_here = False
    try:
        if not pygame.mixer.get_init():
            pygame.mixer.init()
            opened_here = True
        return list(sdl_audio.get_audio_device_names(False))
    except Exception as e:
        logger.warning(f"Could not list audio output devices: {e}", exc_info=True)
        return []
    finally:
        if opened_here:
            try:
                pygame.mixer.quit()
            except Exception:
                pass


class SimpleAudioPlayer:
    """Plays one audio file through pygame.mixer.music.

    Position is tracked from the wall clock since the last play / seek;
    pygame handles decoding and the audio thread itself.
    """

    def __init__(self):
        self._is_initialized = False
        self._is_playing = False
        self._current_file: Optional[str] = None
        self._duration: float = 0.0
        self._start_time: float = 0.0  # When playback started (wall clock)
        self._start_position: float = 0.0  # Position when playback started
        self._paused_position: float = 0.0
        self._volume: float = 1.0  # Volume level (0.0 to 1.0)
        self._muted = False

        # Mixer parameters in effect (set by initialize).
        self._frequency = DEFAULT_FREQUENCY
        self._buffer_size = DEFAULT_BUFFER_SIZE
        self._requested_device = ""   # what the caller asked for
        self._active_device = ""      # what is open ("" = system default)

        # The tab currently driving the player (see claim()).
        self.owner = None

        # Position tracking thread
        self._position_callback: Optional[Callable[[float], None]] = None
        self._position_thread: Optional[threading.Thread] = None
        self._stop_position_thread = False

    # -- mixer lifecycle ---------------------------------------------------

    def initialize(self, frequency: int = DEFAULT_FREQUENCY,
                   buffer_size: int = DEFAULT_BUFFER_SIZE,
                   devicename: str = "") -> bool:
        """Open the mixer on ``devicename`` ("" = system default).

        A named device that cannot be opened (unplugged, renamed) falls
        back to the system default and reports it in Help > Warnings, so
        a missing interface never leaves the show silent without a
        word."""
        if not PYGAME_AVAILABLE:
            logger.warning("pygame not available")
            return False

        self._frequency = int(frequency)
        self._buffer_size = int(buffer_size)
        self._requested_device = devicename or ""
        if self._requested_device:
            try:
                self._open_mixer(self._requested_device)
                self._active_device = self._requested_device
                self._is_initialized = True
                return True
            except Exception as e:
                from utils import user_warnings
                user_warnings.warn(
                    f"Audio output device '{self._requested_device}' could "
                    f"not be opened ({e}); playing on the system default "
                    f"device instead",
                    category="audio",
                    once_key=f"audio-device:{self._requested_device}")
        try:
            self._open_mixer(None)
            self._active_device = ""
            self._is_initialized = True
            return True
        except Exception as e:
            logger.warning(f"Failed to initialize pygame mixer: {e}", exc_info=True)
            return False

    def _open_mixer(self, devicename: Optional[str]) -> None:
        if pygame.mixer.get_init():
            pygame.mixer.quit()
        pygame.mixer.init(frequency=self._frequency, size=-16, channels=2,
                          buffer=self._buffer_size, devicename=devicename)

    def reconfigure(self, frequency: int, buffer_size: int,
                    devicename: str = "") -> bool:
        """Re-open the mixer with new parameters, keeping the loaded file,
        the position and the play state. A no-op when nothing changed."""
        if (self._is_initialized and int(frequency) == self._frequency
                and int(buffer_size) == self._buffer_size
                and (devicename or "") == self._requested_device):
            return True
        was_playing = self._is_playing
        position = self.get_current_position()
        current_file = self._current_file
        self.cleanup()
        if not self.initialize(frequency, buffer_size, devicename):
            return False
        if current_file and self.load(current_file):
            self._paused_position = position
            if was_playing:
                self.play(position)
        return True

    def cleanup(self):
        """Stop playback and close the mixer."""
        self.stop()
        if self._is_initialized:
            try:
                pygame.mixer.quit()
            except Exception:
                pass
            self._is_initialized = False

    @property
    def active_device(self) -> str:
        """The device the mixer is open on ("" = system default)."""
        return self._active_device

    @property
    def frequency(self) -> int:
        return self._frequency

    @property
    def buffer_size(self) -> int:
        return self._buffer_size

    # -- ownership ---------------------------------------------------------

    def claim(self, owner, file_path: str) -> bool:
        """Make ``owner`` the player's driver with ``file_path`` loaded.

        Stops whatever the previous owner was playing, (re)loads the file
        when it differs from the loaded one, and returns whether the
        file is ready."""
        if self.owner is not owner:
            self.stop()
            self.owner = owner
        if self._current_file != file_path:
            return self.load(file_path)
        return True

    def is_owned_by(self, owner) -> bool:
        return self.owner is owner

    def release(self, owner) -> None:
        """Stop and drop ownership if ``owner`` holds the player."""
        if self.owner is owner:
            self.stop()
            self.owner = None

    # -- file + transport --------------------------------------------------

    def load(self, file_path: str) -> bool:
        """Load an audio file."""
        if not self._is_initialized:
            if not self.initialize(self._frequency, self._buffer_size,
                                   self._requested_device):
                return False

        if not os.path.exists(file_path):
            logger.warning(f"Audio file not found: {file_path}")
            return False

        try:
            # Stop any current playback
            self.stop()

            # Load the file
            pygame.mixer.music.load(file_path)
            self._current_file = file_path
            self._apply_volume()

            # Get duration using a Sound object (temporary)
            try:
                sound = pygame.mixer.Sound(file_path)
                self._duration = sound.get_length()
                del sound  # Free memory
            except Exception:
                # Fallback: estimate from file size (rough)
                logger.debug("Could not read the song length; estimating", exc_info=True)
                self._duration = 300.0  # Default 5 minutes

            self._paused_position = 0.0
            return True

        except Exception as e:
            logger.warning(f"Failed to load audio file: {e}", exc_info=True)
            return False

    def set_position_callback(self, callback: Callable[[float], None]):
        """Set callback for position updates (called ~10 times per second)."""
        self._position_callback = callback

    def _position_update_loop(self):
        """Background thread that reports position."""
        while not self._stop_position_thread and self._is_playing:
            if self._position_callback:
                try:
                    pos = self.get_current_position()
                    self._position_callback(pos)
                except Exception:
                    logger.debug("Position callback failed", exc_info=True)
            time.sleep(0.1)  # Update 10 times per second

    def play(self, start_position: float = 0.0) -> bool:
        """Start playback from position."""
        if not self._is_initialized or not self._current_file:
            return False

        try:
            # pygame.mixer.music.play() takes start position in seconds
            pygame.mixer.music.play(start=start_position)
            self._is_playing = True
            self._start_time = time.time()
            self._start_position = start_position

            # Start position update thread
            self._stop_position_thread = False
            self._position_thread = threading.Thread(target=self._position_update_loop, daemon=True)
            self._position_thread.start()

            return True
        except Exception as e:
            logger.warning(f"Failed to start playback: {e}", exc_info=True)
            return False

    def pause(self):
        """Pause playback."""
        if self._is_playing:
            self._paused_position = self.get_current_position()
            pygame.mixer.music.pause()
            self._is_playing = False
            self._stop_position_thread = True

    def unpause(self):
        """Resume from pause."""
        if not self._is_playing and self._current_file:
            pygame.mixer.music.unpause()
            self._is_playing = True
            self._start_time = time.time()
            self._start_position = self._paused_position

            # Restart position thread
            self._stop_position_thread = False
            self._position_thread = threading.Thread(target=self._position_update_loop, daemon=True)
            self._position_thread.start()

    def stop(self):
        """Stop playback."""
        self._stop_position_thread = True
        self._is_playing = False
        self._paused_position = 0.0
        try:
            pygame.mixer.music.stop()
        except Exception:
            pass

    def seek(self, position: float):
        """Seek to position in seconds."""
        if not self._current_file:
            return

        was_playing = self._is_playing

        # pygame doesn't have a seek function, need to restart from position
        try:
            pygame.mixer.music.stop()
            if was_playing:
                pygame.mixer.music.play(start=position)
                self._start_time = time.time()
                self._start_position = position
            else:
                self._paused_position = position
        except Exception as e:
            logger.warning(f"Seek failed: {e}", exc_info=True)

    def get_current_position(self) -> float:
        """Get current playback position in seconds."""
        if not self._is_playing:
            return self._paused_position

        # Calculate position from wall clock
        elapsed = time.time() - self._start_time
        position = self._start_position + elapsed

        # Clamp to duration
        return min(position, self._duration)

    def get_duration(self) -> float:
        """Get audio duration in seconds."""
        return self._duration

    def is_playing(self) -> bool:
        """Check if currently playing."""
        return self._is_playing

    def is_loaded(self) -> bool:
        """Check if a file is loaded."""
        return self._current_file is not None

    @property
    def current_file(self) -> Optional[str]:
        return self._current_file

    # -- volume + mute -----------------------------------------------------

    def set_volume(self, volume: float):
        """Set playback volume, 0.0 (silent) to 1.0 (full). Muting keeps
        the volume and restores it on unmute."""
        self._volume = max(0.0, min(1.0, volume))
        self._apply_volume()

    def get_volume(self) -> float:
        """Get current volume level."""
        return self._volume

    def set_muted(self, muted: bool):
        self._muted = bool(muted)
        self._apply_volume()

    def is_muted(self) -> bool:
        return self._muted

    def effective_volume(self) -> float:
        """What the mixer is actually told: 0 while muted."""
        return 0.0 if self._muted else self._volume

    def _apply_volume(self):
        if self._is_initialized:
            try:
                pygame.mixer.music.set_volume(self.effective_volume())
            except Exception as e:
                logger.warning(f"Failed to set volume: {e}", exc_info=True)


_shared_player: Optional[SimpleAudioPlayer] = None


def shared_player() -> Optional[SimpleAudioPlayer]:
    """The app's one song player (None without pygame).

    Created lazily and NOT initialized: the first tab to play opens the
    mixer with the stored Audio Settings (see
    :func:`ensure_shared_player`)."""
    global _shared_player
    if not PYGAME_AVAILABLE:
        return None
    if _shared_player is None:
        _shared_player = SimpleAudioPlayer()
    return _shared_player


def ensure_shared_player() -> Optional[SimpleAudioPlayer]:
    """The shared player with its mixer open on the stored Audio Settings
    (Settings > Audio Settings), or None when no output can be opened."""
    player = shared_player()
    if player is None:
        return None
    if not player._is_initialized:
        from utils.app_settings import audio_output_settings
        s = audio_output_settings()
        if not player.initialize(s["sample_rate"], s["buffer_size"],
                                 s["output_device"]):
            return None
    return player


def apply_output_settings(sample_rate: int, buffer_size: int,
                          output_device: str) -> bool:
    """Re-open an already-open shared player with new parameters (keeps
    the song and position). A player that was never opened picks the
    stored settings up on first use, so there is nothing to do then."""
    player = shared_player()
    if player is None or not player._is_initialized:
        return True
    return player.reconfigure(sample_rate, buffer_size, output_device)


def _reset_shared_player_for_tests() -> None:
    global _shared_player
    if _shared_player is not None:
        _shared_player.cleanup()
    _shared_player = None


# Quick test
if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python simple_audio_player.py <audio_file>")
        sys.exit(1)

    player = SimpleAudioPlayer()
    if not player.initialize():
        print("Failed to initialize")
        sys.exit(1)

    if not player.load(sys.argv[1]):
        print("Failed to load file")
        sys.exit(1)

    print(f"Duration: {player.get_duration():.2f}s")
    print("Playing... Press Ctrl+C to stop")

    player.set_position_callback(lambda p: print(f"\rPosition: {p:.2f}s", end="", flush=True))
    player.play()

    try:
        while player.is_playing():
            time.sleep(0.1)
    except KeyboardInterrupt:
        pass

    player.cleanup()
    print("\nDone")
