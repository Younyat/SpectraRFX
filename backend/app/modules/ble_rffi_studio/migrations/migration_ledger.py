"""General, auditable migration-provenance mechanism (2026-08-08 correction
#5): every migration script that rewrites already-persisted metadata must
call record_migration() for each field it actually changes. The ledger is
append-only (read-all + append + atomic rewrite, matching this codebase's
existing write_jsonl/read_jsonl convention -- see ble_offline_replay.py; no
prior entry is ever edited or removed by this module).

This module NEVER touches I/Q. It only ever appends MigrationRecord rows to
migration_ledger.jsonl -- callers are responsible for the actual field
mutation, this module is purely the audit trail.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.infrastructure.ble.capture.ble_offline_replay import read_jsonl, utc_now, write_jsonl

from ..contracts.common import identity_hash

MIGRATION_LEDGER_FILENAME = "migration_ledger.jsonl"


def _git_revision() -> str | None:
    """Best-effort real git commit hash of the running code -- None (never
    a fabricated placeholder) when git is unavailable or this isn't a git
    checkout."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=5,
            cwd=Path(__file__).resolve().parents[5],
        )
        return result.stdout.strip() if result.returncode == 0 and result.stdout.strip() else None
    except Exception:
        return None


@dataclass(frozen=True)
class MigrationRecord:
    migration_id: str
    migration_version: str
    timestamp_utc: str
    code_revision: str | None
    artifact_type: str
    artifact_id: str
    field: str
    old_value: Any
    new_value: Any
    reason: str
    migration_tool: str
    status: str  # "SUCCESS" | "FAILURE"
    retroactive: bool = False


def ledger_path(ble_rffi_studio_root: Path) -> Path:
    return ble_rffi_studio_root / "provenance" / MIGRATION_LEDGER_FILENAME


def record_migration(
    ble_rffi_studio_root: Path, *, migration_version: str, artifact_type: str, artifact_id: str, field: str,
    old_value: Any, new_value: Any, reason: str, migration_tool: str, status: str = "SUCCESS",
    retroactive: bool = False, timestamp_utc: str | None = None, code_revision: str | None = None,
) -> MigrationRecord:
    """Appends one real, immutable migration record. timestamp_utc/
    code_revision are computed for real (utc_now()/git rev-parse) unless the
    caller overrides them -- retroactive reconstructions pass an explicit,
    honestly-labeled timestamp_utc for when the ORIGINAL change actually
    happened (best known), never the reconstruction time, and MUST pass
    retroactive=True."""
    resolved_timestamp = timestamp_utc or utc_now()
    resolved_revision = code_revision if code_revision is not None else _git_revision()
    migration_id = identity_hash(migration_version, artifact_type, artifact_id, field, resolved_timestamp, prefix="mig")
    record = MigrationRecord(
        migration_id=migration_id, migration_version=migration_version, timestamp_utc=resolved_timestamp,
        code_revision=resolved_revision, artifact_type=artifact_type, artifact_id=artifact_id, field=field,
        old_value=old_value, new_value=new_value, reason=reason, migration_tool=migration_tool,
        status=status, retroactive=retroactive,
    )
    path = ledger_path(ble_rffi_studio_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = read_jsonl(path)
    existing.append(_record_to_dict(record))
    write_jsonl(path, existing)
    return record


def _record_to_dict(record: MigrationRecord) -> dict[str, Any]:
    return {
        "migration_id": record.migration_id, "migration_version": record.migration_version,
        "timestamp_utc": record.timestamp_utc, "code_revision": record.code_revision,
        "artifact_type": record.artifact_type, "artifact_id": record.artifact_id, "field": record.field,
        "old_value": record.old_value, "new_value": record.new_value, "reason": record.reason,
        "migration_tool": record.migration_tool, "status": record.status, "retroactive": record.retroactive,
    }


def read_migration_ledger(ble_rffi_studio_root: Path) -> list[dict[str, Any]]:
    return read_jsonl(ledger_path(ble_rffi_studio_root))
