"""Orchestrates baseline-model training against a READY split with a PASSED
leakage check -- it refuses to run otherwise, rather than silently training
on a split that hasn't earned that status. Windows are loaded from the real
capture IQ files, base-preprocessed (per design, nothing signal-altering
unless explicitly justified), turned into the feature_vector representation,
scaled with TRAIN-only statistics, then handed to a baseline model.
"""
from __future__ import annotations

import dataclasses
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import numpy as np

from app.infrastructure.ble.capture.ble_offline_replay import utc_now

from ..contracts import ExampleRecord, SplitManifest, TrainingRun
from ..preprocessing import BasePreprocessingProfile, TrainOnlyScaler, apply_base_preprocessing_with_provenance, feature_vector_representation, load_iq_window
from ..preprocessing.representation_profiles import FEATURE_NAMES, morphological_coarse_tf_representation, raw_iq_representation, spectrogram_representation
from ..quality.split_builder import train_label_for
from .baseline_models import BaselineModelTrainer
from .cnn_models import CnnTrainer
from .frozen_reference_baseline import FrozenReferenceBaselineTrainer

DEFAULT_RAW_IQ_LENGTH = 800
DEFAULT_SPECTROGRAM_N_FFT = 64
DEFAULT_SPECTROGRAM_FRAMES = 32
DEFAULT_MORPHOLOGICAL_TF_N_FFT = 16
DEFAULT_MORPHOLOGICAL_TF_FRAMES = 8


@dataclass
class TrainingArtifacts:
    training_run: TrainingRun
    model: Any
    scaler: TrainOnlyScaler | None
    label_classes: list[str]
    metrics: dict[str, dict[str, Any]]
    predictions: dict[str, list[dict[str, Any]]]
    feature_names: list[str] = field(default_factory=lambda: list(FEATURE_NAMES))
    # Real wall-clock: predict_proba() on one VALIDATION example, averaged.
    # None when VALIDATION is empty -- never fabricated as 0.
    validation_latency_ms: float | None = None
    # Eq.(6)-(7) per-burst provenance (2026-08-08, point 3): example_id ->
    # the real PaperCompliantCompensation this burst was preprocessed with,
    # ONLY populated when base_profile.paper_eq6_7_compensation is enabled
    # (empty dict otherwise -- never fabricated for a profile that never
    # ran this step).
    preprocessing_provenance: dict[str, dict[str, Any]] = field(default_factory=dict)


class TrainingService:
    def __init__(
        self,
        capture_iq_paths: dict[str, Path],
        base_profile: BasePreprocessingProfile | None = None,
        iq_window_provider: Callable[[ExampleRecord], np.ndarray] | None = None,
    ) -> None:
        self.capture_iq_paths = capture_iq_paths
        self.base_profile = base_profile or BasePreprocessingProfile(profile_id="base-v1")
        # RQ4 region-specific fitting (2026-08-12): when supplied, replaces
        # the raw-window source (load_iq_window from capture_iq_paths) with
        # an already-region-restricted array (e.g. PRE_PDU/ADVA_EXCLUDED).
        # The SAME apply_base_preprocessing_with_provenance step below still
        # runs on it -- this is not a second training pipeline, only a
        # different raw-IQ source feeding the identical downstream code path.
        self._iq_window_provider = iq_window_provider
        # Reset per TrainingService instance -- each run_* call below starts
        # a fresh accumulation (a new TrainingService is the normal usage
        # pattern; run_* also clears this explicitly at its own start so
        # reusing one instance across two runs never leaks stale provenance).
        self._provenance_by_example_id: dict[str, dict[str, Any]] = {}

    def _label_for(self, example: ExampleRecord, scientific_task: str) -> str:
        # Single source of truth shared with SplitBuilder's own train-class
        # gate (quality/split_builder.py's train_label_for) -- training must
        # never derive a different label scheme than the one the split was
        # validated against, or the two-class guarantee that gate enforces
        # would not actually hold for what gets trained here.
        return train_label_for(scientific_task, example)

    def _window_for(self, example: ExampleRecord) -> np.ndarray:
        if self._iq_window_provider is not None:
            window = self._iq_window_provider(example)
        else:
            path = self.capture_iq_paths[example.capture_id]
            window = load_iq_window(path, example.iq_start_sample, example.iq_end_sample)
        result, provenance = apply_base_preprocessing_with_provenance(window, self.base_profile, float(example.sample_rate_sps))
        if provenance is not None:
            self._provenance_by_example_id[example.example_id] = dataclasses.asdict(provenance)
        return result

    def _features_for(self, examples: list[ExampleRecord]) -> np.ndarray:
        if not examples:
            return np.zeros((0, len(FEATURE_NAMES)))
        return np.stack([feature_vector_representation(self._window_for(e), float(e.sample_rate_sps)) for e in examples])

    def run_baseline(
        self, *, training_run: TrainingRun, split: SplitManifest, examples_by_id: dict[str, ExampleRecord],
        allow_intentional_diagnostic_leakage: bool = False, feature_indices: list[int] | None = None,
    ) -> TrainingArtifacts:
        """`feature_indices` (feature-group ablation, exploratory, added
        2026-08-24): when given, restricts the engineered feature matrix to
        these column indices into FEATURE_NAMES, computed AFTER the full
        10-column `feature_vector_representation()` output -- no new I/Q
        preprocessing, no change to which examples participate. `None`
        (every existing caller, including PRIMARY) reproduces the exact
        prior behavior byte-for-byte: all 10 columns, unchanged."""
        if split.split_status != "READY":
            raise ValueError(f"CANNOT_TRAIN_ON_A_SPLIT_THAT_IS_NOT_READY:{split.split_status}")
        if split.leakage_check.status != "PASSED" and not (
            allow_intentional_diagnostic_leakage and split.split_purpose == "RQ1_ACQUISITION_DEPENDENCE_DIAGNOSTIC"
        ):
            raise ValueError(f"CANNOT_TRAIN_WHEN_LEAKAGE_CHECK_DID_NOT_PASS:{split.leakage_check.status}")
        if training_run.model_type not in ("logistic_regression", "svm_rbf", "random_forest"):
            raise ValueError(f"run_baseline only supports classical baseline model_types, got {training_run.model_type}")
        self._provenance_by_example_id = {}

        by_split: dict[str, list[ExampleRecord]] = {"TRAIN": [], "VALIDATION": [], "TEST": []}
        for assignment in split.assignments:
            by_split[assignment.split].append(examples_by_id[assignment.example_id])
        if not by_split["TRAIN"]:
            raise ValueError("NO_TRAIN_EXAMPLES_IN_SPLIT")

        started_at = utc_now()
        X = {name: self._features_for(exs) for name, exs in by_split.items()}
        if feature_indices is not None:
            X = {name: (arr[:, feature_indices] if len(arr) else arr) for name, arr in X.items()}
        y = {name: [self._label_for(e, split.scientific_task) for e in exs] for name, exs in by_split.items()}
        # Defense in depth: SplitBuilder._finalize already refuses to mark a
        # split READY with fewer than 2 distinct TRAIN labels, but training
        # must never silently proceed on a single class regardless of how it
        # got here -- sklearn's LogisticRegression/SVC already raise on their
        # own; RandomForestClassifier does not, so this check is what
        # actually protects it (and random_forest is not special-cased here
        # on purpose -- every model_type goes through this same guard).
        if len(set(y["TRAIN"])) < 2:
            raise ValueError(f"TRAINING_REQUIRES_AT_LEAST_TWO_CLASSES: TRAIN contains only {sorted(set(y['TRAIN']))}")

        scaler = TrainOnlyScaler()
        scaler.fit(X["TRAIN"], split="TRAIN")
        X_scaled = {name: (scaler.transform(arr) if len(arr) else arr) for name, arr in X.items()}

        trainer = BaselineModelTrainer()
        model = trainer.build(training_run.model_type, training_run.random_seed, training_run.hyperparameters)
        trainer.fit(model, X_scaled["TRAIN"], y["TRAIN"])
        classes = trainer.classes(model)

        metrics: dict[str, dict[str, Any]] = {}
        predictions: dict[str, list[dict[str, Any]]] = {}
        for name in ("TRAIN", "VALIDATION", "TEST"):
            exs = by_split[name]
            if not exs:
                continue
            proba = trainer.predict_proba(model, X_scaled[name])
            predicted_idx = np.argmax(proba, axis=1)
            predicted_labels = [classes[i] for i in predicted_idx]
            true_labels = y[name]
            accuracy = float(np.mean([p == t for p, t in zip(predicted_labels, true_labels)]))
            metrics[name] = {"accuracy": accuracy, "n_examples": len(true_labels)}
            predictions[name] = [
                {
                    "example_id": exs[i].example_id,
                    "true_label": true_labels[i],
                    "predicted_label": predicted_labels[i],
                    "probabilities": {cls: float(p) for cls, p in zip(classes, proba[i])},
                    # Canonical physical_unit_id join (2026-08-12, Scientific
                    # Closure pass point 7): the SAME real identity
                    # ExampleRecord already carries, propagated once here so
                    # Coverage/S1/Sensitivity/per-unit summaries never infer
                    # identity from a filename or display label.
                    "physical_unit_id": exs[i].physical_unit_id,
                }
                for i in range(len(exs))
            ]

        validation_latency_ms = self._measure_latency_ms(lambda sample: trainer.predict_proba(model, sample), X_scaled["VALIDATION"])

        completed_run = training_run.model_copy(update={"status": "COMPLETED", "started_at": started_at, "completed_at": utc_now()})
        feature_names = [FEATURE_NAMES[i] for i in feature_indices] if feature_indices is not None else list(FEATURE_NAMES)
        return TrainingArtifacts(
            training_run=completed_run, model=model, scaler=scaler, label_classes=classes, metrics=metrics, predictions=predictions,
            validation_latency_ms=validation_latency_ms, preprocessing_provenance=dict(self._provenance_by_example_id),
            feature_names=feature_names,
        )

    def _measure_latency_ms(self, predict_one, validation_X: np.ndarray, repeats: int = 10) -> float | None:
        if len(validation_X) == 0:
            return None
        sample = validation_X[:1]
        timings = []
        for _ in range(repeats):
            start = time.perf_counter()
            predict_one(sample)
            timings.append((time.perf_counter() - start) * 1000.0)
        return float(np.mean(timings))

    def _morphological_features_for(self, examples: list[ExampleRecord]) -> np.ndarray:
        n_features = DEFAULT_MORPHOLOGICAL_TF_N_FFT * DEFAULT_MORPHOLOGICAL_TF_FRAMES
        if not examples:
            return np.zeros((0, n_features))
        return np.stack([
            morphological_coarse_tf_representation(self._window_for(e), float(e.sample_rate_sps), n_fft=DEFAULT_MORPHOLOGICAL_TF_N_FFT, target_frames=DEFAULT_MORPHOLOGICAL_TF_FRAMES)
            for e in examples
        ])

    def run_frozen_reference_baseline(
        self, *, training_run: TrainingRun, split: SplitManifest, examples_by_id: dict[str, ExampleRecord],
        allow_intentional_diagnostic_leakage: bool = False,
    ) -> TrainingArtifacts:
        """RQ2's 4th branch: a simple, frozen (no iterative optimization)
        morphological/coarse time-frequency nearest-centroid reference --
        see frozen_reference_baseline.py. Structurally parallel to
        run_baseline (same split/leakage/two-class guards, same
        metrics/predictions shape) but deliberately its own method, not a
        branch inside run_baseline: it uses a different representation
        (morphological_coarse_tf, not the classical feature vector) and
        skips TRAIN-only scaling (z-scoring would distort the L2-normalized
        shape vectors nearest-centroid distance relies on)."""
        if split.split_status != "READY":
            raise ValueError(f"CANNOT_TRAIN_ON_A_SPLIT_THAT_IS_NOT_READY:{split.split_status}")
        if split.leakage_check.status != "PASSED" and not (
            allow_intentional_diagnostic_leakage and split.split_purpose == "RQ1_ACQUISITION_DEPENDENCE_DIAGNOSTIC"
        ):
            raise ValueError(f"CANNOT_TRAIN_WHEN_LEAKAGE_CHECK_DID_NOT_PASS:{split.leakage_check.status}")
        if training_run.model_type != "frozen_morphological_baseline":
            raise ValueError(f"run_frozen_reference_baseline only supports frozen_morphological_baseline, got {training_run.model_type}")
        self._provenance_by_example_id = {}

        by_split: dict[str, list[ExampleRecord]] = {"TRAIN": [], "VALIDATION": [], "TEST": []}
        for assignment in split.assignments:
            by_split[assignment.split].append(examples_by_id[assignment.example_id])
        if not by_split["TRAIN"]:
            raise ValueError("NO_TRAIN_EXAMPLES_IN_SPLIT")

        started_at = utc_now()
        X = {name: self._morphological_features_for(exs) for name, exs in by_split.items()}
        y = {name: [self._label_for(e, split.scientific_task) for e in exs] for name, exs in by_split.items()}
        if len(set(y["TRAIN"])) < 2:
            raise ValueError(f"TRAINING_REQUIRES_AT_LEAST_TWO_CLASSES: TRAIN contains only {sorted(set(y['TRAIN']))}")

        trainer = FrozenReferenceBaselineTrainer()
        model = trainer.build(training_run.model_type, training_run.random_seed, training_run.hyperparameters)
        trainer.fit(model, X["TRAIN"], y["TRAIN"])
        classes = trainer.classes(model)

        metrics: dict[str, dict[str, Any]] = {}
        predictions: dict[str, list[dict[str, Any]]] = {}
        for name in ("TRAIN", "VALIDATION", "TEST"):
            exs = by_split[name]
            if not exs:
                continue
            proba = trainer.predict_proba(model, X[name])
            predicted_idx = np.argmax(proba, axis=1)
            predicted_labels = [classes[i] for i in predicted_idx]
            true_labels = y[name]
            accuracy = float(np.mean([p == t for p, t in zip(predicted_labels, true_labels)]))
            metrics[name] = {"accuracy": accuracy, "n_examples": len(true_labels)}
            predictions[name] = [
                {
                    "example_id": exs[i].example_id,
                    "true_label": true_labels[i],
                    "predicted_label": predicted_labels[i],
                    "probabilities": {cls: float(p) for cls, p in zip(classes, proba[i])},
                    "physical_unit_id": exs[i].physical_unit_id,
                }
                for i in range(len(exs))
            ]

        validation_latency_ms = self._measure_latency_ms(lambda sample: trainer.predict_proba(model, sample), X["VALIDATION"])

        completed_run = training_run.model_copy(update={"status": "COMPLETED", "started_at": started_at, "completed_at": utc_now()})
        return TrainingArtifacts(
            training_run=completed_run, model=model, scaler=None, label_classes=classes, metrics=metrics,
            predictions=predictions, feature_names=[f"tf_bin_{i}" for i in range(X["TRAIN"].shape[1])] if len(X["TRAIN"]) else [],
            validation_latency_ms=validation_latency_ms, preprocessing_provenance=dict(self._provenance_by_example_id),
        )

    def _cnn_representation(self, example: ExampleRecord, model_type: str) -> np.ndarray:
        window = self._window_for(example)
        if model_type == "cnn1d":
            return raw_iq_representation(window, DEFAULT_RAW_IQ_LENGTH)
        return spectrogram_representation(window, float(example.sample_rate_sps), n_fft=DEFAULT_SPECTROGRAM_N_FFT, target_frames=DEFAULT_SPECTROGRAM_FRAMES)

    def run_cnn(
        self, *, training_run: TrainingRun, split: SplitManifest, examples_by_id: dict[str, ExampleRecord], epochs: int = 30,
        allow_intentional_diagnostic_leakage: bool = False,
    ) -> TrainingArtifacts:
        if split.split_status != "READY":
            raise ValueError(f"CANNOT_TRAIN_ON_A_SPLIT_THAT_IS_NOT_READY:{split.split_status}")
        if split.leakage_check.status != "PASSED" and not (
            allow_intentional_diagnostic_leakage and split.split_purpose == "RQ1_ACQUISITION_DEPENDENCE_DIAGNOSTIC"
        ):
            raise ValueError(f"CANNOT_TRAIN_WHEN_LEAKAGE_CHECK_DID_NOT_PASS:{split.leakage_check.status}")
        if training_run.model_type not in ("cnn1d", "cnn2d"):
            raise ValueError(f"run_cnn only supports cnn1d/cnn2d, got {training_run.model_type}")
        self._provenance_by_example_id = {}

        by_split: dict[str, list[ExampleRecord]] = {"TRAIN": [], "VALIDATION": [], "TEST": []}
        for assignment in split.assignments:
            by_split[assignment.split].append(examples_by_id[assignment.example_id])
        if not by_split["TRAIN"]:
            raise ValueError("NO_TRAIN_EXAMPLES_IN_SPLIT")

        started_at = utc_now()
        classes = sorted({self._label_for(e, split.scientific_task) for e in by_split["TRAIN"]})
        class_to_idx = {label: idx for idx, label in enumerate(classes)}
        # Same defense-in-depth guard as run_baseline -- unlike sklearn's
        # LogisticRegression/SVC, neither PyTorch nor CnnTrainer.build/fit
        # refuse a single-class TRAIN on their own, so this is what actually
        # protects cnn1d/cnn2d from "succeeding" on a meaningless model.
        if len(classes) < 2:
            raise ValueError(f"TRAINING_REQUIRES_AT_LEAST_TWO_CLASSES: TRAIN contains only {classes}")

        X = {name: (np.stack([self._cnn_representation(e, training_run.model_type) for e in exs]) if exs else np.zeros((0,))) for name, exs in by_split.items()}
        y_labels = {name: [self._label_for(e, split.scientific_task) for e in exs] for name, exs in by_split.items()}

        trainer = CnnTrainer()
        model = trainer.build(training_run.model_type, num_classes=len(classes))
        y_train_idx = np.array([class_to_idx.get(label, -1) for label in y_labels["TRAIN"]])
        if (y_train_idx < 0).any():
            raise ValueError("TRAIN_LABEL_NOT_IN_CLASS_SET")  # cannot happen: classes are derived from TRAIN itself
        trainer.fit(model, X["TRAIN"], y_train_idx, random_seed=training_run.random_seed, epochs=epochs)

        metrics: dict[str, dict[str, Any]] = {}
        predictions: dict[str, list[dict[str, Any]]] = {}
        for name in ("TRAIN", "VALIDATION", "TEST"):
            exs = by_split[name]
            if not exs:
                continue
            proba = trainer.predict_proba(model, X[name])
            predicted_idx = np.argmax(proba, axis=1)
            predicted_labels = [classes[i] for i in predicted_idx]
            true_labels = y_labels[name]
            # A VALIDATION/TEST example whose true label never appeared in
            # TRAIN (e.g. an UNKNOWN_DEVICE_REJECTION unknown-device session)
            # cannot be "correctly classified" among TRAIN's classes -- it is
            # excluded from this closed-set accuracy, not silently counted
            # as right or wrong; Fase 5's UNKNOWN calibration handles it.
            comparable = [i for i in range(len(exs)) if true_labels[i] in class_to_idx]
            accuracy = float(np.mean([predicted_labels[i] == true_labels[i] for i in comparable])) if comparable else None
            metrics[name] = {"accuracy": accuracy, "n_examples": len(true_labels), "n_comparable_to_train_classes": len(comparable)}
            predictions[name] = [
                {
                    "example_id": exs[i].example_id,
                    "true_label": true_labels[i],
                    "predicted_label": predicted_labels[i],
                    "probabilities": {cls: float(p) for cls, p in zip(classes, proba[i])},
                    "physical_unit_id": exs[i].physical_unit_id,
                }
                for i in range(len(exs))
            ]

        validation_latency_ms = self._measure_latency_ms(lambda sample: trainer.predict_proba(model, sample), X["VALIDATION"])

        completed_run = training_run.model_copy(update={"status": "COMPLETED", "started_at": started_at, "completed_at": utc_now()})
        return TrainingArtifacts(
            training_run=completed_run, model=model, scaler=None, label_classes=classes, metrics=metrics, predictions=predictions,
            validation_latency_ms=validation_latency_ms, preprocessing_provenance=dict(self._provenance_by_example_id),
        )
