"""Guardrail unit tests: PII redaction, input validation, output sanitizing."""
from __future__ import annotations

import pytest

from src.guardrails import (
    InputValidationError,
    MaxIterationsExceeded,
    check_iterations,
    extract_customer_email,
    redact_pii,
    sanitize_output,
    validate_input,
)


def test_redact_email() -> None:
    result = redact_pii("Contact me at alice@example.com please")
    assert "alice@example.com" not in result.text
    assert "[EMAIL_REDACTED]" in result.text
    assert result.findings["email"] == 1


def test_redact_phone() -> None:
    result = redact_pii("Call me on +1 415-555-0132 tomorrow")
    assert "415-555-0132" not in result.text
    assert "[PHONE_REDACTED]" in result.text
    assert result.findings["phone"] == 1


def test_redact_ssn_and_card() -> None:
    result = redact_pii("SSN 123-45-6789, card 4111 1111 1111 1111")
    assert "123-45-6789" not in result.text
    assert "[SSN_REDACTED]" in result.text
    assert "4111" not in result.text
    assert "[CARD_REDACTED]" in result.text
    assert result.findings["ssn"] == 1
    assert result.findings["card"] == 1


def test_redact_clean_text_untouched() -> None:
    result = redact_pii("Where is my order?")
    assert result.text == "Where is my order?"
    assert sum(result.findings.values()) == 0


def test_validate_empty_raises() -> None:
    with pytest.raises(InputValidationError):
        validate_input("   ")


def test_validate_too_long_raises() -> None:
    with pytest.raises(InputValidationError):
        validate_input("x" * 5000, max_chars=4000)


def test_validate_ok() -> None:
    assert validate_input("  hello  ") == "hello"


def test_check_iterations_raises_past_budget() -> None:
    with pytest.raises(MaxIterationsExceeded):
        check_iterations(13, 12)
    check_iterations(12, 12)  # boundary is fine


def test_sanitize_output_redacts_phone() -> None:
    assert "[PHONE_REDACTED]" in sanitize_output("Call 415-555-0132")


def test_extract_customer_email() -> None:
    assert extract_customer_email("mail me at bob@example.com!") == "bob@example.com"
    assert extract_customer_email("no email here") is None
