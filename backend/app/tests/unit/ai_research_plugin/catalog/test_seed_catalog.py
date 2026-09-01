from __future__ import annotations

from app.modules.ai_research_plugin.catalog.contracts import CatalogEntryKind, CatalogStatus
from app.modules.ai_research_plugin.catalog.seed_catalog import curated_catalog_entries


def test_every_curated_entry_has_a_unique_id():
    entries = curated_catalog_entries()
    ids = [entry.id for entry in entries]
    assert len(ids) == len(set(ids))
    assert len(entries) >= 14


def test_dataset_entries_are_never_presented_as_downloadable_models():
    entries = curated_catalog_entries()
    dataset_entries = [entry for entry in entries if entry.kind == CatalogEntryKind.DATASET]
    assert len(dataset_entries) >= 1
    for entry in dataset_entries:
        assert entry.conversion_status == CatalogStatus.DATASET_ONLY
        assert entry.onnx_available is False


def test_ready_entries_really_have_onnx_available():
    entries = curated_catalog_entries()
    ready_entries = [entry for entry in entries if entry.conversion_status == CatalogStatus.READY]
    assert len(ready_entries) >= 3
    for entry in ready_entries:
        assert entry.onnx_available is True


def test_unverified_entry_is_explicitly_flagged_and_never_marked_ready():
    entries = curated_catalog_entries()
    unverified = [entry for entry in entries if entry.independently_verified is False]
    assert len(unverified) >= 1
    for entry in unverified:
        assert entry.conversion_status != CatalogStatus.READY
        assert entry.notes


def test_no_entry_invents_classes_it_does_not_have_evidence_for():
    entries = curated_catalog_entries()
    # A foundation model with no confirmed downstream head must not carry
    # a fabricated class list.
    foundation_entries = [entry for entry in entries if entry.task.value == "FOUNDATION_MODEL"]
    assert len(foundation_entries) >= 2
    for entry in foundation_entries:
        assert entry.classes is None
