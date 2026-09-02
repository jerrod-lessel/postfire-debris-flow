"""
Terrain analysis: slope, basin delineation, and the M1 terrain variable T.

Same design split as severity.py:
    (a) pure array math, unit-testable with no IO or pysheds, and
    (b) pysheds watershed routines, which need a real georeferenced DEM.

WHY BASIN SCALE MATTERS MORE THAN ANYTHING ELSE HERE
    M1 was calibrated on small watersheds, roughly 0.1 to 8 km2. If your basins
    are much larger, burn severity and steepness get averaged over terrain that
    never contributes sediment to the channel, T is diluted toward zero, and
    the model systematically UNDER-predicts hazard. This is the single most
    likely reason your numbers will disagree with a published USGS assessment,
    which is why basin area is an explicit, documented parameter rather than
    whatever the data happens to give you.
"""

import numpy as np

# Restores np.in1d, which numpy 2 removed but pysheds 0.5 still calls.
# Must be imported before any pysheds flow-accumulation call. See _compat.py.
from debrisflow import _compat  # noqa: F401

# M1's slope break point. Steeper than this is where runoff-driven rilling and
# dry ravel actually mobilise sediment into channels.
STEEP_SLOPE_DEGREES = 23.0

# Basin area bounds, in km2, matching the scale M1 was calibrated at.
MIN_BASIN_AREA_KM2 = 0.1
MAX_BASIN_AREA_KM2 = 8.0

# The models were calibrated on 10 m DEM data. USGS explicitly recommends a
# 10 m DEM for standard applications, since slope statistics are resolution
# dependent: a coarser DEM smooths away exactly the steep pixels M1 cares about.
RECOMMENDED_DEM_RESOLUTION_M = 10


# --- pure slope math ----------------------------------------------------------

def slope_degrees(dem, cellsize_m=RECOMMENDED_DEM_RESOLUTION_M):
    """Slope in degrees from an elevation array, via Horn's method.

    Horn's 3x3 kernel is what GDAL and ArcGIS use, so results are comparable to
    standard GIS output. Edge pixels are returned as NaN rather than guessed.

    Parameters
    ----------
    dem : 2D array
        Elevation in metres.
    cellsize_m : float
        Ground distance between cell centres, in metres. If your DEM is in
        geographic coordinates this is NOT constant, so reproject to a metric
        CRS (e.g. UTM) before calling this.
    """
    z = np.asarray(dem, dtype="float64")
    if z.ndim != 2:
        raise ValueError("DEM must be 2D")

    out = np.full(z.shape, np.nan, dtype="float32")

    # Horn's method: weighted differences across a 3x3 neighbourhood.
    a, b, c = z[:-2, :-2], z[:-2, 1:-1], z[:-2, 2:]
    d, _, f = z[1:-1, :-2], z[1:-1, 1:-1], z[1:-1, 2:]
    g, h, i = z[2:, :-2],  z[2:, 1:-1],  z[2:, 2:]

    dzdx = ((c + 2 * f + i) - (a + 2 * d + g)) / (8 * cellsize_m)
    dzdy = ((g + 2 * h + i) - (a + 2 * b + c)) / (8 * cellsize_m)

    out[1:-1, 1:-1] = np.degrees(np.arctan(np.sqrt(dzdx ** 2 + dzdy ** 2)))
    return out


def steep_mask(slope_deg, threshold=STEEP_SLOPE_DEGREES):
    """Boolean mask of pixels at or above the M1 slope threshold.

    NaN slope (DEM edges, nodata) is False, so it is never counted as steep.
    """
    s = np.asarray(slope_deg, dtype="float32")
    return np.where(np.isfinite(s), s >= threshold, False)


def basin_T(steep, moderate_high, basin_mask):
    """The M1 terrain variable T.

    T = fraction of basin area that is BOTH steep AND burned at moderate/high
    severity. This is an INTERSECTION. Computing it as
    (fraction steep) * (fraction burned) is wrong whenever the steep parts and
    the burned parts are spatially correlated, which in real burn scars they
    almost always are.
    """
    basin = np.asarray(basin_mask, dtype=bool)
    n = int(basin.sum())
    if n == 0:
        raise ValueError("Basin mask selected no pixels.")
    both = np.asarray(steep, dtype=bool) & np.asarray(moderate_high, dtype=bool) & basin
    return float(both.sum()) / n


def basin_area_km2(basin_mask, cellsize_m=RECOMMENDED_DEM_RESOLUTION_M):
    """Basin area in km2, from a pixel mask and the cell size."""
    n = int(np.asarray(basin_mask, dtype=bool).sum())
    return n * (cellsize_m ** 2) / 1e6


def in_calibration_range(area_km2,
                         lo=MIN_BASIN_AREA_KM2, hi=MAX_BASIN_AREA_KM2):
    """Is this basin within the scale M1 was calibrated at?

    Basins outside this range still produce a number, but that number is an
    extrapolation. Flag them in the output rather than dropping them silently,
    so the map can show which predictions are on solid ground.
    """
    return lo <= area_km2 <= hi


# --- pysheds watershed delineation --------------------------------------------

def condition_dem(grid, dem):
    """Fill pits and depressions and resolve flats so flow routing works.

    A raw DEM has small artificial sinks. Left alone, flow accumulation dead
    ends in them and your basins come out fragmented. Order matters: pits,
    then depressions, then flats.
    """
    pit_filled = grid.fill_pits(dem)
    flooded = grid.fill_depressions(pit_filled)
    return grid.resolve_flats(flooded)


def flow_grids(grid, conditioned_dem):
    """Compute D8 flow direction and flow accumulation.

    Returns (fdir, acc). Accumulation is in upstream pixel counts; multiply by
    pixel area to get contributing area.
    """
    fdir = grid.flowdir(conditioned_dem)
    acc = grid.accumulation(fdir)
    return fdir, acc


def pour_points_from_accumulation(acc, min_cells, max_cells):
    """Candidate outlet cells whose contributing area sits in the target range.

    A crude first pass. Real delineation usually snaps pour points to a stream
    network and to locations of interest, such as canyon mouths above roads and
    structures, which is where post-fire debris flows actually cause harm.
    """
    a = np.asarray(acc)
    return np.argwhere((a >= min_cells) & (a <= max_cells))


def cells_for_area(area_km2, cellsize_m=RECOMMENDED_DEM_RESOLUTION_M):
    """Convert a target basin area in km2 to a pixel count."""
    return int(round(area_km2 * 1e6 / (cellsize_m ** 2)))
