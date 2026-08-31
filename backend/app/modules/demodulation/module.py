from app.infrastructure.web.api.routes.demodulation_routes import build_demodulation_router
from app.modules.types import BackendModuleDefinition

def _build(context):
    return build_demodulation_router(context.container.demodulation_controller)

demodulation_module = BackendModuleDefinition('demodulation','Demodulation',True,60,'Marker-band demodulation endpoints.',_build)
