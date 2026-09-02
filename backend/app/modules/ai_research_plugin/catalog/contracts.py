"""RF Model Discovery Catalog contracts.

Deliberately separate from RFModelManifest/RFTask/InputRepresentation in
../contracts.py: those describe a model already IMPORTED into this plugin
(narrow, operational, used to gate a real compatibility check against a
real capture). The taxonomy here describes a model being DISCOVERED from
the outside world, before any of that -- a catalog entry may have no real
artifact at all yet (RESEARCH_MODEL) or not even be a model (a dataset or
a framework/toolkit), and is never itself used to gate inference.

The three-way split in `CatalogEntryKind` exists specifically so a dataset
(e.g. DeepSig RadioML) can never be presented as a downloadable model by
construction -- the conceptual error this catalog replaces.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel


class CatalogTask(str, Enum):
    MODULATION_CLASSIFICATION = "MODULATION_CLASSIFICATION"
    WIRELESS_TECHNOLOGY_CLASSIFICATION = "WIRELESS_TECHNOLOGY_CLASSIFICATION"
    RADIO_SYSTEM_IDENTIFICATION = "RADIO_SYSTEM_IDENTIFICATION"
    PROTOCOL_IDENTIFICATION = "PROTOCOL_IDENTIFICATION"
    SIGNAL_DETECTION = "SIGNAL_DETECTION"
    WIDEBAND_SIGNAL_DETECTION = "WIDEBAND_SIGNAL_DETECTION"
    RF_FINGERPRINTING = "RF_FINGERPRINTING"
    EMITTER_IDENTIFICATION = "EMITTER_IDENTIFICATION"
    INTERFERENCE_CLASSIFICATION = "INTERFERENCE_CLASSIFICATION"
    RADAR_WAVEFORM_CLASSIFICATION = "RADAR_WAVEFORM_CLASSIFICATION"
    UAV_RF_CLASSIFICATION = "UAV_RF_CLASSIFICATION"
    SPECTRUM_SENSING = "SPECTRUM_SENSING"
    SPECTRUM_ANOMALY_DETECTION = "SPECTRUM_ANOMALY_DETECTION"
    FOUNDATION_MODEL = "FOUNDATION_MODEL"
    REPRESENTATION_MODEL = "REPRESENTATION_MODEL"
    UNKNOWN = "UNKNOWN"


class CatalogInputRepresentation(str, Enum):
    RAW_IQ = "RAW_IQ"
    COMPLEX_IQ = "COMPLEX_IQ"
    IQ_FEATURES = "IQ_FEATURES"
    SPECTROGRAM = "SPECTROGRAM"
    WATERFALL_IMAGE = "WATERFALL_IMAGE"
    PSD = "PSD"
    FFT = "FFT"
    CONSTELLATION = "CONSTELLATION"
    MEL_SPECTROGRAM = "MEL_SPECTROGRAM"
    PREAMBLE_IQ = "PREAMBLE_IQ"
    TRANSIENT_IQ = "TRANSIENT_IQ"
    FEATURE_VECTOR = "FEATURE_VECTOR"
    CSI = "CSI"
    CIR = "CIR"
    OTHER = "OTHER"
    UNKNOWN = "UNKNOWN"


class CatalogEntryKind(str, Enum):
    MODEL = "MODEL"
    FRAMEWORK_TOOLKIT = "FRAMEWORK_TOOLKIT"
    DATASET = "DATASET"


class CatalogStatus(str, Enum):
    # A real artifact that (a) is a genuine, loadable ONNX file AND (b)
    # declares an input shape that matches one of THIS PLUGIN's actually
    # implemented representations (iq_tensor/flat_iq/spectrogram/psd)
    # exactly -- i.e. it will run end-to-end with zero extra work.
    # Deliberately a STRICTER bar than "the .onnx file loads" alone: this
    # catalog previously marked entries READY on that weaker basis, and
    # real testing showed loadable ONNX files whose declared shape still
    # doesn't match any implemented representation (see
    # PLATFORM_ADAPTER_REQUIRED below) -- conflating the two was a real,
    # since-corrected mistake.
    READY = "READY"
    CONVERTIBLE = "CONVERTIBLE"
    CONVERSION_REQUIRED = "CONVERSION_REQUIRED"
    # Real, loadable ONNX file (confirmed importable), but its declared
    # input shape does not match iq_tensor/flat_iq/spectrogram/psd -- it
    # needs a NEW representation adapter in this plugin (matching its real
    # documented preprocessing), not a framework conversion
    # (CONVERSION_REQUIRED is a different concept: PyTorch/TF -> ONNX).
    PLATFORM_ADAPTER_REQUIRED = "PLATFORM_ADAPTER_REQUIRED"
    FOUNDATION_FINE_TUNING_REQUIRED = "FOUNDATION_FINE_TUNING_REQUIRED"
    RESEARCH_MODEL = "RESEARCH_MODEL"
    DATASET_ONLY = "DATASET_ONLY"
    UNSUPPORTED = "UNSUPPORTED"


class CatalogOriginalFormat(str, Enum):
    ONNX = "onnx"
    SAFETENSORS = "safetensors"
    PYTORCH_PT = "pt"
    PYTORCH_PTH = "pth"
    CHECKPOINT = "ckpt"
    HF_BIN = "bin"
    TORCHSCRIPT = "torchscript"
    KERAS_H5 = "h5"
    KERAS = "keras"
    TENSORFLOW_SAVEDMODEL = "tensorflow_savedmodel"
    TFLITE = "tflite"
    TENSORRT_ENGINE = "engine"
    NONE = "none"
    UNKNOWN = "unknown"


class CatalogSourceKind(str, Enum):
    # Hand-verified by a human/agent against the real source (repo README,
    # model card, ...) before being hardcoded into seed_catalog.py.
    CURATED = "CURATED"
    # A live Hugging Face Hub search result -- real (comes straight from
    # HF's own API), but not individually reviewed the way a CURATED entry
    # is; see `independently_verified`.
    HUGGINGFACE_LIVE = "HUGGINGFACE_LIVE"


class RFModelCatalogEntry(BaseModel):
    """One real, external RF-related artifact: a model, a framework/
    toolkit, or a dataset. `kind` makes the spec section 2 distinction
    structural rather than a documentation convention."""

    id: str
    name: str
    kind: CatalogEntryKind
    provider: str
    source_url: str
    paper_url: str | None = None
    download_url: str | None = None

    task: CatalogTask = CatalogTask.UNKNOWN
    signal_domain: str | None = None
    classes: list[str] | None = None

    input_representation: CatalogInputRepresentation = CatalogInputRepresentation.UNKNOWN
    expected_sample_rate_hz: float | None = None
    input_length: int | None = None
    input_shape: list[int | None] | None = None
    normalization: str | None = None
    preprocessing: str | None = None

    framework: str | None = None
    original_format: CatalogOriginalFormat = CatalogOriginalFormat.UNKNOWN
    onnx_available: bool = False
    conversion_status: CatalogStatus = CatalogStatus.UNSUPPORTED
    opset: int | None = None
    output_shape: list[int | None] | None = None
    output_labels: list[str] | None = None

    license: str | None = None
    dataset: str | None = None
    reported_metrics: dict[str, Any] | None = None
    # Deliberately a string, not a bool -- "Validated = yes" collapses
    # structural/runtime/conversion-match validation into one meaningless
    # flag (spec section 20). This catalog only ever asserts "UNVALIDATED"
    # (nothing here has been run through ONNX Runtime yet); real
    # VALIDATED_STRUCTURE/VALIDATED_RUNTIME/CONVERSION_MATCH states belong
    # to an imported RFModelManifest, not a discovery-catalog entry.
    validation_status: str = "UNVALIDATED"

    # False only for an entry whose existence/details this session could
    # not independently confirm via a real fetch -- carried forward
    # honestly rather than dropped, so the operator can verify it
    # themselves, but never presented as equivalent to a verified entry.
    independently_verified: bool = True

    priority: str | None = None
    notes: str | None = None
    source_kind: CatalogSourceKind = CatalogSourceKind.CURATED


class CatalogFilters(BaseModel):
    task: CatalogTask | None = None
    input_representation: CatalogInputRepresentation | None = None
    kind: CatalogEntryKind | None = None
    onnx_available: bool | None = None
    conversion_status: CatalogStatus | None = None
    source_kind: CatalogSourceKind | None = None


class CatalogListResponse(BaseModel):
    entries: list[RFModelCatalogEntry]
    total: int


def apply_filters(entries: list[RFModelCatalogEntry], filters: CatalogFilters) -> list[RFModelCatalogEntry]:
    result = entries
    if filters.task is not None:
        result = [entry for entry in result if entry.task == filters.task]
    if filters.input_representation is not None:
        result = [entry for entry in result if entry.input_representation == filters.input_representation]
    if filters.kind is not None:
        result = [entry for entry in result if entry.kind == filters.kind]
    if filters.onnx_available is not None:
        result = [entry for entry in result if entry.onnx_available == filters.onnx_available]
    if filters.conversion_status is not None:
        result = [entry for entry in result if entry.conversion_status == filters.conversion_status]
    if filters.source_kind is not None:
        result = [entry for entry in result if entry.source_kind == filters.source_kind]
    return result
