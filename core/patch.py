"""
Position tracking for pyjsgf AST nodes.

pyjsgf's parse actions don't preserve source positions. This module provides:
- A Position dataclass (LSP 0-indexed line/character)
- scan_rule_positions(): text-scan approach that finds positions by regex
  and attaches them to nodes after parsing
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Position:
    line: int        # 0-indexed (LSP convention)
    character: int   # 0-indexed


def _line_offsets(source: str) -> list[int]:
    """Return the character offset of the start of each line."""
    offsets = [0]
    for i, ch in enumerate(source):
        if ch == '\n':
            offsets.append(i + 1)
    return offsets


def offset_to_position(offset: int, offsets: list[int]) -> Position:
    """Convert a character offset to a Position using pre-computed line offsets."""
    import bisect
    line = bisect.bisect_right(offsets, offset) - 1
    character = offset - offsets[line]
    return Position(line=line, character=character)


def scan_positions(source: str) -> dict[str, list[Position]]:
    """
    Scan source text and return positions of all rule references and definitions.

    Returns a dict mapping rule names to sorted lists of Positions where
    they appear as references (i.e. '<ruleName>').  Definition positions
    are also included so callers can distinguish start of the rule keyword.
    """
    offsets = _line_offsets(source)
    positions: dict[str, list[Position]] = {}
    for m in re.finditer(r'<([A-Za-z0-9_.$-]+)>', source):
        name = m.group(1)
        pos = offset_to_position(m.start() + 1, offsets)  # +1 to skip '<'
        positions.setdefault(name, []).append(pos)
    return positions


def scan_rule_def_positions(source: str) -> dict[str, Position]:
    """
    Return the Position of each rule definition (at the '<' of the rule name).
    """
    offsets = _line_offsets(source)
    positions: dict[str, Position] = {}
    # Matches optional 'public', '<ruleName>', optional LHS flag blocks, then '='
    for m in re.finditer(r'(?:public\s+)?<([A-Za-z0-9_.$-]+)>(?:\s*\{[^}]*\})*\s*=', source):
        name = m.group(1)
        # Position at the '<'
        angle_offset = m.start(1) - 1  # the '<' before the name
        pos = offset_to_position(angle_offset, offsets)
        if name not in positions:
            positions[name] = pos
    return positions
