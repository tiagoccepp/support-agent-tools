"""Free-model rotation: fallbacks on removed/rate-limited models, no retry on auth."""
from __future__ import annotations

import os
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from src.loop import FREE_POOL, OpenAILLMClient, rotation_list  # noqa: E402


class _Resp:
    def __init__(self, status: int, detail: str = "") -> None:
        self.status_code = status
        self.text = f"http {status} {detail}".strip()
        self._detail = detail

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            exc = RuntimeError(self.text)
            exc.response = self  # type: ignore[attr-defined]
            raise exc

    def json(self):  # noqa: ANN202
        return {"choices": [{"message": {"content": "done", "tool_calls": []}}]}


class _StubClient:
    """Stub httpx.AsyncClient: fail `fails` posts with `status`, then 200."""

    def __init__(self, status: int, fails: int, calls: list) -> None:
        self.status = status
        self.fails = fails
        self.calls = calls

    async def __aenter__(self):  # noqa: ANN204
        return self

    async def __aexit__(self, *a):  # noqa: ANN001, ANN202
        return False

    async def post(self, url, headers=None, json=None):  # noqa: ANN001, ANN202
        self.calls.append(json["model"])
        if len(self.calls) <= self.fails:
            return _Resp(self.status, getattr(self, "detail", ""))
        return _Resp(200)


def _client(monkeypatch, status: int, fails: int, models: list[str], detail: str = ""):
    import httpx

    calls: list = []
    stub = _StubClient(status, fails, calls)
    stub.detail = detail
    monkeypatch.setattr(httpx, "AsyncClient", lambda timeout=None: stub)
    return OpenAILLMClient("dummy", models[0], models=models), calls


async def test_rotation_list() -> None:
    assert rotation_list("beam-free", "")[0] == "beam-free"
    assert rotation_list("x", "a,b,a") == ["x", "a", "b"]
    assert "beam-free" in FREE_POOL


async def test_chat_falls_back_on_404(monkeypatch) -> None:
    c, calls = _client(monkeypatch, 404, 1, ["gone", "beam-free"])
    r = await c.chat([{"role": "user", "content": "hi"}], [])
    assert r.content == "done"
    assert calls == ["gone", "beam-free"]


async def test_chat_retries_400_model_gone_not_param_error(monkeypatch) -> None:
    c, calls = _client(monkeypatch, 400, 1, ["gone", "beam-free"], "Model is unavailable")
    r = await c.chat([{"role": "user", "content": "hi"}], [])
    assert r.content == "done"
    assert calls == ["gone", "beam-free"]
    c2, calls2 = _client(monkeypatch, 400, 99, ["a", "b"], "invalid temperature")
    try:
        await c2.chat([{"role": "user", "content": "hi"}], [])
    except RuntimeError:
        pass
    else:
        raise AssertionError("should raise")
    assert calls2 == ["a"]


async def test_chat_no_retry_on_401(monkeypatch) -> None:
    c, calls = _client(monkeypatch, 401, 99, ["a", "b"])
    try:
        await c.chat([{"role": "user", "content": "hi"}], [])
    except RuntimeError:
        pass
    else:
        raise AssertionError("should raise")
    assert calls == ["a"]


async def test_chat_raises_last_when_all_fail(monkeypatch) -> None:
    c, calls = _client(monkeypatch, 429, 99, ["a", "b"])
    try:
        await c.chat([{"role": "user", "content": "hi"}], [])
    except RuntimeError:
        pass
    else:
        raise AssertionError("should raise")
    assert calls == ["a", "b"]
