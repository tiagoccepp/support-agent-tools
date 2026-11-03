"""Agent-loop tests with mocked LLM clients (no network, no API key)."""
from __future__ import annotations

from src.loop import AgentLoop, LLMResponse, MockLLMClient, RuleBasedLLMClient, ToolCallRequest
from src.tools import email_tool


def _tc(name: str, **args) -> ToolCallRequest:
    return ToolCallRequest(name=name, arguments=args)


async def test_multi_step_run_with_mock_llm() -> None:
    llm = MockLLMClient([
        LLMResponse(tool_calls=[_tc("handoff_to", target_agent="support", reason="test")]),
        LLMResponse(tool_calls=[_tc("kb_search", query="password reset")]),
        LLMResponse(tool_calls=[_tc("db_create_ticket", customer_email="a@b.com",
                                    subject="pw reset", agent="support")]),
        LLMResponse(content="Password reset done."),
    ])
    result = await AgentLoop(llm=llm).run("I forgot my password, a@b.com")
    assert result.resolved is True
    assert result.escalated is False
    assert result.agents_path == ["triage", "support"]
    assert result.tools_called == ["handoff_to", "kb_search", "db_create_ticket"]
    assert result.ticket_id is not None


async def test_parallel_tool_calls_execute_in_one_turn() -> None:
    llm = MockLLMClient([
        LLMResponse(tool_calls=[_tc("handoff_to", target_agent="support", reason="test")]),
        LLMResponse(tool_calls=[
            _tc("kb_search", query="stock ACME-1001"),
            _tc("inventory_lookup", sku_or_query="ACME-1001"),
        ]),
        LLMResponse(content="In stock!"),
    ])
    result = await AgentLoop(llm=llm).run("Is ACME-1001 in stock?")
    assert result.tools_called == ["handoff_to", "kb_search", "inventory_lookup"]
    assert result.resolved is True


async def test_max_steps_exceeded_escalates() -> None:
    llm = MockLLMClient([
        LLMResponse(tool_calls=[_tc("handoff_to", target_agent="support", reason="test")]),
        LLMResponse(tool_calls=[_tc("kb_search", query="loop forever")]),
    ])
    result = await AgentLoop(llm=llm, max_steps=2).run("never ending ticket")
    assert result.escalated is True
    assert result.resolved is False
    assert any(s.name == "max_iterations" for s in result.steps)


async def test_invalid_handoff_is_blocked_and_escalated() -> None:
    llm = MockLLMClient([
        LLMResponse(tool_calls=[_tc("handoff_to", target_agent="billing", reason="nope")]),
    ])
    result = await AgentLoop(llm=llm).run("some ticket")
    assert result.escalated is True
    assert any(s.name == "invalid_handoff" for s in result.steps)


async def test_empty_input_rejected() -> None:
    result = await AgentLoop(llm=MockLLMClient([LLMResponse(content="x")])).run("   ")
    assert result.resolved is False
    assert "rejected" in result.final_answer.lower()


async def test_rulebased_support_resolves_end_to_end() -> None:
    result = await AgentLoop(llm=RuleBasedLLMClient()).run(
        "Hi, I forgot my password and can't log in. How do I reset it? My email is alice@example.com"
    )
    assert result.resolved is True
    assert result.escalated is False
    assert result.agents_path == ["triage", "support"]
    assert result.tools_called == ["handoff_to", "kb_search", "db_create_ticket", "email_send"]
    assert len(email_tool.get_outbox()) == 1


async def test_rulebased_escalates_gibberish() -> None:
    result = await AgentLoop(llm=RuleBasedLLMClient()).run("asdf qwer zxcv blorp 12345")
    assert result.escalated is True
    assert result.tools_called == ["handoff_to", "kb_search", "db_create_ticket", "handoff_to"]
