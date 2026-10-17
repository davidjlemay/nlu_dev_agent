from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .dialect import DataSource, DialectRegistry, LazyLoadingConfig


@dataclass
class CerenceWorkspace:
    lang: str
    workspace_root: Path
    jsgf_dirs: list[Path]
    gazetteer_dirs: list[Path]
    dialect: DialectRegistry
    data_sources: dict[str, DataSource]
    jsgf_stark: Path | None
    gazetteer_stark: Path | None
    features_json: Path | None
    grammar_aliases: dict[str, str] = field(default_factory=dict)
    grammar_overrides: dict[str, str] = field(default_factory=dict)


_JSGF_STARK_BLOCK_RE = re.compile(
    r'"([^"]+)"\s*\{(.*?)\}',
    re.DOTALL,
)

_GAZETTEER_REF_RE = re.compile(
    r'gazetteers\.(?:"([^"]+)"|([A-Za-z0-9_]+))',
    re.DOTALL,
)

_NTFILE_GAZ_RE = re.compile(
    r'ntFile\s*\(\s*file\s*\([^)]*?"([^"]+\.gaz)"\s*\)\s*\)',
    re.IGNORECASE,
)


class CerenceConfigLoader:
    def __init__(self, config_path: Path, repo_root: Path = Path('.')):
        self.config_path = config_path.resolve()
        self.repo_root = repo_root.resolve()

    def load(self) -> CerenceWorkspace:
        raw = yaml.safe_load(self.config_path.read_text(encoding='utf-8'))
        if raw is None:
            raw = {}

        lang = raw.get('lang', self.config_path.stem)
        base_dialect = raw.get('base_dialect', 'nlu_dev_agent/dialects/cerence/cerence.json')
        dialect_path = self._resolve(base_dialect)
        dialect = DialectRegistry.from_config(dialect_path)

        ws_root = self._resolve(raw.get('workspace_root', f'resources/anno-lang/{lang}/CTagger/data/jsgf'))
        jsgf_dirs = [self._resolve(p) for p in raw.get('jsgf_dirs', [str(ws_root)])]
        jsgf_dirs += [self._resolve(p) for p in raw.get('common_jsgf_dirs', [])]
        gazetteer_dirs = [self._resolve(p) for p in raw.get('gazetteer_dirs', [f'resources/anno-lang/{lang}/CTagger/data/gazetteers'])]
        gazetteer_dirs += [self._resolve(p) for p in raw.get('common_gazetteer_dirs', [])]

        jsgf_stark = self._resolve_or_none(raw.get('jsgf_stark', f'resources/anno-lang/{lang}/jsgf.stark'))
        gazetteer_stark = self._resolve_or_none(raw.get('gazetteer_stark', f'resources/anno-lang/{lang}/gazetteer.stark'))
        features_json = self._resolve_or_none(raw.get('features_json', f'resources/anno-lang/{lang}/CTagger/config/genfromjsgf-specs/features.json'))

        if features_json:
            dialect.avm_features = _load_features(features_json)

        ll_raw = raw.get('lazy_loading', {})
        dialect.lazy_loading = LazyLoadingConfig(
            lookup_limit=ll_raw.get('lookup_limit', dialect.lazy_loading.lookup_limit),
            expansion_limit=ll_raw.get('expansion_limit', dialect.lazy_loading.expansion_limit),
        )

        data_sources = self._build_data_sources(jsgf_stark, gazetteer_dirs, raw.get('slot_map', {}), raw.get('gazetteer_overrides', {}))
        grammar_aliases = raw.get('grammar_aliases', {})
        grammar_overrides = raw.get('grammar_overrides', {})

        return CerenceWorkspace(
            lang=lang,
            workspace_root=ws_root,
            jsgf_dirs=jsgf_dirs,
            gazetteer_dirs=gazetteer_dirs,
            dialect=dialect,
            data_sources=data_sources,
            jsgf_stark=jsgf_stark,
            gazetteer_stark=gazetteer_stark,
            features_json=features_json,
            grammar_aliases=grammar_aliases,
            grammar_overrides=grammar_overrides,
        )

    def _resolve(self, path: str) -> Path:
        p = Path(path)
        if p.is_absolute():
            return p.resolve()
        if (self.repo_root / p).exists():
            return (self.repo_root / p).resolve()
        if (self.config_path.parent / p).exists():
            return (self.config_path.parent / p).resolve()
        return (self.repo_root / p).resolve()

    def _resolve_or_none(self, path: str | None) -> Path | None:
        if not path:
            return None
        p = self._resolve(path)
        return p if p.exists() else None

    def _build_data_sources(
        self,
        jsgf_stark: Path | None,
        gazetteer_dirs: list[Path],
        slot_map: dict[str, str],
        gazetteer_overrides: dict[str, str],
    ) -> dict[str, DataSource]:
        sources: dict[str, DataSource] = {}
        if jsgf_stark is None or not jsgf_stark.exists():
            return sources

        nt_to_gaz = _parse_jsgf_stark(jsgf_stark)
        for nt_name, gaz_name in nt_to_gaz.items():
            source_name = slot_map.get(nt_name, nt_name)
            if gaz_name.startswith('git.'):
                gaz_name = gaz_name[4:]
            gaz_name = gazetteer_overrides.get(gaz_name, gaz_name)
            gaz_file = _find_gazetteer(gaz_name, gazetteer_dirs)
            if gaz_file:
                sources[source_name] = DataSource(
                    name=source_name,
                    type='file',
                    path=str(gaz_file),
                    format='lines',
                )
        return sources


def _load_features(path: Path) -> dict[str, list[str]]:
    data = json.loads(path.read_text(encoding='utf-8'))
    features: dict[str, list[str]] = {}
    for key, value in data.items():
        if isinstance(value, list):
            features[key] = [str(v) for v in value]
    return features


def _parse_jsgf_stark(path: Path) -> dict[str, str]:
    text = path.read_text(encoding='utf-8')
    result: dict[str, str] = {}
    for block_m in _JSGF_STARK_BLOCK_RE.finditer(text):
        nt_name = block_m.group(1)
        body = block_m.group(2)
        gaz_m = _GAZETTEER_REF_RE.search(body)
        nt_m = _NTFILE_GAZ_RE.search(body)
        if gaz_m:
            result[nt_name] = gaz_m.group(1) or gaz_m.group(2)
        elif nt_m:
            result[nt_name] = nt_m.group(1)
    return result


def _find_gazetteer(gaz_name: str, dirs: list[Path]) -> Path | None:
    for d in dirs:
        if gaz_name.endswith('.gaz') or '/' in gaz_name or '\\' in gaz_name:
            candidate = d / gaz_name
        else:
            candidate = d / f'{gaz_name}.gaz'
        if candidate.exists():
            return candidate
    return None
