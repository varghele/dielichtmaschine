# config/models.py

from dataclasses import dataclass, field, asdict, InitVar
from typing import Dict, List, Optional, Tuple
import yaml
import xml.etree.ElementTree as ET
import os
import uuid


@dataclass
class FixtureMode:
    name: str
    channels: int


@dataclass
class Fixture:
    universe: int
    address: int
    manufacturer: str
    model: str
    name: str
    current_mode: str
    available_modes: List[FixtureMode]

    # Group membership - the source of truth (multi-group plan stage 1,
    # docs/multi-group-fixtures-plan.md). Order = the order the user
    # added them; groups[0] is the PRIMARY group ("first group wins"):
    # data color, orientation defaults, lighting role and export
    # intensity all come from it. Empty list = ungrouped.
    groups: List[str] = field(default_factory=list)

    # Legacy single-group constructor keyword / YAML key. Consumed by
    # __post_init__: Fixture(group="X") becomes groups=["X"] ("" -> [])
    # unless `groups` was given too, in which case `groups` wins and
    # this is ignored (dual-written files carry both). Reading/writing
    # `fixture.group` goes through the compat property attached below
    # the class (getter = primary group, setter REPLACES the list).
    group: InitVar[Optional[str]] = None

    type: str = "PAR"  # Default type if none specified
    x: float = 0.0     # X position in meters
    y: float = 0.0     # Y position in meters
    z: float = 0.0     # Z height in meters

    # Orientation using Euler angles (degrees)
    # Convention: Yaw (Z) -> Pitch (Y) -> Roll (X)
    mounting: str = "hanging"  # "hanging", "standing", "wall_left", "wall_right", "wall_back", "wall_front"
    yaw: float = 0.0           # Rotation around world Z (degrees, -180 to 180)
    pitch: float = 0.0         # Rotation around local Y after yaw (degrees, -90 to 90)
    roll: float = 0.0          # Rotation around local X after pitch (degrees, -180 to 180)

    # Override flags (True = use own value, False = use group default)
    orientation_uses_group_default: bool = True
    z_uses_group_default: bool = True

    # Stage layer assignment ("" = no layer). Layers are named Z-planes
    # (ground stack / mid-truss / top-truss); see StageLayer.
    layer: str = ""

    # Truss docking: element_id of the truss StageElement this fixture
    # hangs on ("" = not docked). A docked fixture lives on the truss's
    # layer and follows the truss when it moves on the plan.
    docked_to: str = ""

    # Definition provenance (GDTF plan Phase 2). "qxf" or "gdtf"; absent
    # in pre-GDTF configs, so the default keeps them loading unchanged.
    # The GDTF FixtureTypeID GUID enables exact re-resolution and GDTF
    # Share update checks; None for .qxf-sourced fixtures.
    definition_source: str = "qxf"
    gdtf_fixture_type_id: Optional[str] = None

    def __post_init__(self, group: Optional[str]):
        # Defensive: a YAML `groups:` key that is present but null.
        if self.groups is None:
            self.groups = []
        # Legacy migration: single `group` string -> one-element list
        # ("" -> stays ungrouped). An explicit non-empty `groups` wins.
        if not self.groups and group:
            self.groups = [group]

    def get_effective_orientation(self, group: Optional['FixtureGroup'] = None) -> tuple:
        """
        Get effective orientation values, considering group defaults if applicable.

        Returns:
            tuple: (mounting, yaw, pitch, roll)
        """
        if self.orientation_uses_group_default and group is not None:
            return (
                group.default_mounting,
                group.default_yaw,
                group.default_pitch,
                group.default_roll
            )
        return (self.mounting, self.yaw, self.pitch, self.roll)

    def get_effective_z(self, group: Optional['FixtureGroup'] = None) -> float:
        """Get effective Z height, considering group default if applicable."""
        if self.z_uses_group_default and group is not None:
            return group.default_z_height
        return self.z


def _fixture_group_get(self) -> str:
    """Compat: the primary group (groups[0]), or "" when ungrouped."""
    return self.groups[0] if self.groups else ""


def _fixture_group_set(self, value: str) -> None:
    """Compat: REPLACES the whole membership list with [value] ("" clears).

    Existing single-group callers keep their replace semantics; multi-group
    membership editing goes through `groups` directly (plan stage 2)."""
    self.groups = [value] if value else []


# Attached after the class body: the InitVar's class-level default (None)
# must still be None when @dataclass generates __init__; a property named
# `group` inside the body would be picked up as that default. Instances
# never store a `group` attribute (InitVar), so this data descriptor
# handles every read/write of `fixture.group`.
Fixture.group = property(_fixture_group_get, _fixture_group_set)


def fixture_asdict(fixture: Fixture) -> dict:
    """asdict plus the legacy `group` key (= groups[0] or "").

    Dual-write: saved configs carry `groups` (the source of truth) AND
    the old single `group` string for one release so older builds still
    open the file. Dropping the legacy key is stage 5 of
    docs/multi-group-fixtures-plan.md."""
    d = asdict(fixture)
    d['group'] = fixture.group
    return d


@dataclass
class Spot:
    name: str
    x: float = 0.0     # X position in meters
    y: float = 0.0     # Y position in meters
    z: float = 0.0     # Z height in meters (for 3D targeting)


@dataclass
class StageLayer:
    """A named horizontal Z-plane of the rig (ground stack, mid-truss, ...).

    Fixtures opt in via Fixture.layer. Assigning a fixture to a layer snaps
    its Z to z_height; a layer with visible=False is omitted from the 2D
    stage plot and every 3D preview (fixtures on it still exist, patch, and
    export normally).
    """
    name: str
    z_height: float = 3.0   # nominal plane height in meters
    visible: bool = True


@dataclass
class StageElement:
    """A static, non-DMX object on the stage plan (riser, wedge, amp,
    FOH desk, truss shape, ...).

    ``kind`` keys into the stageplot symbol set (resources/stageplot/
    <kind>.svg, catalog in utils/stage_element_catalog.py). Purely
    visual/planning data: elements render on the 2D stage plan and the
    printable stage plot, participate in the layer system like
    fixtures, and carry no DMX meaning. Truss docking (fixtures
    attached to trusses) is future work; a truss placed today is just
    a static shape.
    """
    kind: str
    x: float = 0.0          # stage coords, meters, element center
    y: float = 0.0
    rotation: float = 0.0   # degrees, clockwise in the top view
    width: float = 1.0      # footprint in meters
    depth: float = 1.0
    label: str = ""         # optional user caption on the plan
    layer: str = ""         # StageLayer name; "" = unassigned.
    #   For TRUSS kinds this is the layer the truss DEFINES (created
    #   when the truss is placed): docked fixtures join it and the
    #   layer's z_height is the truss hang height.
    # Stable identity for docking references (Fixture.docked_to).
    element_id: str = ""


@dataclass
class StagePlane:
    """A face of the stage bounding cuboid for movement targeting."""
    name: str                                    # "Floor", "Ceiling", "Front", "Back", "Left", "Right"
    point: Tuple[float, float, float]            # Center of the face (meters)
    normal: Tuple[float, float, float]           # Inward-facing normal
    u_axis: Tuple[float, float, float]           # Tangent axis (pan maps to)
    v_axis: Tuple[float, float, float]           # Tangent axis (tilt maps to)


@dataclass
class FixtureGroup:
    name: str
    fixtures: List[Fixture]
    color: str = '#808080'  # Default color for the group
    capabilities: Optional['FixtureGroupCapabilities'] = None  # Auto-detected sublane capabilities

    # Group-level defaults for orientation
    default_mounting: str = "hanging"
    default_yaw: float = 0.0
    default_pitch: float = 0.0
    default_roll: float = 0.0
    default_z_height: float = 3.0  # Default height in meters

    # User-assigned lighting role for autogen activation decisions
    lighting_role: str = ""  # "backbone", "accent", "ambient", "movement", "effect"

    # Max DMX intensity for export (0-255), used for brightness balancing across groups
    export_intensity: int = 255

    # Deterministic topology (v1.5 morphing prerequisite, decided
    # 2026-07-15): ``fixtures`` IS the canonical order every consumer
    # reads (Group:N targets, chase direction, morph routing).
    # ``fixture_order`` persists that order as a name list so it
    # survives fixture-list reshuffles; groups loaded without one
    # snapshot their derived order (zero behavior change for existing
    # configs). ``order_mode`` records how the order is maintained:
    # "manual" (the list as-is, user-arranged) or "spatial" (stage X,
    # then Y - the default for NEWLY created groups).
    fixture_order: List[str] = field(default_factory=list)
    order_mode: str = "manual"  # "manual" | "spatial"

    def apply_fixture_order(self) -> None:
        """Bring ``fixtures`` into the canonical order.

        Spatial mode re-derives from geometry; manual mode follows
        ``fixture_order`` (unknown names keep their current relative
        order, appended after the ordered ones). Always re-snapshots
        ``fixture_order`` to the resulting membership."""
        if self.order_mode == "spatial":
            self.fixtures.sort(key=lambda f: (f.x, f.y, f.name))
        elif self.fixture_order:
            index = {name: i for i, name in enumerate(self.fixture_order)}
            self.fixtures.sort(
                key=lambda f: index.get(f.name, len(index)))
        self.fixture_order = [f.name for f in self.fixtures]

    def sort_spatially(self) -> None:
        """Switch the group to spatial order (stage X, then Y)."""
        self.order_mode = "spatial"
        self.apply_fixture_order()

    def set_manual_order(self, names: List[str]) -> None:
        """Pin an explicit order (switches the group to manual mode)."""
        self.order_mode = "manual"
        self.fixture_order = list(names)
        self.apply_fixture_order()


@dataclass
class FixtureGroupCapabilities:
    """Capabilities of a fixture group, determining which sublanes to display."""
    has_dimmer: bool = False
    has_colour: bool = False
    has_movement: bool = False
    has_special: bool = False

    def to_dict(self) -> Dict:
        return {
            "has_dimmer": self.has_dimmer,
            "has_colour": self.has_colour,
            "has_movement": self.has_movement,
            "has_special": self.has_special
        }

    @classmethod
    def from_dict(cls, data: Dict) -> 'FixtureGroupCapabilities':
        return cls(
            has_dimmer=data.get("has_dimmer", False),
            has_colour=data.get("has_colour", False),
            has_movement=data.get("has_movement", False),
            has_special=data.get("has_special", False)
        )


@dataclass
class DimmerBlock:
    """Dimmer sublane block - controls intensity and shutter effects."""
    start_time: float
    end_time: float
    intensity: float = 255.0  # 0-255
    strobe_speed: float = 0.0  # 0 = no strobe, >0 = strobe speed
    iris: float = 255.0  # 0-255, if applicable
    effect_type: str = "static"  # Rudiment effect type
    effect_speed: str = "1"  # Speed multiplier: "1/4", "1/2", "1", "2", "4", etc.
    direction: str = "down"  # Direction: "down"/"up" (waterfall), "in"/"out" (fade)
    chase_scope: str = "fixture"  # Chase scope: "fixture" (per-fixture) or "global" (cross-fixture)
    phase_offset_per_fixture: bool = False  # Per-fixture phase spread (pulse)
    build_fraction: float = 0.7  # Build portion of cascade (0.0-1.0)
    modified: bool = False  # True if user edited this block after riff insertion

    def to_dict(self) -> Dict:
        d = {
            "start_time": self.start_time,
            "end_time": self.end_time,
            "intensity": self.intensity,
            "strobe_speed": self.strobe_speed,
            "iris": self.iris,
            "effect_type": self.effect_type,
            "effect_speed": self.effect_speed,
            "modified": self.modified,
        }
        # Only serialize non-default values to keep files clean
        if self.direction != "down":
            d["direction"] = self.direction
        if self.chase_scope != "fixture":
            d["chase_scope"] = self.chase_scope
        if self.phase_offset_per_fixture:
            d["phase_offset_per_fixture"] = self.phase_offset_per_fixture
        if self.build_fraction != 0.7:
            d["build_fraction"] = self.build_fraction
        return d

    @classmethod
    def from_dict(cls, data: Dict) -> 'DimmerBlock':
        return cls(
            start_time=data.get("start_time", 0.0),
            end_time=data.get("end_time", 0.0),
            intensity=data.get("intensity", 255.0),
            strobe_speed=data.get("strobe_speed", 0.0),
            iris=data.get("iris", 255.0),
            effect_type=data.get("effect_type", "static"),
            effect_speed=data.get("effect_speed", "1"),
            direction=data.get("direction", "down"),
            chase_scope=data.get("chase_scope", "fixture"),
            phase_offset_per_fixture=data.get("phase_offset_per_fixture", False),
            build_fraction=data.get("build_fraction", 0.7),
            modified=data.get("modified", False),
        )


@dataclass
class ColourBlock:
    """Colour sublane block - controls color parameters."""
    start_time: float
    end_time: float
    color_mode: str = "RGB"  # "RGB", "CMY", "HSV", "Wheel"

    # RGB/CMY/RGBW values (0-255)
    red: float = 0.0
    green: float = 0.0
    blue: float = 0.0
    white: float = 0.0
    amber: float = 0.0
    cyan: float = 0.0
    magenta: float = 0.0
    yellow: float = 0.0
    uv: float = 0.0
    lime: float = 0.0

    # HSV values
    hue: float = 0.0  # 0-360
    saturation: float = 0.0  # 0-100
    value: float = 0.0  # 0-100

    # Color wheel
    color_wheel_position: int = 0  # Wheel position

    modified: bool = False  # True if user edited this block after riff insertion

    # Palette role (v1.5, decided 2026-07-15): the block's INTENT
    # ("primary", "accent", ...). The literal channel values above stay
    # authoritative for every consumer (playback, export, visualizer) -
    # the role is metadata that Song.apply_palette() and the morph
    # compile re-resolve into literals. "" = literal-only block.
    palette_role: str = ""

    def to_dict(self) -> Dict:
        data = {
            "start_time": self.start_time,
            "end_time": self.end_time,
            "color_mode": self.color_mode,
            "red": self.red,
            "green": self.green,
            "blue": self.blue,
            "white": self.white,
            "amber": self.amber,
            "cyan": self.cyan,
            "magenta": self.magenta,
            "yellow": self.yellow,
            "uv": self.uv,
            "lime": self.lime,
            "hue": self.hue,
            "saturation": self.saturation,
            "value": self.value,
            "color_wheel_position": self.color_wheel_position,
            "modified": self.modified
        }
        if self.palette_role:
            data["palette_role"] = self.palette_role
        return data

    @classmethod
    def from_dict(cls, data: Dict) -> 'ColourBlock':
        return cls(
            start_time=data.get("start_time", 0.0),
            end_time=data.get("end_time", 0.0),
            color_mode=data.get("color_mode", "RGB"),
            red=data.get("red", 0.0),
            green=data.get("green", 0.0),
            blue=data.get("blue", 0.0),
            white=data.get("white", 0.0),
            amber=data.get("amber", 0.0),
            cyan=data.get("cyan", 0.0),
            magenta=data.get("magenta", 0.0),
            yellow=data.get("yellow", 0.0),
            uv=data.get("uv", 0.0),
            lime=data.get("lime", 0.0),
            hue=data.get("hue", 0.0),
            saturation=data.get("saturation", 0.0),
            value=data.get("value", 0.0),
            color_wheel_position=data.get("color_wheel_position", 0),
            modified=data.get("modified", False),
            palette_role=data.get("palette_role", "")
        )


@dataclass
class MovementBlock:
    """Movement sublane block - controls pan, tilt, and positioning.

    Supports both static positioning and dynamic shape effects (circle, diamond, etc.).
    When effect_type is 'static', pan/tilt define the exact position.
    When effect_type is a shape, pan/tilt define the center, and the shape is traced
    within the bounds defined by pan_min/pan_max and tilt_min/tilt_max.
    """
    start_time: float
    end_time: float
    pan: float = 127.5  # 0-255 (center position for shapes, or static position)
    tilt: float = 127.5  # 0-255 (center position for shapes, or static position)
    pan_fine: float = 0.0  # Fine adjustment
    tilt_fine: float = 0.0  # Fine adjustment
    speed: float = 255.0  # Movement speed (DMX)
    interpolate_from_previous: bool = True  # Gradual transition from previous block

    # Effect type and speed (similar to DimmerBlock)
    effect_type: str = "static"  # "static", "circle", "diamond", "lissajous", "figure_8", "square", "triangle", "random", "bounce"
    effect_speed: str = "1"  # Speed multiplier: "1/4", "1/2", "1", "2", "4"

    # Boundary limits (hard limits the effect cannot exceed)
    pan_min: float = 0.0  # Minimum pan value (0-255)
    pan_max: float = 255.0  # Maximum pan value (0-255)
    tilt_min: float = 0.0  # Minimum tilt value (0-255)
    tilt_max: float = 255.0  # Maximum tilt value (0-255)

    # Amplitude (size of the effect within the bounds)
    pan_amplitude: float = 50.0  # How far pan moves from center (0-127.5)
    tilt_amplitude: float = 50.0  # How far tilt moves from center (0-127.5)

    # Lissajous-specific parameter
    lissajous_ratio: str = "1:2"  # Frequency ratio for lissajous curves: "1:2", "2:3", "3:4", "3:2", "4:3"

    # Phase offset for multi-fixture effects
    phase_offset_enabled: bool = False  # Enable phase offset between fixtures
    phase_offset_degrees: float = 0.0  # Phase offset in degrees (0-360)

    # Target spot for automatic pan/tilt calculation
    target_spot_name: Optional[str] = None  # Name of spot to point at (None = use manual pan/tilt)

    # Target plane for world-space movement (takes priority over target_spot_name)
    target_plane_name: Optional[str] = None  # Name of stage plane ("Floor", "Front", etc.)

    # Ad-hoc world-space aim point in stage coordinates (x, y, z metres)
    # - v1.5a focus geometry. Resolution priority: plane > spot > point
    # > manual pan/tilt. Unlike a named spot this needs no entry in
    # Configuration.spots (click-to-aim writes here); like a spot, the
    # per-fixture pan/tilt resolve from geometry at playback/export.
    target_point: Optional[List[float]] = None

    modified: bool = False  # True if user edited this block after riff insertion

    def to_dict(self) -> Dict:
        return {
            "start_time": self.start_time,
            "end_time": self.end_time,
            "pan": self.pan,
            "tilt": self.tilt,
            "pan_fine": self.pan_fine,
            "tilt_fine": self.tilt_fine,
            "speed": self.speed,
            "interpolate_from_previous": self.interpolate_from_previous,
            "effect_type": self.effect_type,
            "effect_speed": self.effect_speed,
            "pan_min": self.pan_min,
            "pan_max": self.pan_max,
            "tilt_min": self.tilt_min,
            "tilt_max": self.tilt_max,
            "pan_amplitude": self.pan_amplitude,
            "tilt_amplitude": self.tilt_amplitude,
            "lissajous_ratio": self.lissajous_ratio,
            "phase_offset_enabled": self.phase_offset_enabled,
            "phase_offset_degrees": self.phase_offset_degrees,
            "target_spot_name": self.target_spot_name,
            "target_plane_name": self.target_plane_name,
            "target_point": (list(self.target_point)
                             if self.target_point else None),
            "modified": self.modified
        }

    @classmethod
    def from_dict(cls, data: Dict) -> 'MovementBlock':
        return cls(
            start_time=data.get("start_time", 0.0),
            end_time=data.get("end_time", 0.0),
            pan=data.get("pan", 127.5),
            tilt=data.get("tilt", 127.5),
            pan_fine=data.get("pan_fine", 0.0),
            tilt_fine=data.get("tilt_fine", 0.0),
            speed=data.get("speed", 255.0),
            interpolate_from_previous=data.get("interpolate_from_previous", True),
            effect_type=data.get("effect_type", "static"),
            effect_speed=data.get("effect_speed", "1"),
            pan_min=data.get("pan_min", 0.0),
            pan_max=data.get("pan_max", 255.0),
            tilt_min=data.get("tilt_min", 0.0),
            tilt_max=data.get("tilt_max", 255.0),
            pan_amplitude=data.get("pan_amplitude", 50.0),
            tilt_amplitude=data.get("tilt_amplitude", 50.0),
            lissajous_ratio=data.get("lissajous_ratio", "1:2"),
            phase_offset_enabled=data.get("phase_offset_enabled", False),
            phase_offset_degrees=data.get("phase_offset_degrees", 0.0),
            target_spot_name=data.get("target_spot_name"),
            target_plane_name=data.get("target_plane_name"),
            target_point=(list(data["target_point"])
                          if data.get("target_point") else None),
            modified=data.get("modified", False)
        )


@dataclass
class SpecialBlock:
    """Special sublane block - controls gobo, beam, and prism effects."""
    start_time: float
    end_time: float
    gobo_index: int = 0  # Gobo selection
    gobo_rotation: float = 0.0  # Gobo rotation speed/position
    focus: float = 127.5  # Beam focus (0-255)
    zoom: float = 127.5  # Beam zoom (0-255)
    prism_enabled: bool = False  # Prism on/off
    prism_rotation: float = 0.0  # Prism rotation speed
    modified: bool = False  # True if user edited this block after riff insertion

    def to_dict(self) -> Dict:
        return {
            "start_time": self.start_time,
            "end_time": self.end_time,
            "gobo_index": self.gobo_index,
            "gobo_rotation": self.gobo_rotation,
            "focus": self.focus,
            "zoom": self.zoom,
            "prism_enabled": self.prism_enabled,
            "prism_rotation": self.prism_rotation,
            "modified": self.modified
        }

    @classmethod
    def from_dict(cls, data: Dict) -> 'SpecialBlock':
        return cls(
            start_time=data.get("start_time", 0.0),
            end_time=data.get("end_time", 0.0),
            gobo_index=data.get("gobo_index", 0),
            gobo_rotation=data.get("gobo_rotation", 0.0),
            focus=data.get("focus", 127.5),
            zoom=data.get("zoom", 127.5),
            prism_enabled=data.get("prism_enabled", False),
            prism_rotation=data.get("prism_rotation", 0.0),
            modified=data.get("modified", False)
        )


# =============================================================================
# RIFF SYSTEM - Beat-based reusable effect patterns
# =============================================================================

@dataclass
class RiffDimmerBlock:
    """Dimmer block within a riff - timing is in beats, not seconds."""
    start_beat: float  # e.g., 0.0 = start of riff
    end_beat: float    # e.g., 4.0 = ends at beat 4

    # Parameters (same as DimmerBlock)
    intensity: float = 255.0
    strobe_speed: float = 0.0
    iris: float = 255.0
    effect_type: str = "static"
    effect_speed: str = "1"

    def to_dict(self) -> Dict:
        return {
            "start_beat": self.start_beat,
            "end_beat": self.end_beat,
            "intensity": self.intensity,
            "strobe_speed": self.strobe_speed,
            "iris": self.iris,
            "effect_type": self.effect_type,
            "effect_speed": self.effect_speed
        }

    @classmethod
    def from_dict(cls, data: Dict) -> 'RiffDimmerBlock':
        return cls(
            start_beat=data.get("start_beat", 0.0),
            end_beat=data.get("end_beat", 0.0),
            intensity=data.get("intensity", 255.0),
            strobe_speed=data.get("strobe_speed", 0.0),
            iris=data.get("iris", 255.0),
            effect_type=data.get("effect_type", "static"),
            effect_speed=data.get("effect_speed", "1")
        )


@dataclass
class RiffColourBlock:
    """Colour block within a riff - timing is in beats."""
    start_beat: float
    end_beat: float

    # Parameters (same as ColourBlock)
    color_mode: str = "RGB"
    red: float = 255.0
    green: float = 255.0
    blue: float = 255.0
    white: float = 0.0
    amber: float = 0.0
    cyan: float = 0.0
    magenta: float = 0.0
    yellow: float = 0.0
    uv: float = 0.0
    lime: float = 0.0
    hue: float = 0.0
    saturation: float = 0.0
    value: float = 0.0
    color_wheel_position: int = 0

    def to_dict(self) -> Dict:
        return {
            "start_beat": self.start_beat,
            "end_beat": self.end_beat,
            "color_mode": self.color_mode,
            "red": self.red,
            "green": self.green,
            "blue": self.blue,
            "white": self.white,
            "amber": self.amber,
            "cyan": self.cyan,
            "magenta": self.magenta,
            "yellow": self.yellow,
            "uv": self.uv,
            "lime": self.lime,
            "hue": self.hue,
            "saturation": self.saturation,
            "value": self.value,
            "color_wheel_position": self.color_wheel_position
        }

    @classmethod
    def from_dict(cls, data: Dict) -> 'RiffColourBlock':
        return cls(
            start_beat=data.get("start_beat", 0.0),
            end_beat=data.get("end_beat", 0.0),
            color_mode=data.get("color_mode", "RGB"),
            red=data.get("red", 255.0),
            green=data.get("green", 255.0),
            blue=data.get("blue", 255.0),
            white=data.get("white", 0.0),
            amber=data.get("amber", 0.0),
            cyan=data.get("cyan", 0.0),
            magenta=data.get("magenta", 0.0),
            yellow=data.get("yellow", 0.0),
            uv=data.get("uv", 0.0),
            lime=data.get("lime", 0.0),
            hue=data.get("hue", 0.0),
            saturation=data.get("saturation", 0.0),
            value=data.get("value", 0.0),
            color_wheel_position=data.get("color_wheel_position", 0)
        )


@dataclass
class RiffMovementBlock:
    """Movement block within a riff - timing is in beats."""
    start_beat: float
    end_beat: float

    # Parameters (same as MovementBlock)
    pan: float = 127.5
    tilt: float = 127.5
    pan_fine: float = 0.0
    tilt_fine: float = 0.0
    speed: float = 255.0
    interpolate_from_previous: bool = True
    effect_type: str = "static"
    effect_speed: str = "1"
    pan_min: float = 0.0
    pan_max: float = 255.0
    tilt_min: float = 0.0
    tilt_max: float = 255.0
    pan_amplitude: float = 50.0
    tilt_amplitude: float = 50.0
    lissajous_ratio: str = "1:2"
    phase_offset_enabled: bool = False
    phase_offset_degrees: float = 0.0

    def to_dict(self) -> Dict:
        return {
            "start_beat": self.start_beat,
            "end_beat": self.end_beat,
            "pan": self.pan,
            "tilt": self.tilt,
            "pan_fine": self.pan_fine,
            "tilt_fine": self.tilt_fine,
            "speed": self.speed,
            "interpolate_from_previous": self.interpolate_from_previous,
            "effect_type": self.effect_type,
            "effect_speed": self.effect_speed,
            "pan_min": self.pan_min,
            "pan_max": self.pan_max,
            "tilt_min": self.tilt_min,
            "tilt_max": self.tilt_max,
            "pan_amplitude": self.pan_amplitude,
            "tilt_amplitude": self.tilt_amplitude,
            "lissajous_ratio": self.lissajous_ratio,
            "phase_offset_enabled": self.phase_offset_enabled,
            "phase_offset_degrees": self.phase_offset_degrees
        }

    @classmethod
    def from_dict(cls, data: Dict) -> 'RiffMovementBlock':
        return cls(
            start_beat=data.get("start_beat", 0.0),
            end_beat=data.get("end_beat", 0.0),
            pan=data.get("pan", 127.5),
            tilt=data.get("tilt", 127.5),
            pan_fine=data.get("pan_fine", 0.0),
            tilt_fine=data.get("tilt_fine", 0.0),
            speed=data.get("speed", 255.0),
            interpolate_from_previous=data.get("interpolate_from_previous", True),
            effect_type=data.get("effect_type", "static"),
            effect_speed=data.get("effect_speed", "1"),
            pan_min=data.get("pan_min", 0.0),
            pan_max=data.get("pan_max", 255.0),
            tilt_min=data.get("tilt_min", 0.0),
            tilt_max=data.get("tilt_max", 255.0),
            pan_amplitude=data.get("pan_amplitude", 50.0),
            tilt_amplitude=data.get("tilt_amplitude", 50.0),
            lissajous_ratio=data.get("lissajous_ratio", "1:2"),
            phase_offset_enabled=data.get("phase_offset_enabled", False),
            phase_offset_degrees=data.get("phase_offset_degrees", 0.0)
        )


@dataclass
class RiffSpecialBlock:
    """Special block within a riff - timing is in beats."""
    start_beat: float
    end_beat: float

    # Parameters (same as SpecialBlock)
    gobo_index: int = 0
    gobo_rotation: float = 0.0
    focus: float = 127.5
    zoom: float = 127.5
    prism_enabled: bool = False
    prism_rotation: float = 0.0

    def to_dict(self) -> Dict:
        return {
            "start_beat": self.start_beat,
            "end_beat": self.end_beat,
            "gobo_index": self.gobo_index,
            "gobo_rotation": self.gobo_rotation,
            "focus": self.focus,
            "zoom": self.zoom,
            "prism_enabled": self.prism_enabled,
            "prism_rotation": self.prism_rotation
        }

    @classmethod
    def from_dict(cls, data: Dict) -> 'RiffSpecialBlock':
        return cls(
            start_beat=data.get("start_beat", 0.0),
            end_beat=data.get("end_beat", 0.0),
            gobo_index=data.get("gobo_index", 0),
            gobo_rotation=data.get("gobo_rotation", 0.0),
            focus=data.get("focus", 127.5),
            zoom=data.get("zoom", 127.5),
            prism_enabled=data.get("prism_enabled", False),
            prism_rotation=data.get("prism_rotation", 0.0)
        )


@dataclass
class Scene:
    """A whole-rig look that spans multiple fixture groups.

    Unlike a :class:`Riff` (a per-group, beat-based pattern applied to the
    current selection), a Scene is a static full-rig snapshot across
    several groups, not tied to any single selection. Scenes are
    predefined and populated later; this is the data shell plus JSON
    round-trip, no engine resolve yet.
    """
    name: str
    category: str = "general"
    description: str = ""
    # Optional display swatch hex (e.g. "#F0562E"); empty means no chip.
    color: str = ""
    # The fixture groups this look spans.
    groups: List[str] = field(default_factory=list)
    # Metadata.
    tags: List[str] = field(default_factory=list)
    author: str = ""
    version: str = "1.0"

    def to_dict(self) -> Dict:
        """Serialize to dictionary for JSON storage."""
        return {
            "name": self.name,
            "category": self.category,
            "description": self.description,
            "color": self.color,
            "groups": self.groups,
            "tags": self.tags,
            "author": self.author,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> 'Scene':
        """Deserialize from dictionary."""
        return cls(
            name=data.get("name", ""),
            category=data.get("category", "general"),
            description=data.get("description", ""),
            color=data.get("color", ""),
            groups=data.get("groups", []),
            tags=data.get("tags", []),
            author=data.get("author", ""),
            version=data.get("version", "1.0"),
        )


@dataclass
class Riff:
    """A reusable pattern of sublane blocks measured in beats."""
    name: str
    category: str = "general"
    description: str = ""

    length_beats: float = 4.0
    signature: str = "4/4"

    # Fixture compatibility - empty list means universal
    fixture_types: List[str] = field(default_factory=list)

    # Content - empty lists mean "no effect on this sublane"
    dimmer_blocks: List[RiffDimmerBlock] = field(default_factory=list)
    colour_blocks: List[RiffColourBlock] = field(default_factory=list)
    movement_blocks: List[RiffMovementBlock] = field(default_factory=list)
    special_blocks: List[RiffSpecialBlock] = field(default_factory=list)

    # Metadata
    tags: List[str] = field(default_factory=list)
    author: str = ""
    version: str = "1.0"

    def to_dict(self) -> Dict:
        """Serialize to dictionary for JSON storage."""
        return {
            "name": self.name,
            "category": self.category,
            "description": self.description,
            "length_beats": self.length_beats,
            "signature": self.signature,
            "fixture_types": self.fixture_types,
            "dimmer_blocks": [b.to_dict() for b in self.dimmer_blocks],
            "colour_blocks": [b.to_dict() for b in self.colour_blocks],
            "movement_blocks": [b.to_dict() for b in self.movement_blocks],
            "special_blocks": [b.to_dict() for b in self.special_blocks],
            "tags": self.tags,
            "author": self.author,
            "version": self.version
        }

    @classmethod
    def from_dict(cls, data: Dict) -> 'Riff':
        """Deserialize from dictionary."""
        riff = cls(
            name=data.get("name", ""),
            category=data.get("category", "general"),
            description=data.get("description", ""),
            length_beats=data.get("length_beats", 4.0),
            signature=data.get("signature", "4/4"),
            fixture_types=data.get("fixture_types", []),
            tags=data.get("tags", []),
            author=data.get("author", ""),
            version=data.get("version", "1.0")
        )

        # Load sublane blocks
        riff.dimmer_blocks = [
            RiffDimmerBlock.from_dict(b) for b in data.get("dimmer_blocks", [])
        ]
        riff.colour_blocks = [
            RiffColourBlock.from_dict(b) for b in data.get("colour_blocks", [])
        ]
        riff.movement_blocks = [
            RiffMovementBlock.from_dict(b) for b in data.get("movement_blocks", [])
        ]
        riff.special_blocks = [
            RiffSpecialBlock.from_dict(b) for b in data.get("special_blocks", [])
        ]

        return riff

    def is_compatible_with(self, fixture_group: 'FixtureGroup') -> tuple:
        """Check if riff can be used with fixture group.

        Compatibility is checked at the :class:`Chassis` level — both
        the riff's required ``fixture_types`` and the group's fixtures
        are normalised to Chassis enum values before intersecting.

        ``fixture_types`` entries may be either:
        - Legacy 6-string types (``"MH"``, ``"PAR"``, ``"BAR"``,
          ``"PIXELBAR"``, ``"SUNSTRIP"``, ``"WASH"``) — for backward
          compatibility with existing riff JSON.
        - :class:`Chassis` enum names (``"moving_yoke"``, ``"par"``,
          ``"bar"``, ``"panel"``, ``"scanner"``, ``"effect"``,
          ``"particle"``, ``"laser"``, ``"other"``) — for new riffs
          targeting capability archetypes the legacy enum can't express.
        Case-insensitive on both sides.

        Returns:
            tuple: (is_compatible: bool, reason_if_not: str)
        """
        # Universal riffs are compatible with everything
        if not self.fixture_types:
            return (True, "")

        if fixture_group.fixtures:
            from utils.fixture_capabilities import Chassis, chassis_from_legacy_type

            group_chassis = {
                chassis_from_legacy_type(f.type) for f in fixture_group.fixtures
            }
            required: set = set()
            for entry in self.fixture_types:
                if not entry:
                    continue
                try:
                    required.add(Chassis(entry.lower()))
                except ValueError:
                    required.add(chassis_from_legacy_type(entry))

            if group_chassis & required:
                return (True, "")
            return (False, f"Requires fixture types: {', '.join(self.fixture_types)}")

        return (False, "No fixtures in group")

    def to_light_block(self, start_time: float, song_structure) -> 'LightBlock':
        """Convert riff to absolute-timed LightBlock.

        Uses song_structure.get_bpm_at_time() for each beat to handle
        BPM transitions correctly. The riff "stretches" to match the grid.

        Args:
            start_time: Absolute time in seconds where riff starts
            song_structure: SongStructure object with get_bpm_at_time() method

        Returns:
            LightBlock with absolute timing
        """
        def beat_to_time(beat_offset: float) -> float:
            """Convert a beat offset from riff start to absolute time.

            For efficiency, check if BPM is constant first.
            If not, sample at quarter-beat intervals for accuracy.
            """
            if beat_offset <= 0:
                return start_time

            # Check if BPM is constant across the riff duration
            # (optimization for the common case)
            start_bpm = song_structure.get_bpm_at_time(start_time)
            # Estimate end time assuming constant BPM
            estimated_end = start_time + (self.length_beats * 60.0 / start_bpm)
            end_bpm = song_structure.get_bpm_at_time(estimated_end)

            if abs(start_bpm - end_bpm) < 0.01:
                # BPM is constant, use simple calculation
                seconds_per_beat = 60.0 / start_bpm
                return start_time + (beat_offset * seconds_per_beat)

            # BPM varies - sample at quarter-beat intervals
            current_time = start_time
            remaining_beats = beat_offset
            sample_size = 0.25  # Quarter-beat samples for accuracy

            while remaining_beats > 0:
                bpm = song_structure.get_bpm_at_time(current_time)
                seconds_per_beat = 60.0 / bpm

                beats_this_sample = min(remaining_beats, sample_size)
                time_this_sample = beats_this_sample * seconds_per_beat

                current_time += time_this_sample
                remaining_beats -= beats_this_sample

            return current_time

        # Convert dimmer blocks
        dimmer_blocks = []
        for rb in self.dimmer_blocks:
            dimmer_blocks.append(DimmerBlock(
                start_time=beat_to_time(rb.start_beat),
                end_time=beat_to_time(rb.end_beat),
                intensity=rb.intensity,
                strobe_speed=rb.strobe_speed,
                iris=rb.iris,
                effect_type=rb.effect_type,
                effect_speed=rb.effect_speed,
                modified=False
            ))

        # Convert colour blocks
        colour_blocks = []
        for rb in self.colour_blocks:
            colour_blocks.append(ColourBlock(
                start_time=beat_to_time(rb.start_beat),
                end_time=beat_to_time(rb.end_beat),
                color_mode=rb.color_mode,
                red=rb.red,
                green=rb.green,
                blue=rb.blue,
                white=rb.white,
                amber=rb.amber,
                cyan=rb.cyan,
                magenta=rb.magenta,
                yellow=rb.yellow,
                uv=rb.uv,
                lime=rb.lime,
                hue=rb.hue,
                saturation=rb.saturation,
                value=rb.value,
                color_wheel_position=rb.color_wheel_position,
                modified=False
            ))

        # Convert movement blocks
        movement_blocks = []
        for rb in self.movement_blocks:
            movement_blocks.append(MovementBlock(
                start_time=beat_to_time(rb.start_beat),
                end_time=beat_to_time(rb.end_beat),
                pan=rb.pan,
                tilt=rb.tilt,
                pan_fine=rb.pan_fine,
                tilt_fine=rb.tilt_fine,
                speed=rb.speed,
                interpolate_from_previous=rb.interpolate_from_previous,
                effect_type=rb.effect_type,
                effect_speed=rb.effect_speed,
                pan_min=rb.pan_min,
                pan_max=rb.pan_max,
                tilt_min=rb.tilt_min,
                tilt_max=rb.tilt_max,
                pan_amplitude=rb.pan_amplitude,
                tilt_amplitude=rb.tilt_amplitude,
                lissajous_ratio=rb.lissajous_ratio,
                phase_offset_enabled=rb.phase_offset_enabled,
                phase_offset_degrees=rb.phase_offset_degrees,
                modified=False
            ))

        # Convert special blocks
        special_blocks = []
        for rb in self.special_blocks:
            special_blocks.append(SpecialBlock(
                start_time=beat_to_time(rb.start_beat),
                end_time=beat_to_time(rb.end_beat),
                gobo_index=rb.gobo_index,
                gobo_rotation=rb.gobo_rotation,
                focus=rb.focus,
                zoom=rb.zoom,
                prism_enabled=rb.prism_enabled,
                prism_rotation=rb.prism_rotation,
                modified=False
            ))

        return LightBlock(
            start_time=start_time,
            end_time=beat_to_time(self.length_beats),
            effect_name=f"riff:{self.name}",
            modified=False,
            dimmer_blocks=dimmer_blocks,
            colour_blocks=colour_blocks,
            movement_blocks=movement_blocks,
            special_blocks=special_blocks,
            riff_source=f"{self.category}/{self.name}",
            riff_version=self.version
        )


@dataclass
class ShowEffect:
    show_part: str
    fixture_group: str
    effect: str
    speed: str
    color: str
    intensity: int = 200
    spot: str = ""

@dataclass
class ShowPart:
    name: str
    color: str
    signature: str
    bpm: float
    num_bars: int
    transition: str
    # Runtime fields (calculated, not stored)
    start_time: float = 0.0
    duration: float = 0.0


@dataclass
class LightBlock:
    """Represents an effect block (envelope) on a light lane timeline with sublanes.

    The LightBlock acts as an envelope containing sublane blocks.
    Start/end times are automatically adjusted based on sublane block extents.
    """
    start_time: float      # In seconds (envelope start)
    end_time: float        # In seconds (envelope end)
    effect_name: str       # "module.function" e.g., "bars.static"
    modified: bool = False  # True if sublanes modified beyond original effect

    # Sublane blocks - now supports MULTIPLE blocks per sublane type
    dimmer_blocks: List[DimmerBlock] = field(default_factory=list)
    colour_blocks: List[ColourBlock] = field(default_factory=list)
    movement_blocks: List[MovementBlock] = field(default_factory=list)
    special_blocks: List[SpecialBlock] = field(default_factory=list)

    # Riff tracking - identifies if this block came from a riff
    riff_source: Optional[str] = None      # e.g., "builds/strobe_build_4bar"
    riff_version: Optional[str] = None     # e.g., "1.0"

    # User-defined name for the effect block
    name: Optional[str] = None  # Custom name set by user (displays as "base" if None)

    # Morph provenance (v1.5b, design doc 5.3): "" = authored in the
    # editor; "morphed:<edge_id>" = written by a morph compile;
    # "hand_edited" = a morphed block the editor touched afterwards.
    # Re-morph uses this to list exactly what a replace will destroy.
    provenance: str = ""

    # Legacy support (deprecated, kept for migration)
    duration: Optional[float] = None  # Deprecated: use end_time - start_time
    parameters: Dict[str, any] = field(default_factory=dict)  # Deprecated

    def get_duration(self) -> float:
        """Calculate duration from start and end times."""
        return self.end_time - self.start_time

    def update_envelope_bounds(self):
        """Update envelope start/end times based on sublane block extents."""
        # Collect all sublane blocks from all lists
        all_blocks = (
            self.dimmer_blocks +
            self.colour_blocks +
            self.movement_blocks +
            self.special_blocks
        )

        if all_blocks:
            self.start_time = min(b.start_time for b in all_blocks)
            self.end_time = max(b.end_time for b in all_blocks)

    def to_dict(self) -> Dict:
        return {
            "start_time": self.start_time,
            "end_time": self.end_time,
            "effect_name": self.effect_name,
            "modified": self.modified,
            "dimmer_blocks": [b.to_dict() for b in self.dimmer_blocks],
            "colour_blocks": [b.to_dict() for b in self.colour_blocks],
            "movement_blocks": [b.to_dict() for b in self.movement_blocks],
            "special_blocks": [b.to_dict() for b in self.special_blocks],
            # Riff tracking
            "riff_source": self.riff_source,
            "riff_version": self.riff_version,
            # User-defined name
            "name": self.name,
            # Morph provenance (only when set - keeps old files stable)
            **({"provenance": self.provenance} if self.provenance else {}),
            # Legacy fields
            "duration": self.get_duration(),
            "parameters": self.parameters
        }

    @classmethod
    def from_dict(cls, data: Dict) -> 'LightBlock':
        # Handle both new format and legacy format
        start_time = data.get("start_time", 0.0)
        end_time = data.get("end_time")

        # Legacy: if no end_time, calculate from duration
        if end_time is None:
            duration = data.get("duration", 4.0)
            end_time = start_time + duration

        block = cls(
            start_time=start_time,
            end_time=end_time,
            effect_name=data.get("effect_name", ""),
            modified=data.get("modified", False),
            riff_source=data.get("riff_source"),
            riff_version=data.get("riff_version"),
            name=data.get("name"),
            provenance=data.get("provenance", ""),
            duration=data.get("duration"),
            parameters=data.get("parameters", {})
        )

        # Load sublane blocks - handle both new list format and old single-block format
        # New format: dimmer_blocks (list)
        if data.get("dimmer_blocks"):
            block.dimmer_blocks = [DimmerBlock.from_dict(b) for b in data["dimmer_blocks"]]
        # Old format: dimmer_block (single) - migrate to list
        elif data.get("dimmer_block"):
            block.dimmer_blocks = [DimmerBlock.from_dict(data["dimmer_block"])]

        if data.get("colour_blocks"):
            block.colour_blocks = [ColourBlock.from_dict(b) for b in data["colour_blocks"]]
        elif data.get("colour_block"):
            block.colour_blocks = [ColourBlock.from_dict(data["colour_block"])]

        if data.get("movement_blocks"):
            block.movement_blocks = [MovementBlock.from_dict(b) for b in data["movement_blocks"]]
        elif data.get("movement_block"):
            block.movement_blocks = [MovementBlock.from_dict(data["movement_block"])]

        if data.get("special_blocks"):
            block.special_blocks = [SpecialBlock.from_dict(b) for b in data["special_blocks"]]
        elif data.get("special_block"):
            block.special_blocks = [SpecialBlock.from_dict(data["special_block"])]

        return block


@dataclass
class LightLane:
    """Represents a lane controlling fixture targets on the timeline"""
    name: str
    fixture_targets: List[str] = field(default_factory=list)
    muted: bool = False
    solo: bool = False
    light_blocks: List[LightBlock] = field(default_factory=list)
    # Stable identity (v1.5 morphing): plans key edges by lane_id so a
    # renamed lane keeps its routing. Assigned on creation / first load;
    # never shown in the UI.
    lane_id: str = field(default_factory=lambda: uuid.uuid4().hex)

    @property
    def fixture_group(self) -> str:
        """Backward compatibility: returns first target or empty string."""
        return self.fixture_targets[0] if self.fixture_targets else ""

    @fixture_group.setter
    def fixture_group(self, value: str):
        """Backward compatibility: sets single target."""
        self.fixture_targets = [value] if value else []

    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "lane_id": self.lane_id,
            "fixture_targets": self.fixture_targets,
            "muted": self.muted,
            "solo": self.solo,
            "light_blocks": [block.to_dict() for block in self.light_blocks]
        }

    @classmethod
    def from_dict(cls, data: Dict) -> 'LightLane':
        lane = cls(
            name=data.get("name", ""),
            muted=data.get("muted", False),
            solo=data.get("solo", False)
        )
        # Lanes from before v1.5 get an id on first load; it persists on
        # the next save.
        lane.lane_id = data.get("lane_id") or lane.lane_id
        # Migration: handle old fixture_group format
        if "fixture_targets" in data:
            lane.fixture_targets = data["fixture_targets"]
        elif "fixture_group" in data:
            old_group = data.get("fixture_group", "")
            lane.fixture_targets = [old_group] if old_group else []

        for block_data in data.get("light_blocks", []):
            lane.light_blocks.append(LightBlock.from_dict(block_data))
        return lane


@dataclass
class TimelineData:
    """Timeline-specific data for a show"""
    lanes: List[LightLane] = field(default_factory=list)
    audio_file_path: Optional[str] = None

    def to_dict(self) -> Dict:
        return {
            "lanes": [lane.to_dict() for lane in self.lanes],
            "audio_file_path": self.audio_file_path
        }

    @classmethod
    def from_dict(cls, data: Dict) -> 'TimelineData':
        timeline = cls(
            audio_file_path=data.get("audio_file_path")
        )
        for lane_data in data.get("lanes", []):
            timeline.lanes.append(LightLane.from_dict(lane_data))
        return timeline


@dataclass
class Song:
    """A single song: parts, effects, timeline data, audio.

    Formerly ``Show``. Since the setlist rework, a "show" is the whole
    evening (see :class:`Setlist`); the parts + BPM + audio unit is a Song.
    """
    name: str
    parts: List[ShowPart] = field(default_factory=list)
    effects: List[ShowEffect] = field(default_factory=list)  # Keep for backwards compatibility
    timeline_data: Optional[TimelineData] = None  # NEW: Timeline representation
    trigger_device: str = ""    # MIDI input profile name (e.g. "Akai APC Mini mk2"), empty = no trigger
    trigger_channel: int = -1   # MIDI channel number (-1 = no trigger)
    # Palette (v1.5): role -> (r, g, b) 0-255. Colour blocks carrying a
    # palette_role are re-resolved by apply_palette(); blocks without a
    # role are untouched literals. Empty dict = no palette defined.
    palette: Dict[str, List[int]] = field(default_factory=dict)
    # Morph lineage (v1.5b, design doc 5.3): set by the morph compile on
    # songs it writes - source show hash, plan hash, config hashes, app
    # version, timestamp. Empty dict = not a morphed song.
    lineage: Dict[str, str] = field(default_factory=dict)
    # Cached per-section audio metrics (v1.5b, design doc 5.7): every
    # SectionAnalysis scalar + the 32-float flux envelope, keyed by an
    # audio content hash - lets the morph's autogen regeneration run
    # without the audio file. utils/morph/analysis_cache.py owns the
    # shape. Empty dict = never analyzed.
    analysis_cache: Dict = field(default_factory=dict)

    def apply_palette(self) -> int:
        """Re-resolve every role-tagged colour block against ``palette``.

        Only the RGB literals are rewritten (the role stays); blocks
        whose role is not in the palette are left alone. Returns the
        number of blocks updated. Consumers (playback, export,
        visualizer) keep reading literals - this is the realization
        boundary the v1.5 design demands."""
        updated = 0
        if not self.timeline_data:
            return updated
        for lane in self.timeline_data.lanes:
            for block in lane.light_blocks:
                for cb in block.colour_blocks:
                    rgb = self.palette.get(cb.palette_role)
                    if not cb.palette_role or not rgb:
                        continue
                    cb.red, cb.green, cb.blue = (
                        float(rgb[0]), float(rgb[1]), float(rgb[2]))
                    updated += 1
        return updated

    def to_dict(self) -> Dict:
        """Serialize this song's contents (excludes `name`; that's the key in
        Configuration.songs). For a standalone song file, include the name
        at the caller: ``{'name': song.name, **song.to_dict()}``."""
        data = {
            'parts': [
                {k: v for k, v in asdict(part).items() if k not in ('start_time', 'duration')}
                for part in self.parts
            ],
            'effects': [asdict(effect) for effect in self.effects],
            'timeline_data': self.timeline_data.to_dict() if self.timeline_data else None,
            'trigger_device': self.trigger_device if self.trigger_device else None,
            'trigger_channel': self.trigger_channel if self.trigger_channel >= 0 else None,
        }
        if self.palette:
            data['palette'] = {role: list(rgb)
                               for role, rgb in self.palette.items()}
        if self.lineage:
            data['lineage'] = dict(self.lineage)
        if self.analysis_cache:
            data['analysis_cache'] = dict(self.analysis_cache)
        return data

    @classmethod
    def from_dict(cls, name: str, data: Dict) -> 'Song':
        """Deserialize a song. `name` is supplied externally (usually the
        mapping key in Configuration.songs, or the `name:` field of a
        standalone song YAML)."""
        parts = [
            ShowPart(
                name=p['name'],
                color=p['color'],
                signature=p['signature'],
                bpm=p['bpm'],
                num_bars=p['num_bars'],
                transition=p['transition'],
            )
            for p in data.get('parts', [])
        ]
        effects = [
            ShowEffect(
                show_part=e['show_part'],
                fixture_group=e['fixture_group'],
                effect=e['effect'],
                speed=e['speed'],
                color=e['color'],
                intensity=e['intensity'],
                spot=e['spot'],
            )
            for e in data.get('effects', [])
        ]
        timeline_data = (
            TimelineData.from_dict(data['timeline_data'])
            if data.get('timeline_data') else None
        )
        return cls(
            name=name,
            parts=parts,
            effects=effects,
            timeline_data=timeline_data,
            palette={role: list(rgb) for role, rgb
                     in (data.get('palette') or {}).items()},
            lineage=dict(data.get('lineage') or {}),
            analysis_cache=dict(data.get('analysis_cache') or {}),
            trigger_device=data.get('trigger_device', '') or '',
            trigger_channel=(
                data.get('trigger_channel', -1)
                if data.get('trigger_channel') is not None else -1
            ),
        )


@dataclass
class SongTrigger:
    """How a setlist entry's song starts.

    Modes: "manual" (operator hits go), "midi_pc" (MIDI program change,
    ``value`` = program number), "midi_note" (``value`` = note number),
    "mtc" / "smpte" (chase to ``timecode``, e.g. "00:14:32:00"), and
    "follow" (chains automatically after the previous song's pause look).
    The engine that listens arrives in slices: SMPTE/LTC with v1.4,
    the rest (MIDI, MTC, follow) with v1.8; until then this is stored
    and edited data only.
    """
    mode: str = "manual"   # "manual" | "midi_pc" | "midi_note" | "mtc" | "smpte" | "follow"
    value: int = 0         # program / note number (midi_pc, midi_note)
    channel: int = 1       # MIDI channel (1-16)
    timecode: str = ""     # "HH:MM:SS:FF" start time for mtc/smpte

    def to_dict(self) -> Dict:
        return {
            "mode": self.mode,
            "value": self.value,
            "channel": self.channel,
            "timecode": self.timecode,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> 'SongTrigger':
        return cls(
            mode=data.get("mode", "manual"),
            value=data.get("value", 0),
            channel=data.get("channel", 1),
            timecode=data.get("timecode", ""),
        )


@dataclass
class PauseLook:
    """The look on stage between two setlist songs.

    Modes: "blackout", "warm_white" (``level`` percent), "hold_last"
    (freeze the previous song's last look), "ambient_loop" (reuses the
    screensaver rig behaviour once the engine lands). ``until`` decides
    how the pause ends: "trigger" (next song's start trigger) or
    "duration" (``duration_s`` seconds, then follow on).
    """
    mode: str = "hold_last"   # "blackout" | "warm_white" | "hold_last" | "ambient_loop"
    level: int = 20           # percent, used by warm_white
    until: str = "trigger"    # "trigger" | "duration"
    duration_s: float = 0.0   # used when until == "duration"

    def to_dict(self) -> Dict:
        return {
            "mode": self.mode,
            "level": self.level,
            "until": self.until,
            "duration_s": self.duration_s,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> 'PauseLook':
        return cls(
            mode=data.get("mode", "hold_last"),
            level=data.get("level", 20),
            until=data.get("until", "trigger"),
            duration_s=data.get("duration_s", 0.0),
        )


@dataclass
class SetlistEntry:
    """One slot of the setlist: a song (by name key into
    Configuration.songs), its start trigger, and the pause look that
    plays after it ends."""
    song: str
    trigger: SongTrigger = field(default_factory=SongTrigger)
    pause_after: PauseLook = field(default_factory=PauseLook)

    def to_dict(self) -> Dict:
        return {
            "song": self.song,
            "trigger": self.trigger.to_dict(),
            "pause_after": self.pause_after.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: Dict) -> 'SetlistEntry':
        return cls(
            song=data.get("song", ""),
            trigger=SongTrigger.from_dict(data.get("trigger") or {}),
            pause_after=PauseLook.from_dict(data.get("pause_after") or {}),
        )


@dataclass
class Setlist:
    """The whole evening: an ordered list of songs with triggers and
    pause looks, plus the sync source the triggers listen to.

    One setlist per config file for now (the design shows one per show
    file)."""
    name: str = ""
    entries: List[SetlistEntry] = field(default_factory=list)
    sync_mode: str = "manual"   # "midi" | "mtc" | "smpte" | "manual"
    sync_device: str = ""       # MIDI/LTC input device hint

    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "entries": [e.to_dict() for e in self.entries],
            "sync_mode": self.sync_mode,
            "sync_device": self.sync_device,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> 'Setlist':
        return cls(
            name=data.get("name", ""),
            entries=[SetlistEntry.from_dict(e) for e in data.get("entries", []) or []],
            sync_mode=data.get("sync_mode", "manual"),
            sync_device=data.get("sync_device", ""),
        )

    @classmethod
    def from_song_names(cls, names) -> 'Setlist':
        """Synthesize a setlist for configs that predate setlists: the
        given songs in sorted-name order, manual triggers, hold-last
        pause looks that wait for the next trigger."""
        return cls(entries=[
            SetlistEntry(
                song=name,
                trigger=SongTrigger(mode="manual"),
                pause_after=PauseLook(mode="hold_last", until="trigger"),
            )
            for name in sorted(names)
        ])


@dataclass
class MidiInputDevice:
    """A MIDI input device configured for triggering shows."""
    name: str              # Profile name (e.g. "Akai APC Mini mk2")
    uid: str               # Device UID for QLC+ (e.g. "APC mini mk2")
    profile: str           # Profile reference for QLC+ (same as name)
    universe_id: int       # QLC+ universe ID (0-based) this device is assigned to
    line: int = 1          # MIDI line number


@dataclass
class PauseShowConfig:
    """Settings for the auto-generated PAUSE show."""
    enabled: bool = False
    color: str = "#0000FF"
    trigger_device: str = ""
    trigger_channel: int = -1


@dataclass
class Universe:
    id: int
    name: str
    output: Dict[str, any]

    def __post_init__(self):
        if self.name is None:
            self.name = f"Universe {self.id}"

@dataclass
class UniverseOutput:
    plugin: str
    line: str
    parameters: Dict[str, str]



@dataclass
class Configuration:
    fixtures: List[Fixture] = field(default_factory=list)
    groups: Dict[str, FixtureGroup] = field(default_factory=dict)
    songs: Dict[str, Song] = field(default_factory=dict)
    setlist: Setlist = field(default_factory=Setlist)
    universes: Dict[int, Universe] = field(default_factory=dict)
    spots: Dict[str, Spot] = field(default_factory=dict)
    workspace_path: Optional[str] = None
    shows_directory: Optional[str] = None  # Directory where show CSV files and audio are stored
    midi_input_devices: List[MidiInputDevice] = field(default_factory=list)
    pause_show: PauseShowConfig = field(default_factory=PauseShowConfig)
    stage_width: float = 10.0  # Stage width in meters
    stage_height: float = 6.0  # Stage depth in meters (called height for compatibility)
    grid_size: float = 0.5  # Grid spacing in meters
    stage_layers: List[StageLayer] = field(default_factory=list)
    stage_elements: List[StageElement] = field(default_factory=list)

    def get_stage_layer(self, name: str) -> Optional[StageLayer]:
        return next((l for l in self.stage_layers if l.name == name), None)

    def is_fixture_visible(self, fixture: Fixture) -> bool:
        """False only when the fixture sits on a hidden stage layer.

        Fixtures without a layer, or referencing a layer that no longer
        exists, are always visible.
        """
        if not fixture.layer:
            return True
        layer = self.get_stage_layer(fixture.layer)
        return layer.visible if layer is not None else True

    @classmethod
    def from_workspace(cls, workspace_path: str) -> 'Configuration':
        """Create Configuration from QLC+ workspace file"""
        fixture_definitions = cls._scan_fixture_definitions()
        fixtures_data = cls._parse_workspace(workspace_path, fixture_definitions)

        config = cls(fixtures=[], groups={}, workspace_path=workspace_path)

        for fixture_data in fixtures_data:
            # Get fixture definition for type info
            fixture_def = fixture_definitions.get(
                (fixture_data['Manufacturer'], fixture_data['Model']))

            # Create FixtureMode objects from the available modes
            modes = []
            if fixture_data['AvailableModes']:
                for mode in fixture_data['AvailableModes']:
                    modes.append(FixtureMode(
                        name=mode['name'],
                        channels=mode['channels']
                    ))

            fixture = Fixture(
                universe=fixture_data['Universe'],
                address=fixture_data['Address'],
                manufacturer=fixture_data['Manufacturer'],
                model=fixture_data['Model'],
                name=fixture_data['Name'],
                group=fixture_data['Group'],
                current_mode=fixture_data['CurrentMode'],
                available_modes=modes,
                type=fixture_def['type'] if fixture_def else "PAR",  # Default to PAR if no definition found
                x=fixture_data.get('X', 0.0),
                y=fixture_data.get('Y', 0.0),
                z=fixture_data.get('Z', 0.0),
                # Orientation defaults (from workspace, these are set to defaults)
                mounting="hanging",
                yaw=0.0,
                pitch=0.0,
                roll=0.0,
                orientation_uses_group_default=True,
                z_uses_group_default=True
            )
            config.fixtures.append(fixture)

            for group_name in fixture.groups:
                if group_name not in config.groups:
                    config.groups[group_name] = FixtureGroup(group_name, [])
                config.groups[group_name].fixtures.append(fixture)

        for group in config.groups.values():
            group.apply_fixture_order()

        return config

    def audio_bundle_dir(self, create: bool = False) -> Optional[str]:
        """Resolve the directory audio files live in for this config.

        Resolution order:
        1. ``<dir of self._loaded_from>/audiofiles/`` - the new v1.0 layout
           where audio bundles next to the config.
        2. ``<self.shows_directory>/audiofiles/`` - the legacy layout from
           when ``shows_directory`` was authoritative; kept as a fallback
           so existing configs keep finding their audio files.

        Returns ``None`` when neither path is resolvable (a config that
        has never been saved AND has no shows_directory hint).

        With ``create=True``, ensures the directory exists (for the
        primary path only). Used when copying a freshly loaded audio file
        into the bundle.
        """
        loaded_from = getattr(self, '_loaded_from', None)
        if loaded_from:
            primary = os.path.join(os.path.dirname(loaded_from), 'audiofiles')
            if create:
                os.makedirs(primary, exist_ok=True)
                return primary
            if os.path.exists(primary):
                return primary
        if self.shows_directory:
            legacy = os.path.join(self.shows_directory, 'audiofiles')
            if os.path.exists(legacy):
                return legacy
        if loaded_from and create:
            # Caller explicitly asked us to create; return the primary
            # path even though we already returned it above (defensive).
            return os.path.join(os.path.dirname(loaded_from), 'audiofiles')
        return None

    def save(self, filename: str):
        """Save configuration to YAML file"""
        data = {
            # fixture_asdict dual-writes `groups` (source of truth) and
            # the legacy `group` key for older builds (plan stage 5
            # removes it).
            'fixtures': [fixture_asdict(f) for f in self.fixtures],
            'groups': {
                name: {
                    'name': group.name,
                    'color': group.color,
                    'default_mounting': group.default_mounting,
                    'default_yaw': group.default_yaw,
                    'default_pitch': group.default_pitch,
                    'default_roll': group.default_roll,
                    'default_z_height': group.default_z_height,
                    'lighting_role': group.lighting_role,
                    'export_intensity': group.export_intensity,
                    # Canonical topology (v1.5): the order every indexed
                    # target and chase consumes, pinned by name.
                    'fixture_order': [f.name for f in group.fixtures],
                    'order_mode': group.order_mode,
                    'fixtures': [fixture_asdict(f) for f in group.fixtures]
                }
                for name, group in self.groups.items()
            },
            'universes': {
                str(universe.id): {
                    'name': universe.name,
                    'output': universe.output
                }
                for universe in self.universes.values()
            },
            'songs': {
                song.name: song.to_dict()
                for song in self.songs.values()
            },
            'setlist': self.setlist.to_dict() if self.setlist else Setlist().to_dict(),
            'midi_input_devices': [asdict(d) for d in self.midi_input_devices] if self.midi_input_devices else None,
            'pause_show': asdict(self.pause_show) if self.pause_show and self.pause_show.enabled else None,
            'spots': {
                name: asdict(spot)
                for name, spot in self.spots.items()
            },
            'workspace_path': self.workspace_path,
            'shows_directory': self.shows_directory,
            # Stage geometry — historically lost on round-trip because
            # save() didn't emit and load() didn't read these. The
            # Stage tab's stage-size spinboxes effectively reset on
            # every config load. Persist them now.
            'stage_width': self.stage_width,
            'stage_height': self.stage_height,
            'grid_size': self.grid_size,
            'stage_layers': [asdict(layer) for layer in self.stage_layers],
            'stage_elements': [asdict(e) for e in self.stage_elements],
        }

        from config.compact_serializer import compact_serialize
        data = compact_serialize(data)

        with open(filename, 'w') as f:
            yaml.dump(data, f, default_flow_style=False)

        # Track save location so audio_bundle_dir resolves correctly after
        # Save As (file moved relative to where audio was last written).
        self._loaded_from = os.path.abspath(filename)

    @classmethod
    def load(cls, filename: str) -> 'Configuration':
        """Load configuration from YAML file"""
        with open(filename, 'r') as f:
            data = yaml.safe_load(f)

        # Legacy key migration: configs written before the setlist rework
        # store the songs under a top-level `shows:` key. Accept it forever;
        # the per-file block tables (block_defs / light_block_defs) are
        # untouched by the rename, so expand_compact works on the migrated
        # key exactly as before.
        if 'songs' not in data and 'shows' in data:
            data['songs'] = data.pop('shows')

        from config.compact_serializer import expand_compact
        data = expand_compact(data)

        # Convert dictionary back to Configuration object
        fixtures = []
        for f_data in data.get('fixtures', []):
            if 'available_modes' in f_data:
                modes = []
                for mode_data in f_data['available_modes']:
                    mode = FixtureMode(
                        name=mode_data['name'],
                        channels=mode_data['channels']
                    )
                    modes.append(mode)
                f_data['available_modes'] = modes

            # Remove deprecated fields if present (direction, rotation)
            f_data.pop('direction', None)
            f_data.pop('rotation', None)

            fixtures.append(Fixture(**f_data))

        # Reconcile stored mode names against the resolved definitions.
        # A GDTF definition can shadow a same-identity .qxf and carry
        # differently-named modes; without this, such fixtures fall back
        # to empty channel maps (docs/gdtf-coverage-note.md item 4).
        from utils.fixture_io import reconcile_fixture_modes
        from utils import user_warnings
        for warning in reconcile_fixture_modes(fixtures):
            user_warnings.warn(warning, category="config-load")

        # Bring stored orientations onto the canonical mounting table
        # (utils/orientation.py). Configs written before 2026-07-12 saved
        # `mounting: hanging` next to yaw/pitch/roll = 0, and every
        # consumer used the zeros and ignored the mounting - so a hanging
        # rig aimed as if it were wall-mounted. Custom orientations are
        # left untouched; the rewrite is idempotent.
        from utils.orientation import migrate_orientation_angles
        for fixture in fixtures:
            fixture.yaw, fixture.pitch, fixture.roll = \
                migrate_orientation_angles(fixture.mounting, fixture.yaw,
                                           fixture.pitch, fixture.roll)

        # Handle groups with colors and orientation defaults
        # Groups reference the same fixture objects as the top-level fixtures list
        groups = {}
        for name, group_data in data.get('groups', {}).items():
            # Find fixtures that belong to this group from the top-level
            # fixtures. Membership is the full `groups` list, so a fixture
            # appears in every group it lists.
            group_fixtures = [f for f in fixtures if name in f.groups]

            group_mounting = group_data.get('default_mounting', 'hanging')
            group_yaw, group_pitch, group_roll = migrate_orientation_angles(
                group_mounting,
                group_data.get('default_yaw', 0.0),
                group_data.get('default_pitch', 0.0),
                group_data.get('default_roll', 0.0),
            )
            groups[name] = FixtureGroup(
                name=name,
                fixtures=group_fixtures,
                color=group_data.get('color', '#808080'),
                # Orientation defaults (canonical angles - migrated above)
                default_mounting=group_mounting,
                default_yaw=group_yaw,
                default_pitch=group_pitch,
                default_roll=group_roll,
                default_z_height=group_data.get('default_z_height', 3.0),
                lighting_role=group_data.get('lighting_role', ''),
                export_intensity=group_data.get('export_intensity', 255),
                # Deterministic topology: a stored order re-applies; a
                # config from before the field snapshots its derived
                # order (identical to today's behavior, now pinned).
                fixture_order=group_data.get('fixture_order', []),
                order_mode=group_data.get('order_mode', 'manual'),
            )
            groups[name].apply_fixture_order()

        # Handle songs (legacy `shows:` was migrated to `songs` above)
        songs = {}
        if 'songs' in data:
            for song_name, song_data in data['songs'].items():
                songs[song_name] = Song.from_dict(song_name, song_data)

        # Handle setlist. Configs that predate setlists (legacy `shows:`
        # files) get one synthesized from the sorted song names: manual
        # triggers, hold-last pause looks until the next trigger.
        setlist_data = data.get('setlist')
        if setlist_data:
            setlist = Setlist.from_dict(setlist_data)
        else:
            setlist = Setlist.from_song_names(songs.keys())

        # Handle universes
        universes = {}
        if 'universes' in data:
            for universe_id_str, universe_data in data['universes'].items():
                universe_id = int(universe_id_str)
                universes[universe_id] = Universe(
                    id=universe_id,
                    output=universe_data.get('output', {
                        'plugin': 'E1.31',
                        'line': '0',
                        'parameters': {
                            'ip': f'192.168.1.{universe_id}',
                            'port': '6454',
                            'subnet': '0',
                            'universe': str(universe_id)
                        }
                    }),
                    name=universe_data.get('name', f"Universe {universe_id}")
                )

        # Handle spots
        spots = {}
        if 'spots' in data:
            for spot_name, spot_data in data['spots'].items():
                spots[spot_name] = Spot(**spot_data)

        # Handle MIDI input devices
        midi_input_devices = []
        if 'midi_input_devices' in data and data['midi_input_devices']:
            for dev_data in data['midi_input_devices']:
                midi_input_devices.append(MidiInputDevice(**dev_data))

        # Handle pause show config
        pause_show_data = data.get('pause_show')
        pause_show = PauseShowConfig(**pause_show_data) if pause_show_data else PauseShowConfig()

        config = cls(
            fixtures=fixtures,
            groups=groups,
            universes=universes,
            songs=songs,
            setlist=setlist,
            spots=spots,
            midi_input_devices=midi_input_devices,
            pause_show=pause_show,
            workspace_path=data.get('workspace_path'),
            shows_directory=data.get('shows_directory'),
            # Stage geometry; fall back to dataclass defaults when the
            # YAML predates the field (older saved configs).
            stage_width=data.get('stage_width', 10.0),
            stage_height=data.get('stage_height', 6.0),
            grid_size=data.get('grid_size', 0.5),
            stage_layers=[
                StageLayer(**layer_data)
                for layer_data in data.get('stage_layers', [])
            ],
            stage_elements=[
                StageElement(**element_data)
                for element_data in data.get('stage_elements', [])
            ],
        )

        # Transient attribute (not persisted): the path the config was loaded
        # from. Used by audio-bundle-dir resolution so audio files referenced
        # by filename land under <config_dir>/audiofiles/ regardless of where
        # the user copied the config from.
        config._loaded_from = os.path.abspath(filename)

        return config

    @staticmethod
    def _scan_fixture_definitions():
        """Scan QLC+ fixture definitions (full-library sweep for .qxw import)."""
        from utils.fixture_library import iter_definitions

        fixture_definitions = {}
        for defn in iter_definitions():
            fixture_definitions[(defn.manufacturer, defn.model)] = {
                'path': defn.path,
                'modes': [
                    {
                        'name': mode.name,
                        'channels': len(mode.channels),
                        'type': defn.legacy_type,  # Same type for all modes
                    }
                    for mode in defn.modes
                ],
                'type': defn.legacy_type,
            }
        return fixture_definitions

    @staticmethod
    def _parse_workspace(workspace_path: str, fixture_definitions: dict) -> List[Dict]:
        """
        Parse QLC+ workspace file and extract fixture data

        Args:
            workspace_path: Path to QLC+ workspace file
            fixture_definitions: Dictionary of fixture definitions

        Returns:
            List of fixture data dictionaries
        """
        try:
            tree = ET.parse(workspace_path)
            root = tree.getroot()
            ns = {'qlc': 'http://www.qlcplus.org/Workspace'}

            # Extract fixtures with their groups
            fixtures_data = []
            existing_groups = set()

            # First pass - collect all groups
            for group in root.findall(".//qlc:Engine/qlc:ChannelsGroup", ns):
                existing_groups.add(group.get('Name'))

            # Second pass - process fixtures
            for fixture in root.findall(".//qlc:Engine/qlc:Fixture", ns):
                fixture_id = fixture.find("qlc:ID", ns).text
                manufacturer = fixture.find("qlc:Manufacturer", ns).text
                model = fixture.find("qlc:Model", ns).text
                current_mode = fixture.find("qlc:Mode", ns).text

                # Get channel count from workspace (this is the actual count for the current mode)
                channels_elem = fixture.find("qlc:Channels", ns)
                workspace_channels = int(channels_elem.text) if channels_elem is not None else 6

                # Find group for this fixture
                group_name = ""
                for group in root.findall(".//qlc:Engine/qlc:ChannelsGroup", ns):
                    channel_pairs = group.text.split(',')
                    fixture_ids = set(channel_pairs[::2])  # Take every other item (fixture IDs)

                    if fixture_id in fixture_ids:
                        group_name = group.get('Name')
                        break

                # Get fixture definition if available
                fixture_def = fixture_definitions.get((manufacturer, model))

                # Use fixture definition modes if available, otherwise create from workspace data
                if fixture_def and fixture_def['modes']:
                    available_modes = fixture_def['modes']
                else:
                    # Fallback: create a single mode from workspace data
                    available_modes = [{
                        'name': current_mode,
                        'channels': workspace_channels,
                        'type': 'PAR'  # Default type
                    }]

                fixtures_data.append({
                    'Universe': int(fixture.find("qlc:Universe", ns).text) + 1,
                    'Address': int(fixture.find("qlc:Address", ns).text) + 1,
                    'Manufacturer': manufacturer,
                    'Model': model,
                    'Name': fixture.find("qlc:Name", ns).text,
                    'Group': group_name,
                    'CurrentMode': current_mode,
                    'AvailableModes': available_modes,
                    'WorkspaceChannels': workspace_channels  # Store for validation
                })

            return fixtures_data

        except ET.ParseError as e:
            raise ValueError(f"Invalid workspace file format: {e}")
        except Exception as e:
            raise RuntimeError(f"Error parsing workspace file: {e}")

    def initialize_default_universes(self):
        """Initialize default universes with placeholder values"""
        for i in range(1, 5):  # Create 4 universes
            self.universes[i] = Universe(
                id=i,
                name=f"Universe {i}",
                output={
                    'plugin': 'E1.31',
                    'line': '0',
                    'parameters': {
                        'ip': f'192.168.1.{i}',
                        'port': '6454',
                        'subnet': '0',
                        'universe': str(i)
                    }
                }
            )

    def add_universe(self, universe_id: int, output_type: str, ip: str, port: str, subnet: str, universe: str):
        """Add or update a universe configuration"""
        self.universes[universe_id] = Universe(
            id=universe_id,
            name=f"Universe {universe_id}",
            output={
                'plugin': output_type,
                'line': '0',
                'parameters': {
                    'ip': ip,
                    'port': port,
                    'subnet': subnet,
                    'universe': universe
                }
            }
        )

    def remove_universe(self, universe_id: int):
        """Remove a universe configuration"""
        if universe_id in self.universes:
            del self.universes[universe_id]

    def ensure_universes_for_fixtures(self):
        """
        Ensure universes exist for all fixtures.

        Creates universes automatically based on fixture assignments.
        Uses ArtNet broadcast output for visualizer compatibility.

        Returns:
            bool: True if any universes were created, False if all already existed
        """
        if not self.fixtures:
            # No fixtures, nothing to do
            return False

        # Collect all unique universe IDs from fixtures
        universe_ids_needed = set()
        for fixture in self.fixtures:
            universe_ids_needed.add(fixture.universe)

        # Find missing universes
        existing_ids = set(self.universes.keys())
        missing_ids = universe_ids_needed - existing_ids

        if not missing_ids:
            # All needed universes already exist
            return False

        # Create universes for each missing ID
        for universe_id in sorted(missing_ids):
            self.universes[universe_id] = Universe(
                id=universe_id,
                name=f"Universe {universe_id}",
                output={
                    'plugin': 'ArtNet',
                    'line': '0',
                    'parameters': {
                        'ip': '255.255.255.255',  # Broadcast for visualizer
                        'port': '6454',
                        'subnet': '0',
                        'universe': str(universe_id)
                    }
                }
            )

        print(f"Auto-created {len(missing_ids)} universe(s) for visualizer: {sorted(missing_ids)}")

        return True

