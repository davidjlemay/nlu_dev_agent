"""Tests for core/validator.py — LHS flag validation."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.document import GrammarDocument
from core.index import GrammarIndex
from core.dialect import DialectRegistry

FIXTURES = Path(__file__).parent / 'fixtures'
DIALECT_JSON = Path(__file__).resolve().parent.parent / 'jsgf-dialect.json'


def _diags(source: str, dialect: DialectRegistry) -> list:
    path = Path('/tmp/test_validator.gram')
    index = GrammarIndex(Path('/tmp'), dialect)
    index.update_file(path, source)
    doc = index._documents[path]
    # get_diagnostics returns structural diags; dialect diags come from
    # validate_dialect which is wired in via GrammarIndex
    from core.validator import validate_dialect
    return validate_dialect(doc, dialect)


# ------------------------------------------------------------------ #
#  LHS flag — dialect enabled                                         #
# ------------------------------------------------------------------ #

def test_lhs_flag_accepted_when_enabled():
    dialect = DialectRegistry.from_config(DIALECT_JSON)
    assert dialect.lhs_flags_enabled is True

    source = """\
#JSGF V1.0;
grammar test;
public <item> {number:enum=singular} = book | pen;
"""
    diags = _diags(source, dialect)
    errors = [d for d in diags if 'LHS' in d.message or 'allow_lhs' in d.message]
    assert errors == [], f"Unexpected LHS errors: {[d.message for d in errors]}"


def test_lhs_flag_type_validated():
    dialect = DialectRegistry.from_config(DIALECT_JSON)
    source = """\
#JSGF V1.0;
grammar test;
public <item> {number:badtype=singular} = book;
"""
    diags = _diags(source, dialect)
    type_errors = [d for d in diags if 'badtype' in d.message]
    assert len(type_errors) == 1


def test_multiple_lhs_flags_accepted():
    dialect = DialectRegistry.from_config(DIALECT_JSON)
    source = """\
#JSGF V1.0;
grammar test;
public <item> {number:enum=singular} {intent:string=pick_item} = book | pen;
"""
    diags = _diags(source, dialect)
    errors = [d for d in diags if 'LHS' in d.message]
    assert errors == []


# ------------------------------------------------------------------ #
#  LHS flag — dialect disabled                                        #
# ------------------------------------------------------------------ #

def test_lhs_flag_rejected_when_disabled():
    dialect = DialectRegistry.standard()
    assert dialect.lhs_flags_enabled is False

    source = """\
#JSGF V1.0;
grammar test;
public <item> {number:enum=singular} = book | pen;
"""
    diags = _diags(source, dialect)
    errors = [d for d in diags if 'LHS flags are not enabled' in d.message]
    assert len(errors) == 1


def test_multiple_lhs_flags_all_rejected_when_disabled():
    dialect = DialectRegistry.standard()
    source = """\
#JSGF V1.0;
grammar test;
public <item> {number:enum=singular} {intent:string=pick} = book;
"""
    diags = _diags(source, dialect)
    errors = [d for d in diags if 'LHS flags are not enabled' in d.message]
    assert len(errors) == 2  # one diagnostic per flag block


# ------------------------------------------------------------------ #
#  RHS tags still validated normally                                  #
# ------------------------------------------------------------------ #

def test_rhs_tag_type_still_validated():
    dialect = DialectRegistry.from_config(DIALECT_JSON)
    source = """\
#JSGF V1.0;
grammar test;
public <item> = book {number:badtype=singular};
"""
    diags = _diags(source, dialect)
    type_errors = [d for d in diags if 'badtype' in d.message]
    assert len(type_errors) == 1


def test_rhs_tag_with_lhs_flag_both_validated():
    """Rule with LHS flag and RHS tag: both are checked independently."""
    dialect = DialectRegistry.from_config(DIALECT_JSON)
    source = """\
#JSGF V1.0;
grammar test;
public <item> {number:enum=singular} = book {intent:string=pick_item};
"""
    diags = _diags(source, dialect)
    # Both flags are valid — expect no errors
    assert diags == []


# ------------------------------------------------------------------ #
#  Agreement fixture                                                  #
# ------------------------------------------------------------------ #

def test_agreement_fixture_valid():
    dialect = DialectRegistry.from_config(DIALECT_JSON)
    path = FIXTURES / 'agreement.gram'
    index = GrammarIndex(FIXTURES, dialect)
    index.update_file(path, path.read_text())
    doc = index._documents[path]

    from core.validator import validate_dialect
    diags = validate_dialect(doc, dialect)
    assert diags == [], f"Unexpected diagnostics: {[d.message for d in diags]}"


def test_agreement_fixture_parses_four_rules():
    dialect = DialectRegistry.from_config(DIALECT_JSON)
    path = FIXTURES / 'agreement.gram'
    doc = GrammarDocument.parse(path, path.read_text())
    assert doc.parse_error is None
    assert len(doc.rules) == 4
    names = doc.rule_names()
    assert 'item_singular' in names
    assert 'verb_plural' in names


# ------------------------------------------------------------------ #
#  Parameterized rule arity checks                                     #
# ------------------------------------------------------------------ #

def test_parameterized_arity_ok():
    """Call site with correct arg count → no arity error."""
    dialect = DialectRegistry.from_config(DIALECT_JSON)
    source = """\
#JSGF V1.0;
grammar test;
public <transfer[$from, $to]> {currency:enum=usd} = transfer $from to $to;
public <savings>  = savings account;
public <chequing> = chequing account;
public <my_transfer> = <transfer[<savings>, <chequing>]> {currency:enum=usd};
"""
    diags = _diags(source, dialect)
    arity_errors = [d for d in diags if 'argument' in d.message]
    assert arity_errors == [], f"Unexpected arity errors: {[d.message for d in arity_errors]}"


def test_parameterized_arity_mismatch():
    """Call site with wrong arg count → error diagnostic."""
    dialect = DialectRegistry.from_config(DIALECT_JSON)
    source = """\
#JSGF V1.0;
grammar test;
public <transfer[$from, $to]> {currency:enum=usd} = transfer $from to $to;
public <savings>  = savings account;
public <bad_call> = <transfer[<savings>]> {currency:enum=usd};
"""
    diags = _diags(source, dialect)
    arity_errors = [d for d in diags if 'argument' in d.message and 'transfer' in d.message]
    assert len(arity_errors) == 1
    assert '2' in arity_errors[0].message   # expected 2
    assert '1' in arity_errors[0].message   # got 1


def test_parameterized_arity_unflagged_mismatch():
    """Unflagged parameterized call site with wrong arg count → error."""
    dialect = DialectRegistry.standard()
    source = """\
#JSGF V1.0;
grammar test;
public <date_range[$start, $end]> = from $start to $end;
public <dep> = departure;
public <bad_booking> = <date_range[<dep>]>;
"""
    diags = _diags(source, dialect)
    arity_errors = [d for d in diags if 'argument' in d.message and 'date_range' in d.message]
    assert len(arity_errors) == 1


def test_parameterized_fixture_no_arity_errors():
    """The parameterized.gram fixture should have no arity errors."""
    dialect = DialectRegistry.from_config(DIALECT_JSON)
    path = FIXTURES / 'parameterized.gram'
    index = GrammarIndex(FIXTURES, dialect)
    index.update_file(path, path.read_text())
    doc = index._documents[path]

    from core.validator import validate_dialect
    diags = validate_dialect(doc, dialect)
    arity_errors = [d for d in diags if 'argument' in d.message]
    assert arity_errors == [], f"Unexpected arity errors: {[d.message for d in arity_errors]}"
