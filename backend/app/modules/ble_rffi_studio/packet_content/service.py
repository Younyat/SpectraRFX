"""RQ4 orchestration: ties field_mapping.py's pure sample-range math to real,
already-decoded packets. pdu_type_name comes from the SAME
packet_association_ledger.jsonl EvidenceStage already reads (this row's
"pdu_type" field, itself sourced from the decoder's pdu_type_name -- see
ble_offline_replay.py's _build_ledger) -- read directly here rather than
adding a new field to ExampleRecord, since packet_content is a derived,
on-demand artifact, not part of the evidence identity/labeling schema.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import numpy as np

from app.infrastructure.ble.capture.ble_offline_replay import read_jsonl

from ..contracts import ExampleRecord
from .field_mapping import AdvaExcludedArtifact, AnalyticalRegion, derive_packet_content_variants


def resolve_latest_replay_dir(legacy_capture_root: Path, capture_id: str) -> Path | None:
    replays_dir = legacy_capture_root / capture_id / "offline_replays"
    if not replays_dir.is_dir():
        return None
    ledgers = sorted(replays_dir.glob("*/packet_association_ledger.jsonl"))
    return ledgers[-1].parent if ledgers else None


def load_pdu_type_by_packet_id(replay_dir: Path) -> dict[str, str | None]:
    ledger_path = replay_dir / "packet_association_ledger.jsonl"
    return {row["packet_id"]: row.get("pdu_type") for row in read_jsonl(ledger_path) if row.get("packet_id")}


def build_packet_content_variants_for_examples(
    examples: list[ExampleRecord], *, legacy_capture_root: Path, capture_iq_paths: dict[str, Path],
) -> dict[str, dict[AnalyticalRegion, np.ndarray | None]]:
    """Real, end-to-end RQ4 derivation over a list of already-evidenced
    examples: for each, loads its own IQ window from the ORIGINAL capture IQ
    file (capture_iq_paths -- the same caller-resolved capture_id -> path
    mapping TrainingService/OfflineInferenceService already take, never
    re-derived from a downstream artifact), looks up its real pdu_type from
    the same capture's packet_association_ledger.jsonl (under
    legacy_capture_root), and returns FULL_BURST/ADVA_MASKED/PRE_PDU. An
    example whose capture has no resolvable replay/ledger yields
    pdu_type_name=None -- ADVA_MASKED becomes None (unknown layout),
    FULL_BURST/PRE_PDU are still always real."""
    from ..preprocessing import load_iq_window

    pdu_type_cache: dict[str, dict[str, str | None]] = {}
    results: dict[str, dict[AnalyticalRegion, np.ndarray | None]] = {}

    for example in examples:
        if example.capture_id not in pdu_type_cache:
            replay_dir = resolve_latest_replay_dir(legacy_capture_root, example.capture_id)
            pdu_type_cache[example.capture_id] = load_pdu_type_by_packet_id(replay_dir) if replay_dir else {}
        pdu_type_name = pdu_type_cache[example.capture_id].get(example.packet_id)

        window = load_iq_window(capture_iq_paths[example.capture_id], example.iq_start_sample, example.iq_end_sample)
        results[example.example_id] = derive_packet_content_variants(
            iq_window=window, iq_start_sample=example.iq_start_sample, sample_rate_sps=float(example.sample_rate_sps), pdu_type_name=pdu_type_name,
        )
    return results


def region_restricted_provider_and_eligible_ids(
    examples: list[ExampleRecord], *, analytical_region: AnalyticalRegion, legacy_capture_root: Path, capture_iq_paths: dict[str, Path],
) -> tuple[Callable[[ExampleRecord], np.ndarray], set[str]]:
    """RQ4 region-specific fitting (2026-08-12): builds the
    TrainingService/OfflineInferenceService `iq_window_provider` hook for
    ONE analytical_region, plus the real set of example_ids for which that
    region actually has a real array (never None) -- an example whose
    derived region variant is None (e.g. ADVA_EXCLUDED for a PDU type
    outside PDU_TYPES_WITH_LEADING_ADVA) is simply absent from both the
    provider and the eligible set, never substituted with a fallback
    window. Comparability (point 6/7 of the RQ4 closure): the SAME
    derive_packet_content_variants used everywhere else in this package is
    reused here, never a second derivation -- FULL_BURST never needs this
    helper at all (the caller should keep using the plain, unrestricted
    path for it, since FULL_BURST IS the original, already-loaded window)."""
    variants = build_packet_content_variants_for_examples(examples, legacy_capture_root=legacy_capture_root, capture_iq_paths=capture_iq_paths)
    windows_by_example_id: dict[str, np.ndarray] = {}
    for example_id, region_variants in variants.items():
        value = region_variants.get(analytical_region)
        if value is None:
            continue
        windows_by_example_id[example_id] = value.window if isinstance(value, AdvaExcludedArtifact) else value

    def provider(example: ExampleRecord) -> np.ndarray:
        return windows_by_example_id[example.example_id]

    return provider, set(windows_by_example_id.keys())
