"""Tests for hwval.ml: features, sklearn training, prediction, evaluation.

Each test gets a fresh, small SQLite DB under tmp_path (and its own
artifacts dir, so trained models never touch the shared
artifacts/hwval_test.db or artifacts/models) -- same pattern as
tests/test_reporting.py.
"""
from __future__ import annotations

import pytest


@pytest.fixture()
def seeded_env(tmp_path, monkeypatch):
    """Point config + engine at a throwaway tmp_path SQLite DB, seed it small
    but with enough DUTs/anomalies for a grouped train/test split to be
    meaningful."""
    db_path = tmp_path / "hwval_ml_test.db"
    artifacts_dir = tmp_path / "artifacts"

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("ARTIFACTS_DIR", str(artifacts_dir))

    from hwval.config import reset_settings_cache
    from hwval.db.engine import dispose_engine

    reset_settings_cache()
    dispose_engine()

    from hwval.db.seed import GenConfig, seed_database

    stats = seed_database(
        GenConfig(n_duts=24, runs_per_dut=4, samples_per_run=20, anomaly_rate=0.3, seed=7),
        verbose=False,
    )

    yield {"stats": stats}

    dispose_engine()
    reset_settings_cache()


def test_feature_frame_one_row_per_run_no_leakage(seeded_env):
    from hwval.db.engine import read_sql
    from hwval.ml.features import FEATURE_COLUMNS, build_feature_frame

    df = build_feature_frame()
    n_runs = int(read_sql("SELECT COUNT(*) AS n FROM test_run").iloc[0]["n"])

    assert len(df) == n_runs
    assert df["run_id"].is_unique
    assert not df.empty

    feats = FEATURE_COLUMNS(df)
    for leak in ("is_anomaly", "failure_mode", "status", "run_id"):
        assert leak not in feats, f"{leak} must never enter FEATURE_COLUMNS"
    # every returned column must actually be numeric-ish (no stray object cols)
    assert all(str(df[c].dtype) != "object" for c in feats)


def test_sklearn_train_predict_evaluate_pipeline(seeded_env):
    from hwval.ml.evaluate import evaluate_all
    from hwval.ml.predict import score_runs
    from hwval.ml.train_sklearn import train_sklearn

    metrics = train_sklearn(test_size=0.3, save=True)
    assert metrics["supervised"]["f1"] >= 0.5, metrics["supervised"]
    assert metrics["n_features"] > 0
    assert metrics["iforest"]["contamination"] > 0

    scored = score_runs()
    expected_cols = {
        "run_id", "iforest_score", "supervised_proba", "ae_recon_error",
        "fused_score", "severity", "predicted_failure_mode", "top_features",
    }
    assert expected_cols <= set(scored.columns)
    assert not scored["run_id"].duplicated().any()
    assert scored["severity"].isin(["LOW", "MEDIUM", "HIGH", "CRITICAL"]).all()
    assert scored["fused_score"].between(0.0, 1.0 + 1e-9).all()
    # no autoencoder trained in this test -> that score column is all-NaN
    assert scored["ae_recon_error"].isna().all()

    result = evaluate_all()
    assert "baseline_limit_screen" in result
    assert "fused" in result
    assert "precision" in result["baseline_limit_screen"]
    assert "confusion_matrix" in result["baseline_limit_screen"]
    assert "test_escapes" in result and "overkill" in result
    assert "supervised_holdout" in result and result["supervised_holdout"] is not None
