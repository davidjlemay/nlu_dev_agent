#!/usr/bin/env bash
# Slurm job: download a Hugging Face model and serve it with vLLM.
#
# Usage:
#   sbatch cluster/vllm-serve.sh
#   MODEL=meta-llama/Llama-3.1-8B-Instruct sbatch cluster/vllm-serve.sh
#
# After the job starts, run cluster/use-vllm.sh on the machine running pi to
# point pi-mono at the live endpoint.
#
#SBATCH --job-name=vllm-serve
#SBATCH --ntasks=1
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=08:00:00
#SBATCH --output=/scratch/%u/nlu_dev_agent/cluster/logs/vllm-%j.log

set -euo pipefail

# ── Configuration ─────────────────────────────────────────────────────────────
MODEL="${MODEL:-Qwen/Qwen2.5-7B-Instruct}"
PORT="${PORT:-8000}"
MAX_MODEL_LEN="${MAX_MODEL_LEN:-8192}"
HF_CACHE="${HF_CACHE:-/scratch/$USER/hf-cache}"
PROJ="${PROJ:-/scratch/$USER/nlu_dev_agent}"
VLLM_VENV="${VLLM_VENV:-/scratch/$USER/vllm-venv}"
API_KEY="${API_KEY:-EMPTY}"

# ── Setup ──────────────────────────────────────────────────────────────────────
mkdir -p "$HF_CACHE" "$PROJ/cluster/logs"
export HF_HOME="$HF_CACHE"

# Activate venv (must have vllm + huggingface_hub installed)
# shellcheck disable=SC1091
source "$VLLM_VENV/bin/activate"

# ── Download model ─────────────────────────────────────────────────────────────
echo "==> Downloading $MODEL to $HF_CACHE"
huggingface-cli download "$MODEL"

# ── Write endpoint ─────────────────────────────────────────────────────────────
NODE="$(hostname -f)"
ENDPOINT="http://${NODE}:${PORT}/v1"
echo "$ENDPOINT" > "$PROJ/cluster/vllm.endpoint"
echo "==> Endpoint: $ENDPOINT  (written to $PROJ/cluster/vllm.endpoint)"
echo "==> Model:    $MODEL"

# ── Launch vLLM ───────────────────────────────────────────────────────────────
exec python -m vllm.entrypoints.openai.api_server \
    --model         "$MODEL" \
    --host          0.0.0.0 \
    --port          "$PORT" \
    --max-model-len "$MAX_MODEL_LEN" \
    --tensor-parallel-size 1 \
    --api-key       "$API_KEY" \
    --dtype         auto
