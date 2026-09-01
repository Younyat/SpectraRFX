"""Backend module wiring for Storage & Artifact Repository Management.

Read-mostly: only ever calls `.list_captures()` on the SAME BLE capture
manager `ble_lab` already constructed against the real capture storage --
never a second, competing manager (same reuse pattern as
`ai_research_plugin.capture_bridge`). If `ble_lab` did not initialize one,
BLE captures still appear as generic, unlabeled directories under `ble/`
(degraded, not broken).
"""

from __future__ import annotations

from app.config.settings import settings
from app.modules.types import BackendModuleDefinition


def _build(context):
    from app.modules.ble_lab.shared_managers import get_shared_managers
    from app.modules.storage_management.routes import build_storage_management_router
    from app.modules.storage_management.service import StorageManagementService

    shared = get_shared_managers()
    capture_manager = shared.capture_manager if shared else None
    service = StorageManagementService(settings.storage.storage_root, capture_manager=capture_manager)
    return build_storage_management_router(service)


storage_management_module = BackendModuleDefinition(
    "storage_management",
    "Storage & Artifact Repository Management",
    True,
    210,  # after ble_lab, so get_shared_managers() is already populated
    "Real, filesystem-grounded disk-usage inventory across every storage category, "
    "plus a confirmation-gated per-artifact deletion endpoint. Additive: no existing "
    "route or behavior changes.",
    _build,
)
