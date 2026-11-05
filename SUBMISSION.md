# Support Agent Tools — submission one-pager

Production-grade **multi-agent LLM system** for client onboarding + support: explicit tool-use loop, parallel tool calls, agent handoffs (Triage → Support / Onboarding → Escalate), guardrails (PII redaction, validation, max-steps). OpenAI Agents SDK pattern, provider-agnostic at test time.

## Agent topology (5 lines)

1. Triage classifies every message: onboarding signals → Onboarding; anger/legal/human-request → Escalate; else Support.
2. Support resolves via tools: `kb_search`, `inventory_lookup`, `db_create_ticket`, `email_send` (parallel where independent).
3. Onboarding creates customer + checklist records and sends the welcome email.
4. Escalate stops the run at triage with a reason (e.g. legal threat) — `escalated: true`, no guessing.
5. Guardrails wrap everything: PII redaction in/out, input validation, iteration cap, trajectory logging.

## Run locally (no API keys)

```bash
./demo.sh            # boots offline API on :8000 (mock LLM)
pytest -q            # 35 tests, offline
python eval/run_evals.py   # 17 golden tasks, trajectory evals, rate 1.0
```

Set `MOCK_MODE=false` + `OPENAI_API_KEY` for the real-model path (httpx client).

## Key files to read

- `src/loop.py` — explicit agent loop (parallel calls, max-steps, invalid-handoff handling)
- `src/agents.py` — Triage/Support/Onboarding prompts + handoff routing
- `src/guardrails.py` — PII redaction, validation
- `src/tools/` — inventory (8-SKU mock), KB search, SQLite tickets/customers, mock email outbox
- `src/evals.py`, `eval/golden_tasks.json` — trajectory F1 + agent-path + outcome
- `demo/transcript.md` — verified live transcript

## Sample exchanges (from live transcript)

- "I forgot my password…" → triage → support, ticket #1, KB "How to reset your password", email sent
- "I am going to sue you" → ESCALATED at triage, 1 iteration, reason: legal keyword
