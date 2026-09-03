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
    # [batch, 2N] -- N complex I/Q samples flattened into one interleaved
    # real/imag vector (I0,Q0,I1,Q1,...), never channel-first like
    # IQ_TENSOR's [batch,2,N]. A real, distinct, deterministic shape family
    # -- e.g. MT-PreamCNN's real documented [None,1600] input (800 complex
    # samples). Never a "features" vector (no statistical/cyclostationary
    # computation happens here, just a reshape) -- kept a separate value
    # from FEATURES so that gap stays honestly disclosed and unconflated.
    FLAT_IQ = "flat_iq"
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
    # Never discovered from an ONNX graph -- no inspection of the model
    # file can know what physical RF frequency it was trained for. Purely
    # an operator assertion (see LIVE frequency-applicability gating in
    # compatibility.py), left None ("unknown, not confirmed applicable
    # here") until the operator sets it via an override.
    expected_center_frequency_hz: float | None = None
    expected_frequency_tolerance_hz: float | None = None
    # The real, typical OCCUPIED bandwidth of the signal type this model
    # recognizes (e.g. ~2 MHz for BLE, ~20 MHz for 802.11) -- deliberately
    # a DIFFERENT concept from `bandwidth_hz` above (that one is the
    # capture/analysis bandwidth fed INTO the model, used for input
    # compatibility checking). This one is used only to size the LIVE
    # detection's 3D highlight -- never discovered, since nothing about an
    # ONNX graph says how wide the signal it classifies actually is.
    expected_signal_bandwidth_hz: float | None = None


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
    # Never discovered -- an ONNX graph carries zero semantic information
    # about what "class 3" means, only class NAMES if the operator typed
    # them into `classes` above. This is a further, optional, operator-
    # typed-once explanation per class name (e.g. "BPSK" -> "Binary Phase
    # Shift Keying -- 1 bit/symbol"), so every future prediction from this
    # model shows the explanation automatically without retyping it. Keys
    # not present in `classes` are harmless and ignored by the frontend.
    class_descriptions: dict[str, str] | None = None


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

    # The real, absolute path this .onnx was found at on the operator's own
    # machine, set only when imported via import_from_folder() (a bulk local
    # directory scan) -- null for a model imported one at a time through the
    # browser file picker. Never inferred or guessed: this is what lets the
    # UI separate "my real local models" from whatever else got imported
    # along the way (a demo/test file picked one at a time), without relying
    # on any assumption about what the operator meant by either.
    local_source_path: str | None = None

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


class FolderImportFailure(BaseModel):
    filename: str
    error: str


class FolderImportResult(BaseModel):
    """Real outcome of scanning one local directory for .onnx files --
    every file in the folder is accounted for in exactly one of the three
    lists below, never silently dropped."""

    folder_path: str
    imported: list[RFModelManifest]
    # Already registered under this exact model_sha256 (from any prior
    # import, folder-scan or one-at-a-time) -- skipped, never re-imported
    # as a duplicate entry.
    skipped_duplicate: list[str]
    failed: list[FolderImportFailure]


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

    # Real, measured wall-clock durations (spec-adjacent "latencia de
    # detección") -- never estimated. capture_latency_ms is null for an
    # OFFLINE run (there is no "waiting for a live snapshot" step to time);
    # inference_latency_ms/total_latency_ms are always real when set.
    capture_latency_ms: float | None = None
    inference_latency_ms: float | None = None
    total_latency_ms: float | None = None


def utc_now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def new_record_id() -> str:
    return f"AI-INFER-{uuid.uuid4().hex[:12]}"
