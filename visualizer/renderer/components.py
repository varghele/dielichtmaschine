"""Fixture components for the composable renderer (Phase B).

Each :class:`FixtureComponent` is a small state holder: it reads from a
512-byte DMX universe buffer using its own pre-known channel indices,
then exposes typed accessors (``rgb``, ``dimmer``, ``pan_deg``, ...)
that the renderer reads to drive GL uniforms.

State-only components live here. :class:`BeamComponent` and its
subclasses (defined later in this file) additionally own GL programs +
VAOs because the beam *is* the visible output. Components never store a
back-reference to a parent renderer — they are owned by the
:class:`FixtureRenderer` and combined by it explicitly.

Phase B leaves the old ``fixtures.py`` untouched. Phase D wires this
module into ``FixtureManager._create_fixture``.
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from typing import List, Optional, Tuple

from utils.fixture_capabilities import (
    BeamShape,
    ColorMixing,
    ColorMixingMode,
    ColorWheel,
    GoboWheel,
    Movement,
    Prism,
)


# Built-in gobo pattern IDs (0=open, 1=dots, 2=star, 3=lines, 4=triangle,
# 5=cross, 6=breakup) match the shaders in ``shaders.py``.
GOBO_PATTERN_OPEN = 0
GOBO_PATTERN_DOTS = 1
GOBO_PATTERN_STAR = 2
GOBO_PATTERN_LINES = 3
GOBO_PATTERN_TRIANGLE = 4
GOBO_PATTERN_CROSS = 5
GOBO_PATTERN_BREAKUP = 6


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read_dmx(dmx_data: bytes, address: int, channel: Optional[int]) -> int:
    """Read one byte at ``(address - 1) + channel``. Returns 0 if out of range."""
    if channel is None:
        return 0
    idx = (address - 1) + channel
    if 0 <= idx < len(dmx_data):
        return dmx_data[idx]
    return 0


def _hsl_to_rgb(h: float, s: float, l: float) -> Tuple[float, float, float]:
    """HSL → RGB (all inputs and outputs in 0..1)."""
    if s <= 0:
        return (l, l, l)
    q = l + s - l * s if l < 0.5 else l + s - l * s
    # Standard HSL formula (Wikipedia: HSL and HSV).
    c = (1 - abs(2 * l - 1)) * s
    h_prime = (h * 6.0) % 6.0
    x = c * (1 - abs(h_prime % 2 - 1))
    if h_prime < 1:
        r, g, b = c, x, 0.0
    elif h_prime < 2:
        r, g, b = x, c, 0.0
    elif h_prime < 3:
        r, g, b = 0.0, c, x
    elif h_prime < 4:
        r, g, b = 0.0, x, c
    elif h_prime < 5:
        r, g, b = x, 0.0, c
    else:
        r, g, b = c, 0.0, x
    m = l - c / 2.0
    return (r + m, g + m, b + m)


def _parse_hex(color_hex: str) -> Optional[Tuple[float, float, float]]:
    """Parse ``"#RRGGBB"`` → (r,g,b) in 0..1. Returns None on bad input."""
    if not color_hex or not color_hex.startswith('#') or len(color_hex) != 7:
        return None
    try:
        r = int(color_hex[1:3], 16) / 255.0
        g = int(color_hex[3:5], 16) / 255.0
        b = int(color_hex[5:7], 16) / 255.0
        return (r, g, b)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------


class FixtureComponent(ABC):
    """A capability component. Reads DMX, exposes typed state to the renderer."""

    @abstractmethod
    def update_dmx(self, dmx_data: bytes, address: int) -> None:
        """Read this component's channels from the universe buffer.

        ``address`` is the fixture's 1-indexed DMX address. Channel
        indices stored on the component are mode-local 0-indexed offsets.
        """


# ---------------------------------------------------------------------------
# Intensity
# ---------------------------------------------------------------------------


class DimmerComponent(FixtureComponent):
    """Master dimmer (intensity scalar 0..1)."""

    def __init__(self, channel: int):
        self.channel = channel
        self._value = 0  # 0-255

    def update_dmx(self, dmx_data: bytes, address: int) -> None:
        self._value = _read_dmx(dmx_data, address, self.channel)

    @property
    def normalized(self) -> float:
        return self._value / 255.0


class StrobeComponent(FixtureComponent):
    """Strobe rate scalar (0..1). 0 = no strobe (open shutter)."""

    def __init__(self, channel: int):
        self.channel = channel
        self._value = 0

    def update_dmx(self, dmx_data: bytes, address: int) -> None:
        self._value = _read_dmx(dmx_data, address, self.channel)

    @property
    def rate(self) -> float:
        """0..1 strobe rate. Sub-range semantics (open / strobe / pulse)
        from <Capability Preset> aren't decoded here — Phase D may
        revisit if visual fidelity demands it."""
        if self._value < 10:
            return 0.0
        return self._value / 255.0

    @property
    def is_strobing(self) -> bool:
        return self.rate > 0


# ---------------------------------------------------------------------------
# Color
# ---------------------------------------------------------------------------


class ColorComponent(FixtureComponent):
    """Combined color mixing + color wheel.

    If both are present (e.g. a CMY moving head with a color wheel) the
    mixing path wins when the mix produces any color; the wheel is the
    fallback for "no RGB selected" cases.
    """

    def __init__(
        self,
        mixing: Optional[ColorMixing] = None,
        wheel: Optional[ColorWheel] = None,
    ):
        self.mixing = mixing
        self.wheel = wheel
        self._rgb: Tuple[float, float, float] = (0.0, 0.0, 0.0)
        self._white_contribution: float = 0.0

    def update_dmx(self, dmx_data: bytes, address: int) -> None:
        rgb: Optional[Tuple[float, float, float]] = None
        white = 0.0

        if self.mixing is not None:
            rgb, white = self._sample_mixing(dmx_data, address)

        # Fall back to color wheel only when mixing is absent OR mixing produces black.
        if (rgb is None or rgb == (0.0, 0.0, 0.0)) and self.wheel is not None:
            wheel_rgb = self._sample_wheel(dmx_data, address)
            if wheel_rgb is not None:
                rgb = wheel_rgb

        # If still no color and we have any color capability, default to white
        # (matches MovingHeadRenderer.get_color fallback).
        if rgb is None and (self.mixing is not None or self.wheel is not None):
            rgb = (1.0, 1.0, 1.0)

        self._rgb = rgb if rgb is not None else (0.0, 0.0, 0.0)
        self._white_contribution = white

    def _sample_mixing(
        self,
        dmx_data: bytes,
        address: int,
    ) -> Tuple[Optional[Tuple[float, float, float]], float]:
        ch = self.mixing.channels
        mode = self.mixing.mode

        if mode is ColorMixingMode.HSL:
            h = _read_dmx(dmx_data, address, ch.get('hue')) / 255.0
            s = _read_dmx(dmx_data, address, ch.get('saturation')) / 255.0
            l = _read_dmx(dmx_data, address, ch.get('lightness')) / 255.0
            return _hsl_to_rgb(h, s, l), 0.0

        if mode in (ColorMixingMode.HSV, ColorMixingMode.HSI):
            h = _read_dmx(dmx_data, address, ch.get('hue')) / 255.0
            s = _read_dmx(dmx_data, address, ch.get('saturation')) / 255.0
            v = _read_dmx(dmx_data, address, ch.get('value')) / 255.0
            return _hsl_to_rgb(h, s, v * 0.5), 0.0  # rough HSV→HSL approximation

        if mode is ColorMixingMode.CMY:
            c = _read_dmx(dmx_data, address, ch.get('cyan')) / 255.0
            m = _read_dmx(dmx_data, address, ch.get('magenta')) / 255.0
            y = _read_dmx(dmx_data, address, ch.get('yellow')) / 255.0
            # Subtractive: white minus CMY (clamped).
            return (max(0.0, 1.0 - c), max(0.0, 1.0 - m), max(0.0, 1.0 - y)), 0.0

        # Additive RGB(W/A/UV) variants
        r = _read_dmx(dmx_data, address, ch.get('red')) / 255.0
        g = _read_dmx(dmx_data, address, ch.get('green')) / 255.0
        b = _read_dmx(dmx_data, address, ch.get('blue')) / 255.0
        w = _read_dmx(dmx_data, address, ch.get('white')) / 255.0
        a = _read_dmx(dmx_data, address, ch.get('amber')) / 255.0
        uv = _read_dmx(dmx_data, address, ch.get('uv')) / 255.0

        # Combine extra components into RGB approximations.
        # Amber ≈ (1, 0.75, 0), UV ≈ (0.5, 0, 1) — visualizer approximations.
        rgb_r = r + w + a * 1.0 + uv * 0.5
        rgb_g = g + w + a * 0.75
        rgb_b = b + w + uv * 1.0

        return (min(1.0, rgb_r), min(1.0, rgb_g), min(1.0, rgb_b)), w

    def _sample_wheel(
        self,
        dmx_data: bytes,
        address: int,
    ) -> Optional[Tuple[float, float, float]]:
        value = _read_dmx(dmx_data, address, self.wheel.channel)
        for entry in self.wheel.entries:
            if entry.dmx_min <= value <= entry.dmx_max:
                if entry.hex_color is not None:
                    return _parse_hex(entry.hex_color)
                # Capability without hex_color: treat as white. The wheel
                # was matched, so this isn't a "no color" state.
                return (1.0, 1.0, 1.0)
        return None

    @property
    def rgb(self) -> Tuple[float, float, float]:
        return self._rgb

    @property
    def white(self) -> float:
        """Raw white-channel contribution (0..1) when present. Useful for
        warm-white halo rendering separate from RGB color."""
        return self._white_contribution


# ---------------------------------------------------------------------------
# Movement
# ---------------------------------------------------------------------------


class MovementComponent(FixtureComponent):
    """Pan/tilt, optionally with 16-bit fine channels."""

    def __init__(self, movement: Movement):
        self.movement = movement
        self.pan_deg: float = 0.0
        self.tilt_deg: float = 0.0

    def update_dmx(self, dmx_data: bytes, address: int) -> None:
        pan_coarse = _read_dmx(dmx_data, address, self.movement.pan_channel)
        pan_fine = _read_dmx(dmx_data, address, self.movement.pan_fine_channel)
        tilt_coarse = _read_dmx(dmx_data, address, self.movement.tilt_channel)
        tilt_fine = _read_dmx(dmx_data, address, self.movement.tilt_fine_channel)

        # 16-bit combine (low byte is the fine channel; matches existing renderer).
        pan_combined = (pan_coarse * 256 + pan_fine) / 65535.0
        tilt_combined = (tilt_coarse * 256 + tilt_fine) / 65535.0

        # Center-based mapping: DMX 0..255 → -max/2..+max/2.
        self.pan_deg = (pan_combined - 0.5) * self.movement.pan_max_deg
        self.tilt_deg = (tilt_combined - 0.5) * self.movement.tilt_max_deg


# ---------------------------------------------------------------------------
# Beam-shaping modifiers
# ---------------------------------------------------------------------------


class FocusComponent(FixtureComponent):
    """Focus channel: DMX maps to a focal distance in meters.

    Sharpness depends on how close the projection plane is to the focal
    distance — the renderer asks for ``sharpness(projection_distance)``
    when computing per-frame uniforms.
    """

    MIN_FOCUS_M = 1.0
    MAX_FOCUS_M = 10.0
    BLUR_RATE = 0.3  # falloff width — 50% sharpness at ~1.2m off

    def __init__(self, channel: int):
        self.channel = channel
        self._value = 127

    def update_dmx(self, dmx_data: bytes, address: int) -> None:
        self._value = _read_dmx(dmx_data, address, self.channel)

    @property
    def focal_distance_m(self) -> float:
        return self.MIN_FOCUS_M + (self._value / 255.0) * (self.MAX_FOCUS_M - self.MIN_FOCUS_M)

    def sharpness(self, projection_distance_m: float) -> float:
        err = abs(projection_distance_m - self.focal_distance_m)
        s = math.exp(-err * err * self.BLUR_RATE)
        return max(0.0, min(1.0, s))


class IrisComponent(FixtureComponent):
    """Iris: 0..1 where 1 = fully open."""

    def __init__(self, channel: int):
        self.channel = channel
        self._value = 255

    def update_dmx(self, dmx_data: bytes, address: int) -> None:
        self._value = _read_dmx(dmx_data, address, self.channel)

    @property
    def opening(self) -> float:
        return self._value / 255.0


class FrostComponent(FixtureComponent):
    """Frost: 0..1 where 1 = maximum diffusion."""

    def __init__(self, channel: int):
        self.channel = channel
        self._value = 0

    def update_dmx(self, dmx_data: bytes, address: int) -> None:
        self._value = _read_dmx(dmx_data, address, self.channel)

    @property
    def diffusion(self) -> float:
        return self._value / 255.0


class ZoomComponent(FixtureComponent):
    """Zoom: DMX value → current beam angle within the lens range."""

    def __init__(self, channel: int, beam: BeamShape):
        self.channel = channel
        self.beam = beam
        self._value = 127

    def update_dmx(self, dmx_data: bytes, address: int) -> None:
        self._value = _read_dmx(dmx_data, address, self.channel)

    @property
    def current_angle_deg(self) -> float:
        if not self.beam.is_zoom:
            return self.beam.max_deg
        t = self._value / 255.0
        return self.beam.min_deg + t * (self.beam.max_deg - self.beam.min_deg)


# ---------------------------------------------------------------------------
# Pattern / image
# ---------------------------------------------------------------------------


class GoboComponent(FixtureComponent):
    """Gobo wheel selector + optional rotation channel.

    The pattern ID is derived from the SVG path name in each wheel entry
    (or the entry name) via a small heuristic mapped to the seven
    built-in shader patterns. Rotation speed maps to DMX:
    0 = stop, 1..127 = CW slow→fast, 128..255 = CCW slow→fast.
    """

    MAX_REV_PER_SEC = 1.0

    def __init__(self, wheel: GoboWheel):
        self.wheel = wheel
        self._gobo_value = 0
        self._rotation_value = 0
        self._rotation_rad = 0.0
        self._patterns = [_infer_pattern(entry) for entry in wheel.entries]

    def update_dmx(self, dmx_data: bytes, address: int) -> None:
        self._gobo_value = _read_dmx(dmx_data, address, self.wheel.channel)
        if self.wheel.rotation_channel is not None:
            self._rotation_value = _read_dmx(dmx_data, address, self.wheel.rotation_channel)

    def advance_rotation(self, delta_time: float) -> None:
        """Integrate rotation by ``delta_time`` seconds. Called by the renderer
        once per frame after ``update_dmx``."""
        if self._rotation_value == 0:
            return
        if self._rotation_value < 128:
            speed = (self._rotation_value / 127.0) * 2.0 * math.pi * self.MAX_REV_PER_SEC
        else:
            speed = -((self._rotation_value - 128) / 127.0) * 2.0 * math.pi * self.MAX_REV_PER_SEC
        self._rotation_rad = (self._rotation_rad + speed * delta_time) % (2 * math.pi)

    @property
    def pattern_id(self) -> int:
        if self._gobo_value == 0 or not self.wheel.entries:
            return GOBO_PATTERN_OPEN
        for entry, pid in zip(self.wheel.entries, self._patterns):
            if entry.dmx_min <= self._gobo_value <= entry.dmx_max:
                return pid
        return GOBO_PATTERN_OPEN

    @property
    def rotation_rad(self) -> float:
        return self._rotation_rad


def _infer_pattern(entry) -> int:
    """Map a gobo entry to one of the seven built-in shader patterns.

    Heuristic on the entry name and SVG path: keywords like "dot",
    "star", "line", "triangle", "cross" pick those patterns; everything
    else falls back to BREAKUP. "Open" returns OPEN.
    """
    text = ((entry.name or '') + ' ' + (entry.svg_path or '')).lower()
    if 'open' in text or not text.strip():
        return GOBO_PATTERN_OPEN
    if 'dot' in text or 'circle' in text or 'spot' in text:
        return GOBO_PATTERN_DOTS
    if 'star' in text:
        return GOBO_PATTERN_STAR
    if 'line' in text or 'stripe' in text or 'bar' in text:
        return GOBO_PATTERN_LINES
    if 'triangle' in text or 'tri' in text:
        return GOBO_PATTERN_TRIANGLE
    if 'cross' in text or 'plus' in text:
        return GOBO_PATTERN_CROSS
    return GOBO_PATTERN_BREAKUP


class PrismComponent(FixtureComponent):
    """Prism on/off + facet count."""

    def __init__(self, prism: Prism):
        self.prism = prism
        self._value = 0
        self._rotation_value = 0

    def update_dmx(self, dmx_data: bytes, address: int) -> None:
        self._value = _read_dmx(dmx_data, address, self.prism.channel)
        if self.prism.rotation_channel is not None:
            self._rotation_value = _read_dmx(dmx_data, address, self.prism.rotation_channel)

    @property
    def is_active(self) -> bool:
        # PrismEffectOn typically starts at DMX 128. Be tolerant of fixtures
        # that put the on-range elsewhere by treating any value > 64 as on.
        return self._value > 64

    @property
    def facets(self) -> int:
        return self.prism.facets
