# utils/timecode/runner.py
"""The setlist obeys the timecode (docs/ltc-plan.md phase 3, policy
layer).

`SetlistTimecodeRunner` maps a chase position onto the setlist's SMPTE
windows and issues transport commands. It is pure policy: the
transport is a small adapter the shell implements (`load_song`,
`play_at`, `seek`, `stop`, `position`), durations come from an
injected callable, and `update(t)` is driven by the shell's tick - so
the whole thing tests against fakes, no Qt anywhere.

Policy (settled in the plan):
- Entries with ``trigger.mode == "smpte"`` and a parseable timecode
  make windows ``[start, start + duration)``; everything else is
  invisible here. Overlaps resolve latest-start-wins (warned once).
- T inside a window: fire that song at ``T - start`` (mid-song joins
  are normal); once playing, drift within the threshold is left
  alone, larger drift is ONE seek per update.
- T outside every window: stop (the arbiter idle floor shows; pause
  looks are v1.8).
- T is None (no signal beyond freewheel): DO NOTHING - a dropped
  cable must never black out a gig. The show keeps running on its own
  clock until timecode returns.
"""

import logging
from typing import Callable, List, Optional, Tuple

from .tc import FrameRate, Timecode

logger = logging.getLogger(__name__)

# Two 25 fps frames: drift below this is jitter, not error.
DEFAULT_RESYNC_THRESHOLD_S = 0.08


class SetlistTimecodeRunner:
    """Chase position in, transport commands out."""

    def __init__(self, setlist, transport,
                 duration_of: Callable[[str], float],
                 rate: FrameRate,
                 resync_threshold_s: float = DEFAULT_RESYNC_THRESHOLD_S):
        """
        Args:
            setlist: config.models.Setlist (entries are read live on
                rebuild(), so edits during a session can be picked up).
            transport: adapter with load_song(name) / play_at(s) /
                seek(s) / stop() / position() -> float.
            duration_of: song name -> duration in seconds (the shell
                answers from the song's structure).
            rate: the FrameRate the entry timecodes are written in
                (from the detected incoming rate).
        """
        self.setlist = setlist
        self.transport = transport
        self.duration_of = duration_of
        self.rate = rate
        self.resync_threshold_s = resync_threshold_s

        self.windows: List[Tuple[float, float, str]] = []
        self.skipped: List[str] = []       # entries with broken timecodes
        self._current: Optional[str] = None
        self._initialized = False
        self.rebuild()

    # -- window table ------------------------------------------------------

    def rebuild(self) -> None:
        """Recompute the window table from the setlist."""
        windows: List[Tuple[float, float, str]] = []
        self.skipped = []
        for entry in self.setlist.entries:
            if entry.trigger.mode != "smpte":
                continue
            try:
                start = Timecode.parse(entry.trigger.timecode,
                                       self.rate).to_seconds()
            except ValueError:
                self.skipped.append(entry.song)
                logger.warning(
                    "Setlist entry %r has an unparseable SMPTE start "
                    "%r; it will not fire", entry.song,
                    entry.trigger.timecode)
                continue
            duration = max(0.0, float(self.duration_of(entry.song)))
            windows.append((start, start + duration, entry.song))
        windows.sort(key=lambda w: w[0])
        for (s0, e0, n0), (s1, _, n1) in zip(windows, windows[1:]):
            if s1 < e0:
                logger.warning(
                    "SMPTE windows overlap: %r (until %.2fs) and %r "
                    "(from %.2fs) - the later start wins while both "
                    "are open", n0, e0, n1, s1)
        self.windows = windows

    def resolve(self, t: float) -> Optional[Tuple[str, float]]:
        """The (song, position-in-song) for chase position ``t``, or
        None between windows. Overlaps: latest start wins."""
        hit = None
        for start, end, name in self.windows:
            if start <= t < end:
                hit = (name, t - start)   # later windows overwrite
        return hit

    # -- the tick -----------------------------------------------------------

    @property
    def current_song(self) -> Optional[str]:
        return self._current

    def update(self, t: Optional[float]) -> None:
        """Called by the shell's tick with the chase position (None =
        no signal)."""
        if t is None:
            return  # hold the show on its own clock; never go dark

        resolved = self.resolve(t)
        if resolved is None:
            if self._current is not None or not self._initialized:
                # Outside every window: nothing should play. The
                # first-update stop also silences whatever manual
                # playback was running when the chase was armed.
                self.transport.stop()
                self._current = None
            self._initialized = True
            return
        self._initialized = True

        name, song_pos = resolved
        if name != self._current:
            self.transport.load_song(name)
            self.transport.play_at(song_pos)
            self._current = name
            return

        drift = self.transport.position() - song_pos
        if abs(drift) > self.resync_threshold_s:
            logger.info("LTC chase resync: drift %+.3fs on %r",
                        drift, name)
            self.transport.seek(song_pos)
