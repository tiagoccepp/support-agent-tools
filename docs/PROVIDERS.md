# LLM providers

The loop speaks **OpenAI Chat Completions with function calling**, so any
OpenAI-compatible endpoint works. Tests, evals and the demo run offline
(`MOCK_MODE=true`); set `MOCK_MODE=false` + key for a real model.

## Supported endpoints

| Provider | Base URL | Key | Cost |
|---|---|---|---|
| OpenAI | `https://api.openai.com/v1` (default) | `OPENAI_API_KEY` | paid |
| OpenRouter | `https://openrouter.ai/api/v1` | free key at openrouter.ai/keys | free `:free` models, no card |
| Ollama (local) | `http://localhost:11434/v1` | none needed | free, private |
| opencode Zen ✅ verified | `https://opencode.ai/zen/go/v1` | your Zen key | free `beam-free` model ($0) |
| other gateways | your gateway URL | your gateway key | varies |

## Configure

```bash
cp .env.example .env
# OpenRouter free example:
# MOCK_MODE=false
# OPENAI_API_KEY=sk-or-v1-...
# OPENAI_BASE_URL=https://openrouter.ai/api/v1
# MODEL=nvidia/nemotron-3.5-lightning:free
```

## Verify with one real call

```bash
python scripts/live_smoke.py
# provider=... model=... tool_called=True ... LIVE_SMOKE=OK
```

The script makes exactly one function-calling call (`get_stock` tool),
reports whether the model called the tool, and never prints the key.
CI stays keyless: tests and evals always use the rule-based mock.

## Notes

- Zen requires an `x-opencode-session` header — `scripts/live_smoke.py` sends it
  automatically (override with `OPENCODE_SESSION_ID`); other providers ignore it.

- Small/free models sometimes answer in prose instead of emitting a tool
  call; the smoke reports the outcome without failing on model behavior.
  The loop itself treats "no tool call" as a final answer (see `src/loop.py`).
- Timeouts are 60s. Production hardening (retries with backoff on 429/5xx)
  is tracked future work.
- Never commit `.env` or keys — `.gitignore` excludes them.
