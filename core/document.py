"""
GrammarDocument: parse a single JSGF file and produce diagnostics.

Two-stage parsing strategy:
1. Full pyjsgf parse → rich AST with rules, imports, expansions
2. If parse fails, resilient tokeniser finds rule boundaries so the document
   remains structurally useful (rule names known, bodies unparseable)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from lsprotocol import types as lsp
from pyparsing import ParseException

from .patch import (
    Position,
    scan_positions,
    scan_rule_def_positions,
    _line_offsets,
    offset_to_position,
)

if TYPE_CHECKING:
    from .index import GrammarIndex

# Lazy import to avoid circular deps at module level
def _strip_dialect_tags(source: str) -> str:
    """
    Prepare source for pyjsgf parsing by neutralising dialect extensions:

    1. LHS flags — {…} blocks between > and = on rule declarations — are
       removed entirely.  pyjsgf has no concept of rule-level metadata and
       would reject even a sanitised {tag} token in that position.

    2. Remaining RHS tags (in expansion bodies) are replaced with {tag} so
       that pyjsgf can build a correct AST for rule-ref and import analysis.
       pyjsgf's tag regex only allows [\\w\\-\\'] so dialect content like
       {intent:string=greet} must be stripped.

    Dialect-specific validation is done separately by core/validator.py.
    """
    # Step 1: remove LHS flag blocks (one or more {…} between > and =)
    source = re.sub(r'(?<=>)(\s*\{[^}]*\})+(?=\s*=)', '', source)
    # Step 2: replace remaining RHS dialect tag content with a plain token
    return re.sub(r'\{[^}]*\}', '{tag}', source)


def _parse_grammar(source: str):
    from jsgf.parser import parse_grammar_string
    return parse_grammar_string(_strip_dialect_tags(source))


@dataclass
class RuleInfo:
    """Lightweight record of a discovered rule (even from resilient tokeniser)."""
    name: str
    visible: bool
    body_source: str | None      # None if the rule body failed to parse
    grammar_object: object | None  # pyjsgf Rule, if parsed successfully


@dataclass
class ImportInfo:
    """Record of an import statement."""
    name: str           # e.g. 'com.example.shared.*'
    grammar_name: str   # e.g. 'com.example.shared'
    rule_name: str      # e.g. '*' or specific rule name
    wildcard: bool
    position: Position = field(default_factory=lambda: Position(0, 0))


@dataclass
class GrammarDocument:
    path: Path
    source: str
    grammar_name: str | None
    rules: list[RuleInfo]
    imports: list[ImportInfo]
    parse_error: Exception | None
    # Positions of rule references in source (name → sorted list of positions)
    ref_positions: dict[str, list[Position]]
    # Positions of rule definitions (name → position of opening '<')
    def_positions: dict[str, Position]
    # The parsed pyjsgf Grammar object (None if parse failed)
    pyjsgf_grammar: object | None = None

    # ------------------------------------------------------------------ #
    #  Construction                                                        #
    # ------------------------------------------------------------------ #

    @classmethod
    def parse(cls, path: Path, source: str) -> GrammarDocument:
        ref_positions = scan_positions(source)
        def_positions = scan_rule_def_positions(source)

        grammar_name = _extract_grammar_name(source)
        parse_error: Exception | None = None
        rules: list[RuleInfo] = []
        imports: list[ImportInfo] = []

        pyjsgf_grammar = None
        try:
            g = _parse_grammar(source)
            grammar_name = g.name
            pyjsgf_grammar = g
            for rule in g.rules:
                rules.append(RuleInfo(
                    name=rule.name,
                    visible=rule.visible,
                    body_source=None,
                    grammar_object=rule,
                ))
            for imp in g.imports:
                imports.append(ImportInfo(
                    name=imp.name,
                    grammar_name=imp.grammar_name,
                    rule_name=imp.rule_name,
                    wildcard=imp.wildcard_import,
                    position=def_positions.get(imp.name, Position(0, 0)),
                ))
        except (ParseException, Exception) as exc:
            parse_error = exc
            # Fall back to resilient tokeniser
            rules, imports = _resilient_parse(source, def_positions)

        return cls(
            path=path,
            source=source,
            grammar_name=grammar_name,
            rules=rules,
            imports=imports,
            parse_error=parse_error,
            ref_positions=ref_positions,
            def_positions=def_positions,
            pyjsgf_grammar=pyjsgf_grammar,
        )

    # ------------------------------------------------------------------ #
    #  Diagnostics                                                         #
    # ------------------------------------------------------------------ #

    def get_diagnostics(self, index: GrammarIndex) -> list[lsp.Diagnostic]:
        diags: list[lsp.Diagnostic] = []

        # Report parse error
        if self.parse_error is not None:
            diags.append(lsp.Diagnostic(
                range=_parse_error_range(self.parse_error),
                message=f"Parse error: {self.parse_error}",
                severity=lsp.DiagnosticSeverity.Error,
                source='jsgf-lsp',
            ))

        # Check for duplicate rule names within this file
        seen: dict[str, str] = {}
        for rule in self.rules:
            if rule.name in seen:
                rng = self._rule_def_range(rule.name)
                diags.append(lsp.Diagnostic(
                    range=rng,
                    message=f"Duplicate rule definition: <{rule.name}>",
                    severity=lsp.DiagnosticSeverity.Error,
                    source='jsgf-lsp',
                ))
            else:
                seen[rule.name] = rule.name

        # Check each rule's body for undefined rule references
        for rule in self.rules:
            if rule.grammar_object is None:
                continue
            for ref_name in _collect_rule_refs(rule.grammar_object):
                if not index.resolve_rule(ref_name, self.path):
                    positions = self.ref_positions.get(ref_name, [])
                    pos = positions[0] if positions else Position(0, 0)
                    diags.append(lsp.Diagnostic(
                        range=_pos_to_range(pos, len(ref_name)),
                        message=f"Undefined rule: <{ref_name}>",
                        severity=lsp.DiagnosticSeverity.Error,
                        source='jsgf-lsp',
                    ))

        # Check imports resolve to known grammar files
        for imp in self.imports:
            if not index.resolve_import(imp, self.path):
                pos = imp.position
                diags.append(lsp.Diagnostic(
                    range=_pos_to_range(pos, len(imp.name)),
                    message=f"Cannot resolve import: {imp.name}",
                    severity=lsp.DiagnosticSeverity.Warning,
                    source='jsgf-lsp',
                ))

        return diags

    # ------------------------------------------------------------------ #
    #  Helpers                                                             #
    # ------------------------------------------------------------------ #

    def rule_names(self) -> list[str]:
        return [r.name for r in self.rules]

    def get_rule(self, name: str) -> RuleInfo | None:
        for r in self.rules:
            if r.name == name:
                return r
        return None

    def _rule_def_range(self, name: str) -> lsp.Range:
        pos = self.def_positions.get(name, Position(0, 0))
        return _pos_to_range(pos, len(name))


# ------------------------------------------------------------------ #
#  Module-level helpers                                               #
# ------------------------------------------------------------------ #

def _pos_to_range(pos: Position, length: int = 0) -> lsp.Range:
    return lsp.Range(
        start=lsp.Position(line=pos.line, character=pos.character),
        end=lsp.Position(line=pos.line, character=pos.character + length),
    )


def _parse_error_range(exc: Exception) -> lsp.Range:
    """Try to extract line/col from a pyparsing ParseException."""
    if isinstance(exc, ParseException):
        line = max(0, exc.lineno - 1)   # 1-indexed → 0-indexed
        col = max(0, exc.col - 1)
        return lsp.Range(
            start=lsp.Position(line=line, character=col),
            end=lsp.Position(line=line, character=col + 1),
        )
    return lsp.Range(
        start=lsp.Position(line=0, character=0),
        end=lsp.Position(line=0, character=1),
    )


def _collect_rule_refs(pyjsgf_rule) -> list[str]:
    """Walk a pyjsgf Rule's expansion and collect all NamedRuleRef names."""
    return _collect_rule_refs_from_expansion(pyjsgf_rule.expansion)


def _collect_rule_refs_from_expansion(expansion) -> list[str]:
    """Walk an expansion and collect all NamedRuleRef names."""
    from jsgf.expansions import NamedRuleRef
    refs: list[str] = []

    def walk(e):
        if isinstance(e, NamedRuleRef):
            refs.append(e.name)
        for child in getattr(e, 'children', []):
            walk(child)

    walk(expansion)
    return refs


def _extract_grammar_name(source: str) -> str | None:
    """Fast regex extraction of grammar name from header."""
    m = re.search(r'\bgrammar\s+([\w.$-]+)\s*[;\n]', source)
    return m.group(1) if m else None


def _resilient_parse(
    source: str,
    def_positions: dict[str, Position],
) -> tuple[list[RuleInfo], list[ImportInfo]]:
    """
    Tokeniser-only fallback: scan for rule boundaries and import lines.
    Returns partial RuleInfo/ImportInfo lists without grammar objects.
    """
    rules: list[RuleInfo] = []
    imports: list[ImportInfo] = []

    # Find import lines
    for m in re.finditer(
        r'\bimport\s+<([\w.$*-]+)>\s*[;\n]', source
    ):
        full_name = m.group(1)
        parts = full_name.rsplit('.', 1)
        grammar_nm = parts[0] if len(parts) > 1 else full_name
        rule_nm = parts[1] if len(parts) > 1 else '*'
        imports.append(ImportInfo(
            name=full_name,
            grammar_name=grammar_nm,
            rule_name=rule_nm,
            wildcard=(rule_nm == '*'),
            position=def_positions.get(full_name, Position(0, 0)),
        ))

    # Find rule definitions: optional 'public' <name> [lhs-flags] = ... ;
    for m in re.finditer(
        r'(public\s+)?<([A-Za-z0-9_.$-]+)>(?:\s*\{[^}]*\})*\s*=([^;]+);', source, re.DOTALL
    ):
        visible = bool(m.group(1))
        name = m.group(2)
        body = m.group(3).strip()
        rules.append(RuleInfo(
            name=name,
            visible=visible,
            body_source=body,
            grammar_object=None,
        ))

    return rules, imports
