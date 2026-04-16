 Engine Capability Constraints in Dialect Config

 Context

 The NLU dev agent's dialect system defines all available extensions (functions, LHS/RHS flags, parameterized rules, lazy loading). Different ASR/NLU engines can only handle subsets of these features — some
 don't support functions, some limit to one public rule, some only understand LHS flags. Currently the dialect is all-or-nothing. We need a way to constrain validation and generation to what a given engine
 can actually process.

 Why settings over dialect-swapping: The dialect is deeply woven into parsing (_strip_dialect_tags), expansion (_generate_expansions), and validation. Swapping a whole dialect to express "this engine only
 allows one public rule" would mean duplicating dialect files that are mostly identical. The cleaner model is: dialect = what's defined/available; capabilities = what's permitted for the target engine.

 ---
 Approach

 1. Add EngineCapabilities dataclass to core/dialect.py

 @dataclass
 class EngineCapabilities:
     max_public_rules: int | None = None
     # "none" | "lhs_only" | "rhs_only" | "both"
     flags: str = "both"
     # None = all functions allowed with canonical names
     # dict = subset + optional rename: {canonical_name: engine_name}
     # {} = no functions allowed
     function_map: dict[str, str] | None = None
     allow_parameterized_rules: bool = True

 function_map example: {"lookup": "dict_lookup", "normalise": "normalize"} — only those two functions are allowed, and their engine-facing names differ. Functions absent from the map are forbidden. null
 means all canonical functions pass through unchanged.

 Embed in DialectRegistry:
 @dataclass
 class DialectRegistry:
     ...
     capabilities: EngineCapabilities = field(default_factory=EngineCapabilities)

 Load from config in DialectRegistry.from_config() — parse optional "capabilities" key with defaults. standard() factory keeps defaults (all permissive).

 2. Add validate_engine_capabilities() to core/validator.py

 New function parallel to validate_dialect(). Checks:
 - Max public rules: only for root grammars (not imported by any other doc in the workspace). Add GrammarIndex.is_library(doc_path) -> bool that checks the reverse import graph — if any other document
 imports this one, it's a library and the check is skipped. For root docs, count doc.grammar.visible_rules and emit diagnostic if exceeded.
 - Flag position: if "none" → error on any {...} tag; if "lhs_only" → error on RHS {...} tags; if "rhs_only" → error on LHS flags (check doc.rules for mangled names)
 - Function map: iterate doc.func_placeholders, check each canonical function name is a key in function_map; if function_map={} → any function is an error; if a name is missing from the map → error naming
 the engine-friendly alternative if one exists
 - Parameterized rules: if disabled, error when doc.param_placeholder_map is non-empty

 Returns list[lsp.Diagnostic] like the existing validators.

 3. Wire into validation call sites

 Two places call validate_dialect():
 - agent/api.py:276 — validate_generated_grammar()
 - Any LSP diagnostics path in lsp/server.py

 Add diags += validate_engine_capabilities(doc, self.index.dialect) after each validate_dialect() call.

 4. Surface capabilities in generation context (agent/api.py)

 In get_generation_context(), add to the returned context:
 capabilities = asdict(self.index.dialect.capabilities)
 So the LLM prompt knows constraints (e.g., "max 1 public rule") and respects them during generation.

 5. Update jsgf-dialect.json

 Add optional "capabilities" section (current engine gets permissive defaults, so no behavior change):
 {
   "engine": "proprietary-asr-v2",
   "capabilities": {
     "max_public_rules": null,
     "flags": "both",
     "function_map": null,
     "allow_parameterized_rules": true
   },
   ...
 }

 A more restricted engine example:
 {
   "engine": "basic-asr",
   "capabilities": {
     "max_public_rules": 1,
     "flags": "lhs_only",
     "function_map": {"lookup": "dict_lookup"},
     "allow_parameterized_rules": false
   }
 }

 ---
 Critical Files

 ┌───────────────────┬───────────────────────────────────────────────────────────────────────────────┐
 │       File        │                                    Change                                     │
 ├───────────────────┼───────────────────────────────────────────────────────────────────────────────┤
 │ core/dialect.py   │ Add EngineCapabilities dataclass; embed in DialectRegistry; parse from config │
 ├───────────────────┼───────────────────────────────────────────────────────────────────────────────┤
 │ core/index.py     │ Add GrammarIndex.is_library(path) -> bool using reverse import graph          │
 ├───────────────────┼───────────────────────────────────────────────────────────────────────────────┤
 │ core/validator.py │ Add validate_engine_capabilities(doc, dialect) function                       │
 ├───────────────────┼───────────────────────────────────────────────────────────────────────────────┤
 │ agent/api.py      │ Call validate_engine_capabilities; include capabilities in generation context │
 ├───────────────────┼───────────────────────────────────────────────────────────────────────────────┤
 │ lsp/server.py     │ Call validate_engine_capabilities in diagnostics handler                      │
 ├───────────────────┼───────────────────────────────────────────────────────────────────────────────┤
 │ jsgf-dialect.json │ Add "capabilities" section                                                    │
 └───────────────────┴───────────────────────────────────────────────────────────────────────────────┘

 ---
 Out of Scope (follow-on work)

 - Multi-engine profiles in one config: "engines": { "basic": {...}, "full": {...} } with a "target_engine" selector — useful but more complex; not needed for the immediate constraint use case
 - LSP command to switch active engine at runtime

 ---
 Verification

 1. Add a test fixture with 2 public rules → confirm diagnostic fires when max_public_rules=1 for a root grammar, but NOT for that same grammar when it is imported by another
 2. Add a test with $lookup(...) → confirm diagnostic fires when allowed_functions=[]
 3. Add a test with RHS tags → confirm diagnostic fires when flags="lhs_only"
 4. Confirm existing 111 tests still pass (defaults are permissive, no regressions)
 5. Run skills/jsgf-validate/validate.py smoke test on tests/fixtures/agreement.jsgf 


Here's a summary of what was implemented:

  core/dialect.py — Added EngineCapabilities dataclass with max_public_rules, flags, function_map, allow_parameterized_rules; embedded as DialectRegistry.capabilities; parsed from optional "capabilities" key
  in dialect JSON.

  core/index.py — Added GrammarIndex.is_library(path) -> bool using the existing _dependents reverse-import graph.

  core/validator.py — Added validate_engine_capabilities(doc, dialect, index=None) that checks all four constraint types with proper LSP diagnostic positions.

  agent/api.py — Calls validate_engine_capabilities in validate_generated_grammar(); includes engine_capabilities dict in GenerationContext.

  lsp/server.py + skills/jsgf-validate/validate.py — Both call validate_engine_capabilities after validate_dialect.

  jsgf-dialect.json — Added "capabilities" section with permissive defaults (no behavior change for existing engine).

  tests/test_engine_capabilities.py — 19 new tests covering all constraint types, the library-skip logic, and the agreement.jsgf fixture. All 130 tests pass.
