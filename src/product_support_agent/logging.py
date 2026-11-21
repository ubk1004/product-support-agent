import json
import logging
import re
from datetime import UTC, datetime

from product_support_agent.request_context import request_id_context

# Key names whose values are secrets, optionally prefixed (for example
# client_secret, access_token, x-api-key) and optionally quoted as JSON keys.
_SECRET_ASSIGNMENT = re.compile(
    r"""(?ix)
    (?<![\w-])
    ((?:[\w-]*[_-])?
     (?:password|passwd|pwd|secret|token|api[_-]?key|apikey|account[_-]?key
        |shared[_-]?access[_-]?key|sig|credential))
    \b
    (["']?\s*[:=]\s*)
    (?:"[^"]*"|'[^']*'|[^\s,;&"'}]+)
    """
)
_AUTHORIZATION = re.compile(r"(?i)\bauthorization\s*[:=]\s*(?:(?:bearer|basic)\s+)?[^\s,;]+")
_BEARER_TOKEN = re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}")
_COOKIE_HEADER = re.compile(r"(?i)\b((?:set-)?cookie\s*:\s*)[^\r\n]+")
_URL_USERINFO = re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://[^\s/:@]+:)[^\s/@]+@")
_JWT = re.compile(r"\beyJ[\w-]{5,}\.[\w-]{5,}\.[\w-]*")
_EMAIL_ADDRESS = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)

# Server loggers that install their own handlers and do not propagate, which
# would otherwise bypass redaction (for example uvicorn access logs, which
# include query strings).
_SERVER_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access")


def redact_sensitive_text(value: str) -> str:
    value = _URL_USERINFO.sub(r"\1[REDACTED]@", value)
    value = _AUTHORIZATION.sub("Authorization: [REDACTED]", value)
    value = _COOKIE_HEADER.sub(r"\1[REDACTED]", value)
    value = _BEARER_TOKEN.sub(r"\1 [REDACTED]", value)
    value = _SECRET_ASSIGNMENT.sub(r"\1\2[REDACTED]", value)
    value = _JWT.sub("[REDACTED_JWT]", value)
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


def configure_redacted_logging(level: int = logging.INFO) -> None:
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    if not root_logger.handlers:
        root_logger.addHandler(logging.StreamHandler())

    for handler in root_logger.handlers:
        handler.setFormatter(JsonLogFormatter())
        if not any(isinstance(item, RedactingFilter) for item in handler.filters):
            handler.addFilter(RedactingFilter())

    # Route server loggers through the redacting root handlers. A server logger
    # with no handlers is left alone so that options such as uvicorn's
    # --no-access-log keep working.
    for name in _SERVER_LOGGERS:
        server_logger = logging.getLogger(name)
        if server_logger.handlers:
            server_logger.handlers.clear()
            server_logger.propagate = True
