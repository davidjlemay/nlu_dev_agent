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

# Regex that matches parameterized call sites: <name[args]> NOT followed by =
# (declarations are handled separately by _mangle_source)
_CALL_SITE_RE = re.compile(
    r'<([A-Za-z0-9_.$-]+)\[([^\]]*)\]>(?!\s*(?:\{[^}]*\}\s*)*=)'
)


def _strip_dialect_tags(
    source: str,
    func_map: dict | None = None,
    param_map: dict | None = None,
    call_site_map: dict | None = None,
) -> str:
    """
    Prepare source for pyjsgf parsing by neutralising dialect extensions.

    Optional side-effect maps (populated in-place when provided):
      func_map       — token ('PLHDR0') → (fn_name, [args])
      param_map      — token ('PARM_x') → param_name ('x')
      call_site_map  — rule_name → list of arg-lists from call sites

    Steps:
    -1. Capture parameterized call-site args into call_site_map.
     0. Strip [args] from inside angle brackets (parameterized refs/decls).
     0b.Replace bare $param refs with named PARM_<name> tokens.
     1. Remove LHS flag blocks (one or more {…} between > and =).
     2. Replace remaining RHS dialect tag content with {tag}.
     3. Replace $function(...) calls with indexed PLHDR<n> tokens.
    """
    # Step -1: capture call-site args before we strip them
    if call_site_map is not None:
        for m in _CALL_SITE_RE.finditer(source):
            args = [a.strip() for a in m.group(2).split(',') if a.strip()]
            call_site_map.setdefault(m.group(1), []).append(args)

    # Step 0: strip [args] from inside angle brackets (parameterized refs/decls)
    source = re.sub(r'(<[A-Za-z0-9_.$-]+)\[[^\]]*\]>', r'\1>', source)

    # Step 0b: replace bare $param refs (not function calls) with named tokens
    # \b anchors to the end of the identifier so partial prefixes don't match
    # when the full name IS followed by '(' (e.g. $normalise(...) must not match).
    def _param_replacer(m: re.Match) -> str:
        param_name = m.group(1)
        token = f'PARM_{param_name}'
        if param_map is not None:
            param_map[token] = param_name
        return token

    source = re.sub(r'\$([A-Za-z_][A-Za-z0-9_]*)\b(?!\()', _param_replacer, source)

    # Step 1: remove LHS flag blocks (one or more {…} between > and =)
    source = re.sub(r'(?<=>)(\s*\{[^}]*\})+(?=\s*=)', '', source)
    # Step 2: replace remaining RHS dialect tag content with a plain token
    source = re.sub(r'\{[^}]*\}', '{tag}', source)

    # Step 3: replace $function(...) calls with indexed placeholder literals
    _func_counter = [0]

    def _func_replacer(m: re.Match) -> str:
        token = f'PLHDR{_func_counter[0]}'
        _func_counter[0] += 1
        args = [a.strip().strip("'\"") for a in m.group(2).split(',') if a.strip()]
        if func_map is not None:
            func_map[token] = (m.group(1), args)
        return token

    source = re.sub(r'\$([A-Za-z_][A-Za-z0-9_]*)\(([^)]*)\)', _func_replacer, source)
    return source


def _parse_grammar(source: str):
    from jsgf.parser import parse_grammar_string
    return parse_grammar_string(_strip_dialect_tags(source))


# Regex to extract key/type/value triples from a LHS flags string
_FLAG_MANGLE_RE = re.compile(r'\{([^:}]+):([^=}]+)=([^}]+)\}')

# Matches rule declarations that carry at least one LHS flag block.
# Optional [$param1, $param2] after the rule name is captured and dropped
# from pyjsgf output (params are irrelevant to pyjsgf).
_LHS_DECL_RE = re.compile(
    r'(?P<pub>(?:public\s+)?)'
    r'<(?P<rulename>[A-Za-z0-9_.$-]+)'
    r'(?P<params>\[[^\]]*\])?'          # optional [$param1, $param2]
    r'>'
    r'(?P<flags>(?:\s*\{[^}]*\})+)'
    r'(?P<eq>\s*=)'
)


def _safe_flag_val(v: str) -> str:
    """Replace non-identifier chars in a flag value with underscores."""
    return re.sub(r'[^A-Za-z0-9]', '_', v)


def _parse_params(params_str: str) -> list[str]:
    """Parse a params block like '[$from, $to]' into ['from', 'to'].

    Returns an empty list if *params_str* is empty or contains no items.
    The leading '$' is stripped from each param name.
    """
    s = params_str.strip('[] \t')
    if not s:
        return []
    return [p.strip().lstrip('$') for p in s.split(',') if p.strip()]


def _mangle_name(base_name: str, flags_str: str) -> str:
    """
    Compute the pyjsgf-safe rule name by appending sorted flag key/value pairs.

    ``noun`` + ``{number:enum=singular}`` → ``noun__number_singular``
    ``x`` + ``{b:bool=true} {a:enum=masc}`` → ``x__a_masc__b_true``  (sorted)

    Returns *base_name* unchanged if *flags_str* is empty or has no parseable flags.
    """
    if not flags_str or not flags_str.strip():
        return base_name
    flags: dict[str, str] = {}
    for m in _FLAG_MANGLE_RE.finditer(flags_str):
        key = m.group(1).strip()
        val = _safe_flag_val(m.group(3).strip())
        flags[key] = val
    if not flags:
        return base_name
    suffix = '__'.join(f'{k}_{v}' for k, v in sorted(flags.items()))
    return f'{base_name}__{suffix}'


def _mangle_source(
    source: str,
) -> tuple[str, dict[str, str], dict[str, Position]]:
    """
    Rewrite each rule declaration that carries LHS flags so that pyjsgf sees a
    unique, identifier-safe rule name.  Only the declaration name is rewritten;
    references in rule bodies are left unchanged.

    Returns:
        mangled_source      — source with declaration names replaced
        pyjsgf_to_original  — mangled_name → original_name
        pyjsgf_to_position  — mangled_name → Position of '<' in *source*
    """
    pyjsgf_to_original: dict[str, str] = {}
    pyjsgf_to_position: dict[str, Position] = {}
    offsets = _line_offsets(source)

    def replacer(m: re.Match) -> str:
        original = m.group('rulename')
        flags_str = m.group('flags')
        mangled = _mangle_name(original, flags_str)
        if mangled != original:
            pyjsgf_to_original[mangled] = original
            angle_offset = m.start('rulename') - 1  # position of '<'
            pyjsgf_to_position[mangled] = offset_to_position(angle_offset, offsets)
        pub = m.group('pub')
        flags = m.group('flags')
        eq = m.group('eq')
        return f'{pub}<{mangled}>{flags}{eq}'

    mangled_source = _LHS_DECL_RE.sub(replacer, source)

    # Build the full set of known mangled names for flagged-reference resolution.
    _all_mangled: set[str] = set(pyjsgf_to_original.keys())

    # Resolve *flagged body references*: <quel> {gender:enum=masculine} in a rule
    # body should resolve to <quel__gender_masculine>.  The inline flags are
    # consumed (removed) so pyjsgf never sees them.  Optional [args] at the
    # call site (parameterized rules) are also consumed.
    _FLAGGED_REF_RE = re.compile(
        r'<([A-Za-z0-9_.$-]+)'         # base rule name
        r'(?:\[[^\]]*\])?'             # optional [args] (consumed)
        r'>'
        r'((?:\s*\{[^}]*\})+)'         # one or more flag blocks
        r'(?!\s*=)'                     # NOT followed by '=' (that's a declaration)
    )

    def _flagged_ref_replacer(m: re.Match) -> str:
        ref_name = m.group(1)
        flags_str = m.group(2)
        candidate = _mangle_name(ref_name, flags_str)
        if candidate in _all_mangled:
            return f'<{candidate}>'
        # If the mangled name isn't a known declaration, leave it unchanged
        # (will be caught as an undefined-ref diagnostic later).
        return m.group(0)

    mangled_source = _FLAGGED_REF_RE.sub(_flagged_ref_replacer, mangled_source)

    # Post-pass: resolve bare (unflagged) body references to flagged rules.
    original_to_mangled: dict[str, list[str]] = {}
    for mangled_nm, orig_nm in pyjsgf_to_original.items():
        original_to_mangled.setdefault(orig_nm, []).append(mangled_nm)

    unambiguous = {
        orig: mangled_list[0]
        for orig, mangled_list in original_to_mangled.items()
        if len(mangled_list) == 1
    }
    ambiguous = {
        orig: mangled_list
        for orig, mangled_list in original_to_mangled.items()
        if len(mangled_list) > 1
    }

    if unambiguous:
        def _ref_replacer(m: re.Match) -> str:
            name = m.group(1)
            if name in unambiguous:
                return f'<{unambiguous[name]}>'
            return m.group(0)
        # Only replace references (not declarations — those are already mangled).
        # Also handles parameterized refs like <name[args]> — params are dropped.
        mangled_source = re.sub(
            r'<([A-Za-z0-9_.$-]+)(?:\[[^\]]*\])?>(?!\s*(?:\{[^}]*\}\s*)*=)',
            _ref_replacer, mangled_source)

    # For ambiguous names (multiple flag variants), append synthetic union rules
    # so that pyjsgf can resolve bare references like <quel> to any variant.
    if ambiguous:
        union_rules: list[str] = []
        for orig, mangled_list in sorted(ambiguous.items()):
            alts = ' | '.join(f'<{m}>' for m in sorted(mangled_list))
            union_rules.append(f'<{orig}> = {alts};')
        mangled_source += '\n// [synthetic union rules for pyjsgf]\n'
        mangled_source += '\n'.join(union_rules) + '\n'

    return mangled_source, pyjsgf_to_original, pyjsgf_to_position


@dataclass
class RuleInfo:
    """Lightweight record of a discovered rule (even from resilient tokeniser)."""
    name: str
    visible: bool
    body_source: str | None      # None if the rule body failed to parse
    grammar_object: object | None  # pyjsgf Rule, if parsed successfully
    pyjsgf_name: str = ''         # mangled pyjsgf name; defaults to name
    params: list = field(default_factory=list)  # parameter names for parameterized rules

    def __post_init__(self):
        if not self.pyjsgf_name:
            self.pyjsgf_name = self.name


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
    # Positions of rule definitions keyed by pyjsgf_name (mangled for flagged rules)
    pyjsgf_def_positions: dict[str, Position] = field(default_factory=dict)
    # Lookup function placeholders: 'PLHDR0' → ('lookup', ['bank_names'])
    func_placeholders: dict[str, tuple] = field(default_factory=dict)
    # Param token map: 'PARM_from' → 'from'  (informational)
    param_placeholder_map: dict[str, str] = field(default_factory=dict)
    # Parameterized call sites: rule_name → list of arg-lists (before stripping)
    param_call_sites: dict[str, list] = field(default_factory=dict)

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

        # Build params lookup from original source: base name → param list
        # (same params used across all flag variants of a rule)
        _PARAMS_SCAN_RE = re.compile(
            r'(?:public\s+)?<([A-Za-z0-9_.$-]+)(\[[^\]]*\])?>(?:\s*\{[^}]*\})*\s*='
        )
        _name_to_params: dict[str, list[str]] = {}
        for _pm in _PARAMS_SCAN_RE.finditer(source):
            _nm = _pm.group(1)
            if _nm not in _name_to_params:
                _name_to_params[_nm] = _parse_params(_pm.group(2) or '')

        # Mangle rule names for LHS flag variants so pyjsgf sees unique names
        mangled_source, pyjsgf_to_original, pyjsgf_to_pos = _mangle_source(source)

        # pyjsgf_def_positions: unflagged rules keep name == pyjsgf_name,
        # flagged variants get their per-variant positions from _mangle_source
        pyjsgf_def_positions = dict(def_positions)
        pyjsgf_def_positions.update(pyjsgf_to_pos)

        pyjsgf_grammar = None
        # Names that have synthetic union rules — these should not appear in
        # the public rules list (they exist only to let pyjsgf resolve refs).
        _synthetic_names = set(ambiguous) if 'ambiguous' in dir() else set()
        # Safely capture from _mangle_source's post-pass
        _synthetic_names = {
            orig for orig, mangled_list in original_to_mangled.items()
            if len(mangled_list) > 1
        } if (original_to_mangled := {}) or True else set()
        # Re-derive from pyjsgf_to_original
        _orig_to_mangled: dict[str, list[str]] = {}
        for mn, on in pyjsgf_to_original.items():
            _orig_to_mangled.setdefault(on, []).append(mn)
        _synthetic_names = {on for on, ml in _orig_to_mangled.items() if len(ml) > 1}

        # Collect side-effect maps during dialect-tag stripping
        func_placeholders: dict[str, tuple] = {}
        param_placeholder_map: dict[str, str] = {}
        param_call_sites: dict[str, list] = {}

        try:
            from jsgf.parser import parse_grammar_string
            stripped = _strip_dialect_tags(
                mangled_source,
                func_map=func_placeholders,
                param_map=param_placeholder_map,
                call_site_map=param_call_sites,
            )
            g = parse_grammar_string(stripped)
            grammar_name = g.name
            pyjsgf_grammar = g
            for rule in g.rules:
                original_name = pyjsgf_to_original.get(rule.name, rule.name)
                # Skip synthetic union rules added by _mangle_source
                if rule.name in _synthetic_names and rule.name not in pyjsgf_to_original:
                    continue
                rules.append(RuleInfo(
                    name=original_name,
                    visible=rule.visible,
                    body_source=None,
                    grammar_object=rule,
                    pyjsgf_name=rule.name,
                    params=_name_to_params.get(original_name, []),
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
            pyjsgf_def_positions=pyjsgf_def_positions,
            func_placeholders=func_placeholders,
            param_placeholder_map=param_placeholder_map,
            param_call_sites=param_call_sites,
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

        # Check for duplicate rule names within this file.
        # Two rules are duplicates only if they share the same pyjsgf_name
        # (i.e. same base name AND same LHS flags combination).
        seen: dict[str, str] = {}
        for rule in self.rules:
            if rule.pyjsgf_name in seen:
                rng = self._rule_def_range(rule)
                diags.append(lsp.Diagnostic(
                    range=rng,
                    message=f"Duplicate rule definition: <{rule.name}>",
                    severity=lsp.DiagnosticSeverity.Error,
                    source='jsgf-lsp',
                ))
            else:
                seen[rule.pyjsgf_name] = rule.name

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
            if r.name == name or r.pyjsgf_name == name:
                return r
        return None

    def _rule_def_range(self, rule: RuleInfo) -> lsp.Range:
        pos = self.pyjsgf_def_positions.get(rule.pyjsgf_name, Position(0, 0))
        return _pos_to_range(pos, len(rule.name))


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

    # Find rule definitions: optional 'public' <name[params]> [lhs-flags] = ... ;
    for m in re.finditer(
        r'(public\s+)?<([A-Za-z0-9_.$-]+)(\[[^\]]*\])?>((?:\s*\{[^}]*\})*)\s*=([^;]+);',
        source, re.DOTALL
    ):
        visible = bool(m.group(1))
        name = m.group(2)
        params_str = m.group(3) or ''
        flags_str = m.group(4) or ''
        body = m.group(5).strip()
        pyjsgf_nm = _mangle_name(name, flags_str)
        params = _parse_params(params_str)
        rules.append(RuleInfo(
            name=name,
            visible=visible,
            body_source=body,
            grammar_object=None,
            pyjsgf_name=pyjsgf_nm,
            params=params,
        ))

    return rules, imports
