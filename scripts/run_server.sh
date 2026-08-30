#!/usr/bin/env bash
# Start llama-server for the Marvin brain. Backgrounds it and waits for /health.
#
# --mlock is deliberately absent here. On the Pi it is required (MVP.md 3.2:
# no model may page in from disk on the critical path); on a Colab VM it either
# fails or pins memory you do not have.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LLAMA_DIR="${LLAMA_DIR:-${REPO_ROOT}/.llama.cpp}"
MODEL_DIR="${MODEL_DIR:-${REPO_ROOT}/pi/models}"
MODEL_FILE="${MODEL_FILE:-qwen2.5-1.5b-instruct-q4_k_m.gguf}"
PORT="${PORT:-8080}"
CONTEXT="${CONTEXT:-4096}"
LOG="${LOG:-${REPO_ROOT}/.llama-server.log}"

MODEL_PATH="${MODEL_DIR}/${MODEL_FILE}"
SERVER="${LLAMA_DIR}/build/bin/llama-server"

[ -x "${SERVER}" ] || { echo "no llama-server at ${SERVER}; run scripts/colab_setup.sh" >&2; exit 1; }
[ -f "${MODEL_PATH}" ] || { echo "no model at ${MODEL_PATH}; run scripts/colab_setup.sh" >&2; exit 1; }

pkill -f "llama-server.*--port ${PORT}" 2>/dev/null || true

nohup "${SERVER}" \
  --model "${MODEL_PATH}" \
  --host 127.0.0.1 --port "${PORT}" \
  --ctx-size "${CONTEXT}" \
  --threads "$(nproc)" \
  --parallel 1 \
  >"${LOG}" 2>&1 &

echo "llama-server starting on port ${PORT}, log at ${LOG}"
for _ in $(seq 1 120); do
  if curl -sf "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1; then
    echo "ready."
    exit 0
  fi
  sleep 1
done

echo "server did not become healthy in 120s; last log lines:" >&2
tail -20 "${LOG}" >&2
exit 1
