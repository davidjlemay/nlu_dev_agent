"""Tests for core/loader.py — DataLoader."""

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.dialect import DataSource, LazyLoadingConfig
from core.loader import DataLoader


def _loader(sources: dict, limit: int = 50, expansion_limit: int = 200) -> DataLoader:
    config = LazyLoadingConfig(lookup_limit=limit, expansion_limit=expansion_limit)
    return DataLoader(sources, config, Path('/tmp'))


# ------------------------------------------------------------------ #
#  Inline source                                                       #
# ------------------------------------------------------------------ #

def test_inline_source_returns_values():
    src = DataSource(name='currencies', type='inline', values=['USD', 'EUR', 'GBP'])
    loader = _loader({'currencies': src})
    result = loader.load('currencies')
    assert result == ['USD', 'EUR', 'GBP']


def test_inline_source_respects_limit():
    src = DataSource(name='x', type='inline', values=['a', 'b', 'c', 'd', 'e'])
    loader = _loader({'x': src}, limit=3)
    result = loader.load('x')
    assert result == ['a', 'b', 'c']


def test_unknown_source_returns_empty():
    loader = _loader({})
    assert loader.load('nonexistent') == []


# ------------------------------------------------------------------ #
#  File source                                                         #
# ------------------------------------------------------------------ #

def test_file_source_lines():
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
        f.write('td bank\nrbc\ncibc\n')
        fpath = f.name
    src = DataSource(name='banks', type='file', path=fpath, format='lines')
    loader = _loader({'banks': src})
    result = loader.load('banks')
    assert result == ['td bank', 'rbc', 'cibc']


def test_file_source_json():
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        json.dump(['apple', 'banana', 'cherry'], f)
        fpath = f.name
    src = DataSource(name='fruits', type='file', path=fpath, format='json')
    loader = _loader({'fruits': src})
    result = loader.load('fruits')
    assert result == ['apple', 'banana', 'cherry']


def test_file_source_limit():
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
        f.write('\n'.join(f'item{i}' for i in range(10)))
        fpath = f.name
    src = DataSource(name='items', type='file', path=fpath)
    loader = _loader({'items': src}, limit=4)
    result = loader.load('items')
    assert len(result) == 4
    assert result[0] == 'item0'


def test_file_source_missing_file_returns_empty():
    src = DataSource(name='missing', type='file', path='/nonexistent/path/file.txt')
    loader = _loader({'missing': src})
    result = loader.load('missing')
    assert result == []


# ------------------------------------------------------------------ #
#  Command source                                                      #
# ------------------------------------------------------------------ #

def test_command_source_reads_stdout():
    src = DataSource(
        name='nums',
        type='command',
        command='python3',
        args=['-c', 'print("one\\ntwo\\nthree")'],
    )
    loader = _loader({'nums': src})
    result = loader.load('nums')
    assert result == ['one', 'two', 'three']


def test_command_source_limit():
    src = DataSource(
        name='nums',
        type='command',
        command='python3',
        args=['-c', 'print("\\n".join(str(i) for i in range(20)))'],
    )
    loader = _loader({'nums': src}, limit=5)
    result = loader.load('nums')
    assert len(result) == 5


# ------------------------------------------------------------------ #
#  Cache behaviour                                                     #
# ------------------------------------------------------------------ #

def test_cache_populated_after_first_load():
    src = DataSource(name='x', type='inline', values=['a', 'b'])
    loader = _loader({'x': src})
    r1 = loader.load('x')
    r2 = loader.load('x')
    assert r1 is r2   # same object from cache


def test_invalidate_single_source():
    src = DataSource(name='x', type='inline', values=['a'])
    loader = _loader({'x': src})
    loader.load('x')
    assert 'x' in loader._cache
    loader.invalidate('x')
    assert 'x' not in loader._cache


def test_invalidate_all():
    s1 = DataSource(name='a', type='inline', values=['1'])
    s2 = DataSource(name='b', type='inline', values=['2'])
    loader = _loader({'a': s1, 'b': s2})
    loader.load('a')
    loader.load('b')
    loader.invalidate()
    assert loader._cache == {}


# ------------------------------------------------------------------ #
#  expansion_limit property                                            #
# ------------------------------------------------------------------ #

def test_expansion_limit_property():
    src = DataSource(name='x', type='inline', values=[])
    loader = _loader({'x': src}, expansion_limit=42)
    assert loader.expansion_limit == 42


# ------------------------------------------------------------------ #
#  load_filtered — flag-based filtering                               #
# ------------------------------------------------------------------ #

def test_load_filtered_json_by_flag():
    src = DataSource(name='banks', type='inline', format='json', values=[
        {'value': 'TD', 'flags': {'region': 'ca'}},
        {'value': 'BMO', 'flags': {'region': 'ca'}},
        {'value': 'Chase', 'flags': {'region': 'us'}},
    ])
    loader = _loader({'banks': src})
    result = loader.load_filtered('banks', {'region': 'ca'})
    assert result == ['TD', 'BMO']


def test_load_filtered_json_us_flag():
    src = DataSource(name='banks', type='inline', format='json', values=[
        {'value': 'TD', 'flags': {'region': 'ca'}},
        {'value': 'Chase', 'flags': {'region': 'us'}},
    ])
    loader = _loader({'banks': src})
    result = loader.load_filtered('banks', {'region': 'us'})
    assert result == ['Chase']


def test_load_filtered_lines_by_flag():
    src = DataSource(name='banks', type='inline', values=[
        'TD{region=ca}',
        'BMO{region=ca}',
        'Chase{region=us}',
    ])
    loader = _loader({'banks': src})
    result = loader.load_filtered('banks', {'region': 'ca'})
    assert result == ['TD', 'BMO']


def test_load_filtered_untagged_items_always_match():
    src = DataSource(name='items', type='inline', format='json', values=[
        'global_bank',
        {'value': 'TD', 'flags': {'region': 'ca'}},
    ])
    loader = _loader({'items': src})
    result = loader.load_filtered('items', {'region': 'ca'})
    assert 'global_bank' in result
    assert 'TD' in result


def test_load_filtered_untagged_lines_always_match():
    src = DataSource(name='items', type='inline', values=[
        'global_bank',
        'TD{region=ca}',
    ])
    loader = _loader({'items': src})
    result = loader.load_filtered('items', {'region': 'us'})
    assert 'global_bank' in result
    assert 'TD' not in result


def test_load_filtered_no_flags_delegates_to_load():
    src = DataSource(name='items', type='inline', values=['a', 'b'])
    loader = _loader({'items': src})
    assert loader.load_filtered('items', {}) == loader.load('items')


def test_load_lines_strips_flag_suffix():
    """load() with no filter returns clean values (flag suffixes stripped)."""
    src = DataSource(name='banks', type='inline', values=[
        'TD{region=ca}',
        'Chase{region=us}',
        'plain_bank',
    ])
    loader = _loader({'banks': src})
    result = loader.load('banks')
    assert result == ['TD', 'Chase', 'plain_bank']


def test_load_filtered_cached():
    src = DataSource(name='banks', type='inline', format='json', values=[
        {'value': 'TD', 'flags': {'region': 'ca'}},
    ])
    loader = _loader({'banks': src})
    r1 = loader.load_filtered('banks', {'region': 'ca'})
    r2 = loader.load_filtered('banks', {'region': 'ca'})
    assert r1 is r2


def test_load_filtered_file_lines(tmp_path):
    banks_file = tmp_path / 'banks.txt'
    banks_file.write_text('TD{region=ca}\nBMO{region=ca}\nChase{region=us}\n')
    src = DataSource(name='banks', type='file', path=str(banks_file), format='lines')
    loader = DataLoader({'banks': src}, LazyLoadingConfig(), tmp_path)
    assert loader.load_filtered('banks', {'region': 'ca'}) == ['TD', 'BMO']
    assert loader.load('banks') == ['TD', 'BMO', 'Chase']


def test_invalidate_clears_filtered_cache():
    src = DataSource(name='x', type='inline', format='json', values=[
        {'value': 'a', 'flags': {'k': 'v'}},
    ])
    loader = _loader({'x': src})
    loader.load_filtered('x', {'k': 'v'})
    assert len(loader._filtered_cache) == 1
    loader.invalidate('x')
    assert len(loader._filtered_cache) == 0


def test_invalidate_all_clears_filtered_cache():
    src = DataSource(name='x', type='inline', format='json', values=[
        {'value': 'a', 'flags': {'k': 'v'}},
    ])
    loader = _loader({'x': src})
    loader.load_filtered('x', {'k': 'v'})
    loader.invalidate()
    assert loader._filtered_cache == {}


# ------------------------------------------------------------------ #
#  _find_dialect_cfg (walk-up helper used by CLI skills)              #
# ------------------------------------------------------------------ #

def _load_coverage_skill():
    """Load the coverage skill module (handles hyphenated directory name)."""
    import importlib.util
    skill_path = Path(__file__).parent.parent / 'skills' / 'jsgf-coverage' / 'coverage.py'
    spec = importlib.util.spec_from_file_location('coverage_skill', skill_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_find_dialect_cfg_walks_up_to_parent():
    """Config found by walking up from a subdirectory."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        sub = root / 'grammars'
        sub.mkdir()
        cfg = root / 'jsgf-dialect.json'
        cfg.write_text('{}')

        find = _load_coverage_skill()._find_dialect_cfg

        # Start from sub/ — should walk up and find config at root/
        found_cfg, data_root = find(sub)
        assert found_cfg == cfg
        assert data_root == root


def test_find_dialect_cfg_finds_in_start_dir():
    """Config found in the start directory itself (no walk needed)."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cfg = root / 'jsgf-dialect.json'
        cfg.write_text('{}')

        find = _load_coverage_skill()._find_dialect_cfg
        found_cfg, data_root = find(root)
        assert found_cfg == cfg
        assert data_root == root


def test_find_dialect_cfg_returns_none_when_missing():
    """Falls back to (None, start) when no config file exists anywhere."""
    find = _load_coverage_skill()._find_dialect_cfg

    with tempfile.TemporaryDirectory() as tmp:
        start = Path(tmp) / 'deep' / 'nested'
        start.mkdir(parents=True)
        found_cfg, data_root = find(start)
        assert found_cfg is None
        assert data_root == start
