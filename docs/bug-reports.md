# Bug reports

Open defects found but not yet fixed. Each has a strict-xfail test that
flips to a pass the moment the bug is fixed, so the suite tells us when
one is closed. Remove the entry (and drop the xfail) when that happens.

Format: one heading per bug, with the failing test, the root cause, the
user-visible effect, and a fix sketch.

## 1. RGB-only colour edits are recorded as wheel colours

- **Test:** `tests/unit/test_fixture_caches.py::TestColourDialogWheelMode::test_rgb_only_edit_on_a_wheel_mode_records_rgb` (xfail, strict)
- **Where:** `timeline_ui/colour_block_dialog.py` in `accept()`.
- **Root cause:** `accept()` sets `color_mode="Wheel"` whenever wheel
  options exist, even when the user only touched the RGB sliders and
  never opened the wheel combo.
- **Effect:** on a fixture whose patched mode has both RGB and a colour
  wheel / macro channel (the Stairville par in `8 Channel` mode), an
  RGB slider edit is stored as a wheel pick, and playback writes the
  wheel position onto the macro channel. The mode-blind wheel options
  that made this hit wheel-less modes too (a 6 channel par) were fixed
  in v1.5.5 (G5): wheel options now come from the patched mode.
- **Fix sketch:** only set `color_mode="Wheel"` when the wheel combo was
  actually the active input (track which colour control the user last
  changed). Mind wheel-only movers, whose RGB picks are synced to the
  nearest wheel slot today.
