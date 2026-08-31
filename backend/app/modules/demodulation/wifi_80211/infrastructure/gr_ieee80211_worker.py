from __future__ import annotations

import json
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from time import monotonic


@dataclass(frozen=True)
class WorkerResult:
    status: str
    exit_code: int | None
    stdout: str
    stderr: str
    timed_out: bool
    cancelled: bool
    duration_seconds: float


class GrIeee80211Worker:
    """Stable process boundary; no GNU Radio code runs in FastAPI."""

    def __init__(self, command: list[str], timeout_seconds: float = 300.0) -> None:
        if not command:
            raise ValueError("Worker command is empty")
        self.command = command
        self.timeout_seconds = timeout_seconds

    def run(self, manifest: Path, output_dir: Path, cancel: threading.Event | None = None) -> WorkerResult:
        output_dir.mkdir(parents=True, exist_ok=True)
        started = monotonic()
        process = subprocess.Popen(
            [*self.command, "--manifest", str(manifest), "--output-dir", str(output_dir)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        timed_out = cancelled = False
        while process.poll() is None:
            if cancel is not None and cancel.is_set():
                cancelled = True; process.terminate(); break
            if monotonic() - started > self.timeout_seconds:
                timed_out = True; process.kill(); break
            try:
                process.wait(timeout=0.1)
            except subprocess.TimeoutExpired:
                pass
        stdout, stderr = process.communicate()
        code = process.returncode
        status = "cancelled" if cancelled else "timeout" if timed_out else "complete" if code == 0 else "failed"
        result = WorkerResult(status, code, stdout, stderr, timed_out, cancelled, monotonic() - started)
        (output_dir / "worker_process.json").write_text(json.dumps(result.__dict__, indent=2), encoding="utf-8")
        (output_dir / "worker.stdout.log").write_text(stdout, encoding="utf-8")
        (output_dir / "worker.stderr.log").write_text(stderr, encoding="utf-8")
        return result
