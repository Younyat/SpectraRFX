"""Real production caller for run_confirmatory_statistical_plan()
(2026-08-09): ScientificResultsRepository.run_confirmatory_statistical_plan
persists a real artifact under 06_statistics/, not just a value returned
from a unit test.
"""
from __future__ import annotations

import json

from app.modules.ble_rffi_studio.contracts import CaptureRecord
from app.modules.ble_scientific_results.api.scientific_results_repository import ScientificResultsRepository


def _repo(tmp_path):
    return ScientificResultsRepository(tmp_path / "scientific_reports", tmp_path / "ble_rffi_studio")


def test_run_confirmatory_statistical_plan_persists_a_real_artifact(tmp_path):
    repo = _repo(tmp_path)
    as_dict = repo.run_confirmatory_statistical_plan(
        "RUN-1", non_inferiority_differences=[0.01, -0.02, 0.0, 0.01, -0.01], non_inferiority_margin=0.1,
    )
    assert as_dict["non_inferiority"]["status"] == "EXECUTED"

    persisted_path = tmp_path / "scientific_reports" / "RUN-1" / "06_statistics" / "confirmatory_statistical_plan_report.json"
    assert persisted_path.is_file()
    on_disk = json.loads(persisted_path.read_text(encoding="utf-8"))
    assert on_disk["non_inferiority"]["status"] == "EXECUTED"
    assert on_disk["rq3_within_device_permutation_test"]["status"] == "SKIPPED_NO_DATA"


def test_get_confirmatory_statistical_plan_report_reads_back_the_persisted_artifact(tmp_path):
    repo = _repo(tmp_path)
    assert repo.get_confirmatory_statistical_plan_report("RUN-2") is None

    repo.run_confirmatory_statistical_plan("RUN-2")
    reloaded = repo.get_confirmatory_statistical_plan_report("RUN-2")
    assert reloaded is not None
    assert reloaded["balanced_accuracy"]["status"] == "SKIPPED_NO_DATA"


def _capture(capture_id: str, *, pre_or_post: str) -> CaptureRecord:
    return CaptureRecord(
        project_id="P1", campaign_id="C1", capture_id=capture_id, session_id=f"S-{capture_id}",
        execution_id=f"EXEC-{capture_id}", data_origin="REAL_B200", target_reference_id="UNIT-A",
        capture_purpose="TARGET_DEVICE_ON", target_state="POWERED_ON",
        receiver_device_id="dev-1", sdr_model="B200", rx_channel="RX2", antenna_port="RX2",
        sample_rate_sps=4_000_000, sample_dtype="cf32_le", byte_order="little_endian", sample_count=1000, channel_count=1,
        center_frequency_hz=2_402_000_000, frontend_bandwidth_hz=2_000_000, effective_bandwidth_hz=2_000_000, gain_db=20.0, gain_mode="manual",
        capture_duration_s=1.0, capture_tool="real", iq_path="iq.cf32", iq_size_bytes=1, iq_sha256="sha",
        acquisition_quality="PASSED", discontinuities=0, replay_status="FULLY_PROCESSED", created_at="2026-08-01T00:00:00Z",
        day_id="2026-08-01", intervention_arm="RESET", pre_or_post=pre_or_post,
        receiver_epoch="epoch-1", receiver_session_id="session-1",
    )


def test_run_confirmatory_statistical_plan_persists_the_real_rq3_pair_registry(tmp_path):
    """Dashboard closure (2026-08-11): rq3_pairs is real PrePostPair identity
    from build_pre_post_pairs() over the real captures on disk -- computed
    independently of the caller's stats kwargs, never a fabricated D value
    (see _build_rq3_pair_registry's own docstring)."""
    repo = _repo(tmp_path)
    captures_dir = tmp_path / "ble_rffi_studio" / "captures"
    captures_dir.mkdir(parents=True)
    (captures_dir / "CAP-PRE.json").write_text(json.dumps(_capture("CAP-PRE", pre_or_post="PRE").model_dump(mode="json")), encoding="utf-8")
    (captures_dir / "CAP-POST.json").write_text(json.dumps(_capture("CAP-POST", pre_or_post="POST").model_dump(mode="json")), encoding="utf-8")

    as_dict = repo.run_confirmatory_statistical_plan("RUN-3")
    assert as_dict["rq3_pairs"] == [{
        "physical_unit_id": "UNIT-A", "day_id": "2026-08-01", "intervention_arm": "RESET",
        "pre_capture_id": "CAP-PRE", "post_capture_id": "CAP-POST",
        "pre_receiver_epoch": "epoch-1", "post_receiver_epoch": "epoch-1",
        "pre_receiver_session_id": "session-1", "post_receiver_session_id": "session-1",
        "valid": True, "invalidation_reason": None,
    }]
    # No key on any pair claims a PRE/POST numeric value or D -- that stays
    # MISSING_CANONICAL_METRIC on the frontend, never fabricated here.
    assert "pre_value" not in as_dict["rq3_pairs"][0]
    assert "post_value" not in as_dict["rq3_pairs"][0]
    assert "d" not in as_dict["rq3_pairs"][0]


def test_run_confirmatory_statistical_plan_reports_an_empty_rq3_pair_registry_when_no_real_captures_exist(tmp_path):
    repo = _repo(tmp_path)
    as_dict = repo.run_confirmatory_statistical_plan("RUN-4")
    assert as_dict["rq3_pairs"] == []
