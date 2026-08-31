"""Fase 5: offline inference over an exported bundle -- reads a frozen model
+ scaler + label map + calibrated threshold from disk and scores NEW,
previously-unseen ExampleRecords. Deliberately offline only: this never
touches Live Monitor or any live streaming path (explicitly out of scope
until a bundle is trained, evaluated, and exported, per the original design).
"""
from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any, Callable

import joblib
import numpy as np
import torch

from app.infrastructure.ble.capture.ble_offline_replay import read_json, utc_now

from ..contracts import ExampleRecord, ModelBundleManifest
from ..evaluation import Evaluator
from .decision_windows import AGGREGATION_RULE, DEFAULT_MINIMUM_ELIGIBLE_BURSTS, DEFAULT_WINDOW_DURATION_S, aggregate_window_probabilities, group_examples_into_windows
from ..preprocessing import BasePreprocessingProfile, apply_base_preprocessing_with_provenance, load_iq_window, resolve_preprocessing_profile
from ..preprocessing.representation_profiles import feature_vector_representation, morphological_coarse_tf_representation, raw_iq_representation, spectrogram_representation
from ..training.training_service import (
    DEFAULT_MORPHOLOGICAL_TF_FRAMES,
    DEFAULT_MORPHOLOGICAL_TF_N_FFT,
    DEFAULT_RAW_IQ_LENGTH,
    DEFAULT_SPECTROGRAM_FRAMES,
    DEFAULT_SPECTROGRAM_N_FFT,
)

_TORCH_MODEL_TYPES = {"cnn1d", "cnn2d"}


class BundleNotFoundError(Exception):
    pass


class OfflineInferenceService:
    def __init__(
        self,
        bundle_root: Path,
        capture_iq_paths: dict[str, Path],
        iq_window_provider: Callable[[ExampleRecord], np.ndarray] | None = None,
    ) -> None:
        self.bundle_root = bundle_root
        self.capture_iq_paths = capture_iq_paths
        self.evaluator = Evaluator()
        # RQ4 region-specific fitting (2026-08-12): mirrors TrainingService's
        # own provider hook -- when supplied, run() scores an already
        # region-restricted array instead of the full captured burst. Never
        # a second scoring path: the same apply_base_preprocessing_with_
        # provenance -> representation -> predict_proba sequence below runs
        # regardless of the raw-window source.
        self._iq_window_provider = iq_window_provider

    def _load_bundle(self, bundle_id: str) -> dict[str, Any]:
        bundle_dir = self.bundle_root / bundle_id
        manifest_path = bundle_dir / "bundle_manifest.json"
        if not manifest_path.is_file():
            raise BundleNotFoundError(f"BUNDLE_NOT_FOUND:{bundle_id}")
        manifest = ModelBundleManifest.model_validate(read_json(manifest_path))
        model_manifest = read_json(bundle_dir / "model_manifest.json")
        feature_config = read_json(bundle_dir / "feature_config.json")
        thresholds = read_json(bundle_dir / "thresholds.json")
        # Preprocessing-registry correction (2026-08-08): resolve the SAME
        # profile this bundle was actually trained with -- previously
        # run()/run_live() always defaulted to identity preprocessing
        # regardless of what the bundle's own preprocessing_config.json said,
        # a real train/inference mismatch risk for any non-identity profile.
        preprocessing_config = read_json(bundle_dir / "preprocessing_config.json")
        base_profile = resolve_preprocessing_profile(preprocessing_config["base_preprocessing_profile_id"])

        model_type = model_manifest["model_type"]
        if model_type in _TORCH_MODEL_TYPES:
            model = torch.load(bundle_dir / model_manifest["model_file"], weights_only=False)
            model.eval()
        else:
            model = joblib.load(bundle_dir / model_manifest["model_file"])

        scaler = None
        if feature_config.get("scaler_file"):
            scaler = joblib.load(bundle_dir / feature_config["scaler_file"])

        return {
            "manifest": manifest, "model": model, "model_type": model_type,
            "label_classes": model_manifest["label_classes"],
            "representation_profile_id": feature_config["representation_profile_id"],
            "scaler": scaler,
            "acceptance_threshold": thresholds.get("acceptance_threshold"),
            "base_profile": base_profile,
        }

    def _representation(self, window: np.ndarray, sample_rate_sps: float, representation_profile_id: str) -> np.ndarray:
        if representation_profile_id.startswith("feature_vector"):
            return feature_vector_representation(window, sample_rate_sps)
        if representation_profile_id.startswith("raw_iq"):
            return raw_iq_representation(window, DEFAULT_RAW_IQ_LENGTH)
        if representation_profile_id.startswith("spectrogram"):
            return spectrogram_representation(window, sample_rate_sps, n_fft=DEFAULT_SPECTROGRAM_N_FFT, target_frames=DEFAULT_SPECTROGRAM_FRAMES)
        if representation_profile_id.startswith("morphological_coarse_tf"):
            return morphological_coarse_tf_representation(window, sample_rate_sps, n_fft=DEFAULT_MORPHOLOGICAL_TF_N_FFT, target_frames=DEFAULT_MORPHOLOGICAL_TF_FRAMES)
        raise ValueError(f"UNSUPPORTED_REPRESENTATION_PROFILE:{representation_profile_id}")

    def _predict_proba(self, bundle: dict[str, Any], X: np.ndarray) -> np.ndarray:
        if bundle["model_type"] in _TORCH_MODEL_TYPES:
            with torch.no_grad():
                logits = bundle["model"](torch.from_numpy(X.astype(np.float32)))
                return torch.softmax(logits, dim=1).numpy()
        return bundle["model"].predict_proba(X)

    def run_live(
        self, *, bundle_id: str, iq_window: np.ndarray, sample_rate_sps: float,
        base_profile: BasePreprocessingProfile | None = None,
    ) -> dict[str, Any]:
        """Live counterpart to run(): scores ONE already-extracted raw IQ
        burst window directly (e.g. from Live Monitor's circular IQ buffer),
        never touching ExampleRecord/capture_id/dataset/evidence at all --
        this is deliberately the smallest possible path from "raw IQ burst"
        to "prediction", reusing the exact same bundle-loading,
        preprocessing, representation, and scoring logic run() uses for
        offline batch inference (never a second, divergent implementation).

        Compatibility (center frequency, channel, sample rate, IQ format,
        bandwidth, extractor version) is deliberately NOT checked here --
        this class has no notion of what the CURRENT live tuning is, only
        what a single window looks like. The caller (StudioRepository, which
        already resolves a bundle's training-time acquisition parameters via
        the Physical capture registry) is responsible for that check before
        ever calling this.
        """
        bundle = self._load_bundle(bundle_id)
        # An explicit caller-supplied base_profile is still honored (e.g. a
        # deliberate what-if comparison) -- but the default is now the
        # bundle's OWN training-time profile, never a blind identity default.
        base_profile = base_profile or bundle["base_profile"]
        acceptance_threshold = bundle["acceptance_threshold"]
        if acceptance_threshold is None:
            raise ValueError(f"BUNDLE_HAS_NO_CALIBRATED_ACCEPTANCE_THRESHOLD:{bundle_id}")

        window, _ = apply_base_preprocessing_with_provenance(iq_window, base_profile, sample_rate_sps)
        features = self._representation(window, sample_rate_sps, bundle["representation_profile_id"])
        X = features[np.newaxis, ...]
        if bundle["scaler"] is not None:
            X = bundle["scaler"].transform(X)
        proba = self._predict_proba(bundle, X)[0]
        probabilities = {cls: float(p) for cls, p in zip(bundle["label_classes"], proba)}
        return self.evaluator.classify_with_threshold({"example_id": None, "probabilities": probabilities}, acceptance_threshold)

    def run(self, *, bundle_id: str, examples: list[ExampleRecord], base_profile: BasePreprocessingProfile | None = None) -> list[dict[str, Any]]:
        bundle = self._load_bundle(bundle_id)
        base_profile = base_profile or bundle["base_profile"]
        acceptance_threshold = bundle["acceptance_threshold"]
        if acceptance_threshold is None:
            raise ValueError(f"BUNDLE_HAS_NO_CALIBRATED_ACCEPTANCE_THRESHOLD:{bundle_id}")

        results: list[dict[str, Any]] = []
        for example in examples:
            if self._iq_window_provider is not None:
                window = self._iq_window_provider(example)
            else:
                iq_path = self.capture_iq_paths[example.capture_id]
                window = load_iq_window(iq_path, example.iq_start_sample, example.iq_end_sample)
            # Eq.(6)-(7) provenance correction (2026-08-08, point 3):
            # inference calls the EXACT same apply_base_preprocessing_with_
            # provenance TrainingService uses -- never a second
            # implementation -- so a burst scored here under
            # paper-eq6-7-v1 gets a real (phi_b0, f_b) estimated the same
            # way training's did, not a stale or re-approximated one.
            window, provenance = apply_base_preprocessing_with_provenance(window, base_profile, float(example.sample_rate_sps))
            features = self._representation(window, float(example.sample_rate_sps), bundle["representation_profile_id"])
            X = features[np.newaxis, ...]
            if bundle["scaler"] is not None:
                X = bundle["scaler"].transform(X)
            proba = self._predict_proba(bundle, X)[0]
            probabilities = {cls: float(p) for cls, p in zip(bundle["label_classes"], proba)}
            decision = self.evaluator.classify_with_threshold({"example_id": example.example_id, "probabilities": probabilities}, acceptance_threshold)
            # Decision-window correction (2026-08-08): the full per-class
            # distribution is needed to aggregate several bursts into one
            # window decision (median-per-class, see decision_windows.py) --
            # classify_with_threshold's own return only keeps the top-1
            # confidence, so it is added back here rather than lost.
            # Canonical physical_unit_id join (2026-08-12, Scientific
            # Closure pass point 7): the SAME real ground-truth identity
            # ExampleRecord already carries, propagated once here so
            # Coverage/S1/Sensitivity/per-unit summaries never infer
            # identity from a filename or display label.
            result = {**decision, "probabilities": probabilities, "physical_unit_id": example.physical_unit_id}
            if provenance is not None:
                result["preprocessing_provenance"] = dataclasses.asdict(provenance)
            results.append(result)
        return results

    def run_decision_windows(
        self, *, bundle_id: str, examples: list[ExampleRecord], window_duration_s: float = DEFAULT_WINDOW_DURATION_S,
        minimum_eligible_bursts: int = DEFAULT_MINIMUM_ELIGIBLE_BURSTS, base_profile: BasePreprocessingProfile | None = None,
    ) -> list[dict[str, Any]]:
        """Real decision windows (2026-08-08): groups examples into the same
        time windows decision_window_records.py already defines for
        accounting, scores every burst with the SAME frozen bundle run() uses
        (no second scoring path), aggregates each window's bursts by the
        declared AGGREGATION_RULE (median probability per class), and applies
        the bundle's own calibrated acceptance_threshold to the AGGREGATED
        distribution -- exactly classify_with_threshold's existing logic,
        just given a window's combined evidence instead of one burst's.
        A window with fewer than minimum_eligible_bursts scored bursts
        abstains (INSUFFICIENT_EVIDENCE) before that threshold check ever
        runs -- not enough evidence is a distinct reason from "evidence
        existed but was unconvincing"."""
        bundle = self._load_bundle(bundle_id)
        acceptance_threshold = bundle["acceptance_threshold"]
        if acceptance_threshold is None:
            raise ValueError(f"BUNDLE_HAS_NO_CALIBRATED_ACCEPTANCE_THRESHOLD:{bundle_id}")

        burst_decisions = self.run(bundle_id=bundle_id, examples=examples, base_profile=base_profile)
        by_example_id = {d["example_id"]: d for d in burst_decisions}
        windows = group_examples_into_windows(examples, window_duration_s)

        results: list[dict[str, Any]] = []
        for (capture_id, window_index), window_examples in sorted(windows.items()):
            burst_example_ids = [e.example_id for e in window_examples]
            window_burst_decisions = [by_example_id[eid] for eid in burst_example_ids]
            window_id = f"{capture_id}-decision-win-{window_index:05d}"
            # Canonical physical_unit_id join (2026-08-12, Scientific
            # Closure pass point 7): real ground truth ONLY when every
            # constituent burst genuinely agrees on the same unit (true by
            # construction for a physically-isolated capture) -- None
            # (never guessed) on a mixed or undeclared window.
            window_units = {e.physical_unit_id for e in window_examples}
            window_physical_unit_id = next(iter(window_units)) if len(window_units) == 1 else None

            if len(window_burst_decisions) < minimum_eligible_bursts:
                results.append({
                    "decision_window_id": window_id, "capture_id": capture_id, "window_index": window_index,
                    "window_duration_s": window_duration_s, "burst_example_ids": burst_example_ids, "burst_count": len(burst_example_ids),
                    "aggregation_rule": AGGREGATION_RULE, "bundle_id": bundle_id, "aggregated_probabilities": None,
                    "predicted_class": None, "class_probability": None, "acceptance_threshold": acceptance_threshold,
                    "final_decision": "INSUFFICIENT_EVIDENCE", "physical_unit_id": window_physical_unit_id,
                    "abstention_reason": f"BELOW_MINIMUM_ELIGIBLE_BURSTS:{len(window_burst_decisions)}<{minimum_eligible_bursts}",
                })
                continue

            aggregated_probabilities = aggregate_window_probabilities(window_burst_decisions, bundle["label_classes"])
            decision = self.evaluator.classify_with_threshold({"example_id": window_id, "probabilities": aggregated_probabilities}, acceptance_threshold)
            results.append({
                "decision_window_id": window_id, "capture_id": capture_id, "window_index": window_index,
                "window_duration_s": window_duration_s, "burst_example_ids": burst_example_ids, "burst_count": len(burst_example_ids),
                "aggregation_rule": AGGREGATION_RULE, "bundle_id": bundle_id, "aggregated_probabilities": aggregated_probabilities,
                "physical_unit_id": window_physical_unit_id,
                "predicted_class": decision["predicted_class"], "class_probability": decision["class_probability"],
                "acceptance_threshold": acceptance_threshold, "final_decision": decision["final_decision"], "abstention_reason": None,
            })
        return results

    def run_with_provenance(
        self, *, bundle_id: str, examples: list[ExampleRecord], inference_run_id: str,
        capture_iq_sha256_by_id: dict[str, str] | None = None, base_profile: BasePreprocessingProfile | None = None,
    ) -> dict[str, Any]:
        """Inference-provenance correction (2026-08-08): the audit's own
        finding -- "the provenance chain terminates at the model": a
        prediction was computed but never bound, on disk, to WHICH exact
        bundle (by content hash, not just id) and WHICH exact source IQ
        (by sha256) produced it. This wraps run() (never a second scoring
        path) and returns a real, hashable manifest a caller persists --
        never silently skips a capture whose real iq_sha256 the caller did
        not supply (source_iq_sha256_by_capture_id records None for it
        rather than fabricating a hash)."""
        bundle = self._load_bundle(bundle_id)
        decisions = self.run(bundle_id=bundle_id, examples=examples, base_profile=base_profile)
        capture_iq_sha256_by_id = capture_iq_sha256_by_id or {}
        source_capture_ids = sorted({e.capture_id for e in examples})
        return {
            "inference_run_id": inference_run_id,
            "bundle_id": bundle_id,
            "bundle_sha256": bundle["manifest"].bundle_sha256,
            "representation_profile_id": bundle["representation_profile_id"],
            "base_preprocessing_profile_id": bundle["base_profile"].profile_id,
            "source_capture_ids": source_capture_ids,
            "source_iq_sha256_by_capture_id": {capture_id: capture_iq_sha256_by_id.get(capture_id) for capture_id in source_capture_ids},
            "prediction_count": len(decisions),
            "created_at": utc_now(),
            "decisions": decisions,
        }
