"""Tests for basin delineation.

A wrong basin is indistinguishable from a right one on a real DEM, so every test
here uses a synthetic flow grid whose correct answer is known by hand, or checks
an invariant that must hold regardless of the input.

The one test that touches real machinery is `test_matches_pysheds_catchment`,
which is the check that this module's traversal means the same thing as the
reference implementation. It is skipped when pysheds is unavailable.
"""

import numpy as np
import pytest

from debrisflow import basins
from debrisflow.basins import DEFAULT_DIRMAP as DM

# Direction codes, named, so the test grids below are readable.
N, NE, E, SE, S, SW, W, NW = DM


# --------------------------------------------------------------------------
# downstream_index
# --------------------------------------------------------------------------

def test_downstream_index_inverts_the_encoding():
    # A 1x3 row draining east: cell 0 -> cell 1 -> cell 2 -> off the edge.
    fdir = np.array([[E, E, E]])
    dst = basins.downstream_index(fdir)
    assert dst[0, 0] == 1
    assert dst[0, 1] == 2
    assert dst[0, 2] == -1        # drains off the grid


def test_downstream_index_marks_unknown_codes_as_sinks():
    fdir = np.array([[E, 0, 999]])
    dst = basins.downstream_index(fdir)
    assert dst[0, 0] == 1
    assert dst[0, 1] == -1
    assert dst[0, 2] == -1


def test_downstream_index_handles_every_direction():
    # A 3x3 where all eight neighbours drain into the centre. Each outer cell
    # must point at index 4. This is the test that catches an OFFSETS/dirmap
    # mismatch, which is the most likely way to get basins draining backwards.
    fdir = np.array([
        [SE, S,  SW],
        [E,   0,  W],
        [NE, N,  NW],
    ])
    dst = basins.downstream_index(fdir)
    for r in range(3):
        for c in range(3):
            if (r, c) == (1, 1):
                continue
            assert dst[r, c] == 4, f"cell ({r}, {c}) does not drain to the centre"


# --------------------------------------------------------------------------
# upstream_mask
# --------------------------------------------------------------------------

def test_upstream_mask_single_channel_takes_everything():
    # Every cell drains east along its row, then the last column drains south
    # to the bottom-right corner. Seeding the corner must return all 25 cells.
    fdir = np.full((5, 5), E)
    fdir[:, 4] = S
    fdir[4, 4] = 0
    mask = basins.upstream_mask(fdir, 4, 4)
    assert mask.all()
    assert mask.sum() == 25


def test_upstream_mask_two_basins_do_not_intersect():
    # Left half drains west, right half drains east. Two independent systems.
    fdir = np.zeros((4, 6), dtype=int)
    fdir[:, :3] = W
    fdir[:, 3:] = E
    left = basins.upstream_mask(fdir, 0, 0)
    right = basins.upstream_mask(fdir, 0, 5)

    # Row 0 only, since rows do not drain into each other here.
    assert left[0].sum() == 3
    assert right[0].sum() == 3
    assert not (left & right).any()


def test_upstream_mask_y_junction():
    # Two arms meeting at (2, 1), which then drains south to (3, 1).
    #   (0,0) SE ->        (0,2) SW ->
    #   (1,0) SE -> (1,1)? no: keep arms explicit
    fdir = np.zeros((4, 3), dtype=int)
    fdir[0, 0] = SE      # -> (1,1)
    fdir[1, 1] = S       # -> (2,1)
    fdir[0, 2] = SW      # -> (1,1)
    fdir[2, 1] = S       # -> (3,1)
    fdir[3, 1] = 0       # outlet

    below = basins.upstream_mask(fdir, 3, 1)
    # Both arms plus the junction chain and the outlet itself.
    assert below[0, 0] and below[0, 2] and below[1, 1] and below[2, 1] and below[3, 1]
    assert below.sum() == 5

    # Seeding one arm returns only that arm.
    left_arm = basins.upstream_mask(fdir, 0, 0)
    assert left_arm.sum() == 1
    assert not left_arm[0, 2]


def test_upstream_mask_rejects_out_of_bounds_seed():
    fdir = np.full((3, 3), E)
    with pytest.raises(IndexError):
        basins.upstream_mask(fdir, 5, 0)


# --------------------------------------------------------------------------
# delineate
# --------------------------------------------------------------------------

def _two_arm_grid():
    """Two 4-cell arms joining a trunk, on a 6x3 grid.

    Column 1 is the trunk running south. Columns 0 and 2 drain into it.
    Accumulation is set by hand so the arms are eligible outlets and the trunk
    below the junction is too large to be one.
    """
    fdir = np.zeros((6, 3), dtype=int)
    fdir[:, 0] = E        # left column drains into the trunk
    fdir[:, 2] = W        # right column drains into the trunk
    fdir[:, 1] = S        # trunk runs south
    fdir[5, 1] = 0        # outlet

    acc = np.zeros((6, 3), dtype=float)
    acc[:, 0] = 1
    acc[:, 2] = 1
    acc[:, 1] = np.arange(1, 7) * 3     # 3, 6, 9, 12, 15, 18
    return fdir, acc


def test_delineate_produces_non_overlapping_labels():
    fdir, acc = _two_arm_grid()
    labels, records = basins.delineate(fdir, acc, min_cells=3, max_cells=9)
    # Labels are a single integer per cell, so overlap is impossible by
    # construction. The invariant worth asserting is that every labelled cell
    # belongs to a basin that was actually recorded.
    ids = {r["id"] for r in records}
    present = set(np.unique(labels)) - {0}
    assert present <= ids


def test_delineate_respects_the_area_window():
    fdir, acc = _two_arm_grid()
    labels, records = basins.delineate(fdir, acc, min_cells=3, max_cells=9)
    assert records, "expected at least one basin"
    for rec in records:
        assert 3 <= rec["outlet_acc_cells"] <= 9


def test_delineate_takes_the_largest_eligible_outlet_first():
    fdir, acc = _two_arm_grid()
    labels, records = basins.delineate(fdir, acc, min_cells=3, max_cells=9)
    # Trunk cells have accumulation 3, 6, 9, 12, 15, 18. The largest eligible
    # is 9, at row 2. Greedy must pick that one first, and everything upstream
    # of it then belongs to that basin rather than starting its own.
    first = records[0]
    assert first["outlet_acc_cells"] == 9
    assert first["outlet_row"] == 2 and first["outlet_col"] == 1
    assert labels[0, 1] == first["id"]      # upstream trunk was absorbed
    assert labels[1, 1] == first["id"]


def test_delineate_leaves_oversized_trunk_unassigned():
    fdir, acc = _two_arm_grid()
    labels, _ = basins.delineate(fdir, acc, min_cells=3, max_cells=9)
    # Rows 3, 4 and 5 of the trunk have accumulation 12, 15 and 18, all above
    # max_cells, and they are downstream of every outlet, so nothing can claim
    # them. They must be 0 rather than silently folded into a basin.
    assert labels[3, 1] == 0
    assert labels[4, 1] == 0
    assert labels[5, 1] == 0


def test_delineate_region_mask_restricts_outlets_not_basins():
    fdir, acc = _two_arm_grid()
    region = np.zeros_like(fdir, dtype=bool)
    region[2, 1] = True                      # only this cell may be an outlet

    labels, records = basins.delineate(fdir, acc, min_cells=3, max_cells=9,
                                       region_mask=region)
    assert len(records) == 1
    assert (records[0]["outlet_row"], records[0]["outlet_col"]) == (2, 1)
    # The basin still extends upstream past the region mask.
    assert labels[0, 1] == records[0]["id"]
    assert labels[0, 0] == records[0]["id"]


def test_delineate_is_deterministic():
    # Greedy selection with tied sort keys can silently reorder between runs.
    # A pipeline whose output shifts run to run is not defensible, so the tie
    # break is pinned.
    rng = np.random.default_rng(0)
    fdir = rng.choice(np.array(DM), size=(30, 30))
    acc = rng.integers(1, 400, size=(30, 30)).astype(float)

    a_labels, a_recs = basins.delineate(fdir, acc, min_cells=10, max_cells=200)
    b_labels, b_recs = basins.delineate(fdir, acc, min_cells=10, max_cells=200)

    assert np.array_equal(a_labels, b_labels)
    assert a_recs == b_recs


def test_delineate_every_cell_drains_to_its_own_outlet():
    """The property that actually matters, checked without knowing the answer.

    For every labelled cell, walking downstream must reach that basin's outlet
    before reaching any other outlet. This catches a whole class of errors that
    the small hand-built grids above would miss.
    """
    rng = np.random.default_rng(7)
    fdir = rng.choice(np.array(DM), size=(40, 40))
    acc = rng.integers(1, 500, size=(40, 40)).astype(float)

    labels, records = basins.delineate(fdir, acc, min_cells=20, max_cells=300)
    outlets = {r["id"]: r["outlet_row"] * 40 + r["outlet_col"] for r in records}
    dst = basins.downstream_index(fdir).ravel()
    flat = labels.ravel()

    for idx in np.flatnonzero(flat):
        target = outlets[flat[idx]]
        cur, steps = idx, 0
        while cur != target and cur >= 0 and steps <= flat.size:
            cur = dst[cur]
            steps += 1
        assert cur == target, f"cell {idx} never reaches its own outlet"


# --------------------------------------------------------------------------
# basin_attributes
# --------------------------------------------------------------------------

def test_basin_attributes_area_and_overlap():
    labels = np.array([
        [1, 1, 2],
        [1, 1, 2],
    ], dtype=np.int32)
    records = [
        {"id": 1, "outlet_row": 1, "outlet_col": 1, "outlet_acc_cells": 4.0},
        {"id": 2, "outlet_row": 1, "outlet_col": 2, "outlet_acc_cells": 2.0},
    ]
    burn = np.array([
        [True,  False, True],
        [False, False, True],
    ])

    attrs = basins.basin_attributes(labels, records, burn, cellsize_m=100)

    a, b = attrs
    assert a["cells"] == 4
    assert a["area_km2"] == pytest.approx(4 * 0.01)
    assert a["overlap_fraction"] == pytest.approx(0.25)
    assert b["cells"] == 2
    assert b["overlap_fraction"] == pytest.approx(1.0)


def test_basin_attributes_flags_extrapolation():
    labels = np.ones((10, 10), dtype=np.int32)
    records = [{"id": 1, "outlet_row": 9, "outlet_col": 9, "outlet_acc_cells": 100.0}]

    # 100 cells at 10 m is 0.01 km2, below the 0.1 km2 calibration floor.
    small = basins.basin_attributes(labels, records, cellsize_m=10)[0]
    assert small["in_calibration_range"] is False

    # The same 100 cells at 100 m is 1.0 km2, inside the window.
    ok = basins.basin_attributes(labels, records, cellsize_m=100)[0]
    assert ok["in_calibration_range"] is True


def test_basin_attributes_without_burn_mask():
    labels = np.array([[1, 1], [0, 1]], dtype=np.int32)
    records = [{"id": 1, "outlet_row": 1, "outlet_col": 1, "outlet_acc_cells": 3.0}]
    attrs = basins.basin_attributes(labels, records, cellsize_m=10)
    assert attrs[0]["cells"] == 3
    assert attrs[0]["overlap_fraction"] == 0.0


# --------------------------------------------------------------------------
# Cross-check against the reference implementation
# --------------------------------------------------------------------------

def _cone_with_dimple(tmp_path):
    """Build a small real DEM and route it with pysheds. Returns (fdir, acc).

    A cone draining inward, with a dimple so conditioning has something to do
    and the flow network is not trivially radial.
    """
    pytest.importorskip("pysheds")
    rasterio = pytest.importorskip("rasterio")
    from pysheds.grid import Grid

    from debrisflow import _compat  # noqa: F401  numpy 2 shim
    from debrisflow import terrain

    n = 60
    yy, xx = np.mgrid[0:n, 0:n]
    dem = 100 + np.hypot(yy - n / 2, xx - n / 2) * 2.0
    dem[40:44, 40:44] -= 15.0
    dem = dem.astype("float32")

    path = tmp_path / "cone.tif"
    transform = rasterio.transform.from_origin(0, n * 10, 10, 10)
    with rasterio.open(path, "w", driver="GTiff", height=n, width=n, count=1,
                       dtype="float32", crs="EPSG:32611", transform=transform,
                       nodata=-9999) as dst:
        dst.write(dem, 1)

    grid = Grid.from_raster(str(path))
    raster = grid.read_raster(str(path))
    conditioned = terrain.condition_dem(grid, raster)
    fdir, acc = terrain.flow_grids(grid, conditioned)
    return grid, fdir, np.asarray(fdir), np.asarray(acc)


def test_matches_pysheds_accumulation(tmp_path):
    """The size of `upstream_mask` must equal pysheds' own flow accumulation.

    This is the cross-check that establishes this module's traversal means the
    same thing as the reference implementation. Flow accumulation at a cell IS
    the count of cells draining to it, computed by pysheds through a completely
    different algorithm, so exact agreement across many seeds is strong evidence
    the D8 encoding is being inverted correctly.

    Preferred over `grid.catchment` because accumulation is unambiguous: no
    coordinate conversion, no pour point snapping, no boundary convention.
    """
    grid, fdir, fdir_arr, acc_arr = _cone_with_dimple(tmp_path)

    rng = np.random.default_rng(0)
    checked = 0
    for _ in range(40):
        r = int(rng.integers(1, fdir_arr.shape[0] - 1))
        c = int(rng.integers(1, fdir_arr.shape[1] - 1))
        if fdir_arr[r, c] not in DM:
            continue                     # nodata cell, nothing to compare
        mask = basins.upstream_mask(fdir_arr, r, c)
        assert mask.sum() == acc_arr[r, c], (
            f"seed ({r}, {c}): upstream_mask counted {mask.sum()}, "
            f"pysheds accumulation says {acc_arr[r, c]}"
        )
        checked += 1

    assert checked >= 30, "too few valid seeds; the test is not meaningful"


def test_matches_pysheds_catchment_interior(tmp_path):
    """`upstream_mask` matches `grid.catchment`, away from the grid border.

    The two agree exactly on the interior. They differ on the outermost row and
    column, where pysheds' catchment omits cells that its own accumulation
    counts. On the test DEM that is 75 border cells, all of which do genuinely
    drain to the seed (verified by walking the flow directions downstream), and
    `grid.catchment` returns no cell that `upstream_mask` misses.

    So this is a boundary convention in pysheds' catchment routine rather than a
    disagreement about routing, and the comparison is restricted to the interior
    rather than papered over. `test_matches_pysheds_accumulation` is the
    unrestricted check.
    """
    grid, fdir, fdir_arr, acc_arr = _cone_with_dimple(tmp_path)

    edge = np.zeros(fdir_arr.shape, dtype=bool)
    edge[0, :] = edge[-1, :] = edge[:, 0] = edge[:, -1] = True
    interior = ~edge

    seed_acc = np.where(interior, acc_arr, 0)
    r, c = np.unravel_index(np.argmax(seed_acc), seed_acc.shape)

    ours = basins.upstream_mask(fdir_arr, int(r), int(c))
    theirs = np.asarray(
        grid.catchment(x=int(c), y=int(r), fdir=fdir, xytype="index")
    ).astype(bool)

    assert ours.sum() > 20, "seed produced a trivial catchment; test is not meaningful"
    assert np.array_equal(ours[interior], theirs[interior])
    # pysheds must never claim a cell that we miss; only the reverse happens.
    assert not (theirs & ~ours).any()
