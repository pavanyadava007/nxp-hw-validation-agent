"""Tests for hwval.db.maintenance.

Every action here is exercised with dry_run=True (or is inherently read-only),
so these tests never mutate the shared session database -- see
tests/conftest.py's hwval_db fixture docstring for why that sharing is safe.
"""
from __future__ import annotations

import pytest

from hwval.db import maintenance as maint

# kwargs that make every hwval.db.maintenance.ACTIONS entry callable, safely,
# against SQLite (dry_run=True everywhere a function supports it).
ACTION_KWARGS: dict[str, dict] = {
    "table_stats": {},
    "index_advisor": {},
    "integrity_check": {},
    "long_running_transactions": {},
    "vacuum_analyze": {"dry_run": True},
    "reindex": {"table": "measurement", "dry_run": True},
    "retention_purge": {"dry_run": True},
    "partition_advisor": {},
}


def test_action_kwargs_cover_every_registered_action():
    assert set(ACTION_KWARGS) == set(maint.ACTIONS)


@pytest.mark.parametrize("action_name", sorted(ACTION_KWARGS))
def test_every_maintenance_action_runs_on_sqlite_without_raising(hwval_db, action_name):
    fn = maint.ACTIONS[action_name]
    result = fn(**ACTION_KWARGS[action_name])

    assert isinstance(result, dict)
    assert result["action"] == action_name
    assert "status" in result
    assert result["status"] in ("ok", "error"), result
    # a genuine SQLite failure would show up as status=="error" with a message
    assert result["status"] == "ok", result.get("error")


def test_dry_run_retention_purge_never_mutates_rows(hwval_db):
    from hwval.db.engine import read_sql

    before = int(read_sql("SELECT COUNT(*) AS n FROM measurement").iloc[0]["n"])

    # older_than_days=0 -> cutoff is "now", so this matches virtually every
    # seeded row (all timestamps are in the past). If dry_run didn't actually
    # protect against mutation, this call would wipe the measurement table.
    result = maint.retention_purge(older_than_days=0, dry_run=True)

    after = int(read_sql("SELECT COUNT(*) AS n FROM measurement").iloc[0]["n"])

    assert after == before
    assert result["dry_run"] is True
    assert result.get("rows_matched", 0) > 0, "cutoff=now should have matched seeded rows"
    assert "would_execute" in result
    assert "executed" not in result


def test_dry_run_vacuum_analyze_never_executes(hwval_db):
    result = maint.vacuum_analyze(table="measurement", dry_run=True)
    assert result["dry_run"] is True
    assert "would_execute" in result
    assert "executed" not in result


def test_safe_table_accepts_known_table(hwval_db):
    assert maint._safe_table("measurement") == "measurement"


@pytest.mark.parametrize(
    "bad_name",
    [
        "not_a_real_table",
        "measurement; DROP TABLE measurement;--",
        "measurement WHERE 1=1",
        "",
    ],
)
def test_safe_table_rejects_unknown_or_injected_names(hwval_db, bad_name):
    with pytest.raises(ValueError):
        maint._safe_table(bad_name)


@pytest.mark.parametrize("action_name", sorted(ACTION_KWARGS))
def test_executed_action_appends_maintenance_log_row(hwval_db, action_name):
    from hwval.db.engine import read_sql

    before = int(read_sql("SELECT COUNT(*) AS n FROM maintenance_log").iloc[0]["n"])

    maint.ACTIONS[action_name](**ACTION_KWARGS[action_name])

    after = int(read_sql("SELECT COUNT(*) AS n FROM maintenance_log").iloc[0]["n"])
    assert after == before + 1

    last = read_sql("SELECT action FROM maintenance_log ORDER BY id DESC LIMIT 1")
    assert last.iloc[0]["action"] == action_name


def test_integrity_check_reports_clean_on_freshly_seeded_db(hwval_db):
    result = maint.integrity_check()

    assert result["action"] == "integrity_check"
    assert result["status"] == "ok"
    assert result["orphan_measurements"] == 0
    assert result["passed_flag_mismatch"] == 0
    assert result["unlimited_parameters"] == []
    assert result["clean"] is True


def test_run_maintenance_plan_dry_run_end_to_end(hwval_db):
    report = maint.run_maintenance_plan(dry_run=True)

    assert report["dry_run"] is True
    assert isinstance(report["steps"], list) and report["steps"]
    assert report["summary"]["errors"] == []
    step_actions = {s["action"] for s in report["steps"]}
    assert {"table_stats", "integrity_check", "index_advisor", "partition_advisor", "retention_purge"} <= step_actions


def test_maintenance_history_reflects_logged_actions(hwval_db):
    maint.table_stats()
    history = maint.maintenance_history(limit=5)

    assert isinstance(history, list)
    assert history  # at least the call above shows up
    assert "action" in history[0]
