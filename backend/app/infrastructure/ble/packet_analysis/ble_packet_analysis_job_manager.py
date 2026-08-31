"""Async job wrapper around BlePacketAnalysisService, following the exact
same pattern as BleCaptureJobManager's offline-replay jobs (background
thread, job.json state machine, ordered cancellation) so the frontend reuses
one mental model across both labs instead of learning a second one.
"""
from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..capture.ble_capture_metadata import atomic_json
from ..capture.ble_offline_replay import read_jsonl
from .ble_packet_analysis_service import BlePacketAnalysisService
from .models import JOB_PHASES

TERMINAL = {"completed", "failed", "cancelled"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class BlePacketAnalysisJobManager:
    def __init__(self, capture_root: Path, session_root: Path, analysis_root: Path, jobs_root: Path) -> None:
        self.service = BlePacketAnalysisService(capture_root, session_root, analysis_root)
        self.jobs_root = jobs_root
        self.jobs_root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._active: str | None = None
        self._cancel: set[str] = set()

    def list_captures(self) -> dict[str, Any]:
        return self.service.list_captures()

    def latest_completed_capture(self) -> dict[str, Any]:
        listing = self.service.list_captures()
        capture_id = listing["classification"].get("LAST_FULLY_ANALYZED_CAPTURE")
        if not capture_id:
            raise FileNotFoundError("NO_FULLY_ANALYZED_CAPTURE_YET")
        capture = next(row for row in listing["captures"] if row["capture_id"] == capture_id)
        return {"classification": "LAST_FULLY_ANALYZED_CAPTURE", "capture": capture}

    def start_job(self, capture_id: str, replay_run_id: str | None = None) -> dict[str, Any]:
        with self._lock:
            if self._active:
                raise RuntimeError("PACKET_ANALYSIS_JOB_ALREADY_RUNNING")
            job_id = "BLE-PKTLAB-JOB-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:6]
            job_dir = self._job_dir(job_id)
            job_dir.mkdir(parents=True, exist_ok=False)
            atomic_json(job_dir / "job.json", {
                "schema_version": "ble-packet-analysis-job-v1", "job_id": job_id, "job_type": "BLE_PACKET_ANALYSIS",
                "capture_id": capture_id, "replay_run_id": replay_run_id, "state": "queued", "cancellable": True,
                "phase": None, "phase_progress": 0.0, "overall_progress": 0.0, "message": None,
                "started_at": utc_now(), "updated_at": utc_now(),
            })
            self._active = job_id
        threading.Thread(target=self._run, args=(job_id, capture_id, replay_run_id), daemon=True).start()
        return self.get_job(job_id)

    def _run(self, job_id: str, capture_id: str, replay_run_id: str | None) -> None:
        job_dir = self._job_dir(job_id)
        phase_names = [name for name, _ in JOB_PHASES]
        weights = dict(JOB_PHASES)

        def progress(phase: str, phase_progress: float, message: str) -> None:
            index = phase_names.index(phase) if phase in phase_names else len(phase_names)
            done_weight = sum(weight for _, weight in JOB_PHASES[:index])
            overall = min(1.0, done_weight + weights.get(phase, 0.0) * phase_progress)
            self._write(job_dir, "running", phase=phase, phase_progress=phase_progress, overall_progress=round(overall, 4), message=message)

        try:
            result = self.service.analyze(capture_id, replay_run_id, progress=progress, cancel_requested=lambda: job_id in self._cancel)
            if result.get("cancelled"):
                self._write(job_dir, "cancelled", overall_progress=1.0, message="Cancelado de forma ordenada")
            else:
                self._write(job_dir, "completed", overall_progress=1.0, phase="COMPLETED", analysis_id=result["analysis_id"], result_summary=result["summary"])
        except Exception as error:
            self._write(job_dir, "failed", error=f"{type(error).__name__}:{error}")
        finally:
            with self._lock:
                if self._active == job_id:
                    self._active = None
                self._cancel.discard(job_id)

    def get_job(self, job_id: str) -> dict[str, Any]:
        job_path = self._job_dir(job_id) / "job.json"
        if not job_path.is_file():
            raise FileNotFoundError("PACKET_ANALYSIS_JOB_NOT_FOUND")
        return json.loads(job_path.read_text(encoding="utf-8"))

    def cancel_job(self, job_id: str) -> dict[str, Any]:
        job = self.get_job(job_id)
        if job.get("state") not in TERMINAL:
            with self._lock:
                self._cancel.add(job_id)
            self._write(self._job_dir(job_id), "cancel_requested")
        return self.get_job(job_id)

    def _write(self, job_dir: Path, state: str, **fields: Any) -> None:
        path = job_dir / "job.json"
        previous = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
        atomic_json(path, {**previous, **fields, "state": state, "updated_at": utc_now()})

    def _job_dir(self, job_id: str) -> Path:
        if not job_id.startswith("BLE-PKTLAB-JOB-") or any(part in job_id for part in ("/", "\\", "..")):
            raise ValueError("INVALID_JOB_ID")
        return self.jobs_root / job_id

    def get_analysis(self, capture_id: str, analysis_id: str) -> dict[str, Any]:
        analysis_dir = self.service.analysis_root / analysis_id
        manifest_path = analysis_dir / "analysis_manifest.json"
        if not manifest_path.is_file():
            raise FileNotFoundError("ANALYSIS_NOT_FOUND")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("capture_id") != capture_id:
            raise FileNotFoundError("ANALYSIS_DOES_NOT_BELONG_TO_CAPTURE")
        return {
            **manifest,
            "summary": json.loads((analysis_dir / "analysis_summary.json").read_text(encoding="utf-8")),
            "transmitters": json.loads((analysis_dir / "transmitter_catalog.json").read_text(encoding="utf-8"))["transmitters"],
            "packets": read_jsonl(analysis_dir / "packet_analysis.jsonl"),
            "windows_only_observations": read_jsonl(analysis_dir / "windows_observation_catalog.jsonl"),
            "sensor_views": read_jsonl(analysis_dir / "sensor_data_observations.jsonl"),
        }

    def latest_analysis_for_capture(self, capture_id: str) -> dict[str, Any]:
        candidates = []
        if not self.service.analysis_root.is_dir():
            raise FileNotFoundError("NO_ANALYSIS_FOR_CAPTURE")
        for analysis_dir in self.service.analysis_root.iterdir():
            manifest_path = analysis_dir / "analysis_manifest.json"
            if not manifest_path.is_file():
                continue
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if manifest.get("capture_id") == capture_id:
                candidates.append((analysis_dir.stat().st_mtime, manifest["analysis_id"]))
        if not candidates:
            raise FileNotFoundError("NO_ANALYSIS_FOR_CAPTURE")
        candidates.sort(reverse=True)
        return self.get_analysis(capture_id, candidates[0][1])
