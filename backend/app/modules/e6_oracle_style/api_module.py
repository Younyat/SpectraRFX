from __future__ import annotations

from app.config.settings import settings
from app.modules.e6_oracle_style.routes import build_e6_router
from app.modules.e6_oracle_style.service import E6Service
from app.modules.types import BackendModuleDefinition


def _build(context):
    service = E6Service(settings.storage.storage_root)
    return build_e6_router(service)


e6_oracle_style_module = BackendModuleDefinition(
    "e6_oracle_style",
    "E6 Oracle-Style RF Dataset and Classical Fingerprinting Lab",
    True,
    96,
    "Independent E6 module: Oracle/KRI/UAV/CBRS external dataset import, local dataset creation, "
    "37-feature tabular extraction, 8 classical sklearn models, model registry, and live spectrum inference.",
    _build,
)
