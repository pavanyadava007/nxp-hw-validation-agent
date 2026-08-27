"""Turn the raw per-sample measurement fact table into one feature row per
``test_run``.

Design notes (the "why", since this is the part of the project that gets
asked about in interviews):

* The measurement table is EAV/narrow (one row per (run, param, sample_idx))
  so that the parameter set can change without a schema migration -- see
  ``hwval.db.models``. Any model needs the *wide*, one-row-per-run shape, so
  this module is the single place that does that reshape.
* Everything is pulled with one ``read_sql`` (measurement joined to
  test_run/dut/test_limit/run_label) and then reshaped with pandas
  groupby/pivot -- pushing the join and the row filter down to the database
  and doing only vectorised work in pandas keeps this fast even as the
  measurement table grows into the millions of rows.
* ``is_anomaly`` / ``failure_mode`` / the underlying ``test_run.status`` must
  never leak into the numeric feature set that a model trains on -- that is
  exactly the label the models are trying to predict. ``FEATURE_COLUMNS``
  is the single choke point that enforces this, so every training/serving
  script can trust it instead of re-deriving the exclusion list.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from hwval.config import get_settings
from hwval.db.engine import read_sql

# Measurement parameters present in every seeded run (see docs/INTERFACES.md).
PARAMS: list[str] = [
    "VDD_CORE_V",
    "VDD_IO_V",
    "ICC_MA",
    "TJ_C",
    "CLK_MHZ",
    "JITTER_PS",
    "LEAK_UA",
    "VOH_V",
]

# Per-parameter statistics computed for every run. Kept as a module constant
# so the naming scheme ("<param>_<stat>") is defined in exactly one place.
_STATS: list[str] = [
    "mean", "std", "min", "max", "p05", "p95", "range",
    "slope", "roughness", "ripple", "frac_oor",
]

# Columns that must never be treated as a model input -- they either *are*
# the label (is_anomaly, failure_mode) or are a non-feature identifier
# (run_id). Kept private and only consumed through FEATURE_COLUMNS().
_LEAKAGE_COLUMNS = {"run_id", "is_anomaly", "failure_mode"}

_CATEGORICAL_COLUMNS = ["corner", "part_number", "silicon_rev"]


def _param_in_clause() -> str:
    return ", ".join(f"'{p}'" for p in PARAMS)


def _run_filter_clause(run_ids: list[int] | None, alias: str) -> str:
    """Inline-safe IN-clause: run_ids are always ints from our own DB, and
    PARAMS is a fixed module constant, so there is no untrusted input here."""
    if run_ids is None:
        return ""
    if not run_ids:
        return "AND 1 = 0"
    ids = ", ".join(str(int(i)) for i in run_ids)
    return f"AND {alias}.run_id IN ({ids})"


def _fetch_joined(run_ids: list[int] | None) -> pd.DataFrame:
    """The single round trip: measurement joined to test_run, dut, test_limit
    and (left-joined) run_label. One query beats pulling four tables and
    merging them in Python, and it lets the database apply the run_id filter
    before any data crosses the wire."""
    sql = f"""
        SELECT
            m.run_id, m.sample_idx, m.param_name, m.value,
            r.corner, r.temp_setpoint_c, r.supply_setpoint_v,
            d.serial AS dut_serial, d.part_number, d.silicon_rev,
            tl.limit_low, tl.limit_high,
            rl.is_anomaly, rl.failure_mode
        FROM measurement m
        JOIN test_run r ON r.id = m.run_id
        JOIN dut d ON d.id = r.dut_id
        JOIN test_limit tl ON tl.param_name = m.param_name
        LEFT JOIN run_label rl ON rl.run_id = m.run_id
        WHERE m.param_name IN ({_param_in_clause()})
        {_run_filter_clause(run_ids, alias="m")}
    """
    return read_sql(sql)


def _read_param_values(run_ids: list[int] | None) -> pd.DataFrame:
    """Lighter query for the sequence tensor: no joins, just the raw samples."""
    sql = f"""
        SELECT run_id, sample_idx, param_name, value
        FROM measurement
        WHERE param_name IN ({_param_in_clause()})
        {_run_filter_clause(run_ids, alias="measurement")}
    """
    return read_sql(sql)


def _param_stats(g: pd.DataFrame) -> pd.Series:
    """Per-(run, parameter) descriptive + shape statistics.

    slope/roughness/ripple all describe *how* the parameter moved over the
    run, not just its level -- that is what lets a model tell a slow thermal
    ramp (thermal_runaway) apart from a step change (iddq_leakage_shift)
    even when their means end up similar.
    """
    g = g.sort_values("sample_idx")
    y = g["value"].to_numpy(dtype=float)
    n = len(y)

    if n > 1:
        x = np.linspace(0.0, 1.0, n)  # normalised so slope is comparable across run lengths
        slope, intercept = np.polyfit(x, y, 1)
        resid = y - (slope * x + intercept)
        roughness = float(np.mean(np.abs(np.diff(y))))
    else:
        slope, resid, roughness = 0.0, np.zeros(1), 0.0

    lo, hi = g["limit_low"].iloc[0], g["limit_high"].iloc[0]
    frac_oor = float(np.mean((y < lo) | (y > hi))) if n else 0.0

    return pd.Series({
        "mean": float(np.mean(y)) if n else np.nan,
        "std": float(np.std(y, ddof=0)) if n else np.nan,
        "min": float(np.min(y)) if n else np.nan,
        "max": float(np.max(y)) if n else np.nan,
        "p05": float(np.percentile(y, 5)) if n else np.nan,
        "p95": float(np.percentile(y, 95)) if n else np.nan,
        "range": float(np.max(y) - np.min(y)) if n else np.nan,
        "slope": float(slope),
        "roughness": roughness,
        "ripple": float(np.std(resid, ddof=0)),
        "frac_oor": frac_oor,
    })


def _pairwise_cross_features(pivot: pd.DataFrame) -> pd.DataFrame:
    """Features that relate two parameters sample-for-sample and therefore
    cannot be derived from the independent per-parameter stats above."""

    def _fn(g: pd.DataFrame) -> pd.Series:
        g = g.droplevel("run_id").sort_index()
        leak_slope = np.nan
        if {"TJ_C", "LEAK_UA"} <= set(g.columns):
            tj = g["TJ_C"].to_numpy(dtype=float)
            leak = g["LEAK_UA"].to_numpy(dtype=float)
            mask = ~np.isnan(tj) & ~np.isnan(leak)
            if mask.sum() > 1 and np.std(tj[mask]) > 1e-9:
                leak_slope = float(np.polyfit(tj[mask], leak[mask], 1)[0])

        power_mean = np.nan
        if {"VDD_CORE_V", "ICC_MA"} <= set(g.columns):
            power_mean = float((g["VDD_CORE_V"] * g["ICC_MA"] / 1000.0).mean())

        return pd.Series({"leakage_temp_slope": leak_slope, "power_est_mean": power_mean})

    return pivot.groupby(level="run_id").apply(_fn)


def build_feature_frame(run_ids: list[int] | None = None) -> pd.DataFrame:
    """One row per test_run, aggregated from its per-sample measurements.

    Columns: run_id, corner, part_number, silicon_rev, temp_setpoint_c,
    supply_setpoint_v, dut_serial, one-hot dummies for the three categorical
    columns, <param>_<stat> for every PARAMS x _STATS combination, the
    cross-parameter engineered features, and finally is_anomaly/failure_mode
    (NaN / "" when a run has no run_label row yet -- e.g. freshly scored,
    unlabelled runs).
    """
    empty_cols = [
        "run_id", "corner", "part_number", "silicon_rev",
        "temp_setpoint_c", "supply_setpoint_v", "dut_serial",
        "is_anomaly", "failure_mode",
    ]
    raw = _fetch_joined(run_ids)
    if raw.empty:
        return pd.DataFrame(columns=empty_cols)

    raw["is_anomaly"] = raw["is_anomaly"].astype("float64")
    raw["failure_mode"] = raw["failure_mode"].fillna("")

    run_meta = raw.drop_duplicates("run_id").set_index("run_id")[
        ["corner", "temp_setpoint_c", "supply_setpoint_v", "dut_serial",
         "part_number", "silicon_rev", "is_anomaly", "failure_mode"]
    ]

    stat_rows = raw.groupby(["run_id", "param_name"], sort=False).apply(
        _param_stats, include_groups=False
    )
    stat_wide = stat_rows.unstack("param_name")
    stat_wide.columns = [f"{param}_{stat}" for stat, param in stat_wide.columns]

    pivot = raw.pivot_table(index=["run_id", "sample_idx"], columns="param_name", values="value")
    cross = _pairwise_cross_features(pivot)

    tj_limit_high = np.nan
    limits = raw.drop_duplicates("param_name").set_index("param_name")["limit_high"]
    if "TJ_C" in limits.index:
        tj_limit_high = float(limits.loc["TJ_C"])

    df = run_meta.join(stat_wide, how="left").join(cross, how="left").reset_index()

    # --- device-physics engineered features (see seed.py's electro-thermal
    #     loop: droop -> current/temp/jitter rise is the correlation
    #     structure these features are meant to expose) -------------------
    if "TJ_C_max" in df.columns:
        df["thermal_headroom"] = tj_limit_high - df["TJ_C_max"]
    if {"JITTER_PS_mean", "VDD_CORE_V_ripple"} <= set(df.columns):
        ripple = df["VDD_CORE_V_ripple"].where(df["VDD_CORE_V_ripple"].abs() > 1e-9)
        df["jitter_ripple_ratio"] = df["JITTER_PS_mean"] / ripple
    if {"supply_setpoint_v", "VDD_CORE_V_min"} <= set(df.columns):
        df["droop_depth"] = df["supply_setpoint_v"] - df["VDD_CORE_V_min"]

    dummies = pd.get_dummies(df[_CATEGORICAL_COLUMNS], prefix=_CATEGORICAL_COLUMNS)
    df = pd.concat([df, dummies], axis=1)

    return df


def FEATURE_COLUMNS(df: pd.DataFrame) -> list[str]:
    """Numeric model inputs only -- no run_id, no label columns. This is the
    only place that decides what a model is allowed to see; every training
    and scoring script must go through it rather than hand-rolling a column
    list, so a leakage bug can only be introduced once, here."""
    numeric = df.select_dtypes(include=[np.number, bool]).columns
    return [c for c in numeric if c not in _LEAKAGE_COLUMNS]


def param_normalisation_stats() -> tuple[np.ndarray, np.ndarray]:
    """Per-parameter mean/std over the *entire* measurement population.

    Sequence models normalise with these fixed, population-wide statistics
    rather than per-call/per-batch statistics. That is deliberate: if
    scoring a single run later recomputed mean/std from just that run's own
    samples, the features fed to the model at serving time would live on a
    different scale than the ones it trained on (train/serve skew) -- the
    exact bug the RunLabel docstring warns about, just for a continuous
    input instead of a label.
    """
    values = _read_param_values(None)
    means = values.groupby("param_name")["value"].mean().reindex(PARAMS).fillna(0.0)
    stds = values.groupby("param_name")["value"].std(ddof=0).reindex(PARAMS)
    stds = stds.mask(stds.abs() < 1e-9, 1.0).fillna(1.0)
    return means.to_numpy(dtype=np.float64), stds.to_numpy(dtype=np.float64)


def build_sequence_tensor(run_ids: list[int] | None = None) -> tuple[np.ndarray, list[int]]:
    """(n_runs, seq_len, n_params) array, z-scored per parameter, plus the
    run_ids in the same order as axis 0.

    Runs shorter than settings.sequence_length are padded by repeating their
    last sample; longer runs are truncated. Both are edge cases in this
    dataset (samples_per_run is fixed per GenConfig) but the sequence model
    should not crash if that ever changes.
    """
    settings = get_settings()
    seq_len = settings.sequence_length
    n_params = len(PARAMS)

    means, stds = param_normalisation_stats()

    raw = _read_param_values(run_ids)
    if raw.empty:
        return np.zeros((0, seq_len, n_params), dtype=np.float32), []

    wide = raw.pivot_table(index=["run_id", "sample_idx"], columns="param_name", values="value")
    wide = wide.reindex(columns=PARAMS)

    ids = sorted(int(i) for i in wide.index.get_level_values("run_id").unique())
    arr = np.zeros((len(ids), seq_len, n_params), dtype=np.float64)
    for i, rid in enumerate(ids):
        sub = wide.xs(rid, level="run_id").sort_index()
        vals = sub.to_numpy(dtype=np.float64)
        n = min(len(vals), seq_len)
        if n > 0:
            arr[i, :n, :] = vals[:n]
            if n < seq_len:
                arr[i, n:, :] = vals[n - 1]

    arr = (arr - means) / stds
    arr = np.nan_to_num(arr, nan=0.0, posinf=0.0, neginf=0.0).astype(np.float32)
    return arr, ids
