from app.config.settings import settings
from app.modules.rf_intelligence.service import RFIntelligenceService
from app.modules.rf_signal_understanding.application.signal_understanding_service import RFSignalUnderstandingService
from app.modules.rf_signal_understanding.presentation.routes import build_rf_signal_understanding_router
from app.modules.types import BackendModuleDefinition


_legacy_service = RFIntelligenceService()
_service = RFSignalUnderstandingService(
    settings.storage.storage_root / "rf_signal_understanding",
    legacy_service=_legacy_service,
)


def _build(context):
    return build_rf_signal_understanding_router(
        _service,
        context.container.spectrum_controller,
        context.container.modulated_signal_controller,
    )


rf_signal_understanding_module = BackendModuleDefinition(
    "rf-signal-understanding",
    "RF Signal Understanding",
    True,
    56,
    "Waterfall-based I/Q analysis, time-frequency region detection, cautious signal hypotheses, and legacy comparison.",
    _build,
)
