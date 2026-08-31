from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional, List

@dataclass(slots=True)
class Session:
    session_id: str
    name: str = ""
    created_utc: str = ""
    description: Optional[str] = None
    captures: List[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    
    def add_capture(self, capture_id: str) -> None:
        if capture_id not in self.captures:
            self.captures.append(capture_id)
    
    def remove_capture(self, capture_id: str) -> None:
        if capture_id in self.captures:
            self.captures.remove(capture_id)
    
    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "name": self.name,
            "created_utc": self.created_utc,
            "description": self.description,
            "captures": self.captures,
        }