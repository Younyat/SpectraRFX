"""Paper progress dashboard, point 4 (2026-08-11): S1 (CH37->CH38/39
channel transport) and S2 (offline vs near-live) engineering-analysis
report schemas + pure aggregation functions. Explicitly separate from
RQ1-RQ4 -- these interpret as "bounded channel transport" (never "channel
invariance") and offline/near-live equivalence, never a paper RQ.

Both aggregation functions reuse ONLY already-established, dependency-light
primitives (`statistics.metrics.balanced_accuracy`/`coverage`) -- no new
statistical test, no retraining, no model change. Neither function computes
anything from raw I/Q or re-runs a model; both take already-scored
per-example predictions the caller supplies (exactly like
`statistics.sensitivity.enrolled_population_class_exclusion_sensitivity` already does for
RQ2/RQ3/RQ4).

S1's method (frozen model trained on CH37 development data, no retraining,
same decision rule applied to CH38/39 examples) is fully specified by the
shape of `compute_channel_transport_report`'s input -- the caller is
structurally required to supply already-scored predictions from ONE frozen
model, never a per-channel retrained one.

S2's join-key was frozen 2026-08-11 (before any real campaign runs, so it
is never adjusted after seeing results): two decisions -- one offline, one
near-live -- form a pair iff they share the same `evidence_interval_id`
(see `compute_evidence_interval_id`), a real, deterministic identity over
(source_iq_sha256, sample_start, sample_end). `compute_offline_nearlive_report`
performs this exact match itself (a real, dependency-light set
intersection -- not a new statistical test); an id present on only one
side is UNPAIRED and counted, never silently dropped, backfilled, or
matched by nearest timestamp.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Sequence

from .statistics.metrics import balanced_accuracy, coverage

CHANNEL_TRANSPORT_SCHEMA_VERSION = "ble-scientific-results-channel-transport-v1"
OFFLINE_NEARLIVE_SCHEMA_VERSION = "ble-scientific-results-offline-nearlive-v1"


def _macro_f1(true_labels: Sequence[str], predicted_labels: Sequence[str], labels: Sequence[str]) -> float:
    """Same macro-F1 definition Evaluator.evaluate_split already uses
    (precision/recall per class, averaged) -- reimplemented here in a
    dependency-light way (no sklearn/Evaluator import) purely to avoid a
    circular import (ble_rffi_studio.evaluation.evaluator already imports
    FROM this package's statistics module)."""
    f1_scores = []
    for label in labels:
        tp = sum(1 for t, p in zip(true_labels, predicted_labels) if t == label and p == label)
        fp = sum(1 for t, p in zip(true_labels, predicted_labels) if t != label and p == label)
        fn = sum(1 for t, p in zip(true_labels, predicted_labels) if t == label and p != label)
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
        f1_scores.append(f1)
    return sum(f1_scores) / len(f1_scores) if f1_scores else 0.0


def _confusion_matrix(true_labels: Sequence[str], predicted_labels: Sequence[str], labels: Sequence[str]) -> dict[str, dict[str, int]]:
    matrix = {t: {p: 0 for p in labels} for t in labels}
    for t, p in zip(true_labels, predicted_labels):
        if t in matrix and p in matrix[t]:
            matrix[t][p] += 1
    return matrix


def _per_unit_recall(decided: list[dict[str, Any]]) -> dict[str, float] | None:
    """S1 closure (2026-08-12): real per-unit recall from the SAME real
    physical_unit_id join every decided prediction now carries (Scientific
    Closure pass point 7) -- None (never a fabricated dict) when no
    prediction here ever declared a physical_unit_id at all."""
    units = sorted({p.get("physical_unit_id") for p in decided if p.get("physical_unit_id")})
    if not units:
        return None
    result: dict[str, float] = {}
    for unit in units:
        unit_trials = [p for p in decided if p.get("physical_unit_id") == unit and p["true_label"] == unit]
        if unit_trials:
            result[unit] = sum(1 for p in unit_trials if p["predicted_label"] == p["true_label"]) / len(unit_trials)
    return result or None


@dataclass
class ChannelTransportReport:
    schema_version: str = CHANNEL_TRANSPORT_SCHEMA_VERSION
    per_channel: list[dict[str, Any]] = field(default_factory=list)
    interpretation_note: str = "bounded channel transport -- never channel invariance"


def compute_channel_transport_report(
    *, frozen_bundle_id: str, predictions_by_channel: dict[int, list[dict[str, Any]]], known_classes: Sequence[str],
    center_frequency_hz_by_channel: dict[int, int],
) -> ChannelTransportReport:
    """`predictions_by_channel`: {channel: [{"example_id","true_label",
    "predicted_label","final_decision"}, ...]} -- already-scored predictions
    from the ONE frozen model named by `frozen_bundle_id` (no retraining per
    channel, structurally enforced by there being only one bundle id for
    the whole call). Raises ValueError on an empty input -- never returns a
    fabricated zero-channel report."""
    if not predictions_by_channel:
        raise ValueError("NEED_AT_LEAST_ONE_CHANNEL_OF_PREDICTIONS")
    per_channel: list[dict[str, Any]] = []
    for channel, predictions in sorted(predictions_by_channel.items()):
        comparable = [p for p in predictions if p["true_label"] in known_classes]
        decided = [p for p in comparable if p.get("final_decision", "IDENTIFIED") != "INSUFFICIENT_EVIDENCE"]
        true_labels = [p["true_label"] for p in decided]
        predicted_labels = [p["predicted_label"] for p in decided]
        entry: dict[str, Any] = {
            "channel": channel, "center_frequency_hz": center_frequency_hz_by_channel.get(channel),
            "frozen_bundle_id": frozen_bundle_id, "windows": len(predictions),
        }
        if decided:
            entry["balanced_accuracy"] = balanced_accuracy(true_labels, predicted_labels, labels=list(known_classes))
            entry["macro_f1"] = _macro_f1(true_labels, predicted_labels, known_classes)
            entry["coverage"] = coverage(len(comparable), len(comparable) - len(decided)) if comparable else None
            entry["confusion_matrix"] = _confusion_matrix(true_labels, predicted_labels, known_classes)
            entry["per_unit_recall"] = _per_unit_recall(decided)
        else:
            entry["balanced_accuracy"] = None
            entry["macro_f1"] = None
            entry["coverage"] = None
            entry["confusion_matrix"] = None
            entry["per_unit_recall"] = None
        per_channel.append(entry)
    return ChannelTransportReport(per_channel=per_channel)


def compute_evidence_interval_id(*, source_iq_sha256: str, sample_start: int, sample_end: int) -> str:
    """Reporting closure, point B (2026-08-11): the frozen S2 join-key. Two
    decisions -- one offline, one near-live -- refer to "the same retained
    sample interval" iff they were computed over the identical
    (source_iq_sha256, sample_start, sample_end) triple. This is a real,
    deterministic identity derived from already-real fields (the same ones
    `ExampleRecord` already carries) -- never a nearest-timestamp or other
    proximity heuristic. Frozen before any real campaign starts, so the
    matching rule is never adjusted after seeing results."""
    digest = hashlib.sha256(f"{source_iq_sha256}:{sample_start}:{sample_end}".encode("utf-8")).hexdigest()
    return f"evidence-interval-{digest[:32]}"


@dataclass
class OfflineNearliveReport:
    schema_version: str = OFFLINE_NEARLIVE_SCHEMA_VERSION
    pairing_status: str = "NO_DATA"  # NO_DATA | COMPUTED_FROM_EXACT_EVIDENCE_INTERVAL_MATCH
    pairing_note: str = "No offline or near-live predictions supplied -- nothing to pair."
    matched_pair_count: int = 0
    unpaired_offline_count: int = 0
    unpaired_nearlive_count: int = 0
    analytical_agreement: dict[str, Any] | None = None
    computational_behavior: dict[str, Any] | None = None


_COMPUTATIONAL_FIELDS = ("median_latency_ms", "p95_latency_ms", "throughput_per_s", "drop_count", "drop_rate", "backlog", "declared_hardware", "declared_software_path")


def compute_offline_nearlive_report(
    *, offline_predictions: list[dict[str, Any]] | None = None, nearlive_predictions: list[dict[str, Any]] | None = None,
    computational_metrics: dict[str, Any] | None = None,
) -> OfflineNearliveReport:
    """`offline_predictions`/`nearlive_predictions`: each entry a dict with
    a real `evidence_interval_id` (see `compute_evidence_interval_id`) plus
    `predicted_class`/`final_decision` and optionally `class_probability`.
    Pairing is a real, deterministic exact match on `evidence_interval_id`
    -- NEVER nearest-timestamp or other proximity heuristic, and never
    invented after the fact. An id present on only one side is
    `UNPAIRED` (counted, never silently dropped or backfilled).
    `computational_metrics`: a dict with whichever of _COMPUTATIONAL_FIELDS
    were actually measured -- any field absent stays `NOT_MEASURED`, never
    0."""
    report = OfflineNearliveReport()
    offline_predictions = offline_predictions or []
    nearlive_predictions = nearlive_predictions or []

    if offline_predictions or nearlive_predictions:
        offline_by_id = {p["evidence_interval_id"]: p for p in offline_predictions}
        nearlive_by_id = {p["evidence_interval_id"]: p for p in nearlive_predictions}
        matched_ids = sorted(set(offline_by_id) & set(nearlive_by_id))
        report.matched_pair_count = len(matched_ids)
        report.unpaired_offline_count = len(offline_by_id) - len(matched_ids)
        report.unpaired_nearlive_count = len(nearlive_by_id) - len(matched_ids)
        report.pairing_status = "COMPUTED_FROM_EXACT_EVIDENCE_INTERVAL_MATCH"
        report.pairing_note = (
            f"Paired by exact evidence_interval_id match (source_iq_sha256 + sample_start + sample_end) -- "
            f"{report.matched_pair_count} matched, {report.unpaired_offline_count} offline unpaired, "
            f"{report.unpaired_nearlive_count} near-live unpaired. No nearest-timestamp or proximity heuristic used."
        )
        if matched_ids:
            n = len(matched_ids)
            class_agree = sum(1 for eid in matched_ids if offline_by_id[eid].get("predicted_class") == nearlive_by_id[eid].get("predicted_class"))
            abstention_agree = sum(1 for eid in matched_ids if offline_by_id[eid].get("final_decision") == nearlive_by_id[eid].get("final_decision"))
            score_pairs = [
                (offline_by_id[eid].get("class_probability"), nearlive_by_id[eid].get("class_probability")) for eid in matched_ids
                if offline_by_id[eid].get("class_probability") is not None and nearlive_by_id[eid].get("class_probability") is not None
            ]
            report.analytical_agreement = {
                "decision_count": n,
                "class_prediction_agreement": class_agree / n,
                "abstention_agreement": abstention_agree / n,
                "score_agreement_mean_abs_diff": (sum(abs(o - nl) for o, nl in score_pairs) / len(score_pairs)) if score_pairs else None,
                "score_agreement_n_comparable": len(score_pairs),
            }

    computational_metrics = computational_metrics or {}
    report.computational_behavior = {field_name: computational_metrics.get(field_name, "NOT_MEASURED") for field_name in _COMPUTATIONAL_FIELDS}
    return report
