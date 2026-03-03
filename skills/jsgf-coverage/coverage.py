#!/usr/bin/env python3
"""
jsgf-coverage: Check whether a JSGF rule matches a list of utterances.

Usage:
    python coverage.py <rule_name> <file.gram> --utterances '["hello", "hi"]'
    python coverage.py <rule_name> <file.gram> --utterances-file utterances.txt
    python coverage.py <rule_name> <file.gram> [--workspace <dir>]

Outputs JSON to stdout:
    {
        "rule": "greeting",
        "file": "path/to/file.gram",
        "coverage_ratio": 0.75,
        "covered": ["hello", "hi", "hey"],
        "uncovered": ["good morning"]
    }
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
    parser = argparse.ArgumentParser(description='Check utterance coverage for a JSGF rule')
    parser.add_argument('rule', help='Rule name (without angle brackets)')
    parser.add_argument('file', help='Path to the .gram file defining the rule')
    parser.add_argument(
        '--utterances', '-u',
        help='JSON array of utterance strings',
        default=None,
    )
    parser.add_argument(
        '--utterances-file', '-f',
        help='Path to a file with one utterance per line',
        default=None,
    )
    parser.add_argument(
        '--workspace', '-w',
        help='Workspace root (default: parent directory of file)',
        default=None,
    )
    args = parser.parse_args()

    file_path = Path(args.file).resolve()
    if not file_path.exists():
        _error(f"File not found: {file_path}")

    workspace = Path(args.workspace).resolve() if args.workspace else file_path.parent

    # Parse utterances
    utterances: list[str] = []
    if args.utterances:
        try:
            utterances = json.loads(args.utterances)
        except json.JSONDecodeError as e:
            _error(f"Invalid --utterances JSON: {e}")
    elif args.utterances_file:
        utt_path = Path(args.utterances_file)
        if not utt_path.exists():
            _error(f"Utterances file not found: {utt_path}")
        utterances = [line.strip() for line in utt_path.read_text().splitlines() if line.strip()]
    else:
        _error("Provide --utterances or --utterances-file")

    # Build index and API
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
    result = api.validate_coverage(args.rule, file_path, utterances)

    print(json.dumps({
        'rule': args.rule,
        'file': str(file_path),
        'coverage_ratio': result.coverage_ratio,
        'covered': result.covered,
        'uncovered': result.uncovered,
    }, indent=2))


def _error(msg: str) -> None:
    print(json.dumps({'error': msg}), file=sys.stderr)
    sys.exit(1)


if __name__ == '__main__':
    main()
