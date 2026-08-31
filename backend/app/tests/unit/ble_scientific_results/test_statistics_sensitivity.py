from __future__ import annotations

from app.modules.ble_scientific_results.statistics.sensitivity import enrolled_population_class_exclusion_sensitivity


def _predictions() -> list[dict]:
    return [
        {"example_id": "e1", "true_label": "A", "predicted_label": "A"},
        {"example_id": "e2", "true_label": "A", "predicted_label": "A"},
        {"example_id": "e3", "true_label": "B", "predicted_label": "A"},  # device D2's only example, misclassified
        {"example_id": "e4", "true_label": "B", "predicted_label": "B"},
    ]


def _device_map() -> dict[str, str]:
    return {"e1": "D1", "e2": "D1", "e3": "D2", "e4": "D3"}


def test_excluding_the_device_that_drags_the_score_down_raises_the_remaining_accuracy():
    results = enrolled_population_class_exclusion_sensitivity(_predictions(), _device_map(), known_classes=["A", "B"])
    by_device = {r.excluded_device_id: r for r in results}
    assert set(by_device.keys()) == {"D1", "D2", "D3"}
    # Excluding D2 (whose only example is misclassified) should leave a
    # perfect remaining accuracy.
    assert by_device["D2"].accuracy == 1.0
    assert by_device["D2"].n_comparable == 3


def test_returns_empty_list_when_no_prediction_maps_to_a_known_device():
    results = enrolled_population_class_exclusion_sensitivity(_predictions(), {}, known_classes=["A", "B"])
    assert results == []


def test_excluded_device_with_nothing_left_comparable_reports_none_not_a_fabricated_number():
    predictions = [{"example_id": "e1", "true_label": "A", "predicted_label": "A"}]
    results = enrolled_population_class_exclusion_sensitivity(predictions, {"e1": "D1"}, known_classes=["A"])
    assert len(results) == 1
    assert results[0].accuracy is None
    assert results[0].n_comparable == 0
