from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class AnalyzeCaptureRequest(BaseModel):
    file_path: str
    sample_rate_hz: float
    center_frequency_hz: float
    format: Literal["complex64", "cfile", "iq"] = "complex64"
    n_fft: int = 1024
    hop_length: int = 256
    window: str = "hann"
    analysis_id: str | None = None


class CompareWithRFIntelligenceRequest(AnalyzeCaptureRequest):
    legacy_frame: dict[str, Any] | None = None


class TrainingRequest(BaseModel):
    dataset_path: str | None = None
    dataset_name: str | None = None
    model_type: Literal["region_detector", "waterfall_classifier", "mlp_spectral_classifier"] = "region_detector"
    model_id: str | None = None
    execution_target: Literal["local", "remote"] = "local"
    remote_user: str = ""
    remote_host: str = ""
    remote_venv_activate: str = ""
    include_weak_labels: bool = True
    weak_label_weight: float = 0.4
    min_samples_per_class: int = 5
    split_strategy: Literal["random", "session_id", "capture_id"] = "session_id"
    epochs: int = 250
    learning_rate: float = 0.05
    test_split: float = 0.25
    feature_bins: int = 128


class ValidationRequest(BaseModel):
    dataset_path: str | None = None
    task: Literal["region_detection", "signal_type_classification", "robustness", "transmitter_identification"] = "region_detection"


class RegionReviewRequest(BaseModel):
    analysis_id: str
    bbox_id: str
    label: str
    review_status: Literal["accepted", "confirmed", "corrected", "rejected", "ambiguous", "unknown"] = "corrected"
    reviewer: str | None = None
    notes: str = ""
    send_to_training_buffer: bool = True
    legacy_label: str | None = None


class ExportLabelledRegionsRequest(BaseModel):
    analysis_ids: list[str] = Field(default_factory=list)
    dataset_name: str = "rf_signal_understanding_regions"
    include_unreviewed: bool = False


class PseudoLabelRequest(BaseModel):
    analysis_id: str
    bbox_id: str
    legacy_label: str
    legacy_family: str | None = None
    legacy_confidence: float
    training_weight: float = 0.4
    center_frequency_hz: float | None = None
    occupied_bandwidth_hz: float | None = None
    snr_db: float | None = None
    session_id: str | None = None
    capture_id: str | None = None


class IncrementalTrainingRequest(TrainingRequest):
    base_model_id: str | None = None
    new_model_id: str


class CompareModelsRequest(BaseModel):
    dataset_path: str | None = None
    dataset_name: str | None = None
    previous_model_id: str | None = None
    current_model_id: str
    include_legacy: bool = True


class CaptureForTrainingRequest(BaseModel):
    start_frequency_hz: float
    stop_frequency_hz: float
    duration_seconds: float = 5.0
    label_hint: str = ""
    session_id: str = ""
    file_format: Literal["iq", "cfile"] = "iq"
    gain_db: float | None = None
    profile_key: str | None = None
    profile: dict[str, Any] | None = None
    apply_bandpass_filter: bool = False
    filter_stopband_attenuation_db: float = 60.0
    filter_transition_width_hz: float | None = None
    live_preview_snr_db: float | None = None
    live_preview_noise_floor_db: float | None = None
    live_preview_peak_level_db: float | None = None
    live_preview_peak_frequency_hz: float | None = None
    transmitter_id: str | None = None
    transmitter_class: str | None = None
    operator: str | None = None
    environment: str | None = None


class RegisterCaptureRequest(BaseModel):
    capture_id: str | None = None
    file_path: str
    file_format: Literal["iq", "cfile", "complex64"] = "iq"
    sample_rate_hz: float
    center_frequency_hz: float
    gain_db: float | None = None
    duration_s: float | None = None
    source: str = "capture_lab"
    session_id: str | None = None
    profile_key: str | None = None
    profile: dict[str, Any] | None = None
    transmitter_id: str | None = None
    transmitter_class: str | None = None
    operator: str | None = None
    environment: str | None = None


class ModelSummary(BaseModel):
    model_id: str
    model_type: str
    status: str
    path: str
    trained: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)
