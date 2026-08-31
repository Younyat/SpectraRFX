from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field


class LaunchTrainingRequest(BaseModel):
    remote_user: str
    remote_host: str
    remote_venv_activate: str = ""
    target_center_frequency_hz: float | None = None
    center_frequency_tolerance_hz: float = 1.0
    epochs: int = 20
    batch_size: int = 128
    window_size: int = 1024
    stride: int = 1024
    local_dataset_dir: str = "rf_dataset"
    local_output_dir: str = "remote_trained_model"


class ValidationRunRequest(BaseModel):
    val_root: str = "rf_dataset_val"
    model_dir: str = "remote_trained_model"
    output_json: str = "validation/validation_report.json"
    batch_size: int = 256
    python_exe: str = ""
    selected_metadata_paths: list[str] = Field(default_factory=list)
    selected_capture_ids: list[str] = Field(default_factory=list)


class InferenceRequest(BaseModel):
    cfile_path: str


class PredictionStartRequest(BaseModel):
    cfile_path: str
    metadata_path: str = ""
    model_dir: str = "remote_trained_model"
    output_json: str = "inference/prediction_report.json"
    batch_size: int = 256
    python_exe: str = ""


def build_mlops_router(service) -> APIRouter:
    router = APIRouter(tags=["mlops"])

    @router.get("/training/dashboard")
    async def training_dashboard(local_output_dir: str | None = Query(default=None)) -> dict[str, Any]:
        payload = {"local_output_dir": local_output_dir} if local_output_dir else {}
        return service.training_dashboard(payload)

    @router.get("/training/models")
    async def training_models() -> list[dict[str, Any]]:
        return service.list_models()

    @router.post("/training/start")
    async def training_start(body: LaunchTrainingRequest) -> dict[str, Any]:
        try:
            return service.start_training(body.model_dump(), retrain=False)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/training/retrain")
    async def training_retrain(body: LaunchTrainingRequest) -> dict[str, Any]:
        try:
            return service.start_training(body.model_dump(), retrain=True)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/training/status")
    async def training_status(job_id: str | None = Query(default=None)) -> dict[str, Any]:
        return service.training_status(job_id=job_id)

    @router.post("/validation/run")
    async def validation_run(body: ValidationRunRequest) -> dict[str, Any]:
        try:
            return service.run_validation(body.model_dump(), async_mode=False)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/validation/start")
    async def validation_start(body: ValidationRunRequest) -> dict[str, Any]:
        try:
            return service.run_validation(body.model_dump(), async_mode=True)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/validation/status")
    async def validation_status(job_id: str | None = Query(default=None)) -> dict[str, Any]:
        return service.validation_status(job_id=job_id)

    @router.get("/validation/reports")
    async def validation_reports() -> list[dict[str, Any]]:
        return service.list_validation_reports()

    @router.post("/inference/classify")
    async def inference_classify(body: InferenceRequest) -> dict[str, Any]:
        return service.classify_capture(body.model_dump())

    @router.post("/inference/verify")
    async def inference_verify(body: InferenceRequest) -> dict[str, Any]:
        return service.verify_capture(body.model_dump())

    @router.get("/inference/predict/captures")
    async def inference_prediction_captures() -> list[dict[str, Any]]:
        return service.list_prediction_captures()

    @router.post("/inference/predict/start")
    async def inference_prediction_start(body: PredictionStartRequest) -> dict[str, Any]:
        try:
            return service.start_prediction(body.model_dump())
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/inference/predict/status")
    async def inference_prediction_status(job_id: str | None = Query(default=None)) -> dict[str, Any]:
        return service.prediction_status(job_id=job_id)

    @router.get("/models/overview")
    async def models_overview() -> dict[str, Any]:
        return service.training_dashboard()

    @router.get("/models/current")
    async def models_current() -> dict[str, Any]:
        data = service.current_model()
        if data is None:
            return {
                "available": False,
                "status": "not_found",
                "message": "No current operational model is registered yet.",
                "data": None,
            }
        return data

    @router.get("/models/{version}")
    async def model_by_version(version: str) -> dict[str, Any]:
        data = service.model_by_version(version)
        if data is None:
            raise HTTPException(status_code=404, detail="Model version not found")
        return data

    return router
