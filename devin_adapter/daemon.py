#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import socket
import socketserver
import sys
import threading
from pathlib import Path

_HERE = Path(__file__).resolve().parent.parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from agent.api import GrammarAgentAPI
from core.cerence_config import CerenceConfigLoader
from core.index import GrammarIndex
from core.loader import DataLoader
from core.workspace_cache import WorkspaceCache
from core.validator import (
    validate_dialect,
    validate_engine_capabilities,
    validate_import_aliases,
)


class NluDevAgentServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True

    def __init__(
        self,
        socket_path: Path,
        repo_root: Path,
        cache_dir: Path | None = None,
    ):
        self.socket_path = Path(socket_path)
        self.repo_root = Path(repo_root)
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self._lock = threading.Lock()
        self._indices: dict[str, tuple[GrammarIndex, GrammarAgentAPI]] = {}
        if self.socket_path.exists():
            self.socket_path.unlink()
        self.socket_path.parent.mkdir(parents=True, exist_ok=True)
        super().__init__(str(self.socket_path), NluDevAgentHandler)

    def _load_lang(self, lang: str) -> tuple[GrammarIndex, GrammarAgentAPI]:
        with self._lock:
            if lang in self._indices:
                return self._indices[lang]
            config_path = self.repo_root / '.devin' / 'config' / 'nlu_dev_agent' / f'{lang}.yaml'
            if not config_path.exists():
                raise FileNotFoundError(f'No nlu_dev_agent config for {lang}: {config_path}')
            ws = CerenceConfigLoader(config_path, self.repo_root).load()
            root = ws.workspace_root if ws.workspace_root.exists() else ws.jsgf_dirs[0]
            index = GrammarIndex(root, ws.dialect, ws.grammar_aliases, ws.grammar_overrides, ws.exclude_patterns)
            if self.cache_dir:
                cache = WorkspaceCache(
                    self.cache_dir / lang,
                    root,
                    [ws.config_path, ws.dialect_path, ws.features_json, ws.jsgf_stark],
                )
                index.index_workspace_from_cache(cache)
            else:
                index.index_workspace()
            data_loader = DataLoader(ws.data_sources, ws.dialect.lazy_loading, root)
            api = GrammarAgentAPI(index, data_loader)
            self._indices[lang] = (index, api)

        threading.Thread(
            target=index._pre_resolve_all,
            daemon=True,
            name=f'pre-resolve-{lang}',
        ).start()
        return index, api

    def dispatch(self, cmd: dict) -> dict:
        action = cmd.get('action')
        lang = cmd.get('lang')

        if action == 'status':
            return {'ok': True, 'langs': list(self._indices.keys())}
        if action == 'stop':
            threading.Thread(target=self.shutdown).start()
            return {'ok': True}

        if not lang:
            return {'ok': False, 'error': 'missing lang'}

        index, api = self._load_lang(lang)

        if action == 'validate':
            return self._do_validate(index, cmd)
        if action == 'coverage':
            return self._do_coverage(api, cmd)
        if action == 'context':
            return self._do_context(api, cmd)
        if action == 'introspect':
            return self._do_introspect(api, cmd)
        if action == 'index':
            return self._do_index(index, cmd)

        return {'ok': False, 'error': f'unknown action: {action}'}

    def _do_validate(self, index: GrammarIndex, cmd: dict) -> dict:
        file_path = Path(cmd['file']).resolve()
        index.ensure_resolved(file_path)
        source = cmd.get('source')
        if source is None:
            source = file_path.read_text(encoding='utf-8')
        index.update_file(file_path, source)
        doc = index._documents[file_path]
        diags = doc.get_diagnostics(index)
        diags += validate_dialect(doc, index.dialect)
        diags += validate_engine_capabilities(doc, index.dialect, index)
        diags += validate_import_aliases(doc, index)
        return {'ok': True, 'valid': len(diags) == 0, 'diagnostics': _diags_to_dicts(diags)}

    def _do_coverage(self, api: GrammarAgentAPI, cmd: dict) -> dict:
        rule = cmd['rule']
        file_path = Path(cmd['file']).resolve()
        api.index.ensure_resolved(file_path)
        utterances = cmd.get('utterances', [])
        result = api.validate_coverage(rule, file_path, utterances)
        return {'ok': True, **result.as_dict()}

    def _do_context(self, api: GrammarAgentAPI, cmd: dict) -> dict:
        file_path = Path(cmd['file']).resolve()
        api.index.ensure_resolved(file_path)
        intent = cmd.get('intent', '')
        examples = cmd.get('examples', [])
        rule = cmd.get('rule')
        if rule:
            rule_examples = api.get_examples(rule, file_path, n=20)
            if rule_examples:
                examples = rule_examples
            if not intent:
                intent = rule
        ctx = api.get_generation_context(file_path, intent, examples)
        result = ctx.as_dict()
        if rule:
            result['rule'] = rule
        result['target_file'] = str(file_path)
        return {'ok': True, **result}

    def _do_introspect(self, api: GrammarAgentAPI, cmd: dict) -> dict:
        rule = cmd['rule']
        file_path = Path(cmd['file']).resolve()
        api.index.ensure_resolved(file_path)
        path = cmd.get('path')
        if isinstance(path, str):
            path = [int(p) for p in path.split('.') if p] if path else None
        elif isinstance(path, list):
            path = [int(p) for p in path]
        utterances = cmd.get('utterances', [])
        max_expansions = cmd.get('max_expansions', 1000)
        try:
            result = api.introspect_rule(
                rule, file_path, path=path, utterances=utterances,
                max_expansions=max_expansions,
            )
            return {'ok': True, **result.as_dict()}
        except ValueError as exc:
            return {'ok': False, 'error': str(exc)}

    def _do_index(self, index: GrammarIndex, cmd: dict) -> dict:
        file_path = Path(cmd['file']).resolve()
        source = cmd.get('source')
        if source is None:
            source = file_path.read_text(encoding='utf-8')
        index.update_file(file_path, source)
        return {'ok': True}


class NluDevAgentHandler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        try:
            line = self.rfile.readline()
            if not line:
                return
            cmd = json.loads(line.decode('utf-8'))
            resp = self.server.dispatch(cmd)
        except Exception as exc:
            resp = {'ok': False, 'error': str(exc)}
        self.wfile.write((json.dumps(resp, ensure_ascii=False) + '\n').encode('utf-8'))


def _diags_to_dicts(diags: list) -> list[dict]:
    severity_map = {1: 'error', 2: 'warning', 3: 'information', 4: 'hint'}
    result: list[dict] = []
    for d in diags:
        severity = d.severity
        value = severity.value if hasattr(severity, 'value') else severity
        result.append({
            'line': d.range.start.line,
            'character': d.range.start.character,
            'severity': severity_map.get(value, 'error'),
            'message': d.message,
        })
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description='nlu_dev_agent Devin daemon')
    parser.add_argument('--socket', '-s', default='.devin/tmp/nlu_dev_agent.sock')
    parser.add_argument('--repo-root', '-r', default=str(Path.cwd()))
    parser.add_argument(
        '--cache-dir',
        default=os.environ.get('NLU_DEV_AGENT_CACHE_DIR'),
        help='Directory for per-language GrammarDocument caches',
    )
    args = parser.parse_args()

    cache_dir = Path(args.cache_dir) if args.cache_dir else None
    server = NluDevAgentServer(Path(args.socket), Path(args.repo_root), cache_dir)
    try:
        server.serve_forever()
    finally:
        server.socket_path.unlink(missing_ok=True)


if __name__ == '__main__':
    main()
