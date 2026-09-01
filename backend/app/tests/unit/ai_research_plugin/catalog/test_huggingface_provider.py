from __future__ import annotations

from app.modules.ai_research_plugin.catalog.contracts import CatalogOriginalFormat, CatalogSourceKind, CatalogStatus
from app.modules.ai_research_plugin.catalog.huggingface_provider import to_catalog_entries


def test_to_catalog_entries_skips_models_with_no_id():
    assert to_catalog_entries([{"siblings": []}]) == []


def test_to_catalog_entries_detects_onnx_and_marks_ready():
    raw = [{
        "id": "some-org/rf-model",
        "siblings": [{"rfilename": "model.onnx"}, {"rfilename": "README.md"}],
        "cardData": {"license": "mit"},
    }]
    entries = to_catalog_entries(raw)
    assert len(entries) == 1
    entry = entries[0]
    assert entry.id == "HF-LIVE-some-org--rf-model"
    assert entry.source_url == "https://huggingface.co/some-org/rf-model"
    assert entry.onnx_available is True
    assert entry.original_format == CatalogOriginalFormat.ONNX
    assert entry.conversion_status == CatalogStatus.READY
    assert entry.license == "mit"
    assert entry.source_kind == CatalogSourceKind.HUGGINGFACE_LIVE
    assert entry.independently_verified is False


def test_to_catalog_entries_without_onnx_but_with_pytorch_weights_needs_conversion():
    raw = [{"id": "org/model-pt", "siblings": [{"rfilename": "pytorch_model.pt"}]}]
    entries = to_catalog_entries(raw)
    assert entries[0].onnx_available is False
    assert entries[0].original_format == CatalogOriginalFormat.PYTORCH_PT
    assert entries[0].conversion_status == CatalogStatus.CONVERSION_REQUIRED


def test_to_catalog_entries_with_no_recognizable_artifact_is_unsupported():
    raw = [{"id": "org/docs-only", "siblings": [{"rfilename": "README.md"}]}]
    entries = to_catalog_entries(raw)
    assert entries[0].original_format == CatalogOriginalFormat.UNKNOWN
    assert entries[0].conversion_status == CatalogStatus.UNSUPPORTED


def test_to_catalog_entries_never_invents_task_or_classes():
    raw = [{"id": "org/rf-model", "siblings": [{"rfilename": "model.onnx"}]}]
    entry = to_catalog_entries(raw)[0]
    assert entry.task.value == "UNKNOWN"
    assert entry.classes is None
