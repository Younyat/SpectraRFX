from app.modules.rf_intelligence.routes import build_rf_intelligence_router
from app.modules.rf_intelligence.service import RFIntelligenceService
from app.modules.types import BackendModuleDefinition


_service = RFIntelligenceService()


def _build(context):
    return build_rf_intelligence_router(_service, context.container.spectrum_controller)


rf_intelligence_module = BackendModuleDefinition(
    "rf-intelligence",
    "RF Intelligence",
    True,
    55,
    "Real-time RF scene detection, metrics, rule-based protocol hypotheses, and tracking.",
    _build,
)
