from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import threading
import time

from app.modules.kiwisdr.application.use_cases import (
    CheckReceiverHealthUseCase,
    CreateKiwiSessionUseCase,
    GetReceiverDetailsUseCase,
    ListReceiversUseCase,
    RefreshReceiverCatalogUseCase,
)
from app.modules.kiwisdr.infrastructure.probe_client import KiwisdrReceiverProbeClient
from app.modules.kiwisdr.infrastructure.public_catalog_client import KiwisdrPublicCatalogClient
from app.modules.kiwisdr.infrastructure.repository import ReceiverRepository
from app.modules.kiwisdr.presentation.controller import KiwiSessionController, ReceiverController


@dataclass(slots=True)
class KiwisdrModule:
    receiver_controller: ReceiverController
    session_controller: KiwiSessionController
    refresh_receiver_catalog_use_case: RefreshReceiverCatalogUseCase
    _refresh_thread_started: bool = False

    def start_background_refresh(self) -> None:
        if self._refresh_thread_started:
            return
        self._refresh_thread_started = True
        interval_s = max(300, int(os.environ.get("KIWISDR_CATALOG_REFRESH_SECONDS", "3600")))

        def worker() -> None:
            while True:
                try:
                    self.refresh_receiver_catalog_use_case.execute(force=False)
                except Exception:
                    pass
                time.sleep(interval_s)

        threading.Thread(target=worker, name="kiwisdr-catalog-refresh", daemon=True).start()


def build_kiwisdr_module(storage_root: Path) -> KiwisdrModule:
    module_dir = storage_root / "kiwisdr"
    repository = ReceiverRepository(
        catalog_path=module_dir / "receiver_catalog.json",
        sessions_path=module_dir / "kiwi_sessions.json",
    )
    catalog_client = KiwisdrPublicCatalogClient()
    probe_client = KiwisdrReceiverProbeClient()

    refresh_receiver_catalog_use_case = RefreshReceiverCatalogUseCase(repository, catalog_client)
    receiver_controller = ReceiverController(
        list_receivers_use_case=ListReceiversUseCase(repository),
        get_receiver_details_use_case=GetReceiverDetailsUseCase(repository),
        refresh_receiver_catalog_use_case=refresh_receiver_catalog_use_case,
        check_receiver_health_use_case=CheckReceiverHealthUseCase(repository, probe_client),
    )
    session_controller = KiwiSessionController(
        create_session_use_case=CreateKiwiSessionUseCase(repository)
    )
    return KiwisdrModule(
        receiver_controller=receiver_controller,
        session_controller=session_controller,
        refresh_receiver_catalog_use_case=refresh_receiver_catalog_use_case,
    )
