# timeline_ui/locking.py
"""The per-song lock's shared refusal feedback (v1.5, 2026-07-22).

Song.locked is an EDITOR fence: every timeline/structure mutation
handler early-returns when the owning song is locked, and calls
flash_locked so the refusal is visible without a modal. Playback,
export, morphing and the setlist are untouched by design - as are the
lane mute/solo/snap toggles (output controls, not show content) and
every read-only path (selection, copy, save-as-riff).

Kept in timeline_ui so both the timeline widgets and the gui tabs can
import it without a gui -> timeline_ui -> gui cycle.
"""

LOCKED_MSG = "Song is locked · unlock to edit"


def flash_locked(widget) -> None:
    """Non-modal 'no': a transient statusbar message on the widget's
    window (the gui.py convert-report precedent). Silent when the
    widget has no window or the window has no statusbar (headless
    tests, bare-widget hosts) - the early-return is the enforcement,
    this is only the explanation."""
    window = widget.window() if widget is not None else None
    statusbar = getattr(window, "statusbar", None)
    if statusbar is not None:
        try:
            statusbar.showMessage(LOCKED_MSG, 6000)
        except Exception:
            pass
