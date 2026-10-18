"""
WorkspaceCache: on-disk persistence for parsed GrammarDocuments.

Uses pickle to avoid re-parsing unchanged .jsgf/.jgram files on daemon startup.
Invalidation is by file mtime + size and by the mtime + size of language
configuration inputs (YAML, dialect, features, jsgf.stark).
"""

from __future__ import annotations

import hashlib
import json
import pickle
from pathlib import Path
from typing import Iterable

from .document import GrammarDocument


CACHE_VERSION = '1'


class WorkspaceCache:
    def __init__(
        self,
        cache_dir: Path,
        root: Path,
        config_paths: Iterable[Path | str] = (),
    ) -> None:
        self.cache_dir = Path(cache_dir)
        self.root = Path(root).resolve()
        self.config_paths = [
            Path(p).resolve() for p in config_paths if p is not None
        ]
        self.manifest_path = self.cache_dir / 'manifest.json'
        self.docs_dir = self.cache_dir / 'docs'
        self.docs_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ #
    #  Public interface                                                  #
    # ------------------------------------------------------------------ #

    def load_documents(self) -> dict[Path, GrammarDocument]:
        """
        Return a path -> GrammarDocument map for the current workspace.

        Unchanged files are loaded from pickle; changed/new files are parsed
        from disk and the cache is updated. Missing files are removed from
        the manifest.
        """
        manifest = self._load_manifest()
        if manifest is None or manifest.get('version') != CACHE_VERSION:
            manifest = {
                'version': CACHE_VERSION,
                'config_fingerprint': None,
                'files': {},
            }

        config_fingerprint = self._config_fingerprint()
        if manifest.get('config_fingerprint') != config_fingerprint:
            manifest = {
                'version': CACHE_VERSION,
                'config_fingerprint': config_fingerprint,
                'files': {},
            }
            self._clear_cached_docs()

        documents: dict[Path, GrammarDocument] = {}
        new_files: dict[str, dict] = {}

        for ext in ('*.jsgf', '*.jgram'):
            for path in self.root.rglob(ext):
                try:
                    if not path.is_file():
                        continue
                    abs_path = path.resolve()
                    rel = self._relative_key(path)

                    stat = path.stat()
                    mtime = stat.st_mtime
                    size = stat.st_size

                    cached = manifest['files'].get(rel)
                    if (
                        cached
                        and cached.get('mtime') == mtime
                        and cached.get('size') == size
                    ):
                        doc = self._load_doc(cached['pickle'])
                        if doc is not None:
                            documents[abs_path] = doc
                            new_files[rel] = cached
                            continue

                    source = path.read_text(encoding='utf-8')
                    doc = GrammarDocument.parse(path, source)
                    documents[abs_path] = doc

                    pickle_name = self._pickle_name(rel)
                    if self._save_doc(doc, pickle_name):
                        new_files[rel] = {
                            'mtime': mtime,
                            'size': size,
                            'pickle': pickle_name,
                        }
                except OSError:
                    pass

        manifest['files'] = new_files
        manifest['config_fingerprint'] = config_fingerprint
        self._save_manifest(manifest)
        return documents

    # ------------------------------------------------------------------ #
    #  Private helpers                                                   #
    # ------------------------------------------------------------------ #

    def _load_manifest(self) -> dict | None:
        if not self.manifest_path.exists():
            return None
        try:
            text = self.manifest_path.read_text(encoding='utf-8')
            return json.loads(text)
        except (json.JSONDecodeError, OSError):
            return None

    def _save_manifest(self, manifest: dict) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        text = json.dumps(manifest, indent=2, sort_keys=True)
        self.manifest_path.write_text(text, encoding='utf-8')

    def _clear_cached_docs(self) -> None:
        if not self.docs_dir.exists():
            return
        for p in self.docs_dir.glob('*.pkl'):
            try:
                p.unlink()
            except OSError:
                pass

    def _load_doc(self, pickle_name: str) -> GrammarDocument | None:
        pkl_path = self.docs_dir / pickle_name
        if not pkl_path.exists():
            return None
        try:
            with pkl_path.open('rb') as f:
                return pickle.load(f)
        except Exception:
            try:
                pkl_path.unlink(missing_ok=True)
            except OSError:
                pass
            return None

    def _save_doc(self, doc: GrammarDocument, pickle_name: str) -> bool:
        pkl_path = self.docs_dir / pickle_name
        try:
            with pkl_path.open('wb') as f:
                pickle.dump(doc, f, protocol=pickle.HIGHEST_PROTOCOL)
            return True
        except Exception:
            try:
                pkl_path.unlink(missing_ok=True)
            except OSError:
                pass
            return False

    def _pickle_name(self, rel: str) -> str:
        h = hashlib.sha1(rel.encode('utf-8')).hexdigest()
        return f'{h}.pkl'

    def _relative_key(self, path: Path) -> str:
        rel = path.resolve().relative_to(self.root.resolve())
        return rel.as_posix()

    def _config_fingerprint(self) -> str:
        parts: list[tuple] = []
        for p in self.config_paths:
            if not p.exists():
                parts.append((str(p), None, None))
                continue
            stat = p.stat()
            parts.append((str(p), stat.st_mtime, stat.st_size))
        return hashlib.sha1(
            json.dumps(parts, sort_keys=True).encode('utf-8')
        ).hexdigest()
