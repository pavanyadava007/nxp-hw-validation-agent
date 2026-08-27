"""PostgreSQL maintenance agent.

This is the module behind the "design and implement a maintenance agent for a
PostgreSQL database" requirement. Every action is:

  * **introspective first** – it reports what it would do (``dry_run=True`` is
    the default) before it touches anything;
  * **logged** – every execution writes a ``maintenance_log`` row, which is what
    makes an autonomous agent acceptable in a certified environment;
  * **dialect-aware** – Postgres-only catalogue queries degrade to a documented
    SQLite equivalent so the whole project still runs in CI and on a laptop.

The LLM never writes maintenance SQL. It only chooses which of these audited,
parameterised actions to invoke — that separation is the security boundary.
"""
from __future__ import annotations

import datetime as dt
import time
from typing import Any, Callable

from sqlalchemy import text

from hwval.config import get_settings
from hwval.db.engine import dialect_name, get_engine, read_sql, session_scope
from hwval.db.models import ALL_TABLES, MaintenanceLog

# --- Postgres catalogue queries -------------------------------------------

Q_TABLE_STATS_PG = """
SELECT relname                        AS table_name,
       n_live_tup                     AS live_rows,
       n_dead_tup                     AS dead_rows,
       CASE WHEN n_live_tup > 0
            THEN round(100.0 * n_dead_tup / n_live_tup, 2) ELSE 0 END AS dead_pct,
       last_vacuum, last_autovacuum, last_analyze, last_autoanalyze,
       pg_size_pretty(pg_total_relation_size(relid)) AS total_size,
       pg_total_relation_size(relid)  AS total_bytes
FROM pg_stat_user_tables
ORDER BY pg_total_relation_size(relid) DESC
"""

Q_INDEX_USAGE_PG = """
SELECT s.relname AS table_name,
       s.indexrelname AS index_name,
       s.idx_scan AS scans,
       pg_size_pretty(pg_relation_size(s.indexrelid)) AS index_size,
       pg_relation_size(s.indexrelid) AS index_bytes,
       i.indisunique AS is_unique,
       i.indisprimary AS is_primary
FROM pg_stat_user_indexes s
JOIN pg_index i ON i.indexrelid = s.indexrelid
ORDER BY s.idx_scan ASC, pg_relation_size(s.indexrelid) DESC
"""

Q_SEQSCAN_PG = """
SELECT relname AS table_name, seq_scan, seq_tup_read, idx_scan,
       CASE WHEN seq_scan + COALESCE(idx_scan,0) > 0
            THEN round(100.0 * seq_scan / (seq_scan + COALESCE(idx_scan,0)), 1)
            ELSE 0 END AS seq_scan_pct
FROM pg_stat_user_tables
WHERE seq_scan > 0
ORDER BY seq_tup_read DESC
"""

Q_LONG_TX_PG = """
SELECT pid, state, wait_event_type,
       EXTRACT(EPOCH FROM (now() - xact_start)) AS tx_age_s,
       left(query, 160) AS query
FROM pg_stat_activity
WHERE xact_start IS NOT NULL AND state <> 'idle'
ORDER BY xact_start ASC
"""

Q_ROWCOUNTS_GENERIC = "SELECT COUNT(*) AS n FROM {table}"


def _log(action: str, target: str, dry_run: bool, details: dict, ms: float) -> None:
    try:
        with session_scope() as sess:
            sess.add(
                MaintenanceLog(
                    action=action,
                    target=target,
                    dry_run=dry_run,
                    details=details,
                    duration_ms=round(ms, 2),
                )
            )
    except Exception:  # logging must never break the maintenance action itself
        pass


def _timed(action: str, target: str, dry_run: bool, fn: Callable[[], dict]) -> dict:
    t0 = time.perf_counter()
    try:
        details = fn()
        status = "ok"
    except Exception as exc:
        details = {"error": str(exc)}
        status = "error"
    ms = (time.perf_counter() - t0) * 1000
    payload = {"action": action, "target": target, "dry_run": dry_run, "status": status, **details}
    _log(action, target, dry_run, details, ms)
    payload["duration_ms"] = round(ms, 2)
    return payload


def _safe_table(name: str) -> str:
    """Whitelist check — the only defence that actually works against injection
    when an identifier (not a value) has to be interpolated."""
    if name not in ALL_TABLES:
        raise ValueError(f"unknown table {name!r}; allowed: {', '.join(ALL_TABLES)}")
    return name


# --------------------------------------------------------------------------
# 1. inspection
# --------------------------------------------------------------------------
def table_stats() -> dict:
    """Size, row count and dead-tuple ratio per table."""

    def _run() -> dict:
        if dialect_name() == "postgresql":
            df = read_sql(Q_TABLE_STATS_PG)
            return {"rows": df.to_dict("records"), "source": "pg_stat_user_tables"}
        rows = []
        for t in ALL_TABLES:
            n = read_sql(Q_ROWCOUNTS_GENERIC.format(table=_safe_table(t))).iloc[0]["n"]
            rows.append({"table_name": t, "live_rows": int(n), "dead_rows": None})
        return {"rows": rows, "source": "count(*) (sqlite has no dead-tuple catalogue)"}

    return _timed("table_stats", "*", True, _run)


def index_advisor(unused_scan_threshold: int = 0) -> dict:
    """Find indexes that are never scanned (write amplification with no read
    benefit) and tables that are dominated by sequential scans (missing index)."""

    def _run() -> dict:
        if dialect_name() != "postgresql":
            return {
                "supported": False,
                "reason": "requires pg_stat_user_indexes; run against Postgres",
            }
        idx = read_sql(Q_INDEX_USAGE_PG)
        seq = read_sql(Q_SEQSCAN_PG)
        unused = idx[
            (idx["scans"] <= unused_scan_threshold)
            & (~idx["is_unique"])
            & (~idx["is_primary"])
        ]
        recommendations = [
            f"DROP INDEX {r.index_name};  -- {r.scans} scans, {r.index_size} wasted"
            for r in unused.itertuples()
        ]
        hot_seq = seq[(seq["seq_scan_pct"] > 60) & (seq["seq_tup_read"] > 10_000)]
        recommendations += [
            f"-- {r.table_name}: {r.seq_scan_pct}% sequential scans over "
            f"{int(r.seq_tup_read)} tuples; add an index on the filtered column"
            for r in hot_seq.itertuples()
        ]
        return {
            "supported": True,
            "unused_indexes": unused.to_dict("records"),
            "seq_scan_hotspots": hot_seq.to_dict("records"),
            "recommendations": recommendations or ["no index changes recommended"],
        }

    return _timed("index_advisor", "*", True, _run)


def integrity_check() -> dict:
    """Domain-level consistency checks that no FK constraint can express."""

    def _run() -> dict:
        checks: dict[str, Any] = {}
        checks["orphan_measurements"] = int(
            read_sql(
                "SELECT COUNT(*) n FROM measurement m "
                "LEFT JOIN test_run r ON r.id = m.run_id WHERE r.id IS NULL"
            ).iloc[0]["n"]
        )
        checks["runs_without_measurements"] = int(
            read_sql(
                "SELECT COUNT(*) n FROM test_run r "
                "LEFT JOIN measurement m ON m.run_id = r.id WHERE m.id IS NULL"
            ).iloc[0]["n"]
        )
        # the passed flag must agree with the spec limits it was derived from
        checks["passed_flag_mismatch"] = int(
            read_sql(
                "SELECT COUNT(*) n FROM measurement m JOIN test_limit l "
                "  ON l.param_name = m.param_name "
                "WHERE (m.value BETWEEN l.limit_low AND l.limit_high) <> m.passed"
            ).iloc[0]["n"]
        )
        checks["unlimited_parameters"] = read_sql(
            "SELECT DISTINCT m.param_name FROM measurement m "
            "LEFT JOIN test_limit l ON l.param_name = m.param_name "
            "WHERE l.id IS NULL"
        )["param_name"].tolist()
        checks["runs_missing_label"] = int(
            read_sql(
                "SELECT COUNT(*) n FROM test_run r "
                "LEFT JOIN run_label l ON l.run_id = r.id WHERE l.id IS NULL"
            ).iloc[0]["n"]
        )
        checks["clean"] = (
            checks["orphan_measurements"] == 0
            and checks["passed_flag_mismatch"] == 0
            and not checks["unlimited_parameters"]
        )
        return checks

    return _timed("integrity_check", "*", True, _run)


def long_running_transactions(min_age_s: float = 30.0) -> dict:
    def _run() -> dict:
        if dialect_name() != "postgresql":
            return {"supported": False, "reason": "requires pg_stat_activity"}
        df = read_sql(Q_LONG_TX_PG)
        offenders = df[df["tx_age_s"] >= min_age_s]
        return {
            "supported": True,
            "active_transactions": len(df),
            "offenders": offenders.to_dict("records"),
        }

    return _timed("long_running_transactions", "*", True, _run)


# --------------------------------------------------------------------------
# 2. actions (mutating — dry_run defaults to the settings value)
# --------------------------------------------------------------------------
def vacuum_analyze(table: str | None = None, full: bool = False, dry_run: bool | None = None) -> dict:
    """VACUUM (ANALYZE) a table. VACUUM FULL takes an ACCESS EXCLUSIVE lock, so
    it is never the default and is called out explicitly in the result."""
    s = get_settings()
    dry = s.maintenance_dry_run if dry_run is None else dry_run
    target = _safe_table(table) if table else "ALL"

    def _run() -> dict:
        if dialect_name() == "postgresql":
            stmt = f"VACUUM ({'FULL, ' if full else ''}ANALYZE) {target if table else ''}".strip()
            if dry:
                return {"would_execute": stmt, "lock": "ACCESS EXCLUSIVE" if full else "SHARE UPDATE EXCLUSIVE"}
            # VACUUM cannot run inside a transaction block
            with get_engine().connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
                conn.execute(text(stmt))
            return {"executed": stmt}
        stmt = "VACUUM" if not table else f"ANALYZE {target}"
        if dry:
            return {"would_execute": stmt, "note": "sqlite: VACUUM rewrites the whole file"}
        with get_engine().connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            conn.execute(text(stmt))
        return {"executed": stmt}

    return _timed("vacuum_analyze", target, dry, _run)


def reindex(table: str, dry_run: bool | None = None) -> dict:
    s = get_settings()
    dry = s.maintenance_dry_run if dry_run is None else dry_run
    target = _safe_table(table)

    def _run() -> dict:
        if dialect_name() == "postgresql":
            stmt = f"REINDEX TABLE CONCURRENTLY {target}"
            if dry:
                return {"would_execute": stmt, "note": "CONCURRENTLY avoids blocking writers"}
            with get_engine().connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
                conn.execute(text(stmt))
            return {"executed": stmt}
        stmt = f"REINDEX {target}"
        if dry:
            return {"would_execute": stmt}
        with get_engine().connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            conn.execute(text(stmt))
        return {"executed": stmt}

    return _timed("reindex", target, dry, _run)


def retention_purge(older_than_days: int = 180, dry_run: bool | None = None) -> dict:
    """Delete measurement rows for runs older than the retention window.

    Measurements dominate the table size (48 samples x 8 parameters per run), so
    this is the one action that actually controls storage growth. Runs, labels
    and anomaly events are kept — the aggregate history stays queryable after
    the raw samples are gone.
    """
    s = get_settings()
    dry = s.maintenance_dry_run if dry_run is None else dry_run
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=older_than_days)

    def _run() -> dict:
        affected = read_sql(
            "SELECT COUNT(*) n FROM measurement m JOIN test_run r ON r.id = m.run_id "
            "WHERE r.started_at < :cutoff",
            {"cutoff": cutoff},
        ).iloc[0]["n"]
        stmt = (
            "DELETE FROM measurement WHERE run_id IN "
            "(SELECT id FROM test_run WHERE started_at < :cutoff)"
        )
        if dry:
            return {"cutoff": cutoff.isoformat(), "rows_matched": int(affected), "would_execute": stmt}
        with get_engine().begin() as conn:
            res = conn.execute(text(stmt), {"cutoff": cutoff})
        return {
            "cutoff": cutoff.isoformat(),
            "rows_deleted": int(res.rowcount or 0),
            "executed": stmt,
        }

    return _timed("retention_purge", "measurement", dry, _run)


def partition_advisor(rows_per_partition: int = 5_000_000) -> dict:
    """Emit the DDL for converting `measurement` to a monthly range-partitioned
    table once it outgrows a single heap. Advisory only — never executed."""

    def _run() -> dict:
        n = int(read_sql("SELECT COUNT(*) n FROM measurement").iloc[0]["n"])
        span = read_sql("SELECT MIN(ts) lo, MAX(ts) hi FROM measurement").iloc[0]
        needed = n > rows_per_partition
        ddl = (
            "-- one-shot migration (run in a maintenance window)\n"
            "CREATE TABLE measurement_p (LIKE measurement INCLUDING ALL)\n"
            "  PARTITION BY RANGE (ts);\n"
            "CREATE TABLE measurement_p_2026_01 PARTITION OF measurement_p\n"
            "  FOR VALUES FROM ('2026-01-01') TO ('2026-02-01');\n"
            "-- ... one partition per month, created ahead by pg_partman\n"
            "INSERT INTO measurement_p SELECT * FROM measurement;\n"
            "ALTER TABLE measurement RENAME TO measurement_old;\n"
            "ALTER TABLE measurement_p RENAME TO measurement;"
        )
        return {
            "current_rows": n,
            "threshold": rows_per_partition,
            "recommended": needed,
            "time_span": {"from": str(span["lo"]), "to": str(span["hi"])},
            "rationale": (
                "Range-partitioning on ts turns the retention purge into a DROP "
                "PARTITION (metadata-only, no bloat) and lets the planner prune "
                "whole months for time-filtered queries."
            ),
            "ddl": ddl,
        }

    return _timed("partition_advisor", "measurement", True, _run)


# --------------------------------------------------------------------------
# 3. orchestration
# --------------------------------------------------------------------------
ACTIONS: dict[str, Callable[..., dict]] = {
    "table_stats": table_stats,
    "index_advisor": index_advisor,
    "integrity_check": integrity_check,
    "long_running_transactions": long_running_transactions,
    "vacuum_analyze": vacuum_analyze,
    "reindex": reindex,
    "retention_purge": retention_purge,
    "partition_advisor": partition_advisor,
}


def run_maintenance_plan(dry_run: bool | None = None) -> dict:
    """The nightly plan: inspect, then act on what the inspection found."""
    s = get_settings()
    dry = s.maintenance_dry_run if dry_run is None else dry_run
    report: dict[str, Any] = {"dry_run": dry, "steps": []}

    stats = table_stats()
    report["steps"].append(stats)
    bloated = [
        r["table_name"]
        for r in stats.get("rows", [])
        if (r.get("dead_pct") or 0) > 20 and (r.get("live_rows") or 0) > 10_000
    ]
    for t in bloated:
        report["steps"].append(vacuum_analyze(t, dry_run=dry))

    report["steps"].append(integrity_check())
    report["steps"].append(index_advisor())
    report["steps"].append(partition_advisor())
    report["steps"].append(retention_purge(dry_run=True))  # purge is always proposed, never silent

    report["summary"] = {
        "tables_vacuumed": bloated,
        "errors": [s_["action"] for s_ in report["steps"] if s_.get("status") == "error"],
    }
    return report


def maintenance_history(limit: int = 20) -> list[dict]:
    df = read_sql(
        "SELECT ts, action, target, dry_run, duration_ms FROM maintenance_log "
        "ORDER BY id DESC LIMIT :lim",
        {"lim": limit},
    )
    return df.to_dict("records")
