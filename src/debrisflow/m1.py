"""
USGS Staley et al. (2017) M1 post-fire debris-flow likelihood model.

Deliberately small and dependency-free so the math can be tested in isolation,
before any raster or vector data is involved.

IMPORTANT / UNVERIFIED:
    The rainfall term convention (accumulation in mm over the duration vs.
    intensity in mm/hr) MUST be confirmed against Staley et al. (2017) Table 2
    before these coefficients are trusted. For a 15-min duration the two
    conventions differ by a factor of 4. See RainfallConvention below.
"""

from dataclasses import dataclass
from enum import Enum
from math import exp


class RainfallConvention(str, Enum):
    """How the rainfall term R is expressed in the fitted coefficients."""
    ACCUMULATION_MM = "accumulation_mm"   # mm accumulated over the duration
    INTENSITY_MM_HR = "intensity_mm_hr"   # mm/hr peak intensity


# Coefficients keyed by rainfall duration in minutes.
# SOURCE TO VERIFY: Staley et al. (2017), Table 2.
# The 15-min set below is widely reproduced in the literature.
M1_COEFFICIENTS = {
    15: {"b0": -3.63, "b1": 0.41, "b2": 0.67, "b3": 0.70},
    # 30: {...},  # fill in from the paper before use
    # 60: {...},
}

# Convention the coefficients above were fitted under. Change this only after
# reproducing a published USGS basin probability (see validate.py).
ASSUMED_CONVENTION = RainfallConvention.ACCUMULATION_MM


@dataclass(frozen=True)
class BasinPredictors:
    """The three M1 predictors, computed per drainage basin.

    x1: fraction of upslope area that is BOTH >=23 degrees slope AND burned at
        moderate/high severity. This is an intersection, not two separate
        proportions. Range 0-1.
    x2: mean dNBR of the basin, divided by 1000. Typically ~0.1-0.8.
    x3: area-weighted mean soil KF-factor. Typically ~0.02-0.55.
    """
    x1: float
    x2: float
    x3: float

    def __post_init__(self):
        if not 0.0 <= self.x1 <= 1.0:
            raise ValueError(f"x1 must be a fraction in [0, 1], got {self.x1}")
        if not 0.0 <= self.x3 <= 1.0:
            raise ValueError(f"x3 (KF-factor) out of plausible range: {self.x3}")


def to_model_rainfall(value, value_convention, duration_min=15,
                      target_convention=ASSUMED_CONVENTION):
    """Convert a rainfall figure into whatever convention the coefficients want."""
    if value_convention == target_convention:
        return value
    hours = duration_min / 60.0
    if target_convention == RainfallConvention.ACCUMULATION_MM:
        return value * hours          # mm/hr -> mm over the duration
    return value / hours              # mm over the duration -> mm/hr


def likelihood(predictors, rainfall, rainfall_convention, duration_min=15):
    """Debris-flow likelihood P in [0, 1] for one basin under one design storm."""
    try:
        c = M1_COEFFICIENTS[duration_min]
    except KeyError:
        raise ValueError(
            f"No coefficients loaded for a {duration_min}-min duration. "
            "Add them from Staley et al. (2017) Table 2."
        )

    r = to_model_rainfall(rainfall, rainfall_convention, duration_min)

    x = (
        c["b0"]
        + c["b1"] * predictors.x1 * r
        + c["b2"] * predictors.x2 * r
        + c["b3"] * predictors.x3 * r
    )
    return exp(x) / (1.0 + exp(x))


def hazard_class(p):
    """USGS-style discrete rating."""
    if p < 0.2:
        return "Low"
    if p < 0.6:
        return "Moderate"
    return "High"


def rainfall_threshold(predictors, target_p=0.5, duration_min=15,
                       out_convention=RainfallConvention.INTENSITY_MM_HR):
    """Invert M1: the rainfall required to reach target_p for this basin.

    This is the number USGS actually publishes for early warning, and it is
    often more useful than the probability itself.
    """
    from math import log
    c = M1_COEFFICIENTS[duration_min]
    denom = c["b1"] * predictors.x1 + c["b2"] * predictors.x2 + c["b3"] * predictors.x3
    if denom <= 0:
        return float("inf")  # basin can never reach target_p
    r = (log(target_p / (1.0 - target_p)) - c["b0"]) / denom
    return to_model_rainfall(r, ASSUMED_CONVENTION, duration_min, out_convention)
