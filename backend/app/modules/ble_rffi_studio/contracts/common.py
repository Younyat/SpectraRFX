"""Shared base machinery for every BLE-RFFI Studio contract.

Every contract in this package is a frozen (immutable) pydantic model with an
explicit schema_version. Identity hashes are computed over canonical JSON
(sorted keys, no whitespace) so the same logical content always produces the
same hash regardless of field construction order -- this is what lets
example_id stay stable even though the record's fields could theoretically be
supplied in any order by different callers.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import BaseModel, ConfigDict


class StudioContract(BaseModel):
    """Base class for every BLE-RFFI Studio contract.

    Frozen: once constructed, a contract instance can never be mutated in
    place. Any change must produce a new instance (and, where the field is
    part of an identity hash, a new identity) -- this is the structural
    guarantee behind "the same RF fragment must not become a different
    example just because its interpretation changed": ExampleRecord simply
    has no label field for a label change to touch.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    def canonical_json(self, *, exclude: set[str] | None = None) -> bytes:
        payload: dict[str, Any] = self.model_dump(mode="json", exclude=exclude)
        return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")

    def content_hash(self, *, exclude: set[str] | None = None) -> str:
        return hashlib.sha256(self.canonical_json(exclude=exclude)).hexdigest()


def identity_hash(*parts: Any, prefix: str) -> str:
    """Deterministic id from an ordered tuple of identity fields. Same inputs
    -> same id, regardless of which caller builds it or in what order its
    surrounding record's other fields were supplied."""
    digest = hashlib.sha256(":".join(str(part) for part in parts).encode("utf-8")).hexdigest()
    return f"{prefix}-{digest[:32]}"
