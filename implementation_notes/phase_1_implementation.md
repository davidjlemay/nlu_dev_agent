  Phase 1 — Core Foundation (fully implemented and tested):

  - core/patch.py — Position tracking via text scanning (regex-based, no fragile pyparsing hooks). Finds positions of all rule definitions and references in source.
  - core/dialect.py — DialectRegistry loading jsgf-dialect.json: typed flags, custom functions with arity/type validation, reserved rules.
  - core/document.py — GrammarDocument with two-stage parsing: full pyjsgf parse with dialect-tag stripping, falling back to resilient line-level tokeniser on failure.
  - core/index.py — GrammarIndex with incremental file updates, grammar-name→path index, forward/reverse import graph, and pre-resolution of pyjsgf imports via a memo dict (avoids filesystem scanning at match
   time).
  - core/validator.py — Dialect-aware validation: typed flag types, function call arity.

  Phase 2 — LSP Server:
  - lsp/server.py — pygls 2.x server: diagnostics push, completion (rules + dialect functions), go-to-definition, find-references, rename refactoring.

  Phase 3 — Agent API & CLI Skills:
  - agent/api.py — GrammarAgentAPI: coverage validation, expansion sampling, find_rules_matching, get_generation_context, validate_generated_grammar.
  - skills/jsgf-{validate,coverage,context,generate}/ — CLI wrappers with READMEs.

  Phase 4 — DSPy Generation Pipeline:
  - agent/generation/{program,metrics,loop,optimize}.py — 4-module DSPy pipeline, JSGFCoverageMetric, async correction loop (Anthropic API), MIPROv2 optimisation runner.

  pi-extension/jsgf-nlu.ts — pi TypeScript extension with jsgf_validate, jsgf_coverage, jsgf_context tools and /generate-intent command.

  38 tests passing across patch, dialect, document, index, and API layers.
