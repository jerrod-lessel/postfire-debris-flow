"""
Burn severity from Sentinel-2: NBR, dNBR, and the corrections that matter.

DESIGN NOTE: this module is deliberately split into
    (a) pure array math, which is fully unit-testable with no network, and
    (b) STAC search helpers, which touch the network.
Keeping the math free of IO is what lets the test suite actually pin down
correctness. The Colab notebook does the IO and hands arrays to the math.
"""

import numpy as np

# Sentinel-2 band roles for NBR.
# B08 = NIR (842 nm, 10 m), B12 = SWIR-2 (2190 nm, 20 m).
# Healthy vegetation is bright in NIR and dark in SWIR-2. Fire flips that:
# it removes the NIR-bright canopy and exposes SWIR-bright char and bare soil.
NIR_BAND = "B08"
SWIR2_BAND = "B12"

# USGS / Key & Benson dNBR severity break points (dNBR scaled by 1000).
SEVERITY_BREAKS = {
    "unburned_low": 270,   # below this: unburned or low severity
    "moderate_high": 660,  # at or above this: high severity
}

# Sentinel-2 L2A digital numbers are reflectance * 10000.
L2A_QUANTIFICATION_VALUE = 10000

# Processing Baseline 04.00 (products from 2022-01-25 onward) added a -1000
# radiometric offset to the digital numbers. Miss it and every NBR is wrong.
L2A_BASELINE_0400_OFFSET = -1000
L2A_BASELINE_0400_DATE = "2022-01-25"


def to_reflectance(dn, apply_offset=True):
    """Convert Sentinel-2 L2A digital numbers to surface reflectance (0-1).

    Parameters
    ----------
    dn : array
        Raw integer digital numbers as stored in the COG.
    apply_offset : bool
        Whether to apply the Baseline 04.00 -1000 offset. True for any scene
        acquired on or after 2022-01-25. Use `needs_baseline_offset()` rather
        than deciding this by hand.
    """
    dn = np.asarray(dn, dtype="float32")
    if apply_offset:
        dn = dn + L2A_BASELINE_0400_OFFSET
    return dn / L2A_QUANTIFICATION_VALUE


def needs_baseline_offset(acquisition_date):
    """Does this scene need the Baseline 04.00 offset? Pass an ISO date string."""
    return str(acquisition_date)[:10] >= L2A_BASELINE_0400_DATE


def nbr(nir, swir2):
    """Normalized Burn Ratio: (NIR - SWIR2) / (NIR + SWIR2).

    Ranges -1 to +1. High for healthy vegetation, low or negative for burned
    ground. Division by zero is returned as NaN rather than inf, so that bad
    pixels propagate visibly instead of poisoning downstream statistics.
    """
    nir = np.asarray(nir, dtype="float32")
    swir2 = np.asarray(swir2, dtype="float32")
    denom = nir + swir2
    with np.errstate(divide="ignore", invalid="ignore"):
        out = np.where(denom == 0, np.nan, (nir - swir2) / denom)
    return out.astype("float32")


def dnbr(nbr_pre, nbr_post, scale=1000, offset=0.0):
    """Differenced NBR: (pre - post), conventionally scaled by 1000.

    Parameters
    ----------
    offset : float
        The dNBR offset correction, in the SAME scaled units as the output.
        Subtracting it removes the phenological and atmospheric drift between
        the pre and post dates that would otherwise leak straight into the
        model's F variable. Get it from `dnbr_offset()`.
    """
    d = (np.asarray(nbr_pre, dtype="float32") - np.asarray(nbr_post, dtype="float32")) * scale
    return (d - offset).astype("float32")


def dnbr_offset(dnbr_uncorrected, unburned_mask):
    """Estimate the dNBR offset from unburned pixels inside the same scene.

    Standard practice: the mean dNBR over an area known to be unburned should
    be zero. Whatever it actually is, is your offset. Skipping this step is one
    of the most common ways a dNBR product ends up quietly biased.

    `unburned_mask` should be True over unburned ground in the same scene,
    ideally similar vegetation and elevation to the burn area.
    """
    vals = np.asarray(dnbr_uncorrected, dtype="float32")[np.asarray(unburned_mask, dtype=bool)]
    vals = vals[np.isfinite(vals)]
    if vals.size == 0:
        raise ValueError("Unburned mask selected no valid pixels.")
    return float(np.mean(vals))


def severity_class(dnbr_values):
    """Classify dNBR into 0 = unburned/low, 1 = moderate, 2 = high.

    NaN pixels return -1 so they can be excluded from zonal statistics rather
    than silently counted as unburned.
    """
    d = np.asarray(dnbr_values, dtype="float32")
    out = np.full(d.shape, -1, dtype="int8")
    valid = np.isfinite(d)
    out[valid & (d < SEVERITY_BREAKS["unburned_low"])] = 0
    out[valid & (d >= SEVERITY_BREAKS["unburned_low"])] = 1
    out[valid & (d >= SEVERITY_BREAKS["moderate_high"])] = 2
    return out


def moderate_high_mask(dnbr_values):
    """Boolean mask of moderate-or-high severity (dNBR >= 270).

    This is one half of the M1 terrain variable T. The other half is the
    slope >= 23 degree mask, and T is their INTERSECTION over basin area.
    """
    return severity_class(dnbr_values) >= 1


def basin_F(dnbr_values, basin_mask):
    """The M1 fire variable F: mean dNBR within the basin, divided by 1000.

    NaN pixels are excluded from the mean rather than dragging it around.
    """
    d = np.asarray(dnbr_values, dtype="float32")[np.asarray(basin_mask, dtype=bool)]
    d = d[np.isfinite(d)]
    if d.size == 0:
        raise ValueError("Basin mask selected no valid dNBR pixels.")
    return float(np.mean(d)) / 1000.0
