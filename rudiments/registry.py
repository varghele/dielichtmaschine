"""Registry of all available rudiments with their envelopes and parameters."""

import math
from typing import Dict, Optional

from rudiments.rudiment import (
    Rudiment, RudimentType, FluxEnvelope, RudimentParameter,
    EnvelopeCategory, CycleMode,
)


# ──────────────────────────────────────────────
# Envelope generation helpers
# ──────────────────────────────────────────────

def _flat(n=32):
    return [1.0] * n

def _spike(n=32):
    peak = n // 2
    return [math.exp(-abs(i - peak) * 0.5) for i in range(n)]

def _sine(n=32):
    return [(math.sin(2 * math.pi * i / n) + 1) / 2 for i in range(n)]

def _square(n=32):
    return [1.0 if i < n // 2 else 0.0 for i in range(n)]

def _sawtooth(n=32):
    return [i / (n - 1) for i in range(n)]

def _ramp_up(n=32):
    return [i / (n - 1) for i in range(n)]

def _rolling(n=32):
    """Chase/waterfall envelope — rolling sawtooth-like."""
    return [0.5 * (1 + math.sin(2 * math.pi * i / n - math.pi / 2)) for i in range(n)]

def _stochastic(n=32):
    """Sparkle/random stroke — irregular pattern (deterministic)."""
    import hashlib
    result = []
    for i in range(n):
        h = int(hashlib.md5(f"stoch_{i}".encode()).hexdigest()[:4], 16)
        result.append((h % 100) / 100.0)
    return result

def _heartbeat(n=32):
    """Double-pulse pattern."""
    result = []
    for i in range(n):
        pos = i / n
        if pos < 0.10:
            result.append(pos / 0.10)
        elif pos < 0.20:
            result.append(1.0 - 0.4 * ((pos - 0.10) / 0.10))
        elif pos < 0.30:
            result.append(0.6 + 0.2 * ((pos - 0.20) / 0.10))
        elif pos < 0.50:
            result.append(0.8 * (1 - (pos - 0.30) / 0.20))
        else:
            result.append(0.0)
    return result

def _cascade(n=32, build_frac=0.7):
    """Build up then sharp release."""
    result = []
    for i in range(n):
        pos = i / n
        if pos < build_frac:
            result.append(pos / build_frac)
        else:
            release = (pos - build_frac) / (1 - build_frac)
            result.append(max(0.0, 1.0 - release * 3))
    return result

def _fill_envelope(n=32):
    """Fill: ramp up then ramp down (center-out then back)."""
    half = n // 2
    return [i / half if i < half else (n - i) / half for i in range(n)]

def _throb(n=32):
    """Sharp attack with 70% floor."""
    return [0.7 + 0.3 * math.exp(-4 * i / n) for i in range(n)]


# ──────────────────────────────────────────────
# Intensity Rudiments
# ──────────────────────────────────────────────

INTENSITY_RUDIMENTS: Dict[str, Rudiment] = {}
MOVEMENT_RUDIMENTS: Dict[str, Rudiment] = {}


def _register_intensity_rudiments():
    defs = [
        ("static", "All fixtures at constant intensity",
         FluxEnvelope(_flat(), EnvelopeCategory.FLAT, CycleMode.ONE_SHOT),
         [RudimentParameter("intensity", "float", 1.0, 0.0, 1.0)]),

        ("stroke", "Instant attack to full, exponential decay to zero",
         FluxEnvelope(_spike(), EnvelopeCategory.SPIKE, CycleMode.CYCLING),
         [RudimentParameter("intensity", "float", 1.0, 0.0, 1.0),
          RudimentParameter("speed", "float", 1.0, 0.25, 4.0)]),

        ("throb", "Sharp attack, exponential decay to 70% floor",
         FluxEnvelope(_throb(), EnvelopeCategory.OSCILLATING, CycleMode.CYCLING),
         [RudimentParameter("intensity", "float", 1.0, 0.0, 1.0),
          RudimentParameter("speed", "float", 1.0, 0.25, 4.0)]),

        ("ping_pong", "Intensity alternates between fixtures in a bounce pattern",
         FluxEnvelope(_square(), EnvelopeCategory.OSCILLATING, CycleMode.CYCLING),
         [RudimentParameter("intensity", "float", 1.0, 0.0, 1.0),
          RudimentParameter("speed", "float", 1.0, 0.25, 4.0)]),

        ("chase", "Sequential fixture activation bouncing back and forth",
         FluxEnvelope(_rolling(), EnvelopeCategory.ROLLING, CycleMode.CYCLING),
         [RudimentParameter("intensity", "float", 1.0, 0.0, 1.0),
          RudimentParameter("speed", "float", 1.0, 0.25, 4.0),
          RudimentParameter("chase_scope", "enum", "fixture", enum_values=["fixture", "global"],
                           description="fixture=per-fixture, global=cross-fixture chain")]),

        ("wave", "Intensity wave travels across fixtures",
         FluxEnvelope(_sine(), EnvelopeCategory.ROLLING, CycleMode.CYCLING),
         [RudimentParameter("intensity", "float", 1.0, 0.0, 1.0),
          RudimentParameter("speed", "float", 1.0, 0.25, 4.0)]),

        ("waterfall", "Light cascades through segments with drifting offset",
         FluxEnvelope(_rolling(), EnvelopeCategory.ROLLING, CycleMode.CYCLING),
         [RudimentParameter("intensity", "float", 1.0, 0.0, 1.0),
          RudimentParameter("speed", "float", 1.0, 0.25, 4.0),
          RudimentParameter("direction", "enum", "down", enum_values=["down", "up"])]),

        ("fill", "Progressive fill from center outward, then unfill",
         FluxEnvelope(_fill_envelope(), EnvelopeCategory.RAMP, CycleMode.CYCLING),
         [RudimentParameter("intensity", "float", 1.0, 0.0, 1.0),
          RudimentParameter("speed", "float", 1.0, 0.25, 4.0)]),

        ("random_stroke", "Fixtures activate in unpredictable shuffled order",
         FluxEnvelope(_stochastic(), EnvelopeCategory.STOCHASTIC, CycleMode.CYCLING),
         [RudimentParameter("intensity", "float", 1.0, 0.0, 1.0),
          RudimentParameter("speed", "float", 1.0, 0.25, 4.0)]),

        ("sparkle", "Short random flashes per segment with smooth transitions",
         FluxEnvelope(_stochastic(), EnvelopeCategory.STOCHASTIC, CycleMode.CYCLING),
         [RudimentParameter("intensity", "float", 1.0, 0.0, 1.0),
          RudimentParameter("speed", "float", 1.0, 0.25, 4.0)]),

        ("pulse", "Smooth sine breathing, one cycle per bar",
         FluxEnvelope(_sine(), EnvelopeCategory.OSCILLATING, CycleMode.CYCLING),
         [RudimentParameter("intensity", "float", 1.0, 0.0, 1.0),
          RudimentParameter("speed", "float", 1.0, 0.25, 4.0),
          RudimentParameter("phase_offset_per_fixture", "bool", False,
                           description="Spread phase across fixtures for wave effect")]),

        ("strobe", "Rapid on/off flashing",
         FluxEnvelope(_square(), EnvelopeCategory.OSCILLATING, CycleMode.CYCLING),
         [RudimentParameter("intensity", "float", 1.0, 0.0, 1.0),
          RudimentParameter("speed", "float", 1.0, 0.25, 4.0)]),

        ("fade", "Linear intensity ramp over block duration",
         FluxEnvelope(_ramp_up(), EnvelopeCategory.RAMP, CycleMode.ONE_SHOT),
         [RudimentParameter("direction", "enum", "in", enum_values=["in", "out"])]),

        ("cascade", "Accumulative build followed by sharp release",
         FluxEnvelope(_cascade(), EnvelopeCategory.SPIKE, CycleMode.ONE_SHOT),
         [RudimentParameter("build_fraction", "float", 0.7, 0.1, 0.95,
                           description="Portion of block spent building (0.0-1.0)")]),

        ("heartbeat", "Double-pulse pattern (bump-bump... pause...)",
         FluxEnvelope(_heartbeat(), EnvelopeCategory.OSCILLATING, CycleMode.CYCLING),
         [RudimentParameter("intensity", "float", 1.0, 0.0, 1.0),
          RudimentParameter("speed", "float", 1.0, 0.25, 4.0)]),
    ]

    for name, desc, envelope, params in defs:
        r = Rudiment(
            name=name,
            rudiment_type=RudimentType.INTENSITY,
            envelope=envelope,
            parameters=params,
            effect_function=name,  # Registry key matches rudiment name
            description=desc,
        )
        r.compute_average_flux()
        INTENSITY_RUDIMENTS[name] = r


# ──────────────────────────────────────────────
# Movement Rudiments
# ──────────────────────────────────────────────

def _register_movement_rudiments():
    defs = [
        ("static", "Fixed pan/tilt position",
         FluxEnvelope(_flat(), EnvelopeCategory.FLAT, CycleMode.ONE_SHOT),
         [RudimentParameter("pan", "float", 127.5, 0.0, 255.0),
          RudimentParameter("tilt", "float", 127.5, 0.0, 255.0)]),

        ("circle", "Circular sweep",
         FluxEnvelope(_sine(), EnvelopeCategory.OSCILLATING, CycleMode.CYCLING),
         [RudimentParameter("amplitude", "float", 50.0, 0.0, 127.0),
          RudimentParameter("speed", "float", 1.0, 0.25, 4.0)]),

        ("figure_8", "Figure-eight pattern",
         FluxEnvelope(_sine(), EnvelopeCategory.OSCILLATING, CycleMode.CYCLING),
         [RudimentParameter("amplitude", "float", 50.0, 0.0, 127.0),
          RudimentParameter("speed", "float", 1.0, 0.25, 4.0)]),

        ("lissajous", "Configurable frequency ratio pattern",
         FluxEnvelope(_sine(), EnvelopeCategory.OSCILLATING, CycleMode.CYCLING),
         [RudimentParameter("amplitude", "float", 50.0, 0.0, 127.0),
          RudimentParameter("speed", "float", 1.0, 0.25, 4.0),
          RudimentParameter("freq_ratio", "enum", "1:2",
                           enum_values=["1:2", "2:3", "3:4", "3:2", "4:3", "1:3", "2:1", "3:1"])]),

        ("linear_sweep", "Back-and-forth along one axis",
         FluxEnvelope(_sawtooth(), EnvelopeCategory.ROLLING, CycleMode.CYCLING),
         [RudimentParameter("amplitude", "float", 50.0, 0.0, 127.0),
          RudimentParameter("speed", "float", 1.0, 0.25, 4.0)]),

        ("diamond", "4-corner diamond path",
         FluxEnvelope(_sine(), EnvelopeCategory.OSCILLATING, CycleMode.CYCLING),
         [RudimentParameter("amplitude", "float", 50.0, 0.0, 127.0),
          RudimentParameter("speed", "float", 1.0, 0.25, 4.0)]),

        ("square", "4-corner square path",
         FluxEnvelope(_sine(), EnvelopeCategory.OSCILLATING, CycleMode.CYCLING),
         [RudimentParameter("amplitude", "float", 50.0, 0.0, 127.0),
          RudimentParameter("speed", "float", 1.0, 0.25, 4.0)]),

        ("triangle", "3-corner triangular path",
         FluxEnvelope(_sine(), EnvelopeCategory.OSCILLATING, CycleMode.CYCLING),
         [RudimentParameter("amplitude", "float", 50.0, 0.0, 127.0),
          RudimentParameter("speed", "float", 1.0, 0.25, 4.0)]),

        ("random", "Smooth pseudo-random motion",
         FluxEnvelope(_stochastic(), EnvelopeCategory.STOCHASTIC, CycleMode.CYCLING),
         [RudimentParameter("amplitude", "float", 50.0, 0.0, 127.0),
          RudimentParameter("speed", "float", 1.0, 0.25, 4.0)]),

        ("bounce", "Triangle wave back and forth",
         FluxEnvelope(_sawtooth(), EnvelopeCategory.OSCILLATING, CycleMode.CYCLING),
         [RudimentParameter("amplitude", "float", 50.0, 0.0, 127.0),
          RudimentParameter("speed", "float", 1.0, 0.25, 4.0)]),

        ("fan", "Synchronized spread/converge across fixture group",
         FluxEnvelope(_sine(), EnvelopeCategory.OSCILLATING, CycleMode.CYCLING),
         [RudimentParameter("spread_angle", "float", 45.0, 0.0, 180.0),
          RudimentParameter("speed", "float", 1.0, 0.25, 4.0)]),
    ]

    for name, desc, envelope, params in defs:
        r = Rudiment(
            name=name,
            rudiment_type=RudimentType.MOVEMENT,
            envelope=envelope,
            parameters=params,
            effect_function=name,
            description=desc,
        )
        r.compute_average_flux()
        MOVEMENT_RUDIMENTS[name] = r


# Initialize on import
_register_intensity_rudiments()
_register_movement_rudiments()


# ──────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────

def get_rudiment(name: str) -> Optional[Rudiment]:
    return INTENSITY_RUDIMENTS.get(name) or MOVEMENT_RUDIMENTS.get(name)

def get_intensity_rudiments() -> Dict[str, Rudiment]:
    return INTENSITY_RUDIMENTS

def get_movement_rudiments() -> Dict[str, Rudiment]:
    return MOVEMENT_RUDIMENTS
