"""Enrolled-population class-exclusion metric sensitivity (2026-08-09
addition -- did not exist before this pass; renamed 2026-08-22,
methodological-audit item 4). Reuses the same per-example prediction
records and accuracy definition every other confirmatory metric in this
package uses (see evaluator.py's balanced_accuracy/macro_f1) -- no new
model, no retraining. This is NOT a leave-one-device-out cross-validation:
the underlying model was trained WITH every enrolled device's examples,
including the one being "excluded" here. What this function actually does
is recompute the SAME already-scored predictions from that one fixed
model, filtering one class's own examples out of the aggregate metric each
time, to show how much the reported balanced accuracy/accuracy depends on
any single enrolled class's contribution to the average -- never how the
model would perform on a device it never saw during training. Calling this
"leave-one-device-out" (its original 2026-08-09 name) overstated what it
measures; the misnomer was caught during a methodological audit of the
paper this feeds, not during the original implementation.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from .metrics import balanced_accuracy


@dataclass(frozen=True)
class ClassExclusionSensitivityResult:
    excluded_device_id: str
    n_comparable: int
    accuracy: float | None
    balanced_accuracy_value: float | None


def enrolled_population_class_exclusion_sensitivity(
    predictions: list[dict[str, Any]], device_id_by_example_id: dict[str, str], known_classes: Sequence[str],
) -> list[ClassExclusionSensitivityResult]:
    """`predictions` are already-scored records (`example_id`, `true_label`,
    `predicted_label`) from ONE real, already-trained, frozen model -- that
    model was fit on every enrolled device's examples, this device included;
    nothing here retrains or refits anything. One result per device that
    appears in `device_id_by_example_id`, excluding that device's own
    examples from the METRIC computation only (post-hoc filtering of
    already-scored predictions, exactly the same shape
    Evaluator.evaluate_split consumes). Returns [] (never a fabricated
    result) when no prediction maps to a known device."""
    device_ids = sorted({device_id_by_example_id[p["example_id"]] for p in predictions if p["example_id"] in device_id_by_example_id})
    results: list[ClassExclusionSensitivityResult] = []
    for excluded_device in device_ids:
        remaining = [
            p for p in predictions
            if device_id_by_example_id.get(p["example_id"], excluded_device) != excluded_device
        ]
        comparable = [p for p in remaining if p["true_label"] in known_classes]
        if not comparable:
            results.append(ClassExclusionSensitivityResult(excluded_device_id=excluded_device, n_comparable=0, accuracy=None, balanced_accuracy_value=None))
            continue
        accuracy = sum(1 for p in comparable if p["predicted_label"] == p["true_label"]) / len(comparable)
        try:
            ba = balanced_accuracy([p["true_label"] for p in comparable], [p["predicted_label"] for p in comparable], labels=list(known_classes))
        except ValueError:
            ba = None
        results.append(ClassExclusionSensitivityResult(excluded_device_id=excluded_device, n_comparable=len(comparable), accuracy=accuracy, balanced_accuracy_value=ba))
    return results
