from __future__ import annotations

import json
import shutil
import unittest
import hashlib
import csv
from pathlib import Path
from uuid import uuid4

import numpy as np

from app.modules.rf_experiment_lab.experiment_config_schema import ExperimentConfig
from app.modules.rf_experiment_lab.experiment_registry import ExperimentRegistry
from app.modules.rf_experiment_lab.experiment_runner import RFExperimentLabService
from app.modules.rf_experiment_lab.region_detection.morphological_adapter import MorphologicalHeuristicAdapter
from app.modules.rf_experiment_lab.split_manager import SplitManager


class RFExperimentLabIntegrationTest(unittest.TestCase):
    def test_config_schema_rejects_stage_1_device_fingerprinting(self) -> None:
        with self.assertRaises(ValueError):
            ExperimentConfig.model_validate(
                {
                    "experiment_id": "invalid_stage_mix",
                    "paper_reference": "test",
                    "task": "device_fingerprinting",
                    "stage": "stage_1",
                    "technology": "wifi",
                    "input_representation": "raw_iq",
                    "model_type": "cnn1d",
                }
            )

    def test_experiment_registry_lists_morphological_default(self) -> None:
        overview = ExperimentRegistry().overview()
        self.assertEqual(overview["default_region_detector"], "morphological_heuristic")
        self.assertTrue(
            any(item["id"] == "morphological_heuristic" and item["default"] for item in overview["region_detectors"])
        )

    def test_split_manager_prevents_group_leakage(self) -> None:
        captures = [
            {"capture_id": "a", "session_id": "s1"},
            {"capture_id": "b", "session_id": "s1"},
            {"capture_id": "c", "session_id": "s2"},
        ]
        config = ExperimentConfig.model_validate(
            {
                "experiment_id": "split_test",
                "paper_reference": "test",
                "task": "signal_recognition",
                "stage": "stage_1",
                "input_representation": "waterfall",
                "split": {"strategy": "session_disjoint", "group_by": ["session_id"]},
            }
        )
        split = SplitManager().build_split(captures, config.split)
        self.assertTrue(split["leakage_check"]["passed"])

    def test_morphological_detector_adapter_available(self) -> None:
        detector = MorphologicalHeuristicAdapter()
        status = detector.status()
        self.assertTrue(status["available"])
        self.assertTrue(status["fallback"])
        matrix = np.zeros((8, 8), dtype=np.float32)
        regions = detector.detect(matrix, list(range(8)), list(range(8)))
        self.assertIsInstance(regions, list)

    def test_dry_run_response_format_with_metadata(self) -> None:
        workspace_tmp = Path("tmp_rf_tests")
        workspace_tmp.mkdir(parents=True, exist_ok=True)
        tmp_path = workspace_tmp / f"rf_experiment_lab_test_{uuid4().hex}"
        tmp_path.mkdir(parents=True, exist_ok=False)
        try:
            metadata_path = tmp_path / "capture_0001.json"
            metadata_path.write_text(
                json.dumps(
                    {
                        "capture_id": "capture_0001",
                        "session_id": "session_001",
                        "dataset_split": "train",
                        "capture_config": {
                            "output_path": "capture_0001.cfile",
                            "sample_dtype": "complex64",
                            "sample_rate_hz": 20_000_000,
                            "center_frequency_hz": 2_437_000_000,
                            "capture_duration_s": 5.0,
                            "sdr_model": "USRP B200",
                            "sdr_serial": "usrp_b200_rx_01",
                        },
                        "scenario": {"timestamp_utc": "2026-05-01T13:00:00Z"},
                    }
                ),
                encoding="utf-8",
            )
            service = RFExperimentLabService(tmp_path)
            preview = service.dry_run_preview(
                {
                    "metadata_path": str(metadata_path),
                    "template_id": "morphological_baseline",
                    "waterfall_matrix": [[0.0, 0.0], [0.0, 1.0]],
                    "time_axis_s": [0.0, 1.0],
                    "freq_axis_hz": [100.0, 200.0],
                }
            )
            self.assertTrue(preview["preview_only"])
            self.assertFalse(preview["training_started"])
            self.assertEqual(preview["metadata"]["capture_id"], "capture_0001")
            self.assertTrue(preview["split"]["leakage_check"]["passed"])
            self.assertEqual(preview["detector_preview"]["detector_type"], "morphological_heuristic")
        finally:
            shutil.rmtree(tmp_path, ignore_errors=True)

    def test_e0_preview_does_not_start_training(self) -> None:
        tmp_path, metadata_path = self._make_e0_workspace()
        try:
            service = RFExperimentLabService(tmp_path)
            preview = service.e0_morphological_baseline_preview(self._e0_payload(metadata_path))
            self.assertTrue(preview["preview_only"])
            self.assertFalse(preview["training_started"])
            self.assertEqual(preview["experiment_family"], "E0")
            self.assertEqual(preview["detector_type"], "morphological_heuristic")
        finally:
            shutil.rmtree(tmp_path, ignore_errors=True)

    def test_e0_run_returns_stable_json_and_result_package(self) -> None:
        tmp_path, metadata_path = self._make_e0_workspace()
        try:
            service = RFExperimentLabService(tmp_path)
            result = service.e0_morphological_baseline_run(self._e0_payload(metadata_path))
            self.assertFalse(result["preview_only"])
            self.assertFalse(result["training_started"])
            self.assertEqual(result["detector_type"], "morphological_heuristic")
            self.assertIn("detections", result)
            self.assertIn("metrics", result)
            self.assertIn("runtime_log", result)
            package = result["result_package"]
            self.assertIsNotNone(package)
            files = set(package["files"])
            self.assertTrue(
                {
                    "config.yaml",
                    "paper_reference.txt",
                    "detections.json",
                    "metrics.json",
                    "runtime_log.csv",
                    "dataset_version.txt",
                    "source_capture_metadata.json",
                }.issubset(files)
            )
        finally:
            shutil.rmtree(tmp_path, ignore_errors=True)

    def test_e3_torchvision_models_write_package_when_available(self) -> None:
        tmp_path, capture_ids = self._make_e5_dataset()
        try:
            service = RFExperimentLabService(tmp_path)
            if not service.e3_service._torchvision_available({"force_torchvision_unavailable": False}):
                self.skipTest("torchvision unavailable")
            for model_type in ("resnet18", "vgg11"):
                result = service.e3_spectrogram_cnn2d_run(
                    {
                        "capture_ids": capture_ids,
                        "model_type": model_type,
                        "epochs": 1,
                        "batch_size": 4,
                        "window_size_samples": 512,
                        "max_samples": 12,
                        "n_fft": 64,
                        "hop_length": 32,
                        "image_height": 32,
                        "image_width": 32,
                        "split": {"strategy": "capture_disjoint", "group_by": ["capture_id"], "train_ratio": 0.7, "validation_ratio": 0.15, "test_ratio": 0.15},
                    }
                )
                files = set(result["result_package"]["files"])
                self.assertIn("model.pt", files)
                self.assertIn("model_metadata.json", files)
                metadata = json.loads((Path(result["result_package"]["result_dir"]) / "model_metadata.json").read_text(encoding="utf-8"))
                self.assertEqual(metadata["model_type"], model_type)
                self.assertFalse(metadata["pretrained_used"])
        finally:
            shutil.rmtree(tmp_path, ignore_errors=True)

    def test_e0_preserves_morphological_heuristic_detector_type(self) -> None:
        tmp_path, metadata_path = self._make_e0_workspace()
        try:
            service = RFExperimentLabService(tmp_path)
            result = service.e0_morphological_baseline_preview(self._e0_payload(metadata_path))
            self.assertEqual(result["config"]["detector_type"], "morphological_heuristic")
            self.assertTrue(all(item["detector_type"] == "morphological_heuristic" for item in result["detections"]))
        finally:
            shutil.rmtree(tmp_path, ignore_errors=True)

    def test_e0_does_not_require_learned_detector_dependencies(self) -> None:
        tmp_path, metadata_path = self._make_e0_workspace()
        try:
            service = RFExperimentLabService(tmp_path)
            health = service.health()
            self.assertEqual(health["future_modules"]["ssd"], "not_implemented")
            self.assertEqual(health["future_modules"]["yolo"], "not_implemented")
            result = service.e0_morphological_baseline_preview(self._e0_payload(metadata_path))
            self.assertEqual(result["detector_type"], "morphological_heuristic")
        finally:
            shutil.rmtree(tmp_path, ignore_errors=True)

    def test_e0_reports_no_ground_truth_annotations_when_absent(self) -> None:
        tmp_path, metadata_path = self._make_e0_workspace()
        try:
            service = RFExperimentLabService(tmp_path)
            result = service.e0_morphological_baseline_preview(self._e0_payload(metadata_path))
            self.assertEqual(result["metrics"]["status"], "no_ground_truth_annotations")
            self.assertIn("detected_region_count", result["metrics"])
            self.assertIn("latency_ms", result["metrics"])
        finally:
            shutil.rmtree(tmp_path, ignore_errors=True)

    def test_sigmf_preview_does_not_write_files(self) -> None:
        tmp_path, iq_path, metadata_path = self._make_export_workspace()
        try:
            service = RFExperimentLabService(tmp_path)
            output_dir = tmp_path / "sigmf"
            preview = service.sigmf_preview(
                {"iq_path": str(iq_path), "metadata_path": str(metadata_path), "output_dir": str(output_dir)}
            )
            self.assertTrue(preview["preview_only"])
            self.assertFalse(Path(preview["would_write"]["sigmf_data"]).exists())
            self.assertFalse(Path(preview["would_write"]["sigmf_meta"]).exists())
        finally:
            shutil.rmtree(tmp_path, ignore_errors=True)

    def test_sigmf_export_writes_files_and_preserves_original(self) -> None:
        tmp_path, iq_path, metadata_path = self._make_export_workspace()
        try:
            original_hash = self._sha256(iq_path)
            service = RFExperimentLabService(tmp_path)
            result = service.sigmf_export(
                {"iq_path": str(iq_path), "metadata_path": str(metadata_path), "output_dir": str(tmp_path / "sigmf")}
            )
            self.assertTrue(Path(result["sigmf_data"]).exists())
            self.assertTrue(Path(result["sigmf_meta"]).exists())
            self.assertEqual(self._sha256(iq_path), original_hash)
            self.assertEqual(self._sha256(Path(result["sigmf_data"])), original_hash)
        finally:
            shutil.rmtree(tmp_path, ignore_errors=True)

    def test_sigmf_required_metadata_validation_fails_cleanly(self) -> None:
        tmp_path, iq_path, metadata_path = self._make_export_workspace()
        try:
            metadata_path.write_text(json.dumps({"capture_id": "bad"}), encoding="utf-8")
            service = RFExperimentLabService(tmp_path)
            preview = service.sigmf_preview({"iq_path": str(iq_path), "metadata_path": str(metadata_path)})
            self.assertFalse(preview["validation"]["valid"])
            self.assertIn("sample_rate_hz", preview["validation"]["missing"])
            self.assertIn("center_frequency_hz", preview["validation"]["missing"])
        finally:
            shutil.rmtree(tmp_path, ignore_errors=True)

    def test_hdf5_manifest_preview_returns_stable_json(self) -> None:
        tmp_path, iq_path, metadata_path = self._make_export_workspace()
        try:
            service = RFExperimentLabService(tmp_path)
            self._seed_dataset_adapter_capture(service, iq_path, metadata_path)
            preview = service.hdf5_manifest_preview({"dataset_id": "test_dataset", "dataset_version": "v1"})
            self.assertTrue(preview["preview_only"])
            self.assertIn("manifest", preview)
            self.assertEqual(preview["manifest"]["dataset_id"], "test_dataset")
            self.assertIn("raw_iq", [item["id"] for item in preview["manifest"]["representations"]])
        finally:
            shutil.rmtree(tmp_path, ignore_errors=True)

    def test_hdf5_manifest_export_writes_manifest_file(self) -> None:
        tmp_path, iq_path, metadata_path = self._make_export_workspace()
        try:
            service = RFExperimentLabService(tmp_path)
            self._seed_dataset_adapter_capture(service, iq_path, metadata_path)
            output_path = tmp_path / "exports" / "manifest.json"
            result = service.hdf5_manifest_export({"output_path": str(output_path), "dataset_version": "v1"})
            self.assertTrue(output_path.exists())
            self.assertEqual(result["path"], str(output_path))
            written = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(written["generator_version"], "rf_experiment_lab_hdf5_manifest_v1")
        finally:
            shutil.rmtree(tmp_path, ignore_errors=True)

    def test_dataset_version_includes_source_hashes(self) -> None:
        tmp_path, iq_path, metadata_path = self._make_export_workspace()
        try:
            service = RFExperimentLabService(tmp_path)
            self._seed_dataset_adapter_capture(service, iq_path, metadata_path)
            version = service.dataset_version_preview({"dataset_version": "v1"})
            self.assertEqual(version["dataset_version"], "v1")
            self.assertIn("capture_0001", version["source_capture_hashes"])
            self.assertEqual(version["source_capture_hashes"]["capture_0001"]["raw_iq"], self._sha256(iq_path))
        finally:
            shutil.rmtree(tmp_path, ignore_errors=True)

    def test_raw_iq_preview_does_not_write_files(self) -> None:
        tmp_path, iq_path, metadata_path = self._make_export_workspace(sample_count=4096)
        try:
            service = RFExperimentLabService(tmp_path)
            output_dir = tmp_path / "representations"
            preview = service.representation_preview(
                "raw_iq",
                {
                    "metadata_path": str(metadata_path),
                    "iq_path": str(iq_path),
                    "output_dir": str(output_dir),
                    "window_size_samples": 1024,
                    "max_preview_windows": 1,
                },
            )
            self.assertTrue(preview["preview_only"])
            self.assertEqual(preview["representation_type"], "raw_iq")
            self.assertEqual(len(preview["window_plan"]), 1)
            self.assertFalse(output_dir.exists())
        finally:
            shutil.rmtree(tmp_path, ignore_errors=True)

    def test_raw_iq_export_writes_npy_and_json_segments(self) -> None:
        tmp_path, iq_path, metadata_path = self._make_export_workspace(sample_count=4096)
        try:
            service = RFExperimentLabService(tmp_path)
            result = service.representation_export(
                "raw_iq",
                {
                    "metadata_path": str(metadata_path),
                    "iq_path": str(iq_path),
                    "output_dir": str(tmp_path / "representations"),
                    "window_size_samples": 1024,
                    "max_export_windows": 2,
                },
            )
            self.assertFalse(result["preview_only"])
            self.assertEqual(len(result["artifacts"]), 2)
            for artifact in result["artifacts"]:
                self.assertTrue(Path(artifact["data_path"]).exists())
                self.assertTrue(Path(artifact["metadata_path"]).exists())
        finally:
            shutil.rmtree(tmp_path, ignore_errors=True)

    def test_fft_psd_preview_works_on_small_capture(self) -> None:
        tmp_path, iq_path, metadata_path = self._make_export_workspace(sample_count=4096)
        try:
            service = RFExperimentLabService(tmp_path)
            preview = service.representation_preview(
                "fft_psd",
                {"metadata_path": str(metadata_path), "iq_path": str(iq_path), "window_size_samples": 2048, "n_fft": 512},
            )
            summary = preview["summary"]["windows"][0]
            self.assertEqual(preview["representation_type"], "fft_psd")
            self.assertIn("noise_floor_db", summary)
            self.assertIn("occupied_bandwidth_hz", summary)
        finally:
            shutil.rmtree(tmp_path, ignore_errors=True)

    def test_spectrogram_preview_returns_shape_and_parameters(self) -> None:
        tmp_path, iq_path, metadata_path = self._make_export_workspace(sample_count=4096)
        try:
            service = RFExperimentLabService(tmp_path)
            preview = service.representation_preview(
                "spectrogram",
                {
                    "metadata_path": str(metadata_path),
                    "iq_path": str(iq_path),
                    "window_size_samples": 2048,
                    "n_fft": 256,
                    "hop_length": 128,
                    "window_type": "hann",
                },
            )
            summary = preview["summary"]["windows"][0]
            self.assertEqual(preview["representation_parameters"]["n_fft"], 256)
            self.assertIn("shape", summary)
            self.assertEqual(summary["window_type"], "hann")
        finally:
            shutil.rmtree(tmp_path, ignore_errors=True)

    def test_waterfall_preview_returns_shape_and_parameters(self) -> None:
        tmp_path, iq_path, metadata_path = self._make_export_workspace(sample_count=4096)
        try:
            service = RFExperimentLabService(tmp_path)
            preview = service.representation_preview(
                "waterfall",
                {
                    "metadata_path": str(metadata_path),
                    "iq_path": str(iq_path),
                    "window_size_samples": 2048,
                    "n_fft": 256,
                    "hop_length": 128,
                },
            )
            summary = preview["summary"]["windows"][0]
            self.assertEqual(preview["representation_type"], "waterfall")
            self.assertEqual(summary["adapter"], "rf_experiment_lab_stft_waterfall_adapter")
            self.assertIn("shape", summary)
        finally:
            shutil.rmtree(tmp_path, ignore_errors=True)

    def test_representations_manifest_export_includes_artifact_hashes(self) -> None:
        tmp_path, iq_path, metadata_path = self._make_export_workspace(sample_count=4096)
        try:
            service = RFExperimentLabService(tmp_path)
            raw = service.representation_export(
                "raw_iq",
                {
                    "metadata_path": str(metadata_path),
                    "iq_path": str(iq_path),
                    "output_dir": str(tmp_path / "representations"),
                    "window_size_samples": 1024,
                    "max_export_windows": 1,
                },
            )
            manifest = service.representation_manifest_export(
                {
                    "metadata_path": str(metadata_path),
                    "iq_path": str(iq_path),
                    "output_dir": str(tmp_path / "representations"),
                    "dataset_id": "test_dataset",
                    "dataset_version": "v2",
                    "artifact_paths": [raw["artifacts"][0]["data_path"]],
                }
            )
            self.assertTrue(Path(manifest["path"]).exists())
            self.assertIn(raw["artifacts"][0]["data_path"], manifest["manifest"]["artifact_sha256"])
        finally:
            shutil.rmtree(tmp_path, ignore_errors=True)

    def test_preview_uses_window_plan_for_large_file(self) -> None:
        tmp_path, iq_path, metadata_path = self._make_export_workspace(sample_count=100_000)
        try:
            service = RFExperimentLabService(tmp_path)
            preview = service.representation_preview(
                "raw_iq",
                {
                    "metadata_path": str(metadata_path),
                    "iq_path": str(iq_path),
                    "window_size_samples": 1024,
                    "max_preview_windows": 1,
                },
            )
            self.assertEqual(len(preview["window_plan"]), 1)
            self.assertEqual(preview["window_plan"][0]["num_samples"], 1024)
        finally:
            shutil.rmtree(tmp_path, ignore_errors=True)

    def test_e5_preview_does_not_train_and_reports_models(self) -> None:
        tmp_path, capture_ids = self._make_e5_dataset()
        try:
            service = RFExperimentLabService(tmp_path)
            preview = service.e5_spectral_baseline_preview({"capture_ids": capture_ids})
            self.assertTrue(preview["preview_only"])
            self.assertFalse(preview["training_started"])
            self.assertIn("logistic_regression", preview["models"])
            self.assertIn("random_forest", preview["models"])
        finally:
            shutil.rmtree(tmp_path, ignore_errors=True)

    def test_e5_run_fails_cleanly_if_labels_missing(self) -> None:
        tmp_path, capture_ids = self._make_e5_dataset(with_labels=False)
        try:
            service = RFExperimentLabService(tmp_path)
            with self.assertRaises(ValueError):
                service.e5_spectral_baseline_run({"capture_ids": capture_ids})
        finally:
            shutil.rmtree(tmp_path, ignore_errors=True)

    def test_e5_run_fails_cleanly_if_sklearn_missing(self) -> None:
        tmp_path, capture_ids = self._make_e5_dataset()
        try:
            service = RFExperimentLabService(tmp_path)
            with self.assertRaises(RuntimeError):
                service.e5_spectral_baseline_run({"capture_ids": capture_ids, "force_sklearn_unavailable": True})
        finally:
            shutil.rmtree(tmp_path, ignore_errors=True)

    def test_e5_feature_extraction_stable_dimensions(self) -> None:
        tmp_path, capture_ids = self._make_e5_dataset()
        try:
            service = RFExperimentLabService(tmp_path)
            config = service.e5_service._config({"capture_ids": capture_ids})
            captures = service.e5_service._selected_captures(config)
            rows, x, y, ids = service.e5_service._extract_features(captures, config)
            self.assertEqual(x.shape[1], len(service.e5_service.feature_names))
            self.assertEqual(len(rows), len(y))
            self.assertEqual(len(ids), len(rows))
        finally:
            shutil.rmtree(tmp_path, ignore_errors=True)

    def test_e5_split_uses_group_disjoint_behavior(self) -> None:
        tmp_path, capture_ids = self._make_e5_dataset()
        try:
            service = RFExperimentLabService(tmp_path)
            preview = service.e5_spectral_baseline_preview({"capture_ids": capture_ids})
            self.assertTrue(preview["split"]["leakage_check"]["passed"])
        finally:
            shutil.rmtree(tmp_path, ignore_errors=True)

    def test_e5_result_package_written_when_training_succeeds(self) -> None:
        tmp_path, capture_ids = self._make_e5_dataset()
        try:
            service = RFExperimentLabService(tmp_path)
            result = service.e5_spectral_baseline_run(
                {
                    "capture_ids": capture_ids,
                    "models": ["logistic_regression"],
                    "split": {"strategy": "capture_disjoint", "group_by": ["capture_id"], "train_ratio": 0.7, "validation_ratio": 0.15, "test_ratio": 0.15},
                    "window_size_samples": 1024,
                    "n_fft": 256,
                }
            )
            self.assertTrue(result["training_completed"])
            package = result["result_package"]
            files = set(package["files"])
            self.assertTrue(
                {
                    "config.yaml",
                    "paper_reference.txt",
                    "features.json",
                    "features.npy",
                    "model.pkl",
                    "metrics.json",
                    "predictions.csv",
                    "confusion_matrix.csv",
                    "classification_report.json",
                    "split_definition.json",
                    "dataset_version.txt",
                    "runtime_log.csv",
                }.issubset(files)
            )
        finally:
            shutil.rmtree(tmp_path, ignore_errors=True)

    def test_e5_all_model_comparison_produces_metrics_per_model(self) -> None:
        tmp_path, capture_ids = self._make_e5_dataset()
        try:
            service = RFExperimentLabService(tmp_path)
            result = service.e5_spectral_baseline_run(
                {
                    "capture_ids": capture_ids,
                    "models": ["logistic_regression", "random_forest", "svm_rbf", "knn"],
                    "split": {"strategy": "capture_disjoint", "group_by": ["capture_id"], "train_ratio": 0.7, "validation_ratio": 0.15, "test_ratio": 0.15},
                    "window_size_samples": 1024,
                    "n_fft": 256,
                }
            )
            self.assertEqual(set(result["metrics"]["models"].keys()), {"logistic_regression", "random_forest", "svm_rbf", "knn"})
            self.assertEqual(len(result["metrics"]["comparison"]), 4)
        finally:
            shutil.rmtree(tmp_path, ignore_errors=True)

    def test_experiment_listing_and_detail_load_e5(self) -> None:
        tmp_path, capture_ids = self._make_e5_dataset()
        try:
            service = RFExperimentLabService(tmp_path)
            service.e5_spectral_baseline_run({"capture_ids": capture_ids, "models": ["logistic_regression"], "split": {"strategy": "capture_disjoint", "group_by": ["capture_id"], "train_ratio": 0.7, "validation_ratio": 0.15, "test_ratio": 0.15}})
            listing = service.list_experiments()
            self.assertTrue(any(item["experiment_type"] == "e5_spectral_feature_baseline" for item in listing))
            detail = service.get_experiment_detail(listing[0]["experiment_id"])
            self.assertIn("metrics", detail)
            self.assertIn("config", detail)
        finally:
            shutil.rmtree(tmp_path, ignore_errors=True)

    def test_experiment_comparison_sorts_by_macro_f1(self) -> None:
        tmp_path, capture_ids = self._make_e5_dataset()
        try:
            service = RFExperimentLabService(tmp_path)
            first = service.e5_spectral_baseline_run({"capture_ids": capture_ids, "models": ["logistic_regression"], "split": {"strategy": "capture_disjoint", "group_by": ["capture_id"], "train_ratio": 0.7, "validation_ratio": 0.15, "test_ratio": 0.15}})
            second = service.e5_spectral_baseline_run({"capture_ids": capture_ids, "models": ["random_forest"], "split": {"strategy": "capture_disjoint", "group_by": ["capture_id"], "train_ratio": 0.7, "validation_ratio": 0.15, "test_ratio": 0.15}})
            ids = [
                f"e5_spectral_feature_baseline:{Path(first['result_package']['result_dir']).name}",
                f"e5_spectral_feature_baseline:{Path(second['result_package']['result_dir']).name}",
            ]
            comparison = service.compare_experiments({"experiment_ids": ids, "metric": "macro_f1"})
            values = [row["macro_f1"] for row in comparison["rows"]]
            self.assertEqual(values, sorted(values, reverse=True))
        finally:
            shutil.rmtree(tmp_path, ignore_errors=True)

    def test_e5_normalized_confusion_matrix_and_predictions_columns(self) -> None:
        tmp_path, capture_ids = self._make_e5_dataset()
        try:
            service = RFExperimentLabService(tmp_path)
            result = service.e5_spectral_baseline_run({"capture_ids": capture_ids, "models": ["logistic_regression"], "split": {"strategy": "capture_disjoint", "group_by": ["capture_id"], "train_ratio": 0.7, "validation_ratio": 0.15, "test_ratio": 0.15}})
            result_dir = Path(result["result_package"]["result_dir"])
            self.assertTrue((result_dir / "confusion_matrix_normalized.csv").exists())
            with (result_dir / "predictions.csv").open("r", newline="", encoding="utf-8") as handle:
                reader = csv.DictReader(handle)
                self.assertIn("true_label", reader.fieldnames or [])
                self.assertIn("predicted_label", reader.fieldnames or [])
        finally:
            shutil.rmtree(tmp_path, ignore_errors=True)

    def test_e5_random_forest_feature_importance_exported(self) -> None:
        tmp_path, capture_ids = self._make_e5_dataset()
        try:
            service = RFExperimentLabService(tmp_path)
            result = service.e5_spectral_baseline_run({"capture_ids": capture_ids, "models": ["random_forest"], "split": {"strategy": "capture_disjoint", "group_by": ["capture_id"], "train_ratio": 0.7, "validation_ratio": 0.15, "test_ratio": 0.15}})
            result_dir = Path(result["result_package"]["result_dir"])
            self.assertTrue((result_dir / "feature_importance.json").exists())
            self.assertTrue((result_dir / "feature_importance.csv").exists())
        finally:
            shutil.rmtree(tmp_path, ignore_errors=True)

    def test_e1_preview_does_not_train_and_reports_torch(self) -> None:
        tmp_path, capture_ids = self._make_e5_dataset()
        try:
            service = RFExperimentLabService(tmp_path)
            preview = service.e1_raw_iq_cnn1d_preview({"capture_ids": capture_ids, "window_size_samples": 512, "max_windows": 12})
            self.assertTrue(preview["preview_only"])
            self.assertFalse(preview["training_started"])
            self.assertIn("available", preview["torch"])
            self.assertEqual(preview["input_representation"], "raw_iq")
            self.assertEqual(preview["input_shape"], [2, 512])
        finally:
            shutil.rmtree(tmp_path, ignore_errors=True)

    def test_e1_run_fails_cleanly_if_torch_unavailable(self) -> None:
        tmp_path, capture_ids = self._make_e5_dataset()
        try:
            service = RFExperimentLabService(tmp_path)
            with self.assertRaises(RuntimeError):
                service.e1_raw_iq_cnn1d_run({"capture_ids": capture_ids, "force_torch_unavailable": True})
        finally:
            shutil.rmtree(tmp_path, ignore_errors=True)

    def test_e1_run_fails_cleanly_if_labels_missing(self) -> None:
        tmp_path, capture_ids = self._make_e5_dataset(with_labels=False)
        try:
            service = RFExperimentLabService(tmp_path)
            with self.assertRaises(ValueError):
                service.e1_raw_iq_cnn1d_run({"capture_ids": capture_ids, "epochs": 1, "max_windows": 12})
        finally:
            shutil.rmtree(tmp_path, ignore_errors=True)

    def test_e1_run_writes_expected_result_package_when_torch_available(self) -> None:
        tmp_path, capture_ids = self._make_e5_dataset()
        try:
            service = RFExperimentLabService(tmp_path)
            result = service.e1_raw_iq_cnn1d_run(
                {
                    "capture_ids": capture_ids,
                    "epochs": 1,
                    "batch_size": 4,
                    "window_size_samples": 512,
                    "max_windows": 12,
                    "split": {"strategy": "capture_disjoint", "group_by": ["capture_id"], "train_ratio": 0.7, "validation_ratio": 0.15, "test_ratio": 0.15},
                }
            )
            self.assertTrue(result["training_completed"])
            files = set(result["result_package"]["files"])
            self.assertTrue(
                {
                    "config.yaml",
                    "paper_reference.txt",
                    "model.pt",
                    "model_summary.txt",
                    "metrics.json",
                    "predictions.csv",
                    "confusion_matrix_raw.csv",
                    "confusion_matrix_normalized.csv",
                    "classification_report.json",
                    "split_definition.json",
                    "dataset_version.txt",
                    "runtime_log.csv",
                    "training_history.csv",
                }.issubset(files)
            )
        finally:
            shutil.rmtree(tmp_path, ignore_errors=True)

    def test_e1_uses_raw_iq_representation_layer_and_group_split(self) -> None:
        tmp_path, capture_ids = self._make_e5_dataset()
        try:
            service = RFExperimentLabService(tmp_path)
            preview = service.e1_raw_iq_cnn1d_preview(
                {
                    "capture_ids": capture_ids,
                    "window_size_samples": 512,
                    "max_windows": 12,
                    "split": {"strategy": "session_disjoint", "group_by": ["session_id"]},
                }
            )
            self.assertEqual(preview["input_representation"], "raw_iq")
            self.assertTrue(preview["split"]["leakage_check"]["passed"])
        finally:
            shutil.rmtree(tmp_path, ignore_errors=True)

    def test_e1_listing_detail_metadata_and_history(self) -> None:
        tmp_path, capture_ids = self._make_e5_dataset()
        try:
            service = RFExperimentLabService(tmp_path)
            result = service.e1_raw_iq_cnn1d_run(
                {
                    "capture_ids": capture_ids,
                    "epochs": 1,
                    "batch_size": 4,
                    "window_size_samples": 512,
                    "max_windows": 12,
                    "split": {"strategy": "capture_disjoint", "group_by": ["capture_id"], "train_ratio": 0.7, "validation_ratio": 0.15, "test_ratio": 0.15},
                }
            )
            listing = service.list_experiments()
            self.assertTrue(any(item["experiment_type"] == "e1_raw_iq_cnn1d" for item in listing))
            exp_id = f"e1_raw_iq_cnn1d:{Path(result['result_package']['result_dir']).name}"
            detail = service.get_experiment_detail(exp_id)
            self.assertIn("metrics", detail)
            self.assertIn("config", detail)
            self.assertIn("metadata", detail["model_metadata"])
            result_dir = Path(result["result_package"]["result_dir"])
            self.assertTrue((result_dir / "training_history.json").exists())
        finally:
            shutil.rmtree(tmp_path, ignore_errors=True)

    def test_e1_and_e5_compare_together(self) -> None:
        tmp_path, capture_ids = self._make_e5_dataset()
        try:
            service = RFExperimentLabService(tmp_path)
            e5 = service.e5_spectral_baseline_run({"capture_ids": capture_ids, "models": ["logistic_regression"], "split": {"strategy": "capture_disjoint", "group_by": ["capture_id"], "train_ratio": 0.7, "validation_ratio": 0.15, "test_ratio": 0.15}})
            e1 = service.e1_raw_iq_cnn1d_run({"capture_ids": capture_ids, "epochs": 1, "batch_size": 4, "window_size_samples": 512, "max_windows": 12, "split": {"strategy": "capture_disjoint", "group_by": ["capture_id"], "train_ratio": 0.7, "validation_ratio": 0.15, "test_ratio": 0.15}})
            ids = [
                f"e5_spectral_feature_baseline:{Path(e5['result_package']['result_dir']).name}",
                f"e1_raw_iq_cnn1d:{Path(e1['result_package']['result_dir']).name}",
            ]
            comparison = service.compare_experiments({"experiment_ids": ids, "metric": "macro_f1"})
            types = {row["experiment_type"] for row in comparison["rows"]}
            self.assertIn("e5_spectral_feature_baseline", types)
            self.assertIn("e1_raw_iq_cnn1d", types)
        finally:
            shutil.rmtree(tmp_path, ignore_errors=True)

    def test_e1_evaluation_artifacts_written(self) -> None:
        tmp_path, capture_ids = self._make_e5_dataset()
        try:
            service = RFExperimentLabService(tmp_path)
            result = service.e1_raw_iq_cnn1d_run(
                {
                    "capture_ids": capture_ids,
                    "epochs": 1,
                    "batch_size": 4,
                    "window_size_samples": 512,
                    "max_windows": 12,
                    "split": {"strategy": "capture_disjoint", "group_by": ["capture_id"], "train_ratio": 0.7, "validation_ratio": 0.15, "test_ratio": 0.15},
                }
            )
            result_dir = Path(result["result_package"]["result_dir"])
            self.assertTrue((result_dir / "overfitting_summary.json").exists())
            self.assertTrue((result_dir / "group_metrics.json").exists())
            self.assertTrue((result_dir / "group_metrics.csv").exists())
            self.assertTrue((result_dir / "confidence_summary.json").exists())
            metadata = json.loads((result_dir / "model_metadata.json").read_text(encoding="utf-8"))
            self.assertIn("input_shape", metadata)
            self.assertIn("parameter_count", metadata)
        finally:
            shutil.rmtree(tmp_path, ignore_errors=True)

    def test_e3_preview_does_not_train_and_reports_torch(self) -> None:
        tmp_path, capture_ids = self._make_e5_dataset()
        try:
            service = RFExperimentLabService(tmp_path)
            preview = service.e3_spectrogram_cnn2d_preview(
                {"capture_ids": capture_ids, "window_size_samples": 512, "max_samples": 12, "image_height": 32, "image_width": 32}
            )
            self.assertTrue(preview["preview_only"])
            self.assertFalse(preview["training_started"])
            self.assertIn("available", preview["torch"])
            self.assertEqual(preview["input_representation"], "spectrogram")
            self.assertEqual(preview["input_shape"], [1, 32, 32])
            self.assertEqual(preview["image_normalization_mode"], "per_sample_standardization")
            self.assertEqual(preview["model_type"], "simple_cnn2d")
            self.assertEqual(preview["default_model_type"], "simple_cnn2d")
            self.assertIn("simple_cnn2d", preview["available_model_types"])
            self.assertIn("resnet18", preview["available_model_types"])
            self.assertIn("vgg11", preview["available_model_types"])
        finally:
            shutil.rmtree(tmp_path, ignore_errors=True)

    def test_e3_torchvision_models_fail_cleanly_when_unavailable(self) -> None:
        tmp_path, capture_ids = self._make_e5_dataset()
        try:
            service = RFExperimentLabService(tmp_path)
            for model_type in ("resnet18", "vgg11"):
                preview = service.e3_spectrogram_cnn2d_preview(
                    {
                        "capture_ids": capture_ids,
                        "model_type": model_type,
                        "force_torchvision_unavailable": True,
                        "window_size_samples": 512,
                        "max_samples": 12,
                        "image_height": 32,
                        "image_width": 32,
                    }
                )
                self.assertFalse(preview["available_model_types"][model_type]["available"])
                with self.assertRaises(RuntimeError):
                    service.e3_spectrogram_cnn2d_run(
                        {
                            "capture_ids": capture_ids,
                            "model_type": model_type,
                            "force_torchvision_unavailable": True,
                            "epochs": 1,
                            "max_samples": 12,
                        }
                    )
        finally:
            shutil.rmtree(tmp_path, ignore_errors=True)

    def test_e3_run_fails_cleanly_if_torch_unavailable(self) -> None:
        tmp_path, capture_ids = self._make_e5_dataset()
        try:
            service = RFExperimentLabService(tmp_path)
            with self.assertRaises(RuntimeError):
                service.e3_spectrogram_cnn2d_run({"capture_ids": capture_ids, "force_torch_unavailable": True})
        finally:
            shutil.rmtree(tmp_path, ignore_errors=True)

    def test_e3_run_fails_cleanly_if_labels_missing(self) -> None:
        tmp_path, capture_ids = self._make_e5_dataset(with_labels=False)
        try:
            service = RFExperimentLabService(tmp_path)
            with self.assertRaises(ValueError):
                service.e3_spectrogram_cnn2d_run({"capture_ids": capture_ids, "epochs": 1, "max_samples": 12})
        finally:
            shutil.rmtree(tmp_path, ignore_errors=True)

    def test_e3_run_writes_expected_result_package_when_torch_available(self) -> None:
        tmp_path, capture_ids = self._make_e5_dataset()
        try:
            service = RFExperimentLabService(tmp_path)
            result = service.e3_spectrogram_cnn2d_run(
                {
                    "capture_ids": capture_ids,
                    "epochs": 1,
                    "batch_size": 4,
                    "window_size_samples": 512,
                    "max_samples": 12,
                    "n_fft": 64,
                    "hop_length": 32,
                    "image_height": 32,
                    "image_width": 32,
                    "split": {"strategy": "capture_disjoint", "group_by": ["capture_id"], "train_ratio": 0.7, "validation_ratio": 0.15, "test_ratio": 0.15},
                }
            )
            self.assertTrue(result["training_completed"])
            files = set(result["result_package"]["files"])
            self.assertTrue(
                {
                    "config.yaml",
                    "paper_reference.txt",
                    "model.pt",
                    "model_summary.txt",
                    "model_metadata.json",
                    "metrics.json",
                    "predictions.csv",
                    "confusion_matrix_raw.csv",
                    "confusion_matrix_normalized.csv",
                    "classification_report.json",
                    "split_definition.json",
                    "dataset_version.txt",
                    "runtime_log.csv",
                    "training_history.csv",
                    "training_history.json",
                    "overfitting_summary.json",
                    "group_metrics.json",
                    "group_metrics.csv",
                    "confidence_summary.json",
                }.issubset(files)
            )
            metadata = json.loads((Path(result["result_package"]["result_dir"]) / "model_metadata.json").read_text(encoding="utf-8"))
            self.assertEqual(metadata["model_type"], "simple_cnn2d")
            self.assertFalse(metadata["pretrained_used"])
            self.assertIn("torchvision_available", metadata)
        finally:
            shutil.rmtree(tmp_path, ignore_errors=True)

    def test_e3_uses_waterfall_representation_layer_and_group_split(self) -> None:
        tmp_path, capture_ids = self._make_e5_dataset()
        try:
            service = RFExperimentLabService(tmp_path)
            preview = service.e3_spectrogram_cnn2d_preview(
                {
                    "capture_ids": capture_ids,
                    "input_representation": "waterfall",
                    "window_size_samples": 512,
                    "max_samples": 12,
                    "image_height": 32,
                    "image_width": 32,
                    "split": {"strategy": "session_disjoint", "group_by": ["session_id"]},
                }
            )
            self.assertEqual(preview["input_representation"], "waterfall")
            self.assertTrue(preview["split"]["leakage_check"]["passed"])
        finally:
            shutil.rmtree(tmp_path, ignore_errors=True)

    def test_e3_listing_detail_and_comparison_with_e1_e5(self) -> None:
        tmp_path, capture_ids = self._make_e5_dataset()
        try:
            service = RFExperimentLabService(tmp_path)
            split = {"strategy": "capture_disjoint", "group_by": ["capture_id"], "train_ratio": 0.7, "validation_ratio": 0.15, "test_ratio": 0.15}
            e5 = service.e5_spectral_baseline_run({"capture_ids": capture_ids, "models": ["logistic_regression"], "split": split})
            e1 = service.e1_raw_iq_cnn1d_run({"capture_ids": capture_ids, "epochs": 1, "batch_size": 4, "window_size_samples": 512, "max_windows": 12, "split": split})
            e3 = service.e3_spectrogram_cnn2d_run(
                {
                    "capture_ids": capture_ids,
                    "epochs": 1,
                    "batch_size": 4,
                    "window_size_samples": 512,
                    "max_samples": 12,
                    "n_fft": 64,
                    "hop_length": 32,
                    "image_height": 32,
                    "image_width": 32,
                    "split": split,
                }
            )
            listing = service.list_experiments()
            self.assertTrue(any(item["experiment_type"] == "e3_spectrogram_cnn2d" for item in listing))
            e3_id = f"e3_spectrogram_cnn2d:{Path(e3['result_package']['result_dir']).name}"
            detail = service.get_experiment_detail(e3_id)
            self.assertIn("metadata", detail["model_metadata"])
            ids = [
                f"e5_spectral_feature_baseline:{Path(e5['result_package']['result_dir']).name}",
                f"e1_raw_iq_cnn1d:{Path(e1['result_package']['result_dir']).name}",
                e3_id,
            ]
            comparison = service.compare_experiments({"experiment_ids": ids, "metric": "macro_f1"})
            types = {row["experiment_type"] for row in comparison["rows"]}
            self.assertIn("e5_spectral_feature_baseline", types)
            self.assertIn("e1_raw_iq_cnn1d", types)
            self.assertIn("e3_spectrogram_cnn2d", types)
        finally:
            shutil.rmtree(tmp_path, ignore_errors=True)

    def test_benchmark_report_compares_e1_e3_e5_and_sorts_macro_f1(self) -> None:
        tmp_path, service, ids = self._make_benchmark_runs()
        try:
            report = service.benchmark_report({"experiment_ids": ids})
            self.assertEqual(set(report["experiment_ids"]), set(ids))
            types = {row["experiment_type"] for row in report["metric_comparison_table"]}
            self.assertIn("e5_spectral_feature_baseline", types)
            self.assertIn("e1_raw_iq_cnn1d", types)
            self.assertIn("e3_spectrogram_cnn2d", types)
            values = [row["macro_f1"] for row in report["metric_comparison_table"] if row["macro_f1"] is not None]
            self.assertEqual(values, sorted(values, reverse=True))
        finally:
            shutil.rmtree(tmp_path, ignore_errors=True)

    def test_benchmark_report_warnings_for_dataset_and_split_mismatch(self) -> None:
        tmp_path, service, ids = self._make_benchmark_runs(dataset_versions=("dataset_a", "dataset_b", "dataset_c"), split_variants=True)
        try:
            report = service.benchmark_report({"experiment_ids": ids, "include_group_metrics": True})
            self.assertTrue(report["warnings"]["different_dataset_versions"]["active"])
            self.assertTrue(report["warnings"]["different_split_strategies"]["active"])
            self.assertIn("missing_metrics", report["warnings"])
            self.assertIn("missing_group_metrics", report["warnings"])
            self.assertIn("incompatible_label_spaces", report["warnings"])
            self.assertIn("debug_random_split_used", report["warnings"])
            self.assertIn("low_sample_count", report["warnings"])
            self.assertIn("class_missing_in_test", report["warnings"])
        finally:
            shutil.rmtree(tmp_path, ignore_errors=True)

    def test_benchmark_report_identifies_best_fastest_and_exports(self) -> None:
        tmp_path, service, ids = self._make_benchmark_runs()
        try:
            report = service.benchmark_report(
                {
                    "experiment_ids": ids,
                    "include_predictions_summary": True,
                    "include_group_metrics": True,
                    "include_confusion_matrices": True,
                    "export": True,
                }
            )
            self.assertIsNotNone(report["best_model_by_macro_f1"])
            self.assertIsNotNone(report["best_model_by_balanced_accuracy"])
            self.assertIsNotNone(report["fastest_model_by_inference_time_ms"])
            self.assertIn("export_package", report)
            files = set(report["export_package"]["files"])
            self.assertIn("benchmark_report.json", files)
            self.assertIn("benchmark_report.md", files)
            self.assertIn("comparison_table.csv", files)
            self.assertIn("warnings.json", files)
            self.assertIn("reproducibility_summary.json", files)
            self.assertIn("predictions_summary", report)
            self.assertIn("confusion_matrices", report)
        finally:
            shutil.rmtree(tmp_path, ignore_errors=True)

    def test_benchmark_report_accepts_e3_architecture_variants(self) -> None:
        tmp_path, capture_ids = self._make_e5_dataset()
        try:
            service = RFExperimentLabService(tmp_path)
            if not service.e3_service._torchvision_available({"force_torchvision_unavailable": False}):
                self.skipTest("torchvision unavailable")
            split = {"strategy": "capture_disjoint", "group_by": ["capture_id"], "train_ratio": 0.7, "validation_ratio": 0.15, "test_ratio": 0.15}
            ids = []
            for model_type in ("simple_cnn2d", "resnet18", "vgg11"):
                result = service.e3_spectrogram_cnn2d_run(
                    {
                        "capture_ids": capture_ids,
                        "model_type": model_type,
                        "epochs": 1,
                        "batch_size": 4,
                        "window_size_samples": 512,
                        "max_samples": 12,
                        "n_fft": 64,
                        "hop_length": 32,
                        "image_height": 32,
                        "image_width": 32,
                        "split": split,
                    }
                )
                ids.append(f"e3_spectrogram_cnn2d:{Path(result['result_package']['result_dir']).name}")
            report = service.benchmark_report({"experiment_ids": ids})
            model_types = {row["model_type"] for row in report["metric_comparison_table"]}
            self.assertIn("simple_cnn2d", model_types)
            self.assertIn("resnet18", model_types)
            self.assertIn("vgg11", model_types)
        finally:
            shutil.rmtree(tmp_path, ignore_errors=True)

    def test_rf_experiment_dataset_v1_internal_export_and_e1_preview(self) -> None:
        tmp_path, capture_ids = self._make_e5_dataset()
        try:
            service = RFExperimentLabService(tmp_path)
            exported = service.rf_experiment_dataset_v1_export(
                {
                    "dataset_id": "internal_unified_test",
                    "dataset_version": "v1",
                    "task": "device_fingerprinting",
                    "label_field": "transmitter_id",
                    "capture_ids": capture_ids,
                    "split_strategy": "session_disjoint",
                    "split_group_fields": ["session_id"],
                }
            )
            manifest_path = Path(exported["manifest_path"])
            self.assertTrue(manifest_path.exists())
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["schema_version"], "RFExperimentDatasetV1")
            self.assertEqual(len(manifest["samples"]), len(capture_ids))
            self.assertTrue(all("sample_id" in sample and "sha256" in sample for sample in manifest["samples"]))

            preview = service.e1_raw_iq_cnn1d_preview(
                {
                    "dataset_manifest_path": str(manifest_path),
                    "label_field": "transmitter_id",
                    "window_size_samples": 512,
                    "max_windows": 12,
                    "split": {"strategy": "session_disjoint", "group_by": ["session_id"]},
                    "force_torch_unavailable": True,
                }
            )
            self.assertEqual(preview["dataset"]["capture_count"], len(capture_ids))
            self.assertEqual(preview["input_shape"], [2, 512])
            self.assertFalse(preview["training_started"])
        finally:
            shutil.rmtree(tmp_path, ignore_errors=True)

    def test_external_dataset_import_warns_for_radioml_fingerprinting(self) -> None:
        workspace_tmp = Path("tmp_rf_tests")
        workspace_tmp.mkdir(parents=True, exist_ok=True)
        tmp_path = workspace_tmp / f"external_{uuid4().hex[:8]}"
        try:
            class_dir = tmp_path / "bpsk"
            class_dir.mkdir(parents=True, exist_ok=False)
            iq_path = class_dir / "sample_0001.iq"
            np.ones(64, dtype=np.complex64).tofile(iq_path)
            service = RFExperimentLabService(tmp_path)
            preview = service.external_dataset_import_preview(
                {
                    "dataset_id": "radioml_debug",
                    "dataset_source": "radioml",
                    "source_path": str(tmp_path),
                    "source_format": "iq",
                    "task": "device_fingerprinting",
                    "label_field": "transmitter_id",
                    "sample_rate_hz": 1_000_000,
                    "center_frequency_hz": 100_000_000,
                }
            )
            warning_types = {item["type"] for item in preview["warnings"]}
            self.assertIn("dataset_task_mismatch", warning_types)
            self.assertEqual(preview["schema_version"], "RFExperimentDatasetV1")
            self.assertEqual(preview["sample_count"], 1)
        finally:
            shutil.rmtree(tmp_path, ignore_errors=True)

    def test_e5_preview_accepts_rf_experiment_dataset_manifest(self) -> None:
        tmp_path, capture_ids = self._make_e5_dataset()
        try:
            service = RFExperimentLabService(tmp_path)
            exported = service.rf_experiment_dataset_v1_export(
                {
                    "dataset_id": "e5_manifest_test",
                    "dataset_version": "v1",
                    "task": "device_fingerprinting",
                    "label_field": "transmitter_id",
                    "capture_ids": capture_ids,
                }
            )
            preview = service.e5_spectral_baseline_preview(
                {
                    "dataset_manifest_path": exported["manifest_path"],
                    "label_field": "transmitter_id",
                    "models": ["logistic_regression"],
                    "split": {"strategy": "session_disjoint", "group_by": ["session_id"]},
                }
            )
            self.assertEqual(preview["dataset"]["capture_count"], len(capture_ids))
            self.assertIn("device_0", preview["dataset"]["labels"])
            self.assertIn("device_1", preview["dataset"]["labels"])
        finally:
            shutil.rmtree(tmp_path, ignore_errors=True)

    def test_internal_dataset_sample_review_export_and_random_debug_warning(self) -> None:
        tmp_path, iq_path, _metadata_path = self._make_export_workspace(sample_count=256)
        try:
            service = RFExperimentLabService(tmp_path)
            created = service.create_internal_dataset_sample(
                {
                    "iq_path": str(iq_path),
                    "sample_id": "lab_sample_001",
                    "task": "device_fingerprinting",
                    "label": "device_a",
                    "transmitter_id": "device_a",
                    "sample_rate_hz": 1_000_000,
                    "center_frequency_hz": 100_000_000,
                    "session_id": "session_a",
                    "receiver_id": "rx_1",
                    "environment_id": "lab",
                    "distance_m": 1.5,
                    "qc_summary": {"qc_status": "accepted"},
                }
            )
            self.assertEqual(created["sample"]["sample_id"], "lab_sample_001")
            reviewed = service.review_internal_dataset_sample("lab_sample_001", {"review_status": "accepted", "notes": "ok"})
            self.assertEqual(reviewed["review_status"], "accepted")
            exported = service.rf_experiment_dataset_v1_export(
                {
                    "dataset_id": "internal_lab",
                    "dataset_version": "v1",
                    "task": "device_fingerprinting",
                    "label_field": "transmitter_id",
                    "split_strategy": "random",
                }
            )
            warning_types = {item["type"] for item in exported["warnings"]}
            self.assertIn("debug_split", warning_types)
            manifest = json.loads(Path(exported["manifest_path"]).read_text(encoding="utf-8"))
            self.assertEqual(manifest["samples"][0]["sample_id"], "lab_sample_001")
            self.assertEqual(manifest["samples"][0]["rf_metadata"]["sample_rate_hz"], 1_000_000)
        finally:
            shutil.rmtree(tmp_path, ignore_errors=True)

    def test_e5_result_package_records_manifest_reproducibility_and_inference_persistence(self) -> None:
        tmp_path, capture_ids = self._make_e5_dataset()
        try:
            service = RFExperimentLabService(tmp_path)
            exported = service.rf_experiment_dataset_v1_export(
                {
                    "dataset_id": "repro_e5",
                    "dataset_version": "v1",
                    "task": "device_fingerprinting",
                    "label_field": "transmitter_id",
                    "capture_ids": capture_ids,
                }
            )
            result = service.e5_spectral_baseline_run(
                {
                    "dataset_manifest_path": exported["manifest_path"],
                    "dataset_version": "v1",
                    "label_field": "transmitter_id",
                    "models": ["logistic_regression"],
                    "split": {"strategy": "session_disjoint", "group_by": ["session_id"]},
                }
            )
            result_dir = Path(result["result_package"]["result_dir"])
            for filename in ("dataset_manifest_path.txt", "training_config.json", "label_schema.json", "normalization_params.json", "confusion_matrix_raw.csv"):
                self.assertTrue((result_dir / filename).exists(), filename)
            self.assertEqual((result_dir / "dataset_manifest_path.txt").read_text(encoding="utf-8").strip(), exported["manifest_path"])

            experiment_id = f"e5_spectral_feature_baseline:{result_dir.name}"
            prediction = service.predict(
                {
                    "experiment_ids": [experiment_id],
                    "source_type": "saved_capture",
                    "input_sample_id": "capture_0001",
                    "persist": True,
                }
            )
            self.assertIn("prediction_result", prediction)
            self.assertIn("confidence", prediction["prediction_result"])
            self.assertTrue(Path(prediction["result_path"]).exists())
            persisted = json.loads(Path(prediction["result_path"]).read_text(encoding="utf-8"))
            self.assertEqual(persisted["input_sample_id"], "capture_0001")
            self.assertIn("model_id", persisted)
            self.assertIn("timestamp", persisted)
        finally:
            shutil.rmtree(tmp_path, ignore_errors=True)

    def test_region_comparison_returns_agreement_disagreement_fields(self) -> None:
        tmp_path, service, ids = self._make_benchmark_runs()
        try:
            result = service.compare_models_on_region(
                {
                    "experiment_ids": ids,
                    "source_type": "marker_region",
                    "input_sample_id": "marker_m1_m2",
                    "marker_region": {"marker_1_hz": 100_000_000, "marker_2_hz": 101_000_000},
                    "persist": True,
                }
            )
            summary = result["prediction_result"]
            self.assertIn("predictions", summary)
            self.assertIn("latency_ms", summary)
            self.assertIn("agreement", summary["agreement"])
            self.assertIn("disagreement", summary["agreement"])
            self.assertTrue(Path(result["result_path"]).exists())
        finally:
            shutil.rmtree(tmp_path, ignore_errors=True)

    def _make_e0_workspace(self) -> tuple[Path, Path]:
        workspace_tmp = Path("tmp_rf_tests")
        workspace_tmp.mkdir(parents=True, exist_ok=True)
        tmp_path = workspace_tmp / f"e0_{uuid4().hex[:8]}"
        tmp_path.mkdir(parents=True, exist_ok=False)
        metadata_path = tmp_path / "capture_0001.json"
        metadata_path.write_text(
            json.dumps(
                {
                    "capture_id": "capture_0001",
                    "session_id": "session_001",
                    "dataset_split": "train",
                    "dataset_version": "test_dataset_v1",
                    "capture_config": {
                        "output_path": "capture_0001.cfile",
                        "sample_dtype": "complex64",
                        "sample_rate_hz": 20_000_000,
                        "center_frequency_hz": 2_437_000_000,
                        "capture_duration_s": 5.0,
                        "sdr_model": "USRP B200",
                        "sdr_serial": "usrp_b200_rx_01",
                    },
                    "scenario": {"timestamp_utc": "2026-05-01T13:00:00Z"},
                }
            ),
            encoding="utf-8",
        )
        return tmp_path, metadata_path

    def _make_export_workspace(self, sample_count: int = 128) -> tuple[Path, Path, Path]:
        workspace_tmp = Path("tmp_rf_tests")
        workspace_tmp.mkdir(parents=True, exist_ok=True)
        tmp_path = workspace_tmp / f"export_{uuid4().hex[:8]}"
        tmp_path.mkdir(parents=True, exist_ok=False)
        iq_path = tmp_path / "capture_0001.cfile"
        iq = (np.linspace(0.0, 1.0, sample_count, dtype=np.float32) + 1j * np.linspace(1.0, 0.0, sample_count, dtype=np.float32)).astype(np.complex64)
        iq.tofile(iq_path)
        metadata_path = tmp_path / "capture_0001.json"
        metadata_path.write_text(
            json.dumps(
                {
                    "capture_id": "capture_0001",
                    "session_id": "session_001",
                    "dataset_split": "train",
                    "dataset_version": "test_dataset_v1",
                    "capture_config": {
                        "output_path": str(iq_path),
                        "file_format": ".cfile",
                        "sample_dtype": "complex64",
                        "sample_rate_hz": 20_000_000,
                        "center_frequency_hz": 2_437_000_000,
                        "capture_duration_s": 5.0,
                        "sample_count": sample_count,
                        "sdr_model": "USRP B200",
                        "antenna_port": "RX2",
                        "gain_settings": {"composite_gain_db": 30.0},
                    },
                    "transmitter": {
                        "transmitter_id": "router_001",
                        "transmitter_class": "wifi",
                        "family": "wifi",
                    },
                    "scenario": {
                        "operator": "NICS Lab",
                        "environment": "indoor_lab",
                        "timestamp_utc": "2026-05-01T13:00:00Z",
                    },
                    "quality_metrics": {"estimated_snr_db": 32.4},
                }
            ),
            encoding="utf-8",
        )
        return tmp_path, iq_path, metadata_path

    def _seed_dataset_adapter_capture(self, service: RFExperimentLabService, iq_path: Path, metadata_path: Path) -> None:
        captures_dir = service.dataset_adapter.fingerprinting_capture_dir
        captures_dir.mkdir(parents=True, exist_ok=True)
        record = json.loads(metadata_path.read_text(encoding="utf-8"))
        record["artifacts"] = {
            "iq_file": str(iq_path),
            "metadata_file": str(metadata_path),
            "sha256": self._sha256(iq_path),
        }
        (captures_dir / "capture_0001.json").write_text(json.dumps(record), encoding="utf-8")

    def _sha256(self, path: Path) -> str:
        digest = hashlib.sha256()
        digest.update(path.read_bytes())
        return digest.hexdigest()

    def _make_e5_dataset(self, with_labels: bool = True) -> tuple[Path, list[str]]:
        workspace_tmp = Path("tmp_rf_tests")
        workspace_tmp.mkdir(parents=True, exist_ok=True)
        tmp_path = workspace_tmp / f"e5_{uuid4().hex[:8]}"
        captures_dir = tmp_path / "fingerprinting" / "captures"
        captures_dir.mkdir(parents=True, exist_ok=True)
        capture_ids = []
        for index in range(12):
            capture_id = f"capture_{index:04d}"
            capture_ids.append(capture_id)
            iq_path = tmp_path / f"{capture_id}.cfile"
            label_index = index % 2
            base = 0.05 + label_index * 0.2
            samples = 4096
            t = np.arange(samples, dtype=np.float32)
            iq = (np.exp(1j * 2.0 * np.pi * base * t).astype(np.complex64) * (1.0 + 0.05 * index)).astype(np.complex64)
            iq.tofile(iq_path)
            metadata_path = captures_dir / f"{capture_id}.json"
            transmitter = (
                {
                    "transmitter_id": f"device_{label_index}",
                    "transmitter_class": "wifi",
                    "family": "wifi",
                    "transmitter_label": f"router_{label_index}",
                }
                if with_labels
                else {}
            )
            metadata_path.write_text(
                json.dumps(
                    {
                        "capture_id": capture_id,
                        "session_id": f"session_{index:04d}",
                        "dataset_split": "train",
                        "capture_config": {
                            "output_path": str(iq_path),
                            "sample_dtype": "complex64",
                            "sample_rate_hz": 1_000_000,
                            "center_frequency_hz": 100_000_000,
                            "capture_duration_s": 0.004096,
                            "sample_count": samples,
                            "sdr_model": "test_sdr",
                            "sdr_serial": "rx_test",
                        },
                        "transmitter": transmitter,
                        "scenario": {
                            "operator": "test",
                            "environment": "lab",
                            "timestamp_utc": "2026-05-01T13:00:00Z",
                        },
                        "quality_metrics": {"estimated_snr_db": 30.0},
                        "artifacts": {
                            "iq_file": str(iq_path),
                            "metadata_file": str(metadata_path),
                            "sha256": self._sha256(iq_path),
                        },
                    }
                ),
                encoding="utf-8",
            )
        return tmp_path, capture_ids

    def _make_benchmark_runs(
        self,
        dataset_versions: tuple[str, str, str] = ("bench_dataset", "bench_dataset", "bench_dataset"),
        split_variants: bool = False,
    ) -> tuple[Path, RFExperimentLabService, list[str]]:
        tmp_path, capture_ids = self._make_e5_dataset()
        service = RFExperimentLabService(tmp_path)
        capture_split = {"strategy": "capture_disjoint", "group_by": ["capture_id"], "train_ratio": 0.7, "validation_ratio": 0.15, "test_ratio": 0.15}
        session_split = {"strategy": "session_disjoint", "group_by": ["session_id"], "train_ratio": 0.7, "validation_ratio": 0.15, "test_ratio": 0.15}
        e5_split = capture_split
        e1_split = session_split if split_variants else capture_split
        e3_split = capture_split
        e5 = service.e5_spectral_baseline_run(
            {"capture_ids": capture_ids, "dataset_version": dataset_versions[0], "models": ["logistic_regression"], "split": e5_split}
        )
        e1 = service.e1_raw_iq_cnn1d_run(
            {
                "capture_ids": capture_ids,
                "dataset_version": dataset_versions[1],
                "epochs": 1,
                "batch_size": 4,
                "window_size_samples": 512,
                "max_windows": 12,
                "split": e1_split,
            }
        )
        e3 = service.e3_spectrogram_cnn2d_run(
            {
                "capture_ids": capture_ids,
                "dataset_version": dataset_versions[2],
                "epochs": 1,
                "batch_size": 4,
                "window_size_samples": 512,
                "max_samples": 12,
                "n_fft": 64,
                "hop_length": 32,
                "image_height": 32,
                "image_width": 32,
                "split": e3_split,
            }
        )
        ids = [
            f"e5_spectral_feature_baseline:{Path(e5['result_package']['result_dir']).name}",
            f"e1_raw_iq_cnn1d:{Path(e1['result_package']['result_dir']).name}",
            f"e3_spectrogram_cnn2d:{Path(e3['result_package']['result_dir']).name}",
        ]
        return tmp_path, service, ids

    def _e0_payload(self, metadata_path: Path) -> dict:
        matrix = np.zeros((32, 48), dtype=np.float32)
        matrix[8:18, 12:28] = 4.0
        return {
            "metadata_path": str(metadata_path),
            "waterfall_matrix": matrix.tolist(),
            "time_axis_s": np.linspace(0.0, 5.0, 32).tolist(),
            "freq_axis_hz": np.linspace(2_427_000_000, 2_447_000_000, 48).tolist(),
        }


if __name__ == "__main__":
    unittest.main()
