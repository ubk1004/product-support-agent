import json
import logging
import re
from datetime import UTC, datetime

from product_support_agent.request_context import request_id_context

_SECRET_ASSIGNMENT = re.compile(
    r"""(?ix)
    \b(password|passwd|secret|token|api[_-]?key)\b
    (\s*[:=]\s*)
    (?:"[^"]*"|'[^']*'|[^\s,;]+)
    """
)
_AUTHORIZATION = re.compile(r"(?i)\bauthorization\s*[:=]\s*(?:bearer\s+)?[^\s,;]+")
_EMAIL_ADDRESS = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)


def redact_sensitive_text(value: str) -> str:
    value = _SECRET_ASSIGNMENT.sub(r"\1\2[REDACTED]", value)
    value = _AUTHORIZATION.sub("Authorization: [REDACTED]", value)
    return _EMAIL_ADDRESS.sub("[REDACTED_EMAIL]", value)


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact_sensitive_text(record.getMessage())
        record.args = ()

        if record.exc_info:
            record.exc_text = redact_sensitive_text(
                logging.Formatter().formatException(record.exc_info)
            )
            record.exc_info = None
        elif record.exc_text:
            record.exc_text = redact_sensitive_text(record.exc_text)

        return True


class JsonLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": redact_sensitive_text(record.getMessage()),
            "request_id": request_id_context.get(),
        }
        if record.exc_info:
            entry["exception"] = redact_sensitive_text(self.formatException(record.exc_info))
        elif record.exc_text:
            entry["exception"] = redact_sensitive_text(record.exc_text)
        return json.dumps(entry, ensure_ascii=True, separators=(",", ":"))


def configure_redacted_logging() -> None:
    root_logger = logging.getLogger()
    if not root_logger.handlers:
        root_logger.addHandler(logging.StreamHandler())

    for handler in root_logger.handlers:
        handler.setFormatter(JsonLogFormatter())
        if not any(isinstance(item, RedactingFilter) for item in handler.filters):
            handler.addFilter(RedactingFilter())
