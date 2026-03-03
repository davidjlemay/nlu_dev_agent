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
