  Data structures

  GrammarIndex maintains five in-memory maps:

  ┌─────────────────────┬───────────────────────────────────────────────────────────────────┐
  │         Map         │                            Key → Value                            │
  ├─────────────────────┼───────────────────────────────────────────────────────────────────┤
  │ _documents          │ Path → GrammarDocument                                            │
  ├─────────────────────┼───────────────────────────────────────────────────────────────────┤
  │ _rule_index         │ rule_name → defining Path                                         │
  ├─────────────────────┼───────────────────────────────────────────────────────────────────┤
  │ _grammar_name_index │ grammar_name → Path (e.g. "com.example.shared" → .../shared.jsgf) │
  ├─────────────────────┼───────────────────────────────────────────────────────────────────┤
  │ _imports            │ Path → set[Path] (forward edges)                                  │
  ├─────────────────────┼───────────────────────────────────────────────────────────────────┤
  │ _dependents         │ Path → set[Path] (reverse edges)                                  │
  └─────────────────────┴───────────────────────────────────────────────────────────────────┘

  Bootstrap (index_workspace)

  On startup, it does an rglob for *.jsgf, *.jsgf, and *.jgram under the workspace root, then calls update_file() on each one.

  Incremental update (update_file)

  Every file open/save goes through update_file(path, source):

  1. Parse — GrammarDocument.parse() produces rules, imports, positions, etc.
  2. Rule index — clears old entries for this path, writes rule_name → path for each rule.
  3. Grammar name index — maps the grammar header (e.g. com.example.shared) → path.
  4. Import graph — removes old forward edges, resolves new imports via the grammar name index, writes new edges in both directions. Returns the union of {path} + its dependents (files that import it).
  5. Pre-resolve — calls pyjsgf.Grammar.resolve_imports(memo) on all affected docs so Rule.matches() works without hitting the filesystem.

  Import resolution

  JSGF imports use dotted grammar names (import <com.example.shared.*>), not file paths. The index bridges them: resolve_import() looks up imp.grammar_name in _grammar_name_index to get a Path, then
  optionally checks that the specific rule is public.

  Rule lookup (resolve_rule)

  Checks the requesting file's local rules first, then walks its direct imports (one hop only — JSGF doesn't chain imports transitively in the lookup).

  Cascade invalidation

  When a library file changes, update_file returns all its dependents. The LSP server uses this to re-run diagnostics on every file that imports the changed one.

  pyjsgf integration (build_pyjsgf_memo / pre_resolve_grammar_imports)

  pyjsgf normally resolves imports by scanning the filesystem for grammar files. The index bypasses this by building a grammar_name → pyjsgf.Grammar memo and passing it to Grammar.resolve_imports(memo) — so
  cross-file Rule.matches() calls work without filesystem access.
