"""FastAPI service: chat, SSE streaming, health and tool listing."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from src.config import settings
from src.loop import AgentLoop
from src.ratelimit import RateLimitMiddleware
from src.tools import TOOL_REGISTRY


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    max_steps: int | None = Field(default=None, ge=1, le=50)


class ChatResponse(BaseModel):
    answer: str
    resolved: bool
    escalated: bool
    agents_path: list[str]
    tools_called: list[str]
    ticket_id: int | None = None
    iterations: int


app = FastAPI(title="Support Agent Tools", version="0.1.0")
app.add_middleware(RateLimitMiddleware, prefixes=("/chat",))
# Public demo API: allow browser fetches from the portfolio dashboard.
# Rate-limited, no credentials — safe to be open.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _build_loop(max_steps: int | None) -> AgentLoop:
    return AgentLoop(max_steps=max_steps or settings.max_steps)


@app.get("/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "mock_mode": settings.mock_mode, "model": settings.model}


@app.get("/ui", include_in_schema=False)
def ui() -> FileResponse:
    """Minimal demo UI (single static file, no build step)."""
    return FileResponse(Path(__file__).resolve().parent / "static" / "ui.html")


@app.get("/tools")
def tools() -> dict[str, Any]:
    return {"tools": [
        {"name": name, "description": tool.description} for name, tool in sorted(TOOL_REGISTRY.items())
    ]}


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    loop = _build_loop(request.max_steps)
    result = await loop.run(request.message)
    if not result.agents_path and not result.resolved:
        raise HTTPException(status_code=422, detail=result.final_answer)
    return ChatResponse(
        answer=result.final_answer, resolved=result.resolved, escalated=result.escalated,
        agents_path=result.agents_path, tools_called=result.tools_called,
        ticket_id=result.ticket_id, iterations=result.iterations,
    )


@app.post("/chat/stream")
async def chat_stream(request: ChatRequest) -> StreamingResponse:
    loop = _build_loop(request.max_steps)

    def _json_default(o: Any) -> Any:
        if isinstance(o, BaseModel):
            return o.model_dump(mode="json")
        return str(o)

    async def _events():
        async for event in loop.run_stream(request.message):
            yield f"data: {json.dumps(event, default=_json_default)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(_events(), media_type="text/event-stream")
