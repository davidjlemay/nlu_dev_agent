"""
Dialect-aware validator.

Runs additional checks beyond standard JSGF structure:
- Typed flag key/type/value validation
- Custom function arity and argument type checks
- Parameterized rule call-site arity (stub — requires dialect parser extension)

Called by GrammarDocument.get_diagnostics() after the base structural checks.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from lsprotocol import types as lsp

from .dialect import DialectRegistry
from .patch import Position
from .document import GrammarDocument, _pos_to_range


# Typed flag pattern:  key:type=value  (value may contain |)
_FLAG_RE = re.compile(
    r'([A-Za-z_][A-Za-z0-9_]*):(string|int|float|bool|enum)=([^,}]+)'
)

# Function call pattern: $name(...)
_FUNC_RE = re.compile(r'\$([A-Za-z_][A-Za-z0-9_]*)\(([^)]*)\)')


def validate_dialect(
    doc: GrammarDocument,
    dialect: DialectRegistry,
) -> list[lsp.Diagnostic]:
    """
    Return dialect-specific diagnostics for *doc*.
    """
    diags: list[lsp.Diagnostic] = []

    if not dialect.functions and not dialect.allowed_flag_types:
        return diags  # standard-jsgf dialect — nothing extra to check

    offsets = _line_offsets(doc.source)

    # Check typed flags in tags
    for m in re.finditer(r'\{([^}]+)\}', doc.source):
        tag_content = m.group(1)
        tag_start = m.start() + 1
        for flag_m in _FLAG_RE.finditer(tag_content):
            key = flag_m.group(1)
            type_str = flag_m.group(2)
            value = flag_m.group(3).strip()
            errors = dialect.validate_flag(key, type_str, value)
            if errors:
                flag_offset = tag_start + flag_m.start()
                pos = _offset_to_position(flag_offset, offsets)
                diags.append(lsp.Diagnostic(
                    range=_pos_to_range(pos, len(flag_m.group(0))),
                    message=errors[0],
                    severity=lsp.DiagnosticSeverity.Error,
                    source='jsgf-lsp',
                ))

    # Check custom function calls
    for m in _FUNC_RE.finditer(doc.source):
        fn_name = m.group(1)
        args_str = m.group(2).strip()
        arg_count = len(args_str.split(',')) if args_str else 0
        errors = dialect.validate_function_call(fn_name, arg_count)
        if errors:
            pos = _offset_to_position(m.start(), offsets)
            diags.append(lsp.Diagnostic(
                range=_pos_to_range(pos, len(m.group(0))),
                message=errors[0],
                severity=lsp.DiagnosticSeverity.Error,
                source='jsgf-lsp',
            ))

    return diags


def _line_offsets(source: str) -> list[int]:
    offsets = [0]
    for i, ch in enumerate(source):
        if ch == '\n':
            offsets.append(i + 1)
    return offsets


def _offset_to_position(offset: int, offsets: list[int]) -> Position:
    import bisect
    line = bisect.bisect_right(offsets, offset) - 1
    character = offset - offsets[line]
    return Position(line=line, character=character)
