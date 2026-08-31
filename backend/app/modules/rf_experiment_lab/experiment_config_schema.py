from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


Stage = Literal["stage_1", "stage_2", "open_set_spoofing", "edge_inference"]
Task = Literal["signal_recognition", "device_fingerprinting", "region_detection", "open_set_spoofing", "edge_inference"]
SplitStrategy = Literal[
    "capture_disjoint",
    "session_disjoint",
    "day_disjoint",
    "environment_disjoint",
    "distance_disjoint",
    "receiver_disjoint",
    "device_holdout",
    "random",
]


class ExperimentWindowConfig(BaseModel):
    size_samples: int = 65536
    overlap: float = Field(default=0.5, ge=0.0, lt=1.0)


class ExperimentSplitConfig(BaseModel):
    strategy: SplitStrategy = "session_disjoint"
    train_ratio: float = Field(default=0.70, gt=0.0, lt=1.0)
    validation_ratio: float = Field(default=0.15, ge=0.0, lt=1.0)
    test_ratio: float = Field(default=0.15, gt=0.0, lt=1.0)
    group_by: list[str] = Field(default_factory=lambda: ["capture_id", "session_id"])

    @model_validator(mode="after")
    def validate_ratios(self) -> "ExperimentSplitConfig":
        total = self.train_ratio + self.validation_ratio + self.test_ratio
        if abs(total - 1.0) > 1e-6:
            raise ValueError("split ratios must sum to 1.0")
        return self


class ExperimentTrainingConfig(BaseModel):
    epochs: int = Field(default=100, ge=0)
    batch_size: int = Field(default=64, ge=1)
    optimizer: str = "adamw"
    learning_rate: float = Field(default=0.0001, gt=0.0)
    early_stopping: bool = True
    seed: int = 42


class ExperimentConfig(BaseModel):
    experiment_id: str
    paper_reference: str
    technique_name: str = ""
    task: Task
    stage: Stage
    technology: str | None = None
    input_representation: str
    model_type: str | None = None
    detector_type: str | None = None
    trainable: bool = True
    dataset_version: str = "unversioned"
    window: ExperimentWindowConfig = Field(default_factory=ExperimentWindowConfig)
    split: ExperimentSplitConfig = Field(default_factory=ExperimentSplitConfig)
    training: ExperimentTrainingConfig = Field(default_factory=ExperimentTrainingConfig)
    metrics: list[str] = Field(default_factory=list)
    parameters: dict[str, Any] = Field(default_factory=dict)
    augmentation: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_scientific_boundaries(self) -> "ExperimentConfig":
        if self.stage == "stage_1" and self.task == "device_fingerprinting":
            raise ValueError("stage_1 is reserved for signal, modulation and protocol recognition")
        if self.stage == "stage_2" and self.task != "device_fingerprinting":
            raise ValueError("stage_2 must be technology-specific device fingerprinting")
        if self.task == "device_fingerprinting" and not self.technology:
            raise ValueError("device fingerprinting experiments must set technology")
        if self.task == "region_detection" and not self.detector_type:
            raise ValueError("region detection experiments must set detector_type")
        return self


DEFAULT_METRICS = [
    "accuracy",
    "balanced_accuracy",
    "macro_f1",
    "precision_macro",
    "recall_macro",
    "confusion_matrix",
    "training_time",
    "inference_time",
    "model_size",
]

OPEN_SET_METRICS = [
    "auroc",
    "auprc",
    "eer",
    "false_accept_rate",
    "false_reject_rate",
    "unknown_recall",
    "open_set_f1",
    "spoofing_detection_rate",
]

REGION_DETECTION_METRICS = [
    "latency",
    "detected_regions",
    "region_area_statistics",
    "region_frequency_span",
    "region_time_span",
    "iou_if_annotations_available",
]
