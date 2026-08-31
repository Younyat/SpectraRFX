from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True, frozen=True)
class ReceiverLocation:
    lat: float | None = None
    lon: float | None = None
    country: str = ""
    city: str = ""
    locator: str = ""
    approximate: bool = True


@dataclass(slots=True, frozen=True)
class ReceiverStatus:
    is_online: bool = True
    is_public: bool = True
    current_users: int | None = None
    max_users: int | None = None
    health_status: str = "unknown"
    latency_ms: float | None = None
    last_checked: str | None = None


@dataclass(slots=True, frozen=True)
class ReceiverCapabilities:
    frequency_min_khz: float = 0.0
    frequency_max_khz: float = 30_000.0
    gps_locked: bool | None = None
    tdoa_available: bool | None = None
    drm: bool | None = None
    iq: bool = True


@dataclass(slots=True, frozen=True)
class ReceiverNode:
    id: str
    name: str
    host: str
    port: int
    url: str
    location: ReceiverLocation
    status: ReceiverStatus = field(default_factory=ReceiverStatus)
    capabilities: ReceiverCapabilities = field(default_factory=ReceiverCapabilities)
    snr: float | None = None
    antenna: str = ""
    owner: str = ""
    receiver_type: str = "KiwiSDR"
    source: str = "kiwisdr_public"
    notes: str = ""
    last_seen: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data.update(
            {
                "lat": self.location.lat,
                "lon": self.location.lon,
                "country": self.location.country,
                "city": self.location.city,
                "locator": self.location.locator,
                "is_online": self.status.is_online,
                "is_public": self.status.is_public,
                "current_users": self.status.current_users,
                "max_users": self.status.max_users,
                "health_status": self.status.health_status,
                "latency_ms": self.status.latency_ms,
                "gps_locked": self.capabilities.gps_locked,
                "tdoa_available": self.capabilities.tdoa_available,
                "frequency_min_khz": self.capabilities.frequency_min_khz,
                "frequency_max_khz": self.capabilities.frequency_max_khz,
            }
        )
        return data


@dataclass(slots=True, frozen=True)
class ReceiverCatalogSnapshot:
    receivers: list[ReceiverNode]
    refreshed_at: str
    source: str
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "refreshed_at": self.refreshed_at,
            "source": self.source,
            "notes": self.notes,
            "count": len(self.receivers),
            "receivers": [receiver.to_dict() for receiver in self.receivers],
        }


@dataclass(slots=True, frozen=True)
class KiwiSessionRequest:
    receiver_id: str
    frequency_khz: float = 7100.0
    mode: str = "iq"
    compression: bool = True
    agc: bool = True


@dataclass(slots=True, frozen=True)
class KiwiSession:
    session_id: str
    receiver_id: str
    host: str
    port: int
    status: str
    sample_rate: int
    mode: str
    frequency_khz: float
    compression: bool
    agc: bool
    created_at: str
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
