#!/usr/bin/env python3
"""
jsgf-generate: Generate a JSGF rule from a natural-language intent description.

This is a thin wrapper over the agentic correction loop. It works with any
OpenAI-compatible LLM provider (OpenAI, Anthropic, Ollama, OpenRouter, etc.).

Configuration via environment variables:
    LLM_BASE_URL   API base URL  (default: OpenAI; use https://api.anthropic.com/v1
                   for Anthropic, http://localhost:11434/v1 for Ollama, etc.)
    LLM_API_KEY    API key       (default: OPENAI_API_KEY)
    LLM_MODEL      Default model (default: gpt-4o)

Usage:
    python generate.py <file.gram> \
        --intent "Transfer funds between accounts" \
        --examples '["transfer 100 to savings", "move fifty dollars"]'

    # Anthropic
    LLM_BASE_URL=https://api.anthropic.com/v1 LLM_API_KEY=$ANTHROPIC_API_KEY \
        python generate.py grammars/transfer.gram --model claude-opus-4-6 ...

    # Ollama (local)
    LLM_BASE_URL=http://localhost:11434/v1 LLM_API_KEY=ollama \
        python generate.py grammars/transfer.gram --model llama3 ...

Outputs the generated grammar source to stdout and validation results to stderr.
"""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_HERE))

from core.dialect import DialectRegistry
from core.index import GrammarIndex
from core.loader import DataLoader
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
    parser.add_argument(
        '--model', '-m',
        default=None,
        help='Model name (default: LLM_MODEL env var, or gpt-4o)',
    )
    parser.add_argument(
        '--base-url',
        default=None,
        help='API base URL (default: LLM_BASE_URL env var, or OpenAI default)',
    )
    args = parser.parse_args()

    file_path = Path(args.file).resolve()
    workspace = Path(args.workspace).resolve() if args.workspace else file_path.parent

    try:
        examples = json.loads(args.examples)
    except json.JSONDecodeError as e:
        print(f"Error: Invalid --examples JSON: {e}", file=sys.stderr)
        sys.exit(1)

    model = args.model or os.environ.get('LLM_MODEL', 'gpt-4o-mini')
    base_url = args.base_url or os.environ.get('LLM_BASE_URL') or None
    api_key = os.environ.get('LLM_API_KEY') or None  # falls back to OPENAI_API_KEY inside openai

    dialect_cfg = workspace / 'jsgf-dialect.json'
    dialect = (
        DialectRegistry.from_config(dialect_cfg)
        if dialect_cfg.exists()
        else DialectRegistry.standard()
    )
    index = GrammarIndex(workspace, dialect)
    index.index_workspace()
    loader = DataLoader(dialect.data_sources, dialect.lazy_loading, workspace)
    api = GrammarAgentAPI(index, loader=loader)

    try:
        from agent.generation.loop import generate_grammar
        import openai

        client = openai.OpenAI(base_url=base_url, api_key=api_key)

        async def run():
            result = await generate_grammar(
                client=client,
                api=api,
                target_file=file_path,
                description=args.intent,
                examples=examples,
                max_iterations=args.max_iterations,
                model=model,
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
            "Install the openai package: pip install openai\n"
            "Then configure your provider via LLM_BASE_URL / LLM_API_KEY / LLM_MODEL.",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == '__main__':
    main()
