 Lazy Loading for Lookup Functions and Parameterized Rules

 Context

 Currently, $lookup('bank_names') function calls and <transfer[$from, $to]> parameterized
 rule refs are stripped to opaque literals (PLACEHOLDER / PARAM) before pyjsgf parses
 them. All semantic content is lost — example generation returns "PLACEHOLDER" and coverage
 matching against real utterances always fails. This plan adds lazy loading so the server can
 introspect those rules for real validation and coverage.

 Goals:
 1. Lookup functions load first N items from a configured file or stream
 2. Parameterized rules expand up to N argument combinations from call sites
 3. Both limits and data source paths live in jsgf-dialect.json
 4. Example generation and coverage checking use the loaded data

 ---
 1. Config: extend jsgf-dialect.json

 Add two top-level sections:

 "lazy_loading": {
   "lookup_limit": 50,
   "expansion_limit": 200
 },
 "data_sources": {
   "bank_names": { "type": "file",    "path": "data/bank_names.txt" },
   "currencies":  { "type": "inline", "values": ["USD", "EUR", "GBP"] },
   "cardinals":   { "type": "command", "command": "python3 scripts/gen_cardinals.py",
                    "args": ["--max", "100"] }
 }

 - lookup_limit — max items loaded per source; default 50 when section absent
 - expansion_limit — max total utterances generated before aborting; default 200
 - type — one of "file", "inline", "command"
 - "file" supports optional "format": "lines" (default) or "json" (JSON array)
 - "command" runs a subprocess and reads stdout

 ---
 2. core/dialect.py — new dataclasses

 Add two dataclasses and extend DialectRegistry:

 @dataclass
 class DataSource:
     name: str
     type: str                          # 'file' | 'inline' | 'command'
     path: str | None = None            # for type='file'
     format: str = 'lines'              # 'lines' | 'json'
     values: list[str] = field(default_factory=list)   # for type='inline'
     command: str | None = None         # for type='command'
     args: list[str] = field(default_factory=list)

 @dataclass
 class LazyLoadingConfig:
     lookup_limit: int = 50
     expansion_limit: int = 200

 In DialectRegistry:
 lazy_loading: LazyLoadingConfig = field(default_factory=LazyLoadingConfig)
 data_sources: dict[str, DataSource] = field(default_factory=dict)

 Parse both sections in DialectRegistry.from_config (no change to standard()).

 ---
 3. New core/loader.py — DataLoader

 class DataLoader:
     def __init__(self, sources: dict[str, DataSource],
                  config: LazyLoadingConfig, workspace_root: Path): ...

     def load(self, source_name: str) -> list[str]:
         """Return up to lookup_limit items; cached after first call."""

     def invalidate(self, source_name: str | None = None) -> None:
         """Drop cache for one source or all."""

 - "file": Path.read_text(), split on lines (or json.loads), slice to limit
 - "inline": return values[:limit]
 - "command": subprocess.run(timeout=10), parse stdout, slice to limit
 - Cache: dict[str, list[str]] keyed by source name; populated on first access
 - Returns [] silently for any unknown source or IO error

 ---
 4. core/document.py — indexed placeholders

 4a. New fields on GrammarDocument

 # 'PLHDR0' → ('lookup', ['bank_names'])  — filled during parse
 func_placeholders: dict[str, tuple[str, list[str]]] = field(default_factory=dict)
 # 'PARM_from' → 'from'  — informational, filled during parse
 param_placeholder_map: dict[str, str] = field(default_factory=dict)
 # 'transfer' → [['<savings>', '<chequing>'], ...]  — call-site args before stripping
 param_call_sites: dict[str, list[list[str]]] = field(default_factory=dict)

 4b. Modify _strip_dialect_tags

 Change signature to accept optional side-effect maps:

 def _strip_dialect_tags(
     source: str,
     func_map: dict | None = None,
     param_map: dict | None = None,
     call_site_map: dict | None = None,
 ) -> str:

 Step -1 (new, before existing step 0) — capture parameterized call-site args:
 # Match call sites like <transfer[<savings>, <chequing>]> NOT followed by =
 _CALL_SITE_RE = re.compile(
     r'<([A-Za-z0-9_.$-]+)\[([^\]]*)\]>(?!\s*(?:\{[^}]*\}\s*)*=)'
 )
 for m in _CALL_SITE_RE.finditer(source):
     args = [a.strip() for a in m.group(2).split(',') if a.strip()]
     call_site_map.setdefault(m.group(1), []).append(args)

 Step 0b — param refs become named tokens (was flat PARAM):
 def _param_replacer(m):
     token = f'PARM_{m.group(1)}'
     if param_map is not None: param_map[token] = m.group(1)
     return token
 source = re.sub(r'\$([A-Za-z_][A-Za-z0-9_]*)\b(?!\()', _param_replacer, source)

 Step 3 — function calls become indexed tokens (was flat PLACEHOLDER):
 _func_counter = [0]
 def _func_replacer(m):
     token = f'PLHDR{_func_counter[0]}'; _func_counter[0] += 1
     args = [a.strip().strip("'\"") for a in m.group(2).split(',') if a.strip()]
     if func_map is not None: func_map[token] = (m.group(1), args)
     return token
 source = re.sub(r'\$([A-Za-z_][A-Za-z0-9_]*)\([^)]*\)', _func_replacer, source)

 _parse_grammar (called from tests) passes no maps → backward-compatible.

 4c. Wire maps into GrammarDocument.parse

 In GrammarDocument.parse, before calling _parse_grammar:
 func_placeholders, param_placeholder_map, param_call_sites = {}, {}, {}
 # Call _strip_dialect_tags directly (instead of through _parse_grammar) to populate maps:
 stripped = _strip_dialect_tags(mangled_source,
     func_map=func_placeholders,
     param_map=param_placeholder_map,
     call_site_map=param_call_sites)
 from jsgf.parser import parse_grammar_string
 g = parse_grammar_string(stripped)
 Then pass the three dicts to cls(...).

 4d. Backward compatibility

 - When no $func(...) calls exist: func_placeholders == {}
 - PLHDRn and PARM_name are valid alphanumeric pyjsgf literals
 - One breaking test: test_dollar_param_in_body_becomes_placeholder currently asserts
 'PARAM' in stripped — must be updated to assert 'PARM_start' in stripped (or whatever
 the specific param names are)

 ---
 5. agent/api.py — expanded generation and coverage

 5a. GrammarAgentAPI.__init__

 def __init__(self, index: GrammarIndex, loader: DataLoader | None = None):
     self.index = index
     self.loader = loader   # None → graceful degradation (old behaviour)

 5b. _generate_expansions — new signature

 def _generate_expansions(
     expansion, index, from_file, depth=0,
     loader=None, doc=None, bindings=None, budget=None
 ):
 - bindings: dict[str, str] | None — maps PARM_name → resolved string value
 - budget: list[int] | None — mutable [remaining] counter; yields stop when 0

 5c. Literal branch — substitution and lookup

 if isinstance(expansion, Literal):
     text = expansion.text
     # 1. Param substitution
     if bindings:
         for token, value in bindings.items():
             text = text.replace(token, value)
     # 2. Function placeholder expansion
     if loader and doc and text.startswith('PLHDR'):
         fn_info = doc.func_placeholders.get(text.strip())
         if fn_info:
             fn_name, fn_args = fn_info
             if fn_name == 'lookup' and fn_args:
                 for item in loader.load(fn_args[0]):
                     if budget: budget[0] -= 1;
                     if budget and budget[0] <= 0: return
                     yield item
                 return   # don't fall through to raw token
     yield text

 5d. NamedRuleRef branch — parameterized expansion

 When loc.rule.params is non-empty (the target is a parameterized rule):
 1. Look up doc.param_call_sites.get(expansion.name, []) for captured arg-lists
 2. For each arg-list, expand each arg as a rule ref (or literal) to get sample strings
 3. Cross-product the arg samples; for each combo build new_bindings and recurse into
 the rule body; honour budget and expansion_limit from loader
 4. Cross-file: get the target doc with index._documents.get(loc.file)

 When no call-site info is available (or rule has no params), use existing behaviour.

 5e. get_examples — pass loader and doc

 doc = self.index._documents.get(from_file)
 budget = [self.loader.expansion_limit if self.loader else 200]
 expansions = list(_generate_expansions(
     loc.rule.grammar_object.expansion, self.index, from_file,
     loader=self.loader, doc=doc, budget=budget
 ))

 5f. validate_coverage — expansion-based path for lookup rules

 When doc.func_placeholders is non-empty and self.loader is set, generate all
 expansions into a set and use set membership (instead of rule_obj.matches()). When
 loader is absent or no placeholders exist, the original matches() path is unchanged.

 ---
 6. Wiring — CLI skills and LSP

 All three places that construct GrammarAgentAPI gain a DataLoader:

 dialect = DialectRegistry.from_config(dialect_path)
 index = GrammarIndex(workspace, dialect)
 index.index_workspace()
 loader = DataLoader(dialect.data_sources, dialect.lazy_loading, workspace)
 api = GrammarAgentAPI(index, loader=loader)

 Files to update:
 - skills/jsgf-coverage/coverage.py
 - skills/jsgf-generate/generate.py
 - skills/jsgf-context/context.py
 - lsp/server.py (constructs GrammarAgentAPI for diagnostics)

 ---
 7. Critical files

 ┌───────────────────────────┬───────────────────────────────────────────────────────────────────────────────────────────────────────┐
 │           File            │                                                Change                                                 │
 ├───────────────────────────┼───────────────────────────────────────────────────────────────────────────────────────────────────────┤
 │ jsgf-dialect.json         │ Add lazy_loading, data_sources sections                                                               │
 ├───────────────────────────┼───────────────────────────────────────────────────────────────────────────────────────────────────────┤
 │ core/dialect.py           │ Add DataSource, LazyLoadingConfig; extend DialectRegistry                                             │
 ├───────────────────────────┼───────────────────────────────────────────────────────────────────────────────────────────────────────┤
 │ core/loader.py            │ New — DataLoader class                                                                                │
 ├───────────────────────────┼───────────────────────────────────────────────────────────────────────────────────────────────────────┤
 │ core/document.py          │ Indexed placeholders in _strip_dialect_tags; 3 new fields on GrammarDocument; wire maps in parse()    │
 ├───────────────────────────┼───────────────────────────────────────────────────────────────────────────────────────────────────────┤
 │ agent/api.py              │ Extend GrammarAgentAPI.__init__; rewrite _generate_expansions; update get_examples, validate_coverage │
 ├───────────────────────────┼───────────────────────────────────────────────────────────────────────────────────────────────────────┤
 │ skills/*/ + lsp/server.py │ Pass DataLoader when constructing GrammarAgentAPI                                                     │
 └───────────────────────────┴───────────────────────────────────────────────────────────────────────────────────────────────────────┘

 ---
 8. Verification

 1. Unit tests — pytest tests/ must remain green (89 existing + new)
 2. New tests/test_loader.py — inline, file, command sources; limit; cache; invalidate
 3. Updated tests/test_document.py — PARM_<name> tokens; PLHDR<n> tokens; func_placeholders and param_call_sites populated correctly
 4. New tests/test_api.py cases — get_examples returns real words (not PLHDR0);
 validate_coverage returns 1.0 when utterance is in loaded set
 5. Smoke test (CLI):
 # With a grammar that uses $lookup('bank_names') and a data/bank_names.txt file:
 python skills/jsgf-coverage/coverage.py --grammar grammars/check_balance.gram \
   --rule check_balance --utterances "td bank savings account"
 # Expect covered: ["td bank savings account"], ratio: 1.0

  Implementation Summary

  Files created

  - core/loader.py — DataLoader class with load(source_name) (cached), invalidate(), supporting file, inline, and command source types

  Files modified

  jsgf-dialect.json — added lazy_loading and data_sources sections with example bank_names and currencies sources

  core/dialect.py — added DataSource and LazyLoadingConfig dataclasses; extended DialectRegistry with lazy_loading and data_sources fields parsed from config

  core/document.py — refactored _strip_dialect_tags to accept optional func_map/param_map/call_site_map dicts; produces indexed PLHDR0/PARM_<name> tokens (was flat PLACEHOLDER/PARAM); added three new fields to GrammarDocument; wired
  maps into parse()

  agent/api.py — GrammarAgentAPI.__init__ accepts optional loader; _generate_expansions handles PLHDR tokens embedded in pyjsgf-lowercased literal text (cross-product expansion), param bindings, and parameterized rule call sites;
  validate_coverage uses expansion-set path when placeholders are present

  skills/*/ + LSP — all three skills now construct DataLoader and pass it to GrammarAgentAPI

  Key gotcha discovered

  pyjsgf lowercases all literal text — PLHDR0 becomes plhdr0 and PARM_from becomes parm_from in the AST. The expansion generator uses re.compile(r'\bplhdr\d+\b') and .upper() to look up func_placeholders, and applies param bindings
  with .lower().
