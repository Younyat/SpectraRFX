"""Job orchestration for the experimental Gate 2A.2 offline IQ analysis flow.

Deliberately a separate class from BleJobManager (ble_job_manager.py), not a
subclass or a branch inside it -- Gate 1B's manifest/CRC/duplicate-publication
rules must never be able to regress because of a change made here. This
manager reuses BleRepository as-is (already generic over job-id prefix) but
has its own, simpler state machine: no artifact-hash manifest validation step,
since ble-worker-lab's own worker script (ble_gate2a2_offline_worker.py) is
what actually calls the frozen Gate 1A/1B decode+CRC code -- the job manager's
role here is only to run it as a subprocess and expose the result, not to
re-validate it the way Gate 1B's artifact validator does."""
from __future__ import annotations

import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

TERMINAL = {"completed", "failed", "cancelled", "timed_out"}


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass
class Gate2a2WorkerConfig:
    repository: Path
    python_executable: Path
    entry_point: Path
    timeout_seconds: float = 120.0


class BleGate2a2WorkerAdapter:
    """Subprocess boundary for the experimental worker. Unlike BleWorkerAdapter
    (Gate 1B), this does NOT hard-pin and verify a git commit -- ble-worker-lab
    is explicitly not frozen for Gate 2A.2, so there is no single commit to
    demand. The worker script itself records whatever commit it actually ran
    against as provenance."""

    def __init__(self, config: Gate2a2WorkerConfig) -> None:
        self.config = config

    def available(self) -> bool:
        return (
            self.config.python_executable.is_file()
            and self.config.repository.is_dir()
            and self.config.entry_point.is_file()
        )

    def run(self, job_id: str, job_dir: Path, cancel_requested: Callable[[], bool]) -> dict[str, Any]:
        if not self.available():
            raise RuntimeError("gate2a2_worker_unavailable")
        request = job_dir / "request.json"
        stdout_path = job_dir / "worker_stdout.log"
        stderr_path = job_dir / "worker_stderr.log"
        command = [
            str(self.config.python_executable), str(self.config.entry_point),
            "--worker-repository", str(self.config.repository),
            "--request", str(request), "--output-dir", str(job_dir), "--job-id", job_id,
        ]
        started = time.monotonic()
        with stdout_path.open("wb") as out, stderr_path.open("wb") as err:
            process = subprocess.Popen(command, cwd=self.config.entry_point.parent, stdout=out, stderr=err)
            while process.poll() is None:
                if cancel_requested():
                    process.terminate(); process.wait(timeout=5)
                    return {"cancelled": True, "exit_code": process.returncode}
                if time.monotonic() - started > self.config.timeout_seconds:
                    process.kill(); process.wait()
                    raise TimeoutError("gate2a2_worker_timeout")
                time.sleep(0.05)
        return {"exit_code": process.returncode, "cancelled": False}


class BleGate2a2JobManager:
    def __init__(self, repository, adapter: BleGate2a2WorkerAdapter, enabled: bool = True) -> None:
        self.repository = repository
        self.adapter = adapter
        self.enabled = enabled
        self.cancelled: set[str] = set()
        self.lock = threading.Lock()

    def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.enabled:
            raise PermissionError("ble_gate2a2_offline_disabled")
        missing = [key for key in ("iq_file_path", "channel_index") if not payload.get(key)]
        if missing:
            raise ValueError(f"missing_fields:{','.join(missing)}")
        with self.lock:
            existing = [
                int(p.name.rsplit("-", 1)[-1])
                for p in self.repository.root.glob("BLE-G2A2-JOB-*")
                if p.name.rsplit("-", 1)[-1].isdigit()
            ]
            job_id = f"BLE-G2A2-JOB-{max(existing, default=0) + 1:06d}"
            request_data = dict(payload)
            request_data["job_id"] = job_id
            request_data.setdefault("contract_version", "ble-gate2a2-offline-job-v1")
            self.repository.create(job_id, request_data)
            self.repository.write(job_id, "job.json", {"job_id": job_id, "state": "created", "request": request_data})
            self.transition(job_id, "created", None, "request_accepted")
            self.transition(job_id, "queued", "created", "execution_scheduled")
        threading.Thread(target=self.execute, args=(job_id,), daemon=True).start()
        return self.get(job_id)

    def transition(self, job_id: str, state: str, previous: str | None, reason: str, **extra: Any) -> None:
        event = {
            "sequence": len(self.repository.events(job_id)) + 1, "job_id": job_id, "timestamp_utc": now(),
            "previous_state": previous, "new_state": state, "reason": reason, **extra,
        }
        self.repository.append_event(job_id, event)
        job = self.repository.read(job_id, "job.json")
        job.update(state=state, updated_at_utc=event["timestamp_utc"], error=extra.get("error"))
        self.repository.write(job_id, "job.json", job)

    def execute(self, job_id: str) -> None:
        state = "queued"
        try:
            for next_state, reason in (("starting_worker", "dequeued"), ("running", "worker_started")):
                self.transition(job_id, next_state, state, reason)
                state = next_state
            result = self.adapter.run(job_id, self.repository.job_dir(job_id), lambda: job_id in self.cancelled)
            if result.get("cancelled"):
                self.transition(job_id, "cancelled", state, "worker_cancelled")
                return
            if result.get("exit_code") != 0:
                raise RuntimeError(f"worker_exit_nonzero:{result.get('exit_code')}")
            self.transition(job_id, "completed", state, "worker_exit_zero", worker_exit_code=0)
        except TimeoutError as error:
            self.transition(job_id, "timed_out", state, "worker_timeout", error=str(error))
        except Exception as error:
            self.transition(job_id, "failed", state, "worker_failed", error=str(error))

    def get(self, job_id: str) -> dict[str, Any]:
        return self.repository.read(job_id, "job.json")

    def cancel(self, job_id: str) -> dict[str, Any]:
        job = self.get(job_id)
        if job["state"] not in TERMINAL:
            self.cancelled.add(job_id)
            self.transition(job_id, "cancel_requested", job["state"], "user_requested")
        return self.get(job_id)
