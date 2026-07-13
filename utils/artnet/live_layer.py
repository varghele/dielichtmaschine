# utils/artnet/live_layer.py
"""The Live busk surface as an output-arbiter layer
(docs/output-sync-plan.md phase 3) - the first pass where the Live
tab makes actual light.

The layer renders ``LiveState`` (gui/tabs/live_tab.py) through
FixtureChannelMaps into (values, mask) frames, claiming ONLY what the
busk programmer actually drives:

- A group with an APPLIED COLOUR claims its fixtures' dimmer (at the
  group's pre-grandmaster level), colour channels (swatch RGB; the
  two-colour swatches alternate primary/secondary across the group's
  fixtures by stage X) and shutter-open. A claim to zero on the unused
  colour channels is deliberate: a red busk over a blue show must read
  red, not purple.
- A group HELD ON FLASH without a colour claims only dimmer +
  shutter - the show's colour keeps showing through underneath at
  busk intensity (dimmer merges HTP in the arbiter).
- STROBE ON chops the claimed dimmers against the wall clock at a
  rate mapped from the strobe fader - real time-based output, no
  capability guessing on shutter channels.
- Fixtures without a dimmer channel get their COLOUR scaled by the
  level instead (and flash-only reads as a white flash).
- A mover group with an APPLIED POSITION (LiveState.positions, per
  group) claims pan + tilt on its pan/tilt-capable fixtures, aimed at
  the palette's stage-space target through the same calculate_pan_tilt
  path the playback layer uses for spot-targeted MovementBlocks, at the
  definition's physical ranges (FixtureChannelMap.pan_range/tilt_range),
  encoded 16-bit (pan_tilt_to_dmx16): coarse + fine bytes, so the aim
  resolves to the fixture's real precision instead of the ~2-degree
  coarse step - and the claimed fines keep a movement block underneath
  from jittering the busked aim. Position claims NO dimmer and NO
  shutter: movers can be pre-aimed dark, and intensity stays whatever
  the show (or a busk colour/flash) says.
- Groups without busk content claim nothing - RELEASE ALL clears the
  programmer, the claims vanish, and every channel falls through to
  whatever runs underneath. That IS busk-on-top.

A fixture in several claimed groups is written once per group in
config-group order - later groups win, mirroring the playback layer's
lane-order-wins call (locked 2026-07-11).

Grandmaster and DBO are NOT applied here: LiveState feeds them to the
arbiter's post-merge master stage (gui.py wiring), so they cap
timeline/Auto playback too.
"""

from typing import Callable, Dict, Optional, Tuple

from utils.orientation import calculate_pan_tilt, pan_tilt_to_dmx16
from utils.position_presets import (
    MARK_PREFIX, compute_presets, group_has_movers, mark_name,
)

from .arbiter import Frame

# Strobe rate fader (0-100) maps linearly onto this chop frequency
# band (Hz); 50% duty cycle against the arbiter clock.
STROBE_MIN_HZ = 1.0
STROBE_MAX_HZ = 10.0


def _hex_to_rgb(hex_color: str) -> Tuple[int, int, int]:
    value = (hex_color or "").lstrip("#")
    if len(value) != 6:
        return (0, 0, 0)
    try:
        return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return (0, 0, 0)


class LiveBuskLayer:
    """Arbiter LIVE layer over a ``LiveState``.

    ``config_provider`` is a zero-arg callable returning the current
    Configuration (the main window rebinds its config object on load,
    so the layer must not hold a stale reference). ``swatches`` is the
    Live tab's COLOUR_SWATCHES table, injected so this module stays
    gui-free: an iterable of (id, label, primary_hex, secondary_hex).

    Channel maps arrive via :meth:`set_fixture_maps` - the arbiter
    forwards whatever the active playback controller registered, so
    the busk layer lights up as soon as ArtNet output is enabled
    anywhere.
    """

    def __init__(self, state, config_provider: Callable,
                 swatches=()) -> None:
        self._state = state
        self._config_provider = config_provider
        self._swatch_colors: Dict[str, Tuple[str, Optional[str]]] = {
            swatch_id: (primary, secondary)
            for swatch_id, _label, primary, secondary in swatches
        }
        self._fixture_maps: Dict = {}

    def set_fixture_maps(self, fixture_maps) -> None:
        self._fixture_maps = dict(fixture_maps)

    # -- the arbiter layer contract -----------------------------------------

    def render(self, now: float) -> Frame:
        state = self._state
        config = self._config_provider()
        if config is None or not self._fixture_maps:
            return {}

        claimed_groups = []
        position_groups = []
        for group_name, group in getattr(config, "groups", {}).items():
            has_colour = group_name in state.colours
            has_flash = group_name in state.flash
            if has_colour or has_flash:
                claimed_groups.append((group_name, group, has_colour))
            position_id = state.positions.get(group_name)
            if position_id and group_has_movers(group):
                position_groups.append((group, position_id))
        if not claimed_groups and not position_groups:
            return {}

        strobe_open = True
        if state.strobe_on:
            frequency = STROBE_MIN_HZ + (STROBE_MAX_HZ - STROBE_MIN_HZ) \
                * (state.strobe_rate / 100.0)
            strobe_open = (now * frequency) % 1.0 < 0.5

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

        for group_name, group, has_colour in claimed_groups:
            level = state.group_level_local(group_name)
            effective = level if strobe_open else 0.0
            primary_hex, secondary_hex = (None, None)
            if has_colour:
                primary_hex, secondary_hex = self._swatch_colors.get(
                    state.colours[group_name], (None, None))

            fixtures = sorted(getattr(group, "fixtures", None) or [],
                              key=lambda f: f.x)
            for index, fixture in enumerate(fixtures):
                fixture_map = self._fixture_maps.get(fixture.name)
                if fixture_map is None:
                    continue

                if has_colour and primary_hex:
                    hex_color = secondary_hex \
                        if (secondary_hex and index % 2) else primary_hex
                    red, green, blue = _hex_to_rgb(hex_color)
                elif not fixture_map.dimmer_channels:
                    # Flash-only on a dimmerless fixture: white flash.
                    red, green, blue = (255, 255, 255)
                else:
                    red = green = blue = None   # no colour claim

                if fixture_map.dimmer_channels:
                    _write(fixture_map, fixture_map.dimmer_channels,
                           round(255 * effective))
                    colour_scale = 1.0
                else:
                    # Colour IS the intensity on dimmerless fixtures.
                    colour_scale = effective

                if red is not None:
                    _write(fixture_map, fixture_map.red_channels,
                           round(red * colour_scale))
                    _write(fixture_map, fixture_map.green_channels,
                           round(green * colour_scale))
                    _write(fixture_map, fixture_map.blue_channels,
                           round(blue * colour_scale))
                    # White rides along only for pure white; CMY is the
                    # inverse of RGB; the remaining colour attributes are
                    # claimed to zero so the show below cannot tint the
                    # busk colour.
                    white = 255 if (red, green, blue) == (255, 255, 255) \
                        else 0
                    _write(fixture_map, fixture_map.white_channels,
                           round(white * colour_scale))
                    _write(fixture_map, fixture_map.cyan_channels,
                           round((255 - red) * colour_scale))
                    _write(fixture_map, fixture_map.magenta_channels,
                           round((255 - green) * colour_scale))
                    _write(fixture_map, fixture_map.yellow_channels,
                           round((255 - blue) * colour_scale))
                    for attr in ("amber_channels", "uv_channels",
                                 "lime_channels"):
                        _write(fixture_map, getattr(fixture_map, attr), 0)

                # Open the shutter so movers actually emit; the strobe
                # chop happens on the dimmer, not the shutter channel.
                _write(fixture_map, fixture_map.strobe_channels, 255)

        # -- position palettes: aim each group's movers at its target --
        # A fixture in several position-holding groups is written once
        # per group in config-group order - later groups win, same
        # lane-order-wins call as the colour pass above.
        if position_groups:
            presets_by_id = {p.preset_id: p
                             for p in compute_presets(config)}
            for group, position_id in position_groups:
                for fixture in (getattr(group, "fixtures", None) or []):
                    fixture_map = self._fixture_maps.get(fixture.name)
                    if fixture_map is None:
                        continue
                    if not (fixture_map.pan_channels
                            or fixture_map.tilt_channels):
                        continue
                    target = self._target_for(config, presets_by_id,
                                              position_id, fixture)
                    if target is None:
                        continue
                    # Orientation comes from the PRIMARY group (groups[0]
                    # drives orientation - locked first-group-wins), same
                    # as the playback layer's spot targeting.
                    primary = config.groups.get(fixture.group) \
                        if fixture.group else None
                    mounting, yaw, pitch, roll = \
                        fixture.get_effective_orientation(primary)
                    fixture_z = fixture.get_effective_z(primary)
                    pan_deg, tilt_deg = calculate_pan_tilt(
                        fixture_x=fixture.x, fixture_y=fixture.y,
                        fixture_z=fixture_z,
                        target_x=target[0], target_y=target[1],
                        target_z=target[2],
                        mounting=mounting, yaw=yaw, pitch=pitch,
                        roll=roll,
                        pan_range=fixture_map.pan_range,
                        tilt_range=fixture_map.tilt_range,
                    )
                    # 16-bit aim: the coarse byte alone quantizes a
                    # 540-degree pan to ~2 degrees (~18 cm at 5 m);
                    # writing the fine bytes takes the aim to the
                    # fixture's real resolution. Claiming the fines also
                    # keeps a movement block underneath from jittering
                    # the busked aim.
                    pan_c, pan_f, tilt_c, tilt_f = pan_tilt_to_dmx16(
                        pan_deg, tilt_deg,
                        fixture_map.pan_range, fixture_map.tilt_range)
                    _write(fixture_map, fixture_map.pan_channels, pan_c)
                    _write(fixture_map, fixture_map.tilt_channels, tilt_c)
                    _write(fixture_map, fixture_map.pan_fine_channels,
                           pan_f)
                    _write(fixture_map, fixture_map.tilt_fine_channels,
                           tilt_f)

        return {u: (bytes(values[u]), bytes(masks[u])) for u in values}

    @staticmethod
    def _target_for(config, presets_by_id, position_id, fixture):
        """The stage-space (x, y, z) a position id aims this fixture at,
        or None when the id is stale (pruning is the state's job; a
        stale id between prunes must render nothing, not crash)."""
        if position_id.startswith(MARK_PREFIX):
            spot = (getattr(config, "spots", None)
                    or {}).get(mark_name(position_id))
            if spot is None:
                return None
            return (spot.x, spot.y, spot.z)
        preset = presets_by_id.get(position_id)
        if preset is None:
            return None
        return preset.target_for(fixture)
