"""
USGS Staley et al. (2017) M1 post-fire debris-flow likelihood model.

This is a from-scratch teaching / cross-check implementation. The authoritative
implementation is the USGS `pfdf` package (models.staley2017), and production
numbers in this project should be cross-validated against it. This module
exists so the math is transparent and unit-testable, not to replace theirs.

UNITS: RESOLVED.
    The M1 rainfall term R is a rainfall ACCUMULATION IN MILLIMETRES over the
    duration, NOT an intensity in mm/hr. Confirmed against the USGS pfdf
    documentation for models.staley2017, which gives the model form as
    X = B + Ct*T*R + Cf*F*R + Cs*S*R with "R: Rainfall accumulation in mm",
    and separately notes that the staley2017 module works strictly with
    accumulations while gartner2014 (volume) expects intensities.

    Watch out: if this project later adds Gartner 2014 volumes, the two models
    want DIFFERENT rainfall conventions in the same pipeline. Always convert
    explicitly at the call site. Never pass a bare number.

NAMING: deliberately mirrors the USGS pfdf package (B, Ct, Cf, Cs / T, F, S, R)
    so anyone who knows that package can read this without translation.
"""

from dataclasses import dataclass
from enum import Enum
from math import exp, log


class RainfallConvention(str, Enum):
    """How a rainfall figure is expressed."""
    ACCUMULATION_MM = "accumulation_mm"   # mm accumulated over the duration
    INTENSITY_MM_HR = "intensity_mm_hr"   # mm/hr peak intensity


# The model's own convention. This is a fact about M1, not a tunable option.
MODEL_CONVENTION = RainfallConvention.ACCUMULATION_MM

# Published M1 parameters, keyed by rainfall duration in minutes.
# SOURCE: Staley et al. (2017), Geomorphology 278, 149-162.
# CROSS-CHECK REQUIRED: verify against pfdf's M1.parameters() before trusting
# production output. See tests/test_cross_validation.py.
M1_PARAMETERS = {
    15: {"B": -3.63, "Ct": 0.41, "Cf": 0.67, "Cs": 0.70},
    # 30 and 60 minute parameter sets: fill in from the paper when needed.
}


@dataclass(frozen=True)
class BasinVariables:
    """The three M1 predictors for a single drainage basin.

    T (terrain): fraction of upslope area that is BOTH >=23 degrees slope AND
        burned at moderate/high severity. An INTERSECTION, not two separate
        proportions. A basin can be 90% steep and 90% burned while the steep
        parts and the burned parts barely overlap; the model cares about where
        they coincide, because that is where rilling and dry ravel actually
        deliver sediment to the channel. Range 0-1.

    F (fire): mean dNBR of the basin, DIVIDED BY 1000. Continuous, not a class
        proportion. Typically ~0.1-0.8.

    S (soil): area-weighted mean soil KF-factor (erodibility). Typically
        ~0.02-0.55. Note USGS operationally uses STATSGO; SSURGO is finer but
        is a deviation from the calibration data, so say so in the writeup.
    """
    T: float
    F: float
    S: float

    def __post_init__(self):
        if not 0.0 <= self.T <= 1.0:
            raise ValueError(f"T must be a fraction in [0, 1], got {self.T}")
        if not 0.0 <= self.S <= 1.0:
            raise ValueError(f"S (KF-factor) out of plausible range: {self.S}")
        if self.F < 0.0:
            raise ValueError(f"F (dNBR/1000) should not be negative: {self.F}")


def convert_rainfall(value, frm, to, duration_min=15):
    """Convert a rainfall figure between intensity and accumulation.

    Over a 15 minute duration these differ by a factor of 4, so getting this
    wrong silently produces a plausible-looking but wrong hazard map.
    """
    if frm == to:
        return value
    hours = duration_min / 60.0
    if to == RainfallConvention.ACCUMULATION_MM:
        return value * hours          # mm/hr -> mm over the duration
    return value / hours              # mm over the duration -> mm/hr


def likelihood(variables, rainfall, convention, duration_min=15):
    """Debris-flow likelihood p in [0, 1] for one basin under one design storm.

    `convention` is REQUIRED and has no default, on purpose. Forcing the caller
    to state the units is the cheapest possible guard against the 4x error.
    """
    try:
        p = M1_PARAMETERS[duration_min]
    except KeyError:
        raise ValueError(
            f"No M1 parameters loaded for a {duration_min}-minute duration. "
            "Add them from Staley et al. (2017)."
        )

    # Convert whatever the caller handed us into the model's own units.
    R = convert_rainfall(rainfall, convention, MODEL_CONVENTION, duration_min)

    X = (
        p["B"]
        + p["Ct"] * variables.T * R
        + p["Cf"] * variables.F * R
        + p["Cs"] * variables.S * R
    )
    return exp(X) / (1.0 + exp(X))


def accumulation(variables, target_p=0.5, duration_min=15,
                 out_convention=RainfallConvention.INTENSITY_MM_HR):
    """Invert M1: the rainfall needed for this basin to reach target_p.

    This is the number USGS publishes for early warning, because a forecaster
    can compare it directly against a predicted storm cell intensity. Named to
    match pfdf's `accumulation` solver, but defaults to returning mm/hr since
    that is what operational products quote.
    """
    p = M1_PARAMETERS[duration_min]
    denom = p["Ct"] * variables.T + p["Cf"] * variables.F + p["Cs"] * variables.S
    if denom <= 0:
        return float("inf")  # basin can never reach target_p at any rainfall
    R = (log(target_p / (1.0 - target_p)) - p["B"]) / denom
    return convert_rainfall(R, MODEL_CONVENTION, out_convention, duration_min)


def hazard_class(p):
    """Discrete rating used for map symbology."""
    if p < 0.2:
        return "Low"
    if p < 0.6:
        return "Moderate"
    return "High"
