import io
import json
import logging

from product_support_agent.logging import JsonLogFormatter, RedactingFilter
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
