from __future__ import annotations

import asyncio
from pathlib import Path

import numpy as np
import pytest

from app.modules.ai_research_plugin.contracts import CompatibilityVerdict, InputRepresentation
from app.modules.ai_research_plugin.inference_service import (
    DEFAULT_LIVE_SAMPLE_COUNT,
    AiInferenceService,
    InferenceError,
    _infer_required_sample_count,
)
from app.modules.ai_research_plugin.live_bridge import LiveIqSnapshot
from app.modules.ai_research_plugin.model_registry import ModelRegistry
from app.modules.ai_research_plugin.storage import AiPluginStorage
from app.tests.unit.ai_research_plugin.onnx_fixtures import N_CLASSES, N_SAMPLES, build_toy_amc_onnx_bytes

SAMPLE_RATE_HZ = 2_000_000.0
CENTER_FREQUENCY_HZ = 2_440_000_000.0
CLASSES = ["BPSK", "QPSK", "8PSK", "16QAM", "64QAM"]
assert len(CLASSES) == N_CLASSES


def _tone_snapshot(n_samples: int, freq_hz: float = 50_000.0, data_sha256: str = "live-hash-abc") -> LiveIqSnapshot:
    n = np.arange(n_samples)
    phase = 2 * np.pi * freq_hz * n / SAMPLE_RATE_HZ
    return LiveIqSnapshot(
        re=np.cos(phase).astype(np.float32),
        im=np.sin(phase).astype(np.float32),
        sample_rate_hz=SAMPLE_RATE_HZ,
        center_frequency_hz=CENTER_FREQUENCY_HZ,
        timestamp_utc="2026-01-01T00:00:00Z",
        data_sha256=data_sha256,
    )


class FakeLiveBridge:
    def __init__(self, snapshot: LiveIqSnapshot | None, error: Exception | None = None):
        self._snapshot = snapshot
        self._error = error
        self.requested_sample_counts: list[int] = []

    async def capture_snapshot(self, sample_count: int, timeout_seconds: float = 5.0) -> LiveIqSnapshot:
        self.requested_sample_counts.append(sample_count)
        if self._error:
            raise self._error
        return self._snapshot


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture
def registry(tmp_path: Path) -> ModelRegistry:
    return ModelRegistry(AiPluginStorage(tmp_path / "ai_research_plugin"))


def _import_toy_model(registry: ModelRegistry, with_classes: bool = True):
    manifest = registry.import_onnx_model(build_toy_amc_onnx_bytes(), "toy_amc.onnx", model_name="Toy AMC")
    if with_classes:
        manifest = registry.apply_overrides(manifest.model_id, output_overrides={"classes": CLASSES})
    return manifest


def test_infer_required_sample_count_uses_the_models_real_declared_shape(registry: ModelRegistry):
    manifest = _import_toy_model(registry)
    assert _infer_required_sample_count(manifest) == N_SAMPLES  # the toy model's real declared last dim


def test_infer_required_sample_count_falls_back_to_a_documented_default_when_unset():
    from app.modules.ai_research_plugin.contracts import ModelFramework, RFModelManifest

    manifest = RFModelManifest(
        model_id="AI-MODEL-no-shape", model_name="no-shape", framework=ModelFramework.ONNX,
        model_file="x.onnx", model_sha256="a" * 64, imported_at_utc="2026-01-01T00:00:00Z",
    )
    assert _infer_required_sample_count(manifest) == DEFAULT_LIVE_SAMPLE_COUNT


def test_infer_required_sample_count_halves_the_declared_dim_for_flat_iq(registry: ModelRegistry):
    # FLAT_IQ's declared last dim is 2N (interleaved real/imag) -- the real
    # MT-PreamCNN shape is [None, 1600] for 800 complex samples.
    manifest = _import_toy_model(registry)  # real declared last dim is N_SAMPLES
    manifest = registry.apply_overrides(manifest.model_id, input_overrides={"tensor_shape": [None, 1600]})
    assert _infer_required_sample_count(manifest, InputRepresentation.FLAT_IQ) == 800
    # Every other representation's last dim already equals N -- unaffected.
    assert _infer_required_sample_count(manifest, InputRepresentation.IQ_TENSOR) == 1600


def test_run_inference_live_requests_exactly_the_models_required_sample_count(registry: ModelRegistry):
    manifest = _import_toy_model(registry)
    live_bridge = FakeLiveBridge(_tone_snapshot(N_SAMPLES))
    service = AiInferenceService(registry=registry, capture_bridge=None, storage=registry.storage, live_bridge=live_bridge)

    _run(service.run_inference_live(manifest.model_id, InputRepresentation.IQ_TENSOR))

    assert live_bridge.requested_sample_counts == [N_SAMPLES]


def test_run_inference_live_produces_a_real_classification_and_persists_a_record(registry: ModelRegistry):
    manifest = _import_toy_model(registry)
    live_bridge = FakeLiveBridge(_tone_snapshot(N_SAMPLES))
    service = AiInferenceService(registry=registry, capture_bridge=None, storage=registry.storage, live_bridge=live_bridge)

    record = _run(service.run_inference_live(manifest.model_id, InputRepresentation.IQ_TENSOR))

    assert record.capture_id == "LIVE"
    assert record.capture_data_sha256 == "live-hash-abc"
    assert record.interpretation["kind"] == "classification"
    assert record.interpretation["predicted_class"] in CLASSES
    assert record.selected_time_seconds[1] == pytest.approx(N_SAMPLES / SAMPLE_RATE_HZ)

    persisted = service.storage.load_record(record.record_id)
    assert persisted is not None
    assert persisted.capture_id == "LIVE"


def test_run_inference_live_attaches_a_real_compatibility_result_from_live_metadata(registry: ModelRegistry):
    manifest = _import_toy_model(registry)
    registry.apply_overrides(manifest.model_id, input_overrides={"sample_rate_hz": SAMPLE_RATE_HZ})
    live_bridge = FakeLiveBridge(_tone_snapshot(N_SAMPLES))
    service = AiInferenceService(registry=registry, capture_bridge=None, storage=registry.storage, live_bridge=live_bridge)

    record = _run(service.run_inference_live(manifest.model_id, InputRepresentation.IQ_TENSOR))

    sample_rate_check = next(c for c in record.compatibility.checks if c.field == "sample_rate_hz")
    assert sample_rate_check.matched is True
    assert record.compatibility.verdict in (CompatibilityVerdict.COMPATIBLE, CompatibilityVerdict.PARTIALLY_COMPATIBLE)


def test_run_inference_live_fails_closed_without_a_wired_live_bridge(registry: ModelRegistry):
    manifest = _import_toy_model(registry)
    service = AiInferenceService(registry=registry, capture_bridge=None, storage=registry.storage, live_bridge=None)

    with pytest.raises(InferenceError, match="unavailable"):
        _run(service.run_inference_live(manifest.model_id, InputRepresentation.IQ_TENSOR))


def test_run_inference_live_raises_a_clear_error_for_an_unknown_model_id(registry: ModelRegistry):
    live_bridge = FakeLiveBridge(_tone_snapshot(N_SAMPLES))
    service = AiInferenceService(registry=registry, capture_bridge=None, storage=registry.storage, live_bridge=live_bridge)
    with pytest.raises(InferenceError, match="Unknown model_id"):
        _run(service.run_inference_live("AI-MODEL-does-not-exist", InputRepresentation.IQ_TENSOR))


def test_run_inference_live_measures_real_latency_fields(registry: ModelRegistry):
    manifest = _import_toy_model(registry)
    live_bridge = FakeLiveBridge(_tone_snapshot(N_SAMPLES))
    service = AiInferenceService(registry=registry, capture_bridge=None, storage=registry.storage, live_bridge=live_bridge)

    record = _run(service.run_inference_live(manifest.model_id, InputRepresentation.IQ_TENSOR))

    assert record.capture_latency_ms is not None and record.capture_latency_ms >= 0
    assert record.inference_latency_ms is not None and record.inference_latency_ms >= 0
    assert record.total_latency_ms is not None
    # total covers at least capture + inference -- never smaller than either part.
    assert record.total_latency_ms >= record.capture_latency_ms
    assert record.total_latency_ms >= record.inference_latency_ms


def test_run_inference_live_flags_a_real_center_frequency_mismatch(registry: ModelRegistry):
    manifest = _import_toy_model(registry)
    registry.apply_overrides(
        manifest.model_id,
        input_overrides={"expected_center_frequency_hz": 915_000_000.0, "expected_frequency_tolerance_hz": 500_000.0},
    )
    live_bridge = FakeLiveBridge(_tone_snapshot(N_SAMPLES))  # real snapshot center frequency is 2.44 GHz
    service = AiInferenceService(registry=registry, capture_bridge=None, storage=registry.storage, live_bridge=live_bridge)

    record = _run(service.run_inference_live(manifest.model_id, InputRepresentation.IQ_TENSOR))

    frequency_check = next(c for c in record.compatibility.checks if c.field == "center_frequency_hz")
    assert frequency_check.matched is False
    assert frequency_check.capture_value == CENTER_FREQUENCY_HZ


def test_run_inference_live_propagates_a_real_bridge_timeout_as_inference_error(registry: ModelRegistry):
    from app.modules.ai_research_plugin.live_bridge import LiveIqBridgeError

    manifest = _import_toy_model(registry)
    live_bridge = FakeLiveBridge(None, error=LiveIqBridgeError("Timed out waiting for a live I/Q snapshot"))
    service = AiInferenceService(registry=registry, capture_bridge=None, storage=registry.storage, live_bridge=live_bridge)

    with pytest.raises(InferenceError, match="Timed out"):
        _run(service.run_inference_live(manifest.model_id, InputRepresentation.IQ_TENSOR))
