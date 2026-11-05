# Security & confidentiality notes

## Done

- PII redaction in and out (`src/guardrails.py`): emails, phones, SSNs and
  card numbers become `[EMAIL_REDACTED]` etc. before the LLM sees them and in
  stored/logged text. Verified in `demo/transcript.md`.
- Input validation (length caps, shape checks) and an iteration cap
  (`MAX_STEPS`) bound abuse and runaway loops.
- Secrets from env/`.env` only; `.env` gitignored; live smoke prints key last4 only.
- Escalation-by-design: anger/legal/human-request signals stop the run at
  triage instead of letting the agent improvise on sensitive cases.

## Known tradeoffs (demo scope)

- The demo stores `customer_email` in SQLite to make onboarding/ticket flows
  tangible. All data here is mock; production would tokenize contact details
  and add a retention/deletion policy.
- The mock email tool writes to an in-memory outbox — nothing ever sends.
