"""Tests for hwval.reporting: plots, tables, report assembly, and test plans.

Each test gets a fresh tiny SQLite DB under tmp_path so tests never touch the
shared artifacts/hwval_test.db and can run in parallel / repeatedly.
"""
from __future__ import annotations

import math

import pytest


@pytest.fixture()
def seeded_env(tmp_path, monkeypatch):
    """Point config + engine at a throwaway tmp_path SQLite DB, seed it small."""
    db_path = tmp_path / "hwval_test.db"
    artifacts_dir = tmp_path / "artifacts"

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("ARTIFACTS_DIR", str(artifacts_dir))

    from hwval.config import reset_settings_cache
    from hwval.db.engine import dispose_engine

    reset_settings_cache()
    dispose_engine()

    from hwval.db.seed import GenConfig, seed_database

    stats = seed_database(
        GenConfig(n_duts=6, runs_per_dut=3, samples_per_run=12, seed=7), verbose=False
    )

    yield {"stats": stats}

    dispose_engine()
    reset_settings_cache()


# ---------------------------------------------------------------------------
# plots
# ---------------------------------------------------------------------------
def _assert_nonempty_png(path):
    assert path.exists(), f"{path} was not written"
    assert path.suffix == ".png"
    assert path.stat().st_size > 0
    with open(path, "rb") as fh:
        assert fh.read(8) == b"\x89PNG\r\n\x1a\n"


def test_plot_parameter_timeseries(seeded_env):
    from hwval.db.engine import read_sql
    from hwval.reporting.plots import plot_parameter_timeseries

    run_id = int(read_sql("SELECT id FROM test_run LIMIT 1").iloc[0]["id"])
    out = plot_parameter_timeseries(run_id)
    _assert_nonempty_png(out)


def test_plot_corner_boxplot(seeded_env):
    from hwval.reporting.plots import plot_corner_boxplot

    out = plot_corner_boxplot("VDD_CORE_V")
    _assert_nonempty_png(out)


def test_plot_yield_pareto(seeded_env):
    from hwval.reporting.plots import plot_yield_pareto

    out = plot_yield_pareto()
    _assert_nonempty_png(out)


def test_plot_anomaly_scores(seeded_env):
    from hwval.reporting.plots import plot_anomaly_scores

    # anomaly_event is empty at this point (ML layer hasn't run) -- must still
    # produce a valid placeholder figure, not raise.
    out = plot_anomaly_scores()
    _assert_nonempty_png(out)


def test_plot_correlation_heatmap(seeded_env):
    from hwval.reporting.plots import plot_correlation_heatmap

    out = plot_correlation_heatmap()
    _assert_nonempty_png(out)


def test_plot_wafer_map(seeded_env):
    from hwval.reporting.plots import plot_wafer_map

    out = plot_wafer_map()
    _assert_nonempty_png(out)

    out_scoped = plot_wafer_map(part_number="S32K344")
    _assert_nonempty_png(out_scoped)
    assert out_scoped != out


# ---------------------------------------------------------------------------
# tables
# ---------------------------------------------------------------------------
def test_summary_table(seeded_env):
    from hwval.reporting.tables import summary_table

    df = summary_table()
    assert not df.empty
    assert {"corner", "n_runs", "n_pass", "n_fail", "yield_pct"}.issubset(df.columns)
    assert (df["yield_pct"] >= 0).all() and (df["yield_pct"] <= 100).all()


def test_cpk_table_finite(seeded_env):
    from hwval.db.seed import LIMITS
    from hwval.reporting.tables import cpk_table

    df = cpk_table()
    expected_params = {row[0] for row in LIMITS}
    assert set(df["param_name"]) == expected_params

    for _, row in df.iterrows():
        assert math.isfinite(row["cp"]), f"cp not finite for {row['param_name']}"
        assert math.isfinite(row["cpk"]), f"cpk not finite for {row['param_name']}"
        assert row["n"] > 0


def test_df_to_markdown(seeded_env):
    from hwval.reporting.tables import df_to_markdown, summary_table

    md = df_to_markdown(summary_table())
    assert "|" in md
    assert "corner" in md


# ---------------------------------------------------------------------------
# report
# ---------------------------------------------------------------------------
def test_build_report_markdown(seeded_env):
    from hwval.reporting.report import build_validation_report

    out = build_validation_report(fmt="md")
    assert out.exists()
    text = out.read_text(encoding="utf-8")
    assert text.strip()
    assert "# Hardware Validation Report" in text
    assert "## Appendix: SQL Query Traceability" in text


def test_build_report_html_embeds_figures(seeded_env):
    from hwval.reporting.report import build_validation_report

    out = build_validation_report(fmt="html")
    assert out.exists()
    text = out.read_text(encoding="utf-8")
    assert text.strip()
    assert "data:image/png;base64," in text
    assert "<html" in text.lower()


def test_build_report_scoped_to_run_ids(seeded_env):
    from hwval.db.engine import read_sql
    from hwval.reporting.report import build_validation_report

    run_ids = read_sql("SELECT id FROM test_run LIMIT 2")["id"].tolist()
    out = build_validation_report(run_ids=run_ids, fmt="md")
    assert out.exists()
    text = out.read_text(encoding="utf-8")
    assert f"run_id in [{run_ids[0]}, {run_ids[1]}]" in text


def test_build_report_custom_narrative(seeded_env):
    from hwval.reporting.report import build_validation_report

    out = build_validation_report(narrative="Custom executive summary text.", fmt="md")
    text = out.read_text(encoding="utf-8")
    assert "Custom executive summary text." in text


# ---------------------------------------------------------------------------
# test plan
# ---------------------------------------------------------------------------
REQUIRED_HEADINGS = [
    "## Scope",
    "## Applicable Standards",
    "## DUT Configuration",
    "## PVT Corner Matrix",
    "## Parameter / Limit Table",
    "## Test Cases",
    "## Pass/Fail Criteria",
    "## Required Instrumentation",
    "## Data Collection and Traceability Plan",
    "## Risk and Mitigation",
]


def test_generate_test_plan_deterministic(seeded_env):
    from hwval.reporting.testplan import generate_test_plan

    md = generate_test_plan("S32K344", "Automotive-grade supply and clock margin", llm=None)
    for heading in REQUIRED_HEADINGS:
        assert heading in md, f"missing section: {heading}"
    assert "TC-001" in md
    for corner in ["COLD_LOWV", "COLD_NOMV", "ROOM_NOMV", "ROOM_HIGHV", "HOT_NOMV", "HOT_HIGHV"]:
        assert corner in md


def test_generate_test_plan_llm_fallback_on_error(seeded_env):
    from hwval.reporting.testplan import generate_test_plan

    class BrokenLLM:
        def invoke(self, prompt):
            raise RuntimeError("no api key configured")

    md = generate_test_plan("i.MX93", "Bench characterization", llm=BrokenLLM())
    for heading in REQUIRED_HEADINGS:
        assert heading in md
    assert "TC-001" in md


def test_generate_test_plan_uses_llm_content(seeded_env):
    from hwval.reporting.testplan import generate_test_plan

    class FakeResponse:
        content = "# LLM-authored plan\n\nSome content."

    class FakeLLM:
        def invoke(self, prompt):
            assert "S32K344" in prompt
            return FakeResponse()

    md = generate_test_plan("S32K344", "req", llm=FakeLLM())
    assert md == "# LLM-authored plan\n\nSome content."


def test_save_test_plan_bumps_version_on_collision(seeded_env):
    from hwval.reporting.testplan import save_test_plan

    id1 = save_test_plan("Demo Plan", "1.0", "content v1")
    id2 = save_test_plan("Demo Plan", "1.0", "content v2")
    assert id1 != id2

    from hwval.db.engine import read_sql

    rows = read_sql("SELECT id, version FROM test_plan WHERE name = 'Demo Plan' ORDER BY id")
    assert len(rows) == 2
    assert rows.iloc[0]["version"] == "1.0"
    assert rows.iloc[1]["version"] == "1.1"
