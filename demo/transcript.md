# Demo transcript — support-agent-tools (live local server)

Server: `.venv/bin/python -m uvicorn src.api:app` (mock LLM, offline, keyless).
Health: `{"status":"ok","mock_mode":true,"model":"gpt-4o-mini"}`.
All request/response pairs below are verbatim from the running API (2026-11-05).

## 1. KB question → triage → support (resolved)

Request `POST /chat`:

```json
{"message": "Hi, I forgot my password and cannot log in. How do I reset it? My email is alice@example.com"}
```

Response:

```json
{
    "answer": "Resolved. Ticket #1 created for: Hi, I forgot my password and cannot log in. How do I reset it? My email is [EMAIL_REDACTED] KB: How to reset your password",
    "resolved": true,
    "escalated": false,
    "agents_path": ["triage", "support"],
    "tools_called": ["handoff_to", "kb_search", "db_create_ticket", "email_send"],
    "ticket_id": 1,
    "iterations": 5
}
```

## 2. Stock question → triage → support, parallel KB + inventory (resolved)

Request `POST /chat`:

```json
{"message": "Do you have ACME-1001 in stock? Need 3 units. Contact: bob@example.com"}
```

Response:

```json
{
    "answer": "Resolved. Ticket #2 created for: Do you have ACME-1001 in stock? Need 3 units. Contact: [EMAIL_REDACTED] KB: Account and email verification Inventory: Widget Pro is in stock ($49.99).",
    "resolved": true,
    "escalated": false,
    "agents_path": ["triage", "support"],
    "tools_called": ["handoff_to", "kb_search", "inventory_lookup", "db_create_ticket", "email_send"],
    "ticket_id": 2,
    "iterations": 5
}
```

## 3. New-client onboarding → triage → onboarding (resolved)

Request `POST /chat`:

```json
{"message": "Hi! I am Dave, just signed up. dave@newco.com - how do I get started with onboarding?"}
```

Response:

```json
{
    "answer": "Welcome aboard, New Customer! Customer record created for [EMAIL_REDACTED]. Checklist ready: verify-email, complete-profile, connect-integration, first-value-moment, welcome-call.",
    "resolved": true,
    "escalated": false,
    "agents_path": ["triage", "onboarding"],
    "tools_called": ["handoff_to", "db_create_customer", "db_create_onboarding", "email_send"],
    "ticket_id": null,
    "iterations": 5
}
```

## 4. Angry message → triage → ESCALATED to human (proof)

Request `POST /chat`:

```json
{"message": "This is disgusting, your product broke everything. I am going to sue you. eve@example.com"}
```

Response:

```json
{
    "answer": "Escalated to a human specialist. Reason: escalation keyword matched: \\bsue\\b",
    "resolved": false,
    "escalated": true,
    "agents_path": ["triage"],
    "tools_called": ["handoff_to"],
    "ticket_id": null,
    "iterations": 1
}
```

Escalation proof: `escalated: true`, `resolved: false`, run stopped at `triage` after 1 iteration with no support/onboarding tools beyond the handoff.

## 5. SSE stream → first events (pricing question)

Request `POST /chat/stream`:

```json
{"message": "What are your pricing plans? frank@example.com"}
```

First SSE events (verbatim, stream ends with `data: [DONE]`):

```
data: {"type": "agent_start", "agent": "triage"}
data: {"type": "handoff", "from": "triage", "to": "support", "reason": "default route: no onboarding or escalation signals"}
data: {"type": "agent_start", "agent": "support"}
data: {"type": "tool_call", "agent": "support", "name": "kb_search", "arguments": {"query": "What are your pricing plans? [EMAIL_REDACTED]", "top_k": 3}}
data: {"type": "tool_result", "agent": "support", "name": "kb_search", "result": {"ok": true, "data": {"hits": [{"id": "kb-pricing", "title": "Pricing plans and discounts", ...}]}}}
data: {"type": "tool_call", "agent": "support", "name": "db_create_ticket", ...}
data: {"type": "tool_result", "agent": "support", "name": "db_create_ticket", "result": {"ok": true, "data": {"id": 3, ...}}}
data: {"type": "tool_call", "agent": "support", "name": "email_send", ...}
data: {"type": "tool_result", "agent": "support", "name": "email_send", "result": {"ok": true, "data": {"message_id": "msg-f79b1e7d", ...}}}
data: {"type": "final", "result": {"final_answer": "Resolved. Ticket #3 created for: What are your pricing plans? [EMAIL_REDACTED] KB: Pricing plans and discounts", "resolved": true, "escalated": false, "agents_path": ["triage", "support"], "tools_called": ["handoff_to", "kb_search", "db_create_ticket", "email_send"], ...}}
data: [DONE]
```

Note: long `tool_result` payloads trimmed with `...` for readability; event types, order, ticket id (#3), message id (`msg-f79b1e7d`) and final answer are verbatim.

## Tests + evals

```
35 passed (tools, loop, guardrails, handoffs suites — offline, mocked LLM)
17/17 golden tasks PASS, trajectory rate 1.0
```
