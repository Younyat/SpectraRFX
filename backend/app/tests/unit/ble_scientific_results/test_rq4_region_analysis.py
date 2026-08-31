"""RQ4 region-specific fitting closure (2026-08-12): rq4_primary_analysis=
REGION_SPECIFIC_FITTING_AND_EVALUATION. rq4_region_analysis.py's pure
functions are proven with stub inference services (the same
dependency-injection pattern test_rq3_frr_analysis.py uses), and
ScientificResultsRepository.run_rq4_region_analysis's real orchestration is
proven end-to-end against a REAL StudioRepository training pipeline (real
synthetic IQ, real region-restricted re-fitting via
train_region_specific_variant, real bundle export, real decision-window
scoring) -- no fabricated numbers anywhere, matching the RQ4 closure's
explicit instruction to validate the mechanism with fixtures only.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.infrastructure.ble.capture.ble_offline_replay import sha256_file, utc_now, write_json, write_jsonl
from app.modules.ble_rffi_studio.api import StudioRepository
from app.modules.ble_rffi_studio.contracts import CaptureRecord
from app.modules.ble_rffi_studio.inference.offline_inference import OfflineInferenceService
from app.modules.ble_scientific_results.api.scientific_results_repository import ScientificResultsRepository
from app.modules.ble_scientific_results.rq4_region_analysis import (
    ANALYTICAL_REGIONS,
    build_matched_region_blocks,
    compute_rq4_region_report,
    matched_region_block_id,
)
from app.tests.unit.ble_rffi_studio._helpers import write_synthetic_capture_iq

from ._helpers import make_example

PROJECT_ID = "SYN-PROJECT"


def _capture(**overrides) -> CaptureRecord:
    fields = dict(
        project_id="P1", campaign_id="C1", capture_id="CAP-1", session_id="S1", execution_id="EXEC-1",
        data_origin="REAL_B200", receiver_device_id="dev-1", sdr_model="B200", rx_channel="RX2", antenna_port="RX2",
        sample_rate_sps=4_000_000, sample_dtype="cf32_le", byte_order="little_endian", sample_count=1000, channel_count=1,
        center_frequency_hz=2_402_000_000, frontend_bandwidth_hz=2_000_000, effective_bandwidth_hz=2_000_000, gain_db=20.0, gain_mode="manual",
        capture_duration_s=1.0, capture_tool="real", iq_path="iq.cf32", iq_size_bytes=1, iq_sha256="deadbeef",
        acquisition_quality="PASSED", discontinuities=0, replay_status="FULLY_PROCESSED", created_at="2026-08-01T00:00:00Z",
        physical_unit_id="UNIT-A", day_id="2026-08-01", packet_condition="ORIGINAL",
    )
    fields.update(overrides)
    return CaptureRecord(**fields)


class _StubOfflineInferenceService:
    def __init__(self, windows_by_capture_id: dict[str, list[dict]]) -> None:
        self.windows_by_capture_id = windows_by_capture_id
        self.calls: list[dict] = []
        self.bundle_root = Path("/unused")

    def run_decision_windows(self, *, bundle_id, examples, window_duration_s, minimum_eligible_bursts, base_profile=None):
        self.calls.append({"bundle_id": bundle_id, "n_examples": len(examples)})
        if not examples:
            return []
        return self.windows_by_capture_id.get(examples[0].capture_id, [])


def _window(window_id: str, *, decision: str, predicted_class: str | None = None, abstention_reason: str | None = None) -> dict:
    return {
        "decision_window_id": window_id, "final_decision": decision, "predicted_class": predicted_class,
        "abstention_reason": abstention_reason,
    }


# ------------------------------------------------------------------
# Pure functions
# ------------------------------------------------------------------

def test_matched_region_block_id_is_none_without_a_full_real_identity():
    assert matched_region_block_id(_capture(physical_unit_id=None)) is None
    assert matched_region_block_id(_capture(day_id=None)) is None
    assert matched_region_block_id(_capture(packet_condition=None)) is None
    assert matched_region_block_id(_capture()) == "UNIT-A|2026-08-01|ORIGINAL"


def test_build_matched_region_blocks_groups_by_unit_day_condition_and_excludes_incomplete_captures():
    captures = [
        _capture(capture_id="CAP-1"), _capture(capture_id="CAP-2"),  # same block
        _capture(capture_id="CAP-3", day_id="2026-08-02"),  # different block
        _capture(capture_id="CAP-4", physical_unit_id=None),  # excluded
    ]
    blocks = build_matched_region_blocks(captures)
    assert set(blocks.keys()) == {"UNIT-A|2026-08-01|ORIGINAL", "UNIT-A|2026-08-02|ORIGINAL"}
    assert {c.capture_id for c in blocks["UNIT-A|2026-08-01|ORIGINAL"]} == {"CAP-1", "CAP-2"}


def test_compute_rq4_region_report_computes_per_block_recall_and_pairs_the_primary_contrast():
    capture = _capture(capture_id="CAP-1")
    blocks = {"UNIT-A|2026-08-01|ORIGINAL": [capture]}
    example = make_example(capture=capture, index=0, physical_unit_id="UNIT-A")
    examples_by_capture_id = {"CAP-1": [example]}

    full_burst_service = _StubOfflineInferenceService({
        "CAP-1": [_window("w0", decision="IDENTIFIED", predicted_class="UNIT-A"), _window("w1", decision="IDENTIFIED", predicted_class="UNIT-A")],
    })  # 2/2 accepted -> recall 1.0
    pre_pdu_service = _StubOfflineInferenceService({
        "CAP-1": [_window("w0", decision="IDENTIFIED", predicted_class="UNIT-A"), _window("w1", decision="INSUFFICIENT_EVIDENCE", abstention_reason="BELOW_MINIMUM_ELIGIBLE_BURSTS:1<2")],
    })  # 1/2 accepted -> recall 0.5

    report = compute_rq4_region_report(
        blocks=blocks, examples_by_capture_id=examples_by_capture_id,
        eligible_example_ids_by_region={"FULL_BURST": {example.example_id}, "PRE_PDU": {example.example_id}, "ADVA_EXCLUDED": set()},
        inference_services={"FULL_BURST": full_burst_service, "PRE_PDU": pre_pdu_service, "ADVA_EXCLUDED": None},
        bundle_ids={"FULL_BURST": "BUNDLE-FULL", "PRE_PDU": "BUNDLE-PRE", "ADVA_EXCLUDED": None},
        window_duration_s=10.0, minimum_eligible_bursts=1,
    )

    row = report["matched_region_blocks"][0]
    assert row["matched_region_block_id"] == "UNIT-A|2026-08-01|ORIGINAL"
    full = row["regions"]["FULL_BURST"]
    pre = row["regions"]["PRE_PDU"]
    assert full["recall"] == pytest.approx(1.0)
    assert full["eligible_windows"] == 2 and full["decided_windows"] == 2 and full["abstained_windows"] == 0
    assert pre["recall"] == pytest.approx(0.5)
    assert pre["eligible_windows"] == 2 and pre["decided_windows"] == 1 and pre["abstained_windows"] == 1
    assert row["regions"]["ADVA_EXCLUDED"] is None  # honestly NO_DATA -- no bundle/service for this region

    assert report["primary_contrast"] == {"a_region": "FULL_BURST", "b_region": "PRE_PDU", "n_matched_blocks": 1}
    assert report["primary_contrast_scores_a"] == pytest.approx([1.0])
    assert report["primary_contrast_scores_b"] == pytest.approx([0.5])
    # ADVA_EXCLUDED has no real recall anywhere -- secondary contrast stays empty, never fabricated.
    assert report["secondary_contrast_scores_a"] == []
    assert report["secondary_contrast_scores_b"] == []


def test_compute_rq4_region_report_never_pairs_a_block_missing_either_side():
    capture = _capture(capture_id="CAP-1")
    blocks = {"UNIT-A|2026-08-01|ORIGINAL": [capture]}
    example = make_example(capture=capture, index=0, physical_unit_id="UNIT-A")
    examples_by_capture_id = {"CAP-1": [example]}
    full_burst_service = _StubOfflineInferenceService({"CAP-1": [_window("w0", decision="IDENTIFIED", predicted_class="UNIT-A")]})

    report = compute_rq4_region_report(
        blocks=blocks, examples_by_capture_id=examples_by_capture_id,
        eligible_example_ids_by_region={"FULL_BURST": {example.example_id}, "PRE_PDU": set(), "ADVA_EXCLUDED": set()},
        inference_services={"FULL_BURST": full_burst_service, "PRE_PDU": None, "ADVA_EXCLUDED": None},
        bundle_ids={"FULL_BURST": "BUNDLE-FULL", "PRE_PDU": None, "ADVA_EXCLUDED": None},
        window_duration_s=10.0, minimum_eligible_bursts=1,
    )
    assert report["primary_contrast_scores_a"] == []
    assert report["primary_contrast_scores_b"] == []


# ------------------------------------------------------------------
# Real end-to-end orchestration
# ------------------------------------------------------------------

def _seed_matched_block_captures(repository: StudioRepository, tmp_path: Path, **kwargs) -> list[str]:
    """Mirrors ble_rffi_studio/test_rq4_region_specific_fitting.py's own
    fixture, additionally stamping every capture with the REAL
    physical_unit_id/day_id/packet_condition identity matched_region_block_id
    needs, plus a leading-AdvA ledger so ADVA_EXCLUDED is real too."""
    raw_iq_dir = tmp_path / "raw_iq"
    raw_iq_dir.mkdir(parents=True, exist_ok=True)
    examples, iq_paths = write_synthetic_capture_iq(raw_iq_dir, **kwargs)
    by_capture: dict[str, list] = {}
    for example in examples:
        by_capture.setdefault(example.capture_id, []).append(example)
    for capture_id, capture_examples in by_capture.items():
        capture_dir = repository.legacy_capture_root / capture_id
        capture_dir.mkdir(parents=True, exist_ok=True)
        dest = capture_dir / "iq.cf32"
        dest.write_bytes(iq_paths[capture_id].read_bytes())
        unit_id = capture_examples[0].physical_unit_id
        capture = CaptureRecord(
            project_id=PROJECT_ID, campaign_id="SYN-CAMPAIGN-01", capture_id=capture_id, session_id=capture_examples[0].session_id,
            execution_id=f"EXEC-{capture_id}", data_origin="REAL_B200", receiver_device_id="E3R04Z1B2", sdr_model="B200", rx_channel="RX2", antenna_port="RX2",
            sample_rate_sps=4_000_000, sample_dtype="cf32_le", byte_order="little_endian", sample_count=1_000_000, channel_count=1,
            center_frequency_hz=2_402_000_000, frontend_bandwidth_hz=2_000_000, effective_bandwidth_hz=2_000_000, gain_db=20.0, gain_mode="manual",
            capture_duration_s=1.0, capture_tool="real", iq_path="iq.cf32", iq_size_bytes=dest.stat().st_size, iq_sha256=sha256_file(dest),
            acquisition_quality="PASSED", discontinuities=0, replay_status="FULLY_PROCESSED", created_at=utc_now(),
            physical_unit_id=unit_id, day_id="2026-08-01", packet_condition="ORIGINAL",
        )
        write_json(repository.captures_dir / f"{capture_id}.json", capture.model_dump(mode="json"))
        capture_evidence_dir = repository.evidence_dir / capture_id
        capture_evidence_dir.mkdir(parents=True, exist_ok=True)
        write_jsonl(capture_evidence_dir / "examples.jsonl", [e.model_dump(mode="json") for e in capture_examples])
        write_jsonl(capture_evidence_dir / "annotations.jsonl", [])

        ledger_dir = capture_dir / "offline_replays" / "run-1"
        ledger_dir.mkdir(parents=True, exist_ok=True)
        write_jsonl(ledger_dir / "packet_association_ledger.jsonl", [
            {"packet_id": e.packet_id, "pdu_type": "ADV_IND"} for e in capture_examples
        ])
    return list(by_capture.keys())


@pytest.fixture
def studio_repository(tmp_path):
    return StudioRepository(tmp_path / "studio", legacy_capture_root=tmp_path / "legacy_captures", legacy_session_root=tmp_path / "legacy_sessions")


@pytest.fixture
def sci_repository(tmp_path, studio_repository):
    return ScientificResultsRepository(tmp_path / "sci_results", studio_repository.root, legacy_capture_root=studio_repository.legacy_capture_root)


def _write_paper_run(sci_repository, paper_run_id: str) -> None:
    run_dir = sci_repository.root / paper_run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    write_json(run_dir / "run.json", {
        "schema_version": "ble-scientific-results-paper-run-v1", "paper_run_id": paper_run_id, "campaign_id": "C1",
        "protocol_id": "PROTO-1", "protocol_version": 1, "dataset_id": "DS1", "dataset_version": "1.0.0",
        "scientific_task": "SAME_MODEL_UNIT_IDENTIFICATION", "analysis_code_commit": "abc", "analysis_environment_hash": "def",
        "storage_path": str(run_dir), "created_at": "2026-08-01T00:00:00Z",
    })


def _write_rq2_primary(sci_repository, paper_run_id: str, *, training_run_id: str, model_bundle_id: str) -> None:
    (sci_repository._run_dir(paper_run_id) / "06_statistics").mkdir(parents=True, exist_ok=True)
    write_json(sci_repository._run_dir(paper_run_id) / "06_statistics" / "rq2_representation_comparison_report.json", {
        "branches": [{"branch": "raw_iq", "analysis_role": "PRIMARY", "evaluation_domain": "VALIDATION", "training_run_id": training_run_id, "model_bundle_id": model_bundle_id}],
    })


def test_run_rq4_region_analysis_real_end_to_end(studio_repository, sci_repository, tmp_path):
    capture_ids = _seed_matched_block_captures(studio_repository, tmp_path, units=2, sessions_per_unit=3, examples_per_session=10)
    prepared = studio_repository.prepare_and_train(
        capture_ids=capture_ids, project_id=PROJECT_ID, campaign_id="SYN-CAMPAIGN-01",
        scientific_task="SAME_MODEL_UNIT_IDENTIFICATION", dataset_id="SYN-AUTO-DS", speed_profile="quick_pilot",
    )
    recommended_id = prepared["recommended_training_run_id"]
    full_burst_bundle_id = "FULL-BURST-BUNDLE"
    studio_repository.export_bundle(training_run_id=recommended_id, bundle_id=full_burst_bundle_id, acceptance_criteria={}, model_card_text="test")

    paper_run_id = "RUN-1"
    _write_paper_run(sci_repository, paper_run_id)
    _write_rq2_primary(sci_repository, paper_run_id, training_run_id=recommended_id, model_bundle_id=full_burst_bundle_id)

    iq_paths = {cid: studio_repository.legacy_capture_root / cid / "iq.cf32" for cid in capture_ids}
    full_burst_service = OfflineInferenceService(studio_repository.bundle_builder.root, iq_paths)

    as_dict = sci_repository.run_rq4_region_analysis(
        paper_run_id=paper_run_id, offline_inference_service=full_burst_service, studio_repository=studio_repository,
    )

    report = as_dict["rq4_region_report"]
    assert report["bundle_ids"]["FULL_BURST"] == full_burst_bundle_id
    # Both ADVA_EXCLUDED and PRE_PDU were real-trained (the ledger declares ADV_IND for every example).
    assert report["bundle_ids"]["ADVA_EXCLUDED"] is not None
    assert report["bundle_ids"]["PRE_PDU"] is not None
    assert len(report["matched_region_blocks"]) > 0
    for row in report["matched_region_blocks"]:
        for region in ANALYTICAL_REGIONS:
            assert row["regions"][region] is not None
            assert row["regions"][region]["eligible_windows"] >= 0

    # PRIMARY contrast (FULL_BURST vs PRE_PDU) was fed into the untouched NI/Holm pipeline.
    assert report["primary_contrast"]["n_matched_blocks"] > 0
    assert as_dict["rq4_paired_comparison"]["status"] == "EXECUTED"
    # SECONDARY (FULL_BURST vs ADVA_EXCLUDED) is reported but never Holm-corrected --
    # it must never appear inside rq4_paired_comparison's own p-value.
    assert "secondary_contrast_scores_a" in report

    reloaded = sci_repository.get_confirmatory_statistical_plan_report(paper_run_id)
    assert reloaded["rq4_region_report"]["bundle_ids"]["PRE_PDU"] is not None


def test_run_rq4_region_analysis_raises_without_a_frozen_primary_rq2_branch(sci_repository):
    _write_paper_run(sci_repository, "RUN-1")
    with pytest.raises(ValueError, match="NO_FROZEN_PRIMARY_RQ2_BRANCH_WITH_A_MODEL_BUNDLE_ID"):
        sci_repository.run_rq4_region_analysis(paper_run_id="RUN-1", offline_inference_service=_StubOfflineInferenceService({}), studio_repository=None)


def test_run_rq4_region_analysis_raises_without_any_matched_block_captures(sci_repository, studio_repository):
    _write_paper_run(sci_repository, "RUN-1")
    _write_rq2_primary(sci_repository, "RUN-1", training_run_id="TR-1", model_bundle_id="BUNDLE-1")
    with pytest.raises(ValueError, match="NO_CAPTURES_WITH_A_REAL_MATCHED_REGION_BLOCK_IDENTITY"):
        sci_repository.run_rq4_region_analysis(paper_run_id="RUN-1", offline_inference_service=_StubOfflineInferenceService({}), studio_repository=studio_repository)
