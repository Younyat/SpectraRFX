from __future__ import annotations

import time
import json
import importlib.util
from pathlib import Path
from typing import Any

import numpy as np

from app.modules.rf_experiment_lab.benchmark_report import BenchmarkReportBuilder
from app.modules.rf_experiment_lab.dataset_adapter import DatasetAdapter
from app.modules.rf_experiment_lab.e1_raw_iq_cnn1d import E1RawIQCNN1DService
from app.modules.rf_experiment_lab.e3_spectrogram_cnn2d import E3SpectrogramCNN2DService
from app.modules.rf_experiment_lab.e5_spectral_baseline import E5SpectralBaselineService
from app.modules.rf_experiment_lab.experiment_config_schema import (
    DEFAULT_METRICS,
    OPEN_SET_METRICS,
    REGION_DETECTION_METRICS,
    ExperimentConfig,
)
from app.modules.rf_experiment_lab.experiment_registry import ExperimentRegistry
from app.modules.rf_experiment_lab.experiment_result_store import ExperimentResultStore
from app.modules.rf_experiment_lab.hdf5_experiment_exporter import HDF5ExperimentExporter
from app.modules.rf_experiment_lab.inference_service import RFExperimentInferenceService
from app.modules.rf_experiment_lab.metrics_service import MetricsService
from app.modules.rf_experiment_lab.model_registry_adapter import ModelRegistryAdapter
from app.modules.rf_experiment_lab.region_detection.learned_detector_interface import OptionalLearnedDetectorStub
from app.modules.rf_experiment_lab.region_detection.morphological_adapter import MorphologicalHeuristicAdapter
from app.modules.rf_experiment_lab.representation_extraction_service import RepresentationExtractionService
from app.modules.rf_experiment_lab.report_builder import ForensicReportBuilder
from app.modules.rf_experiment_lab.sigmf_exporter import SigMFExporter
from app.modules.rf_experiment_lab.split_manager import SplitManager


class RFExperimentLabService:
    def __init__(self, storage_root: Path, mlops_service: Any | None = None) -> None:
        self.registry = ExperimentRegistry()
        self.dataset_adapter = DatasetAdapter(storage_root)
        self.result_store = ExperimentResultStore(storage_root)
        self.split_manager = SplitManager()
        self.metrics = MetricsService()
        self.model_registry = ModelRegistryAdapter(mlops_service)
        self.report_builder = ForensicReportBuilder()
        self.benchmark_report_builder = BenchmarkReportBuilder(self.result_store)
        self.inference_service = RFExperimentInferenceService(storage_root, self.result_store)
        self.sigmf_exporter = SigMFExporter()
        self.hdf5_exporter = HDF5ExperimentExporter()
        self.representation_service = RepresentationExtractionService()
        self.e5_service = E5SpectralBaselineService(
            self.representation_service,
            self.dataset_adapter,
            self.split_manager,
            self.result_store,
        )
        self.e1_service = E1RawIQCNN1DService(
            self.representation_service,
            self.dataset_adapter,
            self.split_manager,
            self.result_store,
        )
        self.e3_service = E3SpectrogramCNN2DService(
            self.representation_service,
            self.dataset_adapter,
            self.split_manager,
            self.result_store,
        )
        self.morphological_detector = MorphologicalHeuristicAdapter()
        self.learned_detectors = {
            "ssd_waterfall": OptionalLearnedDetectorStub("ssd_waterfall"),
            "faster_rcnn_waterfall": OptionalLearnedDetectorStub("faster_rcnn_waterfall"),
            "yolo_waterfall": OptionalLearnedDetectorStub("yolo_waterfall"),
            "learned_detector": OptionalLearnedDetectorStub("learned_detector"),
        }

    def health(self) -> dict[str, Any]:
        optional = ["h5py", "torch", "sklearn"]
        optional_missing = [name for name in optional if importlib.util.find_spec(name) is None]
        required = ["numpy", "scipy", "pydantic"]
        required_available = {name: importlib.util.find_spec(name) is not None for name in required}
        learned = {name: detector.status() for name, detector in self.learned_detectors.items()}
        return {
            "module_loaded": True,
            "dependencies_available": required_available,
            "optional_dependencies_missing": optional_missing,
            "morphological_detector_available": self.morphological_detector.status(),
            "learned_detectors_available": learned,
            "future_modules": {
                "ssd": "not_implemented",
                "faster_rcnn": "not_implemented",
                "yolo": "not_implemented",
                "cnn1d": "not_implemented",
                "cnn2d": "implemented_simple_cnn2d_baseline",
                "transformer": "not_implemented",
                "metric_learning": "not_implemented",
                "bispectrum": "not_implemented",
                "csp": "not_implemented",
            },
            "dataset_adapter_available": True,
            "default_region_detector": "morphological_heuristic",
            "message": "RF Experiment Lab is loaded as an optional layer. Learned detectors are disabled until implemented and trained.",
        }

    def overview(self) -> dict[str, Any]:
        return {
            **self.registry.overview(),
            "dataset": self.dataset_adapter.dataset_summary(),
            "model_registry": {
                "current_models": self.model_registry.list_current_models(),
                "integration_policy": self.model_registry.describe_integration_policy(),
            },
        }

    def supported_dataset_sources(self) -> dict[str, Any]:
        return self.dataset_adapter.supported_dataset_sources()

    def rf_experiment_dataset_v1_preview(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.dataset_adapter.rf_experiment_dataset_v1_preview(payload)

    def rf_experiment_dataset_v1_export(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.dataset_adapter.rf_experiment_dataset_v1_export(payload)

    def external_dataset_import_preview(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.dataset_adapter.external_dataset_import_preview(payload)

    def external_dataset_import_export(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.dataset_adapter.external_dataset_import_export(payload)

    def internal_dataset_samples(self) -> list[dict[str, Any]]:
        return self.dataset_adapter.internal_dataset_lab.list_samples()

    def create_internal_dataset_sample(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.dataset_adapter.internal_dataset_lab.create_sample(payload)

    def review_internal_dataset_sample(self, sample_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self.dataset_adapter.internal_dataset_lab.review_sample(sample_id, payload)

    def predict(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.inference_service.predict(payload)

    def compare_models_on_region(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.inference_service.compare_on_region(payload)

    def model_registry_list(self) -> list[dict[str, Any]]:
        from app.modules.rf_experiment_lab.live_inference_adapter import LiveInferenceAdapter
        return LiveInferenceAdapter().model_registry(self.result_store.results_dir)

    def run_live_inference(self, payload: dict[str, Any]) -> dict[str, Any]:
        from app.modules.rf_experiment_lab.live_inference_adapter import LiveInferenceAdapter, ModelReadinessGate

        model_id = str(payload.get("model_id", ""))
        live_context = payload.get("live_context") or {}
        if ":" not in model_id:
            raise ValueError(f"Invalid model_id format (expected experiment_type:run_id): {model_id!r}")
        exp_type, run_id = model_id.split(":", 1)
        result_dir = self.result_store.results_dir / exp_type / run_id
        if not result_dir.exists():
            raise ValueError(f"Model result directory not found for model_id={model_id!r}")

        readiness = ModelReadinessGate.check(result_dir, exp_type)
        if not readiness["live_compatible"]:
            return {
                "model_id": model_id,
                "experiment_type": exp_type,
                "status": "incompatible",
                "compatible": False,
                "ready_for_live_inference": False,
                "rejection_reasons": readiness["rejection_reasons"],
                "predicted_label": None,
                "confidence": None,
                "top_k": [],
            }
        if not readiness["ready_for_live_inference"]:
            return {
                "model_id": model_id,
                "experiment_type": exp_type,
                "status": "not_ready",
                "compatible": True,
                "ready_for_live_inference": False,
                "rejection_reasons": readiness["rejection_reasons"],
                "predicted_label": None,
                "confidence": None,
                "top_k": [],
            }

        freq = live_context.get("frequency_array_hz") or []
        pwr = live_context.get("power_levels_db") or []
        center = float(live_context.get("center_frequency_hz") or 0.0)
        marker_start = live_context.get("marker_start_hz")
        marker_stop = live_context.get("marker_stop_hz")
        if marker_start is not None:
            marker_start = float(marker_start)
        if marker_stop is not None:
            marker_stop = float(marker_stop)

        adapter = LiveInferenceAdapter()
        result = adapter.run_e5_live_inference(
            model_pkl_path=readiness["model_file"],
            label_schema=readiness["label_schema"] or {},
            frequency_array_hz=freq,
            power_levels_db=pwr,
            center_frequency_hz=center,
            marker_start_hz=marker_start,
            marker_stop_hz=marker_stop,
        )
        return {
            "model_id": model_id,
            "experiment_type": exp_type,
            "status": "ok",
            "compatible": True,
            "ready_for_live_inference": True,
            "rejection_reasons": [],
            **result,
        }

    def list_configs(self) -> list[dict[str, Any]]:
        return self.result_store.list_configs()

    def save_config(self, payload: dict[str, Any]) -> dict[str, Any]:
        config = ExperimentConfig.model_validate(payload)
        if not config.metrics:
            config.metrics.extend(self._default_metrics_for(config))
        return self.result_store.save_config(config)

    def get_config(self, experiment_id: str) -> dict[str, Any]:
        return self.result_store.load_config(experiment_id).model_dump()

    def create_template(self, template_id: str) -> dict[str, Any]:
        templates = {
            "morphological_baseline": {
                "experiment_id": "exp_region_morphological_baseline_v1",
                "paper_reference": "Current RF-Fingerprint-Lab-v6 morphological heuristic detector baseline",
                "technique_name": "e0_morphological_baseline",
                "task": "region_detection",
                "stage": "stage_1",
                "input_representation": "waterfall",
                "detector_type": "morphological_heuristic",
                "trainable": False,
                "parameters": {
                    "threshold_mode": "adaptive",
                    "morphology_enabled": True,
                    "min_region_area": 20,
                    "merge_close_regions": True,
                },
                "metrics": REGION_DETECTION_METRICS,
            },
            "raw_iq_cnn1d_wifi": {
                "experiment_id": "exp_iq_cnn1d_wifi_riyaz_v1",
                "paper_reference": "Riyaz et al., Deep Learning Convolutional Neural Networks for Radio Identification; Jian et al.",
                "technique_name": "riyaz_raw_iq_cnn",
                "task": "device_fingerprinting",
                "technology": "wifi",
                "stage": "stage_2",
                "input_representation": "raw_iq",
                "model_type": "cnn1d",
                "dataset_version": "wifi_dataset_v1.0.0",
                "split": {
                    "strategy": "session_disjoint",
                    "train_ratio": 0.70,
                    "validation_ratio": 0.15,
                    "test_ratio": 0.15,
                    "group_by": ["capture_id", "session_id", "day_id"],
                },
                "metrics": DEFAULT_METRICS,
            },
            "open_set_triplet_wifi": {
                "experiment_id": "exp_wifi_triplet_open_set_v1",
                "paper_reference": "Shi et al.; Jian et al.",
                "technique_name": "metric_learning_open_set",
                "task": "open_set_spoofing",
                "technology": "wifi",
                "stage": "open_set_spoofing",
                "input_representation": "raw_iq",
                "model_type": "triplet",
                "split": {"strategy": "device_holdout", "group_by": ["transmitter_id"]},
                "metrics": DEFAULT_METRICS + OPEN_SET_METRICS,
            },
        }
        if template_id not in templates:
            raise ValueError(f"Unknown template: {template_id}")
        return ExperimentConfig.model_validate(templates[template_id]).model_dump()

    def e0_morphological_baseline_preview(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._execute_e0_morphological_baseline(payload, persist=False)

    def e0_morphological_baseline_run(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._execute_e0_morphological_baseline(payload, persist=True)

    def e5_spectral_baseline_preview(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.e5_service.preview(payload)

    def e5_spectral_baseline_run(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.e5_service.run(payload)

    def e1_raw_iq_cnn1d_preview(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.e1_service.preview(payload)

    def e1_raw_iq_cnn1d_run(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.e1_service.run(payload)

    def e3_spectrogram_cnn2d_preview(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.e3_service.preview(payload)

    def e3_spectrogram_cnn2d_run(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.e3_service.run(payload)

    def run_experiment(self, experiment_id: str, dry_run: bool = True) -> dict[str, Any]:
        config = self.result_store.load_config(experiment_id)
        captures = self.dataset_adapter.list_existing_captures()
        if config.task == "device_fingerprinting" and config.technology:
            captures = [item for item in captures if str(item.get("technology", "")).lower() == config.technology.lower()]
        split = self.split_manager.build_split(captures, config.split)
        result_dir = self.result_store.create_result_folder(config)
        metrics: dict[str, Any]
        detections = None
        if config.task == "region_detection" and config.detector_type in MorphologicalHeuristicAdapter.aliases:
            detections, metrics = self._run_morphological_baseline(config)
        else:
            metrics = {
                **self.metrics.empty_classification_metrics(),
                "training_time": None,
                "inference_time": None,
                "model_size": None,
                "status": "dry_run_contract_created" if dry_run else "training_backend_not_installed",
                "note": "Experiment folder and strict split were created without modifying operational RF workflows.",
            }
        artifacts = self.result_store.write_experiment_artifacts(result_dir, config, metrics, split, detections)
        return {
            "experiment_id": experiment_id,
            "dry_run": dry_run,
            "config": config.model_dump(),
            "split": split,
            "metrics": metrics,
            "artifacts": artifacts,
        }

    def dry_run_preview(self, payload: dict[str, Any]) -> dict[str, Any]:
        metadata_path = Path(str(payload.get("metadata_path", "")))
        if not metadata_path.exists():
            raise FileNotFoundError(f"metadata_path not found: {metadata_path}")
        metadata = self._load_metadata(metadata_path)
        config_payload = payload.get("experiment_config") or self.create_template(
            str(payload.get("template_id", "morphological_baseline"))
        )
        config = ExperimentConfig.model_validate(config_payload)
        captures = [self._metadata_to_capture_record(metadata, metadata_path)]
        split = self.split_manager.build_split(captures, config.split)
        representation = self._resolve_representation(config.input_representation, metadata)
        detector_preview: dict[str, Any] | None = None
        if config.detector_type in MorphologicalHeuristicAdapter.aliases:
            matrix = np.asarray(payload.get("waterfall_matrix", []), dtype=np.float32)
            if matrix.size == 0:
                matrix = np.empty((0, 0), dtype=np.float32)
            time_axis = payload.get("time_axis_s") or []
            freq_axis = payload.get("freq_axis_hz") or []
            started = time.perf_counter()
            regions = self.morphological_detector.detect(matrix, time_axis, freq_axis, config.parameters)
            detector_preview = {
                "status": "executed",
                "detector_type": "morphological_heuristic",
                "regions": regions,
                "metrics": self.metrics.region_detection_metrics(regions, (time.perf_counter() - started) * 1000.0),
            }
        elif config.detector_type:
            detector_preview = {
                "status": "not_implemented",
                "detector_type": config.detector_type,
                "message": f"{config.detector_type} is disabled until implemented and trained.",
            }
        return {
            "preview_only": True,
            "training_started": False,
            "metadata": {
                "path": str(metadata_path),
                "capture_id": captures[0].get("capture_id"),
                "validation": self.dataset_adapter.validate_required_metadata(captures[0]),
            },
            "config": config.model_dump(),
            "representation": representation,
            "split": split,
            "detector_preview": detector_preview,
        }

    def detect_regions(
        self,
        waterfall_matrix: list[list[float]],
        time_axis_s: list[float],
        freq_axis_hz: list[float],
        mode: str = "morphological_heuristic",
        parameters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        matrix = np.asarray(waterfall_matrix, dtype=np.float32)
        started = time.perf_counter()
        if mode in MorphologicalHeuristicAdapter.aliases:
            regions = self.morphological_detector.detect(matrix, time_axis_s, freq_axis_hz, parameters)
        elif mode == "hybrid":
            regions = self.morphological_detector.detect(matrix, time_axis_s, freq_axis_hz, parameters)
            for detector in self.learned_detectors.values():
                try:
                    regions.extend(detector.detect(matrix, time_axis_s, freq_axis_hz, parameters))
                except NotImplementedError:
                    continue
        elif mode in self.learned_detectors:
            return {
                "region_detection_mode": mode,
                "status": "not_implemented",
                "fallback_available": True,
                "regions": [],
                "metrics": self.metrics.region_detection_metrics([], 0.0),
                "message": f"{mode} is disabled until implemented and trained. Use morphological_heuristic for the default baseline.",
            }
        else:
            raise ValueError(f"Unsupported region detector mode: {mode}")
        latency_ms = (time.perf_counter() - started) * 1000.0
        return {
            "region_detection_mode": mode,
            "status": "ok",
            "fallback_available": True,
            "regions": regions,
            "metrics": self.metrics.region_detection_metrics(regions, latency_ms),
        }

    def list_results(self) -> list[dict[str, Any]]:
        return self.result_store.list_results()

    def list_experiments(self) -> list[dict[str, Any]]:
        return self.result_store.list_results()

    def get_experiment_detail(self, experiment_id: str) -> dict[str, Any]:
        return self.result_store.get_experiment_detail(experiment_id)

    def compare_experiments(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.result_store.compare_experiments(
            payload.get("experiment_ids") or [],
            payload.get("metric", "macro_f1"),
        )

    def benchmark_report(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.benchmark_report_builder.build(payload)

    def build_forensic_report(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.report_builder.build_report(
            case_id=str(payload.get("case_id", "rf_case_unassigned")),
            evidence_id=str(payload.get("evidence_id", payload.get("capture_id", "rf_capture_unassigned"))),
            raw_iq_path=payload.get("raw_iq_path"),
            metadata_path=payload.get("metadata_path"),
            detector_mode=str(payload.get("detector_mode", "morphological_heuristic")),
            stage_1_result=payload.get("stage_1_result")
            or {
                "stage_1_model": "current_rf_intelligence_v1",
                "region_detection_mode": payload.get("detector_mode", "morphological_heuristic"),
                "paper_reference": "Current RF-Fingerprint-Lab-v6 baseline",
            },
            stage_2_result=payload.get("stage_2_result"),
        )

    def export_sigmf(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.sigmf_export(payload)

    def sigmf_preview(self, payload: dict[str, Any]) -> dict[str, Any]:
        iq_path = payload.get("iq_path") or payload.get("cfile_path")
        if not iq_path:
            raise ValueError("iq_path or cfile_path is required")
        return self.sigmf_exporter.preview(
            iq_path=str(iq_path),
            metadata_path=str(payload["metadata_path"]),
            output_dir=payload.get("output_dir") or str(self.result_store.root / "exports" / "sigmf"),
        )

    def sigmf_export(self, payload: dict[str, Any]) -> dict[str, Any]:
        iq_path = payload.get("iq_path") or payload.get("cfile_path")
        if not iq_path:
            raise ValueError("iq_path or cfile_path is required")
        return self.sigmf_exporter.export(
            iq_path=str(iq_path),
            metadata_path=str(payload["metadata_path"]),
            output_dir=payload.get("output_dir") or str(self.result_store.root / "exports" / "sigmf"),
        )

    def export_hdf5_manifest(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.hdf5_manifest_export(payload)

    def hdf5_manifest_preview(self, payload: dict[str, Any]) -> dict[str, Any]:
        captures = self.dataset_adapter.list_existing_captures()
        return self.hdf5_exporter.preview_manifest(payload, captures)

    def hdf5_manifest_export(self, payload: dict[str, Any]) -> dict[str, Any]:
        captures = self.dataset_adapter.list_existing_captures()
        return self.hdf5_exporter.export_manifest_json(
            output_path=payload.get("output_path") or str(self.result_store.root / "exports" / "hdf5_manifest.json"),
            payload=payload,
            records=captures,
        )

    def dataset_version_preview(self, payload: dict[str, Any]) -> dict[str, Any]:
        captures = self.dataset_adapter.list_existing_captures()
        return self.hdf5_exporter.dataset_version_object(payload, captures)

    def representation_preview(self, representation_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._representation_action(representation_type, payload, preview=True)

    def representation_export(self, representation_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._representation_action(representation_type, payload, preview=False)

    def representation_manifest_export(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.representation_service.manifest_export(payload)

    def _representation_action(self, representation_type: str, payload: dict[str, Any], preview: bool) -> dict[str, Any]:
        methods = {
            ("raw_iq", True): self.representation_service.raw_iq_preview,
            ("raw_iq", False): self.representation_service.raw_iq_export,
            ("fft_psd", True): self.representation_service.fft_psd_preview,
            ("fft_psd", False): self.representation_service.fft_psd_export,
            ("spectrogram", True): self.representation_service.spectrogram_preview,
            ("spectrogram", False): self.representation_service.spectrogram_export,
            ("waterfall", True): self.representation_service.waterfall_preview,
            ("waterfall", False): self.representation_service.waterfall_export,
        }
        key = (representation_type, preview)
        if key not in methods:
            raise ValueError(f"Unsupported representation action: {representation_type}")
        return methods[key](payload)

    def _run_morphological_baseline(self, config: ExperimentConfig) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        rows = int(config.parameters.get("synthetic_rows", 64))
        cols = int(config.parameters.get("synthetic_cols", 128))
        matrix = np.zeros((rows, cols), dtype=np.float32)
        matrix[rows // 3 : rows // 2, cols // 4 : cols // 2] = 1.0
        time_axis = np.linspace(0.0, 1.0, rows).tolist()
        freq_axis = np.linspace(-1.0, 1.0, cols).tolist()
        started = time.perf_counter()
        detections = self.morphological_detector.detect(matrix, time_axis, freq_axis, config.parameters)
        latency_ms = (time.perf_counter() - started) * 1000.0
        return detections, self.metrics.region_detection_metrics(detections, latency_ms)

    def _execute_e0_morphological_baseline(self, payload: dict[str, Any], persist: bool) -> dict[str, Any]:
        metadata_path = Path(str(payload.get("metadata_path", "")))
        if not metadata_path.exists():
            raise FileNotFoundError(f"metadata_path not found: {metadata_path}")
        metadata = self._load_metadata(metadata_path)
        config_payload = payload.get("experiment_config") or self.create_template("morphological_baseline")
        config = ExperimentConfig.model_validate(config_payload)
        if config.detector_type not in MorphologicalHeuristicAdapter.aliases:
            raise ValueError("E0 must use detector_type=morphological_heuristic")
        if config.trainable:
            raise ValueError("E0 is a non-trainable morphological baseline experiment")
        if config.dataset_version == "unversioned" and metadata.get("dataset_version"):
            config.dataset_version = str(metadata.get("dataset_version"))

        runtime_log: list[dict[str, Any]] = []
        step_started = time.perf_counter()
        matrix, time_axis, freq_axis, representation = self._resolve_e0_time_frequency_data(payload, metadata, metadata_path)
        runtime_log.append(
            {
                "step": "resolve_representation",
                "status": "ok",
                "message": representation["message"],
                "latency_ms": (time.perf_counter() - step_started) * 1000.0,
            }
        )

        started = time.perf_counter()
        raw_regions = self.morphological_detector.detect(matrix, time_axis, freq_axis, config.parameters)
        latency_ms = (time.perf_counter() - started) * 1000.0
        runtime_log.append(
            {
                "step": "morphological_heuristic_detection",
                "status": "ok",
                "message": f"Detected {len(raw_regions)} regions",
                "latency_ms": latency_ms,
            }
        )

        detections = self._normalize_e0_detections(raw_regions, matrix)
        annotations = payload.get("annotations") if isinstance(payload.get("annotations"), list) else []
        metrics = self._e0_metrics(detections, annotations, latency_ms)
        capture_record = self._metadata_to_capture_record(metadata, metadata_path)
        split = self.split_manager.build_split([capture_record], config.split)
        result_package = None
        if persist:
            result_dir = self.result_store.create_result_folder(config)
            result_package = self.result_store.write_e0_artifacts(
                result_dir=result_dir,
                config=config,
                detections=detections,
                metrics=metrics,
                runtime_log=runtime_log,
                source_capture_metadata=metadata,
            )

        return {
            "experiment_id": config.experiment_id,
            "experiment_family": "E0",
            "preview_only": not persist,
            "training_started": False,
            "detector_type": "morphological_heuristic",
            "paper_reference": "Current RF-Fingerprint-Lab-v6 morphological heuristic detector baseline",
            "source": {
                "metadata_path": str(metadata_path),
                "capture_id": capture_record.get("capture_id"),
                "representation": representation,
            },
            "config": config.model_dump(),
            "split": split,
            "detections": detections,
            "metrics": metrics,
            "runtime_log": runtime_log,
            "result_package": result_package,
        }

    def _default_metrics_for(self, config: ExperimentConfig) -> list[str]:
        if config.task == "region_detection":
            return REGION_DETECTION_METRICS
        if config.task == "open_set_spoofing":
            return DEFAULT_METRICS + OPEN_SET_METRICS
        return DEFAULT_METRICS

    def _load_metadata(self, path: Path) -> dict[str, Any]:
        try:
            value = json.loads(path.read_text(encoding="utf-8-sig"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid metadata JSON: {path}") from exc
        if not isinstance(value, dict):
            raise ValueError("metadata JSON must contain an object")
        return value

    def _metadata_to_capture_record(self, metadata: dict[str, Any], metadata_path: Path) -> dict[str, Any]:
        config = metadata.get("capture_config", {}) if isinstance(metadata.get("capture_config"), dict) else {}
        scenario = metadata.get("scenario", {}) if isinstance(metadata.get("scenario"), dict) else {}
        transmitter = metadata.get("transmitter", {}) if isinstance(metadata.get("transmitter"), dict) else {}
        return {
            "capture_id": metadata.get("capture_id") or metadata_path.stem,
            "raw_file": metadata.get("raw_file") or config.get("output_path"),
            "metadata_file": str(metadata_path),
            "datatype": metadata.get("datatype") or config.get("sample_dtype", "complex64"),
            "sample_rate_hz": metadata.get("sample_rate_hz") or config.get("sample_rate_hz"),
            "center_frequency_hz": metadata.get("center_frequency_hz") or config.get("center_frequency_hz"),
            "duration_seconds": metadata.get("duration_seconds") or config.get("capture_duration_s"),
            "receiver_id": metadata.get("receiver_id") or config.get("sdr_serial") or config.get("sdr_model"),
            "timestamp_utc": metadata.get("timestamp_utc") or scenario.get("timestamp_utc"),
            "session_id": metadata.get("session_id"),
            "technology": metadata.get("technology") or transmitter.get("family") or transmitter.get("transmitter_class"),
            "transmitter_id": metadata.get("transmitter_id") or transmitter.get("transmitter_id"),
            "dataset_split": metadata.get("dataset_split"),
        }

    def _resolve_representation(self, representation: str, metadata: dict[str, Any]) -> dict[str, Any]:
        implemented = {"raw_iq": "metadata_resolved", "waterfall": "requires_matrix_input", "spectrogram": "requires_iq_processing"}
        if representation in implemented:
            return {
                "id": representation,
                "status": implemented[representation],
                "available": representation in {"raw_iq", "waterfall"},
                "raw_file": metadata.get("raw_file")
                or (metadata.get("capture_config", {}) if isinstance(metadata.get("capture_config"), dict) else {}).get("output_path"),
            }
        return {
            "id": representation,
            "status": "not_implemented",
            "available": False,
            "message": f"{representation} representation is registered but not implemented in the validation layer.",
        }

    def _resolve_e0_time_frequency_data(
        self,
        payload: dict[str, Any],
        metadata: dict[str, Any],
        metadata_path: Path,
    ) -> tuple[np.ndarray, list[float], list[float], dict[str, Any]]:
        if payload.get("waterfall_matrix") is not None:
            matrix = np.asarray(payload.get("waterfall_matrix"), dtype=np.float32)
            source = "request.waterfall_matrix"
        else:
            matrix_path = self._find_matrix_path(payload, metadata, metadata_path)
            if matrix_path is None:
                raise ValueError("E0 requires existing waterfall/spectrogram matrix data or a metadata path to a .npy matrix")
            matrix = np.asarray(np.load(matrix_path), dtype=np.float32)
            source = str(matrix_path)
        if matrix.ndim != 2:
            raise ValueError("E0 waterfall/spectrogram matrix must be two-dimensional")
        time_axis = self._axis_from_payload_or_metadata(payload, metadata, "time_axis_s", matrix.shape[0], 0.0, self._duration_from_metadata(metadata))
        freq_axis = self._axis_from_payload_or_metadata(
            payload,
            metadata,
            "freq_axis_hz",
            matrix.shape[1],
            self._freq_start_from_metadata(metadata),
            self._freq_stop_from_metadata(metadata),
        )
        return matrix, time_axis, freq_axis, {
            "id": "waterfall",
            "available": True,
            "source": source,
            "shape": list(matrix.shape),
            "message": "Resolved existing waterfall/spectrogram matrix for E0 morphological baseline.",
        }

    def _find_matrix_path(self, payload: dict[str, Any], metadata: dict[str, Any], metadata_path: Path) -> Path | None:
        candidates: list[Any] = [
            payload.get("waterfall_matrix_path"),
            payload.get("spectrogram_matrix_path"),
            metadata.get("waterfall_matrix_path"),
            metadata.get("spectrogram_matrix_path"),
        ]
        waterfall = metadata.get("waterfall") if isinstance(metadata.get("waterfall"), dict) else {}
        spectrogram = metadata.get("spectrogram") if isinstance(metadata.get("spectrogram"), dict) else {}
        candidates.extend([waterfall.get("matrix_path"), waterfall.get("waterfall_matrix_path"), spectrogram.get("matrix_path")])
        for candidate in candidates:
            if not candidate:
                continue
            path = Path(str(candidate))
            if not path.is_absolute():
                path = metadata_path.parent / path
            if path.exists() and path.suffix.lower() == ".npy":
                return path
        return None

    def _axis_from_payload_or_metadata(
        self,
        payload: dict[str, Any],
        metadata: dict[str, Any],
        key: str,
        length: int,
        start: float,
        stop: float,
    ) -> list[float]:
        values = payload.get(key) or metadata.get(key)
        if isinstance(values, list) and len(values) == length:
            return [float(item) for item in values]
        if length <= 0:
            return []
        if length == 1:
            return [float(start)]
        return np.linspace(float(start), float(stop), length).tolist()

    def _duration_from_metadata(self, metadata: dict[str, Any]) -> float:
        config = metadata.get("capture_config", {}) if isinstance(metadata.get("capture_config"), dict) else {}
        return float(metadata.get("duration_seconds") or config.get("capture_duration_s") or 0.0)

    def _freq_start_from_metadata(self, metadata: dict[str, Any]) -> float:
        config = metadata.get("capture_config", {}) if isinstance(metadata.get("capture_config"), dict) else {}
        explicit = metadata.get("start_frequency_hz") or config.get("start_frequency_hz")
        if explicit is not None:
            return float(explicit)
        center = float(metadata.get("center_frequency_hz") or config.get("center_frequency_hz") or 0.0)
        sample_rate = float(metadata.get("sample_rate_hz") or config.get("sample_rate_hz") or 0.0)
        return center - sample_rate / 2.0

    def _freq_stop_from_metadata(self, metadata: dict[str, Any]) -> float:
        config = metadata.get("capture_config", {}) if isinstance(metadata.get("capture_config"), dict) else {}
        explicit = metadata.get("stop_frequency_hz") or config.get("stop_frequency_hz")
        if explicit is not None:
            return float(explicit)
        center = float(metadata.get("center_frequency_hz") or config.get("center_frequency_hz") or 0.0)
        sample_rate = float(metadata.get("sample_rate_hz") or config.get("sample_rate_hz") or 0.0)
        return center + sample_rate / 2.0

    def _normalize_e0_detections(self, raw_regions: list[dict[str, Any]], matrix: np.ndarray) -> list[dict[str, Any]]:
        detections: list[dict[str, Any]] = []
        for index, region in enumerate(raw_regions, start=1):
            bounds = region.get("pixel_bounds", {}) if isinstance(region.get("pixel_bounds"), dict) else {}
            t0 = int(bounds.get("time_start", 0))
            t1 = int(bounds.get("time_end", -1))
            f0 = int(bounds.get("freq_start", 0))
            f1 = int(bounds.get("freq_end", -1))
            submatrix = matrix[max(t0, 0) : min(t1 + 1, matrix.shape[0]), max(f0, 0) : min(f1 + 1, matrix.shape[1])]
            area = int(max(t1 - t0 + 1, 0) * max(f1 - f0 + 1, 0))
            time_start = float(region.get("time_start_s") or 0.0)
            time_end = float(region.get("time_end_s") or time_start)
            frequency_start = float(region.get("freq_start_hz") or 0.0)
            frequency_end = float(region.get("freq_end_hz") or frequency_start)
            detections.append(
                {
                    "region_id": region.get("bbox_id") or f"region_{index:03d}",
                    "time_start": time_start,
                    "time_end": time_end,
                    "frequency_start_hz": frequency_start,
                    "frequency_end_hz": frequency_end,
                    "bandwidth_hz": max(frequency_end - frequency_start, 0.0),
                    "duration_s": max(time_end - time_start, 0.0),
                    "peak_power": float(np.max(submatrix)) if submatrix.size else None,
                    "mean_power": float(np.mean(submatrix)) if submatrix.size else None,
                    "area": area,
                    "confidence_like_score": region.get("confidence"),
                    "detector_type": "morphological_heuristic",
                    "pixel_bounds": bounds,
                }
            )
        return detections

    def _e0_metrics(self, detections: list[dict[str, Any]], annotations: list[dict[str, Any]], latency_ms: float) -> dict[str, Any]:
        metrics: dict[str, Any] = {
            "status": "no_ground_truth_annotations" if not annotations else "ground_truth_annotations_available",
            "detected_region_count": len(detections),
            "latency_ms": latency_ms,
            "mean_region_area": self._mean([item.get("area") for item in detections]),
            "mean_bandwidth_hz": self._mean([item.get("bandwidth_hz") for item in detections]),
            "mean_duration_s": self._mean([item.get("duration_s") for item in detections]),
            "iou": None,
            "precision": None,
            "recall": None,
            "false_positives": None,
            "false_negatives": None,
        }
        if annotations:
            matching = self._match_annotations(detections, annotations)
            metrics.update(matching)
        return metrics

    def _match_annotations(self, detections: list[dict[str, Any]], annotations: list[dict[str, Any]]) -> dict[str, Any]:
        threshold = 0.5
        matched_annotations: set[int] = set()
        true_positive = 0
        ious: list[float] = []
        for detection in detections:
            best_iou = 0.0
            best_index = -1
            for index, annotation in enumerate(annotations):
                if index in matched_annotations:
                    continue
                iou = self._bbox_iou(detection.get("pixel_bounds", {}), annotation.get("pixel_bounds", annotation))
                if iou > best_iou:
                    best_iou = iou
                    best_index = index
            if best_iou >= threshold and best_index >= 0:
                true_positive += 1
                matched_annotations.add(best_index)
                ious.append(best_iou)
        false_positives = len(detections) - true_positive
        false_negatives = len(annotations) - true_positive
        return {
            "iou": self._mean(ious),
            "precision": true_positive / max(true_positive + false_positives, 1),
            "recall": true_positive / max(true_positive + false_negatives, 1),
            "false_positives": false_positives,
            "false_negatives": false_negatives,
        }

    def _bbox_iou(self, left: dict[str, Any], right: dict[str, Any]) -> float:
        lt0 = float(left.get("time_start", 0))
        lt1 = float(left.get("time_end", 0))
        lf0 = float(left.get("freq_start", 0))
        lf1 = float(left.get("freq_end", 0))
        rt0 = float(right.get("time_start", 0))
        rt1 = float(right.get("time_end", 0))
        rf0 = float(right.get("freq_start", 0))
        rf1 = float(right.get("freq_end", 0))
        inter_t = max(min(lt1, rt1) - max(lt0, rt0) + 1.0, 0.0)
        inter_f = max(min(lf1, rf1) - max(lf0, rf0) + 1.0, 0.0)
        intersection = inter_t * inter_f
        left_area = max(lt1 - lt0 + 1.0, 0.0) * max(lf1 - lf0 + 1.0, 0.0)
        right_area = max(rt1 - rt0 + 1.0, 0.0) * max(rf1 - rf0 + 1.0, 0.0)
        union = left_area + right_area - intersection
        return float(intersection / union) if union > 0 else 0.0

    def _mean(self, values: list[Any]) -> float | None:
        clean = [float(value) for value in values if value is not None]
        if not clean:
            return None
        return float(np.mean(np.asarray(clean, dtype=np.float64)))
