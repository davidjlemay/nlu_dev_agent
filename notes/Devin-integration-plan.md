---
agent: devin-local
session: observant-chef
created: 2026-09-28T20:52:54Z
---
# Integrate nlu_dev_agent into the Agentic_NLU JSGF pipeline

Port the nlu_dev_agent language server and four skills into the Agentic_NLU Devin workflow so local JSGF validation, coverage, context, and generation can run without NLTOOLS, while closing the generate→validate loop against the Cerence dialect.

## Summary

This plan ports the `nlu_dev_agent` language-server and agentic loop into the existing `Agentic_NLU` Devin skill pipeline. The integration gives `agentic-jsgf-generation` fast, local, queryable validation and coverage, maps the parser to the Cerence JSGF dialect, and drives generation through Devin/Cascade instead of external LLM APIs.

## Decisions from discussion

- **Per-language config:** `.devin/config/nlu_dev_agent/<lang>.yaml`
- **Daemon:** one multi-language daemon; it keeps a map of `lang -> GrammarIndex` and loads the requested language on demand
- **`nlu-dev-agent-generate`:** included in the first pass, but uses Devin/Cascade for the actual rule generation step (no external LLM APIs)
- **`validate-and-correct-jsgf`:** remains the final quality gate and fallback when `nlu-dev-agent-validate` cannot resolve an issue

## Implementation Steps

### Phase 0 — Dialect discovery & central config
1. **Design a per-language central config schema** in `.devin/config/nlu_dev_agent/<lang>.yaml` that developers fill in with paths to `jsgf.stark`, `gazetteer.stark`, `features.json`, gazetteer directories, JSGF rule directories, and common-language libraries.
2. **Create a base Cerence dialect descriptor** at `nlu_dev_agent/dialects/cerence/cerence.json` defining engine capabilities for the proprietary ASR v2 engine: one public root rule per file, AVM `{key:value[,...]}` flags allowed on both rule LHS and RHS, `$SLOT` syntax as a data-source/non-terminal reference, `#ANNOTATION` tags, parameterized rules disabled, and no built-in functions.
3. **Add a `CerenceConfigLoader`** (`nlu_dev_agent/core/cerence_config.py`) that reads the per-language central config, resolves `jsgf.stark` and `features.json`, and produces a `Dialect` plus a slot→data-source map at runtime.

### Phase 1 — Core parser & dialect extensions
4. **Extend `nlu_dev_agent/core/dialect.py`** to accept new config keys: `flag_style` (`typed`|`avm`), `avm_features`, `slot_reference_syntax`, `slot_map`, `avm_wildcards`, and `annotation_tag_style`.
5. **Extend `nlu_dev_agent/core/document.py`**:
   - Parse AVM flag blocks on rule LHS and RHS, including `?var`, `*`, and `|` disjunctions.
   - Mangle rule names (e.g. `rule{ko:n,num:pl}` → a pyjsgf-safe internal name) so multiple constrained variants can coexist.
   - Treat bare `$SLOT` as a lookup to a `DataSource` or non-terminal rule instead of a function.
   - Preserve `#ANNOTATION` tags in `RuleInfo` while stripping them to a placeholder `{tag}` for pyjsgf parsing.
6. **Extend `nlu_dev_agent/core/validator.py`** to validate AVM feature keys/values against the `features.json` catalog, flag unknown features, detect `#ANNOTATION` misuse, and enforce Cerence-specific constraints.
7. **Add `nlu_dev_agent/core/cerence_data_loader.py`** (or extend `DataLoader`):
   - Parse `jsgf.stark` non-terminal definitions.
   - Parse `.gaz` files with the pattern `surface{flags}|canonical`.
   - Build `DataSource` objects for each slot so coverage and expansion can sample real values.
   - Provide a wildcard/fallback for `TEXT`-style free-form slots.

### Phase 2 — Devin adapter & language server
8. **Add `nlu_dev_agent/devin_adapter/daemon.py`**: a single persistent JSON-over-Unix-socket server wrapping a map of `GrammarIndex` and `GrammarAgentAPI` instances. Commands include `validate`, `coverage`, `context`, `generate`, `index`, `status`, `stop`; each command accepts a `lang` parameter and lazily loads the language workspace.
9. **Add `nlu_dev_agent/devin_adapter/client.py`**: connects to the daemon and starts it on demand from a skill/tool.
10. **Add `nlu_dev_agent/devin_adapter/cli.py`**: a single Devin-facing CLI `nlu-dev-agent --lang <lang> --action <validate|coverage|context|generate> ...`.
11. **Add `nlu_dev_agent/lsp/tcp_server.py`** so the existing pygls LSP can be started on a TCP socket for optional editor support.
12. **Create `.devin/skills/nlu-dev-agent-start/SKILL.md`** to start/ensure the daemon is running when skills load.
13. **Set up a virtual environment** (`nlu_dev_agent/.venv` or reuse `.devin/tmp/venv`) and install `pygls`, `pyjsgf`, and other dependencies from `nlu_dev_agent/pyproject.toml` or `requirements.txt`.

### Phase 3 — Convert pi-mono skills to Devin standard
14. **Create Devin skill wrappers** under `.devin/skills/`:
    - `nlu-dev-agent-validate/SKILL.md`
    - `nlu-dev-agent-coverage/SKILL.md`
    - `nlu-dev-agent-context/SKILL.md`
    - `nlu-dev-agent-generate/SKILL.md`
   Each uses the Devin `SKILL.md` frontmatter, triggers, and instructions, and calls `nlu_dev_agent/devin_adapter/cli.py`.
15. **Port the intent and usage examples** from `nlu_dev_agent/.pi/skills/*.md` and `nlu_dev_agent/skills/*/README.md` into the new Devin skills, removing pi-mono-specific setup.
16. **For `nlu-dev-agent-generate`**: the skill orchestrates a Devin/Cascade loop — call `nlu-dev-agent-context` for grammar context, ask Devin/Cascade to produce the JSGF rule, then call `nlu-dev-agent-validate` and `nlu-dev-agent-coverage`; feed failures back to the generation step. This removes any external LLM API dependency.
17. **Optionally add a meta-skill** `.devin/skills/nlu-dev-agent/SKILL.md` describing the `validate → coverage → context → generate` loop.

### Phase 4 — Map nlu_dev_agent to the Cerence JSGF dialect
18. **Write `nlu_dev_agent/dialects/cerence/cerence.json`** with the engine capabilities described in Phase 0.
19. **Write per-language central configs** at `.devin/config/nlu_dev_agent/fra-FRA.yaml` (and later `hin-IND.yaml`, `eng-USA.yaml`) that point at the corresponding `resources/anno-lang/<lang>` directories. Use `workspace_utils.py` heuristics as a fallback when a config is missing.
20. **Wire `daemon.py`/`cli.py`** to load the Cerence base dialect and the per-language config based on `--lang`.
21. **Smoke-test the mapping** on a known French file (`resources/anno-lang/fra-FRA/CTagger/data/jsgf/add_def.jsgf`) and a simple rule to confirm parsing, import resolution, and `$SLOT` resolution.

### Phase 5 — Plug into `agentic-jsgf-generation`
22. **Update `.devin/skills/jsgf-rule-generation/SKILL.md`** to optionally call `nlu-dev-agent-context` before generation to discover helper rules and AVM patterns in the target language.
23. **Update `.devin/skills/validate-and-correct-jsgf/SKILL.md`**: `nlu-dev-agent-validate` runs first; if it cannot resolve an error or config is missing, fall back to the existing `jsgf_validator.py` / `mj-expansion-and-testing` path.
24. **Update `.devin/skills/agentic-jsgf-generation/SKILL.md`** to insert:
    - Step 7.5: `nlu-dev-agent-validate` on the generated JSGF.
    - Step 7.6: `nlu-dev-agent-coverage` against localized FAS utterances; if coverage < 1.0, feed the uncovered cases back to `nlu-dev-agent-generate`/correction.
    - Step 11: replace the `jsgf_validator.py` syntax check with `nlu-dev-agent-validate`; keep Step 12 (`mj-expansion-and-testing`) as the final quality gate.
25. **Update `.devin/skills/signature-analysis/SKILL.md`** to use `nlu-dev-agent-validate`/`nlu-dev-agent-context` for rule discovery and non-standard grammar-structure detection, replacing the brittle regex `<top>` extraction.
26. **Update `.devin/tools/signature_coverage_tool.py` / `signature_coverage_reporter.py`** to use the nlu_dev_agent index or client for rule extraction.

### Phase 6 — Verification
27. Run existing `nlu_dev_agent` unit tests (`pytest`) after core changes.
28. Add tests for AVM rule-name mangling and `$SLOT` data-source resolution.
29. Run `nlu-dev-agent-validate` on `resources/anno-lang/fra-FRA/CTagger/data/jsgf/add_def.jsgf` and `alarm_add.jsgf` and confirm no unresolved imports or duplicate-rule errors.
30. Run `nlu-dev-agent-coverage` for the `alarm_add` public `<top>` rule against a few French sample utterances and check coverage.
31. Run a small end-to-end `agentic-jsgf-generation` workflow (or synthetic ticket) and confirm that `nlu-dev-agent-validate` and `nlu-dev-agent-coverage` are executed before the NLTOOLS cluster step, with `validate-and-correct-jsgf` as the final gate.

## Files to Modify

| File | Change |
|------|--------|
| `nlu_dev_agent/core/dialect.py` | Add Cerence/AAM-specific config keys |
| `nlu_dev_agent/core/document.py` | Parse AVM flags, `$SLOT`, `#ANNOTATION`; mangle rule names |
| `nlu_dev_agent/core/validator.py` | Validate AVM values and Cerence constraints |
| `nlu_dev_agent/core/cerence_config.py` | Load per-language `.devin/config/nlu_dev_agent/<lang>.yaml` |
| `nlu_dev_agent/core/cerence_data_loader.py` | Load `jsgf.stark` / `.gaz` / `features.json` |
| `nlu_dev_agent/dialects/cerence/cerence.json` | New base dialect descriptor |
| `.devin/config/nlu_dev_agent/fra-FRA.yaml` | New per-language central config |
| `nlu_dev_agent/devin_adapter/daemon.py` | New multi-language JSON daemon |
| `nlu_dev_agent/devin_adapter/client.py` | New client |
| `nlu_dev_agent/devin_adapter/cli.py` | New Devin-facing CLI |
| `nlu_dev_agent/lsp/tcp_server.py` | Optional TCP LSP entry point |
| `.devin/skills/nlu-dev-agent-*/SKILL.md` | New Devin skill wrappers |
| `.devin/skills/nlu-dev-agent-start/SKILL.md` | New server startup skill |
| `.devin/skills/agentic-jsgf-generation/SKILL.md` | Insert nlu_dev_agent steps |
| `.devin/skills/validate-and-correct-jsgf/SKILL.md` | nlu_dev_agent as first check, old skill as fallback/final gate |
| `.devin/skills/jsgf-rule-generation/SKILL.md` | Call `nlu-dev-agent-context` |
| `.devin/skills/signature-analysis/SKILL.md` | Use nlu_dev_agent for rule discovery |
| `.devin/tools/signature_coverage_tool.py` | Use nlu_dev_agent index |
| `.devin/tools/signature_coverage_reporter.py` | Use nlu_dev_agent index |

## Verification

- [ ] Existing `nlu_dev_agent` unit tests pass (`pytest`)
- [ ] `nlu-dev-agent-validate` reports no unresolved import / duplicate-rule errors on `fra-FRA` sample JSGFs
- [ ] `nlu-dev-agent-coverage` covers at least one sample utterance for `alarm_add`
- [ ] End-to-end `agentic-jsgf-generation` workflow reaches Step 12 (MJ expansion) with `nlu-dev-agent` diagnostics produced earlier and `validate-and-correct-jsgf` as fallback

## Risks & Considerations

- **AVM unification**: Rule-name mangling by AVM constraints is a pragmatic first step; a full unification engine may be needed later.
- **Free-form `TEXT` slots**: These cannot be exhaustively expanded; coverage checks may need representative sampling or wildcard tokens.
- **Indexing performance**: Re-indexing all `.jsgf` files in a language workspace can be slow; the daemon must cache results and support incremental `index` updates.
- **Dialect config maintenance**: Per-language configs add a new maintenance surface. Provide `workspace_utils.py` fallbacks when a config is absent.
- **pyjsgf gaps**: `utf-8 fr`, `$SLOT`, and AVM syntax may require additional patches beyond the existing `_strip_dialect_tags` fallback.
- **Devin/Cascade generation loop**: The `nlu-dev-agent-generate` loop is driven by the assistant, so prompt engineering and a tight feedback path are needed to avoid infinite loops or over-correction.
- **Cluster dependency**: `mj-expansion-and-testing` and `validate-and-correct-jsgf` remain the final quality gates, so the `nlu_dev_agent` integration is an accelerator rather than a replacement for cluster validation.
- **Test scope**: The local `jsgf_handler` test suite is not part of the official pipeline on this branch and should not be used as a verification gate.
