"""Tests for hwval.mcp_server.server: the FastMCP wrapper around the same
audited tool/action set the LangChain agent uses.

FastMCP's call_tool/read_resource/list_* are coroutines; there is no
pytest-asyncio in this project's dependencies, so each test drives its own
event loop with asyncio.run() rather than adding a new test dependency.
"""
from __future__ import annotations

import asyncio

import pytest

from hwval.mcp_server import server as mcp_server

EXPECTED_TOOL_NAMES = {
    "describe_schema",
    "run_sql_query",
    "list_test_runs",
    "get_yield_summary",
    "detect_anomalies",
    "evaluate_models",
    "create_plot",
    "build_report",
    "generate_test_plan",
    "run_db_maintenance",
    "maintenance_action",
    "check_db_integrity",
}

EXPECTED_RESOURCE_URIS = {"hwval://health", "hwval://limits"}
EXPECTED_RESOURCE_TEMPLATES = {"hwval://runs/{run_id}"}


def _run(coro):
    return asyncio.run(coro)


def _text_of(call_tool_result) -> str:
    """call_tool() returns (list[ContentBlock], structured_result_dict)."""
    blocks, _structured = call_tool_result
    return "".join(getattr(b, "text", "") for b in blocks)


def test_server_lists_expected_tool_names(hwval_db):
    tools = _run(mcp_server.mcp.list_tools())
    assert {t.name for t in tools} == EXPECTED_TOOL_NAMES


def test_server_lists_expected_resources_and_templates(hwval_db):
    resources = _run(mcp_server.mcp.list_resources())
    assert {str(r.uri) for r in resources} == EXPECTED_RESOURCE_URIS

    templates = _run(mcp_server.mcp.list_resource_templates())
    assert {t.uriTemplate for t in templates} == EXPECTED_RESOURCE_TEMPLATES


def test_server_lists_expected_prompt(hwval_db):
    prompts = _run(mcp_server.mcp.list_prompts())
    assert "triage_run" in {p.name for p in prompts}


def test_call_tool_get_yield_summary_returns_nonempty_text(hwval_db):
    result = _run(mcp_server.mcp.call_tool("get_yield_summary", {}))
    text = _text_of(result)

    assert text.strip()
    assert "ERROR" not in text
    assert "corner" in text.lower()


def test_call_tool_describe_schema_returns_nonempty_text(hwval_db):
    result = _run(mcp_server.mcp.call_tool("describe_schema", {}))
    text = _text_of(result)

    assert text.strip()
    assert "ERROR" not in text
    assert "dut" in text  # a known table name should show up in the schema dump


def test_read_resource_health_returns_nonempty_text(hwval_db):
    contents = _run(mcp_server.mcp.read_resource("hwval://health"))

    assert contents
    text = contents[0].content
    assert isinstance(text, str)
    assert text.strip()
    assert '"ok": true' in text.lower()


def test_read_resource_limits_returns_nonempty_text(hwval_db):
    contents = _run(mcp_server.mcp.read_resource("hwval://limits"))

    text = contents[0].content
    assert text.strip()
    assert "VDD_CORE_V" in text


def test_read_resource_run_detail_template(hwval_db):
    from hwval.db.engine import read_sql

    run_id = int(read_sql("SELECT id FROM test_run LIMIT 1").iloc[0]["id"])

    contents = _run(mcp_server.mcp.read_resource(f"hwval://runs/{run_id}"))
    text = contents[0].content

    assert text.strip()
    assert "param_name" in text
