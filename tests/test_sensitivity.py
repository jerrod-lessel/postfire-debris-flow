"""Tests for debrisflow.sensitivity.

The aggregation is the least defended part of the sensitivity study, so these
tests lean on the failure modes that actually happen in a notebook: a run that
silently overwrote another, a basin lost in a merge, an anchor run leaking into
the envelope, and the wrong High cutoff.
"""

import pandas as pd
import pytest

from debrisflow.sensitivity import (
    HIGH_P,
    REQUIRED_COLUMNS,
    anchor_agreement,
    stability_class,
    threshold_envelope,
    validate_runs,
)

ENVELOPE = ["t200_drop", "t270_drop", "t350_drop",
            "t200_zero", "t270_zero", "t350_zero"]
ANCHORS = ["baer_drop", "baer_zero"]


def make_frame(basins=3, runs=ENVELOPE, anchors=(), p_by_basin=None):
    """Build a rectangular long frame with plausible values."""
    rows = []
    all_runs = list(runs) + list(anchors)
    for b in range(basins):
        basin_id = f"B{b:03d}"
        f_value = 0.4 + 0.05 * b          # constant across runs by definition
        for i, run in enumerate(all_runs):
            if p_by_basin is not None:
                p = p_by_basin[basin_id][run]
            else:
                p = 0.30 + 0.10 * b + 0.02 * i
            rows.append(
                {
                    "basin_id": basin_id,
                    "run_id": run,
                    "T": 0.5 + 0.01 * i,
                    "F": f_value,
                    "S": 0.25,
                    "threshold_mm_hr": 16.0 + b + i,
                    "p_24": p,
                }
            )
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- validate

def test_validate_accepts_rectangular_frame():
    df = make_frame()
    assert validate_runs(df, ENVELOPE) is df


def test_validate_accepts_frame_without_declared_runs():
    df = make_frame()
    validate_runs(df)


@pytest.mark.parametrize("column", REQUIRED_COLUMNS)
def test_validate_rejects_missing_column(column):
    df = make_frame().drop(columns=[column])
    with pytest.raises(ValueError, match="missing required columns"):
        validate_runs(df, ENVELOPE)


def test_validate_rejects_empty_frame():
    df = make_frame().iloc[0:0]
    with pytest.raises(ValueError, match="empty"):
        validate_runs(df, ENVELOPE)


def test_validate_rejects_nulls():
    df = make_frame()
    df.loc[2, "T"] = None
    with pytest.raises(ValueError, match="null values"):
        validate_runs(df, ENVELOPE)


def test_validate_rejects_duplicate_basin_run_pair():
    """A run that overwrote another and got appended twice."""
    df = make_frame()
    df = pd.concat([df, df.iloc[[0]]], ignore_index=True)
    with pytest.raises(ValueError, match="duplicate basin/run"):
        validate_runs(df, ENVELOPE)


def test_validate_rejects_basin_missing_from_one_run():
    """A basin dropped by an inner join on one run."""
    df = make_frame()
    df = df.drop(index=df.index[(df.basin_id == "B001") & (df.run_id == "t350_drop")])
    with pytest.raises(ValueError, match="do not appear in all"):
        validate_runs(df, ENVELOPE)


def test_validate_rejects_unexpected_run_id():
    """Anchor runs left in when only envelope runs were declared."""
    df = make_frame(anchors=ANCHORS)
    with pytest.raises(ValueError, match="unexpected run ids"):
        validate_runs(df, ENVELOPE)


def test_validate_rejects_declared_run_absent():
    df = make_frame(runs=ENVELOPE[:-1])
    with pytest.raises(ValueError, match="not in the frame"):
        validate_runs(df, ENVELOPE)


def test_validate_rejects_moving_F():
    """F is mean catchment dNBR, so it cannot vary across runs."""
    df = make_frame()
    df.loc[(df.basin_id == "B000") & (df.run_id == "t350_drop"), "F"] = 0.9
    with pytest.raises(ValueError, match="F varies across runs"):
        validate_runs(df, ENVELOPE)


def test_validate_rejects_empty_run_list():
    with pytest.raises(ValueError, match="empty"):
        validate_runs(make_frame(), [])


def test_validate_rejects_repeated_run_in_list():
    with pytest.raises(ValueError, match="repeated run ids"):
        validate_runs(make_frame(), ENVELOPE + ["t200_drop"])


# ---------------------------------------------------------------- envelope

def test_envelope_shape_and_columns():
    env = threshold_envelope(make_frame(), ENVELOPE)
    assert len(env) == 3
    assert list(env.columns) == [
        "basin_id", "F", "threshold_min", "threshold_median",
        "threshold_max", "threshold_spread", "n_runs",
    ]
    assert (env["n_runs"] == 6).all()


def test_envelope_values_for_known_basin():
    df = make_frame()
    env = threshold_envelope(df, ENVELOPE).set_index("basin_id")
    # B000 thresholds are 16 through 21 across the six runs.
    assert env.loc["B000", "threshold_min"] == 16.0
    assert env.loc["B000", "threshold_max"] == 21.0
    assert env.loc["B000", "threshold_spread"] == 5.0
    # Even run count, so the median sits between the two middle values.
    assert env.loc["B000", "threshold_median"] == 18.5


def test_envelope_ignores_anchor_runs():
    """Anchors carried in the frame must not widen the envelope."""
    p = None
    df = make_frame(anchors=ANCHORS, p_by_basin=p)
    df.loc[df.run_id.isin(ANCHORS), "threshold_mm_hr"] = 99.0
    env = threshold_envelope(df, ENVELOPE).set_index("basin_id")
    assert env.loc["B000", "threshold_max"] == 21.0
    assert (env["n_runs"] == 6).all()


def test_envelope_rejects_unknown_run():
    with pytest.raises(ValueError, match="not in the frame"):
        threshold_envelope(make_frame(), ENVELOPE + ["nope"])


def test_envelope_carries_constant_F():
    env = threshold_envelope(make_frame(), ENVELOPE).set_index("basin_id")
    assert env.loc["B000", "F"] == pytest.approx(0.40)
    assert env.loc["B002", "F"] == pytest.approx(0.50)


# --------------------------------------------------------------- stability

def p_map(values):
    """Build a p_24 lookup from {basin: [p per envelope run]} plus anchors."""
    out = {}
    for basin, plist in values.items():
        out[basin] = dict(zip(ENVELOPE, plist))
    return out


def test_stability_always_sometimes_never():
    p = p_map(
        {
            "B000": [0.10] * 6,                          # never
            "B001": [0.70, 0.70, 0.55, 0.70, 0.70, 0.70],  # sometimes
            "B002": [0.90] * 6,                          # always
        }
    )
    out = stability_class(make_frame(p_by_basin=p), ENVELOPE).set_index("basin_id")
    assert out.loc["B000", "stability"] == "never"
    assert out.loc["B001", "stability"] == "sometimes"
    assert out.loc["B002", "stability"] == "always"
    assert out.loc["B001", "n_high"] == 5
    assert out.loc["B001", "frac_high"] == pytest.approx(5 / 6)


def test_high_cutoff_is_p_ge_point_six_not_point_five():
    """A basin sitting between P = 0.5 and P = 0.6 is Moderate, not High.

    This is the difference between classifying on p_24 >= 0.6 and classifying
    on threshold_mm_hr <= 24, which is the P = 0.5 cutoff.
    """
    p = p_map({f"B{b:03d}": [0.55] * 6 for b in range(3)})
    out = stability_class(make_frame(p_by_basin=p), ENVELOPE)
    assert (out["stability"] == "never").all()
    assert (out["n_high"] == 0).all()


def test_high_cutoff_is_inclusive_at_exactly_point_six():
    p = p_map({f"B{b:03d}": [HIGH_P] * 6 for b in range(3)})
    out = stability_class(make_frame(p_by_basin=p), ENVELOPE)
    assert (out["stability"] == "always").all()


def test_stability_ignores_anchor_runs():
    p = {}
    for b in range(3):
        basin = f"B{b:03d}"
        p[basin] = {r: 0.10 for r in ENVELOPE}
        p[basin].update({r: 0.99 for r in ANCHORS})
    out = stability_class(make_frame(anchors=ANCHORS, p_by_basin=p), ENVELOPE)
    assert (out["stability"] == "never").all()
    assert (out["n_runs"] == 6).all()


def test_stability_rejects_bad_cutoff():
    with pytest.raises(ValueError, match="between 0 and 1"):
        stability_class(make_frame(), ENVELOPE, high_p=1.4)


def test_stability_rejects_missing_p_column():
    df = make_frame().rename(columns={"p_24": "p24"})
    with pytest.raises(ValueError, match="no column"):
        stability_class(df, ENVELOPE)


# ------------------------------------------------------------------ anchor

def test_anchor_flags_the_interesting_case():
    """Always High under every parameter choice, not High under BAER."""
    p = {}
    p["B000"] = {r: 0.90 for r in ENVELOPE}
    p["B000"].update({"baer_drop": 0.20, "baer_zero": 0.90})
    p["B001"] = {r: 0.10 for r in ENVELOPE}
    p["B001"].update({"baer_drop": 0.95, "baer_zero": 0.10})
    p["B002"] = {r: 0.10 for r in ENVELOPE}
    p["B002"]["t200_drop"] = 0.95                     # sometimes
    p["B002"].update({"baer_drop": 0.95, "baer_zero": 0.10})

    df = make_frame(anchors=ANCHORS, p_by_basin=p)
    out = anchor_agreement(df, ENVELOPE, ANCHORS).set_index(["basin_id", "run_id"])

    assert out.loc[("B000", "baer_drop"), "agreement"] == "contradicts_high"
    assert out.loc[("B000", "baer_zero"), "agreement"] == "confirms_high"
    assert out.loc[("B001", "baer_drop"), "agreement"] == "contradicts_not_high"
    assert out.loc[("B001", "baer_zero"), "agreement"] == "confirms_not_high"
    assert out.loc[("B002", "baer_drop"), "agreement"] == "unstable_anchor_high"
    assert out.loc[("B002", "baer_zero"), "agreement"] == "unstable_anchor_not_high"


def test_anchor_output_has_one_row_per_basin_per_anchor():
    df = make_frame(basins=4, anchors=ANCHORS)
    out = anchor_agreement(df, ENVELOPE, ANCHORS)
    assert len(out) == 8
    assert list(out.columns) == [
        "basin_id", "run_id", "stability", "anchor_p", "anchor_high", "agreement",
    ]


def test_anchor_rejects_overlap_with_envelope():
    df = make_frame(anchors=ANCHORS)
    with pytest.raises(ValueError, match="stay outside the envelope"):
        anchor_agreement(df, ENVELOPE + ["baer_drop"], ANCHORS)


def test_anchor_rejects_basin_absent_from_envelope():
    df = make_frame(anchors=ANCHORS)
    df = df.drop(index=df.index[(df.basin_id == "B001") & df.run_id.isin(ENVELOPE)])
    with pytest.raises(ValueError, match="absent from the envelope"):
        anchor_agreement(df, ENVELOPE, ANCHORS)
