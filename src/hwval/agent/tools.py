"""LangChain tools — the agent's entire action space.

Design rules that make this safe enough for a validation lab:

1. **The LLM never writes DDL/DML.** ``run_sql_query`` is SELECT-only, single
   statement, keyword-blacklisted and LIMIT-clamped. Everything that mutates is
   a named, parameterised action (see ``hwval.db.maintenance``).
2. **Every call is audited.** ``@audited`` writes an ``agent_audit`` row with
   arguments, latency and a result preview, so any agent-produced number in a
   report can be traced back to the query that produced it.
3. **Tools return strings.** Compact JSON or markdown, truncated — a tool that
   returns 40 kB is a tool that destroys the model's context.
4. **Tools never raise into the agent loop.** An exception becomes an error
   string the model can read and react to, which is what keeps the loop alive.
"""
from __future__ import annotations

import functools
import re
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from langchain_core.tools import tool

from hwval.agent.llm import to_json
from hwval.config import get_settings
from hwval.db import maintenance as maint
from hwval.db.engine import dialect_name, read_sql, session_scope
from hwval.db.models import ALL_TABLES, AgentAudit

SESSION_ID = str(uuid.uuid4())

FORBIDDEN_SQL = re.compile(
    r"\b(insert|update|delete|drop|alter|create|truncate|grant|revoke|copy|vacuum|"
    r"reindex|attach|pragma|call|do|merge)\b",
    re.IGNORECASE,
)


def audited(fn: Callable[..., str]) -> Callable[..., str]:
    """Log every tool invocation to ``agent_audit`` and convert exceptions to
    readable error strings."""

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> str:
        t0 = time.perf_counter()
        status = "ok"
        try:
            result = fn(*args, **kwargs)
        except Exception as exc:
            status = "error"
            result = f"ERROR in {fn.__name__}: {type(exc).__name__}: {exc}"
        ms = (time.perf_counter() - t0) * 1000
        try:
            with session_scope() as sess:
                sess.add(
                    AgentAudit(
                        session_id=SESSION_ID,
                        tool_name=fn.__name__,
                        arguments={"args": [str(a) for a in args], "kwargs": kwargs},
                        status=status,
                        latency_ms=round(ms, 2),
                        result_preview=str(result)[:500],
                    )
                )
        except Exception:
            pass
        return result

    return wrapper


# --------------------------------------------------------------------------
# 1. schema + SQL
# --------------------------------------------------------------------------
@tool
@audited
def describe_schema() -> str:
    """Return the database schema: every table, its columns with types, and the
    current row count. Call this before writing any SQL."""
    from sqlalchemy import inspect

    from hwval.db.engine import get_engine

    insp = inspect(get_engine())
    out: dict[str, Any] = {"dialect": dialect_name(), "tables": {}}
    for table in ALL_TABLES:
        cols = [f"{c['name']} {c['type']}" for c in insp.get_columns(table)]
        n = int(read_sql(f"SELECT COUNT(*) AS n FROM {table}").iloc[0]["n"])
        out["tables"][table] = {"rows": n, "columns": cols}
    out["parameters"] = read_sql(
        "SELECT param_name, unit, limit_low, limit_high FROM test_limit ORDER BY param_name"
    ).to_dict("records")
    return to_json(out, limit=8000)


def _validate_sql(sql: str) -> str:
    s = get_settings()
    stripped = sql.strip().rstrip(";").strip()
    if ";" in stripped:
        raise ValueError("only a single statement is allowed")
    if not re.match(r"^\s*(select|with)\b", stripped, re.IGNORECASE):
        raise ValueError("only SELECT/WITH queries are allowed")
    if s.sql_read_only and FORBIDDEN_SQL.search(stripped):
        raise ValueError("statement contains a forbidden keyword (read-only mode)")
    if not re.search(r"\blimit\b", stripped, re.IGNORECASE):
        stripped = f"{stripped} LIMIT {s.sql_row_limit}"
    return stripped


@tool
@audited
def run_sql_query(sql: str) -> str:
    """Run a read-only SELECT query against the validation database and return
    the rows as JSON. A LIMIT is added automatically when missing. Use
    describe_schema first to get table and column names."""
    safe = _validate_sql(sql)
    df = read_sql(safe)
    return to_json({"sql": safe, "row_count": len(df), "rows": df.to_dict("records")})


CANNED_QUERIES: dict[str, tuple[str, str]] = {
    "yield_by_corner": (
        r"yield|pass rate|by corner",
        "SELECT corner, COUNT(*) AS runs, "
        "SUM(CASE WHEN status='PASS' THEN 1 ELSE 0 END) AS passed, "
        "ROUND(100.0*SUM(CASE WHEN status='PASS' THEN 1 ELSE 0 END)/COUNT(*),1) AS yield_pct "
        "FROM test_run GROUP BY corner ORDER BY yield_pct ASC",
    ),
    "worst_parameters": (
        r"worst|which parameter|most fail|pareto",
        "SELECT param_name, COUNT(*) AS fail_samples FROM measurement "
        "WHERE passed = 0 OR passed = false GROUP BY param_name ORDER BY fail_samples DESC",
    ),
    "failed_runs": (
        r"failed runs|failing|fail list",
        "SELECT r.id AS run_id, d.serial, d.part_number, r.corner, r.status, r.started_at "
        "FROM test_run r JOIN dut d ON d.id = r.dut_id WHERE r.status='FAIL' "
        "ORDER BY r.started_at DESC LIMIT 25",
    ),
    "temperature_extremes": (
        r"temperature|thermal|tj|hot",
        "SELECT r.id AS run_id, r.corner, ROUND(MAX(m.value),2) AS max_tj_c "
        "FROM measurement m JOIN test_run r ON r.id = m.run_id "
        "WHERE m.param_name='TJ_C' GROUP BY r.id, r.corner ORDER BY max_tj_c DESC LIMIT 15",
    ),
    "campaign_overview": (
        r".*",
        "SELECT (SELECT COUNT(*) FROM dut) AS duts, "
        "(SELECT COUNT(*) FROM test_run) AS runs, "
        "(SELECT COUNT(*) FROM measurement) AS measurements, "
        "(SELECT COUNT(*) FROM test_run WHERE status='FAIL') AS failed_runs",
    ),
}


@tool
@audited
def query_measurements(question: str) -> str:
    """Answer a common validation question about the measurement database
    without writing SQL yourself. Handles yield by corner, worst parameters,
    failed runs, temperature extremes and campaign overview."""
    q = question.lower()
    for name, (pattern, sql) in CANNED_QUERIES.items():
        if re.search(pattern, q):
            df = read_sql(sql)
            return to_json({"intent": name, "sql": sql, "rows": df.to_dict("records")})
    return "no canned query matched; use run_sql_query instead"


@tool
@audited
def get_yield_summary() -> str:
    """Return the per-corner yield summary table and the per-parameter Cp/Cpk
    capability table as markdown."""
    from hwval.reporting.tables import cpk_table, df_to_markdown, summary_table

    return (
        "## Yield by corner\n"
        + df_to_markdown(summary_table())
        + "\n\n## Process capability (Cp/Cpk)\n"
        + df_to_markdown(cpk_table())
    )


@tool
@audited
def list_test_runs(limit: int = 20, status: str = "", corner: str = "") -> str:
    """List recent test runs with DUT, corner and status. Optionally filter by
    status (PASS/FAIL/ABORT) and by corner (e.g. HOT_HIGHV)."""
    clauses, params = [], {"lim": max(1, min(int(limit), 200))}
    if status:
        clauses.append("r.status = :status")
        params["status"] = status.upper()
    if corner:
        clauses.append("r.corner = :corner")
        params["corner"] = corner.upper()
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    df = read_sql(
        "SELECT r.id AS run_id, d.serial, d.part_number, d.silicon_rev, r.corner, "
        f"r.status, r.station_id, r.started_at FROM test_run r JOIN dut d ON d.id = r.dut_id {where} "
        "ORDER BY r.started_at DESC LIMIT :lim",
        params,
    )
    return to_json({"row_count": len(df), "rows": df.to_dict("records")})


# --------------------------------------------------------------------------
# 2. ML
# --------------------------------------------------------------------------
@tool
@audited
def detect_anomalies(run_id: int | None = None, top_n: int = 10, persist: bool = True) -> str:
    """Score test runs for hardware anomalies with the trained models
    (IsolationForest + supervised classifier + LSTM autoencoder, fused). Give a
    run_id for one run, otherwise the top_n most anomalous runs are returned.
    Results are written to the anomaly_event table when persist is true."""
    from hwval.ml.predict import persist_anomaly_events, score_runs

    df = score_runs([int(run_id)] if run_id else None)
    if df.empty:
        return "no runs scored — has the model been trained (make train)?"
    df = df.sort_values("fused_score", ascending=False)
    top = df if run_id else df.head(max(1, int(top_n)))
    if persist:
        flagged = df[df["severity"].isin(["MEDIUM", "HIGH", "CRITICAL"])]
        persist_anomaly_events(flagged)
    return to_json(
        {
            "scored_runs": len(df),
            "returned": len(top),
            "results": top.round(4).to_dict("records"),
        }
    )


@tool
@audited
def evaluate_models() -> str:
    """Compare the trained anomaly models against the naive spec-limit screen:
    precision, recall, F1, plus test-escape and overkill counts."""
    from hwval.ml.evaluate import evaluate_all

    return to_json(evaluate_all(), limit=8000)


@tool
@audited
def train_models(include_autoencoder: bool = False) -> str:
    """Retrain the anomaly-detection models on the current contents of the
    database. Slow (seconds to minutes) — only call when asked to retrain."""
    from hwval.ml.train_sklearn import train_sklearn

    out: dict[str, Any] = {"sklearn": train_sklearn()}
    if include_autoencoder:
        from hwval.ml.train_tf import train_autoencoder

        out["autoencoder"] = train_autoencoder()
    return to_json(out, limit=6000)


# --------------------------------------------------------------------------
# 3. visualisation + documents
# --------------------------------------------------------------------------
PLOT_KINDS = (
    "timeseries",
    "corner_boxplot",
    "yield_pareto",
    "anomaly_scores",
    "correlation_heatmap",
    "wafer_map",
)


@tool
@audited
def create_plot(kind: str, run_id: int | None = None, param_name: str = "") -> str:
    """Render a diagram and return its file path. kind must be one of:
    timeseries (needs run_id), corner_boxplot (needs param_name),
    yield_pareto, anomaly_scores, correlation_heatmap, wafer_map."""
    from hwval.reporting import plots

    kind = kind.strip().lower()
    if kind not in PLOT_KINDS:
        return f"unknown kind {kind!r}; choose from {', '.join(PLOT_KINDS)}"
    if kind == "timeseries":
        if run_id is None:
            run_id = int(read_sql("SELECT id FROM test_run ORDER BY id DESC LIMIT 1").iloc[0]["id"])
        path: Path = plots.plot_parameter_timeseries(int(run_id))
    elif kind == "corner_boxplot":
        path = plots.plot_corner_boxplot(param_name.upper() or "VDD_CORE_V")
    elif kind == "yield_pareto":
        path = plots.plot_yield_pareto()
    elif kind == "anomaly_scores":
        path = plots.plot_anomaly_scores()
    elif kind == "correlation_heatmap":
        path = plots.plot_correlation_heatmap()
    else:
        path = plots.plot_wafer_map()
    return to_json({"kind": kind, "path": str(path), "exists": Path(path).exists()})


@tool
@audited
def build_report(fmt: str = "md", narrative: str = "") -> str:
    """Build the full validation report (yield tables, Cp/Cpk, figures, anomaly
    findings, SQL appendix). fmt is md, html or pdf. Returns the file path."""
    from hwval.reporting.report import build_validation_report

    path = build_validation_report(narrative=narrative or None, fmt=fmt)
    return to_json({"format": fmt, "path": str(path), "bytes": Path(path).stat().st_size})


@tool
@audited
def generate_test_plan(product: str, requirements: str, standard: str = "AEC-Q100") -> str:
    """Generate a structured hardware validation test plan (scope, PVT corner
    matrix, parameter limits, numbered test cases, pass/fail criteria,
    instrumentation, traceability) and save it to the test_plan table."""
    from hwval.agent.llm import get_chat_model, resolve_provider
    from hwval.reporting.testplan import generate_test_plan as _gen
    from hwval.reporting.testplan import save_test_plan

    llm = get_chat_model() if resolve_provider() != "rulebased" else None
    content = _gen(product=product, requirements=requirements, standard=standard, llm=llm)
    plan_id = save_test_plan(
        name=f"{product} — {standard} validation",
        version="1.0",
        content_md=content,
        generated_by="llm" if llm else "template",
    )
    return to_json(
        {"test_plan_id": plan_id, "characters": len(content), "preview": content[:1200]}
    )


# --------------------------------------------------------------------------
# 4. database maintenance
# --------------------------------------------------------------------------
@tool
@audited
def run_db_maintenance(dry_run: bool = True) -> str:
    """Run the full PostgreSQL maintenance plan: table statistics, vacuum of
    bloated tables, integrity checks, index advice, partitioning advice and a
    retention-purge proposal. dry_run=True only reports what it would do."""
    return to_json(maint.run_maintenance_plan(dry_run=dry_run), limit=9000)


@tool
@audited
def maintenance_action(action: str, table: str = "", dry_run: bool = True) -> str:
    """Run one maintenance action by name. Available: table_stats,
    index_advisor, integrity_check, long_running_transactions, vacuum_analyze,
    reindex, retention_purge, partition_advisor."""
    fn = maint.ACTIONS.get(action)
    if fn is None:
        return f"unknown action {action!r}; available: {', '.join(maint.ACTIONS)}"
    kwargs: dict[str, Any] = {}
    if action in ("vacuum_analyze", "reindex", "retention_purge"):
        kwargs["dry_run"] = dry_run
    if action in ("vacuum_analyze", "reindex") and table:
        kwargs["table"] = table
    return to_json(fn(**kwargs), limit=8000)


@tool
@audited
def check_db_integrity() -> str:
    """Run domain-level consistency checks (orphan measurements, pass-flag vs
    spec-limit disagreement, runs without labels, parameters without limits)."""
    return to_json(maint.integrity_check())


ALL_TOOLS = [
    describe_schema,
    run_sql_query,
    query_measurements,
    get_yield_summary,
    list_test_runs,
    detect_anomalies,
    evaluate_models,
    train_models,
    create_plot,
    build_report,
    generate_test_plan,
    run_db_maintenance,
    maintenance_action,
    check_db_integrity,
]

TOOLS_BY_NAME = {t.name: t for t in ALL_TOOLS}
