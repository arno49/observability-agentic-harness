from __future__ import annotations

import json
import logging
import logging.handlers
import os
from datetime import datetime, timezone

# Mirrors Hugging Face's LOG_LEVEL convention; use BEACON_ prefix to avoid collisions.
_LOG_LEVEL = os.getenv("BEACON_LOG_LEVEL", "WARNING").upper()
_LOG_DIR = os.getenv("BEACON_LOG_DIR", "logs")

_configured = False


class _JSONFormatter(logging.Formatter):
    """Structured JSON lines for the rotating file handler."""

    def format(self, record: logging.LogRecord) -> str:
        entry: dict = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if hasattr(record, "data"):
            entry["data"] = record.data
        return json.dumps(entry, default=str)


def _setup() -> None:
    global _configured
    if _configured:
        return
    _configured = True

    level = getattr(logging, _LOG_LEVEL, logging.WARNING)

    root = logging.getLogger("beacon")
    root.setLevel(logging.DEBUG)  # individual handlers apply their own level
    root.propagate = False

    # Console — same format string as HuggingFace transformers/datasets
    console = logging.StreamHandler()
    console.setLevel(level)
    console.setFormatter(logging.Formatter("%(levelname)s:%(name)s:%(message)s"))
    root.addHandler(console)

    # Rotating JSON file — always DEBUG so nothing is silently dropped
    os.makedirs(_LOG_DIR, exist_ok=True)
    fh = logging.handlers.RotatingFileHandler(
        os.path.join(_LOG_DIR, "beacon.log"),
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(_JSONFormatter())
    root.addHandler(fh)


def get_logger(name: str) -> logging.Logger:
    """Return a ``beacon.<name>`` logger, configuring handlers on first call."""
    _setup()
    return logging.getLogger(f"beacon.{name}")
