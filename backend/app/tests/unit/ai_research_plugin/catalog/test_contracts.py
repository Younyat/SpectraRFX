from __future__ import annotations

from app.modules.ai_research_plugin.catalog.contracts import (
    CatalogEntryKind,
    CatalogFilters,
    CatalogTask,
    RFModelCatalogEntry,
    apply_filters,
)


def _entry(**overrides) -> RFModelCatalogEntry:
    defaults = dict(id="X", name="X", kind=CatalogEntryKind.MODEL, provider="p", source_url="https://x")
    defaults.update(overrides)
    return RFModelCatalogEntry(**defaults)


def test_apply_filters_with_no_filters_returns_everything():
    entries = [_entry(id="a"), _entry(id="b")]
    assert apply_filters(entries, CatalogFilters()) == entries


def test_apply_filters_by_task():
    entries = [
        _entry(id="a", task=CatalogTask.MODULATION_CLASSIFICATION),
        _entry(id="b", task=CatalogTask.RF_FINGERPRINTING),
    ]
    result = apply_filters(entries, CatalogFilters(task=CatalogTask.RF_FINGERPRINTING))
    assert [entry.id for entry in result] == ["b"]


def test_apply_filters_by_onnx_available():
    entries = [_entry(id="a", onnx_available=True), _entry(id="b", onnx_available=False)]
    result = apply_filters(entries, CatalogFilters(onnx_available=True))
    assert [entry.id for entry in result] == ["a"]


def test_apply_filters_by_kind_excludes_datasets():
    entries = [_entry(id="a", kind=CatalogEntryKind.MODEL), _entry(id="b", kind=CatalogEntryKind.DATASET)]
    result = apply_filters(entries, CatalogFilters(kind=CatalogEntryKind.MODEL))
    assert [entry.id for entry in result] == ["a"]


def test_apply_filters_combines_multiple_conditions():
    entries = [
        _entry(id="a", task=CatalogTask.RF_FINGERPRINTING, onnx_available=True),
        _entry(id="b", task=CatalogTask.RF_FINGERPRINTING, onnx_available=False),
        _entry(id="c", task=CatalogTask.MODULATION_CLASSIFICATION, onnx_available=True),
    ]
    result = apply_filters(entries, CatalogFilters(task=CatalogTask.RF_FINGERPRINTING, onnx_available=True))
    assert [entry.id for entry in result] == ["a"]
