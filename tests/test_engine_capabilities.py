"""Tests for validate_engine_capabilities() in core/validator.py."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.document import GrammarDocument
from core.index import GrammarIndex
from core.dialect import DialectRegistry, EngineCapabilities
from core.validator import validate_engine_capabilities

FIXTURES = Path(__file__).parent / 'fixtures'
DIALECT_JSON = FIXTURES / 'jsgf-dialect.json'


def _make_dialect(**cap_kwargs) -> DialectRegistry:
    """Return a full dialect (from config) with overridden capabilities."""
    dialect = DialectRegistry.from_config(DIALECT_JSON)
    dialect.capabilities = EngineCapabilities(**cap_kwargs)
    return dialect


def _caps_diags(source: str, dialect: DialectRegistry, path: Path | None = None) -> list:
    """Parse *source* and return engine-capability diagnostics."""
    p = path or Path('/tmp/test_caps.jsgf')
    index = GrammarIndex(Path('/tmp'), dialect)
    index.update_file(p, source)
    doc = index._documents[p]
    return validate_engine_capabilities(doc, dialect, index)


# ------------------------------------------------------------------ #
#  Defaults — permissive, no regressions                              #
# ------------------------------------------------------------------ #

def test_default_capabilities_no_errors():
    """Permissive defaults must not produce any capability diagnostics."""
    dialect = DialectRegistry.from_config(DIALECT_JSON)
    source = """\
#JSGF V1.0;
grammar test;
public <greet> {intent:string=greet} = hello | hi;
public <bye>   {intent:string=bye}   = goodbye | bye;
"""
    diags = _caps_diags(source, dialect)
    assert diags == [], f"Unexpected: {[d.message for d in diags]}"


def test_standard_dialect_no_errors():
    """standard() dialect has permissive EngineCapabilities by default."""
    dialect = DialectRegistry.standard()
    source = """\
#JSGF V1.0;
grammar test;
public <greet> = hello | hi;
public <bye>   = goodbye;
"""
    diags = _caps_diags(source, dialect)
    assert diags == []


# ------------------------------------------------------------------ #
#  max_public_rules                                                   #
# ------------------------------------------------------------------ #

def test_max_public_rules_ok():
    dialect = _make_dialect(max_public_rules=2)
    source = """\
#JSGF V1.0;
grammar test;
public <a> = a;
public <b> = b;
"""
    diags = _caps_diags(source, dialect)
    assert diags == []


def test_max_public_rules_exceeded():
    dialect = _make_dialect(max_public_rules=1)
    source = """\
#JSGF V1.0;
grammar test;
public <a> = a;
public <b> = b;
"""
    diags = _caps_diags(source, dialect)
    errors = [d for d in diags if 'public rule' in d.message or 'exceeds' in d.message]
    assert len(errors) == 1
    assert '<b>' in errors[0].message


def test_max_public_rules_library_skipped():
    """A grammar imported by another is a library; max_public_rules is not checked."""
    dialect = _make_dialect(max_public_rules=1)
    tmp = Path('/tmp')
    index = GrammarIndex(tmp, dialect)

    lib_path = tmp / 'lib.jsgf'
    root_path = tmp / 'root.jsgf'

    lib_source = """\
#JSGF V1.0;
grammar lib;
public <a> = a;
public <b> = b;
"""
    root_source = """\
#JSGF V1.0;
grammar root;
import <lib.*>;
public <main> = <a> | <b>;
"""
    index.update_file(lib_path, lib_source)
    index.update_file(root_path, root_source)

    lib_doc = index._documents[lib_path]
    assert index.is_library(lib_path), "lib should be a library"
    lib_diags = validate_engine_capabilities(lib_doc, dialect, index)
    assert lib_diags == [], f"Library should skip max_public_rules: {[d.message for d in lib_diags]}"

    root_doc = index._documents[root_path]
    root_diags = validate_engine_capabilities(root_doc, dialect, index)
    assert root_diags == [], f"Root has 1 public rule: {[d.message for d in root_diags]}"


# ------------------------------------------------------------------ #
#  flags = "none"                                                     #
# ------------------------------------------------------------------ #

def test_flags_none_no_tags_ok():
    dialect = _make_dialect(flags="none")
    source = """\
#JSGF V1.0;
grammar test;
public <greet> = hello | hi;
"""
    diags = _caps_diags(source, dialect)
    assert diags == []


def test_flags_none_rhs_tag_errors():
    dialect = _make_dialect(flags="none")
    source = """\
#JSGF V1.0;
grammar test;
public <greet> = hello {intent:string=greet};
"""
    diags = _caps_diags(source, dialect)
    errors = [d for d in diags if 'does not support tags' in d.message]
    assert len(errors) == 1


def test_flags_none_lhs_tag_errors():
    dialect = DialectRegistry.from_config(DIALECT_JSON)
    dialect.capabilities = EngineCapabilities(flags="none")
    source = """\
#JSGF V1.0;
grammar test;
public <greet> {intent:string=greet} = hello | hi;
"""
    diags = _caps_diags(source, dialect)
    errors = [d for d in diags if 'does not support tags' in d.message]
    assert len(errors) == 1


# ------------------------------------------------------------------ #
#  flags = "lhs_only"                                                 #
# ------------------------------------------------------------------ #

def test_flags_lhs_only_rhs_tag_errors():
    dialect = _make_dialect(flags="lhs_only")
    source = """\
#JSGF V1.0;
grammar test;
public <greet> = hello {intent:string=greet};
"""
    diags = _caps_diags(source, dialect)
    errors = [d for d in diags if 'LHS flags' in d.message]
    assert len(errors) == 1


def test_flags_lhs_only_lhs_flag_ok():
    dialect = _make_dialect(flags="lhs_only")
    source = """\
#JSGF V1.0;
grammar test;
public <greet> {intent:string=greet} = hello | hi;
"""
    diags = _caps_diags(source, dialect)
    errors = [d for d in diags if 'LHS flags' in d.message or 'RHS' in d.message]
    assert errors == []


# ------------------------------------------------------------------ #
#  flags = "rhs_only"                                                 #
# ------------------------------------------------------------------ #

def test_flags_rhs_only_lhs_flag_errors():
    dialect = _make_dialect(flags="rhs_only")
    source = """\
#JSGF V1.0;
grammar test;
public <greet> {intent:string=greet} = hello | hi;
"""
    diags = _caps_diags(source, dialect)
    errors = [d for d in diags if 'LHS flags' in d.message]
    assert len(errors) == 1


def test_flags_rhs_only_rhs_tag_ok():
    dialect = _make_dialect(flags="rhs_only")
    source = """\
#JSGF V1.0;
grammar test;
public <greet> = hello {intent:string=greet};
"""
    diags = _caps_diags(source, dialect)
    errors = [d for d in diags if 'LHS flags' in d.message or 'RHS' in d.message]
    assert errors == []


# ------------------------------------------------------------------ #
#  function_map                                                       #
# ------------------------------------------------------------------ #

def test_function_map_none_all_allowed():
    """function_map=None means all functions pass through."""
    dialect = _make_dialect(function_map=None)
    source = """\
#JSGF V1.0;
grammar test;
public <bank> = $lookup(bank_names);
"""
    diags = _caps_diags(source, dialect)
    fn_errors = [d for d in diags if 'function' in d.message.lower()]
    assert fn_errors == []


def test_function_map_empty_blocks_all_functions():
    """function_map={} means no functions allowed."""
    dialect = _make_dialect(function_map={})
    source = """\
#JSGF V1.0;
grammar test;
public <bank> = $lookup(bank_names);
"""
    diags = _caps_diags(source, dialect)
    fn_errors = [d for d in diags if 'does not support function' in d.message]
    assert len(fn_errors) == 1
    assert 'lookup' in fn_errors[0].message


def test_function_map_subset_allowed():
    """Function in function_map is OK; one outside is an error."""
    dialect = _make_dialect(function_map={"lookup": "dict_lookup"})
    source = """\
#JSGF V1.0;
grammar test;
public <bank> = $lookup(bank_names);
public <amount> = $normalise(<amount>, usd);
"""
    diags = _caps_diags(source, dialect)
    fn_errors = [d for d in diags if 'does not support function' in d.message]
    assert len(fn_errors) == 1
    assert 'normalise' in fn_errors[0].message


# ------------------------------------------------------------------ #
#  allow_parameterized_rules                                          #
# ------------------------------------------------------------------ #

def test_parameterized_rules_allowed():
    dialect = _make_dialect(allow_parameterized_rules=True)
    source = """\
#JSGF V1.0;
grammar test;
public <transfer[$from, $to]> = transfer $from to $to;
"""
    diags = _caps_diags(source, dialect)
    param_errors = [d for d in diags if 'parameterized' in d.message]
    assert param_errors == []


def test_parameterized_rules_disallowed():
    dialect = _make_dialect(allow_parameterized_rules=False)
    source = """\
#JSGF V1.0;
grammar test;
public <transfer[$from, $to]> = transfer $from to $to;
"""
    diags = _caps_diags(source, dialect)
    param_errors = [d for d in diags if 'parameterized' in d.message]
    assert len(param_errors) == 1


# ------------------------------------------------------------------ #
#  agreement.jsgf smoke test (existing fixture)                       #
# ------------------------------------------------------------------ #

def test_agreement_fixture_default_caps_clean():
    """agreement.jsgf with permissive capabilities should produce no cap errors."""
    dialect = DialectRegistry.from_config(DIALECT_JSON)
    path = FIXTURES / 'agreement.jsgf'
    index = GrammarIndex(FIXTURES, dialect)
    index.update_file(path, path.read_text())
    doc = index._documents[path]
    diags = validate_engine_capabilities(doc, dialect, index)
    assert diags == [], f"Unexpected: {[d.message for d in diags]}"


def test_agreement_fixture_max_1_public_rule_fails():
    """agreement.jsgf has 4 public rules; max_public_rules=1 should flag 3."""
    dialect = DialectRegistry.from_config(DIALECT_JSON)
    dialect.capabilities = EngineCapabilities(max_public_rules=1)
    path = FIXTURES / 'agreement.jsgf'
    index = GrammarIndex(FIXTURES, dialect)
    index.update_file(path, path.read_text())
    doc = index._documents[path]
    diags = validate_engine_capabilities(doc, dialect, index)
    errors = [d for d in diags if 'exceeds' in d.message]
    assert len(errors) == 3, f"Expected 3 errors, got: {[d.message for d in errors]}"
