#!/usr/bin/env bash
# One-time venv setup for nlu-agent on the cluster.
# Usage: bash cluster/setup-venv.sh
set -euo pipefail

PROJ="${PROJ:-/scratch/$USER/nlu_dev_agent}"
SIF="${SIF:-/scratch/$USER/nlu-agent.sif}"

echo "==> Setting up venv: PROJ=$PROJ  SIF=$SIF"
[ -f "$SIF" ] || { echo "ERROR: SIF not found at $SIF" >&2; exit 1; }

singularity exec \
    --bind "$PROJ:/app" \
    "$SIF" \
    bash -c '
        set -e
        echo "--- Creating venv"
        python3 -m venv /app/.venv
        echo "--- Installing requirements.txt"
        /app/.venv/bin/pip install --no-cache-dir -r /app/requirements.txt
        echo "--- Installing optional deps"
        /app/.venv/bin/pip install --no-cache-dir anthropic openai
        echo "--- Verifying"
        /app/.venv/bin/python3 -c "import pyjsgf; import pygls; print(\"venv OK\")"
    '

echo "==> Done. Venv is at $PROJ/.venv"
