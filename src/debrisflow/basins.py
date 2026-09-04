"""Basin delineation from a D8 flow direction grid.

`terrain.py` measures rasters: slope, flow direction, flow accumulation. This
module turns that routing output into discrete, labelled, non-overlapping basin
objects, which are the units every M1 prediction is made over.

The delineation here is deliberately written as pure functions over numpy arrays
rather than as calls into pysheds. A basin that drains the wrong way looks
exactly like a basin that drains the right way, so this needs to be checkable
against synthetic grids whose correct answer is known by hand. `upstream_mask`
is also cross-checked against `pysheds.Grid.catchment` on a real DEM, which is
what establishes that this implementation means the same thing as the reference.

D8 direction encoding
---------------------
The default `dirmap` matches pysheds: eight codes starting at north and
proceeding clockwise. A cell holding code `dirmap[i]` drains to its neighbour at
offset `OFFSETS[i]`. Inverting that mapping correctly is the single most
error-prone part of this module, which is why it is isolated in one place.
"""

from __future__ import annotations

import numpy as np

# North, northeast, east, southeast, south, southwest, west, northwest.
OFFSETS = (
    (-1, 0), (-1, 1), (0, 1), (1, 1),
    (1, 0), (1, -1), (0, -1), (-1, -1),
)

# pysheds' default encoding, in the same order as OFFSETS.
DEFAULT_DIRMAP = (64, 128, 1, 2, 4, 8, 16, 32)


def downstream_index(fdir, dirmap=DEFAULT_DIRMAP):
    """Linear index of the cell each cell drains into.

    Returns an int64 array the same shape as `fdir`, holding the flat index of
    the downstream neighbour. Cells that drain off the edge of the grid, or that
    hold a code not present in `dirmap` (sinks, nodata), get -1.

    This is the inverse of the D8 encoding, computed once and vectorised, so
    that nothing downstream has to reason about direction codes again.
    """
    fdir = np.asarray(fdir)
    if fdir.ndim != 2:
        raise ValueError("fdir must be 2D")
    nrows, ncols = fdir.shape

    rows, cols = np.indices(fdir.shape)
    dst = np.full(fdir.shape, -1, dtype=np.int64)

    for (dr, dc), code in zip(OFFSETS, dirmap):
        match = fdir == code
        if not match.any():
            continue
        tr = rows + dr
        tc = cols + dc
        inside = (tr >= 0) & (tr < nrows) & (tc >= 0) & (tc < ncols)
        take = match & inside
        dst[take] = (tr[take] * ncols + tc[take]).astype(np.int64)

    return dst


def upstream_mask(fdir, row, col, dirmap=DEFAULT_DIRMAP):
    """Every cell that drains to (row, col), including that cell.

    A breadth-first walk against the flow direction. Pure function of an array
    and a seed, so it can be tested on grids small enough to verify by hand.

    This is the definition of a D8 catchment. `delineate` does not call it, for
    performance reasons, but the two are checked against each other.
    """
    fdir = np.asarray(fdir)
    nrows, ncols = fdir.shape
    if not (0 <= row < nrows and 0 <= col < ncols):
        raise IndexError(f"seed ({row}, {col}) is outside the grid {fdir.shape}")

    mask = np.zeros(fdir.shape, dtype=bool)
    mask[row, col] = True
    stack = [(row, col)]

    while stack:
        r, c = stack.pop()
        # A neighbour at offset (dr, dc) drains INTO (r, c) when it holds the
        # code for that offset. So we look at (r - dr, c - dc) for each offset.
        for (dr, dc), code in zip(OFFSETS, dirmap):
            ur, uc = r - dr, c - dc
            if not (0 <= ur < nrows and 0 <= uc < ncols):
                continue
            if mask[ur, uc]:
                continue
            if fdir[ur, uc] == code:
                mask[ur, uc] = True
                stack.append((ur, uc))

    return mask


def delineate(fdir, acc, min_cells, max_cells, region_mask=None,
              dirmap=DEFAULT_DIRMAP):
    """Greedy, non-overlapping basin delineation.

    Every cell whose contributing area falls between `min_cells` and
    `max_cells` is a candidate outlet, and there are hundreds of thousands of
    them, all nested inside one another along every stream. The selection rule
    is: take the largest unclaimed candidate, give it everything upstream, and
    repeat.

    That is implemented as a single pass over cells sorted by accumulation
    descending, rather than as one catchment traversal per candidate. Because a
    cell's downstream neighbour always has greater-or-equal accumulation, it has
    already been decided by the time we reach the cell, so each cell simply
    inherits its downstream neighbour's label. Same result as the naive greedy
    loop, one pass instead of hundreds of thousands.

    Parameters
    ----------
    fdir, acc : 2D arrays
        Flow direction codes and flow accumulation in upstream cell counts,
        as returned by `terrain.flow_grids`.
    min_cells, max_cells : int
        Contributing-area bounds for an outlet, in cells. Use
        `terrain.cells_for_area` rather than converting by hand.
    region_mask : 2D bool array, optional
        Where outlets are ALLOWED. Basins still extend upstream beyond it; this
        only restricts where a basin may start. Use it to avoid delineating
        terrain that is nowhere near the fire.

    Returns
    -------
    labels : int32 array
        Basin id per cell. 0 means unassigned: cells below every outlet, and
        trunk drainages too large to be an outlet at this scale.
    records : list of dict
        One per basin, in id order, with `id`, `outlet_row`, `outlet_col` and
        `outlet_acc_cells`.
    """
    fdir = np.asarray(fdir)
    acc = np.asarray(acc)
    if fdir.shape != acc.shape:
        raise ValueError("fdir and acc must have the same shape")
    if min_cells > max_cells:
        raise ValueError("min_cells must not exceed max_cells")

    nrows, ncols = fdir.shape
    n = fdir.size

    dst = downstream_index(fdir, dirmap).ravel()
    acc_flat = acc.ravel()

    eligible = (acc_flat >= min_cells) & (acc_flat <= max_cells)
    if region_mask is not None:
        region_mask = np.asarray(region_mask)
        if region_mask.shape != fdir.shape:
            raise ValueError("region_mask must match fdir's shape")
        eligible &= region_mask.ravel()

    # Descending accumulation. Stable sort on the negated key so that ties break
    # by flat index, which makes the whole delineation reproducible run to run.
    order = np.argsort(-acc_flat, kind="stable")

    labels = np.zeros(n, dtype=np.int32)
    records = []
    next_id = 1

    for idx in order:
        d = dst[idx]
        inherited = labels[d] if d >= 0 else 0
        if inherited:
            labels[idx] = inherited
        elif eligible[idx]:
            labels[idx] = next_id
            records.append({
                "id": next_id,
                "outlet_row": int(idx // ncols),
                "outlet_col": int(idx % ncols),
                "outlet_acc_cells": float(acc_flat[idx]),
            })
            next_id += 1

    return labels.reshape(fdir.shape), records


def basin_attributes(labels, records, burn_mask=None, cellsize_m=10,
                     lo_km2=0.1, hi_km2=8.0):
    """Per-basin area, burn overlap and calibration flag.

    `overlap_fraction` is the share of the basin inside the burn perimeter. It
    is recorded rather than used to filter: a basin that is 5% burned should
    still be scored, and the model's own output is a better judge of whether it
    is dangerous than an arbitrary overlap cutoff would be.

    `in_calibration_range` follows the project's existing rule: basins outside
    the 0.1 to 8 km2 window M1 was fitted on still produce a number, but that
    number is an extrapolation and the map should say so.
    """
    labels = np.asarray(labels)
    cell_km2 = (cellsize_m ** 2) / 1e6

    n_basins = len(records)
    counts = np.bincount(labels.ravel(), minlength=n_basins + 1)

    if burn_mask is not None:
        burn_mask = np.asarray(burn_mask, dtype=bool)
        if burn_mask.shape != labels.shape:
            raise ValueError("burn_mask must match labels' shape")
        burned = np.bincount(labels[burn_mask].ravel(), minlength=n_basins + 1)
    else:
        burned = np.zeros(n_basins + 1, dtype=np.int64)

    out = []
    for rec in records:
        i = rec["id"]
        cells = int(counts[i])
        area = cells * cell_km2
        out.append({
            **rec,
            "cells": cells,
            "area_km2": area,
            "burned_cells": int(burned[i]),
            "overlap_fraction": (burned[i] / cells) if cells else 0.0,
            "in_calibration_range": bool(lo_km2 <= area <= hi_km2),
        })
    return out
