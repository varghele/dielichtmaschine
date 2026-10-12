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

## 2. The CSV rig sheet drops secondary groups

- **Test:** `tests/unit/test_fixture_io.py::TestCsvSecondaryGroups::test_csv_round_trip_keeps_every_group` (xfail, strict)
- **Where:** `utils/fixture_io.py`, `write_fixture_list_csv` (writes
  `fixture.group`, the primary only) and `read_fixture_list_csv` (reads
  one name from the `group` column).
- **Root cause:** the CSV sheet predates multi-group fixtures and was
  never given a way to carry more than one group per row.
- **Effect:** exporting the rig as CSV and importing it again puts every
  fixture in its first group only; secondary memberships (and the lanes
  and indexed targets that depend on them) are lost without a warning.
  The JSON rig keeps them (`groups` list).
- **Fix sketch:** needs a file-format choice that hand-written sheets
  can live with: either a separator inside the `group` column (e.g.
  `Front;Side`, first = primary) or an extra `groups` column next to
  `group`, read when present. Either way an old single-group sheet must
  keep importing unchanged, and the CSV import wizard
  (`utils/csv_table_import.py`) should accept the same convention.
