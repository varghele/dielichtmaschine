# TODO: output + synchronisation architecture

Working notes ahead of the backend build. Tab polish happens first;
this file collects what the architecture pass must decide so nothing
gets lost in the meantime. Promote to a docs/ plan when the work
starts.

## Honest current state (2026-07-10)

Output today is two independent senders and one silent surface:

- **Timeline playback**: `utils/artnet/shows_artnet_controller.py`
  (`ShowsArtNetController`), owns its own `ArtNetSender`, driven by the
  Shows tab transport.
- **Auto mode**: `auto/dmx_output.py`, its own `DMXManager` +
  `ArtNetSender` ("completely independent" by its own docstring), plus
  a second broadcast sender for the visualizer.
- **Live tab**: NO output at all. The whole busking surface (colours,
  submasters, grandmaster, queue, scenes/effects) mutates in-memory
  `LiveState` only; `group_level()` already resolves per-group
  intensity as a pure function, waiting for a consumer.
- **Setlist triggers/pause looks/sync mode**: data + editing UI shipped
  (docs/setlist-plan.md); the runtime ignores all of it (v1.7).
- **Clocks**: the timeline transport, Auto's beat tracker and the Live
  tab's TapBPM are three unrelated time sources. No MIDI clock, MTC,
  LTC (v1.7 roadmap items).

So yes: the backend is mostly missing. What exists is one-way,
per-feature, last-writer-wins-by-accident.

## Decisions the architecture note must make

1. **One output arbiter.** A single DMX merge stage in front of one
   ArtNetSender per universe. Every producer (timeline playback, Auto,
   Live busk layer, pause looks, screensaver/ambient loop) submits
   frames to it instead of owning sockets.
2. **Merge model.** Per-channel precedence: Live overrides > running
   playbacks (timeline or Auto) > pause look > blackout floor. HTP vs
   LTP per channel class (intensity HTP, everything else LTP)?
   Grandmaster/DBO applied where - producer side (Live already scales)
   or arbiter side (probably arbiter, so it also caps timeline/Auto)?
   Release semantics: Live tab RELEASE ALL must hand channels back
   cleanly to whatever runs underneath (busk-on-top, Live plan stage E).
3. **One clock.** A transport/conductor object owning song position
   (bar.beat), tempo map (per-part BPM already in the model), and
   play/pause/hold. Timeline playback, Auto phrase alignment and the
   Live tab BPM display all read it. External sync (MIDI clock, MTC,
   LTC) slaves this clock, not the individual features (v1.7).
4. **Setlist runner.** Consumes Setlist entries: waits for the entry's
   trigger (manual now; MIDI PC/NOTE, MTC/SMPTE later), plays the song,
   applies the pause look after, honours "follows automatically".
   Pause look "ambient loop" = screensaver rig behaviour - needs the
   arbiter to exist first.
5. **Visualizer feed.** Auto broadcasts separately today; the arbiter's
   post-merge frame is the natural single feed (embedded + TCP).
6. **Threading/rate.** One send loop at the ArtNet max rate (44 Hz),
   producers write into buffers; today each sender rate-limits itself.

## Constraints to respect

- ArtNet stays the primary native output (standalone pivot).
- `.qxw` export path is untouched by any of this (byte-identical
  export is a regression gate, scripts/export_hash_check.py).
- LiveState must stay a pure-function resolve source (it already is).
- Engine work maps to roadmap v1.7 (clock sync, setlist trigger
  engine) and Live plan stage E (busk-on-top merge); this note should
  not invent a new milestone, just wire the existing ones together.

## Before the backend build (user)

- [ ] Tab polish pass on the individual tabs (in progress, user-led)
- [ ] Review this file, then promote to docs/output-sync-plan.md with
      phases + tests
