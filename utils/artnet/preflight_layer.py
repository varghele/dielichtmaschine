# utils/artnet/preflight_layer.py
"""The venue pre-flight as an output-arbiter layer (design doc
docs/design-show-morphing.md 7.2, v1.5b phase 5) - the rig-driving
half of the checklist screen, modeled directly on the Live busk layer
(utils/artnet/live_layer.py).

The layer renders ONE checklist item's ``drive_state`` at a time into
(values, mask) frames, claiming only what the active test drives:

- ``flash_full``: the whole group at full - dimmer 255, white where
  RGB emitters exist (claim-to-zero on the other colour attributes so
  nothing tints the test), shutter open. Wheel-only fixtures get the
  wheel steered to the white slot via the same rgb_to_color_wheel
  mapping playback uses. The patch/address check: a silent fixture is
  a patch error.
- ``aim_spot``: the group's movers aim at the named stage spot through
  the exact math the busk layer uses (calculate_pan_tilt at the
  definition's physical ranges, 16-bit pan_tilt_to_dmx16, fines
  claimed), PLUS full white so the operator sees where the beams land.
- ``rgb_steps``: a settable current colour - pure RED, GREEN, BLUE by
  step index - at full. Catches channel-order and mode mismatches.
- ``special_steps``: full white plus the gobo channels stepped through
  wheel positions at index steps (v1: evenly spaced DMX values; the
  routed capability values ride GDTF work later).
- ``hold_aim_for_capture``: aim (the drive_state's spot when present,
  else the config's first spot) + full, holding steady while the
  operator trims focus/zoom live: ``set_capture_levels`` drives the
  definition's focus/zoom channels when mapped, and drives nothing
  extra when the fixture has none - CAPTURE still records the slider
  values into Fixture.calibration (the dialog owns that write).

One item active at a time (``arm``/``disarm``); releasing is mask
fall-through exactly like the busk layer - no claims, lower layers
show through. The layer plugs into the shared arbiter's EXCLUSIVE
playback slot (owner "preflight"): a running timeline or Auto show
refuses the attach, and detaching never stops a loop another producer
streams through (the arbiter rules, docs/output-sync-plan.md).
"""

from typing import Callable, Dict, Optional, Tuple

from utils.orientation import calculate_pan_tilt, pan_tilt_to_dmx16

from .arbiter import Frame
from .dmx_manager import rgb_to_color_wheel

#: the exclusive playback-slot owner tag (timeline = "timeline",
#: Auto = "auto"; the pre-flight is a third, equally exclusive driver).
SLOT_OWNER = "preflight"

#: rgb_steps order - the checklist instruction says RED, GREEN, BLUE.
RGB_STEPS: Tuple[Tuple[int, int, int], ...] = (
    (255, 0, 0), (0, 255, 0), (0, 0, 255))
RGB_STEP_LABELS = ("RED", "GREEN", "BLUE")

#: special_steps v1: gobo wheel positions at evenly spaced DMX values.
SPECIAL_STEP_COUNT = 8


def special_step_value(index: int) -> int:
    """The gobo-channel DMX value of step ``index`` (wraps)."""
    step = index % SPECIAL_STEP_COUNT
    return round(step * 255 / (SPECIAL_STEP_COUNT - 1))


class PreflightRigLayer:
    """Arbiter layer over one checklist item's ``drive_state``.

    ``config_provider`` is a zero-arg callable returning the config
    under test (the pre-flight dialog's config object - for a morph
    that is config B, not necessarily the open project).
    ``fixture_maps`` are that config's FixtureChannelMaps
    (DMXManager.build_fixture_maps); the layer occupies the playback
    slot, which the arbiter does NOT forward maps to, so the caller
    supplies them.
    """

    def __init__(self, config_provider: Callable,
                 fixture_maps: Optional[Dict] = None) -> None:
        self._config_provider = config_provider
        self._fixture_maps: Dict = dict(fixture_maps or {})
        self._drive_state: Optional[Dict] = None
        self._rgb_step = 0
        self._special_step = 0
        self._focus: Optional[int] = None
        self._zoom: Optional[int] = None
        self._arbiter = None
        self._started_loop = False

    def set_fixture_maps(self, fixture_maps) -> None:
        self._fixture_maps = dict(fixture_maps)

    # -- arbiter attachment (the exclusive playback slot) -------------------

    def attach(self, arbiter) -> bool:
        """Claim the exclusive playback slot and make sure the loop
        runs. False when a timeline/Auto show holds the slot - the
        caller tells the operator instead of evicting a running show."""
        if self._arbiter is not None:
            return True
        if not arbiter.acquire_playback_slot(self, SLOT_OWNER):
            return False
        self._arbiter = arbiter
        # Remember whether WE started the loop: detach must never stop
        # a loop another producer (OUTPUT switch, busk) streams through.
        self._started_loop = not arbiter.running
        arbiter.start()
        return True

    def detach(self) -> None:
        """Release the slot; stop the loop only if this layer started
        it (idempotent)."""
        arbiter = self._arbiter
        if arbiter is None:
            return
        self._arbiter = None
        self.disarm()
        arbiter.release_playback_slot(SLOT_OWNER)
        if self._started_loop and arbiter.playback_slot_owner() is None:
            arbiter.stop(blackout=True)
        self._started_loop = False

    # -- item state ----------------------------------------------------------

    @property
    def armed(self) -> bool:
        return self._drive_state is not None

    @property
    def drive_state(self) -> Optional[Dict]:
        return self._drive_state

    def arm(self, drive_state: Dict) -> None:
        """One item active at a time: arming replaces the previous
        state and resets the step indices and capture levels."""
        self._drive_state = dict(drive_state or {})
        self._rgb_step = 0
        self._special_step = 0
        self._focus = None
        self._zoom = None

    def disarm(self) -> None:
        """Release: the next render claims nothing (mask fall-through,
        the busk layer's release contract)."""
        self._drive_state = None

    def set_rgb_step(self, index: int) -> None:
        self._rgb_step = int(index) % len(RGB_STEPS)

    @property
    def rgb_step(self) -> int:
        return self._rgb_step

    def set_special_step(self, index: int) -> None:
        self._special_step = int(index) % SPECIAL_STEP_COUNT

    @property
    def special_step(self) -> int:
        return self._special_step

    def set_capture_levels(self, focus: Optional[int] = None,
                           zoom: Optional[int] = None) -> None:
        """Live focus/zoom trim (0-255) for hold_aim_for_capture; None
        leaves the channel unclaimed."""
        self._focus = None if focus is None \
            else max(0, min(255, int(focus)))
        self._zoom = None if zoom is None else max(0, min(255, int(zoom)))

    # -- the arbiter layer contract ------------------------------------------

    def render(self, now: float) -> Frame:
        state = self._drive_state
        config = self._config_provider()
        if not state or config is None or not self._fixture_maps:
            return {}
        action = state.get("action", "")
        group = (getattr(config, "groups", {}) or {}).get(
            state.get("group", ""))
        if group is None:
            return {}

        values: Dict[int, bytearray] = {}
        masks: Dict[int, bytearray] = {}

        def _write(fixture_map, offsets, value) -> None:
            universe = fixture_map.universe
            if universe not in values:
                values[universe] = bytearray(512)
                masks[universe] = bytearray(512)
            for offset in offsets:
                _, channel = fixture_map.get_absolute_address(offset)
                if 0 <= channel < 512:
                    values[universe][channel] = max(0, min(255, int(value)))
                    masks[universe][channel] = 1

        def _write_colour(fixture_map, red, green, blue) -> None:
            """The busk layer's colour treatment at full: RGB, white
            only for pure white, CMY inverse, remaining colour
            attributes claimed to zero, and wheel-only fixtures steered
            to the nearest slot (never for fixtures WITH emitters - the
            group-Colour aliasing quirk pinned in test_dmx_masks.py)."""
            _write(fixture_map, fixture_map.red_channels, red)
            _write(fixture_map, fixture_map.green_channels, green)
            _write(fixture_map, fixture_map.blue_channels, blue)
            white = 255 if (red, green, blue) == (255, 255, 255) else 0
            _write(fixture_map, fixture_map.white_channels, white)
            _write(fixture_map, fixture_map.cyan_channels, 255 - red)
            _write(fixture_map, fixture_map.magenta_channels, 255 - green)
            _write(fixture_map, fixture_map.yellow_channels, 255 - blue)
            for attr in ("amber_channels", "uv_channels", "lime_channels"):
                _write(fixture_map, getattr(fixture_map, attr), 0)
            if not (fixture_map.red_channels or fixture_map.green_channels
                    or fixture_map.blue_channels):
                _write(fixture_map, fixture_map.color_wheel_channels,
                       rgb_to_color_wheel(red, green, blue))

        def _full(fixture_map, red=255, green=255, blue=255) -> None:
            """Full intensity in the given colour + open shutter."""
            _write(fixture_map, fixture_map.dimmer_channels, 255)
            _write_colour(fixture_map, red, green, blue)
            _write(fixture_map, fixture_map.strobe_channels, 255)

        def _aim(fixture, fixture_map, target) -> None:
            """The busk layer's aim path: orientation from the primary
            group (first-group-wins), definition physical ranges,
            16-bit encoding with the fines claimed."""
            if not (fixture_map.pan_channels or fixture_map.tilt_channels):
                return
            primary = config.groups.get(fixture.group) \
                if fixture.group else None
            mounting, yaw, pitch, roll = \
                fixture.get_effective_orientation(primary)
            pan_deg, tilt_deg = calculate_pan_tilt(
                fixture_x=fixture.x, fixture_y=fixture.y,
                fixture_z=fixture.get_effective_z(primary),
                target_x=target[0], target_y=target[1], target_z=target[2],
                mounting=mounting, yaw=yaw, pitch=pitch, roll=roll,
                pan_range=fixture_map.pan_range,
                tilt_range=fixture_map.tilt_range,
            )
            pan_c, pan_f, tilt_c, tilt_f = pan_tilt_to_dmx16(
                pan_deg, tilt_deg,
                fixture_map.pan_range, fixture_map.tilt_range)
            _write(fixture_map, fixture_map.pan_channels, pan_c)
            _write(fixture_map, fixture_map.tilt_channels, tilt_c)
            _write(fixture_map, fixture_map.pan_fine_channels, pan_f)
            _write(fixture_map, fixture_map.tilt_fine_channels, tilt_f)

        target = None
        if action in ("aim_spot", "hold_aim_for_capture"):
            spots = getattr(config, "spots", {}) or {}
            spot_name = state.get("spot", "")
            if not spot_name and spots:
                # hold_aim_for_capture carries no spot: hold the first.
                spot_name = sorted(spots)[0]
            spot = spots.get(spot_name)
            if spot is not None:
                target = (spot.x, spot.y, spot.z)

        for fixture in (getattr(group, "fixtures", None) or []):
            fixture_map = self._fixture_maps.get(fixture.name)
            if fixture_map is None:
                continue
            if action == "flash_full":
                _full(fixture_map)
            elif action == "rgb_steps":
                red, green, blue = RGB_STEPS[self._rgb_step]
                _full(fixture_map, red, green, blue)
            elif action == "special_steps":
                _full(fixture_map)
                _write(fixture_map, fixture_map.gobo_channels,
                       special_step_value(self._special_step))
            elif action in ("aim_spot", "hold_aim_for_capture"):
                _full(fixture_map)
                if target is not None:
                    _aim(fixture, fixture_map, target)
                if action == "hold_aim_for_capture":
                    if self._focus is not None:
                        _write(fixture_map, fixture_map.focus_channels,
                               self._focus)
                    if self._zoom is not None:
                        _write(fixture_map, fixture_map.zoom_channels,
                               self._zoom)

        return {u: (bytes(values[u]), bytes(masks[u])) for u in values}
