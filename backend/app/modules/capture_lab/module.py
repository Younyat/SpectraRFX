from app.infrastructure.web.api.routes.modulated_signal_routes import build_modulated_signal_router
from app.modules.types import BackendModuleDefinition

def _build(context):
    return build_modulated_signal_router(context.container.modulated_signal_controller)

capture_lab_module = BackendModuleDefinition('capture-lab','Capture Lab',True,70,'Modulated signal Capture Lab endpoints.',_build)
