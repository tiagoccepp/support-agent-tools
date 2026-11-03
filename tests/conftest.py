"""Shared fixtures: project root on sys.path, isolated DB + outbox per test."""
from __future__ import annotations

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.chdir(ROOT)
    from src.tools import db_tool, email_tool
    from src.tools.inventory_tool import reset_catalog

    db_tool.set_db_path(str(tmp_path / "test.db"))
    email_tool.clear_outbox()
    reset_catalog()
    yield
    db_tool.set_db_path(None)
    email_tool.clear_outbox()
    reset_catalog()
