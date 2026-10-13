# utils/artnet/pause_layer.py
"""The pause-look layer: the light between two setlist songs.

Minimal slice of the v1.8 conductor (built 2026-07-17 for the
Stellwerk gig): while the LTC chase is armed and no song is playing,
the shell activates the current setlist entry's ``pause_after`` on
this layer and the arbiter renders it in the pause slot - BELOW
playback and the Live busk (compose order pause > floor only), so the
next timecode-fired song simply covers it and a busked colour still
wins on its groups. The shell clears the layer when a song starts or
the chase disarms (gui.MainWindow._ltc_tick drives both).

Modes rendered here:

- ``scene``       a SceneLibrary look ("category/name" in
                  ``PauseLook.scene``): its colour on its groups,
                  scaled by ``level`` percent, plus the scene's mover
                  aims (``Scene.positions``) through the same
                  aim_fixture_at_position the busk layer uses.
- ``warm_white``  the whole rig warm white at ``level`` percent.
- ``blackout``    every fixture's dimmer and colour claimed to ZERO -
                  a claim, so it beats the editor's full-white
                  "fixtures visible" floor too.

``hold_last`` and ``ambient_loop`` stay data-only (the full v1.8
engine); this layer renders nothing for them, so the idle floor shows
exactly as before.
"""

from typing import Callable, Dict, Optional

from utils.position_presets import compute_presets

from .arbiter import Frame
from .dmx_manager import rgb_to_color_wheel
from .live_layer import _hex_to_rgb, aim_fixture_at_position

WARM_WHITE_RGB = (255, 190, 120)

#: FixtureChannelMap colour attributes claimed to zero in blackout and
#: zeroed alongside an active colour so the show below cannot tint it.
_EXTRA_COLOUR_ATTRS = ("amber_channels", "uv_channels", "lime_channels")


class PauseLookLayer:
    """Arbiter pause slot renderer over one active PauseLook (or none).

    ``config_provider`` is a zero-arg callable returning the current
    Configuration; ``scene_provider`` maps a "category/name" key to a
    Scene (both injected, same pattern as LiveBuskLayer). Channel maps
    arrive via :meth:`set_fixture_maps` - the arbiter forwards them to
    every map-less layer it hosts.
    """

    def __init__(self, config_provider: Callable,
                 scene_provider: Optional[Callable] = None) -> None:
        self._config_provider = config_provider
        self._scene_provider = scene_provider
        self._fixture_maps: Dict = {}
        self._look = None

    def set_fixture_maps(self, fixture_maps) -> None:
        self._fixture_maps = dict(fixture_maps)

    # -- shell control -------------------------------------------------

    def activate(self, look) -> None:
        """Show ``look`` (a config.models.PauseLook); idempotent."""
        self._look = look

    def clear(self) -> None:
        self._look = None

    @property
    def active(self) -> bool:
        return self._look is not None

    # -- the arbiter layer contract -------------------------------------

    def render(self, now: float) -> Frame:
        look = self._look
        if look is None or not self._fixture_maps:
            return {}
        config = self._config_provider() \
            if self._config_provider is not None else None
        if config is None:
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

        mode = getattr(look, "mode", "")
        level = max(0, min(100, int(getattr(look, "level", 100)))) / 100.0

        if mode == "blackout":
            for fixture_map in self._fixture_maps.values():
                self._colour_fixture(_write, fixture_map, (0, 0, 0), 0.0)
        elif mode == "warm_white":
            for fixture_map in self._fixture_maps.values():
                self._colour_fixture(_write, fixture_map, WARM_WHITE_RGB,
                                     level)
        elif mode == "scene":
            scene = self._scene_provider(getattr(look, "scene", "")) \
                if self._scene_provider is not None else None
            if scene is None:
                return {}
            rgb = _hex_to_rgb(getattr(scene, "color", "")) \
                if getattr(scene, "color", "") else None
            groups = getattr(config, "groups", {}) or {}
            if rgb is not None:
                for group_name in getattr(scene, "groups", ()) or ():
                    group = groups.get(group_name)
                    for fixture in (getattr(group, "fixtures", None)
                                    or []):
                        fixture_map = self._fixture_maps.get(fixture.name)
                        if fixture_map is not None:
                            self._colour_fixture(_write, fixture_map, rgb,
                                                 level)
            positions = getattr(scene, "positions", None) or {}
            if positions:
                presets_by_id = {p.preset_id: p
                                 for p in compute_presets(config)}
                for group_name, position_id in positions.items():
                    group = groups.get(group_name)
                    for fixture in (getattr(group, "fixtures", None)
                                    or []):
                        fixture_map = self._fixture_maps.get(fixture.name)
                        if fixture_map is not None:
                            aim_fixture_at_position(
                                _write, config, presets_by_id,
                                position_id, fixture, fixture_map)
        else:
            # hold_last / ambient_loop: full v1.8 engine - nothing here.
            return {}

        return {u: (bytes(values[u]), bytes(masks[u])) for u in values}

    # -- rendering helpers ----------------------------------------------

    @staticmethod
    def _colour_fixture(write, fixture_map, rgb, level: float) -> None:
        """One fixture in one flat colour at ``level`` - the pause-look
        cut of the busk layer's colour semantics: dimmer carries the
        level where one exists (colour at full), colour IS the level on
        dimmerless fixtures, CMY inverted, other colour attributes
        claimed to zero, wheel-only fixtures steer the wheel, shutter
        open (except blackout: everything lands at zero anyway)."""
        red, green, blue = rgb
        if fixture_map.dimmer_channels:
            write(fixture_map, fixture_map.dimmer_channels,
                  round(255 * level))
            colour_scale = 1.0
        else:
            colour_scale = level
        write(fixture_map, fixture_map.red_channels,
              round(red * colour_scale))
        write(fixture_map, fixture_map.green_channels,
              round(green * colour_scale))
        write(fixture_map, fixture_map.blue_channels,
              round(blue * colour_scale))
        white = 255 if (red, green, blue) == (255, 255, 255) else 0
        write(fixture_map, fixture_map.white_channels,
              round(white * colour_scale))
        write(fixture_map, fixture_map.cyan_channels,
              round((255 - red) * colour_scale))
        write(fixture_map, fixture_map.magenta_channels,
              round((255 - green) * colour_scale))
        write(fixture_map, fixture_map.yellow_channels,
              round((255 - blue) * colour_scale))
        for attr in _EXTRA_COLOUR_ATTRS:
            write(fixture_map, getattr(fixture_map, attr), 0)
        if not (fixture_map.red_channels or fixture_map.green_channels
                or fixture_map.blue_channels):
            write(fixture_map, fixture_map.color_wheel_channels,
                  rgb_to_color_wheel(red, green, blue))
        shutter = 0 if level <= 0 and rgb == (0, 0, 0) else 255
        write(fixture_map, fixture_map.strobe_channels, shutter)
