"""Per-module progress/error log -- same rotating-file convention as
`ble_rffi_studio.module_logging`, kept as an independent copy (not a shared
import) so this module's log volume and rotation never compete with or
depend on ble_rffi_studio's own logger instance.
"""
from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path

_LOGGER_NAME = "ble_scientific_results"


def build_module_logger(root: Path) -> logging.Logger:
    logger = logging.getLogger(_LOGGER_NAME)
    logger.setLevel(logging.INFO)
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
    logs_dir = root / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(
        logs_dir / "ble_scientific_results.log", maxBytes=5_000_000, backupCount=3, encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    logger.propagate = False
    return logger
