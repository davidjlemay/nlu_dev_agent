#!/usr/bin/env python3
"""
jsgf-validate: Validate a JSGF grammar file against the workspace index.

Usage:
    python validate.py <file.gram> [--workspace <dir>]

Outputs JSON to stdout:
    {
        "file": "path/to/file.gram",
        "valid": true,
        "diagnostics": [
            {
                "line": 4,
                "character": 8,
                "severity": "error",
                "message": "Undefined rule: <unknownRule>"
            }
        ]
    }
"""

import argparse
import json
import sys
from pathlib import Path

# Resolve project root
_HERE = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_HERE))

from core.dialect import DialectRegistry
from core.document import GrammarDocument
from core.index import GrammarIndex
from core.validator import validate_dialect, validate_engine_capabilities


def main():
    parser = argparse.ArgumentParser(description='Validate a JSGF grammar file')
    parser.add_argument('file', help='Path to the .gram file to validate')
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

    # Load dialect if present
    dialect_cfg = workspace / 'jsgf-dialect.json'
    dialect = (
        DialectRegistry.from_config(dialect_cfg)
        if dialect_cfg.exists()
        else DialectRegistry.standard()
    )

    # Build index
    index = GrammarIndex(workspace, dialect)
    index.index_workspace()
    # Re-index target file with current content (may not be saved)
    source = file_path.read_text(encoding='utf-8')
    index.update_file(file_path, source)

    doc = index._documents[file_path]
    diags = doc.get_diagnostics(index)
    diags += validate_dialect(doc, dialect)
    diags += validate_engine_capabilities(doc, dialect, index)

    result = {
        'file': str(file_path),
        'valid': len(diags) == 0,
        'diagnostics': [_diag_to_dict(d) for d in diags],
    }
    print(json.dumps(result, indent=2))


def _diag_to_dict(d) -> dict:
    severity_map = {1: 'error', 2: 'warning', 3: 'information', 4: 'hint'}
    return {
        'line': d.range.start.line,
        'character': d.range.start.character,
        'severity': severity_map.get(d.severity.value if hasattr(d.severity, 'value') else d.severity, 'error'),
        'message': d.message,
    }


def _error(msg: str) -> None:
    print(json.dumps({'error': msg}), file=sys.stderr)
    sys.exit(1)


if __name__ == '__main__':
    main()
