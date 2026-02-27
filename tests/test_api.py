"""Tests for agent/api.py — GrammarAgentAPI."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.dialect import DialectRegistry
from core.index import GrammarIndex
from agent.api import GrammarAgentAPI, CoverageResult

FIXTURES = Path(__file__).parent / 'fixtures'


def _api() -> GrammarAgentAPI:
    dialect = DialectRegistry.standard()
    index = GrammarIndex(FIXTURES, dialect)
    index.index_workspace()
    return GrammarAgentAPI(index)


def test_validate_coverage_full_match():
    api = _api()
    shared = FIXTURES / 'shared.gram'
    result = api.validate_coverage('currency', shared, ['dollars', 'euros', 'pounds'])
    assert result.coverage_ratio == 1.0
    assert result.uncovered == []


def test_validate_coverage_partial():
    api = _api()
    shared = FIXTURES / 'shared.gram'
    result = api.validate_coverage('currency', shared, ['dollars', 'yen'])
    assert result.coverage_ratio < 1.0
    assert 'yen' in result.uncovered
    assert 'dollars' in result.covered


def test_validate_coverage_rule_not_found():
    api = _api()
    shared = FIXTURES / 'shared.gram'
    result = api.validate_coverage('nonexistent', shared, ['test'])
    assert result.coverage_ratio == 0.0
    assert result.uncovered == ['test']


def test_get_examples():
    api = _api()
    shared = FIXTURES / 'shared.gram'
    examples = api.get_examples('currency', shared, n=10)
    assert len(examples) > 0
    assert all(isinstance(e, str) for e in examples)
    assert 'dollars' in examples or 'euros' in examples or 'pounds' in examples


def test_find_rules_matching():
    api = _api()
    results = api.find_rules_matching(['dollars', 'euros'])
    assert len(results) > 0
    top_rule, top_cov = results[0]
    assert top_cov.coverage_ratio > 0


def test_get_generation_context():
    api = _api()
    transfer = FIXTURES / 'transfer.gram'
    ctx = api.get_generation_context(
        transfer,
        'Transfer money between accounts',
        ['transfer ten dollars to savings'],
    )
    assert isinstance(ctx.existing_rules, list)
    assert isinstance(ctx.dialect_functions, list)
    assert isinstance(ctx.similar_rules, list)


def test_validate_generated_grammar_valid():
    api = _api()
    target = FIXTURES / 'shared.gram'
    source = """\
#JSGF V1.0;
grammar com.example.test;
public <yesno> = yes | no | maybe;
"""
    diags, coverage = api.validate_generated_grammar(source, Path('/tmp/test.gram'), ['yes', 'no'])
    assert diags == []
    assert coverage is not None
    assert coverage.coverage_ratio == 1.0


def test_validate_generated_grammar_with_error():
    api = _api()
    source = """\
#JSGF V1.0;
grammar com.example.test;
public <broken> = <undefinedRef>;
"""
    diags, coverage = api.validate_generated_grammar(
        source, Path('/tmp/test_broken.gram'), ['test']
    )
    assert len(diags) > 0
    assert coverage is None
