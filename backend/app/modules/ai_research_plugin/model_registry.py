"""Model Registry: import, inspect, list, and manually annotate models
(spec sections 4, 5, 21).

Phase 1 scope, deliberately: **ONNX only**. `torch` is already a real
dependency of this backend (used by `mlops`/`ble_rffi_studio`), which made
TorchScript tempting too, but ONNX was chosen instead because it is the
one format where Model Inspection (spec section 4) is genuinely automatic
and reliable -- the graph format stores real input/output tensor shapes
and dtypes, so "what does this model expect" is an inspection, not a
guess. TorchScript graphs do not reliably expose static input shapes the
same way, and would have pushed most of section 4 onto "ask the operator
to type it in" for every model. PyTorch/TorchScript and TensorFlow support
are real, disclosed gaps (see module.py's docstring and the plugin's own
README), not a silent omission.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from app.modules.ai_research_plugin.contracts import (
    FolderImportFailure,
    FolderImportResult,
    ModelFramework,
    RFModelInputFields,
    RFModelManifest,
    RFModelOutputFields,
    RFTask,
    new_model_id,
    utc_now_iso,
)
from app.modules.ai_research_plugin.onnx_inspection import (
    infer_output_type_from_shape,
    infer_representation_from_shape,
    inspect_onnx_model,
)
from app.modules.ai_research_plugin.storage import AiPluginStorage


class ModelImportError(Exception):
    pass


class ModelRegistry:
    def __init__(self, storage: AiPluginStorage) -> None:
        self.storage = storage

    def import_onnx_model(self, file_bytes: bytes, filename: str, model_name: str | None = None, local_source_path: str | None = None) -> RFModelManifest:
        model_id = new_model_id()
        model_path = self.storage.model_file_path(model_id, filename)
        model_path.write_bytes(file_bytes)  # a copy in the plugin's own storage -- the caller's original file/upload is untouched

        inspection = inspect_onnx_model(model_path)
        if not inspection.valid:
            model_path.unlink(missing_ok=True)
            raise ModelImportError(f"Not a valid ONNX model: {inspection.error}")

        input_discovered = RFModelInputFields()
        if inspection.inputs:
            primary_input = inspection.inputs[0]
            input_discovered = RFModelInputFields(
                representation=infer_representation_from_shape(primary_input.shape),
                tensor_shape=primary_input.shape,
                dtype=primary_input.dtype,
                input_name=primary_input.name,
            )

        output_discovered = RFModelOutputFields()
        if inspection.outputs:
            primary_output = inspection.outputs[0]
            output_discovered = RFModelOutputFields(
                output_type=infer_output_type_from_shape(primary_output.shape),
                tensor_shape=primary_output.shape,
                output_name=primary_output.name,
            )

        manifest = RFModelManifest(
            model_id=model_id,
            model_name=model_name or filename,
            framework=ModelFramework.ONNX,
            model_file=filename,
            model_sha256=hashlib.sha256(file_bytes).hexdigest(),
            imported_at_utc=utc_now_iso(),
            local_source_path=local_source_path,
            task=RFTask.OTHER,
            input_discovered=input_discovered,
            output_discovered=output_discovered,
        )
        self.storage.save_manifest(manifest)
        return manifest

    def import_from_folder(self, folder_path: str) -> FolderImportResult:
        """Scans one real local directory (non-recursive -- a subfolder is
        the operator's own organizational choice, never assumed to also
        hold models) for .onnx files and imports every one not already
        registered under the same model_sha256. This is the direct-local-
        import path: unlike import_onnx_model() (one file at a time,
        through a browser file picker), this reads straight from the
        operator's own filesystem and records exactly where each model was
        found (RFModelManifest.local_source_path) -- what lets the UI show
        "my local models" as a distinct group from anything imported one
        file at a time."""
        folder = Path(folder_path).expanduser()
        if not folder.is_dir():
            raise ModelImportError(f"Not a real, existing directory: {folder_path}")

        existing_hashes = {m.model_sha256 for m in self.list_models()}
        imported: list[RFModelManifest] = []
        skipped_duplicate: list[str] = []
        failed: list[FolderImportFailure] = []

        for onnx_path in sorted(folder.glob("*.onnx")):
            file_bytes = onnx_path.read_bytes()
            sha256 = hashlib.sha256(file_bytes).hexdigest()
            if sha256 in existing_hashes:
                skipped_duplicate.append(onnx_path.name)
                continue
            try:
                manifest = self.import_onnx_model(file_bytes, onnx_path.name, local_source_path=str(onnx_path.resolve()))
                imported.append(manifest)
                existing_hashes.add(sha256)
            except ModelImportError as error:
                failed.append(FolderImportFailure(filename=onnx_path.name, error=str(error)))

        return FolderImportResult(folder_path=str(folder.resolve()), imported=imported, skipped_duplicate=skipped_duplicate, failed=failed)

    def get(self, model_id: str) -> RFModelManifest | None:
        return self.storage.load_manifest(model_id)

    def list_models(self) -> list[RFModelManifest]:
        return self.storage.list_manifests()

    def delete(self, model_id: str) -> None:
        self.storage.delete_model(model_id)

    def apply_overrides(
        self,
        model_id: str,
        task: RFTask | None = None,
        input_overrides: dict | None = None,
        output_overrides: dict | None = None,
        preprocessing: dict | None = None,
        provenance: dict | None = None,
    ) -> RFModelManifest:
        """Records operator-supplied values -- never overwrites
        `*_discovered` (those stay exactly what real inspection found,
        permanently)."""
        manifest = self.storage.load_manifest(model_id)
        if manifest is None:
            raise ModelImportError(f"Unknown model_id: {model_id}")

        if task is not None:
            manifest.task = task
        if input_overrides:
            manifest.input_overrides = manifest.input_overrides.model_copy(update=input_overrides)
        if output_overrides:
            manifest.output_overrides = manifest.output_overrides.model_copy(update=output_overrides)
        if preprocessing:
            manifest.preprocessing = manifest.preprocessing.model_copy(update=preprocessing)
        if provenance:
            manifest.provenance = manifest.provenance.model_copy(update=provenance)

        self.storage.save_manifest(manifest)
        return manifest

    def model_path(self, manifest: RFModelManifest) -> Path:
        return self.storage.model_file_path(manifest.model_id, manifest.model_file)
