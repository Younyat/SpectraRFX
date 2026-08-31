"""RQ3 real FRR pre/post analysis (2026-08-11) -- Scientific Dashboard
Closure audit finding: RQ3's pair construction was real, but the actual
scientific estimand (FRR_pre, FRR_post, D) had no real producer even
though the frozen inference pipeline that computes it was already real.
These tests prove rq3_frr_analysis.py's pure functions (never touching a
real trained model -- a stub `offline_inference_service` stands in for
OfflineInferenceService, exactly the same dependency-injection pattern
test_rq2_benchmark.py uses for StudioRepository) and
ScientificResultsRepository.run_rq3_frr_analysis's real orchestration.
"""
from __future__ import annotations

import hashlib
import json

import pytest

from app.modules.ble_rffi_studio.campaign.pre_post_pairing import PrePostPair
from app.modules.ble_rffi_studio.contracts import CaptureRecord
from app.modules.ble_scientific_results.api.scientific_results_repository import ScientificResultsRepository
from app.modules.ble_scientific_results.rq3_frr_analysis import (
    Rq3FrrAnalysisError,
    compute_rq3_pair_frr,
    device_day_values_for_permutation_test,
    mean_d_with_ci,
    per_unit_mean_d,
)
from ._helpers import make_example, write_examples


def _repo(tmp_path):
    return ScientificResultsRepository(tmp_path / "sci_results", tmp_path / "ble_rffi_studio")


def _pair(*, unit="UNIT-A", day="2026-08-01", arm="RESET", pre="CAP-PRE", post="CAP-POST", valid=True, reason=None) -> PrePostPair:
    return PrePostPair(
        physical_unit_id=unit, day_id=day, intervention_arm=arm, pre_capture_id=pre, post_capture_id=post,
        pre_receiver_epoch="epoch-1", post_receiver_epoch="epoch-1", pre_receiver_session_id="sess-1", post_receiver_session_id="sess-1",
        valid=valid, invalidation_reason=reason,
    )


class _StubOfflineInferenceService:
    """Returns a caller-scripted window sequence per capture_id -- never
    loads a real bundle/model from disk."""

    def __init__(self, windows_by_capture_id: dict[str, list[dict]]) -> None:
        self.windows_by_capture_id = windows_by_capture_id
        self.calls: list[dict] = []

    def run_decision_windows(self, *, bundle_id, examples, window_duration_s, minimum_eligible_bursts, base_profile=None):
        self.calls.append({"bundle_id": bundle_id, "n_examples": len(examples), "window_duration_s": window_duration_s})
        if not examples:
            return []
        capture_id = examples[0].capture_id
        return self.windows_by_capture_id.get(capture_id, [])


def _windows(capture_id: str, *, identified_count: int, rejected_count: int, target_unit: str = "UNIT-A") -> list[dict]:
    windows = []
    for i in range(identified_count):
        windows.append({"decision_window_id": f"{capture_id}-w{i}", "final_decision": "IDENTIFIED", "predicted_class": target_unit})
    for i in range(rejected_count):
        windows.append({"decision_window_id": f"{capture_id}-r{i}", "final_decision": "UNKNOWN", "predicted_class": "OTHER"})
    return windows


def test_compute_rq3_pair_frr_computes_real_frr_pre_post_and_d():
    pairs = [_pair()]
    service = _StubOfflineInferenceService({
        "CAP-PRE": _windows("CAP-PRE", identified_count=8, rejected_count=2),   # FRR_pre = 2/10 = 0.2
        "CAP-POST": _windows("CAP-POST", identified_count=5, rejected_count=5),  # FRR_post = 5/10 = 0.5
    })
    examples_by_capture_id = {
        "CAP-PRE": [make_example(capture=_make_capture("CAP-PRE"), index=0, physical_unit_id="UNIT-A")],
        "CAP-POST": [make_example(capture=_make_capture("CAP-POST"), index=0, physical_unit_id="UNIT-A")],
    }
    enriched = compute_rq3_pair_frr(
        pairs, offline_inference_service=service, bundle_id="BUNDLE-1", scientific_task="SAME_MODEL_UNIT_IDENTIFICATION",
        examples_by_capture_id=examples_by_capture_id, window_duration_s=10.0, minimum_eligible_bursts=1,
    )
    assert len(enriched) == 1
    row = enriched[0]
    assert row["n_pre_windows"] == 10
    assert row["n_post_windows"] == 10
    assert row["pre_frr"] == pytest.approx(0.2)
    assert row["post_frr"] == pytest.approx(0.5)
    assert row["d"] == pytest.approx(0.3)


def test_compute_rq3_pair_frr_never_scores_an_invalid_pair():
    pairs = [_pair(valid=False, reason="RECEIVER_EPOCH_CHANGED_BETWEEN_PRE_AND_POST:e1!=e2")]
    service = _StubOfflineInferenceService({})
    enriched = compute_rq3_pair_frr(
        pairs, offline_inference_service=service, bundle_id="BUNDLE-1", scientific_task="SAME_MODEL_UNIT_IDENTIFICATION",
        examples_by_capture_id={}, window_duration_s=10.0, minimum_eligible_bursts=1,
    )
    assert enriched[0]["valid"] is False
    assert enriched[0]["pre_frr"] is None
    assert enriched[0]["post_frr"] is None
    assert enriched[0]["d"] is None
    assert service.calls == []  # never even attempted to score an invalid pair


def test_compute_rq3_pair_frr_refuses_target_vs_background_task():
    with pytest.raises(Rq3FrrAnalysisError, match="RQ3_REQUIRES_A_DEVICE_IDENTIFICATION_SCIENTIFIC_TASK"):
        compute_rq3_pair_frr(
            [_pair()], offline_inference_service=_StubOfflineInferenceService({}), bundle_id="BUNDLE-1",
            scientific_task="TARGET_VS_BACKGROUND", examples_by_capture_id={}, window_duration_s=10.0, minimum_eligible_bursts=1,
        )


def test_per_unit_mean_d_averages_only_valid_pairs_with_a_real_d():
    pairs = [
        {"valid": True, "physical_unit_id": "UNIT-A", "intervention_arm": "RESET", "d": 0.2},
        {"valid": True, "physical_unit_id": "UNIT-A", "intervention_arm": "RESET", "d": 0.4},
        {"valid": True, "physical_unit_id": "UNIT-A", "intervention_arm": "CONTROL", "d": 0.1},
        {"valid": False, "physical_unit_id": "UNIT-A", "intervention_arm": "RESET", "d": None},
    ]
    result = per_unit_mean_d(pairs)
    assert result["reset"]["UNIT-A"] == pytest.approx(0.3)
    assert result["control"]["UNIT-A"] == pytest.approx(0.1)


def test_mean_d_with_ci_computes_a_real_bootstrap_ci_clustered_by_unit():
    pairs = [
        {"valid": True, "physical_unit_id": "UNIT-A", "intervention_arm": "RESET", "d": 0.2},
        {"valid": True, "physical_unit_id": "UNIT-A", "intervention_arm": "RESET", "d": 0.3},
        {"valid": True, "physical_unit_id": "UNIT-B", "intervention_arm": "RESET", "d": 0.1},
        {"valid": True, "physical_unit_id": "UNIT-B", "intervention_arm": "CONTROL", "d": 0.05},
        {"valid": False, "physical_unit_id": "UNIT-C", "intervention_arm": "RESET", "d": None},
    ]
    result = mean_d_with_ci(pairs, intervention_arm="RESET", n_resamples=200)
    assert result is not None
    assert result["point_estimate"] == pytest.approx((0.2 + 0.3 + 0.1) / 3)
    assert result["ci_low"] <= result["point_estimate"] <= result["ci_high"]
    assert result["n_resamples"] == 200


def test_mean_d_with_ci_returns_none_for_an_arm_with_zero_valid_pairs():
    pairs = [{"valid": True, "physical_unit_id": "UNIT-A", "intervention_arm": "CONTROL", "d": 0.1}]
    assert mean_d_with_ci(pairs, intervention_arm="RESET") is None


def test_device_day_values_excludes_units_with_only_one_arm():
    pairs = [
        {"valid": True, "physical_unit_id": "UNIT-A", "intervention_arm": "RESET", "d": 0.2},
        {"valid": True, "physical_unit_id": "UNIT-A", "intervention_arm": "CONTROL", "d": 0.1},
        {"valid": True, "physical_unit_id": "UNIT-B", "intervention_arm": "RESET", "d": 0.3},  # UNIT-B never has a CONTROL day
    ]
    values, is_reset = device_day_values_for_permutation_test(pairs)
    assert set(values.keys()) == {"UNIT-A"}
    assert values["UNIT-A"] == [0.2, 0.1]
    assert is_reset["UNIT-A"] == [True, False]


def _make_capture(capture_id: str, **overrides) -> CaptureRecord:
    fields = dict(
        project_id="P1", campaign_id="C1", capture_id=capture_id, session_id=f"S-{capture_id}",
        execution_id=f"EXEC-{capture_id}", data_origin="REAL_B200", target_reference_id="UNIT-A",
        capture_purpose="TARGET_DEVICE_ON", target_state="POWERED_ON",
        receiver_device_id="dev-1", sdr_model="B200", rx_channel="RX2", antenna_port="RX2",
        sample_rate_sps=4_000_000, sample_dtype="cf32_le", byte_order="little_endian", sample_count=1000, channel_count=1,
        center_frequency_hz=2_402_000_000, frontend_bandwidth_hz=2_000_000, effective_bandwidth_hz=2_000_000, gain_db=20.0, gain_mode="manual",
        capture_duration_s=1.0, capture_tool="real", iq_path="iq.cf32", iq_size_bytes=1, iq_sha256=hashlib.sha256(capture_id.encode()).hexdigest(),
        acquisition_quality="PASSED", discontinuities=0, replay_status="FULLY_PROCESSED", created_at="2026-08-01T00:00:00Z",
        day_id="2026-08-01", intervention_arm="RESET", pre_or_post="PRE", receiver_epoch="epoch-1", receiver_session_id="session-1",
    )
    fields.update(overrides)
    return CaptureRecord(**fields)


def test_run_rq3_frr_analysis_persists_a_real_enriched_report(tmp_path):
    repo = _repo(tmp_path)
    captures_dir = tmp_path / "ble_rffi_studio" / "captures"
    captures_dir.mkdir(parents=True)
    pre_capture = _make_capture("CAP-PRE", pre_or_post="PRE")
    post_capture = _make_capture("CAP-POST", pre_or_post="POST")
    (captures_dir / "CAP-PRE.json").write_text(json.dumps(pre_capture.model_dump(mode="json")), encoding="utf-8")
    (captures_dir / "CAP-POST.json").write_text(json.dumps(post_capture.model_dump(mode="json")), encoding="utf-8")

    write_examples(tmp_path / "ble_rffi_studio", pre_capture, [make_example(capture=pre_capture, index=0, physical_unit_id="UNIT-A")])
    write_examples(tmp_path / "ble_rffi_studio", post_capture, [make_example(capture=post_capture, index=0, physical_unit_id="UNIT-A")])

    service = _StubOfflineInferenceService({
        "CAP-PRE": _windows("CAP-PRE", identified_count=9, rejected_count=1),
        "CAP-POST": _windows("CAP-POST", identified_count=6, rejected_count=4),
    })
    # Real run + real RQ2 report so bundle_id auto-resolves from the PRIMARY branch.
    run_dir = tmp_path / "sci_results" / "RUN-1"
    (run_dir / "06_statistics").mkdir(parents=True)
    (run_dir / "06_statistics" / "rq2_representation_comparison_report.json").write_text(json.dumps({
        "branches": [{"branch": "raw_iq", "analysis_role": "PRIMARY", "evaluation_domain": "VALIDATION", "model_bundle_id": "BUNDLE-PRIMARY"}],
    }), encoding="utf-8")
    (tmp_path / "sci_results" / "RUN-1" / "run.json").write_text(json.dumps({
        "schema_version": "ble-scientific-results-paper-run-v1", "paper_run_id": "RUN-1", "campaign_id": "C1",
        "protocol_id": "PROTO-1", "protocol_version": 1, "dataset_id": "DS1", "dataset_version": "1.0.0",
        "scientific_task": "SAME_MODEL_UNIT_IDENTIFICATION", "analysis_code_commit": "abc", "analysis_environment_hash": "def",
        "storage_path": str(run_dir), "created_at": "2026-08-01T00:00:00Z",
    }), encoding="utf-8")

    as_dict = repo.run_rq3_frr_analysis(paper_run_id="RUN-1", offline_inference_service=service)

    assert service.calls[0]["bundle_id"] == "BUNDLE-PRIMARY"  # auto-resolved from the frozen PRIMARY branch
    pair_row = as_dict["rq3_pairs"][0]
    assert pair_row["pre_frr"] == pytest.approx(0.1)
    assert pair_row["post_frr"] == pytest.approx(0.4)
    assert pair_row["d"] == pytest.approx(0.3)
    assert as_dict["rq3_bundle_id"] == "BUNDLE-PRIMARY"
    # Only one arm (RESET) is present for UNIT-A here -- the permutation
    # test correctly reports SKIPPED_NO_DATA rather than dividing by zero.
    assert as_dict["rq3_within_device_permutation_test"]["status"] == "SKIPPED_NO_DATA"

    reloaded = repo.get_confirmatory_statistical_plan_report("RUN-1")
    assert reloaded["rq3_pairs"][0]["d"] == pytest.approx(0.3)


def test_run_rq3_frr_analysis_raises_without_a_frozen_primary_rq2_branch(tmp_path):
    repo = _repo(tmp_path)
    (tmp_path / "sci_results" / "RUN-1").mkdir(parents=True)
    (tmp_path / "sci_results" / "RUN-1" / "run.json").write_text(json.dumps({
        "schema_version": "ble-scientific-results-paper-run-v1", "paper_run_id": "RUN-1", "campaign_id": "C1",
        "protocol_id": "PROTO-1", "protocol_version": 1, "dataset_id": "DS1", "dataset_version": "1.0.0",
        "scientific_task": "SAME_MODEL_UNIT_IDENTIFICATION", "analysis_code_commit": "abc", "analysis_environment_hash": "def",
        "storage_path": str(tmp_path / "sci_results" / "RUN-1"), "created_at": "2026-08-01T00:00:00Z",
    }), encoding="utf-8")
    with pytest.raises(ValueError, match="NO_FROZEN_PRIMARY_RQ2_BRANCH_WITH_A_MODEL_BUNDLE_ID"):
        repo.run_rq3_frr_analysis(paper_run_id="RUN-1", offline_inference_service=_StubOfflineInferenceService({}))
