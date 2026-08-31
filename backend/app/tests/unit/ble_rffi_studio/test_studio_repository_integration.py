"""Integration tests for the API layer's StudioRepository/StudioJobManager --
the same code every HTTP route calls. (FastAPI's TestClient needs an httpx
build this environment doesn't have -- see the compiled router-construction
smoke test in test_studio_routes_smoke.py for HTTP wiring; correctness lives
here, at the layer the routes are a thin pass-through over.)

Part A exercises the REAL capture end to end: register unit -> bind address
-> build capture -> build evidence (direct call, then again via the
background job manager) -> build dataset -> quality gate -> split (honestly
NOT_FEASIBLE, one session).

Part B seeds a synthetic multi-unit/multi-session capture set directly into
the repository's own storage (bypassing the legacy B200 capture pipeline,
which only the real capture exercises) to drive dataset -> READY split ->
training -> evaluation -> export -> offline inference through the exact
StudioRepository methods the routes call.
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from app.infrastructure.ble.capture.ble_offline_replay import sha256_file, utc_now, write_json, write_jsonl
from app.modules.ble_rffi_studio.api import StudioJobManager, StudioRepository
from app.modules.ble_rffi_studio.contracts import CaptureRecord, TrainingRun

from ._helpers import write_synthetic_capture_iq

STORAGE_ROOT = Path(__file__).resolve().parents[3] / "infrastructure" / "persistence" / "storage"
REAL_CAPTURE_ROOT = STORAGE_ROOT / "ble" / "iq_captures"
REAL_SESSION_ROOT = STORAGE_ROOT / "ble_lab" / "sessions"
REAL_CAPTURE_ID = "BLE-IQ-e8edc49b59a0"
PROJECT_ID = "BLE-RFFI-CC2650"

pytestmark = pytest.mark.skipif(not (REAL_CAPTURE_ROOT / REAL_CAPTURE_ID).is_dir(), reason="real capture fixture not present in this environment")


@pytest.fixture
def repository(tmp_path):
    return StudioRepository(tmp_path / "studio", legacy_capture_root=REAL_CAPTURE_ROOT, legacy_session_root=REAL_SESSION_ROOT)


def test_real_capture_golden_path_through_the_repository(repository):
    unit = repository.register_physical_unit(physical_unit_id="CC2650-UNIT-01", project_id=PROJECT_ID, device_family="TI_SENSOR_TAG", manufacturer="Texas Instruments", model="CC2650", operator_declaration_id="decl-1")
    assert unit.physical_unit_id == "CC2650-UNIT-01"
    binding = repository.declare_binding(project_id=PROJECT_ID, address="B0:B4:48:C0:36:06", address_type="public", physical_unit_id="CC2650-UNIT-01", reason="Operator declares factory address", decision_artifact_id="decl-1")
    assert binding.bound_physical_unit_id == "CC2650-UNIT-01"
    assert repository.list_physical_units() == [unit]
    assert len(repository.list_bindings()) == 1

    legacy = repository.list_legacy_captures()
    assert any(row["capture_id"] == REAL_CAPTURE_ID for row in legacy["captures"])
    row_before_evidence = next(row for row in legacy["captures"] if row["capture_id"] == REAL_CAPTURE_ID)
    assert row_before_evidence["device_source"] == "NOT_ANALYZED"

    capture = repository.build_capture(capture_id=REAL_CAPTURE_ID, project_id=PROJECT_ID, campaign_id="CC2650-CAMPAIGN-01")
    assert repository.get_capture(REAL_CAPTURE_ID) == capture
    assert repository.list_captures() == [capture]

    summary = repository.build_evidence(capture=capture, project_id=PROJECT_ID, ble_channel=37)
    assert summary["n_examples"] == 539
    examples = repository.list_examples(REAL_CAPTURE_ID)
    annotations = repository.list_annotations(REAL_CAPTURE_ID)
    assert len(examples) == len(annotations) == 539
    assert repository.has_evidence(REAL_CAPTURE_ID)

    # The capture picker must now identify this recording as the real unit's,
    # not leave the operator guessing from an opaque capture_id.
    row_after_evidence = next(row for row in repository.list_legacy_captures()["captures"] if row["capture_id"] == REAL_CAPTURE_ID)
    assert row_after_evidence["device_source"] == "ADDRESS_MATCH"
    assert "CC2650-UNIT-01" in row_after_evidence["device_label"]

    result = repository.build_dataset(dataset_id="BLE-RFFI-CC2650-DS01", dataset_version="1.0.0", project_id=PROJECT_ID, campaign_id="CC2650-CAMPAIGN-01", capture_ids=[REAL_CAPTURE_ID])
    dataset = result["dataset"]
    assert dataset.frozen is True
    assert repository.get_dataset("BLE-RFFI-CC2650-DS01", "1.0.0") == dataset

    report = repository.build_quality_report(dataset_id="BLE-RFFI-CC2650-DS01", dataset_version="1.0.0")
    assert report.gate_decision == "ACCEPTED_FOR_TRAINING"
    assert repository.get_quality_report("BLE-RFFI-CC2650-DS01", "1.0.0") == report

    split = repository.build_split(dataset_id="BLE-RFFI-CC2650-DS01", dataset_version="1.0.0", scientific_task="SAME_MODEL_UNIT_IDENTIFICATION")
    assert split.split_status == "NOT_FEASIBLE"  # honest: one physical unit, one session
    assert repository.get_split("BLE-RFFI-CC2650-DS01", "1.0.0", "SAME_MODEL_UNIT_IDENTIFICATION") == split


def test_device_label_is_isolation_declared_when_the_capture_says_so(repository):
    repository.build_capture(
        capture_id=REAL_CAPTURE_ID, project_id=PROJECT_ID, campaign_id="CC2650-CAMPAIGN-01",
        isolation_declared_physical_unit_id="SOME-OTHER-UNIT",
    )
    row = next(row for row in repository.list_legacy_captures()["captures"] if row["capture_id"] == REAL_CAPTURE_ID)
    assert row["device_source"] == "ISOLATION_DECLARED"
    assert "SOME-OTHER-UNIT" in row["device_label"]


def test_device_label_is_environment_when_evidence_matches_no_registered_unit(repository):
    # No physical unit registered anywhere in this project -- every example's
    # address lookup comes back empty, so the capture is real environmental
    # noise, not a specific device's recording.
    capture = repository.build_capture(capture_id=REAL_CAPTURE_ID, project_id="EMPTY-PROJECT", campaign_id="CC2650-CAMPAIGN-01")
    repository.build_evidence(capture=capture, project_id="EMPTY-PROJECT", ble_channel=37)
    row = next(row for row in repository.list_legacy_captures()["captures"] if row["capture_id"] == REAL_CAPTURE_ID)
    assert row["device_source"] == "ENVIRONMENT_NO_MATCH"
    assert "Entorno" in row["device_label"]


def test_capture_type_label_is_unclassified_before_any_capturerecord_exists(repository):
    row = next(row for row in repository.list_legacy_captures()["captures"] if row["capture_id"] == REAL_CAPTURE_ID)
    assert row["capture_type_label"] == "Sin clasificar"
    assert row["capture_decision"] == "NOT_ANALYZED_YET"


def test_capture_type_label_and_decision_for_a_target_device_capture(repository):
    repository.register_physical_unit(physical_unit_id="CC2650-UNIT-01", project_id=PROJECT_ID, device_family="TI_SENSOR_TAG", operator_declaration_id="decl-1")
    repository.declare_binding(project_id=PROJECT_ID, address="B0:B4:48:C0:36:06", address_type="public", physical_unit_id="CC2650-UNIT-01", reason="test", decision_artifact_id="decl-1")
    capture = repository.build_capture(
        capture_id=REAL_CAPTURE_ID, project_id=PROJECT_ID, campaign_id="CC2650-CAMPAIGN-01",
        capture_purpose="TARGET_DEVICE_ON", target_state="POWERED_ON",
        target_reference_id="CC2650-UNIT-01", dataset_role="POSITIVE_CANDIDATE",
    )

    # Before evidence exists, the type is already known from the declared
    # purpose, but the decision honestly still says nothing has been analyzed.
    row = next(row for row in repository.list_legacy_captures()["captures"] if row["capture_id"] == REAL_CAPTURE_ID)
    assert row["capture_type_label"] == "Dispositivo encendido"
    assert row["capture_decision"] == "NOT_ANALYZED_YET"

    repository.build_evidence(capture=capture, project_id=PROJECT_ID, ble_channel=37)
    row = next(row for row in repository.list_legacy_captures()["captures"] if row["capture_id"] == REAL_CAPTURE_ID)
    assert row["capture_type_label"] == "Dispositivo encendido"
    assert row["capture_decision"] == "ELIGIBLE_AS_POSITIVE"  # the real address-matched packets are still includable


def test_capture_type_label_and_decision_for_a_background_general_capture(repository):
    # No specific unit in question at all -- BACKGROUND_GENERAL, not
    # BACKGROUND_TARGET_OFF-without-a-reference (a genuinely different
    # capture_purpose value, not the same intent minus one optional field).
    capture = repository.build_capture(
        capture_id=REAL_CAPTURE_ID, project_id="EMPTY-PROJECT", campaign_id="CC2650-CAMPAIGN-01",
        capture_purpose="BACKGROUND_GENERAL", dataset_role="NEGATIVE_CANDIDATE",
    )
    repository.build_evidence(capture=capture, project_id="EMPTY-PROJECT", ble_channel=37)
    row = next(row for row in repository.list_legacy_captures()["captures"] if row["capture_id"] == REAL_CAPTURE_ID)
    assert row["capture_type_label"] == "Entorno general"
    assert row["capture_decision"] == "ELIGIBLE_AS_BACKGROUND"
    assert row["target_presence_status"] == "NOT_APPLICABLE"


def test_capture_type_label_and_decision_for_a_background_target_off_capture_with_a_contradicted_unit(repository):
    # The declared-off unit's own real address is registered here, so every
    # one of its packets is a genuine contradiction: the target actually
    # showed up while declared off/removed. This must quarantine the whole
    # capture-level verdict -- never silently treated as good evidence just
    # because other, genuinely unrelated background traffic also exists in
    # the same capture (the exact original bug: a real contradiction hiding
    # behind unrelated clean data elsewhere in the same recording).
    repository.register_physical_unit(physical_unit_id="CC2650-UNIT-01", project_id=PROJECT_ID, device_family="TI_SENSOR_TAG", operator_declaration_id="decl-1")
    repository.declare_binding(project_id=PROJECT_ID, address="B0:B4:48:C0:36:06", address_type="public", physical_unit_id="CC2650-UNIT-01", reason="test", decision_artifact_id="decl-1")
    capture = repository.build_capture(
        capture_id=REAL_CAPTURE_ID, project_id=PROJECT_ID, campaign_id="CC2650-CAMPAIGN-01",
        capture_purpose="BACKGROUND_TARGET_OFF", target_state="OPERATOR_DECLARED_POWERED_OFF_OR_REMOVED",
        target_reference_id="CC2650-UNIT-01", dataset_role="NEGATIVE_CANDIDATE",
    )
    repository.build_evidence(capture=capture, project_id=PROJECT_ID, ble_channel=37)
    row = next(row for row in repository.list_legacy_captures()["captures"] if row["capture_id"] == REAL_CAPTURE_ID)
    assert row["capture_type_label"] == "Entorno -- dispositivo apagado"
    assert row["capture_decision"] == "QUARANTINED"
    assert row["target_presence_status"] == "DETECTED"


def test_evidence_job_manager_matches_the_direct_call(repository, tmp_path):
    repository.register_physical_unit(physical_unit_id="CC2650-UNIT-01", project_id=PROJECT_ID, device_family="TI_SENSOR_TAG", operator_declaration_id="decl-1")
    repository.declare_binding(project_id=PROJECT_ID, address="B0:B4:48:C0:36:06", address_type="public", physical_unit_id="CC2650-UNIT-01", reason="test", decision_artifact_id="decl-1")
    repository.build_capture(capture_id=REAL_CAPTURE_ID, project_id=PROJECT_ID, campaign_id="CC2650-CAMPAIGN-01")

    job_manager = StudioJobManager(repository, tmp_path / "jobs")
    job = job_manager.start_evidence_job(capture_id=REAL_CAPTURE_ID, project_id=PROJECT_ID, ble_channel=37)
    job_id = job["job_id"]
    assert job_id.startswith("BLE-RFFI-STUDIO-JOB-")

    deadline = time.time() + 30
    while job_manager.get_job(job_id)["state"] not in ("completed", "failed"):
        if time.time() > deadline:
            pytest.fail("evidence job did not terminate in time")
        time.sleep(0.2)

    final = job_manager.get_job(job_id)
    assert final["state"] == "completed"
    assert final["result_summary"]["n_examples"] == 539
    assert len(repository.list_examples(REAL_CAPTURE_ID)) == 539


# ---------------------------------------------------------------------------
# Synthetic multi-unit path: dataset -> READY split -> training -> evaluation
# -> export -> offline inference, seeded directly (no legacy B200 tree).
# ---------------------------------------------------------------------------

def _seed_synthetic_capture(repository: StudioRepository, tmp_path: Path):
    raw_iq_dir = tmp_path / "raw_iq"
    raw_iq_dir.mkdir(parents=True, exist_ok=True)
    examples, iq_paths = write_synthetic_capture_iq(raw_iq_dir, units=2, sessions_per_unit=3, examples_per_session=10)
    by_capture: dict[str, list] = {}
    for example in examples:
        by_capture.setdefault(example.capture_id, []).append(example)

    for capture_id, capture_examples in by_capture.items():
        capture_dir = repository.legacy_capture_root / capture_id
        capture_dir.mkdir(parents=True, exist_ok=True)
        src = iq_paths[capture_id]
        dest = capture_dir / "iq.cf32"
        dest.write_bytes(src.read_bytes())
        capture = CaptureRecord(
            project_id="SYN-PROJECT", campaign_id="SYN-CAMPAIGN-01", capture_id=capture_id, session_id=capture_examples[0].session_id,
            execution_id=f"EXEC-{capture_id}", data_origin="SYNTHETIC_TEST_ONLY", receiver_device_id="synthetic", sdr_model="synthetic", rx_channel="RX2", antenna_port="RX2",
            sample_rate_sps=4_000_000, sample_dtype="cf32_le", byte_order="little_endian", sample_count=1_000_000, channel_count=1,
            center_frequency_hz=2_402_000_000, frontend_bandwidth_hz=2_000_000, effective_bandwidth_hz=2_000_000, gain_db=20.0, gain_mode="manual",
            capture_duration_s=1.0, capture_tool="synthetic", iq_path="iq.cf32", iq_size_bytes=dest.stat().st_size, iq_sha256=sha256_file(dest),
            acquisition_quality="PASSED", discontinuities=0, replay_status="FULLY_PROCESSED", created_at=utc_now(),
        )
        write_json(repository.captures_dir / f"{capture_id}.json", capture.model_dump(mode="json"))
        capture_evidence_dir = repository.evidence_dir / capture_id
        capture_evidence_dir.mkdir(parents=True, exist_ok=True)
        write_jsonl(capture_evidence_dir / "examples.jsonl", [e.model_dump(mode="json") for e in capture_examples])
        write_jsonl(capture_evidence_dir / "annotations.jsonl", [])

    return list(by_capture.keys())


@pytest.fixture
def synthetic_repository(tmp_path):
    return StudioRepository(tmp_path / "studio", legacy_capture_root=tmp_path / "legacy_captures", legacy_session_root=tmp_path / "legacy_sessions")


def test_synthetic_multi_unit_full_pipeline_through_the_repository(synthetic_repository, tmp_path):
    repository = synthetic_repository
    capture_ids = _seed_synthetic_capture(repository, tmp_path)

    result = repository.build_dataset(dataset_id="SYN-DS", dataset_version="1.0.0", project_id="SYN-PROJECT", campaign_id="SYN-CAMPAIGN-01", capture_ids=capture_ids)
    dataset = result["dataset"]
    assert dataset.frozen

    report = repository.build_quality_report(dataset_id="SYN-DS", dataset_version="1.0.0")
    assert report.gate_decision == "ACCEPTED_FOR_TRAINING"

    split = repository.build_split(dataset_id="SYN-DS", dataset_version="1.0.0", scientific_task="SAME_MODEL_UNIT_IDENTIFICATION")
    assert split.split_status == "READY"

    assert dataset.data_origin == "SYNTHETIC_TEST_ONLY"  # this fixture's whole point
    training_run = TrainingRun(
        training_run_id="run-syn-1", project_id="SYN-PROJECT", campaign_id="SYN-CAMPAIGN-01",
        dataset_id="SYN-DS", dataset_version="1.0.0", dataset_manifest_sha256=dataset.dataset_manifest_sha256, split_manifest_sha256=split.split_manifest_sha256,
        scientific_task="SAME_MODEL_UNIT_IDENTIFICATION", model_type="logistic_regression",
        data_origin=dataset.data_origin, operational_use="FORBIDDEN", base_preprocessing_profile_id="base-v1", representation_profile_id="feature_vector-v1", random_seed=0,
    )
    completed = repository.run_training(training_run=training_run)
    assert completed.status == "COMPLETED"

    stored = repository.get_training_run("run-syn-1")
    assert stored["status"] == "COMPLETED"
    assert stored["metrics"]["TEST"]["accuracy"] > 0.5
    assert [row["training_run_id"] for row in repository.list_training_runs()] == ["run-syn-1"]

    evaluation = repository.evaluate_training_run("run-syn-1", min_identified_precision=0.7, include_test=True)
    assert set(evaluation["evaluation_report"].keys()) == {"TRAIN", "VALIDATION", "TEST"}
    assert evaluation["calibration"]["acceptance_threshold"] is not None
    assert repository.get_evaluation("run-syn-1") is not None

    manifest, reasons = repository.export_bundle(training_run_id="run-syn-1", bundle_id="bundle-syn-1", acceptance_criteria={"min_test_accuracy": 0.5}, model_card_text="# Synthetic test bundle")
    # A synthetic-origin bundle proves the software pipeline works, nothing
    # about physical RFFI capability -- it can never reach EVALUATED/
    # APPROVED_FOR_LIVE_PILOT, only this explicit, lower ceiling.
    assert manifest.approval_status == "SYNTHETIC_PIPELINE_VERIFIED"
    assert manifest.data_origin == "SYNTHETIC_TEST_ONLY"
    assert manifest.operational_use == "FORBIDDEN"
    assert reasons == []
    assert repository.get_bundle("bundle-syn-1") == manifest
    assert repository.list_bundles() == [manifest]

    with pytest.raises(ValueError, match="CANNOT_APPROVE_A_SYNTHETIC_ORIGIN_BUNDLE"):
        repository.approve_bundle("bundle-syn-1")

    decisions = repository.run_inference(bundle_id="bundle-syn-1", capture_id=capture_ids[0])
    assert decisions
    assert all(d["final_decision"] in ("IDENTIFIED", "UNKNOWN", "INSUFFICIENT_EVIDENCE") for d in decisions)

    # Inference-provenance correction (2026-08-08): run_inference's public
    # return shape (a bare list of decisions) is unchanged, but a real,
    # persisted manifest binding this run to the bundle's content hash and
    # the source capture's real iq_sha256 must now exist on disk.
    runs = repository.list_inference_runs()
    assert len(runs) == 1
    run = runs[0]
    assert run["bundle_id"] == "bundle-syn-1"
    assert run["bundle_sha256"] == manifest.bundle_sha256
    assert run["source_capture_ids"] == [capture_ids[0]]
    real_capture = repository.get_capture(capture_ids[0])
    assert run["source_iq_sha256_by_capture_id"][capture_ids[0]] == real_capture.iq_sha256
    assert repository.get_inference_run(run["inference_run_id"]) == run


def test_training_job_manager_persists_a_completed_run(synthetic_repository, tmp_path):
    repository = synthetic_repository
    capture_ids = _seed_synthetic_capture(repository, tmp_path)
    result = repository.build_dataset(dataset_id="SYN-DS", dataset_version="1.0.0", project_id="SYN-PROJECT", campaign_id="SYN-CAMPAIGN-01", capture_ids=capture_ids)
    dataset = result["dataset"]
    split = repository.build_split(dataset_id="SYN-DS", dataset_version="1.0.0", scientific_task="SAME_MODEL_UNIT_IDENTIFICATION")
    assert split.split_status == "READY"

    training_run = TrainingRun(
        training_run_id="run-syn-job", project_id="SYN-PROJECT", campaign_id="SYN-CAMPAIGN-01",
        dataset_id="SYN-DS", dataset_version="1.0.0", dataset_manifest_sha256=dataset.dataset_manifest_sha256, split_manifest_sha256=split.split_manifest_sha256,
        scientific_task="SAME_MODEL_UNIT_IDENTIFICATION", model_type="logistic_regression",
        data_origin=dataset.data_origin, operational_use="FORBIDDEN", base_preprocessing_profile_id="base-v1", representation_profile_id="feature_vector-v1", random_seed=0,
    )
    job_manager = StudioJobManager(repository, tmp_path / "jobs")
    job = job_manager.start_training_job(training_run=training_run)
    deadline = time.time() + 30
    while job_manager.get_job(job["job_id"])["state"] not in ("completed", "failed"):
        if time.time() > deadline:
            pytest.fail("training job did not terminate in time")
        time.sleep(0.2)
    final = job_manager.get_job(job["job_id"])
    assert final["state"] == "completed"
    assert repository.get_training_run("run-syn-job")["status"] == "COMPLETED"
