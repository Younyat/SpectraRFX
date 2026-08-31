from app.infrastructure.web.api.routes.marker_routes import build_marker_router
from app.modules.types import BackendModuleDefinition

def _build(context):
    return build_marker_router(context.container.marker_controller)

markers_module = BackendModuleDefinition('markers','Markers',True,40,'Marker CRUD endpoints.',_build)
