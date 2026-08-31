"""FastAPI routes for E6 Oracle-Style Lab — prefix /api/e6."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, UploadFile

from app.modules.e6_oracle_style.schemas import (
    E6AddCaptureBody,
    E6BuildSplitsBody,
    E6CreateLocalDatasetBody,
    E6ImportExistingModelBody,
    E6ImportExternalBody,
    E6ImportModelsDirBody,
    E6PredictFileBody,
    E6PredictFrozenSpectrumBody,
    E6PredictLiveWindowBody,
    E6RegisterDeviceBody,
    E6RetrainBody,
    E6ScanExternalBody,
    E6ScanModelsDirBody,
    E6TrainAllBody,
    E6TrainBody,
)
from app.modules.e6_oracle_style.service import E6Service
from app.modules.e6_oracle_style import job_tracker as jt


def _ok(data: Any, message: str = "ok") -> dict[str, Any]:
    return {"status": "ok", "module": "e6_oracle_style", "available": True, "message": message, "data": data}


def _err(exc: Exception) -> dict[str, Any]:
    return {"status": "error", "module": "e6_oracle_style", "available": True, "message": str(exc), "data": None}


def build_e6_router(service: E6Service) -> APIRouter:
    router = APIRouter(prefix="/e6", tags=["E6 Oracle-Style Lab"])

    @router.get("/health")
    def e6_health() -> dict[str, Any]:
        try:
            return _ok(service.health(), "E6 Oracle-Style Lab health check")
        except Exception as exc:
            return _err(exc)

    # ── External source discovery ───────────────────────────────────────────

    @router.get("/sources")
    def list_external_sources() -> dict[str, Any]:
        try:
            return _ok(service.list_external_sources(), "Supported external dataset sources")
        except Exception as exc:
            return _err(exc)

    @router.post("/datasets/scan-external")
    def scan_external(body: E6ScanExternalBody) -> dict[str, Any]:
        try:
            return _ok(service.scan_external_dataset(body.model_dump()), "External dataset scan complete")
        except Exception as exc:
            return _err(exc)

    @router.post("/datasets/import-external")
    def import_external(body: E6ImportExternalBody) -> dict[str, Any]:
        try:
            return _ok(service.import_external_dataset(body.model_dump()), "External dataset imported")
        except Exception as exc:
            return _err(exc)

    # ── Dataset management ──────────────────────────────────────────────────

    @router.get("/datasets")
    def list_datasets() -> dict[str, Any]:
        try:
            return _ok(service.list_datasets(), "E6 datasets")
        except Exception as exc:
            return _err(exc)

    @router.post("/datasets/create-local")
    def create_local_dataset(body: E6CreateLocalDatasetBody) -> dict[str, Any]:
        try:
            return _ok(service.create_local_dataset(body.model_dump()), "Local dataset created")
        except Exception as exc:
            return _err(exc)

    @router.get("/datasets/{dataset_name}")
    def get_dataset(dataset_name: str) -> dict[str, Any]:
        try:
            return _ok(service.get_dataset_summary(dataset_name), f"Dataset summary: {dataset_name}")
        except Exception as exc:
            return _err(exc)

    @router.delete("/datasets/{dataset_name}")
    def delete_dataset(dataset_name: str) -> dict[str, Any]:
        try:
            return _ok(service.delete_dataset(dataset_name), f"Dataset deleted: {dataset_name}")
        except Exception as exc:
            return _err(exc)

    @router.post("/datasets/add-capture")
    def add_capture(body: E6AddCaptureBody) -> dict[str, Any]:
        try:
            return _ok(service.add_capture(body.model_dump()), "Capture added to dataset")
        except Exception as exc:
            return _err(exc)

    @router.post("/datasets/register-device")
    def register_device(body: E6RegisterDeviceBody) -> dict[str, Any]:
        try:
            return _ok(service.register_device(body.model_dump()), "Device registered")
        except Exception as exc:
            return _err(exc)

    @router.post("/datasets/build-splits")
    def build_splits(body: E6BuildSplitsBody) -> dict[str, Any]:
        try:
            return _ok(service.build_splits(body.model_dump()), "Splits built")
        except Exception as exc:
            return _err(exc)

    # ── File upload ─────────────────────────────────────────────────────────

    @router.post("/files/upload")
    async def upload_iq_file(file: UploadFile = File(...)) -> dict[str, Any]:
        try:
            service.uploads_dir.mkdir(parents=True, exist_ok=True)
            safe_name = Path(file.filename or "upload.bin").name
            dest = service.uploads_dir / safe_name
            content = await file.read()
            dest.write_bytes(content)
            return _ok(
                {"filename": safe_name, "saved_path": str(dest), "size_bytes": len(content)},
                "File uploaded successfully",
            )
        except Exception as exc:
            return _err(exc)

    # ── Training ────────────────────────────────────────────────────────────

    @router.post("/train")
    def train(body: E6TrainBody) -> dict[str, Any]:
        try:
            return _ok(service.train(body.model_dump()), "E6 training complete")
        except Exception as exc:
            return _err(exc)

    @router.post("/train-all")
    def train_all(body: E6TrainAllBody) -> dict[str, Any]:
        try:
            return _ok(service.train_all(body.model_dump()), "E6 benchmark training complete")
        except Exception as exc:
            return _err(exc)

    @router.post("/retrain")
    def retrain(body: E6RetrainBody) -> dict[str, Any]:
        try:
            return _ok(service.retrain(body.model_dump()), "E6 retrain complete")
        except Exception as exc:
            return _err(exc)

    # ── Model registry ──────────────────────────────────────────────────────

    @router.get("/models")
    def list_models() -> dict[str, Any]:
        try:
            return _ok(service.list_models(), "E6 model registry")
        except Exception as exc:
            return _err(exc)

    @router.get("/models/live-ready")
    def live_ready_models() -> dict[str, Any]:
        try:
            return _ok(service.live_ready_models(), "E6 models enabled for live detection")
        except Exception as exc:
            return _err(exc)

    @router.post("/models/scan-directory")
    def scan_models_dir(body: E6ScanModelsDirBody) -> dict[str, Any]:
        try:
            return _ok(service.scan_models_directory(body.model_dump()), "Models directory scan complete")
        except Exception as exc:
            return _err(exc)

    @router.post("/models/import-existing")
    def import_existing_model(body: E6ImportExistingModelBody) -> dict[str, Any]:
        try:
            return _ok(service.import_existing_model(body.model_dump()), "Model imported and registered")
        except Exception as exc:
            return _err(exc)

    @router.post("/models/import-directory")
    def import_models_dir(body: E6ImportModelsDirBody) -> dict[str, Any]:
        try:
            return _ok(service.import_models_directory(body.model_dump()), "Models directory import complete")
        except Exception as exc:
            return _err(exc)

    @router.get("/models/{model_id}")
    def get_model(model_id: str) -> dict[str, Any]:
        try:
            return _ok(service.get_model(model_id), f"Model: {model_id}")
        except Exception as exc:
            return _err(exc)

    @router.post("/models/{model_id}/enable-live")
    def enable_live(model_id: str) -> dict[str, Any]:
        try:
            return _ok(service.set_live_enabled(model_id, True), f"Model {model_id} enabled for live detection")
        except Exception as exc:
            return _err(exc)

    @router.post("/models/{model_id}/disable-live")
    def disable_live(model_id: str) -> dict[str, Any]:
        try:
            return _ok(service.set_live_enabled(model_id, False), f"Model {model_id} disabled for live detection")
        except Exception as exc:
            return _err(exc)

    # ── Inference ───────────────────────────────────────────────────────────

    @router.post("/predict-file")
    def predict_file(body: E6PredictFileBody) -> dict[str, Any]:
        try:
            return _ok(service.predict_file(body.model_dump()), "E6 file prediction complete")
        except Exception as exc:
            return _err(exc)

    @router.post("/predict-live-window")
    def predict_live_window(body: E6PredictLiveWindowBody) -> dict[str, Any]:
        try:
            return _ok(service.predict_live_window(body.model_dump()), "E6 live window prediction complete")
        except Exception as exc:
            return _err(exc)

    @router.post("/predict-frozen-spectrum")
    def predict_frozen_spectrum(body: E6PredictFrozenSpectrumBody) -> dict[str, Any]:
        try:
            return _ok(service.predict_frozen_spectrum(body.model_dump()), "E6 frozen spectrum prediction complete")
        except Exception as exc:
            return _err(exc)

    # ── Job progress polling ─────────────────────────────────────────────────

    @router.post("/predict-live-spectrum")
    def predict_live_spectrum(body: E6PredictFrozenSpectrumBody) -> dict[str, Any]:
        try:
            return _ok(service.predict_frozen_spectrum(body.model_dump()), "E6 live spectrum prediction complete")
        except Exception as exc:
            return _err(exc)

    @router.get("/jobs")
    def list_jobs() -> dict[str, Any]:
        try:
            return _ok(jt.list_jobs(), "E6 job list")
        except Exception as exc:
            return _err(exc)

    @router.get("/jobs/{job_id}")
    def get_job(job_id: str) -> dict[str, Any]:
        job = jt.get_job(job_id)
        if job is None:
            return {"status": "error", "module": "e6_oracle_style", "available": True,
                    "message": f"Job not found: {job_id}", "data": None}
        return _ok(job, f"Job status: {job_id}")

    return router
