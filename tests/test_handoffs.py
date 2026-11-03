"""Handoff tests: triage routing, graph validity, full cross-agent paths."""
from __future__ import annotations

from src.agents import is_valid_handoff, triage_route
from src.loop import AgentLoop, RuleBasedLLMClient
from src.tools import email_tool


def test_triage_routes_to_onboarding() -> None:
    decision = triage_route("Hi, we just signed up and need help getting started")
    assert decision.needs_escalation is False
    assert decision.target == "onboarding"


def test_triage_routes_to_support_by_default() -> None:
    decision = triage_route("Where is my order? Tracking shows nothing.")
    assert decision.needs_escalation is False
    assert decision.target == "support"


def test_triage_does_not_misroute_api_setup() -> None:
    decision = triage_route("How do I set up the API integration? Getting auth errors.")
    assert decision.target == "support"


def test_triage_flags_escalation() -> None:
    decision = triage_route("This is a scam, I am calling my lawyer to sue you")
    assert decision.needs_escalation is True
    human = triage_route("Let me talk to a real person right now")
    assert human.needs_escalation is True


def test_handoff_graph_edges() -> None:
    assert is_valid_handoff("triage", "support") is True
    assert is_valid_handoff("triage", "onboarding") is True
    assert is_valid_handoff("triage", "escalate") is True
    assert is_valid_handoff("support", "onboarding") is True
    assert is_valid_handoff("support", "triage") is False
    assert is_valid_handoff("triage", "billing") is False
    assert is_valid_handoff("onboarding", "support") is True


async def test_full_triage_to_onboarding_path() -> None:
    result = await AgentLoop(llm=RuleBasedLLMClient()).run(
        "Hi! I'm Dave, just signed up. dave@newco.com - how do I get started with onboarding?"
    )
    assert result.resolved is True
    assert result.agents_path == ["triage", "onboarding"]
    assert result.tools_called == ["handoff_to", "db_create_customer", "db_create_onboarding", "email_send"]
    assert email_tool.get_outbox()[0].to == "dave@newco.com"


async def test_full_triage_to_escalate_path() -> None:
    result = await AgentLoop(llm=RuleBasedLLMClient()).run(
        "This is disgusting, your product broke everything. I'm going to sue you."
    )
    assert result.escalated is True
    assert result.agents_path == ["triage"]
    assert result.tools_called == ["handoff_to"]
