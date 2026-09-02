"""Small JSON logger with an intentionally narrow, non-sensitive event surface."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_LOGGER_NAME = "healthcheck"
_SAFE_FIELDS = frozenset({"operation", "service", "status", "count", "reason"})


class JsonFormatter(logging.Formatter):
    """Serialize only structured event metadata, never arbitrary log messages."""

    def format(self, record: logging.LogRecord) -> str:
        event = getattr(record, "event", record.name)
        fields = getattr(record, "safe_fields", {})
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "event": str(event),
        }
        payload.update({key: str(value) for key, value in fields.items() if key in _SAFE_FIELDS})
        if record.exc_info:
            payload["exception"] = "present"
        return json.dumps(payload, ensure_ascii=True, sort_keys=True)


def get_logger() -> logging.Logger:
    return logging.getLogger(_LOGGER_NAME)


def log_event(event: str, **fields: Any) -> None:
    """Write a safe event; unknown fields are deliberately discarded."""

    safe_fields = {key: value for key, value in fields.items() if key in _SAFE_FIELDS}
    get_logger().info(event, extra={"event": event, "safe_fields": safe_fields})


def configure_logging(log_dir: Path, level: str = "INFO") -> Path:
    """Configure console and external-file JSON logging and return the log path."""

    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "healthcheck.log"
    logger = get_logger()
    logger.handlers.clear()
    logger.setLevel(level)
    logger.propagate = False

    formatter = JsonFormatter()
    stream = logging.StreamHandler()
    stream.setFormatter(formatter)
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(stream)
    logger.addHandler(file_handler)
    return log_path
