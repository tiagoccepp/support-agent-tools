"""Per-IP sliding-window rate limiter for expensive POST endpoints.

Zero dependencies, in-memory: correct for single-instance deploys (Render
free runs one instance). GETs and health checks are never limited.

Set RATE_LIMIT_PER_MIN=0 to disable (load tests, evals).
"""
from __future__ import annotations

import os
import time

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

WINDOW_S = 60.0
_hits: dict[str, list[float]] = {}


def _limit() -> int:
    try:
        return max(0, int(os.getenv("RATE_LIMIT_PER_MIN", "30")))
    except ValueError:
        return 30


def _client_ip(scope: Scope) -> str:
    client = scope.get("client")
    if client:
        return str(client[0])
    return "unknown"


class RateLimitMiddleware:
    """Reject POSTs over the per-minute budget with 429 + Retry-After."""

    def __init__(self, app: ASGIApp, prefixes: tuple[str, ...]) -> None:
        self.app = app
        self.prefixes = prefixes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or scope["method"] != "POST"
            or not scope["path"].startswith(self.prefixes)
        ):
            await self.app(scope, receive, send)
            return
        limit = _limit()
        if limit <= 0:
            await self.app(scope, receive, send)
            return
        now = time.monotonic()
        ip = _client_ip(scope)
        if limit <= 0:
            await self.app(scope, receive, send)
            return
        recent = [t for t in _hits.get(ip, []) if now - t < WINDOW_S]
        if len(recent) >= limit:
            retry = max(1, int(WINDOW_S - (now - recent[0])))
            resp = JSONResponse(
                {"detail": f"rate limit exceeded ({limit}/min), retry later"},
                status_code=429,
                headers={"Retry-After": str(retry)},
            )
            await resp(scope, receive, send)
            return
        recent.append(now)
        _hits[ip] = recent
        await self.app(scope, receive, send)


def reset_for_tests() -> None:
    _hits.clear()
