from __future__ import annotations

import pytest

from app.modules.ai_research_plugin.catalog import catalog_service as catalog_service_module
from app.modules.ai_research_plugin.catalog.catalog_service import HuggingFaceProviderError, ModelCatalogService
from app.modules.ai_research_plugin.catalog.contracts import CatalogFilters, CatalogTask


def test_list_curated_returns_the_real_seed_catalog():
    service = ModelCatalogService()
    entries = service.list_curated()
    assert len(entries) >= 14
    assert any(entry.id == "CATALOG-MT-PREAMCNN" for entry in entries)


def test_list_curated_applies_filters():
    service = ModelCatalogService()
    entries = service.list_curated(CatalogFilters(task=CatalogTask.RF_FINGERPRINTING))
    assert len(entries) >= 1
    assert all(entry.task == CatalogTask.RF_FINGERPRINTING for entry in entries)


def test_get_curated_returns_none_for_unknown_id():
    service = ModelCatalogService()
    assert service.get_curated("does-not-exist") is None


def test_get_curated_returns_the_matching_entry():
    service = ModelCatalogService()
    entry = service.get_curated("CATALOG-BACALHAUNET")
    assert entry is not None
    assert entry.name == "BacalhauNet"


def test_search_huggingface_delegates_to_the_live_provider(monkeypatch):
    calls = []

    def fake_search(query, limit=20):
        calls.append((query, limit))
        return [{"id": "org/model", "siblings": [{"rfilename": "model.onnx"}]}]

    monkeypatch.setattr(catalog_service_module, "search_huggingface_models", fake_search)
    service = ModelCatalogService()

    entries = service.search_huggingface("rf fingerprint", limit=5)

    assert calls == [("rf fingerprint", 5)]
    assert len(entries) == 1
    assert entries[0].name == "org/model"


def test_search_huggingface_propagates_provider_errors(monkeypatch):
    def fake_search(query, limit=20):
        raise HuggingFaceProviderError("network down")

    monkeypatch.setattr(catalog_service_module, "search_huggingface_models", fake_search)
    service = ModelCatalogService()

    with pytest.raises(HuggingFaceProviderError):
        service.search_huggingface("rf")
