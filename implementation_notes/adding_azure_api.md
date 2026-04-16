 Azure OpenAI Support for NLU Dev Agent

 Context

 The grammar generation sub-agent creates openai.OpenAI(base_url=..., api_key=...) in
 generate.py. Azure OpenAI requires the openai.AzureOpenAI client class with
 azure_endpoint + api_version, so LLM_BASE_URL cannot express an Azure deployment.

 pi-mono already has first-class Azure support via azure-openai-responses provider, reading
 AZURE_OPENAI_BASE_URL, AZURE_OPENAI_API_KEY, and AZURE_OPENAI_API_VERSION env vars.

 The goal is to align generate.py to use the same env vars so users configure Azure
 once and both the pi agent and the generation sub-agent pick it up.

 agent/generation/loop.py is unaffected — it accepts any client.
 jsgf-nlu.ts is unaffected — it just shells out to generate.py.

 Config for the whole agent

 pi agent (main conversation) — .pi/settings.json

 {
   "defaultProvider": "azure-openai-responses",
   "defaultModel": "my-deployment-name",
   ...
 }
 Plus env vars: AZURE_OPENAI_BASE_URL, AZURE_OPENAI_API_KEY (pi-mono reads these natively).

 generate.py sub-agent — same env vars, no extra config needed

 Changes to skills/jsgf-generate/generate.py

 1. New env vars (priority 2, same as pi-mono's Azure env vars)

 - AZURE_OPENAI_BASE_URL — e.g. https://my-resource.openai.azure.com/
 - AZURE_OPENAI_API_KEY — Azure API key
 - AZURE_OPENAI_API_VERSION — e.g. 2024-02-01 (defaulted when AZURE_OPENAI_BASE_URL is set)

 2. New CLI args

 - --azure-endpoint — explicit override (maps to AZURE_OPENAI_BASE_URL)
 - --azure-api-version — explicit override (maps to AZURE_OPENAI_API_VERSION)

 3. Extend _resolve_pi_config return value

 Change from (model, base_url, api_key) → (model, base_url, api_key, azure_endpoint, api_version).

 Support "defaultProvider": "azure-openai-responses" in .pi/settings.json:
 - azure_endpoint ← AZURE_OPENAI_BASE_URL env var (pi-mono reads this the same way)
 - api_key ← auth.json ["azure-openai-responses"]["key"] or AZURE_OPENAI_API_KEY
 - api_version ← AZURE_OPENAI_API_VERSION env var (default "2024-02-01")
 - base_url → None (mutually exclusive with azure_endpoint)

 4. Updated priority chain (generate.py)

 1. CLI args         --model, --base-url, --azure-endpoint, --azure-api-version
 2. LLM_* env vars   LLM_MODEL, LLM_BASE_URL, LLM_API_KEY
    Azure env vars   AZURE_OPENAI_BASE_URL, AZURE_OPENAI_API_KEY, AZURE_OPENAI_API_VERSION
 3. pi-mono config   .pi/settings.json + ~/.pi/agent/auth.json
 4. Provider env     ANTHROPIC_API_KEY (auto-sets base_url to Anthropic)
 5. Built-in default gpt-4o-mini

 5. Client construction in main() (replace line 177)

 if azure_endpoint:
     client = openai.AzureOpenAI(
         azure_endpoint=azure_endpoint,
         api_key=api_key,
         api_version=api_version or "2024-02-01",
     )
 else:
     client = openai.OpenAI(base_url=base_url, api_key=api_key)

 6. Docstring update

 Add usage example:
 # Azure OpenAI
 AZURE_OPENAI_BASE_URL=https://my-resource.openai.azure.com/ \
 AZURE_OPENAI_API_KEY=$KEY LLM_MODEL=my-deployment-name \
     python generate.py grammars/transfer.jsgf --intent "..." --examples '[...]'

 Critical files

 - skills/jsgf-generate/generate.py (lines 48–51, 54–93, 121–177) — only file to modify

 Verification

 # 1. Standard OpenAI — no regression
 LLM_API_KEY=test LLM_MODEL=gpt-4o python skills/jsgf-generate/generate.py \
     grammars/test.jsgf --intent "test" --examples '["test"]' --max-iterations 1

 # 2. Azure via env vars (same vars pi-mono uses)
 AZURE_OPENAI_BASE_URL=https://my-resource.openai.azure.com/ \
 AZURE_OPENAI_API_KEY=$AZURE_KEY LLM_MODEL=my-gpt4o-deployment \
     python skills/jsgf-generate/generate.py grammars/test.jsgf \
     --intent "greet user" --examples '["hello", "hi there"]'

 # 3. Azure via CLI args
 python skills/jsgf-generate/generate.py grammars/test.jsgf \
     --intent "greet" --examples '["hello"]' \
     --azure-endpoint https://my-resource.openai.azure.com/ \
     --model my-deployment --azure-api-version 2024-02-01

 # 4. Azure via pi-mono config (settings.json + env vars)
 # .pi/settings.json: {"defaultProvider":"azure-openai-responses","defaultModel":"my-deployment",...}
 # env: AZURE_OPENAI_BASE_URL=... AZURE_OPENAI_API_KEY=...
 python skills/jsgf-generate/generate.py grammars/test.jsgf \
     --intent "greet" --examples '["hello"]'
