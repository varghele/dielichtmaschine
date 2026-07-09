# Setlist: Show becomes the evening, songs carry the parts

Reference: `design_handoff_lichtmaschine_app/screens/05b-show-structure-v2-setlist.html`
(1920x1080). The screen's status bar states the hierarchy change:
**SHOW (SETLIST) -> SONGS -> PARTS**. What the app calls a "Show" today
(parts + BPM + audio) is renamed **Song**; the Show is now the whole
evening: an ordered setlist of songs with per-song start triggers,
pause looks between songs, and a sync mode.

Decisions locked 2026-07-09:

- **Full model rename** (not UI-only): `Show` -> `Song` in
  `config/models.py`, plus a new `Setlist`. YAML writes `songs` +
  `setlist`; the loader accepts the legacy `shows` key forever
  (migrates to one setlist in order, no triggers, default pause look).
- **Data + UI only this pass.** Triggers, sync modes and pause looks are
  stored and edited; the engine that listens (MIDI PC/NOTE in, MTC/SMPTE
  chase) is v1.7 ("Live operations and clock sync") - LEARN and the
  MTC/SMPTE fields are honest placeholders until then.
- Runs in parallel with the timeline v3 track
  (`docs/timeline-v3-plan.md`).
- No Bibliothek topbar section, no .lms extension this pass (noted in
  ROADMAP.md v1.3).

UI copy is English (the design mock is German): "Pause look",
"Follows automatically", "After the song", "Start trigger", "Learn".
Separator " · ", no em-dashes.

## S1 - the model

New/renamed in `config/models.py`:

- `Song` = today's `Show` verbatim (parts, audio, analysis). Rename
  class + `Configuration.shows` -> `Configuration.songs`.
- `SongTrigger`: `mode` ("manual" | "midi_pc" | "midi_note" | "mtc" |
  "smpte" | "follow"), `value` (program/note number), `channel`,
  `timecode` (str, for mtc/smpte start times like "00:14:32:00").
  "follow" = chains automatically after the previous song's pause look.
- `PauseLook`: `mode` ("blackout" | "warm_white" | "hold_last" |
  "ambient_loop"), `level` (percent, warm_white), `until` ("trigger" |
  "duration"), `duration_s`. The ambient loop reuses the screensaver
  rig behaviour when the engine lands.
- `SetlistEntry`: `song` (name key), `trigger: SongTrigger`,
  `pause_after: PauseLook`.
- `Setlist`: `name`, `entries: List[SetlistEntry]`, `sync_mode`
  ("midi" | "mtc" | "smpte" | "manual"), `sync_device` (str).
- `Configuration.setlist: Setlist` (single setlist per config file for
  now - the design shows one per show file).

Serialization: YAML schema bump. Save writes `songs:` + `setlist:`;
load accepts `shows:` (legacy) and synthesizes a setlist from the sorted
song names with manual triggers and hold-last pause looks. Round-trip +
legacy-load tests; the compact serializer's per-file block tables
(`block_defs` / `light_block_defs`) are untouched - go through the
object model, never raw-YAML merges.

Rename ripple (inventory, updated as S1 executes): `gui/tabs/shows_tab.py`
(`config.shows`, `current_show_name`), `gui/tabs/structure_tab.py`,
`gui/gui.py` (rebind ladder, autosave fingerprint), `autogen/*` (show
generation entry points), `utils/to_xml/*` (workspace export reads
songs), `utils/config_merge.py`, demos generators + demo YAMLs
(regenerate via `python -m demos.generate_shows`), tests that construct
`Show(...)`. The public YAML stays loadable at every step.

## S2 - structure tab rebuild (three sub-stages, goldens each)

**S2a - setlist rail (left, 330px).** Numbered song cards (name,
duration, colour edge, trigger line in mono: "PC#5 · CH 1",
"NOTE C2 · CH 1", "Follows automatically"), active song highlighted
with accent border; dashed pause-look rows between songs; "+ SONG"
dashed tile; header with setlist name + "N SONGS · MM MIN" and the SYNC
segment (MIDI / MTC / SMPTE / MANUAL + device hint). Selecting a card
opens that song in the centre editor.

**S2b - song editor (centre).** Song title row (condensed display name,
mono meta "192.0 BPM · 4/4 · 19 BARS · 00:23", rename + delete
outline buttons); part cards restyled (3px part-colour top border,
tinted body, stat lines in mono) with INSTANT ▾ transition chips
between cards and a dashed + tile; master grid with a 150px header
column (MASTER · N BARS / AUDIO + filename) and the parts band +
waveform; snap hint line. Kills the dead zone and the legacy bottom
row: "Pause Show" is replaced by the per-entry pause looks (S2a), and
the old per-show TRIGGER row moves into the inspector (S2c).

**S2c - inspector (right, 340px).** SONG section: START-TRIGGER
segment (MIDI / MTC / SMPTE / MANUAL), value field + LEARN button
(disabled, tooltip "arrives with the sync engine (v1.7)"), MTC/SMPTE
start-time field; AFTER THE SONG pause-look dropdown (blackout /
warm white % / hold last look / ambient loop). PART section: stat
tiles (BPM / TIME SIG / BARS / COLOUR swatch) + TRANSITION OUT
dropdown. AUDIO ANALYSIS: energy / vocals / contrast as real progress
bars (accent fill for the leading metric), replacing the bare dashes.
DELETE PART pinned at the bottom.

## S3 - timeline linkage

The timeline's SONG selector shows setlist numbering ("02 · MONSTERS")
and orders by setlist position; songs not in the setlist list after a
divider. Autogen's "generate show from audio" wording becomes
"generate song from audio".

## S4 - engine (deferred to v1.7)

MIDI PC/NOTE input, MTC/SMPTE chase, pause-look output and the
follow-chain runner consume this model; roadmap v1.7 items cover them.
Until then the structure tab edits data and the runtime ignores it -
marked honestly in the inspector copy.

## Test matrix

- Model: round-trip songs+setlist; legacy `shows:` load synthesizes the
  setlist; trigger/pause-look defaults; entry reorder = setlist order.
- UI: rail card per entry + pause rows between; selection drives the
  editor; trigger edits persist to the entry; after-song dropdown maps
  to PauseLook modes; LEARN disabled; analysis bars bound to real
  values; goldens per sub-stage (structure_tab golden becomes three:
  rail / full tab dark / full tab light if needed - decide at S2a).
- Regression: full suite green at every stage; export hash check
  (`scripts/export_hash_check.py`) unchanged by the rename.
