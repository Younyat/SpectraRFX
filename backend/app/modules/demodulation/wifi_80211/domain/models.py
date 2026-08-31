from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class WifiCaptureContract:
    input_file: str
    datatype: str
    sample_rate_hz: float
    hardware_center_frequency_hz: float
    channel_center_frequency_hz: float
    channel_width_hz: float
    capture_start_utc: str | None
    sample_count: int
    gain_db: float | None
    antenna: str | None
    device_model: str | None
    device_serial: str | None
    source: str
    input_iq_sha256: str
    overflow_count: int | None
    gaps_detected: bool | None
    dc_correction_applied: bool
    iq_correction_applied: bool
    filter_definition: dict[str, Any]
    decoder_mode: str
    temporal_order_known: bool
    metadata_evidence: dict[str, str] = field(default_factory=dict)

    def validate(self) -> list[str]:
        missing = []
        if not Path(self.input_file).is_file(): missing.append("input_file")
        if self.datatype not in {"cf32_le", "ci16_le", "cu8"}: missing.append("datatype")
        if self.sample_rate_hz <= 0: missing.append("sample_rate_hz")
        if self.hardware_center_frequency_hz <= 0 or self.channel_center_frequency_hz <= 0: missing.append("frequency")
        if self.sample_count <= 0: missing.append("sample_count")
        if not self.temporal_order_known: missing.append("temporal_order_known")
        return missing

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
