from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.config.runtime_settings import apply_device_profile, device_profiles_payload, runtime_settings_payload, save_runtime_values


class RuntimeSettingsSaveRequest(BaseModel):
    values: dict[str, Any] = Field(default_factory=dict)


def build_runtime_settings_router() -> APIRouter:
    router = APIRouter(prefix="/runtime-settings", tags=["runtime-settings"])

    @router.get("")
    async def get_runtime_settings() -> dict[str, Any]:
        return runtime_settings_payload()

    @router.post("")
    async def save_runtime_settings(request: RuntimeSettingsSaveRequest) -> dict[str, Any]:
        try:
            save_runtime_values(request.values)
        except ValueError as exc:
            detail: Any = str(exc)
            try:
                detail = json.loads(str(exc))
            except Exception:
                pass
            raise HTTPException(status_code=400, detail=detail) from exc
        payload = runtime_settings_payload()
        payload["status"] = "saved"
        return payload

    # Bundles over the exact same values POST above accepts -- switching
    # devices without hand-typing every RF_* number.
    @router.get("/device-profiles")
    async def get_device_profiles() -> dict[str, Any]:
        return device_profiles_payload()

    @router.post("/device-profiles/{profile_id}/apply")
    async def apply_device_profile_route(profile_id: str) -> dict[str, Any]:
        try:
            apply_device_profile(profile_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        payload = device_profiles_payload()
        payload["status"] = "applied"
        return payload

    return router
