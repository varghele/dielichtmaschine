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
renderer), the embedded preview, the .qxw export and every test consume
it unchanged - and the rig ends up matching the visualizer. Only
fixtures that render through the GDTF chain are converted, exactly the
ones whose visualizer render also converts, so procedural fixtures stay
consistent end to end.
"""

from functools import lru_cache
from typing import Tuple

from utils.orientation import pan_tilt_to_dmx16


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
def gdtf_chain_yoke(manufacturer: str, model: str,
                    mode: str) -> Tuple[bool, bool]:
    """``(uses_chain, flipped)`` for a fixture identity.

    - ``uses_chain``: a GDTF definition exists for this fixture, so it
      renders through the geometry chain - the case that needs the
      output conversion (procedural fixtures do not).
    - ``flipped``: the chain's authoring posture (hanging-authored tree),
      which selects the conversion's sign branch.

    Cached by identity; the lazy imports keep the DMX thread clear of
    the renderer package until a GDTF mover is actually on the wire.
    """
    try:
        from utils.fixture_library import get_definition
        defn = get_definition(manufacturer, model)
        if defn is None or getattr(defn, "gdtf", None) is None:
            return (False, False)
        from visualizer.renderer.gdtf_draw_plan import build_draw_plan
        plan = build_draw_plan(defn.gdtf, mode)
        return (True, bool(getattr(plan, "flipped", False)))
    except Exception:
        return (False, False)


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


def apply_yoke_to_universe(buf: bytearray, fmap, flipped: bool) -> None:
    """In place: rewrite one mover's pan/tilt (coarse + fine) in a
    universe buffer from solver convention to the real yoke. No-op if
    the map has no pan/tilt channels."""
    if not (fmap.pan_channels and fmap.tilt_channels):
        return
    pan_solver = _decode16(buf, fmap, fmap.pan_channels,
                           fmap.pan_fine_channels, fmap.pan_range)
    tilt_solver = _decode16(buf, fmap, fmap.tilt_channels,
                            fmap.tilt_fine_channels, fmap.tilt_range)
    pan_g, tilt_g = solver_to_gdtf_axes(pan_solver, tilt_solver, flipped)
    pan_c, pan_f, tilt_c, tilt_f = pan_tilt_to_dmx16(
        pan_g, tilt_g, fmap.pan_range, fmap.tilt_range)
    _write(buf, fmap, fmap.pan_channels, pan_c)
    _write(buf, fmap, fmap.pan_fine_channels, pan_f)
    _write(buf, fmap, fmap.tilt_channels, tilt_c)
    _write(buf, fmap, fmap.tilt_fine_channels, tilt_f)
