"""Logging setup: rotating ``app.log`` plus a daily ``batch_YYYY-MM-DD.log``."""
from __future__ import annotations

import logging
import logging.handlers
from datetime import date

from app.utils.paths import logs_dir

_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_configured = False


def setup_logging(level: int = logging.INFO) -> None:
    global _configured
    if _configured:
        return
    _configured = True
    root = logging.getLogger()
    root.setLevel(level)
    fmt = logging.Formatter(_FORMAT)

    app_handler = logging.handlers.RotatingFileHandler(
        logs_dir() / "app.log", maxBytes=5_000_000, backupCount=5, encoding="utf-8"
    )
    app_handler.setFormatter(fmt)
    root.addHandler(app_handler)

    console = logging.StreamHandler()
    console.setFormatter(fmt)
    console.setLevel(logging.WARNING)
    root.addHandler(console)

    # Batch events additionally go to a per-day file.
    batch_handler = logging.FileHandler(
        logs_dir() / f"batch_{date.today().isoformat()}.log", encoding="utf-8"
    )
    batch_handler.setFormatter(fmt)
    batch_logger = logging.getLogger("batch")
    batch_logger.addHandler(batch_handler)

    # httpx logs every request at INFO including full URLs; keep it quieter.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
