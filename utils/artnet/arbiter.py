# utils/artnet/arbiter.py
"""The single output arbiter (docs/output-sync-plan.md).

One `OutputArbiter` owns the one ArtNetSender and the one send loop;
every producer of light is a LAYER that renders `(values, mask)`
frames on demand and nobody else touches a socket. The stack, top
wins:

    DBO (post-merge kill)  >  Live busk  >  playback slot
    (timeline XOR auto)    >  pause look (v1.8)  >  idle floor

Merge rules (locked 2026-07-11): strict priority (LTP) for every
channel except dimmer-class channels, which merge HTP (max) BETWEEN
LAYERS; the idle floor never participates in HTP - it only shows
through where no layer claims. The grandmaster scales, and DBO
zeroes, each fixture's intensity channels post-merge: the dimmer
channel where one exists, else the colour channels (a dumb RGB par
has no dimmer, and a grandmaster that skipped it would be a no-op).

A frame is `{config_universe_id: (values512, mask512)}` - the mask is
the claim mask from DMXManager.get_frame (1 = deliberately driven,
a written 0 is a claim to zero). Unclaimed channels fall through.

The loop runs at the ArtNet ceiling (44 Hz) and PULLS: each tick
calls every active layer's `render(now)` under the arbiter lock, so a
layer that raises only loses its own frame. Sends are forced past the
sender's own rate limit - the loop is the rate limiter.
"""

import logging
import threading
import time
from typing import Callable, Dict, Iterable, List, Optional, Tuple

from .sender import ArtNetSender

logger = logging.getLogger(__name__)

# One layer frame: config universe id -> (512 value bytes, 512 claim bytes).
Frame = Dict[int, Tuple[bytes, bytes]]

# Idle floor policies (user decision 2026-07-11): the editor keeps the
# rig visible for authoring, live contexts drop to blackout (the pause
# look replaces blackout in v1.8).
IDLE_VISIBLE = "visible"
IDLE_BLACKOUT = "blackout"

TICK_HZ = 44  # ArtNet ceiling; the two legacy senders looped at 30.

BROADCAST_IP = "255.255.255.255"


def artnet_target_from_config(config) -> str:
    """The native output's ArtNet destination, from the configured
    universes: the first ArtNet-plugin universe (by id) with a target
    IP set. Falls back to limited broadcast when nothing is configured.

    Before 2026-07-13 the universe's "Target IP" was only honoured by
    the .qxw export - native output always broadcast, which on a
    multi-homed machine leaves via ONE interface (the default route)
    and never reaches a node on a secondary NIC (the classic 2.x.x.x
    ArtNet network). Unicast to the configured node fixes that; the
    arbiter's broadcast mirror keeps the local visualizer fed.
    """
    universes = getattr(config, "universes", {}) or {}
    for _uid, universe in sorted(universes.items()):
        output = getattr(universe, "output", None) or {}
        if output.get("plugin") != "ArtNet":
            continue
        ip = ((output.get("parameters") or {}).get("ip") or "").strip()
        if ip:
            return ip
    return BROADCAST_IP


# set_fixtures_visible() equivalents for the visible floor (values by
# channel class; colour wheel 0 = open/white, pan/tilt 127 = centered).
_VISIBLE_FULL = 255
_VISIBLE_WHEEL_OPEN = 0
_VISIBLE_CENTER = 127

# FixtureChannelMap attributes that count as colour intensity - the
# grandmaster fallback for fixtures without a dimmer channel.
_COLOUR_CHANNEL_ATTRS = (
    "red_channels", "green_channels", "blue_channels", "white_channels",
    "amber_channels", "cyan_channels", "magenta_channels",
    "yellow_channels", "uv_channels", "lime_channels",
)


# ---------------------------------------------------------------------------
# Pure merge core (unit-tested without sockets or threads)
# ---------------------------------------------------------------------------

def build_channel_class_masks(fixture_maps) -> Tuple[Dict[int, bytearray],
                                                     Dict[int, bytearray]]:
    """Per-universe channel-class masks from FixtureChannelMaps.

    Returns ``(htp_masks, gm_masks)``:

    - ``htp_masks``: 1 on dimmer-class channels - the only channels
      that merge HTP between layers.
    - ``gm_masks``: the channels the grandmaster scales and DBO kills:
      a fixture's dimmer channels where it has any, else its colour
      intensity channels.
    """
    htp: Dict[int, bytearray] = {}
    gm: Dict[int, bytearray] = {}

    def _mask(masks, universe):
        if universe not in masks:
            masks[universe] = bytearray(512)
        return masks[universe]

    for fixture_map in fixture_maps.values():
        universe = fixture_map.universe
        if fixture_map.dimmer_channels:
            for offset in fixture_map.dimmer_channels:
                _, channel = fixture_map.get_absolute_address(offset)
                if 0 <= channel < 512:
                    _mask(htp, universe)[channel] = 1
                    _mask(gm, universe)[channel] = 1
        else:
            for attr in _COLOUR_CHANNEL_ATTRS:
                for offset in getattr(fixture_map, attr):
                    _, channel = fixture_map.get_absolute_address(offset)
                    if 0 <= channel < 512:
                        _mask(gm, universe)[channel] = 1
    return htp, gm


def render_visible_floor(fixture_maps) -> Frame:
    """The "fixtures visible" idle floor: dimmer + RGBW full, shutter
    open, colour wheel open, pan/tilt centered - the exact writes of
    DMXManager.set_fixtures_visible, expressed as a claimed frame."""
    values: Dict[int, bytearray] = {}
    claims: Dict[int, bytearray] = {}

    def _write(fixture_map, offsets, value):
        for offset in offsets:
            _, channel = fixture_map.get_absolute_address(offset)
            if not 0 <= channel < 512:
                continue
            universe = fixture_map.universe
            if universe not in values:
                values[universe] = bytearray(512)
                claims[universe] = bytearray(512)
            values[universe][channel] = value
            claims[universe][channel] = 1

    for fixture_map in fixture_maps.values():
        _write(fixture_map, fixture_map.dimmer_channels, _VISIBLE_FULL)
        _write(fixture_map, fixture_map.red_channels, _VISIBLE_FULL)
        _write(fixture_map, fixture_map.green_channels, _VISIBLE_FULL)
        _write(fixture_map, fixture_map.blue_channels, _VISIBLE_FULL)
        _write(fixture_map, fixture_map.white_channels, _VISIBLE_FULL)
        _write(fixture_map, fixture_map.strobe_channels, _VISIBLE_FULL)
        _write(fixture_map, fixture_map.color_wheel_channels,
               _VISIBLE_WHEEL_OPEN)
        for attr in ("pan_channels", "tilt_channels",
                     "pan_fine_channels", "tilt_fine_channels"):
            _write(fixture_map, getattr(fixture_map, attr), _VISIBLE_CENTER)

    return {u: (bytes(values[u]), bytes(claims[u])) for u in values}


def compose(universes: Iterable[int], floor: Frame, layers: List[Frame],
            htp_masks: Dict[int, bytearray], grandmaster: int = 100,
            dbo: bool = False,
            gm_masks: Optional[Dict[int, bytearray]] = None,
            ) -> Dict[int, bytearray]:
    """Merge the floor and the layer frames (bottom-up order) into one
    output buffer per universe, then apply grandmaster/DBO.

    Pure: frames in, buffers out. The floor is fall-through only; a
    layer channel claimed on top of ANOTHER LAYER's claim merges HTP
    if dimmer-class, else the upper layer wins (LTP). A claim to zero
    is a claim (it beats the floor and, on non-HTP channels, lower
    layers).
    """
    all_universes = set(int(u) for u in universes) | set(floor)
    for frame in layers:
        all_universes |= set(frame)

    gm_masks = gm_masks or {}
    grandmaster = max(0, min(100, int(grandmaster)))
    if grandmaster < 100:
        gm_table = bytes(v * grandmaster // 100 for v in range(256))
    else:
        gm_table = None

    out: Dict[int, bytearray] = {}
    for universe in all_universes:
        values = bytearray(512)
        floor_pair = floor.get(universe)
        if floor_pair is not None:
            floor_values, floor_mask = floor_pair
            for channel in range(512):
                if floor_mask[channel]:
                    values[channel] = floor_values[channel]

        htp = htp_masks.get(universe)
        layer_claims = bytearray(512)   # claims ABOVE the floor
        for frame in layers:
            pair = frame.get(universe)
            if pair is None:
                continue
            layer_values, layer_mask = pair
            for channel in range(512):
                if not layer_mask[channel]:
                    continue
                if (htp is not None and htp[channel]
                        and layer_claims[channel]):
                    if layer_values[channel] > values[channel]:
                        values[channel] = layer_values[channel]
                else:
                    values[channel] = layer_values[channel]
                layer_claims[channel] = 1

        gm = gm_masks.get(universe)
        if gm is not None:
            if dbo:
                for channel in range(512):
                    if gm[channel]:
                        values[channel] = 0
            elif gm_table is not None:
                for channel in range(512):
                    if gm[channel]:
                        values[channel] = gm_table[values[channel]]

        out[universe] = values
    return out


# ---------------------------------------------------------------------------
# The arbiter
# ---------------------------------------------------------------------------

class OutputArbiter:
    """One send loop, one sender, layered producers.

    Layers plug into named SLOTS (never a free-form priority list):
    ``set_playback_layer`` is the exclusive playback slot (timeline
    XOR auto - phase 2 enforces the swap), ``set_live_layer`` the busk
    surface (phase 3), ``set_pause_look_layer`` v1.8. A layer is any
    object with ``render(now) -> Frame``; returning {} means "nothing
    running, let lower layers through".

    Thread-safety: slot/config mutators and the tick both take the
    arbiter lock; layer ``render`` is called under it, so layers may
    mutate their own state from the UI thread behind the same lock via
    the mutators they already own.
    """

    def __init__(self, config=None, sender: Optional[ArtNetSender] = None,
                 target_ip: str = "255.255.255.255",
                 tick_hz: int = TICK_HZ):
        self._lock = threading.RLock()
        self._sender = sender if sender is not None \
            else ArtNetSender(target_ip=target_ip)
        self._tick_interval = 1.0 / float(tick_hz)

        self._universes: set = set()
        # config universe id -> ArtNet universe number (0-based wire).
        self._universe_mapping: Dict[int, int] = {}
        if config is not None:
            for universe_id in getattr(config, "universes", {}).keys():
                self._universes.add(int(universe_id))
            for fixture in getattr(config, "fixtures", []) or []:
                self._universes.add(int(fixture.universe))
        self._universe_mapping = {u: u - 1 for u in self._universes}

        self._playback_layer = None
        self._playback_owner: Optional[str] = None
        self._live_layer = None
        self._pause_look_layer = None

        # Optional broadcast mirror (Auto mode's visualizer path,
        # generalised): a second sender that repeats every frame to
        # broadcast when the primary target is unicast.
        self._mirror_enabled = False
        self._mirror_sender: Optional[ArtNetSender] = None

        self._fixture_maps: Dict = {}
        self._htp_masks: Dict[int, bytearray] = {}
        self._gm_masks: Dict[int, bytearray] = {}
        self._idle_policy = IDLE_VISIBLE
        self._floor: Frame = {}

        self._grandmaster = 100
        self._dbo = False

        self._local_dmx_callback: Optional[Callable[[int, bytes], None]] = \
            None

        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        # Monotonic frame counter for status displays (the Live tab's
        # OUT chip polls it to light its activity dot).
        self._frames_sent = 0

    # -- configuration ---------------------------------------------------

    def set_fixture_maps(self, fixture_maps) -> None:
        """Adopt the fixture channel maps (from the playback layer's
        DMXManager): rebuilds the HTP/grandmaster class masks and the
        idle floor, learns any universes the maps introduce, and
        forwards the maps to map-less layers (the Live busk layer and
        the future pause look render through the same maps)."""
        with self._lock:
            self._fixture_maps = dict(fixture_maps)
            self._htp_masks, self._gm_masks = \
                build_channel_class_masks(self._fixture_maps)
            for fixture_map in self._fixture_maps.values():
                universe = int(fixture_map.universe)
                if universe not in self._universes:
                    self._universes.add(universe)
                    self._universe_mapping.setdefault(universe, universe - 1)
            self._rebuild_floor()
            self._forward_fixture_maps()

    def _forward_fixture_maps(self) -> None:
        for layer in (self._live_layer, self._pause_look_layer):
            forward = getattr(layer, "set_fixture_maps", None)
            if forward is not None:
                forward(self._fixture_maps)

    def set_idle_policy(self, policy: str) -> None:
        """"visible" (editor: rig lit for authoring) or "blackout"
        (live contexts). The shell wires this to the active surface."""
        with self._lock:
            self._idle_policy = policy if policy in (IDLE_VISIBLE,
                                                     IDLE_BLACKOUT) \
                else IDLE_VISIBLE
            self._rebuild_floor()

    def _rebuild_floor(self) -> None:
        if self._idle_policy == IDLE_VISIBLE:
            self._floor = render_visible_floor(self._fixture_maps)
        else:
            self._floor = {}

    def set_universe_mapping(self, mapping: Dict[int, int]) -> None:
        """{config universe id: ArtNet universe number} - Auto mode's
        venue remapping, generalised to every producer."""
        with self._lock:
            self._universe_mapping = dict(mapping)
            self._universes |= set(int(u) for u in mapping)

    def set_target_ip(self, ip: str) -> None:
        self._sender.target_ip = ip

    def set_local_dmx_callback(
            self, callback: Optional[Callable[[int, bytes], None]]) -> None:
        """Per-universe post-merge frame hook for the embedded
        visualizer: called with (config universe id, 512 bytes)."""
        with self._lock:
            self._local_dmx_callback = callback

    def set_grandmaster(self, percent: int) -> None:
        with self._lock:
            self._grandmaster = max(0, min(100, int(percent)))

    def set_dbo(self, on: bool) -> None:
        with self._lock:
            self._dbo = bool(on)

    def set_broadcast_mirror(self, enabled: bool,
                             sender: Optional[ArtNetSender] = None) -> None:
        """Repeat every merged frame on a second sender so the LOCAL
        standalone visualizer always receives ArtNet, whatever the
        primary target is. The default mirror goes to loopback
        (127.0.0.1): a 255.255.255.255 broadcast leaves via ONE
        interface on a multi-homed machine (the default route), which
        is typically NOT the lighting NIC and does not reliably reach
        local listeners - the viewer went dark exactly that way once
        output learned to unicast to the node (2026-07-13). A viewer on
        ANOTHER machine should be fed by pointing the primary target at
        it or at broadcast. Pass ``sender`` to inject a stub in tests."""
        with self._lock:
            self._mirror_enabled = bool(enabled)
            if sender is not None:
                self._mirror_sender = sender
            elif enabled and self._mirror_sender is None:
                self._mirror_sender = ArtNetSender(
                    target_ip="127.0.0.1")

    # -- layer slots -------------------------------------------------------

    def set_playback_layer(self, layer) -> None:
        """Low-level slot write (tests, teardown). Producers use
        acquire_playback_slot/release_playback_slot so exclusivity is
        enforced."""
        with self._lock:
            self._playback_layer = layer
            if layer is None:
                self._playback_owner = None

    def acquire_playback_slot(self, layer, owner: str) -> bool:
        """Claim the EXCLUSIVE playback slot (timeline XOR auto, user
        decision 2026-07-11). Returns False when another owner holds
        it - the caller refuses its start and tells the user, rather
        than silently evicting a running show."""
        with self._lock:
            if (self._playback_layer is not None
                    and self._playback_owner not in (None, owner)):
                return False
            self._playback_layer = layer
            self._playback_owner = owner
            return True

    def release_playback_slot(self, owner: str) -> None:
        """Release the slot if ``owner`` holds it (idempotent)."""
        with self._lock:
            if self._playback_owner == owner:
                self._playback_layer = None
                self._playback_owner = None

    def playback_slot_owner(self) -> Optional[str]:
        with self._lock:
            return self._playback_owner

    def set_live_layer(self, layer) -> None:
        with self._lock:
            self._live_layer = layer
            self._forward_fixture_maps()

    def set_pause_look_layer(self, layer) -> None:
        with self._lock:
            self._pause_look_layer = layer
            self._forward_fixture_maps()

    # -- the loop ----------------------------------------------------------

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        """Start the 44 Hz send loop (idempotent). While running, the
        merged frame streams continuously - the floor alone when
        nothing plays, which doubles as the periodic refresh ArtNet
        receivers expect."""
        with self._lock:
            if self.running:
                return
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._loop, name="OutputArbiter", daemon=True)
            self._thread.start()

    def stop(self, blackout: bool = True) -> None:
        """Stop the loop; by default send one forced blackout so the
        rig (and any visualizer) does not hold the last frame."""
        thread = self._thread
        self._stop_event.set()
        if thread is not None and thread.is_alive():
            thread.join(timeout=1.0)
        self._thread = None
        if blackout:
            self._send_blackout()

    def shutdown(self) -> None:
        """stop() + close the sockets. The arbiter is done after this."""
        self.stop(blackout=True)
        self._sender.close()
        if self._mirror_sender is not None:
            self._mirror_sender.close()

    def _loop(self) -> None:
        while not self._stop_event.is_set():
            frame_start = time.perf_counter()
            try:
                self.tick_once(time.monotonic())
            except Exception:
                logger.exception("OutputArbiter tick failed")
            elapsed = time.perf_counter() - frame_start
            sleep_time = self._tick_interval - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)

    def tick_once(self, now: float) -> Dict[int, bytearray]:
        """Render, merge and send exactly one frame. Public so tests
        (and the e2e workflow) can drive deterministic single frames.
        Returns the merged buffers keyed by config universe id."""
        with self._lock:
            frames: List[Frame] = []
            # Bottom-up: pause look, playback, live.
            for layer in (self._pause_look_layer, self._playback_layer,
                          self._live_layer):
                if layer is None:
                    continue
                try:
                    frames.append(layer.render(now) or {})
                except Exception:
                    logger.exception("output layer render failed: %r", layer)
                    frames.append({})
            merged = compose(self._universes, self._floor, frames,
                             self._htp_masks, self._grandmaster, self._dbo,
                             self._gm_masks)
            mapping = dict(self._universe_mapping)
            callback = self._local_dmx_callback
            mirror = self._mirror_sender if self._mirror_enabled else None
            fixture_maps = dict(self._fixture_maps)

        # Hardware gets the real-yoke conversion (utils/yoke); the mirror
        # and local callback keep the solver-convention frame because
        # the visualizer converts in its own renderer. So the rig and
        # the 3D view agree. Every mover with a definition is converted.
        hw = self._hardware_frame(merged, fixture_maps)

        for universe in sorted(merged):
            wire_universe = mapping.get(universe, universe - 1)
            self._sender.send_dmx(wire_universe, hw[universe],
                                  force=True)
            if mirror is not None:
                try:
                    mirror.send_dmx(wire_universe, merged[universe],
                                    force=True)
                except Exception:
                    logger.exception("broadcast mirror send failed")
            if callback is not None:
                try:
                    callback(universe, bytes(merged[universe]))
                except Exception:
                    logger.exception("local DMX callback failed")
        self._frames_sent += 1
        return merged

    def _hardware_frame(self, merged: Dict[int, bytearray],
                        fixture_maps: Dict) -> Dict[int, bytearray]:
        """A copy of the merged frame with each GDTF-chain mover's
        pan/tilt converted from solver convention to the real yoke, for
        the physical node only. Returns ``merged`` itself when nothing
        needs converting (the common no-movers / no-GDTF case), so the
        hot path allocates nothing extra."""
        from utils.yoke import apply_yoke_to_universe, fixture_yoke

        converted: Dict[int, bytearray] = {}
        for fmap in fixture_maps.values():
            if not (getattr(fmap, "pan_channels", None)
                    and getattr(fmap, "tilt_channels", None)):
                continue
            fx = getattr(fmap, "fixture", None)
            if fx is None:
                continue
            uses_chain, flipped = fixture_yoke(
                fx.manufacturer, fx.model, getattr(fmap, "mode_name", ""))
            invert_pan = getattr(fx, "invert_pan", False)
            invert_tilt = getattr(fx, "invert_tilt", False)
            # No yoke chain AND no inversion = nothing to rewrite; an
            # inverted head converts (invert-only) even without a chain.
            if not uses_chain and not (invert_pan or invert_tilt):
                continue
            universe = fmap.universe
            buf = merged.get(universe)
            if buf is None:
                continue
            if universe not in converted:
                converted[universe] = bytearray(buf)
            apply_yoke_to_universe(converted[universe], fmap, flipped,
                                   convert=uses_chain,
                                   invert_pan=invert_pan,
                                   invert_tilt=invert_tilt)
        if not converted:
            return merged
        return {u: converted.get(u, merged[u]) for u in merged}

    def status(self) -> dict:
        """A cheap snapshot for status displays: whether the loop is
        streaming, how many frames have gone out (poll the delta for
        an activity indicator), and the universe wire mapping."""
        with self._lock:
            return {
                "running": self.running,
                "frames_sent": self._frames_sent,
                "universe_mapping": dict(self._universe_mapping),
            }

    def _send_blackout(self) -> None:
        with self._lock:
            mapping = dict(self._universe_mapping)
            # The mirror gets the blackout even when currently disabled:
            # a viewer would otherwise hold the last mirrored frame if
            # mirroring was toggled off mid-show (kept from Auto mode).
            mirror = self._mirror_sender
        blackout = bytearray(512)
        for wire_universe in mapping.values():
            try:
                self._sender.send_dmx(wire_universe, blackout, force=True)
                if mirror is not None:
                    mirror.send_dmx(wire_universe, blackout, force=True)
            except Exception:
                logger.exception("blackout send failed")
