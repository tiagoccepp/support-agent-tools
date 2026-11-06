"""CORS regression: public demo API must allow browser fetches."""
from fastapi.testclient import TestClient

from src.api import app


def test_cors_allows_browser_origin():
    with TestClient(app) as c:
        r = c.get("/health", headers={"Origin": "https://tiagoccepp.github.io"})
    assert r.status_code == 200
    assert r.headers.get("access-control-allow-origin") == "*"
