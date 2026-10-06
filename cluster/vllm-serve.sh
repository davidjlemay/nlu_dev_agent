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
DTYPE="${DTYPE:-float16}"          # V100 doesn't support bfloat16; use float16; use bfloat16 on A100/H100
QUANTIZATION="${QUANTIZATION:-}"     # quantization method: awq | gptq | fp8 | bitsandbytes | ... (omit to auto-detect)
HF_TOKEN="${HF_TOKEN:-}"           # required for gated models (e.g. Gemma); set via: HF_TOKEN=hf_... sbatch ...
TOOL_CALL_PARSER="${TOOL_CALL_PARSER:-}"  # enable function calling: gemma3 | llama3_json | mistral | hermes | ...

# ── Setup ──────────────────────────────────────────────────────────────────────
mkdir -p "$HF_CACHE" "$PROJ/cluster/logs"
export HF_HOME="$HF_CACHE"
[[ -n "$HF_TOKEN" ]] && export HUGGING_FACE_HUB_TOKEN="$HF_TOKEN"

# Activate conda env (source init script so `conda activate` works in batch jobs)
# shellcheck disable=SC1091
source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate venv

# Sanity-check CUDA visibility before spending time on the model download
python - <<'EOF'
import torch, sys
if not torch.cuda.is_available():
    print("ERROR: torch.cuda.is_available() is False — check conda env or CUDA_VISIBLE_DEVICES", file=sys.stderr)
    sys.exit(1)
print(f"==> CUDA OK: {torch.cuda.device_count()} device(s), {torch.version.cuda}")
EOF

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
TOOL_ARGS=()
[[ -n "$TOOL_CALL_PARSER" ]] && TOOL_ARGS=(--enable-auto-tool-choice --tool-call-parser "$TOOL_CALL_PARSER")
QUANT_ARGS=()
[[ -n "$QUANTIZATION" ]] && QUANT_ARGS=(--quantization "$QUANTIZATION")

vllm serve "$MODEL" \
    --host          0.0.0.0 \
    --port          "$PORT" \
    --max-model-len "$MAX_MODEL_LEN" \
    --tensor-parallel-size 1 \
    --api-key       "$API_KEY" \
    --dtype         "$DTYPE" \
    "${QUANT_ARGS[@]}" \
    "${TOOL_ARGS[@]}" &

VLLM_PID=$!

echo "==> Waiting for server to become ready..."
until curl -sf "http://localhost:${PORT}/health" > /dev/null 2>&1; do
    kill -0 "$VLLM_PID" 2>/dev/null || { echo "ERROR: vLLM process exited unexpectedly"; exit 1; }
    sleep 5
done
echo "==> Server is ready at $ENDPOINT"

wait "$VLLM_PID"
