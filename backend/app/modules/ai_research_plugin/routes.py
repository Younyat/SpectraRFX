"""FastAPI router for the AI Model Research Plugin -- an entirely new,
isolated router (spec section 22: "no cambia... APIs existentes"). Only
mounted at all when the module is enabled (see module.py); every route
here is additive, nothing here is imported by or referenced from any
other router in the platform.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from app.modules.ai_research_plugin.capture_bridge import CaptureBridgeError, ReadOnlyCaptureBridge
from app.modules.ai_research_plugin.contracts import InputRepresentation, RFTask
from app.modules.ai_research_plugin.inference_service import AiInferenceService, InferenceError
from app.modules.ai_research_plugin.model_registry import ModelImportError, ModelRegistry


class ManifestOverrideBody(BaseModel):
    task: RFTask | None = None
    input_overrides: dict[str, Any] = Field(default_factory=dict)
    output_overrides: dict[str, Any] = Field(default_factory=dict)
    preprocessing: dict[str, Any] = Field(default_factory=dict)
    provenance: dict[str, Any] = Field(default_factory=dict)


class CompatibilityRequestBody(BaseModel):
    model_id: str
    capture_id: str
    t0_seconds: float
    t1_seconds: float
    representation: InputRepresentation


class InferenceRequestBody(BaseModel):
    model_id: str
    capture_id: str
    t0_seconds: float
    t1_seconds: float
    representation: InputRepresentation


class LiveInferenceRequestBody(BaseModel):
    model_id: str
    representation: InputRepresentation


def build_ai_research_plugin_router(
    registry: ModelRegistry,
    capture_bridge: ReadOnlyCaptureBridge,
    inference_service: AiInferenceService,
) -> APIRouter:
    router = APIRouter(prefix="/ai-research-plugin", tags=["ai-research-plugin-experimental"])

    @router.get("/status")
    def status() -> dict:
        return {
            "enabled": True,
            "capture_bridge_available": capture_bridge.available,
            "live_inference_available": inference_service.live_bridge is not None,
        }

    @router.post("/models/import")
    def import_model(file: UploadFile = File(...), model_name: str | None = Form(None)):
        if not file.filename.endswith(".onnx"):
            raise HTTPException(400, "Only .onnx files are supported in this phase (PyTorch/TensorFlow are documented, not-yet-implemented gaps)")
        try:
            file_bytes = file.file.read()
            manifest = registry.import_onnx_model(file_bytes, file.filename, model_name=model_name)
        except ModelImportError as error:
            raise HTTPException(400, str(error)) from error
        return manifest

    @router.get("/models")
    def list_models():
        return registry.list_models()

    @router.get("/models/{model_id}")
    def get_model(model_id: str):
        manifest = registry.get(model_id)
        if manifest is None:
            raise HTTPException(404, f"Unknown model_id: {model_id}")
        return manifest

    @router.patch("/models/{model_id}")
    def update_model(model_id: str, body: ManifestOverrideBody):
        try:
            return registry.apply_overrides(
                model_id,
                task=body.task,
                input_overrides=body.input_overrides,
                output_overrides=body.output_overrides,
                preprocessing=body.preprocessing,
                provenance=body.provenance,
            )
        except ModelImportError as error:
            raise HTTPException(404, str(error)) from error

    @router.delete("/models/{model_id}")
    def delete_model(model_id: str):
        registry.delete(model_id)
        return {"deleted": model_id}

    @router.get("/captures")
    def list_captures():
        try:
            return capture_bridge.list_captures()
        except CaptureBridgeError as error:
            raise HTTPException(503, str(error)) from error

    @router.post("/compatibility")
    def check_compatibility_endpoint(body: CompatibilityRequestBody):
        try:
            result = inference_service.check_compatibility_for_region(
                body.model_id, body.capture_id, body.t0_seconds, body.t1_seconds, body.representation,
            )
        except InferenceError as error:
            raise HTTPException(400, str(error)) from error
        return result

    @router.post("/inference")
    def run_inference_endpoint(body: InferenceRequestBody):
        try:
            record = inference_service.run_inference(
                body.model_id, body.capture_id, body.t0_seconds, body.t1_seconds, body.representation,
            )
        except InferenceError as error:
            raise HTTPException(400, str(error)) from error
        return record

    @router.post("/inference/live")
    async def run_inference_live_endpoint(body: LiveInferenceRequestBody):
        try:
            record = await inference_service.run_inference_live(body.model_id, body.representation)
        except InferenceError as error:
            raise HTTPException(400, str(error)) from error
        return record

    @router.get("/inference")
    def list_inference_records():
        return inference_service.storage.list_records()

    @router.get("/inference/{record_id}")
    def get_inference_record(record_id: str):
        record = inference_service.storage.load_record(record_id)
        if record is None:
            raise HTTPException(404, f"Unknown record_id: {record_id}")
        return record

    return router
