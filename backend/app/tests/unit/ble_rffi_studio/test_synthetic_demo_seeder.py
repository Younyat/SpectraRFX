"""SYNTHETIC_DEMO seeding: the only way to exercise the READY-split path
without SDR hardware. Every id it produces is clearly prefixed/labeled so it
can never be mistaken for a real capture downstream.
"""
from __future__ import annotations

import pytest

from app.modules.ble_rffi_studio.api import StudioRepository
from app.modules.ble_rffi_studio.demo import DEMO_CAMPAIGN_ID, DEMO_PROJECT_ID


@pytest.fixture
def repository(tmp_path):
    return StudioRepository(tmp_path / "studio", legacy_capture_root=tmp_path / "legacy_captures", legacy_session_root=tmp_path / "legacy_sessions")


def test_seed_synthetic_demo_produces_labeled_captures_and_evidence(repository):
    result = repository.seed_synthetic_demo()

    assert result["project_id"] == DEMO_PROJECT_ID == "SYNTHETIC_DEMO"
    assert result["campaign_id"] == DEMO_CAMPAIGN_ID
    assert len(result["capture_ids"]) == 2 * 3  # 2 units x 3 sessions by default
    assert all(cid.startswith("SYNTHETIC-CAP-") for cid in result["capture_ids"])
    assert all(uid.startswith("SYNTHETIC-UNIT-") for uid in result["physical_unit_ids"])

    for capture_id in result["capture_ids"]:
        capture = repository.get_capture(capture_id)
        assert capture is not None
        assert capture.project_id == DEMO_PROJECT_ID
        examples = repository.list_examples(capture_id)
        assert len(examples) == 12  # default examples_per_session
        assert all(e.project_id == DEMO_PROJECT_ID for e in examples)


def test_seeded_demo_feeds_prepare_and_train_to_a_ready_split(repository):
    seeded = repository.seed_synthetic_demo()

    result = repository.prepare_and_train(
        capture_ids=seeded["capture_ids"], project_id=seeded["project_id"], campaign_id=seeded["campaign_id"],
        scientific_task="SAME_MODEL_UNIT_IDENTIFICATION", dataset_id="SYNTHETIC-DEMO-DS", speed_profile="quick_pilot",
    )

    assert result["stopped_at"] is None
    assert result["split"].split_status == "READY"
    assert result["recommended_training_run_id"] is not None
