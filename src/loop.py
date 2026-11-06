"""Explicit agent loop: multi-step tool use, parallel calls, handoffs, guardrails.

Pattern follows the OpenAI Agents SDK (agent -> model -> tools -> handoff)
implemented as an explicit async loop so it runs offline with a deterministic
rule-based client, in tests with a scripted mock, and in production against
the OpenAI Chat Completions API via httpx.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import uuid
from typing import Any, Protocol

from pydantic import BaseModel, Field

from src.agents import AgentName, build_system_prompt, is_valid_handoff, triage_route
from src.config import settings
from src.guardrails import (
    MaxIterationsExceeded,
    InputValidationError,
    check_iterations,
    extract_customer_email,
    redact_pii,
    sanitize_output,
    validate_input,
)
from src.tools import execute_tool, list_tools

UNKNOWN_EMAIL = "noreply@unknown.invalid"
SKU_RE = re.compile(r"\b([A-Z]{2,}-\d+)\b")
NAME_RES = [
    re.compile(r"my name is ([A-Z][a-z]+(?: [A-Z][a-z]+)?)"),
    re.compile(r"(?:i'm|i am|this is) ([A-Z][a-z]+(?: [A-Z][a-z]+)?)"),
    re.compile(r"(?:^|\b)([A-Z][a-z]+) here\b"),
]
_QTY_RE = re.compile(r"(\d+)\s*(?:units?|pcs|pieces?)", re.IGNORECASE)

_STOCK_KEYWORDS = (
    "stock", "inventory", "sku", "availability", "in stock", "out of stock",
    "order status", "where is my order", "tracking", "backorder", "restock",
)
_BROWSE_KEYWORDS = ("catalog", "browse", "list products", "what do you sell", "product list")
_RESERVE_KEYWORDS = ("reserve", "hold", "set aside")


# ---- LLM client protocol + implementations ----

class ToolCallRequest(BaseModel):
    call_id: str = Field(default_factory=lambda: f"call-{uuid.uuid4().hex[:8]}")
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class LLMResponse(BaseModel):
    content: str = ""
    tool_calls: list[ToolCallRequest] = Field(default_factory=list)


class LLMClient(Protocol):
    async def chat(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> LLMResponse:
        ...


class MockLLMClient:
    """Scripted mock for tests. Repeats the last response once the queue drains."""

    def __init__(self, scripted: list[LLMResponse]) -> None:
        if not scripted:
            raise ValueError("MockLLMClient needs at least one scripted response")
        self._scripted = scripted
        self.calls = 0

    async def chat(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> LLMResponse:
        index = min(self.calls, len(self._scripted) - 1)
        self.calls += 1
        response = self._scripted[index]
        return LLMResponse(
            content=response.content,
            tool_calls=[
                ToolCallRequest(name=tc.name, arguments=dict(tc.arguments))
                for tc in response.tool_calls
            ],
        )


def _parse_active_agent(system_prompt: str) -> str:
    match = re.search(r"^ACTIVE_AGENT:\s*(\w+)", system_prompt or "", re.MULTILINE)
    return match.group(1) if match else AgentName.SUPPORT.value


def _parse_verified_email(system_prompt: str) -> str | None:
    match = re.search(r"Verified customer contact.*?:\s*(\S+)", system_prompt or "")
    if not match or match.group(1).lower() == "none":
        return None
    return match.group(1)


def _called_tools(messages: list[dict[str, Any]]) -> list[str]:
    called: list[str] = []
    for message in messages:
        for tool_call in message.get("tool_calls", []) or []:
            called.append(tool_call.get("name", ""))
    return called


def _called_after_last_system(messages: list[dict[str, Any]]) -> list[str]:
    """Tool names called by the current agent (after the latest system prompt)."""
    names: list[str] = []
    for message in reversed(messages):
        if message.get("role") == "system":
            break
        for tool_call in message.get("tool_calls", []) or []:
            names.append(tool_call.get("name", ""))
    return names


def _tool_payloads(messages: list[dict[str, Any]]) -> dict[str, Any]:
    payloads: dict[str, Any] = {}
    for message in messages:
        if message.get("role") == "tool" and message.get("name"):
            try:
                payloads[message["name"]] = json.loads(message.get("content", "{}"))
            except (json.JSONDecodeError, TypeError):
                payloads[message["name"]] = {}
    return payloads


def _tool_data(payload: dict[str, Any]) -> Any:
    if isinstance(payload, dict) and payload.get("ok"):
        return payload.get("data")
    return None


class RuleBasedLLMClient:
    """Deterministic offline stand-in for an LLM with function calling.

    Encodes the same policy as the agent instructions (KB first, parallel
    inventory lookup when relevant, persist records, confirm by email, escalate
    on zero evidence) so evals and demos run without an API key.
    """

    async def chat(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> LLMResponse:
        _ = tools  # policy is fixed; schemas come from the registry
        systems = [m.get("content", "") for m in messages if m.get("role") == "system"]
        system = systems[-1] if systems else ""  # latest wins: handoffs append a new prompt
        ticket = next((m.get("content", "") for m in messages if m.get("role") == "user"), "")
        agent = _parse_active_agent(system)
        verified = _parse_verified_email(system)
        called = _called_tools(messages)
        recent_called = _called_after_last_system(messages)
        payloads = _tool_payloads(messages)
        lowered = ticket.lower()

        if agent == AgentName.TRIAGE.value:
            decision = triage_route(ticket)
            target = "escalate" if decision.needs_escalation else decision.target
            return LLMResponse(tool_calls=[
                ToolCallRequest(name="handoff_to", arguments={"target_agent": target, "reason": decision.reason})
            ])
        if agent == AgentName.ONBOARDING.value:
            return self._onboarding_turn(ticket, lowered, called, verified)
        return self._support_turn(ticket, lowered, called, recent_called, payloads, verified)

    def _support_turn(
        self,
        ticket: str,
        lowered: str,
        called: list[str],
        recent_called: list[str],
        payloads: dict[str, Any],
        verified: str | None,
    ) -> LLMResponse:
        calls: list[ToolCallRequest] = []
        if "kb_search" not in called:
            calls.append(ToolCallRequest(name="kb_search", arguments={"query": ticket[:200], "top_k": 3}))
        wants_stock = bool(SKU_RE.search(ticket)) or any(k in lowered for k in _STOCK_KEYWORDS)
        wants_browse = any(k in lowered for k in _BROWSE_KEYWORDS)
        if wants_browse and "inventory_list_products" not in called and "inventory_lookup" not in called:
            calls.append(ToolCallRequest(name="inventory_list_products", arguments={"in_stock_only": False}))
        elif wants_stock and "inventory_lookup" not in called and "inventory_list_products" not in called:
            sku_match = SKU_RE.search(ticket.upper())
            query = sku_match.group(1) if sku_match else ticket[:200]
            calls.append(ToolCallRequest(name="inventory_lookup", arguments={"sku_or_query": query}))
        if calls:
            return LLMResponse(tool_calls=calls)  # first turn: KB + inventory run in parallel

        if "db_create_ticket" not in called:
            return LLMResponse(tool_calls=[ToolCallRequest(name="db_create_ticket", arguments={
                "customer_email": verified or UNKNOWN_EMAIL,
                "subject": ticket[:80] or "support request",
                "agent": "support",
                "summary": ticket[:300],
            })])

        kb_hits = (_tool_data(payloads.get("kb_search", {})) or {}).get("hits", [])
        inventory = _tool_data(payloads.get("inventory_lookup", {})) or {}
        product_list = _tool_data(payloads.get("inventory_list_products", {})) or []
        has_evidence = bool(kb_hits) or bool(inventory.get("found")) or bool(product_list)

        if not has_evidence and "handoff_to" not in recent_called:
            return LLMResponse(tool_calls=[ToolCallRequest(name="handoff_to", arguments={
                "target_agent": "escalate",
                "reason": "no KB match and no inventory record; needs a human",
            })])

        wants_reserve = any(k in lowered for k in _RESERVE_KEYWORDS)
        sku_match = SKU_RE.search(ticket.upper())
        if wants_reserve and sku_match and "inventory_reserve" not in called:
            qty_match = _QTY_RE.search(ticket)
            return LLMResponse(tool_calls=[ToolCallRequest(name="inventory_reserve", arguments={
                "sku": sku_match.group(1), "quantity": int(qty_match.group(1)) if qty_match else 1,
            })])

        if verified and "email_send" not in called:
            ticket_data = _tool_data(payloads.get("db_create_ticket", {})) or {}
            ticket_id = ticket_data.get("id", "?")
            return LLMResponse(tool_calls=[ToolCallRequest(name="email_send", arguments={
                "to": verified,
                "subject": f"Re: your support request (ticket #{ticket_id})",
                "body": self._support_email_body(ticket, kb_hits, inventory, ticket_id),
            })])

        ticket_data = _tool_data(payloads.get("db_create_ticket", {})) or {}
        return LLMResponse(content=self._support_final(ticket, kb_hits, inventory, ticket_data.get("id")))

    def _support_email_body(
        self, ticket: str, kb_hits: list[dict[str, Any]], inventory: dict[str, Any], ticket_id: Any
    ) -> str:
        parts = [f"Hi — your ticket #{ticket_id} is resolved.", f"Request: {ticket[:160]}"]
        if kb_hits:
            parts.append(f"Help article: {kb_hits[0].get('title')} — {kb_hits[0].get('snippet', '')[:160]}")
        if inventory.get("found"):
            availability = "in stock" if inventory.get("in_stock") else "currently out of stock"
            parts.append(f"Inventory: {inventory.get('name')} ({inventory.get('sku')}) is {availability}.")
        parts.append("Reply to this email if you need anything else.")
        return "\n".join(parts)

    def _support_final(
        self, ticket: str, kb_hits: list[dict[str, Any]], inventory: dict[str, Any], ticket_id: Any
    ) -> str:
        parts = [f"Resolved. Ticket #{ticket_id} created for: {ticket[:120]}"]
        if kb_hits:
            parts.append(f"KB: {kb_hits[0].get('title')}")
        if inventory.get("found"):
            availability = "in stock" if inventory.get("in_stock") else "out of stock"
            parts.append(f"Inventory: {inventory.get('name')} is {availability} (${inventory.get('price_usd')}).")
        return " ".join(parts)

    def _onboarding_turn(
        self, ticket: str, lowered: str, called: list[str], verified: str | None
    ) -> LLMResponse:
        email = verified or UNKNOWN_EMAIL
        if "db_create_customer" not in called:
            return LLMResponse(tool_calls=[ToolCallRequest(name="db_create_customer", arguments={
                "name": self._extract_name(ticket), "email": email, "plan": self._extract_plan(lowered),
            })])
        if "db_create_onboarding" not in called:
            return LLMResponse(tool_calls=[ToolCallRequest(
                name="db_create_onboarding", arguments={"customer_email": email})])
        if verified and "email_send" not in called:
            return LLMResponse(tool_calls=[ToolCallRequest(name="email_send", arguments={
                "to": verified,
                "subject": "Welcome! Your onboarding checklist is ready",
                "body": (
                    f"Hi {self._extract_name(ticket)} — your account is set up.\n"
                    "Your checklist: verify-email, complete-profile, connect-integration, "
                    "first-value-moment, welcome-call.\nReply if you get stuck."
                ),
            })])
        return LLMResponse(content=(
            f"Welcome aboard, {self._extract_name(ticket)}! Customer record created for {email}. "
            "Checklist ready: verify-email, complete-profile, connect-integration, "
            "first-value-moment, welcome-call."
        ))

    @staticmethod
    def _extract_name(ticket: str) -> str:
        for pattern in NAME_RES:
            match = pattern.search(ticket)
            if match:
                return match.group(1).strip()
        return "New Customer"

    @staticmethod
    def _extract_plan(lowered: str) -> str:
        if "enterprise" in lowered:
            return "enterprise"
        if "scale" in lowered:
            return "scale"
        if "pro" in lowered:
            return "pro"
        return "starter"


class OpenAILLMClient:
    """Production client: OpenAI Chat Completions with function calling (httpx)."""

    def __init__(self, api_key: str, model: str, base_url: str = "https://api.openai.com/v1") -> None:
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")

    async def chat(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> LLMResponse:
        import httpx

        openai_messages: list[dict[str, Any]] = []
        for message in messages:
            role = message.get("role")
            if role == "tool":
                openai_messages.append({
                    "role": "tool",
                    "tool_call_id": message.get("tool_call_id", ""),
                    "content": str(message.get("content", "")),
                })
            elif role == "assistant" and message.get("tool_calls"):
                openai_messages.append({
                    "role": "assistant",
                    "content": message.get("content") or None,
                    "tool_calls": [
                        {
                            "id": tc.get("call_id", tc.get("id")),
                            "type": "function",
                            "function": {"name": tc.get("name"), "arguments": json.dumps(tc.get("arguments", {}))},
                        }
                        for tc in message["tool_calls"]
                    ],
                })
            else:
                openai_messages.append({"role": role, "content": str(message.get("content", ""))})
        async with httpx.AsyncClient(timeout=60) as client:
            try:
                response = await client.post(
                    f"{self._base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "User-Agent": "portfolio-live-smoke/1.0",
                        "x-opencode-session": os.getenv("OPENCODE_SESSION_ID", "portfolio-api"),
                    },
                    json={"model": self._model, "messages": openai_messages, "tools": tools or None,
                          "tool_choice": "auto" if tools else "none"},
                )
                response.raise_for_status()
            except Exception as exc:
                body = getattr(getattr(exc, "response", None), "text", "")[:500]
                print(f"[llm] call failed: {exc} | body: {body}")
                raise
            choice = response.json()["choices"][0]["message"]
        tool_calls = [
            ToolCallRequest(
                call_id=tc.get("id", f"call-{uuid.uuid4().hex[:8]}"),
                name=tc["function"]["name"],
                arguments=json.loads(tc["function"].get("arguments") or "{}"),
            )
            for tc in choice.get("tool_calls", []) or []
        ]
        return LLMResponse(content=choice.get("content") or "", tool_calls=tool_calls)


# ---- Trajectory + result models ----

class StepRecord(BaseModel):
    step: int
    agent: str
    kind: str = Field(description="llm | tools | handoff | guardrail | final")
    name: str = ""
    summary: str = ""


class RunResult(BaseModel):
    final_answer: str
    resolved: bool
    escalated: bool
    agents_path: list[str]
    tools_called: list[str]
    steps: list[StepRecord]
    ticket_id: int | None = None
    verified_email: str | None = None
    iterations: int = 0


# ---- The loop ----

class AgentLoop:
    """Runs Triage -> Specialist with parallel tool calls and handoffs."""

    def __init__(self, llm: LLMClient | None = None, max_steps: int | None = None) -> None:
        if llm is not None:
            self.llm = llm
        elif not settings.mock_mode and settings.openai_api_key:
            self.llm = OpenAILLMClient(settings.openai_api_key, settings.model, settings.openai_base_url)
        else:
            self.llm = RuleBasedLLMClient()
        self.max_steps = max_steps or settings.max_steps

    async def run_stream(self, ticket_text: str):  # async generator of event dicts
        """Core loop as an event stream (also powers SSE)."""
        try:
            clean = validate_input(ticket_text)
        except InputValidationError as exc:
            yield {"type": "error", "error": str(exc)}
            return
        verified = extract_customer_email(ticket_text or "")
        redacted = redact_pii(clean).text

        agent = AgentName.TRIAGE.value
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": build_system_prompt(agent, verified)},
            {"role": "user", "content": redacted},
        ]
        steps: list[StepRecord] = [StepRecord(step=0, agent=agent, kind="guardrail",
                                              name="validate+redact",
                                              summary=f"input validated, contact={'set' if verified else 'none'}")]
        tools_called: list[str] = []
        agents_path = [agent]
        ticket_id: int | None = None
        step = 0

        yield {"type": "agent_start", "agent": agent}

        while True:
            step += 1
            try:
                check_iterations(step, self.max_steps)
            except MaxIterationsExceeded:
                steps.append(StepRecord(step=step, agent=agent, kind="guardrail",
                                        name="max_iterations",
                                        summary=f"budget exhausted at max_steps={self.max_steps}"))
                yield {"type": "final", "result": RunResult(
                    final_answer="I could not resolve this within my step budget, so I escalated it to a human.",
                    resolved=False, escalated=True, agents_path=agents_path,
                    tools_called=tools_called, steps=steps, ticket_id=ticket_id,
                    verified_email=verified, iterations=step,
                ).model_dump()}
                return

            response = await self.llm.chat(messages, list_tools(agent))
            steps.append(StepRecord(step=step, agent=agent, kind="llm", name="chat",
                                    summary=(response.content[:120] if response.content
                                             else f"{len(response.tool_calls)} tool call(s)")))

            if not response.tool_calls:
                answer = sanitize_output(response.content or "Done.")
                resolved = agent in (AgentName.SUPPORT.value, AgentName.ONBOARDING.value)
                steps.append(StepRecord(step=step, agent=agent, kind="final", name="answer",
                                        summary=answer[:160]))
                yield {"type": "final", "result": RunResult(
                    final_answer=answer, resolved=resolved, escalated=False,
                    agents_path=agents_path, tools_called=tools_called, steps=steps,
                    ticket_id=ticket_id, verified_email=verified, iterations=step,
                ).model_dump()}
                return

            handoffs = [tc for tc in response.tool_calls if tc.name == "handoff_to"]
            regular = [tc for tc in response.tool_calls if tc.name != "handoff_to"]

            if regular:
                for tool_call in regular:
                    tools_called.append(tool_call.name)
                    yield {"type": "tool_call", "agent": agent, "name": tool_call.name,
                           "arguments": tool_call.arguments}
                # Parallel execution: same-turn calls run concurrently.
                results = await asyncio.gather(*[
                    execute_tool(tool_call.name, tool_call.arguments) for tool_call in regular
                ])
                messages.append({"role": "assistant", "content": response.content or "",
                                 "tool_calls": [{"call_id": tc.call_id, "name": tc.name,
                                                 "arguments": tc.arguments} for tc in regular]})
                for tool_call, result in zip(regular, results):
                    content = json.dumps(result, default=str)
                    messages.append({"role": "tool", "tool_call_id": tool_call.call_id,
                                     "name": tool_call.name, "content": content})
                    summary = content[:200]
                    steps.append(StepRecord(step=step, agent=agent, kind="tools",
                                            name=tool_call.name, summary=summary))
                    yield {"type": "tool_result", "agent": agent, "name": tool_call.name,
                           "result": result}
                    if tool_call.name == "db_create_ticket" and result.get("ok"):
                        data = result.get("data") or {}
                        if isinstance(data.get("id"), int):
                            ticket_id = data["id"]
            else:
                messages.append({"role": "assistant", "content": response.content or "",
                                 "tool_calls": [{"call_id": tc.call_id, "name": tc.name,
                                                 "arguments": tc.arguments} for tc in handoffs]})
                for tc in handoffs:
                    # Synthetic tool result: OpenAI-compatible APIs 400 when an
                    # assistant message lists tool_calls with no following tool
                    # message. Handoffs run locally, so acknowledge them here.
                    messages.append({"role": "tool", "tool_call_id": tc.call_id,
                                     "name": "handoff_to",
                                     "content": json.dumps({"ok": True, "to": tc.arguments.get("target_agent", "")})})

            for handoff in handoffs:
                target = str(handoff.arguments.get("target_agent", ""))
                reason = str(handoff.arguments.get("reason", ""))[:300]
                tools_called.append("handoff_to")
                if not is_valid_handoff(agent, target):
                    steps.append(StepRecord(step=step, agent=agent, kind="guardrail",
                                            name="invalid_handoff",
                                            summary=f"rejected {agent}->{target}"))
                    yield {"type": "final", "result": RunResult(
                        final_answer=f"Invalid handoff {agent}->{target} blocked; escalated to a human.",
                        resolved=False, escalated=True, agents_path=agents_path,
                        tools_called=tools_called, steps=steps, ticket_id=ticket_id,
                        verified_email=verified, iterations=step,
                    ).model_dump()}
                    return
                steps.append(StepRecord(step=step, agent=agent, kind="handoff",
                                        name=f"{agent}->{target}", summary=reason))
                yield {"type": "handoff", "from": agent, "to": target, "reason": reason}
                if target == "escalate":
                    answer = sanitize_output(
                        f"Escalated to a human specialist. Reason: {reason or 'needs human judgment'}")
                    yield {"type": "final", "result": RunResult(
                        final_answer=answer, resolved=False, escalated=True,
                        agents_path=agents_path, tools_called=tools_called, steps=steps,
                        ticket_id=ticket_id, verified_email=verified, iterations=step,
                    ).model_dump()}
                    return
                agent = target
                agents_path.append(agent)
                messages.append({"role": "system", "content": build_system_prompt(agent, verified)})
                yield {"type": "agent_start", "agent": agent}

    async def run(self, ticket_text: str) -> RunResult:
        """Run the loop to completion and return the final result."""
        final: RunResult | None = None
        async for event in self.run_stream(ticket_text):
            if event["type"] == "final":
                final = RunResult(**event["result"])
            elif event["type"] == "error":
                return RunResult(
                    final_answer=f"Input rejected: {event['error']}", resolved=False,
                    escalated=False, agents_path=[], tools_called=[], steps=[],
                    iterations=0,
                )
        assert final is not None, "loop ended without a final event"
        return final

    def run_sync(self, ticket_text: str) -> RunResult:
        return asyncio.run(self.run(ticket_text))
