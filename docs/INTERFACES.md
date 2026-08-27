# Internal module contract (frozen)

All modules import via `hwval.*` with `src/` on `PYTHONPATH`. Settings come from
`hwval.config.get_settings()`. DB access goes through `hwval.db.engine`
(`session_scope()`, `read_sql(sql, params)`, `get_engine()`).

## Already implemented

```python
# hwval.config
get_settings() -> Settings          # .database_url .models_dir .figures_dir .reports_dir
                                    # .anomaly_contamination .sequence_length .random_seed
                                    # .sql_row_limit .sql_read_only .maintenance_dry_run
available_llm_keys() -> dict[str, bool]

# hwval.db.engine
get_engine(); dispose_engine(); session_scope(); init_db(drop=False)
read_sql(sql: str, params: dict | None = None) -> pandas.DataFrame
dialect_name() -> str; healthcheck() -> dict

# hwval.db.models
Base, DUT, TestPlan, TestRun, TestLimit, Measurement, RunLabel,
AnomalyEvent, AgentAudit, MaintenanceLog, ALL_TABLES

# hwval.db.seed
GenConfig(n_duts, runs_per_dut, samples_per_run, sample_period_s,
          anomaly_rate, glitch_rate, days_history, seed)
seed_database(cfg=None, drop=True, verbose=True) -> dict
LIMITS, CORNERS, FAILURE_MODES, PART_NUMBERS, STATIONS
```

Measurement parameters (`param_name`): `VDD_CORE_V, VDD_IO_V, ICC_MA, TJ_C,
CLK_MHZ, JITTER_PS, LEAK_UA, VOH_V`. Grain: one row per (run, param, sample_idx).

## To implement — `hwval.ml`

```python
# hwval.ml.features
PARAMS: list[str]
build_feature_frame(run_ids: list[int] | None = None) -> pandas.DataFrame
    # index-free df with columns: run_id, corner, part_number, silicon_rev,
    # temp_setpoint_c, supply_setpoint_v, <per-param stats>, is_anomaly, failure_mode
    # is_anomaly/failure_mode are NaN/"" when no run_label row exists.
FEATURE_COLUMNS(df) -> list[str]        # numeric model inputs only, no leakage
build_sequence_tensor(run_ids=None) -> tuple[np.ndarray, list[int]]
    # (n_runs, seq_len, n_params) z-scored per parameter; also returns run_ids

# hwval.ml.train_sklearn
train_sklearn(test_size=0.25, save=True) -> dict   # metrics dict, persists joblib bundle
# hwval.ml.train_tf
train_autoencoder(epochs=30, save=True) -> dict    # LSTM AE; degrades gracefully if TF missing
# hwval.ml.predict
load_models() -> dict
score_runs(run_ids: list[int] | None = None) -> pandas.DataFrame
    # columns: run_id, iforest_score, supervised_proba, ae_recon_error,
    #          fused_score, severity, predicted_failure_mode, top_features(str)
persist_anomaly_events(df) -> int    # writes AnomalyEvent rows
# hwval.ml.evaluate
evaluate_all() -> dict   # includes limit-screen baseline vs model, PR/ROC, confusion
```

Requirements: deterministic (`random_seed`), no target leakage (`is_anomaly`,
`failure_mode`, `status` must never enter `FEATURE_COLUMNS`), grouped split by
`dut` serial to avoid the same die in train and test, TensorFlow import guarded
by try/except so the repo installs without it.

## To implement — `hwval.reporting`

```python
# hwval.reporting.plots  (matplotlib, Agg backend, saves PNG, returns Path)
plot_parameter_timeseries(run_id: int, params: list[str] | None = None) -> Path
plot_corner_boxplot(param_name: str) -> Path
plot_yield_pareto() -> Path
plot_anomaly_scores() -> Path
plot_correlation_heatmap() -> Path
plot_wafer_map(part_number: str | None = None) -> Path

# hwval.reporting.tables
summary_table(...) -> pandas.DataFrame ; df_to_markdown(df) -> str
cpk_table() -> pandas.DataFrame     # per-parameter Cp/Cpk vs spec limits

# hwval.reporting.report
build_validation_report(run_ids=None, narrative: str | None = None,
                        fmt: str = "md") -> Path   # fmt in {md, html, pdf}

# hwval.reporting.testplan
generate_test_plan(product: str, requirements: str, standard: str = "AEC-Q100",
                   llm=None) -> str                # markdown; deterministic fallback if llm None
save_test_plan(name, version, content_md, generated_by="llm") -> int
```

Rules: matplotlib only (no seaborn), one chart per figure, no explicit colours
beyond a single defined palette constant, figures written to
`get_settings().figures_dir`, reports to `reports_dir`. PDF generation must fall
back to HTML when no PDF engine is present.
