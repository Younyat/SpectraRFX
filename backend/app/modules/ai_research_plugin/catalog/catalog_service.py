from __future__ import annotations

from app.modules.ai_research_plugin.catalog.contracts import (
    CatalogFilters,
    RFModelCatalogEntry,
    apply_filters,
)
from app.modules.ai_research_plugin.catalog.huggingface_provider import (
    HuggingFaceProviderError,
    search_huggingface_models,
    to_catalog_entries,
)
from app.modules.ai_research_plugin.catalog.seed_catalog import curated_catalog_entries


class ModelCatalogService:
    def __init__(self) -> None:
        self._curated = curated_catalog_entries()

    def list_curated(self, filters: CatalogFilters | None = None) -> list[RFModelCatalogEntry]:
        entries = self._curated
        if filters is not None:
            entries = apply_filters(entries, filters)
        return entries

    def get_curated(self, entry_id: str) -> RFModelCatalogEntry | None:
        return next((entry for entry in self._curated if entry.id == entry_id), None)

    def search_huggingface(self, query: str, limit: int = 20) -> list[RFModelCatalogEntry]:
        raw_models = search_huggingface_models(query, limit=limit)
        return to_catalog_entries(raw_models)


__all__ = ["ModelCatalogService", "HuggingFaceProviderError"]
