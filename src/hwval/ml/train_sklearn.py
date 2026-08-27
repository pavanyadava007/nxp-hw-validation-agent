"""Two classical models trained on the same feature frame:

* an unsupervised ``IsolationForest`` -- useful in production where most
  runs never get a human FA disposition, so it has to work without labels;
* a supervised classifier -- RandomForest vs HistGradientBoosting are swept
  with a small GroupKFold cross-validation and the better one (by average
  precision) is kept, since which model wins is itself dataset-dependent
  and not worth hard-coding.

Both the primary train/test split and the CV folds inside it are grouped by
DUT serial: the same physical die appears in multiple corners/runs, and
letting one die's runs land in both train and test would let the model
memorise die-specific quirks instead of learning the general failure
signature -- an easy way this kind of project silently overstates itself.
"""
from __future__ import annotations

from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.ensemble import (
    HistGradientBoostingClassifier,
    IsolationForest,
    RandomForestClassifier,
)
from sklearn.inspection import permutation_importance
from sklearn.metrics import (
    average_precision_score,
    precision_recall_curve,
    roc_auc_score,
)
from sklearn.model_selection import GroupKFold, GroupShuffleSplit
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from hwval.config import get_settings
from hwval.ml.features import FEATURE_COLUMNS, build_feature_frame

_MIN_CLASS_SAMPLES = 3  # failure modes rarer than this get folded into "other"
_TOP_K_IMPORTANCE = 12


def _candidate_models(seed: int) -> dict[str, Any]:
    return {
        "random_forest": RandomForestClassifier(
            n_estimators=300, random_state=seed, n_jobs=-1, class_weight="balanced"
        ),
        "hist_gb": HistGradientBoostingClassifier(random_state=seed, max_iter=200),
    }


def _best_f1_threshold(y_true: np.ndarray, scores: np.ndarray) -> tuple[float, float, float, float]:
    """Return (threshold, precision, recall, f1) at the F1-maximising point
    of the precision-recall curve."""
    if len(np.unique(y_true)) < 2:
        return 0.5, 0.0, 0.0, 0.0
    precision, recall, thresholds = precision_recall_curve(y_true, scores)
    f1 = np.where((precision + recall) > 0, 2 * precision * recall / (precision + recall + 1e-12), 0.0)
    idx = int(np.argmax(f1[:-1])) if len(thresholds) else 0
    thr = float(thresholds[idx]) if len(thresholds) else 0.5
    return thr, float(precision[idx]), float(recall[idx]), float(f1[idx])


def _cv_average_precision(
    X: pd.DataFrame, y: np.ndarray, groups: np.ndarray, seed: int
) -> dict[str, float]:
    """Small GroupKFold sweep used only to pick between the two supervised
    candidates -- not the final reported metric (that comes from the held-out
    test split)."""
    candidates = _candidate_models(seed)
    n_groups = len(np.unique(groups))
    if n_groups < 2 or len(np.unique(y)) < 2:
        return {name: float("nan") for name in candidates}

    n_splits = max(2, min(4, n_groups))
    gkf = GroupKFold(n_splits=n_splits)
    scores: dict[str, list[float]] = {name: [] for name in candidates}
    for name, est in candidates.items():
        pipe = Pipeline([("scaler", StandardScaler()), ("clf", clone(est))])
        for tr, va in gkf.split(X, y, groups=groups):
            y_tr, y_va = y[tr], y[va]
            if len(np.unique(y_tr)) < 2 or len(np.unique(y_va)) < 2:
                continue
            pipe.fit(X.iloc[tr], y_tr)
            proba = pipe.predict_proba(X.iloc[va])[:, 1]
            scores[name].append(average_precision_score(y_va, proba))
    return {name: (float(np.mean(v)) if v else float("nan")) for name, v in scores.items()}


def _fit_failure_mode_classifier(
    X: pd.DataFrame, failure_mode: np.ndarray, seed: int
) -> tuple[Pipeline | None, list[str]]:
    """Multiclass classifier fitted only on anomalous runs. Failure modes with
    fewer than _MIN_CLASS_SAMPLES examples are merged into 'other' so a rare
    class doesn't blow up stratification/CV with a class of size 1."""
    if len(X) < 6:
        return None, []
    counts = pd.Series(failure_mode).value_counts()
    rare = set(counts[counts < _MIN_CLASS_SAMPLES].index)
    merged = np.array(["other" if m in rare else m for m in failure_mode])
    classes = sorted(set(merged))
    if len(classes) < 2:
        return None, []

    pipe = Pipeline([
        ("scaler", StandardScaler()),
        ("clf", RandomForestClassifier(n_estimators=200, random_state=seed, class_weight="balanced")),
    ])
    pipe.fit(X, merged)
    return pipe, classes


def train_sklearn(test_size: float = 0.25, save: bool = True) -> dict:
    """Train the IsolationForest + supervised classifier pair, persist a
    single joblib bundle, and return a metrics dict summarising both."""
    settings = get_settings()
    seed = settings.random_seed

    df = build_feature_frame()
    feats = FEATURE_COLUMNS(df)
    X = df[feats].replace([np.inf, -np.inf], np.nan).fillna(0.0)
    y = df["is_anomaly"].fillna(0).astype(int).to_numpy()
    groups = df["dut_serial"].to_numpy()

    n_groups = len(np.unique(groups))
    if n_groups >= 2:
        gss = GroupShuffleSplit(n_splits=1, test_size=test_size, random_state=seed)
        train_idx, test_idx = next(gss.split(X, y, groups=groups))
    else:  # degenerate (e.g. tiny test fixtures) -- fall back to using it all twice
        train_idx = test_idx = np.arange(len(X))

    X_train, X_test = X.iloc[train_idx], X.iloc[test_idx]
    y_train, y_test = y[train_idx], y[test_idx]

    # ---- unsupervised: IsolationForest -----------------------------------
    scaler = StandardScaler().fit(X_train)
    iforest = IsolationForest(
        n_estimators=200, contamination=settings.anomaly_contamination, random_state=seed
    )
    iforest.fit(scaler.transform(X_train))
    iforest_test_score = -iforest.decision_function(scaler.transform(X_test))  # higher = more anomalous
    if len(np.unique(y_test)) > 1:
        iforest_metrics = {
            "roc_auc": float(roc_auc_score(y_test, iforest_test_score)),
            "pr_auc": float(average_precision_score(y_test, iforest_test_score)),
        }
    else:
        iforest_metrics = {"roc_auc": float("nan"), "pr_auc": float("nan")}
    iforest_metrics["contamination"] = settings.anomaly_contamination

    # ---- supervised: RandomForest vs HistGradientBoosting -----------------
    cv_scores = _cv_average_precision(X_train, y_train, groups[train_idx], seed)
    valid = {k: v for k, v in cv_scores.items() if not np.isnan(v)}
    best_name = max(valid, key=valid.get) if valid else "random_forest"

    supervised_pipeline = Pipeline([
        ("scaler", StandardScaler()),
        ("clf", clone(_candidate_models(seed)[best_name])),
    ])
    supervised_pipeline.fit(X_train, y_train)
    proba_test = supervised_pipeline.predict_proba(X_test)[:, 1]

    threshold, precision, recall, f1 = _best_f1_threshold(y_test, proba_test)
    if len(np.unique(y_test)) > 1:
        roc_auc = float(roc_auc_score(y_test, proba_test))
        pr_auc = float(average_precision_score(y_test, proba_test))
    else:
        roc_auc, pr_auc = float("nan"), float("nan")

    try:
        perm = permutation_importance(
            supervised_pipeline, X_test, y_test,
            n_repeats=10, random_state=seed, scoring="average_precision", n_jobs=-1,
        )
        order = np.argsort(perm.importances_mean)[::-1][:_TOP_K_IMPORTANCE]
        top_importance = [
            {"feature": feats[i], "importance": float(perm.importances_mean[i])} for i in order
        ]
    except ValueError:
        top_importance = []

    supervised_metrics = {
        "model_selected": best_name,
        "cv_average_precision": cv_scores,
        "roc_auc": roc_auc,
        "pr_auc": pr_auc,
        "threshold": threshold,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "permutation_importance_top12": top_importance,
    }

    # ---- failure-mode multiclass classifier (anomalous rows only) --------
    # Restricted to the training split so its rows never overlap the runs
    # used to report the headline supervised/fused metrics above.
    train_anom_mask = y_train == 1
    fm_pipeline, fm_classes = _fit_failure_mode_classifier(
        X_train.loc[train_anom_mask],
        df["failure_mode"].to_numpy()[train_idx][train_anom_mask],
        seed,
    )

    # ---- nominal reference stats, used later by predict.top_features -----
    nominal_mask = y_train == 0
    nominal_mean = X_train.loc[nominal_mask].mean()
    nominal_std = X_train.loc[nominal_mask].std(ddof=0).replace(0.0, 1.0).fillna(1.0)

    metrics = {
        "n_samples": int(len(df)),
        "n_features": int(len(feats)),
        "n_anomalies": int(y.sum()),
        "n_train": int(len(train_idx)),
        "n_test": int(len(test_idx)),
        "test_size": test_size,
        "random_seed": seed,
        "iforest": iforest_metrics,
        "supervised": supervised_metrics,
        "failure_mode_classifier": {
            "trained": fm_pipeline is not None,
            "classes": fm_classes,
            "n_train": int(train_anom_mask.sum()),
        },
    }

    if save:
        bundle = {
            "scaler": scaler,
            "iforest": iforest,
            "supervised_pipeline": supervised_pipeline,
            "failure_mode_pipeline": fm_pipeline,
            "failure_mode_classes": fm_classes,
            "feature_columns": feats,
            "threshold": threshold,
            "metrics": metrics,
            "nominal_mean": nominal_mean,
            "nominal_std": nominal_std,
            "random_seed": seed,
        }
        settings.models_dir.mkdir(parents=True, exist_ok=True)
        joblib.dump(bundle, settings.models_dir / "sklearn_bundle.joblib")

    return metrics
