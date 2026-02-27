#!/usr/bin/env python3
"""
jsgf-generate: Generate a JSGF rule from a natural-language intent description.

This is a thin wrapper over the agentic correction loop. It requires an
ANTHROPIC_API_KEY environment variable and the `anthropic` package.

Usage:
    python generate.py <file.gram> \
        --intent "Transfer funds between accounts" \
        --examples '["transfer 100 to savings", "move fifty dollars"]'

Outputs the generated grammar source to stdout and validation results to stderr.
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_HERE))

from core.dialect import DialectRegistry
from core.index import GrammarIndex
from agent.api import GrammarAgentAPI


def main():
    parser = argparse.ArgumentParser(description='Generate a JSGF rule from an intent description')
    parser.add_argument('file', help='Target .gram file to write')
    parser.add_argument('--intent', '-i', required=True, help='Intent description')
    parser.add_argument(
        '--examples', '-e',
        required=True,
        help='JSON array of example utterances that the rule must match',
    )
    parser.add_argument(
        '--workspace', '-w',
        default=None,
        help='Workspace root (default: parent directory of file)',
    )
    parser.add_argument(
        '--max-iterations', '-n',
        type=int,
        default=5,
        help='Maximum correction iterations (default: 5)',
    )
    args = parser.parse_args()

    file_path = Path(args.file).resolve()
    workspace = Path(args.workspace).resolve() if args.workspace else file_path.parent

    try:
        examples = json.loads(args.examples)
    except json.JSONDecodeError as e:
        print(f"Error: Invalid --examples JSON: {e}", file=sys.stderr)
        sys.exit(1)

    dialect_cfg = workspace / 'jsgf-dialect.json'
    dialect = (
        DialectRegistry.from_config(dialect_cfg)
        if dialect_cfg.exists()
        else DialectRegistry.standard()
    )
    index = GrammarIndex(workspace, dialect)
    index.index_workspace()
    api = GrammarAgentAPI(index)

    try:
        from agent.generation.loop import generate_grammar
        import anthropic

        client = anthropic.Anthropic()

        async def run():
            result = await generate_grammar(
                client=client,
                api=api,
                target_file=file_path,
                description=args.intent,
                examples=examples,
                max_iterations=args.max_iterations,
            )
            return result

        source = asyncio.run(run())

        if source is None:
            print("Error: Generation failed to converge after maximum iterations", file=sys.stderr)
            sys.exit(1)

        print(source)

    except ImportError as e:
        print(
            f"Error: {e}\n"
            "Install the anthropic package: pip install anthropic\n"
            "Then set ANTHROPIC_API_KEY in your environment.",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == '__main__':
    main()
