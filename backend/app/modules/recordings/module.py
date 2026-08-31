from app.infrastructure.web.api.routes.recording_routes import build_recording_router
from app.modules.types import BackendModuleDefinition

def _build(context):
    return build_recording_router(context.container.recording_controller)

recordings_module = BackendModuleDefinition('recordings','Recordings',True,50,'Recording library endpoints.',_build)
