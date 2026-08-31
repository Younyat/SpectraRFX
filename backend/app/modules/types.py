from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from fastapi import APIRouter


@dataclass(frozen=True)
class BackendModuleDefinition:
    id: str
    name: str
    enabled: bool
    order: int
    description: str
    build_router: Callable[[object], APIRouter]
