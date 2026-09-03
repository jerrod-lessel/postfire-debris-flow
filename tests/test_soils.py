import numpy as np
import pytest

from debrisflow.soils import (
    weighted_mean, horizon_to_component, component_to_mapunit,
    mapunit_to_basin, validate_kf, flag_low_coverage, kf_by_mapunit_sql,
    KF_MIN, KF_MAX, KF_FIELD,
)


# --- weighted mean and the missing-data policy --------------------------------

def test_equal_weights_is_plain_mean():
    m, cov = weighted_mean([0.2, 0.4], [1, 1])
    assert m == pytest.approx(0.3) and cov == pytest.approx(1.0)


def test_weights_actually_weight():
    m, _ = weighted_mean([0.2, 0.4], [3, 1])
    assert m == pytest.approx(0.25)


def test_weights_need_not_sum_to_one():
    """comppct_r does not always total 100, so it must be renormalised."""
    a, _ = weighted_mean([0.2, 0.4], [30, 60])
    b, _ = weighted_mean([0.2, 0.4], [1, 2])
    assert a == pytest.approx(b)


def test_missing_values_are_dropped_not_zeroed():
    """Treating a null KF as 0.0 would drag the mean down and under-predict."""
    dropped, cov = weighted_mean([0.3, np.nan], [1, 1])
    assert dropped == pytest.approx(0.3)      # the surviving value
    assert cov == pytest.approx(0.5)          # but only half the area covered

    zeroed = np.average([0.3, 0.0], weights=[1, 1])
    assert zeroed == pytest.approx(0.15)      # what the wrong approach gives
    assert dropped > zeroed


def test_coverage_reports_the_valid_fraction():
    _, cov = weighted_mean([0.3, np.nan, np.nan], [50, 25, 25])
    assert cov == pytest.approx(0.5)


def test_all_missing_returns_nan_and_zero_coverage():
    m, cov = weighted_mean([np.nan, np.nan], [1, 1])
    assert np.isnan(m) and cov == 0.0


def test_zero_weight_entries_do_not_count_toward_coverage():
    m, cov = weighted_mean([0.3, 0.9], [1, 0])
    assert m == pytest.approx(0.3) and cov == pytest.approx(1.0)


def test_mismatched_lengths_fail_loudly():
    with pytest.raises(ValueError):
        weighted_mean([0.1, 0.2], [1])


def test_negative_weights_rejected():
    with pytest.raises(ValueError):
        weighted_mean([0.1, 0.2], [1, -1])


def test_zero_total_weight_rejected():
    with pytest.raises(ValueError):
        weighted_mean([0.1, 0.2], [0, 0])


# --- the three aggregation levels ---------------------------------------------

def test_surface_horizon_is_what_counts():
    """Post-fire rilling acts on the surface, so deeper horizons are ignored."""
    kf, cov = horizon_to_component([0.24, 0.55, 0.60], [10, 40, 80])
    assert kf == pytest.approx(0.24) and cov == pytest.approx(1.0)


def test_full_profile_mode_weights_by_thickness():
    kf, _ = horizon_to_component([0.2, 0.4], [1, 3], surface_only=False)
    assert kf == pytest.approx(0.35)


def test_missing_surface_horizon_is_nan():
    kf, cov = horizon_to_component([np.nan, 0.4], [10, 40])
    assert np.isnan(kf) and cov == 0.0


def test_empty_horizons_is_nan():
    kf, cov = horizon_to_component([], [])
    assert np.isnan(kf) and cov == 0.0


def test_component_rollup_uses_comppct():
    """A map unit that is 80% erodible soil should read close to that soil."""
    kf, _ = component_to_mapunit([0.43, 0.10], [80, 20])
    assert kf == pytest.approx(0.364)


def test_mapunit_rollup_uses_intersected_area():
    """A polygon barely clipping the basin must barely influence S."""
    kf, _ = mapunit_to_basin([0.20, 0.60], [990_000, 10_000])
    assert kf == pytest.approx(0.204)


def test_full_chain_produces_a_plausible_S():
    """Horizons -> components -> map units -> one basin S value."""
    mu_a, _ = component_to_mapunit(
        [horizon_to_component([0.28, 0.5], [12, 30])[0],
         horizon_to_component([0.17, 0.3], [8, 25])[0]],
        [70, 30],
    )
    mu_b, _ = component_to_mapunit(
        [horizon_to_component([0.43, 0.4], [15, 40])[0]], [100]
    )
    S, cov = mapunit_to_basin([mu_a, mu_b], [1_200_000, 800_000])
    assert KF_MIN <= S <= KF_MAX
    assert cov == pytest.approx(1.0)
    assert validate_kf(S) == pytest.approx(S)


# --- guard rails --------------------------------------------------------------

def test_validate_accepts_realistic_values():
    for v in (0.02, 0.24, 0.43, 0.69):
        assert validate_kf(v) == pytest.approx(v)


def test_validate_rejects_out_of_range():
    with pytest.raises(ValueError, match="outside plausible range"):
        validate_kf(1.5)          # e.g. a percent/fraction mixup
    with pytest.raises(ValueError, match="outside plausible range"):
        validate_kf(0.001)


def test_validate_rejects_nan_with_a_useful_message():
    with pytest.raises(ValueError, match="no valid soil data"):
        validate_kf(float("nan"))


def test_low_coverage_flagging():
    assert flag_low_coverage(0.95) is False
    assert flag_low_coverage(0.30) is True    # mostly rock outcrop or water
    assert flag_low_coverage(0.50) is False   # threshold is inclusive


# --- query construction -------------------------------------------------------

def test_sql_uses_kf_not_kw():
    """kwfact is the rock-free variant. Staley uses KF. Do not substitute."""
    sql = kf_by_mapunit_sql(["1234"])
    assert KF_FIELD == "kffact"
    assert "kffact" in sql and "kwfact" not in sql


def test_sql_includes_all_mukeys_and_orders_by_depth():
    sql = kf_by_mapunit_sql(["100", "200", "300"])
    assert "'100'" in sql and "'200'" in sql and "'300'" in sql
    assert "hzdept_r" in sql        # so the surface horizon comes first


def test_sql_rejects_unknown_dataset():
    with pytest.raises(ValueError, match="statsgo"):
        kf_by_mapunit_sql(["1"], dataset="gssurgo")


def test_sql_rejects_empty_mukeys():
    with pytest.raises(ValueError, match="no mukeys"):
        kf_by_mapunit_sql([])
