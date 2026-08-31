from __future__ import annotations

from app.config.settings import settings
from app.modules.rf_experiment_lab.experiment_runner import RFExperimentLabService
from app.modules.rf_experiment_lab.routes import build_rf_experiment_lab_router
from app.modules.types import BackendModuleDefinition


def _build(context):
    service = RFExperimentLabService(settings.storage.storage_root, mlops_service=context.mlops_service)
    return build_rf_experiment_lab_router(service)


rf_experiment_lab_module = BackendModuleDefinition(
    "rf_experiment_lab",
    "RF Experiment Lab",
    True,
    95,
    "Optional paper-based RF experimentation layer with strict splits, detector baselines, and forensic traceability.",
    _build,
)
