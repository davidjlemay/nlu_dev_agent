"""
Dialect Registry: loads engine-specific extensions from jsgf-dialect.json.

Supports:
- Custom functions ($functionName(args)) with typed parameter specs
- Typed flags ({key:type=value}) inside tags
- Reserved rule names and flag keys
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class DataSource:
    name: str
    type: str                                          # 'file' | 'inline' | 'command'
    path: str | None = None                            # for type='file'
    format: str = 'lines'                              # 'lines' | 'json'
    values: list[str] = field(default_factory=list)    # for type='inline'
    command: str | None = None                         # for type='command'
    args: list[str] = field(default_factory=list)


@dataclass
class LazyLoadingConfig:
    lookup_limit: int = 50
    expansion_limit: int = 200


@dataclass
class ParameterSpec:
    name: str
    type: str          # 'rule_ref' | 'string' | 'int' | 'float' | 'bool' | 'enum'
    optional: bool = False


@dataclass
class CustomFunction:
    name: str
    parameters: list[ParameterSpec]
    return_type: str   # 'expansion' | 'slot' | 'string'
    doc: str = ''


@dataclass
class DialectRegistry:
    engine: str
    functions: dict[str, CustomFunction] = field(default_factory=dict)
    reserved_rules: list[str] = field(default_factory=list)
    allowed_flag_types: list[str] = field(default_factory=list)
    reserved_flag_keys: list[str] = field(default_factory=list)
    allow_multiline_tags: bool = False
    value_interpolation: bool = False
    lhs_flags_enabled: bool = False
    lazy_loading: LazyLoadingConfig = field(default_factory=LazyLoadingConfig)
    data_sources: dict[str, DataSource] = field(default_factory=dict)

    @classmethod
    def from_config(cls, path: Path) -> DialectRegistry:
        data = json.loads(path.read_text())
        functions: dict[str, CustomFunction] = {}
        for name, spec in data.get('functions', {}).items():
            params = [
                ParameterSpec(
                    name=p['name'],
                    type=p['type'],
                    optional=p.get('optional', False),
                )
                for p in spec.get('parameters', [])
            ]
            functions[name] = CustomFunction(
                name=name,
                parameters=params,
                return_type=spec.get('return_type', 'expansion'),
                doc=spec.get('doc', ''),
            )
        flags = data.get('flags', {})
        tag_ext = data.get('tag_extensions', {})
        ll_raw = data.get('lazy_loading', {})
        lazy_loading = LazyLoadingConfig(
            lookup_limit=ll_raw.get('lookup_limit', 50),
            expansion_limit=ll_raw.get('expansion_limit', 200),
        )
        data_sources: dict[str, DataSource] = {}
        for src_name, src_spec in data.get('data_sources', {}).items():
            data_sources[src_name] = DataSource(
                name=src_name,
                type=src_spec.get('type', 'inline'),
                path=src_spec.get('path'),
                format=src_spec.get('format', 'lines'),
                values=src_spec.get('values', []),
                command=src_spec.get('command'),
                args=src_spec.get('args', []),
            )
        return cls(
            engine=data['engine'],
            functions=functions,
            reserved_rules=data.get('reserved_rules', []),
            allowed_flag_types=flags.get('allowed_types', []),
            reserved_flag_keys=flags.get('reserved_keys', []),
            allow_multiline_tags=tag_ext.get('allow_multiline', False),
            value_interpolation=tag_ext.get('value_interpolation', False),
            lhs_flags_enabled=flags.get('allow_lhs', False),
            lazy_loading=lazy_loading,
            data_sources=data_sources,
        )

    @classmethod
    def standard(cls) -> DialectRegistry:
        """No extensions; pure JSGF V1.0."""
        return cls(engine='standard-jsgf')

    def validate_flag(self, key: str, type_str: str, value: str) -> list[str]:
        """
        Validate a typed flag against the registry schema.
        Returns a list of error messages (empty if valid).
        """
        errors: list[str] = []
        if self.allowed_flag_types and type_str not in self.allowed_flag_types:
            errors.append(
                f"Flag type '{type_str}' is not allowed. "
                f"Allowed: {self.allowed_flag_types}"
            )
        return errors

    def validate_function_call(
        self, name: str, arg_count: int
    ) -> list[str]:
        """
        Validate a function call against the registry.
        Returns error messages (empty if valid).
        """
        errors: list[str] = []
        fn = self.functions.get(name)
        if fn is None:
            errors.append(f"Unknown dialect function: ${name}")
            return errors
        required = sum(1 for p in fn.parameters if not p.optional)
        total = len(fn.parameters)
        if arg_count < required or arg_count > total:
            errors.append(
                f"${name} expects {required}–{total} arguments, got {arg_count}"
            )
        return errors
