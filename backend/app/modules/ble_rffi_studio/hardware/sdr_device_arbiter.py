"""Cross-process exclusivity for a physical SDR device (e.g. one USRP B200).

The existing exclusivity mechanism (`RealSpectrumStream.begin_exclusive_operation`
/ `end_exclusive_operation`) is a `threading.Lock` plus an in-memory reason
string -- it only protects against two operations racing inside the SAME
Python process. BLE capture and live-spectrum streaming run as separate OS
processes/subprocesses against the same physical B200, so that in-memory lock
never sees the other side at all. This module fixes that by persisting lock
state to disk (atomic write via os.replace, same pattern as
ble_offline_replay.write_json) and verifying the owning PID is still alive
before trusting a lock found on disk.

States: AVAILABLE (no lock file, or file explicitly marked available) |
ACQUIRED | RELEASING (transient, written just before the file is removed) |
ERROR (a release/cleanup could not be completed cleanly; surfaced instead of
silently discarded).

Orphan cleanup: any lock whose owning PID is no longer alive, OR whose lease
has expired, is treated as available on the next acquire()/get_status() call
-- this is what makes the arbiter survive a crashed worker or a backend
restart without a human having to delete a stale lock file by hand.
"""
from __future__ import annotations

import ctypes
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

AVAILABLE = "AVAILABLE"
ACQUIRED = "ACQUIRED"
RELEASING = "RELEASING"
ERROR = "ERROR"

DEFAULT_LEASE_SECONDS = 300.0


def _is_pid_alive(pid: int) -> bool:
    if pid is None or pid <= 0:
        return False
    if os.name == "nt":
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if handle:
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _safe_device_id(device_id: str) -> str:
    if not device_id or any(part in device_id for part in ("/", "\\", "..")):
        raise ValueError(f"INVALID_DEVICE_ID:{device_id}")
    return device_id


@dataclass
class AcquireResult:
    granted: bool
    status: str
    current_owner: str | None
    current_operation_id: str | None
    lease_expires_at: float | None


class SdrDeviceArbiter:
    """One arbiter instance per lock directory. Safe to construct fresh in
    every process/subprocess that needs to acquire the same device_id -- all
    state lives on disk, not in this instance."""

    def __init__(self, lock_root: Path) -> None:
        self.lock_root = lock_root
        self.lock_root.mkdir(parents=True, exist_ok=True)

    def _lock_path(self, device_id: str) -> Path:
        return self.lock_root / f"{_safe_device_id(device_id)}.json"

    def _read(self, device_id: str) -> dict[str, Any] | None:
        path = self._lock_path(device_id)
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {"status": ERROR, "device_id": device_id, "owner": None, "operation_id": None, "pid": None, "acquired_at": None, "lease_expires_at": None}

    def _write(self, device_id: str, record: dict[str, Any]) -> None:
        path = self._lock_path(device_id)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(record, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(temporary, path)

    def _is_stale(self, record: dict[str, Any], now: float) -> bool:
        if record.get("status") != ACQUIRED and record.get("status") != RELEASING:
            return False
        lease_expires_at = record.get("lease_expires_at")
        if lease_expires_at is not None and now > float(lease_expires_at):
            return True
        return not _is_pid_alive(record.get("pid"))

    def acquire(self, device_id: str, owner: str, operation_id: str, lease_seconds: float = DEFAULT_LEASE_SECONDS) -> AcquireResult:
        now = time.time()
        existing = self._read(device_id)

        if existing is not None and existing.get("status") in (ACQUIRED, RELEASING) and not self._is_stale(existing, now):
            if existing.get("owner") == owner and existing.get("operation_id") == operation_id:
                # Idempotent re-acquire by the same owner/operation: refresh the lease.
                record = dict(existing, lease_expires_at=now + lease_seconds)
                self._write(device_id, record)
                return AcquireResult(True, ACQUIRED, owner, operation_id, record["lease_expires_at"])
            return AcquireResult(False, existing.get("status", ACQUIRED), existing.get("owner"), existing.get("operation_id"), existing.get("lease_expires_at"))

        # Either no lock, AVAILABLE, ERROR, or a stale/orphaned ACQUIRED/RELEASING record.
        record = {
            "device_id": device_id,
            "status": ACQUIRED,
            "owner": owner,
            "operation_id": operation_id,
            "pid": os.getpid(),
            "acquired_at": now,
            "lease_expires_at": now + lease_seconds,
        }
        self._write(device_id, record)
        return AcquireResult(True, ACQUIRED, owner, operation_id, record["lease_expires_at"])

    def release(self, device_id: str, owner: str, operation_id: str) -> bool:
        existing = self._read(device_id)
        if existing is None or existing.get("status") not in (ACQUIRED, RELEASING):
            return False
        now = time.time()
        if existing.get("owner") != owner or existing.get("operation_id") != operation_id:
            if not self._is_stale(existing, now):
                return False  # held by someone else, and not orphaned -- refuse to release it
        # Mark RELEASING first so a crash between these two writes is still
        # observable (and self-heals via _is_stale, since RELEASING with a
        # dead PID is treated as stale) instead of leaving a phantom ACQUIRED.
        self._write(device_id, dict(existing, status=RELEASING))
        record = {
            "device_id": device_id,
            "status": AVAILABLE,
            "owner": None,
            "operation_id": None,
            "pid": None,
            "acquired_at": None,
            "lease_expires_at": None,
        }
        self._write(device_id, record)
        return True

    def get_status(self, device_id: str) -> dict[str, Any]:
        existing = self._read(device_id)
        if existing is None:
            return {"device_id": device_id, "status": AVAILABLE, "owner": None, "operation_id": None, "acquired_at": None, "lease_expires_at": None}
        now = time.time()
        if self._is_stale(existing, now):
            # Self-heal: an orphaned lock (dead PID or expired lease) reports
            # -- and is persisted -- as AVAILABLE, not as a stale ACQUIRED that
            # would wrongly block the next acquire() forever.
            record = {"device_id": device_id, "status": AVAILABLE, "owner": None, "operation_id": None, "pid": None, "acquired_at": None, "lease_expires_at": None}
            self._write(device_id, record)
            return {k: v for k, v in record.items() if k != "pid"}
        return {k: v for k, v in existing.items() if k != "pid"}
