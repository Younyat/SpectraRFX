"""Paper progress dashboard, point 4 (2026-08-11): S1/S2 engineering report
aggregators -- pure functions over explicitly-synthetic fixtures, never
touching real repository storage. Both reuse only existing metric
primitives (balanced_accuracy/coverage); neither is a new statistical test.
"""
from __future__ import annotations

import pytest

from app.modules.ble_scientific_results.engineering_reports import (
    compute_channel_transport_report,
    compute_evidence_interval_id,
    compute_offline_nearlive_report,
)

CHANNEL_TRANSPORT_SYNTHETIC_FIXTURE = {
    37: [
        {"example_id": "e1", "true_label": "A", "predicted_label": "A", "final_decision": "IDENTIFIED"},
        {"example_id": "e2", "true_label": "B", "predicted_label": "B", "final_decision": "IDENTIFIED"},
    ],
    38: [
        {"example_id": "e3", "true_label": "A", "predicted_label": "A", "final_decision": "IDENTIFIED"},
        {"example_id": "e4", "true_label": "B", "predicted_label": "A", "final_decision": "IDENTIFIED"},
    ],
}

_MATCHED_ID = compute_evidence_interval_id(source_iq_sha256="iq-sha-1", sample_start=0, sample_end=1000)
_MATCHED_ID_2 = compute_evidence_interval_id(source_iq_sha256="iq-sha-2", sample_start=500, sample_end=1500)
_OFFLINE_ONLY_ID = compute_evidence_interval_id(source_iq_sha256="iq-sha-3", sample_start=0, sample_end=1000)
_NEARLIVE_ONLY_ID = compute_evidence_interval_id(source_iq_sha256="iq-sha-4", sample_start=0, sample_end=1000)

OFFLINE_PREDICTIONS_SYNTHETIC_FIXTURE = [
    {"evidence_interval_id": _MATCHED_ID, "predicted_class": "A", "final_decision": "IDENTIFIED", "class_probability": 0.9},
    {"evidence_interval_id": _MATCHED_ID_2, "predicted_class": "B", "final_decision": "IDENTIFIED", "class_probability": 0.7},
    {"evidence_interval_id": _OFFLINE_ONLY_ID, "predicted_class": "A", "final_decision": "IDENTIFIED", "class_probability": 0.6},
]
NEARLIVE_PREDICTIONS_SYNTHETIC_FIXTURE = [
    {"evidence_interval_id": _MATCHED_ID, "predicted_class": "A", "final_decision": "IDENTIFIED", "class_probability": 0.85},
    {"evidence_interval_id": _MATCHED_ID_2, "predicted_class": "A", "final_decision": "IDENTIFIED", "class_probability": 0.6},
    {"evidence_interval_id": _NEARLIVE_ONLY_ID, "predicted_class": "B", "final_decision": "IDENTIFIED", "class_probability": 0.55},
]


def test_channel_transport_report_computes_real_metrics_per_channel():
    report = compute_channel_transport_report(
        frozen_bundle_id="BUNDLE-CH37-DEV", predictions_by_channel=CHANNEL_TRANSPORT_SYNTHETIC_FIXTURE,
        known_classes=["A", "B"], center_frequency_hz_by_channel={37: 2_402_000_000, 38: 2_426_000_000},
    )
    by_channel = {row["channel"]: row for row in report.per_channel}
    assert by_channel[37]["balanced_accuracy"] == 1.0
    assert by_channel[38]["balanced_accuracy"] == 0.5
    assert by_channel[38]["confusion_matrix"]["B"]["A"] == 1
    assert report.interpretation_note == "bounded channel transport -- never channel invariance"


def test_channel_transport_report_rejects_empty_input():
    with pytest.raises(ValueError):
        compute_channel_transport_report(frozen_bundle_id="B", predictions_by_channel={}, known_classes=["A"], center_frequency_hz_by_channel={})


def test_channel_transport_report_is_none_for_per_unit_recall_when_no_physical_unit_id_was_ever_supplied():
    report = compute_channel_transport_report(
        frozen_bundle_id="BUNDLE-CH37-DEV", predictions_by_channel=CHANNEL_TRANSPORT_SYNTHETIC_FIXTURE,
        known_classes=["A", "B"], center_frequency_hz_by_channel={37: 2_402_000_000, 38: 2_426_000_000},
    )
    by_channel = {row["channel"]: row for row in report.per_channel}
    assert by_channel[37]["per_unit_recall"] is None  # honest -- CHANNEL_TRANSPORT_SYNTHETIC_FIXTURE never declares physical_unit_id


def test_channel_transport_report_computes_real_per_unit_recall_when_supplied():
    """S1 closure (2026-08-12): reuses the SAME physical_unit_id join point
    7 already put on every prediction dict -- never a new identity source."""
    predictions_by_channel = {
        37: [
            {"example_id": "e1", "true_label": "UNIT-A", "predicted_label": "UNIT-A", "final_decision": "IDENTIFIED", "physical_unit_id": "UNIT-A"},
            {"example_id": "e2", "true_label": "UNIT-A", "predicted_label": "UNIT-B", "final_decision": "IDENTIFIED", "physical_unit_id": "UNIT-A"},
            {"example_id": "e3", "true_label": "UNIT-B", "predicted_label": "UNIT-B", "final_decision": "IDENTIFIED", "physical_unit_id": "UNIT-B"},
        ],
    }
    report = compute_channel_transport_report(
        frozen_bundle_id="BUNDLE-X", predictions_by_channel=predictions_by_channel,
        known_classes=["UNIT-A", "UNIT-B"], center_frequency_hz_by_channel={37: 1},
    )
    per_unit_recall = report.per_channel[0]["per_unit_recall"]
    assert per_unit_recall["UNIT-A"] == pytest.approx(0.5)  # 1 correct of 2 trials genuinely from UNIT-A
    assert per_unit_recall["UNIT-B"] == pytest.approx(1.0)


def test_channel_transport_uses_only_the_one_named_frozen_bundle():
    report = compute_channel_transport_report(
        frozen_bundle_id="BUNDLE-X", predictions_by_channel=CHANNEL_TRANSPORT_SYNTHETIC_FIXTURE,
        known_classes=["A", "B"], center_frequency_hz_by_channel={37: 1, 38: 2},
    )
    assert all(row["frozen_bundle_id"] == "BUNDLE-X" for row in report.per_channel)


def test_evidence_interval_id_is_stable_and_deterministic():
    a = compute_evidence_interval_id(source_iq_sha256="iq-sha-1", sample_start=0, sample_end=1000)
    b = compute_evidence_interval_id(source_iq_sha256="iq-sha-1", sample_start=0, sample_end=1000)
    c = compute_evidence_interval_id(source_iq_sha256="iq-sha-1", sample_start=0, sample_end=1001)
    assert a == b
    assert a != c


def test_offline_nearlive_report_with_no_predictions_is_no_data():
    report = compute_offline_nearlive_report()
    assert report.pairing_status == "NO_DATA"
    assert report.analytical_agreement is None
    assert report.matched_pair_count == 0
    assert all(v == "NOT_MEASURED" for v in report.computational_behavior.values())


def test_offline_nearlive_report_pairs_by_exact_evidence_interval_match():
    report = compute_offline_nearlive_report(
        offline_predictions=OFFLINE_PREDICTIONS_SYNTHETIC_FIXTURE, nearlive_predictions=NEARLIVE_PREDICTIONS_SYNTHETIC_FIXTURE,
    )
    assert report.pairing_status == "COMPUTED_FROM_EXACT_EVIDENCE_INTERVAL_MATCH"
    assert report.matched_pair_count == 2
    assert report.unpaired_offline_count == 1
    assert report.unpaired_nearlive_count == 1
    assert report.analytical_agreement["decision_count"] == 2
    assert report.analytical_agreement["class_prediction_agreement"] == 0.5
    assert report.analytical_agreement["abstention_agreement"] == 1.0


def test_offline_nearlive_report_never_uses_nearest_timestamp_or_proximity_matching():
    # Two predictions with DIFFERENT evidence_interval_id never pair, no
    # matter how "close" they might otherwise seem -- only exact identity.
    report = compute_offline_nearlive_report(
        offline_predictions=[{"evidence_interval_id": "A", "predicted_class": "X", "final_decision": "IDENTIFIED"}],
        nearlive_predictions=[{"evidence_interval_id": "B", "predicted_class": "X", "final_decision": "IDENTIFIED"}],
    )
    assert report.matched_pair_count == 0
    assert report.unpaired_offline_count == 1
    assert report.unpaired_nearlive_count == 1
    assert report.analytical_agreement is None


def test_offline_nearlive_report_never_fabricates_unmeasured_computational_fields():
    report = compute_offline_nearlive_report(
        offline_predictions=OFFLINE_PREDICTIONS_SYNTHETIC_FIXTURE, nearlive_predictions=NEARLIVE_PREDICTIONS_SYNTHETIC_FIXTURE,
        computational_metrics={"median_latency_ms": 42.0},
    )
    assert report.computational_behavior["median_latency_ms"] == 42.0
    assert report.computational_behavior["p95_latency_ms"] == "NOT_MEASURED"
    assert report.computational_behavior["drop_rate"] == "NOT_MEASURED"
