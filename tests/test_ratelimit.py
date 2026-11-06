"""Rate limiter: 429 after budget, health untouched."""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from fastapi.testclient import TestClient  # noqa: E402

from src import api  # noqa: E402
from src.ratelimit import reset_for_tests  # noqa: E402

MSG = "Hi, I forgot my password and can't log in. How do I reset it? My email is alice@example.com"


def test_post_budget_then_429(monkeypatch) -> None:
    monkeypatch.setenv("RATE_LIMIT_PER_MIN", "2")
    reset_for_tests()
    c = TestClient(api.app)
    assert c.post("/chat", json={"message": MSG}).status_code == 200
    assert c.post("/chat", json={"message": MSG}).status_code == 200
    r = c.post("/chat", json={"message": MSG})
    assert r.status_code == 429
    assert "retry-after" in r.headers
    assert c.get("/health").status_code == 200


def test_disabled_with_zero(monkeypatch) -> None:
    monkeypatch.setenv("RATE_LIMIT_PER_MIN", "0")
    reset_for_tests()
    c = TestClient(api.app)
    for _ in range(4):
        assert c.post("/chat", json={"message": MSG}).status_code == 200
