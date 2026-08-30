"""Streamlit demo UI for hwval — the AI-driven hardware validation agent.

Design notes
------------
* Every call into the DB/ML/reporting layers is wrapped so a missing table
  (DB never initialised), an untrained model, or an absent TensorFlow install
  degrades to an ``st.info`` with the exact ``make`` command that fixes it --
  never a traceback in front of an interviewer.
* Expensive calls (row counts, scoring, evaluation, figures) are behind
  ``st.cache_data`` with a short TTL; each cached section has its own
  "refresh" button that clears just that cache, since the underlying data
  changes only when the user seeds/trains/scores from this same app.
* The compiled LangGraph agent (``hwval.agent.core.build_agent``) is cached
  with ``st.cache_resource`` so one graph is reused across chat turns instead
  of being rebuilt on every rerun.
"""
from __future__ import annotations

import inspect
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

# --- deploy shim -----------------------------------------------------------
# Make the `hwval` package importable and pick a zero-infra SQLite database
# when the host provides no DATABASE_URL (e.g. Streamlit Community Cloud, which
# installs requirements.txt but does not `pip install -e .`). This must run
# before any `hwval.*` import below. No effect locally where hwval is already
# installed and DATABASE_URL is set.
import os
import sys

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SRC = _REPO_ROOT / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
os.environ.setdefault(
    "DATABASE_URL", f"sqlite:///{_REPO_ROOT / 'artifacts' / 'hwval.db'}"
)
# ---------------------------------------------------------------------------

from hwval.agent.core import DEMO_QUESTIONS, ask, build_agent
from hwval.agent.llm import llm_status
from hwval.config import get_settings
from hwval.db import maintenance as maint
from hwval.db.engine import dialect_name, healthcheck, read_sql
from hwval.db.models import ALL_TABLES
from hwval.db.seed import GenConfig, seed_database
from hwval.reporting import plots
from hwval.reporting.tables import cpk_table, summary_table

st.set_page_config(
    page_title="hwval — Hardware Validation Agent",
    page_icon="\U0001f52c",
    layout="wide",
)

_SEVERITY_BG = {
    "LOW": "#dcfce7",
    "MEDIUM": "#fef9c3",
    "HIGH": "#fed7aa",
    "CRITICAL": "#fecaca",
}


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------
def _error_box(exc: Exception, hint: str) -> None:
    """Uniform, traceback-free failure surface with the fix spelled out."""
    st.info(f"{hint}\n\nDetails: `{type(exc).__name__}: {exc}`")


def _refresh_button(label: str, *cached_fns: Callable, key: str) -> None:
    if st.button(label, key=key, help="Clear the cache for this section and reload"):
        for fn in cached_fns:
            fn.clear()
        st.rerun()


def _mime_for(path: Path) -> str:
    return {
        ".md": "text/markdown",
        ".html": "text/html",
        ".pdf": "application/pdf",
        ".json": "application/json",
    }.get(path.suffix, "application/octet-stream")


# ---------------------------------------------------------------------------
# cached data access
# ---------------------------------------------------------------------------
@st.cache_data(ttl=15, show_spinner=False)
def _cached_healthcheck() -> dict:
    return healthcheck()


@st.cache_data(ttl=15, show_spinner=False)
def _cached_counts() -> dict:
    duts = int(read_sql("SELECT COUNT(*) AS n FROM dut").iloc[0]["n"])
    runs = int(read_sql("SELECT COUNT(*) AS n FROM test_run").iloc[0]["n"])
    meas = int(read_sql("SELECT COUNT(*) AS n FROM measurement").iloc[0]["n"])
    passed = int(read_sql("SELECT COUNT(*) AS n FROM test_run WHERE status = 'PASS'").iloc[0]["n"])
    anomalies = int(read_sql("SELECT COUNT(DISTINCT run_id) AS n FROM anomaly_event").iloc[0]["n"])
    yield_pct = round(100.0 * passed / runs, 1) if runs else float("nan")
    return {
        "duts": duts,
        "runs": runs,
        "measurements": meas,
        "yield_pct": yield_pct,
        "anomalies": anomalies,
    }


@st.cache_data(ttl=30, show_spinner=False)
def _cached_summary_table() -> pd.DataFrame:
    return summary_table()


@st.cache_data(ttl=30, show_spinner=False)
def _cached_cpk_table() -> pd.DataFrame:
    return cpk_table()


@st.cache_data(ttl=30, show_spinner=False)
def _cached_pareto_path() -> str:
    return str(plots.plot_yield_pareto())


@st.cache_data(ttl=120, show_spinner=False)
def _cached_timeseries_path(run_id: int) -> str:
    return str(plots.plot_parameter_timeseries(run_id))


@st.cache_data(ttl=45, show_spinner=False)
def _cached_scored_runs() -> pd.DataFrame:
    from hwval.ml.predict import score_runs

    return score_runs()


@st.cache_data(ttl=60, show_spinner=False)
def _cached_models_present() -> dict:
    from hwval.ml.predict import load_models

    models = load_models()
    return {
        "sklearn": models["sklearn"] is not None,
        "autoencoder": models["autoencoder"] is not None,
        "autoencoder_backend": (models["autoencoder"] or {}).get("backend"),
    }


@st.cache_data(ttl=60, show_spinner=False)
def _cached_evaluation() -> dict:
    from hwval.ml.evaluate import evaluate_all

    return evaluate_all()


@st.cache_data(ttl=15, show_spinner=False)
def _cached_maintenance_history() -> list[dict]:
    return maint.maintenance_history(limit=15)


@st.cache_resource(show_spinner=False)
def _get_agent():
    return build_agent()


def _augment_with_latency(run_dict: dict) -> dict:
    """Join the freshly-run tool trace back to ``agent_audit`` so the trace
    can show real per-call latency (recorded there by ``hwval.agent.tools``'s
    ``@audited`` decorator) without hwval.agent.core having to track it itself."""
    n = len(run_dict.get("tool_calls", []))
    if n == 0:
        return run_dict
    try:
        audit = read_sql(
            "SELECT tool_name, latency_ms FROM agent_audit ORDER BY id DESC LIMIT :n", {"n": n}
        )
        latencies = audit.iloc[::-1]["latency_ms"].tolist()
        for call, lat in zip(run_dict["tool_calls"], latencies, strict=False):
            call["latency_ms"] = round(float(lat), 2)
    except Exception:
        pass
    return run_dict


def _style_severity(df: pd.DataFrame) -> Any:
    def _row(row: pd.Series) -> list[str]:
        color = _SEVERITY_BG.get(row.get("severity"), "")
        return [f"background-color: {color}" if color else "" for _ in row]

    return df.style.apply(_row, axis=1)


# ---------------------------------------------------------------------------
# sidebar
# ---------------------------------------------------------------------------
def _sidebar() -> None:
    st.sidebar.title("\U0001f52c hwval")
    st.sidebar.caption("AI-driven hardware validation & reporting agent")

    st.sidebar.subheader("Database")
    _refresh_button("\U0001f504 Refresh status", _cached_healthcheck, _cached_counts, key="refresh_db")
    health = _cached_healthcheck()
    if health.get("ok"):
        st.sidebar.success(f"Connected — dialect: **{health['dialect']}**")
    else:
        st.sidebar.error(f"Not connected: {health.get('error', 'unknown error')}")
    st.sidebar.caption(health.get("url", ""))

    try:
        counts = _cached_counts()
        c1, c2, c3 = st.sidebar.columns(3)
        c1.metric("DUTs", counts["duts"])
        c2.metric("Runs", counts["runs"])
        c3.metric("Meas.", f"{counts['measurements']:,}")
    except Exception as exc:
        st.sidebar.info(f"No data yet — seed the database below.\n\n`{type(exc).__name__}`")

    st.sidebar.subheader("LLM agent")
    status = llm_status()
    if status["offline_fallback"]:
        st.sidebar.warning("\U0001f50c Offline deterministic planner (no LLM API key set)")
    else:
        st.sidebar.success(f"✅ {status['provider']} / {status['model']}")
    present = [k for k, v in status["keys_present"].items() if v]
    st.sidebar.caption(f"Keys present: {', '.join(present) if present else 'none'}")

    st.sidebar.subheader("Actions")
    n_duts = st.sidebar.number_input("DUTs to seed", min_value=2, max_value=500, value=60, step=10)
    if st.sidebar.button("\U0001f331 Seed database", use_container_width=True):
        with st.spinner(f"Seeding {n_duts} DUTs..."):
            try:
                seed_database(GenConfig(n_duts=int(n_duts)), drop=True, verbose=False)
                st.cache_data.clear()
                st.sidebar.success("Seeded.")
            except Exception as exc:
                _error_box(exc, "Seeding failed.")
        st.rerun()

    include_ae = st.sidebar.checkbox("Include autoencoder", value=True)
    if st.sidebar.button("\U0001f9e0 Train models", use_container_width=True):
        with st.spinner("Training sklearn models..."):
            try:
                from hwval.ml.train_sklearn import train_sklearn

                train_sklearn()
                if include_ae:
                    from hwval.ml.train_tf import train_autoencoder

                    train_autoencoder()
                st.cache_data.clear()
                st.sidebar.success("Training complete.")
            except Exception as exc:
                _error_box(
                    exc,
                    "Training failed — this usually means there isn't enough seeded "
                    "data yet. Try `make seed` (or the Seed button above) first.",
                )
        st.rerun()


# ---------------------------------------------------------------------------
# tabs
# ---------------------------------------------------------------------------
def _tab_overview() -> None:
    _refresh_button("\U0001f504 Refresh", _cached_counts, _cached_summary_table,
                     _cached_cpk_table, _cached_pareto_path, key="refresh_overview")
    try:
        counts = _cached_counts()
    except Exception as exc:
        _error_box(exc, "Database not initialised yet. Run `make seed` or use the sidebar.")
        return

    cols = st.columns(5)
    cols[0].metric("DUTs", counts["duts"])
    cols[1].metric("Test runs", counts["runs"])
    cols[2].metric("Measurements", f"{counts['measurements']:,}")
    cols[3].metric("Yield %", counts["yield_pct"])
    cols[4].metric("Anomalous runs", counts["anomalies"])

    st.subheader("Yield by PVT corner")
    try:
        df = _cached_summary_table()
        st.dataframe(df, use_container_width=True, hide_index=True)
    except Exception as exc:
        _error_box(exc, "No yield data yet. Seed the database first (`make seed`).")

    st.subheader("Process capability (Cp/Cpk)")
    try:
        st.dataframe(_cached_cpk_table(), use_container_width=True, hide_index=True)
    except Exception as exc:
        _error_box(exc, "No measurement data yet. Seed the database first (`make seed`).")

    st.subheader("Yield loss Pareto")
    try:
        st.image(_cached_pareto_path(), use_container_width=True)
    except Exception as exc:
        _error_box(exc, "Could not render the Pareto chart. Seed the database first (`make seed`).")


def _tab_ask() -> None:
    st.caption(
        "Every answer is grounded in a tool call against the live database or ML "
        "layer — expand the trace below an answer to see exactly what ran."
    )
    st.write("**Try one of these:**")
    cols = st.columns(3)
    for i, q in enumerate(DEMO_QUESTIONS):
        if cols[i % 3].button(q, key=f"demo_q_{i}", use_container_width=True):
            st.session_state["pending_question"] = q

    st.session_state.setdefault("chat_history", [])

    for turn in st.session_state["chat_history"]:
        with st.chat_message("user"):
            st.write(turn["question"])
        with st.chat_message("assistant"):
            st.write(turn["answer"])
            label = f"Tool trace — provider: {turn['provider']}, elapsed: {turn['elapsed_s']:.2f}s"
            with st.expander(label):
                if turn["tool_calls"]:
                    for call in turn["tool_calls"]:
                        lat = call.get("latency_ms")
                        st.markdown(f"**`{call['name']}`**" + (f" — {lat} ms" if lat is not None else ""))
                        st.code(json.dumps(call.get("args", {}), default=str, indent=2), language="json")
                else:
                    st.caption("No tools were called for this answer.")

    pending = st.session_state.pop("pending_question", None)
    typed = st.chat_input("Ask about yield, anomalies, maintenance, reports...")
    question = typed or pending
    if question:
        with st.spinner("Thinking..."):
            try:
                agent = _get_agent()
                run = ask(question, agent)
                st.session_state["chat_history"].append(_augment_with_latency(run.as_dict()))
            except Exception as exc:
                st.session_state["chat_history"].append(
                    {
                        "question": question,
                        "answer": f"The agent could not complete this request ({type(exc).__name__}: {exc}).",
                        "tool_calls": [],
                        "elapsed_s": 0.0,
                        "provider": "error",
                    }
                )
        st.rerun()

    if st.session_state["chat_history"] and st.button("Clear conversation"):
        st.session_state["chat_history"] = []
        st.rerun()


def _tab_anomalies() -> None:
    _refresh_button("\U0001f504 Refresh", _cached_scored_runs, _cached_models_present, key="refresh_anom")
    try:
        present = _cached_models_present()
    except Exception:
        present = {"sklearn": False, "autoencoder": False}

    if not present["sklearn"]:
        st.info(
            "No trained sklearn models found — scores below will be zero/LOW for "
            "every run. Run `make train` (or the sidebar's Train button) to enable "
            "real anomaly detection."
        )
    if not present["autoencoder"]:
        st.caption(
            "No autoencoder artefact found (LSTM or its PCA fallback) — "
            "`ae_recon_error` will be blank. Run `make train`."
        )
    elif present["autoencoder_backend"] == "pca_fallback":
        st.caption("Autoencoder backend: PCA fallback (TensorFlow not installed/trained).")

    try:
        df = _cached_scored_runs()
    except Exception as exc:
        _error_box(exc, "Could not score runs. Seed the database first (`make seed`).")
        return

    if df.empty:
        st.info("No test runs to score yet. Seed the database first (`make seed`).")
        return

    st.subheader("Scored runs")
    show_cols = ["run_id", "fused_score", "severity", "predicted_failure_mode",
                 "iforest_score", "supervised_proba", "ae_recon_error", "top_features"]
    sorted_df = df[show_cols].sort_values("fused_score", ascending=False).reset_index(drop=True)
    st.dataframe(_style_severity(sorted_df), use_container_width=True, height=380)

    st.subheader("Run timeseries")
    run_ids = sorted_df["run_id"].tolist()
    selected = st.selectbox("Pick a run to inspect", run_ids)
    if selected is not None:
        try:
            st.image(_cached_timeseries_path(int(selected)), use_container_width=True)
        except Exception as exc:
            _error_box(exc, "Could not render the timeseries plot for this run.")


def _tab_model_performance() -> None:
    _refresh_button("\U0001f504 Refresh", _cached_evaluation, key="refresh_eval")
    try:
        result = _cached_evaluation()
    except Exception as exc:
        _error_box(
            exc,
            "Could not evaluate models. Make sure the database is seeded and run "
            "`make train` first.",
        )
        return

    rows = []
    for key in ("baseline_limit_screen", "iforest", "supervised", "autoencoder", "fused"):
        m = result.get(key)
        if not m:
            continue
        rows.append({
            "model": key,
            "precision": m.get("precision"),
            "recall": m.get("recall"),
            "f1": m.get("f1"),
            "roc_auc": m.get("roc_auc"),
            "pr_auc": m.get("pr_auc"),
        })
    comparison = pd.DataFrame(rows)

    st.subheader("Model vs. spec-limit-screen baseline")
    if comparison.empty:
        st.info("No comparable models yet. Run `make train` then `make score`.")
    else:
        st.dataframe(comparison, use_container_width=True, hide_index=True)

        try:
            import matplotlib.pyplot as plt

            fig, ax = plt.subplots(figsize=(7, 4), dpi=120)
            ax.bar(comparison["model"], comparison["f1"].fillna(0.0), color=plots.PALETTE["primary"])
            ax.set_ylabel("F1 score")
            ax.set_ylim(0, 1)
            ax.set_title("F1: baseline vs. trained models")
            ax.grid(alpha=0.3, axis="y", color=plots.PALETTE["grid"])
            fig.tight_layout()
            st.pyplot(fig)
            plt.close(fig)
        except Exception as exc:
            _error_box(exc, "Could not render the F1 comparison chart.")

    st.subheader("Test escapes vs. overkill")
    c1, c2, c3 = st.columns(3)
    c1.metric("n runs evaluated", result.get("n_runs", 0))
    c2.metric("Test escapes (baseline missed)", result.get("test_escapes", {}).get("count", 0))
    c3.metric("Overkill (baseline over-flagged)", result.get("overkill", {}).get("count", 0))
    if result.get("supervised_holdout"):
        st.caption(
            "`supervised_holdout` (true out-of-sample metrics from the grouped "
            f"train/test split): {json.dumps(result['supervised_holdout'], default=str)[:400]}"
        )


def _tab_maintenance() -> None:
    st.caption(
        "Every action below runs through `hwval.db.maintenance` — the same "
        "audited, parameterised actions the LLM agent is allowed to call. "
        "Dry run is on by default; nothing mutates the database unless you turn it off."
    )
    dry_run = st.toggle("Dry run", value=True, key="maint_dry_run")
    default_table = "measurement" if "measurement" in ALL_TABLES else ALL_TABLES[0]
    table_choice = st.selectbox(
        "Target table (used by vacuum_analyze / reindex)",
        ALL_TABLES,
        index=ALL_TABLES.index(default_table),
    )

    st.session_state.setdefault("maint_result", None)
    cols = st.columns(4)
    for i, name in enumerate(maint.ACTIONS):
        fn = maint.ACTIONS[name]
        if cols[i % 4].button(name, use_container_width=True, key=f"maint_btn_{name}"):
            params = inspect.signature(fn).parameters
            kwargs: dict[str, Any] = {}
            if "dry_run" in params:
                kwargs["dry_run"] = dry_run
            if "table" in params:
                kwargs["table"] = table_choice
            try:
                result = fn(**kwargs)
                st.session_state["maint_result"] = {"action": name, "ok": True, "result": result}
            except Exception as exc:
                st.session_state["maint_result"] = {
                    "action": name, "ok": False, "error": f"{type(exc).__name__}: {exc}"
                }
            _cached_maintenance_history.clear()

    if st.session_state["maint_result"]:
        r = st.session_state["maint_result"]
        st.subheader(f"Result: `{r['action']}`")
        st.json(r.get("result") if r.get("ok") else {"error": r.get("error")})

    st.subheader("Recent maintenance log")
    try:
        history = _cached_maintenance_history()
        st.dataframe(pd.DataFrame(history), use_container_width=True, hide_index=True)
    except Exception as exc:
        _error_box(exc, "No maintenance history yet.")


def _tab_reports() -> None:
    st.subheader("Validation report")
    st.caption(
        "Yield tables, Cp/Cpk, figures, anomaly findings and a SQL-traceability "
        "appendix, assembled from whatever is currently in the database."
    )
    cols = st.columns(3)
    for fmt, col in zip(["md", "html", "pdf"], cols, strict=True):
        if col.button(f"Build {fmt.upper()} report", use_container_width=True, key=f"report_{fmt}"):
            with st.spinner(f"Building {fmt} report..."):
                try:
                    from hwval.reporting.report import build_validation_report

                    path = build_validation_report(fmt=fmt)
                    st.session_state["report_path"] = str(path)
                    st.success(f"Built: {path.name}")
                except Exception as exc:
                    _error_box(exc, "Could not build the report. Seed the database first (`make seed`).")

    report_path = st.session_state.get("report_path")
    if report_path and Path(report_path).exists():
        p = Path(report_path)
        st.download_button(
            f"⬇️ Download {p.name}",
            data=p.read_bytes(),
            file_name=p.name,
            mime=_mime_for(p),
            use_container_width=True,
        )

    st.divider()
    st.subheader("Test-plan generator")
    with st.form("testplan_form"):
        product = st.text_input("Product", value="S32K344")
        standard = st.text_input("Standard", value="AEC-Q100")
        requirements = st.text_area(
            "Requirements", value="Supply-droop and thermal robustness over PVT corners"
        )
        submitted = st.form_submit_button("Generate test plan")

    if submitted:
        with st.spinner("Generating test plan..."):
            try:
                from hwval.agent.llm import get_chat_model, resolve_provider
                from hwval.reporting.testplan import generate_test_plan, save_test_plan

                llm = get_chat_model() if resolve_provider() != "rulebased" else None
                content = generate_test_plan(product, requirements, standard, llm=llm)
                save_test_plan(
                    f"{product} — {standard} validation", "1.0", content,
                    "llm" if llm else "template",
                )
                st.session_state["testplan_md"] = content
            except Exception as exc:
                _error_box(exc, "Could not generate the test plan.")

    md = st.session_state.get("testplan_md")
    if md:
        st.markdown(md)
        st.download_button(
            "⬇️ Download test_plan.md",
            data=md.encode("utf-8"),
            file_name=f"test_plan_{product.replace(' ', '_')}.md",
            mime="text/markdown",
            use_container_width=True,
        )


# ---------------------------------------------------------------------------
# first-run bootstrap (Streamlit Cloud / any fresh deploy)
# ---------------------------------------------------------------------------
@st.cache_resource(show_spinner=False)
def _bootstrap_demo_data() -> dict:
    """Seed + train + score once on a fresh database so the demo has data on
    first load. No-op when the DB is already populated (e.g. a redeploy that
    kept the volume, or a locally seeded DB). Runs once per server process.

    Uses the sklearn models only -- TensorFlow is intentionally not a deploy
    dependency, and hwval.ml degrades to the PCA autoencoder fallback."""
    try:
        existing = int(read_sql("SELECT COUNT(*) AS n FROM test_run").iloc[0]["n"])
    except Exception:
        existing = 0  # table/schema not created yet
    if existing > 0:
        return {"bootstrapped": False, "runs": existing}

    from hwval.ml.predict import persist_anomaly_events, score_runs
    from hwval.ml.train_sklearn import train_sklearn

    with st.spinner("First run: generating the validation campaign and training "
                    "the anomaly models (~30s, one time only)…"):
        seed_database(GenConfig(n_duts=60), drop=True, verbose=False)
        train_sklearn()
        scored = score_runs()
        persist_anomaly_events(
            scored[scored["severity"].isin(["MEDIUM", "HIGH", "CRITICAL"])]
        )
    return {"bootstrapped": True, "runs": int(len(scored))}


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main() -> None:
    get_settings()  # populate/validate config + ensure artifact dirs exist
    try:
        _bootstrap_demo_data()
    except Exception as exc:  # never crash the UI; sidebar Seed/Train is the fallback
        _error_box(exc, "Automatic first-run setup did not complete. Use the sidebar "
                        "**Seed database** then **Train models** to initialise the demo.")
    st.title("\U0001f52c Hardware Validation Agent")
    st.caption(
        f"Semiconductor test-data analysis, ML anomaly detection and reporting — "
        f"database dialect: **{dialect_name()}**"
    )
    _sidebar()

    tabs = st.tabs(
        ["Overview", "Ask the agent", "Anomalies", "Model performance", "Maintenance", "Reports"]
    )
    with tabs[0]:
        _tab_overview()
    with tabs[1]:
        _tab_ask()
    with tabs[2]:
        _tab_anomalies()
    with tabs[3]:
        _tab_model_performance()
    with tabs[4]:
        _tab_maintenance()
    with tabs[5]:
        _tab_reports()


main()
