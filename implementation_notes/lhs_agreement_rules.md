Plan: Rule name mangling for LHS agreement variants

 Context

 JSGF rules with LHS flags (e.g. {number:enum=singular}) are now supported, but pyjsgf
 raises GrammarError if two rules in the same file share a name — even when they carry
 distinct agreement flags and are intentionally different variants of the same abstract rule.

 The fix is to mangle rule names before pyjsgf sees the source:

 public <noun> {number:enum=singular} = book | cat;   →  pyjsgf: <noun__number_singular>
 public <noun> {number:enum=plural}   = books | cats; →  pyjsgf: <noun__number_plural>

 All source-level operations (LSP, agent, diagnostics) continue to use the original name
 noun. Only pyjsgf-level operations (matching, coverage) use the mangled name.

 Mangling format

 {base_name}__{key1}_{val1}__{key2}_{val2} — flag keys sorted lexicographically;
 non-alphanumeric characters in values replaced with _.

 - noun + {number:enum=singular} → noun__number_singular
 - noun + {number:enum=plural}   → noun__number_plural
 - x    + {b:bool=true} {a:enum=masc} → x__a_masc__b_true  (sorted)

 Applied to all rules that carry any LHS flag (not just when a duplicate exists),
 so grammar writers can always predict the pyjsgf name from looking at the declaration.

 Files to modify

 ┌───────────────────────────────────┬───────────────────────────────────────────────────────────────────────────────────────────────────┐
 │               File                │                                              Changes                                              │
 ├───────────────────────────────────┼───────────────────────────────────────────────────────────────────────────────────────────────────┤
 │ core/document.py                  │ Main: mangling logic, RuleInfo.pyjsgf_name, pyjsgf_def_positions, updated parse + duplicate check │
 ├───────────────────────────────────┼───────────────────────────────────────────────────────────────────────────────────────────────────┤
 │ core/index.py                     │ Add resolve_rules() returning all variants by original name                                       │
 ├───────────────────────────────────┼───────────────────────────────────────────────────────────────────────────────────────────────────┤
 │ agent/api.py                      │ validate_coverage() unions coverage across all variants                                           │
 ├───────────────────────────────────┼───────────────────────────────────────────────────────────────────────────────────────────────────┤
 │ tests/fixtures/noun_variants.jsgf │ New fixture with two <noun> variants                                                              │
 ├───────────────────────────────────┼───────────────────────────────────────────────────────────────────────────────────────────────────┤
 │ tests/test_document.py            │ New mangling + variant tests                                                                      │
 ├───────────────────────────────────┼───────────────────────────────────────────────────────────────────────────────────────────────────┤
 │ tests/test_index.py               │ New resolve_rules tests                                                                           │
 ├───────────────────────────────────┼───────────────────────────────────────────────────────────────────────────────────────────────────┤
 │ tests/test_api.py                 │ New multi-variant coverage tests                                                                  │
 └───────────────────────────────────┴───────────────────────────────────────────────────────────────────────────────────────────────────┘

 Implementation steps

 1. core/document.py — new helpers

 _safe_flag_val(v: str) → str — replace chars not valid in an identifier with _.

 _mangle_name(base_name: str, flags_str: str) → str
 - Parse key/type/value triples from flags_str using _FLAG_MANGLE_RE
 (same pattern as existing _FLAG_RE but as a new module-level constant)
 - Sort by key, join: base_name + '__' + '__'.join(f'{k}_{v}' for k, v in sorted(flags.items()))
 - Return base_name unchanged if flags_str is empty (no flags on that rule)

 _mangle_source(source: str) → tuple[str, dict[str, str], dict[str, Position]]

 New compiled regex _LHS_DECL_RE (module-level):
 _LHS_DECL_RE = re.compile(
     r'(?P<pub>(?:public\s+)?)'
     r'<(?P<rulename>[A-Za-z0-9_.$-]+)>'
     r'(?P<flags>(?:\s*\{[^}]*\})+)'
     r'(?P<eq>\s*=)'
 )

 Algorithm:
 - Use _LHS_DECL_RE.sub(replacer, source) where replacer:
   - Computes mangled = _mangle_name(m.group('rulename'), m.group('flags'))
   - Records pyjsgf_to_original[mangled] = original
   - Records pyjsgf_to_position[mangled] = offset_to_position(angle_offset, offsets)
 where angle_offset = m.start('rulename') - 1 (position of the < in original source)
   - Returns f"{pub}<{mangled}>{eq}" — note: keeps the {flags} block in the output
 (it will be stripped by the subsequent _strip_dialect_tags() call)
 - Returns (mangled_source, pyjsgf_to_original, pyjsgf_to_position)

 _line_offsets and offset_to_position are already imported from core/patch.py.

 2. core/document.py — extend RuleInfo

 @dataclass
 class RuleInfo:
     name: str            # original name (e.g. "noun")
     visible: bool
     body_source: str | None
     grammar_object: object | None
     pyjsgf_name: str = ''   # mangled name; set to name by __post_init__ if blank

     def __post_init__(self):
         if not self.pyjsgf_name:
             self.pyjsgf_name = self.name

 All existing construction sites omit pyjsgf_name → it auto-defaults to name. No
 existing call sites need updating.

 3. core/document.py — extend GrammarDocument

 Add field (with default so it can precede pyjsgf_grammar):
 pyjsgf_def_positions: dict[str, Position] = field(default_factory=dict)
 Maps pyjsgf_name → Position of the < in the original source. For unflagged rules
 pyjsgf_name == name, so this subsumes def_positions for per-variant lookup.

 4. core/document.py — update GrammarDocument.parse()

 # Before existing ref/def scanning:
 mangled_source, pyjsgf_to_original, pyjsgf_to_pos = _mangle_source(source)

 # Build pyjsgf_def_positions: unflagged rules from def_positions, variants from pyjsgf_to_pos
 pyjsgf_def_positions = dict(def_positions)   # pyjsgf_name == name for unflagged
 pyjsgf_def_positions.update(pyjsgf_to_pos)  # overwrite/add per-variant positions

 # Pass mangled_source to pyjsgf (was: source)
 g = _parse_grammar(mangled_source)           # _strip_dialect_tags runs inside, removes {flags}

 # When creating RuleInfo from pyjsgf rules:
 original_name = pyjsgf_to_original.get(rule.name, rule.name)
 rules.append(RuleInfo(
     name=original_name,          # was: rule.name
     pyjsgf_name=rule.name,       # the mangled pyjsgf name
     ...
 ))

 # Pass pyjsgf_def_positions to constructor:
 return cls(..., pyjsgf_def_positions=pyjsgf_def_positions, ...)

 5. core/document.py — update _resilient_parse()

 Extend the rule-finding regex to capture the flags block as group 3:
 r'(public\s+)?<([A-Za-z0-9_.$-]+)>((?:\s*\{[^}]*\})*)\s*=([^;]+);'
 #                                   ^^^^^^^^^^^^^^^^^^^^ new cap group
 In the loop body, call pyjsgf_nm = _mangle_name(name, m.group(3)) and set
 RuleInfo(name=name, ..., pyjsgf_name=pyjsgf_nm).

 6. core/document.py — update get_diagnostics() duplicate check

 Use pyjsgf_name as the uniqueness key (two variants with different flags will have
 different pyjsgf_name → not considered duplicates):

 seen: dict[str, str] = {}
 for rule in self.rules:
     if rule.pyjsgf_name in seen:
         rng = self._rule_def_range(rule)    # ← now takes RuleInfo
         diags.append(Diagnostic(f"Duplicate rule definition: <{rule.name}>", ...))
     else:
         seen[rule.pyjsgf_name] = rule.name

 7. core/document.py — update _rule_def_range() and get_rule()

 def _rule_def_range(self, rule: RuleInfo) -> lsp.Range:
     # Only one call site (duplicate check above) — signature change is safe
     pos = self.pyjsgf_def_positions.get(rule.pyjsgf_name, Position(0, 0))
     return _pos_to_range(pos, len(rule.name))   # range length = original name length

 def get_rule(self, name: str) -> RuleInfo | None:
     for r in self.rules:
         if r.name == name or r.pyjsgf_name == name:   # also matches mangled names
             return r
     return None

 8. core/index.py — add resolve_rules()

 def resolve_rules(self, name: str, from_file: Path) -> list[RuleLocation]:
     """Return all variants of *name* visible from *from_file* (local then imported)."""
     results = []
     doc = self._documents.get(from_file)
     if doc:
         for rule in doc.rules:
             if rule.name == name or rule.pyjsgf_name == name:
                 results.append(RuleLocation(file=from_file, rule=rule))
     if not results:
         for imp_path in self._imports.get(from_file, set()):
             imp_doc = self._documents.get(imp_path)
             if imp_doc:
                 for rule in imp_doc.rules:
                     if (rule.name == name or rule.pyjsgf_name == name) and rule.visible:
                         results.append(RuleLocation(file=imp_path, rule=rule))
     return results

 resolve_rule() is unchanged — it still returns the first match (adequate for LSP
 go-to-def and undefined-ref checking, which use original names from source).

 9. agent/api.py — update validate_coverage()

 Replace the single resolve_rule call with resolve_rules, then test each utterance
 against all variant grammar_objects — covered if any variant matches:

 locs = self.index.resolve_rules(rule_name, from_file)
 rule_objs = [loc.rule.grammar_object for loc in locs if loc.rule.grammar_object]
 if not rule_objs:
     loc = self.index.resolve_rule(rule_name, from_file)  # pyjsgf_name fallback
     if not loc or not loc.rule.grammar_object:
         return CoverageResult([], utterances, 0.0)
     rule_objs = [loc.rule.grammar_object]

 for u in utterances:
     matched = any(
         _try_match(rule_obj, u) for rule_obj in rule_objs
     )
     (covered if matched else uncovered).append(u)

 Extract _try_match(rule_obj, u) → bool as a local helper that wraps the existing
 try/except RecursionError guard.

 New fixture: tests/fixtures/noun_variants.jsgf

 #JSGF V1.0;
 grammar com.example.nounvariants;

 public <noun> {number:enum=singular} = book | cat | table;
 public <noun> {number:enum=plural}   = books | cats | tables;

 (No <sentence> rule referencing the abstract <noun> — body references to abstract
 names would be unresolved in pyjsgf; callers use mangled names in rule bodies.)

 New / updated tests

 tests/test_document.py — add

 - test_mangle_name_single_flag — _mangle_name('noun', '{number:enum=singular}') == 'noun__number_singular'
 - test_mangle_name_no_flags — _mangle_name('bare', '') == 'bare'
 - test_mangle_name_multi_flag_sorted — multiple flags → keys sorted deterministically
 - test_mangle_source_rewrites_declaration_not_body — body references to <noun> are not rewritten; only the declaration name is
 - test_same_name_variants_parse_successfully — two <noun> rules → parse_error is None
 - test_same_name_variants_pyjsgf_names — rules[0].pyjsgf_name == 'noun__number_singular', rules[1].pyjsgf_name == 'noun__number_plural'
 - test_same_name_variants_original_names_preserved — rules[0].name == rules[1].name == 'noun'
 - test_same_name_variants_no_duplicate_diagnostic — get_diagnostics() emits no "Duplicate rule" error for different-flag variants
 - test_true_duplicate_still_detected — same name + same flags (same pyjsgf_name) → diagnostic emitted
 - test_pyjsgf_def_positions_per_variant — pyjsgf_def_positions['noun__number_singular'].line != pyjsgf_def_positions['noun__number_plural'].line
 - test_get_rule_by_pyjsgf_name — doc.get_rule('noun__number_plural') returns the plural variant
 - test_resilient_parse_sets_pyjsgf_name — broken source with flagged rule → resilient path sets pyjsgf_name correctly

 tests/test_index.py — add

 - test_resolve_rules_all_variants — returns list of 2 RuleLocation objects for 'noun'
 - test_resolve_rules_pyjsgf_name_lookup — resolve_rules('noun__number_singular', ...) returns the singular variant
 - test_resolve_rules_single_unflagged_rule — list of length 1 for a plain rule

 tests/test_api.py — add

 - test_validate_coverage_multi_variant — 'book' covered by singular, 'books' by plural, 'yen' uncovered; ratio = 2/3
 - test_validate_coverage_pyjsgf_name_direct — lookup by 'noun__number_singular' returns only singular matches

 Verification

 .venv/bin/pytest tests/ -v
 # Expect 52 existing + ~18 new = ~70 tests, all passing

 Smoke-test the CLI skill:
 .venv/bin/python3 skills/jsgf-coverage/coverage.py noun tests/fixtures/noun_variants.jsgf \
     --utterances '["book", "cats", "elephant"]'
 # Expected: coverage_ratio: 0.67, covered: [book, cats], uncovered: [elephant]
