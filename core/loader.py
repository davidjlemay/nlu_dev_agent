"""
DataLoader: lazy-loads vocabulary items from configured data sources.

Supports three source types:
- 'file':    read items from a text file (one per line) or JSON array
- 'inline':  items listed directly in the dialect config
- 'command': run a subprocess and read stdout as items

Flag filtering:
- Line format: items may carry an inline flag suffix  value{key=val,key2=val2}
- JSON format: items may be plain strings or {"value": ..., "flags": {...}} dicts
- Untagged items (no suffix / plain strings) always match any filter.
- load_filtered(name, flags) returns only items whose flags match all provided
  key/value pairs; load(name) returns all values (flag suffixes stripped).
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from .dialect import DataSource, LazyLoadingConfig

# Parses inline flag suffix from line items: "TD Bank{region=ca,number=sg}"
_INLINE_FLAG_RE = re.compile(r'^(.*?)\{([^}]+)\}\s*$')


def _parse_line_item(line: str) -> tuple[str, dict[str, str]]:
    """Split ``"TD Bank{region=ca}"`` into ``("TD Bank", {"region": "ca"})``.

    Gazetteer lines may use ``surface|canonical`` (the canonical is ignored).
    Returns ``(line, {})`` when no flag suffix is present.
    Multiple flags are comma-separated: ``value{a=1,b=2}``.
    """
    if '|' in line:
        line = line.rsplit('|', 1)[0]
    m = _INLINE_FLAG_RE.match(line)
    if not m:
        value = line
    else:
        value = m.group(1).strip()
        flags: dict[str, str] = {}
        for part in m.group(2).split(','):
            part = part.strip()
            if '=' in part:
                k, _, v = part.partition('=')
                flags[k.strip()] = v.strip()
    # Strip Cerence compound wordform markers (\cpd) from surface forms.
    value = re.sub(r'\\[A-Za-z0-9_]+', '', value)
    value = re.sub(r'[-_\s]+$', '', value)
    if not m:
        return value, {}
    return value, flags


class DataLoader:
    def __init__(
        self,
        sources: dict[str, DataSource],
        config: LazyLoadingConfig,
        workspace_root: Path,
    ) -> None:
        self._sources = sources
        self._config = config
        self._workspace_root = workspace_root
        self._cache: dict[str, list[str]] = {}
        self._filtered_cache: dict[tuple, list[str]] = {}

    # ------------------------------------------------------------------ #
    #  Public interface                                                    #
    # ------------------------------------------------------------------ #

    @property
    def expansion_limit(self) -> int:
        return self._config.expansion_limit

    def load(self, source_name: str) -> list[str]:
        """Return up to lookup_limit items; result is cached after first call.

        For line-format sources any inline flag suffix (e.g. ``{region=ca}``)
        is stripped so callers always receive clean values.
        """
        if source_name in self._cache:
            return self._cache[source_name]
        result = self._load_uncached(source_name)
        self._cache[source_name] = result
        return result

    def load_filtered(self, source_name: str, flags: dict[str, str]) -> list[str]:
        """Return items whose flags match all key/value pairs in *flags*.

        Untagged items (plain strings / lines without a ``{...}`` suffix)
        always match any filter.  When *flags* is empty, delegates to
        :meth:`load` (returns all items).

        Results are cached per ``(source_name, frozenset(flags.items()))``.
        """
        if not flags:
            return self.load(source_name)
        cache_key = (source_name, frozenset(flags.items()))
        if cache_key in self._filtered_cache:
            return self._filtered_cache[cache_key]
        src = self._sources.get(source_name)
        if src is None:
            return []
        limit = self._config.lookup_limit
        result: list[str] = []
        def _is_wildcard(v: str) -> bool:
            return v == '*' or v.startswith('?')

        try:
            if src.format == 'json':
                raw = self._load_raw_json(src, limit)
                for item in raw:
                    if isinstance(item, str):
                        result.append(item)          # untagged: always match
                    elif isinstance(item, dict):
                        item_flags = item.get('flags', {})
                        if all(_is_wildcard(v) or item_flags.get(k) == v for k, v in flags.items()):
                            result.append(str(item.get('value', '')))
            else:   # 'lines' format — parse inline {key=val} suffix
                lines = self._load_raw_lines(src, limit)
                for line in lines:
                    value, item_flags = _parse_line_item(line)
                    if not item_flags or all(_is_wildcard(v) or item_flags.get(k) == v for k, v in flags.items()):
                        result.append(value)
        except Exception:
            pass
        self._filtered_cache[cache_key] = result
        return result

    def invalidate(self, source_name: str | None = None) -> None:
        """Drop cache for one source or all sources."""
        if source_name is None:
            self._cache.clear()
            self._filtered_cache.clear()
        else:
            self._cache.pop(source_name, None)
            # Remove all filtered-cache entries for this source
            for key in [k for k in self._filtered_cache if k[0] == source_name]:
                del self._filtered_cache[key]

    # ------------------------------------------------------------------ #
    #  Private helpers                                                     #
    # ------------------------------------------------------------------ #

    def _load_uncached(self, source_name: str) -> list[str]:
        src = self._sources.get(source_name)
        if src is None:
            return []
        limit = self._config.lookup_limit
        try:
            if src.type == 'inline':
                if src.format == 'json':
                    # inline JSON: values list may contain dicts
                    raw = src.values[:limit]
                    return [
                        str(item.get('value', '')) if isinstance(item, dict) else str(item)
                        for item in raw
                    ]
                return [_parse_line_item(v)[0] for v in src.values[:limit]]
            elif src.type == 'file':
                return self._load_file(src, limit)
            elif src.type == 'command':
                return self._load_command(src, limit)
        except Exception:
            pass
        return []

    def _load_file(self, src: DataSource, limit: int) -> list[str]:
        if src.format == 'json':
            raw = self._load_raw_json(src, limit)
            return [
                str(item.get('value', '')) if isinstance(item, dict) else str(item)
                for item in raw
            ]
        # Default: lines — strip inline flag suffixes
        lines = self._load_raw_lines(src, limit)
        return [_parse_line_item(line)[0] for line in lines]

    def _load_raw_lines(self, src: DataSource, limit: int) -> list[str]:
        """Return raw lines from a file or inline source (no flag stripping)."""
        if src.type == 'inline':
            return [str(v) for v in src.values[:limit]]
        if src.path is None:
            return []
        path = Path(src.path)
        if not path.is_absolute():
            path = self._workspace_root / path
        text = path.read_text(encoding='utf-8')
        return [line.strip() for line in text.splitlines() if line.strip()][:limit]

    def _load_raw_json(self, src: DataSource, limit: int) -> list:
        """Return raw parsed JSON list (items not yet value-extracted)."""
        if src.type == 'inline':
            return list(src.values[:limit])
        if src.path is None:
            return []
        path = Path(src.path)
        if not path.is_absolute():
            path = self._workspace_root / path
        text = path.read_text(encoding='utf-8')
        items = json.loads(text)
        return items[:limit]

    def _load_command(self, src: DataSource, limit: int) -> list[str]:
        if src.command is None:
            return []
        cmd = [src.command] + list(src.args)
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=10,
            cwd=str(self._workspace_root),
        )
        lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        # Strip inline flag suffixes from command output too
        return [_parse_line_item(line)[0] for line in lines[:limit]]
