from __future__ import annotations

from typing import Any, Literal

from .capture import DataOrigin
from .common import StudioContract

DATASET_SCHEMA_VERSION = "ble-rffi-studio-dataset-v1"


class DatasetManifest(StudioContract):
    """A dataset version. Freezing is one-way: once frozen=True and
    dataset_manifest_sha256 is set, any change must produce a new
    dataset_version (derived_from records the parent), never mutate this one
    -- same discipline as Fase 1's replay checkpoints, applied here to
    dataset construction instead of decoding."""

    schema_version: Literal["ble-rffi-studio-dataset-v1"] = DATASET_SCHEMA_VERSION
    dataset_id: str
    dataset_version: str
    project_id: str
    campaign_id: str
    # Never mixed: DatasetBuilder refuses to freeze a dataset whose captures
    # do not all share one data_origin (see StudioRepository.build_dataset).
    data_origin: DataOrigin

    physical_units: list[str] = []
    captures: list[str] = []
    sessions: list[str] = []
    example_ids: list[str] = []
    class_distribution: dict[str, int] = {}
    creation_policy: dict[str, Any] = {}

    frozen: bool = False
    dataset_manifest_sha256: str | None = None
    derived_from: str | None = None
    created_at: str
