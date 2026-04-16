# Azure OpenAI URL Configuration Gotcha

## The Problem

Azure OpenAI exposes two distinct API surfaces with different URL schemes, and the
`AZURE_OPENAI_BASE_URL` environment variable means something subtly different for each.

### Chat Completions API (`gpt-5.2` and earlier deployment-based models)

URL pattern:
```
{base_endpoint}/openai/deployments/{deployment-name}/chat/completions?api-version={version}
```

The Python `openai.AzureOpenAI` SDK constructs this path internally when given
`azure_endpoint`. The env var should be the **bare endpoint** — no `/openai/v1` suffix:

```
AZURE_OPENAI_BASE_URL=https://nlu-aoai-gpt4-dev-use2.openai.azure.com
```

### Responses API (`gpt-5.3-codex` and newer model-in-body models)

URL pattern:
```
{base}/openai/v1/responses
```

Both the TypeScript `AzureOpenAI` SDK (used by pi-mono) and the Python SDK (used by the
generate skill) append the API path to `baseURL` directly. The env var must therefore
include the `/openai/v1` path component:

```
AZURE_OPENAI_BASE_URL=https://<resource>.openai.azure.com/openai/v1
```

Without it, requests land on `/responses` instead of `/openai/v1/responses` and Azure
returns **404 Resource Not Found**.

## Recommended Setup

If you only use Responses API models (e.g. `gpt-5.3-codex`), set:

```bash
AZURE_OPENAI_BASE_URL=https://<resource>.openai.azure.com/openai/v1
AZURE_OPENAI_API_KEY=<key>
AZURE_OPENAI_API_VERSION=2025-01-01-preview
```

If you need both Chat Completions and Responses API models, use
`AZURE_OPENAI_RESOURCE_NAME` instead of `AZURE_OPENAI_BASE_URL`. pi-mono's
`buildDefaultBaseUrl` constructs the correct `/openai/v1`-suffixed URL from the
resource name, while the Python generate skill can derive the endpoint independently:

```bash
AZURE_OPENAI_RESOURCE_NAME=<resource>
AZURE_OPENAI_API_KEY=<key>
AZURE_OPENAI_API_VERSION=2025-01-01-preview
# Leave AZURE_OPENAI_BASE_URL unset
```

## How Each Component Uses the URL

| Component | Env var consumed | Expected format |
|---|---|---|
| `generate.py` (chat completions) | `AZURE_OPENAI_BASE_URL` as `azure_endpoint` | `https://<resource>.openai.azure.com` |
| `generate.py` (responses API) | `AZURE_OPENAI_BASE_URL` as `azure_endpoint` | same — Python SDK handles path |
| pi-mono `azure-openai-responses` | `AZURE_OPENAI_BASE_URL` as `baseURL` | `https://<resource>.openai.azure.com/openai/v1` |
| pi-mono fallback | `AZURE_OPENAI_RESOURCE_NAME` | resource name only, no URL |

## Root Cause

The Chat Completions SDK takes an *endpoint* and builds deployment URLs itself.
The Responses SDK takes a *base URL* and appends only the API method name (`/responses`).
Azure requires `/openai/v1/responses` — so the `/openai/v1` segment must come from
`baseURL`, not from the SDK.
