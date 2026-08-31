from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

SIGMF_VERSION = "1.2.6"
MANIFEST_VERSION = "1.0"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _long_path(path: Path) -> str:
    """Windows silently refuses to create/replace a file whose absolute
    path exceeds MAX_PATH (260 chars, including the .tmp atomic-write
    suffix) unless given the \\\\?\\ extended-length prefix -- observed for
    real: a guided-validation run_id/action_id nesting pushed an artifact
    path to exactly 260 chars and CreateFileW failed with "path not
    found" instead of a clearer length error. No-op on non-Windows."""
    resolved = str(path.resolve())
    if os.name == "nt" and not resolved.startswith("\\\\?\\"):
        return "\\\\?\\" + resolved
    return resolved


def atomic_json(path: Path, value: Any) -> None:
    os.makedirs(_long_path(path.parent), exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with open(_long_path(temporary), "w", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    # os.replace() can raise a transient PermissionError ([WinError 5]) when
    # something else (antivirus real-time scan, search indexer, OneDrive/
    # backup sync) briefly has the destination open -- observed directly in
    # real, otherwise-successful long-running jobs. A short retry absorbs
    # that without masking a genuine, persistent failure.
    last_error: OSError | None = None
    for attempt in range(6):
        try:
            os.replace(_long_path(temporary), _long_path(path))
            return
        except PermissionError as error:
            last_error = error
            time.sleep(0.05 * (2 ** attempt))
    raise last_error


def validate_sigmf(metadata: dict[str, Any]) -> None:
    global_meta = metadata.get("global")
    captures = metadata.get("captures")
    if not isinstance(global_meta, dict) or not isinstance(captures, list) or len(captures) != 1:
        raise ValueError("INVALID_SIGMF_STRUCTURE")
    required_global = {"core:version", "core:datatype", "core:sample_rate", "core:hw", "core:recorder"}
    if not required_global.issubset(global_meta):
        raise ValueError("INVALID_SIGMF_GLOBAL")
    if global_meta["core:datatype"] not in {"ci8", "ci16_le", "cf32_le"}:
        raise ValueError("UNSUPPORTED_SIGMF_DATATYPE")
    if not {"core:sample_start", "core:frequency", "core:datetime"}.issubset(captures[0]):
        raise ValueError("INVALID_SIGMF_CAPTURE")
