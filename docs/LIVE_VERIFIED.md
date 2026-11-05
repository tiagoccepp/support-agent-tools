# Live verification

Verified against a real LLM API via `scripts/live_smoke.py` (exactly one real
call, stdlib only, key never printed).

- Date: 2026-11-05
- Provider: opencode Zen — OpenAI-compatible `https://opencode.ai/zen/go/v1`
- Model: `beam-free` (free tier, $0)
- Key: local file, shown redacted below

```text
provider=https://opencode.ai/zen/go/v1 model=beam-free key=*** latency_ms=1233
tool_called=True content=
tool=get_stock args={"sku": "ACME-1001"}
LIVE_SMOKE=OK
```

What this proves: real function-calling works end-to-end — the model received
the `get_stock` tool schema and emitted a valid tool call with the correct
arguments (`ACME-1001` extracted from the user message).
