# utils/artnet/dmx_manager.py
# DMX state manager for real-time DMX output

import time
import math
from typing import Dict, List, Optional, Tuple, Any
from config.models import Configuration, Fixture, LightBlock, DimmerBlock, ColourBlock, MovementBlock, SpecialBlock
from utils import user_warnings
from utils.effects_utils import get_channels_by_property
from utils.orientation import calculate_pan_tilt, pan_tilt_to_dmx
from effects import (
    DimmerContext, DimmerResult, MovementContext, MovementResult,
    DIMMER_REGISTRY, MOVEMENT_REGISTRY, parse_speed, get_bpm, movement_total_cycles,
)

# Debug flag - set to False to disable verbose prints (improves performance significantly)
DEBUG_PRINTS = False

# Assumed pan/tilt travel when the fixture definition declares no
# <Physical><Focus> ranges (PanMax/TiltMax absent or 0). Matches the
# calculate_pan_tilt/pan_tilt_to_dmx defaults so aiming stays unchanged
# for definitions without physical data.
DEFAULT_PAN_RANGE = 540.0
DEFAULT_TILT_RANGE = 270.0


def rgb_to_color_wheel(r: float, g: float, b: float) -> int:
    """
    Map RGB to color wheel position.

    Simple mapping to closest standard color.
    DMX values are set to mid-range of typical color wheel positions
    to work with most fixtures (Varytec Hero Spot 60, etc.)

    Module-level so the Live busk layer (utils/artnet/live_layer.py)
    steers wheel-only movers the same way playback does.
    """
    # Standard color wheel positions (using mid-range DMX values)
    # Most color wheels have ~25 DMX values per color
    wheel_colors = [
        (255, 255, 255, 12),   # White (typically 0-24)
        (255, 0, 0, 37),       # Red (typically 25-50)
        (255, 255, 0, 63),     # Yellow (typically 51-75)
        (173, 216, 230, 88),   # Light Blue (typically 76-100)
        (0, 255, 0, 113),      # Green (typically 101-125)
        (255, 170, 0, 138),    # Amber/Orange (typically 126-150)
        (238, 130, 238, 163),  # Violet (typically 151-175)
        (0, 0, 255, 188),      # Blue (typically 176-200)
    ]

    min_distance = float('inf')
    closest_value = 12  # Default to white

    for wr, wg, wb, dmx_value in wheel_colors:
        distance = ((r - wr) ** 2 + (g - wg) ** 2 + (b - wb) ** 2) ** 0.5
        if distance < min_distance:
            min_distance = distance
            closest_value = dmx_value

    return closest_value


class FixtureChannelMap:
    """
    Maps a fixture's capabilities to its DMX channel addresses.

    Handles conversion from fixture universe/address to absolute DMX channels.
    """

    def __init__(self, fixture: Fixture, fixture_def: dict, config: Configuration):
        """
        Initialize fixture channel mapping.

        Args:
            fixture: Fixture instance
            fixture_def: Fixture definition from .qxf parsing
            config: Configuration containing universe settings
        """
        self.fixture = fixture
        self.fixture_def = fixture_def
        self.config = config

        # Get base DMX address (universe and channel)
        self.universe = fixture.universe
        self.base_address = fixture.address - 1  # DMX is 1-indexed, array is 0-indexed

        # Get channel mappings from fixture definition
        self.mode_name = fixture.current_mode
        self._build_channel_map()

        # Physical pan/tilt travel (degrees) from the definition's
        # <Physical><Focus>, with the historical defaults as fallback
        # when the definition declares none (absent key or 0).
        physical = fixture_def.get('physical') or {}
        self.pan_range = float(physical.get('pan_max') or 0.0) \
            or DEFAULT_PAN_RANGE
        self.tilt_range = float(physical.get('tilt_max') or 0.0) \
            or DEFAULT_TILT_RANGE

    def _build_channel_map(self):
        """Build channel mapping from fixture definition."""
        # Query channels by property using effects_utils
        # Include "Intensity" as a group name that some fixtures use for dimmer
        properties = [
            "IntensityMasterDimmer", "IntensityDimmer", "Intensity",
            "IntensityRed", "IntensityGreen", "IntensityBlue", "IntensityWhite",
            "IntensityAmber", "IntensityCyan", "IntensityMagenta", "IntensityYellow",
            "IntensityUV", "IntensityLime",
            "PositionPan", "PositionTilt", "PositionPanFine", "PositionTiltFine",
            "ColorWheel", "ColorMacro", "Colour",
            "GoboWheel", "Gobo", "Gobo1", "Gobo2",
            "PrismRotation", "Prism",
            "BeamFocusNearFar", "BeamZoomSmallBig", "BeamIrisCloseOpen",
            "ShutterStrobeOpen", "ShutterStrobeFast", "ShutterStrobeRandom", "Shutter"
        ]

        channels_dict = get_channels_by_property(self.fixture_def, self.mode_name, properties)

        # Store channel mappings (property -> list of channel offsets)
        # Include "Intensity" group for fixtures that use that naming
        self.dimmer_channels = self._get_channel_offsets(channels_dict, ["IntensityMasterDimmer", "IntensityDimmer", "Intensity"])
        self.red_channels = self._get_channel_offsets(channels_dict, ["IntensityRed"])
        self.green_channels = self._get_channel_offsets(channels_dict, ["IntensityGreen"])
        self.blue_channels = self._get_channel_offsets(channels_dict, ["IntensityBlue"])
        self.white_channels = self._get_channel_offsets(channels_dict, ["IntensityWhite"])
        self.amber_channels = self._get_channel_offsets(channels_dict, ["IntensityAmber"])
        self.cyan_channels = self._get_channel_offsets(channels_dict, ["IntensityCyan"])
        self.magenta_channels = self._get_channel_offsets(channels_dict, ["IntensityMagenta"])
        self.yellow_channels = self._get_channel_offsets(channels_dict, ["IntensityYellow"])
        self.uv_channels = self._get_channel_offsets(channels_dict, ["IntensityUV"])
        self.lime_channels = self._get_channel_offsets(channels_dict, ["IntensityLime"])
        self.pan_channels = self._get_channel_offsets(channels_dict, ["PositionPan"])
        self.tilt_channels = self._get_channel_offsets(channels_dict, ["PositionTilt"])
        self.pan_fine_channels = self._get_channel_offsets(channels_dict, ["PositionPanFine"])
        self.tilt_fine_channels = self._get_channel_offsets(channels_dict, ["PositionTiltFine"])
        self.color_wheel_channels = self._get_channel_offsets(channels_dict, ["ColorWheel", "ColorMacro", "Colour"])
        self.gobo_channels = self._get_channel_offsets(channels_dict, ["GoboWheel", "Gobo", "Gobo1"])
        self.prism_channels = self._get_channel_offsets(channels_dict, ["Prism"])
        self.focus_channels = self._get_channel_offsets(channels_dict, ["BeamFocusNearFar"])
        self.zoom_channels = self._get_channel_offsets(channels_dict, ["BeamZoomSmallBig"])
        self.strobe_channels = self._get_channel_offsets(channels_dict, ["ShutterStrobeOpen", "ShutterStrobeFast", "ShutterStrobeRandom", "Shutter", "ShutterOpen"])

    def _get_channel_offsets(self, channels_dict: dict, properties: List[str]) -> List[int]:
        """
        Get channel offsets for given properties.

        Args:
            channels_dict: Dictionary from get_channels_by_property
            properties: List of property names to look for

        Returns:
            List of channel offsets (0-indexed)
        """
        offsets = []
        for prop in properties:
            if prop in channels_dict:
                for ch_info in channels_dict[prop]:
                    offsets.append(ch_info['channel'])
        return offsets

    def get_absolute_address(self, channel_offset: int) -> Tuple[int, int]:
        """
        Convert fixture-relative channel to absolute universe/channel.

        Args:
            channel_offset: Channel offset (0-indexed)

        Returns:
            (universe, channel) tuple
        """
        absolute_channel = self.base_address + channel_offset
        return (self.universe, absolute_channel)


class DMXManager:
    """
    Manages DMX state for all universes.

    Tracks active blocks and converts them to DMX values in real-time.
    Handles overlapping blocks with LTP (Latest Takes Priority).

    Alongside the value buffers the manager keeps a per-universe CLAIM
    MASK (``dmx_touched``): one byte per channel, 1 where this renderer
    deliberately drives the channel. Every write through
    :meth:`set_dmx_value` claims its channel - including a write of 0,
    which is a claim to zero - while :meth:`clear_all_dmx` resets both
    values and claims (a buffer reset is not a claim). The output
    arbiter (docs/output-sync-plan.md) merges renderers by these masks;
    an unclaimed channel falls through to the layer below. Because
    :meth:`update_dmx` starts every frame from ``clear_all_dmx`` and
    re-applies the safe idle state plus the active blocks, the mask is
    exact per frame with no decay bookkeeping.
    """

    @staticmethod
    def build_fixture_maps(config: Configuration,
                           fixture_definitions: dict = None) -> dict:
        """Channel maps for every fixture in ``config``, standalone.

        The same maps :meth:`_build_fixture_maps` builds for a full
        DMXManager, without constructing one - so the output arbiter
        can render the "fixtures visible" idle floor before any
        playback controller exists (OUTPUT toggled on with nothing
        playing used to stream an all-zero floor because the maps only
        arrived with playback). Definitions default to the shared
        cache, loaded for exactly the config's models.
        """
        if fixture_definitions is None:
            from utils.fixture_utils import get_cached_fixture_definitions
            models = {(f.manufacturer, f.model)
                      for f in getattr(config, "fixtures", []) or []}
            fixture_definitions = get_cached_fixture_definitions(models) \
                if models else {}
        maps = {}
        for fixture in getattr(config, "fixtures", []) or []:
            fixture_def = fixture_definitions.get(
                f"{fixture.manufacturer}_{fixture.model}")
            if fixture_def:
                maps[fixture.name] = FixtureChannelMap(
                    fixture, fixture_def, config)
        return maps

    def __init__(self, config: Configuration, fixture_definitions: dict, song_structure=None,
                 emit_safe_idle: bool = True):
        """
        Initialize DMX manager.

        Args:
            config: Configuration with fixtures and universes
            fixture_definitions: Dictionary of parsed fixture definitions
            song_structure: Optional SongStructure for BPM-aware timing
            emit_safe_idle: When True (default, playback behaviour),
                update_dmx claims safe idle values on EVERY fixture
                (shutter open, colour wheel white, pan/tilt centre).
                The Live engine's private managers pass False - they
                must claim ONLY what their staged blocks drive, so the
                busk rides on top of the show instead of grabbing every
                mover's wheel and yoke (docs/live-output-plan.md).
        """
        self.config = config
        self.fixture_definitions = fixture_definitions
        self.song_structure = song_structure
        self.emit_safe_idle = emit_safe_idle

        # DMX state - universe_id -> 512-byte array, plus the parallel
        # claim mask (see class docstring): 1 = channel deliberately
        # driven this frame, 0 = unclaimed (falls through in a merge).
        self.dmx_state: Dict[int, bytearray] = {}
        self.dmx_touched: Dict[int, bytearray] = {}

        # Initialize universes from configuration (ensure int keys - YAML may load as string)
        for universe_id in config.universes.keys():
            self.dmx_state[int(universe_id)] = bytearray(512)
            self.dmx_touched[int(universe_id)] = bytearray(512)

        # Also initialize universes for all fixtures (in case fixture uses unconfigured universe)
        for fixture in config.fixtures:
            if fixture.universe not in self.dmx_state:
                self.dmx_state[fixture.universe] = bytearray(512)
                self.dmx_touched[fixture.universe] = bytearray(512)

        # Build fixture channel maps
        self.fixture_maps: Dict[str, FixtureChannelMap] = {}
        self._build_fixture_maps()

        # Track active blocks (LTP - Latest Takes Priority)
        # Dictionary: lane_key -> {sublane_type -> (fixtures, block, start_time)}
        # fixtures is a list of Fixture objects resolved from the lane's targets
        self.active_blocks: Dict[str, Dict[str, Tuple[List[Fixture], object, float]]] = {}

        # Movement speed limiting
        self._max_pan_tilt_speed: float = 0.0  # degrees/sec, 0 = unlimited
        self._prev_pan: Dict[str, float] = {}  # fixture_key -> last pan DMX
        self._prev_tilt: Dict[str, float] = {}  # fixture_key -> last tilt DMX

        # Stage planes for world-space movement (set by live mode)
        self._stage_planes: Dict[str, 'StagePlane'] = {}

        print(f"DMX Manager initialized with {len(self.dmx_state)} universes")

    def set_max_pan_tilt_speed(self, degrees_per_sec: float):
        """Set maximum pan/tilt speed in degrees/second. 0 = unlimited."""
        self._max_pan_tilt_speed = max(0.0, degrees_per_sec)

    def set_stage_planes(self, planes: dict):
        """Set stage planes dict (name -> StagePlane) for world-space movement."""
        self._stage_planes = planes

    def set_song_structure(self, song_structure):
        """
        Set or update the song structure for BPM-aware calculations.

        Args:
            song_structure: SongStructure instance
        """
        self.song_structure = song_structure

    def _build_fixture_maps(self):
        """Build channel maps for all fixtures."""
        mapped_count = 0
        missing_defs = []

        for fixture in self.config.fixtures:
            # Get fixture definition - keys are "manufacturer_model" strings
            fixture_key = f"{fixture.manufacturer}_{fixture.model}"
            fixture_def = self.fixture_definitions.get(fixture_key)

            if fixture_def:
                self.fixture_maps[fixture.name] = FixtureChannelMap(fixture, fixture_def, self.config)
                mapped_count += 1
            else:
                missing_defs.append(fixture.name)

        # Summary logging instead of per-fixture
        if missing_defs:
            user_warnings.warn(
                f"No fixture definitions for: {', '.join(missing_defs)}. "
                f"These fixtures will not output.",
                category="output",
                once_key="missing-defs:" + ",".join(sorted(missing_defs)))

    def rebuild_fixture_maps(self):
        """Rebuild fixture maps when fixtures are added, removed, or modified."""
        self.fixture_maps.clear()
        self._build_fixture_maps()

        # Ensure all fixture universes are initialized in dmx_state
        new_universes = []
        for fixture in self.config.fixtures:
            if fixture.universe not in self.dmx_state:
                self.dmx_state[fixture.universe] = bytearray(512)
                self.dmx_touched[fixture.universe] = bytearray(512)
                new_universes.append(fixture.universe)

        if new_universes:
            print(f"DMXManager: Added universe(s) {new_universes}")

    def clear_all_dmx(self):
        """Clear all DMX values to 0 and drop all channel claims.

        A buffer reset is not a claim: after this, every channel is
        unclaimed until something writes it through set_dmx_value.
        """
        # PERFORMANCE: Use fill() instead of creating new bytearray objects
        for universe_id in self.dmx_state.keys():
            self.dmx_state[universe_id][:] = b'\x00' * 512
            self.dmx_touched[universe_id][:] = b'\x00' * 512

    def clear_active_blocks(self):
        """Clear all active block tracking state.

        This should be called when switching shows to ensure the old show's
        block state doesn't persist into the new show.
        """
        self.active_blocks.clear()

    def set_fixtures_visible(self):
        """Set all fixtures to a visible idle state (dimmer at 255, white color, shutter open, centered)."""
        for fixture_name, fixture_map in self.fixture_maps.items():
            universe = fixture_map.universe

            # Set dimmer to full
            for ch_offset in fixture_map.dimmer_channels:
                _, channel = fixture_map.get_absolute_address(ch_offset)
                self.set_dmx_value(universe, channel, 255)

            # Set RGB to white
            for ch_offset in fixture_map.red_channels:
                _, channel = fixture_map.get_absolute_address(ch_offset)
                self.set_dmx_value(universe, channel, 255)
            for ch_offset in fixture_map.green_channels:
                _, channel = fixture_map.get_absolute_address(ch_offset)
                self.set_dmx_value(universe, channel, 255)
            for ch_offset in fixture_map.blue_channels:
                _, channel = fixture_map.get_absolute_address(ch_offset)
                self.set_dmx_value(universe, channel, 255)
            for ch_offset in fixture_map.white_channels:
                _, channel = fixture_map.get_absolute_address(ch_offset)
                self.set_dmx_value(universe, channel, 255)

            # Open shutter (many moving heads need this to emit light)
            for ch_offset in fixture_map.strobe_channels:
                _, channel = fixture_map.get_absolute_address(ch_offset)
                self.set_dmx_value(universe, channel, 255)  # Usually 255 = open

            # Set color wheel to first position (usually white/open)
            for ch_offset in fixture_map.color_wheel_channels:
                _, channel = fixture_map.get_absolute_address(ch_offset)
                self.set_dmx_value(universe, channel, 0)  # Usually 0 = white/open

            # Reset pan/tilt to center position (127 = middle of 0-255 range)
            for ch_offset in fixture_map.pan_channels:
                _, channel = fixture_map.get_absolute_address(ch_offset)
                self.set_dmx_value(universe, channel, 127)
            for ch_offset in fixture_map.tilt_channels:
                _, channel = fixture_map.get_absolute_address(ch_offset)
                self.set_dmx_value(universe, channel, 127)
            # Also reset fine channels to center
            for ch_offset in fixture_map.pan_fine_channels:
                _, channel = fixture_map.get_absolute_address(ch_offset)
                self.set_dmx_value(universe, channel, 127)
            for ch_offset in fixture_map.tilt_fine_channels:
                _, channel = fixture_map.get_absolute_address(ch_offset)
                self.set_dmx_value(universe, channel, 127)

    def _set_safe_idle_state(self):
        """Set all fixtures to a safe idle state (shutter open, color wheel at white).

        Unlike set_fixtures_visible(), this keeps dimmers at 0 so fixtures appear off,
        but prevents strobe modes and other unwanted behavior by setting control channels
        to safe defaults.
        """
        for fixture_name, fixture_map in self.fixture_maps.items():
            universe = fixture_map.universe

            # Keep dimmers at 0 (already cleared by clear_all_dmx)
            # But ensure shutter is open to prevent strobe modes
            for ch_offset in fixture_map.strobe_channels:
                _, channel = fixture_map.get_absolute_address(ch_offset)
                self.set_dmx_value(universe, channel, 255)  # 255 = shutter open

            # Set color wheel to first position (white/open) to prevent weird colors
            for ch_offset in fixture_map.color_wheel_channels:
                _, channel = fixture_map.get_absolute_address(ch_offset)
                self.set_dmx_value(universe, channel, 0)  # 0 = white/open

            # Set pan/tilt to center so moving heads don't snap around
            for ch_offset in fixture_map.pan_channels:
                _, channel = fixture_map.get_absolute_address(ch_offset)
                self.set_dmx_value(universe, channel, 127)
            for ch_offset in fixture_map.tilt_channels:
                _, channel = fixture_map.get_absolute_address(ch_offset)
                self.set_dmx_value(universe, channel, 127)
            for ch_offset in fixture_map.pan_fine_channels:
                _, channel = fixture_map.get_absolute_address(ch_offset)
                self.set_dmx_value(universe, channel, 127)
            for ch_offset in fixture_map.tilt_fine_channels:
                _, channel = fixture_map.get_absolute_address(ch_offset)
                self.set_dmx_value(universe, channel, 127)

    def set_dmx_value(self, universe: int, channel: int, value: int):
        """
        Set a single DMX channel value and claim the channel (a write
        of 0 is a claim to zero, not a release - release is
        clear_all_dmx).

        Args:
            universe: Universe ID
            channel: Channel number (0-511)
            value: DMX value (0-255)
        """
        if universe not in self.dmx_state:
            user_warnings.warn(
                f"Universe {universe} is not initialized; DMX writes to "
                f"it are dropped",
                category="output", once_key=f"universe:{universe}")
            return

        if 0 <= channel < 512:
            self.dmx_state[universe][channel] = max(0, min(255, value))
            self.dmx_touched[universe][channel] = 1

    def get_dmx_data(self, universe: int) -> bytes:
        """
        Get DMX data for a universe.

        Args:
            universe: Universe ID

        Returns:
            512 bytes of DMX data
        """
        if universe not in self.dmx_state:
            return bytes(512)

        return bytes(self.dmx_state[universe])

    def get_touched_mask(self, universe: int) -> bytes:
        """The claim mask for a universe: one byte per channel, 1 where
        this renderer deliberately drives the channel this frame.

        Args:
            universe: Universe ID

        Returns:
            512 bytes of 0/1 claims (all zeros for unknown universes)
        """
        if universe not in self.dmx_touched:
            return bytes(512)
        return bytes(self.dmx_touched[universe])

    def get_frame(self, universe: int) -> Tuple[bytes, bytes]:
        """The (values, mask) pair the output arbiter merges by
        (docs/output-sync-plan.md).

        Args:
            universe: Universe ID

        Returns:
            (512 value bytes, 512 claim bytes)
        """
        return self.get_dmx_data(universe), self.get_touched_mask(universe)

    def block_started(self, lane_key: str, fixtures: List[Fixture], block: object, block_type: str, current_time: float):
        """
        Called when a block starts playback.

        Args:
            lane_key: Unique identifier for the lane (usually lane name)
            fixtures: List of resolved Fixture objects to apply the effect to
            block: Block instance (DimmerBlock, ColourBlock, etc.)
            block_type: Type of block ('dimmer', 'colour', 'movement', 'special')
            current_time: Current playback time in seconds
        """
        # Initialize lane if needed
        if lane_key not in self.active_blocks:
            self.active_blocks[lane_key] = {}

        # Store fixtures, block, and start time (LTP)
        self.active_blocks[lane_key][block_type] = (fixtures, block, current_time)

    def block_ended(self, lane_key: str, block_type: str):
        """
        Called when a block ends playback.

        Args:
            lane_key: Unique identifier for the lane (usually lane name)
            block_type: Type of block ('dimmer', 'colour', 'movement', 'special')
        """
        if lane_key in self.active_blocks:
            if block_type in self.active_blocks[lane_key]:
                del self.active_blocks[lane_key][block_type]

    def update_dmx(self, current_time: float):
        """
        Update DMX state based on active blocks at current time.

        Args:
            current_time: Current playback time in seconds
        """
        # Clear all DMX values first - only fixtures with active blocks should be lit
        self.clear_all_dmx()

        # Set safe default values for ALL fixtures to prevent strobe/weird modes
        # This ensures shutters are open, dimmers at 0, etc. for non-targeted fixtures
        # (suppressed for the Live engine's private managers - see __init__).
        if self.emit_safe_idle:
            self._set_safe_idle_state()

        # Process each lane's active blocks
        # Make a copy of items to avoid issues during iteration
        active_items = list(self.active_blocks.items())
        for lane_key, active in active_items:
            # Get active blocks for this lane
            dimmer_data = active.get('dimmer')
            colour_data = active.get('colour')
            movement_data = active.get('movement')
            special_data = active.get('special')

            # Extract fixtures and blocks from the stored data
            # Each data entry is (fixtures, block, start_time)
            dimmer_fixtures = dimmer_data[0] if dimmer_data else []
            dimmer_block = dimmer_data[1] if dimmer_data else None
            colour_fixtures = colour_data[0] if colour_data else []
            colour_block = colour_data[1] if colour_data else None
            movement_fixtures = movement_data[0] if movement_data else []
            movement_block = movement_data[1] if movement_data else None
            special_fixtures = special_data[0] if special_data else []
            special_block = special_data[1] if special_data else None

            # Apply dimmer block to its resolved fixtures
            if dimmer_block and dimmer_fixtures:
                # Sort fixtures by x-position for spatial effects like ping_pong
                sorted_fixtures = sorted(dimmer_fixtures, key=lambda f: f.x)
                total_fixtures = len(sorted_fixtures)

                # Debug: Print once around 12.5s
                if DEBUG_PRINTS and 12.4 < current_time < 12.6 and not hasattr(self, '_debug_dmx_12_5'):
                    self._debug_dmx_12_5 = True
                    fixture_names = [f.name for f in sorted_fixtures]
                    print(f"\n=== DMX DEBUG at {current_time:.3f}s ===")
                    print(f"  Lane: {lane_key}")
                    print(f"  Dimmer block: {dimmer_block.effect_type}, {dimmer_block.start_time:.2f}-{dimmer_block.end_time:.2f}")
                    print(f"  Fixtures: {fixture_names}, total={total_fixtures}")
                    for f in sorted_fixtures:
                        in_maps = f.name in self.fixture_maps
                        print(f"    {f.name}: in fixture_maps={in_maps}")
                    print("=== END DMX DEBUG ===\n")

                # Debug: Print WASH fixtures around 137s
                if DEBUG_PRINTS:
                    fixture_names_check = [f.name for f in sorted_fixtures]
                    if 137.0 < current_time < 137.5 and any('W1' in n or 'W2' in n for n in fixture_names_check):
                        if not hasattr(self, '_debug_dmx_wash'):
                            self._debug_dmx_wash = True
                            print(f"\n=== DMX WASH DEBUG at {current_time:.3f}s ===")
                            print(f"  Lane: {lane_key}")
                            print(f"  Dimmer block: {dimmer_block.effect_type}, intensity={dimmer_block.intensity}")
                            print(f"  Block time range: {dimmer_block.start_time:.2f}-{dimmer_block.end_time:.2f}")
                            print(f"  Fixtures: {fixture_names_check}")
                            for f in sorted_fixtures:
                                in_maps = f.name in self.fixture_maps
                                print(f"    {f.name}: universe={f.universe}, address={f.address}, in_maps={in_maps}")
                                if in_maps:
                                    fm = self.fixture_maps[f.name]
                                    print(f"      dimmer_channels={fm.dimmer_channels}, red={fm.red_channels}, green={fm.green_channels}, blue={fm.blue_channels}")
                            print(f"  DMX state universes: {list(self.dmx_state.keys())}")
                            print("=== END DMX WASH DEBUG ===\n")

                for fixture_index, fixture in enumerate(sorted_fixtures):
                    if fixture.name not in self.fixture_maps:
                        continue

                    fixture_map = self.fixture_maps[fixture.name]
                    self._apply_dimmer_block(fixture_map, dimmer_block, current_time,
                                            fixture_index, total_fixtures)

            # Apply colour block to its resolved fixtures
            if colour_block and colour_fixtures:
                # Debug: Print WASH colour blocks around 137s
                if DEBUG_PRINTS:
                    colour_fixture_names = [f.name for f in colour_fixtures]
                    if 137.0 < current_time < 137.5 and any('W1' in n or 'W2' in n for n in colour_fixture_names):
                        if not hasattr(self, '_debug_colour_wash'):
                            self._debug_colour_wash = True
                            print(f"\n=== COLOUR WASH DEBUG at {current_time:.3f}s ===")
                            print(f"  Lane: {lane_key}")
                            print(f"  Colour block: R={colour_block.red}, G={colour_block.green}, B={colour_block.blue}")
                            print(f"  Block time range: {colour_block.start_time:.2f}-{colour_block.end_time:.2f}")
                            print(f"  Fixtures: {colour_fixture_names}")
                            print("=== END COLOUR WASH DEBUG ===\n")

                for fixture in colour_fixtures:
                    if fixture.name not in self.fixture_maps:
                        continue
                    fixture_map = self.fixture_maps[fixture.name]
                    self._apply_colour_block(fixture_map, colour_block, current_time)

            # Apply movement block to its resolved fixtures
            if movement_block and movement_fixtures:
                # Sort fixtures by x-position for consistent phase offset ordering
                sorted_movement_fixtures = sorted(movement_fixtures, key=lambda f: f.x)
                total_movement_fixtures = len(sorted_movement_fixtures)

                # Debug: log movement block application once
                if DEBUG_PRINTS and not hasattr(self, '_debug_movement_logged'):
                    self._debug_movement_logged = True
                    fixture_names = [f.name for f in sorted_movement_fixtures]
                    print(f"[DMX DEBUG] Movement block: {movement_block.effect_type} on {fixture_names}, "
                          f"pan={movement_block.pan}, tilt={movement_block.tilt}, "
                          f"phase_offset={movement_block.phase_offset_enabled}, "
                          f"phase_degrees={movement_block.phase_offset_degrees}")

                for fixture_index, fixture in enumerate(sorted_movement_fixtures):
                    if fixture.name not in self.fixture_maps:
                        continue
                    fixture_map = self.fixture_maps[fixture.name]
                    self._apply_movement_block(fixture_map, movement_block, current_time,
                                               fixture_index, total_movement_fixtures)

            # Apply special block to its resolved fixtures
            if special_block and special_fixtures:
                for fixture in special_fixtures:
                    if fixture.name not in self.fixture_maps:
                        continue
                    fixture_map = self.fixture_maps[fixture.name]
                    self._apply_special_block(fixture_map, special_block, current_time)

    def _apply_dimmer_block(self, fixture_map: FixtureChannelMap, block: DimmerBlock, current_time: float,
                            fixture_index: int = 0, total_fixtures: int = 1):
        """Apply dimmer block to fixture channels.

        Args:
            fixture_map: Channel mapping for this fixture
            block: DimmerBlock with effect settings
            current_time: Current playback time in seconds
            fixture_index: This fixture's index within the group (for group effects)
            total_fixtures: Total fixtures in the group (for group effects)
        """
        # Clear any previous segment intensities
        # (will be set again if the effect produces segment intensities)
        if hasattr(fixture_map, '_segment_intensities'):
            delattr(fixture_map, '_segment_intensities')

        # Determine fixture type and segment info
        fixture_type = getattr(fixture_map.fixture, 'type', '')
        is_pixelbar = fixture_type in ('PIXELBAR', 'BAR')
        is_segmented_type = fixture_type in ('PIXELBAR', 'BAR', 'SUNSTRIP')
        has_color_segments = bool(fixture_map.red_channels or fixture_map.white_channels)
        has_dimmer_segments = len(fixture_map.dimmer_channels) > 1
        is_segmented = is_segmented_type and (has_color_segments or has_dimmer_segments)

        if is_segmented:
            if has_color_segments:
                num_segments = max(
                    len(fixture_map.red_channels),
                    len(fixture_map.green_channels),
                    len(fixture_map.blue_channels),
                    len(fixture_map.white_channels),
                    1
                )
                is_dimmer_only = False
            else:
                num_segments = len(fixture_map.dimmer_channels)
                is_dimmer_only = True
        else:
            # For sparkle on non-segmented fixtures, num_segments = dimmer channel count
            num_segments = max(len(fixture_map.dimmer_channels), 1)
            is_dimmer_only = True

        # Build context
        speed_multiplier = parse_speed(block.effect_speed)
        bpm = get_bpm(self.song_structure, current_time)

        ctx = DimmerContext(
            time_in_block=current_time - block.start_time,
            block_duration=block.end_time - block.start_time,
            intensity=block.intensity,
            speed_multiplier=speed_multiplier,
            bpm=bpm,
            fixture_index=fixture_index,
            total_fixtures=total_fixtures,
            num_segments=num_segments,
            fixture_name=fixture_map.fixture.name,
            block_start_time=block.start_time,
            is_segmented=is_segmented,
            direction=getattr(block, 'direction', 'down'),
            chase_scope=getattr(block, 'chase_scope', 'fixture'),
            phase_offset_per_fixture=getattr(block, 'phase_offset_per_fixture', False),
            build_fraction=getattr(block, 'build_fraction', 0.7),
        )

        # Dispatch to effect function
        effect_fn = DIMMER_REGISTRY.get(block.effect_type, DIMMER_REGISTRY["static"])
        result = effect_fn(ctx)

        # Apply result to DMX channels
        self._apply_dimmer_result(fixture_map, block, result, is_segmented, is_pixelbar,
                                   has_color_segments, is_dimmer_only)

        # For fixtures with shutter channels (like moving heads), ensure shutter is open
        for ch_offset in fixture_map.strobe_channels:
            universe, channel = fixture_map.get_absolute_address(ch_offset)
            self.set_dmx_value(universe, channel, 255)

    def _apply_dimmer_result(self, fixture_map: FixtureChannelMap, block: DimmerBlock,
                              result: DimmerResult, is_segmented: bool, is_pixelbar: bool,
                              has_color_segments: bool, is_dimmer_only: bool):
        """Apply a DimmerResult to fixture DMX channels.

        Handles pixelbar vs regular fixture branching in one place.
        """
        if result.segment_intensities is not None:
            if is_segmented and has_color_segments and not is_dimmer_only:
                # Pixelbar with color segments: set master dimmer to full,
                # store segment intensities for colour_block to scale colors
                for ch_offset in fixture_map.dimmer_channels:
                    universe, channel = fixture_map.get_absolute_address(ch_offset)
                    self.set_dmx_value(universe, channel, int(block.intensity))
                fixture_map._segment_intensities = result.segment_intensities
            elif is_segmented and is_dimmer_only:
                # Sunstrip / dimmer-only segments: write each dimmer channel directly
                for seg_idx, ch_offset in enumerate(fixture_map.dimmer_channels):
                    if seg_idx < len(result.segment_intensities):
                        seg_intensity = int(block.intensity * result.segment_intensities[seg_idx])
                        universe, channel = fixture_map.get_absolute_address(ch_offset)
                        self.set_dmx_value(universe, channel, seg_intensity)
            else:
                # Non-segmented fixture with per-channel intensities (e.g. sparkle)
                for idx, ch_offset in enumerate(fixture_map.dimmer_channels):
                    if idx < len(result.segment_intensities):
                        channel_intensity = int(block.intensity * result.segment_intensities[idx])
                    else:
                        channel_intensity = int(block.intensity)
                    universe, channel = fixture_map.get_absolute_address(ch_offset)
                    self.set_dmx_value(universe, channel, channel_intensity)
        else:
            # Single intensity multiplier for all dimmer channels
            if is_pixelbar and has_color_segments:
                # Pixelbar: set master dimmer to full, store uniform multiplier for colour scaling
                for ch_offset in fixture_map.dimmer_channels:
                    universe, channel = fixture_map.get_absolute_address(ch_offset)
                    self.set_dmx_value(universe, channel, int(block.intensity))
                num_segments = max(
                    len(fixture_map.red_channels),
                    len(fixture_map.green_channels),
                    len(fixture_map.blue_channels),
                    len(fixture_map.white_channels),
                    1
                )
                fixture_map._segment_intensities = [result.intensity_multiplier] * num_segments
            else:
                # Regular fixture: apply multiplier to dimmer channels
                final_intensity = int(block.intensity * result.intensity_multiplier)
                for ch_offset in fixture_map.dimmer_channels:
                    universe, channel = fixture_map.get_absolute_address(ch_offset)
                    self.set_dmx_value(universe, channel, final_intensity)

    def _apply_colour_block(self, fixture_map: FixtureChannelMap, block: ColourBlock, current_time: float):
        """Apply colour block to fixture channels."""
        # Check if the dimmer effect stored per-segment intensities for this fixture
        # If so, scale color values per segment accordingly
        segment_intensities = getattr(fixture_map, '_segment_intensities', None)

        # Get base RGB values
        red_value = block.red
        green_value = block.green
        blue_value = block.blue

        # If fixture has no white channel, mix white into RGB
        if not fixture_map.white_channels and block.white > 0:
            red_value = min(255, red_value + block.white)
            green_value = min(255, green_value + block.white)
            blue_value = min(255, blue_value + block.white)

        # Set RGB/RGBW channels
        color_mapping = [
            (fixture_map.red_channels, red_value),
            (fixture_map.green_channels, green_value),
            (fixture_map.blue_channels, blue_value),
            (fixture_map.white_channels, block.white),
            (fixture_map.amber_channels, block.amber),
            (fixture_map.cyan_channels, block.cyan),
            (fixture_map.magenta_channels, block.magenta),
            (fixture_map.yellow_channels, block.yellow),
            (fixture_map.uv_channels, block.uv),
            (fixture_map.lime_channels, block.lime),
        ]

        for channels, value in color_mapping:
            for idx, ch_offset in enumerate(channels):
                # If twinkle intensities exist, scale the color value per segment
                if segment_intensities and idx < len(segment_intensities):
                    scaled_value = int(value * segment_intensities[idx])
                else:
                    scaled_value = int(value)
                universe, channel = fixture_map.get_absolute_address(ch_offset)
                self.set_dmx_value(universe, channel, scaled_value)

        # Set color wheel if fixture has one
        if fixture_map.color_wheel_channels:
            # Check if color mode is Wheel - use stored position directly
            color_mode = getattr(block, 'color_mode', 'RGB')
            if color_mode == 'Wheel':
                # Use the color_wheel_position directly (already a DMX value)
                wheel_value = getattr(block, 'color_wheel_position', 0)
            elif (not fixture_map.red_channels and
                  not fixture_map.green_channels and
                  not fixture_map.blue_channels):
                # No RGB channels, try to map RGB to color wheel
                wheel_value = self._rgb_to_color_wheel(block.red, block.green, block.blue)
            else:
                # Has RGB channels, skip color wheel
                wheel_value = None

            if wheel_value is not None:
                for ch_offset in fixture_map.color_wheel_channels:
                    universe, channel = fixture_map.get_absolute_address(ch_offset)
                    self.set_dmx_value(universe, channel, int(wheel_value))

    def _point_center(self, fixture_map: FixtureChannelMap,
                      point) -> tuple:
        """(center_pan, center_tilt) DMX for a world-space aim point:
        per-fixture IK at the definition's real ranges. Shared by the
        target_point path and the dangling-spot-name fall-through
        (2026-07-16)."""
        fixture = fixture_map.fixture
        group = self.config.groups.get(fixture.group) \
            if fixture.group else None
        mounting, yaw, pitch, roll = \
            fixture.get_effective_orientation(group)
        fixture_z = fixture.get_effective_z(group)
        pan_degrees, tilt_degrees = calculate_pan_tilt(
            fixture_x=fixture.x, fixture_y=fixture.y, fixture_z=fixture_z,
            target_x=point[0], target_y=point[1], target_z=point[2],
            mounting=mounting, yaw=yaw, pitch=pitch, roll=roll,
            pan_range=fixture_map.pan_range,
            tilt_range=fixture_map.tilt_range,
        )
        pan_dmx, tilt_dmx = pan_tilt_to_dmx(
            pan_degrees, tilt_degrees,
            fixture_map.pan_range, fixture_map.tilt_range)
        return float(pan_dmx), float(tilt_dmx)

    def _apply_movement_block(self, fixture_map: FixtureChannelMap, block: MovementBlock, current_time: float,
                               fixture_index: int = 0, total_fixtures: int = 1):
        """Apply movement block to fixture channels with real-time shape calculation.

        Args:
            fixture_map: Channel mapping for this fixture
            block: MovementBlock with effect settings
            current_time: Current playback time in seconds
            fixture_index: This fixture's index within the group (for phase offset)
            total_fixtures: Total fixtures in the group (for phase offset)
        """
        time_in_block = current_time - block.start_time
        block_duration = block.end_time - block.start_time
        pan_min = block.pan_min
        pan_max = block.pan_max
        tilt_min = block.tilt_min
        tilt_max = block.tilt_max

        # Compute timing parameters (shared by both rendering modes)
        speed_multiplier = parse_speed(block.effect_speed)
        bpm = get_bpm(self.song_structure, current_time)

        seconds_per_beat = 60.0 / bpm
        seconds_per_bar = seconds_per_beat * 4
        total_cycles = movement_total_cycles(block_duration, seconds_per_bar, speed_multiplier)

        if block_duration > 0:
            progress = time_in_block / block_duration
        else:
            progress = 0
        t = 2 * math.pi * total_cycles * progress

        # Apply phase offset for t-based shapes
        if block.phase_offset_enabled and total_fixtures > 1:
            phase_offset_radians = block.phase_offset_degrees * math.pi / 180.0
            t = t + (fixture_index * phase_offset_radians)

        # Check for plane-based world-space rendering
        plane = None
        if block.target_plane_name and self._stage_planes:
            plane = self._stage_planes.get(block.target_plane_name)

        if plane:
            # ── World-space plane rendering ──
            # Run shape with normalized center/amplitude to extract offsets
            norm_center = 127.5
            norm_amplitude = 50.0
            ctx = MovementContext(
                t=t, progress=progress, total_cycles=total_cycles,
                center_pan=norm_center, center_tilt=norm_center,
                pan_amplitude=norm_amplitude, tilt_amplitude=norm_amplitude,
                fixture_index=fixture_index, total_fixtures=total_fixtures,
                phase_offset_enabled=block.phase_offset_enabled,
                phase_offset_degrees=block.phase_offset_degrees,
                lissajous_ratio=block.lissajous_ratio,
            )
            shape_fn = MOVEMENT_REGISTRY.get(block.effect_type, MOVEMENT_REGISTRY["static"])
            result = shape_fn(ctx)

            # Extract normalized offsets (-1 to +1)
            if norm_amplitude > 0:
                u_offset = (result.pan - norm_center) / norm_amplitude
                v_offset = (result.tilt - norm_center) / norm_amplitude
            else:
                u_offset = 0.0
                v_offset = 0.0

            # Convert amplitude from DMX-like units to meters on plane
            amplitude_meters = block.pan_amplitude / 20.0

            # Compute world-space target on the plane
            target_x = plane.point[0] + u_offset * amplitude_meters * plane.u_axis[0] + v_offset * amplitude_meters * plane.v_axis[0]
            target_y = plane.point[1] + u_offset * amplitude_meters * plane.u_axis[1] + v_offset * amplitude_meters * plane.v_axis[1]
            target_z = plane.point[2] + u_offset * amplitude_meters * plane.u_axis[2] + v_offset * amplitude_meters * plane.v_axis[2]

            # Convert world target to pan/tilt for this fixture
            fixture = fixture_map.fixture
            group = self.config.groups.get(fixture.group) if fixture.group else None
            mounting, yaw, pitch, roll = fixture.get_effective_orientation(group)
            fixture_z = fixture.get_effective_z(group)

            pan_degrees, tilt_degrees = calculate_pan_tilt(
                fixture_x=fixture.x, fixture_y=fixture.y, fixture_z=fixture_z,
                target_x=target_x, target_y=target_y, target_z=target_z,
                mounting=mounting, yaw=yaw, pitch=pitch, roll=roll,
                pan_range=fixture_map.pan_range,
                tilt_range=fixture_map.tilt_range,
            )
            pan_dmx, tilt_dmx = pan_tilt_to_dmx(
                pan_degrees, tilt_degrees,
                fixture_map.pan_range, fixture_map.tilt_range)

            pan = max(pan_min, min(pan_max, float(pan_dmx)))
            tilt = max(tilt_min, min(tilt_max, float(tilt_dmx)))
        else:
            # ── Standard DMX-space rendering ──
            # Resolve center position (target spot or manual)
            if block.target_spot_name and self.config and hasattr(self.config, 'spots'):
                spot = self.config.spots.get(block.target_spot_name)
                if spot:
                    fixture = fixture_map.fixture
                    group = self.config.groups.get(fixture.group) if fixture.group else None
                    mounting, yaw, pitch, roll = fixture.get_effective_orientation(group)
                    fixture_z = fixture.get_effective_z(group)

                    pan_degrees, tilt_degrees = calculate_pan_tilt(
                        fixture_x=fixture.x, fixture_y=fixture.y, fixture_z=fixture_z,
                        target_x=spot.x, target_y=spot.y, target_z=spot.z,
                        mounting=mounting, yaw=yaw, pitch=pitch, roll=roll,
                        pan_range=fixture_map.pan_range,
                        tilt_range=fixture_map.tilt_range,
                    )
                    pan_dmx, tilt_dmx = pan_tilt_to_dmx(
                        pan_degrees, tilt_degrees,
                        fixture_map.pan_range, fixture_map.tilt_range)

                    if DEBUG_PRINTS:
                        debug_key = f"_spot_debug_{fixture.name}"
                        if not hasattr(self, debug_key):
                            setattr(self, debug_key, True)
                            print(f"[SPOT TARGET] {fixture.name} at ({fixture.x}, {fixture.y}, {fixture_z}) "
                                  f"-> Spot '{block.target_spot_name}' at ({spot.x}, {spot.y}, {spot.z})")
                            print(f"  orientation: mounting={mounting}, yaw={yaw}, pitch={pitch}, roll={roll}")
                            print(f"  calculated: pan={pan_degrees:.1f}°, tilt={tilt_degrees:.1f}°")
                            print(f"  DMX: pan={pan_dmx}, tilt={tilt_dmx}")

                    center_pan = float(pan_dmx)
                    center_tilt = float(tilt_dmx)
                elif getattr(block, 'target_point', None):
                    # Dangling spot NAME (not in this config's spots):
                    # continue down the documented priority chain
                    # (plane > spot > point > manual) instead of
                    # jumping to the raw pan/tilt - a morphed show's
                    # spot names come from rig A, and rig A's manual
                    # values point anywhere but rig B's stage
                    # (2026-07-16 fix).
                    center_pan, center_tilt = self._point_center(
                        fixture_map, block.target_point)
                else:
                    center_pan = block.pan
                    center_tilt = block.tilt
            elif getattr(block, 'target_point', None) and self.config:
                # Ad-hoc world point (v1.5a): a spot without a name,
                # same per-fixture IK at the definition's real ranges.
                center_pan, center_tilt = self._point_center(
                    fixture_map, block.target_point)
            else:
                center_pan = block.pan
                center_tilt = block.tilt

            # Build context and dispatch to shape function
            ctx = MovementContext(
                t=t, progress=progress, total_cycles=total_cycles,
                center_pan=center_pan, center_tilt=center_tilt,
                pan_amplitude=block.pan_amplitude, tilt_amplitude=block.tilt_amplitude,
                fixture_index=fixture_index, total_fixtures=total_fixtures,
                phase_offset_enabled=block.phase_offset_enabled,
                phase_offset_degrees=block.phase_offset_degrees,
                lissajous_ratio=block.lissajous_ratio,
            )

            shape_fn = MOVEMENT_REGISTRY.get(block.effect_type, MOVEMENT_REGISTRY["static"])
            result = shape_fn(ctx)

            pan = max(pan_min, min(pan_max, result.pan))
            tilt = max(tilt_min, min(tilt_max, result.tilt))

        # Apply speed limiting (max degrees/sec)
        if self._max_pan_tilt_speed > 0:
            fixture_key = f"{fixture_map.fixture.universe}_{fixture_map.fixture.address}"
            prev_pan = self._prev_pan.get(fixture_key, pan)
            prev_tilt = self._prev_tilt.get(fixture_key, tilt)

            # Convert degrees/sec to max DMX change per frame (30Hz, 540 degree pan range)
            max_dmx_per_frame = (self._max_pan_tilt_speed / 540.0) * 255.0 / 30.0

            delta_pan = max(-max_dmx_per_frame, min(max_dmx_per_frame, pan - prev_pan))
            delta_tilt = max(-max_dmx_per_frame, min(max_dmx_per_frame, tilt - prev_tilt))

            pan = prev_pan + delta_pan
            tilt = prev_tilt + delta_tilt

            self._prev_pan[fixture_key] = pan
            self._prev_tilt[fixture_key] = tilt

        # Set pan/tilt channels
        for ch_offset in fixture_map.pan_channels:
            universe, channel = fixture_map.get_absolute_address(ch_offset)
            self.set_dmx_value(universe, channel, int(pan))

        for ch_offset in fixture_map.tilt_channels:
            universe, channel = fixture_map.get_absolute_address(ch_offset)
            self.set_dmx_value(universe, channel, int(tilt))

    def _apply_special_block(self, fixture_map: FixtureChannelMap, block: SpecialBlock, current_time: float):
        """Apply special block to fixture channels."""
        # Set gobo
        if fixture_map.gobo_channels:
            # Map gobo_index to DMX value (simple linear mapping)
            gobo_value = min(255, block.gobo_index * 25)
            for ch_offset in fixture_map.gobo_channels:
                universe, channel = fixture_map.get_absolute_address(ch_offset)
                self.set_dmx_value(universe, channel, gobo_value)

        # Set prism
        if fixture_map.prism_channels:
            prism_value = 128 if block.prism_enabled else 0
            for ch_offset in fixture_map.prism_channels:
                universe, channel = fixture_map.get_absolute_address(ch_offset)
                self.set_dmx_value(universe, channel, prism_value)

        # Set focus
        if fixture_map.focus_channels:
            for ch_offset in fixture_map.focus_channels:
                universe, channel = fixture_map.get_absolute_address(ch_offset)
                self.set_dmx_value(universe, channel, int(block.focus))

        # Set zoom
        if fixture_map.zoom_channels:
            for ch_offset in fixture_map.zoom_channels:
                universe, channel = fixture_map.get_absolute_address(ch_offset)
                self.set_dmx_value(universe, channel, int(block.zoom))

    def _rgb_to_color_wheel(self, r: float, g: float, b: float) -> int:
        return rgb_to_color_wheel(r, g, b)
