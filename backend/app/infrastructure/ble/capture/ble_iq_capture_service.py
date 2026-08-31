from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


@dataclass(frozen=True)
class CaptureWorkerConfig:
    python_executable: Path
    tool_path: Path
    runtime_root: Path | None = None
    timeout_margin_seconds: float = 20.0


class BleIqCaptureService:
    def __init__(self, config: CaptureWorkerConfig) -> None:
        self.config = config

    def _environment(self) -> dict[str, str]:
        environment = dict(os.environ); root = self.config.runtime_root
        if root:
            system32 = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
            environment["PATH"] = os.pathsep.join(str(path) for path in (root/"Library"/"bin",root/"Scripts",root,system32))
            environment["SOAPY_SDR_PLUGIN_PATH"] = str(root/"Library"/"lib"/"SoapySDR"/"modules0.8")
        return environment

    def capture(self, request_path: Path, output_dir: Path, cancel: Callable[[], bool]) -> dict[str, Any]:
        request = json.loads(request_path.read_text(encoding="utf-8"))
        timeout = float(request["duration_seconds"]) + self.config.timeout_margin_seconds
        command = [str(self.config.python_executable), str(self.config.tool_path), "capture",
                   "--request", str(request_path), "--output-dir", str(output_dir)]
        stdout_path, stderr_path = output_dir / "capture.stdout.log", output_dir / "capture.stderr.log"
        started = time.monotonic()
        with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
            process = subprocess.Popen(command, stdout=stdout, stderr=stderr, shell=False, env=self._environment())
            while process.poll() is None:
                if cancel():
                    process.terminate()
                    try: process.wait(timeout=5)
                    except subprocess.TimeoutExpired: process.kill(); process.wait()
                    return {"cancelled": True, "exit_code": process.returncode}
                if time.monotonic() - started > timeout:
                    process.kill(); process.wait()
                    raise TimeoutError("CAPTURE_TIMEOUT")
                time.sleep(0.05)
        if process.returncode != 0:
            raise RuntimeError(f"CAPTURE_WORKER_FAILED:{process.returncode}")
        return {"cancelled": False, "exit_code": 0}
