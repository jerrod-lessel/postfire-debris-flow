import numpy as np
import pytest

from debrisflow.terrain import (
    slope_degrees, steep_mask, basin_T, basin_area_km2,
    in_calibration_range, cells_for_area, STEEP_SLOPE_DEGREES,
)


# --- slope math ---------------------------------------------------------------

def test_flat_dem_has_zero_slope():
    dem = np.full((5, 5), 100.0)
    s = slope_degrees(dem, cellsize_m=10)
    assert np.nanmax(s) == pytest.approx(0.0, abs=1e-9)


def test_known_45_degree_plane():
    """A plane rising 10 m per 10 m cell is exactly 45 degrees."""
    dem = np.tile(np.arange(5) * 10.0, (5, 1))
    s = slope_degrees(dem, cellsize_m=10)
    assert np.nanmax(s) == pytest.approx(45.0, abs=1e-6)


def test_known_gentle_plane():
    """Rise of 1 m per 10 m cell -> atan(0.1) = 5.71 degrees."""
    dem = np.tile(np.arange(6) * 1.0, (6, 1))
    s = slope_degrees(dem, cellsize_m=10)
    assert np.nanmax(s) == pytest.approx(np.degrees(np.arctan(0.1)), abs=1e-6)


def test_slope_is_direction_agnostic():
    """Same gradient running north-south gives the same slope."""
    ew = slope_degrees(np.tile(np.arange(6) * 5.0, (6, 1)), 10)
    ns = slope_degrees(np.tile(np.arange(6) * 5.0, (6, 1)).T, 10)
    assert np.nanmax(ew) == pytest.approx(np.nanmax(ns), abs=1e-9)


def test_cellsize_changes_slope():
    """The same elevations over larger cells is a gentler slope."""
    dem = np.tile(np.arange(6) * 10.0, (6, 1))
    assert np.nanmax(slope_degrees(dem, 10)) > np.nanmax(slope_degrees(dem, 30))


def test_edges_are_nan_not_guessed():
    s = slope_degrees(np.random.rand(6, 6) * 100, 10)
    assert np.all(np.isnan(s[0, :])) and np.all(np.isnan(s[-1, :]))
    assert np.all(np.isnan(s[:, 0])) and np.all(np.isnan(s[:, -1]))


def test_rejects_non_2d_dem():
    with pytest.raises(ValueError):
        slope_degrees(np.arange(10), 10)


# --- steep mask ---------------------------------------------------------------

def test_steep_mask_threshold_is_inclusive():
    s = np.array([22.9, 23.0, 23.1], dtype="float32")
    assert list(steep_mask(s)) == [False, True, True]
    assert STEEP_SLOPE_DEGREES == 23.0


def test_nan_slope_is_never_steep():
    assert steep_mask(np.array([np.nan], dtype="float32"))[0] == False


# --- the T variable, and why the intersection matters -------------------------

def test_basin_T_is_the_intersection():
    steep = np.array([True, True, False, False])
    burned = np.array([True, False, True, False])
    basin = np.ones(4, dtype=bool)
    assert basin_T(steep, burned, basin) == pytest.approx(0.25)


def test_basin_T_respects_the_basin_mask():
    steep = np.array([True, True, True, True])
    burned = np.array([True, True, True, True])
    basin = np.array([True, True, False, False])
    assert basin_T(steep, burned, basin) == pytest.approx(1.0)


def test_product_of_fractions_is_wrong_when_correlated():
    """The core error from the original spec, pinned down.

    Steep and burned areas overlap perfectly here. The intersection is 0.5;
    multiplying the two fractions gives 0.25, a 2x underestimate of T.
    """
    steep = np.array([True] * 50 + [False] * 50)
    burned = np.array([True] * 50 + [False] * 50)
    basin = np.ones(100, dtype=bool)

    true_T = basin_T(steep, burned, basin)
    naive = steep.mean() * burned.mean()

    assert true_T == pytest.approx(0.5)
    assert naive == pytest.approx(0.25)
    assert true_T / naive == pytest.approx(2.0)


def test_product_is_also_wrong_when_anticorrelated():
    """It errs the other way too: here the steep and burned areas never overlap."""
    steep = np.array([True] * 50 + [False] * 50)
    burned = np.array([False] * 50 + [True] * 50)
    basin = np.ones(100, dtype=bool)
    assert basin_T(steep, burned, basin) == pytest.approx(0.0)
    assert steep.mean() * burned.mean() == pytest.approx(0.25)  # nonsense


def test_basin_T_empty_mask_fails_loudly():
    with pytest.raises(ValueError):
        basin_T(np.array([True]), np.array([True]), np.zeros(1, dtype=bool))


# --- basin scale --------------------------------------------------------------

def test_basin_area_from_pixel_count():
    """10000 pixels at 10 m = 1 km2."""
    assert basin_area_km2(np.ones(10000, dtype=bool), 10) == pytest.approx(1.0)


def test_cells_for_area_roundtrip():
    n = cells_for_area(2.5, cellsize_m=10)
    assert basin_area_km2(np.ones(n, dtype=bool), 10) == pytest.approx(2.5)


def test_calibration_range_flags_out_of_scale_basins():
    assert in_calibration_range(1.0) is True
    assert in_calibration_range(0.05) is False   # too small
    assert in_calibration_range(50.0) is False   # NHDPlus-sized, T gets diluted
