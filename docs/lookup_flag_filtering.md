 Plan: Flag-Filtered Non-Terminal Lookups

 Context

 Rules with LHS flags that use $lookup() in their bodies all currently load the
 same vocabulary regardless of which flag variant is being expanded. Non-terminal
 lists can be structured as disjoint flag-tagged subsets (e.g. Canadian banks vs.
 US banks), and the expansion engine should load only the matching subset.

 Example:
 public <bank> {region:enum=ca} = $lookup('banks');
 public <bank> {region:enum=us} = $lookup('banks');
 banks source should yield only ca-tagged items for the first rule and only
 us-tagged items for the second.

 ---
 Data format

 Both line-format and JSON-format data sources support per-item flag metadata.

 Line format (format: 'lines'): flags appended as a {key=val,...} suffix:
 TD Bank{region=ca}
 BMO{region=ca}
 Bank of America{region=us}
 global_bank

 JSON format (format: 'json'): items are plain strings or flag-bearing dicts:
 [
   {"value": "TD Bank", "flags": {"region": "ca"}},
   {"value": "BMO",     "flags": {"region": "ca"}},
   {"value": "Bank of America", "flags": {"region": "us"}},
   "global_bank"
 ]

 In both formats:
 - Items with flags: included only when all filter keys match
 - Untagged items (no suffix / plain strings): always included (match any filter)

 No changes to DataSource dataclass or jsgf-dialect.json schema are required.

 ---
 Files to modify

 ┌────────────────────────────────────┬────────────────────────────────────────────────────────────────────────────────────────────────────┐
 │                File                │                                               Change                                               │
 ├────────────────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────┤
 │ core/loader.py                     │ load_filtered(), _filtered_cache, refactor _load_file                                              │
 ├────────────────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────┤
 │ core/document.py                   │ _mangle_source returns pyjsgf_to_flags; new placeholder_flags field; populate in parse()           │
 ├────────────────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────┤
 │ agent/api.py                       │ Use load_filtered() in _generate_expansions; union variants in expansion path of validate_coverage │
 ├────────────────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────┤
 │ tests/fixtures/flagged_lookup.jsgf │ New fixture                                                                                        │
 ├────────────────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────┤
 │ tests/test_loader.py               │ New load_filtered tests                                                                            │
 ├────────────────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────┤
 │ tests/test_document.py             │ New placeholder_flags tests                                                                        │
 ├────────────────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────┤
 │ tests/test_api.py                  │ New flagged-lookup coverage tests                                                                  │
 └────────────────────────────────────┴────────────────────────────────────────────────────────────────────────────────────────────────────┘

 ---
 Implementation steps

 1. core/loader.py — add load_filtered()

 __init__: add self._filtered_cache: dict[tuple, list[str]] = {}.

 invalidate(): also call self._filtered_cache.clear() (or remove the
 specific key) so filtered results don't go stale.

 _INLINE_FLAG_RE: module-level compiled regex to parse inline line flags:
 _INLINE_FLAG_RE = re.compile(r'^(.*?)\{([^}]+)\}\s*$')

 _parse_line_item(line) -> tuple[str, dict[str, str]]: new private static
 helper — splits "TD Bank{region=ca}" into ("TD Bank", {"region": "ca"}).
 Returns (line, {}) when no flag suffix is present. Parse the flag block by
 splitting on , and then =.

 _load_raw_json(src, limit) -> list: new private helper — reads the JSON
 source and returns the raw parsed list (before value extraction). Used by
 load_filtered. Refactor _load_file's JSON branch to delegate to this helper.

 load_filtered(source_name, flags) -> list[str]:
 def load_filtered(self, source_name: str, flags: dict[str, str]) -> list[str]:
     if not flags:
         return self.load(source_name)
     cache_key = (source_name, frozenset(flags.items()))
     if cache_key in self._filtered_cache:
         return self._filtered_cache[cache_key]
     src = self._sources.get(source_name)
     if src is None:
         return []
     limit = self._config.lookup_limit
     result: list[str] = []
     if src.format == 'json':
         raw = self._load_raw_json(src, limit)
         for item in raw:
             if isinstance(item, str):
                 result.append(item)   # untagged: always match
             elif isinstance(item, dict):
                 item_flags = item.get('flags', {})
                 if all(item_flags.get(k) == v for k, v in flags.items()):
                     result.append(str(item.get('value', '')))
     else:  # 'lines' format — parse inline {key=val} suffix
         try:
             lines = self._load_raw_lines(src, limit)
         except Exception:
             lines = []
         for line in lines:
             value, item_flags = _parse_line_item(line)
             if not item_flags or all(item_flags.get(k) == v for k, v in flags.items()):
                 result.append(value)
     self._filtered_cache[cache_key] = result
     return result

 Also add _load_raw_lines(src, limit) -> list[str] that returns the raw (unparsed)
 lines from the source (extracted from the current _load_file lines branch), so
 load_filtered can parse flag suffixes before stripping them. Refactor _load_file
 to call _load_raw_lines and apply _parse_line_item to extract plain values —
 so load() (no filter) also strips the {...} suffix and returns clean strings.

 2. core/document.py — extend _mangle_source

 Change return type to 4-tuple, adding pyjsgf_to_flags: dict[str, dict[str, str]].

 In replacer(), after computing mangled:
 flags_dict: dict[str, str] = {}
 for fm in _FLAG_MANGLE_RE.finditer(flags_str):
     flags_dict[fm.group(1).strip()] = fm.group(3).strip()  # raw value, not safe'd
 pyjsgf_to_flags[mangled] = flags_dict

 Return: mangled_source, pyjsgf_to_original, pyjsgf_to_position, pyjsgf_to_flags.

 3. core/document.py — add placeholder_flags field

 # Maps PLHDR token → LHS flags of the enclosing rule (empty for unflagged rules)
 placeholder_flags: dict[str, dict[str, str]] = field(default_factory=dict)

 4. core/document.py — populate placeholder_flags in parse()

 After the _strip_dialect_tags call that produces stripped:

 # Unpack 4-tuple from _mangle_source (update the earlier call)
 mangled_source, pyjsgf_to_original, pyjsgf_to_pos, pyjsgf_to_flags = _mangle_source(source)

 # ... (existing parse logic) ...

 # Post-pass: find which PLHDR tokens live in flagged rule bodies
 placeholder_flags: dict[str, dict[str, str]] = {}
 if pyjsgf_to_flags:
     _RULE_BODY_RE = re.compile(r'<([A-Za-z0-9_.$-]+)>\s*=([^;]+);')
     for rm in _RULE_BODY_RE.finditer(stripped):
         rule_pyjsgf_name = rm.group(1)
         if rule_pyjsgf_name not in pyjsgf_to_flags:
             continue
         for plhdr_m in re.finditer(r'\bplhdr\d+\b', rm.group(2).lower()):
             placeholder_flags[plhdr_m.group().upper()] = pyjsgf_to_flags[rule_pyjsgf_name]

 Pass placeholder_flags=placeholder_flags to the cls(...) constructor.

 The post-pass runs on the stripped source (after LHS flag blocks and dialect tags
 are removed), so <rule__flag_val> = PLHDRn ...; is clearly visible.

 5. agent/api.py — use load_filtered in _generate_expansions

 In the Literal branch, PLHDR expansion (lines ~420–430):

 fn_info = doc.func_placeholders.get(plhdr_lower.upper())
 if fn_info:
     fn_name, fn_args = fn_info
     if fn_name == 'lookup' and fn_args:
         plhdr_flags = (doc.placeholder_flags or {}).get(plhdr_lower.upper(), {})
         loaded = (
             loader.load_filtered(fn_args[0], plhdr_flags)
             if plhdr_flags else
             loader.load(fn_args[0])
         )
         segment_options.append(loaded if loaded else [plhdr_lower])

 6. agent/api.py — union variants in expansion-path coverage

 validate_coverage expansion path currently only uses locs[0]. When multiple
 flagged variants each have lookup placeholders, we must union their expansions:

 if use_expansion_path:
     expansion_set: set[str] = set()
     for loc in locs:
         if loc.rule.grammar_object is not None:
             target_doc = self.index._documents.get(loc.file) or doc
             budget = [self.loader.expansion_limit]
             try:
                 expansion_set |= {
                     e.lower() for e in _generate_expansions(
                         loc.rule.grammar_object.expansion, self.index, loc.file,
                         loader=self.loader, doc=target_doc, budget=budget,
                     )
                 }
             except RecursionError:
                 pass
     covered = [u for u in utterances if u.lower() in expansion_set]
     uncovered = [u for u in utterances if u.lower() not in expansion_set]
     ratio = len(covered) / len(utterances) if utterances else 0.0
     return CoverageResult(covered, uncovered, ratio)

 ---
 New fixture: tests/fixtures/flagged_lookup.jsgf

 #JSGF V1.0;
 grammar com.example.flaggedlookup;

 public <bank> {region:enum=ca} = $lookup('banks');
 public <bank> {region:enum=us} = $lookup('banks');

 In tests, inject a DataLoader with an inline banks source (JSON format):
 [
   {"value": "TD", "flags": {"region": "ca"}},
   {"value": "BMO", "flags": {"region": "ca"}},
   {"value": "Chase", "flags": {"region": "us"}}
 ]

 ---
 New tests

 tests/test_loader.py
 - test_load_filtered_json_by_flag — JSON source: load_filtered('banks', {'region': 'ca'}) returns only ca items
 - test_load_filtered_lines_by_flag — line source with TD Bank{region=ca} suffix: same semantics
 - test_load_filtered_untagged_items_always_match — untagged items (no suffix / plain strings) always included
 - test_load_filtered_no_flags_delegates_to_load — load_filtered(name, {}) returns same as load(name)
 - test_load_lines_strips_flag_suffix — load() (no filter) returns values with flag suffixes stripped
 - test_load_filtered_cached — second call returns cached result

 tests/test_document.py
 - test_placeholder_flags_populated_for_flagged_rules — after parsing flagged_lookup.jsgf,
 doc.placeholder_flags['PLHDR0'] == {'region': 'ca'} and ['PLHDR1'] == {'region': 'us'}
 - test_placeholder_flags_empty_for_unflagged_rule — unflagged $lookup() rule has no entry
 in placeholder_flags

 tests/test_api.py
 - test_validate_coverage_flagged_lookup — with flagged lookup fixture + loader with tagged banks,
 'TD' covered by ca variant, 'Chase' by us variant, 'unknown' uncovered; ratio = 2/3

 ---
 Verification

 cd /home/david_lemay/nlu_dev_agent
 source .venv/bin/activate

 # Full test suite
 pytest tests/ -v

 # Smoke test
 ./pi.sh run 'validate the grammar tests/fixtures/flagged_lookup.jsgf'

 Expected: ~130 existing tests + ~8 new = ~138 passing.

---
Summary

● All 149 tests pass (130 existing + 19 new). Here's a summary of what was implemented:

  core/loader.py:
  - _parse_line_item(line) — parses "TD Bank{region=ca}" → ("TD Bank", {"region": "ca"})
  - _load_raw_lines() / _load_raw_json() — raw item loading without value extraction
  - load_filtered(source_name, flags) — returns only items whose flags match (untagged items always pass)
  - load() now strips {...} suffixes from line-format items so plain loads stay clean
  - invalidate() clears both _cache and _filtered_cache

  core/document.py:
  - _mangle_source returns a 4-tuple now, adding pyjsgf_to_flags (mangled_name → {key: raw_val})
  - New placeholder_flags field on GrammarDocument maps each PLHDR token to the LHS flags of its enclosing rule
  - parse() runs a post-pass on the stripped source to populate placeholder_flags for flagged rules

  agent/api.py:
  - _generate_expansions calls loader.load_filtered() instead of loader.load() when the PLHDR token has flag context
  - validate_coverage expansion path now unions expansions across all variants (not just locs[0]), so flagged lookup rules with different subsets are properly combined
