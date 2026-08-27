#!/usr/bin/env bash
# End-to-end pipeline: init -> seed -> train -> score -> evaluate -> report.
#
# Usage:
#   ./scripts/run_pipeline.sh                     # SQLite demo DB, 60 DUTs
#   DUTS=120 ./scripts/run_pipeline.sh             # more synthetic data
#   DATABASE_URL=postgresql+psycopg2://... ./scripts/run_pipeline.sh
#
# Run from anywhere -- paths below are resolved relative to the repo root.
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." &>/dev/null && pwd)"
cd "${REPO_ROOT}"

export PYTHONPATH="${REPO_ROOT}/src"
export TF_CPP_MIN_LOG_LEVEL="${TF_CPP_MIN_LOG_LEVEL:-3}"
export DATABASE_URL="${DATABASE_URL:-sqlite:///${REPO_ROOT}/artifacts/hwval.db}"

DUTS="${DUTS:-60}"
REPORT_FMT="${REPORT_FMT:-html}"
HWVAL=(python3 -m hwval.cli)

_step() { printf '\n\033[1;36m==> %s\033[0m\n' "$1"; }
t0=$(date +%s)

_step "1/6  init        (database: ${DATABASE_URL%%://*})"
"${HWVAL[@]}" init --drop

_step "2/6  seed        (${DUTS} DUTs)"
"${HWVAL[@]}" seed --duts "${DUTS}"

_step "3/6  train       (sklearn + autoencoder, falls back to PCA without TensorFlow)"
"${HWVAL[@]}" train

_step "4/6  score       (fused anomaly scoring, persists anomaly_event rows)"
"${HWVAL[@]}" score

_step "5/6  evaluate    (models vs. naive spec-limit screen)"
"${HWVAL[@]}" evaluate

_step "6/6  report      (fmt=${REPORT_FMT})"
REPORT_PATH="$("${HWVAL[@]}" report --fmt "${REPORT_FMT}" | python3 -c 'import json,sys; print(json.load(sys.stdin)["path"])')"

t1=$(date +%s)
printf '\n\033[1;32mPipeline complete in %ss.\033[0m\n' "$((t1 - t0))"
printf 'Report: %s\n' "${REPORT_PATH}"
printf 'Figures: %s\n' "${REPO_ROOT}/artifacts/figures"
printf 'Models:  %s\n' "${REPO_ROOT}/artifacts/models"
printf '\nTry the agent:  make ask Q="What is the yield by PVT corner?"\n'
printf 'Or the UI:      make ui\n'
