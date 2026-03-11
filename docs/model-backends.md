# Model Backend Configuration

The pi agent (main conversation) and the `jsgf-generate` sub-agent each have their own
model and credentials. By default the sub-agent inherits the same provider you configured
for pi, but you can point it at a different model or provider entirely.

## How the sub-agent resolves its model

`skills/jsgf-generate/generate.py` applies this priority chain, stopping at the first
value that is set:

| Priority | Source | Variables / files |
|----------|--------|-------------------|
| 1 | CLI args | `--model`, `--base-url`, `--azure-endpoint`, `--azure-api-version` |
| 2 | LLM env vars | `LLM_MODEL`, `LLM_BASE_URL`, `LLM_API_KEY` |
| 2 | Azure env vars | `AZURE_OPENAI_BASE_URL`, `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_API_VERSION` |
| 3 | pi-mono config | `.pi/settings.json` + `~/.pi/agent/auth.json` |
| 4 | Provider fallback | `ANTHROPIC_API_KEY` (auto-sets Anthropic base URL) |
| 5 | Built-in default | `gpt-4o-mini` via OpenAI |

Because LLM env vars have higher priority than pi-mono config, you can set them in your
shell to override the pi model without touching `.pi/settings.json`.

---

## Option A — Azure OpenAI (recommended for corporate deployments)

Azure is the primary provider configured in `.pi/settings.json` for this project.

### Configure pi-mono

`.pi/settings.json`:
```json
{
  "defaultProvider": "azure-openai-responses",
  "defaultModel": "my-gpt4o-deployment"
}
```

Set credentials in the environment (or in `~/.pi/agent/auth.json` — see Option B):
```bash
export AZURE_OPENAI_BASE_URL=https://my-resource.openai.azure.com/
export AZURE_OPENAI_API_KEY=<your-key>
export AZURE_OPENAI_API_VERSION=2024-02-01   # optional, defaults to 2024-02-01
```

Because the sub-agent reads the same three env vars as pi-mono, no extra configuration
is needed — both the pi conversation and grammar generation use Azure automatically.

### Override the deployment for generate only

If grammar generation should use a different (e.g. cheaper) Azure deployment:
```bash
LLM_MODEL=my-cheaper-deployment python skills/jsgf-generate/generate.py ...
```
`LLM_MODEL` overrides the model while the Azure endpoint/key env vars stay the same.

### Azure via CLI args (one-off)
```bash
python skills/jsgf-generate/generate.py grammars/transfer.gram \
    --intent "Transfer funds between accounts" \
    --examples '["transfer 100 to savings"]' \
    --azure-endpoint https://my-resource.openai.azure.com/ \
    --model my-gpt4o-deployment \
    --azure-api-version 2024-02-01
```

---

## Option B — pi-mono auth file (all providers)

`~/.pi/agent/auth.json` stores API keys for any provider. The sub-agent reads this file
when pi-mono config is reached in the priority chain (priority 3).

```json
{
  "anthropic":              { "type": "api_key", "key": "sk-ant-..." },
  "openai":                 { "type": "api_key", "key": "sk-..." },
  "azure-openai-responses": { "type": "api_key", "key": "<azure-key>" }
}
```

The `key` field can be:
- A literal value: `"sk-ant-..."`
- An env var name: `"MY_ANTHROPIC_KEY"` (pi-mono resolves it)
- A shell command: `"!op read 'op://vault/item/anthropic'"` (pi-mono executes it)

> **Note:** The sub-agent only reads literal `api_key` entries from auth.json. OAuth
> tokens and shell-command keys stored there are consumed by pi-mono directly; the
> sub-agent falls back to env vars for those providers.

---

## Option C — OpenAI (direct)

```bash
export OPENAI_API_KEY=sk-...          # picked up by the openai SDK automatically
# or explicitly:
export LLM_API_KEY=sk-...

# run pi
./pi.sh

# generate (inherits from pi-mono config, or uses OPENAI_API_KEY implicitly)
python skills/jsgf-generate/generate.py grammars/transfer.gram \
    --intent "..." --examples '[...]'
```

---

## Option D — Anthropic

```bash
export ANTHROPIC_API_KEY=sk-ant-...

# pi-mono settings.json:
# { "defaultProvider": "anthropic", "defaultModel": "claude-opus-4-6" }

# The sub-agent auto-detects ANTHROPIC_API_KEY and sets the Anthropic base URL.
# To use a different Anthropic model for generation only:
LLM_MODEL=claude-haiku-4-5-20251001 python skills/jsgf-generate/generate.py ...
```

---

## Option E — Local / self-hosted (Ollama, vLLM, LM Studio)

Any OpenAI-compatible server:
```bash
LLM_BASE_URL=http://localhost:11434/v1 LLM_API_KEY=ollama LLM_MODEL=llama3 \
    python skills/jsgf-generate/generate.py grammars/transfer.gram \
    --intent "..." --examples '[...]'
```

To use a local model for generation while keeping a cloud provider for pi:
```bash
# pi still uses .pi/settings.json (e.g. Azure)
# generation uses local Ollama
LLM_BASE_URL=http://localhost:11434/v1 LLM_API_KEY=ollama LLM_MODEL=llama3 \
    ./pi.sh
# or set them in your shell before starting pi so the sub-agent picks them up
```

---

## Using a different model for generate than for pi

Because LLM env vars sit above pi-mono config in the priority chain, set them before
invoking the sub-agent (or before starting pi) to override just grammar generation:

```bash
# pi uses Azure gpt-4o (from .pi/settings.json + AZURE_OPENAI_*)
# generation uses a cheaper Azure deployment
export LLM_MODEL=my-gpt4o-mini-deployment
./pi.sh

# generation uses a completely different provider (OpenAI direct)
export LLM_BASE_URL=https://api.openai.com/v1
export LLM_API_KEY=sk-...
export LLM_MODEL=gpt-4o-mini
./pi.sh
```

Or pass `--model` directly when calling generate:
```bash
python skills/jsgf-generate/generate.py grammars/transfer.gram \
    --model my-gpt4o-mini-deployment \
    --intent "..." --examples '[...]'
```

`--model` is the highest-priority override and only affects that single invocation.
