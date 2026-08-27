"""MCP server exposing the validation toolchain to any MCP client.

Why bother, when the tools are already LangChain tools? Because MCP decouples
the tools from the agent framework: the same audited SQL/ML/report/maintenance
actions become available inside Claude Desktop, an IDE, or another team's agent,
without them importing this codebase or getting database credentials. The
LangChain agent in ``hwval.agent`` and an MCP client are then two front-ends over
one authorised action set.

Run:
    python -m hwval.mcp_server.server                 # stdio (Claude Desktop)
    python -m hwval.mcp_server.server --http 8765     # streamable HTTP
"""
from __future__ import annotations

import argparse
import json

from mcp.server.fastmcp import FastMCP

from hwval.agent import tools as T
from hwval.db.engine import healthcheck, read_sql

mcp = FastMCP(
    "hwval",
    instructions=(
        "Hardware validation database and analysis toolkit. Query silicon test "
        "measurements, detect anomalies with trained ML models, generate figures, "
        "validation reports and test plans, and run PostgreSQL maintenance."
    ),
)


def _call(langchain_tool, **kwargs) -> str:
    """Invoke the underlying function of a LangChain tool.

    The audit decorator sits on the wrapped callable, so going through
    ``.invoke`` keeps MCP calls in the same ``agent_audit`` trail as agent calls.
    """
    return langchain_tool.invoke(kwargs)


# --- database -------------------------------------------------------------
@mcp.tool()
def describe_schema() -> str:
    """Return every table, its columns and current row counts, plus the spec limits."""
    return _call(T.describe_schema)


@mcp.tool()
def run_sql_query(sql: str) -> str:
    """Run a read-only SELECT against the validation database (auto-LIMITed)."""
    return _call(T.run_sql_query, sql=sql)


@mcp.tool()
def list_test_runs(limit: int = 20, status: str = "", corner: str = "") -> str:
    """List recent test runs, optionally filtered by status and PVT corner."""
    return _call(T.list_test_runs, limit=limit, status=status, corner=corner)


@mcp.tool()
def get_yield_summary() -> str:
    """Per-corner yield table and per-parameter Cp/Cpk capability table."""
    return _call(T.get_yield_summary)


# --- ML -------------------------------------------------------------------
@mcp.tool()
def detect_anomalies(run_id: int | None = None, top_n: int = 10) -> str:
    """Score runs for hardware anomalies with the fused ML ensemble."""
    return _call(T.detect_anomalies, run_id=run_id, top_n=top_n)


@mcp.tool()
def evaluate_models() -> str:
    """Compare the ML models against the naive spec-limit screen."""
    return _call(T.evaluate_models)


# --- documents ------------------------------------------------------------
@mcp.tool()
def create_plot(kind: str, run_id: int | None = None, param_name: str = "") -> str:
    """Render a diagram (timeseries, corner_boxplot, yield_pareto, anomaly_scores,
    correlation_heatmap, wafer_map) and return its path."""
    return _call(T.create_plot, kind=kind, run_id=run_id, param_name=param_name)


@mcp.tool()
def build_report(fmt: str = "md", narrative: str = "") -> str:
    """Build the full validation report (md, html or pdf) and return its path."""
    return _call(T.build_report, fmt=fmt, narrative=narrative)


@mcp.tool()
def generate_test_plan(product: str, requirements: str, standard: str = "AEC-Q100") -> str:
    """Generate and store a structured validation test plan."""
    return _call(T.generate_test_plan, product=product, requirements=requirements, standard=standard)


# --- maintenance ----------------------------------------------------------
@mcp.tool()
def run_db_maintenance(dry_run: bool = True) -> str:
    """Run the full PostgreSQL maintenance plan (dry run by default)."""
    return _call(T.run_db_maintenance, dry_run=dry_run)


@mcp.tool()
def maintenance_action(action: str, table: str = "", dry_run: bool = True) -> str:
    """Run one named maintenance action (table_stats, index_advisor, vacuum_analyze, ...)."""
    return _call(T.maintenance_action, action=action, table=table, dry_run=dry_run)


@mcp.tool()
def check_db_integrity() -> str:
    """Domain-level consistency checks across the validation schema."""
    return _call(T.check_db_integrity)


# --- resources ------------------------------------------------------------
@mcp.resource("hwval://health")
def health() -> str:
    """Database connectivity and dialect."""
    return json.dumps(healthcheck(), indent=2)


@mcp.resource("hwval://limits")
def limits() -> str:
    """The spec-limit table — the source of truth for pass/fail."""
    return read_sql("SELECT * FROM test_limit ORDER BY param_name").to_json(orient="records")


@mcp.resource("hwval://runs/{run_id}")
def run_detail(run_id: str) -> str:
    """Full metadata and per-parameter statistics for one test run."""
    df = read_sql(
        "SELECT m.param_name, COUNT(*) n, MIN(m.value) min_v, AVG(m.value) avg_v, "
        "MAX(m.value) max_v, SUM(CASE WHEN m.passed THEN 0 ELSE 1 END) fails "
        "FROM measurement m WHERE m.run_id = :rid GROUP BY m.param_name",
        {"rid": int(run_id)},
    )
    return df.to_json(orient="records")


@mcp.prompt()
def triage_run(run_id: int) -> str:
    """Prompt template: triage one suspicious test run end to end."""
    return (
        f"Triage test run {run_id}. Steps: 1) read hwval://runs/{run_id}, "
        "2) call detect_anomalies for that run, 3) plot its timeseries, "
        "4) state the most likely failure mechanism and the evidence for it."
    )


def main() -> None:
    ap = argparse.ArgumentParser(description="hwval MCP server")
    ap.add_argument("--http", type=int, default=0, help="serve streamable HTTP on this port")
    args = ap.parse_args()
    if args.http:
        mcp.settings.port = args.http
        mcp.run(transport="streamable-http")
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
