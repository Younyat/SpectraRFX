"""Synthetic construction helpers for ble_scientific_results tests -- builds
a minimal, valid ble_rffi_studio-shaped storage tree (captures/, evidence/,
datasets/, splits/, quality_reports/) using the SAME contract classes real
ble_rffi_studio code uses, so this module's preflight logic is exercised
against schema-correct fixtures without depending on any real capture. IDs
and IQ content are made-up (a tiny real file is still written to disk so the
integrity check's file-existence check has something real to find).
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from app.modules.ble_rffi_studio.contracts import (
    CaptureRecord,
    DatasetManifest,
    DatasetQualityReport,
    ExactDuplicatesResult,
    ExampleRecord,
    LeakageCheckResult,
    NearDuplicateResult,
    SampleOverlapResult,
    SplitAssignment,
    SplitManifest,
)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(record, sort_keys=True) for record in records) + ("\n" if records else ""), encoding="utf-8")


def write_capture(ble_root: Path, *, capture_id: str, session_id: str, sample_count: int = 40_000_000, physical_unit_id: str | None = None) -> CaptureRecord:
    # Same layout StudioRepository.resolve_iq_path() expects in production:
    # CaptureRecord.iq_path is a bare filename, resolved against
    # legacy_capture_root/<capture_id>/<iq_path> -- ble_root.parent here
    # matches ScientificResultsRepository's own default
    # (ble_rffi_studio_root.parent / "ble" / "iq_captures").
    filename = f"{capture_id}.cf32"
    legacy_capture_root = ble_root.parent / "ble" / "iq_captures"
    iq_path = legacy_capture_root / capture_id / filename
    iq_path.parent.mkdir(parents=True, exist_ok=True)
    payload = b"\x00" * 64
    iq_path.write_bytes(payload)
    capture = CaptureRecord(
        project_id="SCI-RESULTS-TEST-PROJECT", campaign_id="SCI-RESULTS-TEST-CAMPAIGN", capture_id=capture_id,
        session_id=session_id, execution_id=f"{capture_id}-EXEC", data_origin="SYNTHETIC_TEST_ONLY",
        physical_unit_id=physical_unit_id, capture_purpose="TARGET_DEVICE_ON" if physical_unit_id else "BACKGROUND_GENERAL",
        receiver_device_id="SYN-RX-01", sdr_model="USRP_B200_SYNTHETIC", rx_channel="RX2", antenna_port="RX2",
        sample_rate_sps=4_000_000, sample_dtype="cf32", byte_order="LE", sample_count=sample_count, channel_count=1,
        center_frequency_hz=2_402_000_000, frontend_bandwidth_hz=2_000_000, effective_bandwidth_hz=2_000_000,
        gain_db=20.0, gain_mode="MANUAL", capture_duration_s=10.0, capture_tool="synthetic-test-fixture",
        iq_path=filename, iq_size_bytes=len(payload), iq_sha256=hashlib.sha256(payload).hexdigest(),
        acquisition_quality="PASSED", created_at="2026-08-01T00:00:00Z",
    )
    _write_json(ble_root / "captures" / f"{capture_id}.json", capture.model_dump(mode="json"))
    return capture


def write_examples(ble_root: Path, capture: CaptureRecord, examples: list[ExampleRecord]) -> None:
    _write_jsonl(ble_root / "evidence" / capture.capture_id / "examples.jsonl", [example.model_dump(mode="json") for example in examples])


def make_example(*, capture: CaptureRecord, index: int, physical_unit_id: str | None, association_status: str = "PHYSICAL_ISOLATION_DECLARED", capture_purpose: str | None = None) -> ExampleRecord:
    start = index * 1000
    end = start + 800
    candidate_id = f"cand-{capture.capture_id}-{index}"
    packet_id = f"pkt-{capture.capture_id}-{index}"
    example_id = ExampleRecord.make_example_id(capture.iq_sha256, start, end, candidate_id, packet_id)
    return ExampleRecord(
        example_id=example_id, project_id=capture.project_id, campaign_id=capture.campaign_id, capture_id=capture.capture_id,
        execution_id=capture.execution_id, session_id=capture.session_id, candidate_id=candidate_id, packet_id=packet_id,
        source_iq_sha256=capture.iq_sha256, iq_start_sample=start, iq_end_sample=end, physical_unit_id=physical_unit_id,
        logical_transmitter_id=f"TX-{physical_unit_id}" if physical_unit_id else None,
        capture_purpose=capture_purpose if capture_purpose is not None else capture.capture_purpose,
        association_status=association_status, quality_status="PASSED", dataset_eligibility="PENDING_ANALYSIS",
        channel=37, sample_rate_sps=capture.sample_rate_sps, center_frequency_hz=capture.center_frequency_hz, created_at="2026-08-01T00:00:00Z",
    )


def write_frozen_dataset(ble_root: Path, *, dataset_id: str, dataset_version: str, physical_units: list[str], captures: list[str], example_ids: list[str], class_distribution: dict[str, int]) -> DatasetManifest:
    draft = DatasetManifest(
        dataset_id=dataset_id, dataset_version=dataset_version, project_id="SCI-RESULTS-TEST-PROJECT",
        campaign_id="SCI-RESULTS-TEST-CAMPAIGN", data_origin="SYNTHETIC_TEST_ONLY", physical_units=physical_units,
        captures=captures, sessions=captures, example_ids=example_ids, class_distribution=class_distribution,
        creation_policy={"source_captures": captures}, frozen=False, created_at="2026-08-01T00:00:00Z",
    )
    sha256 = draft.content_hash(exclude={"frozen", "dataset_manifest_sha256"})
    frozen = draft.model_copy(update={"frozen": True, "dataset_manifest_sha256": sha256})
    _write_json(ble_root / "datasets" / f"{dataset_id}__{dataset_version}.json", frozen.model_dump(mode="json"))
    return frozen


def write_ready_split(ble_root: Path, *, dataset: DatasetManifest, scientific_task: str, example_ids: list[str]) -> SplitManifest:
    assignments = [
        SplitAssignment(example_id=example_id, physical_unit_id=None, capture_id=f"cap-for-{example_id}", session_id=f"session-for-{example_id}", split="TRAIN", split_reason="synthetic fixture")
        for example_id in example_ids
    ]
    draft = SplitManifest(
        dataset_id=dataset.dataset_id, dataset_version=dataset.dataset_version, scientific_task=scientific_task,
        policy="synthetic-test-policy", split_status="READY", assignments=assignments,
        leakage_check=LeakageCheckResult(status="PASSED", checked_group_fields=["capture_id", "execution_id", "session_id", "candidate_id", "packet_id"]),
        created_at="2026-08-01T00:00:00Z",
    )
    sha256 = draft.content_hash(exclude={"split_manifest_sha256", "split_purpose", "non_confirmatory"})
    frozen = draft.model_copy(update={"split_manifest_sha256": sha256})
    _write_json(ble_root / "splits" / f"{dataset.dataset_id}__{dataset.dataset_version}__{scientific_task}.json", frozen.model_dump(mode="json"))
    return frozen


def write_not_feasible_split(ble_root: Path, *, dataset: DatasetManifest, scientific_task: str) -> SplitManifest:
    draft = SplitManifest(
        dataset_id=dataset.dataset_id, dataset_version=dataset.dataset_version, scientific_task=scientific_task,
        policy="synthetic-test-policy", split_status="NOT_FEASIBLE",
        infeasibility_reason="Leakage check failed on field(s): ['capture_id', 'execution_id', 'session_id']",
        assignments=[], leakage_check=LeakageCheckResult(status="FAILED", checked_group_fields=["capture_id", "execution_id", "session_id"], overlapping_keys={"capture_id": ["cap-1"]}),
        created_at="2026-08-01T00:00:00Z",
    )
    sha256 = draft.content_hash(exclude={"split_manifest_sha256", "split_purpose", "non_confirmatory"})
    frozen = draft.model_copy(update={"split_manifest_sha256": sha256})
    _write_json(ble_root / "splits" / f"{dataset.dataset_id}__{dataset.dataset_version}__{scientific_task}.json", frozen.model_dump(mode="json"))
    return frozen


def write_quality_report(ble_root: Path, *, dataset: DatasetManifest, gate_decision: str = "ACCEPTED_FOR_TRAINING") -> DatasetQualityReport:
    report = DatasetQualityReport(
        dataset_id=dataset.dataset_id, dataset_version=dataset.dataset_version,
        exact_duplicates=ExactDuplicatesResult(status="PASSED"), sample_overlap=SampleOverlapResult(status="PASSED"),
        near_duplicates=NearDuplicateResult(status="NOT_EXECUTED"), gate_decision=gate_decision,
        gate_reasons=[] if gate_decision == "ACCEPTED_FOR_TRAINING" else ["synthetic test forces rejection"],
        created_at="2026-08-01T00:00:00Z",
    )
    _write_json(ble_root / "quality_reports" / f"{dataset.dataset_id}__{dataset.dataset_version}.json", report.model_dump(mode="json"))
    return report


def write_replay_artifacts(
    ble_root: Path, *, capture_id: str, replay_run_id: str = "REPLAY-01",
    candidates: list[dict] | None = None, ledger_rows: list[dict] | None = None,
) -> Path:
    """Writes candidate_manifest.jsonl + packet_association_ledger.jsonl +
    replay_summary.json under the REAL layout
    legacy_capture_root/<capture_id>/offline_replays/<replay_run_id>/ --
    verified this session against real on-disk replay output (field names
    match exactly: candidate_id/start_sample/end_sample/processing_status/
    crc_status for candidates; packet_id/candidate_id/pdu_type/
    advertiser_address_canonical/association_strength/
    association_rejection_reason/time_delta_ms for ledger rows).
    replay_summary.json's mere presence is what BleCaptureLocator.
    resolve_replay_dir() uses to recognize a completed replay directory."""
    legacy_capture_root = ble_root.parent / "ble" / "iq_captures"
    replay_dir = legacy_capture_root / capture_id / "offline_replays" / replay_run_id
    replay_dir.mkdir(parents=True, exist_ok=True)

    _write_jsonl(replay_dir / "candidate_manifest.jsonl", candidates or [])
    _write_jsonl(replay_dir / "packet_association_ledger.jsonl", ledger_rows or [])
    _write_json(replay_dir / "replay_summary.json", {"schema_version": "test", "capture_id": capture_id})
    _write_json(replay_dir / "replay_final_report.json", {
        "capture_id": capture_id, "source_acquisition_quality": {"overflow_count": 0, "discontinuity_count": 0, "short_read_count": 0, "hash_status": "MATCH"},
    })
    return replay_dir


def make_candidate(*, index: int, capture_id: str, processing_status: str = "PROCESSED", crc_status: str = "VALID", samples_per_burst: int = 800) -> dict:
    start = index * 1000
    return {
        "candidate_id": f"cand-{capture_id}-{index}", "candidate_index": index, "burst_id": f"burst-{capture_id}-{index:06d}",
        "start_sample": start, "end_sample": start + samples_per_burst, "duration_samples": samples_per_burst,
        "mean_power_dbfs": -30.0, "peak_power_dbfs": -28.0, "iq_segment_path": f"iq_bursts/burst-{index:06d}.cf32",
        "iq_segment_sha256": f"sha-{capture_id}-{index}", "processing_status": processing_status, "attempt_count": 1,
        "processing_duration_ms": 1.0, "rejection_reason": None, "crc_status": crc_status,
    }


def make_ledger_row(*, candidate_id: str, association_strength: str = "STRONG", association_rejection_reason: str | None = None, time_delta_ms: float | None = 12.5, target_address_match: bool = True) -> dict:
    return {
        "packet_id": f"pkt-{candidate_id}", "candidate_id": candidate_id, "packet_sha256": f"sha-{candidate_id}",
        "packet_start_sample": 0, "rf_timestamp_utc": None, "pdu_type": "ADV_IND",
        "advertiser_address_raw": "AABBCCDDEEFF", "advertiser_address_canonical": "FF:EE:DD:CC:BB:AA",
        "address_type": "public", "tx_add": 0, "rx_add": 0, "payload_sha256": f"payload-{candidate_id}",
        "nearest_windows_callback_timestamp": None, "time_delta_ms": time_delta_ms,
        "address_match_status": "MATCHED" if association_strength == "STRONG" else "AMBIGUOUS",
        "temporal_match_status": "MATCHED" if association_strength == "STRONG" else "AMBIGUOUS",
        "association_strength": association_strength, "association_rejection_reason": association_rejection_reason,
        "target_address_match": target_address_match,
    }


def build_passing_fixture(ble_root: Path, *, dataset_id: str = "SCI-TEST-DS", dataset_version: str = "1", scientific_task: str = "TARGET_VS_BACKGROUND") -> tuple[str, str, str]:
    """One capture, a few positive + background examples, a frozen dataset,
    a READY leakage-passed split, and an ACCEPTED_FOR_TRAINING quality
    report -- the minimal shape scientific preflight should PASS on."""
    capture = write_capture(ble_root, capture_id="SCI-TEST-CAP-01", session_id="SCI-TEST-SESSION-01", physical_unit_id="SCI-TEST-UNIT-01")
    examples = [make_example(capture=capture, index=index, physical_unit_id="SCI-TEST-UNIT-01" if index % 2 == 0 else None) for index in range(6)]
    write_examples(ble_root, capture, examples)
    example_ids = [example.example_id for example in examples]
    dataset = write_frozen_dataset(
        ble_root, dataset_id=dataset_id, dataset_version=dataset_version, physical_units=["SCI-TEST-UNIT-01"],
        captures=[capture.capture_id], example_ids=example_ids, class_distribution={"SCI-TEST-UNIT-01": 3, "UNKNOWN": 3},
    )
    write_ready_split(ble_root, dataset=dataset, scientific_task=scientific_task, example_ids=example_ids)
    write_quality_report(ble_root, dataset=dataset)
    return dataset_id, dataset_version, scientific_task
