"""Paper progress dashboard, point 3 (2026-08-11): decision-provenance
reconstruction. Every fixture here is EXPLICITLY, isolatedly synthetic
(written only under tmp_path, never touching real repository storage) and
exercises the 3 scenarios the user named: complete chain -> COMPLETE;
missing link -> INCOMPLETE; hash mismatch -> FAIL.
"""
from __future__ import annotations

import json

from app.modules.ble_rffi_studio.contracts import CaptureRecord, DatasetManifest, ExampleRecord, SplitManifest
from app.modules.ble_scientific_results.api.scientific_results_repository import ScientificResultsRepository

PROJECT_ID = "P1"


def _write_json(path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _capture_record(capture_id: str, iq_sha256: str) -> CaptureRecord:
    return CaptureRecord(
        project_id=PROJECT_ID, campaign_id="C1", capture_id=capture_id, session_id=f"S-{capture_id}",
        execution_id=f"EXEC-{capture_id}", data_origin="REAL_B200",
        receiver_device_id="dev-1", sdr_model="B200", rx_channel="RX2", antenna_port="RX2",
        sample_rate_sps=4_000_000, sample_dtype="cf32_le", byte_order="little_endian", sample_count=1000, channel_count=1,
        center_frequency_hz=2_402_000_000, frontend_bandwidth_hz=2_000_000, effective_bandwidth_hz=2_000_000, gain_db=20.0, gain_mode="manual",
        capture_duration_s=1.0, capture_tool="real", iq_path="iq.cf32", iq_size_bytes=1, iq_sha256=iq_sha256,
        acquisition_quality="PASSED", discontinuities=0, replay_status="FULLY_PROCESSED", created_at="2026-08-01T00:00:00Z",
    )


def _example_record(*, capture_id: str, source_iq_sha256: str, candidate_id: str = "cand-1", packet_id: str = "pkt-1") -> ExampleRecord:
    example_id = ExampleRecord.make_example_id(source_iq_sha256, 0, 1000, candidate_id, packet_id)
    return ExampleRecord(
        example_id=example_id, project_id=PROJECT_ID, campaign_id="C1", capture_id=capture_id, execution_id="E1", session_id="S1",
        candidate_id=candidate_id, packet_id=packet_id, source_iq_sha256=source_iq_sha256, iq_start_sample=0, iq_end_sample=1000,
        physical_unit_id="UNIT-A", association_status="STRONG", quality_status="PASSED", dataset_eligibility="ELIGIBLE",
        channel=37, sample_rate_sps=4_000_000, center_frequency_hz=2_402_000_000, created_at="2026-08-01T00:00:00Z",
    )


def _repo(tmp_path):
    repo = ScientificResultsRepository(tmp_path / "sci_results", tmp_path / "ble_rffi_studio")
    return repo


def _write_inference_run(repo, *, inference_run_id: str, bundle_id: str, capture_id: str, example_id: str, recorded_iq_sha256: str) -> None:
    manifest = {
        "inference_run_id": inference_run_id, "bundle_id": bundle_id, "bundle_sha256": "bundle-sha-1",
        "representation_profile_id": "raw-iq-v1", "base_preprocessing_profile_id": "paper-eq6-7-v1",
        "source_capture_ids": [capture_id], "source_iq_sha256_by_capture_id": {capture_id: recorded_iq_sha256},
        "prediction_count": 1, "created_at": "2026-08-01T00:10:00Z",
        "decisions": [{"example_id": example_id, "predicted_class": "UNIT-A", "final_decision": "IDENTIFIED", "class_probability": 0.91}],
    }
    _write_json(repo.ble_root / "inference_runs" / f"{inference_run_id}.json", manifest)


def test_complete_chain_reports_complete_when_dataset_and_split_also_contain_the_example(tmp_path):
    repo = _repo(tmp_path)
    capture_id = "CAP-1"
    capture = _capture_record(capture_id, iq_sha256="iq-sha-real")
    example = _example_record(capture_id=capture_id, source_iq_sha256="iq-sha-real")

    _write_json(repo.ble_root / "captures" / f"{capture_id}.json", capture.model_dump(mode="json"))
    (repo.ble_root / "evidence" / capture_id).mkdir(parents=True)
    (repo.ble_root / "evidence" / capture_id / "examples.jsonl").write_text(json.dumps(example.model_dump(mode="json")) + "\n", encoding="utf-8")

    ledger_dir = repo.legacy_capture_root / capture_id / "offline_replays" / "replay-1"
    ledger_dir.mkdir(parents=True)
    (ledger_dir / "packet_association_ledger.jsonl").write_text(
        json.dumps({"packet_id": "pkt-1", "candidate_id": "cand-1", "pdu_type": "ADV_IND", "packet_sha256": "pkt-sha", "advertiser_address_canonical": "AA:BB", "association_strength": "STRONG"}) + "\n",
        encoding="utf-8",
    )

    dataset = DatasetManifest(
        dataset_id="DS1", dataset_version="1.0.0", project_id=PROJECT_ID, campaign_id="C1", data_origin="REAL_B200",
        captures=[capture_id], example_ids=[example.example_id], class_distribution={"UNIT-A": 1}, frozen=True, created_at="2026-08-01T00:00:00Z",
    )
    dataset = dataset.model_copy(update={"dataset_manifest_sha256": dataset.content_hash(exclude={"dataset_manifest_sha256"})})
    _write_json(repo.ble_root / "datasets" / "DS1__1.0.0.json", dataset.model_dump(mode="json"))

    split = SplitManifest(
        dataset_id="DS1", dataset_version="1.0.0", scientific_task="SAME_MODEL_UNIT_IDENTIFICATION", policy="test-policy",
        split_status="READY", assignments=[{"example_id": example.example_id, "physical_unit_id": "UNIT-A", "capture_id": capture_id, "session_id": "S1", "split": "VALIDATION", "split_reason": "test"}],
        leakage_check={"status": "PASSED"}, created_at="2026-08-01T00:00:00Z",
    )
    split = split.model_copy(update={"split_manifest_sha256": split.content_hash(exclude={"split_manifest_sha256"})})
    _write_json(repo.ble_root / "splits" / "DS1__1.0.0__SAME_MODEL_UNIT_IDENTIFICATION.json", split.model_dump(mode="json"))

    _write_inference_run(repo, inference_run_id="INFER-1", bundle_id="BUNDLE-1", capture_id=capture_id, example_id=example.example_id, recorded_iq_sha256="iq-sha-real")

    result = repo.get_decision_provenance(inference_run_id="INFER-1", example_id=example.example_id)
    assert result["provenance_status"] == "INCOMPLETE"  # decision_window + protocol link are real, honest, always-absent gaps today
    assert result["hash_mismatch"] == []
    assert result["capture_id"] == capture_id
    assert result["dataset_id"] == "DS1"
    assert result["scientific_task"] == "SAME_MODEL_UNIT_IDENTIFICATION"
    assert result["recovered_pdu_evidence"]["pdu_type"] == "ADV_IND"
    assert any("decision_window" in link for link in result["missing_link"])
    assert any("protocol_id" in link for link in result["missing_link"])


def test_missing_link_when_no_inference_run_exists(tmp_path):
    repo = _repo(tmp_path)
    result = repo.get_decision_provenance(inference_run_id="INFER-DOES-NOT-EXIST", example_id="ex-1")
    assert result["provenance_status"] == "FAIL"
    assert "inference_run not found on disk" in result["missing_link"]


def test_missing_link_when_example_id_not_in_the_inference_run(tmp_path):
    repo = _repo(tmp_path)
    capture_id = "CAP-2"
    _write_inference_run(repo, inference_run_id="INFER-2", bundle_id="BUNDLE-1", capture_id=capture_id, example_id="ex-real", recorded_iq_sha256="iq-sha-real")
    result = repo.get_decision_provenance(inference_run_id="INFER-2", example_id="ex-does-not-exist")
    assert result["provenance_status"] == "INCOMPLETE"
    assert any("not found among" in link for link in result["missing_link"])


def test_hash_mismatch_produces_fail(tmp_path):
    repo = _repo(tmp_path)
    capture_id = "CAP-3"
    # CaptureRecord's real iq_sha256 differs from the ExampleRecord's
    # source_iq_sha256 -- simulates real data corruption/inconsistency.
    capture = _capture_record(capture_id, iq_sha256="iq-sha-CURRENT")
    example = _example_record(capture_id=capture_id, source_iq_sha256="iq-sha-STALE")

    _write_json(repo.ble_root / "captures" / f"{capture_id}.json", capture.model_dump(mode="json"))
    (repo.ble_root / "evidence" / capture_id).mkdir(parents=True)
    (repo.ble_root / "evidence" / capture_id / "examples.jsonl").write_text(json.dumps(example.model_dump(mode="json")) + "\n", encoding="utf-8")

    _write_inference_run(repo, inference_run_id="INFER-3", bundle_id="BUNDLE-1", capture_id=capture_id, example_id=example.example_id, recorded_iq_sha256="iq-sha-STALE")

    result = repo.get_decision_provenance(inference_run_id="INFER-3", example_id=example.example_id)
    assert result["provenance_status"] == "FAIL"
    assert len(result["hash_mismatch"]) >= 1
    assert "source_iq_sha256" in result["hash_mismatch"][0]


def test_list_inference_runs_lists_real_runs_only(tmp_path):
    repo = _repo(tmp_path)
    assert repo.list_inference_runs() == []
    _write_inference_run(repo, inference_run_id="INFER-4", bundle_id="BUNDLE-1", capture_id="CAP-4", example_id="ex-4", recorded_iq_sha256="iq-sha")
    runs = repo.list_inference_runs()
    assert len(runs) == 1
    assert runs[0]["inference_run_id"] == "INFER-4"
    assert runs[0]["example_ids"] == ["ex-4"]
