"""Tool registry: OpenAI function-calling schemas + async dispatcher."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Callable

from src.tools import db_tool, email_tool, inventory_tool, kb_tool


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    parameters: dict[str, Any]
    func: Callable[..., Any]
    agents: tuple[str, ...] = ("support", "onboarding")


def _collect() -> dict[str, ToolDefinition]:
    registry: dict[str, ToolDefinition] = {}
    modules = (inventory_tool, kb_tool, db_tool, email_tool)
    for module in modules:
        for schema in module.TOOL_SCHEMAS:
            fn = schema["function"]
            registry[fn["name"]] = ToolDefinition(
                name=fn["name"],
                description=fn["description"],
                parameters=fn["parameters"],
                func=module.FUNCTIONS[fn["name"]],
            )
    # handoff_to is loop-handled (see src.agents.HANDOFF_SCHEMA); registered here
    # so schemas stay complete, but execute_tool refuses to run it directly.
    registry["handoff_to"] = ToolDefinition(
        name="handoff_to",
        description="Hand the ticket to another agent (support, onboarding) or escalate to a human.",
        parameters={
            "type": "object",
            "properties": {
                "target_agent": {"type": "string", "enum": ["support", "onboarding", "escalate"]},
                "reason": {"type": "string"},
            },
            "required": ["target_agent", "reason"],
        },
        func=_handoff_stub,
        agents=("triage", "support", "onboarding"),
    )
    return registry


def _handoff_stub(target_agent: str, reason: str) -> dict[str, Any]:
    raise RuntimeError("handoff_to is intercepted by the agent loop and must not execute directly")


TOOL_REGISTRY: dict[str, ToolDefinition] = _collect()

# Per-agent tool allowlists (least privilege per specialist).
AGENT_TOOLS: dict[str, tuple[str, ...]] = {
    "triage": ("handoff_to",),
    "support": (
        "kb_search", "kb_get_article",
        "inventory_lookup", "inventory_list_products", "inventory_reserve",
        "db_create_ticket", "db_get_ticket", "db_update_ticket_status",
        "email_send", "handoff_to",
    ),
    "onboarding": (
        "db_create_customer", "db_get_customer",
        "db_create_onboarding", "db_complete_onboarding_step",
        "kb_search", "email_send", "handoff_to",
    ),
}


def list_tools(agent: str | None = None) -> list[dict[str, Any]]:
    """Return OpenAI-style tool schemas, optionally filtered by agent allowlist."""
    names = AGENT_TOOLS.get(agent, tuple(TOOL_REGISTRY)) if agent else tuple(TOOL_REGISTRY)
    schemas: list[dict[str, Any]] = []
    for name in names:
        tool = TOOL_REGISTRY[name]
        schemas.append({"type": "function", "function": {
            "name": tool.name, "description": tool.description, "parameters": tool.parameters,
        }})
    return schemas


async def execute_tool(name: str, args: dict[str, Any] | None) -> dict[str, Any]:
    """Run one tool in a worker thread; always returns a JSON-serializable envelope."""
    if name == "handoff_to":
        return {"ok": False, "error": "handoff_to is handled by the agent loop"}
    tool = TOOL_REGISTRY.get(name)
    if tool is None:
        return {"ok": False, "error": f"unknown tool: {name}"}
    try:
        result = await asyncio.to_thread(tool.func, **(args or {}))
        return {"ok": True, "data": result}
    except TypeError as exc:
        return {"ok": False, "error": f"bad arguments for {name}: {exc}"}
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    except Exception as exc:  # never let one tool crash the loop
        return {"ok": False, "error": f"{name} failed: {exc}"}
