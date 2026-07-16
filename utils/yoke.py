# utils/yoke.py
"""Solver -> real-fixture yoke conversion, applied at the DMX OUTPUT
boundary (found on hardware 2026-07-13).

Two yoke models are in play:

- The app's SOLVER (utils/orientation.calculate_pan_tilt) and the
  procedural chassis: beam +X at home, pan about local Z, tilt about
  local Y - the beam at tilt centre is PERPENDICULAR to the pan axis.
- A REAL moving head, and the GDTF geometry chain that mirrors it: pan
  about the mount's vertical axis, tilt about the head's axis, beam
  ALONG the pan axis at tilt centre.

Feeding solver-convention pan/tilt straight to a real head aims it
elsewhere - a straight-down target comes out horizontal (90 deg off,
measured on the bench). The VISUALIZER already converts on its render
side (visualizer/renderer/gdtf_mesh_chassis via solver_to_gdtf_axes),
which is why it looked right while the wire did not.

This module lets the OutputArbiter apply that same conversion to the
packets bound for the PHYSICAL node only. The internal DMX stays
solver-convention, so the visualizer (which converts in its own
renderer), the embedded preview and every test consume it unchanged -
and the rig ends up matching the visualizer. EVERY mover with a
resolvable definition is converted (see fixture_yoke): GDTF fixtures
via their own geometry chain, .qxf-only fixtures via a synthetic
standard yoke, because real heads are built the same way regardless of
definition format. The .qxw EXPORT applies the same conversion at
generation time (utils/to_xml, 2026-07-13) so QLC+ playback aims like
native output.
"""

from functools import lru_cache
from typing import Tuple

from utils.orientation import (
    calculate_pan_tilt,
    pan_tilt_to_dmx,
    pan_tilt_to_dmx16,
)


def solver_to_gdtf_axes(pan_deg: float, tilt_deg: float,
                        flipped: bool = True) -> Tuple[float, float]:
    """Map solver-convention pan/tilt onto the real (GDTF-chain) yoke
    axes. Thin re-export of the renderer's pure function so output-side
    callers have a GL-free import site (the target lives in the
    renderer package for the render side; it imports only numpy)."""
    from visualizer.renderer.gdtf_draw_plan import (
        solver_to_gdtf_axes as _impl,
    )
    return _impl(pan_deg, tilt_deg, flipped)


@lru_cache(maxsize=256)
def fixture_yoke(manufacturer: str, model: str,
                 mode: str) -> Tuple[bool, bool]:
    """``(convert, flipped)`` for a fixture identity.

    EVERY mover gets the real-yoke conversion on the wire - real moving
    heads are built the same way regardless of definition format:

    - GDTF definition: ``flipped`` comes from the geometry chain's
      authoring posture (hanging-authored tree), so the conversion
      matches the exact file the visualizer renders.
    - .qxf-only definition (no geometry tree): the fixture is brought
      to the GDTF standard with a SYNTHETIC yoke - the hanging-authored
      branch, the one verified against real hardware (bench protocol
      2026-07-13). Fixtures whose real DMX direction differs need the
      per-fixture invert flags (future work), same as on any console.

    ``convert`` is False only when no definition resolves at all (the
    caller additionally gates on the map having pan+tilt channels, so
    non-movers never reach the conversion).

    Cached by identity; the lazy imports keep the DMX thread clear of
    the renderer package until a mover is actually on the wire.
    """
    try:
        from utils.fixture_library import get_definition
        defn = get_definition(manufacturer, model)
        if defn is None:
            return (False, False)
        if getattr(defn, "gdtf", None) is None:
            return (True, True)   # synthetic standard yoke for .qxf
        from visualizer.renderer.gdtf_draw_plan import build_draw_plan
        plan = build_draw_plan(defn.gdtf, mode)
        return (True, bool(getattr(plan, "flipped", False)))
    except Exception:
        return (False, False)






@lru_cache(maxsize=256)
def _physical_ranges(manufacturer: str, model: str) -> Tuple[float, float]:
    """(pan_range, tilt_range) from the definition's <Physical><Focus>,
    with the historical 540/270 defaults when absent or zero."""
    try:
        from utils.fixture_library import get_definition
        defn = get_definition(manufacturer, model)
        pan = float(getattr(defn, "pan_max", 0.0) or 0.0)
        tilt = float(getattr(defn, "tilt_max", 0.0) or 0.0)
        return (pan or 540.0, tilt or 270.0)
    except Exception:
        return (540.0, 270.0)


def physical_ranges(manufacturer: str, model: str) -> Tuple[float, float]:
    """Public accessor for the definition's physical pan/tilt travel
    (utils/movement_migration.py decodes stored solver DMX with it)."""
    return _physical_ranges(manufacturer, model)


def export_aim_dmx(fixture, fixture_z: float,
                   target: Tuple[float, float, float],
                   mounting: str, yaw: float, pitch: float,
                   roll: float) -> Tuple[int, int]:
    """8-bit pan/tilt DMX for the .qxw EXPORT, aimed like native output.

    Aims with the solver at the definition's physical ranges, then
    converts to the real yoke (fixture_yoke) - so QLC+ playback lands a
    spot target where the app and the rig do. Before 2026-07-13 the
    export emitted raw solver angles at hardcoded 540/270, which aims a
    real mover elsewhere (a straight-down target came out horizontal on
    the bench). NOTE: movement PATTERNS in the sequence path still
    oscillate in solver DMX space around this converted centre; per-step
    pattern conversion is the range-aware-export leftover (v1.5a).
    """
    pan_range, tilt_range = _physical_ranges(fixture.manufacturer,
                                             fixture.model)
    pan_deg, tilt_deg = calculate_pan_tilt(
        fixture_x=fixture.x, fixture_y=fixture.y, fixture_z=fixture_z,
        target_x=target[0], target_y=target[1], target_z=target[2],
        mounting=mounting, yaw=yaw, pitch=pitch, roll=roll,
        pan_range=pan_range, tilt_range=tilt_range)
    convert, flipped = fixture_yoke(fixture.manufacturer, fixture.model,
                                    getattr(fixture, "current_mode", ""))
    if convert:
        pan_deg, tilt_deg = solver_to_gdtf_axes(pan_deg, tilt_deg, flipped)
    pan_out, tilt_out = pan_tilt_to_dmx(pan_deg, tilt_deg,
                                        pan_range, tilt_range)
    # Per-fixture DMX direction inversion (v1.5a).
    if getattr(fixture, "invert_pan", False):
        pan_out = 255 - pan_out
    if getattr(fixture, "invert_tilt", False):
        tilt_out = 255 - tilt_out
    return pan_out, tilt_out


def export_solver_aim_dmx(fixture, fixture_z: float,
                          target: Tuple[float, float, float],
                          mounting: str, yaw: float, pitch: float,
                          roll: float) -> Tuple[int, int]:
    """SOLVER-convention 8-bit pan/tilt for a spot aim at the
    definition's physical ranges - NO yoke conversion.

    The export's movement-sequence path builds its shape math on this
    (offsets in solver DMX space, exactly like the native renderer),
    then converts EACH STEP through :func:`convert_solver_dmx`.
    :func:`export_aim_dmx` remains the one-shot static aim (degrees
    end to end, one quantisation)."""
    pan_range, tilt_range = _physical_ranges(fixture.manufacturer,
                                             fixture.model)
    pan_deg, tilt_deg = calculate_pan_tilt(
        fixture_x=fixture.x, fixture_y=fixture.y, fixture_z=fixture_z,
        target_x=target[0], target_y=target[1], target_z=target[2],
        mounting=mounting, yaw=yaw, pitch=pitch, roll=roll,
        pan_range=pan_range, tilt_range=tilt_range)
    return pan_tilt_to_dmx(pan_deg, tilt_deg, pan_range, tilt_range)


def convert_solver_dmx(fixture, pan_dmx: float,
                       tilt_dmx: float) -> Tuple[int, int]:
    """An 8-bit SOLVER-convention pan/tilt pair -> the real-yoke 8-bit
    pair for the .qxw export's movement-sequence steps, at the
    fixture's physical ranges - the per-step equivalent of what the
    output arbiter does to native packets (apply_yoke_to_universe).

    Before 2026-07-13 the exported movement patterns oscillated in
    solver DMX space around a yoke-converted centre - a mixed frame
    that traced the wrong figure on a real head. Now the whole step is
    computed in solver space and converted here, so QLC+ playback
    moves like native output. Identity (int-clamped) when no
    definition resolves, so fixtures without a known yoke export
    unchanged."""
    pan_dmx = max(0.0, min(255.0, float(pan_dmx)))
    tilt_dmx = max(0.0, min(255.0, float(tilt_dmx)))
    convert, flipped = fixture_yoke(fixture.manufacturer, fixture.model,
                                    getattr(fixture, "current_mode", ""))
    if not convert:
        pan_out, tilt_out = int(pan_dmx), int(tilt_dmx)
    else:
        pan_range, tilt_range = _physical_ranges(fixture.manufacturer,
                                                 fixture.model)
        # Inverse of pan_tilt_to_dmx's 8-bit encode (127 = centre).
        pan_deg = (pan_dmx - 127.0) / 127.0 * (pan_range / 2.0)
        tilt_deg = (tilt_dmx - 127.0) / 127.0 * (tilt_range / 2.0)
        pan_g, tilt_g = solver_to_gdtf_axes(pan_deg, tilt_deg, flipped)
        pan_out, tilt_out = pan_tilt_to_dmx(pan_g, tilt_g,
                                            pan_range, tilt_range)
    # Per-fixture DMX direction inversion (v1.5a) - physical truth,
    # applied whether or not a yoke chain resolved.
    if getattr(fixture, "invert_pan", False):
        pan_out = 255 - pan_out
    if getattr(fixture, "invert_tilt", False):
        tilt_out = 255 - tilt_out
    return pan_out, tilt_out


def _decode16(buf, fmap, coarse_offsets, fine_offsets, rng: float) -> float:
    """Decode a channel's coarse(+fine) bytes to degrees from centre."""
    if not coarse_offsets:
        return 0.0
    _, c_ch = fmap.get_absolute_address(coarse_offsets[0])
    if not 0 <= c_ch < 512:
        return 0.0
    coarse = buf[c_ch]
    fine = 0
    if fine_offsets:
        _, f_ch = fmap.get_absolute_address(fine_offsets[0])
        if 0 <= f_ch < 512:
            fine = buf[f_ch]
    return ((coarse * 256 + fine) / 65535.0 - 0.5) * rng


def _write(buf, fmap, offsets, value: int) -> None:
    for offset in offsets or ():
        _, ch = fmap.get_absolute_address(offset)
        if 0 <= ch < 512:
            buf[ch] = value


def _read16(buf, fmap, coarse_offsets, fine_offsets) -> Tuple[int, int]:
    coarse, fine = 0, 0
    if coarse_offsets:
        _, ch = fmap.get_absolute_address(coarse_offsets[0])
        if 0 <= ch < 512:
            coarse = buf[ch]
    if fine_offsets:
        _, ch = fmap.get_absolute_address(fine_offsets[0])
        if 0 <= ch < 512:
            fine = buf[ch]
    return coarse, fine


def _invert16(coarse: int, fine: int) -> Tuple[int, int]:
    value = 65535 - (coarse * 256 + fine)
    return (value >> 8) & 0xFF, value & 0xFF


def apply_yoke_to_universe(buf: bytearray, fmap, flipped: bool,
                           convert: bool = True,
                           invert_pan: bool = False,
                           invert_tilt: bool = False) -> None:
    """In place: rewrite one mover's pan/tilt (coarse + fine) in a
    universe buffer from solver convention to the real yoke, then apply
    the per-fixture DMX direction inversion (v1.5a: a head whose
    physical rotation runs opposite to its definition). ``convert=False``
    skips the yoke math (no resolvable chain) but still inverts. No-op
    if the map has no pan/tilt channels."""
    if not (fmap.pan_channels and fmap.tilt_channels):
        return
    if convert:
        pan_solver = _decode16(buf, fmap, fmap.pan_channels,
                               fmap.pan_fine_channels, fmap.pan_range)
        tilt_solver = _decode16(buf, fmap, fmap.tilt_channels,
                                fmap.tilt_fine_channels, fmap.tilt_range)
        pan_g, tilt_g = solver_to_gdtf_axes(pan_solver, tilt_solver,
                                            flipped)
        pan_c, pan_f, tilt_c, tilt_f = pan_tilt_to_dmx16(
            pan_g, tilt_g, fmap.pan_range, fmap.tilt_range)
    else:
        pan_c, pan_f = _read16(buf, fmap, fmap.pan_channels,
                               fmap.pan_fine_channels)
        tilt_c, tilt_f = _read16(buf, fmap, fmap.tilt_channels,
                                 fmap.tilt_fine_channels)
    if invert_pan:
        pan_c, pan_f = _invert16(pan_c, pan_f)
    if invert_tilt:
        tilt_c, tilt_f = _invert16(tilt_c, tilt_f)
    _write(buf, fmap, fmap.pan_channels, pan_c)
    _write(buf, fmap, fmap.pan_fine_channels, pan_f)
    _write(buf, fmap, fmap.tilt_channels, tilt_c)
    _write(buf, fmap, fmap.tilt_fine_channels, tilt_f)
