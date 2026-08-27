"""Tests for hwval.cli -- the single entry point that ties the whole
pipeline together.

Each test gets its own throwaway tmp_path SQLite DB (init/seed mutate the
schema wholesale, so these never touch the shared session DB other test
modules use) -- same monkeypatch + reset_settings_cache()/dispose_engine()
pattern as tests/test_ml.py and tests/test_reporting.py.
"""
from __future__ import annotations

import json

import pytest

from hwval.cli import main


@pytest.fixture()
def cli_env(tmp_path, monkeypatch):
    db_path = tmp_path / "hwval_cli_test.db"
    artifacts_dir = tmp_path / "artifacts"

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("ARTIFACTS_DIR", str(artifacts_dir))
    monkeypatch.setenv("LLM_PROVIDER", "rulebased")

    from hwval.config import reset_settings_cache
    from hwval.db.engine import dispose_engine

    reset_settings_cache()
    dispose_engine()

    yield {"db_path": db_path, "artifacts_dir": artifacts_dir}

    dispose_engine()
    reset_settings_cache()


def _last_json_object(stdout: str) -> dict:
    """`hwval seed` prints a verbose python-repr progress line before the
    final JSON payload (seed_database(..., verbose=True) inside cmd_seed);
    every other JSON-printing command prints only the JSON. Either way the
    JSON payload is the block starting at the last line-start '{'."""
    idx = stdout.rfind("\n{")
    if idx == -1 and stdout.startswith("{"):
        idx = -1
    text = stdout[idx + 1 :] if idx != -1 else stdout
    return json.loads(text)


def test_cli_init_returns_0_and_prints_valid_json(cli_env, capsys):
    rc = main(["init"])

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {"ok": True, "dropped": False}


def test_cli_seed_returns_0_and_prints_valid_json(cli_env, capsys):
    rc = main(["seed", "--duts", "4", "--samples", "8"])

    assert rc == 0
    out = capsys.readouterr().out
    payload = _last_json_object(out)
    assert payload["duts"] == 4
    assert payload["runs"] > 0
    assert payload["measurements"] > 0
    assert payload["dialect"] == "sqlite"


def test_cli_seed_actually_populates_the_database(cli_env, capsys):
    main(["seed", "--duts", "4", "--samples", "8"])
    capsys.readouterr()

    from hwval.db.engine import read_sql

    n_duts = int(read_sql("SELECT COUNT(*) AS n FROM dut").iloc[0]["n"])
    assert n_duts == 4


def test_cli_maintain_returns_0_and_prints_valid_json(cli_env, capsys):
    main(["seed", "--duts", "4", "--samples", "8"])
    capsys.readouterr()

    rc = main(["maintain"])

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["dry_run"] is True  # --execute was not passed
    assert isinstance(payload["steps"], list) and payload["steps"]
    assert payload["summary"]["errors"] == []


def test_cli_ask_returns_0_and_prints_answer_and_tool_trace(cli_env, capsys):
    main(["seed", "--duts", "4", "--samples", "8"])
    capsys.readouterr()

    rc = main(["ask", "yield", "by", "corner"])

    assert rc == 0
    out = capsys.readouterr().out
    assert out.strip()
    assert "--- tool trace ---" in out
    assert "get_yield_summary" in out
    assert "provider=rulebased" in out
