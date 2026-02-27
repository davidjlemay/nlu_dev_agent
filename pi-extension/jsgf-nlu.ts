/**
 * jsgf-nlu.ts — pi coding agent extension for JSGF grammar development
 *
 * Registers three domain tools and one slash command:
 *   jsgf_validate   — validate a .gram file and return structured diagnostics
 *   jsgf_coverage   — check utterance coverage for a named rule
 *   jsgf_context    — get generation context before writing a new rule
 *   /generate-intent — interactive command to generate a JSGF rule from an intent
 */

import type { ExtensionContext } from '@mariozechner/pi-coding-agent';
import * as path from 'path';

export async function activate(ctx: ExtensionContext) {
  const { pi } = ctx;

  // ------------------------------------------------------------------ //
  //  Tool: jsgf_validate                                                 //
  // ------------------------------------------------------------------ //
  pi.registerTool({
    name: 'jsgf_validate',
    description: `Validate a JSGF grammar file against the workspace index.
Returns structured diagnostics: undefined rules, broken imports, duplicate
definitions, and dialect violations.

Use this:
- Before and after ANY grammar edit to verify correctness
- In the correction loop after generating a grammar
- To check if an existing grammar is valid before referencing its rules

Returns JSON: { file, valid, diagnostics: [{line, character, severity, message}] }`,
    parameters: {
      file: {
        type: 'string',
        description: 'Absolute or workspace-relative path to the .gram file',
      },
      workspace: {
        type: 'string',
        description: 'Workspace root (optional; defaults to file parent directory)',
        optional: true,
      },
    },
    async execute({ file, workspace }: { file: string; workspace?: string }) {
      const args = [
        path.resolve(ctx.workspaceRoot, 'skills/jsgf-validate/validate.py'),
        file,
      ];
      if (workspace) {
        args.push('--workspace', workspace);
      }
      const r = await pi.exec('python', args);
      return JSON.parse(r.stdout);
    },
  });

  // ------------------------------------------------------------------ //
  //  Tool: jsgf_coverage                                                 //
  // ------------------------------------------------------------------ //
  pi.registerTool({
    name: 'jsgf_coverage',
    description: `Check whether a JSGF rule matches a list of test utterances.
Returns covered/uncovered lists and a coverage_ratio (0.0–1.0).

Use this:
- After generating a grammar to verify it matches all required utterances
- To identify gaps when coverage_ratio < 1.0
- In the correction loop — pass uncovered utterances to the correction prompt

Returns JSON: { rule, file, coverage_ratio, covered, uncovered }`,
    parameters: {
      rule: {
        type: 'string',
        description: 'Rule name without angle brackets',
      },
      file: {
        type: 'string',
        description: 'Path to the .gram file defining the rule',
      },
      utterances: {
        type: 'array',
        items: { type: 'string' },
        description: 'List of utterances to test against the rule',
      },
    },
    async execute({ rule, file, utterances }: { rule: string; file: string; utterances: string[] }) {
      const r = await pi.exec('python', [
        path.resolve(ctx.workspaceRoot, 'skills/jsgf-coverage/coverage.py'),
        rule,
        file,
        '--utterances',
        JSON.stringify(utterances),
      ]);
      return JSON.parse(r.stdout);
    },
  });

  // ------------------------------------------------------------------ //
  //  Tool: jsgf_context                                                  //
  // ------------------------------------------------------------------ //
  pi.registerTool({
    name: 'jsgf_context',
    description: `Get generation context for a target JSGF file before writing a new rule.
Returns existing visible rules, dialect functions, similar rules, and import suggestions.

ALWAYS call this before generating a new grammar rule. It tells you:
- Which rules already exist and can be reused/imported (avoids duplication)
- Which dialect functions ($normalise, $lookup, $extract) are available
- Which existing rules partially cover your target utterances
- Which files to import for shared vocabulary

Returns JSON: { existing_rules, dialect_functions, similar_rules, import_suggestions }`,
    parameters: {
      file: {
        type: 'string',
        description: 'Target .gram file (need not exist yet)',
      },
      intent: {
        type: 'string',
        description: 'Natural language description of the intent',
      },
      examples: {
        type: 'array',
        items: { type: 'string' },
        description: 'Example utterances that the new rule should match',
      },
    },
    async execute({ file, intent, examples }: { file: string; intent: string; examples: string[] }) {
      const r = await pi.exec('python', [
        path.resolve(ctx.workspaceRoot, 'skills/jsgf-context/context.py'),
        file,
        '--intent', intent,
        '--examples', JSON.stringify(examples),
      ]);
      return JSON.parse(r.stdout);
    },
  });

  // ------------------------------------------------------------------ //
  //  Command: /generate-intent                                           //
  // ------------------------------------------------------------------ //
  pi.registerCommand('generate-intent', {
    description: 'Generate a JSGF grammar rule from an intent description',
    async handler(cmdCtx: any) {
      const targetFile = await cmdCtx.ui.prompt(
        'Target .gram file path (e.g. grammars/transfer.gram):'
      );
      const description = await cmdCtx.ui.prompt(
        'Intent description (e.g. "Transfer funds between accounts"):'
      );
      const examplesRaw = await cmdCtx.ui.prompt(
        'Example utterances (comma-separated):'
      );
      const examples = examplesRaw
        .split(',')
        .map((s: string) => s.trim())
        .filter(Boolean);

      await pi.steer(
        `Generate a JSGF grammar rule for the following intent:\n` +
        `File: ${targetFile}\n` +
        `Description: ${description}\n` +
        `Required utterances:\n${examples.map((e: string) => `  - ${e}`).join('\n')}\n\n` +
        `Step-by-step instructions:\n` +
        `1. Call jsgf_context to understand what rules and functions already exist\n` +
        `2. Write the JSGF grammar source for the intent\n` +
        `3. Call jsgf_validate to check for structural errors\n` +
        `4. Call jsgf_coverage to verify all utterances are covered\n` +
        `5. If there are errors or uncovered utterances, correct and repeat from step 3\n` +
        `6. Once valid with 100% coverage, write the grammar to ${targetFile}`
      );
    },
  });
}
