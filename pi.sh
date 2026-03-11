#!/usr/bin/env bash
# Launch the pi coding agent with JSGF NLU context.
#
# Usage:
#   ./pi.sh                        # interactive TUI
#   ./pi.sh "your task here"       # run a single task in print mode
#   ./pi.sh --mode json "task"     # JSON event stream
#   ./pi.sh --continue             # resume last session
#   ./pi.sh /generate-intent       # launch the intent generator

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PI="${SCRIPT_DIR}/pi-mono/packages/coding-agent/dist/cli.js"

if [ ! -f "${PI}" ]; then
    echo "pi not built. Run: cd pi-mono && npm run build" >&2
    exit 1
fi

# Run from project root so .pi/ is discovered
cd "${SCRIPT_DIR}"

# Regenerate system prompt from dialect config (skip gracefully if venv absent)
if [ -x "${SCRIPT_DIR}/.venv/bin/python3" ]; then
    "${SCRIPT_DIR}/.venv/bin/python3" "${SCRIPT_DIR}/scripts/render_pi_prompt.py"
else
    echo "WARNING: .venv not found — using pre-rendered .pi/SYSTEM.md" >&2
fi

exec node "${PI}" "$@"
