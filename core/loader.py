"""
DataLoader: lazy-loads vocabulary items from configured data sources.

Supports three source types:
- 'file':    read items from a text file (one per line) or JSON array
- 'inline':  items listed directly in the dialect config
- 'command': run a subprocess and read stdout as items
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from .dialect import DataSource, LazyLoadingConfig


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

    # ------------------------------------------------------------------ #
    #  Public interface                                                    #
    # ------------------------------------------------------------------ #

    @property
    def expansion_limit(self) -> int:
        return self._config.expansion_limit

    def load(self, source_name: str) -> list[str]:
        """Return up to lookup_limit items; result is cached after first call."""
        if source_name in self._cache:
            return self._cache[source_name]
        result = self._load_uncached(source_name)
        self._cache[source_name] = result
        return result

    def invalidate(self, source_name: str | None = None) -> None:
        """Drop cache for one source or all sources."""
        if source_name is None:
            self._cache.clear()
        else:
            self._cache.pop(source_name, None)

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
                return list(src.values[:limit])
            elif src.type == 'file':
                return self._load_file(src, limit)
            elif src.type == 'command':
                return self._load_command(src, limit)
        except Exception:
            pass
        return []

    def _load_file(self, src: DataSource, limit: int) -> list[str]:
        if src.path is None:
            return []
        path = Path(src.path)
        if not path.is_absolute():
            path = self._workspace_root / path
        text = path.read_text(encoding='utf-8')
        if src.format == 'json':
            items = json.loads(text)
            return [str(x) for x in items[:limit]]
        # Default: lines
        return [line.strip() for line in text.splitlines() if line.strip()][:limit]

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
        return lines[:limit]
