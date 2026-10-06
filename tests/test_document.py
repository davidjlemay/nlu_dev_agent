"""Tests for core/document.py — GrammarDocument parsing."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.document import GrammarDocument, _mangle_name, _mangle_source, _parse_params, _strip_dialect_tags, _substitute_param_refs
from core.index import GrammarIndex
from core.dialect import DialectRegistry

FIXTURES = Path(__file__).parent / 'fixtures'


def _make_index(*gram_files: Path) -> GrammarIndex:
    """Build an index from a list of fixture files."""
    dialect = DialectRegistry.standard()
    index = GrammarIndex(FIXTURES, dialect)
    for path in gram_files:
        index.update_file(path, path.read_text())
    return index


def test_parse_valid_grammar():
    path = FIXTURES / 'shared.jsgf'
    doc = GrammarDocument.parse(path, path.read_text())
    assert doc.parse_error is None
    assert doc.grammar_name == 'com.example.shared'
    names = doc.rule_names()
    assert 'cardinal' in names
    assert 'amount' in names


def test_parse_detects_rule_visibility():
    path = FIXTURES / 'shared.jsgf'
    doc = GrammarDocument.parse(path, path.read_text())
    for rule in doc.rules:
        assert rule.visible is True  # all rules in shared.jsgf are public


def test_parse_with_imports():
    path = FIXTURES / 'greeting.jsgf'
    doc = GrammarDocument.parse(path, path.read_text())
    assert doc.parse_error is None
    assert len(doc.imports) == 1
    imp = doc.imports[0]
    assert imp.grammar_name == 'com.example.shared'
    assert imp.wildcard is True


def test_diagnostics_no_errors_valid_workspace():
    shared = FIXTURES / 'shared.jsgf'
    greeting = FIXTURES / 'greeting.jsgf'
    index = _make_index(shared, greeting)
    doc = index._documents[greeting]
    diags = doc.get_diagnostics(index)
    # Should have no errors (import resolved, rules defined)
    errors = [d for d in diags if d.severity.value == 1]
    assert errors == [], f"Unexpected errors: {[d.message for d in errors]}"


def test_diagnostics_undefined_rule():
    source = """\
#JSGF V1.0;
grammar test;
public <broken> = <undefinedRule>;
"""
    path = Path('/tmp/test_broken.jsgf')
    dialect = DialectRegistry.standard()
    index = GrammarIndex(Path('/tmp'), dialect)
    doc = index.update_file(path, source)
    doc = index._documents[path]
    diags = doc.get_diagnostics(index)
    errors = [d for d in diags if 'Undefined rule' in d.message]
    assert len(errors) == 1
    assert 'undefinedRule' in errors[0].message


def test_resilient_parse_on_broken_grammar():
    path = FIXTURES / 'broken.jsgf'
    doc = GrammarDocument.parse(path, path.read_text())
    # Should have a parse error but still recover rule names
    assert doc.parse_error is not None
    names = doc.rule_names()
    # Resilient tokeniser should find at least 'valid_rule'
    assert 'valid_rule' in names


def test_lhs_flag_parse_succeeds():
    source = """\
#JSGF V1.0;
grammar test;
public <item_singular> {number:enum=singular} = book | pen;
public <item_plural>   {number:enum=plural}   = books | pens;
"""
    path = FIXTURES / 'agreement.jsgf'
    doc = GrammarDocument.parse(path, path.read_text())
    assert doc.parse_error is None
    assert 'item_singular' in doc.rule_names()
    assert 'item_plural' in doc.rule_names()


def test_lhs_flag_does_not_confuse_def_positions():
    """Rule def positions should point at '<', not at the flag block."""
    source = """\
#JSGF V1.0;
grammar test;
public <item> {number:enum=singular} = book;
"""
    from pathlib import Path as _Path
    doc = GrammarDocument.parse(_Path('/tmp/t.jsgf'), source)
    assert doc.parse_error is None
    pos = doc.def_positions.get('item')
    assert pos is not None
    # The '<' of <item> is on line 2 (0-indexed)
    assert pos.line == 2


def test_lhs_flag_not_in_rule_body():
    """Rule body source from resilient parser should not contain the LHS flag."""
    source = """\
#JSGF V1.0;
grammar test;
public <item> {number:enum=singular} = book | pen;
"""
    from pathlib import Path as _Path
    doc = GrammarDocument.parse(_Path('/tmp/t.jsgf'), source)
    assert doc.parse_error is None
    rule = doc.get_rule('item')
    assert rule is not None
    # body_source is None when pyjsgf parsed successfully (grammar_object set)
    # verify the pyjsgf parse worked (LHS flag didn't break it)
    assert rule.grammar_object is not None


# ------------------------------------------------------------------ #
#  Rule name mangling                                                  #
# ------------------------------------------------------------------ #

def test_mangle_name_single_flag():
    assert _mangle_name('noun', '{number:enum=singular}') == 'noun__number_singular'


def test_mangle_name_no_flags():
    assert _mangle_name('bare', '') == 'bare'


def test_mangle_name_multi_flag_sorted():
    # Keys must be sorted lexicographically: a < b
    result = _mangle_name('x', '{b:bool=true} {a:enum=masc}')
    assert result == 'x__a_masc__b_true'


def test_mangle_source_rewrites_declaration_not_body():
    source = """\
#JSGF V1.0;
grammar test;
public <noun> {number:enum=singular} = book;
public <sentence> = <noun>;
"""
    mangled, pyjsgf_to_orig, _, _, _ = _mangle_source(source)
    # Declaration is rewritten
    assert '<noun__number_singular>' in mangled
    # Body reference to <noun> in <sentence> IS rewritten (unambiguous: one variant)
    assert '<noun__number_singular>' in mangled.split('<sentence>')[1]
    # Mapping populated correctly
    assert pyjsgf_to_orig.get('noun__number_singular') == 'noun'


def test_mangle_source_ambiguous_reference_not_rewritten():
    """When a rule has multiple flagged variants, body references stay unchanged."""
    source = """\
#JSGF V1.0;
grammar test;
public <noun> {number:enum=singular} = book;
public <noun> {number:enum=plural} = books;
public <sentence> = <noun>;
"""
    mangled, pyjsgf_to_orig, _, _, _ = _mangle_source(source)
    assert '<noun__number_singular>' in mangled
    assert '<noun__number_plural>' in mangled
    # Body reference is ambiguous (two variants) — NOT rewritten
    body = mangled.split('<sentence>')[1]
    assert '<noun>' in body


def test_mangle_source_flagged_body_reference():
    """Flagged body references like <noun> {number:enum=singular} resolve to the mangled name."""
    source = """\
#JSGF V1.0;
grammar test;
<noun> {number:enum=singular} = book;
<noun> {number:enum=plural}   = books;
public <sentence> = I read <noun> {number:enum=plural};
"""
    mangled, pyjsgf_to_orig, _, _, _ = _mangle_source(source)
    # The flagged reference should resolve to the plural variant
    body = mangled.split('<sentence>')[1]
    assert '<noun__number_plural>' in body
    # The inline flags should be consumed (not left in source)
    assert '{number:enum=plural}' not in body.split('=', 1)[1]


def test_mangle_source_flagged_ref_unknown_variant_ambiguous():
    """Flagged body reference to a non-existent variant stays as bare name
    (resolved by synthetic union) when the base name is ambiguous."""
    source = """\
#JSGF V1.0;
grammar test;
<noun> {number:enum=singular} = book;
<noun> {number:enum=plural}   = books;
public <sentence> = I read <noun> {number:enum=dual};
"""
    mangled, _, _, _, _ = _mangle_source(source)
    body = mangled.split('<sentence>')[1]
    # 'dual' variant doesn't exist — flagged ref pass leaves it unchanged,
    # bare <noun> resolves to synthetic union of singular|plural
    assert '<noun>' in body


def test_same_name_variants_parse_successfully():
    path = FIXTURES / 'noun_variants.jsgf'
    doc = GrammarDocument.parse(path, path.read_text())
    assert doc.parse_error is None


def test_same_name_variants_pyjsgf_names():
    path = FIXTURES / 'noun_variants.jsgf'
    doc = GrammarDocument.parse(path, path.read_text())
    pyjsgf_names = [r.pyjsgf_name for r in doc.rules]
    assert 'noun__number_singular' in pyjsgf_names
    assert 'noun__number_plural' in pyjsgf_names


def test_same_name_variants_original_names_preserved():
    path = FIXTURES / 'noun_variants.jsgf'
    doc = GrammarDocument.parse(path, path.read_text())
    for rule in doc.rules:
        assert rule.name == 'noun'


def test_same_name_variants_no_duplicate_diagnostic():
    dialect = DialectRegistry.standard()
    index = GrammarIndex(FIXTURES, dialect)
    path = FIXTURES / 'noun_variants.jsgf'
    index.update_file(path, path.read_text())
    doc = index._documents[path]
    diags = doc.get_diagnostics(index)
    dup_diags = [d for d in diags if 'Duplicate' in d.message]
    assert dup_diags == []


def test_duplicate_rule_declarations_merged():
    """Duplicate rule declarations are merged into a single rule with alternatives."""
    source = """\
#JSGF V1.0;
grammar test;
public <noun> {number:enum=singular} = book;
public <noun> {number:enum=singular} = cat;
"""
    dialect = DialectRegistry.standard()
    index = GrammarIndex(Path('/tmp'), dialect)
    path = Path('/tmp/dup_test.jsgf')
    index.update_file(path, source)
    doc = index._documents[path]
    diags = doc.get_diagnostics(index)
    dup_diags = [d for d in diags if 'Duplicate' in d.message]
    assert dup_diags == []
    rule = doc.get_rule('noun')
    assert rule is not None
    assert rule.grammar_object is not None
    assert rule.grammar_object.matches('book')
    assert rule.grammar_object.matches('cat')


def test_pyjsgf_def_positions_per_variant():
    path = FIXTURES / 'noun_variants.jsgf'
    doc = GrammarDocument.parse(path, path.read_text())
    pos_singular = doc.pyjsgf_def_positions.get('noun__number_singular')
    pos_plural = doc.pyjsgf_def_positions.get('noun__number_plural')
    assert pos_singular is not None
    assert pos_plural is not None
    assert pos_singular.line != pos_plural.line


def test_get_rule_by_pyjsgf_name():
    path = FIXTURES / 'noun_variants.jsgf'
    doc = GrammarDocument.parse(path, path.read_text())
    rule = doc.get_rule('noun__number_plural')
    assert rule is not None
    assert rule.name == 'noun'
    assert rule.pyjsgf_name == 'noun__number_plural'


def test_resilient_parse_sets_pyjsgf_name():
    """When pyjsgf fails, the resilient path should still set pyjsgf_name."""
    source = """\
#JSGF V1.0;
grammar test;
public <item> {number:enum=singular} = book | pen;
INVALID JSGF SYNTAX !!!
"""
    doc = GrammarDocument.parse(Path('/tmp/resilient_pyjsgf_name.jsgf'), source)
    # Resilient parse was used (source has invalid syntax after the rule)
    rule = doc.get_rule('item')
    assert rule is not None
    assert rule.pyjsgf_name == 'item__number_singular'


# ------------------------------------------------------------------ #
#  Custom functions + LHS flags                                        #
# ------------------------------------------------------------------ #

def test_function_body_with_lhs_flag_parses_ok():
    """Rule with LHS flag whose body uses a dialect function parses without error."""
    source = """\
#JSGF V1.0;
grammar test;
public <price> {currency:enum=usd} = $normalise(<cardinal>, 'USD');
public <cardinal> = one | two | three;
"""
    doc = GrammarDocument.parse(Path('/tmp/func_lhs.jsgf'), source)
    assert doc.parse_error is None
    rule = doc.get_rule('price')
    assert rule is not None
    assert rule.pyjsgf_name == 'price__currency_usd'


def test_flagged_ref_to_function_bodied_rule():
    """Flagged body reference to a function-bodied rule resolves to mangled name."""
    source = """\
#JSGF V1.0;
grammar test;
<cost> {currency:enum=usd} = $normalise(<cardinal>, 'USD');
<cost> {currency:enum=gbp} = $normalise(<cardinal>, 'GBP');
public <cardinal> = one | two | three;
public <buy> = pay <cost> {currency:enum=usd};
"""
    mangled, pyjsgf_to_orig, _, _, _ = _mangle_source(source)
    body = mangled.split('<buy>')[1]
    assert '<cost__currency_usd>' in body


# ------------------------------------------------------------------ #
#  Parameterized rules                                                 #
# ------------------------------------------------------------------ #

def test_parse_params_basic():
    assert _parse_params('[$from, $to]') == ['from', 'to']


def test_parse_params_empty():
    assert _parse_params('') == []
    assert _parse_params('[]') == []


def test_parse_params_single():
    assert _parse_params('[$x]') == ['x']


def test_parameterized_decl_strips_params_for_pyjsgf():
    """Unflagged parameterized declaration: pyjsgf sees plain <name>, no parse error."""
    source = """\
#JSGF V1.0;
grammar test;
public <date_range[start, end]> = from <start> to <end>;
"""
    doc = GrammarDocument.parse(Path('/tmp/param_strip.jsgf'), source)
    assert doc.parse_error is None
    assert 'date_range' in doc.rule_names()


def test_parameterized_with_lhs_flag_mangles_name():
    """Parameterized decl with LHS flag: pyjsgf name is mangled, params dropped."""
    source = """\
#JSGF V1.0;
grammar test;
public <transfer[from, to]> {currency:enum=usd} = transfer <from> to <to> in dollars;
"""
    doc = GrammarDocument.parse(Path('/tmp/param_mangle.jsgf'), source)
    assert doc.parse_error is None
    rule = doc.get_rule('transfer')
    assert rule is not None
    assert rule.pyjsgf_name == 'transfer__currency_usd'
    # mangled source should NOT contain [from, to]
    mangled, _, _, _, _ = _mangle_source(source)
    assert '[from, to]' not in mangled


def test_parameterized_flagged_ref_resolves():
    """Parameterized call site with flags resolves to the mangled name."""
    source = """\
#JSGF V1.0;
grammar test;
public <transfer[from, to]> {currency:enum=usd} = transfer <from> to <to>;
public <savings> = savings account;
public <chequing> = chequing account;
public <my_transfer> = <transfer[<savings>, <chequing>]> {currency:enum=usd};
"""
    doc = GrammarDocument.parse(Path('/tmp/param_ref.jsgf'), source)
    assert doc.parse_error is None
    mangled, _, _, _, _ = _mangle_source(source)
    body = mangled.split('<my_transfer>')[1]
    assert '<transfer__currency_usd' in body


def test_parameterized_unflagged_call_site_strips_args():
    """Unflagged parameterized call site: _strip_dialect_tags drops [args]."""
    source = """\
#JSGF V1.0;
grammar test;
public <date_range[start, end]> = from <start> to <end>;
public <departure> = departure date;
public <return> = return date;
public <booking> = <date_range[<departure>, <return>]>;
"""
    doc = GrammarDocument.parse(Path('/tmp/param_unflagged.jsgf'), source)
    assert doc.parse_error is None
    assert 'booking' in doc.rule_names()


def test_param_ref_in_body_becomes_parm_token():
    """<param> rule-ref syntax in parameterized rule body is substituted to PARM_ token."""
    source = """\
#JSGF V1.0;
grammar test;
public <date_range[start, end]> = from <start> to <end>;
"""
    subst, pmap = _substitute_param_refs(source)
    assert '<start>' not in subst
    assert '<end>' not in subst
    assert 'PARM_start' in subst
    assert 'PARM_end' in subst
    assert pmap == {'PARM_start': 'start', 'PARM_end': 'end'}


def test_parameterized_fixture_parses_ok():
    """The parameterized.jsgf fixture should parse without error."""
    path = FIXTURES / 'parameterized.jsgf'
    doc = GrammarDocument.parse(path, path.read_text())
    assert doc.parse_error is None, f"Parse error: {doc.parse_error}"
    names = doc.rule_names()
    assert 'transfer' in names
    assert 'date_range' in names
    assert 'my_transfer' in names
    assert 'booking' in names


def test_parameterized_rule_params_populated():
    """RuleInfo.params is populated for parameterized rules."""
    source = """\
#JSGF V1.0;
grammar test;
public <transfer[from, to]> {currency:enum=usd} = transfer <from> to <to>;
"""
    doc = GrammarDocument.parse(Path('/tmp/param_params.jsgf'), source)
    rule = doc.get_rule('transfer')
    assert rule is not None
    assert rule.params == ['from', 'to']


def test_resilient_parse_parameterized_rule():
    """Resilient parser recognises parameterized rule declarations."""
    source = """\
#JSGF V1.0;
grammar test;
public <transfer[from, to]> {currency:enum=usd} = transfer <from> to <to>;
INVALID SYNTAX !!!
"""
    doc = GrammarDocument.parse(Path('/tmp/param_resilient.jsgf'), source)
    # Should have fallen back to resilient parse
    assert doc.parse_error is not None
    rule = doc.get_rule('transfer')
    assert rule is not None
    assert rule.pyjsgf_name == 'transfer__currency_usd'
    assert rule.params == ['from', 'to']


# ------------------------------------------------------------------ #
#  Indexed placeholder maps (lazy loading)                             #
# ------------------------------------------------------------------ #

def test_func_placeholders_populated():
    """GrammarDocument.func_placeholders maps PLHDR0 → ('lookup', ['bank_names'])."""
    source = """\
#JSGF V1.0;
grammar test;
public <check_balance> = balance of $lookup('bank_names');
"""
    doc = GrammarDocument.parse(Path('/tmp/func_plhdr.jsgf'), source)
    assert doc.parse_error is None
    assert len(doc.func_placeholders) == 1
    token, info = next(iter(doc.func_placeholders.items()))
    assert token.startswith('PLHDR')
    fn_name, fn_args = info
    assert fn_name == 'lookup'
    assert fn_args == ['bank_names']


def test_func_placeholders_indexed():
    """Multiple $func() calls get distinct PLHDR<n> tokens."""
    source = """\
#JSGF V1.0;
grammar test;
public <transfer> = from $lookup('banks') to $lookup('banks');
"""
    doc = GrammarDocument.parse(Path('/tmp/multi_plhdr.jsgf'), source)
    assert doc.parse_error is None
    assert len(doc.func_placeholders) == 2
    tokens = set(doc.func_placeholders.keys())
    assert 'PLHDR0' in tokens
    assert 'PLHDR1' in tokens


def test_param_call_sites_populated():
    """GrammarDocument.param_call_sites records call-site args for parameterized rules."""
    source = """\
#JSGF V1.0;
grammar test;
public <transfer[from, to]> = transfer <from> to <to>;
public <savings> = savings;
public <chequing> = chequing;
public <my_transfer> = <transfer[<savings>, <chequing>]>;
"""
    doc = GrammarDocument.parse(Path('/tmp/call_sites.jsgf'), source)
    assert doc.parse_error is None
    sites = doc.param_call_sites.get('transfer', [])
    assert len(sites) >= 1
    first_args = sites[0]
    assert len(first_args) == 2
    assert '<savings>' in first_args[0]
    assert '<chequing>' in first_args[1]


def test_strip_dialect_tags_with_maps():
    """_strip_dialect_tags populates func_map for both explicit and shorthand lookups."""
    source = "$start and $lookup('banks')"
    func_map: dict = {}
    stripped = _strip_dialect_tags(source, func_map=func_map)
    # Both $start (shorthand) and $lookup('banks') (explicit) become PLHDR tokens
    assert '$start' not in stripped
    assert '$lookup' not in stripped
    assert len(func_map) == 2
    # All entries are lookup functions
    for fn_name, fn_args in func_map.values():
        assert fn_name == 'lookup'
    # Shorthand $start → lookup 'start'
    shorthand_entry = [v for v in func_map.values() if v[1] == ['start']]
    assert len(shorthand_entry) == 1
    # Explicit $lookup('banks') → lookup 'banks'
    explicit_entry = [v for v in func_map.values() if v[1] == ['banks']]
    assert len(explicit_entry) == 1


# ------------------------------------------------------------------ #
#  placeholder_flags — flag context for lookup placeholders           #
# ------------------------------------------------------------------ #

def test_placeholder_flags_populated_for_flagged_rules():
    """Each PLHDR in a flagged rule body gets the rule's LHS flags."""
    fixture = FIXTURES / 'flagged_lookup.jsgf'
    doc = GrammarDocument.parse(fixture, fixture.read_text())
    assert doc.parse_error is None
    # Two variants: PLHDR0 in ca rule, PLHDR1 in us rule
    assert doc.placeholder_flags.get('PLHDR0') == {'region': 'ca'}
    assert doc.placeholder_flags.get('PLHDR1') == {'region': 'us'}


def test_placeholder_flags_empty_for_unflagged_rule():
    """An unflagged rule using $lookup() has no entry in placeholder_flags."""
    source = (
        '#JSGF V1.0;\n'
        'grammar test;\n'
        "public <item> = $lookup('things');\n"
    )
    doc = GrammarDocument.parse(Path('test.jsgf'), source)
    # PLHDR0 exists in func_placeholders but not in placeholder_flags
    assert 'PLHDR0' in doc.func_placeholders
    assert 'PLHDR0' not in doc.placeholder_flags


def test_mangle_source_returns_pyjsgf_to_flags():
    """_mangle_source now returns a 4-tuple including raw flag dicts."""
    source = (
        '#JSGF V1.0;\ngrammar t;\n'
        'public <noun> {number:enum=singular} = book;\n'
        'public <noun> {number:enum=plural} = books;\n'
    )
    _, _, _, pyjsgf_to_flags, _ = _mangle_source(source)
    assert pyjsgf_to_flags.get('noun__number_singular') == {'number': 'singular'}
    assert pyjsgf_to_flags.get('noun__number_plural') == {'number': 'plural'}


# ------------------------------------------------------------------ #
#  _substitute_param_refs and $shorthand                              #
# ------------------------------------------------------------------ #

def test_substitute_param_refs_basic():
    """<param> refs in parameterized rule body are replaced with PARM_ tokens."""
    source = (
        '#JSGF V1.0;\ngrammar test;\n'
        'public <transfer[from, to]> = transfer <from> to <to>;\n'
    )
    subst, pmap = _substitute_param_refs(source)
    assert '<from>' not in subst
    assert '<to>' not in subst
    assert 'PARM_from' in subst
    assert 'PARM_to' in subst
    assert pmap == {'PARM_from': 'from', 'PARM_to': 'to'}


def test_substitute_param_refs_scoped():
    """<from> in a non-parameterized rule is NOT substituted."""
    source = (
        '#JSGF V1.0;\ngrammar test;\n'
        'public <transfer[from, to]> = transfer <from> to <to>;\n'
        'public <other> = go <from> here;\n'  # 'from' is a real rule ref here
    )
    subst, _ = _substitute_param_refs(source)
    # Inside the parameterized rule: substituted
    transfer_body = subst.split('= transfer')[1].split(';')[0]
    assert 'PARM_from' in transfer_body
    # In the other rule: NOT substituted
    other_body = subst.split('<other>')[1].split(';')[0]
    assert '<from>' in other_body


def test_substitute_param_refs_returns_map():
    """Returned map covers all params across all parameterized rules."""
    source = (
        '#JSGF V1.0;\ngrammar test;\n'
        'public <f[x, y]> = <x> and <y>;\n'
        'public <g[a]> = go <a>;\n'
    )
    _, pmap = _substitute_param_refs(source)
    assert set(pmap.keys()) == {'PARM_x', 'PARM_y', 'PARM_a'}


def test_param_ref_not_in_ref_positions():
    """After parse, declared param names do not appear in ref_positions."""
    source = (
        '#JSGF V1.0;\ngrammar test;\n'
        'public <transfer[from, to]> = transfer <from> to <to>;\n'
    )
    doc = GrammarDocument.parse(Path('/tmp/param_ref_pos.jsgf'), source)
    assert 'from' not in doc.ref_positions
    assert 'to' not in doc.ref_positions


def test_shorthand_produces_plhdr():
    """Bare $identifier in rule body is treated as a lookup shorthand."""
    source = (
        '#JSGF V1.0;\ngrammar test;\n'
        'public <check_balance> = balance of $bank_names;\n'
    )
    doc = GrammarDocument.parse(Path('/tmp/shorthand.jsgf'), source)
    assert doc.parse_error is None
    assert len(doc.func_placeholders) == 1
    fn_name, fn_args = next(iter(doc.func_placeholders.values()))
    assert fn_name == 'lookup'
    assert fn_args == ['bank_names']


def test_shorthand_and_explicit_lookup_coexist():
    """$banks shorthand and $lookup('banks') produce equivalent PLHDR entries."""
    source_shorthand = (
        '#JSGF V1.0;\ngrammar test;\n'
        'public <r> = $banks;\n'
    )
    source_explicit = (
        '#JSGF V1.0;\ngrammar test;\n'
        "public <r> = $lookup('banks');\n"
    )
    doc_s = GrammarDocument.parse(Path('/tmp/sh.jsgf'), source_shorthand)
    doc_e = GrammarDocument.parse(Path('/tmp/ex.jsgf'), source_explicit)
    assert doc_s.parse_error is None
    assert doc_e.parse_error is None
    fn_s = next(iter(doc_s.func_placeholders.values()))
    fn_e = next(iter(doc_e.func_placeholders.values()))
    assert fn_s == fn_e  # ('lookup', ['banks']) in both cases


# ------------------------------------------------------------------ #
#  AVM variables and wildcards (Cerence long-distance agreement)     #
# ------------------------------------------------------------------ #

def test_avm_variable_ignored_for_mangling():
    """A rule with a ?-prefixed variable should keep its base pyjsgf name."""
    source = """\
#JSGF V1.0;
grammar test;
public <noun> {number:?n} = book | books;
"""
    doc = GrammarDocument.parse(Path('/tmp/var_mangle.jsgf'), source)
    assert doc.parse_error is None
    rule = doc.get_rule('noun')
    assert rule is not None
    assert rule.pyjsgf_name == 'noun'


def test_avm_wildcard_ignored_for_mangling():
    """A rule with a * wildcard should keep its base pyjsgf name."""
    source = """\
#JSGF V1.0;
grammar test;
public <noun> {number:*} = book | books;
"""
    doc = GrammarDocument.parse(Path('/tmp/wild_mangle.jsgf'), source)
    assert doc.parse_error is None
    rule = doc.get_rule('noun')
    assert rule is not None
    assert rule.pyjsgf_name == 'noun'


def test_avm_disjunction_ignored_for_mangling():
    """A rule with a disjunctive value should keep its base pyjsgf name."""
    source = """\
#JSGF V1.0;
grammar test;
public <noun> {number:plural|singular} = book | books;
"""
    doc = GrammarDocument.parse(Path('/tmp/disj_mangle.jsgf'), source)
    assert doc.parse_error is None
    rule = doc.get_rule('noun')
    assert rule is not None
    assert rule.pyjsgf_name == 'noun'


def test_avm_variable_reference_resolves_to_wildcard_variant():
    """A fixed reference to a variable-only rule resolves to the base rule."""
    source = """\
#JSGF V1.0;
grammar test;
public <noun> {number:?n} = book | books;
public <phrase> = <noun> {number:plural};
"""
    mangled, _, _, _, _ = _mangle_source(source)
    body = mangled.split('<phrase>')[1]
    assert '<noun>' in body
    assert '{number:' not in body


def test_avm_fixed_reference_prefers_exact_variant():
    """A fixed reference prefers the exact matching variant over a wildcard."""
    source = """\
#JSGF V1.0;
grammar test;
public <noun> {number:?n} = book | books;
public <noun> {number:plural} = books;
public <phrase> = <noun> {number:plural};
"""
    mangled, _, _, _, _ = _mangle_source(source)
    body = mangled.split('<phrase>')[1]
    assert '<noun__number_plural>' in body


def test_avm_variable_only_duplicates_merged():
    """Two declarations that differ only by variable name are merged."""
    source = """\
#JSGF V1.0;
grammar test;
public <noun> {number:?n} = book;
public <noun> {number:?m} = books;
"""
    doc = GrammarDocument.parse(Path('/tmp/var_merge.jsgf'), source)
    assert doc.parse_error is None
    rule = doc.get_rule('noun')
    assert rule is not None
    assert rule.grammar_object.matches('book')
    assert rule.grammar_object.matches('books')


# ------------------------------------------------------------------ #
#  Cerence dialect lexing                                            #
# ------------------------------------------------------------------ #

def test_cerence_elision_marker_stripped():
    """The % elision marker is removed before pyjsgf sees the source."""
    source = """\
#JSGF V1.0;
grammar test;
public <a> = test%me;
"""
    doc = GrammarDocument.parse(Path('/tmp/elision.jsgf'), source)
    assert doc.parse_error is None
    rule = doc.get_rule('a')
    assert rule is not None
    assert rule.grammar_object.matches('testme')


def test_cerence_pragma_lines_stripped():
    """Non-JSGF #pragma lines are ignored."""
    source = """\
#JSGF V1.0;
grammar test;
#ALLOW-NULL
#USE something
public <a> = test;
"""
    doc = GrammarDocument.parse(Path('/tmp/pragma.jsgf'), source)
    assert doc.parse_error is None


def test_cerence_weights_stripped():
    """Probability weights like /1/ or /0.5/ are removed."""
    source = """\
#JSGF V1.0;
grammar test;
public <b> = one /1/ | two /2.0/;
"""
    doc = GrammarDocument.parse(Path('/tmp/weights.jsgf'), source)
    assert doc.parse_error is None
    rule = doc.get_rule('b')
    assert rule is not None
    assert rule.grammar_object.matches('one')
    assert rule.grammar_object.matches('two')


def test_cerence_parameterized_rule_parens():
    """Parameter lists may use parentheses as well as brackets."""
    source = """\
#JSGF V1.0;
grammar test;
public <c(from, to)> = from <from> to <to>;
"""
    doc = GrammarDocument.parse(Path('/tmp/paren_params.jsgf'), source)
    assert doc.parse_error is None
    rule = doc.get_rule('c')
    assert rule is not None
    assert rule.params == ['from', 'to']


def test_cerence_parameterized_rule_typed_parens():
    """Parenthesised parameters may carry type/feature annotations."""
    source = """\
#JSGF V1.0;
grammar test;
public <transfer(OBJECT:{gender,number})> = transfer <OBJECT>;
"""
    doc = GrammarDocument.parse(Path('/tmp/typed_paren_params.jsgf'), source)
    assert doc.parse_error is None
    rule = doc.get_rule('transfer')
    assert rule is not None
    assert rule.params == ['OBJECT']


def test_duplicate_unflagged_rules_merged():
    """Duplicate unflagged declarations are merged into one rule."""
    source = """\
#JSGF V1.0;
grammar test;
public <d> = hi;
public <d> = hello;
"""
    doc = GrammarDocument.parse(Path('/tmp/dup_unflag.jsgf'), source)
    assert doc.parse_error is None
    rule = doc.get_rule('d')
    assert rule is not None
    assert rule.grammar_object.matches('hi')
    assert rule.grammar_object.matches('hello')

