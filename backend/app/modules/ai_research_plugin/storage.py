"""Pure filesystem persistence for the AI Research Plugin -- its own
storage directory, never written to or read from by any other module.
No framework/inference logic lives here, only JSON/bytes I/O.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.modules.ai_research_plugin.contracts import InferenceRecord, RFModelManifest


class AiPluginStorage:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.models_dir = root / "models"
        self.manifests_dir = root / "manifests"
        self.records_dir = root / "inference_records"
        for directory in (self.models_dir, self.manifests_dir, self.records_dir):
            directory.mkdir(parents=True, exist_ok=True)

    # -- Models -----------------------------------------------------
    def model_file_path(self, model_id: str, filename: str) -> Path:
        return self.models_dir / f"{model_id}__{filename}"

    def save_manifest(self, manifest: RFModelManifest) -> None:
        path = self.manifests_dir / f"{manifest.model_id}.json"
        path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")

    def load_manifest(self, model_id: str) -> RFModelManifest | None:
        path = self.manifests_dir / f"{model_id}.json"
        if not path.exists():
            return None
        return RFModelManifest.model_validate_json(path.read_text(encoding="utf-8"))

    def list_manifests(self) -> list[RFModelManifest]:
        manifests = []
        for path in sorted(self.manifests_dir.glob("*.json")):
            try:
                manifests.append(RFModelManifest.model_validate_json(path.read_text(encoding="utf-8")))
            except Exception:
                continue  # a malformed individual manifest is skipped, never fatal to the whole list
        return manifests

    def delete_model(self, model_id: str) -> None:
        manifest = self.load_manifest(model_id)
        if manifest is not None:
            model_path = self.model_file_path(model_id, manifest.model_file)
            model_path.unlink(missing_ok=True)
        (self.manifests_dir / f"{model_id}.json").unlink(missing_ok=True)

    # -- Inference records -------------------------------------------
    def save_record(self, record: InferenceRecord) -> None:
        path = self.records_dir / f"{record.record_id}.json"
        path.write_text(record.model_dump_json(indent=2), encoding="utf-8")

    def load_record(self, record_id: str) -> InferenceRecord | None:
        path = self.records_dir / f"{record_id}.json"
        if not path.exists():
            return None
        return InferenceRecord.model_validate_json(path.read_text(encoding="utf-8"))

    def list_records(self) -> list[InferenceRecord]:
        records = []
        for path in sorted(self.records_dir.glob("*.json"), reverse=True):
            try:
                records.append(InferenceRecord.model_validate_json(path.read_text(encoding="utf-8")))
            except Exception:
                continue
        return records
