from __future__ import annotations

import logging

from app.config.settings import settings


def configure_logging() -> None:
    logging.basicConfig(
        level=getattr(logging, settings.logging.level.upper(), logging.INFO),
        format=settings.logging.format,
    )