/**
 * jsgf-nlu — pi coding agent extension for JSGF grammar development
 *
 * Registers three domain tools and one slash command that wire the agent
 * to the Python core layer (via CLI skills in skills/jsgf-*/):
 *
 *   jsgf_validate    — validate a .jsgf file; returns structured diagnostics
 *   jsgf_coverage    — check utterance coverage for a named rule
 *   jsgf_context     — get generation context before writing a new rule
 *   /generate-intent — interactive command to generate a JSGF rule
 */

import { Type } from "@mariozechner/pi-ai";
import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import * as path from "path";

export default function (pi: ExtensionAPI) {
	// ---------------------------------------------------------------- //
	//  Helpers                                                           //
	// ---------------------------------------------------------------- //

	/** Resolve a path relative to project root (ctx.cwd at call time). */
	function skill(ctx: { cwd: string }, scriptName: string): string {
		return path.join(ctx.cwd, "skills", scriptName);
	}

	function python(ctx: { cwd: string }): string {
		return path.join(ctx.cwd, ".venv", "bin", "python3");
	}

	// ---------------------------------------------------------------- //
	//  Tool: jsgf_validate                                              //
	// ---------------------------------------------------------------- //
	pi.registerTool({
		name: "jsgf_validate",
		label: "JSGF Validate",
		description: `Validate a JSGF grammar file against the workspace index.

Returns structured diagnostics: undefined rule references, broken imports,
duplicate rule definitions, and dialect violations (flag types, function arity).

Use this tool:
- Before and after ANY grammar edit to verify correctness
- In the correction loop after generating a grammar
- To check if a grammar file is valid before referencing its rules

Returns JSON: { file, valid, diagnostics: [{line, character, severity, message}] }`,
		parameters: Type.Object({
			file: Type.String({ description: "Path to the .jsgf file to validate (absolute or relative to cwd)" }),
			workspace: Type.Optional(
				Type.String({ description: "Workspace root directory (defaults to file's parent directory)" }),
			),
		}),

		async execute(_toolCallId, params, _signal, _onUpdate, ctx) {
			const args: string[] = [
				skill(ctx, "jsgf-validate/validate.py"),
				params.file,
			];
			if (params.workspace) {
				args.push("--workspace", params.workspace);
			} else {
				args.push("--workspace", ctx.cwd);
			}

			const result = await pi.exec(python(ctx), args);
			const text = result.stdout.trim() || result.stderr.trim();
			return {
				content: [{ type: "text", text }],
				details: { stdout: result.stdout, stderr: result.stderr, exitCode: result.code },
			};
		},
	});

	// ---------------------------------------------------------------- //
	//  Tool: jsgf_coverage                                              //
	// ---------------------------------------------------------------- //
	pi.registerTool({
		name: "jsgf_coverage",
		label: "JSGF Coverage",
		description: `Check whether a JSGF rule matches a list of test utterances.

Returns covered/uncovered lists and a coverage_ratio (0.0 = none, 1.0 = all).

Use this tool:
- After generating a grammar to verify it matches all required utterances
- To identify gaps when coverage_ratio < 1.0
- When building the correction prompt — pass the uncovered list as the target

Returns JSON: { rule, file, coverage_ratio, covered, uncovered }`,
		parameters: Type.Object({
			rule: Type.String({ description: "Rule name without angle brackets (e.g. 'greeting' not '<greeting>')" }),
			file: Type.String({ description: "Path to the .jsgf file defining the rule" }),
			utterances: Type.Array(Type.String(), {
				description: "Utterances to test against the rule",
			}),
		}),

		async execute(_toolCallId, params, _signal, _onUpdate, ctx) {
			const args: string[] = [
				skill(ctx, "jsgf-coverage/coverage.py"),
				params.rule,
				params.file,
				"--utterances",
				JSON.stringify(params.utterances),
				"--workspace",
				ctx.cwd,
			];

			const result = await pi.exec(python(ctx), args);
			const text = result.stdout.trim() || result.stderr.trim();
			return {
				content: [{ type: "text", text }],
				details: { stdout: result.stdout, stderr: result.stderr, exitCode: result.code },
			};
		},
	});

	// ---------------------------------------------------------------- //
	//  Tool: jsgf_context                                               //
	// ---------------------------------------------------------------- //
	pi.registerTool({
		name: "jsgf_context",
		label: "JSGF Context",
		description: `Get generation context for a target JSGF file before writing a new rule.

Returns:
- existing_rules: all visible rules accessible from the target file (local + imported)
- dialect_functions: engine-specific functions from jsgf-dialect.json
- similar_rules: top rules with partial coverage of your example utterances
- import_suggestions: files worth importing for shared vocabulary

ALWAYS call this before generating a new rule to avoid duplication and discover
reusable rules and dialect functions.

Returns JSON: { existing_rules, dialect_functions, similar_rules, import_suggestions }`,
		parameters: Type.Object({
			file: Type.String({ description: "Target .jsgf file (need not exist yet)" }),
			intent: Type.String({ description: "Natural language description of the intent to implement" }),
			examples: Type.Array(Type.String(), {
				description: "Example utterances the new rule should match",
			}),
		}),

		async execute(_toolCallId, params, _signal, _onUpdate, ctx) {
			const args: string[] = [
				skill(ctx, "jsgf-context/context.py"),
				params.file,
				"--intent",
				params.intent,
				"--examples",
				JSON.stringify(params.examples),
				"--workspace",
				ctx.cwd,
			];

			const result = await pi.exec(python(ctx), args);
			const text = result.stdout.trim() || result.stderr.trim();
			return {
				content: [{ type: "text", text }],
				details: { stdout: result.stdout, stderr: result.stderr, exitCode: result.code },
			};
		},
	});

	// ---------------------------------------------------------------- //
	//  Command: /generate-intent                                        //
	// ---------------------------------------------------------------- //
	pi.registerCommand("generate-intent", {
		description: "Generate a JSGF grammar rule from an intent description",
		handler: async (_args, ctx) => {
			const targetFile = await ctx.ui.input(
				"Target grammar file",
				"e.g. grammars/transfer.jsgf",
			);
			if (!targetFile) return;

			const intentDesc = await ctx.ui.input(
				"Intent description",
				"e.g. Transfer funds between accounts",
			);
			if (!intentDesc) return;

			const examplesRaw = await ctx.ui.input(
				"Example utterances",
				"Comma-separated, e.g. transfer 100 to savings, move fifty dollars",
			);
			if (!examplesRaw) return;

			const examples = examplesRaw
				.split(",")
				.map((s) => s.trim())
				.filter(Boolean);

			const prompt =
				`Generate a JSGF grammar rule for the following intent.\n\n` +
				`**Target file:** ${targetFile}\n` +
				`**Intent:** ${intentDesc}\n` +
				`**Required utterances** (the rule MUST match ALL of these):\n` +
				examples.map((e) => `  - ${e}`).join("\n") +
				`\n\n` +
				`**Steps:**\n` +
				`1. Call \`jsgf_context\` with file="${targetFile}", intent="${intentDesc}", ` +
				`and the examples above to understand available rules and dialect functions.\n` +
				`2. Write the JSGF grammar source.\n` +
				`3. Call \`jsgf_validate\` to check for structural errors.\n` +
				`4. Call \`jsgf_coverage\` to verify all utterances are covered.\n` +
				`5. If there are errors or uncovered utterances, correct and repeat from step 3.\n` +
				`6. Once valid with 100% coverage, write the grammar to \`${targetFile}\`.`;

			pi.sendUserMessage(prompt);
		},
	});
}
