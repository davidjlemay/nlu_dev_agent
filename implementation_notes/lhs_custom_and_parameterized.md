 Plan: LHS Flags on Custom Functions and Parameterized Rules                                                                                                                                                  │
│                                                                                                                                                                                                              │
│ Context                                                                                                                                                                                                      │
│                                                                                                                                                                                                              │
│ The last commit added LHS flags on rule references in rule bodies (e.g. <noun> {number:enum=plural}). Section 5.3 of the design doc specifies parameterized rules — rules whose names carry an argument list │
│  inside the angle brackets: <transfer[$from, $to]>. This feature is not yet implemented (validator.py notes it as a stub). The task is to:                                                                   │
│                                                                                                                                                                                                              │
│ 1. Verify (with tests) that rules using custom function bodies work correctly with LHS flags on declaration and reference — the code path likely already works.                                              │
│ 2. Implement parameterized rule syntax (§5.3) with LHS flag integration from the start.                                                                                                                      │
│                                                                                                                                                                                                              │
│ ---                                                                                                                                                                                                          │
│ Parameterized Rule Syntax (§5.3)                                                                                                                                                                             │
│                                                                                                                                                                                                              │
│ # Declaration — params inside angle brackets, optional LHS flags after >                                                                                                                                     │
│ public <transfer[$from, $to]> {currency:enum=usd} = transfer $from to $to;                                                                                                                                   │
│ public <transfer[$from, $to]> {currency:enum=gbp} = transfer $from to $to in pounds;                                                                                                                         │
│                                                                                                                                                                                                              │
│ # Unflagged declaration (no LHS flags)                                                                                                                                                                       │
│ public <date_range[$start, $end]> = from $start to $end;                                                                                                                                                     │
│                                                                                                                                                                                                              │
│ # Call site — args inside angle brackets, optional LHS flags after >                                                                                                                                         │
│ public <my_transfer> = <transfer[<savings>, <chequing>]> {currency:enum=usd};                                                                                                                                │
│ public <booking>     = <date_range[<departure>, <return>]>;                                                                                                                                                  │
│                                                                                                                                                                                                              │
│ Params are lexically substituted at the call site by the runtime engine. The LSP/parser treats them as opaque for pyjsgf purposes.                                                                           │
│                                                                                                                                                                                                              │
│ ---                                                                                                                                                                                                          │
│ Design: pyjsgf Neutralization Strategy                                                                                                                                                                       │
│                                                                                                                                                                                                              │
│ pyjsgf understands none of this syntax. The two-stage approach:                                                                                                                                              │
│                                                                                                                                                                                                              │
│ _mangle_source() handles flagged cases (LHS flags present):                                                                                                                                                  │
│ - <transfer[$p, $q]> {currency:enum=usd} = → mangles name, drops params in output: <transfer__currency_usd> {currency:enum=usd} =                                                                            │
│ - Flagged call sites <transfer[<a>, <b>]> {currency:enum=usd} → resolved to <transfer__currency_usd> (params consumed)                                                                                       │
│                                                                                                                                                                                                              │
│ _strip_dialect_tags() handles unflagged cases and residue:                                                                                                                                                   │
│ - Step 0: (<name)[args]> → \1> — strip [...] from inside any <...> (both decls and call sites without flags)                                                                                                 │
│ - Step 0b: $param references in bodies (no parens) → PARAM literal (distinct from $func(...) → PLACEHOLDER)                                                                                                  │
│                                                                                                                                                                                                              │
│ ---                                                                                                                                                                                                          │
│ Files to Modify                                                                                                                                                                                              │
│                                                                                                                                                                                                              │
│ core/patch.py                                                                                                                                                                                                │
│                                                                                                                                                                                                              │
│ Update both regexes to skip optional [...] inside angle brackets:                                                                                                                                            │
│                                                                                                                                                                                                              │
│ # scan_positions: capture base name only                                                                                                                                                                     │
│ r'<([A-Za-z0-9_.$-]+)(?:\[[^\]]*\])?>'                                                                                                                                                                       │
│                                                                                                                                                                                                              │
│ # scan_rule_def_positions: skip params and LHS flag blocks                                                                                                                                                   │
│ r'(?:public\s+)?<([A-Za-z0-9_.$-]+)(?:\[[^\]]*\])?>(?:\s*\{[^}]*\})*\s*='                                                                                                                                    │
│                                                                                                                                                                                                              │
│ core/document.py                                                                                                                                                                                             │
│                                                                                                                                                                                                              │
│ _strip_dialect_tags() — two new steps inserted before Step 1:                                                                                                                                                │
│ # Step 0: strip [args] from inside angle brackets (both decls and call sites)                                                                                                                                │
│ source = re.sub(r'(<[A-Za-z0-9_.$-]+)\[[^\]]*\]>', r'\1>', source)                                                                                                                                           │
│ # Step 0b: replace bare $param refs (not function calls) with PARAM literal                                                                                                                                  │
│ source = re.sub(r'\$[A-Za-z_][A-Za-z0-9_]*(?!\()', 'PARAM', source)                                                                                                                                          │
│                                                                                                                                                                                                              │
│ _LHS_DECL_RE — add optional (?P<params>\[[^\]]*\])? after the rule name (inside the <>):                                                                                                                     │
│ _LHS_DECL_RE = re.compile(                                                                                                                                                                                   │
│     r'(?P<pub>(?:public\s+)?)'                                                                                                                                                                               │
│     r'<(?P<rulename>[A-Za-z0-9_.$-]+)'                                                                                                                                                                       │
│     r'(?P<params>\[[^\]]*\])?'      # optional [$param1, $param2]                                                                                                                                            │
│     r'>'                                                                                                                                                                                                     │
│     r'(?P<flags>(?:\s*\{[^}]*\})+)'                                                                                                                                                                          │
│     r'(?P<eq>\s*=)'                                                                                                                                                                                          │
│ )                                                                                                                                                                                                            │
│ Replacer drops params — they are not needed by pyjsgf (already {flags} in output, stripped by _strip_dialect_tags() Step 1).                                                                                 │
│                                                                                                                                                                                                              │
│ _FLAGGED_REF_RE — consume optional [args] inside the angle bracket (between name and >):                                                                                                                     │
│ _FLAGGED_REF_RE = re.compile(                                                                                                                                                                                │
│     r'<([A-Za-z0-9_.$-]+)'   # base rule name                                                                                                                                                                │
│     r'(?:\[[^\]]*\])?'        # optional [args] at call site (consumed)                                                                                                                                      │
│     r'>'                                                                                                                                                                                                     │
│     r'((?:\s*\{[^}]*\})+)'   # one or more flag blocks                                                                                                                                                       │
│     r'(?!\s*=)'               # NOT followed by '='                                                                                                                                                          │
│ )                                                                                                                                                                                                            │
│                                                                                                                                                                                                              │
│ Bare-ref post-pass — update the regex to also handle parameterized refs:                                                                                                                                     │
│ re.sub(r'<([A-Za-z0-9_.$-]+)(?:\[[^\]]*\])?>(?!\s*(?:\{[^}]*\}\s*)*=)',                                                                                                                                      │
│        _ref_replacer, mangled_source)                                                                                                                                                                        │
│ _ref_replacer matches by base name (group 1); returns <mangled_name> (dropping params) for unambiguous flagged rules, else m.group(0) (preserving [args] for _strip_dialect_tags() to clean up later).       │
│                                                                                                                                                                                                              │
│ RuleInfo — add params: list[str] = field(default_factory=list).                                                                                                                                              │
│                                                                                                                                                                                                              │
│ _resilient_parse() — update rule-finding regex to handle <name[...]>:                                                                                                                                        │
│ r'(public\s+)?<([A-Za-z0-9_.$-]+)(?:\[[^\]]*\])?>((?:\s*\{[^}]*\})*)\s*=([^;]+);'                                                                                                                            │
│ Extract params string from the match and store on RuleInfo.params.                                                                                                                                           │
│                                                                                                                                                                                                              │
│ GrammarDocument.parse() — populate RuleInfo.params from _LHS_DECL_RE matches (via a new helper that parses [$param1, $param2] into ['param1', 'param2']).                                                    │
│                                                                                                                                                                                                              │
│ core/validator.py                                                                                                                                                                                            │
│                                                                                                                                                                                                              │
│ Un-stub the parameterized rule arity check:                                                                                                                                                                  │
│ - Scan source for all parameterized declarations: <name[...]> before = → name → param_count                                                                                                                  │
│ - Scan source for all parameterized call sites in bodies: <name[...]> not before = → name → arg_count at each occurrence                                                                                     │
│ - Report arity mismatches as DiagnosticSeverity.Error                                                                                                                                                        │
│                                                                                                                                                                                                              │
│ tests/fixtures/parameterized.jsgf (new)                                                                                                                                                                      │
│                                                                                                                                                                                                              │
│ #JSGF V1.0;                                                                                                                                                                                                  │
│ grammar com.example.parameterized;                                                                                                                                                                           │
│                                                                                                                                                                                                              │
│ public <transfer[$from, $to]> {currency:enum=usd} = transfer $from to $to in dollars;                                                                                                                        │
│ public <transfer[$from, $to]> {currency:enum=gbp} = transfer $from to $to in pounds;                                                                                                                         │
│ public <date_range[$start, $end]> = from $start to $end | between $start and $end;                                                                                                                           │
│                                                                                                                                                                                                              │
│ public <my_transfer>  = <transfer[<savings>, <chequing>]> {currency:enum=usd};                                                                                                                               │
│ public <gbp_transfer> = <transfer[<savings>, <chequing>]> {currency:enum=gbp};                                                                                                                               │
│ public <booking>      = <date_range[<departure>, <return>]>;                                                                                                                                                 │
│                                                                                                                                                                                                              │
│ tests/test_document.py — new test cases                                                                                                                                                                      │
│                                                                                                                                                                                                              │
│ Custom functions + LHS flags:                                                                                                                                                                                │
│ - test_function_body_with_lhs_flag_parses_ok — <price> {currency:enum=usd} = $normalise(<cardinal>, 'USD'); → no parse error, pyjsgf name is price__currency_usd                                             │
│ - test_flagged_ref_to_function_bodied_rule — body <price> {currency:enum=usd} resolves to <price__currency_usd> in mangled source                                                                            │
│                                                                                                                                                                                                              │
│ Parameterized rules:                                                                                                                                                                                         │
│ - test_parameterized_decl_strips_params_for_pyjsgf — <date_range[$s, $e]> = → pyjsgf sees <date_range> =, no parse error                                                                                     │
│ - test_parameterized_with_lhs_flag_mangles_name — <transfer[$f, $t]> {currency:enum=usd} = → pyjsgf name transfer__currency_usd, params NOT in mangled source                                                │
│ - test_parameterized_flagged_ref_resolves — <transfer[<a>, <b>]> {currency:enum=usd} in body → resolved to <transfer__currency_usd>                                                                          │
│ - test_parameterized_unflagged_call_site_strips_args — <date_range[<dep>, <ret>]> in body → pyjsgf sees <date_range>                                                                                         │
│ - test_dollar_param_in_body_becomes_placeholder — $from in body → PARAM literal (pyjsgf can parse)                                                                                                           │
│ - test_parameterized_fixture_parses_ok — parameterized.jsgf → no parse error, expected rule names                                                                                                            │
│                                                                                                                                                                                                              │
│ tests/test_validator.py — new test cases                                                                                                                                                                     │
│                                                                                                                                                                                                              │
│ - test_parameterized_arity_ok — call site arg count matches declaration → no errors                                                                                                                          │
│ - test_parameterized_arity_mismatch — call site has wrong arg count → error diagnostic                                                                                                                       │
│                                                                                                                                                                                                              │
│ ---                                                                                                                                                                                                          │
│ Verification                                                                                                                                                                                                 │
│                                                                                                                                                                                                              │
│ cd /home/david_lemay/nlu_dev_agent                                                                                                                                                                           │
│ source .venv/bin/activate                                                                                                                                                                                    │
│                                                                                                                                                                                                              │
│ # Run full test suite                                                                                                                                                                                        │
│ pytest tests/ -v                                                                                                                                                                                             │
│                                                                                                                                                                                                              │
│ # Smoke-test with pi skills on new fixture                                                                                                                                                                   │
│ ./pi.sh run 'validate the grammar tests/fixtures/parameterized.jsgf'                                                                                                                                         │
│ ./pi.sh run 'show coverage for tests/fixtures/parameterized.jsgf'                                                                                                                                            │
│                                                                                                                                                                                                              │
│ Expected: 52 existing tests still pass + ~10 new tests pass, no parse errors on parameterized.jsgf, validator reports arity errors correctly.

  Summary

  core/patch.py

  - Updated scan_positions() and scan_rule_def_positions() regexes to skip optional [...] parameter lists inside angle brackets.

  core/document.py

  - _strip_dialect_tags(): Added Step 0 (strip [args] from <name[args]>) and Step 0b (replace bare $param refs with PARAM literal, using \b(?!\() to avoid clobbering function names like $normalise(...)).
  - _LHS_DECL_RE: Added optional (?P<params>\[[^\]]*\])? capture group so parameterized flagged declarations match and params are dropped in pyjsgf output.
  - _FLAGGED_REF_RE: Added (?:\[[^\]]*\])? to consume [args] at flagged call sites.
  - Bare-ref post-pass: Updated regex to also match <name[args]> patterns, dropping params when resolving to mangled names.
  - _parse_params(): New helper to parse [$from, $to] → ['from', 'to'].
  - RuleInfo.params: New field populated in both pyjsgf and resilient parse paths.
  - _resilient_parse(): Updated rule-finding regex to handle <name[...]>.

  core/validator.py

  - Changed early-return guard to if dialect.functions or dialect.allowed_flag_types: block (so arity checks always run).
  - _PARAM_DECL_RE / _PARAM_CALL_RE: New regexes for parameterized declarations and call sites.
  - _count_items(): Helper to count comma-separated items.
  - Arity check: scans declarations for param counts, call sites for arg counts, reports mismatches as errors.

  New fixtures and tests

  - tests/fixtures/parameterized.jsgf: Fixture with flagged/unflagged parameterized rules and call sites.
  - 13 new tests in test_document.py (custom functions + LHS flags, parameterized rules).
  - 4 new tests in test_validator.py (arity ok, arity mismatch, unflagged mismatch, fixture validation). 
