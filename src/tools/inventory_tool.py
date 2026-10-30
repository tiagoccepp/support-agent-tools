"""Mock inventory API: in-memory product catalog with stock + reservations.

Stands in for a real inventory/OMS HTTP service. Deterministic and offline.
"""
from __future__ import annotations

import re
import uuid
from typing import Any, Callable

from pydantic import BaseModel, Field


class Product(BaseModel):
    sku: str
    name: str
    price_usd: float
    stock: int
    category: str


class StockInfo(BaseModel):
    sku: str
    name: str
    in_stock: bool
    quantity: int


class Reservation(BaseModel):
    reservation_id: str
    sku: str
    quantity: int
    status: str = "confirmed"


_CATALOG: dict[str, Product] = {
    "ACME-1001": Product(sku="ACME-1001", name="Widget Pro", price_usd=49.99, stock=24, category="widgets"),
    "ACME-1002": Product(sku="ACME-1002", name="Widget Mini", price_usd=29.99, stock=0, category="widgets"),
    "ACME-1007": Product(sku="ACME-1007", name="Mega Widget", price_usd=399.00, stock=0, category="widgets"),
    "ACME-2001": Product(sku="ACME-2001", name="Gadget X", price_usd=149.00, stock=7, category="gadgets"),
    "ACME-2002": Product(sku="ACME-2002", name="Gadget X Case", price_usd=19.99, stock=150, category="accessories"),
    "ACME-3001": Product(sku="ACME-3001", name="Sprocket Set", price_usd=89.50, stock=3, category="parts"),
    "ACME-3002": Product(sku="ACME-3002", name="Gearbox Z", price_usd=210.00, stock=12, category="parts"),
    "ACME-4001": Product(sku="ACME-4001", name="Doohickey Plus", price_usd=59.00, stock=41, category="tools"),
}

_RESERVATIONS: list[Reservation] = []
_SKU_RE = re.compile(r"\b([A-Z]{2,}-\d+)\b")


def _tokenize(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def get_product(sku: str) -> Product | None:
    """Return a product by exact SKU (case-insensitive), else None."""
    return _CATALOG.get(sku.strip().upper())


def check_stock(sku: str) -> StockInfo:
    """Return stock status for a SKU. Unknown SKUs report quantity 0."""
    product = get_product(sku)
    if product is None:
        return StockInfo(sku=sku.strip().upper(), name="unknown", in_stock=False, quantity=0)
    return StockInfo(sku=product.sku, name=product.name, in_stock=product.stock > 0, quantity=product.stock)


def list_products(in_stock_only: bool = False) -> list[Product]:
    """List the catalog, optionally filtering to in-stock items."""
    items = list(_CATALOG.values())
    if in_stock_only:
        items = [p for p in items if p.stock > 0]
    return sorted(items, key=lambda p: p.sku)


def lookup(sku_or_query: str) -> dict[str, Any]:
    """Look up inventory by exact SKU or fuzzy product-name query.

    Returns a JSON-serializable dict with ``found`` plus product/stock data.
    """
    query = (sku_or_query or "").strip()
    if not query:
        return {"found": False, "query": query, "reason": "empty query"}
    sku_match = _SKU_RE.search(query.upper())
    if sku_match:
        product = get_product(sku_match.group(1))
        if product is not None:
            return {"found": True, "match": "sku", **product.model_dump(), "in_stock": product.stock > 0}
    tokens = _tokenize(query)
    best: Product | None = None
    best_score = 0
    for product in _CATALOG.values():
        score = len(tokens & _tokenize(product.name)) + len(tokens & {product.sku.lower()})
        if score > best_score:
            best, best_score = product, score
    if best is not None and best_score > 0:
        return {"found": True, "match": "name", **best.model_dump(), "in_stock": best.stock > 0}
    return {"found": False, "query": query, "reason": "no matching product"}


def reserve_stock(sku: str, quantity: int) -> Reservation:
    """Reserve units of a SKU. Raises ValueError when impossible."""
    if quantity <= 0:
        raise ValueError("quantity must be >= 1")
    product = get_product(sku)
    if product is None:
        raise ValueError(f"unknown SKU: {sku}")
    if product.stock < quantity:
        raise ValueError(f"insufficient stock for {product.sku}: have {product.stock}, need {quantity}")
    product.stock -= quantity
    reservation = Reservation(reservation_id=f"rsv-{uuid.uuid4().hex[:8]}", sku=product.sku, quantity=quantity)
    _RESERVATIONS.append(reservation)
    return reservation


def reset_catalog() -> None:
    """Restore initial stock levels (used by tests)."""
    for sku, qty in [
        ("ACME-1001", 24), ("ACME-1002", 0), ("ACME-1007", 0), ("ACME-2001", 7),
        ("ACME-2002", 150), ("ACME-3001", 3), ("ACME-3002", 12), ("ACME-4001", 41),
    ]:
        _CATALOG[sku].stock = qty
    _RESERVATIONS.clear()


# ---- OpenAI function-calling schemas + dispatch table ----

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "inventory_lookup",
            "description": "Look up a product by SKU (e.g. ACME-1001) or free-text name query. Returns availability and price.",
            "parameters": {
                "type": "object",
                "properties": {"sku_or_query": {"type": "string", "description": "Exact SKU or product-name query"}},
                "required": ["sku_or_query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "inventory_list_products",
            "description": "List catalog products, optionally only in-stock ones.",
            "parameters": {
                "type": "object",
                "properties": {"in_stock_only": {"type": "boolean", "default": False}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "inventory_reserve",
            "description": "Reserve units of a SKU for the customer.",
            "parameters": {
                "type": "object",
                "properties": {
                    "sku": {"type": "string"},
                    "quantity": {"type": "integer", "minimum": 1},
                },
                "required": ["sku", "quantity"],
            },
        },
    },
]

FUNCTIONS: dict[str, Callable[..., Any]] = {
    "inventory_lookup": lambda sku_or_query: lookup(sku_or_query),
    "inventory_list_products": lambda in_stock_only=False: [p.model_dump() for p in list_products(in_stock_only)],
    "inventory_reserve": lambda sku, quantity: reserve_stock(sku, quantity).model_dump(),
}
