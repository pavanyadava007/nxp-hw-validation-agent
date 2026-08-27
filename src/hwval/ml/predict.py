"""Load whatever models exist on disk, score runs, and fuse the results into
one severity call per run.

Fusion method -- rank-average of min-max-normalised scores: each raw score
(IsolationForest, supervised probability, autoencoder reconstruction error)
is first min-max scaled to [0, 1] within the current batch so no model
dominates purely because of its native numeric range, then every run's
*rank* within each normalised score is taken and the three ranks are
averaged (a "Borda count"). The averaged rank is itself min-max scaled back
to [0, 1] to produce ``fused_score``. Averaging ranks rather than the
normalised values directly makes the fusion robust to any one model having a
skewed/long-tailed score distribution -- IsolationForest's decision_function
in particular is not remotely uniform.

``top_features`` uses a z-score-vs-nominal-mean ranking rather than the
supervised model's SHAP/feature-contribution values: it is a few lines of
arithmetic against statistics already computed at train time, versus a
second, per-row model explainer call. For a bundle this size the ranking is
visibly consistent with what actually moves the supervised model's
prediction (both are ultimately reading the same engineered features), so
the much cheaper method is the one used here; this is a deliberate
cost/fidelity trade-off, not an oversight.
"""
from __future__ import annotations

import json

import joblib
import numpy as np
import pandas as pd

from hwval.config import get_settings
from hwval.db.engine import session_scope
from hwval.db.models import AnomalyEvent
from hwval.ml.features import build_feature_frame, build_sequence_tensor
from hwval.ml.train_tf import META_FILENAME, model_paths

# Fixed severity bands on fused_score in [0, 1]. Checked top-down.
_SEVERITY_BANDS: list[tuple[str, float]] = [
    ("CRITICAL", 0.90),
    ("HIGH", 0.70),
    ("MEDIUM", 0.40),
]
# fused_score at/above this is "flagged" -- only flagged runs get a
# predicted_failure_mode, since the multiclass model was only ever trained
# on anomalous runs and has nothing meaningful to say about nominal ones.
_ANOMALY_FLAG_THRESHOLD = 0.40

_OUTPUT_COLUMNS = [
    "run_id", "iforest_score", "supervised_proba", "ae_recon_error",
    "fused_score", "severity", "predicted_failure_mode", "top_features",
]


def _severity(score: float) -> str:
    for label, cutoff in _SEVERITY_BANDS:
        if score >= cutoff:
            return label
    return "LOW"


def load_models() -> dict:
    """Load whatever trained artefacts exist; missing ones are None so
    score_runs degrades gracefully (e.g. before train_tf has ever run)."""
    settings = get_settings()
    out: dict = {"sklearn": None, "autoencoder": None}

    sk_path = settings.models_dir / "sklearn_bundle.joblib"
    if sk_path.exists():
        out["sklearn"] = joblib.load(sk_path)

    model_path, meta_path, pca_path = model_paths(settings.models_dir)
    if meta_path.exists():
        meta = json.loads(meta_path.read_text())
        backend = meta.get("backend")
        if backend == "tensorflow" and model_path.exists():
            try:
                import tensorflow as tf

                out["autoencoder"] = {
                    "backend": "tensorflow",
                    "model": tf.keras.models.load_model(model_path),
                    "meta": meta,
                }
            except Exception:
                out["autoencoder"] = None
        elif backend == "pca_fallback" and pca_path.exists():
            bundle = joblib.load(pca_path)
            out["autoencoder"] = {"backend": "pca_fallback", "pca": bundle["pca"], "meta": meta}

    return out


def _ae_recon_error(ae: dict, run_ids: list[int]) -> pd.Series:
    X, ids = build_sequence_tensor(run_ids)
    if len(ids) == 0:
        return pd.Series(dtype=float)
    if ae["backend"] == "tensorflow":
        recon = ae["model"].predict(X, verbose=0)
        err = np.mean((recon - X) ** 2, axis=(1, 2))
    else:
        flat = X.reshape(len(X), -1)
        recon = ae["pca"].inverse_transform(ae["pca"].transform(flat))
        err = np.mean((recon - flat) ** 2, axis=1)
    return pd.Series(err, index=ids)


def _minmax(s: pd.Series) -> pd.Series:
    lo, hi = float(s.min()), float(s.max())
    if not np.isfinite(hi - lo) or (hi - lo) < 1e-12:
        return pd.Series(0.0, index=s.index)
    return (s - lo) / (hi - lo)


def _top_features(row: pd.Series, mean: pd.Series, std: pd.Series, k: int = 3) -> str:
    z = (row - mean) / std
    z = z.replace([np.inf, -np.inf], 0.0).fillna(0.0)
    top = z.abs().sort_values(ascending=False).head(k)
    parts = []
    for feat in top.index:
        direction = "high" if z[feat] > 0 else "low"
        parts.append(f"{feat} {direction} (z={z[feat]:+.1f})")
    return "; ".join(parts)


def score_runs(run_ids: list[int] | None = None) -> pd.DataFrame:
    """Score `run_ids` (or every run in the DB) with every trained model and
    fuse them into one severity call. Columns: run_id, iforest_score,
    supervised_proba, ae_recon_error, fused_score, severity,
    predicted_failure_mode, top_features. A model that has not been trained
    yet simply contributes NaN and is left out of the fusion.
    """
    models = load_models()
    df = build_feature_frame(run_ids)
    if df.empty:
        return pd.DataFrame(columns=_OUTPUT_COLUMNS)

    out = df[["run_id"]].copy()
    out["iforest_score"] = np.nan
    out["supervised_proba"] = np.nan
    out["ae_recon_error"] = np.nan
    out["predicted_failure_mode"] = "nominal"
    out["top_features"] = ""

    bundle = models["sklearn"]
    if bundle is not None:
        feats = bundle["feature_columns"]
        X = df.reindex(columns=feats, fill_value=0.0).fillna(0.0)

        Xs = bundle["scaler"].transform(X)
        out["iforest_score"] = -bundle["iforest"].decision_function(Xs)  # higher = more anomalous
        out["supervised_proba"] = bundle["supervised_pipeline"].predict_proba(X)[:, 1]

        nominal_mean, nominal_std = bundle["nominal_mean"], bundle["nominal_std"]
        out["top_features"] = [_top_features(X.iloc[i], nominal_mean, nominal_std) for i in range(len(X))]

    ae = models["autoencoder"]
    if ae is not None:
        err = _ae_recon_error(ae, df["run_id"].tolist())
        out["ae_recon_error"] = out["run_id"].map(err)

    score_cols = [c for c in ("iforest_score", "supervised_proba", "ae_recon_error") if out[c].notna().any()]
    if score_cols:
        ranks = pd.DataFrame({
            c: _minmax(out[c].fillna(out[c].median())).rank(method="average") for c in score_cols
        })
        out["fused_score"] = _minmax(ranks.mean(axis=1))
    else:
        out["fused_score"] = 0.0

    out["severity"] = out["fused_score"].apply(_severity)

    if bundle is not None and bundle.get("failure_mode_pipeline") is not None:
        flagged = (out["fused_score"] >= _ANOMALY_FLAG_THRESHOLD).to_numpy()
        if flagged.any():
            feats = bundle["feature_columns"]
            X_flagged = df.loc[flagged, :].reindex(columns=feats, fill_value=0.0).fillna(0.0)
            out.loc[flagged, "predicted_failure_mode"] = bundle["failure_mode_pipeline"].predict(X_flagged)

    return out[_OUTPUT_COLUMNS]


def persist_anomaly_events(df: pd.DataFrame) -> int:
    """Write one AnomalyEvent row per record in `df` (typically the flagged
    subset of score_runs' output -- callers decide what counts as worth
    recording). Idempotent: existing events for the run_ids in `df` are
    deleted first, so re-scoring a run never accumulates duplicate events.
    """
    if df.empty:
        return 0
    run_ids = [int(r) for r in df["run_id"].tolist()]
    with session_scope() as sess:
        sess.query(AnomalyEvent).filter(AnomalyEvent.run_id.in_(run_ids)).delete(synchronize_session=False)
        events = [
            AnomalyEvent(
                run_id=int(row.run_id),
                model_name="fused",
                score=float(row.fused_score),
                severity=str(row.severity),
                param_name="",
                failure_mode=str(row.predicted_failure_mode or "unknown"),
                explanation=str(row.top_features or ""),
            )
            for row in df.itertuples(index=False)
        ]
        sess.add_all(events)
    return len(events)
