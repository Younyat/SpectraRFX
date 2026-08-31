"""Fase 5: comparable metrics across models, plus UNKNOWN-rejection threshold
calibration. Design correction #16: the acceptance threshold is selected
using VALIDATION ONLY, and must be evaluated against both known-class
predictions and true "unknown" examples (an example whose true label never
appeared among TRAIN's classes) -- never picked to just look good on the
known classes alone.

This implementation calibrates on max-class-probability rather than
embedding distance to a centroid; the design explicitly allows either
approach and warns against treating either as an automatically-accepted
solution -- so `distance` is left None here and documented as N/A for this
probability-based calibration, not silently omitted.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Sequence

import numpy as np
from sklearn.metrics import confusion_matrix, precision_recall_fscore_support

# Coverage/risk-coverage correction (2026-08-08): real, tested primitives
# that existed in ble_scientific_results.statistics but had no production
# caller anywhere -- these are leaf, dependency-light functions (no import
# of anything ble_rffi_studio-adjacent), so a plain module-level import is
# safe here, unlike the ScientificResultsRepository coupling in
# studio_repository.py (which needs a deferred import to avoid a real
# circular-import risk that does not exist for these).
from app.modules.ble_scientific_results.statistics.inference import (
    BootstrapCiResult,
    hierarchical_cluster_bootstrap,
    independent_domain_bootstrap_delta_ci,
    matched_stratified_bootstrap_delta_ci,
    paired_cluster_bootstrap_delta_ci,
    risk_coverage_curve,
    stratified_hierarchical_cluster_bootstrap,
)

FinalDecision = Literal["IDENTIFIED", "UNKNOWN", "INSUFFICIENT_EVIDENCE"]


@dataclass
class SplitEvaluationReport:
    split: str
    n_examples: int
    n_comparable_to_known_classes: int
    accuracy: float | None
    precision_per_class: dict[str, float]
    recall_per_class: dict[str, float]
    f1_per_class: dict[str, float]
    confusion_matrix: dict[str, dict[str, int]]
    # "VALID" unless known_classes itself has fewer than 2 entries -- a
    # classifier can never be validated against a single class (a confusion
    # matrix with one row/column proves nothing about discrimination, e.g.
    # TARGET_DEVICE vs BACKGROUND_ENVIRONMENT with only TARGET_DEVICE
    # present). training_service.py's own TRAIN-class gate should make this
    # unreachable in practice -- this is defense in depth, not the primary
    # guard, so a report can never be presented as a real result if it is
    # ever reached anyway.
    evaluation_validity: str = "VALID"
    # Plain accuracy alone can look excellent on an imbalanced or
    # session-confounded split while hiding that one class is essentially
    # never recalled -- macro_f1/balanced_accuracy average PER-CLASS
    # performance equally, so a model that only ever predicts the majority
    # class cannot hide behind a high raw accuracy number. Both are derived
    # from precision_per_class/recall_per_class/f1_per_class above (never
    # recomputed independently), so they can never disagree with the
    # per-class numbers already in this same report. None only when there
    # was nothing comparable to evaluate (mirrors accuracy's own None case).
    macro_f1: float | None = None
    balanced_accuracy: float | None = None
    # Coverage/risk-coverage correction (2026-08-08): the real selective-
    # prediction curve (El-Yaniv & Wiener, 2010) over this split's own
    # comparable predictions -- sweeping every achievable confidence
    # threshold, not just the one bundle_builder.py ends up calibrating.
    # None under the same conditions accuracy is None (nothing comparable,
    # or no probabilities recorded) -- never a fabricated empty curve.
    risk_coverage: list[dict[str, float]] | None = None


def _session_clustered_label_pairs(
    predictions: list[dict[str, Any]], known_classes: list[str], session_id_by_example_id: dict[str, str],
) -> list[list[tuple[str, str]]] | None:
    """Shared clustering step behind bootstrap_balanced_accuracy_ci() and
    bootstrap_balanced_accuracy_delta_ci() -- groups (true_label,
    predicted_label) pairs by real session_id, the same indivisible
    resampling unit split_builder.py's own leakage check treats a session
    as. None when nothing is comparable, matching evaluate_split()'s own
    None convention."""
    comparable = [p for p in predictions if p["true_label"] in known_classes]
    if len(known_classes) < 2 or not comparable:
        return None
    by_session: dict[str, list[tuple[str, str]]] = {}
    for prediction in comparable:
        session_id = session_id_by_example_id.get(prediction["example_id"])
        if session_id is None:
            continue
        by_session.setdefault(session_id, []).append((prediction["true_label"], prediction["predicted_label"]))
    if not by_session:
        return None
    return list(by_session.values())


def _session_clustered_label_pairs_by_true_class(
    predictions: list[dict[str, Any]], known_classes: list[str], session_id_by_example_id: dict[str, str],
) -> dict[str, list[list[tuple[str, str]]]] | None:
    """Methodological-audit fix (2026-08-22, item 3): the same real
    session-clustering step `_session_clustered_label_pairs` performs, but
    additionally grouped by each prediction's own real `true_label` (for
    the closed-set MULTI_DEVICE_CLASSIFICATION task this IS the real
    physical_unit_id -- confirmed directly against a real predictions.json
    entry, never a second identity source) so
    `stratified_hierarchical_cluster_bootstrap` can resample within each
    true-class stratum independently -- guaranteeing every resample keeps
    all `known_classes` represented. Stratifying by `true_label` (not a
    separately-looked-up physical_unit_id) is also the mathematically
    correct choice regardless of task: balanced accuracy is DEFINED as mean
    recall over the true classes, so preserving every true class in every
    resample is exactly what a class-preserving bootstrap for BA needs.
    None when nothing is comparable, matching
    `_session_clustered_label_pairs`'s own None convention."""
    comparable = [p for p in predictions if p["true_label"] in known_classes]
    if len(known_classes) < 2 or not comparable:
        return None
    by_class_session: dict[str, dict[str, list[tuple[str, str]]]] = {}
    for prediction in comparable:
        session_id = session_id_by_example_id.get(prediction["example_id"])
        if session_id is None:
            continue
        by_class_session.setdefault(prediction["true_label"], {}).setdefault(session_id, []).append((prediction["true_label"], prediction["predicted_label"]))
    if not by_class_session:
        return None
    return {true_class: list(sessions.values()) for true_class, sessions in by_class_session.items()}


def _balanced_accuracy_statistic(pairs: Sequence[tuple[str, str]], known_classes: list[str]) -> float:
    """Mean-per-class recall over pooled (true_label, predicted_label)
    pairs -- the same balanced_accuracy definition SplitEvaluationReport
    uses (evaluate_split() below), never a second definition."""
    per_class_recall = []
    for known_class in known_classes:
        class_pairs = [p for p in pairs if p[0] == known_class]
        if not class_pairs:
            continue
        correct = sum(1 for true_label, predicted_label in class_pairs if predicted_label == true_label)
        per_class_recall.append(correct / len(class_pairs))
    return sum(per_class_recall) / len(per_class_recall) if per_class_recall else 0.0


class Evaluator:
    def evaluate_split(self, split: str, predictions: list[dict[str, Any]], known_classes: list[str]) -> SplitEvaluationReport:
        if len(known_classes) < 2:
            return SplitEvaluationReport(
                split=split, n_examples=len(predictions), n_comparable_to_known_classes=0, accuracy=None,
                precision_per_class={}, recall_per_class={}, f1_per_class={}, confusion_matrix={},
                evaluation_validity="INVALID_SINGLE_CLASS_EVALUATION",
            )
        comparable = [p for p in predictions if p["true_label"] in known_classes]
        if not comparable:
            return SplitEvaluationReport(
                split=split, n_examples=len(predictions), n_comparable_to_known_classes=0, accuracy=None,
                precision_per_class={}, recall_per_class={}, f1_per_class={}, confusion_matrix={},
            )
        true_labels = [p["true_label"] for p in comparable]
        predicted_labels = [p["predicted_label"] for p in comparable]
        accuracy = float(np.mean([t == pr for t, pr in zip(true_labels, predicted_labels)]))

        precision, recall, f1, _ = precision_recall_fscore_support(true_labels, predicted_labels, labels=known_classes, zero_division=0)
        cm = confusion_matrix(true_labels, predicted_labels, labels=known_classes)
        confusion = {known_classes[i]: {known_classes[j]: int(cm[i][j]) for j in range(len(known_classes))} for i in range(len(known_classes))}

        return SplitEvaluationReport(
            split=split, n_examples=len(predictions), n_comparable_to_known_classes=len(comparable), accuracy=accuracy,
            precision_per_class=dict(zip(known_classes, precision.tolist())),
            recall_per_class=dict(zip(known_classes, recall.tolist())),
            f1_per_class=dict(zip(known_classes, f1.tolist())),
            confusion_matrix=confusion,
            macro_f1=float(np.mean(f1)), balanced_accuracy=float(np.mean(recall)),
            risk_coverage=self._risk_coverage(comparable),
        )

    def _risk_coverage(self, comparable: list[dict[str, Any]]) -> list[dict[str, float]] | None:
        """Real risk-coverage curve over this split's own comparable
        predictions, using each one's own top-1 probability as its
        confidence score and predicted_label==true_label as correctness --
        None only when no prediction here carries a probabilities dict at
        all (e.g. a caller building a minimal test fixture), never a
        fabricated all-zero curve."""
        confidences: list[float] = []
        correct: list[bool] = []
        for prediction in comparable:
            probabilities = prediction.get("probabilities") or {}
            if not probabilities:
                continue
            confidences.append(max(probabilities.values()))
            correct.append(prediction["predicted_label"] == prediction["true_label"])
        if not confidences:
            return None
        points = risk_coverage_curve(confidences, correct)
        return [{"coverage": p.coverage, "risk": p.risk, "threshold": p.threshold} for p in points]

    def bootstrap_accuracy_ci(
        self, predictions: list[dict[str, Any]], known_classes: list[str], session_id_by_example_id: dict[str, str],
        n_resamples: int = 2000, confidence_level: float = 0.95,
    ) -> BootstrapCiResult | None:
        """Bootstrap correction (2026-08-08): hierarchical_cluster_bootstrap
        existed with real tests but no production caller. Resamples WHOLE
        SESSIONS with replacement (never individual bursts) -- the same
        clustering unit split_builder.py's own leakage check treats as one
        indivisible block, since bursts within one session are correlated,
        not independent draws. None when there is nothing comparable to
        bootstrap over, matching evaluate_split's own None convention."""
        comparable = [p for p in predictions if p["true_label"] in known_classes]
        if len(known_classes) < 2 or not comparable:
            return None
        by_session: dict[str, list[float]] = {}
        for prediction in comparable:
            session_id = session_id_by_example_id.get(prediction["example_id"])
            if session_id is None:
                continue
            by_session.setdefault(session_id, []).append(1.0 if prediction["predicted_label"] == prediction["true_label"] else 0.0)
        if not by_session:
            return None
        cluster_values = list(by_session.values())
        return hierarchical_cluster_bootstrap(
            cluster_values, statistic=lambda values: sum(values) / len(values),
            n_resamples=n_resamples, confidence_level=confidence_level,
        )

    def bootstrap_balanced_accuracy_ci(
        self, predictions: list[dict[str, Any]], known_classes: list[str], session_id_by_example_id: dict[str, str],
        n_resamples: int = 2000, confidence_level: float = 0.95,
    ) -> BootstrapCiResult | None:
        """Same real session-clustered resampling engine as
        bootstrap_accuracy_ci() (hierarchical_cluster_bootstrap, untouched)
        -- the only difference is the statistic being resampled. Balanced
        accuracy needs per-class recall, which a single correct/incorrect
        scalar cannot reconstruct, so each cluster holds
        (true_label, predicted_label) pairs instead of a 0/1 correctness
        value; the statistic recomputes mean-per-class-recall (this
        report's own balanced_accuracy definition, evaluate_split() above)
        over the pooled, resampled pairs. RQ1/RQ2 report Balanced Accuracy
        as their primary metric specifically because raw accuracy hides
        per-class imbalance -- a CI computed on raw accuracy would not
        actually describe the uncertainty of the number being reported."""
        cluster_values = _session_clustered_label_pairs(predictions, known_classes, session_id_by_example_id)
        if cluster_values is None:
            return None
        return hierarchical_cluster_bootstrap(
            cluster_values, statistic=lambda pairs: _balanced_accuracy_statistic(pairs, known_classes),
            n_resamples=n_resamples, confidence_level=confidence_level,
        )

    def bootstrap_balanced_accuracy_delta_ci(
        self, predictions_a: list[dict[str, Any]], predictions_b: list[dict[str, Any]], known_classes: list[str],
        session_id_by_example_id_a: dict[str, str], session_id_by_example_id_b: dict[str, str],
        n_resamples: int = 2000, confidence_level: float = 0.95,
    ) -> BootstrapCiResult | None:
        """RQ1's real delta_dependence = BA_window - BA_capture CI (2026-08-17
        completion pass): a joint bootstrap over the SAME two independent,
        session-clustered populations bootstrap_balanced_accuracy_ci already
        clusters (predictions_a=RQ1 diagnostic-split VALIDATION, predictions_b
        =confirmatory VALIDATION -- disjoint session pools by construction,
        see build_rq1_dependence_diagnostic). Never subtracts two
        independently-computed CIs' bounds -- see
        paired_cluster_bootstrap_delta_ci's own docstring for why that would
        be invalid. None when either side has nothing comparable to
        bootstrap over."""
        cluster_values_a = _session_clustered_label_pairs(predictions_a, known_classes, session_id_by_example_id_a)
        cluster_values_b = _session_clustered_label_pairs(predictions_b, known_classes, session_id_by_example_id_b)
        if cluster_values_a is None or cluster_values_b is None:
            return None
        return paired_cluster_bootstrap_delta_ci(
            cluster_values_a, cluster_values_b, statistic=lambda pairs: _balanced_accuracy_statistic(pairs, known_classes),
            n_resamples=n_resamples, confidence_level=confidence_level,
        )

    def bootstrap_balanced_accuracy_ci_stratified_by_class(
        self, predictions: list[dict[str, Any]], known_classes: list[str], session_id_by_example_id: dict[str, str],
        n_resamples: int = 2000, confidence_level: float = 0.95,
    ) -> BootstrapCiResult | None:
        """Methodological-audit fix (2026-08-22, item 3): class-preserving
        sibling of bootstrap_balanced_accuracy_ci() above -- same statistic
        (mean-per-class recall), same session-clustering unit, but resamples
        WITHIN each true class independently (stratified_hierarchical_
        cluster_bootstrap) instead of pooling every session into one draw.
        Use this whenever a domain's session count per class is small
        enough that a plain pooled resample could draw zero sessions from a
        class (RQ1's real closed-set task, e.g. capture-disjoint
        VALIDATION's 12 sessions across 4 units) -- bootstrap_balanced_
        accuracy_ci() stays unchanged for every other real caller (RQ2
        branch CIs, etc.) that has not been audited for this failure mode."""
        cluster_values_by_class = _session_clustered_label_pairs_by_true_class(predictions, known_classes, session_id_by_example_id)
        if cluster_values_by_class is None:
            return None
        return stratified_hierarchical_cluster_bootstrap(
            cluster_values_by_class, statistic=lambda pairs: _balanced_accuracy_statistic(pairs, known_classes),
            n_resamples=n_resamples, confidence_level=confidence_level,
        )

    def bootstrap_balanced_accuracy_delta_ci_stratified_by_class(
        self, predictions_a: list[dict[str, Any]], predictions_b: list[dict[str, Any]], known_classes: list[str],
        session_id_by_example_id_a: dict[str, str], session_id_by_example_id_b: dict[str, str],
        n_resamples: int = 2000, confidence_level: float = 0.95,
    ) -> BootstrapCiResult | None:
        """Methodological-audit fix (2026-08-22, item 3): RQ1's real
        delta_dependence CI, recomputed with class-stratified resampling on
        BOTH sides and terminology that does not claim a "paired" bootstrap
        -- there is no physical pairing between the capture-dependent
        domain's sessions and the capture-disjoint domain's sessions (see
        independent_domain_bootstrap_delta_ci's own docstring). Replaces
        bootstrap_balanced_accuracy_delta_ci() for RQ1's own use; that
        method stays unchanged for other real callers."""
        cluster_values_by_class_a = _session_clustered_label_pairs_by_true_class(predictions_a, known_classes, session_id_by_example_id_a)
        cluster_values_by_class_b = _session_clustered_label_pairs_by_true_class(predictions_b, known_classes, session_id_by_example_id_b)
        if cluster_values_by_class_a is None or cluster_values_by_class_b is None:
            return None
        return independent_domain_bootstrap_delta_ci(
            cluster_values_by_class_a, cluster_values_by_class_b, statistic=lambda pairs: _balanced_accuracy_statistic(pairs, known_classes),
            n_resamples=n_resamples, confidence_level=confidence_level,
        )

    def bootstrap_balanced_accuracy_delta_ci_matched_by_class(
        self, predictions_a: list[dict[str, Any]], predictions_b: list[dict[str, Any]], known_classes: list[str],
        session_id_by_example_id_a: dict[str, str], session_id_by_example_id_b: dict[str, str],
        n_resamples: int = 2000, confidence_level: float = 0.95,
    ) -> BootstrapCiResult | None:
        """RQ4 exploratory fix (2026-08-22): for a genuinely matched design
        -- the SAME real evidence (same example_ids/sessions) scored under
        two analytical regions/representations (e.g. FULL_BURST vs
        PRE_PDU views of the identical VALIDATION set) -- unlike RQ1's
        `..._stratified_by_class` sibling above, which is for two
        INDEPENDENT domains with no real pairing. Raises via
        matched_stratified_bootstrap_delta_ci if the two populations'
        session-cluster structure does not actually match (caller's own
        responsibility to have already verified the underlying evidence is
        the same before calling this)."""
        cluster_values_by_class_a = _session_clustered_label_pairs_by_true_class(predictions_a, known_classes, session_id_by_example_id_a)
        cluster_values_by_class_b = _session_clustered_label_pairs_by_true_class(predictions_b, known_classes, session_id_by_example_id_b)
        if cluster_values_by_class_a is None or cluster_values_by_class_b is None:
            return None
        return matched_stratified_bootstrap_delta_ci(
            cluster_values_by_class_a, cluster_values_by_class_b, statistic=lambda pairs: _balanced_accuracy_statistic(pairs, known_classes),
            n_resamples=n_resamples, confidence_level=confidence_level,
        )

    def calibrate_unknown_threshold(self, validation_predictions: list[dict[str, Any]], known_classes: list[str], min_identified_precision: float = 0.9) -> float:
        """VALIDATION-only. A candidate threshold's precision is measured
        over every VALIDATION example whose top confidence clears it
        (known AND unknown examples alike) -- an unknown example that clears
        the threshold and gets identified as some known class always counts
        against precision, exactly like a known example being misclassified."""
        records = []
        for prediction in validation_predictions:
            probabilities = prediction.get("probabilities") or {}
            if not probabilities:
                continue
            confidence = max(probabilities.values())
            is_known = prediction["true_label"] in known_classes
            correct_if_identified = is_known and prediction["predicted_label"] == prediction["true_label"]
            records.append((confidence, correct_if_identified))

        if not records:
            return 1.0 + 1e-9  # no evidence to calibrate on -- reject everything

        candidate_thresholds = sorted({r[0] for r in records}, reverse=True)
        best_threshold = 1.0 + 1e-9
        for threshold in candidate_thresholds:
            identified = [correct for confidence, correct in records if confidence >= threshold]
            if not identified:
                continue
            precision = sum(identified) / len(identified)
            if precision >= min_identified_precision:
                best_threshold = threshold  # keep trying lower thresholds -- maximize recall subject to the precision floor
        return best_threshold

    def classify_with_threshold(self, prediction: dict[str, Any], acceptance_threshold: float) -> dict[str, Any]:
        probabilities = prediction.get("probabilities") or {}
        if not probabilities:
            return {
                "example_id": prediction.get("example_id"), "distance": None, "class_probability": None,
                "acceptance_threshold": acceptance_threshold, "predicted_class": None, "final_decision": "INSUFFICIENT_EVIDENCE",
            }
        predicted_class = max(probabilities, key=probabilities.get)
        confidence = probabilities[predicted_class]
        final_decision: FinalDecision = "IDENTIFIED" if confidence >= acceptance_threshold else "UNKNOWN"
        return {
            "example_id": prediction.get("example_id"), "distance": None, "class_probability": confidence,
            "acceptance_threshold": acceptance_threshold, "predicted_class": predicted_class, "final_decision": final_decision,
        }
