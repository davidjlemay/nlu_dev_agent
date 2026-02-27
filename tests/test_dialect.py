"""Tests for core/dialect.py — DialectRegistry."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.dialect import DialectRegistry, CustomFunction, ParameterSpec

DIALECT_JSON = Path(__file__).resolve().parent.parent / 'jsgf-dialect.json'


def test_load_from_config():
    registry = DialectRegistry.from_config(DIALECT_JSON)
    assert registry.engine == 'proprietary-asr-v2'
    assert 'normalise' in registry.functions
    assert 'lookup' in registry.functions
    assert 'extract' in registry.functions


def test_standard_dialect():
    registry = DialectRegistry.standard()
    assert registry.engine == 'standard-jsgf'
    assert registry.functions == {}
    assert registry.allowed_flag_types == []


def test_flag_types():
    registry = DialectRegistry.from_config(DIALECT_JSON)
    assert 'string' in registry.allowed_flag_types
    assert 'bool' in registry.allowed_flag_types
    assert 'enum' in registry.allowed_flag_types


def test_validate_flag_valid():
    registry = DialectRegistry.from_config(DIALECT_JSON)
    errors = registry.validate_flag('intent', 'string', 'greet')
    assert errors == []


def test_validate_flag_invalid_type():
    registry = DialectRegistry.from_config(DIALECT_JSON)
    errors = registry.validate_flag('intent', 'unknown_type', 'greet')
    assert len(errors) == 1
    assert 'unknown_type' in errors[0]


def test_validate_function_call_valid():
    registry = DialectRegistry.from_config(DIALECT_JSON)
    errors = registry.validate_function_call('normalise', 2)
    assert errors == []


def test_validate_function_call_wrong_arity():
    registry = DialectRegistry.from_config(DIALECT_JSON)
    errors = registry.validate_function_call('normalise', 1)
    assert len(errors) == 1
    assert 'normalise' in errors[0]


def test_validate_function_call_optional_param():
    registry = DialectRegistry.from_config(DIALECT_JSON)
    # lookup has 1 required + 1 optional; calling with 1 arg is valid
    errors = registry.validate_function_call('lookup', 1)
    assert errors == []
    errors2 = registry.validate_function_call('lookup', 2)
    assert errors2 == []


def test_validate_function_call_unknown():
    registry = DialectRegistry.from_config(DIALECT_JSON)
    errors = registry.validate_function_call('nonexistent', 0)
    assert len(errors) == 1
    assert 'nonexistent' in errors[0]


def test_reserved_rules():
    registry = DialectRegistry.from_config(DIALECT_JSON)
    assert 'VOID' in registry.reserved_rules
    assert 'NULL' in registry.reserved_rules
