#!/usr/bin/env bash
# Configure pi-mono to use a running vLLM instance.
#
# Reads the endpoint written by vllm-serve.sh (cluster/vllm.endpoint) or
# accepts it as an argument, then:
#   1. Writes ~/.pi/agent/models.json  (registers "vllm" provider with the live URL)
#   2. Prints ready-to-use commands for the pi agent and Python skills
#
# settings.json is never modified — pass --provider / --model as CLI args instead.
#
# Usage:
#   bash cluster/use-vllm.sh                         # read endpoint from file
#   bash cluster/use-vllm.sh http://node:8000/v1     # pass endpoint directly
#   MODEL=my/model bash cluster/use-vllm.sh ...      # skip /v1/models query

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJ_ROOT="$(dirname "$SCRIPT_DIR")"
ENDPOINT_FILE="$PROJ_ROOT/cluster/vllm.endpoint"
MODELS_JSON="${HOME}/.pi/agent/models.json"
API_KEY="${API_KEY:-EMPTY}"

# ── Resolve endpoint ───────────────────────────────────────────────────────────
if [[ -n "${1:-}" ]]; then
    ENDPOINT="$1"
elif [[ -f "$ENDPOINT_FILE" ]]; then
    ENDPOINT="$(cat "$ENDPOINT_FILE")"
else
    echo "ERROR: no endpoint file at $ENDPOINT_FILE — copy it from the cluster or pass the URL as an argument" >&2
    exit 1
fi

echo "==> Endpoint: $ENDPOINT"

# ── Resolve model name ─────────────────────────────────────────────────────────
if [[ -z "${MODEL:-}" ]]; then
    if command -v curl &>/dev/null; then
        MODEL="$(curl -sf "${ENDPOINT}/models" -H "Authorization: Bearer ${API_KEY}" \
            | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['data'][0]['id'])" 2>/dev/null)" || true
    fi
fi
if [[ -z "${MODEL:-}" ]]; then
    echo "ERROR: could not detect model — set MODEL env var or ensure vLLM is reachable" >&2
    exit 1
fi
echo "==> Model:    $MODEL"

# ── Write ~/.pi/agent/models.json ──────────────────────────────────────────────
mkdir -p "$(dirname "$MODELS_JSON")"
python3 - "$MODELS_JSON" "$ENDPOINT" "$MODEL" "$API_KEY" <<'PYEOF'
import sys, json, os

models_path, endpoint, model_id, api_key = sys.argv[1:]

existing = {}
if os.path.exists(models_path):
    with open(models_path) as f:
        existing = json.load(f)

providers = existing.get("providers", {})
providers["vllm"] = {
    "baseUrl": endpoint,
    "apiKey":  api_key,
    "api":     "openai-completions",
    "compat": {
        "maxTokensField":         "max_tokens",
        "supportsStore":          False,
        "supportsDeveloperRole":  False,
        "requiresToolResultName": True,
    },
    "models": [
        {
            "id":            model_id,
            "name":          model_id.split("/")[-1],
            "contextWindow": 8192,
            "maxTokens":     4096,
        }
    ],
}

existing["providers"] = providers
with open(models_path, "w") as f:
    json.dump(existing, f, indent=2)
    f.write("\n")
PYEOF

echo "==> Registered 'vllm' provider in $MODELS_JSON"
echo ""
echo "── Pi agent ──────────────────────────────────────────────────────────────"
echo "  OPENAI_API_KEY=$API_KEY ./pi.sh --provider vllm --model '$MODEL'"
echo ""
echo "── Python skills (LLM_* vars override without any config change) ─────────"
echo "  LLM_BASE_URL=$ENDPOINT \\"
echo "  LLM_API_KEY=$API_KEY \\"
echo "  LLM_MODEL=$MODEL \\"
echo "  .venv/bin/python3 skills/jsgf-generate/generate.py grammars/transfer.jsgf \\"
echo "    --intent '...'"
echo ""
echo "  (LLM_* vars work for all four skills: validate, coverage, context, generate)"
