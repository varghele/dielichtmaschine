# Bug reports

Open defects found but not yet fixed. Each has a strict-xfail test that
flips to a pass the moment the bug is fixed, so the suite tells us when
one is closed. Remove the entry (and drop the xfail) when that happens.

Format: one heading per bug, with the failing test, the root cause, the
user-visible effect, and a fix sketch.

## 1. Fixture capabilities ignore the patched mode

- **Test:** `tests/e2e/test_full_workflow.py::TestStep2Fixtures::test_capabilities_must_respect_the_patched_mode` (xfail, strict)
- **Where:** `utils/fixture_utils.py:116` in `detect_fixture_group_capabilities`
- **Root cause:** the scan walks `fixture_def['channels']`, i.e. every
  channel the `.qxf`/GDTF declares across all modes, instead of only the
  channels of the fixture's `current_mode`. `FixtureChannelMap` already
  resolves channels per mode correctly, so the two disagree.
- **Effect:** a fixture patched to a small mode reports capabilities it
  does not have in that mode. Example: a Varytec Hero Spot 60 in its
  `8 Channel` mode has no colour or gobo channel, yet the group reports
  `has_colour` / `has_special`, so the timeline offers colour and special
  sublanes whose DMX goes nowhere.
- **Fix sketch:** resolve the mode's channel list (as `FixtureChannelMap`
  does from `fixture.current_mode`) and iterate that, not the full
  `channels` list. Apply the same change to `get_color_wheel_options`
  (bug 2).

## 2. RGB-only colour edits are recorded as wheel colours

- **Test:** `tests/e2e/test_full_workflow.py::TestStep5Timeline::test_rgb_only_colour_edit_stays_in_rgb_mode` (xfail, strict)
- **Where:** `utils/fixture_utils.py:168` `get_color_wheel_options`
  (same mode-blind flaw as bug 1) and
  `timeline_ui/colour_block_dialog.py:418` in `accept()`.
- **Root cause:** `accept()` sets `color_mode="Wheel"` whenever wheel
  options exist, even when the user only touched the RGB sliders and
  never opened the wheel combo. `get_color_wheel_options` reports wheel
  options for modes that do not expose the wheel, compounding it.
- **Effect:** an RGB slider edit on a 6-channel PAR is stored with
  `color_mode="Wheel"`. Harmless while the fixture stays in a wheel-less
  mode, but the block silently flips to a wheel colour if the fixture is
  re-patched to a mode that has a colour wheel.
- **Fix sketch:** only set `color_mode="Wheel"` when the wheel combo was
  actually the active input (track which colour control the user last
  changed), and make `get_color_wheel_options` mode-aware per bug 1.
