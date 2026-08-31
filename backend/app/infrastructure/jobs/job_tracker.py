"""In-memory, thread-safe job progress tracker for long-running background
operations, shared across feature modules (not persisted across backend
restarts -- matches the existing behavior of the e6_oracle_style job tracker
this was generalized from). Each caller picks its own `operation` label so
jobs from different features can share one registry without colliding."""
from __future__ import annotations

import threading
import time
import uuid
from typing import Any, Dict, List, Optional

_JOBS: Dict[str, Dict[str, Any]] = {}
_LOCK = threading.Lock()


def create_job(operation: str, description: str = "") -> str:
    job_id = str(uuid.uuid4())
    now = time.time()
    with _LOCK:
        _JOBS[job_id] = {
            "job_id": job_id,
            "operation": operation,
            "description": description,
            "status": "running",
            "progress": 0,
            "message": "Starting…",
            "result": None,
            "error": None,
            "started_at": now,
            "finished_at": None,
            "elapsed_s": None,
            "steps": [],
        }
    return job_id


def update_job(job_id: str, progress: int, message: str, **extra: Any) -> None:
    with _LOCK:
        job = _JOBS.get(job_id)
        if job is None or job["status"] != "running":
            return
        clamped = min(max(int(progress), 0), 99)
        job["progress"] = clamped
        job["message"] = message
        elapsed = round(time.time() - job["started_at"], 2)
        job["elapsed_s"] = elapsed
        job["steps"].append({"progress": clamped, "message": message, "t": elapsed})
        for k, v in extra.items():
            job[k] = v


def complete_job(job_id: str, result: Any) -> None:
    with _LOCK:
        job = _JOBS.get(job_id)
        if job is None:
            return
        now = time.time()
        job["status"] = "done"
        job["progress"] = 100
        job["message"] = "Complete"
        job["result"] = result
        job["finished_at"] = now
        job["elapsed_s"] = round(now - job["started_at"], 2)


def fail_job(job_id: str, error: str) -> None:
    with _LOCK:
        job = _JOBS.get(job_id)
        if job is None:
            return
        now = time.time()
        job["status"] = "error"
        job["message"] = error
        job["error"] = error
        job["finished_at"] = now
        job["elapsed_s"] = round(now - job["started_at"], 2)


def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    with _LOCK:
        j = _JOBS.get(job_id)
        if j is None:
            return None
        copy = dict(j)
        copy["steps"] = list(j["steps"])
        return copy


def list_jobs(operation: str | None = None) -> List[Dict[str, Any]]:
    with _LOCK:
        jobs = sorted(_JOBS.values(), key=lambda j: j.get("started_at", 0), reverse=True)
        if operation is not None:
            jobs = [j for j in jobs if j.get("operation") == operation]
        return [{**j, "steps": []} for j in jobs]


def cleanup_old_jobs(max_age_seconds: int = 7200) -> int:
    now = time.time()
    with _LOCK:
        to_delete = [
            jid for jid, job in _JOBS.items()
            if job.get("finished_at") and (now - job["finished_at"]) > max_age_seconds
        ]
        for jid in to_delete:
            _JOBS.pop(jid, None)
    return len(to_delete)
