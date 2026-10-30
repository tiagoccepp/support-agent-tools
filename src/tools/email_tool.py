"""Mock email sender: validates + records into an in-memory outbox (no network)."""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

from pydantic import BaseModel

_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")


class EmailRecord(BaseModel):
    message_id: str
    to: str
    subject: str
    body: str
    status: str
    created_at: str


_OUTBOX: list[EmailRecord] = []


def send_email(to: str, subject: str, body: str) -> EmailRecord:
    """Validate and queue an email. Raises ValueError on bad input."""
    address = (to or "").strip()
    if not _EMAIL_RE.match(address):
        raise ValueError(f"invalid recipient email: {to!r}")
    if not (subject or "").strip():
        raise ValueError("subject must not be empty")
    if not (body or "").strip():
        raise ValueError("body must not be empty")
    record = EmailRecord(
        message_id=f"msg-{uuid.uuid4().hex[:8]}",
        to=address,
        subject=subject.strip(),
        body=body.strip(),
        status="queued",
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    _OUTBOX.append(record)
    return record


def get_outbox() -> list[EmailRecord]:
    return list(_OUTBOX)


def clear_outbox() -> None:
    _OUTBOX.clear()


TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "email_send",
            "description": "Send an email to the customer (mock transport, recorded in outbox).",
            "parameters": {
                "type": "object",
                "properties": {
                    "to": {"type": "string", "description": "Recipient email address"},
                    "subject": {"type": "string"},
                    "body": {"type": "string"},
                },
                "required": ["to", "subject", "body"],
            },
        },
    }
]

FUNCTIONS: dict[str, Callable[..., Any]] = {
    "email_send": lambda to, subject, body: send_email(to, subject, body).model_dump(),
}
