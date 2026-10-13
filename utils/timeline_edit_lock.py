"""The one lock between timeline edits and the playback frame.

Show playback renders on the output arbiter's thread (44 Hz) and reads
the live lane blocks, while the timeline UI edits the same blocks on the
UI thread. A drag shifts a block's start, its end and every sub-block in
separate statements; a frame rendered between two of them saw a torn
interval (start moved, end not yet; siblings half-shifted) and output
one wrong frame, often a block_ended + block_started restart.

``ShowsArtNetController.render`` holds this lock while it schedules and
computes a frame; every UI path that changes more than one interval
field of a block holds it for the mutation only (float math, a few
microseconds, so the UI waits at most one frame). Keep the critical
sections free of Qt calls and of the controller's own ``_render_lock``:
render takes ``_render_lock`` first, so taking them the other way round
here would deadlock.

Reentrant, so a locked helper may call another.
"""

import threading

TIMELINE_EDIT_LOCK = threading.RLock()
