"""Tests for the Soil Data Access parsing layer.

The fixture below is REAL output from the live SDA service (STATSGO map unit
662058, San Gabriel area query), captured 2026-09-03. Synthetic tests missed
both problems this layer exists to solve: SDA returns strings in a leading-dot
format, and it returns interleaved horizon rows that must be grouped by
component before any aggregation is valid.

cokey values are reconstructed from the component grouping in the captured
output; the kffact, comppct_r and hzdept_r values are exactly as returned.
"""

import numpy as np
import pytest

from debrisflow.soils import (
    parse_kf, parse_int, group_rows_by_component, kf_by_mapunit,
    mapunit_to_basin, validate_kf,
)


# (mukey, cokey, comppct_r, kffact, hzdept_r, hzdepb_r)
REAL_SDA_ROWS = [
    ("662058", "c1", "54", ".37", "0",  "10"),
    ("662058", "c1", "54", ".37", "10", "38"),
    ("662058", "c1", "54", ".28", "38", "64"),
    ("662058", "c1", "54", ".10", "64", "99"),
    ("662058", "c2", "18", ".37", "0",  "43"),
    ("662058", "c2", "18", ".24", "43", "69"),
    ("662058", "c2", "18", ".24", "69", "99"),
    ("662058", "c3", "15", ".32", "0",  "25"),
]


# --- parsing what SDA actually sends ------------------------------------------

def test_parses_leading_dot_format():
    """SDA sends '.37', not '0.37'. This is the format that broke first."""
    assert parse_kf(".37") == pytest.approx(0.37)
    assert parse_kf(".10") == pytest.approx(0.10)


def test_parses_ordinary_floats_and_numbers():
    assert parse_kf("0.28") == pytest.approx(0.28)
    assert parse_kf(0.43) == pytest.approx(0.43)
    assert parse_kf(1) == pytest.approx(1.0)


def test_nulls_become_nan_not_zero():
    """A null KF must reach the aggregator as NaN so it gets dropped, not
    averaged in as 0.0 (which would under-predict hazard)."""
    for null in (None, "", "  ", "None", "null", "NA"):
        assert np.isnan(parse_kf(null))


def test_garbage_becomes_nan_rather_than_raising():
    """One bad cell should not kill an entire basin."""
    assert np.isnan(parse_kf("not a number"))
    assert np.isnan(parse_kf("<>"))


def test_parse_int_handles_strings_and_nulls():
    assert parse_int("54") == 54
    assert parse_int("54.0") == 54
    assert parse_int(None) == 0
    assert parse_int("junk", default=-1) == -1


# --- grouping interleaved rows ------------------------------------------------

def test_groups_rows_into_the_right_components():
    """The real failure this catches: 94 flat rows are several components
    interleaved, not one component's horizon stack."""
    grouped = group_rows_by_component(REAL_SDA_ROWS)
    assert set(grouped) == {"c1", "c2", "c3"}
    assert len(grouped["c1"]["horizons"]) == 4
    assert len(grouped["c2"]["horizons"]) == 3
    assert len(grouped["c3"]["horizons"]) == 1


def test_horizons_are_sorted_surface_first():
    grouped = group_rows_by_component(REAL_SDA_ROWS)
    depths = [h[0] for h in grouped["c1"]["horizons"]]
    assert depths == sorted(depths) and depths[0] == 0


def test_grouping_survives_shuffled_row_order():
    """SDA row order is not guaranteed, so grouping must not depend on it."""
    shuffled = list(reversed(REAL_SDA_ROWS))
    a = group_rows_by_component(REAL_SDA_ROWS)
    b = group_rows_by_component(shuffled)
    assert [h[0] for h in a["c1"]["horizons"]] == [h[0] for h in b["c1"]["horizons"]]


def test_component_percentages_are_preserved():
    grouped = group_rows_by_component(REAL_SDA_ROWS)
    assert grouped["c1"]["comppct"] == 54
    assert grouped["c2"]["comppct"] == 18
    assert grouped["c3"]["comppct"] == 15


# --- the full chain on real data ----------------------------------------------

def test_kf_by_mapunit_on_real_rows():
    """Surface horizons are .37, .37, .32 weighted 54/18/15 (sum 87, not 100).

    Expected: (0.37*54 + 0.37*18 + 0.32*15) / 87 = 0.3614
    """
    result = kf_by_mapunit(REAL_SDA_ROWS)
    kf, coverage = result["662058"]
    assert kf == pytest.approx(0.3614, abs=1e-3)
    assert coverage == pytest.approx(1.0)


def test_deeper_horizons_are_ignored_by_default():
    """c1 goes .37 -> .28 -> .10 with depth. Only the .37 surface counts,
    because post-fire rilling acts on the surface."""
    surface = kf_by_mapunit(REAL_SDA_ROWS)["662058"][0]
    full = kf_by_mapunit(REAL_SDA_ROWS, surface_only=False)["662058"][0]
    assert surface > full     # deep horizons are less erodible here
    assert surface == pytest.approx(0.3614, abs=1e-3)


def test_percentages_summing_to_87_are_renormalised():
    """87 percent coverage must not silently scale the result down by 0.87."""
    kf, _ = kf_by_mapunit(REAL_SDA_ROWS)["662058"]
    naive = (0.37 * 54 + 0.37 * 18 + 0.32 * 15) / 100   # the wrong denominator
    assert kf > naive
    assert naive == pytest.approx(0.3144, abs=1e-3)


def test_real_kf_passes_validation_and_reaches_the_model():
    """End to end: raw SDA strings -> a usable S value for one basin."""
    per_mu = kf_by_mapunit(REAL_SDA_ROWS)
    S, coverage = mapunit_to_basin(
        [v[0] for v in per_mu.values()],
        [1_500_000] * len(per_mu),      # placeholder intersected areas
    )
    assert validate_kf(S) == pytest.approx(0.3614, abs=1e-3)
    assert coverage == pytest.approx(1.0)


def test_null_surface_horizon_drops_that_component():
    """A rock-outcrop component contributes nothing rather than dragging
    the map unit toward zero."""
    rows = REAL_SDA_ROWS + [("662058", "c4", "13", None, "0", "20")]
    kf, coverage = kf_by_mapunit(rows)["662058"]
    assert kf == pytest.approx(0.3614, abs=1e-3)   # unchanged
    assert coverage == pytest.approx(87 / 100, abs=1e-2)  # but flagged as partial


def test_empty_rows_do_not_crash():
    assert kf_by_mapunit([]) == {}
