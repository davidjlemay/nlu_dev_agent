#!/usr/bin/env bash
# Launch the JSGF Language Server (pygls stdio transport)
#
# Configure your editor's LSP client to run this script as the server command.
#
# VS Code settings.json example:
#   "jsgf.lsp.command": ["/path/to/nlu_dev_agent/lsp-server.sh"]
#
# Neovim (vim.lsp.start) example:
#   cmd = { "/path/to/nlu_dev_agent/lsp-server.sh" }

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="${SCRIPT_DIR}/.venv/bin/python3"
SERVER="${SCRIPT_DIR}/lsp/server.py"

exec "${PYTHON}" "${SERVER}" "$@"
