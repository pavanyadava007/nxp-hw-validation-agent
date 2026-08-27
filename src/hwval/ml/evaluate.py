"""Headline comparison: the naive spec-limit screen vs the trained anomaly
models. This is the project's central deliverable -- it answers the
question a test engineer actually cares about: does the ML pipeline catch
failures the existing pass/fail screen misses ("test escapes"), and does it
avoid flagging devices the screen wrongly failed on ATE noise it wasn't
actually a defect ("overkill")? The latter is exactly the ATE-glitch
scenario seed.py injects: a single-sample spike trips a hard limit even
though the device is healthy, and a good model should be robust to it.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.metrics import (
    average_precision_score,
    confusion_matrix,
    f1_score,
    precision_recall_curve,
    precision_score,
    recall_score,
    roc_auc_score,
)

from hwval.db.engine import read_sql
from hwval.ml.predict import load_models, score_runs

_SCORE_COLUMNS = [
    ("iforest_score", "iforest"),
    ("supervised_proba", "supervised"),
    ("ae_recon_error", "autoencoder"),
    ("fused_score", "fused"),
]


def _binary_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict:
    cm = confusion_matrix(y_true, y_pred, labels=[0, 1])
    return {
        "precision": float(precision_score(y_true, y_pred, zero_division=0)),
        "recall": float(recall_score(y_true, y_pred, zero_division=0)),
        "f1": float(f1_score(y_true, y_pred, zero_division=0)),
        "confusion_matrix": cm.tolist(),  # [[tn, fp], [fn, tp]]
    }


def _best_f1_threshold(y_true: np.ndarray, scores: np.ndarray) -> tuple[float, np.ndarray]:
    if len(np.unique(y_true)) < 2 or np.nanstd(scores) < 1e-12:
        thr = float(np.nanmedian(scores)) if len(scores) else 0.5
        return thr, (scores >= thr).astype(int)
    precision, recall, thresholds = precision_recall_curve(y_true, scores)
    f1 = np.where((precision + recall) > 0, 2 * precision * recall / (precision + recall + 1e-12), 0.0)
    idx = int(np.argmax(f1[:-1])) if len(thresholds) else 0
    thr = float(thresholds[idx]) if len(thresholds) else 0.5
    return thr, (scores >= thr).astype(int)


def _score_metrics(y_true: np.ndarray, scores: pd.Series) -> tuple[dict, np.ndarray]:
    filled = scores.fillna(scores.median() if scores.notna().any() else 0.0).to_numpy()
    thr, y_pred = _best_f1_threshold(y_true, filled)
    metrics = _binary_metrics(y_true, y_pred)
    metrics["threshold"] = thr
    if len(np.unique(y_true)) > 1:
        metrics["roc_auc"] = float(roc_auc_score(y_true, filled))
        metrics["pr_auc"] = float(average_precision_score(y_true, filled))
    else:
        metrics["roc_auc"] = metrics["pr_auc"] = float("nan")
    return metrics, y_pred


def evaluate_all() -> dict:
    """Score every run, compare each model (and the fused score) against the
    naive limit-screen baseline, and report the confusion matrix plus the
    test-escape / overkill counts that make the comparison concrete.

    Note on methodology: the per-model metrics below (other than
    ``supervised_holdout``) are computed over the *entire* scored
    population, each at its own best-F1 threshold. For the unsupervised
    IsolationForest and autoencoder that is a fair like-for-like comparison
    against the baseline (neither ever "trained on" the label). For the
    supervised classifier it is optimistic, because some of these runs were
    in its training set -- ``supervised_holdout`` carries the true
    out-of-sample precision/recall/F1/ROC-AUC/PR-AUC from the grouped
    train/test split done in ``train_sklearn()`` and should be preferred
    when citing the supervised model's real-world performance.
    """
    scored = score_runs(None)
    labels = read_sql("SELECT run_id, is_anomaly FROM run_label")
    status = read_sql("SELECT id AS run_id, status FROM test_run")

    merged = scored.merge(labels, on="run_id", how="inner").merge(status, on="run_id", how="left")
    y_true = merged["is_anomaly"].astype(int).to_numpy()
    baseline_pred = (merged["status"] == "FAIL").astype(int).to_numpy()

    result: dict = {
        "n_runs": int(len(merged)),
        "n_anomalies": int(y_true.sum()),
        "note": (
            "iforest/autoencoder/supervised/fused metrics are computed over the full "
            "scored population at each score's own best-F1 threshold -- a whole-"
            "population comparison against the naive limit screen, not a held-out "
            "generalisation estimate. See 'supervised_holdout' for the true "
            "out-of-sample metrics from train_sklearn()'s grouped train/test split."
        ),
        "baseline_limit_screen": _binary_metrics(y_true, baseline_pred),
    }

    model_preds: dict[str, np.ndarray] = {}
    for col, key in _SCORE_COLUMNS:
        if col in merged and merged[col].notna().any():
            metrics, y_pred = _score_metrics(y_true, merged[col])
            result[key] = metrics
            model_preds[key] = y_pred
        else:
            result[key] = None

    bundle = load_models()["sklearn"]
    result["supervised_holdout"] = bundle["metrics"]["supervised"] if bundle else None

    fused_pred = model_preds.get("fused")
    if fused_pred is not None:
        escapes = (y_true == 1) & (baseline_pred == 0) & (fused_pred == 1)
        overkill = (y_true == 0) & (baseline_pred == 1) & (fused_pred == 0)
        result["test_escapes"] = {
            "count": int(escapes.sum()),
            "run_ids": merged.loc[escapes, "run_id"].astype(int).tolist(),
        }
        result["overkill"] = {
            "count": int(overkill.sum()),
            "run_ids": merged.loc[overkill, "run_id"].astype(int).tolist(),
        }
    else:
        result["test_escapes"] = {"count": 0, "run_ids": []}
        result["overkill"] = {"count": 0, "run_ids": []}

    return result
