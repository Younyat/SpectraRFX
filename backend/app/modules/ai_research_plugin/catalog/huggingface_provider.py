"""Live search against the public Hugging Face Hub Models API (spec
section 13). Deliberately the ONLY live discovery provider implemented in
this pass -- GitHub code search, Zenodo, arXiv, Papers with Code, and
Kaggle (spec sections 14-15) are real, disclosed gaps, not silently
skipped or faked as no-op buttons.

Uses only HF's public, unauthenticated model-search endpoint -- no API
key, no write access, no download of any model weights. `requests` is
imported lazily inside the function that needs it (not at module import
time), matching this plugin's existing discipline for onnx/onnxruntime:
importing this module never requires a dependency that isn't actually
being used yet.
"""

from __future__ import annotations

from typing import Any

from app.modules.ai_research_plugin.catalog.contracts import (
    CatalogEntryKind,
    CatalogOriginalFormat,
    CatalogSourceKind,
    CatalogStatus,
    CatalogTask,
    RFModelCatalogEntry,
)

HUGGINGFACE_MODELS_API = "https://huggingface.co/api/models"

# Real filename extension -> our CatalogOriginalFormat taxonomy (spec
# section 4/16). Anything not in this map is simply not detected --
# never guessed.
_EXTENSION_TO_FORMAT: dict[str, CatalogOriginalFormat] = {
    ".onnx": CatalogOriginalFormat.ONNX,
    ".safetensors": CatalogOriginalFormat.SAFETENSORS,
    ".pt": CatalogOriginalFormat.PYTORCH_PT,
    ".pth": CatalogOriginalFormat.PYTORCH_PTH,
    ".ckpt": CatalogOriginalFormat.CHECKPOINT,
    ".bin": CatalogOriginalFormat.HF_BIN,
    ".h5": CatalogOriginalFormat.KERAS_H5,
    ".keras": CatalogOriginalFormat.KERAS,
    ".tflite": CatalogOriginalFormat.TFLITE,
}


class HuggingFaceProviderError(Exception):
    pass


def search_huggingface_models(query: str, limit: int = 20, timeout_seconds: float = 10.0) -> list[dict[str, Any]]:
    """Real network call to HF's public search API. Raises
    HuggingFaceProviderError on any network/HTTP failure -- never returns
    a silently-empty result to mask a real error."""
    cleaned = query.strip()
    if not cleaned:
        return []
    import requests

    try:
        response = requests.get(
            HUGGINGFACE_MODELS_API,
            params={"search": cleaned, "limit": limit, "full": "true"},
            timeout=timeout_seconds,
            headers={"User-Agent": "spectrum-lab-ai-research-plugin/1"},
        )
        response.raise_for_status()
    except requests.RequestException as error:
        raise HuggingFaceProviderError(f"Hugging Face search failed: {error}") from error
    body = response.json()
    return body if isinstance(body, list) else []


def _detect_formats(filenames: list[str]) -> list[CatalogOriginalFormat]:
    detected = []
    for name in filenames:
        lowered = name.lower()
        for extension, fmt in _EXTENSION_TO_FORMAT.items():
            if lowered.endswith(extension) and fmt not in detected:
                detected.append(fmt)
    return detected


def to_catalog_entries(raw_models: list[dict[str, Any]]) -> list[RFModelCatalogEntry]:
    """Maps HF's raw API response into our own catalog shape. Every field
    populated here comes directly from HF's response (repo id, license,
    real filenames present in the repo) -- task/input_representation/
    classes are left UNKNOWN, since HF's metadata does not reliably say
    what an RF model actually classifies or expects as input; a human
    still has to review the model card before treating an entry as more
    than a lead."""
    entries = []
    for model in raw_models:
        model_id = model.get("id") or model.get("modelId")
        if not model_id:
            continue
        siblings = model.get("siblings") or []
        filenames = [sibling.get("rfilename", "") for sibling in siblings if sibling.get("rfilename")]
        detected_formats = _detect_formats(filenames)
        onnx_available = CatalogOriginalFormat.ONNX in detected_formats
        primary_format = (
            CatalogOriginalFormat.ONNX if onnx_available
            else detected_formats[0] if detected_formats
            else CatalogOriginalFormat.UNKNOWN
        )
        if onnx_available:
            conversion_status = CatalogStatus.READY
        elif detected_formats:
            conversion_status = CatalogStatus.CONVERSION_REQUIRED
        else:
            conversion_status = CatalogStatus.UNSUPPORTED

        card_data = model.get("cardData") or {}
        entries.append(RFModelCatalogEntry(
            id=f"HF-LIVE-{model_id.replace('/', '--')}",
            name=model_id,
            kind=CatalogEntryKind.MODEL,
            provider="Hugging Face",
            source_url=f"https://huggingface.co/{model_id}",
            task=CatalogTask.UNKNOWN,
            framework=None,
            original_format=primary_format,
            onnx_available=onnx_available,
            conversion_status=conversion_status,
            license=card_data.get("license") if isinstance(card_data, dict) else None,
            validation_status="UNVALIDATED",
            independently_verified=False,
            notes=(
                f"Live Hugging Face search result. Detected files: {', '.join(filenames[:10]) or 'none matched a known format'}"
                f"{' (truncated)' if len(filenames) > 10 else ''}. Not reviewed -- verify task, input representation, and classes "
                "against the model card before use."
            ),
            source_kind=CatalogSourceKind.HUGGINGFACE_LIVE,
        ))
    return entries
