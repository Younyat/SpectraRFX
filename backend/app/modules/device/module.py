from app.infrastructure.web.api.routes.device_routes import build_device_router
from app.modules.types import BackendModuleDefinition

def _build(context):
    return build_device_router(context.container.device_controller)

device_module = BackendModuleDefinition('device','Device',True,10,'Device hardware lifecycle and tuning endpoints.',_build)
