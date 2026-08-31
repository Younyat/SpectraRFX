"""RFModelManifest / CompatibilityResult / InferenceRecord contracts for the
AI Model Research Plugin (spec sections 4, 5, 11, 18, 19).

These types belong EXCLUSIVELY to this plugin -- nothing in the rest of the
platform imports from here, and this module imports nothing platform-global
to define its own schema (spec section 5: "No modificar estructuras
globales de la plataforma para introducir estos campos").

Design principle carried through every model below: a value the plugin
actually MEASURED (by inspecting the model file) and a value the operator
TYPED IN are never merged into one field silently. `discovered` is written
once, at import time, only from real inspection output, and is never
touched again. `overrides` is whatever the operator has since supplied.
`effective_input()`/`effective_output()` compute what will actually be USED
for compatibility checking and inference, preferring an override, but the
two source dicts remain inspectable separately at all times.
"""

from __future__ import annotations

import time
import uuid
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class ModelFramework(str, Enum):
    ONNX = "onnx"
    # Deliberately not implemented in this pass (see module docstring in
    # model_registry.py) -- listed so the enum is honest about the eventual
    # shape of the contract without claiming support that does not exist.
    TORCHSCRIPT = "torchscript"
    TENSORFLOW = "tensorflow"


class RFTask(str, Enum):
    MODULATION_CLASSIFICATION = "modulation_classification"
    SIGNAL_CLASSIFICATION = "signal_classification"
    FINGERPRINTING = "fingerprinting"
    ANOMALY_DETECTION = "anomaly_detection"
    EMITTER_IDENTIFICATION = "emitter_identification"
    OTHER = "other"


class InputRepresentation(str, Enum):
    RAW_IQ = "raw_iq"
    IQ_TENSOR = "iq_tensor"
    SPECTROGRAM = "spectrogram"
    PSD = "psd"
    FEATURES = "features"
    UNKNOWN = "unknown"


class OutputType(str, Enum):
    CLASS_LOGITS = "class_logits"
    CLASS_PROBABILITIES = "class_probabilities"
    EMBEDDING = "embedding"
    RECONSTRUCTION = "reconstruction"
    DETECTOR = "detector"
    UNKNOWN = "unknown"


class RFModelInputFields(BaseModel):
    """One "slot" of input-side knowledge about a model -- either what
    real inspection found, or what an operator has asserted. Never both
    merged into the same instance (see `RFModelManifest`)."""

    representation: InputRepresentation | None = None
    tensor_shape: list[int | None] | None = None  # None entries = dynamic/batch dim, real ONNX concept
    dtype: str | None = None
    input_name: str | None = None
    sample_rate_hz: float | None = None
    bandwidth_hz: float | None = None
    center_frequency_dependency: bool | None = None
    window_samples: int | None = None
    overlap: float | None = None


class RFModelPreprocessing(BaseModel):
    normalization: str | None = None
    fft_size: int | None = None
    stft_window: str | None = None
    stft_hop: int | None = None
    scaling: str | None = None


class RFModelOutputFields(BaseModel):
    output_type: OutputType | None = None
    tensor_shape: list[int | None] | None = None
    output_name: str | None = None
    classes: list[str] | None = None


class RFModelProvenance(BaseModel):
    paper: str | None = None
    authors: str | None = None
    repository: str | None = None
    dataset: str | None = None
    model_version: str | None = None
    notes: str | None = None


class RFModelManifest(BaseModel):
    """The plugin's own per-model descriptor (spec section 5). Persisted
    as one JSON file per imported model in the plugin's own storage
    directory -- never written into any platform-global dataset/model
    registry."""

    model_id: str
    model_name: str
    framework: ModelFramework
    model_file: str  # filename within the plugin's own model storage dir
    model_sha256: str
    imported_at_utc: str

    task: RFTask = RFTask.OTHER

    input_discovered: RFModelInputFields = Field(default_factory=RFModelInputFields)
    input_overrides: RFModelInputFields = Field(default_factory=RFModelInputFields)
    preprocessing: RFModelPreprocessing = Field(default_factory=RFModelPreprocessing)
    output_discovered: RFModelOutputFields = Field(default_factory=RFModelOutputFields)
    output_overrides: RFModelOutputFields = Field(default_factory=RFModelOutputFields)
    provenance: RFModelProvenance = Field(default_factory=RFModelProvenance)

    def effective_input(self) -> RFModelInputFields:
        return _merge_override(self.input_discovered, self.input_overrides, RFModelInputFields)

    def effective_output(self) -> RFModelOutputFields:
        return _merge_override(self.output_discovered, self.output_overrides, RFModelOutputFields)


def _merge_override(discovered: BaseModel, overrides: BaseModel, model_cls: type[BaseModel]) -> BaseModel:
    merged = discovered.model_dump()
    for key, value in overrides.model_dump().items():
        if value is not None:
            merged[key] = value
    return model_cls(**merged)


def new_model_id() -> str:
    return f"AI-MODEL-{uuid.uuid4().hex[:12]}"


class CompatibilityVerdict(str, Enum):
    COMPATIBLE = "COMPATIBLE"
    PARTIALLY_COMPATIBLE = "PARTIALLY_COMPATIBLE"
    INCOMPATIBLE = "INCOMPATIBLE"
    UNKNOWN = "UNKNOWN"


class CompatibilityCheck(BaseModel):
    field: str
    capture_value: Any = None
    model_value: Any = None
    matched: bool | None = None  # None = could not be checked (a real "UNKNOWN", not silently skipped)
    note: str = ""


class CompatibilityResult(BaseModel):
    verdict: CompatibilityVerdict
    checks: list[CompatibilityCheck]


class InferenceRecord(BaseModel):
    """Reproducibility record (spec section 19) -- everything needed to
    re-run exactly the same experiment later. Persisted as one JSON file
    per inference run."""

    record_id: str
    model_id: str
    model_sha256: str
    model_manifest_snapshot: RFModelManifest

    capture_id: str
    capture_data_sha256: str
    selected_time_seconds: tuple[float, float]
    selected_frequency_hz: tuple[float, float] | None

    input_transformation: InputRepresentation
    input_tensor_shape: list[int]
    input_dtype: str
    normalization_applied: str

    inference_timestamp_utc: str
    software_backend: str

    raw_output: list[float]
    raw_output_shape: list[int]
    interpretation: dict[str, Any]

    compatibility: CompatibilityResult


def utc_now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def new_record_id() -> str:
    return f"AI-INFER-{uuid.uuid4().hex[:12]}"
