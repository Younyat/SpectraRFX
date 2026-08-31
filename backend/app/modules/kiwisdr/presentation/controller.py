from __future__ import annotations

from app.modules.kiwisdr.application.use_cases import (
    CheckReceiverHealthUseCase,
    CreateKiwiSessionUseCase,
    GetReceiverDetailsUseCase,
    ListReceiversUseCase,
    RefreshReceiverCatalogUseCase,
    map_payload,
)
from app.modules.kiwisdr.domain.entities import KiwiSessionRequest


class ReceiverController:
    def __init__(
        self,
        list_receivers_use_case: ListReceiversUseCase,
        get_receiver_details_use_case: GetReceiverDetailsUseCase,
        refresh_receiver_catalog_use_case: RefreshReceiverCatalogUseCase,
        check_receiver_health_use_case: CheckReceiverHealthUseCase,
    ) -> None:
        self._list_receivers_use_case = list_receivers_use_case
        self._get_receiver_details_use_case = get_receiver_details_use_case
        self._refresh_receiver_catalog_use_case = refresh_receiver_catalog_use_case
        self._check_receiver_health_use_case = check_receiver_health_use_case

    def list_receivers(self, query: str | None = None, country: str | None = None, online: bool | None = None) -> dict:
        receivers = self._list_receivers_use_case.execute(query=query, country=country, online=online)
        if not receivers:
            try:
                self._refresh_receiver_catalog_use_case.execute(force=False)
                receivers = self._list_receivers_use_case.execute(query=query, country=country, online=online)
            except Exception:
                pass
        return {
            "count": len(receivers),
            "receivers": [receiver.to_dict() for receiver in receivers],
        }

    def get_receiver(self, receiver_id: str) -> dict:
        receiver = self._get_receiver_details_use_case.execute(receiver_id)
        if receiver is None:
            raise ValueError(f"Receiver not found: {receiver_id}")
        return receiver.to_dict()

    def receiver_map(self, query: str | None = None, country: str | None = None, online: bool | None = None) -> dict:
        receivers = self._list_receivers_use_case.execute(query=query, country=country, online=online)
        if not receivers:
            try:
                self._refresh_receiver_catalog_use_case.execute(force=False)
                receivers = self._list_receivers_use_case.execute(query=query, country=country, online=online)
            except Exception:
                pass
        return {"count": len(receivers), "points": map_payload(receivers)}

    def refresh(self, force: bool = True) -> dict:
        try:
            snapshot = self._refresh_receiver_catalog_use_case.execute(force=force)
            payload = snapshot.to_dict()
            payload["status"] = "ok"
            return payload
        except Exception as exc:
            cached = self._refresh_receiver_catalog_use_case.cached_snapshot()
            payload = cached.to_dict()
            payload["status"] = "degraded"
            payload["error"] = str(exc)
            payload["notes"] = (
                "KiwiSDR public catalog refresh failed. Returning the local backend cache; "
                "try again later or check outbound network access to kiwisdr.com."
            )
            return payload

    def health(self, receiver_id: str) -> dict:
        return self._check_receiver_health_use_case.execute(receiver_id)


class KiwiSessionController:
    def __init__(self, create_session_use_case: CreateKiwiSessionUseCase) -> None:
        self._create_session_use_case = create_session_use_case

    def create_session(self, request: KiwiSessionRequest) -> dict:
        return self._create_session_use_case.execute(request).to_dict()
