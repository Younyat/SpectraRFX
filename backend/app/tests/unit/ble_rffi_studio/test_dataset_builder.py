from __future__ import annotations

import pytest

from app.modules.ble_rffi_studio.dataset import DatasetBuilder

from ._helpers import make_example


@pytest.fixture
def builder(tmp_path):
    return DatasetBuilder(tmp_path / "datasets")


def test_select_examples_excludes_quarantined_and_failed_quality(builder):
    ok = make_example(example_index=1, physical_unit_id="U1", session_id="S1", dataset_eligibility="PENDING_ANALYSIS", quality_status="PASSED")
    quarantined = make_example(example_index=2, physical_unit_id=None, session_id="S1", dataset_eligibility="QUARANTINED", quality_status="PASSED")
    bad_quality = make_example(example_index=3, physical_unit_id="U1", session_id="S1", dataset_eligibility="PENDING_ANALYSIS", quality_status="FAILED")

    selected, excluded = builder.select_examples([ok, quarantined, bad_quality])

    assert [e.example_id for e in selected] == [ok.example_id]
    assert excluded[quarantined.example_id] == "DATASET_ELIGIBILITY_QUARANTINED"
    assert excluded[bad_quality.example_id] == "QUALITY_STATUS_FAILED"


def test_build_draft_computes_class_distribution_and_membership(builder):
    examples = [
        make_example(example_index=1, physical_unit_id="U1", session_id="S1"),
        make_example(example_index=2, physical_unit_id="U1", session_id="S1"),
        make_example(example_index=3, physical_unit_id=None, session_id="S1"),
    ]
    draft = builder.build_draft(
        dataset_id="DS1", dataset_version="1.0.0", project_id="P1", campaign_id="C1",
        examples=examples, data_origin="REAL_B200", creation_policy={"selection": "test"}, created_at="2026-07-26T00:00:00Z",
    )
    assert draft.frozen is False
    assert draft.dataset_manifest_sha256 is None
    assert draft.class_distribution == {"U1": 2, "UNKNOWN": 1}
    assert draft.physical_units == ["U1"]
    assert len(draft.example_ids) == 3


def test_freeze_sets_hash_and_is_one_way(builder):
    examples = [make_example(example_index=1, physical_unit_id="U1", session_id="S1")]
    draft = builder.build_draft(dataset_id="DS1", dataset_version="1.0.0", project_id="P1", campaign_id="C1", examples=examples, data_origin="REAL_B200", creation_policy={}, created_at="2026-07-26T00:00:00Z")
    frozen = builder.freeze(draft)
    assert frozen.frozen is True
    assert frozen.dataset_manifest_sha256 is not None

    with pytest.raises(ValueError):
        builder.freeze(frozen)


def test_freeze_is_deterministic_given_identical_content(builder):
    examples = [make_example(example_index=1, physical_unit_id="U1", session_id="S1")]
    draft_a = builder.build_draft(dataset_id="DS1", dataset_version="1.0.0", project_id="P1", campaign_id="C1", examples=examples, data_origin="REAL_B200", creation_policy={}, created_at="2026-07-26T00:00:00Z")
    draft_b = builder.build_draft(dataset_id="DS1", dataset_version="1.0.0", project_id="P1", campaign_id="C1", examples=examples, data_origin="REAL_B200", creation_policy={}, created_at="2026-07-26T00:00:00Z")
    assert builder.freeze(draft_a).dataset_manifest_sha256 == builder.freeze(draft_b).dataset_manifest_sha256


def test_load_round_trips_a_frozen_dataset(builder):
    examples = [make_example(example_index=1, physical_unit_id="U1", session_id="S1")]
    draft = builder.build_draft(dataset_id="DS1", dataset_version="1.0.0", project_id="P1", campaign_id="C1", examples=examples, data_origin="REAL_B200", creation_policy={}, created_at="2026-07-26T00:00:00Z")
    frozen = builder.freeze(draft)
    loaded = builder.load("DS1", "1.0.0")
    assert loaded == frozen


def test_load_unknown_dataset_is_none(builder):
    assert builder.load("NOPE", "1.0.0") is None


def test_a_changed_dataset_must_be_a_new_version_not_a_mutation(builder):
    v1_examples = [make_example(example_index=1, physical_unit_id="U1", session_id="S1")]
    v1 = builder.freeze(builder.build_draft(dataset_id="DS1", dataset_version="1.0.0", project_id="P1", campaign_id="C1", examples=v1_examples, data_origin="REAL_B200", creation_policy={}, created_at="2026-07-26T00:00:00Z"))

    v2_examples = v1_examples + [make_example(example_index=2, physical_unit_id="U1", session_id="S1")]
    v2_draft = builder.build_draft(dataset_id="DS1", dataset_version="1.1.0", project_id="P1", campaign_id="C1", examples=v2_examples, data_origin="REAL_B200", creation_policy={}, created_at="2026-07-26T00:01:00Z", derived_from="DS1@1.0.0")
    v2 = builder.freeze(v2_draft)

    assert v2.derived_from == "DS1@1.0.0"
    assert v2.dataset_manifest_sha256 != v1.dataset_manifest_sha256
    assert builder.load("DS1", "1.0.0") == v1  # v1 untouched by creating v2
