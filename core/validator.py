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


# Typed flag pattern:  key:type=value
# Captures any type name; dialect.validate_flag() decides if it is allowed.
_FLAG_RE = re.compile(
    r'([A-Za-z_][A-Za-z0-9_]*):([A-Za-z_][A-Za-z0-9_]*)=([^,}]+)'
)

# Function call pattern: $name(...)
_FUNC_RE = re.compile(r'\$([A-Za-z_][A-Za-z0-9_]*)\(([^)]*)\)')

# LHS flag block(s): one or more {…} between '>' and '=' on a rule declaration.
# Captures the run of flag blocks (group 1) so individual blocks can be re-scanned.
# Handles optional [params] inside the angle brackets.
_LHS_RULE_RE = re.compile(
    r'(?:public\s+)?<[A-Za-z0-9_.$-]+(?:\[[^\]]*\])?>'  # rule header
    r'((?:\s*\{[^}]*\})+)'                               # one or more LHS flag blocks
    r'\s*='                                               # then =
)

# Parameterized rule declaration: <name[params]> optionally followed by LHS flags, then =
_PARAM_DECL_RE = re.compile(
    r'<([A-Za-z0-9_.$-]+)\[([^\]]*)\]>(?:\s*\{[^}]*\})*\s*='
)

# Parameterized rule call site: <name[args]> NOT followed by LHS flags then =
_PARAM_CALL_RE = re.compile(
    r'<([A-Za-z0-9_.$-]+)\[([^\]]*)\]>(?!\s*(?:\{[^}]*\}\s*)*=)'
)


def _count_items(items_str: str) -> int:
    """Count comma-separated items; empty string → 0."""
    s = items_str.strip()
    return 0 if not s else len(s.split(','))


def validate_dialect(
    doc: GrammarDocument,
    dialect: DialectRegistry,
) -> list[lsp.Diagnostic]:
    """
    Return dialect-specific diagnostics for *doc*.
    """
    diags: list[lsp.Diagnostic] = []
    offsets = _line_offsets(doc.source)

    # ------------------------------------------------------------------ #
    #  LHS flag detection — always run, regardless of dialect             #
    # ------------------------------------------------------------------ #
    # Collect the source offsets of all LHS flag blocks so RHS tag scanning
    # can skip them (they have already been handled / rejected below).
    lhs_flag_offsets: set[int] = set()

    for rule_m in _LHS_RULE_RE.finditer(doc.source):
        # Iterate over each individual {…} block within the captured run
        for block_m in re.finditer(r'\{[^}]*\}', rule_m.group(1)):
            abs_start = rule_m.start(1) + block_m.start()
            lhs_flag_offsets.add(abs_start)

            if not dialect.lhs_flags_enabled:
                pos = _offset_to_position(abs_start, offsets)
                diags.append(lsp.Diagnostic(
                    range=_pos_to_range(pos, len(block_m.group(0))),
                    message=(
                        "LHS flags are not enabled for this dialect. "
                        "Move the flag to the end of the rule body, or set "
                        "\"allow_lhs\": true in jsgf-dialect.json."
                    ),
                    severity=lsp.DiagnosticSeverity.Error,
                    source='jsgf-lsp',
                ))
            else:
                # Validate the flag content with the same typed-flag rules
                tag_content = block_m.group(0)[1:-1]  # strip { }
                tag_start = abs_start + 1
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

    # RHS tag and function checks only apply to dialects with typed extensions
    if dialect.functions or dialect.allowed_flag_types:
        # ---------------------------------------------------------------- #
        #  RHS tag validation                                               #
        # ---------------------------------------------------------------- #
        # Check typed flags in RHS tags (skip LHS blocks already handled above)
        for m in re.finditer(r'\{([^}]+)\}', doc.source):
            if m.start() in lhs_flag_offsets:
                continue
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

    # ------------------------------------------------------------------ #
    #  Parameterized rule arity checks                                     #
    # ------------------------------------------------------------------ #
    # Collect declared param counts per base rule name.
    param_counts: dict[str, int] = {}
    for m in _PARAM_DECL_RE.finditer(doc.source):
        name = m.group(1)
        count = _count_items(m.group(2))
        if name not in param_counts:
            param_counts[name] = count

    # Check all call sites for arity mismatches.
    if param_counts:
        for m in _PARAM_CALL_RE.finditer(doc.source):
            name = m.group(1)
            if name not in param_counts:
                continue
            expected = param_counts[name]
            actual = _count_items(m.group(2))
            if actual != expected:
                pos = _offset_to_position(m.start(), offsets)
                diags.append(lsp.Diagnostic(
                    range=_pos_to_range(pos, len(m.group(0))),
                    message=(
                        f"Parameterized rule <{name}> expects {expected} argument(s), "
                        f"but {actual} were provided."
                    ),
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
