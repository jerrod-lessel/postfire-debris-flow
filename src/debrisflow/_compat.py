"""
Third-party compatibility shims.

Import this before pysheds, anywhere pysheds is used.

WHY THIS EXISTS
    pysheds 0.5 (the current release) calls `np.in1d` inside its D8 flow
    accumulation routine. numpy 2.0 removed `np.in1d` after a long deprecation
    in favour of the identical `np.isin`, so on any numpy>=2 environment
    `grid.accumulation()` raises:

        AttributeError: module 'numpy' has no attribute 'in1d'

    The obvious fix is to pin numpy<2. Don't. Colab and most of the modern
    geospatial stack (rasterio, geopandas, opencv) now require numpy>=2, so
    pinning down forces a slow source build of numpy and breaks other packages.
    Restoring the one removed alias is a smaller, safer change than downgrading
    the entire ecosystem for a single deprecated call.

    `np.in1d` and `np.isin` have identical semantics for 1-D input, which is
    all pysheds uses it for, so this is a true alias and not an approximation.

    Remove this module once pysheds ships a numpy 2 compatible release.
"""

import numpy as np


def patch_numpy_for_pysheds():
    """Restore np.in1d if this numpy removed it. Safe to call repeatedly."""
    if not hasattr(np, "in1d"):
        np.in1d = np.isin
        return True   # patch was applied
    return False      # numpy already has it (numpy < 2), nothing to do


# Applied on import so `import debrisflow._compat` is enough.
PATCHED = patch_numpy_for_pysheds()
