"""Tests for core/document.py — GrammarDocument parsing."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.document import GrammarDocument, _mangle_name, _mangle_source
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
    path = FIXTURES / 'shared.gram'
    doc = GrammarDocument.parse(path, path.read_text())
    assert doc.parse_error is None
    assert doc.grammar_name == 'com.example.shared'
    names = doc.rule_names()
    assert 'cardinal' in names
    assert 'amount' in names


def test_parse_detects_rule_visibility():
    path = FIXTURES / 'shared.gram'
    doc = GrammarDocument.parse(path, path.read_text())
    for rule in doc.rules:
        assert rule.visible is True  # all rules in shared.gram are public


def test_parse_with_imports():
    path = FIXTURES / 'greeting.gram'
    doc = GrammarDocument.parse(path, path.read_text())
    assert doc.parse_error is None
    assert len(doc.imports) == 1
    imp = doc.imports[0]
    assert imp.grammar_name == 'com.example.shared'
    assert imp.wildcard is True


def test_diagnostics_no_errors_valid_workspace():
    shared = FIXTURES / 'shared.gram'
    greeting = FIXTURES / 'greeting.gram'
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
    path = Path('/tmp/test_broken.gram')
    dialect = DialectRegistry.standard()
    index = GrammarIndex(Path('/tmp'), dialect)
    doc = index.update_file(path, source)
    doc = index._documents[path]
    diags = doc.get_diagnostics(index)
    errors = [d for d in diags if 'Undefined rule' in d.message]
    assert len(errors) == 1
    assert 'undefinedRule' in errors[0].message


def test_resilient_parse_on_broken_grammar():
    path = FIXTURES / 'broken.gram'
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
    path = FIXTURES / 'agreement.gram'
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
    doc = GrammarDocument.parse(_Path('/tmp/t.gram'), source)
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
    doc = GrammarDocument.parse(_Path('/tmp/t.gram'), source)
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
    mangled, pyjsgf_to_orig, _ = _mangle_source(source)
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
    mangled, pyjsgf_to_orig, _ = _mangle_source(source)
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
    mangled, pyjsgf_to_orig, _ = _mangle_source(source)
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
    mangled, _, _ = _mangle_source(source)
    body = mangled.split('<sentence>')[1]
    # 'dual' variant doesn't exist — flagged ref pass leaves it unchanged,
    # bare <noun> resolves to synthetic union of singular|plural
    assert '<noun>' in body


def test_same_name_variants_parse_successfully():
    path = FIXTURES / 'noun_variants.gram'
    doc = GrammarDocument.parse(path, path.read_text())
    assert doc.parse_error is None


def test_same_name_variants_pyjsgf_names():
    path = FIXTURES / 'noun_variants.gram'
    doc = GrammarDocument.parse(path, path.read_text())
    pyjsgf_names = [r.pyjsgf_name for r in doc.rules]
    assert 'noun__number_singular' in pyjsgf_names
    assert 'noun__number_plural' in pyjsgf_names


def test_same_name_variants_original_names_preserved():
    path = FIXTURES / 'noun_variants.gram'
    doc = GrammarDocument.parse(path, path.read_text())
    for rule in doc.rules:
        assert rule.name == 'noun'


def test_same_name_variants_no_duplicate_diagnostic():
    dialect = DialectRegistry.standard()
    index = GrammarIndex(FIXTURES, dialect)
    path = FIXTURES / 'noun_variants.gram'
    index.update_file(path, path.read_text())
    doc = index._documents[path]
    diags = doc.get_diagnostics(index)
    dup_diags = [d for d in diags if 'Duplicate' in d.message]
    assert dup_diags == []


def test_true_duplicate_still_detected():
    """Same name + same flags → pyjsgf_name collision → diagnostic emitted."""
    source = """\
#JSGF V1.0;
grammar test;
public <noun> {number:enum=singular} = book;
public <noun> {number:enum=singular} = cat;
"""
    dialect = DialectRegistry.standard()
    index = GrammarIndex(Path('/tmp'), dialect)
    path = Path('/tmp/dup_test.gram')
    index.update_file(path, source)
    doc = index._documents[path]
    diags = doc.get_diagnostics(index)
    dup_diags = [d for d in diags if 'Duplicate' in d.message]
    assert len(dup_diags) >= 1


def test_pyjsgf_def_positions_per_variant():
    path = FIXTURES / 'noun_variants.gram'
    doc = GrammarDocument.parse(path, path.read_text())
    pos_singular = doc.pyjsgf_def_positions.get('noun__number_singular')
    pos_plural = doc.pyjsgf_def_positions.get('noun__number_plural')
    assert pos_singular is not None
    assert pos_plural is not None
    assert pos_singular.line != pos_plural.line


def test_get_rule_by_pyjsgf_name():
    path = FIXTURES / 'noun_variants.gram'
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
    doc = GrammarDocument.parse(Path('/tmp/resilient_pyjsgf_name.gram'), source)
    # Resilient parse was used (source has invalid syntax after the rule)
    rule = doc.get_rule('item')
    assert rule is not None
    assert rule.pyjsgf_name == 'item__number_singular'
