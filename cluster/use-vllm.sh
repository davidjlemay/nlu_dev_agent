#!/usr/bin/env bash
# Point pi-mono at a running vLLM instance.
#
# Reads the endpoint from cluster/vllm.endpoint (written by vllm-serve.sh) or
# accepts it as an argument, then:
#   1. Writes ~/.pi/agent/models.json  (registers "vllm" custom provider)
#   2. Updates .pi/settings.json       (switches defaultProvider + defaultModel)
#
# Usage:
#   # After scp-ing/reading cluster/vllm.endpoint:
#   bash cluster/use-vllm.sh
#
#   # Or pass the endpoint directly:
#   bash cluster/use-vllm.sh http://node123.cluster:8000/v1
#
#   # Restore original settings:
#   bash cluster/use-vllm.sh --restore

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJ_ROOT="$(dirname "$SCRIPT_DIR")"
ENDPOINT_FILE="$PROJ_ROOT/cluster/vllm.endpoint"
PROJECT_SETTINGS="$PROJ_ROOT/.pi/settings.json"
MODELS_JSON="${HOME}/.pi/agent/models.json"
BACKUP_SETTINGS="$PROJ_ROOT/.pi/settings.json.bak"
BACKUP_MODELS="${MODELS_JSON}.bak"
API_KEY="${API_KEY:-EMPTY}"
MODEL="${MODEL:-}"  # if empty, read from vllm.endpoint.model or infer from server

# ── Restore ────────────────────────────────────────────────────────────────────
if [[ "${1:-}" == "--restore" ]]; then
    if [[ -f "$BACKUP_SETTINGS" ]]; then
        cp "$BACKUP_SETTINGS" "$PROJECT_SETTINGS"
        echo "==> Restored $PROJECT_SETTINGS"
    fi
    if [[ -f "$BACKUP_MODELS" ]]; then
        cp "$BACKUP_MODELS" "$MODELS_JSON"
        echo "==> Restored $MODELS_JSON"
    fi
    exit 0
fi

# ── Resolve endpoint ───────────────────────────────────────────────────────────
if [[ -n "${1:-}" ]]; then
    ENDPOINT="$1"
elif [[ -f "$ENDPOINT_FILE" ]]; then
    ENDPOINT="$(cat "$ENDPOINT_FILE")"
else
    echo "ERROR: no endpoint file at $ENDPOINT_FILE — pass the endpoint as argument or copy the file from the cluster" >&2
    exit 1
fi

echo "==> Endpoint: $ENDPOINT"

# ── Resolve model name (query /v1/models if not set) ──────────────────────────
if [[ -z "$MODEL" ]]; then
    if command -v curl &>/dev/null; then
        MODEL="$(curl -sf "${ENDPOINT}/models" -H "Authorization: Bearer ${API_KEY}" \
            | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['data'][0]['id'])" 2>/dev/null)" || true
    fi
fi
if [[ -z "$MODEL" ]]; then
    echo "ERROR: could not detect model — set MODEL env var or ensure the vLLM server is reachable" >&2
    exit 1
fi
echo "==> Model:    $MODEL"

# ── Backup existing files ──────────────────────────────────────────────────────
[[ -f "$PROJECT_SETTINGS" ]] && cp "$PROJECT_SETTINGS" "$BACKUP_SETTINGS"
[[ -f "$MODELS_JSON"      ]] && cp "$MODELS_JSON"      "$BACKUP_MODELS"
mkdir -p "$(dirname "$MODELS_JSON")"

# ── Write ~/.pi/agent/models.json ──────────────────────────────────────────────
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

print(f"  wrote {models_path}")
PYEOF

# ── Update .pi/settings.json ───────────────────────────────────────────────────
python3 - "$PROJECT_SETTINGS" "$MODEL" <<'PYEOF'
import sys, json, os

settings_path, model_id = sys.argv[1:]

settings = {}
if os.path.exists(settings_path):
    with open(settings_path) as f:
        settings = json.load(f)

settings["defaultProvider"] = "vllm"
settings["defaultModel"]    = model_id

with open(settings_path, "w") as f:
    json.dump(settings, f, indent=2)
    f.write("\n")

print(f"  wrote {settings_path}")
PYEOF

echo "==> Done. Run ./pi.sh to use $MODEL via vLLM."
echo "    To revert: bash cluster/use-vllm.sh --restore"
