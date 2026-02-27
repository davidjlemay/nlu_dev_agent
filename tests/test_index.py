"""Tests for core/index.py — GrammarIndex."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.index import GrammarIndex, RuleLocation
from core.dialect import DialectRegistry

FIXTURES = Path(__file__).parent / 'fixtures'


def _full_index() -> GrammarIndex:
    dialect = DialectRegistry.standard()
    index = GrammarIndex(FIXTURES, dialect)
    index.index_workspace()
    return index


def test_index_workspace_finds_all_files():
    index = _full_index()
    paths = list(index._documents.keys())
    assert any(p.name == 'shared.gram' for p in paths)
    assert any(p.name == 'greeting.gram' for p in paths)
    assert any(p.name == 'transfer.gram' for p in paths)


def test_resolve_rule_local():
    index = _full_index()
    shared = FIXTURES / 'shared.gram'
    loc = index.resolve_rule('cardinal', shared)
    assert loc is not None
    assert loc.file == shared
    assert loc.rule.name == 'cardinal'


def test_resolve_rule_via_import():
    index = _full_index()
    greeting = FIXTURES / 'greeting.gram'
    # 'amount' is public in shared.gram, which greeting.gram imports
    loc = index.resolve_rule('amount', greeting)
    assert loc is not None
    assert loc.file == FIXTURES / 'shared.gram'


def test_resolve_rule_not_found():
    index = _full_index()
    shared = FIXTURES / 'shared.gram'
    loc = index.resolve_rule('nonexistent', shared)
    assert loc is None


def test_get_visible_rules_includes_imports():
    index = _full_index()
    greeting = FIXTURES / 'greeting.gram'
    visible = index.get_visible_rules(greeting)
    names = {loc.rule.name for loc in visible}
    # Local rules
    assert 'greeting' in names
    assert 'farewell' in names
    # Imported rules (public from shared.gram)
    assert 'cardinal' in names
    assert 'amount' in names


def test_grammar_name_index():
    index = _full_index()
    assert 'com.example.shared' in index._grammar_name_index
    assert 'com.example.greeting' in index._grammar_name_index


def test_find_references():
    index = _full_index()
    # 'amount' is referenced in transfer.gram
    refs = index.find_references('amount')
    ref_files = {path.name for path, _ in refs}
    assert 'transfer.gram' in ref_files


def test_update_file_returns_affected():
    index = _full_index()
    shared = FIXTURES / 'shared.gram'
    greeting = FIXTURES / 'greeting.gram'
    # Updating shared.gram should affect greeting.gram (which imports it)
    affected = index.update_file(shared, shared.read_text())
    assert greeting in affected


def test_remove_file():
    index = _full_index()
    shared = FIXTURES / 'shared.gram'
    affected = index.remove_file(shared)
    assert shared not in index._documents
    assert 'com.example.shared' not in index._grammar_name_index
