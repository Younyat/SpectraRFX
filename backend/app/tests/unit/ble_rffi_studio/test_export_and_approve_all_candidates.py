"""P0 correction (2026-08-08): export_and_approve_all_candidates() used to
call evaluate_training_run_on_test_opt_in() for every NON-recommended
candidate and then auto-approve it for live pilot -- meaning "normal",
fully-automated model export silently exposed every trained candidate to
TEST, not just the one VALIDATION selected. This had zero test coverage
before this file. These tests exercise the REAL, corrected behavior against
a real prepare_and_train() run over REAL_B200-origin synthetic captures (the
only data_origin that can ever reach APPROVED_FOR_LIVE_PILOT)."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.infrastructure.ble.capture.ble_offline_replay import sha256_file, utc_now, write_json, write_jsonl
from app.modules.ble_rffi_studio.api import StudioRepository
from app.modules.ble_rffi_studio.contracts import CaptureRecord

from ._helpers import write_synthetic_capture_iq

PROJECT_ID = "SYN-PROJECT"


def _seed_real_b200_captures(repository: StudioRepository, tmp_path: Path, **kwargs) -> list[str]:
    """Same shape as test_prepare_and_train.py's _seed_synthetic_capture,
    but with data_origin=REAL_B200 -- required because a SYNTHETIC_TEST_ONLY
    bundle can never pass EVALUATED (it is capped at
    SYNTHETIC_PIPELINE_VERIFIED, see bundle_builder.py), and this file
    specifically needs to exercise the real APPROVED_FOR_LIVE_PILOT path."""
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
        capture = CaptureRecord(
            project_id=PROJECT_ID, campaign_id="SYN-CAMPAIGN-01", capture_id=capture_id, session_id=capture_examples[0].session_id,
            execution_id=f"EXEC-{capture_id}", data_origin="REAL_B200", receiver_device_id="E3R04Z1B2", sdr_model="B200", rx_channel="RX2", antenna_port="RX2",
            sample_rate_sps=4_000_000, sample_dtype="cf32_le", byte_order="little_endian", sample_count=1_000_000, channel_count=1,
            center_frequency_hz=2_402_000_000, frontend_bandwidth_hz=2_000_000, effective_bandwidth_hz=2_000_000, gain_db=20.0, gain_mode="manual",
            capture_duration_s=1.0, capture_tool="real", iq_path="iq.cf32", iq_size_bytes=dest.stat().st_size, iq_sha256=sha256_file(dest),
            acquisition_quality="PASSED", discontinuities=0, replay_status="FULLY_PROCESSED", created_at=utc_now(),
        )
        write_json(repository.captures_dir / f"{capture_id}.json", capture.model_dump(mode="json"))
        capture_evidence_dir = repository.evidence_dir / capture_id
        capture_evidence_dir.mkdir(parents=True, exist_ok=True)
        write_jsonl(capture_evidence_dir / "examples.jsonl", [e.model_dump(mode="json") for e in capture_examples])
        write_jsonl(capture_evidence_dir / "annotations.jsonl", [])

    return list(by_capture.keys())


@pytest.fixture
def repository(tmp_path):
    return StudioRepository(tmp_path / "studio", legacy_capture_root=tmp_path / "legacy_captures", legacy_session_root=tmp_path / "legacy_sessions")


@pytest.fixture
def prepared_result(repository, tmp_path):
    capture_ids = _seed_real_b200_captures(repository, tmp_path, units=2, sessions_per_unit=3, examples_per_session=10)
    result = repository.prepare_and_train(
        capture_ids=capture_ids, project_id=PROJECT_ID, campaign_id="SYN-CAMPAIGN-01",
        scientific_task="SAME_MODEL_UNIT_IDENTIFICATION", dataset_id="SYN-AUTO-DS", speed_profile="quick_pilot",
    )
    assert result["stopped_at"] is None
    assert len(result["trained_models"]) >= 2, "need at least one recommended + one non-recommended candidate for this test to mean anything"
    return result


def test_only_the_recommended_candidate_is_approved_for_live_pilot(repository, prepared_result):
    recommended_id = prepared_result["recommended_training_run_id"]
    non_recommended = [m["training_run_id"] for m in prepared_result["trained_models"] if m["training_run_id"] != recommended_id]
    assert non_recommended  # sanity: the fixture really did train >=2 candidates

    results = repository.export_and_approve_all_candidates(physical_unit_id="SYN-UNIT-01", prepare_and_train_result=prepared_result)
    by_run_id = {r["training_run_id"]: r for r in results}

    assert by_run_id[recommended_id]["approval_status"] == "APPROVED_FOR_LIVE_PILOT"
    recommended_bundle = repository.get_bundle(by_run_id[recommended_id]["bundle_id"])
    assert recommended_bundle.test_evaluation_provenance == "SINGLE_SELECTION_GUARANTEE"
    assert recommended_bundle.confirmatory_eligible is True

    for run_id in non_recommended:
        entry = by_run_id[run_id]
        assert entry["approval_status"] == "TEST_NOT_EXECUTED", (
            f"non-recommended candidate {run_id} must never be auto-approved, got {entry['approval_status']}"
        )
        bundle = repository.get_bundle(entry["bundle_id"])
        assert bundle.approval_status == "TEST_NOT_EXECUTED"
        assert bundle.test_evaluation_provenance == "NOT_EVALUATED"
        assert bundle.confirmatory_eligible is False
        # The real, load-bearing assertion: TEST was never touched for this
        # candidate at all -- not evaluated, not persisted, not readable.
        evaluation = repository.get_evaluation(run_id)
        assert "TEST" not in (evaluation["evaluation_report"] or {})


def test_non_recommended_candidate_bundle_cannot_be_manually_approved_either(repository, prepared_result):
    recommended_id = prepared_result["recommended_training_run_id"]
    non_recommended_id = next(m["training_run_id"] for m in prepared_result["trained_models"] if m["training_run_id"] != recommended_id)

    repository.export_and_approve_all_candidates(physical_unit_id="SYN-UNIT-01", prepare_and_train_result=prepared_result)
    bundle_id = f"SYN-UNIT-01-{next(m['model_type'] for m in prepared_result['trained_models'] if m['training_run_id'] == non_recommended_id)}-bundle"

    with pytest.raises(ValueError, match="CANNOT_APPROVE_A_BUNDLE_WITH_NO_TEST_EVALUATION"):
        repository.approve_bundle(bundle_id)


def test_opting_in_a_non_recommended_candidate_still_works_but_can_never_be_approved(repository, prepared_result):
    """The explicit, separate, human-acknowledged opt-in path must still be
    usable (an operator legitimately comparing exploratory candidates) --
    but P0.2: the resulting bundle must be permanently ineligible for
    live-pilot approval, never silently indistinguishable from a
    confirmatory one."""
    recommended_id = prepared_result["recommended_training_run_id"]
    non_recommended_id = next(m["training_run_id"] for m in prepared_result["trained_models"] if m["training_run_id"] != recommended_id)
    model_type = next(m["model_type"] for m in prepared_result["trained_models"] if m["training_run_id"] == non_recommended_id)

    repository.evaluate_training_run_on_test_opt_in(non_recommended_id, acknowledge_multiple_comparison_risk=True)
    manifest, reasons = repository.export_bundle(
        training_run_id=non_recommended_id, bundle_id=f"{model_type}-opt-in-bundle", acceptance_criteria={},
        model_card_text="# opt-in exploratory bundle",
    )
    assert manifest.approval_status == "EVALUATED"
    assert manifest.test_evaluation_provenance == "OPT_IN_MULTI_CANDIDATE_COMPARISON"
    assert manifest.confirmatory_eligible is False

    with pytest.raises(ValueError, match="CANNOT_APPROVE_A_NON_CONFIRMATORY_BUNDLE_FOR_LIVE_PILOT"):
        repository.approve_bundle(manifest.bundle_id)


# ------------------------------------------------------------------
# P0.3: opening TEST for the recommended candidate must freeze a real
# ble_scientific_results AnalysisContract and log a real, hash-chained
# holdout access entry -- the two systems connected at the one moment that
# actually matters, not two disconnected pipelines.
# ------------------------------------------------------------------

def test_opening_test_freezes_a_real_analysis_contract_and_logs_holdout_access(repository, prepared_result):
    from app.modules.ble_scientific_results.api.scientific_results_repository import ScientificResultsRepository

    recommended_id = prepared_result["recommended_training_run_id"]
    stored = repository.get_training_run(recommended_id)
    assert stored["analysis_contract_protocol_id"] is not None
    assert stored["analysis_contract_protocol_version"] is not None
    assert stored["analysis_contract_hash"] is not None

    sci = ScientificResultsRepository(repository.root.parent / "scientific_reports" / "ble", ble_rffi_studio_root=repository.root)
    contract = sci.get_protocol(stored["analysis_contract_protocol_id"], stored["analysis_contract_protocol_version"])
    assert contract.random_seeds == [42]  # the real seed this run trained with, not a placeholder

    log = sci.list_holdout_access_log()
    assert len(log) >= 1
    entry = next(e for e in log if e.resource_id == recommended_id)
    assert entry.access_type == "OPEN_TEST"
    assert entry.analysis_contract_hash == contract.content_hash()
    assert entry.reason == "SINGLE_SELECTION_GUARANTEE"

    # The chain must actually verify -- not just contain an entry.
    verification = sci.verify_holdout_access_chain()
    assert verification.status == "VALID"


def test_reevaluating_test_reuses_the_same_frozen_contract_not_a_new_version(repository, prepared_result):
    recommended_id = prepared_result["recommended_training_run_id"]
    first = repository.get_training_run(recommended_id)

    # Re-run evaluation with include_test=True again (e.g. a UI "reverificar"
    # click after a restart) -- must NOT mint a second protocol version.
    repository.evaluate_training_run(recommended_id, include_test=True)
    second = repository.get_training_run(recommended_id)

    assert second["analysis_contract_protocol_id"] == first["analysis_contract_protocol_id"]
    assert second["analysis_contract_protocol_version"] == first["analysis_contract_protocol_version"]
