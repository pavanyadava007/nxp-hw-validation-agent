"""Assembles the validation report: metadata, tables, figures, findings,
and a SQL-traceability appendix, in md / html / pdf.

The ML layer (``hwval.ml``) is developed concurrently and may not exist, may
not have trained models yet, or may raise for unrelated reasons (missing
joblib bundle, etc). Every touch point with it is therefore a *lazy* import
inside a function body, wrapped in try/except, so this module -- and every
report it builds -- works standalone.
"""
from __future__ import annotations

import base64
import datetime as dt
import logging
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Sequence

import pandas as pd
from jinja2 import Environment, FileSystemLoader, select_autoescape

from hwval.config import get_settings
from hwval.db.engine import dialect_name, read_sql
from hwval.reporting import plots, tables

logger = logging.getLogger(__name__)

TEMPLATE_DIR = Path(__file__).parent / "templates"

ANOMALY_EVENT_SQL = (
    "SELECT run_id, severity, param_name, failure_mode, score, model_name, explanation "
    "FROM anomaly_event {where} ORDER BY score DESC"
)
LATEST_RUN_SQL = "SELECT id FROM test_run {where} ORDER BY started_at DESC LIMIT 1"


def _id_list_sql(ids: Sequence[int]) -> str:
    return ",".join(str(int(i)) for i in ids)


def _representative_run_id(run_ids: Sequence[int] | None) -> int | None:
    """Pick the run whose waveform gets the full per-sample timeseries plot."""
    where = f"WHERE id IN ({_id_list_sql(run_ids)})" if run_ids else ""
    df = read_sql(LATEST_RUN_SQL.format(where=where))
    if df.empty:
        return None
    return int(df.iloc[0]["id"])


def _anomaly_findings(run_ids: Sequence[int] | None) -> tuple[pd.DataFrame, str]:
    """Anomaly findings from ``anomaly_event`` if populated, else a best-effort
    live scoring via the (possibly absent) ML layer, else "none available"."""
    where = f"WHERE run_id IN ({_id_list_sql(run_ids)})" if run_ids else ""
    df = read_sql(ANOMALY_EVENT_SQL.format(where=where))
    if not df.empty:
        return df, "anomaly_event table"

    try:
        from hwval.ml.predict import score_runs  # lazy: hwval.ml may not exist yet

        live = score_runs(list(run_ids) if run_ids else None)
        if live is not None and not live.empty:
            return live, "live ML scoring (hwval.ml.predict.score_runs)"
    except ImportError:
        logger.info("hwval.ml not available; skipping live anomaly scoring in report")
    except Exception as exc:  # model bundle missing, DB not ready, etc.
        logger.info("Live ML scoring unavailable for report: %s", exc)

    return pd.DataFrame(), "none"


def _executive_summary(narrative: str | None, summary_df: pd.DataFrame,
                        anomaly_df: pd.DataFrame, anomaly_source: str) -> str:
    if narrative:
        return narrative

    if summary_df.empty:
        return "No test runs are in scope for this report."

    total_runs = int(summary_df["n_runs"].sum())
    total_pass = int(summary_df["n_pass"].sum())
    overall_yield = 100.0 * total_pass / total_runs if total_runs else float("nan")
    worst = summary_df.loc[summary_df["yield_pct"].idxmin()]

    lines = [
        f"{total_runs} test runs across {len(summary_df)} PVT corners were analysed, "
        f"for an overall yield of {overall_yield:.1f}%.",
        f"The weakest corner was {worst['corner']} at {worst['yield_pct']:.1f}% yield.",
    ]
    if anomaly_source == "none":
        lines.append("No anomaly-detection data is available yet (ML pipeline not run).")
    else:
        lines.append(f"{len(anomaly_df)} anomaly finding(s) were sourced from {anomaly_source}.")
    return " ".join(lines)


def _figure_paths(run_ids: Sequence[int] | None) -> dict[str, Path]:
    out: dict[str, Path] = {"pareto": plots.plot_yield_pareto(), "wafer": plots.plot_wafer_map(),
                             "corr": plots.plot_correlation_heatmap(), "anomaly": plots.plot_anomaly_scores()}
    for p in tables.KEY_PARAMS:
        out[f"box_{p}"] = plots.plot_corner_boxplot(p)
    rep_run = _representative_run_id(run_ids)
    if rep_run is not None:
        out["timeseries"] = plots.plot_parameter_timeseries(rep_run)
    return out


def _scope_desc(run_ids: Sequence[int] | None) -> str:
    if not run_ids:
        return "all test runs currently in the database"
    ids = ", ".join(str(int(i)) for i in run_ids)
    return f"run_id in [{ids}]"


def _scope_tag(run_ids: Sequence[int] | None) -> str:
    if not run_ids:
        return "all"
    return "runs_" + "_".join(str(int(i)) for i in sorted(run_ids))


def _sql_appendix() -> list[tuple[str, str]]:
    """The exact SQL templates executed while building this report.

    ``{where}``/``:param`` placeholders are filled in at call time with the
    run/parameter scope; the text below is otherwise byte-identical to what
    each module runs, kept here purely for lab traceability review.
    """
    return [
        ("Per-corner run counts (summary_table)", tables.RUN_YIELD_SQL),
        ("Per-corner key-parameter mean/std (summary_table)", tables.MEASUREMENT_STATS_SQL),
        ("Spec limits (cpk_table)", tables.CPK_LIMITS_SQL),
        ("Raw measurements for Cpk (cpk_table)", tables.CPK_MEASUREMENTS_SQL),
        ("Anomaly findings", ANOMALY_EVENT_SQL),
        ("Representative run selection", LATEST_RUN_SQL),
        ("Parameter timeseries (plot_parameter_timeseries)", plots.TIMESERIES_SQL),
        ("Corner boxplot data (plot_corner_boxplot)", plots.BOXPLOT_SQL),
        ("Yield Pareto data (plot_yield_pareto)", plots.PARETO_SQL),
        ("Correlation heatmap data (plot_correlation_heatmap)", plots.CORRELATION_SQL),
        ("Wafer map data (plot_wafer_map)", plots.WAFER_SQL_TEMPLATE),
    ]


def _b64_png(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("ascii")


def _render_markdown(*, run_ids, generated_at, dialect, scope, exec_summary,
                      summary_df, cpk_df, anomaly_df, anomaly_source, figure_paths) -> str:
    lines = [
        "# Hardware Validation Report",
        "",
        f"- **Generated (UTC):** {generated_at}",
        f"- **Database dialect:** {dialect}",
        f"- **Scope:** {scope}",
        "",
        "## Executive Summary",
        "",
        exec_summary,
        "",
        "## Yield Summary by Corner",
        "",
        tables.df_to_markdown(summary_df),
        "",
        "## Process Capability (Cp / Cpk)",
        "",
        tables.df_to_markdown(cpk_df),
        "",
        "## Figures",
        "",
    ]
    for key, path in figure_paths.items():
        lines.append(f"### {key}")
        lines.append(f"![{key}]({path.as_posix()})")
        lines.append("")

    lines += ["## Anomaly Findings", "", f"Source: {anomaly_source}", ""]
    if anomaly_df.empty:
        lines.append("No anomaly findings are available for this scope.")
    else:
        lines.append(tables.df_to_markdown(anomaly_df))
    lines.append("")

    lines += ["## Appendix: SQL Query Traceability", ""]
    for name, sql in _sql_appendix():
        lines.append(f"**{name}**")
        lines.append("```sql")
        lines.append(sql.strip())
        lines.append("```")
        lines.append("")

    return "\n".join(lines)


def _jinja_env() -> Environment:
    return Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)),
                        autoescape=select_autoescape(["html.j2"]))


def _render_html(*, run_ids, generated_at, dialect, scope, exec_summary,
                  summary_df, cpk_df, anomaly_df, anomaly_source, figure_paths) -> str:
    env = _jinja_env()
    template = env.get_template("report.html.j2")

    figures = [
        {"title": key.replace("_", " "), "data_uri": f"data:image/png;base64,{_b64_png(p)}"}
        for key, p in figure_paths.items()
    ]
    ctx = {
        "generated_at": generated_at,
        "dialect": dialect,
        "scope": scope,
        "exec_summary": exec_summary,
        "summary_table_html": summary_df.to_html(index=False, na_rep="-", border=0,
                                                  float_format=lambda x: f"{x:.4g}")
        if not summary_df.empty else "<p><em>No data.</em></p>",
        "cpk_table_html": cpk_df.to_html(index=False, na_rep="-", border=0,
                                          float_format=lambda x: f"{x:.4g}")
        if not cpk_df.empty else "<p><em>No data.</em></p>",
        "anomaly_source": anomaly_source,
        "anomaly_table_html": anomaly_df.to_html(index=False, na_rep="-", border=0)
        if not anomaly_df.empty else "<p><em>No anomaly findings for this scope.</em></p>",
        "figures": figures,
        "queries": _sql_appendix(),
    }
    return template.render(**ctx)


def _pdf_via_matplotlib(md_text: str, figure_paths: dict[str, Path], out_path: Path) -> None:
    """Last-resort PDF writer with zero external dependencies.

    WHY: weasyprint/wkhtmltopdf are optional system packages that may not be
    installed everywhere this demo runs; matplotlib is a hard dependency of
    this whole package already, so a PdfPages-based writer is the one PDF
    path guaranteed to work anywhere the rest of ``hwval.reporting`` does.
    """
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages

    with PdfPages(out_path) as pdf:
        fig = plt.figure(figsize=(8.27, 11.69))  # A4
        fig.text(0.05, 0.97, "Hardware Validation Report", fontsize=16, weight="bold",
                  va="top")
        wrapped = md_text[:6000]
        fig.text(0.05, 0.92, wrapped, fontsize=6, family="monospace", va="top", wrap=True)
        pdf.savefig(fig)
        plt.close(fig)

        for key, path in figure_paths.items():
            img = plt.imread(path)
            fig = plt.figure(figsize=(8.27, 11.69))
            ax = fig.add_axes((0.05, 0.05, 0.9, 0.85))
            ax.imshow(img)
            ax.axis("off")
            ax.set_title(key, fontsize=10)
            pdf.savefig(fig)
            plt.close(fig)


def build_validation_report(run_ids: Sequence[int] | None = None, narrative: str | None = None,
                             fmt: str = "md") -> Path:
    """Assemble the full validation report and write it to ``settings.reports_dir``.

    ``fmt="html"`` embeds every figure as a base64 data URI so the file is a
    single self-contained artifact (mail-able, no broken image links).
    ``fmt="pdf"`` tries weasyprint, then wkhtmltopdf, then a matplotlib-only
    PDF writer, and finally falls back to writing HTML with a logged warning
    if none of those are available -- a validation report must never fail to
    build just because a PDF engine isn't installed on this machine.
    """
    if fmt not in ("md", "html", "pdf"):
        raise ValueError(f"Unsupported fmt: {fmt!r} (expected md, html, or pdf)")

    settings = get_settings()
    generated_at = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    dialect = dialect_name()
    scope = _scope_desc(run_ids)

    summary_df = tables.summary_table(run_ids)
    cpk_df = tables.cpk_table(run_ids)
    anomaly_df, anomaly_source = _anomaly_findings(run_ids)
    exec_summary = _executive_summary(narrative, summary_df, anomaly_df, anomaly_source)
    figure_paths = _figure_paths(run_ids)

    scope_tag = _scope_tag(run_ids)
    kwargs = dict(run_ids=run_ids, generated_at=generated_at, dialect=dialect, scope=scope,
                  exec_summary=exec_summary, summary_df=summary_df, cpk_df=cpk_df,
                  anomaly_df=anomaly_df, anomaly_source=anomaly_source, figure_paths=figure_paths)

    md_text = _render_markdown(**kwargs)

    if fmt == "md":
        out = settings.reports_dir / f"validation_report_{scope_tag}.md"
        out.write_text(md_text, encoding="utf-8")
        return out

    html_text = _render_html(**kwargs)
    if fmt == "html":
        out = settings.reports_dir / f"validation_report_{scope_tag}.html"
        out.write_text(html_text, encoding="utf-8")
        return out

    # fmt == "pdf"
    pdf_out = settings.reports_dir / f"validation_report_{scope_tag}.pdf"
    try:
        import weasyprint  # type: ignore

        weasyprint.HTML(string=html_text, base_url=str(settings.reports_dir)).write_pdf(str(pdf_out))
        return pdf_out
    except ImportError:
        logger.info("weasyprint not installed; trying wkhtmltopdf")
    except Exception as exc:  # pragma: no cover - environment dependent
        logger.warning("weasyprint failed (%s); trying wkhtmltopdf", exc)

    if shutil.which("wkhtmltopdf"):
        try:
            with tempfile.NamedTemporaryFile(suffix=".html", delete=False, dir=settings.reports_dir) as tmp:
                tmp.write(html_text.encode("utf-8"))
                tmp_path = tmp.name
            subprocess.run(
                ["wkhtmltopdf", "--quiet", "--enable-local-file-access", tmp_path, str(pdf_out)],
                check=True, capture_output=True, timeout=60,
            )
            Path(tmp_path).unlink(missing_ok=True)
            if pdf_out.exists() and pdf_out.stat().st_size > 0:
                return pdf_out
        except Exception as exc:  # pragma: no cover - environment dependent
            logger.warning("wkhtmltopdf failed (%s); trying matplotlib PDF writer", exc)

    try:
        _pdf_via_matplotlib(md_text, figure_paths, pdf_out)
        if pdf_out.exists() and pdf_out.stat().st_size > 0:
            return pdf_out
    except Exception as exc:  # pragma: no cover - environment dependent
        logger.warning("matplotlib PDF writer failed (%s); falling back to HTML", exc)

    logger.warning("No PDF engine available; writing HTML instead of %s", pdf_out.name)
    fallback = settings.reports_dir / f"validation_report_{scope_tag}.html"
    fallback.write_text(html_text, encoding="utf-8")
    return fallback
