from __future__ import annotations

import json
import os
import sys
import threading
from pathlib import Path

import numpy as np
import pytest

from app.infrastructure.ble.capture.ble_offline_replay import BleOfflineReplayService, sha256_file

FIXTURES_DIR = Path(__file__).parent / "fixtures"
FAKE_DECODER = FIXTURES_DIR / "fake_ble_decode_worker.py"
# backend/app/tests/unit/test_x.py -> backend/, so _detect() (real, pure-numpy
# burst detector) resolves against the real repo tree. Only the GFSK decode
# step (backend/tools/ble_decode_burst_directory.py) is swapped for the fake.
BACKEND_ROOT = Path(__file__).resolve().parents[3]
SAMPLE_RATE = 4_000_000
BLOCK = 64


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def synthetic_iq_bytes(burst_count: int) -> bytes:
    """Silence/energy blocks laid out so detect_bursts() finds exactly
    burst_count separated groups: 5 silent blocks, 2 signal blocks, repeated,
    with 5 trailing silent blocks."""
    rng = np.random.default_rng(7)
    blocks = []
    for _ in range(burst_count):
        blocks.append(rng.normal(0, 1e-4, size=(5, BLOCK)) + 1j * rng.normal(0, 1e-4, size=(5, BLOCK)))
        blocks.append(np.full((2, BLOCK), 1.0 + 0.0j))
    blocks.append(rng.normal(0, 1e-4, size=(5, BLOCK)) + 1j * rng.normal(0, 1e-4, size=(5, BLOCK)))
    values = np.concatenate(blocks, axis=0).reshape(-1).astype(np.complex64)
    return values.tobytes()


def build_source(tmp_path: Path, burst_count: int, capture_id: str = "BLE-IQ-resumabletest") -> tuple[BleOfflineReplayService, str, str, str]:
    capture_root = tmp_path / "ble" / "iq_captures"
    session_root = tmp_path / "ble_lab" / "sessions"
    execution_id = "BLE-HYBRID-resumabletest"
    capture_dir = capture_root / capture_id
    capture_dir.mkdir(parents=True)
    data = capture_dir / f"{capture_id}.sigmf-data"
    data.write_bytes(synthetic_iq_bytes(burst_count))
    digest = sha256_file(data)
    manifest = {
        "capture_id": capture_id,
        "data_path": data.name,
        "data_sha256": digest,
        "actual_samples": len(data.read_bytes()) // 8,
        "actual_size_bytes": data.stat().st_size,
        "sample_format": "cf32_le",
        "sample_rate_sps": SAMPLE_RATE,
        "center_frequency_hz": 2_402_000_000,
        "bandwidth_hz": 2_000_000,
        "ble_channel": 37,
        "hash_status": "VERIFIED",
        "metadata_status": "COMPLETE",
        "overflow_count": 0,
        "discontinuity_count": 0,
        "short_read_count": 0,
        "write_error_count": 0,
        "experimental_metadata": {
            "campaign_id": "BLE-RFFI-CC2650-UNIT-01-CH37-v1",
            "condition_id": "C001",
            "session_id": "S001-POS",
            "execution_purpose": "POSITIVE_PILOT",
            "source_working_tree_status": "CLEAN",
            "preflight_valid_at_capture_start": True,
        },
    }
    write_json(capture_dir / "capture_manifest.json", manifest)
    write_json(session_root / execution_id / "session_manifest.json", {
        "session_id": execution_id,
        "capture_id": capture_id,
        "target_address": "B0:B4:48:C0:36:06",
        "native_scan_path": str(tmp_path / "ble" / "native" / "scans" / execution_id),
        "experimental_metadata": manifest["experimental_metadata"],
    })
    service = BleOfflineReplayService(capture_root, session_root=session_root, backend_root=BACKEND_ROOT)
    service.decode_tool = FAKE_DECODER
    service.python_executable = Path(sys.executable)
    return service, capture_id, execution_id, digest


def candidate_index_map(service: BleOfflineReplayService, capture_id: str, replay_run_id: str) -> dict[str, dict]:
    replay_dir = service._capture_dir(capture_id) / "offline_replays" / replay_run_id
    rows = [json.loads(line) for line in (replay_dir / "candidate_manifest.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    return {row["candidate_id"]: row for row in rows}


@pytest.fixture(autouse=True)
def _isolate_control_file(monkeypatch, tmp_path):
    monkeypatch.delenv("FAKE_DECODER_CONTROL_PATH", raising=False)
    yield


def set_control(tmp_path: Path, spec: dict) -> None:
    control_path = tmp_path / "decoder_control.json"
    write_json(control_path, spec)
    os.environ["FAKE_DECODER_CONTROL_PATH"] = str(control_path)


def test_replay_processes_all_candidates_and_checkpoints(tmp_path):
    service, capture_id, execution_id, digest = build_source(tmp_path, burst_count=4)
    set_control(tmp_path, {})
    result = service.create(capture_id, {"execution_id": execution_id, "expected_iq_sha256": digest, "batch_size": 2, "job_time_budget_seconds": 30})
    assert result["execution_status"] == "FULLY_PROCESSED"
    assert result["scientific_completion_status"] == "COMPLETE"
    assert result["coverage"]["pending_segments"] == 0
    assert result["coverage"]["total_candidate_segments"] == 4
    candidates = candidate_index_map(service, capture_id, result["replay_run_id"])
    assert len(candidates) == 4
    assert all(row["processing_status"] == "PROCESSED" for row in candidates.values())


def test_resume_continues_from_checkpoint_without_reprocessing_and_matches_full_run(tmp_path):
    service, capture_id, execution_id, digest = build_source(tmp_path, burst_count=6)
    set_control(tmp_path, {f"burst-{i:06d}.cf32": {"sleep_seconds": 0.2, "confirmed_packets": 1 if i % 2 == 0 else 0} for i in range(1, 7)})

    partial = service.create(capture_id, {"execution_id": execution_id, "expected_iq_sha256": digest, "batch_size": 6, "batch_timeout_seconds": 30, "job_time_budget_seconds": 0.5})
    assert partial["execution_status"] == "PARTIAL"
    assert partial["resume_available"] is True
    assert 0 < partial["coverage"]["processed_segments"] < 6

    resumed = service.create(capture_id, {"execution_id": execution_id, "expected_iq_sha256": digest, "replay_run_id": partial["replay_run_id"], "batch_size": 6, "batch_timeout_seconds": 30, "job_time_budget_seconds": 30})
    assert resumed["execution_status"] == "FULLY_PROCESSED"
    assert resumed["coverage"]["pending_segments"] == 0
    assert resumed["coverage"]["processed_segments"] == 6

    straight = service.create(capture_id, {"execution_id": execution_id, "expected_iq_sha256": digest, "batch_size": 6, "batch_timeout_seconds": 30, "job_time_budget_seconds": 30})
    resumed_candidates = candidate_index_map(service, capture_id, resumed["replay_run_id"])
    straight_candidates = candidate_index_map(service, capture_id, straight["replay_run_id"])
    resumed_shape = sorted((row["start_sample"], row["end_sample"], row["crc_status"], (row["decoder_result"] or {}).get("confirmed_packets")) for row in resumed_candidates.values())
    straight_shape = sorted((row["start_sample"], row["end_sample"], row["crc_status"], (row["decoder_result"] or {}).get("confirmed_packets")) for row in straight_candidates.values())
    assert resumed_shape == straight_shape

    packet_ids = [row["packet_id"] for row in resumed["target_association_results"]["packet_association_ledger"]]
    assert len(packet_ids) == len(set(packet_ids))


def test_resume_rejects_when_source_iq_sha_changes(tmp_path):
    service, capture_id, execution_id, digest = build_source(tmp_path, burst_count=3)
    set_control(tmp_path, {})
    partial = service.create(capture_id, {"execution_id": execution_id, "expected_iq_sha256": digest, "batch_size": 1, "job_time_budget_seconds": 0.001})
    data_path = service._capture_dir(capture_id) / f"{capture_id}.sigmf-data"
    manifest_path = service._capture_dir(capture_id) / "capture_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    data_path.write_bytes(synthetic_iq_bytes(5))
    manifest["data_sha256"] = sha256_file(data_path)
    manifest["actual_samples"] = len(data_path.read_bytes()) // 8
    write_json(manifest_path, manifest)
    with pytest.raises(ValueError, match="REPLAY_RESUME_CONFIGURATION_CHANGED:source_iq_sha256"):
        service.create(capture_id, {"execution_id": execution_id, "replay_run_id": partial["replay_run_id"]})


def test_resume_rejects_when_analysis_configuration_changes(tmp_path):
    service, capture_id, execution_id, digest = build_source(tmp_path, burst_count=3)
    set_control(tmp_path, {})
    partial = service.create(capture_id, {"execution_id": execution_id, "expected_iq_sha256": digest, "batch_size": 1, "job_time_budget_seconds": 0.001})
    replay_dir = service._capture_dir(capture_id) / "offline_replays" / partial["replay_run_id"]
    state_path = replay_dir / "replay_state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["analysis_configuration_id"] = "ble-rffi-offline-detector-decoder-replay-v2-changed"
    write_json(state_path, state)
    with pytest.raises(ValueError, match="REPLAY_RESUME_CONFIGURATION_CHANGED:analysis_configuration_id"):
        service.create(capture_id, {"execution_id": execution_id, "replay_run_id": partial["replay_run_id"]})


def test_single_slow_candidate_times_out_without_blocking_the_rest(tmp_path):
    service, capture_id, execution_id, digest = build_source(tmp_path, burst_count=5)
    set_control(tmp_path, {"burst-000003.cf32": {"sleep_seconds": 5.0}})
    result = service.create(capture_id, {
        "execution_id": execution_id, "expected_iq_sha256": digest,
        "batch_size": 5, "batch_timeout_seconds": 0.6, "per_candidate_timeout_seconds": 0.3,
        "job_time_budget_seconds": 30,
    })
    assert result["execution_status"] == "COMPLETED_WITH_FAILED_SEGMENTS"
    assert result["scientific_completion_status"] == "COMPLETE"
    assert result["coverage"]["pending_segments"] == 0
    assert result["coverage"]["failed_segments"] == 1
    candidates = candidate_index_map(service, capture_id, result["replay_run_id"])
    statuses = {row["candidate_index"]: row["processing_status"] for row in candidates.values()}
    assert statuses[2] == "FAILED_TIMEOUT"
    assert sum(1 for status in statuses.values() if status == "PROCESSED") == 4
    assert result["candidate_funnel"]["decoder_timeout_count"] == 1


def test_ordered_cancellation_preserves_checkpoint_and_can_resume(tmp_path):
    service, capture_id, execution_id, digest = build_source(tmp_path, burst_count=6)
    set_control(tmp_path, {f"burst-{i:06d}.cf32": {"confirmed_packets": 0} for i in range(1, 7)})
    cancel_event = threading.Event()

    def checkpoint_hook(coverage):
        if coverage["processed_segments"] >= 2:
            cancel_event.set()

    result = service.create(
        capture_id, {"execution_id": execution_id, "expected_iq_sha256": digest, "batch_size": 1, "job_time_budget_seconds": 30},
        cancel_requested=cancel_event.is_set, checkpoint_hook=checkpoint_hook,
    )
    assert result["execution_status"] == "CANCELLED_WITH_CHECKPOINT"
    assert result["termination_reason"] == "OPERATOR_CANCELLED"
    assert result["resume_available"] is True
    assert result["scientific_completion_status"] == "INCOMPLETE"
    assert "DECODER_REPLAY_CANCELLED_BY_OPERATOR" in result["decision"]["reason_codes"]
    assert result["decision"]["dataset_eligibility_status"] == "NOT_ELIGIBLE"

    resumed = service.create(capture_id, {"execution_id": execution_id, "expected_iq_sha256": digest, "replay_run_id": result["replay_run_id"], "batch_size": 6, "job_time_budget_seconds": 30})
    assert resumed["execution_status"] == "FULLY_PROCESSED"
    assert resumed["coverage"]["pending_segments"] == 0


def test_resume_migrates_legacy_pre_checkpoint_run_without_redecoding(tmp_path):
    """Reproduces the exact shape of a replay started before the resumable
    engine existed: burst_candidates.jsonl + decoded/batch_summary.json exist,
    but replay_state.json/candidate_manifest.jsonl do not. Resuming it must
    bootstrap checkpoint state from those legacy artifacts and continue from
    where the old single-shot run stopped, not from candidate 0."""
    service, capture_id, execution_id, digest = build_source(tmp_path, burst_count=5)
    set_control(tmp_path, {f"burst-{i:06d}.cf32": {"confirmed_packets": 1} for i in range(1, 6)})
    fresh = service.create(capture_id, {"execution_id": execution_id, "expected_iq_sha256": digest, "batch_size": 5, "job_time_budget_seconds": 30})
    assert fresh["coverage"]["processed_segments"] == 5
    assert fresh["candidate_funnel"]["crc_valid_packets"] == 5

    replay_dir = service._capture_dir(capture_id) / "offline_replays" / fresh["replay_run_id"]
    legacy_processed = 3
    legacy_attempts = [
        {"iq_segment": f"burst-{i:06d}.cf32", "confirmed_packets": 1, "semantic_packets": 1}
        for i in range(1, legacy_processed + 1)
    ]
    write_json(replay_dir / "decoded" / "batch_summary.json", {"segments": legacy_processed, "start_index": 0, "end_index": None, "attempts": legacy_attempts, "partial": True})
    kept_decoded = [json.loads(l) for l in (replay_dir / "decoded" / "decoded_packets.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    kept_decoded = [row for row in kept_decoded if row.get("iq_segment") in {a["iq_segment"] for a in legacy_attempts}]
    (replay_dir / "decoded" / "decoded_packets.jsonl").write_text("".join(json.dumps(r) + "\n" for r in kept_decoded), encoding="utf-8")
    (replay_dir / "candidate_manifest.jsonl").unlink()
    (replay_dir / "replay_state.json").unlink()

    migrated = service.create(capture_id, {"execution_id": execution_id, "replay_run_id": fresh["replay_run_id"], "batch_size": 5, "job_time_budget_seconds": 30})
    assert migrated["execution_status"] == "FULLY_PROCESSED"
    assert migrated["coverage"]["processed_segments"] == 5
    assert migrated["coverage"]["pending_segments"] == 0
    assert migrated["candidate_funnel"]["crc_valid_packets"] == 5
    assert migrated["candidate_funnel"]["unique_crc_valid_packets"] == 5
    candidates = candidate_index_map(service, capture_id, fresh["replay_run_id"])
    assert len(candidates) == 5
    assert all(row["processing_status"] == "PROCESSED" for row in candidates.values())
    packet_ids = [row["packet_id"] for row in migrated["target_association_results"]["packet_association_ledger"]]
    assert len(packet_ids) == 5 == len(set(packet_ids))


def test_multiple_packets_from_one_candidate_get_distinct_packet_ids(tmp_path):
    """Regression test for a real bug found via live verification: two
    confirmed packets decoded from the SAME merged candidate collapsed onto
    the same packet_id whenever their payload hash was unavailable, because
    packet_id was computed from the candidate's start_sample (identical for
    both) instead of each packet's own position. Even with an empty payload
    (the exact precondition that triggered the real collision), the two
    packets must still get distinct identities via packet_start_bit."""
    service, capture_id, execution_id, digest = build_source(tmp_path, burst_count=1)
    set_control(tmp_path, {"burst-000001.cf32": {"confirmed_packets": 2, "payload_hex": ""}})
    result = service.create(capture_id, {"execution_id": execution_id, "expected_iq_sha256": digest, "batch_size": 1, "job_time_budget_seconds": 30})
    ledger = result["target_association_results"]["packet_association_ledger"]
    assert len(ledger) == 2
    packet_ids = [row["packet_id"] for row in ledger]
    assert len(set(packet_ids)) == 2, f"packet_ids collided: {packet_ids}"
    start_samples = [row["packet_start_sample"] for row in ledger]
    assert len(set(start_samples)) == 2


def test_association_ledger_pdu_and_address_fields_are_populated(tmp_path):
    """Regression test for a real bug found via live verification: the
    semantic_packets.jsonl join used the wrong key (source_packet_sha256
    instead of the semantic row's own packet_id), so it matched 0/539 rows on
    the real capture and every pdu_type/tx_add/rx_add/address_raw field was
    silently None."""
    service, capture_id, execution_id, digest = build_source(tmp_path, burst_count=1)
    set_control(tmp_path, {"burst-000001.cf32": {"confirmed_packets": 1, "pdu_type_name": "ADV_IND", "address_raw_air_octets": "0698765432B0"}})
    result = service.create(capture_id, {"execution_id": execution_id, "expected_iq_sha256": digest, "batch_size": 1, "job_time_budget_seconds": 30})
    row = result["target_association_results"]["packet_association_ledger"][0]
    assert row["pdu_type"] == "ADV_IND"
    assert row["tx_add"] == 0
    assert row["rx_add"] == 0
    assert row["advertiser_address_raw"] == "0698765432B0"


def test_pending_segments_required_before_global_decision(tmp_path):
    service, capture_id, execution_id, digest = build_source(tmp_path, burst_count=4)
    set_control(tmp_path, {f"burst-{i:06d}.cf32": {"sleep_seconds": 0.5} for i in range(1, 5)})
    partial = service.create(capture_id, {"execution_id": execution_id, "expected_iq_sha256": digest, "batch_size": 1, "job_time_budget_seconds": 0.001})
    assert partial["coverage"]["pending_segments"] > 0
    assert partial["decision"]["dataset_eligibility_status"] == "NOT_ELIGIBLE"
    assert partial["decision"]["scientific_decision"] == "INCOMPLETE_REPLAY"
    assert partial["decision_scope"] == "PROCESSED_SUBSET_ONLY"

    complete = service.create(capture_id, {"execution_id": execution_id, "expected_iq_sha256": digest, "replay_run_id": partial["replay_run_id"], "batch_size": 4, "job_time_budget_seconds": 30})
    assert complete["coverage"]["pending_segments"] == 0
    assert complete["decision_scope"] == "FULL_CAPTURE"
    assert "DECODER_REPLAY_INCOMPLETE" not in complete["decision"]["reason_codes"]
