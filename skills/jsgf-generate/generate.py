#!/usr/bin/env python3
"""
jsgf-generate: Generate a JSGF rule from a natural-language intent description.

This is a thin wrapper over the agentic correction loop. It works with any
OpenAI-compatible LLM provider (OpenAI, Anthropic, Ollama, OpenRouter, etc.)
as well as Azure OpenAI.

Configuration (in priority order):
    1. CLI args         --model, --base-url, --azure-endpoint, --azure-api-version
    2. LLM_* env vars   LLM_MODEL, LLM_BASE_URL, LLM_API_KEY
       Azure env vars   AZURE_OPENAI_BASE_URL, AZURE_OPENAI_API_KEY, AZURE_OPENAI_API_VERSION
    3. pi-mono config   .pi/settings.json (defaultModel/defaultProvider) +
                        ~/.pi/agent/auth.json (api_key entries only)
    4. Provider env     ANTHROPIC_API_KEY, OPENAI_API_KEY (implicit SDK fallback)
    5. Built-in default gpt-4o-mini

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

    # Azure OpenAI
    AZURE_OPENAI_BASE_URL=https://my-resource.openai.azure.com/ \
    AZURE_OPENAI_API_KEY=$KEY LLM_MODEL=my-deployment-name \
        python generate.py grammars/transfer.gram --intent "..." --examples '[...]'

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


_PROVIDER_BASE_URL = {
    'anthropic': 'https://api.anthropic.com/v1',
    'openai': None,
}


def _resolve_pi_config(workspace: Path) -> tuple:
    """Return (model, base_url, api_key, azure_endpoint, api_version) from pi-mono config,
    or (None, None, None, None, None).

    Searches for .pi/settings.json by walking up from workspace, then reads
    ~/.pi/agent/auth.json for the corresponding provider's API key.
    OAuth entries are skipped (token refresh is non-trivial in Python).

    For provider 'azure-openai-responses', reads AZURE_OPENAI_BASE_URL,
    AZURE_OPENAI_API_KEY, and AZURE_OPENAI_API_VERSION env vars (same as pi-mono).
    """
    # Walk up from workspace to find .pi/settings.json
    settings_path = None
    for parent in [workspace, *workspace.parents]:
        candidate = parent / '.pi' / 'settings.json'
        if candidate.exists():
            settings_path = candidate
            break

    if settings_path is None:
        return (None, None, None, None, None)

    try:
        settings = json.loads(settings_path.read_text())
    except (json.JSONDecodeError, OSError):
        return (None, None, None, None, None)

    pi_model = settings.get('defaultModel') or None
    provider = settings.get('defaultProvider') or None

    # Azure provider: read the same env vars pi-mono uses
    if provider == 'azure-openai-responses':
        azure_endpoint = os.environ.get('AZURE_OPENAI_BASE_URL') or None
        api_version = os.environ.get('AZURE_OPENAI_API_VERSION') or '2024-02-01'
        pi_api_key = os.environ.get('AZURE_OPENAI_API_KEY') or None
        # Also check auth.json as fallback for api_key
        if not pi_api_key:
            auth_path = Path.home() / '.pi' / 'agent' / 'auth.json'
            try:
                auth = json.loads(auth_path.read_text())
                entry = auth.get(provider, {})
                if entry.get('type') == 'api_key':
                    pi_api_key = entry.get('key') or None
            except (json.JSONDecodeError, OSError):
                pass
        return (pi_model, None, pi_api_key, azure_endpoint, api_version)

    pi_base_url = _PROVIDER_BASE_URL.get(provider) if provider else None

    # Read API key from ~/.pi/agent/auth.json
    pi_api_key = None
    if provider:
        auth_path = Path.home() / '.pi' / 'agent' / 'auth.json'
        try:
            auth = json.loads(auth_path.read_text())
            entry = auth.get(provider, {})
            if entry.get('type') == 'api_key':
                pi_api_key = entry.get('key') or None
        except (json.JSONDecodeError, OSError):
            pass

    return (pi_model, pi_base_url, pi_api_key, None, None)


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
    parser.add_argument(
        '--azure-endpoint',
        default=None,
        help='Azure OpenAI endpoint URL (default: AZURE_OPENAI_BASE_URL env var)',
    )
    parser.add_argument(
        '--azure-api-version',
        default=None,
        help='Azure OpenAI API version (default: AZURE_OPENAI_API_VERSION env var, or 2024-02-01)',
    )
    args = parser.parse_args()

    file_path = Path(args.file).resolve()
    workspace = Path(args.workspace).resolve() if args.workspace else file_path.parent

    try:
        examples = json.loads(args.examples)
    except json.JSONDecodeError as e:
        print(f"Error: Invalid --examples JSON: {e}", file=sys.stderr)
        sys.exit(1)

    # Priority: CLI args > LLM_* / Azure env vars > pi-mono config > provider env vars > defaults
    model = args.model or os.environ.get('LLM_MODEL')
    base_url = args.base_url or os.environ.get('LLM_BASE_URL') or None
    api_key = os.environ.get('LLM_API_KEY') or None
    azure_endpoint = args.azure_endpoint or os.environ.get('AZURE_OPENAI_BASE_URL') or None
    api_version = args.azure_api_version or os.environ.get('AZURE_OPENAI_API_VERSION') or None
    if not api_key and azure_endpoint:
        api_key = os.environ.get('AZURE_OPENAI_API_KEY') or None

    # Fall through to pi-mono config for any values still unset
    if not model or not api_key:
        pi_model, pi_base_url, pi_api_key, pi_azure_endpoint, pi_api_version = _resolve_pi_config(workspace)
        if not model:
            model = pi_model
        if not azure_endpoint and not base_url:
            azure_endpoint = pi_azure_endpoint
            base_url = pi_base_url
        if not api_key:
            api_key = pi_api_key
        if not api_version:
            api_version = pi_api_version

    # Final default for model
    if not model:
        model = 'gpt-4o-mini'

    # Explicit Anthropic key fallback (so ANTHROPIC_API_KEY is recognised without LLM_API_KEY)
    if not api_key and not base_url and not azure_endpoint:
        api_key = os.environ.get('ANTHROPIC_API_KEY') or None
        if api_key:
            base_url = _PROVIDER_BASE_URL['anthropic']

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

        if azure_endpoint:
            client = openai.AzureOpenAI(
                azure_endpoint=azure_endpoint,
                api_key=api_key,
                api_version=api_version or "2024-02-01",
            )
        else:
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
