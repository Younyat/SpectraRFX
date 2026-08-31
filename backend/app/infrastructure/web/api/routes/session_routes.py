from __future__ import annotations
from fastapi import APIRouter
from pydantic import BaseModel


class CreateSessionBody(BaseModel):
    name: str

def build_session_router(create_session_use_case, get_active_device_state) -> APIRouter:
    router = APIRouter(prefix="/sessions", tags=["sessions"])

    sessions: list[dict] = []

    @router.get("/")
    async def list_sessions():
        return sessions
    
    @router.post("/")
    async def create_session(body: CreateSessionBody):
        result = create_session_use_case.execute(body.name)
        data = result.to_dict() if hasattr(result, 'to_dict') else {}
        sessions.append(data)
        return data
    
    return router
