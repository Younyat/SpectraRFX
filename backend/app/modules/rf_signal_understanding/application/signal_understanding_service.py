from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from collections import deque

import numpy as np

from app.modules.rf_intelligence.schemas import RFIntelligenceSettings, SpectrumFrameInput
from app.modules.rf_intelligence.service import RFIntelligenceService
from app.modules.rf_intelligence.knowledge_base import resolve_band_profile
from app.modules.rf_signal_understanding.application.bispectral_verification_pipeline import BispectralVerificationPipeline
from app.modules.rf_signal_understanding.application.comparative_evaluation_pipeline import ComparativeEvaluationPipeline
from app.modules.rf_signal_understanding.application.decision_fusion_pipeline import DecisionFusionPipeline
from app.modules.rf_signal_understanding.application.region_classification_pipeline import RegionClassificationPipeline
from app.modules.rf_signal_understanding.application.waterfall_detection_pipeline import WaterfallDetectionPipeline
from app.modules.rf_signal_understanding.domain.schemas import (
    AnalyzeCaptureRequest,
    CaptureForTrainingRequest,
    CompareModelsRequest,
    CompareWithRFIntelligenceRequest,
    ExportLabelledRegionsRequest,
    IncrementalTrainingRequest,
    PseudoLabelRequest,
    RegisterCaptureRequest,
    RegionReviewRequest,
    TrainingRequest,
    ValidationRequest,
)
from app.modules.rf_signal_understanding.domain.value_objects import VALIDATION_TASKS
from app.modules.rf_signal_understanding.infrastructure.image_utils import normalize_to_uint8, write_grayscale_png
from app.modules.rf_signal_understanding.infrastructure.iq_region_extractor import IQRegionExtractor
from app.modules.rf_signal_understanding.infrastructure.model_registry import ModelRegistry
from app.modules.rf_signal_understanding.infrastructure.result_repository import ResultRepository
from app.modules.rf_signal_understanding.infrastructure.scientific_traceability import ScientificTraceability
from app.modules.rf_signal_understanding.infrastructure.spectral_feature_extractor import SpectralFeatureExtractor
from app.modules.rf_signal_understanding.infrastructure.stft_waterfall_builder import STFTWaterfallBuilder


class RFSignalUnderstandingService:
    def __init__(self, storage_root: Path, legacy_service: RFIntelligenceService | None = None) -> None:
        self.storage_root = storage_root
        self.module_root = Path(__file__).resolve().parents[1]
        self.repository = ResultRepository(storage_root)
        self.model_registry = ModelRegistry(self.module_root / "models")
        self.traceability = ScientificTraceability(self.module_root / "configs" / "references.json")
        self.waterfall_builder = STFTWaterfallBuilder()
        self.detector = WaterfallDetectionPipeline()
        self.classifier = RegionClassificationPipeline()
        self.iq_extractor = IQRegionExtractor()
        self.spectral_extractor = SpectralFeatureExtractor()
        self.bispectral = BispectralVerificationPipeline()
        self.fusion = DecisionFusionPipeline()
        self.comparison = ComparativeEvaluationPipeline()
        self.legacy_service = legacy_service or RFIntelligenceService()
        self._live_rows: deque[list[float]] = deque(maxlen=160)
        self._live_timestamps: deque[str | None] = deque(maxlen=160)
        self._live_signature: tuple[int, float, float] | None = None
        self._live_result_cache: dict[str, dict[str, Any]] = {}

    def analyze_capture(self, request: AnalyzeCaptureRequest) -> dict[str, Any]:
        analysis_id = request.analysis_id or self.repository.new_analysis_id()
        analysis_dir = self.repository.analysis_dir(analysis_id)
        input_path = Path(request.file_path).expanduser().resolve()
        iq_samples = self._read_iq(input_path)
        input_metadata = {
            "file_path": str(input_path),
            "sample_rate_hz": float(request.sample_rate_hz),
            "center_frequency_hz": float(request.center_frequency_hz),
            "format": request.format,
            "sample_count": int(iq_samples.size),
        }
        self.repository.write_json(analysis_dir, "input_metadata.json", input_metadata)

        waterfall = self.waterfall_builder.build(
            iq_samples,
            request.sample_rate_hz,
            request.center_frequency_hz,
            request.n_fft,
            request.hop_length,
            request.window,
            analysis_dir,
        )
        matrix = waterfall["waterfall_matrix"]
        regions = self.detector.detect(matrix, waterfall["time_axis_s"], waterfall["freq_axis_hz"])
        self.repository.write_json(analysis_dir, "regions.json", regions)

        result_regions: list[dict[str, Any]] = []
        fused_decisions: list[dict[str, Any]] = []
        for region in regions:
            region_matrix = self._region_matrix(matrix, region)
            region_png = analysis_dir / "regions" / f"{region['bbox_id']}.png"
            write_grayscale_png(region_png, normalize_to_uint8(region_matrix))
            iq_info = self.iq_extractor.extract(iq_samples, request.sample_rate_hz, request.center_frequency_hz, region, analysis_dir)
            segment = np.fromfile(iq_info["iq_segment_path"], dtype=np.complex64)
            classification = self.classifier.classify(region_matrix, region)
            trained_classification = self._trained_signal_type_classification(region_matrix, region)
            if trained_classification is not None:
                classification["trained"] = trained_classification
                classification["mlp"] = trained_classification
            spectral = self.spectral_extractor.extract(segment, request.sample_rate_hz, region_matrix, region)
            bispectral = self.bispectral.verify(segment)
            spectral_path = self.repository.write_json(analysis_dir, f"features/{region['bbox_id']}_spectral_features.json", spectral)
            bispectral_path = self.repository.write_json(analysis_dir, f"features/{region['bbox_id']}_bispectral_features.json", bispectral)
            fused = self.fusion.fuse(region, classification["visual"], classification["mlp"], spectral, bispectral)
            fused_decisions.append(fused)
            result_regions.append(
                {
                    "bbox_id": region["bbox_id"],
                    "time_start_s": region["time_start_s"],
                    "time_end_s": region["time_end_s"],
                    "freq_start_hz": region["freq_start_hz"],
                    "freq_end_hz": region["freq_end_hz"],
                    "detector": {"type": region["detector"], "confidence": region["confidence"]},
                    "classification": {
                        "visual_label": classification["visual"]["label"],
                        "visual_confidence": classification["visual"]["confidence"],
                        "mlp_label": classification["mlp"]["label"],
                        "mlp_confidence": classification["mlp"]["confidence"],
                        "visual": classification["visual"],
                        "mlp": classification["mlp"],
                        "trained": classification.get("trained"),
                    },
                    "iq_extraction": iq_info,
                    "region_image_path": str(region_png),
                    "features": {
                        "spectral_features_path": str(spectral_path.relative_to(analysis_dir)),
                        "bispectral_features_path": str(bispectral_path.relative_to(analysis_dir)),
                        "spectral": spectral,
                        "bispectral": bispectral,
                    },
                    "final_decision": {
                        "label": fused["final_label"],
                        "confidence": fused["final_confidence"],
                        "status": fused["decision_status"],
                        "method": fused["method"],
                        "limitations": fused["limitations"],
                    },
                }
            )

        trace = self.traceability.for_steps(
            ["waterfall_generation", "region_detection", "mlp_spectral_classification", "bispectral_verification"]
        )
        result = {
            "analysis_id": analysis_id,
            "input": input_metadata,
            "waterfall": {
                "n_fft": request.n_fft,
                "hop_length": request.hop_length,
                "window": request.window,
                "image_path": "waterfall.png",
                "matrix_path": "waterfall.npy",
                "power_db_min": waterfall["power_db_min"],
                "power_db_max": waterfall["power_db_max"],
            },
            "regions": result_regions,
            "summary": self._summary(result_regions, fused_decisions),
            "scientific_traceability": trace,
        }
        self.repository.write_json(analysis_dir, "scientific_traceability.json", trace)
        self.repository.write_json(analysis_dir, "results.json", result)
        return result

    def get_result(self, analysis_id: str) -> dict[str, Any]:
        return self.repository.read_result(analysis_id)

    def analyze_live_frame(self, raw_frame: dict[str, Any], legacy_result: dict[str, Any] | None = None, decision_mode: str = "hybrid") -> dict[str, Any]:
        levels = raw_frame.get("levels_db") or []
        freqs = raw_frame.get("frequencies_hz") or []
        if not levels or not freqs:
            return self._empty_live_result(raw_frame, "No live spectrum frame is available yet.")

        signature = (
            min(len(levels), len(freqs)),
            float(raw_frame.get("center_frequency_hz") or 0.0),
            float(raw_frame.get("span_hz") or raw_frame.get("sample_rate_hz") or 0.0),
        )
        if self._live_signature is not None and signature != self._live_signature:
            self._live_rows.clear()
            self._live_timestamps.clear()
        self._live_signature = signature

        self._live_rows.append([float(value) for value in levels])
        self._live_timestamps.append(raw_frame.get("timestamp_utc"))
        min_width = min(len(row) for row in self._live_rows)
        if min_width <= 0:
            return self._empty_live_result(raw_frame, "Live spectrum rows are empty.")
        matrix = np.asarray([row[:min_width] for row in self._live_rows], dtype=np.float32)
        freq_axis = [float(value) for value in freqs[: matrix.shape[1]]]
        frame_interval_s = float(raw_frame.get("frame_interval_s") or 0.1)
        time_axis = [index * frame_interval_s for index in range(matrix.shape[0])]
        regions = self.detector.detect(matrix, time_axis, freq_axis)
        result_regions: list[dict[str, Any]] = []

        for region in regions[:8]:
            region_matrix = self._region_matrix(matrix, region)
            classification = self.classifier.classify(region_matrix, region)
            trained_classification = self._trained_signal_type_classification(region_matrix, region)
            if trained_classification is not None:
                classification["trained"] = trained_classification
                classification["mlp"] = trained_classification
            if decision_mode == "ai_only" and trained_classification is None:
                continue
            spectral = self._live_spectral_features(region_matrix, region)
            bispectral = {
                "available": False,
                "reason": "Live mode currently receives PSD/waterfall frames, not raw I/Q samples.",
                "bispectral_peak_energy": 0.0,
                "bispectral_peak_location": [0.0, 0.0],
                "bispectral_entropy": 0.0,
                "phase_coupling_score": 0.0,
                "nonlinear_energy_ratio": 0.0,
            }
            fused = self.fusion.fuse(region, classification["visual"], classification["mlp"], spectral, bispectral, legacy_result)
            if decision_mode == "ai_only" and trained_classification is not None:
                fused = {
                    "final_label": trained_classification["label"],
                    "final_confidence": trained_classification["confidence"],
                    "decision_status": "accepted" if float(trained_classification["confidence"]) >= 0.5 else "ambiguous",
                    "method": "trained_signal_type_classifier_only",
                    "limitations": [
                        "AI-only mode classifies regions proposed by the current region detector.",
                        "This is a learned signal-type hypothesis, not confirmed protocol decoding.",
                    ],
                }
            result_regions.append(
                {
                    "bbox_id": region["bbox_id"],
                    "time_start_s": region["time_start_s"],
                    "time_end_s": region["time_end_s"],
                    "freq_start_hz": region["freq_start_hz"],
                    "freq_end_hz": region["freq_end_hz"],
                    "detector": {"type": region["detector"], "confidence": region["confidence"]},
                    "classification": {
                        "visual_label": classification["visual"]["label"],
                        "visual_confidence": classification["visual"]["confidence"],
                        "mlp_label": classification["mlp"]["label"],
                        "mlp_confidence": classification["mlp"]["confidence"],
                        "visual": classification["visual"],
                        "mlp": classification["mlp"],
                        "trained": classification.get("trained"),
                    },
                    "features": {"spectral": spectral, "bispectral": bispectral},
                    "final_decision": {
                        "label": fused["final_label"],
                        "confidence": fused["final_confidence"],
                        "status": fused["decision_status"],
                        "method": fused["method"],
                        "limitations": fused["limitations"],
                    },
                }
            )

        trace = self.traceability.for_steps(["waterfall_generation", "region_detection", "mlp_spectral_classification"])
        result = {
            "analysis_id": self.repository.new_analysis_id("rsu_live"),
            "mode": "live",
            "source": raw_frame.get("source", "real_sdr"),
            "timestamp_utc": raw_frame.get("timestamp_utc"),
            "input": {
                "center_frequency_hz": raw_frame.get("center_frequency_hz"),
                "sample_rate_hz": raw_frame.get("sample_rate_hz"),
                "span_hz": raw_frame.get("span_hz"),
                "format": "live_psd_waterfall",
            },
            "waterfall": {
                "rows": int(matrix.shape[0]),
                "freq_bins": int(matrix.shape[1]),
                "image_path": None,
                "note": "Live waterfall is built from recent real PSD frames.",
            },
            "regions": result_regions,
            "summary": self._summary(result_regions, []),
            "scientific_traceability": trace,
            "decision_mode": decision_mode,
        }
        self._cache_live_result(result)
        return result

    def compare_live_with_rf_intelligence(self, raw_frame: dict[str, Any], decision_mode: str = "hybrid") -> dict[str, Any]:
        legacy = self._legacy_result_from_frame(raw_frame)
        new_result = self.analyze_live_frame(raw_frame, legacy, decision_mode=decision_mode)
        first_region = new_result["regions"][0] if new_result["regions"] else {}
        first_decision = first_region.get("final_decision", {})
        new_summary = {
            "method": "live_waterfall_region_mlp_fusion",
            "label": first_decision.get("label", "unknown"),
            "confidence": first_decision.get("confidence", 0.0),
            "evidence": self._evidence_lines(first_region),
            "scientific_traceability": new_result["scientific_traceability"],
        }
        return {
            "analysis_id": f"compare_live_{new_result['analysis_id']}",
            "legacy_rf_intelligence": legacy,
            "new_rf_signal_understanding": new_summary,
            "comparison": self.comparison.compare(legacy, new_summary),
            "live_result": new_result,
        }

    def compare_with_rf_intelligence(self, request: CompareWithRFIntelligenceRequest) -> dict[str, Any]:
        new_result = self.analyze_capture(request)
        legacy = self._legacy_result(request)
        first_region = new_result["regions"][0] if new_result["regions"] else {}
        first_decision = first_region.get("final_decision", {})
        new_summary = {
            "method": "waterfall_region_mlp_bispectral_fusion",
            "label": first_decision.get("label", "unknown"),
            "confidence": first_decision.get("confidence", 0.0),
            "evidence": self._evidence_lines(first_region),
            "scientific_traceability": new_result["scientific_traceability"],
        }
        comparison = self.comparison.compare(legacy, new_summary)
        response = {
            "analysis_id": f"compare_{new_result['analysis_id']}",
            "legacy_rf_intelligence": legacy,
            "new_rf_signal_understanding": new_summary,
            "comparison": comparison,
        }
        analysis_dir = self.repository.analysis_dir(new_result["analysis_id"])
        self.repository.write_json(analysis_dir, "comparison_with_legacy.json", response)
        return response

    def train_region_detector(self, request: TrainingRequest) -> dict[str, Any]:
        return {
            "model_type": request.model_type,
            "model_id": request.model_id or "region_detector_v1",
            "task": "region_detection",
            "status": "requires_box_annotations",
            "metrics_required": VALIDATION_TASKS["region_detection"],
            "note": "Train the signal-type classifier first. Region-detector training requires labelled waterfall images with bounding-box ground truth.",
        }

    def train_classifier(self, request: TrainingRequest) -> dict[str, Any]:
        if request.model_type not in {"mlp_spectral_classifier", "waterfall_classifier"}:
            raise ValueError("train-classifier supports mlp_spectral_classifier or waterfall_classifier datasets, not region_detector.")
        if request.execution_target == "remote":
            if not request.remote_user.strip() or not request.remote_host.strip():
                raise ValueError("Remote training requires both remote_user and remote_host.")
            return {
                "status": "remote_training_not_ready",
                "execution_target": "remote",
                "remote_target": f"{request.remote_user}@{request.remote_host}",
                "reason": "RF Signal Understanding remote training needs a dedicated remote runner for the NumPy signal-type classifier. Local training is available now.",
                "next_step": "Use execution_target='local' for the current signal-type classifier, or add a dedicated RSU remote deployment script before enabling remote execution.",
            }
        dataset_dir = self._resolve_dataset_dir(request.dataset_path, request.dataset_name)
        feature_source = "iq_spectral"
        try:
            records = self._load_dataset_records(dataset_dir, require_iq=True, include_weak=request.include_weak_labels, weak_label_weight=request.weak_label_weight)
        except ValueError:
            records = self._load_dataset_records(dataset_dir, require_iq=False, include_weak=request.include_weak_labels, weak_label_weight=request.weak_label_weight)
            feature_source = "rf_region_metadata"
        if len(records) < 2:
            raise ValueError("At least two labelled I/Q region records are required for classifier training.")
        labels = sorted({record["label"] for record in records})
        if len(labels) < 2:
            raise ValueError("At least two labels are required for supervised classifier training.")
        effective_min_samples = 1
        self._enforce_min_samples_per_class(records, effective_min_samples)

        if feature_source == "iq_spectral":
            x = np.asarray([self._iq_feature_vector(self._record_path(record["iq_path"], dataset_dir), request.feature_bins) for record in records], dtype=np.float32)
        else:
            x = np.asarray([self._metadata_feature_vector(record) for record in records], dtype=np.float32)
        y = np.asarray([labels.index(record["label"]) for record in records], dtype=np.int64)
        weights = np.asarray([float(record.get("training_weight", 1.0)) for record in records], dtype=np.float64)
        train_idx, test_idx = self._train_test_split(y, request.test_split, records, request.split_strategy)
        model = self._train_softmax_classifier(x[train_idx], y[train_idx], len(labels), request.epochs, request.learning_rate, weights[train_idx])
        train_metrics = self._evaluate_softmax(model, x[train_idx], y[train_idx], labels)
        test_metrics = self._evaluate_softmax(model, x[test_idx], y[test_idx], labels) if test_idx.size else train_metrics

        model_dir = self.module_root / "models" / "mlp_spectral_classifier"
        model_dir.mkdir(parents=True, exist_ok=True)
        model_id = request.model_id or "signal_type_softmax_v1"
        model_path = model_dir / "model.npz"
        version_dir = self.storage_root / "learning_buffer" / "model_versions" / model_id
        version_dir.mkdir(parents=True, exist_ok=True)
        np.savez(
            model_path,
            weights=model["weights"],
            bias=model["bias"],
            mean=model["mean"],
            std=model["std"],
            labels=np.asarray(labels),
            feature_bins=np.asarray([request.feature_bins], dtype=np.int64),
            feature_source=np.asarray([feature_source]),
        )
        shutil.copy2(model_path, version_dir / "model.npz")
        metadata = {
            "model_id": model_id,
            "model_type": "numpy_softmax_regression",
            "task": "signal_type_classification",
            "input_type": "fixed_length_spectral_features_from_iq" if feature_source == "iq_spectral" else "rf_region_metadata_bootstrap_features",
            "trained_at_utc": datetime.now(timezone.utc).isoformat(),
            "dataset_dir": str(dataset_dir),
            "dataset_name": dataset_dir.name,
            "records": len(records),
            "labels": labels,
            "feature_config": {
                "feature_source": feature_source,
                "n_fft": "adaptive_up_to_4096" if feature_source == "iq_spectral" else None,
                "feature_length": int(x.shape[1]) if x.ndim == 2 else request.feature_bins,
                "normalization": "zscore",
            },
            "epochs": request.epochs,
            "learning_rate": request.learning_rate,
            "test_split": request.test_split,
            "split_strategy": request.split_strategy,
            "include_weak_labels": request.include_weak_labels,
            "weak_label_weight": request.weak_label_weight,
            "num_train_samples": int(train_idx.size),
            "num_validation_samples": int(test_idx.size),
            "requested_min_samples_per_class": request.min_samples_per_class,
            "effective_min_samples_per_class": effective_min_samples,
            "num_strong_samples": int(sum(1 for record in records if record.get("label_strength") == "strong")),
            "num_weak_samples": int(sum(1 for record in records if record.get("label_strength") == "weak")),
            "metrics": test_metrics,
            "train_metrics": train_metrics,
            "test_metrics": test_metrics,
            "status": "trained",
            "caveat": "This is a lightweight trained classifier, not protocol decoding. Metadata-only bootstrap models should be replaced with I/Q-trained models when enough captures exist.",
        }
        self.repository.write_json(model_dir, "metadata.json", metadata)
        self.repository.write_json(version_dir, "metadata.json", metadata)
        return {
            "model_id": model_id,
            "status": "trained",
            "num_strong_samples": metadata["num_strong_samples"],
            "num_weak_samples": metadata["num_weak_samples"],
            "labels": labels,
            "metrics": test_metrics,
            "model_path": str(model_path),
            "version_dir": str(version_dir),
            "feature_source": feature_source,
            "warning": "Trained from metadata-only buffer samples with relaxed minimum samples per class because no I/Q samples were available." if feature_source != "iq_spectral" else None,
        }

    def validate(self, request: ValidationRequest) -> dict[str, Any]:
        if request.task == "signal_type_classification":
            dataset_dir = self._resolve_dataset_dir(request.dataset_path, None)
            records = self._load_dataset_records(dataset_dir, require_iq=True, include_weak=True, weak_label_weight=0.4)
            model = self._load_softmax_model(self.module_root / "models" / "mlp_spectral_classifier" / "model.npz")
            labels = list(model["labels"])
            x = np.asarray([self._iq_feature_vector(self._record_path(record["iq_path"], dataset_dir), int(model["feature_bins"])) for record in records], dtype=np.float32)
            y = np.asarray([labels.index(record["label"]) for record in records if record["label"] in labels], dtype=np.int64)
            filtered_x = np.asarray([row for row, record in zip(x, records) if record["label"] in labels], dtype=np.float32)
            if filtered_x.size == 0:
                raise ValueError("No validation records match the trained model labels.")
            metrics = self._evaluate_softmax(model, filtered_x, y, labels)
            return {
                "task": request.task,
                "dataset_path": str(dataset_dir),
                "records": int(filtered_x.shape[0]),
                "metrics_required": VALIDATION_TASKS[request.task],
                "metrics": metrics,
                "status": "validated",
                "note": "Signal-type classification validation is separate from region detection and transmitter identification.",
            }
        return {
            "task": request.task,
            "dataset_path": request.dataset_path,
            "metrics_required": VALIDATION_TASKS[request.task],
            "status": "validation_spec_ready",
            "note": "Detection, signal-type classification, robustness, and transmitter identification are separate validation tasks.",
        }

    def review_region(self, request: RegionReviewRequest) -> dict[str, Any]:
        analysis_dir = self.repository.analysis_dir(request.analysis_id)
        try:
            result = self.repository.read_result(request.analysis_id)
        except FileNotFoundError:
            result = self._live_result_cache.get(request.analysis_id)
            if result is None:
                raise
        region = next((item for item in result.get("regions", []) if item.get("bbox_id") == request.bbox_id), None)
        if region is None:
            raise ValueError(f"Region not found in analysis {request.analysis_id}: {request.bbox_id}")

        review_record = {
            "analysis_id": request.analysis_id,
            "bbox_id": request.bbox_id,
            "label": request.label,
            "review_status": request.review_status,
            "reviewer": request.reviewer,
            "notes": request.notes,
            "label_source": "operator_correction" if request.review_status == "corrected" else "operator",
            "label_strength": "strong",
            "training_weight": 1.0,
            "legacy_label": request.legacy_label,
            "candidate_label": region.get("final_decision", {}).get("label"),
            "candidate_confidence": region.get("final_decision", {}).get("confidence"),
            "region_image_path": region.get("region_image_path"),
            "iq_segment_path": region.get("iq_extraction", {}).get("iq_segment_path"),
            "frequency": {
                "start_hz": region.get("freq_start_hz"),
                "end_hz": region.get("freq_end_hz"),
            },
            "time": {
                "start_s": region.get("time_start_s"),
                "end_s": region.get("time_end_s"),
            },
        }
        review_dir = analysis_dir / "review"
        review_dir.mkdir(parents=True, exist_ok=True)
        self.repository.write_json(review_dir, f"{request.bbox_id}_review.json", review_record)

        reviews_path = analysis_dir / "region_reviews.json"
        reviews: list[dict[str, Any]] = []
        if reviews_path.exists():
            with reviews_path.open("r", encoding="utf-8") as file:
                reviews = json.load(file)
        reviews = [item for item in reviews if item.get("bbox_id") != request.bbox_id]
        reviews.append(review_record)
        self.repository.write_json(analysis_dir, "region_reviews.json", reviews)
        buffer_record = None
        if request.send_to_training_buffer and request.review_status not in {"rejected", "ambiguous"}:
            buffer_record = self._add_region_to_learning_buffer(analysis_dir, region, review_record)
            self._append_buffer_index("strong_labels.json", buffer_record)
        return {"status": "review_saved", "review": review_record, "learning_buffer_sample": buffer_record}

    def create_pseudo_label(self, request: PseudoLabelRequest) -> dict[str, Any]:
        if request.legacy_confidence < 0.85:
            raise ValueError("Weak pseudo-labels require legacy_confidence >= 0.85.")
        center = float(request.center_frequency_hz or 0.0)
        if 2_400_000_000 <= center <= 2_500_000_000:
            raise ValueError("Automatic pseudo-labels are disabled in ambiguous 2.4 GHz bands; operator confirmation is required.")
        analysis_dir = self.repository.analysis_dir(request.analysis_id)
        result = self.repository.read_result(request.analysis_id)
        region = next((item for item in result.get("regions", []) if item.get("bbox_id") == request.bbox_id), None)
        if region is None:
            raise ValueError(f"Region not found in analysis {request.analysis_id}: {request.bbox_id}")
        label = self._legacy_label_to_signal_label(request.legacy_label, request.legacy_family)
        pseudo = {
            "analysis_id": request.analysis_id,
            "bbox_id": request.bbox_id,
            "label": label,
            "label_source": "legacy_rf_intelligence",
            "label_strength": "weak",
            "legacy_label": request.legacy_label,
            "legacy_family": request.legacy_family,
            "legacy_confidence": request.legacy_confidence,
            "training_weight": min(float(request.training_weight), 0.4),
            "review_status": "pseudo_labeled",
            "session_id": request.session_id,
            "capture_id": request.capture_id,
        }
        sample = self._add_region_to_learning_buffer(analysis_dir, region, pseudo)
        self._append_buffer_index("pseudo_labels.json", sample)
        return {"status": "pseudo_label_added", "sample": sample}

    def train_classifier_incremental(self, request: IncrementalTrainingRequest) -> dict[str, Any]:
        request.dataset_name = request.dataset_name or "learning_buffer"
        request.model_id = request.new_model_id
        result = self.train_classifier(request)
        if result.get("status") != "trained":
            return result
        version_dir = self.storage_root / "learning_buffer" / "model_versions" / request.new_model_id
        metadata_path = version_dir / "metadata.json"
        if metadata_path.exists():
            with metadata_path.open("r", encoding="utf-8") as file:
                metadata = json.load(file)
            metadata["base_model_id"] = request.base_model_id
            metadata["incremental_training"] = True
            self.repository.write_json(version_dir, "metadata.json", metadata)
        return result

    def compare_models(self, request: CompareModelsRequest) -> dict[str, Any]:
        dataset_dir = self._resolve_dataset_dir(request.dataset_path, request.dataset_name)
        records = self._load_dataset_records(dataset_dir, require_iq=True, include_weak=False, weak_label_weight=0.0)
        current = self._load_model_version(request.current_model_id)
        current_metrics = self._evaluate_model_on_records(current, records, dataset_dir)
        previous_metrics = None
        improvement = None
        if request.previous_model_id:
            previous = self._load_model_version(request.previous_model_id)
            previous_metrics = self._evaluate_model_on_records(previous, records, dataset_dir)
            improvement = {
                "accuracy_delta": current_metrics["accuracy"] - previous_metrics["accuracy"],
                "macro_f1_delta": current_metrics["macro_f1"] - previous_metrics["macro_f1"],
            }
        return {
            "dataset_path": str(dataset_dir),
            "current_model_id": request.current_model_id,
            "previous_model_id": request.previous_model_id,
            "legacy_rf_intelligence": self._legacy_agreement_from_records(records) if request.include_legacy else None,
            "current_model_metrics": current_metrics,
            "previous_model_metrics": previous_metrics,
            "improvement_over_previous_model": improvement,
            "note": "Comparison is for signal-type classification only; region detection and transmitter fingerprinting are separate tasks.",
        }

    def export_labelled_regions(self, request: ExportLabelledRegionsRequest) -> dict[str, Any]:
        dataset_dir = self.storage_root / "datasets" / self._safe_dataset_name(request.dataset_name)
        images_dir = dataset_dir / "images"
        iq_dir = dataset_dir / "iq"
        labels_dir = dataset_dir / "labels"
        for path in (images_dir, iq_dir, labels_dir):
            path.mkdir(parents=True, exist_ok=True)

        analysis_ids = request.analysis_ids or self._all_analysis_ids()
        manifest: list[dict[str, Any]] = []
        for analysis_id in analysis_ids:
            analysis_dir = self.repository.analysis_dir(analysis_id)
            result_path = analysis_dir / "results.json"
            if not result_path.exists():
                continue
            with result_path.open("r", encoding="utf-8") as file:
                result = json.load(file)
            reviews = self._load_reviews(analysis_dir)
            for region in result.get("regions", []):
                review = reviews.get(region.get("bbox_id"))
                if review is None and not request.include_unreviewed:
                    continue
                label = (review or {}).get("label") or region.get("final_decision", {}).get("label", "unknown")
                export_id = f"{analysis_id}_{region.get('bbox_id')}"
                image_target = self._copy_if_exists(region.get("region_image_path"), images_dir / f"{export_id}.png")
                iq_target = self._copy_if_exists(region.get("iq_extraction", {}).get("iq_segment_path"), iq_dir / f"{export_id}.iq")
                label_record = {
                    "id": export_id,
                    "sample_id": export_id,
                    "analysis_id": analysis_id,
                    "bbox_id": region.get("bbox_id"),
                    "label": label,
                    "label_source": (review or {}).get("label_source", "operator" if review else "heuristic_candidate"),
                    "label_strength": (review or {}).get("label_strength", "strong" if review else "weak"),
                    "training_weight": float((review or {}).get("training_weight", 1.0 if review else 0.3)),
                    "review_status": (review or {}).get("review_status", "unreviewed"),
                    "candidate_label": region.get("final_decision", {}).get("label"),
                    "candidate_confidence": region.get("final_decision", {}).get("confidence"),
                    "image_path": str(image_target) if image_target else None,
                    "iq_path": str(iq_target) if iq_target else None,
                    "region": {
                        "time_start_s": region.get("time_start_s"),
                        "time_end_s": region.get("time_end_s"),
                        "freq_start_hz": region.get("freq_start_hz"),
                        "freq_end_hz": region.get("freq_end_hz"),
                    },
                    "center_frequency_hz": (float(region.get("freq_start_hz", 0.0)) + float(region.get("freq_end_hz", 0.0))) / 2.0,
                    "occupied_bandwidth_hz": float(region.get("freq_end_hz", 0.0)) - float(region.get("freq_start_hz", 0.0)),
                    "snr_db": region.get("features", {}).get("spectral", {}).get("snr_db"),
                    "sample_rate_hz": result.get("input", {}).get("sample_rate_hz"),
                    "gain_db": result.get("input", {}).get("gain_db"),
                    "capture_id": result.get("input", {}).get("capture_id"),
                    "session_id": result.get("input", {}).get("session_id"),
                }
                self.repository.write_json(labels_dir, f"{export_id}.json", label_record)
                manifest.append(label_record)
        self.repository.write_json(dataset_dir, "manifest.json", manifest)
        return {
            "status": "dataset_exported",
            "dataset_dir": str(dataset_dir),
            "records": len(manifest),
            "labels": sorted({str(item["label"]) for item in manifest}),
        }

    def models(self) -> list[dict[str, Any]]:
        return self.model_registry.list_models()

    def references(self) -> dict[str, Any]:
        return self.traceability.references()

    def register_capture(self, request: RegisterCaptureRequest) -> dict[str, Any]:
        capture = {
            "capture_id": request.capture_id or self.repository.new_analysis_id("cap"),
            "file_path": str(Path(request.file_path).expanduser().resolve()),
            "file_format": "iq" if request.file_format == "complex64" else request.file_format,
            "sample_rate_hz": float(request.sample_rate_hz),
            "center_frequency_hz": float(request.center_frequency_hz),
            "gain_db": request.gain_db,
            "duration_s": request.duration_s,
            "source": request.source,
            "session_id": request.session_id,
            "profile_key": request.profile_key,
            "profile": request.profile,
            "transmitter_id": request.transmitter_id,
            "transmitter_class": request.transmitter_class,
            "operator": request.operator,
            "environment": request.environment,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "analysis_status": "pending",
            "training_status": "not_reviewed",
            "labels": [],
            "used_for_training": False,
        }
        self._upsert_capture(capture)
        return capture

    def list_registered_captures(self) -> dict[str, Any]:
        captures = self._read_capture_registry()
        return {"captures": sorted(captures, key=lambda item: item.get("created_at", ""), reverse=True)}

    def delete_registered_capture(self, capture_id: str) -> None:
        captures = self._read_capture_registry()
        updated_captures = [c for c in captures if c.get("capture_id") != capture_id]
        if len(updated_captures) == len(captures):
            raise FileNotFoundError(f"Registered RF capture not found: {capture_id}")
        self._write_capture_registry(updated_captures)

    def analyze_registered_capture(self, capture_id: str) -> dict[str, Any]:
        capture = self._get_registered_capture(capture_id)
        analysis = self.analyze_capture(
            AnalyzeCaptureRequest(
                file_path=capture["file_path"],
                sample_rate_hz=float(capture["sample_rate_hz"]),
                center_frequency_hz=float(capture["center_frequency_hz"]),
                format="iq" if capture.get("file_format") == "iq" else "cfile",
                analysis_id=f"rsu_{capture_id}",
            )
        )
        legacy = self._legacy_from_analysis_waterfall(analysis)
        comparison = self._comparison_rows(analysis, legacy)
        capture.update(
            {
                "analysis_status": "analyzed",
                "analysis_id": analysis["analysis_id"],
                "region_count": len(analysis.get("regions", [])),
                "legacy_prediction": legacy,
                "comparison": comparison,
            }
        )
        self._upsert_capture(capture)
        analysis_dir = self.repository.analysis_dir(analysis["analysis_id"])
        self.repository.write_json(analysis_dir, "legacy_vs_new_comparison.json", comparison)
        return {"capture": capture, "analysis": analysis, "comparison": comparison}

    def capture_for_training(self, request: CaptureForTrainingRequest, modulated_signal_controller: Any) -> dict[str, Any]:
        resolved_profile = resolve_band_profile(
            start_frequency_hz=request.start_frequency_hz,
            stop_frequency_hz=request.stop_frequency_hz,
        )
        default_label = str((resolved_profile.get("defaults") or {}).get("transmitter_label") or "")
        label_hint = request.label_hint
        if not label_hint or label_hint.strip().lower() in {"unknown", "unlabeled", "profile_pending", "band_profile_pending"}:
            label_hint = default_label or "unresolved_rf_signal"
        capture = modulated_signal_controller.capture_marker_band(
            start_frequency_hz=request.start_frequency_hz,
            stop_frequency_hz=request.stop_frequency_hz,
            duration_seconds=request.duration_seconds,
            label=label_hint,
            modulation_hint=label_hint or "unknown",
            session_id=request.session_id,
            file_format=request.file_format,
            apply_bandpass_filter=bool(request.apply_bandpass_filter),
            filter_stopband_attenuation_db=float(request.filter_stopband_attenuation_db),
            filter_transition_width_hz=request.filter_transition_width_hz,
            live_preview_snr_db=request.live_preview_snr_db,
            live_preview_noise_floor_db=request.live_preview_noise_floor_db,
            live_preview_peak_level_db=request.live_preview_peak_level_db,
            live_preview_peak_frequency_hz=request.live_preview_peak_frequency_hz,
            transmitter_id=request.transmitter_id or "",
            transmitter_class=request.transmitter_class or "",
            operator=request.operator or "",
            environment=request.environment or "",
        )
        iq_path = capture.get("iq_file")
        if not iq_path:
            raise ValueError("Capture Lab did not return an IQ file path")
        registered = self.register_capture(
            RegisterCaptureRequest(
                capture_id=str(capture.get("id") or self.repository.new_analysis_id("cap")),
                file_path=str(iq_path),
                file_format=request.file_format,
                sample_rate_hz=float(capture.get("sample_rate_hz") or 0.0),
                center_frequency_hz=float(capture.get("center_frequency_hz") or 0.0),
                gain_db=capture.get("gain_db"),
                duration_s=float(capture.get("duration_seconds") or request.duration_seconds),
                source="capture_lab",
                session_id=request.session_id,
                profile_key=request.profile_key or resolved_profile.get("profile_key"),
                profile=request.profile or resolved_profile,
                transmitter_id=request.transmitter_id,
                transmitter_class=request.transmitter_class,
                operator=request.operator,
                environment=request.environment,
            )
        )
        analyzed = self.analyze_registered_capture(registered["capture_id"])
        return {"status": "captured_registered_analyzed", "capture": analyzed["capture"], "analysis": analyzed["analysis"], "comparison": analyzed["comparison"]}

    def training_queue_summary(self) -> dict[str, Any]:
        buffer_dir = self.storage_root / "learning_buffer"
        samples = self._read_buffer_manifest(buffer_dir)
        by_class: dict[str, dict[str, int]] = {}
        totals = {
            "total_samples": len(samples),
            "trainable_iq_samples": 0,
            "non_trainable_live_samples": 0,
            "strong_labels": 0,
            "weak_labels": 0,
            "unknown_samples": 0,
            "ambiguous_samples": 0,
            "excluded_samples": 0,
        }
        for sample in samples:
            label = str(sample.get("label") or "unknown")
            strength = str(sample.get("label_strength") or "unknown")
            status = str(sample.get("review_status") or "")
            iq_path = sample.get("iq_path")
            has_iq = bool(iq_path and self._record_path(iq_path, buffer_dir).exists())
            by_class.setdefault(label, {"strong": 0, "weak": 0, "total": 0, "trainable_iq": 0, "bootstrap_metadata": 0})
            by_class[label]["total"] += 1
            if has_iq and label != "ambiguous" and status not in {"ambiguous", "excluded", "rejected"}:
                by_class[label]["trainable_iq"] += 1
                totals["trainable_iq_samples"] += 1
            else:
                totals["non_trainable_live_samples"] += 1
                if label != "ambiguous" and status not in {"ambiguous", "excluded", "rejected"}:
                    by_class[label]["bootstrap_metadata"] += 1
            if strength == "weak":
                by_class[label]["weak"] += 1
                totals["weak_labels"] += 1
            elif strength == "strong":
                by_class[label]["strong"] += 1
                totals["strong_labels"] += 1
            if label == "unknown":
                totals["unknown_samples"] += 1
            if label == "ambiguous" or status == "ambiguous":
                totals["ambiguous_samples"] += 1
            if status == "excluded":
                totals["excluded_samples"] += 1
        target_min_samples = 5
        configured_min_samples = 5
        ready_classes = {label: counts for label, counts in by_class.items() if label != "ambiguous" and counts["trainable_iq"] >= target_min_samples}
        configured_ready_classes = {
            label: counts
            for label, counts in by_class.items()
            if label != "ambiguous" and max(counts["trainable_iq"], counts["bootstrap_metadata"]) >= configured_min_samples
        }
        test_ready_classes = {label: counts for label, counts in by_class.items() if label != "ambiguous" and counts["trainable_iq"] >= 1}
        reasons: list[str] = []
        configured_reasons: list[str] = []
        if totals["trainable_iq_samples"] == 0:
            message = "No trainable I/Q samples are available. Training will use a metadata-only bootstrap model until I/Q samples are collected."
            reasons.append(message)
        metadata_ready_classes = {label: counts for label, counts in by_class.items() if label != "ambiguous" and counts["bootstrap_metadata"] >= 1}
        if len(test_ready_classes) < 2 and len(metadata_ready_classes) < 2:
            message = "At least two non-ambiguous classes with I/Q samples are required."
            reasons.append(message)
            configured_reasons.append(message)
        if len(configured_ready_classes) < 2:
            configured_reasons.append(f"Training button requires at least {configured_min_samples} I/Q samples per non-ambiguous class.")
        if len(ready_classes) < 2:
            reasons.append(f"Target readiness requires at least {target_min_samples} I/Q samples per class.")
        return {
            **totals,
            "samples_per_class": by_class,
            "target_min_samples_per_class": target_min_samples,
            "training_config_min_samples_per_class": configured_min_samples,
            "ready_to_train": len(ready_classes) >= 2,
            "ready_for_training_config": len(configured_ready_classes) >= 2,
            "ready_for_smoke_test": len(test_ready_classes) >= 2,
            "not_ready_reasons": reasons,
            "not_ready_for_training_config_reasons": configured_reasons,
        }

    def _read_iq(self, input_path: Path) -> np.ndarray:
        if not input_path.exists():
            raise FileNotFoundError(f"I/Q capture not found: {input_path}")
        return np.fromfile(input_path, dtype=np.complex64)

    def _region_matrix(self, matrix: np.ndarray, region: dict[str, Any]) -> np.ndarray:
        bounds = region.get("pixel_bounds", {})
        t0 = int(bounds.get("time_start", 0))
        t1 = int(bounds.get("time_end", matrix.shape[0] - 1))
        f0 = int(bounds.get("freq_start", 0))
        f1 = int(bounds.get("freq_end", matrix.shape[1] - 1))
        return matrix[max(t0, 0) : min(t1 + 1, matrix.shape[0]), max(f0, 0) : min(f1 + 1, matrix.shape[1])]

    def _summary(self, regions: list[dict[str, Any]], decisions: list[dict[str, Any]]) -> dict[str, Any]:
        labels: dict[str, int] = {}
        for decision in decisions:
            label = str(decision.get("final_label", "unknown"))
            labels[label] = labels.get(label, 0) + 1
        return {
            "region_count": len(regions),
            "labels": labels,
            "warning": "Labels are signal-type hypotheses, not confirmed protocol decoding.",
        }

    def _legacy_result(self, request: CompareWithRFIntelligenceRequest) -> dict[str, Any]:
        if request.legacy_frame:
            return self._legacy_result_from_frame(request.legacy_frame)
        return {
            "method": "band_profile_matching",
            "label": "unknown",
            "family": "unknown",
            "confidence": 0.0,
            "evidence": ["No legacy spectrum frame was supplied for rf_intelligence comparison."],
        }

    def _legacy_result_from_frame(self, raw_frame: dict[str, Any]) -> dict[str, Any]:
        frame = SpectrumFrameInput(
            timestamp_utc=raw_frame.get("timestamp_utc"),
            center_frequency_hz=raw_frame.get("center_frequency_hz", 0),
            span_hz=raw_frame.get("span_hz", 0),
            start_frequency_hz=raw_frame.get("start_frequency_hz"),
            stop_frequency_hz=raw_frame.get("stop_frequency_hz"),
            sample_rate_hz=raw_frame.get("sample_rate_hz"),
            frequencies_hz=raw_frame.get("frequencies_hz") or [],
            levels_db=raw_frame.get("levels_db") or [],
        )
        scene = self.legacy_service.analyze_frame(frame, RFIntelligenceSettings())
        if scene.detections:
            detection = scene.detections[0]
            return {
                "method": "band_profile_matching",
                "label": detection.label,
                "family": detection.candidate_family,
                "confidence": detection.confidence,
                "evidence": detection.evidence.notes,
            }
        return {
            "method": "band_profile_matching",
            "label": "unknown",
            "family": "unknown",
            "confidence": 0.0,
            "evidence": ["rf_intelligence did not detect an active object in the current live frame."],
        }

    def _evidence_lines(self, region: dict[str, Any]) -> list[str]:
        if not region:
            return ["No clear active time-frequency region detected."]
        classification = region.get("classification", {})
        features = region.get("features", {}).get("spectral", {})
        return [
            "active time-frequency region detected",
            f"visual classifier predicts {classification.get('visual_label', 'unknown')}",
            f"MLP temporal membership supports {classification.get('mlp_label', 'unknown')}",
            f"spectral features indicate occupied bandwidth {features.get('occupied_bandwidth_hz', 0.0):.1f} Hz",
        ]

    def _training_stub(self, request: TrainingRequest, task: str, metrics: list[str]) -> dict[str, Any]:
        return {
            "model_type": request.model_type,
            "model_id": request.model_id or f"{request.model_type}_v1",
            "dataset_path": request.dataset_path,
            "task": task,
            "status": "not_started",
            "metrics_required": metrics,
            "note": "Training endpoint is reserved; provide labeled waterfall regions before enabling model fitting.",
        }

    def _resolve_dataset_dir(self, dataset_path: str | None, dataset_name: str | None = None) -> Path:
        if dataset_path:
            dataset_dir = Path(dataset_path).expanduser().resolve()
        elif dataset_name == "learning_buffer":
            dataset_dir = self.storage_root / "learning_buffer"
        elif dataset_name:
            dataset_dir = self.storage_root / "datasets" / self._safe_dataset_name(dataset_name)
        else:
            datasets_root = self.storage_root / "datasets"
            candidates = [path for path in datasets_root.iterdir() if (path / "manifest.json").exists()] if datasets_root.exists() else []
            if not candidates:
                raise FileNotFoundError("No exported labelled-region dataset found. Export one first.")
            dataset_dir = max(candidates, key=lambda path: path.stat().st_mtime).resolve()
        if not (dataset_dir / "manifest.json").exists():
            raise FileNotFoundError(f"Dataset manifest not found: {dataset_dir / 'manifest.json'}")
        return dataset_dir

    def _load_dataset_records(self, dataset_dir: Path, require_iq: bool, include_weak: bool = True, weak_label_weight: float = 0.4) -> list[dict[str, Any]]:
        with (dataset_dir / "manifest.json").open("r", encoding="utf-8") as file:
            manifest = json.load(file)
        records: list[dict[str, Any]] = []
        for item in manifest:
            label = str(item.get("label", "")).strip()
            iq_path = item.get("iq_path")
            if not label or label in {"rejected", "ambiguous"}:
                continue
            strength = str(item.get("label_strength", "strong"))
            if strength == "weak" and not include_weak:
                continue
            item = {**item, "training_weight": min(float(item.get("training_weight", weak_label_weight)), weak_label_weight) if strength == "weak" else float(item.get("training_weight", 1.0))}
            if require_iq and (not iq_path or not self._record_path(iq_path, dataset_dir).exists()):
                continue
            records.append({**item, "label": label})
        if not records:
            raise ValueError("Dataset has no usable labelled records with I/Q segments.")
        return records

    def _record_path(self, value: Any, dataset_dir: Path) -> Path:
        path = Path(str(value))
        return path if path.is_absolute() else dataset_dir / path

    def _enforce_min_samples_per_class(self, records: list[dict[str, Any]], minimum: int) -> None:
        if minimum <= 1:
            return
        counts: dict[str, int] = {}
        for record in records:
            counts[str(record["label"])] = counts.get(str(record["label"]), 0) + 1
        too_small = {label: count for label, count in counts.items() if count < minimum}
        if too_small:
            raise ValueError(f"Not enough samples per class for training: {too_small}")

    def _iq_feature_vector(self, iq_path: Path, feature_bins: int) -> np.ndarray:
        samples = np.fromfile(iq_path, dtype=np.complex64)
        if samples.size == 0:
            return np.zeros(feature_bins, dtype=np.float32)
        n_fft = min(max(256, 2 ** int(np.ceil(np.log2(min(samples.size, 4096))))), 4096)
        if samples.size < n_fft:
            padded = np.zeros(n_fft, dtype=np.complex64)
            padded[: samples.size] = samples
            samples = padded
        window = np.hanning(n_fft).astype(np.float32)
        spectrum = np.fft.fftshift(np.fft.fft(samples[:n_fft] * window, n=n_fft))
        power = 20.0 * np.log10(np.abs(spectrum) + 1e-9)
        source_x = np.linspace(0.0, 1.0, power.size)
        target_x = np.linspace(0.0, 1.0, feature_bins)
        vector = np.interp(target_x, source_x, power)
        vector = vector - np.mean(vector)
        scale = np.std(vector)
        if scale > 1e-9:
            vector = vector / scale
        return vector.astype(np.float32)

    def _waterfall_feature_vector(self, region_matrix: np.ndarray, feature_bins: int) -> np.ndarray:
        matrix = np.asarray(region_matrix, dtype=np.float32)
        if matrix.size == 0:
            return np.zeros(feature_bins, dtype=np.float32)
        if matrix.ndim == 1:
            power = matrix
        else:
            power = np.mean(matrix, axis=0)
        if power.size == 0:
            return np.zeros(feature_bins, dtype=np.float32)
        source_x = np.linspace(0.0, 1.0, power.size)
        target_x = np.linspace(0.0, 1.0, feature_bins)
        vector = np.interp(target_x, source_x, power)
        vector = vector - np.mean(vector)
        scale = np.std(vector)
        if scale > 1e-9:
            vector = vector / scale
        return vector.astype(np.float32)

    def _metadata_feature_vector(self, record: dict[str, Any]) -> np.ndarray:
        center_hz = float(record.get("center_frequency_hz") or 0.0)
        bandwidth_hz = abs(float(record.get("occupied_bandwidth_hz") or record.get("bandwidth_hz") or 0.0))
        snr_db = float(record.get("snr_db") or 0.0)
        sample_rate_hz = abs(float(record.get("sample_rate_hz") or 0.0))
        gain_db = float(record.get("gain_db") or 0.0)
        duration_s = abs(float(record.get("duration_s") or record.get("burst_duration_s") or 0.0))
        confidence = float(record.get("candidate_confidence") or record.get("confidence") or 0.0)
        return np.asarray(
            [
                np.log10(max(center_hz, 1.0)) / 10.0,
                np.log10(max(bandwidth_hz, 1.0)) / 8.0,
                np.log10(max(sample_rate_hz, 1.0)) / 8.0,
                np.clip(snr_db / 60.0, -1.0, 1.0),
                np.clip(gain_db / 80.0, -1.0, 1.0),
                np.clip(duration_s / 10.0, 0.0, 1.0),
                np.clip(confidence, 0.0, 1.0),
                1.0,
            ],
            dtype=np.float32,
        )

    def _region_metadata_feature_vector(self, region: dict[str, Any]) -> np.ndarray:
        return self._metadata_feature_vector(
            {
                "center_frequency_hz": (float(region.get("freq_start_hz", 0.0)) + float(region.get("freq_end_hz", 0.0))) / 2.0,
                "occupied_bandwidth_hz": float(region.get("freq_end_hz", 0.0)) - float(region.get("freq_start_hz", 0.0)),
                "confidence": region.get("final_decision", {}).get("confidence") or region.get("confidence"),
                "duration_s": float(region.get("time_end_s", 0.0)) - float(region.get("time_start_s", 0.0)),
            }
        )

    def _trained_signal_type_classification(self, region_matrix: np.ndarray, region: dict[str, Any] | None = None) -> dict[str, Any] | None:
        model_path = self.module_root / "models" / "mlp_spectral_classifier" / "model.npz"
        if not model_path.exists():
            return None
        try:
            model = self._load_softmax_model(model_path)
            if model.get("feature_source") == "rf_region_metadata":
                vector = self._region_metadata_feature_vector(region or {})
            else:
                vector = self._waterfall_feature_vector(region_matrix, int(model["feature_bins"]))
            probs = self._predict_softmax(model, vector.reshape(1, -1))[0]
        except Exception:
            return None
        labels = list(model["labels"])
        order = np.argsort(probs)[::-1]
        best_index = int(order[0])
        return {
            "classifier": "trained_signal_type_classifier",
            "model_id": "active_signal_type_softmax",
            "label": labels[best_index],
            "confidence": float(probs[best_index]),
            "top_k": [{"label": labels[int(index)], "score": float(probs[int(index)])} for index in order[: min(3, len(order))]],
            "feature_source": model.get("feature_source", "iq_spectral"),
            "note": "Applied to live detection as a learned signal-type hypothesis.",
        }

    def _train_test_split(self, y: np.ndarray, test_split: float, records: list[dict[str, Any]] | None = None, split_strategy: str = "random") -> tuple[np.ndarray, np.ndarray]:
        if records and split_strategy in {"session_id", "capture_id"}:
            grouped: dict[str, list[int]] = {}
            for index, record in enumerate(records):
                key = str(record.get(split_strategy) or record.get("capture_id") or f"sample_{index}")
                grouped.setdefault(key, []).append(index)
            if len(grouped) > 1:
                rng = np.random.default_rng(1337)
                keys = np.asarray(list(grouped.keys()))
                rng.shuffle(keys)
                test_group_count = max(1, int(round(len(keys) * min(max(test_split, 0.0), 0.8))))
                test_keys = set(keys[:test_group_count])
                test_idx = np.asarray([idx for key in test_keys for idx in grouped[key]], dtype=np.int64)
                train_idx = np.asarray([idx for key, values in grouped.items() if key not in test_keys for idx in values], dtype=np.int64)
                if train_idx.size and test_idx.size:
                    return train_idx, test_idx
        rng = np.random.default_rng(1337)
        train_parts: list[np.ndarray] = []
        test_parts: list[np.ndarray] = []
        for label in np.unique(y):
            indexes = np.flatnonzero(y == label)
            rng.shuffle(indexes)
            if indexes.size <= 2:
                train_parts.append(indexes)
                continue
            test_count = max(1, int(round(indexes.size * min(max(test_split, 0.0), 0.8))))
            test_parts.append(indexes[:test_count])
            train_parts.append(indexes[test_count:])
        train_idx = np.concatenate(train_parts) if train_parts else np.arange(y.size)
        test_idx = np.concatenate(test_parts) if test_parts else np.asarray([], dtype=np.int64)
        rng.shuffle(train_idx)
        rng.shuffle(test_idx)
        return train_idx, test_idx

    def _train_softmax_classifier(
        self,
        x: np.ndarray,
        y: np.ndarray,
        class_count: int,
        epochs: int,
        learning_rate: float,
        sample_weights: np.ndarray | None = None,
    ) -> dict[str, Any]:
        mean = np.mean(x, axis=0)
        std = np.std(x, axis=0) + 1e-6
        xn = (x - mean) / std
        weights = np.zeros((xn.shape[1], class_count), dtype=np.float64)
        bias = np.zeros(class_count, dtype=np.float64)
        one_hot = np.eye(class_count, dtype=np.float64)[y]
        weights_per_sample = np.asarray(sample_weights if sample_weights is not None else np.ones(xn.shape[0]), dtype=np.float64).reshape(-1, 1)
        weights_per_sample = weights_per_sample / max(float(np.mean(weights_per_sample)), 1e-9)
        lr = float(max(min(learning_rate, 1.0), 1e-4))
        for _ in range(max(1, int(epochs))):
            logits = xn @ weights + bias
            logits -= np.max(logits, axis=1, keepdims=True)
            exp_logits = np.exp(logits)
            probs = exp_logits / np.sum(exp_logits, axis=1, keepdims=True)
            error = ((probs - one_hot) * weights_per_sample) / max(xn.shape[0], 1)
            weights -= lr * (xn.T @ error + 1e-4 * weights)
            bias -= lr * np.sum(error, axis=0)
        return {"weights": weights, "bias": bias, "mean": mean, "std": std}

    def _load_softmax_model(self, model_path: Path) -> dict[str, Any]:
        if not model_path.exists():
            raise FileNotFoundError(f"Trained classifier model not found: {model_path}")
        data = np.load(model_path, allow_pickle=False)
        return {
            "weights": data["weights"],
            "bias": data["bias"],
            "mean": data["mean"],
            "std": data["std"],
            "labels": [str(label) for label in data["labels"].tolist()],
            "feature_bins": int(data["feature_bins"][0]),
            "feature_source": str(data["feature_source"][0]) if "feature_source" in data.files else "iq_spectral",
        }

    def _predict_softmax(self, model: dict[str, Any], x: np.ndarray) -> np.ndarray:
        xn = (x - model["mean"]) / model["std"]
        logits = xn @ model["weights"] + model["bias"]
        logits -= np.max(logits, axis=1, keepdims=True)
        exp_logits = np.exp(logits)
        return exp_logits / np.sum(exp_logits, axis=1, keepdims=True)

    def _evaluate_softmax(self, model: dict[str, Any], x: np.ndarray, y: np.ndarray, labels: list[str]) -> dict[str, Any]:
        probs = self._predict_softmax(model, x)
        pred = np.argmax(probs, axis=1)
        accuracy = float(np.mean(pred == y)) if y.size else 0.0
        confusion = np.zeros((len(labels), len(labels)), dtype=int)
        for actual, predicted in zip(y, pred):
            confusion[int(actual), int(predicted)] += 1
        f1_scores: list[float] = []
        per_class_precision: dict[str, float] = {}
        per_class_recall: dict[str, float] = {}
        per_class_f1: dict[str, float] = {}
        for index in range(len(labels)):
            tp = float(confusion[index, index])
            fp = float(np.sum(confusion[:, index]) - tp)
            fn = float(np.sum(confusion[index, :]) - tp)
            precision = tp / max(tp + fp, 1.0)
            recall = tp / max(tp + fn, 1.0)
            f1 = (2 * precision * recall) / max(precision + recall, 1e-9)
            per_class_precision[labels[index]] = precision
            per_class_recall[labels[index]] = recall
            per_class_f1[labels[index]] = f1
            f1_scores.append(f1)
        top_k = min(3, len(labels))
        top_k_pred = np.argsort(probs, axis=1)[:, -top_k:]
        top_k_accuracy = float(np.mean([actual in row for actual, row in zip(y, top_k_pred)])) if y.size else 0.0
        unknown_index = labels.index("unknown") if "unknown" in labels else None
        unknown_detection_rate = None
        if unknown_index is not None:
            unknown_mask = y == unknown_index
            unknown_detection_rate = float(np.mean(pred[unknown_mask] == unknown_index)) if np.any(unknown_mask) else None
        return {
            "accuracy": accuracy,
            "macro_f1": float(np.mean(f1_scores)) if f1_scores else 0.0,
            "per_class_precision": per_class_precision,
            "per_class_recall": per_class_recall,
            "per_class_f1": per_class_f1,
            "top_k_accuracy": top_k_accuracy,
            "unknown_detection_rate": unknown_detection_rate,
            "confusion_matrix": {
                "labels": labels,
                "matrix": confusion.tolist(),
            },
        }

    def _add_region_to_learning_buffer(self, analysis_dir: Path, region: dict[str, Any], label_record: dict[str, Any]) -> dict[str, Any]:
        buffer_dir = self.storage_root / "learning_buffer"
        samples_dir = buffer_dir / "samples"
        samples_dir.mkdir(parents=True, exist_ok=True)
        (buffer_dir / "model_versions").mkdir(parents=True, exist_ok=True)
        sample_id = self._next_sample_id(buffer_dir)
        iq_target = self._copy_if_exists(region.get("iq_extraction", {}).get("iq_segment_path"), samples_dir / f"{sample_id}.iq")
        image_target = self._copy_if_exists(region.get("region_image_path"), samples_dir / f"{sample_id}.png")
        sample = {
            "sample_id": sample_id,
            "analysis_id": label_record.get("analysis_id"),
            "bbox_id": label_record.get("bbox_id"),
            "iq_path": str(iq_target.relative_to(buffer_dir)) if iq_target else None,
            "region_image_path": str(image_target.relative_to(buffer_dir)) if image_target else None,
            "label": label_record.get("label"),
            "legacy_label": label_record.get("legacy_label"),
            "corrected_label": label_record.get("label") if label_record.get("label_source") == "operator_correction" else None,
            "label_source": label_record.get("label_source"),
            "label_strength": label_record.get("label_strength"),
            "legacy_confidence": label_record.get("legacy_confidence"),
            "training_weight": float(label_record.get("training_weight", 1.0)),
            "review_status": label_record.get("review_status"),
            "center_frequency_hz": (float(region.get("freq_start_hz", 0.0)) + float(region.get("freq_end_hz", 0.0))) / 2.0,
            "occupied_bandwidth_hz": float(region.get("freq_end_hz", 0.0)) - float(region.get("freq_start_hz", 0.0)),
            "snr_db": region.get("features", {}).get("spectral", {}).get("snr_db"),
            "sample_rate_hz": None,
            "gain_db": None,
            "session_id": label_record.get("session_id"),
            "capture_id": label_record.get("capture_id"),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        manifest = self._read_buffer_manifest(buffer_dir)
        manifest = [item for item in manifest if item.get("sample_id") != sample_id]
        manifest.append(sample)
        self.repository.write_json(buffer_dir, "manifest.json", manifest)
        return sample

    def _read_buffer_manifest(self, buffer_dir: Path) -> list[dict[str, Any]]:
        manifest_path = buffer_dir / "manifest.json"
        if not manifest_path.exists():
            return []
        with manifest_path.open("r", encoding="utf-8") as file:
            return json.load(file)

    def _next_sample_id(self, buffer_dir: Path) -> str:
        manifest = self._read_buffer_manifest(buffer_dir)
        return f"rsu_sample_{len(manifest) + 1:06d}"

    def _append_buffer_index(self, filename: str, sample: dict[str, Any]) -> None:
        buffer_dir = self.storage_root / "learning_buffer"
        path = buffer_dir / filename
        items: list[dict[str, Any]] = []
        if path.exists():
            with path.open("r", encoding="utf-8") as file:
                items = json.load(file)
        items.append(sample)
        self.repository.write_json(buffer_dir, filename, items)

    def _legacy_label_to_signal_label(self, legacy_label: str, legacy_family: str | None = None) -> str:
        text = f"{legacy_label} {legacy_family or ''}".lower()
        if any(term in text for term in ["fm", "wfm", "broadcast"]):
            return "fm_broadcast_like"
        if any(term in text for term in ["ook", "ask", "remote", "ism"]):
            return "ook_like"
        if "fsk" in text or "gfsk" in text:
            return "fsk_like"
        if any(term in text for term in ["ofdm", "wifi", "lte", "5g", "nr"]):
            return "ofdm_like"
        return "unknown"

    def _load_model_version(self, model_id: str) -> dict[str, Any]:
        version_path = self.storage_root / "learning_buffer" / "model_versions" / model_id / "model.npz"
        return self._load_softmax_model(version_path)

    def _evaluate_model_on_records(self, model: dict[str, Any], records: list[dict[str, Any]], dataset_dir: Path) -> dict[str, Any]:
        labels = list(model["labels"])
        usable = [record for record in records if record["label"] in labels]
        if not usable:
            raise ValueError("No records match the labels for the selected model.")
        x = np.asarray([self._iq_feature_vector(self._record_path(record["iq_path"], dataset_dir), int(model["feature_bins"])) for record in usable], dtype=np.float32)
        y = np.asarray([labels.index(record["label"]) for record in usable], dtype=np.int64)
        return self._evaluate_softmax(model, x, y, labels)

    def _legacy_agreement_from_records(self, records: list[dict[str, Any]]) -> dict[str, Any]:
        comparable = [record for record in records if record.get("legacy_label")]
        if not comparable:
            return {"agreement_with_legacy": None, "legacy_disagreement_cases": []}
        disagreements = [record for record in comparable if self._legacy_label_to_signal_label(str(record.get("legacy_label")), None) != record.get("label")]
        return {
            "agreement_with_legacy": 1.0 - (len(disagreements) / max(len(comparable), 1)),
            "legacy_disagreement_cases": disagreements[:50],
        }

    def _all_analysis_ids(self) -> list[str]:
        analyses_dir = self.storage_root / "analyses"
        if not analyses_dir.exists():
            return []
        return sorted(path.name for path in analyses_dir.iterdir() if path.is_dir())

    def _capture_registry_dir(self) -> Path:
        path = self.storage_root / "capture_registry"
        (path / "captures").mkdir(parents=True, exist_ok=True)
        (path / "datasets").mkdir(parents=True, exist_ok=True)
        (path / "learning_buffer").mkdir(parents=True, exist_ok=True)
        (path / "model_versions").mkdir(parents=True, exist_ok=True)
        return path

    def _capture_registry_path(self) -> Path:
        return self._capture_registry_dir() / "captures.json"

    def _read_capture_registry(self) -> list[dict[str, Any]]:
        path = self._capture_registry_path()
        if not path.exists():
            return []
        with path.open("r", encoding="utf-8") as file:
            return json.load(file)

    def _write_capture_registry(self, captures: list[dict[str, Any]]) -> None:
        registry_dir = self._capture_registry_dir()
        self.repository.write_json(registry_dir, "captures.json", captures)

    def _upsert_capture(self, capture: dict[str, Any]) -> None:
        captures = [item for item in self._read_capture_registry() if item.get("capture_id") != capture.get("capture_id")]
        captures.append(capture)
        self._write_capture_registry(captures)

    def _get_registered_capture(self, capture_id: str) -> dict[str, Any]:
        for capture in self._read_capture_registry():
            if capture.get("capture_id") == capture_id:
                return capture
        raise FileNotFoundError(f"Registered RF capture not found: {capture_id}")

    def _legacy_from_analysis_waterfall(self, analysis: dict[str, Any]) -> dict[str, Any]:
        matrix_path = self.repository.analysis_dir(analysis["analysis_id"]) / str(analysis.get("waterfall", {}).get("matrix_path", "waterfall.npy"))
        if not matrix_path.exists():
            return {"method": "band_profile_matching", "label": "unknown", "family": "unknown", "confidence": 0.0, "evidence": ["No waterfall matrix available."]}
        matrix = np.load(matrix_path)
        levels = np.mean(matrix, axis=0).astype(float).tolist()
        center = float(analysis.get("input", {}).get("center_frequency_hz") or 0.0)
        sample_rate = float(analysis.get("input", {}).get("sample_rate_hz") or 0.0)
        freqs = np.linspace(center - sample_rate / 2.0, center + sample_rate / 2.0, len(levels)).astype(float).tolist()
        return self._legacy_result_from_frame(
            {
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                "center_frequency_hz": center,
                "span_hz": sample_rate,
                "sample_rate_hz": sample_rate,
                "frequencies_hz": freqs,
                "levels_db": levels,
            }
        )

    def _comparison_rows(self, analysis: dict[str, Any], legacy: dict[str, Any]) -> list[dict[str, Any]]:
        legacy_label = self._legacy_label_to_signal_label(str(legacy.get("label", "")), str(legacy.get("family", "")))
        rows = []
        for region in analysis.get("regions", []):
            new_label = str(region.get("final_decision", {}).get("label", "unknown"))
            agreement = "compatible" if legacy_label == new_label and new_label != "unknown" else "different_or_unresolved"
            rows.append(
                {
                    "region": region.get("bbox_id"),
                    "legacy_prediction": legacy.get("label"),
                    "legacy_signal_label": legacy_label,
                    "new_prediction": new_label,
                    "agreement": agreement,
                    "confidence": {
                        "legacy": legacy.get("confidence", 0.0),
                        "new": region.get("final_decision", {}).get("confidence", 0.0),
                    },
                    "suggested_training_label": legacy_label if legacy.get("confidence", 0.0) >= 0.85 and agreement != "compatible" else new_label,
                    "action": "review",
                }
            )
        return rows

    def _load_reviews(self, analysis_dir: Path) -> dict[str, dict[str, Any]]:
        reviews_path = analysis_dir / "region_reviews.json"
        if not reviews_path.exists():
            return {}
        with reviews_path.open("r", encoding="utf-8") as file:
            reviews = json.load(file)
        return {str(item.get("bbox_id")): item for item in reviews}

    def _copy_if_exists(self, source: Any, target: Path) -> Path | None:
        if not source:
            return None
        source_path = Path(str(source))
        if not source_path.exists():
            return None
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, target)
        return target

    def _safe_dataset_name(self, value: str) -> str:
        cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in value.strip())
        return cleaned or "rf_signal_understanding_regions"

    def _live_spectral_features(self, region_matrix: np.ndarray, region: dict[str, Any]) -> dict[str, float]:
        matrix = np.asarray(region_matrix, dtype=np.float32)
        if matrix.size == 0:
            snr_db = 0.0
            entropy = 0.0
            duty = 0.0
        else:
            power = np.maximum(matrix - np.min(matrix), 1e-9)
            probs = power.ravel() / np.sum(power)
            entropy = float(-np.sum(probs * np.log2(probs + 1e-12)) / max(np.log2(probs.size), 1.0))
            snr_db = float(np.percentile(matrix, 95) - np.percentile(matrix, 20))
            duty = float(np.mean(np.max(matrix, axis=1) > np.percentile(matrix, 75))) if matrix.ndim == 2 else 0.0
        return {
            "occupied_bandwidth_hz": float(region.get("occupied_bandwidth_hz", 0.0)),
            "spectral_centroid_hz": float(region.get("center_frequency_hz", 0.0)),
            "spectral_spread_hz": float(region.get("occupied_bandwidth_hz", 0.0)) / 2.0,
            "spectral_entropy": entropy,
            "spectral_kurtosis": 0.0,
            "peak_count": 0.0,
            "burst_duration_s": max(float(region.get("time_end_s", 0.0)) - float(region.get("time_start_s", 0.0)), 0.0),
            "duty_cycle": duty,
            "frequency_drift_hz": 0.0,
            "time_occupancy_ratio": duty,
            "snr_db": snr_db,
        }

    def _empty_live_result(self, raw_frame: dict[str, Any], reason: str) -> dict[str, Any]:
        result = {
            "analysis_id": self.repository.new_analysis_id("rsu_live"),
            "mode": "live",
            "source": raw_frame.get("source", "real_sdr"),
            "timestamp_utc": raw_frame.get("timestamp_utc"),
            "input": {
                "center_frequency_hz": raw_frame.get("center_frequency_hz"),
                "sample_rate_hz": raw_frame.get("sample_rate_hz"),
                "span_hz": raw_frame.get("span_hz"),
                "format": "live_psd_waterfall",
            },
            "waterfall": {"rows": 0, "freq_bins": 0, "image_path": None, "note": reason},
            "regions": [],
            "summary": {"region_count": 0, "labels": {}, "warning": reason},
            "scientific_traceability": self.traceability.for_steps(["waterfall_generation", "region_detection"]),
        }
        self._cache_live_result(result)
        return result

    def _cache_live_result(self, result: dict[str, Any]) -> None:
        analysis_id = str(result.get("analysis_id") or "")
        if not analysis_id:
            return
        self._live_result_cache[analysis_id] = result
        if len(self._live_result_cache) > 25:
            oldest_key = next(iter(self._live_result_cache))
            self._live_result_cache.pop(oldest_key, None)
