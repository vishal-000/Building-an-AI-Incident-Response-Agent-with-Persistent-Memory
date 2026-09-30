"""Structured operational logging configuration for Incident Memory Agent."""

import logging
import sys
from backend.app.config import settings


def setup_logging() -> logging.Logger:
    """Configures structured application logging with clean formatting."""
    log_format = "%(asctime)s | %(levelname)-8s | [%(name)s] %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"

    level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)

    # Configure root logger
    logging.basicConfig(
        level=level,
        format=log_format,
        datefmt=date_format,
        handlers=[logging.StreamHandler(sys.stdout)],
        force=True,
    )

    # Specific logger for application
    logger = logging.getLogger("incident_memory_agent")
    logger.setLevel(level)

    # Suppress overly chatty 3rd-party loggers
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("aiosqlite").setLevel(logging.WARNING)

    return logger


logger = setup_logging()
