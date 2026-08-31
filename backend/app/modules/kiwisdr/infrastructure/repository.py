from __future__ import annotations

import json
from pathlib import Path

from app.modules.kiwisdr.domain.entities import KiwiSession, ReceiverCatalogSnapshot, ReceiverNode, utc_now_iso
from app.modules.kiwisdr.infrastructure.serialization import receiver_from_dict


class ReceiverRepository:
    def __init__(self, catalog_path: Path, sessions_path: Path) -> None:
        self._catalog_path = catalog_path
        self._sessions_path = sessions_path
        self._catalog_path.parent.mkdir(parents=True, exist_ok=True)
        self._sessions_path.parent.mkdir(parents=True, exist_ok=True)

    def save_snapshot(self, snapshot: ReceiverCatalogSnapshot) -> None:
        self._catalog_path.write_text(
            json.dumps(snapshot.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def load_snapshot(self) -> ReceiverCatalogSnapshot:
        if not self._catalog_path.exists():
            return ReceiverCatalogSnapshot(receivers=[], refreshed_at="", source="local_cache")
        data = json.loads(self._catalog_path.read_text(encoding="utf-8"))
        receivers = [receiver_from_dict(item) for item in data.get("receivers", [])]
        return ReceiverCatalogSnapshot(
            receivers=receivers,
            refreshed_at=data.get("refreshed_at") or "",
            source=data.get("source") or "local_cache",
            notes=data.get("notes") or "",
        )

    def list_receivers(self) -> list[ReceiverNode]:
        return self.load_snapshot().receivers

    def get_receiver(self, receiver_id: str) -> ReceiverNode | None:
        for receiver in self.list_receivers():
            if receiver.id == receiver_id:
                return receiver
        return None

    def save_session(self, session: KiwiSession) -> None:
        sessions = self.list_sessions()
        sessions = [item for item in sessions if item.session_id != session.session_id]
        sessions.append(session)
        payload = {
            "updated_at": utc_now_iso(),
            "sessions": [item.to_dict() for item in sessions[-200:]],
        }
        self._sessions_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def list_sessions(self) -> list[KiwiSession]:
        if not self._sessions_path.exists():
            return []
        data = json.loads(self._sessions_path.read_text(encoding="utf-8"))
        sessions = []
        for item in data.get("sessions", []):
            sessions.append(
                KiwiSession(
                    session_id=item["session_id"],
                    receiver_id=item["receiver_id"],
                    host=item["host"],
                    port=int(item["port"]),
                    status=item["status"],
                    sample_rate=int(item["sample_rate"]),
                    mode=item["mode"],
                    frequency_khz=float(item["frequency_khz"]),
                    compression=bool(item["compression"]),
                    agc=bool(item["agc"]),
                    created_at=item["created_at"],
                    notes=list(item.get("notes", [])),
                )
            )
        return sessions
