"""Fase 1 closure item A.4: a run must never depend only on
ble_rffi_studio's mutable manifests at their original location. At
create_run() time, every input manifest this run's dataset/split actually
reference is COPIED into the run's own `01_inputs/input_snapshot/` -- not
merely referenced by path -- so a later edit or deletion in
storage/ble_rffi_studio/ can never silently change what this run's analysis
was computed from. Real I/Q files are the one deliberate exception (they
can be gigabytes): those stay by-reference, but the reference itself
records the fully-resolved path, size, and SHA-256 at snapshot time, so a
later mismatch is at least detectable even though the bytes are not
duplicated.
"""
from __future__ import annotations

from .common import StudioContract

INPUT_ARTIFACT_INDEX_SCHEMA_VERSION = "ble-scientific-results-input-artifact-index-v1"


class InputSnapshotEntry(StudioContract):
    source_path: str
    artifact_type: str
    artifact_id: str
    version: str | None = None
    size_bytes: int
    sha256: str
    snapshot_path: str | None  # None for by-reference-only entries (real I/Q)


class InputArtifactIndex(StudioContract):
    schema_version: str = INPUT_ARTIFACT_INDEX_SCHEMA_VERSION
    paper_run_id: str
    generated_at: str
    entries: list[InputSnapshotEntry] = []
