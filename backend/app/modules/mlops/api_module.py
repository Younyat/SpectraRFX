from app.modules.mlops import build_mlops_router
from app.modules.types import BackendModuleDefinition

def _build(context):
    return build_mlops_router(context.mlops_service)

mlops_module = BackendModuleDefinition('mlops','MLOps',True,90,'Training, retraining, validation, inference, and model registry endpoints.',_build)
