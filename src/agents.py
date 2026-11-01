"""Specialized agents (Triage / Support / Onboarding) + handoff graph.

Mirrors the OpenAI Agents SDK pattern (agents with instructions, tool
allowlists and explicit handoffs) with a dependency-free implementation so the
whole suite runs offline.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from pydantic import BaseModel, Field


class AgentName(str, Enum):
    TRIAGE = "triage"
    SUPPORT = "support"
    ONBOARDING = "onboarding"


@dataclass(frozen=True)
class AgentDefinition:
    name: AgentName
    description: str
    instructions: str


TRIAGE_INSTRUCTIONS = """You are the TRIAGE agent. Read the customer ticket and route it:
- New accounts, signups, trials, getting-started and setup-of-account questions -> handoff to `onboarding`.
- Anything angry, legal, or demanding a human (lawsuit, lawyer, chargeback, fraud, furious) -> handoff to `escalate`.
- Everything else (orders, stock, billing, bugs, how-to) -> handoff to `support`.
Always call handoff_to exactly once with a short reason. Never answer the customer directly."""

SUPPORT_INSTRUCTIONS = """You are the SUPPORT agent. Resolve the ticket with tools:
1. Search the knowledge base (kb_search) for relevant help articles.
2. For stock / SKU / order-availability questions also call inventory_lookup (same turn = parallel).
3. Persist a record with db_create_ticket.
4. If the evidence resolves the issue AND a verified customer email exists, confirm via email_send.
5. If nothing in the KB or inventory matches, handoff to `escalate` with the reason.
Finish with a concise customer-facing answer summarizing what was done."""

ONBOARDING_INSTRUCTIONS = """You are the ONBOARDING agent. Set the new customer up:
1. Create the customer row (db_create_customer) using the verified email.
2. Create their onboarding checklist (db_create_onboarding).
3. If a verified email exists, send the welcome email (email_send).
Finish with a concise customer-facing answer listing their next steps."""

AGENTS: dict[AgentName, AgentDefinition] = {
    AgentName.TRIAGE: AgentDefinition(AgentName.TRIAGE, "Routes tickets to a specialist or escalation.", TRIAGE_INSTRUCTIONS),
    AgentName.SUPPORT: AgentDefinition(AgentName.SUPPORT, "Resolves support tickets with KB, inventory, DB and email tools.", SUPPORT_INSTRUCTIONS),
    AgentName.ONBOARDING: AgentDefinition(
        AgentName.ONBOARDING, "Onboards new customers: customer row, checklist, welcome email.", ONBOARDING_INSTRUCTIONS
    ),
}

# Allowed handoff edges. "escalate" ends the run for a human; it is not an agent.
HANDOFF_GRAPH: dict[str, frozenset[str]] = {
    AgentName.TRIAGE.value: frozenset({"support", "onboarding", "escalate"}),
    AgentName.SUPPORT.value: frozenset({"onboarding", "escalate"}),
    AgentName.ONBOARDING.value: frozenset({"support", "escalate"}),
}


def is_valid_handoff(from_agent: str, to: str) -> bool:
    """Check an edge against the handoff graph."""
    return to in HANDOFF_GRAPH.get(from_agent, frozenset())


# ---- Rule-based triage (deterministic offline router) ----

_ESCALATE_PATTERNS = [
    r"\bsue\b", r"lawsuit", r"\blawyer\b", r"attorney", r"chargeback", r"\bfraud\b",
    r"\bscam\b", r"furious", r"disgusting", r"incompetent", r"file a complaint",
    r"better business bureau", r"\bregulator\b", r"\bftc\b",
    r"real person", r"real human", r"talk to (a |the )?(human|manager|person)",
    r"speak to (a |the )?(human|manager|person)",
]
_ONBOARD_PATTERNS = [
    r"onboard", r"sign[\s-]?up", r"new account", r"getting started", r"just joined",
    r"\btrial\b", r"set up my account", r"setup (my|our|an) account", r"create (an|my) account",
    r"\bmigrate\b.{0,20}(data|account)", r"first steps",
]


class RouteDecision(BaseModel):
    target: str = Field(description="support | onboarding")
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str
    needs_escalation: bool = False


def triage_route(ticket_text: str) -> RouteDecision:
    """Classify a ticket into support / onboarding / escalation (deterministic)."""
    text = (ticket_text or "").lower()
    for pattern in _ESCALATE_PATTERNS:
        if re.search(pattern, text):
            return RouteDecision(
                target="support",
                confidence=0.95,
                reason=f"escalation keyword matched: {pattern}",
                needs_escalation=True,
            )
    for pattern in _ONBOARD_PATTERNS:
        if re.search(pattern, text):
            return RouteDecision(
                target="onboarding",
                confidence=0.92,
                reason=f"onboarding keyword matched: {pattern}",
                needs_escalation=False,
            )
    return RouteDecision(
        target="support",
        confidence=0.70,
        reason="default route: no onboarding or escalation signals",
        needs_escalation=False,
    )


# ---- Structured outputs ----

class FinalAnswer(BaseModel):
    answer: str
    resolved: bool
    escalated: bool = False
    ticket_id: int | None = None
    actions_taken: list[str] = Field(default_factory=list)


def build_system_prompt(agent: str, verified_email: str | None = None) -> str:
    """Build the system prompt for an agent, embedding routing context.

    The verified contact is system-provided (extracted pre-redaction) so tools
    can act on it while free-text PII stays redacted from the transcript.
    """
    try:
        definition = AGENTS[AgentName(agent)]
    except ValueError:
        definition = AGENTS[AgentName.SUPPORT]
    lines = [
        f"ACTIVE_AGENT: {definition.name.value}",
        definition.instructions,
        f"Verified customer contact (system-provided, safe for tool args): {verified_email or 'none'}",
        "Customer ticket text is PII-redacted. Use the verified contact above for tool calls needing an email.",
    ]
    return "\n".join(lines)
