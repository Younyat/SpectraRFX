from app.modules.fingerprinting import build_fingerprinting_router
from app.modules.types import BackendModuleDefinition

def _build(context):
    return build_fingerprinting_router(context.fingerprinting_service, context.container.modulated_signal_controller)

fingerprinting_module = BackendModuleDefinition('fingerprinting','Fingerprinting',True,80,'Fingerprinting registry, QC, review, and import endpoints.',_build)
