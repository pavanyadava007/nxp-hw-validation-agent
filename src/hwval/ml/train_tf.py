"""LSTM-autoencoder anomaly detector over the raw sample sequences.

Trained ONLY on runs labelled nominal -- this is the correct semi-supervised
setup for reconstruction-based anomaly detection: the network only ever
learns to reconstruct "healthy" device behaviour, so at scoring time a run
it reconstructs poorly is, by construction, something it has not seen
before. Training on a mix of nominal and anomalous runs would let the model
learn to reconstruct the anomalies too, which defeats the point of using
reconstruction error as an anomaly score.

TensorFlow is optional: the whole repo must install and run without it, so
the import is guarded and a numpy/PCA reconstruction autoencoder with the
same downstream interface (a saved artefact + a JSON of {threshold, backend,
normalisation stats}) is used as a fallback. ``predict.py`` never needs to
know which backend produced the artefacts it loads.
"""
from __future__ import annotations

import json
from pathlib import Path

import joblib
import numpy as np

from hwval.config import get_settings
from hwval.db.engine import read_sql
from hwval.ml.features import PARAMS, build_sequence_tensor, param_normalisation_stats

MODEL_FILENAME = "lstm_autoencoder.keras"
META_FILENAME = "lstm_autoencoder_meta.json"
PCA_FILENAME = "pca_autoencoder.joblib"

_MIN_NOMINAL_RUNS = 8


def model_paths(models_dir: Path) -> tuple[Path, Path, Path]:
    return models_dir / MODEL_FILENAME, models_dir / META_FILENAME, models_dir / PCA_FILENAME


def _nominal_and_anomalous_ids() -> tuple[list[int], list[int]]:
    labels = read_sql("SELECT run_id, is_anomaly FROM run_label")
    nominal = labels.loc[labels["is_anomaly"] == False, "run_id"].astype(int).tolist()  # noqa: E712
    anomalous = labels.loc[labels["is_anomaly"] == True, "run_id"].astype(int).tolist()  # noqa: E712
    return nominal, anomalous


def train_autoencoder(epochs: int = 30, save: bool = True) -> dict:
    settings = get_settings()
    seq_len = settings.sequence_length
    n_params = len(PARAMS)
    seed = settings.random_seed

    nominal_ids, _anomalous_ids = _nominal_and_anomalous_ids()
    X_all, all_ids = build_sequence_tensor(None)
    pos = {rid: i for i, rid in enumerate(all_ids)}
    train_pos = [pos[r] for r in nominal_ids if r in pos]
    if len(train_pos) < _MIN_NOMINAL_RUNS:
        raise ValueError(
            f"Only {len(train_pos)} nominal runs available; need at least "
            f"{_MIN_NOMINAL_RUNS} to train an autoencoder."
        )
    X_train_full = X_all[train_pos]

    rng = np.random.default_rng(seed)
    perm = rng.permutation(len(X_train_full))
    n_val = max(1, int(0.15 * len(perm)))
    val_idx, tr_idx = perm[:n_val], perm[n_val:]
    X_tr, X_val = X_train_full[tr_idx], X_train_full[val_idx]

    model_path, meta_path, pca_path = model_paths(settings.models_dir)

    try:
        import tensorflow as tf  # noqa: F401 -- import guard, see module docstring
        backend = "tensorflow"
    except ImportError:
        backend = "pca_fallback"

    if backend == "tensorflow":
        epochs_run, train_errors = _train_tf_autoencoder(
            X_tr, X_val, X_train_full, seq_len, n_params, seed, epochs,
            model_path if save else None,
        )
    else:
        epochs_run, train_errors = _train_pca_autoencoder(
            X_tr, X_train_full, pca_path if save else None, seed,
        )

    threshold = float(np.percentile(train_errors, 95))
    means, stds = param_normalisation_stats()

    meta = {
        "backend": backend,
        "threshold": threshold,
        "seq_len": seq_len,
        "n_params": n_params,
        "params": PARAMS,
        "param_means": means.tolist(),
        "param_stds": stds.tolist(),
        "n_train_nominal": int(len(X_train_full)),
        "random_seed": seed,
    }
    if save:
        settings.models_dir.mkdir(parents=True, exist_ok=True)
        meta_path.write_text(json.dumps(meta, indent=2))

    metrics = dict(meta)
    metrics["epochs_run"] = epochs_run
    metrics["train_recon_error_mean"] = float(np.mean(train_errors))
    metrics["train_recon_error_p95"] = threshold
    return metrics


def _train_tf_autoencoder(
    X_tr: np.ndarray,
    X_val: np.ndarray,
    X_train_full: np.ndarray,
    seq_len: int,
    n_params: int,
    seed: int,
    epochs: int,
    save_path: Path | None,
) -> tuple[int, np.ndarray]:
    import tensorflow as tf

    tf.keras.utils.set_random_seed(seed)

    inputs = tf.keras.Input(shape=(seq_len, n_params))
    encoded = tf.keras.layers.LSTM(64, activation="tanh")(inputs)
    encoded = tf.keras.layers.Dense(16, activation="tanh")(encoded)
    repeated = tf.keras.layers.RepeatVector(seq_len)(encoded)
    decoded = tf.keras.layers.LSTM(64, activation="tanh", return_sequences=True)(repeated)
    outputs = tf.keras.layers.TimeDistributed(tf.keras.layers.Dense(n_params))(decoded)
    model = tf.keras.Model(inputs, outputs)
    model.compile(optimizer=tf.keras.optimizers.Adam(1e-3), loss="mse")

    early_stop = tf.keras.callbacks.EarlyStopping(
        monitor="val_loss", patience=5, restore_best_weights=True
    )
    history = model.fit(
        X_tr, X_tr,
        validation_data=(X_val, X_val),
        epochs=epochs,
        batch_size=16,
        shuffle=True,
        verbose=0,
        callbacks=[early_stop],
    )

    recon = model.predict(X_train_full, verbose=0)
    train_errors = np.mean((recon - X_train_full) ** 2, axis=(1, 2))

    if save_path is not None:
        save_path.parent.mkdir(parents=True, exist_ok=True)
        model.save(save_path)

    return len(history.history["loss"]), train_errors


def _train_pca_autoencoder(
    X_tr: np.ndarray, X_train_full: np.ndarray, save_path: Path | None, seed: int
) -> tuple[int, np.ndarray]:
    from sklearn.decomposition import PCA

    flat_tr = X_tr.reshape(len(X_tr), -1)
    flat_full = X_train_full.reshape(len(X_train_full), -1)
    n_components = max(1, min(8, flat_tr.shape[0] - 1, flat_tr.shape[1]))
    pca = PCA(n_components=n_components, random_state=seed)
    pca.fit(flat_tr)

    recon = pca.inverse_transform(pca.transform(flat_full))
    train_errors = np.mean((recon - flat_full) ** 2, axis=1)

    if save_path is not None:
        save_path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump({"pca": pca}, save_path)

    return 0, train_errors
