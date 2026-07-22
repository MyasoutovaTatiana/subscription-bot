import logging
import sys

from app.logging_setup import RedactingFormatter, redact_secrets


def test_redact_secrets_masks_telegram_token() -> None:
    token = "123456789:ABC-DEF_test_token_value_123456789"

    result = redact_secrets(f"request failed: https://api.telegram.org/bot{token}/sendMessage")

    assert token not in result
    assert "[REDACTED_TELEGRAM_TOKEN]" in result


def test_redact_secrets_masks_url_password() -> None:
    database_url = "postgresql+asyncpg://bot_user:very-secret@db.example/subscriptions"

    result = redact_secrets(f"database connection failed: {database_url}")

    assert "very-secret" not in result
    assert "postgresql+asyncpg://bot_user:[REDACTED]@db.example" in result


def test_formatter_redacts_exception_traceback() -> None:
    token = "123456789:ABC-DEF_test_token_value_123456789"
    formatter = RedactingFormatter("%(levelname)s %(message)s")

    try:
        raise RuntimeError(f"request failed with token {token}")
    except RuntimeError:
        record = logging.LogRecord(
            name="test",
            level=logging.ERROR,
            pathname=__file__,
            lineno=1,
            msg="operation failed",
            args=(),
            exc_info=sys.exc_info(),
        )

    result = formatter.format(record)

    assert token not in result
    assert "[REDACTED_TELEGRAM_TOKEN]" in result
