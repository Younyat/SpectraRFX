from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Optional


@dataclass(slots=True)
class SessionDTO:
    session_id: str
    name: str
    created_utc: str
    captures: list[str] = field(default_factory=list)
    notes: Optional[str] = None
    description: Optional[str] = None
    metadata: dict | None = None

    @classmethod
    def from_entity(cls, entity) -> "SessionDTO":
        return cls(
            session_id=entity.session_id,
            name=entity.name,
            created_utc=entity.created_utc,
            captures=list(getattr(entity, "captures", [])),
            description=getattr(entity, "description", None),
            metadata=getattr(entity, "metadata", {}),
        )

    def to_dict(self) -> dict:
        data = asdict(self)
        data["metadata"] = self.metadata or {}
        return data
