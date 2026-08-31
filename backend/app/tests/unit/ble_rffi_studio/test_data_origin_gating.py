"""data_origin / operational_use gating: SYNTHETIC_TEST_ONLY must never be
able to reach APPROVED_FOR_LIVE_PILOT, must never be silently mixed with
REAL_B200 in one dataset, and a TrainingRun's declared data_origin must
always match the dataset it actually trained on. Also covers the sibling
project_id gate: a dataset built under project_id=X must never silently pull
in a capture actually recorded under a different project.
"""
from __future__ import annotations

import pytest

from app.infrastructure.ble.capture.ble_offline_replay import sha256_file, utc_now, write_json
from app.modules.ble_rffi_studio.api import StudioRepository
from app.modules.ble_rffi_studio.contracts import CaptureRecord, TrainingRun

from ._helpers import write_synthetic_capture_iq


@pytest.fixture
def repository(tmp_path):
    return StudioRepository(tmp_path / "studio", legacy_capture_root=tmp_path / "legacy_captures", legacy_session_root=tmp_path / "legacy_sessions")


def _write_capture(repository, tmp_path, capture_id, data_origin, examples_per_session=4, samples_per_example=800, sample_rate=4_000_000.0, project_id="P1"):
    raw_dir = tmp_path / f"raw_{capture_id}"
    raw_dir.mkdir(parents=True, exist_ok=True)
    examples, iq_paths = write_synthetic_capture_iq(raw_dir, units=1, sessions_per_unit=1, examples_per_session=examples_per_session, samples_per_example=samples_per_example)
    only_capture_id = next(iter(iq_paths))
    capture_dir = repository.legacy_capture_root / capture_id
    capture_dir.mkdir(parents=True, exist_ok=True)
    dest = capture_dir / "iq.cf32"
    dest.write_bytes(iq_paths[only_capture_id].read_bytes())
    capture = CaptureRecord(
        project_id=project_id, campaign_id="C1", capture_id=capture_id, session_id=f"S-{capture_id}", execution_id=f"E-{capture_id}",
        data_origin=data_origin, receiver_device_id="test", sdr_model="test", rx_channel="RX2", antenna_port="RX2",
        sample_rate_sps=int(sample_rate), sample_dtype="cf32_le", byte_order="little_endian", sample_count=1000, channel_count=1,
        center_frequency_hz=2_402_000_000, frontend_bandwidth_hz=2_000_000, effective_bandwidth_hz=2_000_000, gain_db=20.0, gain_mode="manual",
        capture_duration_s=1.0, capture_tool="test", iq_path="iq.cf32", iq_size_bytes=dest.stat().st_size, iq_sha256=sha256_file(dest),
        acquisition_quality="PASSED", discontinuities=0, replay_status="FULLY_PROCESSED", created_at=utc_now(),
    )
    write_json(repository.captures_dir / f"{capture_id}.json", capture.model_dump(mode="json"))
    from app.infrastructure.ble.capture.ble_offline_replay import write_jsonl
    renamed = [e.model_copy(update={"capture_id": capture_id, "session_id": f"S-{capture_id}"}) for e in examples]
    evidence_dir = repository.evidence_dir / capture_id
    evidence_dir.mkdir(parents=True, exist_ok=True)
    write_jsonl(evidence_dir / "examples.jsonl", [e.model_dump(mode="json") for e in renamed])
    write_jsonl(evidence_dir / "annotations.jsonl", [])
    return capture_id


def test_build_dataset_rejects_mixed_data_origins(repository, tmp_path):
    real_id = _write_capture(repository, tmp_path, "CAP-REAL", "REAL_B200")
    synthetic_id = _write_capture(repository, tmp_path, "CAP-SYNTH", "SYNTHETIC_TEST_ONLY")

    with pytest.raises(ValueError, match="CANNOT_MIX_DATA_ORIGINS"):
        repository.build_dataset(dataset_id="MIXED-DS", dataset_version="1.0.0", project_id="P1", campaign_id="C1", capture_ids=[real_id, synthetic_id])


def test_build_dataset_deduplicates_a_repeated_capture_id_instead_of_double_counting_its_examples(repository, tmp_path):
    # A real, observed bug: the Guided UI could feed the same capture_id
    # into capture_ids more than once (e.g. clicking "Usar N captura(s)
    # real(es)" twice with an overlapping selection). Without deduplication,
    # every one of that capture's examples becomes its own "exact duplicate"
    # group at quality-gate time -- a dataset that looks broken but is
    # actually just the same evidence counted twice.
    real_id = _write_capture(repository, tmp_path, "CAP-REPEATED", "REAL_B200", examples_per_session=6)
    result = repository.build_dataset(dataset_id="DEDUP-DS", dataset_version="1.0.0", project_id="P1", campaign_id="C1", capture_ids=[real_id, real_id, real_id])
    dataset = result["dataset"]
    assert dataset.captures == [real_id]
    assert len(dataset.example_ids) == len(set(dataset.example_ids))
    assert result["n_selected"] == 6

    report = repository.build_quality_report(dataset_id="DEDUP-DS", dataset_version="1.0.0")
    assert report.exact_duplicates.status == "PASSED"
    assert report.gate_decision == "ACCEPTED_FOR_TRAINING"


def test_build_dataset_records_the_real_data_origin(repository, tmp_path):
    real_id = _write_capture(repository, tmp_path, "CAP-REAL-2", "REAL_B200")
    result = repository.build_dataset(dataset_id="REAL-DS", dataset_version="1.0.0", project_id="P1", campaign_id="C1", capture_ids=[real_id])
    assert result["dataset"].data_origin == "REAL_B200"


def test_build_dataset_records_the_synthetic_data_origin(repository, tmp_path):
    synthetic_id = _write_capture(repository, tmp_path, "CAP-SYNTH-2", "SYNTHETIC_TEST_ONLY")
    result = repository.build_dataset(dataset_id="SYN-DS-2", dataset_version="1.0.0", project_id="P1", campaign_id="C1", capture_ids=[synthetic_id])
    assert result["dataset"].data_origin == "SYNTHETIC_TEST_ONLY"


def test_run_training_refuses_a_training_run_whose_declared_origin_does_not_match_the_dataset(repository, tmp_path):
    synthetic_id = _write_capture(repository, tmp_path, "CAP-SYNTH-3", "SYNTHETIC_TEST_ONLY", examples_per_session=20)
    result = repository.build_dataset(dataset_id="SYN-DS-3", dataset_version="1.0.0", project_id="P1", campaign_id="C1", capture_ids=[synthetic_id])
    dataset = result["dataset"]

    mismatched_run = TrainingRun(
        training_run_id="run-mismatch", project_id="P1", campaign_id="C1", dataset_id="SYN-DS-3", dataset_version="1.0.0",
        dataset_manifest_sha256=dataset.dataset_manifest_sha256 or "", split_manifest_sha256="irrelevant",
        scientific_task="SAME_MODEL_UNIT_IDENTIFICATION", model_type="logistic_regression",
        data_origin="REAL_B200", operational_use="ALLOWED",  # lies about the dataset's real origin
        base_preprocessing_profile_id="base-v1", representation_profile_id="feature_vector-v1", random_seed=0,
    )
    with pytest.raises(ValueError, match="TRAINING_RUN_DATA_ORIGIN_MISMATCH"):
        repository.run_training(training_run=mismatched_run)


def test_build_dataset_rejects_a_capture_recorded_under_a_different_project(repository, tmp_path):
    # The reviewer's explicit "no debe utilizar capturas... de otro proyecto"
    # requirement: a capture actually recorded under project_id="OTHER-PROJECT"
    # must never silently end up inside a dataset declared for project_id="P1".
    own_project_capture = _write_capture(repository, tmp_path, "CAP-OWN-PROJECT", "SYNTHETIC_TEST_ONLY", project_id="P1")
    other_project_capture = _write_capture(repository, tmp_path, "CAP-OTHER-PROJECT", "SYNTHETIC_TEST_ONLY", project_id="OTHER-PROJECT")

    with pytest.raises(ValueError, match="CAPTURE_PROJECT_MISMATCH"):
        repository.build_dataset(dataset_id="CROSS-PROJECT-DS", dataset_version="1.0.0", project_id="P1", campaign_id="C1", capture_ids=[own_project_capture, other_project_capture])
