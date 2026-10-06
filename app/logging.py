from __future__ import annotations

import json
import logging
from typing import Any

SENSITIVE = {"password", "token", "secret", "api_key", "authorization", "encrypted_payload", "bot_token"}


def redact(value: Any, key: str | None = None) -> Any:
    if key and any(part in key.lower() for part in SENSITIVE):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {k: redact(v, k) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(v) for v in value]
    return value


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        extra = getattr(record, "safe_extra", None)
        if extra:
            payload.update(redact(extra))
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(logging.INFO)
