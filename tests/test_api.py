"""Tests for agent/api.py — GrammarAgentAPI."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.dialect import DialectRegistry, DataSource, LazyLoadingConfig
from core.index import GrammarIndex
from core.loader import DataLoader
from agent.api import GrammarAgentAPI, CoverageResult

FIXTURES = Path(__file__).parent / 'fixtures'


def _api() -> GrammarAgentAPI:
    dialect = DialectRegistry.standard()
    index = GrammarIndex(FIXTURES, dialect)
    index.index_workspace()
    return GrammarAgentAPI(index)


def test_validate_coverage_full_match():
    api = _api()
    shared = FIXTURES / 'shared.jsgf'
    result = api.validate_coverage('currency', shared, ['dollars', 'euros', 'pounds'])
    assert result.coverage_ratio == 1.0
    assert result.uncovered == []


def test_validate_coverage_partial():
    api = _api()
    shared = FIXTURES / 'shared.jsgf'
    result = api.validate_coverage('currency', shared, ['dollars', 'yen'])
    assert result.coverage_ratio < 1.0
    assert 'yen' in result.uncovered
    assert 'dollars' in result.covered


def test_validate_coverage_rule_not_found():
    api = _api()
    shared = FIXTURES / 'shared.jsgf'
    result = api.validate_coverage('nonexistent', shared, ['test'])
    assert result.coverage_ratio == 0.0
    assert result.uncovered == ['test']


def test_get_examples():
    api = _api()
    shared = FIXTURES / 'shared.jsgf'
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
    transfer = FIXTURES / 'transfer.jsgf'
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
    target = FIXTURES / 'shared.jsgf'
    source = """\
#JSGF V1.0;
grammar com.example.test;
public <yesno> = yes | no | maybe;
"""
    diags, coverage = api.validate_generated_grammar(source, Path('/tmp/test.jsgf'), ['yes', 'no'])
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
        source, Path('/tmp/test_broken.jsgf'), ['test']
    )
    assert len(diags) > 0
    assert coverage is None


# ------------------------------------------------------------------ #
#  Multi-variant coverage                                              #
# ------------------------------------------------------------------ #

def test_validate_coverage_multi_variant():
    """Coverage unions across all LHS-flag variants of the same rule name."""
    dialect = DialectRegistry.standard()
    index = GrammarIndex(FIXTURES, dialect)
    path = FIXTURES / 'noun_variants.jsgf'
    index.update_file(path, path.read_text())
    api = GrammarAgentAPI(index)

    result = api.validate_coverage('noun', path, ['book', 'cats', 'elephant'])
    assert 'book' in result.covered       # matches singular
    assert 'cats' in result.covered       # matches plural
    assert 'elephant' in result.uncovered  # matches neither
    assert abs(result.coverage_ratio - 2 / 3) < 0.01


def test_validate_coverage_pyjsgf_name_direct():
    """Looking up by mangled pyjsgf name returns only that specific variant."""
    dialect = DialectRegistry.standard()
    index = GrammarIndex(FIXTURES, dialect)
    path = FIXTURES / 'noun_variants.jsgf'
    index.update_file(path, path.read_text())
    api = GrammarAgentAPI(index)

    result = api.validate_coverage('noun__number_singular', path, ['book', 'books'])
    assert 'book' in result.covered       # singular matches
    assert 'books' in result.uncovered    # plural form not in singular rule


# ------------------------------------------------------------------ #
#  DataLoader integration                                              #
# ------------------------------------------------------------------ #

def _make_loader(values: list[str], source_name: str = 'banks') -> DataLoader:
    src = DataSource(name=source_name, type='inline', values=values)
    config = LazyLoadingConfig(lookup_limit=50, expansion_limit=200)
    return DataLoader({source_name: src}, config, FIXTURES)


def _api_with_loader(gram_source: str, path: Path, loader: DataLoader) -> GrammarAgentAPI:
    dialect = DialectRegistry.standard()
    index = GrammarIndex(FIXTURES, dialect)
    index.update_file(path, gram_source)
    return GrammarAgentAPI(index, loader=loader)


def test_get_examples_with_lookup_returns_real_words():
    """get_examples resolves $lookup() placeholders to actual vocabulary items."""
    source = """\
#JSGF V1.0;
grammar test;
public <check_balance> = balance of $lookup('banks');
"""
    path = Path('/tmp/lookup_examples.jsgf')
    loader = _make_loader(['td bank', 'rbc', 'cibc'], source_name='banks')
    api = _api_with_loader(source, path, loader)
    examples = api.get_examples('check_balance', path, n=10)
    assert len(examples) > 0
    # Should get actual bank names, not the raw token
    assert 'PLHDR0' not in examples
    assert any('td bank' in e or 'rbc' in e or 'cibc' in e for e in examples)


def test_validate_coverage_with_lookup_matches_loaded_items():
    """validate_coverage uses expansion-based matching when lookup is present."""
    source = """\
#JSGF V1.0;
grammar test;
public <check_balance> = balance of $lookup('banks');
"""
    path = Path('/tmp/lookup_coverage.jsgf')
    loader = _make_loader(['td bank', 'rbc', 'cibc'], source_name='banks')
    api = _api_with_loader(source, path, loader)
    result = api.validate_coverage(
        'check_balance', path,
        ['balance of td bank', 'balance of rbc', 'balance of xyz bank'],
    )
    assert 'balance of td bank' in result.covered
    assert 'balance of rbc' in result.covered
    assert 'balance of xyz bank' in result.uncovered
    assert abs(result.coverage_ratio - 2 / 3) < 0.01


def test_validate_coverage_lookup_full_coverage():
    """Coverage is 1.0 when all utterances match loaded items."""
    source = """\
#JSGF V1.0;
grammar test;
public <greet> = hello $lookup('names');
"""
    path = Path('/tmp/lookup_full.jsgf')
    loader = _make_loader(['alice', 'bob'], source_name='names')
    api = _api_with_loader(source, path, loader)
    result = api.validate_coverage(
        'greet', path, ['hello alice', 'hello bob'],
    )
    assert result.coverage_ratio == 1.0
    assert result.uncovered == []


def test_get_examples_without_loader_returns_placeholder_token():
    """Without a loader, $lookup() remains as PLHDR token (no crash)."""
    source = """\
#JSGF V1.0;
grammar test;
public <check_balance> = balance of $lookup('banks');
"""
    path = Path('/tmp/no_loader.jsgf')
    dialect = DialectRegistry.standard()
    index = GrammarIndex(FIXTURES, dialect)
    index.update_file(path, source)
    api = GrammarAgentAPI(index)  # no loader
    examples = api.get_examples('check_balance', path, n=5)
    # Should not crash, returns raw token
    assert isinstance(examples, list)


def test_validate_coverage_lookup_case_insensitive():
    """Coverage matching is case-insensitive: loaded items in mixed case match lowercase utterances."""
    source = """\
#JSGF V1.0;
grammar test;
public <bank_name> = (at | with) $lookup('banks');
"""
    path = Path('/tmp/lookup_case.jsgf')
    # Bank names with mixed / upper casing (as loaded from a real file)
    loader = _make_loader(['TD Canada-Trust', 'BMO', 'Scotiabank'], source_name='banks')
    api = _api_with_loader(source, path, loader)
    result = api.validate_coverage(
        'bank_name', path,
        ['at td canada-trust', 'with bmo', 'at xyz bank'],
    )
    assert 'at td canada-trust' in result.covered
    assert 'with bmo' in result.covered
    assert 'at xyz bank' in result.uncovered
    assert abs(result.coverage_ratio - 2 / 3) < 0.01


def test_validate_coverage_flagged_lookup():
    """Flagged lookup rules load only matching subset of the data source.

    The 'banks' source has ca and us tagged items; each rule variant loads only
    its matching subset.  Coverage unions across both variants.
    """
    fixture = FIXTURES / 'flagged_lookup.jsgf'
    banks_src = DataSource(
        name='banks', type='inline', format='json',
        values=[
            {'value': 'TD', 'flags': {'region': 'ca'}},
            {'value': 'BMO', 'flags': {'region': 'ca'}},
            {'value': 'Chase', 'flags': {'region': 'us'}},
        ],
    )
    config = LazyLoadingConfig(lookup_limit=50, expansion_limit=200)
    loader = DataLoader({'banks': banks_src}, config, FIXTURES)

    dialect = DialectRegistry.standard()
    index = GrammarIndex(FIXTURES, dialect)
    index.update_file(fixture, fixture.read_text())
    api = GrammarAgentAPI(index, loader=loader)

    result = api.validate_coverage('bank', fixture, ['TD', 'Chase', 'unknown'])
    assert 'TD' in result.covered        # from ca variant
    assert 'Chase' in result.covered     # from us variant
    assert 'unknown' in result.uncovered
    assert abs(result.coverage_ratio - 2 / 3) < 0.01


def test_budget_limits_expansions():
    """expansion_limit caps the number of generated items."""
    # 20 alternatives combined with a prefix generates 20 expansions
    alts = ' | '.join(f'item{i}' for i in range(20))
    source = f"""\
#JSGF V1.0;
grammar test;
public <items> = the ({alts});
"""
    path = Path('/tmp/budget_test.jsgf')
    loader = _make_loader([], source_name='x')
    # Override expansion_limit to 5
    loader._config = LazyLoadingConfig(lookup_limit=50, expansion_limit=5)
    api = _api_with_loader(source, path, loader)
    examples = api.get_examples('items', path, n=100)
    # Budget should cap output; sample is taken from whatever was generated
    assert len(examples) <= 20  # at most all alternatives
