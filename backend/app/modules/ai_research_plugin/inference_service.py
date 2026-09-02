"""Isolated Inference orchestration (spec sections 8, 11, 12, 19).

Runs in-process via `onnxruntime.InferenceSession` -- a real, disclosed
Phase-1 scope decision, not the "idealmente" separate-process/IPC
isolation spec section 8 describes as an aspiration. onnxruntime's CPU
execution provider has none of the heavyweight, environment-polluting
dependency footprint torch/tensorflow would carry, so the practical case
for process isolation (protecting the host app's own dependencies) is
much weaker here than for those frameworks -- still a real, disclosed gap,
not silently dropped (see the plugin's own README).

Never touches: Live Monitor, SDR acquisition, existing RF processing,
existing storage, existing detections. Only reads (never writes) a real
preserved BLE capture via ReadOnlyCaptureBridge, and only writes into this
plugin's OWN storage directory (model files, manifests, inference
records).
"""

from __future__ import annotations

import time

import numpy as np
import onnxruntime as ort

from app.modules.ai_research_plugin.adapters import adapt
from app.modules.ai_research_plugin.capture_bridge import CaptureBridgeError, ReadOnlyCaptureBridge
from app.modules.ai_research_plugin.compatibility import check_compatibility
from app.modules.ai_research_plugin.contracts import (
    InferenceRecord,
    InputRepresentation,
    RFModelManifest,
    new_record_id,
    utc_now_iso,
)
from app.modules.ai_research_plugin.interpretation import interpret_output
from app.modules.ai_research_plugin.live_bridge import LiveIqBridge, LiveIqBridgeError
from app.modules.ai_research_plugin.model_registry import ModelRegistry
from app.modules.ai_research_plugin.storage import AiPluginStorage

# A LIVE snapshot request always asks for a specific, bounded number of raw
# samples -- never an arbitrary duration (see live_bridge.py's docstring on
# why this must stay bounded: raw complex64 shipped once over a JSON/base64
# pipe). DEFAULT is used only when a model's manifest does not declare a
# static input tensor shape to derive a real requirement from.
DEFAULT_LIVE_SAMPLE_COUNT = 4096
MAX_LIVE_SAMPLE_COUNT = 200_000


def _infer_required_sample_count(manifest: RFModelManifest) -> int:
    """Derives how many raw samples LIVE inference should request for this
    model, preferring the model's own real, discovered/declared input
    tensor shape (last dimension) over any fixed default -- never an
    arbitrary caller-chosen duration."""
    tensor_shape = manifest.effective_input().tensor_shape
    if tensor_shape:
        real_dims = [dim for dim in tensor_shape if dim is not None]
        if real_dims and real_dims[-1] > 0:
            return min(int(real_dims[-1]), MAX_LIVE_SAMPLE_COUNT)
    return DEFAULT_LIVE_SAMPLE_COUNT


class InferenceError(Exception):
    pass


class AiInferenceService:
    def __init__(
        self,
        registry: ModelRegistry,
        capture_bridge: ReadOnlyCaptureBridge,
        storage: AiPluginStorage,
        live_bridge: LiveIqBridge | None = None,
    ) -> None:
        self.registry = registry
        self.capture_bridge = capture_bridge
        self.storage = storage
        self.live_bridge = live_bridge

    def check_compatibility_for_region(
        self,
        model_id: str,
        capture_id: str,
        t0_seconds: float,
        t1_seconds: float,
        representation: InputRepresentation,
    ):
        """Region read + adapt + compare -- exactly the first half of
        run_inference(), used by the standalone /compatibility endpoint so
        an operator can check before committing to a real inference run.
        Never runs the model, never persists anything."""
        manifest = self.registry.get(model_id)
        if manifest is None:
            raise InferenceError(f"Unknown model_id: {model_id}")
        try:
            capture_metadata = self.capture_bridge.get_metadata(capture_id)
            region = self.capture_bridge.read_region(capture_id, t0_seconds, t1_seconds)
        except CaptureBridgeError as error:
            raise InferenceError(str(error)) from error
        adapted = adapt(representation, region.re, region.im, region.sample_rate_hz)
        return check_compatibility(
            capture_metadata=capture_metadata,
            manifest=manifest,
            chosen_representation=representation,
            adapted_tensor_shape=list(adapted.tensor.shape),
        )

    def run_inference(
        self,
        model_id: str,
        capture_id: str,
        t0_seconds: float,
        t1_seconds: float,
        representation: InputRepresentation,
    ) -> InferenceRecord:
        manifest = self.registry.get(model_id)
        if manifest is None:
            raise InferenceError(f"Unknown model_id: {model_id}")

        try:
            capture_metadata = self.capture_bridge.get_metadata(capture_id)
            region = self.capture_bridge.read_region(capture_id, t0_seconds, t1_seconds)
        except CaptureBridgeError as error:
            raise InferenceError(str(error)) from error

        adapted = adapt(representation, region.re, region.im, region.sample_rate_hz)
        compatibility = check_compatibility(
            capture_metadata=capture_metadata,
            manifest=manifest,
            chosen_representation=representation,
            adapted_tensor_shape=list(adapted.tensor.shape),
        )

        inference_started_at = time.perf_counter()
        raw_output, interpretation = self._run_model(manifest, adapted)
        inference_latency_ms = (time.perf_counter() - inference_started_at) * 1000.0

        record = InferenceRecord(
            record_id=new_record_id(),
            model_id=manifest.model_id,
            model_sha256=manifest.model_sha256,
            model_manifest_snapshot=manifest,
            capture_id=capture_id,
            capture_data_sha256=capture_metadata.get("data_sha256", "unknown"),
            selected_time_seconds=(t0_seconds, t1_seconds),
            selected_frequency_hz=None,  # frequency-region selection not implemented in this pass (spec section 14)
            input_transformation=representation,
            input_tensor_shape=list(adapted.tensor.shape),
            input_dtype="float32",
            normalization_applied=manifest.preprocessing.normalization or "none",
            inference_timestamp_utc=utc_now_iso(),
            software_backend=f"onnxruntime=={ort.__version__}",
            raw_output=raw_output.reshape(-1).astype(float).tolist(),
            raw_output_shape=list(raw_output.shape),
            interpretation=interpretation,
            compatibility=compatibility,
            inference_latency_ms=inference_latency_ms,
        )
        self.storage.save_record(record)
        return record

    async def run_inference_live(self, model_id: str, representation: InputRepresentation) -> InferenceRecord:
        """LIVE counterpart of run_inference(): sources raw I/Q from a
        bounded, one-shot snapshot of the SAME live SDR stream Live
        Monitor/RF Terrain already use (via self.live_bridge), instead of
        a preserved capture file. The sample count requested is derived
        from the model's own declared input shape (_infer_required_sample_count),
        never an arbitrary duration. capture_id is the literal "LIVE" --
        an honest signal this is not a stored, replayable capture; the
        record's capture_data_sha256 is still a real hash of the exact
        snapshot bytes actually used."""
        manifest = self.registry.get(model_id)
        if manifest is None:
            raise InferenceError(f"Unknown model_id: {model_id}")
        if self.live_bridge is None:
            raise InferenceError("LIVE inference is unavailable -- no live SDR bridge was wired up for this backend.")

        sample_count = _infer_required_sample_count(manifest)
        run_started_at = time.perf_counter()
        try:
            snapshot = await self.live_bridge.capture_snapshot(sample_count)
        except LiveIqBridgeError as error:
            raise InferenceError(str(error)) from error
        capture_finished_at = time.perf_counter()

        capture_metadata = {
            "sample_rate_sps": snapshot.sample_rate_hz,
            "bandwidth_hz": snapshot.sample_rate_hz,
            "center_frequency_hz": snapshot.center_frequency_hz,
            "data_sha256": snapshot.data_sha256,
        }
        adapted = adapt(representation, snapshot.re, snapshot.im, snapshot.sample_rate_hz)
        compatibility = check_compatibility(
            capture_metadata=capture_metadata,
            manifest=manifest,
            chosen_representation=representation,
            adapted_tensor_shape=list(adapted.tensor.shape),
        )

        inference_started_at = time.perf_counter()
        raw_output, interpretation = self._run_model(manifest, adapted)
        run_finished_at = time.perf_counter()
        capture_latency_ms = (capture_finished_at - run_started_at) * 1000.0
        inference_latency_ms = (run_finished_at - inference_started_at) * 1000.0
        total_latency_ms = (run_finished_at - run_started_at) * 1000.0

        record = InferenceRecord(
            record_id=new_record_id(),
            model_id=manifest.model_id,
            model_sha256=manifest.model_sha256,
            model_manifest_snapshot=manifest,
            capture_id="LIVE",
            capture_data_sha256=snapshot.data_sha256,
            # No absolute position within a larger file exists for an
            # ephemeral live snapshot -- this is the snapshot's own real,
            # measured duration (sample_count / sample_rate_hz), not a
            # placeholder.
            selected_time_seconds=(0.0, len(snapshot.re) / snapshot.sample_rate_hz),
            selected_frequency_hz=None,
            input_transformation=representation,
            input_tensor_shape=list(adapted.tensor.shape),
            input_dtype="float32",
            normalization_applied=manifest.preprocessing.normalization or "none",
            inference_timestamp_utc=snapshot.timestamp_utc,
            software_backend=f"onnxruntime=={ort.__version__}",
            raw_output=raw_output.reshape(-1).astype(float).tolist(),
            raw_output_shape=list(raw_output.shape),
            interpretation=interpretation,
            compatibility=compatibility,
            capture_latency_ms=capture_latency_ms,
            inference_latency_ms=inference_latency_ms,
            total_latency_ms=total_latency_ms,
        )
        self.storage.save_record(record)
        return record

    def _run_model(self, manifest: RFModelManifest, adapted) -> tuple[np.ndarray, dict]:
        model_path = self.registry.model_path(manifest)
        try:
            session = ort.InferenceSession(str(model_path), providers=["CPUExecutionProvider"])
            input_name = manifest.effective_input().input_name or session.get_inputs()[0].name
            outputs = session.run(None, {input_name: adapted.tensor.astype(np.float32)})
        except Exception as error:  # real, varied onnxruntime exception types -- never silently swallowed
            raise InferenceError(f"Inference failed: {error}") from error
        raw_output = np.asarray(outputs[0])
        interpretation = interpret_output(raw_output, manifest)
        return raw_output, interpretation
