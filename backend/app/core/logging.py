"""Structured JSON logging with secret redaction.

Usage:
    logger = logging.getLogger(__name__)
    logger.info("llm_call", extra={"fields": {"agent": "planner", "tokens": 812}})

Each record becomes one JSON line, so logs can be searched and parsed later.
"""

import json
import logging
import sys
from datetime import UTC, datetime

REDACTED = "***REDACTED***"


class RedactSecretsFilter(logging.Filter):
    """Replaces any known secret value in the message or fields with a placeholder."""

    def __init__(self, secrets: list[str]) -> None:
        super().__init__()
        self._secrets = [s for s in secrets if s]

    def _clean(self, text: str) -> str:
        for secret in self._secrets:
            text = text.replace(secret, REDACTED)
        return text

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = self._clean(record.getMessage())
        record.args = None  # already merged into msg above
        fields = getattr(record, "fields", None)
        if isinstance(fields, dict):
            record.fields = json.loads(self._clean(json.dumps(fields, default=str)))
        return True  # never drop the record, only clean it


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        fields = getattr(record, "fields", None)
        if isinstance(fields, dict):
            entry.update(fields)
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str)


def configure_logging(level: str, secrets: list[str]) -> None:
    """Send JSON logs to stderr. Called once at program start."""
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(RedactSecretsFilter(secrets))

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)

    # The HTTP libraries log every request at INFO; keep them quiet.
    for noisy in ("httpx", "httpx2", "httpcore", "openai"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
