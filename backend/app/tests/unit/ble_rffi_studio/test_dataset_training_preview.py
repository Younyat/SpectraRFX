"""dataset_training_preview(): the reviewer's explicit "pantalla de revision
antes de entrenar" -- TRAIN/VALIDATION/TEST classes, sessions per class,
examples per class and capture_ids actually used, computed strictly from the
frozen DatasetManifest and the already-built SplitManifest so these numbers
can never drift from what training itself will consume (the exact original
bug: interface showed 0 eligible examples while training used hundreds).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.infrastructure.ble.capture.ble_offline_replay import sha256_file, utc_now, write_json, write_jsonl
from app.modules.ble_rffi_studio.api import StudioRepository
from app.modules.ble_rffi_studio.contracts import CaptureRecord

from ._helpers import write_target_vs_background_fixture

PROJECT_ID = "SYN-PROJECT"


@pytest.fixture
def repository(tmp_path):
    return StudioRepository(tmp_path / "studio", legacy_capture_root=tmp_path / "legacy_captures", legacy_session_root=tmp_path / "legacy_sessions")


def _seed_target_vs_background_capture(repository: StudioRepository, tmp_path: Path, **kwargs):
    raw_iq_dir = tmp_path / "raw_iq"
    raw_iq_dir.mkdir(parents=True, exist_ok=True)
    examples, iq_paths = write_target_vs_background_fixture(raw_iq_dir, **kwargs)
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
            execution_id=f"EXEC-{capture_id}", data_origin="SYNTHETIC_TEST_ONLY", receiver_device_id="synthetic", sdr_model="synthetic", rx_channel="RX2", antenna_port="RX2",
            sample_rate_sps=4_000_000, sample_dtype="cf32_le", byte_order="little_endian", sample_count=1_000_000, channel_count=1,
            center_frequency_hz=2_402_000_000, frontend_bandwidth_hz=2_000_000, effective_bandwidth_hz=2_000_000, gain_db=20.0, gain_mode="manual",
            capture_duration_s=1.0, capture_tool="synthetic", iq_path="iq.cf32", iq_size_bytes=dest.stat().st_size, iq_sha256=sha256_file(dest),
            acquisition_quality="PASSED", discontinuities=0, replay_status="FULLY_PROCESSED", created_at=utc_now(),
            capture_purpose=capture_examples[0].capture_purpose,
        )
        write_json(repository.captures_dir / f"{capture_id}.json", capture.model_dump(mode="json"))
        capture_evidence_dir = repository.evidence_dir / capture_id
        capture_evidence_dir.mkdir(parents=True, exist_ok=True)
        write_jsonl(capture_evidence_dir / "examples.jsonl", [e.model_dump(mode="json") for e in capture_examples])
        write_jsonl(capture_evidence_dir / "annotations.jsonl", [])

    return list(by_capture.keys())


def test_preview_reports_both_classes_present_in_every_split_and_matches_the_frozen_dataset(repository, tmp_path):
    capture_ids = _seed_target_vs_background_capture(repository, tmp_path, target_sessions=3, background_sessions=3, examples_per_session=16)
    build_result = repository.build_dataset(dataset_id="TVB-DS", dataset_version="1.0.0", project_id=PROJECT_ID, campaign_id="SYN-CAMPAIGN-01", capture_ids=capture_ids)
    dataset = build_result["dataset"]
    split = repository.build_split(dataset_id="TVB-DS", dataset_version="1.0.0", scientific_task="TARGET_VS_BACKGROUND")
    assert split.split_status == "READY"

    preview = repository.dataset_training_preview(dataset_id="TVB-DS", dataset_version="1.0.0", scientific_task="TARGET_VS_BACKGROUND")

    assert preview["ready_to_train"] is True
    assert preview["quality_gate_ok"] is True
    assert preview["quality_gate_reasons"] == []
    assert preview["eligible_examples_total"] == len(dataset.example_ids)
    for split_name in ("TRAIN", "VALIDATION", "TEST"):
        assert set(preview["splits"][split_name]["classes"]) == {"TARGET_DEVICE", "BACKGROUND_ENVIRONMENT"}
        assert all(count > 0 for count in preview["splits"][split_name]["examples_by_class"].values())
        assert preview["splits"][split_name]["capture_ids"]

    # Counters must sum to exactly the frozen dataset's example count -- never
    # a different number than what training will actually see.
    total_previewed = sum(
        count
        for split_data in preview["splits"].values()
        for count in split_data["examples_by_class"].values()
    )
    assert total_previewed == len(dataset.example_ids)


def test_preview_raises_a_clear_error_when_the_split_has_not_been_built_yet(repository, tmp_path):
    capture_ids = _seed_target_vs_background_capture(repository, tmp_path, target_sessions=3, background_sessions=3, examples_per_session=16)
    repository.build_dataset(dataset_id="TVB-DS-2", dataset_version="1.0.0", project_id=PROJECT_ID, campaign_id="SYN-CAMPAIGN-01", capture_ids=capture_ids)

    with pytest.raises(FileNotFoundError, match="SPLIT_NOT_BUILT_YET"):
        repository.dataset_training_preview(dataset_id="TVB-DS-2", dataset_version="1.0.0", scientific_task="TARGET_VS_BACKGROUND")


def test_preview_reports_not_ready_and_reason_for_a_single_class_train(repository, tmp_path):
    # background_sessions=0 -- reproduces the original bug scenario: a
    # TARGET_VS_BACKGROUND split with no real environment evidence.
    capture_ids = _seed_target_vs_background_capture(repository, tmp_path, target_sessions=3, background_sessions=0, examples_per_session=16)
    repository.build_dataset(dataset_id="TVB-DS-3", dataset_version="1.0.0", project_id=PROJECT_ID, campaign_id="SYN-CAMPAIGN-01", capture_ids=capture_ids)
    split = repository.build_split(dataset_id="TVB-DS-3", dataset_version="1.0.0", scientific_task="TARGET_VS_BACKGROUND")
    assert split.split_status == "NOT_FEASIBLE"

    preview = repository.dataset_training_preview(dataset_id="TVB-DS-3", dataset_version="1.0.0", scientific_task="TARGET_VS_BACKGROUND")
    assert preview["ready_to_train"] is False
    assert preview["infeasibility_reason"]


def test_preview_is_never_ready_when_the_frozen_dataset_itself_has_exact_duplicate_examples(repository, tmp_path):
    # The reviewer's exact reported contradiction: the review said "listos
    # para entrenar" while the real quality gate (run right before training)
    # rejected the same frozen examples for duplicates. build_dataset()
    # itself now de-duplicates capture_ids (see test_data_origin_gating.py),
    # so this reconstructs a corrupted frozen DatasetManifest directly --
    # standing in for any other path that could still produce one -- to
    # prove the review catches it regardless of how it got there.
    capture_ids = _seed_target_vs_background_capture(repository, tmp_path, target_sessions=3, background_sessions=3, examples_per_session=16)
    build_result = repository.build_dataset(dataset_id="TVB-DS-4", dataset_version="1.0.0", project_id=PROJECT_ID, campaign_id="SYN-CAMPAIGN-01", capture_ids=capture_ids)
    dataset = build_result["dataset"]
    split = repository.build_split(dataset_id="TVB-DS-4", dataset_version="1.0.0", scientific_task="TARGET_VS_BACKGROUND")
    assert split.split_status == "READY"

    corrupted = dataset.model_copy(update={"example_ids": dataset.example_ids + dataset.example_ids[:5]})
    write_json(repository.dataset_builder.root / "TVB-DS-4__1.0.0.json", corrupted.model_dump(mode="json"))

    preview = repository.dataset_training_preview(dataset_id="TVB-DS-4", dataset_version="1.0.0", scientific_task="TARGET_VS_BACKGROUND")
    assert preview["quality_gate_ok"] is False
    assert preview["ready_to_train"] is False
    assert any("exact-duplicate" in reason for reason in preview["quality_gate_reasons"])
