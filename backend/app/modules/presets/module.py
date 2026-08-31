from app.infrastructure.web.api.routes.preset_routes import build_preset_router
from app.modules.types import BackendModuleDefinition

def _build(context):
    return build_preset_router(context.container.preset_controller)

presets_module = BackendModuleDefinition('presets','Presets',True,120,'Analyzer preset endpoints.',_build)
