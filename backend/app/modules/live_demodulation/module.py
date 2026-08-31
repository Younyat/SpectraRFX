from app.infrastructure.web.api.routes.live_demodulation_routes import build_live_demodulation_router
from app.modules.types import BackendModuleDefinition


def _build(context):
    return build_live_demodulation_router(context.container.live_demodulation_controller)


live_demodulation_module = BackendModuleDefinition(
    "live_demodulation",
    "Live Demodulation",
    True,
    65,
    "Continuous real-time audio demodulation with SSE streaming.",
    _build,
)
