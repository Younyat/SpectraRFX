from app.infrastructure.web.api.routes.waterfall_routes import build_waterfall_router
from app.modules.types import BackendModuleDefinition

def _build(context):
    return build_waterfall_router(context.container.spectrum_controller)

waterfall_module = BackendModuleDefinition('waterfall','Waterfall',True,30,'Waterfall spectrum history endpoints.',_build)
