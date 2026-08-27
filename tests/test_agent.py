"""Tests for the agent/tooling layer: hwval.agent.llm, hwval.agent.tools,
hwval.agent.core.

Uses the shared session-scoped ``hwval_db`` fixture from tests/conftest.py --
these tests only read the database (route a question, run a read-only tool,
inspect the audit trail), so one small seeded DB serves the whole module.
"""
from __future__ import annotations

import json

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from hwval.agent.llm import RuleBasedChatModel
from hwval.agent.tools import ALL_TOOLS, TOOLS_BY_NAME, _validate_sql


# ---------------------------------------------------------------------------
# RuleBasedChatModel
# ---------------------------------------------------------------------------
def test_bind_tools_returns_model_with_tools_bound():
    model = RuleBasedChatModel()
    assert model.bound_tools == []

    bound = model.bind_tools(ALL_TOOLS)

    assert isinstance(bound, RuleBasedChatModel)
    assert bound is not model  # bind_tools returns a clone, not self
    assert len(bound.bound_tools) == len(ALL_TOOLS)
    names = {t.name for t in bound.bound_tools}
    assert names == set(TOOLS_BY_NAME)


ROUTING_CASES = [
    ("What is the yield by corner?", "get_yield_summary"),
    ("Please run maintenance on the database", "run_db_maintenance"),
    ("Show me the anomalous runs this week", "detect_anomalies"),
    ("Please write a test plan for the S32K344", "generate_test_plan"),
    ("Can you plot run 12?", "create_plot"),
]


@pytest.mark.parametrize("question,expected_tool", ROUTING_CASES)
def test_rule_based_routing_picks_expected_tool(question, expected_tool):
    model = RuleBasedChatModel().bind_tools(ALL_TOOLS)

    result = model.invoke([HumanMessage(content=question)])

    assert isinstance(result, AIMessage)
    assert result.tool_calls, f"no tool call produced for {question!r}"
    assert result.tool_calls[0]["name"] == expected_tool


def test_rule_based_routing_extracts_run_id_for_plot():
    model = RuleBasedChatModel().bind_tools(ALL_TOOLS)

    result = model.invoke([HumanMessage(content="Can you plot run 12?")])

    call = result.tool_calls[0]
    assert call["name"] == "create_plot"
    assert call["args"].get("run_id") == 12


def test_rule_based_model_answers_without_tool_calls_after_tool_message():
    """This is what terminates the LangGraph agent loop: once a ToolMessage is
    in the transcript, the offline model must produce a final AIMessage with
    an empty tool_calls list rather than looping forever."""
    model = RuleBasedChatModel().bind_tools(ALL_TOOLS)
    messages = [
        SystemMessage(content="system"),
        HumanMessage(content="What is the yield by corner?"),
        AIMessage(
            content="",
            tool_calls=[{"name": "get_yield_summary", "args": {}, "id": "call_1"}],
        ),
        ToolMessage(content="| corner | yield_pct |\n|---|---|\n", name="get_yield_summary", tool_call_id="call_1"),
    ]

    result = model.invoke(messages)

    assert isinstance(result, AIMessage)
    assert not result.tool_calls
    assert result.content.strip()
    assert "get_yield_summary" in result.content


# ---------------------------------------------------------------------------
# SQL guard: hwval.agent.tools._validate_sql
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO dut (serial) VALUES ('x')",
        "UPDATE test_run SET status='PASS'",
        "DELETE FROM measurement",
        "DROP TABLE dut",
        "select * from dut; drop table dut",
    ],
)
def test_validate_sql_rejects_forbidden_statements(hwval_db, sql):
    with pytest.raises(ValueError):
        _validate_sql(sql)


def test_validate_sql_rejects_multi_statement(hwval_db):
    with pytest.raises(ValueError):
        _validate_sql("SELECT 1; SELECT 2")


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM dut",
        "select id from test_run",
        "WITH x AS (SELECT 1 AS n) SELECT * FROM x",
    ],
)
def test_validate_sql_accepts_select_and_with(hwval_db, sql):
    safe = _validate_sql(sql)
    assert safe.strip().upper().startswith(("SELECT", "WITH"))


def test_validate_sql_auto_appends_limit(hwval_db):
    from hwval.config import get_settings

    safe = _validate_sql("SELECT * FROM dut")
    assert "limit" in safe.lower()
    assert str(get_settings().sql_row_limit) in safe


def test_validate_sql_limit_respects_settings_row_limit(hwval_db, monkeypatch):
    from hwval.config import reset_settings_cache

    monkeypatch.setenv("SQL_ROW_LIMIT", "7")
    reset_settings_cache()
    try:
        safe = _validate_sql("SELECT * FROM dut")
        assert safe.rstrip().endswith("LIMIT 7")
    finally:
        reset_settings_cache()


def test_validate_sql_does_not_append_limit_when_already_present(hwval_db):
    safe = _validate_sql("SELECT * FROM dut LIMIT 3")
    assert safe.lower().count("limit") == 1


def test_run_sql_query_returns_error_string_for_forbidden_statement(hwval_db):
    """@audited must swallow the ValueError _validate_sql raises and hand back
    a readable error string, not let the exception propagate into the agent
    loop."""
    result = TOOLS_BY_NAME["run_sql_query"].invoke({"sql": "DROP TABLE dut"})

    assert isinstance(result, str)
    assert result.startswith("ERROR")
    assert "run_sql_query" in result


# ---------------------------------------------------------------------------
# Audit trail
# ---------------------------------------------------------------------------
def test_tool_call_writes_agent_audit_row(hwval_db):
    from hwval.db.engine import read_sql

    before = int(read_sql("SELECT COUNT(*) AS n FROM agent_audit").iloc[0]["n"])

    TOOLS_BY_NAME["describe_schema"].invoke({})

    df = read_sql(
        "SELECT tool_name, status, latency_ms, result_preview FROM agent_audit "
        "ORDER BY id DESC LIMIT 1"
    )
    after = int(read_sql("SELECT COUNT(*) AS n FROM agent_audit").iloc[0]["n"])

    assert after == before + 1
    row = df.iloc[0]
    assert row["tool_name"] == "describe_schema"
    assert row["status"] == "ok"
    assert row["latency_ms"] >= 0
    assert row["result_preview"]  # non-empty preview of the JSON result


def test_failed_tool_call_is_also_audited_as_error(hwval_db):
    from hwval.db.engine import read_sql

    TOOLS_BY_NAME["run_sql_query"].invoke({"sql": "DROP TABLE dut"})

    df = read_sql(
        "SELECT tool_name, status, result_preview FROM agent_audit "
        "WHERE tool_name = 'run_sql_query' ORDER BY id DESC LIMIT 1"
    )
    row = df.iloc[0]
    assert row["status"] == "error"
    assert "ERROR" in row["result_preview"]


# ---------------------------------------------------------------------------
# every tool in ALL_TOOLS is invocable
# ---------------------------------------------------------------------------
TOOL_ARGS: dict[str, dict] = {
    "describe_schema": {},
    "run_sql_query": {"sql": "SELECT id FROM test_run"},
    "query_measurements": {"question": "what is the yield by corner"},
    "get_yield_summary": {},
    "list_test_runs": {"limit": 5},
    "detect_anomalies": {"top_n": 3, "persist": False},
    "evaluate_models": {},
    "create_plot": {"kind": "yield_pareto"},
    "build_report": {"fmt": "md"},
    "generate_test_plan": {"product": "S32K344", "requirements": "supply-droop robustness"},
    "run_db_maintenance": {"dry_run": True},
    "maintenance_action": {"action": "table_stats"},
    "check_db_integrity": {},
}

SLOW_TOOLS = {"train_models"}  # not exercised here: seconds-to-minutes to run
NEEDS_MODEL_ARTIFACTS = {"detect_anomalies", "evaluate_models"}

assert set(TOOL_ARGS) | SLOW_TOOLS == set(TOOLS_BY_NAME), (
    "TOOL_ARGS + SLOW_TOOLS must cover every tool in ALL_TOOLS"
)


@pytest.mark.parametrize("tool_name", sorted(TOOL_ARGS))
def test_every_tool_is_invocable(hwval_db, tool_name):
    tool = TOOLS_BY_NAME[tool_name]
    result = tool.invoke(TOOL_ARGS[tool_name])

    if tool_name in NEEDS_MODEL_ARTIFACTS and (
        result.startswith("ERROR") or "has the model been trained" in result
    ):
        pytest.skip(f"{tool_name} needs trained model artifacts: {result[:200]}")

    assert isinstance(result, str)
    assert result.strip()
    assert not result.startswith("ERROR"), result


def test_train_models_is_skipped_here():
    pytest.skip("train_models is slow (seconds-to-minutes); covered by tests/test_ml.py")


# ---------------------------------------------------------------------------
# agent end-to-end with the offline planner
# ---------------------------------------------------------------------------
def test_ask_end_to_end_offline_planner(hwval_db):
    from hwval.agent.core import ask

    run = ask("what is the yield by corner?")

    assert run.provider == "rulebased"
    assert run.answer.strip()
    assert run.answer != "(no answer produced)"
    tool_names = [c["name"] for c in run.tool_calls]
    assert "get_yield_summary" in tool_names
    assert run.elapsed_s >= 0


def test_ask_returns_agent_run_dataclass_serialisable(hwval_db):
    from hwval.agent.core import ask

    run = ask("run the database maintenance plan")

    as_dict = run.as_dict()
    json.dumps(as_dict)  # must be JSON-serialisable, e.g. for the CLI/UI
    assert as_dict["question"] == "run the database maintenance plan"
    assert any(c["name"] == "run_db_maintenance" for c in as_dict["tool_calls"])
