from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from app.modules.ai_research_plugin.capture_bridge import ReadOnlyCaptureBridge
from app.modules.ai_research_plugin.contracts import CompatibilityVerdict, InputRepresentation, OutputType
from app.modules.ai_research_plugin.inference_service import AiInferenceService, InferenceError
from app.modules.ai_research_plugin.model_registry import ModelRegistry
from app.modules.ai_research_plugin.storage import AiPluginStorage
from app.tests.unit.ai_research_plugin.onnx_fixtures import N_CLASSES, N_SAMPLES, build_toy_amc_onnx_bytes

SAMPLE_RATE_HZ = 2_000_000.0
CLASSES = ["BPSK", "QPSK", "8PSK", "16QAM", "64QAM"]
assert len(CLASSES) == N_CLASSES


class FakeCaptureManager:
    def __init__(self, data_path: Path, metadata: dict):
        self._data_path = data_path
        self._metadata = metadata

    def list_captures(self):
        return [self._metadata]

    def metadata(self, capture_id: str):
        if capture_id != self._metadata["capture_id"]:
            raise FileNotFoundError(f"Unknown capture_id: {capture_id}")
        return self._metadata

    def data_path(self, capture_id: str) -> Path:
        if capture_id != self._metadata["capture_id"]:
            raise FileNotFoundError(f"Unknown capture_id: {capture_id}")
        return self._data_path


def _write_cf32le_tone(path: Path, n_samples: int, freq_hz: float) -> None:
    n = np.arange(n_samples)
    phase = 2 * np.pi * freq_hz * n / SAMPLE_RATE_HZ
    interleaved = np.empty(n_samples * 2, dtype=np.float32)
    interleaved[0::2] = np.cos(phase).astype(np.float32)
    interleaved[1::2] = np.sin(phase).astype(np.float32)
    path.write_bytes(interleaved.tobytes())


@pytest.fixture
def service(tmp_path: Path) -> AiInferenceService:
    data_path = tmp_path / "capture" / "BLE-IQ-test.sigmf-data"
    data_path.parent.mkdir(parents=True)
    _write_cf32le_tone(data_path, N_SAMPLES * 4, freq_hz=50_000)  # plenty of samples to select a 128-sample region from
    metadata = {
        "capture_id": "BLE-IQ-test",
        "sample_format": "cf32_le",
        "sample_rate_sps": SAMPLE_RATE_HZ,
        "actual_samples": N_SAMPLES * 4,
        "data_sha256": "capture-hash-abc123",
        "bandwidth_hz": SAMPLE_RATE_HZ,
    }
    bridge = ReadOnlyCaptureBridge(FakeCaptureManager(data_path, metadata))
    storage = AiPluginStorage(tmp_path / "ai_research_plugin")
    registry = ModelRegistry(storage)
    return AiInferenceService(registry=registry, capture_bridge=bridge, storage=storage)


def _import_toy_model(service: AiInferenceService, with_classes: bool = True):
    manifest = service.registry.import_onnx_model(build_toy_amc_onnx_bytes(), "toy_amc.onnx", model_name="Toy AMC")
    if with_classes:
        manifest = service.registry.apply_overrides(manifest.model_id, output_overrides={"classes": CLASSES})
    return manifest


def _region_seconds(n_samples: int) -> tuple[float, float]:
    return 0.0, n_samples / SAMPLE_RATE_HZ


def test_runs_a_real_onnx_forward_pass_end_to_end_and_persists_a_reproducible_record(service: AiInferenceService):
    manifest = _import_toy_model(service)
    t0, t1 = _region_seconds(N_SAMPLES)

    record = service.run_inference(manifest.model_id, "BLE-IQ-test", t0, t1, InputRepresentation.IQ_TENSOR)

    assert record.model_id == manifest.model_id
    assert record.capture_id == "BLE-IQ-test"
    assert record.capture_data_sha256 == "capture-hash-abc123"
    assert record.input_tensor_shape == [1, 2, N_SAMPLES]
    assert record.raw_output_shape == [1, N_CLASSES]
    assert len(record.raw_output) == N_CLASSES
    assert record.interpretation["kind"] == "classification"
    assert record.interpretation["predicted_class"] in CLASSES
    assert record.software_backend.startswith("onnxruntime==")

    # Reproducibility: the record is retrievable afterward, exactly as persisted.
    persisted = service.storage.load_record(record.record_id)
    assert persisted is not None
    assert persisted.raw_output == record.raw_output


def test_two_runs_over_the_same_real_region_produce_identical_raw_output(service: AiInferenceService):
    manifest = _import_toy_model(service)
    t0, t1 = _region_seconds(N_SAMPLES)

    record_a = service.run_inference(manifest.model_id, "BLE-IQ-test", t0, t1, InputRepresentation.IQ_TENSOR)
    record_b = service.run_inference(manifest.model_id, "BLE-IQ-test", t0, t1, InputRepresentation.IQ_TENSOR)

    assert record_a.raw_output == record_b.raw_output


def test_attaches_a_real_compatibility_result_without_blocking_a_partial_match(service: AiInferenceService):
    manifest = _import_toy_model(service)
    service.registry.apply_overrides(manifest.model_id, input_overrides={"sample_rate_hz": 999_000_000.0})
    t0, t1 = _region_seconds(N_SAMPLES)

    record = service.run_inference(manifest.model_id, "BLE-IQ-test", t0, t1, InputRepresentation.IQ_TENSOR)

    # A declared-but-mismatched sample rate makes this PARTIALLY_COMPATIBLE
    # (representation still matches) -- inference still ran and produced a
    # real result, per spec section 11's "no bloquear necesariamente".
    assert record.compatibility.verdict == CompatibilityVerdict.PARTIALLY_COMPATIBLE
    assert record.interpretation["kind"] == "classification"


def test_raises_a_clear_error_for_an_unknown_model_id(service: AiInferenceService):
    t0, t1 = _region_seconds(N_SAMPLES)
    with pytest.raises(InferenceError, match="Unknown model_id"):
        service.run_inference("AI-MODEL-does-not-exist", "BLE-IQ-test", t0, t1, InputRepresentation.IQ_TENSOR)


def test_raises_a_clear_error_for_an_unknown_capture_id(service: AiInferenceService):
    manifest = _import_toy_model(service)
    t0, t1 = _region_seconds(N_SAMPLES)
    with pytest.raises(InferenceError):
        service.run_inference(manifest.model_id, "BLE-IQ-does-not-exist", t0, t1, InputRepresentation.IQ_TENSOR)


def test_a_tensor_shape_mismatch_fails_with_a_real_onnxruntime_error_not_a_crash(service: AiInferenceService):
    manifest = _import_toy_model(service)
    # A region far too short for the model's fixed [1, 2, 128] input --
    # onnxruntime itself will reject the shape.
    with pytest.raises(InferenceError, match="Inference failed"):
        service.run_inference(manifest.model_id, "BLE-IQ-test", 0.0, 1.0 / SAMPLE_RATE_HZ, InputRepresentation.IQ_TENSOR)


def test_without_a_class_list_override_the_result_is_honestly_not_interpretable(service: AiInferenceService):
    manifest = _import_toy_model(service, with_classes=False)
    t0, t1 = _region_seconds(N_SAMPLES)
    record = service.run_inference(manifest.model_id, "BLE-IQ-test", t0, t1, InputRepresentation.IQ_TENSOR)
    assert record.interpretation["kind"] == "not_automatically_interpretable"
