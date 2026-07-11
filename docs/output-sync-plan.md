# Output and synchronisation architecture

Promoted from todo.md after the architecture discussion on 2026-07-11
(decisions confirmed by the user in-session). This is the plan for the
single output arbiter, the merge model, the shared clock and the
phased build. Engine work maps to roadmap v1.7 (clock sync, setlist
trigger engine) and Live plan stage E (busk-on-top merge); this plan
wires existing milestones together and invents no new one.

**Status (2026-07-11): phases 0-3 SHIPPED**, same day, branch
v1.2-rebrand - phase 0 masks 402f068, phase 1 arbiter + timeline
layer e6f0003, phase 2 Auto slot afd3f07, phase 3 Live layer f10cceb.
Every phase passed the full gauntlet (unit -n auto, visual serial,
e2e + integration, byte-identical export hash). Phase 4 (conductor,
pause look, setlist runner) remains v1.7 as planned. Notes from the
build: real fixture defs put RGB channels in the colour-wheel class
via the group-"Colour" match, so the safe-idle "wheel open" write
claims them (kept, documented in tests/unit/test_dmx_masks.py);
adapters own the idle policy only on PRIVATE arbiters - on the shared
one the shell owns it (nav section); a producer that failed to
acquire the slot must never stop the shared loop on teardown.

## Where output stands today (2026-07-11, verified in code)

- **Timeline playback**: `utils/artnet/shows_artnet_controller.py`
  owns a `DMXManager` + `ArtNetSender`, runs its own thread at 30 Hz,
  takes sample-accurate position from an audio-engine callback, stops
  to "fixtures visible" (full dimmer, white).
- **Auto mode**: `auto/dmx_output.py` owns its own `DMXManager` +
  `ArtNetSender`, its own 30 Hz thread, PLUS a second broadcast sender
  for the visualizer, PLUS a universe-remapping table (config universe
  to ArtNet universe) the Shows path lacks. Stops to blackout.
- **Live tab**: no output at all; everything mutates the in-memory
  `LiveState`, whose `group_level()` already resolves per-group
  intensity as a pure function, waiting for a consumer.
- **Sender**: `utils/artnet/sender.py` rate-limits at 44 Hz per
  universe, but both feeding loops run at 30 Hz - so the wire never
  sees more than 30 Hz today. One arbiter loop at 44 Hz is an actual
  refresh upgrade, not just consolidation.
- **The structural gap**: `DMXManager.dmx_state` is a flat 512-byte
  buffer per universe with no notion of touched vs untouched
  channels. A merge cannot distinguish "this producer did not write
  this channel" from "this producer wants 0". Channel MASKS are the
  one genuinely new concept this plan introduces.
- **Already there**: `FixtureChannelMap` classifies every fixture's
  channels (dimmer, RGB/CMY, pan/tilt, strobe, ...) - exactly what
  HTP-vs-LTP and grandmaster scaling need. Nothing new to invent.

## Locked decisions

### 1. One arbiter, layered producers

A single `OutputArbiter` owns the one `ArtNetSender` and the send
loop. Producers register as LAYERS with fixed priorities and render
frames on demand; nobody else owns a socket. The existing
`DMXManager` instances stay what they are - renderers that compute
channel values from blocks/engine state - they just stop owning
senders and threads.

Frame contract per layer: `render(now) -> {universe: (values, mask)}`
where `values` is 512 bytes and `mask` marks which channels the layer
actually wrote this frame. Layers that have nothing running return
empty dicts cheaply.

### 2. The layer stack (top wins)

1. **DBO** - arbiter-level hard zero on the intensity mask (not a
   layer, a post-merge kill).
2. **Live busk layer** - renders `LiveState` (colours, group_level,
   flash, strobe; position targets once v1.5a supplies pan/tilt
   math). Live's own soft-blackout/flash logic stays inside
   `LiveState.group_level` - the arbiter does not re-implement it.
3. **Playback slot** - EXCLUSIVE: timeline show OR the Auto engine OR
   empty ("manual live" = empty slot + busk layer). Auto can never
   improvise over a running timeline show; switching the slot swaps
   the producer. (User decision 2026-07-11.)
4. **Pause look** - the setlist runner's between-songs layer (v1.7).
5. **Idle floor** - see policy below.

### 3. Merge rules

- **Strict priority (LTP) for everything except dimmer-class
  channels**: the highest layer whose mask covers a channel wins it.
  This deliberately includes RGB/CMY colour channels even though the
  channel map classifies them as "Intensity" - HTP-merging colour
  between a busk layer and a running show produces additive colour
  garbage (red busk over blue show must give red, not magenta).
- **HTP for dimmer-class channels only** (`FixtureChannelMap`'s
  dimmer channels): merged as max() across layers that touch them.
- **Grandmaster arbiter-side, post-merge**, so it also caps timeline
  and Auto output. It scales the per-fixture GM mask: the dimmer
  channel where one exists, else the colour intensity channels (dumb
  RGB pars have no dimmer - scaling nothing would make GM a no-op for
  them). DBO zeroes the same mask.
- **Release = mask fall-through**: RELEASE ALL clears the Live
  layer's mask and every channel falls back to whatever runs
  underneath on the next frame. That is busk-on-top for free.
  Fade-on-release is a later refinement, not phase work.
- **Intra-layer conflicts (multi-group fixtures)**: two lanes writing
  the same fixture's channels via different groups collide WITHIN the
  playback layer, where layer priority cannot see them. First call:
  lane-order-wins (last lane in timeline order writes last),
  deterministic and cheap; revisit if it bites in practice. (User
  decision 2026-07-11.)

### 4. Idle floor policy

Two floors, switched by context (user decision 2026-07-11):

- **Editor contexts** (SETUP/SHOW surfaces): "fixtures visible" -
  full dimmer, white - so the visualizer shows the rig while
  authoring. This is today's Shows-tab stop behaviour, kept.
- **Live contexts** (LIVE surface, a running setlist): blackout, or
  the active pause look once the setlist runner exists (v1.7).

The arbiter exposes `set_idle_policy(...)`; the shell wires it to the
active surface. The floor is just the bottom layer, always
full-mask.

### 5. One clock: the conductor

A transport/conductor object separate from the arbiter - the arbiter
is spatial (channels, this frame), the conductor is temporal. It owns
song identity, position in seconds, bar.beat via the per-part tempo
map, and play/pause/hold. The Shows tab's sample-accurate
audio-position callback becomes the conductor's internal sync source.
Timeline playback, Auto phrase alignment and the Live tab BPM readout
all read the conductor; external sync (MIDI clock, MTC, LTC) slaves
the conductor in v1.7, never the individual features.

### 6. Setlist runner (v1.7, unchanged)

Consumes Setlist entries: waits for the trigger (manual now, MIDI
PC/NOTE and MTC/SMPTE later), plays the song via the conductor,
applies the pause look after, honours "follows automatically". The
pause-look "ambient loop" reuses the screensaver rig behaviour as a
pause-look-layer renderer. Needs the arbiter first; both live in
phase 4.

### 7. Visualizer feed

The arbiter's post-merge frame is the single feed: one local
in-process callback (embedded visualizer) + one optional broadcast
mirror (standalone visualizer). Auto's second sender and both
existing `local_dmx_callback` paths collapse into this. The
visualizer then shows what the rig actually receives, including
grandmaster and DBO.

### 8. Threading and rate

One arbiter thread at 44 Hz (the ArtNet ceiling the sender already
enforces), PULL model: the loop calls each active layer's
`render(now)`. One thread, no double-buffer handshakes, and a slow
producer degrades only its own layer. Producers keep their
event-driven mutations (block_started, LiveState mutators) on the UI
thread behind the arbiter's lock. Auto's universe-remapping table
generalises into the arbiter/sender config so every producer gets it.

## Constraints (regression gates)

- ArtNet stays the primary native output; `.qxw` export is untouched
  by all of this (byte-identical export via
  `scripts/export_hash_check.py` stays green through every phase).
- `LiveState` stays a pure-function resolve source; the Live layer
  reads it, never the other way round.
- Existing suites green after every phase; merge logic is pure
  (frames in, frame out) and unit-tests without sockets.

## Phases

### Phase 0 - masks

Teach the render path to report touched channels: `DMXManager` writes
through a frame object carrying `(values, mask)` per universe instead
of a bare bytearray. No behaviour change on the wire.
Tests: mask correctness per block type (dimmer/colour/movement/
special touch exactly their mapped channels); full existing suite;
export hash.

### Phase 1 - arbiter + timeline layer

`OutputArbiter` with the 44 Hz pull loop, the idle-floor layer and
ONE playback layer wrapping the Shows path; `ShowsArtNetController`
shrinks to a layer adapter; sender + visualizer callback ownership
move to the arbiter.
Tests: pure merge units (priority, dimmer-HTP, mask fall-through, GM
scaling incl. no-dimmer fixtures, DBO), loop smoke test, Shows
playback end-to-end unchanged.

### Phase 2 - Auto joins the slot

Auto's engine renders through the same playback slot; slot
exclusivity enforced (timeline XOR auto); universe remapping moves
into shared config; the second broadcast sender dies in favour of the
arbiter mirror.
Tests: slot swap (start auto while timeline plays is refused/stops
one), remap equivalence with today's Auto output.

### Phase 3 - Live layer (busk makes light)

The first real output for the Live tab: colours x group_level x
flash/strobe rendered via `FixtureChannelMap`; RELEASE ALL
fall-through proven against a running playback underneath; idle
policy wired to the shell (editor visible, live blackout). Position
presets stay data-only until v1.5a supplies the pan/tilt math.
Tests: LiveState-to-frame resolution units, busk-over-show
precedence, release fall-through, GM/DBO end-to-end.

### Phase 4 - conductor, pause look, setlist runner (v1.7)

Conductor extracted and adopted by timeline/Auto/Live readouts;
pause-look layer + setlist runner; external sync slaving enters here.
Detailed when v1.7 opens; this plan only fixes the seams they plug
into.

## Deliberately deferred

Fade-on-release times, HTP beyond dimmer channels, per-channel
priority overrides, a merge-inspector UI, sACN or other protocols.
