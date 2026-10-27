#!/usr/bin/env bash
# Levanta la API de inferencia localmente (sin Docker), fijada a 1 núcleo de CPU
# para medir la capacidad equivalente a una réplica de 1 vCPU en Azure Container Apps.
#   bash tools/run_api_local.sh            # puerto 8000, MAX_SESSIONS=180
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/services/inference_api"
export MODEL_PATH="${MODEL_PATH:-model/model.json}"
export STRICT_MODEL="${STRICT_MODEL:-true}"
export MAX_SESSIONS="${MAX_SESSIONS:-180}"
export OUTBOX_PATH="${OUTBOX_PATH:-$ROOT/var/outbox/events.jsonl}"
export PYTHONPATH="$ROOT/libs/voxfeatures:."
CPU_PIN=()
command -v taskset >/dev/null && CPU_PIN=(taskset -c "${API_CPU:-0}")
exec "${CPU_PIN[@]}" uvicorn app.main:app --host 127.0.0.1 --port "${PORT:-8000}" \
  --no-access-log --loop uvloop --http httptools
