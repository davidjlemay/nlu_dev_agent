 Reconcile generate.py with pi-mono auth

 Context

 generate.py has its own env-var–driven LLM config (LLM_BASE_URL, LLM_API_KEY,
 LLM_MODEL) that is completely independent of pi-mono's provider/auth system. Users
 who configure their model backend once in pi-mono (via ~/.pi/agent/auth.json or
 .pi/settings.json) still have to re-configure generate.py separately. The goal is
 to make generate.py read pi-mono's configuration as a fallback, so there is one place
 to manage the model backend, while preserving standalone CLI use via LLM_* vars.

 Approach

 Add a _resolve_pi_config(workspace) helper directly in generate.py that tries to
 read pi-mono config files and returns (model, base_url, api_key). Slot it into the
 existing fallback chain as step 3 (between LLM_* env vars and raw provider env vars).

 Priority chain (generate.py)

 1. CLI args — --model, --base-url (explicit overrides, highest priority)
 2. LLM_ env vars* — LLM_MODEL, LLM_BASE_URL, LLM_API_KEY (standalone config)
 3. pi-mono config (NEW) — .pi/settings.json → defaultModel/defaultProvider, then
 ~/.pi/agent/auth.json → { provider: { type: "api_key", key: "..." } }
 4. Standard provider env vars — ANTHROPIC_API_KEY, OPENAI_API_KEY (already present
 as implicit OpenAI SDK fallback; make explicit for Anthropic base_url auto-set)
 5. Built-in defaults — gpt-4o-mini (unchanged)

 pi-mono config resolution logic

 def _resolve_pi_config(workspace: Path) -> tuple[str|None, str|None, str|None]:
     """Returns (model, base_url, api_key) from pi-mono config, or (None, None, None)."""
     # 1. Find .pi/settings.json by walking up from workspace
     # 2. Extract defaultModel + defaultProvider
     # 3. Map provider → OpenAI-compatible base_url:
     #      "anthropic" → "https://api.anthropic.com/v1"
     #      "openai"    → None
     # 4. Read ~/.pi/agent/auth.json → data[provider]["key"] (only type=="api_key")
     # 5. Return tuple; None for any value not found

 auth.json format (pi-mono)

 {
   "anthropic": { "type": "api_key", "key": "sk-ant-..." },
   "openai":    { "type": "api_key", "key": "sk-..." }
 }

 OAuth entries ("type": "oauth") are skipped — token refresh is non-trivial in Python.

 Provider → base_url map

 ┌─────────────────────────┬───────────────────────────────────┐
 │ pi-mono defaultProvider │      OpenAI-compat base_url       │
 ├─────────────────────────┼───────────────────────────────────┤
 │ anthropic               │ https://api.anthropic.com/v1      │
 ├─────────────────────────┼───────────────────────────────────┤
 │ openai                  │ None (SDK default)                │
 ├─────────────────────────┼───────────────────────────────────┤
 │ anything else           │ None (user must set LLM_BASE_URL) │
 └─────────────────────────┴───────────────────────────────────┘

 Critical file to modify

 - skills/jsgf-generate/generate.py (lines 87–106) — add _resolve_pi_config() and update
 the three variable assignments

 Changes summary

 1. Add _resolve_pi_config(workspace) helper (~30 lines) above main().
 2. In main(), after resolving LLM_* env vars, call _resolve_pi_config(workspace) and
 fill in any None values from the result.
 3. Update the docstring to document the new fallback.
 4. No new files, no new dependencies (stdlib json, pathlib, os only).

 Verification

 # 1. Confirm existing LLM_* env vars still take priority
 LLM_API_KEY=test LLM_MODEL=gpt-4o python skills/jsgf-generate/generate.py \
     grammars/test.jsgf --intent "test" --examples '["test"]' --max-iterations 1

 # 2. Set up a fake pi-mono config and confirm it's picked up
 mkdir -p /tmp/test-pi/.pi
 echo '{"defaultProvider":"anthropic","defaultModel":"claude-haiku-4-5-20251001"}' \
     > /tmp/test-pi/.pi/settings.json
 mkdir -p ~/.pi/agent
 echo '{"anthropic":{"type":"api_key","key":"'"$ANTHROPIC_API_KEY"'"}}' \
     > ~/.pi/agent/auth.json
 python skills/jsgf-generate/generate.py /tmp/test-pi/test.jsgf \
     --workspace /tmp/test-pi --intent "greet" --examples '["hello"]'

 # 3. Confirm OAuth entries are skipped gracefully (no crash)
 echo '{"anthropic":{"type":"oauth","access_token":"...","refresh_token":"..."}}' \
     > ~/.pi/agent/auth.json
 python skills/jsgf-generate/generate.py ... # should fall through to env var / default
