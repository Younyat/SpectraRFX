from __future__ import annotations

from app.modules.kiwisdr.domain.entities import (
    ReceiverCapabilities,
    ReceiverLocation,
    ReceiverNode,
    ReceiverStatus,
)


def receiver_from_dict(data: dict) -> ReceiverNode:
    location_data = data.get("location") or {}
    status_data = data.get("status") or {}
    capabilities_data = data.get("capabilities") or {}
    return ReceiverNode(
        id=data["id"],
        name=data.get("name") or data.get("host") or "KiwiSDR",
        host=data.get("host") or "",
        port=int(data.get("port") or 8073),
        url=data.get("url") or "",
        location=ReceiverLocation(
            lat=data.get("lat", location_data.get("lat")),
            lon=data.get("lon", location_data.get("lon")),
            country=data.get("country") or location_data.get("country") or "",
            city=data.get("city") or location_data.get("city") or "",
            locator=data.get("locator") or location_data.get("locator") or "",
            approximate=bool(location_data.get("approximate", True)),
        ),
        status=ReceiverStatus(
            is_online=bool(data.get("is_online", status_data.get("is_online", True))),
            is_public=bool(data.get("is_public", status_data.get("is_public", True))),
            current_users=data.get("current_users", status_data.get("current_users")),
            max_users=data.get("max_users", status_data.get("max_users")),
            health_status=data.get("health_status") or status_data.get("health_status") or "unknown",
            latency_ms=data.get("latency_ms", status_data.get("latency_ms")),
            last_checked=status_data.get("last_checked"),
        ),
        capabilities=ReceiverCapabilities(
            frequency_min_khz=float(data.get("frequency_min_khz", capabilities_data.get("frequency_min_khz", 0.0)) or 0.0),
            frequency_max_khz=float(data.get("frequency_max_khz", capabilities_data.get("frequency_max_khz", 30000.0)) or 30000.0),
            gps_locked=data.get("gps_locked", capabilities_data.get("gps_locked")),
            tdoa_available=data.get("tdoa_available", capabilities_data.get("tdoa_available")),
            drm=capabilities_data.get("drm"),
            iq=bool(capabilities_data.get("iq", True)),
        ),
        snr=data.get("snr"),
        antenna=data.get("antenna") or "",
        owner=data.get("owner") or "",
        receiver_type=data.get("receiver_type") or "KiwiSDR",
        source=data.get("source") or "kiwisdr_public",
        notes=data.get("notes") or "",
        last_seen=data.get("last_seen") or "",
    )
