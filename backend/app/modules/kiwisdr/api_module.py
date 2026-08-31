from app.modules.kiwisdr.presentation.routes import build_kiwi_session_router, build_receiver_router
from app.modules.types import BackendModuleDefinition

def _build_receivers(context):
    return build_receiver_router(context.kiwisdr_module.receiver_controller)

def _build_sessions(context):
    return build_kiwi_session_router(context.kiwisdr_module.session_controller)

kiwi_receivers_module = BackendModuleDefinition('kiwisdr-receivers','KiwiSDR Receivers',True,100,'Remote receiver catalog endpoints.',_build_receivers)
kiwi_sessions_module = BackendModuleDefinition('kiwisdr-sessions','KiwiSDR Sessions',True,110,'Remote receiver session endpoints.',_build_sessions)
