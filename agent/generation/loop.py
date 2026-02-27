"""
Agentic correction loop for JSGF grammar generation.

generate_grammar() iterates:
1. Build generation context from workspace index
2. Call LLM to generate grammar source
3. Validate diagnostics + utterance coverage
4. If perfect → return source
5. If not → build typed correction prompt and retry

Uses the Anthropic API directly (no DSPy dependency for the loop itself).
DSPy is only used in optimize.py for prompt optimisation.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from agent.api import GrammarAgentAPI, CoverageResult
from lsprotocol import types as lsp


_SYSTEM_PROMPT = """\
You are an expert JSGF (JSpeech Grammar Format) grammar engineer.
Your task is to generate valid JSGF grammar files for a proprietary speech
recognition engine.

JSGF V1.0 syntax rules:
- Header: #JSGF V1.0;
- Grammar declaration: grammar <name>;
- Public rule: public <ruleName> = expansion;
- Private rule: <ruleName> = expansion;
- Alternatives: a | b | c
- Optional: [optional text]
- Required group: (a b c)
- Rule reference: <otherRule>
- Kleene star: item*
- One or more: item+
- Tag: text {tag}

Output ONLY the raw JSGF grammar source, no markdown fences or explanation.
"""


def _build_generation_prompt(
    description: str,
    examples: list[str],
    context,
    target_file: Path,
) -> str:
    grammar_name = target_file.stem.replace('-', '_')
    ctx_lines = []

    if context.existing_rules:
        ctx_lines.append("Available rules you may reference or import:")
        for r in context.existing_rules[:10]:
            src = f"  <{r['name']}> ({'public' if r['visible'] else 'private'}) in {Path(r['file']).name}"
            if r.get('example_utterances'):
                src += f"  — e.g. {r['example_utterances'][:3]}"
            ctx_lines.append(src)

    if context.dialect_functions:
        ctx_lines.append("\nDialect functions available:")
        for fn in context.dialect_functions:
            params = ', '.join(p['name'] for p in fn['parameters'])
            ctx_lines.append(f"  ${fn['name']}({params}) → {fn['return_type']}")
            if fn.get('doc'):
                ctx_lines.append(f"    {fn['doc']}")

    if context.import_suggestions:
        ctx_lines.append("\nConsider importing from:")
        for imp in context.import_suggestions:
            ctx_lines.append(f"  {imp}")

    context_block = '\n'.join(ctx_lines)

    return (
        f"Generate a JSGF grammar named '{grammar_name}' that handles:\n"
        f"Intent: {description}\n\n"
        f"The grammar MUST match ALL of these example utterances:\n"
        + '\n'.join(f"  - {u}" for u in examples)
        + (f"\n\nWorkspace context:\n{context_block}" if context_block else "")
        + "\n\nOutput only the raw JSGF source."
    )


def _build_correction_prompt(
    original_prompt: str,
    grammar_source: str,
    diagnostics: list[lsp.Diagnostic],
    coverage: Optional[CoverageResult],
) -> str:
    parts = [
        f"The following grammar has issues that must be fixed:\n\n```\n{grammar_source}\n```\n"
    ]

    if diagnostics:
        parts.append("Structural errors to fix:")
        for d in diagnostics:
            sev = 'ERROR' if d.severity == lsp.DiagnosticSeverity.Error else 'WARNING'
            parts.append(
                f"  Line {d.range.start.line + 1}: [{sev}] {d.message}"
            )

    if coverage and coverage.uncovered:
        parts.append(f"\nUtterances not matched ({len(coverage.uncovered)} of {len(coverage.covered) + len(coverage.uncovered)}):")
        for u in coverage.uncovered:
            parts.append(f"  - {u}")
        parts.append(f"\nCurrent coverage: {coverage.coverage_ratio:.0%}")
        parts.append("The grammar must match ALL utterances above.")

    parts.append("\nOutput only the corrected JSGF source.")
    return '\n'.join(parts)


async def generate_grammar(
    client,       # anthropic.Anthropic
    api: GrammarAgentAPI,
    target_file: Path,
    description: str,
    examples: list[str],
    max_iterations: int = 5,
    model: str = 'claude-opus-4-6',
) -> Optional[str]:
    """
    Generate and iteratively correct a JSGF grammar.

    Returns the grammar source on convergence, or None if max_iterations reached.
    """
    context = api.get_generation_context(target_file, description, examples)
    prompt = _build_generation_prompt(description, examples, context, target_file)

    messages = [{'role': 'user', 'content': prompt}]

    for iteration in range(max_iterations):
        # Call LLM
        response = client.messages.create(
            model=model,
            max_tokens=4096,
            system=_SYSTEM_PROMPT,
            messages=messages,
        )
        source = response.content[0].text.strip()

        # Strip any accidental markdown fences
        if source.startswith('```'):
            lines = source.splitlines()
            source = '\n'.join(
                line for line in lines
                if not line.startswith('```')
            ).strip()

        # Validate
        diags, coverage = api.validate_generated_grammar(source, target_file, examples)

        if not diags and coverage is not None and coverage.coverage_ratio == 1.0:
            return source  # Converged

        # Build correction prompt and continue
        correction = _build_correction_prompt(prompt, source, diags, coverage)
        messages.append({'role': 'assistant', 'content': source})
        messages.append({'role': 'user', 'content': correction})

    return None  # Failed to converge
