"""Tool unit tests: inventory, KB, SQLite DB, mock email."""
from __future__ import annotations

import pytest

from src.tools import db_tool, email_tool
from src.tools.inventory_tool import check_stock, get_product, list_products, lookup, reserve_stock
from src.tools.kb_tool import get_article, search_kb


def test_inventory_check_stock_known() -> None:
    info = check_stock("ACME-1001")
    assert info.in_stock is True
    assert info.quantity == 24
    assert info.name == "Widget Pro"


def test_inventory_check_stock_unknown_sku() -> None:
    info = check_stock("NOPE-9999")
    assert info.in_stock is False
    assert info.quantity == 0


def test_inventory_lookup_by_name() -> None:
    result = lookup("gadget x")
    assert result["found"] is True
    assert result["sku"] == "ACME-2001"


def test_inventory_reserve_decrements_stock() -> None:
    reservation = reserve_stock("ACME-2001", 2)
    assert reservation.status == "confirmed"
    assert check_stock("ACME-2001").quantity == 5
    with pytest.raises(ValueError):
        reserve_stock("ACME-2001", 999)


def test_inventory_list_products_filter() -> None:
    assert len(list_products()) == 8
    assert all(p.stock > 0 for p in list_products(in_stock_only=True))


def test_kb_search_finds_shipping() -> None:
    hits = search_kb("how long does shipping take")
    assert hits, "expected at least one KB hit"
    assert hits[0].id == "kb-shipping"


def test_kb_search_no_match_returns_empty() -> None:
    assert search_kb("asdf qwer zxcv blorp") == []


def test_kb_get_article() -> None:
    article = get_article("kb-password-reset")
    assert article is not None
    assert "password" in article.title.lower()
    assert get_article("kb-missing") is None


def test_db_create_and_get_ticket() -> None:
    ticket = db_tool.create_ticket("t@example.com", "broken widget", agent="support")
    assert ticket.id >= 1
    fetched = db_tool.get_ticket(ticket.id)
    assert fetched is not None
    assert fetched.customer_email == "t@example.com"
    updated = db_tool.update_ticket_status(ticket.id, "resolved")
    assert updated is not None and updated.status == "resolved"


def test_db_onboarding_checklist() -> None:
    db_tool.create_customer("Test User", "new@example.com", plan="pro")
    steps = db_tool.create_onboarding_checklist("new@example.com")
    assert len(steps) == 5
    done = db_tool.complete_onboarding_step("new@example.com", "verify-email")
    assert done is not None and done.done is True


def test_email_send_and_outbox() -> None:
    record = email_tool.send_email("a@b.com", "hello", "body text")
    assert record.status == "queued"
    assert len(email_tool.get_outbox()) == 1
    with pytest.raises(ValueError):
        email_tool.send_email("not-an-email", "s", "b")
