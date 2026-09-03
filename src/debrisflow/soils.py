"""
Soil erodibility (KF-factor) for the M1 soil variable S.

WHICH DATASET, AND WHY IT MATTERS
    USGS operational post-fire assessments use STATSGO KF-factor. M1's
    coefficients were fitted against that data, so STATSGO is what this project
    uses for headline numbers: it keeps cross-validation against published USGS
    assessments apples-to-apples.

    SSURGO is far finer resolution and is genuinely better soil data. But
    swapping it in silently means any disagreement with USGS could be the soil
    input rather than our pipeline, and we would not be able to tell which.
    So SSURGO is supported here as a SECOND run, used as one axis of the
    sensitivity analysis. That turns a deviation we would otherwise have to
    defend into a result we get to present.

THE AGGREGATION CHAIN
    Both datasets share a schema, and the KF-factor has to be rolled up through
    three levels before it becomes one number per basin:

        chorizon  (soil horizons, KF lives here)
            -> weight by horizon thickness, surface horizon only
        component (soil types within a map unit)
            -> weight by comppct_r, the percent of the map unit each occupies
        mapunit   (the mapped polygons)
            -> weight by intersected area within the basin

    Getting a weighting wrong at any level produces a plausible number, which
    is the usual problem. The aggregation functions below are pure and tested.

STATUS OF THE QUERY LAYER
    The pure aggregation math below is unit tested. The Soil Data Access query
    strings are NOT yet verified against the live service. Run
    `check_sda_connection()` in Colab before trusting any output from them.
"""

import json
import urllib.request

import numpy as np

# USDA Soil Data Access REST endpoint. Takes a POST with a SQL query.
SDA_URL = "https://SDMDataAccess.sc.egov.usda.gov/Tabular/post.rest"

# In SDA, STATSGO2 map units are distinguished from SSURGO by their area
# symbol. SSURGO uses per-survey-area symbols (e.g. "CA071"); STATSGO2 uses
# the single national symbol "US".
STATSGO_AREASYMBOL = "US"

# KF vs KW: kffact is the whole-soil erodibility factor INCLUDING rock
# fragments; kwfact is the rock-free variant. Staley et al. use KF, so that is
# the default here. Do not silently substitute kwfact.
KF_FIELD = "kffact"

# Plausible bounds for a KF-factor. Values outside this are a data or parsing
# error, not a real soil.
KF_MIN, KF_MAX = 0.02, 0.69


# --- pure aggregation math ----------------------------------------------------

def weighted_mean(values, weights):
    """Area/percent weighted mean that drops missing values and renormalises.

    Missing KF is common and meaningful: rock outcrop, water, and organic soils
    genuinely have no erodibility factor. The wrong move is to treat those as
    zero, which drags the basin mean down and under-predicts hazard. Instead we
    drop them and renormalise over the weights that remain, then report the
    coverage separately so a thin basin can be flagged.

    Returns
    -------
    (mean, coverage) : the weighted mean over valid entries, and the fraction
        of total weight those valid entries represent (0-1).
    """
    v = np.asarray(values, dtype="float64")
    w = np.asarray(weights, dtype="float64")
    if v.shape != w.shape:
        raise ValueError(f"values {v.shape} and weights {w.shape} must match")
    if v.size == 0:
        raise ValueError("no values to aggregate")
    if np.any(w < 0):
        raise ValueError("weights must be non-negative")

    total = w.sum()
    if total <= 0:
        raise ValueError("weights sum to zero")

    valid = np.isfinite(v) & (w > 0)
    coverage = float(w[valid].sum() / total)
    if not valid.any():
        return float("nan"), 0.0
    return float(np.average(v[valid], weights=w[valid])), coverage


def horizon_to_component(kf_values, thicknesses, surface_only=True):
    """Roll soil horizons up to one KF per component.

    Post-fire runoff and rilling act on the SURFACE, so the top horizon is what
    matters for debris-flow initiation. Deeper horizons are irrelevant to the
    process M1 describes, which is why surface_only defaults True.

    Horizons are assumed ordered top-down (as SDA returns them when sorted by
    hzdept_r).
    """
    kf = np.asarray(kf_values, dtype="float64")
    th = np.asarray(thicknesses, dtype="float64")
    if kf.size == 0:
        return float("nan"), 0.0
    if surface_only:
        return (float(kf[0]), 1.0) if np.isfinite(kf[0]) else (float("nan"), 0.0)
    return weighted_mean(kf, th)


def component_to_mapunit(kf_values, comppct):
    """Roll components up to one KF per map unit, weighted by comppct_r.

    comppct_r is the representative percent of the map unit each soil component
    occupies. It does not always sum to exactly 100, so weighted_mean
    renormalises rather than assuming it does.
    """
    return weighted_mean(kf_values, comppct)


def mapunit_to_basin(kf_values, areas):
    """Roll map units up to the single S value for one basin.

    `areas` must be the area of each map unit polygon INTERSECTED WITH THE
    BASIN, not the polygon's full area. Using full polygon areas over-weights
    map units that only clip the basin edge.
    """
    return weighted_mean(kf_values, areas)


def validate_kf(value):
    """Range-check an aggregated KF-factor before it reaches the model."""
    if not np.isfinite(value):
        raise ValueError("KF-factor is NaN: no valid soil data for this basin")
    if not KF_MIN <= value <= KF_MAX:
        raise ValueError(
            f"KF-factor {value:.3f} outside plausible range "
            f"[{KF_MIN}, {KF_MAX}]. Likely a parsing or units error."
        )
    return float(value)


def flag_low_coverage(coverage, threshold=0.5):
    """Should this basin's S value be treated as unreliable?

    A basin that is mostly rock outcrop or water has a KF derived from a small
    minority of its area. Still worth computing, but the map should say so
    rather than presenting it with the same confidence as a fully covered one.
    """
    return coverage < threshold


# --- Soil Data Access query layer (UNVERIFIED) --------------------------------

def sda_query(sql, timeout=120):
    """POST a SQL query to Soil Data Access and return rows as a list of lists.

    UNVERIFIED against the live service. Run check_sda_connection() first.
    """
    body = json.dumps({"query": sql, "format": "JSON"}).encode("utf-8")
    req = urllib.request.Request(
        SDA_URL, data=body, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    return payload.get("Table", [])


def check_sda_connection():
    """Smoke-test the SDA service and confirm the STATSGO area symbol works.

    Run this in Colab BEFORE trusting anything else in this section. If the
    schema has drifted, this fails fast with a readable error instead of
    silently returning empty soil data that becomes S = NaN downstream.
    """
    rows = sda_query(
        "SELECT TOP 1 areasymbol, areaname FROM legend "
        f"WHERE areasymbol = '{STATSGO_AREASYMBOL}'"
    )
    if not rows:
        raise RuntimeError(
            "SDA returned no rows for the STATSGO area symbol. The service may "
            "be down, or the schema may have changed. Check "
            "https://sdmdataaccess.sc.egov.usda.gov/ before proceeding."
        )
    return rows


def kf_by_mapunit_sql(mukeys, dataset="statsgo"):
    """Build the SQL that fetches surface-horizon KF for a set of map units.

    Parameters
    ----------
    mukeys : sequence
        Map unit keys, obtained from a spatial query over the basin extent.
    dataset : {"statsgo", "ssurgo"}
        Which dataset the mukeys came from. Included so the caller has to state
        it explicitly, and so the sensitivity run is self-documenting.
    """
    if dataset not in ("statsgo", "ssurgo"):
        raise ValueError(f"dataset must be 'statsgo' or 'ssurgo', got {dataset!r}")
    if len(mukeys) == 0:
        raise ValueError("no mukeys supplied")

    keys = ",".join(f"'{k}'" for k in mukeys)
    return (
        "SELECT c.mukey, c.cokey, c.comppct_r, "
        f"ch.{KF_FIELD}, ch.hzdept_r, ch.hzdepb_r "
        "FROM component c "
        "INNER JOIN chorizon ch ON c.cokey = ch.cokey "
        f"WHERE c.mukey IN ({keys}) "
        "ORDER BY c.mukey, c.comppct_r DESC, ch.hzdept_r"
    )
