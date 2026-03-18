# jsgf-generate

Generate a JSGF grammar rule from a natural-language intent description using an LLM.

## Prerequisites

```bash
pip install openai
```

Configure your provider via environment variables:

| Variable | Description |
|---|---|
| `LLM_BASE_URL` | API base URL (omit for OpenAI default) |
| `LLM_API_KEY` | API key (falls back to `OPENAI_API_KEY`) |
| `LLM_MODEL` | Default model name |

### Provider examples

```bash
# OpenAI (default)
export OPENAI_API_KEY=sk-...

# Anthropic
export LLM_BASE_URL=https://api.anthropic.com/v1
export LLM_API_KEY=$ANTHROPIC_API_KEY

# Ollama (local)
export LLM_BASE_URL=http://localhost:11434/v1
export LLM_API_KEY=ollama

# OpenRouter
export LLM_BASE_URL=https://openrouter.ai/api/v1
export LLM_API_KEY=$OPENROUTER_API_KEY
```

## Usage

```bash
python skills/jsgf-generate/generate.py grammars/transfer.jsgf \
  --intent "Transfer funds between accounts" \
  --examples '["transfer 100 to savings", "move fifty dollars to chequing"]'
```

| Argument | Default | Description |
|---|---|---|
| `file` | — | Target `.jsgf` file to write |
| `--intent` | — | Natural language intent description |
| `--examples` | — | JSON array of required utterances (all must match) |
| `--workspace` | Parent dir of file | Workspace root |
| `--max-iterations` | `5` | Maximum LLM correction attempts |
| `--model` | `LLM_MODEL` or `gpt-4o` | Model name |
| `--base-url` | `LLM_BASE_URL` | API base URL override |

## How it works

1. Calls `jsgf-context` to assemble available rules and dialect functions
2. Generates a JSGF grammar via the LLM
3. Validates with `jsgf-validate` — if there are errors, sends typed feedback
4. Checks utterance coverage — if any are uncovered, sends the uncovered list
5. Repeats until valid with 100% coverage, or gives up after `--max-iterations`

## When to use vs. jsgf-validate

| Task | Use |
|---|---|
| Check an existing grammar file | `jsgf-validate` |
| Check utterance coverage | `jsgf-coverage` |
| Understand what's available | `jsgf-context` |
| Create a new rule from scratch | `jsgf-generate` |

## Output

On success: generated grammar source is written to stdout (pipe to file with `>`).
Progress and error messages go to stderr.

```bash
python skills/jsgf-generate/generate.py grammars/transfer.jsgf \
  --intent "Transfer funds" \
  --examples '["transfer 100"]' > grammars/transfer.jsgf
```

## Notes

- Always review generated output before committing
- Use `jsgf-validate` and `jsgf-coverage` to verify the final grammar
- Generation quality improves with more specific `--examples`
