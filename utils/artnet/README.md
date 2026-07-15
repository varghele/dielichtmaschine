# ArtNet DMX Output Module

Real-time ArtNet DMX output for Die Lichtmaschine.

Architecture reference: **docs/output-sync-plan.md** (the single
output arbiter, merge rules, phased build). This README describes the
module layout; the plan doc is the source of truth for the design
decisions.

## Overview

One `OutputArbiter` owns the one `ArtNetSender` and the one 44 Hz
send loop. Every producer of light (timeline playback, Auto mode, the
Live busk surface, the v1.7 pause look) is a LAYER: it renders
per-universe `(values, mask)` frames on demand, and the arbiter
merges the stack and sends. Nobody else touches a socket.

## Components

### 1. `ArtNetSender` (sender.py)
Low-level ArtNet packet generator and UDP sender.

- Generates ArtNet OpDmx packets according to specification
- Rate-limited to 44 Hz per universe (the arbiter forces past this -
  its loop IS the rate limiter)
- Supports broadcast or unicast transmission

### 2. `DMXManager` (dmx_manager.py)
Renderer: manages DMX state for all universes.

- Tracks 512 channels per universe, plus a parallel CLAIM MASK
  (1 = channel deliberately driven this frame; a written 0 is a claim
  to zero). `get_frame(universe)` returns the `(values, mask)` pair a
  layer hands to the arbiter.
- Maps fixtures to DMX channels using `.qxf`/GDTF definitions
  (`FixtureChannelMap`)
- Converts sublane blocks to DMX values in real-time; overlapping
  blocks within one renderer stay LTP, multi-group conflicts are
  lane-order-wins (locked decision)
- No sockets, no threads

### 3. `OutputArbiter` (arbiter.py)
The merge stage and send loop.

- Layer slots: `set_playback_layer` (EXCLUSIVE slot - timeline XOR
  Auto), `set_live_layer`, `set_pause_look_layer`
- Stack, top wins: DBO kill > live > playback > pause look > idle
  floor
- Merge: strict priority (LTP) everywhere except dimmer-class
  channels, which merge HTP between layers; the idle floor is
  fall-through only (never HTP)
- Grandmaster/DBO applied post-merge on each fixture's intensity
  channels (dimmer where one exists, else the colour channels)
- Idle floor policy: `set_idle_policy("visible")` for editor contexts
  (rig lit for authoring), `"blackout"` for live contexts
- Universe remapping (`set_universe_mapping`) for venue-specific
  wiring, e.g. `{1: 0, 2: 1}` for an Enttec ODE
- `set_local_dmx_callback` feeds the embedded visualizer the
  POST-MERGE frame in-process
- `tick_once(now)` runs one deterministic frame (tests, e2e)

### 4. `ShowsArtNetController` (shows_artnet_controller.py)
Timeline playback as an arbiter layer (adapter).

- Keeps the pre-arbiter public API for the Shows tab
- Schedules lane blocks into its `DMXManager`, renders frames when
  playing, holds the last frame when paused, renders nothing when
  stopped (the floor shows through)
- Creates a private arbiter unless a shared one is injected
  (`arbiter=` kwarg - phase 2 shares it with Auto)

## Integration Example

```python
from utils.artnet import ShowsArtNetController

controller = ShowsArtNetController(
    config=config,
    fixture_definitions=fixture_defs,
    song_structure=song_structure,
    target_ip="255.255.255.255",
    local_dmx_callback=embedded_visualizer.feed_dmx,
)
controller.set_light_lanes(lanes)
controller.enable_output()      # arbiter loop starts (floor streams)
controller.start_playback()     # layer renders fresh frames
controller.update_position(t)   # or set_position_callback(...)
controller.stop_playback()      # floor takes over
controller.cleanup()
```

## How a frame happens (44 Hz)

1. The arbiter tick calls each active layer's `render(now)` under the
   arbiter lock.
2. The playback layer pulls fresh audio position (if a position
   callback is set), starts/ends lane blocks, recomputes DMX state
   and returns `(values, mask)` per universe.
3. `compose()` merges floor + layers per the rules above, then
   applies grandmaster/DBO.
4. The merged buffers go to the sender (config universe mapped to the
   0-based wire universe) and to the local visualizer callback.

## Rate

- One loop at **44 Hz** (the ArtNet ceiling). The pre-arbiter
  controllers looped at 30 Hz; this is a real refresh upgrade.
- While output is enabled the merged frame streams continuously -
  the idle floor alone when nothing plays, which doubles as the
  periodic refresh ArtNet receivers expect.

## Troubleshooting

### No DMX output
1. Check that output is enabled (the arbiter loop is running)
2. Check firewall settings (UDP port 6454)
3. Verify fixture definitions are loaded correctly

### Visualizer not receiving
1. Ensure the visualizer listens on the same network
2. Check IP address (use broadcast for testing)
3. Verify universe numbers match (including any universe remapping)

### DMX values incorrect
1. Verify fixture definitions (`.qxf` files) are correct
2. Check fixture current_mode matches available modes
3. Review channel mappings in DMXManager
4. Remember the merge: a higher layer or the grandmaster may be
   shaping the value a producer wrote
