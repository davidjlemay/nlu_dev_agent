 Dynamic Pi-Mono Prompts via Dialect Templates

 Context

 .pi/SYSTEM.md is currently a static file that hardcodes engine-specific details
 (function names $normalise/$lookup/$extract, flag types string/int/float/bool/enum,
 LHS-flags behaviour). Now that jsgf-dialect.json holds structured capabilities,
 functions, and flags config, the system prompt should be generated from that
 config — so changing the dialect (e.g. switching to an engine with no functions) keeps
 the agent's instructions accurate automatically.

 The /generate-intent command in jsgf-nlu.ts also hardcodes a generic workflow that
 doesn't mention capability constraints. It should inject engine-specific constraints at
 call time by reading jsgf-dialect.json directly in TypeScript (it's plain JSON).

 ---
 Approach

 1. Jinja2 template: .pi/SYSTEM.md.j2

 Create .pi/SYSTEM.md.j2 — a Jinja2 template that replaces .pi/SYSTEM.md as the
 source of truth. Dynamic blocks are tagged; static content (JSGF syntax reference,
 tool descriptions, file layout, workflow) is copied verbatim from the current file.

 Dynamic sections:

 {# First line — engine name #}
 You are an expert in JSGF grammar development for **{{ engine }}**.

 {# Engine constraints block — shown only when constraints are active #}
 {% if capabilities.max_public_rules or not capabilities.allow_parameterized_rules
    or capabilities.flags != "both" or capabilities.function_map is not none %}
 ## Engine constraints ({{ engine }})

 {% if capabilities.max_public_rules %}
 ⚠️ **Max {{ capabilities.max_public_rules }} public rule(s)** per root grammar.
 Library grammars (imported by others) are exempt from this limit.
 {% endif %}
 {% if not capabilities.allow_parameterized_rules %}
 ⚠️ **Parameterized rules are not supported.** Do not use `<rule[$a, $b]>` syntax.
 {% endif %}
 {% if capabilities.flags == "none" %}
 ⚠️ **Tags are not supported.** Do not use `{...}` syntax anywhere.
 {% elif capabilities.flags == "lhs_only" %}
 ⚠️ **Only LHS flags are supported.** Do not add RHS `{...}` tags.
 {% elif capabilities.flags == "rhs_only" %}
 ⚠️ **Only RHS tags are supported.** Do not use LHS flag blocks.
 {% endif %}
 {% if capabilities.function_map is not none and not capabilities.function_map %}
 ⚠️ **Custom functions are not supported** by this engine.
 {% elif capabilities.function_map %}
 Only these functions are available (with engine-specific names):
 {% for canonical, engine_name in capabilities.function_map.items() %}
 - `${{ canonical }}(...)` — called `${{ engine_name }}(...)` on the engine
 {% endfor %}
 {% endif %}
 {% endif %}

 {# Typed flags section — show allowed types from dialect config #}
 ### Typed flags in tags (RHS)
 Supported types: {{ allowed_flag_types | join(', ') or 'none' }}

 {# LHS flags section — conditional on lhs_flags_enabled #}
 {% if lhs_flags_enabled %}
 ### LHS flags and agreement variants
 ... (existing LHS section content) ...
 {% endif %}

 {# Custom functions section — dynamic from functions dict #}
 ### Custom functions
 {% if functions %}
 {% for name, fn in functions.items() %}
 - `${{ name }}(...)` — {{ fn.doc or 'no description' }}
 {% endfor %}
 {% else %}
 This engine does not support custom functions.
 {% endif %}

 2. Render script: scripts/render_pi_prompt.py

 New Python script (no new deps beyond Jinja2):

 #!/usr/bin/env python3
 """Render .pi/SYSTEM.md from .pi/SYSTEM.md.j2 + jsgf-dialect.json."""
 import sys
 from pathlib import Path
 from jinja2 import Environment, FileSystemLoader
 sys.path.insert(0, str(Path(__file__).parent.parent))
 from core.dialect import DialectRegistry

 def main():
     root = Path(__file__).parent.parent
     dialect = DialectRegistry.from_config(root / 'jsgf-dialect.json')
     env = Environment(loader=FileSystemLoader(str(root / '.pi')),
                       keep_trailing_newline=True)
     template = env.get_template('SYSTEM.md.j2')
     rendered = template.render(
         engine=dialect.engine,
         functions=dialect.functions,
         allowed_flag_types=dialect.allowed_flag_types,
         reserved_flag_keys=dialect.reserved_flag_keys,
         lhs_flags_enabled=dialect.lhs_flags_enabled,
         capabilities={
             'max_public_rules': dialect.capabilities.max_public_rules,
             'flags': dialect.capabilities.flags,
             'function_map': dialect.capabilities.function_map,
             'allow_parameterized_rules': dialect.capabilities.allow_parameterized_rules,
         },
     )
     out = root / '.pi' / 'SYSTEM.md'
     out.write_text(rendered)
     print(f"Rendered {out}", file=sys.stderr)

 if __name__ == '__main__':
     main()

 3. pi.sh — call render before launch

 # Regenerate system prompt from dialect config
 "${SCRIPT_DIR}/.venv/bin/python3" "${SCRIPT_DIR}/scripts/render_pi_prompt.py"

 exec node "${PI}" "$@"

 4. jsgf-nlu.ts — inject capabilities in /generate-intent

 The TypeScript handler reads jsgf-dialect.json directly (plain JSON, no Python needed)
 and prepends a constraints section to the workflow prompt:

 import * as fs from "node:fs";

 // In the /generate-intent handler, after collecting inputs:
 const dialectPath = path.join(ctx.cwd, "jsgf-dialect.json");
 let capsSection = "";
 if (fs.existsSync(dialectPath)) {
     const dialect = JSON.parse(fs.readFileSync(dialectPath, "utf-8"));
     const caps = dialect.capabilities ?? {};
     const lines: string[] = ["**Engine constraints:**"];
     if (caps.max_public_rules != null)
         lines.push(`- Max ${caps.max_public_rules} public rule(s) per grammar`);
     if (!caps.allow_parameterized_rules)
         lines.push("- Parameterized rules are NOT supported");
     if (caps.flags === "none")
         lines.push("- Tags/flags are NOT supported");
     else if (caps.flags === "lhs_only")
         lines.push("- Only LHS flags allowed; no RHS tags");
     else if (caps.flags === "rhs_only")
         lines.push("- Only RHS tags allowed; no LHS flags");
     if (caps.function_map !== null && caps.function_map !== undefined) {
         const fns = Object.keys(caps.function_map ?? {});
         lines.push(fns.length
             ? `- Only these functions allowed: ${fns.map(f => `$${f}`).join(", ")}`
             : "- Custom functions are NOT supported");
     }
     if (lines.length > 1) capsSection = lines.join("\n") + "\n\n";
 }

 const prompt = capsSection + `Generate a JSGF grammar rule ...`;

 5. requirements.txt — add Jinja2

 Jinja2>=3.1

 ---
 Critical Files

 ┌─────────────────────────────┬─────────────────────────────────────────────────────────────────┐
 │            File             │                             Change                              │
 ├─────────────────────────────┼─────────────────────────────────────────────────────────────────┤
 │ .pi/SYSTEM.md.j2            │ New — Jinja2 template (source of truth for system prompt)       │
 ├─────────────────────────────┼─────────────────────────────────────────────────────────────────┤
 │ .pi/SYSTEM.md               │ Generated — rendered at pi startup; no longer hand-edited       │
 ├─────────────────────────────┼─────────────────────────────────────────────────────────────────┤
 │ scripts/render_pi_prompt.py │ New — render script                                             │
 ├─────────────────────────────┼─────────────────────────────────────────────────────────────────┤
 │ pi.sh                       │ Add render call before exec node                                │
 ├─────────────────────────────┼─────────────────────────────────────────────────────────────────┤
 │ .pi/extensions/jsgf-nlu.ts  │ Read jsgf-dialect.json + inject caps in /generate-intent prompt │
 ├─────────────────────────────┼─────────────────────────────────────────────────────────────────┤
 │ requirements.txt            │ Add Jinja2>=3.1                                                 │
 └─────────────────────────────┴─────────────────────────────────────────────────────────────────┘

 ---
 Out of Scope

 - Skill docs (.pi/skills/*.md) — static, engine-agnostic
 - jsgf-context.md skill doc (missing, but separate issue)
 - Rebuilding jsgf-nlu.ts TypeScript (still needed after edits)

 ---
 Verification

 1. pip install jinja2 in venv → python3 scripts/render_pi_prompt.py → diff .pi/SYSTEM.md against the current file; static sections identical, intro line has proprietary-asr-v2
 2. Edit jsgf-dialect.json to set "max_public_rules": 1, "flags": "lhs_only", re-run render script → confirm .pi/SYSTEM.md now shows the constraints block
 3. Run ./pi.sh → pi launches with fresh SYSTEM.md (render happens before exec)
 4. Invoke /generate-intent → confirm the prompt message starts with a constraints section when caps are non-permissive
 5. Revert dialect change → re-run pi → constraints block gone from SYSTEM.md
 6. Existing 130 tests still pass (pytest tests/) — no core logic touched


 ---
  Files created/modified:

  - .pi/SYSTEM.md.j2 — Jinja2 template; source of truth for the system prompt. Dynamic blocks: engine name, constraints block (conditional), typed-flags section (conditional on flags capability), LHS-flags
  section (conditional on lhs_flags_enabled), custom functions list (filtered by function_map).
  - scripts/render_pi_prompt.py — Loads DialectRegistry from jsgf-dialect.json, renders the template, writes .pi/SYSTEM.md.
  - pi.sh — Added render call before exec node.
  - .pi/extensions/jsgf-nlu.ts — /generate-intent handler now reads jsgf-dialect.json directly, builds a constraints section (only when constraints are non-permissive), and prepends it to the prompt.
  - requirements.txt — Added Jinja2>=3.1; installed in venv.
  - .pi/SYSTEM.md — Regenerated from the template (engine proprietary-asr-v2, permissive defaults → no constraints block shown, all sections present).
