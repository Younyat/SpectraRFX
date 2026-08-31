"""Dataset Builder: selects examples into a draft DatasetManifest, then
freezes it. Freezing is one-way -- once dataset_manifest_sha256 is set, any
further change must be a new dataset_version (derived_from records the
parent), never an edit of this one.

Selection here is deliberately conservative: an example only enters the
draft if Evidence Stage already marked it quality_status=PASSED and
dataset_eligibility in {PENDING_ANALYSIS, ELIGIBLE} -- QUARANTINED/INELIGIBLE
examples are recorded as excluded (with a reason), never silently dropped.
Reaching dataset_eligibility=ELIGIBLE for real is what the Dataset Analyzer's
gate (quality/dataset_analyzer.py) decides next, not this stage.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from app.infrastructure.ble.capture.ble_offline_replay import read_json, write_json

from ..contracts import DataOrigin, DatasetManifest, ExampleRecord

_QUARANTINED_ELIGIBILITY = {"QUARANTINED", "INELIGIBLE"}
_INCLUDABLE_ELIGIBILITY = {"PENDING_ANALYSIS", "ELIGIBLE"}


class DatasetBuilder:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def select_examples(self, examples: list[ExampleRecord]) -> tuple[list[ExampleRecord], dict[str, str]]:
        selected: list[ExampleRecord] = []
        excluded: dict[str, str] = {}
        for example in examples:
            if example.dataset_eligibility in _QUARANTINED_ELIGIBILITY:
                excluded[example.example_id] = f"DATASET_ELIGIBILITY_{example.dataset_eligibility}"
            elif example.quality_status != "PASSED":
                excluded[example.example_id] = f"QUALITY_STATUS_{example.quality_status}"
            elif example.dataset_eligibility not in _INCLUDABLE_ELIGIBILITY:
                excluded[example.example_id] = f"DATASET_ELIGIBILITY_{example.dataset_eligibility}_NOT_INCLUDABLE"
            else:
                selected.append(example)
        return selected, excluded

    def build_draft(
        self,
        *,
        dataset_id: str,
        dataset_version: str,
        project_id: str,
        campaign_id: str,
        examples: list[ExampleRecord],
        data_origin: DataOrigin,
        creation_policy: dict[str, Any],
        created_at: str,
        derived_from: str | None = None,
    ) -> DatasetManifest:
        physical_units = sorted({e.physical_unit_id for e in examples if e.physical_unit_id})
        captures = sorted({e.capture_id for e in examples})
        sessions = sorted({e.session_id for e in examples})
        class_distribution = dict(Counter(e.physical_unit_id or "UNKNOWN" for e in examples))
        return DatasetManifest(
            dataset_id=dataset_id,
            dataset_version=dataset_version,
            project_id=project_id,
            campaign_id=campaign_id,
            data_origin=data_origin,
            physical_units=physical_units,
            captures=captures,
            sessions=sessions,
            example_ids=[e.example_id for e in examples],
            class_distribution=class_distribution,
            creation_policy=creation_policy,
            frozen=False,
            derived_from=derived_from,
            created_at=created_at,
        )

    def freeze(self, manifest: DatasetManifest) -> DatasetManifest:
        if manifest.frozen:
            raise ValueError(f"DATASET_ALREADY_FROZEN:{manifest.dataset_id}:{manifest.dataset_version}")
        sha256 = manifest.content_hash(exclude={"frozen", "dataset_manifest_sha256"})
        frozen = manifest.model_copy(update={"frozen": True, "dataset_manifest_sha256": sha256})
        write_json(self._path(frozen.dataset_id, frozen.dataset_version), frozen.model_dump(mode="json"))
        return frozen

    def load(self, dataset_id: str, dataset_version: str) -> DatasetManifest | None:
        path = self._path(dataset_id, dataset_version)
        if not path.is_file():
            return None
        return DatasetManifest.model_validate(read_json(path))

    def _path(self, dataset_id: str, dataset_version: str) -> Path:
        return self.root / f"{dataset_id}__{dataset_version}.json"
