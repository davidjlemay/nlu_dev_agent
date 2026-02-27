"""Tests for core/patch.py — position scanning."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.patch import (
    Position,
    scan_positions,
    scan_rule_def_positions,
    _line_offsets,
    offset_to_position,
)


SOURCE = """\
#JSGF V1.0;
grammar test;
public <greeting> = hello | hi;
<name> = world | everyone;
<combined> = <greeting> <name>;
"""


def test_line_offsets():
    offsets = _line_offsets(SOURCE)
    assert offsets[0] == 0
    assert offsets[1] == len('#JSGF V1.0;\n')


def test_offset_to_position():
    offsets = _line_offsets(SOURCE)
    pos = offset_to_position(0, offsets)
    assert pos == Position(line=0, character=0)


def test_scan_rule_def_positions():
    defs = scan_rule_def_positions(SOURCE)
    assert 'greeting' in defs
    assert 'name' in defs
    assert 'combined' in defs
    # greeting is on line 2 (0-indexed)
    assert defs['greeting'].line == 2


def test_scan_positions_finds_refs():
    refs = scan_positions(SOURCE)
    # <greeting> and <name> appear as refs in the combined rule
    assert 'greeting' in refs
    assert 'name' in refs
    # The ref in <combined> = <greeting> <name>
    combined_refs = refs.get('greeting', [])
    assert len(combined_refs) >= 1


def test_positions_are_zero_indexed():
    defs = scan_rule_def_positions(SOURCE)
    # First rule <greeting> is on line 2 (0-indexed: line 0 = JSGF header)
    assert defs['greeting'].line == 2
    # <name> is on line 3
    assert defs['name'].line == 3
