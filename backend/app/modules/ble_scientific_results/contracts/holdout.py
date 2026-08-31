"""Append-only, hash-chained log of every access to future-holdout
material -- Fase 1 closure item A.3.

Each entry commits to the entry before it (`previous_entry_hash`), the same
way a blockchain or a git commit chain does, so `verify_holdout_access_chain`
can detect deletion (a gap in `sequence_number`), modification (a
recomputed `entry_hash` that no longer matches what's stored), and
reordering/insertion (a `previous_entry_hash` that doesn't match the actual
prior entry) -- all without needing external storage.

Scope of the guarantee, stated plainly (never oversold): this chain proves
integrity of accesses that went THROUGH ScientificResultsRepository's own
`log_holdout_access()` method. It has no way to detect a `.jsonl` file
edited directly on the filesystem outside the application, because no
instrumentation exists at that layer -- this is a real limitation, not a
detail to gloss over, and is stated again on `verify_holdout_access_chain`
itself and in the Fase 2 delivery report.

Fase 1 does not yet gate any actual resource behind "future holdout" (that
arrives with the campaign/prediction records in a later phase); the logging
contract and its chained storage discipline are built now so later phases
have exactly one place to call into, never a second competing mechanism
invented once the holdout actually exists.
"""
from __future__ import annotations

from typing import Literal

from .common import StudioContract, identity_hash

HOLDOUT_ACCESS_LOG_SCHEMA_VERSION = "ble-scientific-results-holdout-access-v2"

HoldoutChainStatus = Literal["VALID", "BROKEN", "EMPTY"]


class HoldoutAccessLogEntry(StudioContract):
    schema_version: str = HOLDOUT_ACCESS_LOG_SCHEMA_VERSION

    sequence_number: int  # monotonic, starts at 1, one gap-free counter for the whole project-wide log
    previous_entry_hash: str | None  # None only for sequence_number == 1
    entry_hash: str  # sha256(canonical_json(this entry, excluding entry_hash itself))

    analysis_contract_hash: str | None  # content_hash() of the AnalysisContract active at access time, if any
    paper_run_id: str | None

    actor: str
    process: str
    access_type: str
    access_path: str
    resource_id: str
    resource_hash: str | None

    timestamp_utc: str
    reason: str

    @staticmethod
    def make_entry_id(*, user: str, process: str, timestamp_utc: str, resource_accessed: str) -> str:
        # Kept for backward-compatible id derivation semantics (same inputs
        # as before renaming user->actor/resource_accessed->access_path);
        # entry identity itself is now sequence_number, not this string.
        return identity_hash(user, process, timestamp_utc, resource_accessed, prefix="holdout-access")


class HoldoutChainVerificationResult(StudioContract):
    status: HoldoutChainStatus
    entry_count: int
    broken_at_sequence: int | None = None
    findings: list[str] = []
