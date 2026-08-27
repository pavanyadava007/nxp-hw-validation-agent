"""Matplotlib chart builders for the validation report.

Design rules (see docs/INTERFACES.md): Agg backend only (headless CI/servers),
matplotlib only (no seaborn), one chart per figure, every colour pulled from
the single module-level ``PALETTE`` constant, every axis carries physical
units, and spec limits are always drawn as dashed reference lines so a reader
can eyeball margin without cross-referencing the limit table. Every function
degrades to a "no data" placeholder figure instead of raising, because a
report must still build for a corner of the DB that happens to be empty
(e.g. ``anomaly_event`` before the ML pipeline has run).
"""
from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Sequence

import matplotlib

matplotlib.use("Agg")  # must precede pyplot import; no display server in CI/containers

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from hwval.config import get_settings  # noqa: E402
from hwval.db.engine import read_sql  # noqa: E402

DPI = 150

# Single source of colour for every chart in this module. A dict (rather than
# a bare list) so call sites can reach for semantic roles ("fail" = red) as
# well as a qualitative cycle for multi-series charts -- still exactly one
# module-level constant, per the frozen contract.
PALETTE: dict = {
    "primary": "#2563eb",
    "secondary": "#f97316",
    "pass": "#16a34a",
    "fail": "#dc2626",
    "warn": "#eab308",
    "grid": "#94a3b8",
    "muted": "#64748b",
    "categorical": [
        "#2563eb", "#f97316", "#16a34a", "#dc2626",
        "#7c3aed", "#0891b2", "#eab308", "#64748b",
    ],
}

_SEVERITY_COLORS = {"LOW": "#16a34a", "MEDIUM": "#eab308", "HIGH": "#f97316", "CRITICAL": "#dc2626"}


def _safe(name: str) -> str:
    """Collapse a string to a filesystem-safe, deterministic filename fragment."""
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", name).strip("_") or "unnamed"


def _where(conditions: Sequence[str]) -> str:
    conds = [c for c in conditions if c]
    return f"WHERE {' AND '.join(conds)}" if conds else ""


def _save(fig: "plt.Figure", out: Path) -> Path:
    fig.savefig(out, dpi=DPI)
    plt.close(fig)
    return out


# ---------------------------------------------------------------------------
# Exact SQL used by each figure, kept as module constants so the report's
# traceability appendix can quote what actually ran (dynamic run/part filters
# are appended at call time and noted separately).
# ---------------------------------------------------------------------------
TIMESERIES_SQL = (
    "SELECT param_name, sample_idx, value, unit FROM measurement "
    "WHERE run_id = :rid ORDER BY param_name, sample_idx"
)
TIMESERIES_RUNINFO_SQL = (
    "SELECT tr.corner, tr.status, d.serial FROM test_run tr "
    "JOIN dut d ON d.id = tr.dut_id WHERE tr.id = :rid"
)
LIMITS_SQL = "SELECT param_name, limit_low, limit_high FROM test_limit"
BOXPLOT_SQL = (
    "SELECT tr.corner AS corner, m.value AS value, m.unit AS unit FROM measurement m "
    "JOIN test_run tr ON tr.id = m.run_id WHERE m.param_name = :p"
)
PARETO_SQL = "SELECT param_name FROM measurement WHERE passed = 0"
ANOMALY_SCORES_SQL = "SELECT run_id, score, severity, model_name FROM anomaly_event ORDER BY run_id"
CORRELATION_SQL = "SELECT run_id, param_name, value FROM measurement"
WAFER_SQL_TEMPLATE = (
    "SELECT d.die_x AS die_x, d.die_y AS die_y, tr.status AS status "
    "FROM test_run tr JOIN dut d ON d.id = tr.dut_id {where}"
)


def plot_parameter_timeseries(run_id: int, params: list[str] | None = None) -> Path:
    """Per-sample waveform for one test run, one subplot per parameter.

    WHY: a distribution chart collapses time away. Several injected failure
    modes (vdd_droop, iddq_leakage_shift) are only visible as a shape *within*
    a run -- a sag partway through vs. a step -- so the raw trace is the chart
    an FA engineer actually opens first.
    """
    settings = get_settings()
    meas = read_sql(TIMESERIES_SQL, {"rid": int(run_id)})
    if params:
        meas = meas[meas["param_name"].isin(params)]
    run_info = read_sql(TIMESERIES_RUNINFO_SQL, {"rid": int(run_id)})
    limits = read_sql(LIMITS_SQL)
    lim_map = {r.param_name: (r.limit_low, r.limit_high) for r in limits.itertuples()}

    param_list = list(params) if params else sorted(meas["param_name"].unique().tolist())
    if not param_list:
        param_list = ["NO_DATA"]
    ncols = 2
    nrows = math.ceil(len(param_list) / ncols)
    fig, axes = plt.subplots(nrows, ncols, figsize=(6.5 * ncols, 3.1 * nrows), dpi=DPI)
    axes = np.atleast_1d(axes).ravel()

    for ax, p in zip(axes, param_list):
        sub = meas[meas["param_name"] == p]
        if sub.empty:
            ax.text(0.5, 0.5, f"no data: {p}", ha="center", va="center", transform=ax.transAxes)
            ax.set_title(p)
            continue
        unit = sub["unit"].iloc[0]
        ax.plot(sub["sample_idx"], sub["value"], color=PALETTE["primary"], marker="o",
                 markersize=2.5, linewidth=1.2)
        if p in lim_map:
            lo, hi = lim_map[p]
            ax.axhline(lo, ls="--", color=PALETTE["fail"], linewidth=1, label="spec limit")
            ax.axhline(hi, ls="--", color=PALETTE["fail"], linewidth=1)
        ax.set_xlabel("sample index")
        ax.set_ylabel(f"{p} ({unit})")
        ax.set_title(p)
        ax.grid(alpha=0.3, color=PALETTE["grid"])

    for ax in axes[len(param_list):]:
        ax.axis("off")

    if not run_info.empty:
        r = run_info.iloc[0]
        fig.suptitle(f"run {run_id} | {r['serial']} | {r['corner']} | {r['status']}")
    else:
        fig.suptitle(f"run {run_id} (not found)")
    fig.tight_layout()
    out = settings.figures_dir / f"parameter_timeseries_run{int(run_id)}.png"
    return _save(fig, out)


def plot_corner_boxplot(param_name: str) -> Path:
    """Distribution of one parameter across PVT corners.

    WHY: the box shows intrinsic spread and the whisker/median shows where a
    corner has drifted, both against the hard spec limit, in a single chart --
    the standard first-look view in a characterization report.
    """
    settings = get_settings()
    df = read_sql(BOXPLOT_SQL, {"p": param_name})
    limits = read_sql("SELECT limit_low, limit_high FROM test_limit WHERE param_name = :p",
                       {"p": param_name})

    fig, ax = plt.subplots(figsize=(8, 5), dpi=DPI)
    unit = ""
    if df.empty:
        ax.text(0.5, 0.5, f"No measurements for {param_name}", ha="center", va="center",
                transform=ax.transAxes)
    else:
        corners = sorted(df["corner"].unique())
        data = [df.loc[df["corner"] == c, "value"].to_numpy() for c in corners]
        bp = ax.boxplot(data, tick_labels=corners, patch_artist=True)
        for patch in bp["boxes"]:
            patch.set_facecolor(PALETTE["primary"])
            patch.set_alpha(0.55)
        for median in bp["medians"]:
            median.set_color(PALETTE["secondary"])
        unit = df["unit"].iloc[0]
        if not limits.empty:
            lo, hi = float(limits.iloc[0]["limit_low"]), float(limits.iloc[0]["limit_high"])
            ax.axhline(lo, ls="--", color=PALETTE["fail"], linewidth=1.2, label="spec limit")
            ax.axhline(hi, ls="--", color=PALETTE["fail"], linewidth=1.2)
            ax.legend(loc="best", fontsize=8)
        ax.tick_params(axis="x", rotation=30)

    ax.set_xlabel("PVT corner")
    ax.set_ylabel(f"{param_name} ({unit})" if unit else param_name)
    ax.set_title(f"{param_name} distribution by corner")
    ax.grid(alpha=0.3, axis="y", color=PALETTE["grid"])
    fig.tight_layout()
    out = settings.figures_dir / f"corner_boxplot_{_safe(param_name)}.png"
    return _save(fig, out)


def plot_yield_pareto() -> Path:
    """Failing-sample count by parameter, Pareto-sorted, with a cumulative-% line.

    WHY: a Pareto isolates the 1-2 parameters driving most yield loss so a
    lab spends debug effort where it pays off instead of chasing all 8
    parameters equally (classic 80/20).
    """
    settings = get_settings()
    df = read_sql(PARETO_SQL)
    fig, ax1 = plt.subplots(figsize=(8, 5), dpi=DPI)

    if df.empty:
        ax1.text(0.5, 0.5, "No failing measurements recorded", ha="center", va="center",
                  transform=ax1.transAxes)
        ax1.set_xlabel("parameter")
        ax1.set_ylabel("failing samples (count)")
    else:
        counts = df["param_name"].value_counts().sort_values(ascending=False)
        cum_pct = 100.0 * counts.cumsum() / counts.sum()
        x = np.arange(len(counts))
        ax1.bar(x, counts.to_numpy(), color=PALETTE["primary"])
        ax1.set_xticks(x)
        ax1.set_xticklabels(counts.index.tolist(), rotation=30, ha="right")
        ax1.set_ylabel("failing samples (count)")
        ax1.set_xlabel("parameter")

        ax2 = ax1.twinx()
        ax2.plot(x, cum_pct.to_numpy(), color=PALETTE["secondary"], marker="o", linewidth=1.6,
                  label="cumulative %")
        ax2.axhline(80, ls="--", color=PALETTE["fail"], linewidth=1, label="80% line")
        ax2.set_ylabel("cumulative % of failures")
        ax2.set_ylim(0, 105)
        ax2.legend(loc="lower right", fontsize=8)

    ax1.set_title("Yield loss Pareto by parameter")
    ax1.grid(alpha=0.3, axis="y", color=PALETTE["grid"])
    fig.tight_layout()
    out = settings.figures_dir / "yield_pareto.png"
    return _save(fig, out)


def plot_anomaly_scores() -> Path:
    """Detected anomaly score/severity per run, from ``anomaly_event``.

    WHY: this is the hand-off chart between the ML layer and the report. It
    must render a clear placeholder (not raise) when the ML pipeline hasn't
    populated ``anomaly_event`` yet, so report generation never blocks on ML.
    """
    settings = get_settings()
    df = read_sql(ANOMALY_SCORES_SQL)
    fig, ax = plt.subplots(figsize=(8, 5), dpi=DPI)

    if df.empty:
        ax.text(0.5, 0.5, "No anomaly_event rows yet\n(run the ML pipeline to populate)",
                ha="center", va="center", fontsize=11, color=PALETTE["muted"],
                transform=ax.transAxes)
        ax.set_xticks([])
        ax.set_yticks([])
    else:
        colors = [_SEVERITY_COLORS.get(s, PALETTE["muted"]) for s in df["severity"]]
        ax.scatter(df["run_id"], df["score"], c=colors, s=45, edgecolor="black", linewidth=0.4)
        handles = [
            plt.Line2D([0], [0], marker="o", color="w", markerfacecolor=c, markersize=8, label=s)
            for s, c in _SEVERITY_COLORS.items()
        ]
        ax.legend(handles=handles, title="severity", fontsize=8)
        ax.set_xlabel("run id")
        ax.set_ylabel("anomaly score (model-defined scale)")

    ax.set_title("Anomaly scores by run")
    ax.grid(alpha=0.3, color=PALETTE["grid"])
    fig.tight_layout()
    out = settings.figures_dir / "anomaly_scores.png"
    return _save(fig, out)


def plot_correlation_heatmap() -> Path:
    """Correlation matrix between per-run mean parameter values.

    WHY: the seeded electro-thermal loop couples VDD/ICC/TJ/JITTER by
    construction (see hwval.db.seed docstring) -- this is the chart a
    reviewer uses to sanity-check that coupling is real before trusting an
    anomaly model to exploit it.
    """
    settings = get_settings()
    df = read_sql(CORRELATION_SQL)
    fig, ax = plt.subplots(figsize=(6.5, 6), dpi=DPI)

    if df.empty:
        ax.text(0.5, 0.5, "No measurement data", ha="center", va="center", transform=ax.transAxes)
        ax.set_xticks([])
        ax.set_yticks([])
    else:
        wide = df.groupby(["run_id", "param_name"])["value"].mean().unstack("param_name")
        corr = wide.corr()
        im = ax.imshow(corr.to_numpy(), cmap="RdBu_r", vmin=-1, vmax=1)
        labels = corr.columns.tolist()
        ax.set_xticks(range(len(labels)))
        ax.set_xticklabels(labels, rotation=45, ha="right")
        ax.set_yticks(range(len(labels)))
        ax.set_yticklabels(labels)
        for i in range(len(labels)):
            for j in range(len(labels)):
                v = corr.to_numpy()[i, j]
                ax.text(j, i, f"{v:.2f}", ha="center", va="center", fontsize=7,
                         color="white" if abs(v) > 0.6 else "black")
        fig.colorbar(im, ax=ax, label="Pearson r (dimensionless)")

    ax.set_title("Per-run mean parameter correlation")
    fig.tight_layout()
    out = settings.figures_dir / "correlation_heatmap.png"
    return _save(fig, out)


def plot_wafer_map(part_number: str | None = None) -> Path:
    """Die-level failure rate scatter over wafer (die_x, die_y) position.

    WHY: a wafer map exposes spatial process signatures (e.g. edge-die yield
    loss) that any per-parameter distribution chart hides, because location
    on the wafer is thrown away the moment you look at value histograms.
    """
    settings = get_settings()
    cond = "WHERE d.part_number = :pn" if part_number else ""
    sql = WAFER_SQL_TEMPLATE.format(where=cond)
    df = read_sql(sql, {"pn": part_number} if part_number else {})

    fig, ax = plt.subplots(figsize=(6.5, 6), dpi=DPI)
    if df.empty:
        msg = "No runs found" + (f" for {part_number}" if part_number else "")
        ax.text(0.5, 0.5, msg, ha="center", va="center", transform=ax.transAxes)
    else:
        agg = (
            df.groupby(["die_x", "die_y"])["status"]
            .apply(lambda s: 100.0 * (s == "FAIL").mean())
            .reset_index(name="fail_rate_pct")
        )
        sc = ax.scatter(agg["die_x"], agg["die_y"], c=agg["fail_rate_pct"], cmap="RdYlGn_r",
                          s=90, vmin=0, vmax=100, edgecolor="black", linewidth=0.4)
        fig.colorbar(sc, ax=ax, label="failure rate (%)")

    ax.set_xlabel("die_x (wafer grid, dimensionless)")
    ax.set_ylabel("die_y (wafer grid, dimensionless)")
    title = "Wafer map — failure rate by die"
    if part_number:
        title += f" ({part_number})"
    ax.set_title(title)
    ax.set_aspect("equal")
    ax.grid(alpha=0.3, color=PALETTE["grid"])
    fig.tight_layout()
    out = settings.figures_dir / f"wafer_map_{_safe(part_number or 'all')}.png"
    return _save(fig, out)
