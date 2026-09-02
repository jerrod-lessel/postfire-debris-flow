import numpy as np
import pytest

from debrisflow._compat import patch_numpy_for_pysheds


def test_in1d_exists_after_import():
    """Importing the package must leave np.in1d callable, whatever numpy we're on."""
    import debrisflow.terrain  # noqa: F401  (imports _compat as a side effect)
    assert hasattr(np, "in1d")


def test_shim_matches_isin_semantics():
    """The alias must be a true substitute, not an approximation."""
    a = np.array([1, 2, 3, 4, 5])
    b = np.array([2, 4, 6])
    assert np.array_equal(np.in1d(a, b), np.isin(a, b))
    assert list(np.in1d(a, b)) == [False, True, False, True, False]


def test_patch_is_idempotent():
    """Calling it twice must not error or double-apply."""
    patch_numpy_for_pysheds()
    first = patch_numpy_for_pysheds()
    second = patch_numpy_for_pysheds()
    assert first is False and second is False   # already present both times


def test_pysheds_accumulation_actually_runs():
    """The regression this shim exists for: D8 accumulation on numpy 2.

    Without the patch this raises AttributeError: module 'numpy' has no
    attribute 'in1d'.
    """
    rasterio = pytest.importorskip("rasterio")
    pysheds_grid = pytest.importorskip("pysheds.grid")

    from rasterio.transform import from_origin
    from debrisflow.terrain import condition_dem, flow_grids

    n, cs, tmp = 60, 10, "/tmp/_test_dem.tif"
    yy, xx = np.mgrid[0:n, 0:n]
    dem = (300 - 1.5 * np.sqrt((xx - 30.0) ** 2 + (yy - 30.0) ** 2)).astype("float32")

    with rasterio.open(tmp, "w", driver="GTiff", height=n, width=n, count=1,
                       dtype="float32", crs="EPSG:32611", nodata=-9999,
                       transform=from_origin(400000, 3800000, cs, cs)) as ds:
        ds.write(dem, 1)

    grid = pysheds_grid.Grid.from_raster(tmp)
    _, acc = flow_grids(grid, condition_dem(grid, grid.read_raster(tmp)))
    assert int(np.asarray(acc).max()) > 1   # water actually accumulated somewhere
