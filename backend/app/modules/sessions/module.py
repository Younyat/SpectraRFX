from app.infrastructure.web.api.routes.session_routes import build_session_router
from app.modules.types import BackendModuleDefinition

def _build(context):
    return build_session_router(
        create_session_use_case=context.container.create_session_use_case,
        get_active_device_state=context.container.device_manager.get_device_state,
    )

sessions_module = BackendModuleDefinition('sessions','Sessions',True,130,'Lab session endpoints.',_build)
