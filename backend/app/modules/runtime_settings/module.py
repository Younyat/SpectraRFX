from app.infrastructure.web.api.routes.runtime_settings_routes import build_runtime_settings_router
from app.modules.types import BackendModuleDefinition


def _build(context):
    return build_runtime_settings_router()


runtime_settings_module = BackendModuleDefinition(
    "runtime_settings",
    "Runtime Settings",
    True,
    15,
    "Editable runtime parameter catalog and persistence endpoints.",
    _build,
)
