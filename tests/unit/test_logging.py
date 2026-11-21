import io
import json
import logging

import pytest

from product_support_agent.logging import (
    JsonLogFormatter,
    RedactingFilter,
    configure_redacted_logging,
    redact_sensitive_text,
)
from product_support_agent.request_context import request_id_context


def test_redacting_filter_removes_secret_assignments_and_email_addresses() -> None:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.addFilter(RedactingFilter())
    logger = logging.getLogger("product_support_agent.test_redaction")
    logger.addHandler(handler)
    logger.propagate = False
    logger.setLevel(logging.INFO)

    try:
        logger.info(
            "api_key=%s contact=%s Authorization: Bearer %s",
            "test-secret",
            "person@example.com",
            "header-secret",
        )
    finally:
        logger.removeHandler(handler)

    output = stream.getvalue()
    assert "test-secret" not in output
    assert "person@example.com" not in output
    assert "header-secret" not in output
    assert "[REDACTED]" in output
    assert "[REDACTED_EMAIL]" in output


def test_redacting_filter_removes_secrets_from_exception_text() -> None:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.addFilter(RedactingFilter())
    logger = logging.getLogger("product_support_agent.test_exception_redaction")
    logger.addHandler(handler)
    logger.propagate = False
    logger.setLevel(logging.ERROR)

    try:
        try:
            raise RuntimeError("password=exception-secret")
        except RuntimeError:
            logger.exception("Request failed")
    finally:
        logger.removeHandler(handler)

    output = stream.getvalue()
    assert "exception-secret" not in output
    assert "[REDACTED]" in output


@pytest.mark.parametrize(
    ("text", "secret"),
    [
        ("access_token=tok-123", "tok-123"),
        ("client_secret=sec-123", "sec-123"),
        ('{"password": "hunter2-json"}', "hunter2-json"),
        ("password: 'hunter2-quoted'", "hunter2-quoted"),
        ("x-api-key: key-123", "key-123"),
        ("AccountName=dev;AccountKey=c3ludGhldGljLWtleQ==;", "c3ludGhldGljLWtleQ"),
        # Assembled at runtime so scanners do not flag a literal credentialed URI.
        ("mongodb://admin:" + "synthetic-pw" + "@localhost:27017/db", "synthetic-pw"),
        ("GET /x?sig=sas-signature-123&se=2026 HTTP/1.1", "sas-signature-123"),
        ("Bearer abcdefghijklmnop", "abcdefghijklmnop"),
        ("Cookie: session=cookie-value-1", "cookie-value-1"),
        ("jwt eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.signature", "eyJhbGciOiJIUzI1NiJ9"),
    ],
)
def test_redact_sensitive_text_covers_common_secret_shapes(text: str, secret: str) -> None:
    redacted = redact_sensitive_text(text)

    assert secret not in redacted
    assert "REDACTED" in redacted


def test_redact_sensitive_text_leaves_ordinary_text_alone() -> None:
    text = "GET /healthz status=200 tokens_used=5 signature_check passed"

    assert redact_sensitive_text(text) == text


def test_configure_redacted_logging_covers_server_loggers() -> None:
    root_logger = logging.getLogger()
    access_logger = logging.getLogger("uvicorn.access")
    saved_root = (root_logger.level, list(root_logger.handlers), list(root_logger.filters))
    saved_access = (list(access_logger.handlers), access_logger.propagate)

    stream = io.StringIO()
    access_logger.handlers = [logging.StreamHandler(stream)]
    access_logger.propagate = False
    root_logger.handlers = [logging.StreamHandler(stream)]
    try:
        configure_redacted_logging()
        assert access_logger.propagate is True
        assert access_logger.handlers == []

        access_logger.setLevel(logging.INFO)
        access_logger.info('GET /healthz?api_key=%s&e=%s "HTTP/1.1" 200', "leak-1", "a@b.example")
    finally:
        root_logger.setLevel(saved_root[0])
        root_logger.handlers = saved_root[1]
        access_logger.handlers, access_logger.propagate = saved_access

    output = stream.getvalue()
    assert "leak-1" not in output
    assert "a@b.example" not in output
    assert json.loads(output)["logger"] == "uvicorn.access"


def test_configure_redacted_logging_enables_info_level() -> None:
    root_logger = logging.getLogger()
    saved = (root_logger.level, list(root_logger.handlers))
    try:
        configure_redacted_logging()
        assert root_logger.getEffectiveLevel() == logging.INFO
    finally:
        root_logger.setLevel(saved[0])
        root_logger.handlers = saved[1]


def test_json_log_format_includes_request_correlation_id() -> None:
    token = request_id_context.set("request-123")
    try:
        record = logging.LogRecord(
            name="product_support_agent.api",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="API ready",
            args=(),
            exc_info=None,
        )
        entry = json.loads(JsonLogFormatter().format(record))
    finally:
        request_id_context.reset(token)

    assert entry["level"] == "INFO"
    assert entry["logger"] == "product_support_agent.api"
    assert entry["message"] == "API ready"
    assert entry["request_id"] == "request-123"
