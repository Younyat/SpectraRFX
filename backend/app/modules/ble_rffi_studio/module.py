from __future__ import annotations

from app.config.settings import settings
from app.modules.ble_lab.shared_managers import get_shared_managers
from app.modules.types import BackendModuleDefinition

from .api import StudioJobManager, StudioRepository, build_ble_rffi_studio_router
from .campaign import CampaignOrchestrator
from .hardware import SdrDeviceArbiter


def _build(context):
    root = settings.storage.storage_root

    # ble_lab is registered with a lower `order` than this module (see
    # app/modules/registry.py), so its _build() has already run and
    # populated this by the time we get here. When it hasn't (e.g. ble_lab
    # disabled), the real-campaign endpoints fail closed with a clear error
    # instead of silently constructing a second, competing manager against
    # the same USRP B200.
    shared = get_shared_managers()
    campaign_orchestrator = None
    if shared is not None:
        arbiter = SdrDeviceArbiter(root / "ble_rffi_studio" / "hardware_locks")
        campaign_orchestrator = CampaignOrchestrator(
            hybrid_manager=shared.hybrid_manager, capture_manager=shared.capture_manager, arbiter=arbiter, repository=None,
        )

    repository = StudioRepository(
        root / "ble_rffi_studio",
        legacy_capture_root=root / "ble" / "iq_captures",
        legacy_session_root=root / "ble_lab" / "sessions",
        campaign_orchestrator=campaign_orchestrator,
    )
    if campaign_orchestrator is not None:
        campaign_orchestrator.repository = repository
    job_manager = StudioJobManager(repository, root / "ble_rffi_studio" / "jobs")
    return build_ble_rffi_studio_router(repository, job_manager)


ble_rffi_studio_module = BackendModuleDefinition(
    "ble-rffi-studio", "BLE-RFFI End-to-End Studio", True, 86,
    "New, independent BLE-RFFI pipeline: capture -> evidence -> dataset -> training -> evaluation -> export -> offline inference.",
    _build,
)
