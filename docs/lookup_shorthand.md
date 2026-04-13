 Plan: Data Source Shorthand + Parameterized Rule Syntax Cleanup

 Previously completed

 Flag-filtered non-terminal lookups are fully implemented (149 tests passing).
 $lookup('source') and $lookup('source') inside flagged rules now load only
 the matching flagged subset from the data source.

 ---
 Context

 Two related syntax improvements, motivated by the same ambiguity:

 Problem: $identifier (no parens) was reserved for $param references inside
 parameterized rule bodies — but params don't need a special token if they're
 declared in [...] first. This blocks using $identifier as clean shorthand for
 $lookup('identifier').

 Solution:
 1. Move param body references to rule-ref syntax <param> (they're already
 logically rule refs substituted at call sites).
 2. Free up $identifier (no parens) as a lookup shorthand.

 ---
 Feature 1: Parameterized rules — <param> body syntax

 New syntax

 // Declaration: params are plain names ($ optional for backwards compat)
 public <transfer[from, to]> {currency:enum=usd} = transfer <from> to <to> in dollars;
 public <transfer[from, to]> {currency:enum=gbp} = transfer <from> to <to> in pounds;
 public <date_range[start, end]> = from <start> to <end> | between <start> and <end>;

 // Call sites unchanged
 public <my_transfer> = <transfer[<savings>, <chequing>]> {currency:enum=usd};
 public <booking>     = <date_range[<departure>, <return>]>;

 Design

 A new pre-pass _substitute_param_refs(source) runs before scan_positions,
 _mangle_source, and _strip_dialect_tags. It converts <param> → PARM_param
 inside each parameterized rule body, using the declared param list to scope the
 substitution correctly.

 Because substitution happens before scan_positions, param refs never appear in
 ref_positions — so the LSP and undefined-ref checks never see them as rule refs.

 _strip_dialect_tags Step 0b (currently $param → PARM_param) is repurposed
 for Feature 2 (see below). Old $param body syntax is dropped (breaking change
 on fixtures/tests, handled below).

 core/document.py changes

 New _PARAM_BODY_RE (module-level):
 _PARAM_BODY_RE = re.compile(
     r'(?:public\s+)?'
     r'<([A-Za-z0-9_.$-]+)'          # rule name (group 1)
     r'\[([^\]]+)\]'                  # [params] — required (group 2)
     r'>(?:\s*\{[^}]*\})*'            # optional LHS flags
     r'\s*=\s*'
     r'([^;]+)'                       # body (group 3)
     r';'
 )

 New _substitute_param_refs(source) -> tuple[str, dict[str, str]]:
 - Iterates over all _PARAM_BODY_RE matches
 - For each match: parse param names via _parse_params(group(2))
 - For each param, replace <param_name> in the body span with PARM_param_name
 (only within that match's body region, not globally)
 - Returns (modified_source, param_placeholder_map) where map is
 {PARM_from: 'from', ...} (informational, same shape as current field)
 - Body replacement: use re.sub(r'<(param_name)>', 'PARM_param_name', body_text)
 for each param; rejoin with the surrounding source

 _parse_params: keep lstrip('$') so [$from, $to] continues to parse
 correctly for backward compatibility with existing grammars.

 GrammarDocument.parse() — update call order:
 # New: param ref substitution before everything else
 param_subst_source, param_placeholder_map = _substitute_param_refs(source)

 # Scanning now sees PARM_from tokens instead of <from> refs
 ref_positions = scan_positions(param_subst_source)
 def_positions = scan_rule_def_positions(param_subst_source)

 # _PARAMS_SCAN_RE also runs on original source (param decl collection unchanged)
 # _mangle_source runs on param_subst_source
 mangled_source, pyjsgf_to_original, pyjsgf_to_pos, pyjsgf_to_flags = \
     _mangle_source(param_subst_source)

 # _strip_dialect_tags no longer needs param_map (Step 0b repurposed)
 stripped = _strip_dialect_tags(mangled_source, func_map=func_placeholders,
                                 call_site_map=param_call_sites)

 Remove param_map parameter from _strip_dialect_tags (it's now populated by the
 pre-pass). Pass param_placeholder_map directly to the constructor.

 ---
 Feature 2: $identifier shorthand for data source lookups

 New syntax

 public <bank> {region:enum=ca} = $banks;    // sugar for $lookup('banks')
 public <check_balance> = balance of $bank_names;

 Design

 Step 0b in _strip_dialect_tags, freed from param-ref duty, becomes the shorthand
 handler. $identifier (no parens) → PLHDRn with func_map[token] = ('lookup', [identifier]).

 # Step 0b: $identifier (no parens) → PLHDRn  (sugar for $lookup('identifier'))
 def _shorthand_replacer(m: re.Match) -> str:
     token = f'PLHDR{_func_counter[0]}'
     _func_counter[0] += 1
     if func_map is not None:
         func_map[token] = ('lookup', [m.group(1)])
     return token

 source = re.sub(r'\$([A-Za-z_][A-Za-z0-9_]*)\b(?!\()', _shorthand_replacer, source)

 Step 3 (explicit $fn(args)) runs after Step 0b. Since Step 3's pattern requires
 (, and Step 0b excludes (, they don't conflict. The shorthand step must come
 after Step 3 to let $lookup('banks') be handled explicitly first — swap their
 order. Final order: Step 3 then Step 0b-repurposed.

 The placeholder_flags post-pass and load_filtered in _generate_expansions
 already work correctly — the PLHDR token is identical regardless of whether it came
 from $lookup('banks') or $banks.

 Remove param_map parameter from _strip_dialect_tags signature (see Feature 1).

 ---
 Files to modify

 ┌───────────────────────────────────┬───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
 │               File                │                                                              Change                                                               │
 ├───────────────────────────────────┼───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
 │ core/document.py                  │ _substitute_param_refs(), _PARAM_BODY_RE, repurpose Step 0b, update parse() call order, remove param_map from _strip_dialect_tags │
 ├───────────────────────────────────┼───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
 │ tests/fixtures/parameterized.jsgf │ Update body syntax: $from → <from>, $to → <to>, etc.                                                                              │
 ├───────────────────────────────────┼───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
 │ tests/test_document.py            │ Update param-ref tests; add _substitute_param_refs tests; add shorthand tests                                                     │
 ├───────────────────────────────────┼───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
 │ tests/test_api.py                 │ Add shorthand coverage test                                                                                                       │
 └───────────────────────────────────┴───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘

 core/patch.py, core/validator.py, agent/api.py — no changes needed:
 - scan_positions sees PARM_ tokens after pre-pass, not <from> refs
 - Validator arity checks use _PARAM_DECL_RE / _PARAM_CALL_RE on doc.source (original) — unaffected
 - _generate_expansions uses the same PLHDR/PARM_ machinery regardless of source syntax

 ---
 New / updated tests

 tests/test_document.py
 - test_substitute_param_refs_basic — <transfer[from, to]> = transfer <from> to <to>;
 → <from> and <to> replaced with PARM_from, PARM_to in body; not in other rule bodies
 - test_substitute_param_refs_scoped — <from> in a non-parameterized rule is NOT replaced
 - test_substitute_param_refs_returns_map — returned map is {'PARM_from': 'from', 'PARM_to': 'to'}
 - test_param_ref_not_in_ref_positions — after parse, ref_positions has no entry for 'from'
 - test_shorthand_produces_plhdr — $banks in rule body → func_placeholders has ('lookup', ['banks'])
 - test_shorthand_and_explicit_lookup_coexist — $banks and $lookup('banks') both produce PLHDR entries with same lookup args
 - Update test_dollar_param_in_body_becomes_placeholder — rename/update to reflect new <param> syntax

 tests/test_api.py
 - test_validate_coverage_shorthand_lookup — $banks in body; coverage works same as $lookup('banks')

 ---
 Fixture updates

 tests/fixtures/parameterized.jsgf: replace $from → <from>, $to → <to>,
 $start → <start>, $end → <end> in rule bodies; update declarations to
 [from, to] etc. (drop $).

 ---
 Verification

 cd /home/david_lemay/nlu_dev_agent
 source .venv/bin/activate
 pytest tests/ -v
 # Expected: 149 existing + ~8 new = ~157 passing
