"""Aggregation of multi-run sensitivity results down to per-basin summaries.

The sensitivity study runs the scoring pipeline several times with different
defensible choices (dNBR threshold, soil aggregation rule) over a fixed set of
basins. Each run produces one row per basin. This module collapses that long
frame into the two things worth publishing:

* a threshold envelope, the min / median / max rainfall threshold per basin
* a stability class, whether a basin is High under every run, some runs or none

Everything here is pure pandas arithmetic. No file IO, no network, no rasters.
The caller assembles the long frame in the notebook and hands it over.

Vocabulary
----------
envelope runs
    The runs that represent parameter choices within one measurement. These
    define the envelope and the stability classes.
anchor runs
    Runs from a different data source, for example field-validated BAER soil
    burn severity. Reported alongside, never folded into the envelope.

High is P >= 0.6 at the evaluation rainfall, matching ``m1.hazard_class`` and
the USGS ``P_24mmh`` field. It is NOT ``threshold_mm_hr <= 24``, which is the
P >= 0.5 cutoff and would promote a band of Moderate basins to High.
"""

from __future__ import annotations

import pandas as pd

__all__ = [
    "REQUIRED_COLUMNS",
    "HIGH_P",
    "validate_runs",
    "threshold_envelope",
    "stability_class",
    "anchor_agreement",
]

#: Columns every sensitivity frame must carry.
REQUIRED_COLUMNS = (
    "basin_id",
    "run_id",
    "T",
    "F",
    "S",
    "threshold_mm_hr",
    "p_24",
)

#: Probability at or above which a basin is High, per ``m1.hazard_class``.
HIGH_P = 0.6


def _check_runs_present(df: pd.DataFrame, runs, label: str) -> list:
    """Return ``runs`` as a list, raising if any are absent from ``df``."""
    runs = list(runs)
    if len(runs) == 0:
        raise ValueError(f"{label} is empty; pass the run ids explicitly")
    duplicates = sorted({r for r in runs if runs.count(r) > 1})
    if duplicates:
        raise ValueError(f"{label} contains repeated run ids: {duplicates}")
    present = set(df["run_id"].unique())
    missing = [r for r in runs if r not in present]
    if missing:
        raise ValueError(f"{label} names run ids not in the frame: {missing}")
    return runs


def validate_runs(df: pd.DataFrame, runs=None) -> pd.DataFrame:
    """Check that a long sensitivity frame is rectangular and complete.

    This is the guard against silent notebook errors: a run that overwrote
    another, a basin dropped by a merge, a null that sailed through.

    Parameters
    ----------
    df
        Long frame, one row per basin per run, carrying ``REQUIRED_COLUMNS``.
    runs
        The run ids expected. If given, the frame must contain exactly these
        and no others. If ``None``, whatever runs are present are accepted but
        the frame must still be rectangular.

    Returns
    -------
    The frame unchanged, so this can be used inline.

    Raises
    ------
    ValueError
        On any missing column, missing value, duplicate basin-run pair,
        ragged basin coverage, or unexpected run id.
    """
    missing_cols = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing_cols:
        raise ValueError(f"frame is missing required columns: {missing_cols}")

    if len(df) == 0:
        raise ValueError("frame is empty")

    present = list(pd.unique(df["run_id"]))
    if runs is not None:
        expected = _check_runs_present(df, runs, "runs")
        unexpected = [r for r in present if r not in set(expected)]
        if unexpected:
            raise ValueError(f"frame contains unexpected run ids: {sorted(map(str, unexpected))}")
        if len(present) != len(expected):
            absent = [r for r in expected if r not in set(present)]
            raise ValueError(f"frame is missing run ids: {absent}")
        present = expected

    nulls = [c for c in REQUIRED_COLUMNS if df[c].isna().any()]
    if nulls:
        raise ValueError(f"frame has null values in columns: {nulls}")

    dup = df.duplicated(subset=["basin_id", "run_id"])
    if dup.any():
        offenders = (
            df.loc[dup, ["basin_id", "run_id"]]
            .drop_duplicates()
            .to_records(index=False)
            .tolist()
        )
        raise ValueError(
            f"{int(dup.sum())} duplicate basin/run rows, first few: {offenders[:5]}"
        )

    counts = df.groupby("basin_id")["run_id"].count()
    n_runs = len(present)
    ragged = counts[counts != n_runs]
    if len(ragged) > 0:
        raise ValueError(
            f"{len(ragged)} basins do not appear in all {n_runs} runs, "
            f"first few: {ragged.head().to_dict()}"
        )

    # F is a per-basin constant by definition: mean catchment dNBR, no
    # threshold in it. If F moves across runs, something upstream is wrong.
    f_spread = df.groupby("basin_id")["F"].nunique()
    moving = f_spread[f_spread > 1]
    if len(moving) > 0:
        raise ValueError(
            f"F varies across runs for {len(moving)} basins; F is a per-basin "
            f"constant, so this means the runs were built inconsistently. "
            f"First few: {list(moving.index[:5])}"
        )

    return df


def threshold_envelope(df: pd.DataFrame, runs) -> pd.DataFrame:
    """Collapse per-run thresholds to a min / median / max envelope per basin.

    ``threshold_mm_hr`` is the rainfall accumulation that reaches P = 0.5. It is
    continuous, which is why it is the right variable for an envelope, and it is
    the number reported elsewhere in the project.

    With an even number of runs the median falls between the two middle values,
    so it will not equal any single run's threshold. That is expected.

    Parameters
    ----------
    df
        Long frame as validated by :func:`validate_runs`.
    runs
        Explicit list of run ids forming the envelope. Anchor runs must not
        appear here.

    Returns
    -------
    One row per basin, columns ``basin_id``, ``F``, ``threshold_min``,
    ``threshold_median``, ``threshold_max``, ``threshold_spread``, ``n_runs``.
    """
    runs = _check_runs_present(df, runs, "runs")
    subset = df[df["run_id"].isin(runs)]

    grouped = subset.groupby("basin_id")["threshold_mm_hr"]
    out = pd.DataFrame(
        {
            "threshold_min": grouped.min(),
            "threshold_median": grouped.median(),
            "threshold_max": grouped.max(),
        }
    )
    out["threshold_spread"] = out["threshold_max"] - out["threshold_min"]
    out["n_runs"] = grouped.count()
    # F is constant per basin, carried through as a passthrough for joining.
    out["F"] = subset.groupby("basin_id")["F"].first()

    out = out.reset_index()
    return out[
        [
            "basin_id",
            "F",
            "threshold_min",
            "threshold_median",
            "threshold_max",
            "threshold_spread",
            "n_runs",
        ]
    ]


def stability_class(
    df: pd.DataFrame,
    runs,
    high_p: float = HIGH_P,
    p_col: str = "p_24",
) -> pd.DataFrame:
    """Classify each basin as always / sometimes / never High across ``runs``.

    High is ``p_24 >= high_p``, matching ``m1.hazard_class`` and the USGS
    ``P_24mmh`` field. Do not substitute ``threshold_mm_hr <= 24``: that is the
    P = 0.5 cutoff and classifies a band of Moderate basins as High.

    Parameters
    ----------
    df
        Long frame as validated by :func:`validate_runs`.
    runs
        Explicit list of envelope run ids. Anchor runs must not appear here.
    high_p
        Probability cutoff for High.
    p_col
        Column holding the probability at the evaluation rainfall.

    Returns
    -------
    One row per basin, columns ``basin_id``, ``n_high``, ``n_runs``,
    ``frac_high``, ``stability``. ``frac_high`` exists so the "sometimes"
    basins can be shaded by how often rather than drawn as one flat class.
    """
    if p_col not in df.columns:
        raise ValueError(f"frame has no column {p_col!r}")
    if not 0.0 < high_p < 1.0:
        raise ValueError(f"high_p must be between 0 and 1, got {high_p}")

    runs = _check_runs_present(df, runs, "runs")
    subset = df[df["run_id"].isin(runs)].copy()
    subset["_is_high"] = subset[p_col] >= high_p

    grouped = subset.groupby("basin_id")["_is_high"]
    out = pd.DataFrame({"n_high": grouped.sum().astype(int), "n_runs": grouped.count()})
    out["frac_high"] = out["n_high"] / out["n_runs"]

    stability = pd.Series("sometimes", index=out.index, dtype=object)
    stability[out["n_high"] == out["n_runs"]] = "always"
    stability[out["n_high"] == 0] = "never"
    out["stability"] = stability

    return out.reset_index()[
        ["basin_id", "n_high", "n_runs", "frac_high", "stability"]
    ]


def anchor_agreement(
    df: pd.DataFrame,
    envelope_runs,
    anchor_runs,
    high_p: float = HIGH_P,
    p_col: str = "p_24",
) -> pd.DataFrame:
    """Compare anchor runs against the envelope stability class, per basin.

    An anchor run comes from a different data source, so it is never allowed to
    draw the classes. It is reported next to them. The case worth looking at is
    a basin the parameter choices call High every time but the field-validated
    severity does not.

    Parameters
    ----------
    df
        Long frame as validated by :func:`validate_runs`.
    envelope_runs
        Run ids that define the stability class.
    anchor_runs
        Run ids reported against it. Must not overlap ``envelope_runs``.
    high_p, p_col
        As in :func:`stability_class`.

    Returns
    -------
    One row per basin per anchor run, columns ``basin_id``, ``run_id``,
    ``stability``, ``anchor_p``, ``anchor_high``, ``agreement``.

    ``agreement`` takes one of:

    ``confirms_high``
        envelope says always High, anchor agrees
    ``contradicts_high``
        envelope says always High, anchor does not. Look at these.
    ``confirms_not_high``
        envelope says never High, anchor agrees
    ``contradicts_not_high``
        envelope says never High, anchor says High. Look at these too.
    ``unstable_anchor_high`` / ``unstable_anchor_not_high``
        envelope is already split, so there is nothing to contradict
    """
    envelope_runs = _check_runs_present(df, envelope_runs, "envelope_runs")
    anchor_runs = _check_runs_present(df, anchor_runs, "anchor_runs")

    overlap = sorted(set(envelope_runs) & set(anchor_runs))
    if overlap:
        raise ValueError(
            f"anchor runs must stay outside the envelope, but these appear in "
            f"both: {overlap}"
        )

    classes = stability_class(df, envelope_runs, high_p=high_p, p_col=p_col)
    classes = classes[["basin_id", "stability"]]

    anchors = df[df["run_id"].isin(anchor_runs)][
        ["basin_id", "run_id", p_col]
    ].copy()
    anchors = anchors.rename(columns={p_col: "anchor_p"})
    anchors["anchor_high"] = anchors["anchor_p"] >= high_p

    out = anchors.merge(classes, on="basin_id", how="left")
    if out["stability"].isna().any():
        n = int(out["stability"].isna().sum())
        raise ValueError(
            f"{n} anchor rows have basins absent from the envelope runs; "
            f"run validate_runs before aggregating"
        )

    labels = {
        ("always", True): "confirms_high",
        ("always", False): "contradicts_high",
        ("never", True): "contradicts_not_high",
        ("never", False): "confirms_not_high",
        ("sometimes", True): "unstable_anchor_high",
        ("sometimes", False): "unstable_anchor_not_high",
    }
    out["agreement"] = [
        labels[(s, bool(h))] for s, h in zip(out["stability"], out["anchor_high"])
    ]

    return out.sort_values(["run_id", "basin_id"]).reset_index(drop=True)[
        ["basin_id", "run_id", "stability", "anchor_p", "anchor_high", "agreement"]
    ]
