"""Single logging configuration shared by all scrapers, the API, and the UI.

Reads LOG_LEVEL from the environment (default INFO). Idempotent — calling
configure_logging() more than once is safe.
"""

from __future__ import annotations

import logging
import os
from logging import Logger

_CONFIGURED = False
_FORMAT = "%(asctime)s %(name)s %(levelname)s %(message)s"


def configure_logging() -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(level=level, format=_FORMAT)
    _CONFIGURED = True


def get_logger(name: str) -> Logger:
    configure_logging()
    return logging.getLogger(name)
