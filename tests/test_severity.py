import numpy as np
import pytest

from debrisflow.severity import (
    to_reflectance, needs_baseline_offset, nbr, dnbr, dnbr_offset,
    severity_class, moderate_high_mask, basin_F,
)


# --- scaling and the Baseline 04.00 offset ------------------------------------

def test_reflectance_scaling_without_offset():
    # A DN of 3000 with no offset is 0.30 reflectance.
    assert to_reflectance(3000, apply_offset=False) == pytest.approx(0.30)


def test_baseline_offset_shifts_reflectance():
    # Same DN, post-2022 product: (3000 - 1000) / 10000 = 0.20
    assert to_reflectance(3000, apply_offset=True) == pytest.approx(0.20)


def test_baseline_offset_date_cutoff():
    assert needs_baseline_offset("2021-08-14") is False
    assert needs_baseline_offset("2022-01-24") is False
    assert needs_baseline_offset("2022-01-25") is True   # the cutover itself
    assert needs_baseline_offset("2024-09-12") is True   # Bridge Fire era


def test_skipping_the_offset_measurably_biases_dnbr():
    """The offset is not cosmetic: forgetting it moves dNBR by a real amount."""
    nir_pre, swir_pre = 4000, 1500
    nir_post, swir_post = 2000, 3000

    def compute(apply):
        pre = nbr(to_reflectance(nir_pre, apply), to_reflectance(swir_pre, apply))
        post = nbr(to_reflectance(nir_post, apply), to_reflectance(swir_post, apply))
        return float(dnbr(pre, post))

    assert abs(compute(True) - compute(False)) > 20  # well beyond noise


# --- NBR math -----------------------------------------------------------------

def test_nbr_healthy_vegetation_is_high():
    # Bright NIR, dark SWIR2 -> strongly positive.
    assert nbr(0.40, 0.05) == pytest.approx(0.7778, abs=1e-3)


def test_nbr_burned_ground_is_negative():
    # Fire strips the NIR-bright canopy and exposes SWIR-bright char.
    assert nbr(0.10, 0.30) == pytest.approx(-0.5, abs=1e-6)


def test_nbr_is_bounded():
    rng = np.random.default_rng(0)
    vals = nbr(rng.uniform(0, 1, 500), rng.uniform(0, 1, 500))
    assert np.all(vals >= -1) and np.all(vals <= 1)


def test_nbr_zero_denominator_is_nan_not_inf():
    """Bad pixels must propagate visibly, not poison downstream means."""
    assert np.isnan(nbr(0.0, 0.0))


# --- dNBR and the offset correction -------------------------------------------

def test_dnbr_positive_when_vegetation_lost():
    assert dnbr(0.7, -0.3) == pytest.approx(1000.0)


def test_dnbr_offset_is_subtracted():
    assert dnbr(0.7, -0.3, offset=50.0) == pytest.approx(950.0)


def test_dnbr_offset_recovered_from_unburned_area():
    """Simulate a scene with a known drift, then recover it."""
    true_offset = 42.0
    rng = np.random.default_rng(1)
    scene = rng.normal(true_offset, 5.0, 2000).astype("float32")
    unburned = np.ones(2000, dtype=bool)
    assert dnbr_offset(scene, unburned) == pytest.approx(true_offset, abs=1.0)


def test_dnbr_offset_ignores_nan():
    vals = np.array([10.0, np.nan, 20.0, np.nan, 30.0], dtype="float32")
    assert dnbr_offset(vals, np.ones(5, dtype=bool)) == pytest.approx(20.0)


def test_dnbr_offset_empty_mask_fails_loudly():
    with pytest.raises(ValueError):
        dnbr_offset(np.array([1.0, 2.0]), np.zeros(2, dtype=bool))


# --- classification -----------------------------------------------------------

def test_severity_class_break_points():
    vals = np.array([0, 269, 270, 659, 660, 1200], dtype="float32")
    assert list(severity_class(vals)) == [0, 0, 1, 1, 2, 2]


def test_severity_class_nan_is_flagged_not_counted_as_unburned():
    assert severity_class(np.array([np.nan], dtype="float32"))[0] == -1


def test_moderate_high_mask_matches_the_270_threshold():
    vals = np.array([100, 300, 700, np.nan], dtype="float32")
    assert list(moderate_high_mask(vals)) == [False, True, True, False]


# --- the F variable -----------------------------------------------------------

def test_basin_F_is_mean_dnbr_over_1000():
    vals = np.array([400, 600, 500], dtype="float32")
    assert basin_F(vals, np.ones(3, dtype=bool)) == pytest.approx(0.5)


def test_basin_F_respects_the_basin_mask():
    vals = np.array([400, 600, 9999], dtype="float32")
    mask = np.array([True, True, False])
    assert basin_F(vals, mask) == pytest.approx(0.5)


def test_basin_F_excludes_nan():
    vals = np.array([400, np.nan, 600], dtype="float32")
    assert basin_F(vals, np.ones(3, dtype=bool)) == pytest.approx(0.5)


def test_basin_F_lands_in_the_range_m1_expects():
    """Sanity: a realistic burn should give F in roughly 0.1-0.8."""
    rng = np.random.default_rng(2)
    vals = rng.normal(450, 150, 5000).astype("float32")
    assert 0.1 < basin_F(vals, np.ones(5000, dtype=bool)) < 0.8
