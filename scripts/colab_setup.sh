#!/usr/bin/env bash
# Build llama-server and fetch the MVP model. Idempotent; safe to re-run.
#
# CPU-only on purpose. A CUDA build would make Colab behave nothing like a
# Pi 5, and the point of this rig is Phase 1 and 2 behaviour, not speed.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LLAMA_DIR="${LLAMA_DIR:-${REPO_ROOT}/.llama.cpp}"
MODEL_DIR="${MODEL_DIR:-${REPO_ROOT}/pi/models}"
MODEL_REPO="${MODEL_REPO:-Qwen/Qwen2.5-1.5B-Instruct-GGUF}"
MODEL_FILE="${MODEL_FILE:-qwen2.5-1.5b-instruct-q4_k_m.gguf}"

echo "==> python dependencies"
pip install --quiet --upgrade huggingface_hub pytest pytest-cov

if [ ! -x "${LLAMA_DIR}/build/bin/llama-server" ]; then
  echo "==> build tools"
  if command -v apt-get >/dev/null 2>&1; then
    sudo apt-get -qq update
    sudo apt-get -qq install -y build-essential cmake git libcurl4-openssl-dev
  fi

  echo "==> llama.cpp"
  [ -d "${LLAMA_DIR}" ] || git clone --depth 1 https://github.com/ggml-org/llama.cpp "${LLAMA_DIR}"
  cmake -S "${LLAMA_DIR}" -B "${LLAMA_DIR}/build" -DGGML_NATIVE=ON -DLLAMA_CURL=OFF >/dev/null
  cmake --build "${LLAMA_DIR}/build" --target llama-server -j "$(nproc)"
else
  echo "==> llama-server already built, skipping"
fi

echo "==> model: ${MODEL_REPO}/${MODEL_FILE}"
mkdir -p "${MODEL_DIR}"
python3 - "$MODEL_REPO" "$MODEL_FILE" "$MODEL_DIR" <<'PY'
import sys
from huggingface_hub import hf_hub_download

repo_id, filename, local_dir = sys.argv[1:4]
path = hf_hub_download(repo_id=repo_id, filename=filename, local_dir=local_dir)
print(f"    {path}")
PY

echo
echo "ready."
echo "  server : ${LLAMA_DIR}/build/bin/llama-server"
echo "  model  : ${MODEL_DIR}/${MODEL_FILE}"
