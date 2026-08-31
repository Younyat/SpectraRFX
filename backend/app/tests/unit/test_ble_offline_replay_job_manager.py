from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import numpy as np
import pytest

import app.infrastructure.ble.capture.ble_capture_job_manager as job_manager_module
from app.infrastructure.ble.capture.ble_capture_job_manager import BleCaptureJobManager
from app.infrastructure.ble.capture.ble_offline_replay import BleOfflineReplayService as RealReplayService
from app.infrastructure.ble.capture.ble_offline_replay import sha256_file

FIXTURES_DIR = Path(__file__).parent / "fixtures"
FAKE_DECODER = FIXTURES_DIR / "fake_ble_decode_worker.py"
BACKEND_ROOT = Path(__file__).resolve().parents[3]
SAMPLE_RATE = 4_000_000
BLOCK = 64


class FakeDevices:
    def list_devices(self):
        return {"available": True, "devices": [], "reason_code": None}

    def private_args(self, device_id):
        raise ValueError("UNUSED_IN_THESE_TESTS")


class FakeCapture:
    def capture(self, request_path, output, cancel):
        raise AssertionError("offline-replay tests must never trigger a new capture")


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def synthetic_iq_bytes(burst_count: int) -> bytes:
    rng = np.random.default_rng(11)
    blocks = []
    for _ in range(burst_count):
        blocks.append(rng.normal(0, 1e-4, size=(5, BLOCK)) + 1j * rng.normal(0, 1e-4, size=(5, BLOCK)))
        blocks.append(np.full((2, BLOCK), 1.0 + 0.0j))
    blocks.append(rng.normal(0, 1e-4, size=(5, BLOCK)) + 1j * rng.normal(0, 1e-4, size=(5, BLOCK)))
    values = np.concatenate(blocks, axis=0).reshape(-1).astype(np.complex64)
    return values.tobytes()


@pytest.fixture()
def rig(tmp_path, monkeypatch):
    monkeypatch.delenv("FAKE_DECODER_CONTROL_PATH", raising=False)

    class ConfiguredReplayService(RealReplayService):
        def __init__(self, root):
            super().__init__(root, backend_root=BACKEND_ROOT)
            self.decode_tool = FAKE_DECODER
            self.python_executable = Path(sys.executable)

    monkeypatch.setattr(job_manager_module, "BleOfflineReplayService", ConfiguredReplayService)

    root = tmp_path / "ble" / "iq_captures"
    session_root = tmp_path / "ble_lab" / "sessions"
    capture_id = "BLE-IQ-jobmanagertest"
    execution_id = "BLE-HYBRID-jobmanagertest"
    capture_dir = root / capture_id
    capture_dir.mkdir(parents=True)
    burst_count = 5
    data = capture_dir / f"{capture_id}.sigmf-data"
    data.write_bytes(synthetic_iq_bytes(burst_count))
    digest = sha256_file(data)
    manifest = {
        "capture_id": capture_id, "data_path": data.name, "data_sha256": digest,
        "actual_samples": len(data.read_bytes()) // 8, "actual_size_bytes": data.stat().st_size,
        "sample_format": "cf32_le", "sample_rate_sps": SAMPLE_RATE, "center_frequency_hz": 2_402_000_000,
        "bandwidth_hz": 2_000_000, "ble_channel": 37, "hash_status": "VERIFIED", "metadata_status": "COMPLETE",
        "overflow_count": 0, "discontinuity_count": 0, "short_read_count": 0, "write_error_count": 0,
        "experimental_metadata": {"source_working_tree_status": "CLEAN", "preflight_valid_at_capture_start": True},
    }
    write_json(capture_dir / "capture_manifest.json", manifest)
    write_json(session_root / execution_id / "session_manifest.json", {
        "session_id": execution_id, "capture_id": capture_id, "target_address": "B0:B4:48:C0:36:06",
        "native_scan_path": str(tmp_path / "ble" / "native" / "scans" / execution_id),
    })
    # BleCaptureJobManager expects capture jobs under its own root; offline
    # replay reuses the same root for its "recordings" tree.
    manager = BleCaptureJobManager(root, FakeDevices(), FakeCapture(), enabled=True, minimum_free_bytes=0)
    return manager, capture_id, execution_id, digest, session_root


def set_control(tmp_path: Path, spec: dict) -> None:
    control_path = tmp_path / "decoder_control.json"
    write_json(control_path, spec)
    os.environ["FAKE_DECODER_CONTROL_PATH"] = str(control_path)


def poll_job_until_completed(manager, capture_id, replay_run_id, timeout_s=30.0, interval_s=0.02):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            job = manager.offline_replay_job(capture_id, replay_run_id)
        except PermissionError:
            # Windows can transiently deny a read that races the writer's
            # os.replace() during this test's tight polling interval; a real
            # client polls far less often and never observes this.
            time.sleep(interval_s)
            continue
        if job["state"] == "completed":
            return job
        time.sleep(interval_s)
    raise AssertionError("job did not complete in time")


def test_job_status_never_reports_stale_result_while_a_resume_is_running(rig, tmp_path):
    manager, capture_id, execution_id, digest, _ = rig
    set_control(tmp_path, {f"burst-{i:06d}.cf32": {"confirmed_packets": 0} for i in range(1, 6)})

    first = manager.start_offline_replay(capture_id, {"execution_id": execution_id, "expected_iq_sha256": digest, "batch_size": 5, "job_time_budget_seconds": 30})
    finished = poll_job_until_completed(manager, capture_id, first["replay_run_id"])
    assert finished["result"]["coverage"]["pending_segments"] == 0
    stale_completed_at = finished["result"]["completed_at"]

    # Now resume the SAME replay_run_id with a much slower decoder. Immediately
    # after queuing, the job must NOT report the old (already-terminal)
    # replay_summary.json as if it were this new attempt's result.
    set_control(tmp_path, {f"burst-{i:06d}.cf32": {"sleep_seconds": 0.4, "confirmed_packets": 0} for i in range(1, 6)})
    resumed = manager.start_offline_replay(capture_id, {"execution_id": execution_id, "replay_run_id": first["replay_run_id"], "batch_size": 5, "job_time_budget_seconds": 30})
    assert resumed["state"] in {"queued", "running"}
    immediate = manager.offline_replay_job(capture_id, first["replay_run_id"])
    assert immediate["state"] != "completed", "must not report the job as completed before the resumed attempt has actually run"
    if "result" in immediate:
        assert immediate["result"]["completed_at"] != stale_completed_at or immediate["state"] not in {"completed"}

    final = poll_job_until_completed(manager, capture_id, first["replay_run_id"], timeout_s=30.0)
    assert final["result"]["completed_at"] != stale_completed_at
    assert final["result"]["coverage"]["pending_segments"] == 0


def test_legacy_run_without_checkpoint_state_can_be_resumed_via_job_manager(rig, tmp_path):
    manager, capture_id, execution_id, digest, _ = rig
    set_control(tmp_path, {f"burst-{i:06d}.cf32": {"confirmed_packets": 1} for i in range(1, 6)})

    fresh = manager.start_offline_replay(capture_id, {"execution_id": execution_id, "expected_iq_sha256": digest, "batch_size": 5, "job_time_budget_seconds": 30})
    finished = poll_job_until_completed(manager, capture_id, fresh["replay_run_id"])
    assert finished["result"]["coverage"]["processed_segments"] == 5

    replay_dir = manager._offline_replay_dir(capture_id, fresh["replay_run_id"])
    (replay_dir / "candidate_manifest.jsonl").unlink()
    (replay_dir / "replay_state.json").unlink()
    (replay_dir / "job.json").unlink()

    resumed = manager.start_offline_replay(capture_id, {"execution_id": execution_id, "replay_run_id": fresh["replay_run_id"], "batch_size": 5, "job_time_budget_seconds": 30})
    final = poll_job_until_completed(manager, capture_id, resumed["replay_run_id"])
    assert final["result"]["execution_status"] == "FULLY_PROCESSED"
    assert final["result"]["coverage"]["pending_segments"] == 0
    assert final["result"]["candidate_funnel"]["crc_valid_packets"] == 5
