from __future__ import annotations

import time
import uuid
from dataclasses import replace

from app.modules.kiwisdr.domain.entities import (
    KiwiSession,
    KiwiSessionRequest,
    ReceiverCatalogSnapshot,
    ReceiverNode,
    utc_now_iso,
)
from app.modules.kiwisdr.infrastructure.probe_client import KiwisdrReceiverProbeClient
from app.modules.kiwisdr.infrastructure.public_catalog_client import KiwisdrPublicCatalogClient
from app.modules.kiwisdr.infrastructure.repository import ReceiverRepository


class ListReceiversUseCase:
    def __init__(self, repository: ReceiverRepository) -> None:
        self._repository = repository

    def execute(
        self,
        query: str | None = None,
        country: str | None = None,
        online: bool | None = None,
    ) -> list[ReceiverNode]:
        receivers = self._repository.list_receivers()
        if query:
            lowered = query.lower()
            receivers = [
                item for item in receivers
                if lowered in f"{item.name} {item.host} {item.location.country} {item.location.city}".lower()
            ]
        if country:
            receivers = [item for item in receivers if item.location.country.lower() == country.lower()]
        if online is not None:
            receivers = [item for item in receivers if item.status.is_online == online]
        return receivers


class GetReceiverDetailsUseCase:
    def __init__(self, repository: ReceiverRepository) -> None:
        self._repository = repository

    def execute(self, receiver_id: str) -> ReceiverNode | None:
        return self._repository.get_receiver(receiver_id)


class RefreshReceiverCatalogUseCase:
    def __init__(
        self,
        repository: ReceiverRepository,
        catalog_client: KiwisdrPublicCatalogClient,
        cache_ttl_s: int = 3600,
    ) -> None:
        self._repository = repository
        self._catalog_client = catalog_client
        self._cache_ttl_s = cache_ttl_s

    def execute(self, force: bool = False) -> ReceiverCatalogSnapshot:
        snapshot = self._repository.load_snapshot()
        if not force and snapshot.refreshed_at and _age_seconds(snapshot.refreshed_at) < self._cache_ttl_s:
            return snapshot
        snapshot = self._catalog_client.fetch_catalog()
        self._repository.save_snapshot(snapshot)
        return snapshot

    def cached_snapshot(self) -> ReceiverCatalogSnapshot:
        return self._repository.load_snapshot()


class CheckReceiverHealthUseCase:
    def __init__(self, repository: ReceiverRepository, probe_client: KiwisdrReceiverProbeClient) -> None:
        self._repository = repository
        self._probe_client = probe_client

    def execute(self, receiver_id: str) -> dict:
        receiver = self._repository.get_receiver(receiver_id)
        if receiver is None:
            raise ValueError(f"Receiver not found: {receiver_id}")
        return {"receiver_id": receiver_id, **self._probe_client.check_health(receiver.url)}


class CreateKiwiSessionUseCase:
    def __init__(self, repository: ReceiverRepository, sample_rate: int = 12_000) -> None:
        self._repository = repository
        self._sample_rate = sample_rate

    def execute(self, request: KiwiSessionRequest) -> KiwiSession:
        receiver = self._repository.get_receiver(request.receiver_id)
        if receiver is None:
            raise ValueError(f"Receiver not found: {request.receiver_id}")
        if request.frequency_khz < receiver.capabilities.frequency_min_khz:
            raise ValueError("frequency_khz is below receiver coverage")
        if request.frequency_khz > receiver.capabilities.frequency_max_khz:
            raise ValueError("frequency_khz is above receiver coverage")

        session = KiwiSession(
            session_id=f"kiwi_session_{uuid.uuid4().hex[:10]}",
            receiver_id=receiver.id,
            host=receiver.host,
            port=receiver.port,
            status="connecting",
            sample_rate=self._sample_rate,
            mode=request.mode,
            frequency_khz=request.frequency_khz,
            compression=request.compression,
            agc=request.agc,
            created_at=utc_now_iso(),
            notes=[
                "Session object created for KiwiSDR source handoff.",
                "IQ/audio streaming client is intentionally isolated for future integration.",
            ],
        )
        self._repository.save_session(session)
        return session


def map_payload(receivers: list[ReceiverNode]) -> list[dict]:
    points = []
    for receiver in receivers:
        if receiver.location.lat is None or receiver.location.lon is None:
            continue
        points.append(
            {
                "id": receiver.id,
                "name": receiver.name,
                "host": receiver.host,
                "port": receiver.port,
                "url": receiver.url,
                "lat": receiver.location.lat,
                "lon": receiver.location.lon,
                "country": receiver.location.country,
                "city": receiver.location.city,
                "is_online": receiver.status.is_online,
                "current_users": receiver.status.current_users,
                "max_users": receiver.status.max_users,
                "snr": receiver.snr,
                "frequency_min_khz": receiver.capabilities.frequency_min_khz,
                "frequency_max_khz": receiver.capabilities.frequency_max_khz,
                "health_status": receiver.status.health_status,
            }
        )
    return points


def merge_health(receiver: ReceiverNode, health: dict) -> ReceiverNode:
    return replace(
        receiver,
        status=replace(
            receiver.status,
            is_online=bool(health.get("is_online")),
            health_status=health.get("health_status") or receiver.status.health_status,
            latency_ms=health.get("latency_ms"),
            last_checked=utc_now_iso(),
        ),
    )


def _age_seconds(timestamp: str) -> float:
    try:
        parsed = time.strptime(timestamp[:19], "%Y-%m-%dT%H:%M:%S")
        return max(0.0, time.time() - time.mktime(parsed))
    except Exception:
        return float("inf")
