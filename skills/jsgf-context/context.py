#!/usr/bin/env python3
"""
jsgf-context: Get generation context for a target JSGF file.

Usage:
    python context.py <file.gram> --intent "Transfer funds" \
        --examples '["transfer 100 to savings", "move money to chequing"]'

Outputs JSON to stdout with:
- existing_rules: visible rules accessible from target file
- dialect_functions: available engine functions
- similar_rules: top-N rules with partial utterance coverage
- import_suggestions: files worth importing for reuse
"""

import argparse
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_HERE))

from core.dialect import DialectRegistry
from core.index import GrammarIndex
from core.loader import DataLoader
from agent.api import GrammarAgentAPI


def main():
    parser = argparse.ArgumentParser(description='Get generation context for a JSGF file')
    parser.add_argument('file', help='Target .gram file (may not exist yet)')
    parser.add_argument('--intent', '-i', help='Natural language description of the intent', default='')
    parser.add_argument(
        '--examples', '-e',
        help='JSON array of example utterances',
        default='[]',
    )
    parser.add_argument(
        '--workspace', '-w',
        help='Workspace root (default: parent directory of file)',
        default=None,
    )
    args = parser.parse_args()

    file_path = Path(args.file).resolve()
    workspace = Path(args.workspace).resolve() if args.workspace else file_path.parent

    try:
        examples = json.loads(args.examples)
    except json.JSONDecodeError as e:
        _error(f"Invalid --examples JSON: {e}")

    dialect_cfg = workspace / 'jsgf-dialect.json'
    dialect = (
        DialectRegistry.from_config(dialect_cfg)
        if dialect_cfg.exists()
        else DialectRegistry.standard()
    )
    index = GrammarIndex(workspace, dialect)
    index.index_workspace()
    loader = DataLoader(dialect.data_sources, dialect.lazy_loading, workspace)
    api = GrammarAgentAPI(index, loader=loader)
    ctx = api.get_generation_context(file_path, args.intent, examples)

    print(json.dumps(ctx.as_dict(), indent=2))


def _error(msg: str) -> None:
    print(json.dumps({'error': msg}), file=sys.stderr)
    sys.exit(1)


if __name__ == '__main__':
    main()
