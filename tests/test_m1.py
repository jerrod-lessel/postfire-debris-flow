import math
import pytest

from debrisflow.m1 import (
    BasinVariables, RainfallConvention, likelihood, hazard_class,
    accumulation, convert_rainfall,
)

MM_HR = RainfallConvention.INTENSITY_MM_HR
MM = RainfallConvention.ACCUMULATION_MM


def test_zero_rainfall_gives_intercept_only():
    """With no rain, P collapses to the logistic of b0 alone."""
    b = BasinVariables(T=0.5, F=0.4, S=0.3)
    p = likelihood(b, 0.0, MM_HR)
    assert p == pytest.approx(math.exp(-3.63) / (1 + math.exp(-3.63)), rel=1e-9)


def test_probability_increases_with_rainfall():
    b = BasinVariables(T=0.4, F=0.5, S=0.3)
    ps = [likelihood(b, i, MM_HR) for i in (12, 24, 40)]
    assert ps[0] < ps[1] < ps[2]


def test_probability_increases_with_each_predictor():
    base = BasinVariables(T=0.2, F=0.3, S=0.2)
    p0 = likelihood(base, 24, MM_HR)
    assert likelihood(BasinVariables(0.6, 0.3, 0.2), 24, MM_HR) > p0
    assert likelihood(BasinVariables(0.2, 0.7, 0.2), 24, MM_HR) > p0
    assert likelihood(BasinVariables(0.2, 0.3, 0.5), 24, MM_HR) > p0


def test_unburned_flat_basin_is_low_hazard():
    b = BasinVariables(T=0.0, F=0.02, S=0.15)
    assert hazard_class(likelihood(b, 40, MM_HR)) == "Low"


def _logit(p):
    return math.log(p / (1 - p))


def test_unit_convention_is_exactly_four_x_at_15_min():
    """The trap. Probabilities saturate near 1, so it only shows in log-odds:
    the rainfall-dependent part of x scales linearly with r."""
    b = BasinVariables(T=0.45, F=0.55, S=0.35)
    b0 = -3.63
    rain_term_intensity = _logit(likelihood(b, 24, MM_HR)) - b0
    rain_term_accum = _logit(likelihood(b, 24, MM)) - b0
    assert rain_term_accum / rain_term_intensity == pytest.approx(4.0, rel=1e-9)


def test_unit_error_can_flip_the_hazard_class():
    """Why it matters operationally: a modest basin reads Low under one
    convention and High under the other, from the same rain figure."""
    b = BasinVariables(T=0.15, F=0.35, S=0.25)
    assert hazard_class(likelihood(b, 12, MM_HR)) == "Low"
    assert hazard_class(likelihood(b, 12, MM)) == "High"


def test_conversion_roundtrip():
    assert convert_rainfall(24, MM_HR, MM, 15) == pytest.approx(6.0)
    assert convert_rainfall(6, MM, MM_HR, 15) == pytest.approx(24.0)


def test_threshold_inverts_likelihood():
    """accumulation and likelihood must agree with each other."""
    b = BasinVariables(T=0.35, F=0.5, S=0.3)
    r = accumulation(b, target_p=0.5, out_convention=MM_HR)
    assert likelihood(b, r, MM_HR) == pytest.approx(0.5, rel=1e-9)


def test_null_basin_can_never_reach_threshold():
    b = BasinVariables(T=0.0, F=0.0, S=0.0)
    assert accumulation(b) == float("inf")


def test_rejects_impossible_predictors():
    with pytest.raises(ValueError):
        BasinVariables(T=1.4, F=0.3, S=0.2)
    with pytest.raises(ValueError):
        BasinVariables(T=0.3, F=0.3, S=12.0)


def test_missing_duration_fails_loudly():
    b = BasinVariables(T=0.3, F=0.3, S=0.2)
    with pytest.raises(ValueError, match="Staley"):
        likelihood(b, 20, MM_HR, duration_min=60)
