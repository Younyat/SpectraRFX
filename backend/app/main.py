from __future__ import annotations

import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config.settings import settings
from app.infrastructure.di.container import ApplicationContainer
from app.modules.registry import BackendModuleContext, register_backend_modules
from app.modules.fingerprinting import FingerprintingService
from app.modules.mlops import MlOpsService
from app.modules.kiwisdr.module import build_kiwisdr_module


logging.basicConfig(
    level=getattr(logging, settings.logging.level.upper(), logging.INFO),
    format=settings.logging.format,
)

container = ApplicationContainer.build()
kiwisdr_module = build_kiwisdr_module(settings.storage.storage_root)
fingerprinting_service = FingerprintingService(settings.storage.fingerprinting_dir)
mlops_service = MlOpsService(
    settings.storage.mlops_dir,
    settings.storage.mlops_scripts_dir,
    settings.storage.backend_requirements_path,
    radioconda_python=os.environ.get("RADIOCONDA_PYTHON", r"C:\Users\Usuario\radioconda\python.exe"),
)

app = FastAPI(
    title=settings.app.app_name,
    version=settings.app.app_version,
    debug=settings.app.debug,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.api.cors_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

register_backend_modules(
    app,
    BackendModuleContext(
        container=container,
        kiwisdr_module=kiwisdr_module,
        fingerprinting_service=fingerprinting_service,
        mlops_service=mlops_service,
    ),
    api_prefix=settings.api.base_path,
)


@app.on_event("startup")
def start_kiwisdr_catalog_refresh() -> None:
    kiwisdr_module.start_background_refresh()


@app.get("/")
def root() -> dict:
    return {
        "app_name": settings.app.app_name,
        "version": settings.app.app_version,
        "status": "ok",
    }
