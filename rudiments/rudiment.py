from dataclasses import dataclass, field
from enum import Enum
from typing import List, Any


class RudimentType(Enum):
    INTENSITY = "intensity"
    MOVEMENT = "movement"


class EnvelopeCategory(Enum):
    FLAT = "flat"
    SPIKE = "spike"
    OSCILLATING = "oscillating"
    RAMP = "ramp"
    ROLLING = "rolling"
    STOCHASTIC = "stochastic"


class CycleMode(Enum):
    CYCLING = "cycling"
    ONE_SHOT = "one_shot"


@dataclass
class FluxEnvelope:
    """Normalized flux envelope for a rudiment.

    For cycling rudiments: describes one cycle.
    For one-shot rudiments: describes the full duration.
    Values normalized to 0.0-1.0, sampled at `resolution` points.
    """
    samples: List[float]
    category: EnvelopeCategory
    cycle_mode: CycleMode
    resolution: int = 32


@dataclass
class RudimentParameter:
    """Definition of a configurable parameter on a rudiment."""
    name: str
    param_type: str  # "float", "int", "enum", "direction"
    default: Any
    min_value: Any = None
    max_value: Any = None
    enum_values: List[str] = field(default_factory=list)
    description: str = ""


@dataclass
class Rudiment:
    """Atomic lighting pattern definition."""
    name: str
    rudiment_type: RudimentType
    envelope: FluxEnvelope
    parameters: List[RudimentParameter]
    effect_function: str  # Key into DIMMER_REGISTRY or MOVEMENT_REGISTRY
    description: str = ""
    average_flux: float = 0.0

    def compute_average_flux(self):
        if self.envelope.samples:
            self.average_flux = sum(self.envelope.samples) / len(self.envelope.samples)
