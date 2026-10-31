"""Guardrails: input validation, PII redaction, iteration caps, output sanitizing."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from src.config import settings


class InputValidationError(ValueError):
    """Raised when a ticket message fails input guardrails."""


class MaxIterationsExceeded(RuntimeError):
    """Raised when the agent loop exceeds its step budget."""


_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE_RE = re.compile(
    r"(?:\+\d{1,3}[\s.-]?)?(?:\(?\d{3}\)?[\s.-]?)?\d{3}[\s.-]?\d{4}\b"
)
_SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_CC_RE = re.compile(r"\b(?:\d[ -]?){13,19}\b")

_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("EMAIL", _EMAIL_RE),
    ("PHONE", _PHONE_RE),
    ("SSN", _SSN_RE),
    ("CARD", _CC_RE),
)


@dataclass
class RedactionResult:
    text: str
    findings: dict[str, int] = field(default_factory=dict)


def _looks_like_card(candidate: str) -> bool:
    digits = re.sub(r"\D", "", candidate)
    if len(digits) not in (15, 16) or len(set(digits)) < 2:
        return False
    # Luhn check to avoid flagging random digit runs.
    total = 0
    for i, ch in enumerate(reversed(digits)):
        digit = int(ch)
        if i % 2 == 1:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return total % 10 == 0


def _redact_phones(text: str) -> tuple[str, int]:
    """Redact phone-like numbers, skipping card-like digit runs (handled separately)."""
    count = 0

    def _swap(match: re.Match[str]) -> str:
        nonlocal count
        candidate = match.group(0)
        digits = re.sub(r"\D", "", candidate)
        if len(digits) >= 13 or len(digits) < 7:
            return candidate
        count += 1
        return "[PHONE_REDACTED]"

    return _PHONE_RE.sub(_swap, text), count


def redact_pii(text: str) -> RedactionResult:
    """Redact emails, phones, SSNs and card numbers. Returns text + finding counts."""
    findings: dict[str, int] = {}
    redacted, email_count = _EMAIL_RE.subn("[EMAIL_REDACTED]", text or "")
    findings["email"] = email_count
    redacted, ssn_count = _SSN_RE.subn("[SSN_REDACTED]", redacted)
    findings["ssn"] = ssn_count

    card_count = 0

    def _swap_card(match: re.Match[str]) -> str:
        nonlocal card_count
        if _looks_like_card(match.group(0)):
            card_count += 1
            return "[CARD_REDACTED]"
        return match.group(0)

    redacted = _CC_RE.sub(_swap_card, redacted)
    findings["card"] = card_count
    redacted, phone_count = _redact_phones(redacted)
    findings["phone"] = phone_count
    return RedactionResult(text=redacted, findings=findings)


def extract_customer_email(text: str) -> str | None:
    """Pull the first email address from raw text (before redaction)."""
    match = _EMAIL_RE.search(text or "")
    return match.group(0) if match else None


def is_valid_email(email: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", (email or "").strip()))


def validate_input(text: str, max_chars: int | None = None) -> str:
    """Strip + enforce input guardrails. Returns clean text or raises."""
    clean = (text or "").strip()
    if not clean:
        raise InputValidationError("message must not be empty")
    limit = max_chars if max_chars is not None else settings.max_input_chars
    if len(clean) > limit:
        raise InputValidationError(f"message exceeds {limit} characters ({len(clean)})")
    if "\x00" in clean:
        raise InputValidationError("message contains null bytes")
    return clean


def check_iterations(step: int, max_steps: int) -> None:
    """Raise when the loop step exceeds its budget."""
    if step > max_steps:
        raise MaxIterationsExceeded(f"step {step} exceeds max_steps={max_steps}")


def sanitize_output(text: str) -> str:
    """Redact any PII that leaked into a final answer."""
    return redact_pii(text or "").text
