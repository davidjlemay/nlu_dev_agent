#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent.parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from agent.api import GrammarAgentAPI
from core.cerence_config import CerenceConfigLoader
from core.index import GrammarIndex
from core.loader import DataLoader
from core.validator import (
    validate_dialect,
    validate_engine_capabilities,
    validate_import_aliases,
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


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


class InProcessRunner:
    def __init__(self, lang: str, repo_root: Path):
        self.lang = lang
        self.repo_root = repo_root
        config_path = repo_root / '.devin' / 'config' / 'nlu_dev_agent' / f'{lang}.yaml'
        if not config_path.exists():
            raise FileNotFoundError(f'Missing config: {config_path}')
        ws = CerenceConfigLoader(config_path, repo_root).load()
        self.root = ws.workspace_root if ws.workspace_root.exists() else ws.jsgf_dirs[0]
        self.index = GrammarIndex(self.root, ws.dialect, ws.grammar_aliases, ws.grammar_overrides, ws.exclude_patterns)
        self.index.index_workspace()
        self.loader = DataLoader(ws.data_sources, ws.dialect.lazy_loading, self.root)
        self.api = GrammarAgentAPI(self.index, self.loader)

    def validate(self, file_path: Path, source: str | None = None) -> dict:
        if source is None:
            source = file_path.read_text(encoding='utf-8')
        self.index.update_file(file_path, source)
        doc = self.index._documents[file_path]
        diags = doc.get_diagnostics(self.index)
        diags += validate_dialect(doc, self.index.dialect)
        diags += validate_engine_capabilities(doc, self.index.dialect, self.index)
        diags += validate_import_aliases(doc, self.index)
        return {'ok': True, 'valid': len(diags) == 0, 'diagnostics': _diags_to_dicts(diags)}

    def coverage(self, rule: str, file_path: Path, utterances: list[str]) -> dict:
        result = self.api.validate_coverage(rule, file_path, utterances)
        return {'ok': True, **result.as_dict()}

    def context(self, file_path: Path, intent: str, examples: list[str], rule: str | None = None) -> dict:
        if rule:
            rule_examples = self.api.get_examples(rule, file_path, n=20)
            if rule_examples:
                examples = rule_examples
            if not intent:
                intent = rule
        ctx = self.api.get_generation_context(file_path, intent, examples)
        result = ctx.as_dict()
        if rule:
            result['rule'] = rule
        result['target_file'] = str(file_path)
        return {'ok': True, **result}

    def introspect(
        self,
        rule: str,
        file_path: Path,
        path: list[int] | None,
        utterances: list[str] | None,
        max_expansions: int,
    ) -> dict:
        try:
            result = self.api.introspect_rule(
                rule, file_path, path=path,
                utterances=utterances, max_expansions=max_expansions,
            )
            return {'ok': True, **result.as_dict()}
        except ValueError as exc:
            return {'ok': False, 'error': str(exc)}


def _run_daemon_action(cmd: dict, socket_path: str, timeout: float) -> dict | None:
    from devin_adapter.client import DaemonClient
    try:
        return DaemonClient(socket_path).call(cmd, timeout)
    except (FileNotFoundError, ConnectionError, OSError):
        return None


def _start_daemon(socket_path: str, repo_root: Path) -> None:
    daemon = Path(__file__).with_name('daemon.py')
    subprocess.Popen(
        [sys.executable, str(daemon), '--socket', socket_path, '--repo-root', str(repo_root)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description='nlu_dev_agent Devin CLI')
    parser.add_argument('--lang', '-l', default='')
    parser.add_argument('--action', '-a', required=True, choices=['validate', 'coverage', 'context', 'introspect', 'status', 'stop'])
    parser.add_argument('--file', '-f', default='.')
    parser.add_argument('--rule', '-r', default='top')
    parser.add_argument('--utterances', '-u', default='[]')
    parser.add_argument('--intent', '-i', default='')
    parser.add_argument('--examples', '-e', default='[]')
    parser.add_argument('--path', default='')
    parser.add_argument('--max-expansions', type=int, default=1000)
    parser.add_argument('--socket', '-s', default='.devin/tmp/nlu_dev_agent.sock')
    parser.add_argument('--start-daemon', action='store_true')
    parser.add_argument('--timeout', '-t', type=float, default=60.0)
    args = parser.parse_args()

    repo_root = _repo_root()
    file_path = Path(args.file).resolve()

    cmd = {
        'action': args.action,
        'lang': args.lang,
        'file': str(file_path),
    }
    if args.action == 'coverage':
        cmd['rule'] = args.rule
        cmd['utterances'] = json.loads(args.utterances)
    if args.action == 'context':
        cmd['intent'] = args.intent
        cmd['examples'] = json.loads(args.examples)
        if args.rule:
            cmd['rule'] = args.rule
    if args.action == 'introspect':
        cmd['rule'] = args.rule
        cmd['path'] = [int(p) for p in args.path.split('.') if args.path] if args.path else None
        cmd['utterances'] = json.loads(args.utterances)
        cmd['max_expansions'] = args.max_expansions

    if args.start_daemon:
        _start_daemon(args.socket, repo_root)

    resp = _run_daemon_action(cmd, args.socket, args.timeout)
    if resp is None and args.action in ('validate', 'coverage', 'context', 'introspect'):
        runner = InProcessRunner(args.lang, repo_root)
        if args.action == 'validate':
            resp = runner.validate(file_path)
        elif args.action == 'coverage':
            utterances = json.loads(args.utterances)
            resp = runner.coverage(args.rule, file_path, utterances)
        elif args.action == 'introspect':
            path = [int(p) for p in args.path.split('.') if args.path] if args.path else None
            utterances = json.loads(args.utterances)
            resp = runner.introspect(args.rule, file_path, path, utterances, args.max_expansions)
        else:
            examples = json.loads(args.examples)
            resp = runner.context(file_path, args.intent, examples, rule=args.rule)

    if resp is None:
        resp = {'ok': False, 'error': 'daemon not available'}

    print(json.dumps(resp, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
