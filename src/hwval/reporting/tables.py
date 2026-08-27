"""Tabular summaries for the validation report.

Everything here is a thin, deterministic aggregation over the warehouse --
no randomness, no model calls -- so the same DB state always produces the
same tables (a requirement for a report that certifies test results).
"""
from __future__ import annotations

import math
from typing import Sequence

import numpy as np
import pandas as pd

from hwval.db.engine import read_sql

# Parameters surfaced in the summary table's mean/std columns. All 8 tracked
# parameters would make an already-wide table unreadable in markdown; these
# four are the ones that carry the electro-thermal coupling described in
# hwval.db.seed, so they are the ones a reviewer checks first.
KEY_PARAMS = ["VDD_CORE_V", "ICC_MA", "TJ_C", "JITTER_PS"]

# Exact SQL used below, exposed as module constants for the report's
# traceability appendix. `{where}` is substituted with a concrete run/param
# filter at call time.
RUN_YIELD_SQL = "SELECT id, corner, status FROM test_run {where}"
MEASUREMENT_STATS_SQL = (
    "SELECT tr.corner AS corner, m.param_name AS param_name, m.value AS value "
    "FROM measurement m JOIN test_run tr ON tr.id = m.run_id {where}"
)
CPK_LIMITS_SQL = "SELECT param_name, unit, limit_low, limit_high FROM test_limit"
CPK_MEASUREMENTS_SQL = "SELECT param_name, value FROM measurement {where}"


def _where(conditions: Sequence[str]) -> str:
    conds = [c for c in conditions if c]
    return f"WHERE {' AND '.join(conds)}" if conds else ""


def _id_list_sql(ids: Sequence[int]) -> str:
    # Values come straight from DB primary keys (ints), cast defensively so
    # this can never become a string-interpolation injection point.
    return ",".join(str(int(i)) for i in ids)


def summary_table(run_ids: Sequence[int] | None = None) -> pd.DataFrame:
    """Per-corner run counts, yield %, and mean/std of key parameters.

    WHY: corner-level yield is the first thing a validation engineer checks
    after a characterization sweep -- it says *where* to look before anyone
    opens a single waveform. Key-parameter mean/std next to it lets a
    reviewer sanity-check that a yield dip lines up with a real parametric
    shift rather than a fixture/handler issue.
    """
    run_cond = f"id IN ({_id_list_sql(run_ids)})" if run_ids else ""
    runs = read_sql(RUN_YIELD_SQL.format(where=_where([run_cond])))

    cols = ["corner", "n_runs", "n_pass", "n_fail", "yield_pct"]
    cols += [f"{p}_{stat}" for p in KEY_PARAMS for stat in ("mean", "std")]
    if runs.empty:
        return pd.DataFrame(columns=cols)

    grp = runs.groupby("corner")["status"]
    out = grp.agg(n_runs="count", n_pass=lambda s: int((s == "PASS").sum())).reset_index()
    out["n_fail"] = out["n_runs"] - out["n_pass"]
    out["yield_pct"] = 100.0 * out["n_pass"] / out["n_runs"]

    m_run_cond = f"tr.id IN ({_id_list_sql(run_ids)})" if run_ids else ""
    param_cond = "m.param_name IN (" + ",".join(f"'{p}'" for p in KEY_PARAMS) + ")"
    meas = read_sql(MEASUREMENT_STATS_SQL.format(where=_where([m_run_cond, param_cond])))

    if not meas.empty:
        pivot = meas.groupby(["corner", "param_name"])["value"].agg(["mean", "std"])
        wide = pivot.unstack("param_name")
        wide.columns = [f"{p}_{stat}" for stat, p in wide.columns]
        out = out.merge(wide.reset_index(), on="corner", how="left")

    for c in cols:
        if c not in out.columns:
            out[c] = np.nan
    return out[cols].sort_values("corner").reset_index(drop=True)


def cpk_table(run_ids: Sequence[int] | None = None) -> pd.DataFrame:
    """Process-capability indices (Cp, Cpk) per parameter against its spec limit.

    Formulas (standard SPC definitions)::

        Cp  = (USL - LSL) / (6 * sigma)
        Cpk = min(USL - mu, mu - LSL) / (3 * sigma)

    where mu/sigma are the sample mean/std of the parameter's measurements,
    and USL/LSL are ``test_limit.limit_high`` / ``limit_low``.

    One-sided limits (only one of USL/LSL finite -- not present in the seeded
    schema today, but a real spec table can have them) fall back to the
    standard one-sided convention ``Cp == Cpk == (USL-mu)/(3*sigma)`` or
    ``(mu-LSL)/(3*sigma)``, since the two-sided Cp formula is undefined
    without both bounds.

    Zero/near-zero variance would make Cpk diverge to +/-inf under the
    formula above; sigma is floored at a small epsilon instead, so a
    (numerically) constant parameter still yields a finite index -- a real
    zero-spread channel is a fixture artefact worth flagging, not a reason
    for this table to crash or emit NaN/inf that breaks downstream reporting.
    """
    limits = read_sql(CPK_LIMITS_SQL)
    run_cond = f"run_id IN ({_id_list_sql(run_ids)})" if run_ids else ""
    meas = read_sql(CPK_MEASUREMENTS_SQL.format(where=_where([run_cond])))

    eps = 1e-9
    rows: list[dict] = []
    for _, lim in limits.iterrows():
        p = lim["param_name"]
        vals = meas.loc[meas["param_name"] == p, "value"] if not meas.empty else pd.Series(dtype=float)
        lsl, usl = float(lim["limit_low"]), float(lim["limit_high"])
        n = int(len(vals))

        if n == 0:
            rows.append({"param_name": p, "unit": lim["unit"], "n": 0, "mean": np.nan,
                         "std": np.nan, "cp": np.nan, "cpk": np.nan,
                         "limit_low": lsl, "limit_high": usl})
            continue

        mu = float(vals.mean())
        sigma = float(vals.std(ddof=1)) if n > 1 else 0.0
        sigma_eff = max(sigma, eps)

        lsl_ok, usl_ok = math.isfinite(lsl), math.isfinite(usl)
        if lsl_ok and usl_ok:
            cp = (usl - lsl) / (6.0 * sigma_eff)
            cpk = min(usl - mu, mu - lsl) / (3.0 * sigma_eff)
        elif usl_ok:
            cp = cpk = (usl - mu) / (3.0 * sigma_eff)
        elif lsl_ok:
            cp = cpk = (mu - lsl) / (3.0 * sigma_eff)
        else:  # no usable limit at all
            cp = cpk = float("nan")

        rows.append({"param_name": p, "unit": lim["unit"], "n": n, "mean": mu, "std": sigma,
                     "cp": cp, "cpk": cpk, "limit_low": lsl, "limit_high": usl})

    return pd.DataFrame(rows)


def df_to_markdown(df: pd.DataFrame, floatfmt: str = ".4g") -> str:
    """Render a DataFrame as GitHub-flavoured markdown (requires ``tabulate``)."""
    if df.empty:
        return "_(no data)_"
    return df.to_markdown(index=False, floatfmt=floatfmt)
