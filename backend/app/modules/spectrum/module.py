from app.infrastructure.web.api.routes.spectrum_routes import build_spectrum_router
from app.modules.types import BackendModuleDefinition

def _build(context):
    return build_spectrum_router(context.container.spectrum_controller)

spectrum_module = BackendModuleDefinition('spectrum','Spectrum',True,20,'Live spectrum analyzer endpoints.',_build)
