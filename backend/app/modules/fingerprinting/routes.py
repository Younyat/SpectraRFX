from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field


class CaptureConfigBody(BaseModel):
    device_source: str = "uhd"
    sdr_model: str = "unknown"
    sdr_serial: str = "unknown"
    gain_stage: str = "manual"
    antenna_port: str = "RX2"
    capture_type: str = "iq_file"
    center_frequency_hz: float
    sample_rate_hz: float
    effective_bandwidth_hz: float = 0.0
    frontend_bandwidth_hz: float | None = None
    gain_mode: str = "manual"
    gain_settings: dict[str, Any] = Field(default_factory=dict)
    ppm_correction: float = 0.0
    lo_offset_hz: float = 0.0
    capture_duration_s: float
    sample_count: int = 0
    file_format: str = "cfile"
    sample_dtype: str = "complex64"
    byte_order: str = "native"
    channel_count: int = 1
    output_path: str = ""
    dataset_destination: str = ""


class TransmitterBody(BaseModel):
    transmitter_label: str
    transmitter_class: str
    transmitter_id: str
    family: str = ""
    signal_type: str = ""
    modulation_class: str = ""
    protocol_family: str = ""
    band_label: str = ""
    profile_key: str | None = None
    ground_truth_confidence: str = "unknown"


class ScenarioBody(BaseModel):
    operator: str = "unknown"
    environment: str = "unspecified"
    distance_m: float | None = None
    line_of_sight: bool | None = None
    indoor: bool | None = None
    notes: str = ""
    session_number: int = 1
    timestamp_utc: str | None = None


class QualityMetricsBody(BaseModel):
    estimated_snr_db: float = 0.0
    noise_floor_db: float | None = None
    peak_power_db: float | None = None
    average_power_db: float | None = None
    occupied_bandwidth_hz: float | None = None
    peak_frequency_hz: float | None = None
    frequency_offset_hz: float = 0.0
    clipping_pct: float = 0.0
    sample_drop_count: int = 0
    buffer_overflow_count: int = 0
    silence_pct: float = 0.0
    peak_to_average_ratio_db: float | None = None
    kurtosis: float | None = None
    burst_duration_ms: float = 0.0


class BurstDetectionBody(BaseModel):
    method: str = "manual"
    energy_threshold_db: float | None = None
    pre_trigger_samples: int = 0
    post_trigger_samples: int = 0
    min_burst_duration_ms: float = 1.0
    max_burst_duration_ms: float | None = None
    burst_count: int = 1
    regions_of_interest: list[str] = Field(default_factory=list)
    burst_start_sample: int | None = None
    burst_end_sample: int | None = None


class ArtifactsBody(BaseModel):
    iq_file: str | None = None
    metadata_file: str | None = None
    sha256: str | None = None
    source_capture_id: str | None = None


class PreviewMetricsBody(BaseModel):
    live_preview_snr_db: float | None = None
    live_preview_noise_floor_db: float | None = None
    live_preview_peak_level_db: float | None = None
    live_preview_peak_frequency_hz: float | None = None


class FingerprintingCaptureBody(BaseModel):
    capture_id: str | None = None
    capture_mode: str = "guided_capture"
    session_id: str
    dataset_split: Literal["train", "val", "predict"] = "train"
    signal_family: str = "unknown"
    capture_config: CaptureConfigBody
    transmitter: TransmitterBody
    scenario: ScenarioBody = Field(default_factory=ScenarioBody)
    quality_metrics: QualityMetricsBody = Field(default_factory=QualityMetricsBody)
    burst_detection: BurstDetectionBody = Field(default_factory=BurstDetectionBody)
    artifacts: ArtifactsBody = Field(default_factory=ArtifactsBody)
    preview_metrics: PreviewMetricsBody = Field(default_factory=PreviewMetricsBody)
    qc_policy_profile: str = "scientific"
    qc_thresholds: dict[str, Any] = Field(default_factory=dict)
    label_status: str | None = None
    manual_override_reason: str = ""
    operator_decision: str | None = None
    review_notes: str = ""
    export_windows: list[str] = Field(default_factory=list)


class ReviewCaptureBody(BaseModel):
    operator_decision: str | None = None
    review_notes: str = ""
    export_windows: list[str] = Field(default_factory=list)


class ApplyBandProfileBody(BaseModel):
    confirm_as_strong_label: bool = False
    overwrite_existing: bool = False


class DeleteCaptureBody(BaseModel):
    delete_artifacts: bool = True


class ImportModulatedCaptureBody(BaseModel):
    session_id: str = "session_unassigned"
    dataset_split: Literal["train", "val", "predict"] = "train"
    transmitter_label: str = "unlabeled_transmitter"
    transmitter_class: str = "unknown"
    transmitter_id: str = "tx_unknown"
    operator: str = "unknown"
    environment: str = "unspecified"
    notes: str = ""
    ground_truth_confidence: str = "unknown"
    family: str = ""
    signal_family: str = ""
    signal_type: str = ""
    modulation_class: str = ""
    protocol_family: str = ""
    band_label: str = ""
    profile_key: str | None = None
    label_status: str | None = None


def build_fingerprinting_router(service, modulated_signal_controller) -> APIRouter:
    router = APIRouter(prefix="/fingerprinting", tags=["fingerprinting"])

    @router.get("/dashboard")
    async def get_dashboard() -> dict[str, Any]:
        return service.get_dashboard_summary()

    @router.get("/captures")
    async def list_captures(dataset_split: Literal["train", "val", "predict"] | None = None) -> dict[str, Any]:
        captures = service.list_capture_records_by_split(dataset_split) if dataset_split else service.list_capture_records()
        return {"captures": captures}


    @router.get("/captures/compare/{left_capture_id}/{right_capture_id}")
    async def compare_captures(left_capture_id: str, right_capture_id: str) -> dict[str, Any]:
        try:
            return service.compare_rf_captures(left_capture_id, right_capture_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.get("/captures/{capture_id}")
    async def get_capture(capture_id: str) -> dict[str, Any]:
        try:
            return service.get_capture_record(capture_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.post("/captures")
    async def create_capture(body: FingerprintingCaptureBody) -> dict[str, Any]:
        return service.create_capture_record(body.model_dump())

    @router.post("/captures/{capture_id}/review")
    async def review_capture(capture_id: str, body: ReviewCaptureBody) -> dict[str, Any]:
        try:
            return service.review_capture_record(capture_id, body.model_dump())
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.post("/captures/{capture_id}/recompute-qc")
    async def recompute_capture_qc(capture_id: str) -> dict[str, Any]:
        try:
            return service.recompute_capture_record_qc(capture_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.post("/captures/{capture_id}/apply-band-profile")
    async def apply_band_profile(capture_id: str, body: ApplyBandProfileBody) -> dict[str, Any]:
        try:
            return service.apply_band_profile_to_capture(capture_id, body.model_dump())
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.delete("/captures/{capture_id}")
    async def delete_capture(capture_id: str, body: DeleteCaptureBody | None = None) -> dict[str, Any]:
        try:
            return service.delete_capture_record(
                capture_id,
                delete_artifacts=True if body is None else bool(body.delete_artifacts),
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.post("/imports/modulated-signals/{capture_id}")
    async def import_modulated_capture(capture_id: str, body: ImportModulatedCaptureBody) -> dict[str, Any]:
        try:
            modulated_capture = modulated_signal_controller.get_capture(capture_id)
            return service.import_modulated_capture(modulated_capture, body.model_dump())
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    return router
