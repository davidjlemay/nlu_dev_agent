"""Tests for core/document.py — GrammarDocument parsing."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.document import GrammarDocument
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
