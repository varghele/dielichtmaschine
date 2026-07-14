# LTC input: SMPTE-chased shows - implementation plan

Planned 2026-07-14 (ROADMAP v1.4 "The standalone switch", first item).
Goal: decode SMPTE linear timecode from an audio input and make the
setlist obey it - a setlist entry with an SMPTE start trigger fires its
song when incoming timecode reaches its start time, and the playhead
chases the signal from then on. This is the SMPTE slice of the setlist
trigger engine; MIDI PC/NOTE triggers, LEARN, MTC, pause looks and the
"follows automatically" chain stay in v1.8 (they reuse the chase
abstraction built here).

Out of scope by decision (2026-07-14): LTC *output* (no generator
hardware on the desk, no demand yet - the synthetic generator below is
test infrastructure, not a product feature), MTC (v1.8, same chase,
different transport), any pause-look behaviour between songs (v1.8;
the arbiter idle floor covers the gap).

## What already exists (build on, do not duplicate)

- **Audio capture**: `audio/live_input.py` `LiveAudioInput` (sounddevice
  InputStream -> `AudioRingBuffer`, mono float32, 44.1 kHz default) and
  `audio/device_manager.py` (curated device list, host-API
  classification). LTC is a ~2.4 kbaud biphase signal - 44.1 kHz mono is
  ample.
- **Setlist data**: `config/models.py` - `SongTrigger` (mode `"smpte"`,
  `timecode: "HH:MM:SS:FF"`), `SetlistEntry`, `Setlist`
  (`sync_mode: "smpte"`, `sync_device` hint). The Structure tab already
  stores, edits and validates all of it; nothing listens yet.
- **Transport**: `gui/tabs/shows_tab.py` owns the playhead
  (`_start_playback` / `_pause_playback` / `_stop_playback` /
  `_seek_to(position)`, `_get_current_position`), the song selector
  (itemData carries the raw song name), and
  `song_structure.get_total_duration()`. The ArtNet layer pulls position
  via `set_position_callback` at 44 Hz.
- **Status surface**: the Live tab SYNC chip (`#OutputReadout`, "SYNC
  INT" today) and the Structure tab sync segment (MIDI / MTC / SMPTE /
  MANUAL) with the "Device: -" hint label.

## Architecture

New package `utils/timecode/` - pure logic, no Qt below the service
layer:

```
utils/timecode/
  tc.py         Timecode value object + fps math (incl. drop-frame)
  ltc.py        LTCDecoder: audio samples in, LTCFrame stream out
  generator.py  generate_ltc(): synthetic LTC audio (test + smoke rig)
  chase.py      TimecodeChase: frame stream -> continuous clock + state
  runner.py     SetlistTimecodeRunner: chase clock -> transport commands
audio/
  ltc_input.py  LTCInputService: LiveAudioInput -> decoder -> chase,
                on a reader thread, Qt signals at the edge
```

Data flow, one direction only:

```
audio device -> ring buffer -> LTCDecoder -> TimecodeChase -> SetlistTimecodeRunner -> ShowsTab transport
                                                  |                                        |
                                                  v                                        v
                                            SYNC chip state                       playhead / song start
```

### tc.py - timecode math

`Timecode(hours, minutes, seconds, frames, fps, drop_frame)` with
`parse("HH:MM:SS:FF", fps)`, `to_seconds()`, `from_seconds()`,
`to_frame_count()` / `from_frame_count()`. Rates: 24, 25, 30, and 29.97
drop-frame (drop 2 frame NUMBERS per minute except minutes divisible by
10 - label arithmetic, the signal itself never skips). 23.976 and
non-drop 29.97 are out: rare on stage, easy to add later. All offset
math (`incoming TC - entry start TC`) happens on frame counts, never on
float seconds, so an hour-long chase cannot drift by accumulation.

### ltc.py - the decoder

Streaming, allocation-light, stateless API: `feed(samples) ->
List[LTCFrame]`; carries state across calls so callers can feed
arbitrary block sizes straight from the ring buffer.

- **Biphase-mark**: a transition at every bit-cell boundary; an extra
  mid-cell transition = 1, none = 0. Decode from zero-crossing
  intervals against an adaptive cell-period estimate (median of recent
  intervals), so the decoder tracks tape-speed-style rate wobble and
  needs no a-priori fps. Amplitude and polarity are irrelevant by
  construction (only crossing times matter); a DC-blocking one-pole
  filter in front handles offset inputs.
- **Framing**: 80-bit shift register, hunt for the sync word
  `0011 1111 1111 1101` (bits 64-79); on match, decode the BCD time
  fields, the drop-frame flag (bit 10), and keep user bits raw (no
  consumer yet). Parity is soft: log, do not reject (real-world
  generators get BGF/parity wrong constantly).
- **fps inference**: from the measured frame cadence (frames arriving
  per second of samples) snapped to {24, 25, 29.97, 30}, cross-checked
  against the highest frame number seen; exposed as
  `LTCFrame.fps_estimate` and firmed up by the chase after a few
  frames.
- Reverse play detection (sync word arriving mirrored) is explicitly
  NOT handled in v1: chasing a show backwards has no meaning here.

### generator.py - synthetic LTC

`generate_ltc(start, fps, seconds, sample_rate=44100, amplitude=0.8,
polarity=+1, drop_frame=False) -> np.ndarray` plus a
`write_ltc_wav(path, ...)` helper. The inverse of the decoder, but
implemented INDEPENDENTLY from the spec (bit layout tables written
separately, not shared constants) so a round-trip test actually proves
both sides rather than proving `x == x`. Also the manual-check tool:
generate a WAV, play it at the line-in from a phone/DAW, watch the show
chase (the user has no LTC generator hardware - this file IS the bench
signal source).

### chase.py - from frames to a clock

`TimecodeChase` consumes `(LTCFrame, monotonic_arrival_time)` and
answers `position(now_monotonic) -> Optional[float]` (seconds on the
incoming timeline) plus `state` in:

- `NO_SIGNAL` - never locked, or freewheel expired.
- `LOCKED` - N consecutive coherent frames (default 4: ~130-170 ms).
  Coherent = each frame is its predecessor + 1 at the agreed fps.
- `FREEWHEEL` - signal lost while locked: extrapolate at 1.0x from the
  last good frame for `freewheel_s` (default 2.0 s), then drop to
  NO_SIGNAL.

Jitter policy: arrival times wobble (audio block granularity, ~12 ms at
512/44.1k), so the clock is a small linear fit over the last ~8 frames
(offset + rate), clamped to rate 1.0 +- 5%. A discontinuity (incoming
frame more than `jump_threshold_s` = 1.0 s away from the fit) resets
the fit and reports a `jumped` flag - the runner decides what a jump
means. Everything takes an injectable clock; no `time.monotonic()`
calls buried in logic (same testability rule as the beat tracker and
the live engine).

### runner.py - the setlist obeys

`SetlistTimecodeRunner(config, transport, clock)` - the policy layer.
`transport` is a small adapter protocol implemented by the shell
(`load_song(name)`, `play_at(seconds)`, `seek(seconds)`, `stop()`,
`position() -> float`), so the runner is testable against a fake and
never imports Qt.

Resolution: entries with `trigger.mode == "smpte"` and a valid
timecode, sorted by start. Song windows are `[start, start +
song_duration)` (duration from the song structure). Given chase
position T:

- T inside an entry's window -> that entry at song position
  `T - start`. Mid-song joins are normal (operator starts the desk
  tape mid-set at soundcheck).
- T between windows / before the first -> no song: stop playback (the
  arbiter idle floor shows; pause looks arrive in v1.8).
- Overlapping windows (authoring error) -> latest start wins; surface
  a warning once.
- Entries with other trigger modes are invisible to this runner.

Runtime policy, evaluated on a ~10 Hz tick plus on every chase state
change:

- **Fire**: resolved entry differs from the playing one ->
  `load_song`, `play_at(T - start)`.
- **Chase**: same entry -> compare `transport.position()` with the
  chase; |drift| <= `resync_threshold_s` (default 0.08, two 25 fps
  frames) does nothing, larger drift issues one `seek`. No varispeed
  in v1 - jump-resync is what most lighting consoles do and the 44 Hz
  DMX render never interpolates across more than one frame anyway.
- **Jump** (chase reports one): re-resolve from scratch - a desk
  locate lands wherever it lands.
- **Signal loss**: FREEWHEEL keeps playing on the extrapolated clock;
  NO_SIGNAL holds the show RUNNING on its own internal clock (a
  dropped cable must not black out a gig) and re-locks/possibly
  resyncs when signal returns. Stopping is only ever an operator
  action or the end of the resolved window.
- **Song end, TC keeps running**: window exits -> stop; the next
  window fires when reached.

### audio/ltc_input.py - the service

`LTCInputService`: owns a `LiveAudioInput` (device index resolved from
`Setlist.sync_device` via the device manager, default input if unset),
a reader thread draining the ring buffer into the decoder/chase every
~50 ms, and the Qt boundary - a `QObject` facade emitting
`state_changed(str)`, `timecode(str)` (throttled to ~4 Hz for display)
and calling the runner on its tick. Start/stop is idempotent;
construction never opens a stream (the dialog-less failure mode is a
disabled chip + statusbar warning, not a crash). The service lives on
`MainWindow` (accessor like `output_arbiter()`) so it survives tab
switches; the SHELL owns arm/disarm policy, tabs only display - same
ownership rule the arbiter established.

### UI wiring (minimal, v1.4 scope)

- **Structure tab sync row**: the SMPTE segment already exists. Add an
  ARM CHASE toggle chip (enabled only when `sync_mode == "smpte"` and
  at least one entry has an SMPTE trigger) and a device combo replacing
  the "Device: -" placeholder (curated input list from
  `device_manager`, persisted to `Setlist.sync_device`).
- **Live tab SYNC chip**: reads the service - `SYNC LTC` with state
  styling (LOCKED on-state, FREEWHEEL warning, NO SIGNAL off) and the
  last received timecode in the tooltip. `SYNC INT` stays when the
  chase is disarmed.
- **Transport interplay**: arming hands the transport to the runner;
  the operator's STOP disarms (one obvious escape hatch); play/pause
  stay disabled while armed (the desk is the master). Disarm restores
  manual behaviour exactly.

## Phases

### Phase 0 - timecode math + generator + decoder (pure DSP)

`tc.py`, `generator.py`, `ltc.py`. No Qt, no audio device, no config.
Tests (`tests/unit/test_timecode.py`, `test_ltc_decoder.py`):

- Timecode parse/format/seconds round-trips at all four rates;
  drop-frame arithmetic pinned against known vectors (e.g.
  00:09:59;29 + 1 frame = 00:10:00;00, but 00:00:59;29 + 1 =
  00:01:00;02).
- Generate -> decode round-trip: every rate, multiple start times,
  1-minute streams decode every frame in order with zero errors.
- Robustness: inverted polarity, low amplitude (0.05), DC offset,
  additive noise (SNR ~20 dB), 48 kHz sample rate, feeding in odd
  block sizes (1..4096), stream starting mid-frame, a 200 ms dropout
  (decoder recovers on the next sync word).
- fps inference lands on the truth for all four rates.

### Phase 1 - chase (fake clock)

`chase.py`. Tests (`tests/unit/test_timecode_chase.py`):

- Lock after N coherent frames; position() interpolates between frames
  and tracks a +-2% rate skew within one frame of truth.
- Jittered arrival times (+-15 ms) do not wobble position() by more
  than a frame.
- Dropout -> FREEWHEEL extrapolation stays continuous; expiry ->
  NO_SIGNAL; recovery re-locks.
- A 10 s locate lands as `jumped`, not as a 10 s freewheel glide.

### Phase 2 - input service (no real device in tests)

`audio/ltc_input.py`. Tests (`tests/unit/test_ltc_input.py`): inject
generated audio straight into the ring buffer (no InputStream), assert
frames flow decoder -> chase -> signals; device resolution from
`sync_device` (hint matching the device manager's curated list, fall
back to default); idempotent start/stop; a failing device open degrades
to NO_SIGNAL + warning, never raises into the caller.

### Phase 3 - setlist runner + shell integration

`runner.py`, the transport adapter on ShowsTab/MainWindow, ARM chip,
device combo, SYNC chip. Tests (`tests/unit/test_setlist_runner.py` +
tab tests):

- Resolution table: before first window, mid-song join, between songs,
  after last, overlap warning, non-SMPTE entries ignored.
- Fire/chase/drift: fake transport records load/play/seek; small drift
  ignored, big drift = exactly one seek; jump re-resolves; NO_SIGNAL
  does not stop a running song; window exit stops.
- End to end without hardware: generated LTC audio -> decoder -> chase
  -> runner against a 2-song config; song 1 fires at its start TC,
  playhead tracks within a frame, song 2 fires when its window opens.
- UI: ARM enablement rules, STOP disarms, SYNC chip states, device
  combo persists to `Setlist.sync_device`.

### Manual checkpoint (user, desktop + line-in)

Generate a WAV with `write_ltc_wav` covering the demo setlist's
trigger times, play it from a phone/DAW into the line-in, ARM CHASE:
songs must fire at their timecodes, the playhead must follow, pulling
the cable mid-song must NOT stop the show, replugging must re-lock.
(No LTC generator hardware needed - the WAV is the generator.)

## Status

- [x] Phase 0 - tc.py + generator + decoder (2026-07-14: 38 tests in
      test_timecode.py + test_ltc_decoder.py, all four rates round-trip
      incl. the drop-frame boundary, noise/polarity/DC/48k robustness,
      dropout re-lock < 0.2 s, chunked feed == one-shot exactly)
- [x] Phase 1 - chase (2026-07-14: 15 tests in test_timecode_chase.py -
      lock/coherence, jitter and 2% skew tracking, rate clamp, unity
      freewheel, expiry, seamless short-dropout relock, forward and
      backward locates reported exactly once, drop-frame real-seconds
      positions)
- [x] Phase 2 - input service (2026-07-14: audio/ltc_input.py, 11 tests
      in test_ltc_input.py - generated audio through a real ring buffer
      into lock/position/label/rate, state signal walks
      lock/freewheel/no-signal, display throttle, idempotent
      start/stop, failing device degrades cleanly, device-hint
      resolution incl. loose match. Arrival anchoring per drain, so
      audio-clock drift cannot accumulate)
- [ ] Phase 3 - runner + shell integration + SYNC chip
- [ ] Manual checkpoint on the bench
