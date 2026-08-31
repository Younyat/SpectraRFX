from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.config.runtime_settings import runtime_settings_payload, save_runtime_values


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

    return router
