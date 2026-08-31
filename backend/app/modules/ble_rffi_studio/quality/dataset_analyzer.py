"""Real, computed dataset quality checks -- nothing here is a hardcoded
"PASSED" literal. exact_duplicates and sample_overlap are blocking gates;
near_duplicates is always DIAGNOSTIC_CHECK (design correction #12) and can
never by itself produce NOT_ACCEPTED_FOR_TRAINING.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from ..contracts import (
    DatasetManifest,
    DatasetQualityReport,
    ExactDuplicatesResult,
    ExampleRecord,
    NearDuplicateResult,
    SampleOverlapPairDetail,
    SampleOverlapResult,
)

DEFAULT_NEAR_DUPLICATE_THRESHOLD = 0.98
DEFAULT_MAX_GROUP_SIZE = 300


class DatasetAnalyzer:
    def check_exact_duplicates(self, examples: list[ExampleRecord]) -> ExactDuplicatesResult:
        groups: dict[tuple[str, int, int], list[str]] = {}
        for example in examples:
            key = (example.source_iq_sha256, example.iq_start_sample, example.iq_end_sample)
            groups.setdefault(key, []).append(example.example_id)
        duplicate_groups = [sorted(ids) for ids in groups.values() if len(ids) > 1]
        return ExactDuplicatesResult(status="FAILED" if duplicate_groups else "PASSED", duplicate_groups=duplicate_groups)

    def check_sample_overlap(self, examples: list[ExampleRecord]) -> SampleOverlapResult:
        by_source: dict[str, list[ExampleRecord]] = {}
        for example in examples:
            by_source.setdefault(example.source_iq_sha256, []).append(example)

        overlapping_pairs: list[list[str]] = []
        pair_details: list[SampleOverlapPairDetail] = []
        for group in by_source.values():
            ordered = sorted(group, key=lambda e: e.iq_start_sample)
            for i in range(len(ordered)):
                a = ordered[i]
                for j in range(i + 1, len(ordered)):
                    b = ordered[j]
                    if b.iq_start_sample >= a.iq_end_sample:
                        break  # sorted by start -- no later item can overlap `a` either
                    if a.iq_start_sample == b.iq_start_sample and a.iq_end_sample == b.iq_end_sample:
                        continue  # exact duplicate, already reported by check_exact_duplicates
                    overlapping_pairs.append(sorted([a.example_id, b.example_id]))
                    pair_details.append(self._describe_overlap(a, b))
        return SampleOverlapResult(status="FAILED" if overlapping_pairs else "PASSED", overlapping_pairs=overlapping_pairs, pair_details=pair_details)

    def _describe_overlap(self, a: ExampleRecord, b: ExampleRecord) -> SampleOverlapPairDetail:
        """Never a vague "found N pairs" -- names exactly which two examples,
        how much of their windows overlap, and (from evidence actually on the
        two ExampleRecords, never guessed) why the extractor produced them
        this close together. The extractor itself never creates overlapping
        windows on purpose; every case below is two independently detected
        real RF events landing close together, not intentional windowing."""
        overlap_start = max(a.iq_start_sample, b.iq_start_sample)
        overlap_end = min(a.iq_end_sample, b.iq_end_sample)
        overlap_samples = max(0, overlap_end - overlap_start)
        span_a = a.iq_end_sample - a.iq_start_sample
        span_b = b.iq_end_sample - b.iq_start_sample
        smaller_span = min(span_a, span_b)
        overlap_fraction = (overlap_samples / smaller_span) if smaller_span > 0 else 0.0

        if a.packet_id == b.packet_id:
            reason = (
                "IDENTICAL_PACKET_DECODED_TWICE: the same decoded packet_id produced two ExampleRecord "
                "entries -- a real extractor bug, never intentional windowing."
            )
        elif a.candidate_id == b.candidate_id:
            reason = (
                f"TWO_DISTINCT_PACKETS_SAME_BURST_WINDOW: two independently decoded, CRC-checked BLE packets "
                f"(packet_id {a.packet_id} vs {b.packet_id}) were detected inside the same RF burst candidate "
                f"({a.candidate_id}) -- their real transmissions overlapped in time; not an intentional sliding window."
            )
            if a.association_status == "PHYSICAL_ISOLATION_DECLARED" and a.logical_transmitter_id != b.logical_transmitter_id:
                reason += (
                    f" Both were attributed to '{a.physical_unit_id}' only because physical isolation was declared "
                    f"for this capture -- the decoded addresses actually differ ({a.logical_transmitter_id} vs "
                    f"{b.logical_transmitter_id}), meaning a second, unregistered transmitter was active nearby "
                    "during this capture (a likely isolation-declaration violation, not a labeling bug)."
                )
        else:
            reason = (
                f"TWO_DISTINCT_BURSTS_OVERLAP: two independently detected RF burst candidates "
                f"({a.candidate_id} vs {b.candidate_id}) produced packet windows that overlap in raw IQ samples -- "
                "two real, close-in-time RF events, never an intentional overlapping window."
            )

        return SampleOverlapPairDetail(
            example_id_a=a.example_id, example_id_b=b.example_id,
            capture_id_a=a.capture_id, capture_id_b=b.capture_id,
            iq_start_sample_a=a.iq_start_sample, iq_end_sample_a=a.iq_end_sample,
            iq_start_sample_b=b.iq_start_sample, iq_end_sample_b=b.iq_end_sample,
            overlap_samples=overlap_samples, overlap_fraction_of_smaller_window=round(overlap_fraction, 4),
            reason=reason,
        )

    def resolve_overlaps(self, examples: list[ExampleRecord]) -> dict[str, str]:
        """Deterministic, reproducible fix for check_exact_duplicates()/
        check_sample_overlap() FAILED gates -- returns example_id -> reason
        for every example that must be excluded (dataset_eligibility set to
        QUARANTINED by the caller) so the remaining set is duplicate-free and
        overlap-free. Never guesses which of two overlapping decodes is
        "better": there is no signal on an ExampleRecord this pipeline can
        independently trust for that (both already passed CRC/quality_status
        before reaching here). Two separate, principled rules instead:

        1. Exact duplicates (identical source_iq_sha256/start/end): keep the
           lexicographically-lowest example_id, exclude the rest -- an exact
           duplicate carries zero additional information either way.
        2. Overlapping-but-not-identical pairs: within each source IQ file,
           run the textbook "maximum non-overlapping interval subset" greedy
           sweep (sort by iq_end_sample, keep an interval only if it starts
           at or after the last KEPT interval's end) -- this keeps the
           largest possible number of independent examples, never an
           arbitrary "first come" pick, and its result cannot depend on the
           input's original ordering."""
        excluded: dict[str, str] = {}

        exact_groups: dict[tuple[str, int, int], list[ExampleRecord]] = {}
        for example in examples:
            key = (example.source_iq_sha256, example.iq_start_sample, example.iq_end_sample)
            exact_groups.setdefault(key, []).append(example)
        for group in exact_groups.values():
            if len(group) < 2:
                continue
            ordered = sorted(group, key=lambda e: e.example_id)
            kept = ordered[0]
            for dup in ordered[1:]:
                excluded[dup.example_id] = (
                    f"SUPERSEDED_BY_DUPLICATE_RESOLUTION: exact duplicate of {kept.example_id} "
                    "(identical source IQ file and sample range) -- carries no independent information."
                )

        remaining_by_source: dict[str, list[ExampleRecord]] = {}
        for example in examples:
            if example.example_id in excluded:
                continue
            remaining_by_source.setdefault(example.source_iq_sha256, []).append(example)

        for group in remaining_by_source.values():
            ordered = sorted(group, key=lambda e: (e.iq_end_sample, e.example_id))
            kept_end: int | None = None
            kept_id: str | None = None
            for example in ordered:
                if kept_end is not None and example.iq_start_sample < kept_end:
                    excluded[example.example_id] = (
                        f"SUPERSEDED_BY_SAMPLE_OVERLAP_RESOLUTION: overlaps {kept_id} in raw IQ samples -- "
                        "excluded by a deterministic maximum-non-overlapping-subset resolution (keeps the "
                        "largest possible set of independent examples), never a quality judgement between "
                        "the two decodes."
                    )
                    continue
                kept_end = example.iq_end_sample
                kept_id = example.example_id
        return excluded

    def check_near_duplicates(
        self,
        examples: list[ExampleRecord],
        capture_iq_paths: dict[str, Path] | None = None,
        similarity_threshold: float = DEFAULT_NEAR_DUPLICATE_THRESHOLD,
        max_group_size: int = DEFAULT_MAX_GROUP_SIZE,
    ) -> NearDuplicateResult:
        """Real, but deliberately narrow: normalized complex cross-correlation
        magnitude between raw I/Q windows, compared only within the same
        capture (bounding the O(n^2) cost). This is exactly the honest scope
        of a DIAGNOSTIC_CHECK -- it has not been validated for phase/time
        invariance or false-positive rate, so it never blocks freezing."""
        if not capture_iq_paths:
            return NearDuplicateResult(status="NOT_EXECUTED", note="No IQ file paths supplied; near-duplicate diagnostic requires reading raw samples.")

        by_capture: dict[str, list[ExampleRecord]] = {}
        for example in examples:
            by_capture.setdefault(example.capture_id, []).append(example)

        flagged: list[list[str]] = []
        skipped_captures: list[str] = []
        for capture_id, group in by_capture.items():
            path = capture_iq_paths.get(capture_id)
            if path is None or not Path(path).is_file():
                continue
            if len(group) > max_group_size:
                skipped_captures.append(capture_id)
                continue
            data = np.memmap(path, dtype=np.complex64, mode="r")
            windows: dict[str, np.ndarray] = {}
            for example in group:
                start, end = example.iq_start_sample, min(example.iq_end_sample, data.shape[0])
                if start >= end:
                    continue
                windows[example.example_id] = np.asarray(data[start:end])
            ids = list(windows.keys())
            for i in range(len(ids)):
                a = windows[ids[i]]
                for j in range(i + 1, len(ids)):
                    b = windows[ids[j]]
                    n = min(len(a), len(b))
                    if n == 0:
                        continue
                    a_t, b_t = a[:n], b[:n]
                    denom = float(np.linalg.norm(a_t) * np.linalg.norm(b_t))
                    if denom == 0.0:
                        continue
                    similarity = abs(np.vdot(a_t, b_t)) / denom
                    if similarity >= similarity_threshold:
                        flagged.append(sorted([ids[i], ids[j]]))

        note = "Diagnostic only -- never blocks dataset freezing. Compares normalized complex cross-correlation magnitude within the same capture only; not validated for phase/time invariance or false-positive rate."
        if skipped_captures:
            note += f" Skipped {len(skipped_captures)} capture(s) exceeding max_group_size={max_group_size}: {skipped_captures}."
        return NearDuplicateResult(
            status="DIAGNOSTIC_CHECK", similarity_metric="normalized_complex_cross_correlation_magnitude",
            similarity_threshold=similarity_threshold, flagged_pairs=flagged, note=note,
        )

    def build_gate(
        self,
        dataset: DatasetManifest,
        exact_duplicates: ExactDuplicatesResult,
        sample_overlap: SampleOverlapResult,
        near_duplicates: NearDuplicateResult,
        created_at: str,
    ) -> DatasetQualityReport:
        reasons: list[str] = []
        if not dataset.example_ids:
            return DatasetQualityReport(
                dataset_id=dataset.dataset_id, dataset_version=dataset.dataset_version,
                exact_duplicates=exact_duplicates, sample_overlap=sample_overlap, near_duplicates=near_duplicates,
                gate_decision="NOT_ACCEPTED_FOR_TRAINING", gate_reasons=["Dataset has zero examples."], created_at=created_at,
            )

        if exact_duplicates.status == "FAILED":
            reasons.append(f"{len(exact_duplicates.duplicate_groups)} exact-duplicate group(s) found.")
        if sample_overlap.status == "FAILED":
            reasons.append(f"{len(sample_overlap.overlapping_pairs)} overlapping (non-identical) sample-range pair(s) found.")

        if exact_duplicates.status == "FAILED" or sample_overlap.status == "FAILED":
            gate_decision: Any = "NOT_ACCEPTED_FOR_TRAINING"
        elif near_duplicates.status == "DIAGNOSTIC_CHECK" and near_duplicates.flagged_pairs:
            gate_decision = "ACCEPTED_WITH_LIMITATIONS"
            reasons.append(f"{len(near_duplicates.flagged_pairs)} near-duplicate pair(s) flagged as a non-blocking diagnostic; review before drawing strong conclusions.")
        else:
            gate_decision = "ACCEPTED_FOR_TRAINING"

        return DatasetQualityReport(
            dataset_id=dataset.dataset_id, dataset_version=dataset.dataset_version,
            exact_duplicates=exact_duplicates, sample_overlap=sample_overlap, near_duplicates=near_duplicates,
            gate_decision=gate_decision, gate_reasons=reasons, created_at=created_at,
        )
