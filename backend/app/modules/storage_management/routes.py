"""FastAPI router for Storage & Artifact Repository Management -- an
entirely new, isolated, read-mostly router. Nothing here is imported by or
referenced from any other router in the platform.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.modules.storage_management.service import StorageManagementError, StorageManagementService


class DeleteItemBody(BaseModel):
    item_id: str
    confirm: bool = False


def build_storage_management_router(service: StorageManagementService) -> APIRouter:
    router = APIRouter(prefix="/storage-management", tags=["storage-management"])

    @router.get("/summary")
    def summary():
        return service.summary()

    @router.get("/items")
    def list_items(path: str = ""):
        try:
            return service.list_items(path)
        except FileNotFoundError as error:
            raise HTTPException(404, f"Unknown storage path: {path}") from error
        except StorageManagementError as error:
            raise HTTPException(400, str(error)) from error

    @router.delete("/items")
    def delete_item(body: DeleteItemBody):
        try:
            return service.delete_item(body.item_id, confirm=body.confirm)
        except FileNotFoundError as error:
            raise HTTPException(404, f"Unknown storage item: {body.item_id}") from error
        except StorageManagementError as error:
            raise HTTPException(400, str(error)) from error

    return router
