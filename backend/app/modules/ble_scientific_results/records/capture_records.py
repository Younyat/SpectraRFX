"""ScientificCaptureRecord builder. One row per real CaptureRecord already
frozen in ble_rffi_studio -- every field is either a direct copy of an
existing artifact field or explicitly None + not_documented_fields. Nothing
here recomputes DSP or re-derives anything Evidence Stage/Dataset Builder/
Split Builder already decided.

Paper-campaign metadata (day_id, pre_or_post, intervention_arm, etc.) is now
read directly from CaptureRecord's own fields (added to
ble_rffi_studio/contracts/capture.py and populated at capture time by
ble_sdr_capture_worker.py / paper_campaign_runner.py) -- never hardcoded as
absent. A capture recorded before this field set existed, or not run
through the runner, still has them as None on CaptureRecord itself, which
this builder correctly reports as not_documented per-field, per-capture
(never a static list assumed true for every capture).
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

from app.modules.ble_rffi_studio.contracts import CaptureRecord, DatasetManifest, ExampleRecord, SplitManifest

from ..contracts import ScientificCaptureRecord
from .iq_resolution import resolve_iq_path, resolve_replay_dir

DEFAULT_WINDOW_DURATION_S = 10.0

# Genuinely absent everywhere in ble_rffi_studio's real schema today
# (confirmed by direct code research, not assumed) -- no per-capture
# aggregate SNR/noise/signal-power/occupied-bandwidth/CFO field exists;
# mean_power_dbfs/peak_power_dbfs exist only per-candidate
# (candidate_manifest.jsonl), and aggregating them into one capture-level
# number belongs to the descriptive-summary layer (quality_summary.py), not
# a raw canonical value here.
_STRUCTURALLY_ABSENT_CAPTURE_FIELDS = (
    "clipping_fraction", "near_zero_fraction", "noise_power_dbfs", "signal_power_dbfs",
    "snr_db", "occupied_bandwidth_hz", "frequency_offset_hz", "writer_backlog_count",
)

# Optional per-capture fields now sourced from CaptureRecord (checked
# per-row -- a capture recorded before these existed, or outside the paper
# campaign runner, genuinely has None here and is reported not_documented).
_OPTIONAL_CAPTURE_FIELDS = (
    "day_id", "campaign_period", "pre_or_post", "intervention_arm", "packet_condition", "receiver_epoch",
    "receiver_session_id", "receiver_session_id_declared", "host_id", "firmware_hash", "configuration_hash", "time_since_power_on_s", "time_since_intervention_s",
    "capture_order", "review_status", "ambient_temperature_c", "battery_id", "battery_voltage_pre_v",
    "battery_voltage_post_v", "operator_id", "planned_capture_id",
)


def _load_physical_unit_model(ble_root: Path, physical_unit_id: str | None) -> tuple[str | None, str | None]:
    """Returns (device_model, source_manifest_id_or_None). Reads the real
    PhysicalUnitRecord.model field -- honestly None on essentially every
    real unit in this repository today, since no operator workflow
    currently populates it (verified: registry/physical_units/*.json)."""
    if not physical_unit_id:
        return None, None
    path = ble_root / "registry" / "physical_units" / f"{physical_unit_id}.json"
    if not path.is_file():
        return None, None
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload.get("model"), physical_unit_id


def _load_source_acquisition_quality(legacy_capture_root: Path, capture_id: str) -> dict[str, Any] | None:
    replay_dir = resolve_replay_dir(legacy_capture_root, capture_id)
    if replay_dir is None:
        return None
    report_path = replay_dir / "replay_final_report.json"
    if not report_path.is_file():
        return None
    return json.loads(report_path.read_text(encoding="utf-8")).get("source_acquisition_quality")


def _capture_split(split: SplitManifest, capture_id: str) -> str | None:
    for assignment in split.assignments:
        if assignment.capture_id == capture_id:
            return assignment.split
    return None


def _label_status(capture: CaptureRecord, examples: list[ExampleRecord]) -> str:
    """Derived, real classification (never a raw artifact field by this
    exact name): RESOLVED_POSITIVE if any example resolved to a
    physical_unit_id, RESOLVED_NEGATIVE for a declared background capture
    with none resolved, UNRESOLVED otherwise -- mirrors the same real
    distinction ble_rffi_studio's own EvidenceStage already draws between
    "no address match" and "operator confirmed absent", just as one
    queryable field."""
    if any(example.physical_unit_id is not None for example in examples):
        return "RESOLVED_POSITIVE"
    if capture.capture_purpose in ("BACKGROUND_TARGET_OFF", "BACKGROUND_GENERAL"):
        return "RESOLVED_NEGATIVE"
    return "UNRESOLVED"


def build_capture_record(
    *, paper_run_id: str, protocol_id: str, campaign_id: str, capture: CaptureRecord, examples: list[ExampleRecord],
    dataset: DatasetManifest, split: SplitManifest, ble_root: Path, legacy_capture_root: Path,
    window_duration_s: float = DEFAULT_WINDOW_DURATION_S,
) -> ScientificCaptureRecord:
    not_documented = list(_STRUCTURALLY_ABSENT_CAPTURE_FIELDS)

    optional_values: dict[str, Any] = {}
    for field in _OPTIONAL_CAPTURE_FIELDS:
        value = getattr(capture, field, None)
        optional_values[field] = value
        if value is None:
            not_documented.append(field)

    device_model, physical_unit_manifest_id = _load_physical_unit_model(ble_root, capture.physical_unit_id)
    quality = _load_source_acquisition_quality(legacy_capture_root, capture.capture_id)
    if quality is None:
        not_documented += ["overflow_count", "discontinuity_count", "short_read_count"]

    iq_path = resolve_iq_path(legacy_capture_root, capture)
    metadata_path = ble_root / "captures" / f"{capture.capture_id}.json"
    metadata_bytes = metadata_path.read_bytes() if metadata_path.is_file() else None

    # Simple arithmetic identities from the capture's own declared
    # configuration, not inferences -- expected_samples lets campaign
    # accounting flag SAMPLE_COUNT_MISMATCH; expected_windows_per_capture
    # is duration_s / window_duration_s, rounded up (a capture shorter than
    # one full window still gets a single, partial window).
    expected_samples = round(capture.capture_duration_s * capture.sample_rate_sps) if capture.capture_duration_s and capture.sample_rate_sps else None
    expected_windows = math.ceil(capture.capture_duration_s / window_duration_s) if capture.capture_duration_s else None

    capture_eligible = capture.acquisition_quality == "PASSED" and bool(examples)
    blocking_reason_codes: list[str] = []
    diagnostic_flags: list[str] = []
    if capture.acquisition_quality != "PASSED":
        blocking_reason_codes.append(f"CAPTURE_QUALITY_{capture.acquisition_quality}")
    if not examples:
        blocking_reason_codes.append("NO_EVIDENCE_EXAMPLES")
    if (quality or {}).get("overflow_count"):
        diagnostic_flags.append("OVERFLOW_OBSERVED")
    if (quality or {}).get("discontinuity_count"):
        diagnostic_flags.append("DISCONTINUITY_OBSERVED")

    source_manifest_ids = [capture.capture_id]
    if physical_unit_manifest_id:
        source_manifest_ids.append(physical_unit_manifest_id)

    return ScientificCaptureRecord(
        paper_run_id=paper_run_id, protocol_id=protocol_id, campaign_id=campaign_id, capture_id=capture.capture_id,
        physical_unit_id=capture.physical_unit_id, device_model=device_model, source_population=capture.capture_purpose,
        channel=examples[0].channel if examples else None, center_frequency_hz=capture.center_frequency_hz,
        sample_rate_hz=capture.sample_rate_sps, bandwidth_hz=capture.effective_bandwidth_hz, sample_format=capture.sample_dtype,
        gain_db=capture.gain_db, antenna=capture.antenna_port, receiver_id=capture.receiver_device_id,
        receiver_epoch=optional_values["receiver_epoch"], receiver_session_id=optional_values["receiver_session_id"],
        receiver_session_id_declared=optional_values["receiver_session_id_declared"],
        host_id=optional_values["host_id"],
        firmware_hash=optional_values["firmware_hash"], configuration_hash=optional_values["configuration_hash"],
        day_id=optional_values["day_id"], campaign_period=optional_values["campaign_period"],
        session_id=capture.session_id, capture_order=optional_values["capture_order"],
        pre_or_post=optional_values["pre_or_post"], intervention_arm=optional_values["intervention_arm"],
        time_since_power_on_s=optional_values["time_since_power_on_s"], time_since_intervention_s=optional_values["time_since_intervention_s"],
        packet_condition=optional_values["packet_condition"],
        ambient_temperature_c=optional_values["ambient_temperature_c"], battery_id=optional_values["battery_id"],
        battery_voltage_pre_v=optional_values["battery_voltage_pre_v"], battery_voltage_post_v=optional_values["battery_voltage_post_v"],
        operator_id=optional_values["operator_id"], planned_capture_id=optional_values["planned_capture_id"],
        capture_start_utc=capture.created_at, duration_s=capture.capture_duration_s,
        window_duration_s=window_duration_s, expected_windows_per_capture=expected_windows,
        expected_samples=expected_samples, observed_samples=capture.sample_count,
        overflow_count=(quality or {}).get("overflow_count"), discontinuity_count=(quality or {}).get("discontinuity_count"),
        short_read_count=(quality or {}).get("short_read_count"), writer_backlog_count=None,
        clipping_fraction=None, near_zero_fraction=None, noise_power_dbfs=None, signal_power_dbfs=None, snr_db=None,
        occupied_bandwidth_hz=None, frequency_offset_hz=None, capture_quality=capture.acquisition_quality,
        label_status=_label_status(capture, examples), review_status=optional_values["review_status"],
        experimental_role=capture.capture_purpose, split=_capture_split(split, capture.capture_id),
        source_iq_resolved_path=str(iq_path), source_iq_size_bytes=capture.iq_size_bytes, source_iq_sha256=capture.iq_sha256,
        metadata_path=str(metadata_path) if metadata_path.is_file() else None,
        metadata_sha256=hashlib.sha256(metadata_bytes).hexdigest() if metadata_bytes else None,
        capture_eligible=capture_eligible, blocking_reason_codes=blocking_reason_codes, diagnostic_flags=diagnostic_flags,
        source_manifest_ids=source_manifest_ids, not_documented_fields=sorted(set(not_documented)),
    )
