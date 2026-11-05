#!/usr/bin/env python3
"""Live smoke: ONE real function-calling call to an OpenAI-compatible LLM API.

Reads OPENAI_API_KEY / OPENAI_BASE_URL / MODEL from env (see .env.example).
Refuses to run without a key (except localhost endpoints like Ollama).
Never prints the key. Exits nonzero on HTTP/API/shape errors.
Note: small/free models sometimes answer in prose instead of calling the tool;
the script reports what happened without failing on model behavior.
"""
import json
import os
import sys
import time
import urllib.request

BASE = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
KEY = os.getenv("OPENAI_API_KEY", "")
MODEL = os.getenv("MODEL", "gpt-4o-mini")
LOCAL = "localhost" in BASE or "127.0.0.1" in BASE

if not KEY and not LOCAL:
    print("Missing OPENAI_API_KEY. See docs/PROVIDERS.md for free options (OpenRouter :free, Ollama).")
    sys.exit(2)

payload = {
    "model": MODEL,
    "temperature": 0.0,
    "max_tokens": 1024,  # reasoning models spend tokens thinking before answering
    "tools": [{
        "type": "function",
        "function": {
            "name": "get_stock",
            "description": "Look up inventory for a product SKU.",
            "parameters": {"type": "object", "properties": {"sku": {"type": "string"}}, "required": ["sku"]},
        },
    }],
    "tool_choice": "auto",
    "messages": [{"role": "user", "content": "Do you have ACME-1001 in stock?"}],
}
req = urllib.request.Request(
    f"{BASE}/chat/completions",
    data=json.dumps(payload).encode(),
    headers={"Content-Type": "application/json", "Authorization": f"Bearer {KEY}", "User-Agent": "portfolio-live-smoke/1.0", "x-opencode-session": os.getenv("OPENCODE_SESSION_ID", "live-smoke")},  # Zen API requires the session header; ignored by OpenAI/OpenRouter
)
t0 = time.time()
try:
    with urllib.request.urlopen(req, timeout=60) as r:
        body = json.load(r)
except Exception as e:  # noqa: BLE001 - smoke script, surface the error
    print(f"LIVE_SMOKE=ERROR {type(e).__name__}: {e}")
    sys.exit(1)
dt = (time.time() - t0) * 1000
msg = body["choices"][0]["message"]
calls = msg.get("tool_calls") or []
print(f"provider={BASE} model={MODEL} key=***{KEY[-4:] if KEY else 'none'} latency_ms={dt:.0f}")
print(f"tool_called={bool(calls)} content={(msg.get('content') or '')[:200]}")
for c in calls:
    print(f"tool={c['function']['name']} args={c['function'].get('arguments')}")
print("LIVE_SMOKE=OK")
