"""Per-module progress/error log.

Every background job's phase updates and every exception are written here
(in ADDITION to, never instead of, the job.json state each job already
persists) as one plain-text, human-readable file -- so a problem can be
found by opening one file instead of re-running the UI action while
watching the browser network tab. Rotates at 5 MB (keeps 3 backups) so a
long session never grows this unboundedly.
"""
from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path

_LOGGER_NAME = "ble_rffi_studio"


def build_module_logger(root: Path) -> logging.Logger:
    logger = logging.getLogger(_LOGGER_NAME)
    logger.setLevel(logging.INFO)
    # Never duplicate handlers -- module.py can be re-imported/re-wired
    # (e.g. in tests constructing multiple StudioRepository/StudioJobManager
    # instances against different roots) without stacking file handlers.
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
    logs_dir = root / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(
        logs_dir / "ble_rffi_studio.log", maxBytes=5_000_000, backupCount=3, encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    # Never bubble into uvicorn's own root logger/stdout -- this file is a
    # dedicated, additional record, not a replacement for the access log.
    logger.propagate = False
    return logger
