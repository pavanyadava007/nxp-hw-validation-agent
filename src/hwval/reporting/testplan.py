"""Test-plan generation: deterministic template by default, LLM-authored on request.

WHY a deterministic default: this whole project is meant to demo end-to-end
without an API key. ``generate_test_plan(..., llm=None)`` must always produce
a complete, DB-grounded plan; the LLM path is strictly additive and falls
back to the same deterministic plan on any failure.
"""
from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from hwval.db.engine import read_sql, session_scope
from hwval.db.models import TestPlan
from hwval.db.seed import CORNERS
from hwval.reporting.tables import df_to_markdown

logger = logging.getLogger(__name__)

LIMITS_SQL = "SELECT param_name, unit, limit_low, limit_high, spec_ref, description FROM test_limit ORDER BY param_name"


def _corner_matrix() -> pd.DataFrame:
    rows = [
        {"corner": name, "temp_setpoint_c": t, "supply_setpoint_v": v}
        for name, (t, v) in CORNERS.items()
    ]
    return pd.DataFrame(rows).sort_values("corner").reset_index(drop=True)


def _limit_table() -> pd.DataFrame:
    return read_sql(LIMITS_SQL)


def _test_cases_md(corners: pd.DataFrame, limits: pd.DataFrame) -> str:
    lines: list[str] = []
    tc = 0
    for _, row in corners.iterrows():
        tc += 1
        tc_id = f"TC-{tc:03d}"
        lines.append(f"### {tc_id}: Parametric sweep at {row['corner']}")
        lines.append("")
        lines.append(
            f"- **Setpoints:** T_amb = {row['temp_setpoint_c']:.0f} degC, "
            f"VDD_CORE = {row['supply_setpoint_v']:.2f} V"
        )
        lines.append(
            "- **Procedure:** power up DUT at the corner setpoints, allow thermal "
            "soak, then sample all tracked parameters continuously for the full "
            "run duration."
        )
        lines.append(
            "- **Parameters checked:** " + ", ".join(limits["param_name"].tolist())
        )
        lines.append(
            "- **Pass/fail:** every sample of every parameter must fall within its "
            "`test_limit` [limit_low, limit_high]; a single out-of-limit sample "
            "fails the run (see Pass/Fail Criteria)."
        )
        lines.append("")

    tc += 1
    tc_id = f"TC-{tc:03d}"
    lines.append(f"### {tc_id}: Anomaly-robustness regression")
    lines.append("")
    lines.append(
        "- **Objective:** confirm the anomaly-detection model flags injected "
        "failure signatures (vdd_droop, thermal_runaway, ldo_ripple, "
        "clock_jitter_drift, iddq_leakage_shift) while not flagging a "
        "known-healthy run affected only by an ATE contact/handler glitch."
    )
    lines.append(
        "- **Procedure:** run `hwval.ml.predict.score_runs` over a held-out set "
        "of labelled runs (`run_label` table) and compare against the ground truth."
    )
    lines.append(
        "- **Pass/fail:** recall on true anomalies and false-alarm rate on "
        "glitch-only runs must both meet the thresholds in `hwval.ml.evaluate`."
    )
    lines.append("")
    return "\n".join(lines)


def _deterministic_plan(product: str, requirements: str, standard: str) -> str:
    corners = _corner_matrix()
    limits = _limit_table()

    parts = [
        f"# Test Plan: {product}",
        "",
        "## Scope",
        "",
        f"This plan defines the electrical characterization and validation test "
        f"coverage for **{product}**, targeting the following customer/program "
        f"requirements:",
        "",
        f"> {requirements}",
        "",
        "It covers PVT (process/voltage/temperature) corner sweeps, spec-limit "
        "pass/fail screening, and anomaly-detection regression, using the "
        "measurement warehouse defined in `hwval.db.models`.",
        "",
        "## Applicable Standards",
        "",
        f"- Primary qualification standard: **{standard}**",
        "- Device grading and stress qualification follow the applicable AEC-Q100 "
        "grade for the target junction-temperature range (see Parameter/Limit "
        "table for `TJ_C`).",
        "- Measurement traceability follows internal metrology calibration "
        "procedures; all limits are sourced from `test_limit.spec_ref`.",
        "",
        "## DUT Configuration",
        "",
        f"- **Product:** {product}",
        "- **Package:** as bonded/packaged per the production flow (see `dut.package`).",
        "- **Silicon revisions under test:** as recorded per DUT in `dut.silicon_rev`.",
        "- **Sample size:** statistically representative sample per lot, spanning "
        "wafer position (die_x/die_y) to expose spatial process effects.",
        "- **Test stations:** automated ATE and bench stations, logged per run "
        "(`test_run.station_id`).",
        "",
        "## PVT Corner Matrix",
        "",
        df_to_markdown(corners, floatfmt=".2f"),
        "",
        "## Parameter / Limit Table",
        "",
        df_to_markdown(limits, floatfmt=".4g") if not limits.empty else
        "_(no limits found in `test_limit` -- seed the database before running this test plan)_",
        "",
        "## Test Cases",
        "",
        _test_cases_md(corners, limits),
        "## Pass/Fail Criteria",
        "",
        "- A run is **PASS** iff every sampled value of every parameter is within "
        "`[limit_low, limit_high]` from the Parameter/Limit table above.",
        "- A run is **FAIL** if any single sample violates its spec limit "
        "(hard limit screen); such a sample is also flagged `measurement.passed = false`.",
        "- A run is **ABORT** if the station cannot complete the programmed sequence "
        "(handler jam, contact failure, loss of communication).",
        "- An anomaly-model flag (`anomaly_event`) that does not correspond to a "
        "hard limit violation is reported as a **watch item**, not an automatic fail, "
        "and is routed to FA for disposition.",
        "",
        "## Required Instrumentation",
        "",
        "- ATE platform (or bench equivalent) capable of the corner supply/temperature "
        "setpoints in the PVT matrix above.",
        "- Precision DC source/measure unit for VDD_CORE_V / VDD_IO_V with "
        "resolution better than 1/10 of the tightest spec margin.",
        "- Thermal chamber or thermal forcing head spanning -40 degC to +125 degC.",
        "- High-impedance probe or on-die monitor for JITTER_PS / CLK_MHZ.",
        "- Picoammeter-class current measurement for LEAK_UA (IDDQ).",
        "",
        "## Data Collection and Traceability Plan",
        "",
        "- Every sample is written to `measurement` (one row per run/param/sample_idx), "
        "narrow/EAV schema so a new parameter never requires a schema migration.",
        "- Every run is linked to its DUT, test plan, station, operator, and firmware "
        "version (`test_run`), giving full genealogy from a failing sample back to "
        "the exact device and program that produced it.",
        "- Any FA disposition is recorded in `run_label` (ground truth, kept separate "
        "from model features to avoid train/serve leakage).",
        "- Any automated tool invocation against this data is logged in `agent_audit`, "
        "and any destructive/maintenance action in `maintenance_log` -- required for "
        "audit in a certified validation lab.",
        "- This test plan itself is versioned in `test_plan` (see `save_test_plan`), "
        "so every report can cite the exact plan revision it was generated against.",
        "",
        "## Risk and Mitigation",
        "",
        "| Risk | Mitigation |",
        "|---|---|",
        "| ATE contact/handler glitches produce single-sample false FAILs | "
        "Anomaly model cross-checks limit-screen fails against multi-parameter "
        "correlation before flagging a true excursion (see `plot_anomaly_scores`). |",
        "| Thermal runaway undetected until hard TJ_C limit is hit | "
        "Continuous per-sample TJ_C monitoring plus trend-based anomaly scoring "
        "catches the ramp before the hard limit trips. |",
        "| Process/wafer-position yield loss missed when viewed only in aggregate | "
        "Wafer map (die_x/die_y failure-rate heatmap) is generated every report cycle. |",
        "| Test-plan drift between revisions breaks report comparability | "
        "`test_plan.name + version` is unique-constrained; `save_test_plan` bumps "
        "the version automatically instead of silently overwriting. |",
        "| LLM-authored plan hallucinates limits or corners | "
        "Corner matrix and parameter/limit table are always pulled live from the "
        "database, never invented by the LLM; the deterministic template is the "
        "fallback on any LLM failure. |",
        "",
    ]
    return "\n".join(parts)


def _llm_prompt(product: str, requirements: str, standard: str) -> str:
    corners = df_to_markdown(_corner_matrix(), floatfmt=".2f")
    limits = _limit_table()
    limits_md = df_to_markdown(limits, floatfmt=".4g") if not limits.empty else "(none seeded)"
    return (
        "You are a senior hardware validation engineer. Write a complete test plan "
        "in markdown for the following product, grounded strictly in the data given "
        "-- do not invent PVT corners or spec limits, use exactly the ones provided.\n\n"
        f"Product: {product}\n"
        f"Requirements: {requirements}\n"
        f"Qualification standard: {standard}\n\n"
        f"PVT corner matrix:\n{corners}\n\n"
        f"Parameter/limit table:\n{limits_md}\n\n"
        "Include these sections, each as a markdown heading: Scope, Applicable "
        "Standards, DUT Configuration, PVT Corner Matrix, Parameter / Limit Table, "
        "Test Cases (with IDs TC-001, TC-002, ...), Pass/Fail Criteria, Required "
        "Instrumentation, Data Collection and Traceability Plan, Risk and Mitigation."
    )


def generate_test_plan(product: str, requirements: str, standard: str = "AEC-Q100",
                        llm: Any | None = None) -> str:
    """Return a markdown test plan.

    With ``llm=None`` this is a fully deterministic, DB-grounded template
    (what the demo runs without any API key). With an ``llm`` (a
    LangChain-style chat model exposing ``.invoke(prompt) -> response`` with
    a ``.content`` string), the model authors the plan instead -- but any
    failure (network, auth, malformed response) is caught and silently
    degrades to the same deterministic plan, so callers never need their own
    fallback logic.
    """
    if llm is not None:
        try:
            prompt = _llm_prompt(product, requirements, standard)
            response = llm.invoke(prompt)
            content = getattr(response, "content", None)
            if isinstance(content, str) and content.strip():
                return content
            logger.warning("LLM returned no usable content; using deterministic test plan")
        except Exception as exc:  # network/auth/provider errors of any shape
            logger.warning("LLM test-plan generation failed (%s); using deterministic plan", exc)

    return _deterministic_plan(product, requirements, standard)


def _bump_version(version: str) -> str:
    parts = version.split(".")
    try:
        parts[-1] = str(int(parts[-1]) + 1)
        return ".".join(parts)
    except ValueError:
        return f"{version}.1"


def save_test_plan(name: str, version: str, content_md: str, generated_by: str = "llm") -> int:
    """Insert a ``TestPlan`` row, returning its id.

    WHY bump instead of overwrite: ``test_plan`` is unique-constrained on
    (name, version) specifically so a plan revision is an immutable record --
    a validation lab needs to know exactly which plan text a given report was
    checked against. A name+version collision therefore auto-bumps the
    version rather than silently replacing history.
    """
    with session_scope() as sess:
        v = version
        while sess.query(TestPlan).filter_by(name=name, version=v).one_or_none() is not None:
            v = _bump_version(v)
        plan = TestPlan(name=name, version=v, content_md=content_md, generated_by=generated_by)
        sess.add(plan)
        sess.flush()
        return int(plan.id)
