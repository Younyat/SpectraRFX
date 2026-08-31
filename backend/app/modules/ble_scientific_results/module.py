from __future__ import annotations

from app.config.settings import settings
from app.modules.ble_lab.shared_managers import get_shared_managers
from app.modules.ble_rffi_studio.api import StudioRepository
from app.modules.ble_rffi_studio.campaign import CampaignOrchestrator
from app.modules.ble_rffi_studio.hardware import SdrDeviceArbiter
from app.modules.types import BackendModuleDefinition

from .api import ScientificResultsJobManager, ScientificResultsRepository, build_ble_scientific_results_router


def _build(context):
    root = settings.storage.storage_root
    repository = ScientificResultsRepository(
        root / "scientific_reports" / "ble", ble_rffi_studio_root=root / "ble_rffi_studio",
    )

    # Guided Validation's two hardware actions (Live Timing Diagnostic,
    # Reinforced Target-Absence Control) reuse the SAME real
    # CampaignOrchestrator machinery ble_rffi_studio's own module wiring
    # constructs -- the SAME shared hybrid_manager/capture_manager
    # singletons from ble_lab (never a second, competing manager against
    # the same USRP B200 -- see shared_managers.py's own docstring) and the
    # SAME file-based SdrDeviceArbiter lock directory ble_rffi_studio uses,
    # so both modules' capture requests are correctly serialized against
    # each other. None when ble_lab is disabled/not yet built, in which
    # case both hardware actions fail closed (HardwareActionError) instead
    # of touching hardware.
    campaign_orchestrator = None
    shared = get_shared_managers()
    if shared is not None:
        arbiter = SdrDeviceArbiter(root / "ble_rffi_studio" / "hardware_locks")
        hardware_studio_repository = StudioRepository(
            root / "ble_rffi_studio", legacy_capture_root=root / "ble" / "iq_captures", legacy_session_root=root / "ble_lab" / "sessions",
        )
        campaign_orchestrator = CampaignOrchestrator(
            hybrid_manager=shared.hybrid_manager, capture_manager=shared.capture_manager, arbiter=arbiter, repository=hardware_studio_repository,
        )

    # Study Control Center, phase 08 (2026-08-11): RQ2_BENCHMARK needs a
    # StudioRepository to call train_selected_models() -- real training,
    # never real hardware -- so it is built unconditionally, independent of
    # whether ble_lab's shared hardware managers (campaign_orchestrator,
    # above) are available.
    training_studio_repository = StudioRepository(
        root / "ble_rffi_studio", legacy_capture_root=root / "ble" / "iq_captures", legacy_session_root=root / "ble_lab" / "sessions",
    )

    job_manager = ScientificResultsJobManager(
        repository, root / "scientific_reports" / "ble" / "jobs",
        campaign_orchestrator=campaign_orchestrator, studio_repository=training_studio_repository,
    )
    return build_ble_scientific_results_router(repository, job_manager)


ble_scientific_results_module = BackendModuleDefinition(
    "ble-scientific-results", "BLE Scientific Results Studio", True, 87,
    "Deterministic orchestrator for BLE paper evidence: frozen analysis contracts, scientific preflight, "
    "and (in later phases) RQ1-4/S1-S2 statistics, figures, tables and LaTeX export. Read-only over "
    "ble_rffi_studio's own manifests and artifacts -- never modifies them.",
    _build,
)
