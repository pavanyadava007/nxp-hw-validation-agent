"""Shared fixtures for the agent / tooling / maintenance / MCP / CLI test
layer.

``hwval_test_db`` is session-scoped: most of what lives in
``tests/test_agent.py``, ``tests/test_maintenance.py`` and ``tests/test_mcp.py``
only *reads* the database (tool routing, maintenance inspection, MCP
resources), so seeding one small database once for the whole session keeps
the suite fast instead of reseeding per test the way ``test_ml.py`` /
``test_reporting.py`` do (those two need a fresh DB per test because they
train models / compare row counts, so they keep their own local fixture and
are intentionally left untouched here).

``tests/test_cli.py`` mutates the database wholesale (``init --drop``,
``seed``) and therefore never uses this fixture -- it gets its own
per-test tmp_path database, following the same env-var + reset pattern.

Env vars are read/written directly with ``os.environ`` (not the function
scoped ``monkeypatch`` fixture, which cannot be session-scoped) and always
restored on teardown so nothing here leaks past the test session.
"""
from __future__ import annotations

import os

import pytest

# Kept intentionally tiny -- this DB is read by a lot of tests, so shaving
# rows here shaves time off the whole suite. 6 DUTs x 2 runs x 8 samples
# still exercises every corner/status/parameter combination the tools and
# maintenance actions touch.
TINY_SEED = dict(n_duts=6, runs_per_dut=2, samples_per_run=8, seed=11)


@pytest.fixture(scope="session", autouse=True)
def _offline_llm_provider():
    """Force the deterministic offline planner for the whole test session.

    Guarantees hermeticity even if a real provider API key happens to be
    present in the ambient environment -- this suite must never place a
    network call.
    """
    prev = os.environ.get("LLM_PROVIDER")
    os.environ["LLM_PROVIDER"] = "rulebased"
    try:
        from hwval.config import reset_settings_cache

        reset_settings_cache()
    except Exception:
        pass
    yield
    if prev is None:
        os.environ.pop("LLM_PROVIDER", None)
    else:
        os.environ["LLM_PROVIDER"] = prev
    try:
        from hwval.config import reset_settings_cache

        reset_settings_cache()
    except Exception:
        pass


@pytest.fixture(scope="session")
def hwval_test_db(tmp_path_factory):
    """Point hwval at one small, seeded, session-lifetime SQLite database.

    Yields a dict with the db path, the artifacts dir, and the seed_database()
    stats, so tests that need concrete counts (e.g. "how many runs did we
    seed") do not have to re-derive them.
    """
    base = tmp_path_factory.mktemp("hwval_session_db")
    db_path = base / "hwval.db"
    artifacts_dir = base / "artifacts"

    prev_db_url = os.environ.get("DATABASE_URL")
    prev_artifacts = os.environ.get("ARTIFACTS_DIR")
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
    os.environ["ARTIFACTS_DIR"] = str(artifacts_dir)

    from hwval.config import reset_settings_cache
    from hwval.db.engine import dispose_engine

    reset_settings_cache()
    dispose_engine()

    from hwval.db.seed import GenConfig, seed_database

    stats = seed_database(GenConfig(**TINY_SEED), verbose=False)

    yield {"db_path": db_path, "artifacts_dir": artifacts_dir, "stats": stats}

    dispose_engine()
    if prev_db_url is None:
        os.environ.pop("DATABASE_URL", None)
    else:
        os.environ["DATABASE_URL"] = prev_db_url
    if prev_artifacts is None:
        os.environ.pop("ARTIFACTS_DIR", None)
    else:
        os.environ["ARTIFACTS_DIR"] = prev_artifacts
    reset_settings_cache()


@pytest.fixture()
def hwval_db(hwval_test_db):
    """Function-scoped guarantee that hwval.config / hwval.db.engine are
    *currently* pointed at the shared session database.

    Belt-and-braces around fixture/test ordering: cheap (env vars + cache
    reset only, never reseeds) but makes every test that depends on this
    fixture independent of what ran immediately before it.
    """
    from hwval.config import get_settings, reset_settings_cache
    from hwval.db.engine import dispose_engine

    want = f"sqlite:///{hwval_test_db['db_path']}"
    if os.environ.get("DATABASE_URL") != want or os.environ.get("ARTIFACTS_DIR") != str(
        hwval_test_db["artifacts_dir"]
    ):
        os.environ["DATABASE_URL"] = want
        os.environ["ARTIFACTS_DIR"] = str(hwval_test_db["artifacts_dir"])
        reset_settings_cache()
        dispose_engine()
    get_settings()
    return hwval_test_db
