"""Pydantic request/response schemas for E6 API endpoints."""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class E6ScanExternalBody(BaseModel):
    source_type: str
    source_root: str
    ieee_target: str = "auto"
    limit_files: Optional[int] = None


class E6ImportExternalBody(BaseModel):
    source_type: str
    source_root: str
    dataset_name: str
    ieee_target: str = "auto"
    limit_files: Optional[int] = None
    max_files_per_class: Optional[int] = None
    import_percentage: Optional[float] = None  # 0.0–1.0; overrides limit_files when set


class E6CreateLocalDatasetBody(BaseModel):
    dataset_name: str
    task: str = "device_fingerprinting"
    signal_family: str = ""
    protocol: str = ""
    center_frequency_hz: Optional[float] = None
    sample_rate_hz: Optional[float] = None
    bandwidth_hz: Optional[float] = None
    dtype: str = "cf32"
    receiver_model: str = "USRP B200"
    receiver_serial: str = ""
    antenna: str = "RX2"
    gain_db: Optional[float] = None
    environment: str = "lab"
    notes: str = ""


class E6AddCaptureBody(BaseModel):
    dataset_name: str
    iq_path: str
    label: str
    session_id: str = ""
    dtype: Optional[str] = None
    sample_rate_hz: Optional[float] = None
    center_frequency_hz: Optional[float] = None
    sample_count: Optional[int] = None
    notes: str = ""


class E6RegisterDeviceBody(BaseModel):
    dataset_name: str
    transmitter_id: str
    device_type: str = ""
    vendor: str = ""
    model: str = ""
    serial: str = ""
    mac_address: str = ""
    notes: str = ""


class E6BuildSplitsBody(BaseModel):
    dataset_name: str
    train_ratio: float = 0.70
    val_ratio: float = 0.15
    seed: int = 42


class E6TrainBody(BaseModel):
    dataset_name: str
    model_kind: str = "extra_trees"
    window_size: int = 4096
    windows_per_file: int = 3
    window_strategy: str = "linspace"
    test_size: float = 0.25
    random_state: int = 42
    split_from_manifest: bool = True
    enabled_for_live: bool = True
    model_name: str = ""
    notes: str = ""


class E6RetrainBody(BaseModel):
    model_id: str
    additional_dataset_name: Optional[str] = None
    additional_iq_paths: List[str] = Field(default_factory=list)
    additional_labels: List[str] = Field(default_factory=list)
    window_size: Optional[int] = None
    windows_per_file: int = 3
    window_strategy: str = "linspace"
    test_size: float = 0.25
    random_state: int = 42


class E6PredictFileBody(BaseModel):
    model_id: str
    iq_path: str
    dtype: Optional[str] = None
    sample_count: Optional[int] = None
    top_k: int = 5


class E6PredictLiveWindowBody(BaseModel):
    model_id: str
    iq_samples_real: List[float] = Field(default_factory=list)
    iq_samples_imag: List[float] = Field(default_factory=list)
    window_size: Optional[int] = None
    top_k: int = 5


class E6ScanModelsDirBody(BaseModel):
    models_dir: str


class E6ImportExistingModelBody(BaseModel):
    model_path: str
    enabled_for_live: bool = True
    override_task: str = ""
    notes: str = ""


class E6ImportModelsDirBody(BaseModel):
    models_dir: str
    enabled_for_live: bool = True


class E6TrainAllBody(BaseModel):
    dataset_name: str
    window_size: int = 4096
    windows_per_file: int = 3
    window_strategy: str = "linspace"
    test_size: float = 0.25
    random_state: int = 42
    split_from_manifest: bool = True
    enabled_for_live: bool = True


class E6PredictFrozenSpectrumBody(BaseModel):
    model_id: str
    frequency_array_hz: List[float] = Field(default_factory=list)
    power_levels_db: List[float] = Field(default_factory=list)
    marker_start_hz: Optional[float] = None
    marker_stop_hz: Optional[float] = None
    top_k: int = 5
