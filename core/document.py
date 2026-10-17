"""
GrammarDocument: parse a single JSGF file and produce diagnostics.

Two-stage parsing strategy:
1. Full pyjsgf parse → rich AST with rules, imports, expansions
2. If parse fails, resilient tokeniser finds rule boundaries so the document
   remains structurally useful (rule names known, bodies unparseable)
"""

from __future__ import annotations

import hashlib
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

# Cerence grammars can contain deeply nested alternatives. pyjsgf/pyparsing
# and the expansion walker both recurse, so raise the interpreter limit.
sys.setrecursionlimit(max(50000, sys.getrecursionlimit()))

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

# Rule-name character class.  pyjsgf's base_name allows a wider set of
# punctuation; in practice Cerence names use letters/digits/underscore plus
# '.', '$', '&', '#', '%', '+', '!', '~', '^', '-' and ':'.
_RULE_NAME_CHARS = r'[\w.$&:\-#%+!~^]+'

# Regex that matches simple (non-nested) parameterized call sites:
# <name[args]> or <name(args)> NOT followed by =.
# (declarations and nested call sites are handled by _strip_rule_ref_args)
_CALL_SITE_RE = re.compile(
    r'<' + _RULE_NAME_CHARS + r'(?:\[([^\]]*)\]|\(([^)]*)\))>(?!\s*(?:\{[^}]*\}\s*)*=)'
)

# Matches a full parameterized rule (declaration + body) for param-ref substitution.
# Group 1: rule name, Group 2: params block (including brackets), Group 3: body text.
_PARAM_BODY_RE = re.compile(
    r'(?:public\s+)?'
    r'<(' + _RULE_NAME_CHARS + r')'  # rule name
    r'(\[[^\]]+\]|\([^)]+\))'      # [params] or (params) — required
    r'>'
    r'(?:\s*\{[^}]*\})*'            # optional LHS flags
    r'\s*=\s*'
    r'([^;]+)'                       # body
    r';',
    re.DOTALL,
)


def _substitute_param_refs(
    source: str,
) -> tuple[str, dict[str, str]]:
    """
    Pre-pass: replace ``<param>`` rule-ref syntax inside parameterized rule bodies
    with ``PARM_param`` tokens, scoped to each rule's declared parameter list.

    Returns:
        modified_source      — source with ``<param>`` → ``PARM_param`` substituted
        param_placeholder_map — ``{'PARM_from': 'from', ...}`` (informational)

    Body references to real rules whose names happen to collide with a param name
    are only rewritten inside the rule body that declares that param, so scoping
    is correct as long as param names are distinct from each other.
    """
    param_placeholder_map: dict[str, str] = {}
    if '<' not in source:
        return source, param_placeholder_map

    # Build list of (match.start, match.end, {param: token}) for all parameterized rules
    substitutions: list[tuple[int, int, str]] = []  # (body_start, body_end, rewritten_body)

    for m in _PARAM_BODY_RE.finditer(source):
        params = _parse_params(m.group(2))
        if not params:
            continue
        body = m.group(3)
        body_start = m.start(3)
        body_end = m.end(3)
        for param in params:
            token = f'PARM_{param}'
            param_placeholder_map[token] = param
            body = re.sub(rf'<({re.escape(param)})>', lambda _, t=token: t, body)
        substitutions.append((body_start, body_end, body))

    if not substitutions:
        return source, param_placeholder_map

    # Apply substitutions in reverse order to preserve offsets
    result = source
    for body_start, body_end, new_body in reversed(substitutions):
        result = result[:body_start] + new_body + result[body_end:]

    return result, param_placeholder_map


def _strip_weights(source: str) -> str:
    source = re.sub(r'\|\|', '|', source)
    # Strip all JSGF probability weights (/N/ or /N.N/).
    # We do this globally; weights are optional in pyjsgf and frequently use
    # Cerence's `||` alternative separator, which is normalised above.
    # Only consume horizontal whitespace so a weight line does not get glued
    # to a preceding `//` comment line (which would then be stripped entirely).
    return re.sub(r'[^\S\n]*/\d+(?:\.\d+)?/[^\S\n]*', ' ', source)


# Bracket pairs used to balance rule-reference argument lists.
_OPENING = set('([{<')
_CLOSING = {')': '(', ']': '[', '}': '{', '>': '<'}
_RULE_NAME_RE = re.compile(_RULE_NAME_CHARS)


# Punctuation characters that are not valid inside pyjsgf rule-body literals.
# JSGF operators/brackets (()[]{}<>|*+-_'";=$#%/) and word-joiners are excluded.
_PUNCTUATION_BODY_SET = frozenset('.,:?!&~^@')


# Maximum top-level alternatives in a rule body before we chunk it into smaller
# required groups.  pyjsgf/pyparsing can hit Python's recursion limit on very
# long flat alternative lists.
_MAX_RULE_ALTERNATIVES = 10


# Parenthesized rule-name templates used by Cerence generator sources, e.g.:
#   public (<pre> <v_RAD> <post>){self_pronoun:no,...} =
# pyjsgf only supports '<'...'>' rule names, so these are flagged as errors.
_PAREN_LHS_RE = re.compile(
    r'(?:public\s+)?\([^=]*?\)\s*\{[^}]*\}\s*=',
    re.MULTILINE,
)


def _is_rule_declaration(source: str, l: int) -> bool:
    """Return True if the rule reference ending at *l* is a declaration (``>...=``)."""
    n = len(source)
    peek = l + 1
    while peek < n and source[peek].isspace():
        peek += 1
    while peek < n and source[peek] == '{':
        # skip a tag/flag block
        depth = 1
        peek += 1
        while peek < n and depth:
            if source[peek] == '{':
                depth += 1
            elif source[peek] == '}':
                depth -= 1
            peek += 1
        while peek < n and source[peek].isspace():
            peek += 1
    return peek < n and source[peek] == '='


def _mask_comments(source: str) -> str:
    """
    Replace C-style comments with spaces so they no longer match rule headers.

    Positions and newlines are preserved, which keeps line/character offsets
    aligned with the original source for diagnostics.
    """
    result = list(source)
    n = len(source)
    i = 0
    while i < n:
        if source.startswith('/*', i):
            # Mask the opening /* as well as the body and the closing */.
            if result[i] not in '\r\n':
                result[i] = ' '
            if result[i + 1] not in '\r\n':
                result[i + 1] = ' '
            j = i + 2
            while j < n and not source.startswith('*/', j):
                if result[j] not in '\r\n':
                    result[j] = ' '
                j += 1
            if j < n:
                if result[j] not in '\r\n':
                    result[j] = ' '
                if j + 1 < n and result[j + 1] not in '\r\n':
                    result[j + 1] = ' '
                j += 2
            i = j
            continue
        if source.startswith('//', i):
            j = i
            while j < n and source[j] not in '\r\n':
                if result[j] not in '\r\n':
                    result[j] = ' '
                j += 1
            i = j
            continue
        i += 1
    return ''.join(result)


def _skip_balanced(source: str, i: int, open_ch: str, close_ch: str) -> int:
    """Return the index just past the matching *close_ch* starting at *open_ch*."""
    n = len(source)
    if i >= n or source[i] != open_ch:
        return i + 1
    depth = 1
    j = i + 1
    while j < n and depth:
        c = source[j]
        if c == open_ch:
            depth += 1
        elif c == close_ch:
            depth -= 1
        # Strings preserve escapes, but only for double quotes.
        if open_ch == '"' and c == '\\' and j + 1 < n:
            j += 1
        j += 1
    return j


def _skip_rule_ref(source: str, i: int) -> int:
    """Return the index just past a rule reference ``<name[args]``...``>``."""
    n = len(source)
    if i >= n or source[i] != '<':
        return i + 1
    m = _RULE_NAME_RE.match(source, i + 1)
    if not m:
        j = source.find('>', i)
        return j + 1 if j != -1 else n
    j = m.end()
    while j < n and source[j].isspace():
        j += 1
    if j < n and source[j] in '([':
        close = ')' if source[j] == '(' else ']'
        j = _skip_balanced(source, j, source[j], close)
        while j < n and source[j].isspace():
            j += 1
    if j < n and source[j] == '>':
        return j + 1
    return min(j + 1, n)


def _scan_punctuation(
    source: str,
    replace: bool = True,
) -> tuple[str, list[tuple[int, str]]]:
    """
    Scan *source* and either normalise punctuation in rule bodies (``replace=True``)
    or just record where it occurs (``replace=False``).

    Rule references, grammar/import declarations, AVM/tag blocks and double-quoted
    strings are skipped so their punctuation is preserved.
    """
    n = len(source)
    result: list[str] = [] if replace else None  # type: ignore[assignment]
    warnings: list[tuple[int, str]] = []
    i = 0
    at_line_start = True

    while i < n:
        c = source[i]
        if c in '\r\n':
            at_line_start = True
            if replace:
                result.append(c)
            i += 1
            continue
        if at_line_start and c.isspace():
            if replace:
                result.append(c)
            i += 1
            continue
        if at_line_start:
            # Skip the JSGF header line; it can contain a version number like V1.0.
            if source.startswith('#JSGF', i):
                j = i
                while j < n and source[j] not in '\r\n':
                    if replace:
                        result.append(source[j])
                    j += 1
                i = j
                at_line_start = False
                continue
            if (source.startswith('grammar', i) and
                    (i + 7 == n or source[i + 7].isspace())):
                j = i
                while j < n and source[j] != ';':
                    if replace:
                        result.append(source[j])
                    j += 1
                if j < n:
                    if replace:
                        result.append(';')
                    j += 1
                i = j
                at_line_start = False
                continue
            if (source.startswith('import', i) and
                    (i + 6 == n or source[i + 6].isspace())):
                j = i
                while j < n and source[j] != ';':
                    if replace:
                        result.append(source[j])
                    j += 1
                if j < n:
                    if replace:
                        result.append(';')
                    j += 1
                i = j
                at_line_start = False
                continue
            at_line_start = False
        if c == '<':
            j = _skip_rule_ref(source, i)
            if replace:
                result.extend(source[i:j])
            i = j
            continue
        if c == '{':
            j = _skip_balanced(source, i, '{', '}')
            if replace:
                result.extend(source[i:j])
            i = j
            continue
        if c == '"':
            j = _skip_balanced(source, i, '"', '"')
            if replace:
                result.extend(source[i:j])
            i = j
            continue
        if c in _PUNCTUATION_BODY_SET:
            if replace:
                result.append(' ')
            warnings.append((i, c))
            i += 1
            continue
        if replace:
            result.append(c)
        i += 1

    if replace:
        return ''.join(result), warnings
    return source, warnings


def _find_punctuation_warnings(source: str) -> list[tuple[int, str]]:
    """Return positions of punctuation characters in rule bodies."""
    _, warnings = _scan_punctuation(source, replace=False)
    return warnings


def _normalise_punctuation(source: str) -> str:
    """Replace punctuation in rule-body literals with spaces for pyjsgf."""
    cleaned, _ = _scan_punctuation(source, replace=True)
    return cleaned


def _split_wordforms(source: str) -> str:
    def _repl(m):
        return f'{m.group(1)} _{m.group(2)}'
    source = re.sub(r'(<[^>]+>|PARM_[A-Za-z0-9_]+)_' + re.escape(chr(92)) + r'(\w+)', _repl, source)
    return re.sub(re.escape(chr(92)) + r'(\w+)', r' \1', source)


def _fix_grammar_declaration(source: str, path: Path) -> str:
    """
    Normalise the grammar declaration.

    - ``grammar <name>;`` -> ``grammar name;``
    - ``grammar ;``       -> ``grammar <stem>;`` (from the file name)
    - missing grammar line -> insert ``grammar <stem>;`` after the #JSGF header
    """
    # Some files use ``grammar <special_date>;`` — strip the angle brackets.
    source = re.sub(r'\bgrammar\s*<([^>]+)>\s*;', r'grammar \1;', source)

    # Empty grammar name.
    if re.search(r'\bgrammar\s*;', source):
        name = path.stem
        source = re.sub(r'\bgrammar\s*;', f'grammar {name};', source)

    # No grammar line at all (e.g. comment-only files)
    if not re.search(r'\bgrammar\s+\S', source):
        name = path.stem
        m = re.search(r'^#JSGF.*$', source, re.MULTILINE)
        if m:
            insert = m.end()
            source = source[:insert] + f'\ngrammar {name};\n' + source[insert:]
        else:
            source = f'grammar {name};\n' + source
    return source


def _strip_rule_ref_args(source: str, call_site_map: dict | None = None) -> str:
    """
    Remove bracketed argument lists from rule references.

    Declarations are left intact (the parameter list is needed by
    ``_mangle_source`` to distinguish typed-param variants).  Call-site args are
    stripped and, when *call_site_map* is supplied, recorded for later expansion.

    Cerence call sites can nest rule refs, optional groups and AVM tags inside
    their arguments, e.g. ``<all_get_OBJECT((<most_used> (par | avec) ...))>``.
    A simple regex cannot handle the nesting, so we use a tiny bracket stack.
    """
    result: list[str] = []
    i = 0
    n = len(source)

    while i < n:
        ch = source[i]
        if ch != '<':
            result.append(ch)
            i += 1
            continue

        m = _RULE_NAME_RE.match(source, i + 1)
        if not m:
            result.append(ch)
            i += 1
            continue

        name_end = m.end()
        j = name_end
        while j < n and source[j].isspace():
            j += 1
        if j >= n or source[j] not in '([':
            # No argument list after this rule name.
            result.extend(source[i:j])
            i = j
            continue

        open_br = source[j]
        # Walk the source from the opening bracket, balancing all bracket types,
        # until the matching closing bracket for the argument list.
        stack: list[str] = [open_br]
        k = j + 1
        while k < n and stack:
            c = source[k]
            if c in _OPENING:
                stack.append(c)
            elif c in _CLOSING:
                if stack and _CLOSING[c] == stack[-1]:
                    stack.pop()
                # unmatched closing bracket: ignore (it will likely surface later)
            k += 1

        # After the args close, optional whitespace and then the rule-ref ``>``.
        l = k
        while l < n and source[l].isspace():
            l += 1
        if l >= n or source[l] != '>':
            # Malformed; copy what we have and move on.
            result.extend(source[i:j])
            i = j
            continue

        if _is_rule_declaration(source, l):
            # Keep declarations as-is for the mangling pass to see typed params.
            result.extend(source[i:l + 1])
            i = l + 1
            continue

        if call_site_map is not None:
            # Call site: record the raw arguments (best-effort split on commas).
            args_raw = source[j + 1:k - 1]
            args = [a.strip() for a in args_raw.split(',') if a.strip()]
            call_site_map.setdefault(m.group(0), []).append(args)

        # Emit ``<name>`` and skip the arguments and the closing ``>``.
        result.append('<')
        result.extend(m.group(0))
        result.append('>')
        i = l + 1

    return ''.join(result)


def _replace_rhs_tags(source: str) -> str:
    """
    Replace every balanced `{...}` block with the generic `{tag}` token.

    Cerence AVM tags can nest (``{$SLOT{key:value}}``), so a simple regex
    would corrupt the source.  This small scanner preserves nesting.
    """
    result: list[str] = []
    i = 0
    n = len(source)
    while i < n:
        if source[i] == '{':
            depth = 1
            j = i + 1
            while j < n and depth:
                if source[j] == '{':
                    depth += 1
                elif source[j] == '}':
                    depth -= 1
                j += 1
            result.append('{tag}')
            i = j
        else:
            result.append(source[i])
            i += 1
    return ''.join(result)


def _strip_dialect_tags(
    source: str,
    func_map: dict | None = None,
    call_site_map: dict | None = None,
) -> str:
    """
    Prepare source for pyjsgf parsing by neutralising dialect extensions.

    Optional side-effect maps (populated in-place when provided):
      func_map       — token ('PLHDR0') → (fn_name, [args])
      call_site_map  — rule_name → list of arg-lists from call sites

    Steps:
    -2. Normalise typographic apostrophe and middle-dot punctuation.
    -1. Strip ``#`` non-JSGF pragma lines and C++ ``//`` comments.
     0. Replace double-quoted AVM output strings and ``#hash`` literals with
        plain placeholder words.
     1. Strip probability weights and ``%`` elision markers.
     2. Strip bracket/paren argument lists from rule references.
     3. Remove LHS flag blocks (one or more {…} between > and =).
     4. Replace remaining RHS dialect tag content with {tag}.
     5. Replace $function(...) calls with indexed PLHDR<n> tokens.
     6. Replace bare $identifier (no parens) with PLHDR<n> tokens.
    """
    # Normalise non-ASCII punctuation that pyjsgf's word regex does not accept.
    source = source.replace('’', "'")
    source = source.replace('·', ' ')

    # Remove non-JSGF ``#`` pragmas such as ``#ALLOW-NULL`` and ``#USE``.
    source = re.sub(r'^\s*#(?!JSGF).*$', '', source, flags=re.MULTILINE)

    # Strip C++-style line comments; pyjsgf only supports /* … */ comments.
    source = re.sub(r'//.*$', '', source, flags=re.MULTILINE)

    # Replace double-quoted AVM output strings with placeholder literals.
    _avm_counter = [0]

    def _avm_replacer(m: re.Match) -> str:
        token = f'AVM{_avm_counter[0]}'
        _avm_counter[0] += 1
        return token

    source = re.sub(r'"[^"]*"', _avm_replacer, source)

    # Replace ``#hash`` literals (but not ``#JSGF``) with placeholder words.
    _hash_counter = [0]

    def _hash_replacer(m: re.Match) -> str:
        token = f'HASH{_hash_counter[0]}'
        _hash_counter[0] += 1
        return token

    source = re.sub(r'(?<![\w/])#(?!JSGF)([\w-]+)', _hash_replacer, source)

    source = _strip_weights(source)

    # Remove Cerence ``%`` elision marker, e.g. ``xxestcequ%``.
    source = source.replace('%', '')

    # Step 2: strip nested bracket/paren argument lists from rule references.
    source = _strip_rule_ref_args(source, call_site_map)

    # Step 3: remove LHS flag blocks (one or more {…} between > and =)
    source = re.sub(r'(?<=>)(\s*\{[^}]*\})+(?=\s*=)', '', source)
    # Step 4: replace remaining RHS dialect tag content with a plain token.
    # Tags may nest, so the balanced-brace scanner is used instead of a regex.
    source = _replace_rhs_tags(source)

    # Shared counter for PLHDR tokens (Steps 5 and 6 use the same sequence)
    _func_counter = [0]

    # Step 5: replace $function(...) calls with indexed placeholder literals
    def _func_replacer(m: re.Match) -> str:
        token = f'PLHDR{_func_counter[0]}'
        _func_counter[0] += 1
        args = [a.strip().strip("'\"") for a in m.group(2).split(',') if a.strip()]
        if func_map is not None:
            func_map[token] = (m.group(1), args)
        return token

    source = re.sub(r'\$([A-Za-z_][A-Za-z0-9_]*)\(([^)]*)\)', _func_replacer, source)

    # Step 6: bare $identifier (not followed by '(') → PLHDRn lookup shorthand.
    # Runs after Step 5 so explicit $lookup('x') is already consumed.
    # \b ensures we don't partially match function-name prefixes.
    def _shorthand_replacer(m: re.Match) -> str:
        token = f'PLHDR{_func_counter[0]}'
        _func_counter[0] += 1
        if func_map is not None:
            func_map[token] = ('lookup', [m.group(1)])
        return token

    source = re.sub(r'\$([A-Za-z_][A-Za-z0-9_]*)\b(?!\()', _shorthand_replacer, source)
    return source


def _parse_grammar(source: str):
    from jsgf.parser import parse_grammar_string
    return parse_grammar_string(_strip_dialect_tags(source))


# Regex to extract key/value pairs from AVM/typed flag blocks
_AVM_RE = re.compile(r'([A-Za-z_][A-Za-z0-9_]*)\s*:\s*([^,\s}]+)')

# Matches rule declarations (with or without LHS flags).
# Optional [$param1, $param2] or (typed params) after the rule name is
# captured so it can be used to disambiguate typed-param variants.
_LHS_DECL_RE = re.compile(
    r'(?P<pub>(?:public\s+)?)'
    r'<(?P<rulename>' + _RULE_NAME_CHARS + r')'
    r'(?P<params>\[[^\]]*\]|\([^)]*\))?'  # optional [$param1, $param2] or (params)
    r'>'
    r'(?P<flags>(?:\s*\{[^}]*\})*)'        # zero or more LHS flag blocks
    r'(?P<eq>\s*=)'
)


def _safe_flag_val(v: str) -> str:
    """Replace non-identifier chars in a flag value with underscores."""
    return re.sub(r'[^A-Za-z0-9]', '_', v)


_AVM_WILDCARD_VALUES = frozenset({'*', '?'})
_AVM_VARIABLE_PREFIX = '?'


def _is_unconstrained_value(v: str) -> bool:
    """Return True if *v* is an AVM wildcard, variable or disjunction."""
    v = v.strip()
    if not v or v in _AVM_WILDCARD_VALUES:
        return True
    if v.startswith(_AVM_VARIABLE_PREFIX) or '|' in v:
        return True
    return False


def _avm_flag_pairs(flags_str: str) -> dict[str, str]:
    """Parse an AVM/typed flag block into key -> raw value."""
    pairs: dict[str, str] = {}
    for m in _AVM_RE.finditer(flags_str):
        key = m.group(1).strip()
        raw = m.group(2).strip()
        if '=' in raw:
            _, _, raw = raw.partition('=')
        pairs[key] = raw.strip() or '*'
    return pairs


def _canonical_fixed_flags(flags_str: str) -> frozenset[tuple[str, str]]:
    """
    Return the fixed (non-wildcard/variable) key/value pairs from an AVM block.

    Wildcards ('*'), variables ('?n'), and disjunctions ('plural|singular')
    are ignored because they do not constrain the rule to a single value.
    The result is a canonical, hashable key for mangling and merging.
    """
    fixed: set[tuple[str, str]] = set()
    for m in _AVM_RE.finditer(flags_str):
        key = m.group(1).strip()
        raw = m.group(2).strip()
        if '=' in raw:
            _, _, raw = raw.partition('=')
        raw = raw.strip()
        if _is_unconstrained_value(raw):
            continue
        safe = _safe_flag_val(raw)
        if safe:
            fixed.add((key, safe))
    return frozenset(fixed)


def _avm_matches(query: dict[str, str], variant: dict[str, str]) -> bool:
    """Return True if *query* flags unify with *variant* flags."""
    all_keys = set(query) | set(variant)
    for key in all_keys:
        qv = query.get(key)
        vv = variant.get(key)
        # Missing key means "no constraint" on either side.
        if qv is None or vv is None:
            continue
        if _is_unconstrained_value(qv) or _is_unconstrained_value(vv):
            continue
        if qv == vv:
            continue
        return False
    return True


def _avm_specificity(flags: dict[str, str]) -> int:
    """Count how many fixed (constraining) values the flag set contains."""
    return sum(1 for v in flags.values() if not _is_unconstrained_value(v))


def _select_variant(
    base_name: str,
    query_flags: dict[str, str],
    variants: list[dict],
) -> str | None:
    """
    Choose the best pyjsgf rule name for a reference to *base_name* with
    *query_flags*.  *variants* is a list of dicts with keys 'mangled', 'flags'.

    - An exact fixed match is preferred over a wildcard/variable match.
    - Among matches, a variant with fewer extra fixed constraints is preferred
      (so a query {gender:fem} does not pick {gender:fem, number:plural} if a
      bare {gender:fem} variant exists).
    - For a fully unconstrained query, a wildcard variant (mangled == base_name,
      all flags unconstrained) is preferred.  If no wildcard exists and there is
      exactly one variant, that variant is used.  Otherwise the reference is left
      for the synthetic union or a later diagnostic.
    """
    if not variants:
        return None

    query_fixed = {k for k, v in query_flags.items() if not _is_unconstrained_value(v)}

    # Fully unconstrained reference (no fixed query values)
    if not query_fixed:
        for v in variants:
            if v['mangled'] == base_name and _avm_specificity(v['flags']) == 0:
                return v['mangled']
        if len(variants) == 1:
            return variants[0]['mangled']
        return None

    matching = [v for v in variants if _avm_matches(query_flags, v['flags'])]
    if not matching:
        return None

    def score(v: dict) -> tuple[int, int]:
        exact = sum(
            1 for k in query_fixed
            if k in v['flags'] and not _is_unconstrained_value(v['flags'][k]) and v['flags'][k] == query_flags[k]
        )
        extra = _avm_specificity(v['flags']) - exact
        return (exact, -extra)

    return max(matching, key=score)['mangled']


def _parse_params(params_str: str) -> list[str]:
    """Parse a params block like '[$from, $to]' or '(OBJECT:{gender,number})'
    into the list of parameter names.

    Returns an empty list if *params_str* is empty or contains no items.
    The leading '$' is stripped, and type annotations (':...' or '{...}')
    are discarded.  Commas inside nested braces or parentheses are not treated
    as separators, so type descriptors such as ``{gender,number}`` are handled
    correctly.
    """
    s = params_str.strip()
    if s.startswith('[') and s.endswith(']'):
        s = s[1:-1]
    elif s.startswith('(') and s.endswith(')'):
        s = s[1:-1]
    s = s.strip()
    if not s:
        return []

    # Split on commas while respecting nested () and {}.
    items: list[str] = []
    current: list[str] = []
    depth = 0
    for ch in s:
        if ch in '({[':
            depth += 1
        elif ch in ')}]':
            depth -= 1
        if ch == ',' and depth == 0:
            items.append(''.join(current).strip())
            current = []
            continue
        current.append(ch)
    items.append(''.join(current).strip())

    names: list[str] = []
    for p in items:
        if not p:
            continue
        p = p.lstrip('$')
        # Drop ':type' or '{feature,...}' annotations, keeping the base name.
        if ':' in p or '{' in p:
            p = re.split(r'[:{]', p, maxsplit=1)[0]
        p = p.strip()
        if p:
            names.append(p)
    return names


_DECL_HEADER_RE = re.compile(
    r'(?P<pub>(?:public\s+)?)'
    r'<(?P<name>' + _RULE_NAME_CHARS + r')'
    r'(?P<params>(?:\[[^\]]*\]|\([^)]*\)))?'
    r'>'
    r'(?P<flags>(?:\s*\{[^}]*\})*)'
    r'\s*='
)


def _find_rule_declarations(source: str) -> list[dict]:
    """
    Scan *source* for rule declarations.

    Returns a list of declarations with their full span, header, and body text.
    Body boundaries are discovered with a bracket stack so that nested ``( ... )``,
    ``[ ... ]``, ``{ ... }`` and ``< ... >`` do not hide the terminating ``;``.
    """
    decls: list[dict] = []
    for m in _DECL_HEADER_RE.finditer(source):
        eq = m.end()
        stack: list[str] = []
        i = eq
        n = len(source)
        while i < n:
            c = source[i]
            if c in _OPENING:
                stack.append(c)
            elif c in _CLOSING:
                if stack and _CLOSING[c] == stack[-1]:
                    stack.pop()
            elif c == ';' and not stack:
                break
            i += 1
        body = source[eq:i].strip()
        decls.append({
            'start': m.start(),
            'end': i + 1,
            'header_end': eq,
            'pub': bool(m.group('pub')),
            'name': m.group('name'),
            'params': m.group('params') or '',
            'flags': m.group('flags') or '',
            'body': body,
        })
    return decls


def _merge_duplicate_rule_declarations(source: str) -> str:
    """
    Merge rule declarations that share the same name, params and LHS flags.

    Cerence source files frequently repeat a rule header with a different body
    (e.g. two public parameterised variants).  pyjsgf treats these as duplicate
    rule definitions, so we rewrite them as a single rule whose body is the
    disjunction of the original bodies.
    """
    decls = _find_rule_declarations(source)
    if not decls:
        return source

    by_key: dict[tuple[str, str, frozenset], list[dict]] = {}
    for d in decls:
        by_key.setdefault((d['name'], d['params'], _canonical_fixed_flags(d['flags'])), []).append(d)

    replacements: list[tuple[int, int, str]] = []
    for key, group in by_key.items():
        if len(group) <= 1:
            continue
        # Replace the first declaration with the merged rule and remove the rest.
        bodies = [g['body'].strip() for g in group if g['body'].strip()]
        if not bodies:
            # All bodies are empty (e.g. commented placeholders); keep the first
            # declaration and remove the duplicates.  A later rule can override.
            first = group[0]
            replacements.append((first['start'], first['end'], source[first['start']:first['end']]))
            for g in group[1:]:
                replacements.append((g['start'], g['end'], ''))
            continue
        merged = ' | '.join(f'({b})' for b in bodies)
        pub = 'public ' if any(g['pub'] for g in group) else ''
        first = group[0]
        replacement = f'{pub}<{first["name"]}{first["params"]}>{first["flags"]} = {merged};'
        replacements.append((first['start'], first['end'], replacement))
        for g in group[1:]:
            replacements.append((g['start'], g['end'], ''))

    # Apply replacements in reverse order so offsets stay valid.
    replacements.sort(key=lambda x: x[0], reverse=True)
    result = source
    for start, end, repl in replacements:
        result = result[:start] + repl + result[end:]
    return result


def _split_top_level(source: str, sep: str = '|') -> list[str]:
    """Split *source* at *sep* characters that are not inside brackets."""
    segments: list[str] = []
    current: list[str] = []
    stack: list[str] = []
    n = len(source)
    i = 0
    while i < n:
        c = source[i]
        if c in _OPENING:
            stack.append(c)
        elif c in _CLOSING:
            if stack and _CLOSING[c] == stack[-1]:
                stack.pop()
        elif c == sep and not stack:
            segments.append(''.join(current))
            current = []
            i += 1
            continue
        current.append(c)
        i += 1
    segments.append(''.join(current))
    return segments


def _is_outer_group(body: str) -> tuple[bool, int, str] | None:
    """
    If *body* is a single required group (possibly with trailing AVM tags),
    return (True, close_index, trailing_tags).  Otherwise return None.
    """
    body = body.strip()
    if not body.startswith('('):
        return None
    depth = 0
    close_idx = -1
    for i, c in enumerate(body):
        if c == '(':
            depth += 1
        elif c == ')':
            depth -= 1
            if depth == 0:
                close_idx = i
                break
    if close_idx < 0:
        return None

    j = close_idx + 1
    n = len(body)
    while j < n and body[j].isspace():
        j += 1
    trail_start = j
    while j < n and body[j] == '{':
        # Skip a balanced { ... } tag/AVM block.
        d = 1
        j += 1
        while j < n and d:
            if body[j] == '{':
                d += 1
            elif body[j] == '}':
                d -= 1
            j += 1
        while j < n and body[j].isspace():
            j += 1
    if j != n:
        return None
    return True, close_idx, body[trail_start:j]


def _chunk_long_alternatives(
    source: str,
    max_alts: int = _MAX_RULE_ALTERNATIVES,
) -> tuple[str, list[str]]:
    """
    Split rule bodies with too many top-level alternatives into nested groups.

    Returns the rewritten source and a list of rule names that were chunked.
    """
    decls = _find_rule_declarations(source)
    if not decls:
        return source, []

    replacements: list[tuple[int, int, str]] = []
    chunked: list[str] = []

    for d in decls:
        body = d['body'].strip()
        if not body:
            continue

        is_group = _is_outer_group(body)
        if is_group:
            _, close_idx, trail = is_group
            inner = body[1:close_idx]
            outer = True
        else:
            inner = body
            trail = ''
            outer = False

        segments = _split_top_level(inner)
        if len(segments) <= max_alts:
            continue

        # Drop empty/whitespace-only segments that can appear around lone `|` lines.
        segments = [s for s in segments if s.strip()]
        if len(segments) <= max_alts:
            continue

        chunks: list[str] = []
        for k in range(0, len(segments), max_alts):
            group = segments[k:k + max_alts]
            group_str = ' | '.join(g.strip() for g in group)
            chunks.append(f'( {group_str} )')
        new_body = ' | '.join(chunks)
        if outer:
            new_body = f'( {new_body} ){trail}'
        else:
            new_body = f'( {new_body} )'

        # ``header_end`` is just after the `=`, and ``end-1`` is the position of
        # the terminating `;` (exclusive slice).  Keep the original `=` and `;`
        # in place and only replace the body text.
        replacements.append((d['header_end'], d['end'] - 1, f' {new_body}'))
        chunked.append(d['name'])

    if not replacements:
        return source, []

    replacements.sort(key=lambda x: x[0], reverse=True)
    result = source
    for start, end, repl in replacements:
        result = result[:start] + repl + result[end:]
    return result, chunked


def _mangle_name(base_name: str, flags_str: str) -> str:
    """
    Compute the pyjsgf-safe rule name by appending sorted fixed flag values.

    Supports both typed flags (``{number:enum=singular}``) and AVM blocks
    (``{gender:fem,number:sg}``).  Wildcards (``*``), variables (``?var``)
    and disjunctions (``a|b``) are ignored for mangling because they do not
    fix the rule to a single value.

    Returns *base_name* unchanged if *flags_str* is empty or has no fixed flags.
    """
    if not flags_str or not flags_str.strip():
        return base_name
    fixed = _canonical_fixed_flags(flags_str)
    if not fixed:
        return base_name
    suffix = '__'.join(f'{k}_{v}' for k, v in sorted(fixed))
    return f'{base_name}__{suffix}'


def _mangle_rule_header(base_name: str, flags_str: str, params_str: str) -> str:
    """
    Mangle a rule header, including typed parameter lists.

    Variable-only parameter lists (``[from, to]`` or ``(x, y)``) do not affect
    the mangled name, so they are dropped.  Typed parameter lists
    (``(OBJECT:{gender,number})`` or ``(INTENT, GENERIC_BUSINESS:{...})``) are
    hashed and appended as a synthetic ``__params_<hash>`` flag so that two
    declarations with the same base name and flags but different typed params
    become distinct pyjsgf rules.
    """
    s = params_str.strip()
    if s.startswith('[') and s.endswith(']'):
        s = s[1:-1].strip()
    elif s.startswith('(') and s.endswith(')'):
        s = s[1:-1].strip()
    # Typed params contain type annotations (':' or '{').
    if s and (':' in s or '{' in s):
        h = hashlib.md5(params_str.encode()).hexdigest()[:8]
        if flags_str and flags_str.strip():
            augmented = f'{flags_str} {{__params:{h}}}'
        else:
            augmented = f'{{__params:{h}}}'
        return _mangle_name(base_name, augmented)
    return _mangle_name(base_name, flags_str)


def _mangle_source(
    source: str,
) -> tuple[str, dict[str, str], dict[str, Position], dict[str, dict[str, str]], set[str]]:
    """
    Rewrite each rule declaration that carries LHS flags so that pyjsgf sees a
    unique, identifier-safe rule name.  References in rule bodies are resolved
    to the most specific matching variant.  A synthetic union rule is added
    only when a base name has multiple fixed variants and no wildcard variant.

    Returns:
        mangled_source      — source with declaration names replaced
        pyjsgf_to_original  — mangled_name → original_name
        pyjsgf_to_position  — mangled_name → Position of '<' in *source*
        pyjsgf_to_flags     — mangled_name → {flag_key: flag_value, ...} (raw values)
        union_names         — pyjsgf names of synthetic union rules
    """
    pyjsgf_to_original: dict[str, str] = {}
    pyjsgf_to_position: dict[str, Position] = {}
    pyjsgf_to_flags: dict[str, dict[str, str]] = {}
    original_public: set[str] = set()
    offsets = _line_offsets(source)

    # variant_map[base_name] -> list of variant descriptors
    variant_map: dict[str, list[dict]] = {}

    def _add_variant(
        base_name: str,
        mangled: str,
        flags_str: str,
        pub: bool,
        position: Position,
    ) -> None:
        flags_dict = _avm_flag_pairs(flags_str)
        # Same mangled name can come from duplicate declarations (e.g. two
        # variable-only variants).  Keep the first; pyjsgf will see one rule.
        if mangled not in pyjsgf_to_original:
            pyjsgf_to_original[mangled] = base_name
            pyjsgf_to_position[mangled] = position
            pyjsgf_to_flags[mangled] = flags_dict
            variant_map.setdefault(base_name, []).append({
                'mangled': mangled,
                'flags': flags_dict,
                'pub': pub,
            })

    def decl_replacer(m: re.Match) -> str:
        original = m.group('rulename')
        flags_str = m.group('flags')
        params_str = m.group('params') or ''
        mangled = _mangle_rule_header(original, flags_str, params_str)
        pub = bool(m.group('pub'))
        if pub:
            original_public.add(original)
        angle_offset = m.start('rulename') - 1  # position of '<'
        _add_variant(
            original, mangled, flags_str, pub,
            offset_to_position(angle_offset, offsets),
        )
        eq = m.group('eq')
        return f'{m.group("pub")}<{mangled}>{eq}'

    mangled_source = _LHS_DECL_RE.sub(decl_replacer, source)

    # Resolve *flagged body references*: <name[args]> {flags} in a rule body
    # should resolve to the most specific matching variant.  The inline flags
    # are consumed; call-site args are preserved so _strip_rule_ref_args can
    # record them later.
    _FLAGGED_REF_RE = re.compile(
        r'<(' + _RULE_NAME_CHARS + r')'     # base rule name
        r'(?P<args>\[[^\]]*\]|\([^)]*\))?'  # optional [args] or (args)
        r'>'
        r'(?P<flags>(?:\s*\{[^}]*\})+)'     # one or more flag blocks
        r'(?!\s*=)'                          # NOT followed by '=' (declaration)
    )

    def _flagged_ref_replacer(m: re.Match) -> str:
        ref_name = m.group(1)
        ref_flags_str = m.group('flags')
        ref_flags = _avm_flag_pairs(ref_flags_str)
        variants = variant_map.get(ref_name, [])
        target = _select_variant(ref_name, ref_flags, variants)
        if target:
            args = m.group('args') or ''
            return f'<{target}{args}>'
        # No matching variant: drop the inline flags and leave a bare reference.
        # A synthetic union or wildcard variant will resolve it.
        return f'<{ref_name}>'

    mangled_source = _FLAGGED_REF_RE.sub(_flagged_ref_replacer, mangled_source)

    # Post-pass: resolve bare (unflagged) body references to the best variant.
    _UNFLAGGED_REF_RE = re.compile(
        r'<(' + _RULE_NAME_CHARS + r')'
        r'(?P<args>\[[^\]]*\]|\([^)]*\))?'
        r'>(?!\s*(?:\{[^}]*\}\s*)*=)'
    )

    def _unflagged_ref_replacer(m: re.Match) -> str:
        ref_name = m.group(1)
        variants = variant_map.get(ref_name, [])
        target = _select_variant(ref_name, {}, variants)
        if target:
            args = m.group('args') or ''
            return f'<{target}{args}>'
        return m.group(0)

    mangled_source = _UNFLAGGED_REF_RE.sub(_unflagged_ref_replacer, mangled_source)

    # Build synthetic union rules only for base names that have multiple variants
    # and no wildcard variant (mangled == base, all flags unconstrained).
    union_names: set[str] = set()
    for orig, variants in sorted(variant_map.items()):
        if len(variants) <= 1:
            continue
        if any(v['mangled'] == orig and _avm_specificity(v['flags']) == 0 for v in variants):
            continue
        alts = ' | '.join(f'<{v["mangled"]}>' for v in variants)
        pub = 'public ' if any(v['pub'] for v in variants) else ''
        union_rule = f'{pub}<{orig}> = {alts};'
        mangled_source += f'\n{union_rule}'
        union_names.add(orig)
        if orig not in pyjsgf_to_original:
            pyjsgf_to_original[orig] = orig
            first_mangled = variants[0]['mangled']
            pyjsgf_to_position[orig] = pyjsgf_to_position[first_mangled]
            pyjsgf_to_flags[orig] = {}

    return mangled_source, pyjsgf_to_original, pyjsgf_to_position, pyjsgf_to_flags, union_names


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
    # LHS flags of the rule that contains each PLHDR token (empty for unflagged rules)
    placeholder_flags: dict[str, dict[str, str]] = field(default_factory=dict)
    # Rules whose body was split into smaller alternative groups to avoid recursion.
    chunked_rules: list[str] = field(default_factory=list)
    # mangled pyjsgf name → original rule name (for diagnostics / lookups).
    pyjsgf_to_original: dict[str, str] = field(default_factory=dict)

    # ------------------------------------------------------------------ #
    #  Construction                                                        #
    # ------------------------------------------------------------------ #

    @classmethod
    def parse(cls, path: Path, source: str) -> GrammarDocument:
        # Normalise the grammar declaration (empty grammar name, missing header,
        # angle-bracketed grammar name) so pyjsgf gets a valid header.
        source = _fix_grammar_declaration(source, path)

        # Mask comments for all regex passes.  Newlines are preserved so line/char
        # offsets stay aligned with the original source.
        work_source = _mask_comments(source)

        # Pre-pass: substitute <param> rule-ref syntax in parameterized rule bodies
        # with PARM_param tokens, scoped to each rule's declared param list.
        # This must run before scan_positions so param refs don't appear as rule refs.
        param_subst_source, param_placeholder_map = _substitute_param_refs(work_source)

        # Merge duplicate rule declarations (same name/params/flags) so pyjsgf
        # sees a single rule whose body is the disjunction of the originals.
        param_subst_source = _merge_duplicate_rule_declarations(param_subst_source)

        ref_positions = scan_positions(param_subst_source)
        def_positions = scan_rule_def_positions(param_subst_source)

        grammar_name = _extract_grammar_name(source)
        parse_error: Exception | None = None
        rules: list[RuleInfo] = []
        imports: list[ImportInfo] = []

        # Build params lookup from working source: base name → param list
        # (same params used across all flag variants of a rule)
        _PARAMS_SCAN_RE = re.compile(
            r'(?:public\s+)?<([A-Za-z0-9_.$&:\-#%+!~^]+)(\[[^\]]*\]|\([^)]*\))?>(?:\s*\{[^}]*\})*\s*='
        )
        _name_to_params: dict[str, list[str]] = {}
        for _pm in _PARAMS_SCAN_RE.finditer(work_source):
            _nm = _pm.group(1)
            if _nm not in _name_to_params:
                _name_to_params[_nm] = _parse_params(_pm.group(2) or '')

        # Strip nested rule-reference argument lists before mangling.  This makes
        # the LHS/AVM mangling regexes safe against call sites like
        # ``<permut2((...){...})>`` while recording the call-site args first.
        param_call_sites: dict[str, list] = {}
        param_subst_source = _strip_rule_ref_args(param_subst_source, param_call_sites)

        # Header-only or comment-only files contain no rule declarations after
        # masking.  Treat them as valid empty grammars.
        if not _LHS_DECL_RE.search(work_source) and not _find_rule_declarations(work_source):
            return cls(
                path=path,
                source=source,
                grammar_name=grammar_name or path.stem,
                rules=[],
                imports=[],
                parse_error=None,
                ref_positions=ref_positions,
                def_positions=def_positions,
                pyjsgf_grammar=None,
                pyjsgf_def_positions={},
                func_placeholders={},
                param_placeholder_map=param_placeholder_map,
                param_call_sites={},
                placeholder_flags={},
            )

        # Mangle rule names for LHS flag variants so pyjsgf sees unique names.
        # union_names holds synthetic union pyjsgf names; they live in the
        # pyjsgf grammar for ref resolution but are not exposed in doc.rules.
        mangled_source, pyjsgf_to_original, pyjsgf_to_pos, pyjsgf_to_flags, union_names = _mangle_source(param_subst_source)

        # pyjsgf_def_positions: unflagged rules keep name == pyjsgf_name,
        # flagged variants get their per-variant positions from _mangle_source
        pyjsgf_def_positions = dict(def_positions)
        pyjsgf_def_positions.update(pyjsgf_to_pos)

        pyjsgf_grammar = None

        # Collect side-effect maps during dialect-tag stripping
        func_placeholders: dict[str, tuple] = {}
        placeholder_flags: dict[str, dict[str, str]] = {}
        chunked_rules: list[str] = []

        try:
            from jsgf.parser import parse_grammar_string
            mangled_source = _split_wordforms(mangled_source)
            stripped = _strip_dialect_tags(
                mangled_source,
                func_map=func_placeholders,
                call_site_map=param_call_sites,
            )

            # Neutralise punctuation in rule-body literals (e.g. ``f.b.``) so
            # pyjsgf doesn't treat it as a token boundary, then chunk very long
            # alternative lists to avoid pyparsing recursion.
            stripped = _normalise_punctuation(stripped)
            stripped, chunked_rules = _chunk_long_alternatives(stripped, max_alts=_MAX_RULE_ALTERNATIVES)

            # Post-pass: associate each PLHDR token with the LHS flags of its
            # enclosing rule (only for flagged variants; unflagged rules get no entry).
            if pyjsgf_to_flags:
                _RULE_BODY_RE = re.compile(r'<([A-Za-z0-9_.$&:\-#%+!~^]+)>\s*=([^;]+);')
                for _rm in _RULE_BODY_RE.finditer(stripped):
                    _rpn = _rm.group(1)
                    if _rpn not in pyjsgf_to_flags:
                        continue
                    _rflags = pyjsgf_to_flags[_rpn]
                    if not _rflags:
                        continue
                    for _pm in re.finditer(r'\bplhdr\d+\b', _rm.group(2).lower()):
                        placeholder_flags[_pm.group().upper()] = _rflags

            g = parse_grammar_string(stripped)
            grammar_name = g.name
            pyjsgf_grammar = g
            for rule in g.rules:
                original_name = pyjsgf_to_original.get(rule.name, rule.name)
                # Skip synthetic union rules added by _mangle_source; they are
                # only needed to resolve bare refs in the pyjsgf grammar.
                if rule.name in union_names:
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
            rules, imports = _resilient_parse(work_source, def_positions)

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
            placeholder_flags=placeholder_flags,
            chunked_rules=chunked_rules,
            pyjsgf_to_original=pyjsgf_to_original,
        )

    # ------------------------------------------------------------------ #
    #  Diagnostics                                                         #
    # ------------------------------------------------------------------ #

    def get_diagnostics(self, index: GrammarIndex) -> list[lsp.Diagnostic]:
        diags: list[lsp.Diagnostic] = []
        offsets = _line_offsets(self.source)

        # Report parse error
        if self.parse_error is not None:
            diags.append(lsp.Diagnostic(
                range=_parse_error_range(self.parse_error),
                message=f"Parse error: {self.parse_error}",
                severity=lsp.DiagnosticSeverity.Error,
                source='jsgf-lsp',
            ))

        # Flag parenthesized rule-name templates / generator macros, which are not
        # supported by pyjsgf (e.g. ``public (<a> <b>){...} =``).
        for m in _PAREN_LHS_RE.finditer(_mask_comments(self.source)):
            pos = offset_to_position(m.start(), offsets)
            diags.append(lsp.Diagnostic(
                range=_pos_to_range(pos, m.end() - m.start()),
                message=(
                    "Parenthesized rule-name template / generator macro is not "
                    "supported by pyjsgf; use a normal <ruleName> declaration"
                ),
                severity=lsp.DiagnosticSeverity.Error,
                source='jsgf-lsp',
            ))

        # Warn about punctuation in rule-body literals that was ignored by the parser.
        for offset, ch in _find_punctuation_warnings(_mask_comments(self.source)):
            pos = offset_to_position(offset, offsets)
            diags.append(lsp.Diagnostic(
                range=_pos_to_range(pos, 1),
                message=f"Punctuation '{ch}' in rule body was ignored by the parser",
                severity=lsp.DiagnosticSeverity.Warning,
                source='jsgf-lsp',
            ))

        # Warn about rules that were chunked to avoid parser recursion.
        for name in self.chunked_rules:
            pos = self.pyjsgf_def_positions.get(name, Position(0, 0))
            original = self.pyjsgf_to_original.get(name, name)
            diags.append(lsp.Diagnostic(
                range=_pos_to_range(pos, len(original)),
                message=(
                    f"Rule <{original}> has many alternatives and was split into "
                    f"smaller groups (chunk size {_MAX_RULE_ALTERNATIVES}); "
                    "consider refactoring for efficiency"
                ),
                severity=lsp.DiagnosticSeverity.Warning,
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
        seen: set[str] = set()
        names: list[str] = []
        for r in self.rules:
            if r.name not in seen:
                seen.add(r.name)
                names.append(r.name)
        return names

    def get_rule(self, name: str) -> RuleInfo | None:
        # Prefer an exact pyjsgf_name match first; this lets a public synthetic
        # union rule shadow its per-variant aliases when looked up by the
        # original name, while still allowing per-variant lookup by mangled name.
        for r in self.rules:
            if r.pyjsgf_name == name:
                return r
        for r in self.rules:
            if r.name == name:
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

    # Find rule definitions: optional 'public' <name[params]/(params)> [lhs-flags] = ... ;
    for m in re.finditer(
        r'(public\s+)?<(?P<name>' + _RULE_NAME_CHARS + r')(?P<params>\[[^\]]*\]|\([^)]*\))?>'
        r'(?P<flags>(?:\s*\{[^}]*\})*)\s*=(?P<body>[^;]+);',
        source, re.DOTALL
    ):
        visible = bool(m.group(1))
        name = m.group('name')
        params_str = m.group('params') or ''
        flags_str = m.group('flags') or ''
        body = m.group('body').strip()
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
