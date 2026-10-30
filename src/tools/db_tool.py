"""SQLite persistence for tickets, customers and onboarding checklists."""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from typing import Any, Callable

from pydantic import BaseModel

from src.config import settings

_SCHEMA = """
CREATE TABLE IF NOT EXISTS tickets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_email TEXT NOT NULL,
    subject TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    agent TEXT NOT NULL DEFAULT 'support',
    summary TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS customers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    plan TEXT NOT NULL DEFAULT 'starter',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS onboarding (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_email TEXT NOT NULL,
    step TEXT NOT NULL,
    done INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    UNIQUE (customer_email, step)
);
"""

DEFAULT_ONBOARDING_STEPS = [
    "verify-email",
    "complete-profile",
    "connect-integration",
    "first-value-moment",
    "welcome-call",
]

_DB_PATH_OVERRIDE: str | None = None


class TicketRecord(BaseModel):
    id: int
    customer_email: str
    subject: str
    status: str
    agent: str
    summary: str
    created_at: str


class CustomerRecord(BaseModel):
    id: int
    name: str
    email: str
    plan: str
    created_at: str


class OnboardingStep(BaseModel):
    customer_email: str
    step: str
    done: bool


def set_db_path(path: str | None) -> None:
    """Override the sqlite path (tests/evals). None restores settings."""
    global _DB_PATH_OVERRIDE
    _DB_PATH_OVERRIDE = path


def resolve_db_path() -> str:
    path = _DB_PATH_OVERRIDE or settings.db_path
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    return path


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(resolve_db_path())
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    return conn


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_ticket(
    customer_email: str,
    subject: str,
    status: str = "open",
    agent: str = "support",
    summary: str = "",
) -> TicketRecord:
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO tickets (customer_email, subject, status, agent, summary, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (customer_email, subject[:200], status, agent, summary[:500], _now()),
        )
        ticket_id = cur.lastrowid
    ticket = get_ticket(int(ticket_id))
    assert ticket is not None
    return ticket


def get_ticket(ticket_id: int) -> TicketRecord | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
    return TicketRecord(**dict(row)) if row else None


def update_ticket_status(ticket_id: int, status: str) -> TicketRecord | None:
    with _connect() as conn:
        conn.execute("UPDATE tickets SET status = ? WHERE id = ?", (status, ticket_id))
    return get_ticket(ticket_id)


def list_tickets(status: str | None = None) -> list[TicketRecord]:
    with _connect() as conn:
        if status:
            rows = conn.execute("SELECT * FROM tickets WHERE status = ? ORDER BY id", (status,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM tickets ORDER BY id").fetchall()
    return [TicketRecord(**dict(r)) for r in rows]


def create_customer(name: str, email: str, plan: str = "starter") -> CustomerRecord:
    """Create a customer, or return the existing row when the email is taken."""
    existing = get_customer_by_email(email)
    if existing is not None:
        return existing
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO customers (name, email, plan, created_at) VALUES (?, ?, ?, ?)",
            (name, email, plan, _now()),
        )
        customer_id = cur.lastrowid
    customer = get_customer_by_email(email)
    assert customer is not None and customer.id == int(customer_id)
    return customer


def get_customer_by_email(email: str) -> CustomerRecord | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM customers WHERE email = ?", (email,)).fetchone()
    return CustomerRecord(**dict(row)) if row else None


def create_onboarding_checklist(customer_email: str) -> list[OnboardingStep]:
    with _connect() as conn:
        for step in DEFAULT_ONBOARDING_STEPS:
            conn.execute(
                "INSERT OR IGNORE INTO onboarding (customer_email, step, done, created_at) VALUES (?, ?, 0, ?)",
                (customer_email, step, _now()),
            )
    return get_onboarding(customer_email)


def complete_onboarding_step(customer_email: str, step: str) -> OnboardingStep | None:
    with _connect() as conn:
        conn.execute(
            "UPDATE onboarding SET done = 1 WHERE customer_email = ? AND step = ?",
            (customer_email, step),
        )
    for item in get_onboarding(customer_email):
        if item.step == step:
            return item
    return None


def get_onboarding(customer_email: str) -> list[OnboardingStep]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT customer_email, step, done FROM onboarding WHERE customer_email = ? ORDER BY id",
            (customer_email,),
        ).fetchall()
    return [OnboardingStep(customer_email=r["customer_email"], step=r["step"], done=bool(r["done"])) for r in rows]


TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "db_create_ticket",
            "description": "Create a support ticket record.",
            "parameters": {
                "type": "object",
                "properties": {
                    "customer_email": {"type": "string"},
                    "subject": {"type": "string"},
                    "agent": {"type": "string", "default": "support"},
                    "summary": {"type": "string", "default": ""},
                },
                "required": ["customer_email", "subject"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "db_get_ticket",
            "description": "Fetch a ticket by id.",
            "parameters": {
                "type": "object",
                "properties": {"ticket_id": {"type": "integer"}},
                "required": ["ticket_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "db_update_ticket_status",
            "description": "Update a ticket status (open, pending, resolved, escalated).",
            "parameters": {
                "type": "object",
                "properties": {
                    "ticket_id": {"type": "integer"},
                    "status": {"type": "string"},
                },
                "required": ["ticket_id", "status"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "db_create_customer",
            "description": "Create a customer record during onboarding.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "email": {"type": "string"},
                    "plan": {"type": "string", "default": "starter"},
                },
                "required": ["name", "email"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "db_get_customer",
            "description": "Fetch a customer by email.",
            "parameters": {
                "type": "object",
                "properties": {"email": {"type": "string"}},
                "required": ["email"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "db_create_onboarding",
            "description": "Create the onboarding checklist for a customer email.",
            "parameters": {
                "type": "object",
                "properties": {"customer_email": {"type": "string"}},
                "required": ["customer_email"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "db_complete_onboarding_step",
            "description": "Mark one onboarding step done.",
            "parameters": {
                "type": "object",
                "properties": {
                    "customer_email": {"type": "string"},
                    "step": {"type": "string"},
                },
                "required": ["customer_email", "step"],
            },
        },
    },
]

FUNCTIONS: dict[str, Callable[..., Any]] = {
    "db_create_ticket": lambda customer_email, subject, agent="support", summary="": create_ticket(
        customer_email, subject, agent=agent, summary=summary
    ).model_dump(),
    "db_get_ticket": lambda ticket_id: (get_ticket(ticket_id).model_dump() if get_ticket(ticket_id) else {"found": False}),
    "db_update_ticket_status": lambda ticket_id, status: (
        update_ticket_status(ticket_id, status).model_dump() if update_ticket_status(ticket_id, status) else {"found": False}
    ),
    "db_create_customer": lambda name, email, plan="starter": create_customer(name, email, plan).model_dump(),
    "db_get_customer": lambda email: (
        get_customer_by_email(email).model_dump() if get_customer_by_email(email) else {"found": False}
    ),
    "db_create_onboarding": lambda customer_email: {
        "steps": [s.model_dump() for s in create_onboarding_checklist(customer_email)]
    },
    "db_complete_onboarding_step": lambda customer_email, step: (
        complete_onboarding_step(customer_email, step).model_dump()
        if complete_onboarding_step(customer_email, step)
        else {"found": False}
    ),
}
